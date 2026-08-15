# PRD — Этап 214: baseline покрытия тестами

## Статус

`done`

## Цель

Получить воспроизводимое исходное измерение покрытия существующего default test
contour: полный процент, отчёт по файлам/модулям и `coverage.xml` в CI. Coverage
информирует, но не блокирует сборку порогом.

## Проверенные факты

- `Dockerfile` test target уже устанавливает `pytest-cov`, но эта зависимость
  не объявлена в `pyproject.toml` и test runner не передаёт pytest `--cov`.
- Local default contour запускает `scripts/run_default_test_suite.py`; GitHub
  workflow `Tests` запускает fast и default через Docker, но не публикует
  summary или артефакты.
- Existing GitHub `docker run` bind-mounts `${{ github.workspace }}` to `/app`,
  therefore the XML written as `/app/coverage.xml` is already host-visible;
  no `docker cp` or second container is required. The build target must be
  explicit (`--target test`) rather than relying on Dockerfile ordering.
- `/metrics` и весь runtime import tree должны входить в baseline, а tests,
  Alembic migration environment и вспомогательные scripts не являются
  измеряемым product code.

## Декомпозиция

1. Добавить закреплённую dev/test зависимость и единый `.coveragerc` с
   продуктовым source scope и исключениями для test/ops scripts. ≤50 строк.
2. Дополнить default runner coverage summary + `coverage.xml`, не добавляя
   `fail_under`; проверить запуск в test Docker image. ≤50 строк.
3. Обновить CI: явный `--target test`, job summary и XML artifact из того же
   bind-mounted запуска, без второго полного pytest pass. ≤100 строк.
4. Зафиксировать measured total и ключевые модули после full contour. ≤2 ч.

## Архитектурное решение

### Проблема и ограничения

Baseline должен быть сопоставимым между local и CI, но не должен покрывать
тесты самими собой или превращать начальное число в нестабильный quality gate.
Полный suite уже занимает заметное время, поэтому второй прогон только для XML
неприемлем.

### Рассмотренные варианты

1. `pytest --cov=.` с inline flags в workflow. Отклонён: local/CI drift и
   неясный scope при добавлении файлов.
2. Отдельно запускать full pytest и затем ещё раз coverage. Отклонён: почти
   удваивает время CI.
3. Один default pytest pass с централизованным `.coveragerc`, terminal summary
   и XML output. Выбрано: одинаковый scope, один измеряемый run, artifact
   доступен без изменения runtime image.

### Инварианты и fallback

- Нет `fail_under`, `--cov-fail-under` или CI condition, зависящего от процента.
- XML не содержит credentials; это агрегированные пути/line hits исходников.
- Fast contour остаётся быстрым; baseline публикуется из default contour.
- При проблеме upload artifact тестовый результат не маскируется: upload
  выполняется `if: always()`, а успешные тесты остаются источником статуса.

Architecture Critique: not required — изменение затрагивает локальный/CI test
tooling, но не меняет runtime, public API/MCP contract, auth, storage или
production behavior.

## Acceptance criteria

1. `pyproject.toml` и test Docker image объявляют совместимые coverage deps.
2. Default contour печатает total и file-level table, создаёт `coverage.xml`.
3. CI пишет total в job summary и загружает XML; coverage не выполняет второй
   full suite.
4. В финальном отчёте указаны total и auth, feedback, Report AI,
   `service_metrics`, `activation_telemetry`, а также изменение длительности.

## Результат измерения

Default contour завершился с `exit 0`. Line coverage: **88,58%**
(`7464/8426`). По выбранным модулям: `auth/` — 89,11% (`221/248`),
`tools/feedback.py` — 58,33% (`7/12`), `tools/report_ai.py` — 90,37%
(`244/270`), `service_metrics.py` — 98,56% (`206/209`),
`activation_telemetry.py` — 95,45% (`105/110`).

На одной локальной Docker-среде тот же default contour без coverage занял около
5:20, с coverage — 6:02: увеличение около 42 секунд (примерно 13%).
