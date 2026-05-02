# Kimi CLI usage stats — md/PRD review experiment

Цель: оценить, стоит ли держать Kimi CLI в review-пайплайне для документов (PRD, AssumptionLog, README) или отказаться. Стартовала по запросу 2026-05-02.

## Лимитация Kimi CLI на 2026-05-02

`kimi --help` показывает только подкоманды `login/logout/term/acp/info/export/mcp/plugin/vis/web`. Нет `-p prompt` / `--print` / non-interactive headless mode. TUI (`kimi term`) и ACP-сервер (`kimi acp`) — единственные пути.

Stdin-piping (`echo "..." | kimi`) запускает TUI и не печатает ответ в stdout — формат не пригоден для subagent / scripting.

Программное использование требует:
- Поднять `kimi acp` в фоне как ACP server (JSON-RPC over stdio).
- Реализовать минимального ACP-клиента в скрипте (handshake → init → send prompt → drain output → close).
- Парсить ответ из protocol stream, вытащить assistant message.

Это отдельная инфраструктурная задача (~1-2 ч), не в scope per-stage workflow.

## Текущая стратегия

Пока ACP-обвязка не написана — для md/PRD-review **fallback на Claude Sonnet subagent** (`Agent` tool с моделью sonnet, неограниченное количество вызовов согласно user instruction 2026-05-02).

Стата собирается по этапам ниже. После 3 этапов — решение: писать ACP-обвязку или дропать Kimi из CLAUDE.md §3.1/§5 review policy.

## Per-stage log

| Stage | Date | PRD review by | md review by | Notes |
|-------|------|---------------|--------------|-------|
| 153 | 2026-05-02 | Claude Sonnet (subagent), Codex Spark | Claude Sonnet (Kimi headless unavailable) | Baseline run |
