# Продолжение работы vetmanager-mcp — 14.11.2026

Документ фиксирует решения, фактические результаты и границы незавершённой работы для следующего процесса. Он не заменяет `Roadmap.md`, PRD и `AssumptionLog.md` в соответствующих worktree.

## Текущий статус

- **Поезд на паузе по прямой команде владельца.** Возобновление только по отдельной команде.
- Этап 459 — `supervisor_pending`; этап 460 — `supervisor_pending`. Остальные этапы не запущены.
- Активных Codex-процессов, диагностических тестов, background tasks и периодических статусов нет.
- На момент паузы `main` и `origin/main` были `feca9a5d1777beac2764d5f36d32cc93d733b88e`; Docs Check `43620805595` — success. Перед продолжением проверить актуальные `git rev-parse main origin/main`: последующие handoff-коммиты меняют SHA.
- Код 459 и 460 не коммитился и не пушился. Merge и deploy не выполнялись; часовой мониторинг и обновление дашбордов не начинались.
- Рабочие worktree и evidence сохранены. Их нельзя удалять или очищать до продолжения и приёмки.

Очередь в Roadmap: **463 → 459 → 460 → 461 → 462 → 464 → 465**, но сейчас действует пауза. Этап 459 поднят перед 460, потому что полный real suite блокирует приёмку 460.

## Этап 463 — онбординг 1.2: `done`

Сделано:

- Добавлен `AGENT_ONBOARDING.md` 1.2 и ссылки из `AGENTS.md`/`CLAUDE.md`.
- Закреплены безопасность данных, конфиденциальность `vetmanager-extjs`, границы самостоятельности, эскалация через куратора и attestation для неинтерактивного исполнителя.
- OpenAPI описывает контракт, код — реализацию; расхождение нельзя молча признавать нормой.
- Исполнители 459 и 460 записали attestation до изменения кода.
- Основные коммиты: `98a8381` (онбординг), `0eacfdd` (attestation и пострелизный контроль).

## Этап 460 — `recommendation` в списках медкарт: `supervisor_pending`

Исходная проблема #168: REST использует поле `recomendation`, а публичная проекция принимает `recommendation`; текст молча исчезал.

Подготовлен узкий WIP:

- `list_projection.py`;
- `PRD/этап-460-проекция-рекомендации-медкарты.md`;
- `tests/test_stage460_live.py`;
- `tests/test_stage460_medical_card_recommendation.py`;
- изменённые `Roadmap.md` и `AssumptionLog.md`.

Ветка `dev/roadmap-460-462`, базовый и upstream SHA `9ec6dc44b8a22cbad5150373f5a562cbdd2bc087`. Удалённой новой кодовой версии нет.

Решение:

- Только для `get_medical_cards`, `get_medical_cards_by_date`, `get_medical_cards_by_client_id` при запросе `recommendation` читается существующий публичный ключ, а при его отсутствии — исходный `recomendation`.
- Публичный ключ приоритетен даже при `null` и пустой строке.
- Полный ответ без `fields`, write-контракты, filter/sort и `description` не меняются. Глобальный alias не добавлен.

Доказательства:

- PRD/Architecture Critique и сильные PRD-ревью выполнены; незакрытых critical/high нет.
- Красная мутация `source = field`: 3 failed, 7 passed; после восстановления: 10 passed.
- Живой read-only вызов всех трёх инструментов: итоговый REST GET/200, безопасная проекция совпала после очистки.
- Полный mock: **4598 passed, 3 skipped**, exit 0.
- Полный real: **114 passed, 4 failed, 19 skipped-not-configured**, exit 1. Тест 460 внутри него прошёл. Отказали `test_real_nonexistent_client_raises`, stage276 export, stage389 pages и stage396 Report AI.
- Из-за красного real commit, committed-diff review и push не выполнялись. Продолжение только после зелёного 459 и повторных финальных гейтов.

## Этап 459 — стабилизация real suite: `supervisor_pending`

Ветка `dev/roadmap-459-real-suite`, базовый SHA `e619e0b93898376cc1cc901ed090fb49be0be105`. Удалённой ветки нет.

### Подтверждённые исправления

1. **`get_client_by_id`:** точная пустая форма `client={merge_history:[]}` с целочисленным `totalCount=0` больше не считается найденным клиентом; возвращается NotFound. Неожиданные формы не нормализуются в отсутствие.
2. **Real-тест несуществующего клиента:** допущены ровно две наблюдаемые пустые формы, `[]` и `{"merge_history":[]}`; лишние ключи и нецелочисленный count остаются ошибкой.
3. **Stage396:** ручной 24-секундный poll заменён существующим bounded `wait_seconds=120`; постоянный незавершённый job остаётся ошибкой.
4. **Web billing callsite:** включён существующий один ограниченный retry (`max_retries=1`), POST интеграции не дублируется.
5. **Billing lookup:** лимит 5.6 с только для billing, clinic probes остались 2.5 с. Худший последовательный путь 27.6 с при общем GET budget 30 с. Основание — успешные Docker TLS/GET до 4237/5506 мс при прежних лимитах 1.5/2.0/2.5 с.
6. **AnyIO cancellation cleanup:** владелец прежнего сокета доказан как billing resolver client. Запрос завершился `CancelledError`; `client.aclose()` начался и завершился, но `socket.close()` не произошёл. AnyIO 4.15.1 дал красный cancellation guard, AnyIO 4.16.0 — зелёный. В `pyproject.toml` и Dockerfile добавлено `anyio>=4.16.0,<5`.
7. **Stage431 worker cleanup:** failed startup и readiness check включены в cleanup; worker завершается и ожидается, есть kill fallback. Два сторожа были красными до исправления и зелёными после.

### Подтверждённые проверки

- Стандартные test и production builds: exit 0, AnyIO 4.16.0.
- Строгий `test_e2e_real.py`: **59 passed, 6 skipped**, exit 0, без ResourceWarning.
- Focused transport/SSRF: 78 passed; focused real transport: 5 passed; focused live stage431/436: 2 passed с `-W error`.
- Полный mock: **4598 passed, 3 skipped**, exit 0.
- Штатный полный real: **114 passed, 4 failed, 19 skipped-not-configured**, exit 1. Export и stage389/390 прошли.

### Оставшиеся проблемы

- Stage375/420: редкие unclosed uvloop TCPTransport ResourceWarning.
- Stage376: uvloop close EBUSY/thread warning.
- Stage383: upstream timeout вместо ожидаемого 404; assertion не ослаблен.
- Владелец исходного uvloop transport и минимальная стабильная последовательность не установлены. Diagnostic-only прогоны показывали корректное закрытие, но редкий warning не воспроизводился.
- Дополнительный instrumented real дал другие failures workers/subprocess и один skipped-error; он не заменяет штатный гейт и не доказывает регрессию или исправление.
- Нельзя приписывать эти события уже исправленной AnyIO-утечке без нового ownership evidence.

Поэтому commit, committed-diff Astra/Opus и push по-прежнему запрещены. Случайные повторы полного suite, skip, warning filters, отключение unraisable и ослабление assertions запрещены.

### Состав WIP 459

Изменённые файлы:

- `AssumptionLog.md`, `Roadmap.md`, `Dockerfile`, `pyproject.toml`, `host_resolver.py`;
- `tools/client.py`, `vetmanager_connection_service.py`;
- `tests/test_e2e_real.py`, `tests/test_stage396_live.py`, `tests/test_stage431_live.py`, `tests/test_stage448_billing_fallback.py`.

Новые файлы:

- `PRD/этап-459-стабилизация-real-suite.md`;
- `tests/test_stage459_anyio_cancel_cleanup.py`;
- `tests/test_stage459_billing_timeout.py`;
- `tests/test_stage459_billing_web_retry.py`;
- `tests/test_stage459_live.py`;
- `tests/test_stage459_missing_client.py`;
- `tests/test_stage459_worker_cleanup.py`.

## Этапы 461, 462, 464 и 465: `todo`

- **461:** один кластер Report AI `PREVIEW_FAILED / OTHER` по #163–166. Установить класс отказа, допустимость retry и конкретный безопасный workaround; не создавать серию одинаковых jobs.
- **462:** повторный drift `get_clients(fields, include=[])` по #150/#161. Нужна обезличенная форма ответа; fail-closed защиту не снимать.
- **464:** наблюдение всех трёх workers и измеримое начало/восстановление простоя; Prometheus пока видит один worker.
- **465:** пересмотр состава real suite по решению владельца. Построить карту сценариев и рисков, детерминированный release gate и отдельный diagnostic набор. Удаление/перенос проверки — только с rationale и сохранением покрытия, а не из-за её нестабильности.

## Как продолжить после команды владельца

1. Прочитать `AGENTS.md`, `AGENT_ONBOARDING.md` 1.2, `CLAUDE.md`, `.cursor/rules/agent-workflow.mdc`, актуальный `Roadmap.md`, PRD 459/460 и записи AssumptionLog в соответствующих worktree.
2. Проверить HEAD и состав WIP по этому документу. Не делать reset/clean/restore и не удалять worktree.
3. Новому исполнителю записать attestation с версией онбординга, базовым SHA и ограничениями до изменения кода.
4. Для 459 сначала получить ownership/shutdown evidence uvloop warning и отдельно классифицировать stage383. Не начинать с очередного случайного полного прогона.
5. Все полные логи и exit codes сохранять в файлы: `--rm`-контейнер удаляет вывод, недоступный после завершения.
6. После причинного fix: focused red/green и live evidence, полный mock и полный real на финальном SHA. Нужен exit 0, явный pass export/stage389 и отсутствие скрытых warnings/skipped-error.
7. Только затем commit → committed-diff Spark → Astra + Opus → push рабочей ветки и проверка remote SHA.
8. Куратор независимо сверяет evidence, выполняет merge/deploy, production smoke, 60 минут мониторинга и обновление обоих дашбордов. После 459 снова действует пауза до команды владельца; 460 автоматически не запускать.
