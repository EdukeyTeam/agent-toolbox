# Agent usage analytics: research evidence

Verified: 2026-10-17. This is research for an original skill, not permission to copy an existing third-party skill. No external skill was installed.

## Vendor capabilities

| Source | Evidence | Design consequence |
| --- | --- | --- |
| [Codex app server](https://learn.chatgpt.com/docs/app-server) | Documents thread usage notifications, account rate-limit buckets and account token-activity reads. Authentication and supported fields depend on the running version. | Accept structured exports and add supported read-only collection where available; distinguish account-wide and thread-local measures. |
| [Codex pricing and limits](https://learn.chatgpt.com/docs/pricing) | Limits vary by plan, task, speed and model; not every plan has a five-hour limit. API and credit accounting differ. | Read actual window/reset metadata; avoid a universal tokens-per-plan constant. |
| [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) and [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Separate rates can apply to ordinary input, cache reads, cache writes, output, long context and service tiers. | Version explicit rate cards; preserve missing cache dimensions and partial-cost coverage. |
| [Codex protocol source](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs) | Native `TokenUsageRecord` has response identity, response usage, turn totals and thread totals. Older `TokenUsageInfo` has last/cumulative usage and window capacity. | Prefer request identity over repeated last-usage snapshots. Source semantics are version-sensitive. |
| [Codex fork implementation](https://github.com/openai/codex/blob/main/codex-rs/core/src/agent/control/spawn.rs) | Forked history can retain legacy token events while native usage records are dropped. | Parent/child totals need lineage-aware treatment; do not sum inherited histories. |
| [Claude statusline](https://code.claude.com/docs/en/statusline) | Current context component counts, capacity, utilization, session identity and quota fields can be available. Before the first response and after compaction some fields may be absent. | Native observations beat text estimates; null must remain unknown. |
| [Claude monitoring](https://code.claude.com/docs/en/monitoring-usage) | OpenTelemetry exposes usage and tool events with correlation identifiers; content logging is optional and can expose prompts. | Treat telemetry as an additional reconciled source; recommend content-free collection by default. |
| [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) | Cache creation can have different TTL rates; model pricing and tokenizer behavior change across model generations. | Normalize fresh input separately from cache reads/writes; avoid one universal tokenizer or price multiplier. |
| [Copilot session data and Chronicle](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/chronicle) | Native history supports session analysis and personalized cost/workflow suggestions. Local and synced histories have different availability. | Adopt evidence-grounded insights, keeping hosted versus local coverage visible. |
| [Antigravity context panel](https://antigravity.google/docs/cli/commands/context/) | Native categories include messages, tools, customizations and system overhead; checkpoint treatment is product-specific. | Import native categories when present rather than imposing Codex assumptions. |
| [Antigravity headless output](https://antigravity.google/docs/cli/headless/) | JSON result usage can be cumulative across a session; stream step updates expose per-step usage where available. | Do not add final cumulative result usage to step-level usage; preserve schema and cache semantics. |
| [Grok Build sessions](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/17-sessions.md) | Documents persisted sessions and signals, including context and activity counters. | Differentiate context counters from request token billing; support only observed/documented capabilities. |

Documentation was queried through Context7 for `/openai/codex` and `/websites/code_claude`, then checked against the official pages/source above. Schemas must still be detected at runtime.

## Existing tools and skills

The requested discovery command ran successfully:

```bash
npx --yes skills@latest find 'token usage'
```

| Project or discovery result | What it contributes | What remains for this skill |
| --- | --- | --- |
| [ccusage](https://github.com/ccusage/ccusage) | Existing local agent usage/cost reporting, including time and session grouping across many sources | Context composition, explicit uncertainty, provenance, safe portable dashboards and quota calibration in one workflow; support optional imports instead of copying implementation |
| [skillusage](https://github.com/lovstudio/skillusage) | Skill and slash-command invocation analytics | Distinguish frequency from loaded content and request-level token usage |
| [copilot-session-usage](https://github.com/gsemet/copilot-session-usage) | Copilot-specific history and usage analysis | Cross-agent reconciliation and a shared output schema |
| [ECC cost-tracking](https://www.skills.sh/affaan-m/ecc/cost-tracking) | A skill built around its own hook-generated cost metrics | Avoid requiring a preinstalled hook or treating hook summaries as a complete historical ledger |
| [token-efficiency](https://www.skills.sh/delphine-l/claude_global/token-efficiency) | Guidance on token-efficient agent operation | Recommendations here must follow measured local evidence instead of applying blanket behavioral instructions |
| skills CLI result `huajiexiewenfeng/codex-token-usage-skill` | A related Codex usage skill was discoverable | Listing and candidate name were verified; page/source retrieval failed, so its implementation and quality were not assessed |

[Reported ccusage duplicate-counting case](https://github.com/ccusage/ccusage/issues/1288) supplies a regression scenario: repeated Codex `token_count` events can carry unchanged totals while timestamps differ. Treat this as a concrete failure mode to reproduce with synthetic fixtures, not a guarantee about every ccusage version.

No third-party code or skill text will be copied into this repository. Any later dependency requires its own version, license and provenance decision.

## Local metadata observations

Inspection printed schema keys, numeric usage fields and file counts only. It did not print user prompts, tool arguments/results, response text, credentials or account identities. These are observations of this installation, not promises about all installations.

- Current Codex rollouts contain native `token_usage_record`, legacy `token_count`, session metadata and turn context. The observed native record exposes per-response usage and response identity. The session index includes rollout paths and aggregate token metadata.
- Claude JSONL has assistant usage with input, cache creation, cache reads, output, optional output details, cache TTL details and service metadata. Request/shape events also exist; their bodies were not exposed or assumed necessary.
- Copilot's local SQLite database has `assistant_usage_events` with model, input/output/cache/reasoning counters, agent metadata, duration and nano-AIU fields. This differs from the hosted schema in the user's example, so runtime schema detection is necessary.
- Copilot event logs contain `model.model_call_success` with request identity, response usage and quota snapshots. Final session checkpoints are cumulative summaries and must not be added to request totals.
- Grok Build signals include context used/capacity, compaction count, model and tool counters. The inspected signals do not establish a complete billing-token history. Native context is useful even when billing totals remain unknown.
- An AGY configuration/data root exists, but no generic Gemini chat-log schema was established. Use documented JSON export support before claiming native historical ingestion.
- OpenCode SQL storage is present and exposes session/message token metadata. It is a potential later adapter or normalized import source, not a reason to expand the first release beyond the requested priorities.

## Known uncertainties and guardrails

Cloud activity, other devices, deleted history and previously uncollected quota percentages may be absent locally. Reports must state coverage instead of equating local totals with account totals. Provider usage may arrive late or change.

Exact attribution of hidden system prompts, provider tool serialization and retained multimodal content cannot be inferred from text logs alone. A visually complete chart must still expose unknown categories.

Historical prompts and outputs may contain sensitive information. Collection must keep raw content out of its output contract and avoid credential files entirely. A personalized recommendation that requires protected raw content needs the user's authorized data-processing route; numeric analysis can continue independently.

Browser retrieval could not open two skills.sh candidate pages on its first attempts. ECC was subsequently verified through its canonical `www.skills.sh` page and upstream source. The Codex candidate remains unverified beyond the CLI listing; no replacement was silently treated as equivalent.

## Proxy routing and GLM

[Z.ai's Claude Code integration](https://docs.z.ai/devpack/tool/claude) documents mappings from the CLI's model choices to GLM. This establishes why a harness label alone cannot prove the serving model. Historical routing still needs contemporaneous metadata or an explicit confirmed map.

[Official Z.ai pricing](https://docs.z.ai/guides/overview/pricing), checked 2026-10-17, supplies separate input, cached-input and output rates for GLM-5.3 and GLM-5.3-Flash. Those two models are added to the reference card; temporary storage terms and tool fees are outside token estimates. [Coding Plan rules](https://docs.z.ai/devpack/overview) describe credits and reset behavior separately. A subscriber's allowance is not the API price or an Anthropic quota.
