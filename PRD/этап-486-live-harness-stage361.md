# Этап 486. Проверяемый live harness stage361

## Цель и исходные факты

Разблокировать strict real gate, устранив диагностические пробелы test-only harness. Controlled probe на devtr6 API-key: PUT HTTP 201, JSON `success=true`; независимый fresh GET подтвердил точный probe через 206,4 мс; restore HTTP 201, `success=true`, baseline подтверждён. Прежний failure не воспроизведён; задержка upstream не доказана. Evidence остаётся в приватном каталоге, без raw description и PII в репозитории.

## Архитектурное решение

Проблема: старый тест подменяет неизвестный HTTP код строкой `http_success`, выбирает первую подходящую карту, читает и пишет одним клиентом и допускает прогрев MCP cache прямым GET. Изменяется только real-only test и его offline guards. Используется конкретная синтетическая карта devtr6 с зафиксированным SHA-256 baseline и проверенным контекстом записи; при несовпадении останов до PUT. Точный baseline не очищается от чужих markers, probe добавляется один раз и restore возвращает исходный байтовый текст.

Существующий `VetmanagerClient.last_response_status_code` даёт фактический HTTP, JSON `success` проверяется как `True` строго по типу. Для прямого read-back создаётся независимый client; `fresh=True` и точный hash являются oracle наблюдаемого ответа API, без предположений о внутренних слоях upstream. MCP вызывается до прямого read-back, чтобы не использовать прогретый cache как доказательство. Bounded poll до 60 секунд фиксирует время каждого GET и hash, не превращается в бесконечный скрытый retry. `try/finally` охватывает PUT и последующие проверки. Restore выполняется только при точном hash probe и неизменности всех полей контекста из PUT; точный hash baseline после restore обязателен. При чужом состоянии запись не перезаписывается. После аварийного завершения процесса отдельная read-only проверка обязательна перед любой новой записью. Печать только технических флагов, кодов, длительностей и SHA.

Вариант одного клиента и одного GET проще, но не обнаруживает общий cache и не позволяет отличить краткую невидимость записи. Отдельный raw HTTP стек дал бы лишний обход существующей аутентификации и security boundary. Production runtime и публичный контракт MCP не меняются. При изменении синтетического baseline/context harness останавливается до записи; владелец devtr6 подтверждает новый синтетический baseline, исполнитель сохраняет приватный read-only evidence с HTTP/JSON, hash и контекстом, после чего guard обновляется отдельной задачей. Architecture Critique: not required — изменяется лишь test-only real harness, без auth, storage, API, production или нагрузочного контракта.

## Приёмка и декомпозиция

1. Offline guards показывают red на старом harness для baseline/context, фактических HTTP/JSON, независимого клиента, bounded poll и hash restore; затем green. Каждая подзадача ≤150 строк.
2. Focused guards и owning file зелёные; real-only fingerprint оставляет default/PostgreSQL неизменными. Проверить inventory, Roadmap и review validator.
3. Полный pre-freeze review рабочего diff: Spark candidate, Astra и Kimi K3; обязательные findings закрыть и повторить затронутые проверки.
4. Один штатный focused stage361 на devtr6 с restore; при красном остановить серию. При зелёном — свежие real группы последовательно и strict aggregate по manifest на свободном хосте. Зелёный gate не устанавливает причину прежнего failure. Не создавать дополнительные StartReport вне штатных тестов, существующие jobs не дублировать.
5. Только после полностью зелёных gates — commit, committed-diff Spark/Astra/Kimi и push. PR, merge, deploy и monitoring — куратор. Production не трогать.
