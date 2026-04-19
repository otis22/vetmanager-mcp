# Этап 114b. Simplicity debt follow-up

## Цель

Закрыть deferred simplicity findings из super-review 2026-04-19 без broad cleanup ради cleanup. Этап ограничен тремя практическими направлениями: аудит inline imports, схлопывание лишней indirection в profile tools и доведение FilterBuilder migration до одного канонического entrypoint.

## Scope

### 114b.1 Codebase-wide inline imports audit

Проверить все inline imports в `src`/runtime-модулях и разделить их на два класса:
- legitimate keep с явным rationale (cycle break, optional dependency, import-time cost boundary);
- unneeded indirection/fix.

Решение:
- добавить маленький audit script для повторяемой проверки;
- завести allowlist с краткой причиной на каждый keep-case;
- не трогать test/doc/example inline imports.

### 114b.2 3-hop indirection collapse в profile tools

`tools/client.py:get_client_profile` и `tools/pet.py:get_pet_profile` сейчас идут через `_impl` closure + отдельный `_get_*_profile_impl` wrapper только ради inline import target.

Решение:
- перенести imports на module level;
- оставить один вызов `instrument_call(..., lambda/fetch)` без вспомогательных hop-функций;
- сохранить observable MCP contract и instrumentation labels.

### 114b.3 FilterBuilder migration follow-up

В `resources/client_profile.py`, `resources/pet_profile.py` и `tools/medical_card.py` всё ещё есть hand-rolled `json.dumps([...to_dict()])`.

Решение:
- использовать `filters.build_list_query_params(...)` как единую точку сериализации filter/sort/list params;
- оставить short-circuit semantics (`pet_ids == []`) без изменения;
- не переносить весь project на FilterBuilder повторно, только оставшиеся call-sites из acceptance.

### 114b.4 BC shim follow-up review

`tools/_aggregation.py` и `request_credentials.py` уже имеют stage-114b policy `KEEP`. Здесь задача не удалить их, а подтвердить policy и не ломать BC invariants.

Решение:
- не удалять shims в этом цикле;
- сохранить/переподтвердить rationale в PRD и AssumptionLog;
- если audit script покажет 0 legitimate callers, это всё равно не migration trigger само по себе.

## Non-scope

- Удаление BC shim'ов и underscore re-exports.
- Broad style cleanup вне конкретных call-site'ов этапа.
- Product/workflow findings из post-review (`118`/`119`).

## Acceptance

1. Runtime/source inline imports либо задокументированы в audit allowlist, либо удалены.
2. `tools/client.py:get_client_profile` и `tools/pet.py:get_pet_profile` больше не используют 3-hop helper chain.
3. `resources/client_profile.py`, `resources/pet_profile.py`, `tools/medical_card.py` используют `build_list_query_params(...)` вместо hand-rolled JSON filter assembly.
4. BC shim policy явно остаётся `KEEP` в текущем цикле.
5. Targeted tests и full suite зелёные.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---:|---|
| 114b.1 | Audit script + allowlist + test coverage | ~60 | `scripts/inline_imports_audit.py`, tests |
| 114b.2 | Collapse profile-tool indirection | ~25 | `tools/client.py`, `tools/pet.py` |
| 114b.3 | FilterBuilder migration for remaining call-sites | ~35 | `resources/client_profile.py`, `resources/pet_profile.py`, `tools/medical_card.py` |
| 114b.4 | Policy confirmation in docs/log | ~10 | `AssumptionLog.md` |

Total target: ~130 LOC logic/tests plus workflow updates, без нового abstraction layer.

## Rationale для выбранной сложности

- Вариант "просто grep и вручную посмотреть" слишком хрупкий: stage acceptance просит repeatable audit, поэтому нужен маленький script/allowlist.
- Вариант "массово поднять все inline imports на module level" отклонён: часть импортов легитимна и привязана к cycle/optional deps.
- Вариант "сразу удалить BC shims" отклонён: current policy уже `KEEP`, а tests закрепляют identity semantics.
