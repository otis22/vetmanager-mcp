# Review этапа 461 — 16.11.2026

Объект: PRD/Architecture Critique и рабочий diff этапа 461 на базе `cc6bcae74f3bec9bd1e44248d520832d7a3880af`. Исходный факт — один существующий upstream job с `failed/PREVIEW_FAILED/error_subtype=OTHER`; внутренний подкласс ошибки неизвестен. Evidence ревью: `/home/otis/.local/share/vetmanager-mcp-review-evidence/stage461-train-20261116/`.

## Сведение проверенных замечаний

| Область | Проверка и итог |
|---|---|
| Code, architecture | Узкая ветка exact subtype добавлена после более безопасного известного дефекта комбинаций и до retry-эвристик. Владельцем preview failure обозначен upstream; MCP отвечает только за безопасную аннотацию. |
| Simplicity | Новый публичный инструмент и автоматический агрегатор не вводятся. Резервный расчёт остаётся ручным workflow через существующий `get_invoices`. |
| Docs, product | Spark PRD выявил неполный `totalCount` и неполный список филиалов; оба исправлены полным keyset scan и группировкой по `clinic_id`. Нулевые/отрицательные проведённые счета согласованы с `get_revenue_summary(mode=invoiced)`. |
| Security, privacy | Текст `error_message_safe` продолжает удаляться; SQL, intent и строки клиники не сохраняются. Прямое чтение требует `finance.read`; иной метрике сумма счетов не подставляется. |
| Performance, reliability | Повторный StartReport для `OTHER` запрещён, `safe_to_retry=false`. Keyset использует `offset=0`, проверяет `totalCount` и прекращает расчёт при расхождении. |
| Observability | Задание не добавляет логирование сырого upstream ответа и новые метрики с произвольными labels. Для эскалации остаются только структурированные коды и ID job. |
| Tests, blindspot | 4 focused red на исходном коде; 4 ранее красных узла отдельно стали green. Управляемые мутации условия выручки и raw `id`-фильтра дали красные сторожа. Публичный тест проверяет сохранение status/date фильтров на второй странице. |

Pre-review рабочего diff: Spark 1 и 2 — `[]` с прочитанными файлами. Astra 1 нашла medium об опасной универсальной подсказке про счета; Opus 1 нашёл medium о непроверенном сочетании фильтров на второй странице. Оба приняты и исправлены. Astra 2 и Opus 2 — валидные `findings=[]`; общих и незакрытых critical/high нет. Детали verdict, metadata и пути Claude envelope записаны в `AssumptionLog.md`.

Полный default исходного test fingerprint прошёл (4835 passed). Первый real aggregate выявил ошибку test harness stage 399: первая запись клиента не обязана иметь `city_data`. Тест теперь выбирает запись с этой связью и проверяет все режимы на одном ID; focused real и fast после правки зелёные, отдельный Spark scout дал `findings=[]`. Для нового test fingerprint полный default и real aggregate подлежат самостоятельному завершению. Committed-diff gate и push фиксируются в `AssumptionLog.md` после фактического результата; этот отчёт не заменяет эти гейты.

## Final pre-freeze gate после изменения workflow

Куратор подтвердил exit 0 оставленного real runner через `docker wait`; counts wrapper не сохранил, поэтому в отчёте их нет. Runtime/real-only входы после этого не менялись. Детерминированная collection текущего default: 4835 nodes, inventory совпадает, fingerprint `3c482344c3ac0a4df078369d8be37d7b1037ec1bbe78c823cc000f7d8f76de36`. Spark прочитал 20 файлов, `[]`. Astra valid `[]`; Opus valid с двумя medium, общих findings нет. Оба medium проверены и признаны non-blocking документационным долгом: противоречие формулировок контурной инвалидации и формат заголовка записи 461. Они назначены Roadmap 470; по указанию владельца workflow/fingerprint внутри 461 не меняются. Release blockers нет. Полный default на текущем общем fingerprint и committed-diff gate ожидают фактического результата.

## Закрытие default gate

Первый полный default после добавления Roadmap 470 остановился на одном структурном тесте: закрытый 450 вышел из окна 20 номеров. Куратор штатно архивировал 450, проверил структуру и отдельно получил green ранее красного узла. Повторный полный default на неизменных runtime/tests: exit 0, **4835 passed**, 146 deselected, coverage 89 %; complete manifest содержит 4835 узлов и текущий fingerprint `3c482344c3ac0a4df078369d8be37d7b1037ec1bbe78c823cc000f7d8f76de36`, его verifier exit 0. Evidence `stage461-train-20261116/default-after-archive.{log,exit.txt}` и `default-after-archive-verify.{log,exit.txt}`. Открытых release blockers нет. Committed-diff review и push фиксируются после их фактического завершения.

Первый committed-diff release-review SHA `f1ea5f1e7f20e97b2d86c1a41e788ac9ab4a3553`: Spark, Astra и Opus дали валидные `findings=[]`; release blockers 0. Пути evidence и metadata — в `AssumptionLog.md`. Запись этих итогов является docs-only follow-up; окончательный SHA проверяется отдельным вторым раундом перед push.
