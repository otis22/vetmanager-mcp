# Этап 478.5 follow-up — агентские документы в жёстком docs-only пути

## Цель и факты

PR #50 показал, что `AGENTS.md` попадает в полный CI как неизвестный путь.
`scripts/ci_scope.py` и `scripts/ci_test_impact.py` имеют независимые явные
списки корневых документационных файлов. Сейчас три корневых инструкции
`AGENTS.md`, `AGENT_ONBOARDING.md`, `CLAUDE.md` отсутствуют в обоих списках.
478A намеренно относил первые два из них к полному контуру; это узкое
уточнение того контракта по прямому решению владельца.

## Решение и границы

Добавить ровно три имени в оба списка. Статусы `A`/`M` проходят существующую
валидацию; удаление, переименование, пустой и смешанный с неизвестным файлом
diff остаются полным контуром. В impact selector эти документы можно смешать
с изолированным инструментом без расширения owning nodes. Самостоятельный
docs-only PR пропускает product jobs через 478A scope; main пропускает их
только при успешном предыдущем main run. Никаких новых wildcard по `.md`.

Не менять бюджеты, shard map, product runtime, CI workflow, deploy scope и
права инструментов. Architecture Critique: not required — меняется только
поимённый список трёх документов в существующих классификаторах.

## Подзадачи и приёмка

1. Добавить guards для трёх имён в PR/main selector и impact selector;
   показать focused red на старом коде и green после правки.
2. Прогнать owning tests, fast, обязательные fingerprint/structure gates и
   полный default, поскольку изменён его тестовый вход. Аудит diff и
   pre-freeze/release review выполняются по workflow.
3. Обновить Roadmap и AssumptionLog с evidence, commit и push текущей ветки.

Приёмка: `A`/`M` каждого имени строго docs-only; в паре с mapped isolated
tool план остаётся isolated. Unknown root `.md`, неизвестный кодовый путь,
удаление и malformed status по-прежнему выбирают полный контур. Guards
краснеют при возврате прежнего allowlist.
