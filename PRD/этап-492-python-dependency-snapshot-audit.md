# Этап 492. Python dependency snapshot и регулярный audit

## Цель

Зафиксировать единый разрешённый граф Python зависимостей с hashes для production и test, исключить самопроизвольный дрейф сборок и ежедневно проверять фактический production набор пакетов на известные уязвимости без автоматической установки обновлений.

## Проверенные исходные факты

- `Dockerfile` ставит production requirements в `base`, затем отдельно обновляет `anyio` в `production` и `test`; test добавляет ещё один набор пакетов. `pyproject.toml` содержит более широкие верхние границы, в частности для `cryptography`.
- Текущий digest base image содержит Python 3.12.15; существующий локальный production image содержит `cryptography 46.0.7`. GHCR manifest данного base digest только `linux/amd64`.
- `nightly.yml` уже запускается по расписанию на main и собирает test image. Отдельный audit workflow должен читать `pip freeze --all` из **работающего production контейнера** по выделенному read-only SSH доступу с forced command. В scheduled audit job не доступны ни deploy SSH key, ни иные write-capable production credentials: единственный SSH secret — выделенный read-only key. До предоставления такого доступа job падает явно и этап не считается готовым к приёмке. Локальная сборка проверяется отдельно. Audit не меняет production.
- Roadmap уже содержит решение владельца временно принимать прежние четыре проблемы `cryptography` до 493. Точные IDs подтверждены повторным сканом локального образа и чистого candidate image: `PYSEC-2026-3552`, `PYSEC-2026-3553`, `PYSEC-2026-3554`, `GHSA-537c-gmf6-5ccf` при `cryptography==46.0.7`. Исходный JSON 491 в checkout не найден; поэтому первичный источник точных IDs ограничен этими двумя снимками. Дополнительные advisory требуют разбора.

## Архитектурное решение

- `uv.lock` — единый universal dependency snapshot для заявленного `requires-python >=3.11`; production/test exports строятся из него для фактической Python 3.12 и поддерживаемой архитектуры `linux/amd64`, содержат точные версии и все предоставленные upstream hashes. Синхронизация экспорта с lock проверяется сторожем. Сборки на Python 3.11 или иной архитектуре не заявляются до отдельной проверки.
- Docker stages ставят только hash-экспорты через `pip --require-hashes`; отдельный `anyio` install удаляется. Все прямые production/test ограничения живут в `pyproject.toml`: добавить имеющиеся только в Docker `fakeredis` и `ruff` в dev group, добавить `pytest-httpx` в test image через export, включая верхнюю границу `cryptography<47` до 493. APT/browser binaries test stage находятся вне Python lock; их дрейф явно остаётся и не заявляется устранённым этим этапом.
- Scan выполняется из отдельного процесса сканера по файлу `pip freeze --all`, снятому по выделенному read-only SSH доступу с каждого работающего worker. Список workers получает из Compose inventory, а не из захардкоженного количества; все действующие экземпляры обязательны, package sets и image ID совпадают. Версия сканера и его зависимости ставятся из hash-pinned audit export того же `uv.lock`, с guard синхронизации. JSON package/version сверяется с freeze; package/version/advisory ID сверяются с поимённой policy. Фактический production freeze сравнивается с сохранённым `production-installed.txt`: до deploy 492 audit будет красным по ожидаемому drift. Новые findings публикуются и блокируют gate; никаких `--ignore-vuln`. Сканер не устанавливается в production image.
- Временное принятие прежних четырёх `cryptography` IDs истекает по фиксированной дате 22.12.2026; это консервативная граница независимо от даты merge. Этап 493 обязан заменить эту policy при выпуске нового образа. Если 493 задержан после даты, gate красный и требуется явное решение владельца.
- Дневной регулярный CI audit на main выдаёт artifact и summary; update/deploy не выполняет. Политика — временное принятие конкретных findings для 492, не security remediation.

## Подзадачи

1. 492.1a: зафиксировать требования и universal lock, два hash-экспорта и сторож синхронизации/полноты. ≤150 строк кода.
2. 492.1b: перевести Dockerfile на hash-only install, убрать независимый anyio install, проверить фактические `pip freeze`, `pip check`, clean production/test builds на целевых архитектурах. ≤150 строк кода.
3. 492.2a: реализовать audit wrapper, pin сканера и политику exact known findings, доказать red на новом finding, пустом/битом скане и drift. ≤150 строк кода.
4. 492.2b: добавить расписание CI, evidence, документацию запуска/rollback, провести применимые gates. ≤150 строк кода.

## Приёмка

- Один lock разрешает полный граф production и test; оба экспорта получены из него, содержат hashes, не расходятся с lock и не допускают незакреплённые установки. Установка с изменённым hash падает.
- Чистые builds и фактические пакеты production/test совпадают со snapshot, `pip check` успешен. Указаны проверенные Python ABI/архитектуры; неподдерживаемые не заявляются.
- Audit запускается на фактическом production image, версия сканера закреплена. Машинный результат сохраняет все findings; новые, неизвестные или изменённые findings блокируют gate. Пустой/ошибочный ответ не интерпретируется как clean.
- Регулярный CI не выполняет production update, deploy или OS scan. Известные findings раскрыты с ограничением применимости Python audit.
- Focused red/green, fast/default и применимый real aggregate, pre-review/committed review, clean build evidence и self-attestation пройдены по workflow.

## Вне объёма

- Этап 493, смена base image/Python/cryptography major, host APT и любые production writes/deploy/restart.
- Автоматическое исправление findings и полный host/container/OS security scan.

## Простота

Используются встроенные `uv lock/export`, `pip --require-hashes` и один узкий проверяющий скрипт. Audit export строится из того же lock; нового runtime пакета или второго lock нет.
