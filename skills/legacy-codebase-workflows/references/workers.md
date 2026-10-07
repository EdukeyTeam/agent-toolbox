# Bounded workers and source verification

Delegate independent inventory/documentation scopes when the handoff costs less than repeatedly reading the code yourself. Avoid delegation for a question answerable by one search. An inexpensive capable model, for example GPT 6 Luna when available, can inventory modules; a stronger coordinator, for example GPT 6.1 Sol, reconciles evidence and decides the change. Model names are examples, not provider requirements or permission to send private source to a cloud service.

Split by coherent boundaries: entry points/configuration, domain behavior, persistence, integrations, UI or internal framework modules. Give workers disjoint write locations when they create documentation. Assign cross-module reconciliation to the coordinator; do not assume separate summaries cover their interactions.

## Worker prompt

Adapt the file and output budgets to the module instead of imposing one global number.

```text
Investigate <module> in <repository> at <revision> for <question>.
Read the scoped inventory/map, then original definitions and callers.
Stay within <paths>; report external dependencies and sources you need.
Budget: <source-reading budget> and <summary output budget>.
Do not change application code or run its build/startup commands for this investigation.
Return:
- Files and symbols actually examined, and omitted coverage.
- Findings with original path, line range, source hash, supporting quote and observed/inferred status.
- Real framework API examples and relevant error/lifecycle constraints.
- Cross-module calls/configuration edges.
- Unknowns, conflicting evidence and the next source needed.
Do not infer an API from its name or treat a missing map entry as proof of absence.
```

## Coordinator verification

Check the actual coverage and mechanical citations first. Reject unsupported claims and stale evidence. Read the original source behind conclusions that affect the task, including relevant callers/configuration. Reconcile cross-module edges and terminology; test or inspect behavior where source alone leaves uncertainty.

Keep summaries compact but include the facts needed to avoid rediscovery. Request a targeted follow-up for an unresolved edge instead of asking every worker to reread the whole repository. Before implementation, verify the types, conventions and lifecycle of each private framework API the change will use.

Measure quality and cost on representative tasks if this becomes a recurring process: correct source-backed answers, invalid citations, unresolved edges, runtime and token usage. A cheaper model can produce an expensive incorrect summary; do not judge the process only by its input price.
