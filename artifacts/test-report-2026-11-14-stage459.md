# Исправление тестов и Docker-окружения — 14.11.2026

Статус: **исправления готовы; push ожидает решения по внешнему ограничению экспорта**.

Ветка: `dev/test-contours-resource-cleanup`.
База после git pull: `b9c397def6086b6a5eff8aa42a87cb62c346537e` (Already up to date).
Коммит завершённого полного прогона: `42f7e9dcf574cba69755a6766b7906db5434fa64`.
Последующий коммит отчёта меняет только Markdown-файлы.

## Что сделано

- Создана отдельная ветка с префиксом dev/, который запускает штатный CI после push.
- Исправлен тест отсутствующего клиента: при success=true и totalCount=0 допустимы только `[]` и `{"merge_history": []}`. Реальная запись, дополнительные поля и непустая история отвергаются.
- Временный event loop браузерных тестов закрывает созданные им HTTP-клиенты до завершения; клиенты других loop остаются открытыми.
- Дочерние процессы завершаются и собираются, их pipe-потоки закрываются; stderr диагностики activation сохранён. Сбой восстановления PostgreSQL также гарантирует завершение дочернего pytest.
- Recovery удаляет только созданного им тестового клиента прямым тестовым REST-клиентом, независимо от остановленной MCP-БД. Проверяется отсутствие записи либо тот же ID со status=DELETED — это подтверждённый живым probe контракт удаления.
- Guidance-тест получает уникальное задание и проверяет отсутствие дедупликации до ожидания счётчика recreated.
- Добавлены `docker-compose.test.yml` и `scripts/run_isolated_test_suite.py`: отдельные PostgreSQL 16/Redis 7, уникальный Compose project, раздельные БД, без публикации портов; ownership label проверяется перед операциями над контейнером. Volume сохраняет данные для stop/start и удаляется вместе с проектом.
- Credentials и evidence находятся вне репозитория, секретные файлы имеют mode 0600. Missing credentials и пропущенный standalone recovery не дают ложного успеха.
- Задержка TLS shutdown ограничена real/focus/recovery; default/PG не получают глобальную задержку. Пустой DATABASE_URL сохраняет временные URL migration-тестов и исключает наследование production URL.

Кабинет владельца, его старые токены и интеграция не использовались и не менялись. Аккаунты MCP тесты создавали в изолированных временных базах. Production-код, права и инструменты MCP не изменены.

## Завершённый полный прогон

| Проверка | Результат | Exit |
|---|---|---|
| Пересборка образа и запуск изолированных сервисов | PASS | 0 |
| Default: unit/mock/browser | **4599 passed, 1 skipped**, 568.39 с, coverage 89% | 0 |
| Mandatory PostgreSQL + stage424 result gate | **6 passed**, все обязательные файлы выполнены | 0 |
| Real API + user-token + browser + recovery | **135 passed, 0 failed, 1 skipped-error**, 0 skipped-not-configured | **1** |
| Docker cleanup | PASS | 0 |

Реальный стенд: devtr6. Проверены оба способа авторизации Ветменеджера и отдельные тестовые bearer-учётки MCP. Все шесть user-token проверок выполнены.

## Точные пропуски и оставшееся ограничение

1. `tests/test_stage153_review_followup.py::test_f4_concurrent_create_feedback_report_no_lost_update_postgres_only` — существующий безусловный skip: тело true-concurrency теста остаётся заготовкой с NotImplementedError. Наличие PostgreSQL само этот skip не снимает. Новый PostgreSQL-контур фактически выполняет шесть других обязательных регрессий.
2. `tests/test_stage385_export_outcome_live.py::test_export_poll_success_is_one_outcome_across_slots` — Ветменеджер отказал в запуске экспорта. Отдельный повтор также дал skip. Диагностический вызов через тот же HTTP/MCP сценарий подтвердил `RUN_RATE_LIMITED` и ожидание 450 секунд перед одной новой попыткой. Предохранитель стенда не отключался. Существующий runner правильно классифицирует этот skip как ошибку и возвращает exit 1; полный real-набор не объявляется зелёным.

Требуется один из вариантов: дождаться разрешённой попытки и проверить экспорт либо получить явное решение владельца о push этой отдельной ветки с зафиксированным ограничением. Правило проекта запрещает push без пройденных проверок; до решения push не выполнялся.

## Дополнительные проверки

- Фокус после исправлений lifecycle/guidance/recovery: 29 passed, exit 0.
- Новый набор regression guards: 38 passed за 1.70 с в unit-контуре без глобальной задержки; последующая проверка migrations/IP-mask/environment: 40 passed, exit 0.
- Standalone recovery: 1 passed, result gate 0, process exit 0, cleanup 0.
- SIGTERM smoke: прерывание runner, cleanup exit 0, затем 0 контейнеров, volumes и networks его проекта.
- Guards показаны RED намеренными мутациями: whitelist/success/count отсутствующего клиента; ID/status удаления; pipe cleanup; owning-loop cleanup; foreign container labels; required auth; JUnit skip/error/missing; ошибки stop/restore; глобальные delay/DATABASE_URL. После исправления — GREEN.
- Ruff F/E9, roadmap structure, normalized Compose gate и git diff --check прошли. Shell scripts не менялись.

Два предварительных full-запуска остановлены после обнаружения ошибок нового окружения: глобальной задержки и DATABASE_URL. Они не считаются завершёнными успешными прогонами. Завершённый полный прогон в таблице выполнен после исправления обеих настроек.

## Ревью и коммиты

Spark: candidate-проходы с проверкой адекватности. Astra: два валидных PRD и два code-прохода; последнее сильное code-ревью без findings. Последующие узкие настройки окружения проверены отдельными post-budget scout и тестами по постоянному контракту проекта. Открытых critical/high нет. После указания владельца Opus не запускался.

- `39068c8` — основной lifecycle, регрессионные guards и Docker-контуры.
- `e9defa0` — reap pytest при ошибке восстановления PostgreSQL.
- `b6ae89e` — запрет ложного успеха пропущенного recovery.
- `2037993` — scope задержки закрытия HTTP.
- `42f7e9d` — временные URL migration-тестов; это code SHA полного прогона.

Подробный журнал решений и evidence — AssumptionLog.md. Raw evidence сохранён вне публичного репозитория. Значения учётных данных и локаторы upstream в отчёт не включены.
