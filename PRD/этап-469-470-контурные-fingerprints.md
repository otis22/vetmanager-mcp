# Этапы 469 + 470 — контурные fingerprints и документация

## Цель

Повторять обязательные тестовые контуры после изменения относящихся к ним входов, не теряя fail-closed проверку состава и результата. Согласовать правила workflow и исправить формат заголовка записи 461.

## Проверенные исходные факты

- `scripts/offline_gate_manifest.py` сейчас хеширует все Python-файлы, shell-скрипты, `ops/`, конфигурацию и оба offline inventory общим `source_fingerprint`; default и PostgreSQL manifests проверяют точные node IDs и JUnit без skip/failure.
- `scripts/real_group_gate.py` хеширует runtime и тесты групп отдельно; `scripts/run_isolated_test_suite.py` при aggregate проверяет текущие source SHA, точный real node manifest, JUnit и cleanup, но dependency fingerprint берёт из самих shards и не сверяет image ID с текущим образом. Это закрывается этапом 469.
- Состав default, PostgreSQL и real определяется `default_node_inventory.json`, `postgres_node_inventory.json` и `real_group_manifest.json`. Файл с тестами может входить в несколько контуров.
- Работа меняет только тестовые гейты и процессную документацию; MCP-инструменты, API, доступ и трактовку выданных учётных данных не меняет. Живой вызов изменённого инструмента N/A.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` §2–3 фиксирует Python/pytest и Docker Compose как обязательный тестовый контур; `artifacts/prd-vetmanager-mcp-ru.md` §4.3 требует надёжной обратной связи при ошибках. Поэтому изменение касается достоверности проверок, а не API-контракта клиники.

## Решение и граница

Один детерминированный классификатор входов строит пути для `default`, `postgres`, `real`: общий runtime/config/dependency/shared-helper слой и файлы тестов по принадлежности к контурам. Общий слой явно включает все production и test runner Python-файлы вне тестовых модулей, shell-скрипты, `ops/`, `Dockerfile`, оба Compose-файла, `pyproject.toml`, `pytest.ini`, `.coveragerc`, `alembic.ini`, versioned fixture и общие manifest/config; `tests/conftest.py` и `tests/real_suite_outcomes.py` включаются независимо от импортов. Импортированный тестовый helper включается в контур импортёра; неразрешённый импорт или неизвестный тестовый файл включается во все контуры до уточнения inventory. Отсутствующий обязательный вход и несовпадение collect-only с inventory остаются ошибкой. У каждого offline manifest свой fingerprint; real-группы используют общий слой и собственные тесты, а aggregate проверяет свежесть по тем же правилам. Для real aggregate текущие dependency fingerprint и image ID вычисляются из используемого Compose-образа, а не принимаются из самих shards. Изменение только `.md` не меняет fingerprints. Входы конфигурации и версии установленных зависимостей сохраняются.

Вне scope: изменение набора тестов, маркеров, смысла тестов, MCP-инструментов, workflow деплоя и эксплуатационных данных.

## Декомпозиция

1. **469.1** Добавить контракт входов и контурный fingerprint в offline/real gates (≤150 строк на изменение). Сохранить schema/version, точные node IDs, JUnit и fail-closed сборку.
2. **469.2** Написать и показать красными сторожа для real-only, default-only, PostgreSQL-only, shared/runtime/config/dependencies, неизвестных и отсутствующих входов; сделать green, owning, fast и применимые полные проверки.
3. **470.1** После 469 уточнить `CLAUDE.md`, `AGENTS.md`, Cursor rule и шаблон: обязательные focused/fast/default после соответствующих runtime/tests; real-only test инвалидирует только real.
4. **470.2** Привести заголовок записи 461 в `AssumptionLog.md` к `## ` и отделить пустой строкой, сохранив текст.

## Приёмка

- Изменение только real-only теста меняет real fingerprint, но сохраняет default и PostgreSQL; только default-only меняет default (и fast как его подмножество), но не real/PostgreSQL; PostgreSQL-only меняет PostgreSQL.
- Общие runtime, fixtures, config и зависимости инвалидируют связанные контуры; красная мутация real aggregate отдельно меняет текущие dependency fingerprint и image ID и доказывает оба отказа. Неизвестный вход, утрата inventory/node/JUnit и устаревший fingerprint отклоняются.
- Docs-only не повторяет suites; формулировки в четырёх документах согласованы с реализованной границей.
- Красные мутации сторожей, focused/owning/fast, полный default, PostgreSQL и real aggregate, PRD/Architecture Critique, полное pre-freeze и committed-diff review имеют сохранённые exit/verdict evidence. Ни один обязательный красный gate не обойдён.

## Оценка простоты

Граница понятна как «общие входы плюс входы выбранного контура». Используется одна функция выбора путей и существующие manifest/runner; новый кэш или второй источник состава тестов не вводится. При добавлении теста меняется только inventory нужного контура. Неизвестный файл включается во все fingerprints до классификации, поэтому улучшение скорости не покупается ценой пропуска проверки.

## Откат

Откатить целиком контурный классификатор и интеграцию offline/real gates к общему fingerprint, вернуть документацию к действовавшему правилу и повторить обязательные полные контуры. Частичный откат только одного gate не допускается.
