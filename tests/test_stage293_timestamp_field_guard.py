"""Этап 293.3 — голую дату нельзя молча поставить границей timestamp-поля.

Дефект «диапазон теряет последний день» прошёл мимо трижды: его починили для
`get_payments` (проблема #21), оставили в `get_invoices`, в `get_debtors` и в
окне неактивных клиентов. Каждый раз рядом стоял зелёный тест, прибивавший
неверную границу. Значит нужен сторож не на конкретный инструмент, а на форму.

Форма дефекта всегда одна: значение, полученное из `parse_date_param` или
`calculate_inactive_window` — то есть голая дата `YYYY-MM-DD`, — уезжает
границей фильтра по полю из `VM_TIMESTAMP_FIELDS` без обёртки в границы суток.

Сторож разбирает `tools/*.py` как AST, а не грепом: greп не отличит
`_filter_lte("create_date", resolved_date_to)` от той же строки в комментарии
или в докстринге и не увидит, откуда пришло значение.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vm_datetime import VM_TIMESTAMP_FIELDS


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"

# Функции, отдающие голую дату `YYYY-MM-DD`. Список пополняется по месту:
# обёртки над ними ищутся в самом модуле — первая версия сторожа знала только
# `parse_date_param` и **не поймала главный случай**, потому что `get_invoices`
# берёт даты через локальную обёртку `_parse_date_range`. Сторож, не ловящий
# дефект, ради которого написан, — это зелёный тест на пустом месте.
BARE_DATE_PRODUCERS = {"parse_date_param", "calculate_inactive_window"}

# Обёртки, превращающие голую дату в границу суток.
WHOLE_DAY_WRAPPERS = {"day_start", "next_day_start", "_day_start", "_next_day_start"}

# Имена, под которыми в коде вызываются построители сравнений.
COMPARISON_BUILDERS = {
    "gte", "lte", "lt", "gt",
    "_filter_gte", "_filter_lte", "_filter_lt", "_filter_gt",
}


def _called_name(node: ast.expr) -> str:
    func = node.func if isinstance(node, ast.Call) else node
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def _producers_in_module(tree: ast.AST) -> set[str]:
    """Голую дату отдаёт не только `parse_date_param`, но и обёртки над ним.

    `get_invoices` вызывает локальную `_parse_date_range`, которая внутри зовёт
    `parse_date_param` и возвращает пару дат. Обёртки ищутся до неподвижной
    точки: обёртка над обёрткой тоже отдаёт голую дату.
    """
    producers = set(BARE_DATE_PRODUCERS)
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    changed = True
    while changed:
        changed = False
        for function in functions:
            if function.name in producers:
                continue
            if any(
                isinstance(inner, ast.Call) and _called_name(inner) in producers
                for inner in ast.walk(function)
            ):
                producers.add(function.name)
                changed = True
    return producers


def _bare_date_names(tree: ast.AST) -> set[str]:
    """Переменные, в которые положили голую дату.

    Учитывается и распаковка кортежа: `cutoff_oldest, cutoff_newest =
    calculate_inactive_window(...)` — обе переменные голые.
    """
    producers = _producers_in_module(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _called_name(node.value) not in producers:
            continue
        for target in node.targets:
            for element in (target.elts if isinstance(target, ast.Tuple) else [target]):
                if isinstance(element, ast.Name):
                    names.add(element.id)
    return names


def _is_whole_day_bound(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):
        return _called_name(node) in WHOLE_DAY_WRAPPERS
    if isinstance(node, ast.JoinedStr):
        # `f"{day} 00:00:00"` — тот же смысл, записанный руками.
        return any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and "00:00:00" in part.value
            for part in node.values
        )
    return False


def _violations(source: str) -> list[str]:
    tree = ast.parse(source)
    bare = _bare_date_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        called = _called_name(node)
        if called not in COMPARISON_BUILDERS:
            continue
        field, value = node.args[0], node.args[1]
        if not (isinstance(field, ast.Constant) and field.value in VM_TIMESTAMP_FIELDS):
            continue
        if isinstance(value, ast.Name) and value.id in bare and not _is_whole_day_bound(value):
            found.append(f"line {node.lineno}: {called}({field.value!r}, {value.id})")
    return found


def test_the_guard_recognises_the_defect_it_was_written_for() -> None:
    """Самопроверка сторожа на форме, которая трижды доехала до боя.

    Без неё зелёный сторож не отличить от сторожа, который ничего не проверяет.
    """
    bad = """
def register():
    resolved_from = parse_date_param(date_from)
    resolved_to = parse_date_param(date_to)
    filters.append(_filter_gte("create_date", resolved_from))
    filters.append(_filter_lte("create_date", resolved_to))
"""
    violations = _violations(bad)

    assert len(violations) == 2
    assert "create_date" in violations[0]


def test_the_guard_accepts_the_fixed_form() -> None:
    good = """
def register():
    resolved_from = parse_date_param(date_from)
    resolved_to = parse_date_param(date_to)
    filters.append(_filter_gte("create_date", _day_start(resolved_from)))
    filters.append(_filter_lt("create_date", _next_day_start(resolved_to)))
"""
    assert _violations(good) == []


def test_the_guard_accepts_a_hand_written_day_boundary() -> None:
    """`tools/admission.py` строит границу f-строкой — это тот же смысл."""
    good = """
def register():
    effective_from = parse_date_param(date_from)
    filters.append(_filter_gte("admission_date", f"{effective_from} 00:00:00"))
"""
    assert _violations(good) == []


def test_a_field_outside_the_registry_is_not_flagged() -> None:
    """Сторож не должен мешать сравнивать даты там, где колонка — `date`."""
    neutral = """
def register():
    resolved = parse_date_param(value)
    filters.append(_filter_lte("birthday", resolved))
"""
    assert _violations(neutral) == []


@pytest.mark.parametrize(
    "path", sorted(TOOLS_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_no_bare_date_bound_on_a_timestamp_field(path: Path) -> None:
    violations = _violations(path.read_text(encoding="utf-8"))

    assert not violations, (
        f"{path.name}: голая дата поставлена границей timestamp-поля — "
        f"диапазон потеряет последний день:\n  " + "\n  ".join(violations)
    )


def test_the_guard_sees_through_a_local_wrapper() -> None:
    """Форма из `get_invoices`: даты приходят через локальную обёртку.

    Первая версия сторожа знала только `parse_date_param` и на этом коде была
    зелёной — то есть пропускала ровно тот дефект, ради которого написана.
    Проверено на настоящем дореформенном `tools/invoice.py` из коммита dbe3764.
    """
    bad = """
def register():
    def _parse_date_range(date_from, date_to, *, label):
        return parse_date_param(date_from), parse_date_param(date_to)

    resolved_from, resolved_to = _parse_date_range(date_from, date_to, label="date")
    filters.append(_filter_lte("create_date", resolved_to))
"""
    violations = _violations(bad)

    assert violations, "сторож не видит голую дату за обёрткой"
    assert "create_date" in violations[0]
