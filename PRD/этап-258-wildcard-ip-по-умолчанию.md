# Этап 258. Любой IP по умолчанию

## Цель

Пустая IP-маска ручной формы выпускает токен с явной маской `*.*.*.*`, а
ограничение IP остаётся явной, доступной опцией.

## Архитектурное решение

В web route пустое поле нормализуется к wildcard; `confirm_wildcard_ip` и
серверная проверка этого checkbox удаляются. Контракт service остаётся явным:
он принимает непустую строку и сохраняет `*.*.*.*`, а warning в
`issue_service_bearer_token` остаётся. Это сохраняет защиту этапа 155 от
неявного NULL/wildcard: теперь wildcard — осознанная product-норма и всё ещё
записан в БД, логах и UI. Риск — новый токен без IP restriction можно
использовать с любого адреса при компрометации; компенсация — секретность
Bearer-токена, видимый выбор ограниченной маски и operator warning-log.
Rollback: вернуть request-IP fallback и confirmation check.

Architecture Critique: required (authentication/public behavior).

## Декомпозиция

1. Нормализовать пустую mask и удалить wildcard-confirm path, ≤80 LOC.
2. Добавить route/UI regressions, ≤100 LOC.
3. Полный suite и аудит.

## Acceptance criteria

- Пустой ручной `ip_mask` сохраняется как `*.*.*.*`.
- Никакой `confirm_wildcard_ip` не обязателен и не рендерится.
- Specific mask передаётся без изменения.
- Warning лог wildcard сохраняется.
