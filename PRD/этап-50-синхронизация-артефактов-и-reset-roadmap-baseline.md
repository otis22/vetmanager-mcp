# PRD: Этап 50 — синхронизация артефактов и reset roadmap baseline

## Контекст

После завершения этапов `1–49` код и `README.md` уже описывают bearer-only
сервис с web-контуром аккаунтов, хранением Vetmanager integration на уровне
аккаунта, выпуском Bearer-токенов и production/browser verification.

При этом часть управленческих и справочных артефактов отстаёт:
- `Roadmap.md` до этапа 49 закрыт полностью, но не содержит новой baseline-точки
  для следующего цикла планирования;
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` местами всё ещё
  содержит legacy headers-only формулировки (`X-VM-Domain` /
  `X-VM-Api-Key`);
- `artifacts/prd-vetmanager-mcp-ru.md` нужно актуализировать под текущее
  product/runtime состояние после web/bearer этапов.

Этап 50 нужен как короткий artifact-only этап без продуктовой разработки:
сначала выровнять source-of-truth документы, затем от этой точки планировать
следующие этапы.

## Цель

- зафиксировать единый baseline проекта после этапов `1–49`;
- убрать явные противоречия между `README.md`, `Roadmap.md`, `AssumptionLog.md`
  и `artifacts/*`;
- подготовить чистую точку входа для нового roadmap-цикла.

## Ограничения

- этап не должен менять runtime-контракт, storage-схему или бизнес-логику;
- изменения ограничены управленческими и справочными артефактами;
- синхронизация должна опираться на фактическое состояние кода и уже
  завершённые этапы roadmap, а не на новые неподтверждённые предположения.

## Декомпозиция

### 50.1 Аудит рассинхронов

- сверить `Roadmap.md`, `README.md`, `AssumptionLog.md`, `PRD/` и
  `artifacts/*`;
- зафиксировать только подтверждённые рассинхроны;
- выделить документы, которые уже актуальны, и документы, требующие правки.

### 50.2 Baseline фиксация

- определить, что считается текущим baseline после этапов `1–49`:
  bearer-only runtime, web account console, two Vetmanager auth modes,
  observability, production verification;
- зафиксировать этот baseline в справочных артефактах.

### 50.3 Обновление справочных артефактов

- привести `artifacts/prd-vetmanager-mcp-ru.md` к фактическому продуктовому
  состоянию;
- привести `artifacts/technical-requirements-vetmanager-mcp-ru.md` к
  фактическому runtime и deployment состоянию;
- удалить или переписать legacy headers-only формулировки, которые больше не
  соответствуют коду.

### 50.4 PRD этапа 50

- завести отдельный PRD-файл этапа 50;
- сохранить в нём scope этапа как artifact-only, без скрытых кодовых задач.

### 50.5 Финальная фиксация

- обновить `AssumptionLog.md`;
- закрыть этап 50 в `Roadmap.md`;
- зафиксировать новый baseline как отправную точку для этапа 51+.

## Критерии готовности

- `Roadmap.md` содержит завершённый этап 50;
- для этапа 50 существует отдельный PRD;
- `artifacts/prd-vetmanager-mcp-ru.md` и
  `artifacts/technical-requirements-vetmanager-mcp-ru.md` не противоречат
  текущему bearer-only/web состоянию проекта;
- `AssumptionLog.md` содержит отдельную запись с итогами синхронизации и
  зафиксированным baseline после этапа 49.
