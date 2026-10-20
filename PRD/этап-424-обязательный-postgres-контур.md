# Этап 424 — обязательный PostgreSQL-контур CI

Дата: 20.10.2026. Источник: `artifacts/review/2026-10-20-full-stage-420.md`, R4.

## Проблема и цель

`test_contours.py` исключает marker `postgres` из default/fast; PostgreSQL job
в `.github/workflows/test.yml` запускает только три файла. Три более новых
PostgreSQL-регрессии остаются вне обязательного CI. Цель — запускать все
`postgres`-marked tests при каждом Tests run на dev/main и обнаруживать
потерю этого покрытия красным сторожем.

## Проверенные факты и замер

20.10.2026 в CI-подобном окружении: `postgres:16-alpine` с временной БД
`vetmanager_test` на loopback:5432; существующий `vetmanager-mcp-test` image,
`docker run --rm --network host`, тот же `POSTGRES_TEST_DATABASE_URL`, bind
checkout `/app`, пользователь `1001:1001`. Команда:

```sh
/usr/bin/time -f 'elapsed=%e seconds exit=%x' docker run --rm --network host -e POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://vetmanager:vetmanager@127.0.0.1:5432/vetmanager_test -v "$PWD:/app" -u 1001:1001 vetmanager-mcp-test pytest -q -m postgres
```

Результат: **6 passed, 4421 deselected in 12.44s**, wall time **17.26 s**,
exit 0. `pytest --collect-only -q -m postgres` выбрал по одному тесту из
`test_stage227_postgres_activation_telemetry.py`,
`test_stage359_postgres_activation_journal.py`,
`test_stage374_first_session.py`, `test_stage376_expiry_notice.py`,
`test_stage385_cache_barrier.py`, `test_vetmanager_connection_service.py`.
Разница wall/pytest включает старт контейнера и сбор; прогон на GitHub runner
может отличаться, поэтому после push проверяется фактический CI.

## Архитектурное решение

Проблема: состав обязательных тестов расходится с фактическим набором
PostgreSQL-регрессий. Окружение: существующая GitHub Actions job с временным
PostgreSQL 16, изоляция от production и read/write test DB; API и сервисные
контракты не меняются. Ограничение по времени: измеренные 17.26 s wall для
полного набора, что приемлемо относительно сборки Docker image и остальных
контуров CI.

Варианты: (1) перечислить шесть файлов — малое изменение, но будущий файл
можно снова забыть; (2) `pytest -q -m postgres` — автоматически подхватывает
новые marked tests, а текущая стоимость мала. Выбран вариант 2.

Инварианты: PostgreSQL job запускает точную команду
`pytest -q -m postgres --junitxml=/tmp/stage424-postgres.xml` без
ограничивающих selectors и `continue-on-error`; в том же `docker run`
скрипт читает JUnit XML из `/tmp` и требует `skipped=0`, `errors=0`,
`failures=0`, а также присутствие
каждого из шести обязательных test-file в реально исполненных testcase.
Все шесть обязательных файлов имеют выбираемые marked tests. Сторож проверяет
workflow и фактическую коллекцию pytest. Существующий
`test_postgres_race_guard_runs_in_ci` из stage 374 ожидает literal-путь в
workflow; его нужно заменить/обобщить новым сторожем реальной marker-выборки,
чтобы проверка сохраняла смысл после перехода на `-m postgres`.
Если CI на runner выявит
неприемлемую стоимость, fallback — явный
список всех обязательных файлов с обновлённым сторожем и новым замером;
обход тестов или удаление marker не допускается. Rollback — отдельный
ревьюируемый commit с сохранением покрытия шести файлов.

Architecture Critique и PRD-review объединены: решение влияет на CI
performance/load limit; пара Astra/Opus проверяет архитектуру, scope,
критерии и rollback до реализации.

## Подзадачи и приёмка

1. 424.1 (≤2 ч, ≤150 строк): замер, выбор полного контура, PRD-гейт;
   написать guard. Красный: на исходной workflow с трёхфайловой командой
   показать nonzero exit; после Green добавить `--deselect` одного
   обязательного файла и снова показать падение; потеря marker в любом из
   шести файлов также ловится проверкой коллекции. Отдельный красный цикл
   валидатора: XML без обязательного testcase или со `skipped>0` даёт nonzero.
2. 424.2 (≤2 ч, ≤150 строк): изменить job на `pytest -q -m postgres`,
   проверить точно эту команду локально с exit 0, запустить фокусные тесты,
   review, push только dev-ветки; `gh run` Tests success, JUnit проверяет
   все шесть обязательных файлов и 0 skipped; в логе job видны имена тестов,
   включая три R4.

Не меняем сами PostgreSQL-тесты ради прохождения. Проверка отсутствующего
marker у произвольного будущего теста вне scope R4: такой тест попадает в
default-контур; новый guard проверяет marker и выборку шести известных файлов.
Tool code не изменяется:
live MCP/API gate неприменим. Сервисный код не изменяется: по решению
владельца 424 полный mock+real не нужен; для нового сторожа дополнительно
прогоним полный mock/default-контур один раз перед commit. Real API suite
перед merge — работа супервизора релизного поезда. Нет deploy или production
checks.
