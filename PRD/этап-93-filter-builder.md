# Этап 93. FilterBuilder — типизированный API для VM filter-массивов

## Контекст

Baseline H11 (architecture, confidence 0.90): паттерн `json.dumps([{"property": X, "value": Y, "operator": "="}], separators=(",", ":"))` скопирован 15+ раз в `tools/*.py` с subtle differences (ensure_ascii, separators, operator casing, IN-operator list handling). Рулевой фикс — типизированный builder, одна точка валидации.

## Цель

Ввести `Filter` dataclass + helpers-билдеры. `build_list_query_params` принимает list[Filter] ИЛИ legacy list[dict]. Миграция callers — в 93b, отдельной сессией.

## Scope

**В scope (93):**
- Новый модуль `filters.py`: `FilterOp` enum, `Filter` dataclass, helpers `eq/ne/lt/lte/gt/gte/in_/not_in/like`.
- `validators.build_list_query_params` accepts `list[Filter]` (converts to list[dict] internally).
- 15-20 unit тестов на builder и операторы.

**Вне scope (→ 93b):**
- Миграция tools/*.py callers на FilterBuilder.
- Lint/test contract запрещающий raw json.dumps фильтров вне filters.py.
- Gateway/repository layer для entities.

## Подзадачи

### 93.1 `filters.py`

```python
class FilterOp(StrEnum):
    EQ = "="
    NE = "!="
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"

@dataclass(frozen=True)
class Filter:
    property: str
    value: Any
    operator: FilterOp

    def to_dict(self) -> dict:
        return {"property": self.property, "value": self.value, "operator": self.operator.value}

def eq(property: str, value) -> Filter: ...
def ne(property: str, value) -> Filter: ...
...
def in_(property: str, values: list) -> Filter: ...
def not_in(property: str, values: list) -> Filter: ...
def like(property: str, pattern: str) -> Filter: ...
```

LOC: ≤80.

### 93.2 `validators.build_list_query_params` accepts Filter objects

Convert `list[Filter]` → `list[dict]` via `[f.to_dict() for f in filters]`.

LOC: ≤15.

### 93.3 Тесты

- 9 тестов на каждый operator helper
- Филтр combine (`[eq(...), in_(...)]` → корректный список dicts)
- build_list_query_params accepts Filter list

LOC: ≤80.

### 93.4 Codex review + commit

## Acceptance

- `from filters import Filter, eq, in_, like` works
- `build_list_query_params(filters=[eq("status", "ACTIVE"), in_("id", [1,2,3])])` produces same JSON as raw dict equivalent
- Full suite зелёный
- Codex 0 adequate criticals
