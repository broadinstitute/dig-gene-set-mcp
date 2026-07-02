from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from flask import Flask, Response, jsonify, request

from .config import Settings, load_settings
from .database import Database
from .tools import TOOL_DEFINITIONS, ToolError, ToolService, call_tool


class RateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._requests_per_minute = requests_per_minute
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        window_start = now - 60
        bucket = self._buckets[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= self._requests_per_minute:
            return False
        bucket.append(now)
        return True


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    settings = load_settings(base_dir)
    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    _configure_logging(app, settings)
    _log_startup_settings(app.logger, settings)
    database = Database(settings.db_path, settings.query_timeout_seconds)
    tool_service = ToolService(database, settings)
    rate_limiter = RateLimiter(settings.rate_limit_per_minute)

    @app.before_request
    def before_request() -> Response | None:
        if request.path == "/healthz":
            return None
        auth_header = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.bearer_token}"
        if auth_header != expected:
            return jsonify({"error": "Unauthorized"}), 401

        client_key = _client_identity()
        if not rate_limiter.allow(client_key):
            return jsonify({"error": "Rate limit exceeded"}), 429
        return None

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify(
            {
                "status": "ok",
                "app": settings.app_name,
                "db_path": str(settings.db_path),
            }
        )

    @app.get("/tools/search_gene_sets")
    def search_gene_sets_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "search_gene_sets",
            {
                "query": request.args.get("query", ""),
                "organism": request.args.get("organism"),
                "library": request.args.get("library"),
                "limit": _parse_optional_int_arg("limit"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/search_gene_sets_semantic")
    def search_gene_sets_semantic_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "search_gene_sets_semantic",
            {
                "query": request.args.get("query", ""),
                "limit": _parse_optional_int_arg("limit"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/get_gene_set")
    def get_gene_set_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "get_gene_set",
            {
                "gene_set_id": _parse_optional_int_arg("gene_set_id"),
                "standard_name": request.args.get("standard_name"),
                "include_genes": _parse_bool_arg("include_genes", True),
                "max_genes": _parse_optional_int_arg("max_genes"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/get_pigean_gene_set")
    def get_pigean_gene_set_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "get_pigean_gene_set",
            {
                "gene_set_id": request.args.get("gene_set_id"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/get_provenance")
    def get_provenance_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "get_provenance",
            {
                "gene_set_id": _parse_optional_int_arg("gene_set_id"),
                "standard_name": request.args.get("standard_name"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/find_gene_sets_by_gene")
    def find_gene_sets_by_gene_get() -> Response:
        genes = request.args.getlist("gene")
        if not genes:
            csv_genes = request.args.get("genes", "")
            genes = [gene.strip() for gene in csv_genes.split(",") if gene.strip()]
        response, status_code = _tool_http_response(
            tool_service,
            "find_gene_sets_by_gene",
            {
                "genes": genes,
                "organism": request.args.get("organism"),
                "library": request.args.get("library"),
                "limit": _parse_optional_int_arg("limit"),
            },
        )
        return jsonify(response), status_code

    @app.get("/tools/get_graph_neighborhood")
    def get_graph_neighborhood_get() -> Response:
        response, status_code = _tool_http_response(
            tool_service,
            "get_graph_neighborhood",
            {
                "node_type": request.args.get("node_type", ""),
                "node_id": request.args.get("node_id", ""),
                "max_nodes": _parse_optional_int_arg("max_nodes"),
                "max_edges": _parse_optional_int_arg("max_edges"),
                "include_genes": _parse_bool_arg("include_genes", False),
            },
        )
        return jsonify(response), status_code

    @app.route("/mcp", methods=["GET", "POST"])
    def mcp_endpoint() -> Response:
        if request.method == "GET":
            return _sse_response(
                {
                    "jsonrpc": "2.0",
                    "method": "server/ready",
                    "params": {
                        "serverInfo": {"name": settings.app_name, "version": "0.1.0"},
                        "capabilities": {"tools": {}},
                    },
                }
            )

        body = request.get_json(silent=True)
        if body is None:
            return jsonify(_jsonrpc_error(None, -32700, "Invalid JSON body")), 400

        response_body, status_code = _handle_mcp_request(body, tool_service, app.logger)
        wants_stream = "text/event-stream" in request.headers.get("Accept", "") or request.args.get("stream") == "1"
        if wants_stream:
            return _sse_response(response_body, status_code=status_code)
        return jsonify(response_body), status_code

    return app


def _handle_mcp_request(body: Any, tool_service: ToolService, logger: logging.Logger) -> tuple[dict[str, Any], int]:
    request_id = body.get("id") if isinstance(body, dict) else None
    request_uuid = str(uuid.uuid4())
    tool_name = None
    if isinstance(body, dict) and body.get("method") == "tools/call":
        params = body.get("params", {})
        if isinstance(params, dict):
            tool_name = params.get("name")
    logger.info(
        "mcp_request_received request_uuid=%s method=%s tool_name=%s",
        request_uuid,
        body.get("method") if isinstance(body, dict) else None,
        tool_name,
    )

    if not isinstance(body, dict):
        return _jsonrpc_error(request_id, -32600, "Request must be a JSON object"), 400

    method = body.get("method")
    params = body.get("params", {})

    try:
        if method == "initialize":
            return (
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "serverInfo": {"name": "genseco-mcp-server", "version": "0.1.0"},
                        "capabilities": {"tools": {}},
                    },
                },
                200,
            )
        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}, 200
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_DEFINITIONS}}, 200
        if method == "tools/call":
            if not isinstance(params, dict):
                raise ToolError("params must be an object")
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be an object")
            result = call_tool(tool_service, tool_name, arguments)
            return (
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"), ensure_ascii=True)}],
                        "structuredContent": result,
                        "isError": False,
                    },
                },
                200,
            )
        return _jsonrpc_error(request_id, -32601, "Method not found"), 404
    except ToolError as exc:
        logger.warning("mcp_tool_error request_uuid=%s error=%s", request_uuid, exc)
        return (
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            },
            200,
        )
    except Exception as exc:
        logger.exception("mcp_unhandled_error request_uuid=%s", request_uuid)
        return _jsonrpc_error(request_id, -32000, f"Internal server error: {exc}"), 500


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _sse_response(payload: dict[str, Any], status_code: int = 200) -> Response:
    def generate() -> Iterable[str]:
        yield "event: message\n"
        yield f"data: {json.dumps(payload, separators=(',', ':'), ensure_ascii=True)}\n\n"

    return Response(generate(), status=status_code, mimetype="text/event-stream")


def _tool_http_response(tool_service: ToolService, tool_name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], int]:
    filtered_arguments = {key: value for key, value in arguments.items() if value is not None}
    logging.getLogger(__name__).info("tool_http_request tool_name=%s arguments=%s", tool_name, filtered_arguments)
    try:
        result = call_tool(tool_service, tool_name, filtered_arguments)
        return {"tool": tool_name, "ok": True, "result": result}, 200
    except ToolError as exc:
        return {"tool": tool_name, "ok": False, "error": str(exc)}, 400
    except ValueError as exc:
        return {"tool": tool_name, "ok": False, "error": str(exc)}, 400


def _client_identity() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _configure_logging(app: Flask, settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app.logger.setLevel(getattr(logging, settings.log_level, logging.INFO))


def _log_startup_settings(logger: logging.Logger, settings: Settings) -> None:
    logger.info("MCP_BEARER_TOKEN=%s", settings.bearer_token)
    logger.info("MCP_DB_PATH=%s", settings.db_path)
    logger.info("MCP_HOST=%s", settings.host)
    logger.info("MCP_PORT=%s", settings.port)
    logger.info("MCP_LOG_LEVEL=%s", settings.log_level)
    logger.info("MCP_REMOTE_SEARCH_BASE_URL=%s", settings.remote_search_base_url)
    logger.info("MCP_RATE_LIMIT_PER_MINUTE=%s", settings.rate_limit_per_minute)
    logger.info("MCP_QUERY_TIMEOUT_SECONDS=%s", settings.query_timeout_seconds)
    logger.info("MCP_MAX_SEARCH_RESULTS=%s", settings.max_search_results)
    logger.info("MCP_MAX_GENE_RESULTS=%s", settings.max_gene_results)


def _parse_optional_int_arg(name: str) -> int | None:
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return None
    return int(raw_value)


def _parse_bool_arg(name: str, default: bool) -> bool:
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean for {name}: {raw_value}")
