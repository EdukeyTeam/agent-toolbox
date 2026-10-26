# Agent usage analytics: implementation design

Date: 2026-10-17

Design approval: the user's 2026-10-17 follow-up authorized independent expert reviews, documentation, design decisions, implementation and testing through completion. The [PRD](PRD.md), [accounting ADR](ADR-001-accounting-and-storage.md) and [review decisions](review-decisions.md) refine this initial design and take precedence.

Canonical source: `skills/agent-usage-analytics/`. Execution ownership and progress belong in Beads, not this document. Research evidence is in [research.md](research.md).

## Purpose and users

Create an original, publicly installable skill for developers, trainers and course participants who want to understand agent usage. It has two independent workflows: historical usage analysis and inspection of one session's context. Codex is the first priority; Claude Code and GitHub Copilot CLI are also first-class sources. Other agents can supply exports through an explicit import contract.

The skill produces a short chat answer, a detailed Markdown report, a portable JSON report and an attractive, self-contained HTML dashboard. Normal analysis works locally without model calls, credentials, a running server or a third-party chart service.

## Implementation decisions

| Decision | Behavior |
| --- | --- |
| Name | `agent-usage-analytics` |
| Interface | A Python 3.11+ standard-library CLI, invoked by any agent that can run local scripts |
| Storage | Content-free normalized JSON for interchange; an optional local SQLite ledger for repeated collection and quota snapshots |
| Presentation | One offline HTML file with embedded data, CSS and SVG charts; matching Markdown tables and JSON |
| Measurement | Every metric carries source, timestamp, scope and evidence quality: reported, reconstructed, estimated or unavailable |
| Initial native adapters | Codex rollouts; Claude JSONL; Copilot JSONL and supported SQL usage tables |
| Additional sources | Grok Build signals and documented AGY JSON exports where their semantics are established; generic normalized imports for other tools |
| Automation | Idempotent collection and snapshot commands, suitable for an existing scheduler; scheduling is documented, not installed automatically |
| Privacy | Process transcript content locally; retain numeric measurements and safe identifiers, excluding raw prompts, responses, tool arguments/results and credentials from generated reports by default |

## Workflow 1: historical usage

The user selects sources and a date range, such as a calendar month. Discovery lists supported data locations and coverage; it does not recursively scan the whole home directory. Custom roots support Windows, Linux, macOS, archives and several devices. Collection flags identify device and account using user-supplied aliases rather than exposed account IDs.

Collection extracts provider usage and session metadata into a common representation. Reports show input, cache reads, cache writes, output, reasoning where available, request/session counts, cache hit rates, and API-equivalent cost. Views group by day, month, agent, model, session and explicit task category. Period comparisons use equally defined ranges and show missing coverage.

Task categories come from explicit labels or a supplied mapping. Optional local heuristics must be marked inferred, retain an unclassified group, and never represent a guess as a measured task type. The skill may help interpret a sanitized summary; it must not send whole historical transcripts to a model to classify them.

Tool and skill tables distinguish invocation counts and estimated visible content size from historical request usage. They must not claim that all tokens in a request were caused by its last tool or skill. Shared request usage is not counted again for every associated item.

## Workflow 2: a specific session and its context

Resolve an explicit session ID, optionally with a source file path. For Codex, use the current-thread environment identifier when present; otherwise require an explicit session ID. Never silently choose the newest unrelated session. A report records the selected source and observation time, since an active session can grow after the report.

Display a Claude-style grid or stacked bar, latest observed context size/capacity, compaction boundaries and a category table. Candidate categories include instructions, skill catalog descriptions, loaded skills, tool schemas, MCP schemas, user messages, assistant messages, tool arguments/results, compaction summaries and unobservable overhead. A category may be unknown.

The accounting rules are:

- Cumulative processed tokens, latest request input and current context are separate measures with separate labels.
- Preserve the provider's definition of context utilization and any reserved buffer. Do not assume all agents use the same denominator.
- Native context observations take precedence over local reconstruction. Latest request input is labeled as an observation of that request, not an exact view of later in-flight context.
- Apply recorded replacement history and compaction boundaries when reconstructing retained content. Where retention is not recoverable, show uncertainty rather than summing all historical messages into a current window.
- Estimate visible text with a documented method and expose that method. Provider tokenizers can be optional improvements; an approximate byte/character method is never called an exact token count.
- Hidden prompts, lazy-loaded schema state, image/audio payloads and unlogged reasoning remain unknown unless the source supplies trustworthy measurements.
- Keep unknown overhead separate. Do not scale estimated categories to force them to match a reported total, and flag any apparent mismatch.
- Installed or advertised skills are distinct from skills actually loaded. Recognize explicit load events and logged file reads without executing any logged command.
- File inventories measured today are configuration estimates, not proof of what was injected into an older session.

Include the largest observed contributors and three to five evidence-based suggestions when the data supports them. Suggestions can address oversized tool outputs, repeated file reads, instruction duplication, unused schema overhead, excessive orchestration or frequent compaction. Each suggestion cites a measured observation and the uncertainty of potential savings. No automatic disabling of tools, editing of instruction files or deletion of histories.

## Source and reconciliation contract

An adapter emits request usage, context observations, tool/skill observations and quota observations with separate identities and provenance. Missing counts remain null. Zero means a reported zero, not an absent field. The schema records whether input includes cache counts and whether output includes reasoning, then normalizes these into disjoint billing buckets.

For Codex, prefer per-response `token_usage_record` entries and deduplicate by response identity. Support older `token_count` logs through cumulative deltas, skipping unchanged snapshots. Do not add native records, legacy snapshots and SQL thread totals together. Detect counter resets, fork/replay inheritance and missing baselines; uncertain history is reported separately from attributable usage. Preserve request-level model changes.

For Claude, coalesce streaming assistant records by request/message identity and account once for the completed usage. Normalize fresh input, cache reads and cache creation separately. Keep cache-write TTL breakdown when supplied, and do not add reasoning to output when it is already included.

For Copilot, inspect SQL schemas and use allowlisted read-only queries. Prefer event-level usage with stable request IDs when available; SQL and JSONL are alternative evidence for the same activity, not additive totals. The local schema and hosted DuckDB schema are different contracts. Hosted queries must follow the store's documented partition and session bounds.

For all adapters, handle truncated trailing JSONL lines during a live session, malformed rows, rotations, duplicate imports and concurrent ledger writers. Report skipped rows, unavailable fields, unsupported versions and incomplete time coverage. Session indexes locate records and provide cross-checks; their totals are not additional requests.

## Quotas, monitoring and estimation

Store provider-reported utilization, window duration, reset time, model/bucket and observation time separately from locally measured usage. Support five-hour and seven-day views without assuming every plan has both windows. The provider's actual bucket/reset metadata wins over a hardcoded duration.

Display two complementary time views: local rolling usage for the last five hours/seven days, and provider-defined quota periods when observed. Never label a local rolling token total as the exact provider quota consumption.

Estimate tokens per percentage point and burn-rate trends only from aligned snapshots within the same account, bucket and reset period. Exclude reset crossings and decreasing utilization. Label the estimate empirical, show sample count and coverage, and warn when concurrent devices, cloud usage, model/speed changes or delayed accounting prevent a reliable extrapolation. Do not invent a fixed token allowance from a subscription name.

Repeated collection appends content-free observations and produces before/after comparisons. Historical quota snapshots cannot be reconstructed where no observations were saved. Supported live collection uses the agent's documented authenticated interface; it never extracts browser cookies or reads credential files.

## Pricing

Ship a versioned JSON rate card with official source URLs, verification date, effective dates when known, exact model IDs/explicit aliases, currency and prices per million tokens. Include uncached input, cached input, cache writes, output, applicable long-context thresholds and service/speed tiers. Preserve historical versions instead of silently repricing old reports at today's rates.

OpenAI input commonly includes cached tokens; Anthropic fresh input is a separate count from its cache buckets. The normalized calculator avoids double counting in both cases. Reasoning is not charged twice when included in output. Unknown cache-write TTLs or missing billing dimensions yield a range or partial estimate with priced/unpriced coverage, not a fabricated exact amount.

Call the result API-equivalent model cost. It is not the subscription bill, provider quota accounting or a claim that a consumer plan can be converted to dollars exactly. Show separately any provider-reported cost and identified tool fees. Unknown models are listed as unpriced until a rate card is supplied.

## Remote and agent-assisted collection

Keep local, provider-hosted, imported and manually observed data visibly separate. A capability table documents what is available without credentials, within the owning agent, or only to an organization administrator.

Codex app-server account usage and rate-limit reads, Claude native statusline/context/usage exports and Copilot hosted SQL tools are optional inputs. Import their structured exports when the host exposes them. A collection recipe tells the owning agent which numeric fields to return and which raw content to omit. If a tool is unavailable, preserve that gap instead of inventing an endpoint or scraping authentication.

Do not confuse API-organization usage with a personal Claude subscription. Grok and AGY receive only the capabilities their verified formats support; unavailable request-level token history is explicitly unavailable. Document the full product name because different unrelated Grok/Gemini tools have incompatible storage formats.

## Outputs and presentation

The chat response gives scope, measured totals, context/quota status where available, the biggest supported finding and links to artifacts. It stays brief.

Markdown includes coverage, methodology, model/session/day/month tables, context categories, top tools/skills, quota observations, pricing provenance, anomalies and recommendations.

HTML opens through `file://` without fetching scripts, fonts, chart libraries or data. It includes summary cards, time-series usage and cost charts, a context map, ranked contributor bars, quota observations, comparisons and filterable tables. All charts have numeric tables and accessible labels. Agent/model/date filters operate on embedded request data; context and coverage retain the full report scope. It includes readable light/dark styling and a print layout. Text is escaped; imported labels cannot execute HTML or JavaScript.

JSON contains the normalized metrics, source coverage, confidence, pricing references and report schema version. Generated artifacts are written to a user-selected local report directory, outside the skill installation. Real reports, source transcripts, local databases and credentials are never committed to the public repository. A synthetic example report demonstrates the layout.

## Implementation sequence and validation

1. Establish the normalized schema, independent rate-card format and source capability references. Add synthetic fixtures with hand-calculated expected results.
2. Implement Codex accounting and single-session inspection first. Validate repeated snapshots, native/legacy overlap, forks, compaction, model changes, reasoning subsets, partial files and unknown fields.
3. Add Claude and Copilot adapters, read-only SQL ingestion, normalized import, and the verified Grok/AGY portions. Validate streaming coalescence, cache semantics, unsupported schemas and source reconciliation.
4. Implement historical aggregation, quota snapshot comparison, cost calculation and evidence-based insights. Validate timezone/month boundaries, resets, missing coverage, unknown models, pricing tiers and idempotent imports.
5. Generate JSON, Markdown and the offline HTML dashboard from the same report object. Verify numerical agreement, escaping, empty states, offline behavior, filtering, keyboard use and narrow-screen rendering.
6. Package the concise skill instructions and progressive references; add Node-discovered tests that exercise the Python CLI so the existing repository-wide workflow runs the new checks. Update README discovery/install examples and any workflow filters required by runtime assets. Run the required `npm ci` and `npm test` plus focused checks, then prepare the task PR.

Acceptance requires both workflows to run against synthetic fixtures and a local metadata-only Codex session trial, with no raw transcript content entering the public artifacts. A browser review verifies the example HTML against its underlying JSON and Markdown.

## Repository coordination

The existing checkout is shared with the active legacy skill agent. Do not switch its branch, alter its index/staged changes, edit legacy sources/tests/docs or create a worktree without the user's permission. New skill files and this design directory have disjoint ownership. Shared README/workflow changes must be minimal and preserve concurrent edits.

Use a task feature branch and explicitly scoped commits. Publication must contain only this task's paths and changes, without including the concurrent branch's unpublished work. If isolated branch publication cannot be achieved safely in the shared checkout, resolve that repository boundary with the user before changing branches. Human and AI review are required before merge; merging to main remains a separate approval.

## Corrections log

| Date | ID | Before | Change | Reason |
| --- | --- | --- | --- | --- |
| 2026-10-17 | UA-001 | No usage/context analytics skill | Record the two workflows and shared offline reporting design | User's initial request |
| 2026-10-17 | UA-002 | A simple cumulative-snapshot parser was a possible approach | Prefer native response usage; handle replay and cumulative snapshots explicitly | Current Codex schema and documented duplicate-counting failures |
| 2026-10-17 | UA-003 | Quotas could be mistaken for fixed token budgets | Separate measured tokens, provider percentages and empirical calibration | Provider quotas depend on plan, bucket and workload |
| 2026-10-17 | UA-005 | Initial design awaited confirmation | Proceed under user-authorized expert consultation and decision authority | User explicitly asked the agent to finish and validate the result |
| 2026-10-17 | UA-006 | Source transition, context basis and pricing dimensions were underspecified | Record per-request tiered pricing, cache-write presence, metadata/response joins, replay baselines, provider-specific context and Windows CI | Verified Opus 5.5 and Argon 4 review findings |
| 2026-10-17 | UA-007 | Hosted SQL and broad native adapters might imply universal support | Treat local schemas as observed contracts; hosted sources and AGY through explicit numeric exports; preserve unknown accounting | Expert feedback and local schema evidence |
| 2026-10-17 | UA-008 | Alternative-source reconciliation occurred inside individual scans | Reconcile Copilot modes and cumulative AGY observations globally, including ledger reads; align parent/subagent scope and preserve evolving session metadata | Independent implementation review reproduced cross-import double counting |
| 2026-10-17 | UA-009 | Share pseudonyms used public unsalted hashes | Use an unexported per-report salt, preserving generic category labels | Low-entropy metadata should not be recoverable by a simple dictionary |

| 2026-10-17 | UA-010 | Copilot event precedence could hide a larger SQL history; resolved warnings could persist | Select a dominating SQL alternative without adding sources, flag all discrepancies, distinguish fresh spawns/reconciled boundaries, refresh source warnings and retain all calculation rates | Follow-up Opus implementation review |
