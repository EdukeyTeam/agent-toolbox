# Source capabilities and coverage

These adapters are version-aware readers, not promises about every agent version. Extra fields are tolerated; missing required fields produce a coverage warning. Logs can omit cloud tasks, other devices, deleted files or request usage. A local total is not an account-wide bill.

| Agent/input | Support | Contract and limits |
| --- | --- | --- |
| Codex `.codex/sessions`, `archived_sessions` or one rollout JSONL | Native per-response usage, older cumulative snapshots, context observations, visible tool/skill sizes and recorded quotas | Observed schema informed by [upstream protocol](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs). Native response usage wins; thread/index totals are cross-checks. |
| Claude `.claude/projects` or one JSONL | Request usage, streaming deduplication, cache buckets, subagent files and estimated visible context | Observed transcript schema. [Native statusline](https://code.claude.com/docs/en/statusline) supplies capacity/quota data absent from ordinary transcripts. |
| Copilot `.copilot`, session-state/events JSONL or session-store.db | Modern event usage, tool observations, supported SQL usage table | Observed-local contracts; [Chronicle docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/chronicle) document storage and divergence. SQL/event alternatives are reconciled, never simply added. |
| Grok Build `.grok/sessions` or `usage.json` | Verified turn/model counts and context signals | Observed-local schema. Whole-session inherited totals are excluded. [Grok session docs](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/17-sessions.md) describe persistence and fork inheritance. Other unrelated Grok CLIs have different formats. |
| Antigravity `--output-format json` / `stream-json` export file | Explicit export ingestion | [Headless docs](https://antigravity.google/docs/cli/headless/) distinguish per-step usage from cumulative result usage. Ambiguous cache semantics are marked, not silently priced. No native brain-directory assumption. |
| Any agent normalized numeric dataset | Usage, context, tools and quota observations | See schema reference. Provenance/identity must identify overlaps with local sources. |
| Hosted session store | Owning-agent export recipe only | A host may expose SQL tools unavailable elsewhere. Use its actual schema and export numeric observations; no hardcoded universal cloud endpoint. |

## Windows and multiple devices

Provide the Windows user's data root using `--home` for discovery, or repeated `--source` paths for precise selection. Run natively against `C:\Users\...` or from WSL against its mounted path. WSL and Windows Codex homes are different sources even on one physical computer. Never search OneDrive or business-document trees to find agent telemetry.

Source `--device` and `--account` values are user-chosen aliases. Stable request identities deduplicate copied logs; unrelated accounts are not a reason to sum the same replicated request twice. Keep separate ledgers when comparing independent accounts whose identifiers could collide. UTF-8 BOM, CRLF, spaces and non-ASCII path components are supported. Long paths still depend on host filesystem configuration.

## Reading the gaps

`reported` means a recorded provider counter, `reconstructed` means an inferred delta or retained-history interpretation, and `estimated` means a diagnostic heuristic. None is a final invoice. `unavailable` preserves missing evidence. A zero is a reported zero.

Visible context size is estimated from recorded text with a model-aware character heuristic and broad bounds. Built-in schemas, lazy MCP definitions, image/audio representations and encrypted reasoning can be absent. Today’s installed file inventory is not proof of what entered an old session. An advertised skill catalog is not the sum of all installed skill bodies.

If a source is unreadable or unsupported, keep valid sources and name the gap. Do not retry credential extraction, mutate the provider database or substitute estimates into historical billing totals. For a truncated final JSONL line, rerun after the active agent writes it; the warning remains part of coverage.
