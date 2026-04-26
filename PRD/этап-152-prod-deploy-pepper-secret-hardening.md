# Этап 152. Prod deploy pepper secret hardening

## Цель

Закрыть high/medium findings из super-review `artifacts/review/2026-04-26-changed-stage-150-prod.md` вокруг production secret `FEEDBACK_FINGERPRINT_PEPPER`.

Production deploy должен безопасно доставлять pepper на сервер, не светить его в argv remote process, не ломать `.env` на спецсимволах и одинаково работать через GitHub Actions deploy path и private-repo `sync_and_deploy_server.sh` path.

## Контекст

Stage 149 сделал `FEEDBACK_FINGERPRINT_PEPPER` обязательным для PostgreSQL/production feedback fingerprints.
Stage 150 добавил privacy guardrails и prod deploy после этого был починен через GitHub secret.

Super-review подтвердил:

1. High: `scripts/deploy_server.sh` передаёт pepper как positional argument в `ssh ... bash -s ... "$PEPPER"` и подставляет через `sed`.
2. Medium: README не включает `FEEDBACK_FINGERPRINT_PEPPER` в список required GitHub Secrets.
3. Medium: `scripts/sync_and_deploy_server.sh` не прокидывает pepper в `deploy_server.sh`.

## Scope

1. `scripts/deploy_server.sh`
   - Не передавать `FEEDBACK_FINGERPRINT_PEPPER` как positional argv в remote `bash -s`.
   - Fail-fast требовать non-empty локальный `FEEDBACK_FINGERPRINT_PEPPER` в самом `deploy_server.sh`; эти deploy scripts являются production/PostgreSQL path, локальная разработка использует `docker compose` напрямую.
   - Передать значение отдельным SSH stdin write во временный файл на remote через случайный `mktemp` path, а не фиксированное имя.
   - Канал передачи зафиксирован явно: отдельный pre-step SSH call пишет pepper из local stdin в remote temp file; основной `ssh ... bash -s` deploy call получает только non-secret args и читает remote temp file by path. Запрещено embedding pepper в heredoc body remote script.
   - Файл создавать с `umask 077`; cleanup должен быть двойным: local `trap` вызывает remote `rm -f <tmp>` при `EXIT`/`INT`/`TERM` между SSH-вызовами, remote `trap` удаляет файл на любом exit path после deploy start. Не оставлять secret residue после interrupted deploy.
   - Remote `.env` обновлять quoting-safe способом, без `sed` replacement; запись делать атомарно через staging file + `os.replace`/`mv`, сохраняя mode/owner существующего `.env` при наличии. Staging file создаётся `0600`; перед replace выставить прежний mode/owner или `0600` для нового `.env`.
   - Reject newline/carriage-return in pepper for `.env` safety.
   - Пока pepper находится в памяти/файле, deploy path не включает shell tracing: не использовать `set -x`, `bash -x`, `PS4`/debug echo; writer не печатает value, length, hash или derived material в stdout/stderr.
2. `scripts/sync_and_deploy_server.sh`
   - Forward `FEEDBACK_FINGERPRINT_PEPPER` в `deploy_server.sh` тем же env contract, что GitHub Actions.
   - Если env var не задан, fail-fast до запуска deploy с понятным сообщением: для production/PostgreSQL нужно передать `FEEDBACK_FINGERPRINT_PEPPER`; не продолжать молча в надежде на remote `.env`.
3. README
   - Добавить `FEEDBACK_FINGERPRINT_PEPPER` в required GitHub Secrets.
   - Добавить private-repo rsync instruction: export `FEEDBACK_FINGERPRINT_PEPPER` перед запуском; documented rsync deploy path должен быть fail-fast при отсутствии env var.
4. Tests
   - Static regression tests для deploy scripts:
     - pepper не встречается как отдельный аргумент remote `bash -s`;
     - нет `sed -i` для `FEEDBACK_FINGERPRINT_PEPPER`;
     - есть temp-file/stdin transport и cleanup;
     - есть quoting-safe writer;
     - writer rejects newline/CR;
     - writer сохраняет parser-safe `.env` round-trip для `&`, `|`, `\`, `/`, quotes, `#`, `$`, leading/trailing spaces, `=`;
     - writer использует atomic temp file + `mv`, а не in-place partial write;
     - writer сохраняет mode/owner существующего `.env` или создаёт новый `.env` как `0600`;
     - deploy scripts не содержат `set -x`, `bash -x`, `printenv FEEDBACK_FINGERPRINT_PEPPER`, `echo "$FEEDBACK_FINGERPRINT_PEPPER"` и не печатают derived secret material;
     - `sync_and_deploy_server.sh` forwards `FEEDBACK_FINGERPRINT_PEPPER`.
   - Executable integration-style tests with mocked `ssh`/fake remote:
     - direct `deploy_server.sh` path writes `.env` safely and cleans temp file on success;
     - interrupt/failure between pre-step upload and main deploy triggers local cleanup of remote temp file;
     - forced failure path still removes temp file;
     - interrupted/failed writer path leaves original `.env` valid;
     - `sync_and_deploy_server.sh` forwards the same pepper contract into `deploy_server.sh`.

## Out of Scope

- Ротация уже сохранённых feedback fingerprints.
- Изменение значения GitHub secret.
- Изменение схемы БД.
- Полная унификация deploy scripts в один shared library.

## Acceptance Criteria

1. `scripts/deploy_server.sh` больше не содержит `FEEDBACK_FINGERPRINT_PEPPER_ARG` и не передаёт pepper в `ssh ... bash -s` аргументах.
2. `scripts/deploy_server.sh` fail-fast требует non-empty `FEEDBACK_FINGERPRINT_PEPPER` до SSH/deploy work; локальный/dev режим не использует deploy scripts.
3. `scripts/deploy_server.sh` доставляет pepper отдельным SSH pre-step stdin write в random `mktemp` file `0600`; основной `ssh ... bash -s` deploy call не содержит pepper в argv или heredoc body.
4. `scripts/deploy_server.sh` обновляет `.env` без `sed`, атомарно, сохраняет mode/owner или создаёт новый `0600`, и корректно работает с `&`, `|`, `\`, `/`.
5. Newline/CR в pepper reject'ится до записи `.env`; остальные символы round-trip'ятся в `.env` без shell/sed corruption.
6. Temp file удаляется через local cleanup trap между SSH calls и remote cleanup trap на success/error/interrupted remote script path.
7. `scripts/sync_and_deploy_server.sh` fail-fast требует non-empty `FEEDBACK_FINGERPRINT_PEPPER` и прокидывает его безопасным contract.
8. README содержит `FEEDBACK_FINGERPRINT_PEPPER` в required GitHub Secrets и rsync+deploy notes.
9. Targeted deploy script tests включают static checks и executable mocked/fake-remote checks для direct deploy path и rsync wrapper path.
10. Full Docker suite проходит.
11. Committed diff проходит Spark review и стороннее review.
12. Production deploy проходит; проверяется `/healthz` и non-secret evidence, что running container содержит именно переданный pepper: до удаления temp secret file remote script сравнивает `docker compose exec -T mcp sh -c 'test "$FEEDBACK_FINGERPRINT_PEPPER" = "$(cat /run-or-tmp-pepper-file)"'` эквивалентом с exit code only. Запрещены `env`, `printenv`, `echo`, length/hash/first-N-char probes и любой вывод значения или derived secret material.

## Decomposition

- 152a PRD/review gates. ≤2h.
- 152b Deploy script non-argv pepper transport + safe `.env` writer. ≤150 LOC.
- 152c Sync deploy wrapper + docs. ≤150 LOC.
- 152d Regression tests. ≤150 LOC.
- 152e Full checks, reviews, commit/push/deploy, AssumptionLog. ≤2h.

## Simplicity Rationale

Не добавляем новый secrets manager или отдельный remote bootstrap протокол. Минимальный практичный фикс: локальный deploy script передаёт secret через stdin в временный файл `0600`, затем remote script обновляет `.env` через Python writer. Это закрывает argv leak и `sed` metachar risk без широкой перестройки deploy pipeline.
