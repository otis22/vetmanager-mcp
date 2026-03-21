# PRD: Этап 29. Stabilization: убрать test warnings и хвосты инфраструктуры

## Цель

Убрать известные warnings и lifecycle-хвосты тестового контура, чтобы полный
suite проходил без скрытых thread/loop проблем.

## Что сделано

- Исследован источник `aiosqlite` warnings при teardown async tests.
- `storage.reset_storage_state()` теперь не только чистит cache, но и явно
  dispose'ит cached `AsyncEngine`, в том числе из async context.
- В `pytest.ini` явно зафиксирован `asyncio_default_fixture_loop_scope=function`,
  чтобы убрать deprecation warning от `pytest-asyncio`.
- Добавлены regression tests:
  - dispose cached engine в async context;
  - bootstrap fresh storage schema для локального runtime.

## Критерии готовности

- Warning-чувствительный срез проходит с `python -W error -m pytest`.
- Полный suite больше не даёт старый `aiosqlite` warning из-за неубранного engine lifecycle.
