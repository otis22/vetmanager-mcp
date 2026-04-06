# PRD: Этап 58 — Dependency pinning и security hardening

## Цель
Закрепить воспроизводимость сборки и убрать оставшиеся security debt items.

## Подзадачи

### 58.1 Upper bounds зависимостей в Dockerfile
- Добавить верхние границы к pip install (fastmcp<3, httpx<1, etc.)
- Предотвращает неожиданные breaking changes при rebuild

### 58.2 CSP style-src
- 41 inline style="" атрибут в landing_page.py и web.py
- Полное удаление unsafe-inline требует рефакторинга всех стилей в CSS-классы
- Решение: добавить style nonce для `<style>` блоков, inline `style=""` оставить (документировать)
- Альтернатива: добавить upgrade-insecure-requests и закрыть задолженность частично

### 58.3 upgrade-insecure-requests
- Добавить в CSP для production (когда HTTPS включён)

### 58.4 Security threat model
- Обновить AssumptionLog
