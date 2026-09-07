"""Этап 283.5 — у доставок появляется знаменатель, а у знаменателя глубина.

Отчёт показывал `top_known_issues_30d` — числитель без знаменателя. Число `4`
одинаково выглядит и когда отказов было четыре, и когда четыре тысячи.

Знаменатель живёт в Prometheus (`vetmanager_known_issue_lookups_total`), и на
07.09.2026 его ряд начинался вчера: 14 обращений за всю историю. Поэтому
главное, что охраняют эти тесты, — не само отношение, а **глубина данных**,
за которую оно посчитано: отношение «за 30 дней» по ряду длиной в сутки это
не приблизительная правда, а неправда.

Живой Prometheus набору не нужен: HTTP подменяется `httpx.MockTransport`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from scripts.product_metrics_report import (
    _collect_feedback_metrics,
    KNOWN_ISSUE_LOOKUPS_QUERY,
    PROMETHEUS_DEFAULT_URL,
    PROMETHEUS_STEP_SECONDS,
    collect_known_issue_delivery,
    summarize_known_issue_delivery,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
WINDOW_DAYS = 30


def _series(kind: str, outcome: str, points: list[tuple[datetime, float]]) -> dict:
    return {
        "metric": {"kind": kind, "outcome": outcome},
        "values": [[ts.timestamp(), str(value)] for ts, value in points],
    }


def _payload(*series: dict) -> dict:
    return {"status": "success", "data": {"resultType": "matrix", "result": list(series)}}


def _hours_ago(hours: int) -> datetime:
    return NOW - timedelta(hours=hours)


def _one_day_old_payload() -> dict:
    """Ряд, начавшийся сутки назад: ровно то, что было на проде 07.09.2026."""
    return _payload(
        _series("failure", "matched", [(_hours_ago(24), 2.0), (_hours_ago(2), 2.0)]),
        _series("failure", "no_match", [(_hours_ago(24), 6.0), (_hours_ago(2), 4.0)]),
    )


# ── глубина данных ─────────────────────────────────────────────────────────


def test_depth_comes_from_the_series_not_from_the_report_window():
    """Ряд длиной в сутки при окне в 30 дней даёт глубину в сутки."""
    out = summarize_known_issue_delivery(
        _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
    )
    assert out["status"] == "ok"
    assert out["window_days"] == WINDOW_DAYS
    assert out["effective_depth_hours"] == 24
    assert out["first_sample_at"] == _hours_ago(24).isoformat()


def test_short_series_is_flagged_as_partial():
    out = summarize_known_issue_delivery(
        _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
    )
    assert out["depth_is_partial"] is True


def test_full_window_series_is_not_flagged_as_partial():
    full = _payload(
        _series(
            "failure",
            "matched",
            [(_hours_ago(24 * WINDOW_DAYS), 1.0), (_hours_ago(1), 1.0)],
        ),
    )
    out = summarize_known_issue_delivery(full, now=NOW, window_days=WINDOW_DAYS)
    assert out["depth_is_partial"] is False
    assert out["effective_depth_hours"] == 24 * WINDOW_DAYS


def test_depth_is_the_earliest_point_across_all_series():
    """Ряд matched может родиться позже no_match — глубина по метрике целиком."""
    payload = _payload(
        _series("failure", "no_match", [(_hours_ago(50), 3.0), (_hours_ago(1), 2.0)]),
        _series("failure", "matched", [(_hours_ago(5), 1.0)]),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["effective_depth_hours"] == 50


def test_point_older_than_the_window_is_a_broken_answer():
    """Честный query_range за 30 дней такой точки вернуть не может.

    Обрезать её окном значило бы показать полную глубину по ответу, которому
    нельзя верить.
    """
    payload = _payload(
        _series(
            "failure",
            "matched",
            [(_hours_ago(24 * 90), 1.0), (_hours_ago(1), 1.0)],
        ),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "no_data"
    assert out["reason"] == "malformed_response"


def test_point_on_the_window_edge_gives_full_depth():
    payload = _payload(
        _series(
            "failure",
            "matched",
            [(_hours_ago(24 * WINDOW_DAYS), 1.0), (_hours_ago(1), 1.0)],
        ),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["effective_depth_hours"] == 24 * WINDOW_DAYS
    assert out["depth_is_partial"] is False


def test_absurd_timestamp_is_malformed_not_an_overflow():
    """`isfinite` пропускает 1e20 — а datetime им давится и роняет отчёт."""
    for absurd in ("1e20", "-1e20"):
        payload = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"kind": "failure", "outcome": "matched"},
                        "values": [[absurd, "1"]],
                    }
                ],
            },
        }
        out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
        assert out["status"] == "no_data"
        assert out["reason"] == "malformed_response"


# ── числитель, знаменатель и отношение ─────────────────────────────────────


def test_deliveries_and_lookups_come_from_the_same_answer():
    out = summarize_known_issue_delivery(
        _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
    )
    failure = out["by_kind"]["failure"]
    assert failure["deliveries"] == 4
    assert failure["lookups"] == 14
    assert failure["delivery_rate"] == pytest.approx(4 / 14, rel=1e-3)


def test_two_kinds_are_counted_separately_and_never_summed():
    payload = _payload(
        _series("failure", "matched", [(_hours_ago(10), 3.0)]),
        _series("failure", "no_match", [(_hours_ago(10), 7.0)]),
        _series("caller_mistake", "matched", [(_hours_ago(10), 1.0)]),
        _series("caller_mistake", "no_match", [(_hours_ago(10), 1.0)]),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["by_kind"]["failure"] == {
        "deliveries": 3,
        "lookups": 10,
        "delivery_rate": pytest.approx(0.3, rel=1e-3),
    }
    assert out["by_kind"]["caller_mistake"] == {
        "deliveries": 1,
        "lookups": 2,
        "delivery_rate": pytest.approx(0.5, rel=1e-3),
    }


def test_lookup_failed_belongs_to_the_denominator():
    """Не успели посмотреть — это тоже обращение, иначе доля завышена."""
    payload = _payload(
        _series("failure", "matched", [(_hours_ago(10), 1.0)]),
        _series("failure", "lookup_failed", [(_hours_ago(10), 9.0)]),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["by_kind"]["failure"]["lookups"] == 10
    assert out["by_kind"]["failure"]["delivery_rate"] == pytest.approx(0.1, rel=1e-3)


def test_repeated_kind_outcome_pairs_are_summed_not_overwritten():
    """Разные `tool`/инстансы могут прийти отдельными рядами — их складывают."""
    payload = _payload(
        _series("failure", "matched", [(_hours_ago(10), 2.0)]),
        _series("failure", "matched", [(_hours_ago(10), 3.0)]),
        _series("failure", "no_match", [(_hours_ago(10), 5.0)]),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["by_kind"]["failure"]["deliveries"] == 5
    assert out["by_kind"]["failure"]["lookups"] == 10


def test_hourly_pieces_are_added_up_across_the_window():
    payload = _payload(
        _series(
            "failure",
            "matched",
            [(_hours_ago(3), 1.0), (_hours_ago(2), 2.0), (_hours_ago(1), 1.0)],
        ),
    )
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["by_kind"]["failure"]["deliveries"] == 4


# ── три разных сорта пустоты ───────────────────────────────────────────────


def test_missing_matched_inside_an_existing_kind_is_zero_not_no_data():
    payload = _payload(_series("failure", "no_match", [(_hours_ago(10), 8.0)]))
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "ok"
    assert out["by_kind"]["failure"]["deliveries"] == 0
    assert out["by_kind"]["failure"]["lookups"] == 8
    assert out["by_kind"]["failure"]["delivery_rate"] == 0.0


def test_zero_denominator_leaves_the_rate_uncomputed_without_calling_it_a_failure():
    payload = _payload(_series("failure", "matched", [(_hours_ago(10), 0.0)]))
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "ok"
    assert out["by_kind"]["failure"]["lookups"] == 0
    assert out["by_kind"]["failure"]["delivery_rate"] is None


def test_empty_result_is_no_data_with_a_reason():
    out = summarize_known_issue_delivery(_payload(), now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "no_data"
    assert out["reason"] == "empty_series"
    assert out["by_kind"] == {}


def test_prometheus_error_status_is_no_data_with_a_reason():
    out = summarize_known_issue_delivery(
        {"status": "error", "errorType": "bad_data", "error": "boom"},
        now=NOW,
        window_days=WINDOW_DAYS,
    )
    assert out["status"] == "no_data"
    assert out["reason"] == "prometheus_error"


def test_malformed_payload_is_no_data_not_an_exception():
    for broken in ({}, {"data": None}, {"status": "success", "data": {"result": "nope"}}):
        out = summarize_known_issue_delivery(broken, now=NOW, window_days=WINDOW_DAYS)
        assert out["status"] == "no_data"
        assert out["reason"] == "malformed_response"


# ── поход по сети ──────────────────────────────────────────────────────────


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_request_asks_for_hourly_increase_under_the_aggregation():
    """Сброс счётчика чинится формой запроса, а не разбором ответа."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, json=_one_day_old_payload())

    await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    url = seen["url"]
    assert url.path == "/api/v1/query_range"
    query = url.params["query"]
    assert query == KNOWN_ISSUE_LOOKUPS_QUERY
    # increase считает Prometheus по каждому ряду, sum by применяется после —
    # иначе рестарт одного ряда маскируется ростом соседнего.
    assert "increase(vetmanager_known_issue_lookups_total[1h])" in query
    assert query.index("sum by") < query.index("increase(")
    assert url.params["step"] == str(PROMETHEUS_STEP_SECONDS)


@pytest.mark.asyncio
async def test_request_covers_exactly_the_report_window():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = request.url.params
        return httpx.Response(200, json=_one_day_old_payload())

    await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    start = float(seen["params"]["start"])
    end = float(seen["params"]["end"])
    assert end == pytest.approx(NOW.timestamp())
    assert start == pytest.approx((NOW - timedelta(days=WINDOW_DAYS)).timestamp())


@pytest.mark.asyncio
async def test_request_carries_no_secret_and_no_clinic_field():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=_one_day_old_payload())

    await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    request = seen["request"]
    assert "authorization" not in {k.lower() for k in request.headers}
    assert "cookie" not in {k.lower() for k in request.headers}
    body = str(request.url) + request.content.decode()
    for marker in ("token", "bearer", "api_key", "domain", "clinic", "@"):
        assert marker not in body.lower()


@pytest.mark.asyncio
async def test_missing_base_url_env_uses_the_default_address(monkeypatch):
    """Отсутствие переменной — рабочий случай прода, а не отказ."""
    monkeypatch.delenv("PROMETHEUS_BASE_URL", raising=False)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_one_day_old_payload())

    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert seen["url"].startswith(PROMETHEUS_DEFAULT_URL)
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_base_url_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://metrics.internal:9999")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_one_day_old_payload())

    await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert seen["url"].startswith("http://metrics.internal:9999")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raiser", "reason"),
    [
        (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")), "connection_error"),
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
    ],
)
async def test_network_failures_each_become_no_data_with_their_own_reason(raiser, reason):
    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(raiser)
    )
    assert out["status"] == "no_data"
    assert out["reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 404, 500, 503])
async def test_non_2xx_becomes_no_data_with_the_code_in_the_reason(code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text="nope")

    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert out["status"] == "no_data"
    assert out["reason"] == f"http_{code}"


@pytest.mark.asyncio
async def test_body_that_is_not_json_becomes_no_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert out["status"] == "no_data"
    assert out["reason"] == "malformed_response"


# ── место в отчёте ─────────────────────────────────────────────────────────


def test_markdown_names_the_depth_next_to_the_rate():
    from scripts.product_metrics_report import format_markdown

    metrics = _report_skeleton(
        summarize_known_issue_delivery(
            _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
        )
    )
    text = format_markdown(metrics, now=NOW)
    # Глубина обязана стоять рядом с числом, иначе отношение врёт окном.
    # Проверяется целая строка, а не наличие «24» где-то в отчёте: цифры
    # встречаются и в других секциях.
    assert (
        "_data depth: 24h of a 30d window — window not covered. "
        "Counts are Prometheus estimates._"
    ) in text
    assert "| failure | 4 | 14 | 28.6% |" in text


def test_markdown_says_no_data_and_why_when_prometheus_is_silent():
    from scripts.product_metrics_report import format_markdown

    metrics = _report_skeleton(
        {
            "status": "no_data",
            "reason": "connection_error",
            "window_days": WINDOW_DAYS,
            "effective_depth_hours": 0,
            "depth_is_partial": True,
            "first_sample_at": None,
            "by_kind": {},
        }
    )
    text = format_markdown(metrics, now=NOW)
    assert "_no data: connection_error_" in text
    assert "delivery_rate" not in text


def test_json_carries_the_section():
    from scripts.product_metrics_report import format_json

    delivery = summarize_known_issue_delivery(
        _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
    )
    payload = json.loads(format_json(_report_skeleton(delivery), now=NOW))
    section = payload["feedback"]["known_issue_delivery"]
    assert section["effective_depth_hours"] == 24
    assert section["by_kind"]["failure"]["deliveries"] == 4


def _report_skeleton(delivery: dict) -> dict:
    """Минимальный отчёт: остальные секции пустые, нас интересует одна."""
    empty_feedback = {
        "reports": {
            "total_24h": 0, "total_7d": 0, "total_30d": 0,
            "new_open_30d": 0, "possible_pii_30d": 0,
            "by_source_30d": {}, "by_status_30d": {},
            "by_severity_30d": {}, "by_category_30d": {}, "top_tools_30d": [],
        },
        "match_events": {
            "total_7d": 0, "total_30d": 0,
            "by_source_7d": {}, "by_source_30d": {},
            "top_known_issues_30d": [],
        },
        "known_issue_delivery": delivery,
    }
    # Остальные секции отчёта нас здесь не интересуют: любое недостающее
    # скалярное поле читается нулём, списки заданы явно.
    accounts = _Zeros()
    accounts["dead_list"] = []
    accounts["top_by_requests_30d"] = []
    return {
        "accounts": accounts,
        "tokens": _Zeros(),
        "requests": _Zeros(),
        "failures": _Zeros(),
        "feedback": empty_feedback,
        "activation_funnel": _Zeros(),
    }


class _Zeros(dict):
    """Любой неспрошенный ключ отчёта читается нулём, вложенный — тоже."""

    def __missing__(self, key):
        return _Zeros()

    def __str__(self) -> str:
        return "0"


# ── невозможные числа роняют секцию, а не отчёт ────────────────────────────


@pytest.mark.parametrize("bad", ["NaN", "+Inf", "-Inf", "-3"])
def test_impossible_value_makes_the_whole_section_no_data(bad):
    """NaN и отрицательные доставки — не «странное число», а битый ответ.

    Пропустить такую точку молча значит посчитать отношение по остатку и
    выдать его за правду. Ответу, где встретилось невозможное значение,
    доверять нельзя целиком.
    """
    payload = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"kind": "failure", "outcome": "matched"},
                    "values": [[_hours_ago(10).timestamp(), bad]],
                }
            ],
        },
    }
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "no_data"
    assert out["reason"] == "malformed_response"


def test_non_finite_timestamp_is_malformed_not_a_crash():
    payload = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"kind": "failure", "outcome": "matched"},
                    "values": [["NaN", "1"]],
                }
            ],
        },
    }
    out = summarize_known_issue_delivery(payload, now=NOW, window_days=WINDOW_DAYS)
    assert out["status"] == "no_data"
    assert out["reason"] == "malformed_response"


def test_delivery_rate_never_exceeds_one():
    out = summarize_known_issue_delivery(
        _one_day_old_payload(), now=NOW, window_days=WINDOW_DAYS
    )
    for row in out["by_kind"].values():
        assert row["deliveries"] <= row["lookups"]
        assert row["delivery_rate"] is None or 0.0 <= row["delivery_rate"] <= 1.0


def test_naive_now_is_read_as_utc_not_as_local_time(monkeypatch):
    """Иначе глубина тихо съезжает на смещение машины, где считают отчёт.

    Часовой пояс подменяется намеренно: в контейнере UTC, и без подмены тест
    был бы зелёным по совпадению, а не по существу.
    """
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        naive = NOW.replace(tzinfo=None)
        out = summarize_known_issue_delivery(
            _one_day_old_payload(), now=naive, window_days=WINDOW_DAYS
        )
        assert out["effective_depth_hours"] == 24
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


# ── битый адрес — такой же отказ метрик, как и молчащий сервис ─────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", ["not a url", "ftp://prometheus:9090", "http://"])
async def test_broken_base_url_is_no_data_without_touching_the_network(
    monkeypatch, bad_url
):
    """Транспорт отдаёт валидный ответ: если тест зелёный — до сети не дошло."""
    monkeypatch.setenv("PROMETHEUS_BASE_URL", bad_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_one_day_old_payload())

    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert out["status"] == "no_data"
    assert out["reason"] in {"invalid_url", "connection_error"}


@pytest.mark.asyncio
async def test_empty_base_url_env_falls_back_to_the_default(monkeypatch):
    """Пустая переменная — это «не задано», а не «битый адрес»."""
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_one_day_old_payload())

    out = await collect_known_issue_delivery(
        now=NOW, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    assert seen["url"].startswith(PROMETHEUS_DEFAULT_URL)
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_window_is_thirty_real_days_even_across_a_dst_shift():
    """`now - timedelta` в зоне с переводом часов — арифметика по настенным
    часам: окно тихо становится 719 или 721 часом."""
    from zoneinfo import ZoneInfo

    berlin_now = datetime(2026, 4, 10, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = request.url.params
        return httpx.Response(200, json=_one_day_old_payload())

    await collect_known_issue_delivery(
        now=berlin_now, window_days=WINDOW_DAYS, transport=_transport(handler)
    )
    span = float(seen["params"]["end"]) - float(seen["params"]["start"])
    assert span == pytest.approx(WINDOW_DAYS * 24 * 3600)


# ── сеть не живёт внутри сессии БД ─────────────────────────────────────────


@pytest_asyncio.fixture
async def empty_session(tmp_path, sqlite_session_factory_builder):
    factory = await sqlite_session_factory_builder(tmp_path / "stage283-5.db")
    async with factory() as session:
        yield session


@pytest.mark.asyncio
async def test_feedback_metrics_stay_sql_only(empty_session):
    """Поход в Prometheus не должен держать открытым соединение к базе."""
    out = await _collect_feedback_metrics(empty_session, now=NOW, top_n=10)
    assert set(out) == {"reports", "match_events"}
