## Цель этапа 46

Провести архитектурное ревью текущего состояния `vetmanager-mcp` и перевести
наблюдения в управляемый backlog рефакторинга без немедленного переписывания
критических модулей.

## Область ревью

- web/runtime/security/storage контуры
- Vetmanager client и connection lifecycle
- tool registration и tool module organization
- test architecture и стоимость поддержки suite
- наблюдаемость, deploy и operational hooks как часть общей архитектуры

## Подзадачи

### 46.1 Модульные границы
- Зафиксировать текущие bounded contexts:
  - web
  - auth/runtime auth
  - storage
  - client
  - tools
- Описать точки пересечения и места утечки ответственности между слоями.

### 46.2 Дублирование и неявные контракты
- Найти повторяющиеся helpers, patterns и implicit contracts.
- Выделить места, где API между модулями держится на договорённости, а не на явном contract.

### 46.3 Связность и hotspots
- Отметить крупные/high-churn модули.
- Зафиксировать зоны, где изменение одной функции рискованно тянет несколько слоёв.

### 46.4 Test architecture
- Описать текущую test pyramid.
- Зафиксировать стоимость default/browser/real contours и зоны дублирующего покрытия.

### 46.5 Prioritized backlog
- Сформировать список рефакторингов по приоритету и риску.

### 46.6 Quick wins vs long-term
- Отдельно пометить:
  - quick wins
  - medium refactors
  - long-term structural refactors

### 46.7 Артефакты
- Добавить architecture review artifact.
- Добавить debt register artifact.
- Синхронизировать Roadmap и AssumptionLog.

## Критерии готовности

- В репозитории есть отдельный architecture review artifact.
- В репозитории есть отдельный prioritized debt register.
- В backlog есть разделение на quick wins и long-term refactors.
- Этап 46 закрыт без неявных “надо когда-нибудь” формулировок.
