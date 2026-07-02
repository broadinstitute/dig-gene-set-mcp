from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request


LOGGER = logging.getLogger(__name__)


class WebRequestError(Exception):
    pass


def post_json(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    encoded_payload = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=encoded_payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    LOGGER.info("outgoing_web_call method=POST url=%s payload=%s timeout_seconds=%s", url, payload, timeout_seconds)
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            parsed_response = json.loads(response_body)
            item_count = len(parsed_response.get("items", [])) if isinstance(parsed_response, dict) else None
            LOGGER.info(
                "outgoing_web_response method=POST url=%s status=%s item_count=%s",
                url,
                response.status,
                item_count,
            )
            return parsed_response
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        LOGGER.warning(
            "outgoing_web_error method=POST url=%s status=%s body=%s",
            url,
            exc.code,
            response_body,
        )
        raise WebRequestError(f"Remote service returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        LOGGER.warning("outgoing_web_error method=POST url=%s reason=%s", url, exc.reason)
        raise WebRequestError(f"Remote service request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        LOGGER.warning("outgoing_web_error method=POST url=%s reason=invalid_json", url)
        raise WebRequestError("Remote service returned invalid JSON") from exc


def get_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    http_request = request.Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )
    LOGGER.info("outgoing_web_call method=GET url=%s timeout_seconds=%s", url, timeout_seconds)
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            parsed_response = json.loads(response_body)
            data_count = len(parsed_response.get("data", [])) if isinstance(parsed_response, dict) else None
            LOGGER.info(
                "outgoing_web_response method=GET url=%s status=%s data_count=%s",
                url,
                response.status,
                data_count,
            )
            return parsed_response
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        LOGGER.warning(
            "outgoing_web_error method=GET url=%s status=%s body=%s",
            url,
            exc.code,
            response_body,
        )
        raise WebRequestError(f"Remote service returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        LOGGER.warning("outgoing_web_error method=GET url=%s reason=%s", url, exc.reason)
        raise WebRequestError(f"Remote service request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        LOGGER.warning("outgoing_web_error method=GET url=%s reason=invalid_json", url)
        raise WebRequestError("Remote service returned invalid JSON") from exc
