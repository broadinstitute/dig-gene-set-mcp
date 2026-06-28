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
    logger.info("mcp_request_received request_uuid=%s method=%s", request_uuid, body.get("method") if isinstance(body, dict) else None)

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
