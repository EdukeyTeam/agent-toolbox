# Expert review decisions

Date: 2026-10-17. Reviewers: Claude Opus 5.5 through Claude Code CLI and Gemini 4 Argon (High) through Antigravity CLI. Both independently read the initial design/research and consulted upstream sources. Their full reports and runner evidence remain in the local review workspace; this document records the reviewed decisions without private machine metadata.

Both verdicts were conditional approval requiring accounting changes before implementation. Their useful agreement was stronger than their disagreement: use native measurements, never sum repeated snapshots, distinguish current context from historical work, and avoid a confident chart where data is absent.

| Finding | Decision and verification |
| --- | --- |
| Price per request, then aggregate | Accepted. Verified current official model/cache pricing and per-request prompt tiers. Preserve speed, geography and cache TTL dimensions; expose unpriced/range results. |
| OpenAI input includes cache writes as well as reads | Accepted. Preserve field presence; subtract both subsets for ordinary input. Negative counts become anomalies. |
| Codex native records need model/timestamp joins | Accepted. Use envelope time and turn-context model; explicit inference when the exact join is unavailable. |
| Forked rollouts can contain parent metadata and legacy events | Accepted. Establish file ownership from its own final metadata; inherited records become baselines. Native response records and legacy snapshots cannot both charge the same activity. |
| Claude message ID alone is insufficient | Accepted. Use message ID plus request ID, and field maxima across streaming blocks. Subagent completion summaries are not lifetime usage. |
| Context basis differs by agent | Accepted. Preserve native percentage, basis and capacity separately. Post-compaction context without a new request is unknown. |
| Anchor context to measured usage | Accepted. Show heuristic visible categories and an unattributed residual separately; never infer free space from visible text alone. |
| Argon proposed scaling categories to fit an anchor | Rejected. The measured total does not prove why the estimate differs. Show the overrun explicitly; scaling would hide uncertainty. |
| Improve the character heuristic | Accepted as uncertainty, not a replacement fake tokenizer. Use model-aware documented heuristics and broad bounds; exact measured request counts remain separate. Empirical tokenizer fitting is deferred. |
| Add Windows CI | Accepted. A dedicated workflow tests minimum/current Python on Linux and Windows, without changing legacy-owned workflows. |
| Cut the optional SQLite ledger | Rejected for this requested scope. Repeated monitoring and retaining measured history across log rotation need durable deduplication. A small transactional content-free ledger is simpler than inventing a concurrent append/cache protocol. Source SQL remains read-only. |
| Prefer Node over Python | Rejected. The root package has no Node-only runtime requirement, and the repository already supports Python workflows. Python stdlib provides SQLite without external drivers or CLIs. Add explicit CI and a Node discovery wrapper. |
| Remove a proposed Chart.js bundle | No such bundle was proposed. Keep the already selected inline SVG/CSS/vanilla-JS design, without third-party chart code. |
| Remove an alleged multi-parameter OLS calibration engine | No such engine was proposed. Keep strict compatible-snapshot eligibility and descriptive estimates; no universal allowance or exhaustion forecast. |
| Hosted Copilot SQL lacks a universal documented contract | Accepted. Keep an owning-agent collection recipe and numeric import contract, not an invented hosted API. |
| Copilot source divergence | Accepted. Compare alternate sources and disclose SQL-only sessions/orphaned indexes; do not silently discard historical usage because a directory was deleted. Without request identity, source overlap is reconciled conservatively. |
| Use SQLite immutable mode for a live source | Rejected. Immutable mode can ignore a live WAL. Use read-only backup with a bounded busy timeout. |
| Grok and AGY support boundaries | Partly accepted. AGY uses documented exports with explicit ambiguous-field handling. Grok turn usage and context signals are supported as observed schemas, with inherited session totals excluded and limitations stated. Generic Gemini history is deferred. |
| Metadata privacy | Accepted. No raw content is exported; source paths are hashed. Local identifiers remain useful, and share mode pseudonymizes them for course demonstrations. |

## Validation gates

Tests must reproduce duplicate snapshots, mixed native/legacy coverage, inherited metadata, counter resets, Claude streaming and subagents, cache TTL uncertainty, prompt-tier boundaries, SQL/event overlap, live WAL, compaction with no subsequent request, invalid imports, privacy canaries and HTML injection. Real Linux and Windows sessions supply independent numeric baselines, including a Codex session with six compactions. Browser validation uses the installed Chrome.

The reviewers' unverified precision claims, benchmark timings and broad runtime assumptions are not acceptance evidence. Implementation is judged by the documented contracts and actual test results.
