# Этап 334. Миграция 332 без отпечатков у KI-45 и репорта #80

## Цель

Довести supervisor-миграцию этапа 332 до проверенного production-состояния,
когда и KI-45, и репорт #80 имеют `error_fingerprint_hash=null`: создать для
#80 отдельную rule-only известную проблему, безопасно повторять применение и
полностью откатывать его без попыток переноса или сверки отпечатков.

## Проверенные факты и ограничения

- Первый supervisor apply 19.09.2026 в 13:28 сохранил неизменяемый before-state
  `stage-332/ki45-before.json`: KI-45 имеет `error_fingerprint_hash=null`,
  `related_tool=null`, статус `workaround_available`, правила и плейбук v1.
- Второй apply 19.09.2026 в 15:43 на `fcbc77f` завершился с exit 65 до мутаций:
  read-only CLI показал `error_fingerprint_hash=null` у репорта #80. Связь #80
  с KI-45 возникла по текстовому правилу `getting report export file failed`.
  Следовательно, предпосылка этапов 332/333 о переносе или сверке отпечатка #80
  целиком ложна.
- Агент не обращается к production, не меняет production DB/`known_issues` и
  не перезаписывает существующий `ki45-before.json`. Применение делает только
  супервизор после зелёного Deploy Prod.
- Фикстуры этапа 332 остаются источником правил и плейбука download-401.
  Главный PRD требует понятной обработки upstream-ошибок, а technical
  requirements — воспроизводимого rollout/rollback без секретов.

## Scope и декомпозиция

### 334.1 — test-first сторожа `null/null` (≤150 LOC)

1. Расширить fake-SSH harness третьим исходным состоянием: KI-45 `null`, report
   #80 `null`; проверить цепочку apply → retry → rollback → re-rollback →
   re-apply и неизменность before-state.
2. Доказать красным, что target создаётся rule-only с `null` fingerprint,
   получает fixtures, `related_tool=get_report_export_download`, статус
   `workaround_available`, а #80 связан именно с target; `move-fingerprint` и
   fingerprint-сверки в этой ветке отсутствуют.
3. Сохранить fail-closed сторожа для одностороннего fingerprint, чужой ссылки
   #80, неверной identity/status цели и live drift KI-45.

### 334.2 — минимальная миграционная правка (≤150 LOC)

1. Разобрать пару исходных значений до первой записи. Допустить только
   согласованные состояния `present/present` с равными значениями (контракт
   333) и новое `null/null`; отклонить `present/null`, `null/present` и разные
   значения.
2. Для `null/null` вызвать существующий `promote 80`: он создаёт target с
   `error_fingerprint_hash=null`, правилами/плейбуком download-401 из fixtures
   и `related_tool=get_report_export_download`. Не вызывать
   `move-fingerprint` ни вперёд, ни назад и не требовать отпечаток у target.
3. Перед `promote` атомарно создать отдельный marker
   `stage-332/download-401-migration-state.txt` со значением
   `stage334-null-null-v1:prepared` рядом с существующим
   `download-401-known-issue-id.txt`; иной/пустой marker отклонять. Сразу после
   успешного `promote` разобрать target ID, атомарно заменить marker на
   `stage334-null-null-v1:target:<id>` и сохранить тот же ID в отдельном файле,
   до следующих команд. Marker с target ID — источник восстановления при
   утрате отдельного файла. Обрыв не должен порождать дубль: `prepared` +
   `#80→45` означает, что атомарный `promote` не состоялся, и разрешает повтор;
   `prepared` + `#80→candidate` требует полной identity-проверки candidate,
   после чего оба файла получают его ID. Любое другое сочетание, неверный
   marker или непроверенная цель останавливает apply и rollback. До изменений KI-45
   проверять target по `id`, точному `title`, `related_tool`, `status`,
   `fingerprint=null`, точным fixtures и read-only связи #80.
4. Явная матрица rule-only target/link: apply принимает
   `workaround_available/target` (готово), `wontfix/45` (после rollback) и
   `wontfix/target` (обрыв между link и реактивацией); rollback принимает
   `workaround_available/target`, `wontfix/target` и `wontfix/45`. Все прочие
   пары, включая активную цель без ссылки #80, отклоняются. Apply сначала
   перелинковывает #80, затем реактивирует target; rollback сначала ставит
   `wontfix`, затем возвращает ссылку KI-45, поэтому любой промежуточный
   `wontfix/target` восстанавливаем выбранным режимом.
5. Rollback восстанавливает все семь полей KI-45 из before-state, переводит
   target в `wontfix` и перелинковывает #80 на KI-45. Повторный rollback и
   последующий re-apply идемпотентны.

### 334.3 — проверки и доставка (≤2 ч)

1. Выполнить focused Red/Green, ShellCheck v0.9.0, `bash -n`, локальный live
   CLI на SQLite для `null/null`, затем аудит.
2. После всех review-правок один раз выполнить полные mock и real suite на
   финальном code SHA; сохранить log/exit/SHA в evidence `stage-334`.
3. Commit без префикса `Stage 334:`, Spark и ревью сторонней моделью committed
   diff, push, Tests и Deploy Prod. После подтверждённого supervisor apply
   записать production completion, оставить 332 `supervisor_pending`, закрыть
   334, архивировать окно и сделать commit `Stage 334: record production completion`.

## Архитектурное решение

Сохраняется orchestration в supervisor-скрипте и существующие CLI-команды.
`promote` уже наследует nullable fingerprint репорта и атомарно создаёт target
со ссылкой #80; поэтому новая DB-команда или искусственный отпечаток не нужны.
Скрипт классифицирует исходную пару один раз и в `null/null` использует identity
и ссылку отчёта как единственную причинную привязку target. Ветка с двумя
одинаковыми отпечатками сохраняет поведение 333; смешанные состояния остаются
ошибкой.

Rollback не удаляет запись: восстановление snapshot, `wontfix` и обратная
ссылка повторяемы и сохраняют аудит. Несколько CLI-команд не образуют общую
транзакцию, поэтому каждый завершённый шаг проверяется по текущей identity и
может быть безопасно повторён. Architecture Critique совмещается с первым
сильным PRD-review из-за изменения production migration behavior.

## Acceptance criteria

- Новый fake-SSH сценарий `null/null` красным ловит старый отказ, затем зелёным
  проходит apply/retry/rollback/re-rollback/re-apply без `move-fingerprint`.
- После apply target имеет `fingerprint=null`, точные identity/status/fixtures,
  а #80 связан с target; после rollback KI-45 равна всем семи полям snapshot,
  target `wontfix`, #80 снова связан с KI-45.
- Односторонние отпечатки, разные отпечатки, недопустимая target/status/link
  пара, неверные identity/fixtures цели и drift KI-45 отклоняются до
  последующих изменений. Retry проверяет KI-45: до первого target она обязана
  совпадать со всеми семью полями snapshot; после его появления допустимы
  только snapshot либо точная конфигурация KI-45 из fixtures с остальными
  identity-полями snapshot и `fingerprint=null`.
- Fault-injection после `prepared` marker, между успешной DB-транзакцией
  `promote` и сохранением ID, после сохранения ID, изменения KI-45, link, mark
  и restore доказывает, что следующий apply либо rollback безопасно продолжает
  явную матрицу без дубля, а неожиданное состояние не перезаписывается.
- Локальная live CLI-проверка SQLite подтверждает nullable promote/link;
  ShellCheck, `bash -n`, focused, mock, real и CI зелёные, evidence сохранён.
- 334 закрыт как `done`; 332 остаётся `supervisor_pending` до отдельного решения
  владельца после применения миграции.

## Out of scope

- Обращения агента к production host/DB и любые правки production
  `known_issues`.
- Перезапись `stage-332/ki45-before.json`.
- Изменение matcher, схемы БД, публичного MCP-контракта или fixtures этапа 332.
- Искусственное создание отпечатка из текста репорта.

## Оценка простоты

Правка остаётся одной веткой в существующем supervisor-скрипте и расширением
его harness. Новых абстракций, CLI-команд и dual API нет; затрагиваются только
PRD, тест скрипта, сам скрипт и обязательные управленческие артефакты. Более
простой вариант — снять fingerprint-проверки для всех состояний — нарушил бы
fail-closed контракт 333, поэтому отклонён.
