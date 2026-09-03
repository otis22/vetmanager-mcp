#!/usr/bin/env python3
"""Read-only public MCP smoke: initialize, tools/list, then get_users(limit=1).

Этап 289.3: при отказе печатается диагноз, а не тип исключения. Строка
`MCP tool smoke failed: RuntimeError` не отличала отказ авторизации от
недоступного апстрима и стоила двадцати минут ручного поиска в логах прода
03.09.2026. Печатаются четыре вещи, ни одна из которых не секрет: шаг, вид
отказа, код статуса и идентификатор запроса — по последнему строка находится
в журнале прода сразу. Тела ответов, заголовки и токен по-прежнему не
печатаются никогда.
"""

from __future__ import annotations

import os
import sys
import time
import json

import httpx

DEFAULT_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"

STEP_INITIALIZE = "initialize"
STEP_NOTIFY = "notifications/initialized"
STEP_TOOLS_LIST = "tools/list"
STEP_TOOLS_CALL = "tools/call"


class SmokeFailure(Exception):
    """Отказ, о котором есть что сказать, кроме имени класса."""

    def __init__(
        self,
        step: str,
        reason: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"{step}:{reason}")
        self.step = step
        self.reason = reason
        self.status = status
        self.request_id = request_id

    def diagnosis(self) -> str:
        return (
            f"MCP tool smoke failed: step={self.step} reason={self.reason} "
            f"status={self.status if self.status is not None else '-'} "
            f"request_id={self.request_id or '-'}"
        )


def _correlation_id(headers: httpx.Headers | None) -> str | None:
    if headers is None:
        return None
    return headers.get("x-request-id") or headers.get("x-correlation-id")


def _request(
    client: httpx.Client, method: str, params: dict, request_id: int, step: str
) -> tuple[dict, httpx.Headers]:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    if response.status_code >= 400:
        raise SmokeFailure(
            step,
            "http_status",
            status=response.status_code,
            request_id=_correlation_id(response.headers),
        )
    correlation = _correlation_id(response.headers)
    # Разбор тела — тоже отказ шага, а не безымянная ошибка: промежуточный
    # прокси умеет отдать HTML с `content-type: application/json`.
    try:
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            payload = next(
                (json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")),
                None,
            )
        else:
            payload = response.json()
    except ValueError:
        raise SmokeFailure(
            step, "unparsable", status=response.status_code, request_id=correlation
        ) from None
    if not isinstance(payload, dict):
        raise SmokeFailure(step, "malformed_response", status=response.status_code, request_id=correlation)
    if payload.get("id") != request_id:
        raise SmokeFailure(step, "response_id_mismatch", status=response.status_code, request_id=correlation)
    if "error" in payload:
        raise SmokeFailure(step, "jsonrpc_error", status=response.status_code, request_id=correlation)
    if "result" not in payload:
        raise SmokeFailure(step, "result_missing", status=response.status_code, request_id=correlation)
    return payload["result"], response.headers


def main() -> int:
    token = os.environ.get("PROD_SMOKE_BEARER_TOKEN", "").strip()
    if not token:
        print("Missing PROD_SMOKE_BEARER_TOKEN.", file=sys.stderr)
        return 2
    base_url = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    for attempt in range(1, 11):
        try:
            with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
                initialized, response_headers = _request(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "post-deploy-smoke", "version": "1"}}, 1, STEP_INITIALIZE)
                correlation = _correlation_id(response_headers)
                if "protocolVersion" not in initialized:
                    raise SmokeFailure(STEP_INITIALIZE, "protocol_version_missing", request_id=correlation)
                session_id = response_headers.get("mcp-session-id")
                if session_id:
                    client.headers["Mcp-Session-Id"] = session_id
                notification = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                if notification.status_code >= 400:
                    raise SmokeFailure(
                        STEP_NOTIFY,
                        "http_status",
                        status=notification.status_code,
                        request_id=_correlation_id(notification.headers),
                    )
                tools, tools_headers = _request(client, "tools/list", {}, 2, STEP_TOOLS_LIST)
                tools = tools.get("tools", [])
                if "get_users" not in {tool.get("name") for tool in tools}:
                    raise SmokeFailure(
                        STEP_TOOLS_LIST, "tool_missing", request_id=_correlation_id(tools_headers)
                    )
                call, call_headers = _request(client, "tools/call", {"name": "get_users", "arguments": {"limit": 1}}, 3, STEP_TOOLS_CALL)
                if call.get("isError"):
                    # Текст ошибки инструмента не печатается: в нём могут быть
                    # данные клиники. Идентификатор запроса ведёт к полной
                    # причине в журнале прода, где её читать безопасно.
                    raise SmokeFailure(
                        STEP_TOOLS_CALL, "tool_error", request_id=_correlation_id(call_headers)
                    )
            print("MCP read-only tool smoke passed.")
            return 0
        except SmokeFailure as exc:
            # Повторяем только то, что бывает временным сразу после выката.
            if exc.reason == "http_status" and exc.status in {502, 503, 504} and attempt < 10:
                time.sleep(3)
                continue
            print(exc.diagnosis(), file=sys.stderr)
            return 1
        except httpx.TransportError as exc:
            if attempt == 10:
                print(
                    f"MCP tool smoke failed: step=transport reason={type(exc).__name__} "
                    "status=- request_id=-",
                    file=sys.stderr,
                )
                return 1
            time.sleep(3)
        except ValueError:
            # Сюда попадает только разбор вне `_request`; у него шага нет.
            print(
                "MCP tool smoke failed: step=response reason=unparsable status=- request_id=-",
                file=sys.stderr,
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
