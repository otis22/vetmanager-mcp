"""Этап 289.3 — упавший смоук обязан назвать, где и на чём он упал.

03.09.2026 выкат этапа 285 уронил `Deploy Prod` строкой
`MCP tool smoke failed: RuntimeError`. По ней нельзя понять ничего: упал шаг
`initialize` или `tools/call`, отказала авторизация или апстрим, надо срочно
откатывать или это шум. Настоящая причина — отказ по IP — нашлась в логах
прода через двадцать минут ручного поиска.

Смоук молчал не по злому умыслу, а из осторожности: он намеренно не печатает
ни тела ответов, ни заголовков, чтобы не унести в публичный журнал сборки
токен или данные клиники. Осторожность правильная, вывод — нет. Между «сырое
тело ответа» и «тип исключения» есть то, что и нужно: **шаг, вид отказа,
код статуса и идентификатор запроса**. Ни одно из четырёх не секрет, а вместе
они ведут прямо в нужную строку журнала прода.

Проверяется поведением, а не наличием слов в исходнике: тест поднимает
подставной сервер и смотрит, что смоук печатает на самом деле.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import post_deploy_mcp_tool_smoke as smoke  # noqa: E402

TOKEN = "secret-smoke-token-value"
REQUEST_ID = "abc123def456"


class _Handler(BaseHTTPRequestHandler):
    """Отвечает как настоящий сервер до шага, который велено провалить."""

    behaviour = "tool_error"
    protocol_version = "HTTP/1.0"  # соединение закрывается после ответа

    def log_message(self, *args) -> None:  # noqa: D401 — тишина в выводе теста
        return

    send_request_id = True

    def _send(self, status: int, payload: dict | None) -> None:
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("mcp-session-id", "session-1")
        if self.send_request_id:
            self.send_header("x-request-id", REQUEST_ID)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 — имя задано базовым классом
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        request = json.loads(raw) if raw else {}
        method = request.get("method")
        request_id = request.get("id")

        if method == "notifications/initialized":
            self._send(202, None)
            return
        if method == "initialize":
            self._send(200, {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"protocolVersion": "2025-03-26"},
            })
            return
        if method == "tools/list":
            if self.behaviour == "unparsable":
                body = b"<html>502 from a proxy that did not read the Accept header</html>"
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("x-request-id", REQUEST_ID)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.behaviour == "missing_tool":
                self._send(200, {
                    "jsonrpc": "2.0", "id": request_id, "result": {"tools": []},
                })
                return
            self._send(200, {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"tools": [{"name": "get_users"}]},
            })
            return
        if method == "tools/call":
            if self.behaviour == "forbidden":
                self._send(403, {"error": "Invalid authorization."})
                return
            self._send(200, {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"isError": True, "content": [
                    {"type": "text", "text": "Invalid authorization."},
                ]},
            })
            return
        self._send(404, None)


@pytest.fixture()
def stub_server():
    def start(behaviour: str, *, send_request_id: bool = True) -> str:
        _Handler.behaviour = behaviour
        _Handler.send_request_id = send_request_id
        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    started: list = []
    yield start
    for server, thread in started:
        # `shutdown()` останавливает цикл, но слушающий сокет оставляет
        # открытым: набор гоняется с `-W error`, и ResourceWarning про него
        # превращается в ошибку теста.
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run(monkeypatch, base_url: str, capsys) -> tuple[int, str]:
    monkeypatch.setenv("PROD_SMOKE_BEARER_TOKEN", TOKEN)
    monkeypatch.setattr(sys, "argv", ["post_deploy_mcp_tool_smoke.py", base_url])
    code = smoke.main()
    return code, capsys.readouterr().err


def test_a_failing_tool_call_names_the_step_and_the_kind(monkeypatch, stub_server, capsys) -> None:
    code, err = _run(monkeypatch, stub_server("tool_error"), capsys)

    assert code == 1
    assert "step=tools/call" in err, f"не сказано, где упало: {err!r}"
    assert "reason=tool_error" in err, f"не сказано, что именно случилось: {err!r}"


def test_the_diagnosis_carries_the_request_id_into_prod_logs(monkeypatch, stub_server, capsys) -> None:
    """Идентификатор запроса — это то, чем найдётся строка в журнале прода.

    Без него разбор начинается с угадывания времени и грепа по всему потоку,
    что 03.09.2026 и заняло двадцать минут.
    """
    _, err = _run(monkeypatch, stub_server("tool_error"), capsys)

    assert REQUEST_ID in err


def test_an_http_refusal_names_its_status(monkeypatch, stub_server, capsys) -> None:
    code, err = _run(monkeypatch, stub_server("forbidden"), capsys)

    assert code == 1
    assert "status=403" in err, f"код отказа не назван: {err!r}"
    assert "step=tools/call" in err


def test_a_missing_tool_is_not_confused_with_a_broken_one(monkeypatch, stub_server, capsys) -> None:
    code, err = _run(monkeypatch, stub_server("missing_tool"), capsys)

    assert code == 1
    assert "reason=tool_missing" in err, f"вид отказа не различён: {err!r}"


@pytest.mark.parametrize("behaviour", ["tool_error", "forbidden", "missing_tool"])
def test_no_failure_path_leaks_the_token(monkeypatch, stub_server, capsys, behaviour: str) -> None:
    """Осторожность, ради которой вывод и был немым, обязана сохраниться."""
    _, err = _run(monkeypatch, stub_server(behaviour), capsys)

    assert TOKEN not in err
    assert "Bearer" not in err


def test_the_diagnosis_survives_a_server_that_sends_no_request_id(monkeypatch, stub_server, capsys) -> None:
    """Заголовок появился на `/mcp` только этим же этапом (289.4).

    Пока он не доехал до прода — и на любом чужом сервере — идентификатора в
    ответе не будет. Диагноз обязан остаться полезным: подставной сервер,
    который сам отдаёт заголовок, легко делает этот тест зелёным по совпадению.
    """
    code, err = _run(monkeypatch, stub_server("tool_error", send_request_id=False), capsys)

    assert code == 1
    assert "step=tools/call" in err and "reason=tool_error" in err
    assert "request_id=-" in err


def test_an_unparsable_body_still_names_step_status_and_request_id(monkeypatch, stub_server, capsys) -> None:
    """Найдено внешним ревью: путь разбора тела терял весь диагноз.

    Промежуточный прокси отдаёт HTML с `content-type: application/json`,
    `response.json()` бросает `ValueError` мимо `SmokeFailure` — и печатается
    `step=response reason=unparsable status=- request_id=-`, то есть ровно то
    бесполезное сообщение, ради замены которого этап и делался.
    """
    code, err = _run(monkeypatch, stub_server("unparsable"), capsys)

    assert code == 1
    assert "step=tools/list" in err, f"шаг потерян: {err!r}"
    assert "reason=unparsable" in err
    assert "status=200" in err, f"код статуса потерян: {err!r}"
    assert REQUEST_ID in err, f"идентификатор запроса потерян: {err!r}"
    assert "html" not in err.lower(), "тело ответа не должно попадать в вывод"
