# PRD — Этап 213: синхронизация статусов Roadmap и PRD

## Статус

Done — documentation-only reconciliation of current project-management
artifacts.

## Цель

Устранить подтверждённые расхождения между `Roadmap.md` и PRD, чтобы статус
этапа не сообщал незавершённую работу там, где MCP-scope уже закрыт, и не
скрывал внешний upstream blocker.

## Проверенные факты

- В Roadmap этап 172 содержал пять `done` подзадач и одну осознанно остановленную
  `172.3`: real API отклоняет `intent_text` длиной 1001 при upstream limit
  `1000`; MCP не может безопасно изменить этот контракт самостоятельно.
- Этап 198 в Roadmap отмечен `done`, deployed и smoke-verified, однако PRD
  этапов 196/197/199 всё ещё называл его `todo`.
- Roadmap этапа 201 фиксирует completed production rollout, тогда как его PRD
  оставался `in_progress`.
- Этап 211 завершён только в MCP-scope: `211.2` остаётся `stop` до внешнего
  ответа Vetmanager о machine-readable queue/export contract.
- Полный поиск явных status cross-references дополнительно нашёл устаревшее
  утверждение PRD 163, что Stage 162 ещё не завершён; Roadmap фиксирует `done`.
  Historical transition в PRD 86 и generic правило PRD 165 также приведены к
  нейтральной формулировке, чтобы механическая проверка не смешивала их с
  текущими status claims.

## Декомпозиция

1. Сопоставить заголовки Roadmap с явными статусами и status cross-references
   всех PRD. ≤2 ч.
2. Обновить только подтверждённые текущие claims, сохранив historical evidence
   и внешние blockers. ≤150 строк.
3. Проверить Markdown diff и workflow completion checker. ≤2 ч.

## Архитектурное решение

Architecture Critique: not required — задача меняет только документацию и не
затрагивает runtime, API/MCP contract, auth, storage или production behavior.

`Roadmap.md` остаётся единственным источником очереди. Закрытый MCP-scope
помечается `done` только когда все локально управляемые результаты завершены;
недоступный внешний контракт сохраняется как явно названный backlog/blocker,
а не переводится в фиктивный `done`.

## Acceptance criteria

1. Этап 172 отмечен `done` только с явным внешним blocker `intent_text=1000`.
2. PRD 196/197/199, 201 и 163 не противоречат текущему Roadmap.
3. Этап 211 явно отличает завершённый MCP-scope от остановленной `211.2`.
4. Полный scan явных status cross-references не находит новых текущих
   противоречий.
