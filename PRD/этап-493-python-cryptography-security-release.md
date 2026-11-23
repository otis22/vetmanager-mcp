# Этап 493. Python 3.12.16 и cryptography 50

## Цель
Закрыть четыре известных cryptography finding на принятом snapshot 492, сохранив Python 3.12, проверяемое происхождение образа и совместимость данных/rollback.

## Проверенные факты
- Checkout основан на `a85cb35db38f0d0239836c7ce546c9e26990daf9`. По заданию куратора production 492 уже выпущен и принят; Roadmap актуализирован с сохранением датированного предрелизного снимка. Перед deploy куратор сверяет переданный прежний production image ID с сохранённым release artifact и running workers.
- Прежний base GHCR digest `sha256:139b146ecf6cadf1960a88887c83846bd030bf1bc0a478fae48215c49917c075` содержит Python 3.12.15.
- Официальный ECR amd64 manifest `sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177` содержит Python 3.12.16 и OCI source `docker-library/python` revision `3d7e95597e56a415d9e4abc0f15877e005d2cb2e`.
- Локальный ECR image ID `sha256:78976a69c067520ef8be34cde307ef9f6fea6dcefa50edb57039773d241ca0db` совпал с опубликованным GHCR образом, digest `sha256:d632bda0952ef8a17cd233c1f50b987c6ea31423e9b797aad792fd8f8762e336`.
- OS Debian trixie: 87 packages до и после; пять version updates (`apt`, `ca-certificates`, `libapt-pkg7.0`, `liblzma5`, `tzdata`), ноль добавлений/удалений.
- Stage 492 использует `uv.lock` и hash exports; audit policy временно допускает четыре cryptography ID и должна стать exact zero findings после 493.

## Решение
Обновить только Python base digest и `cryptography>=50,<51`, перегенерировать universal lock/hash exports/freeze. Production и test images собирать из digest. Guard подтверждает base, lock, audit zero и чтение Fernet токена, созданного старым образом. Отдельно проверить фактические версии, OS/пакеты, `pip check`, OAuth/auth и аудит собранного production image. Старый release SHA/image ID и digest хранить в rollback manifest. Миграций нет; старый image допускается только со схемой, равной до deploy.

## Архитектурное решение и варианты
Сохраняем существующую цепочку официальный ECR amd64 digest → публичное GHCR зеркало → immutable GHCR digest в Dockerfile: прямое обращение к ECR на CI/production уже ограничено текущим процессом. Новый lock или независимый `pip install` для cryptography отвергнут: один universal `uv.lock` и hash exports позволяют проверить весь граф. Временный allowlist четырёх ID после выпуска отвергнут: scanner должен принимать ровно ноль findings. Миграция данных отвергнута, поскольку Fernet формат совместим по проверенному синтетическому ciphertext, а схему этап не меняет. Эти границы и rollback проверяются Architecture Critique в PRD review.

## Подзадачи
1. Проверить base provenance, OS drift и опубликованный GHCR digest (≤2 ч).
2. Написать красные guards для digest, exact zero audit и backward Fernet (≤2 ч).
3. Обновить lock/hash exports/freeze и собрать production/test images, проверить их фактическое содержимое (≤2 ч на каждый build).
4. На новом test image доказать focused/owning/fast green (≤2 ч на контур).
5. Выполнить working-diff review, затем default/PostgreSQL/применимый real и pinned audit (каждый контур отдельным запуском, ≤2 ч на шаг).
6. Подготовить rollback manifest и AssumptionLog, пройти committed-diff review, commit/push и handoff (≤2 ч на gate).

## Acceptance
- Python 3.12.16, cryptography major 50 и фактический OpenSSL зафиксированы из production image; неожиданный OS/package drift отсутствует.
- Четырёх старых и любых новых/unknown audit IDs нет; exact-zero guard проходит, allowlist не расширена.
- Синтетический Fernet payload, созданный `secret_manager.encrypt_secret_payload` в принятом 492 candidate image `sha256:7887ef41cb942e2acc44844248cf97010c32a4a94096b8a297d72f9c10c7851b`, читается новым `decrypt_secret_payload`; обратный token из 493 candidate читается 492 candidate для rollback. OAuth/auth tests проходят, `pip check` зелёный.
- Clean production/test builds и обязательные suite/review gates зелёные; неприменимый real подтверждён без фиктивных результатов.
- Rollback на прежний release image подготовлен без автоматического DB/host rollback и без новых миграций.

## Вне scope
Production/SSH/Secrets/Variables/services/deploy; Python 3.13; миграции БД; host maintenance 491.2.

## Оценка простоты
Только существующие lock/exports/audit guard и один совместимый Fernet test. Новых абстракций или дополнительных состояний нет.
