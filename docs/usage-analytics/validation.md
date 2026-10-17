# Validation record

Date: 2026-10-17. Real histories and full reviewer transcripts remain local and are excluded from this public repository. The checks below disclose methods and outcomes, without account statistics or transcript content.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Skill structure | Passed | Codex skill-creator validator accepts the frontmatter and layout; repository structure tests discover the new skill. |
| Focused Python suite | 86 tests passed | Hand-counted fixtures cover pricing/cache dimensions, repeated snapshots, imports, SQLite, context/compaction, privacy, source overlap and CLI artifacts. |
| Committed feature branch | 111 Node tests passed | `npm ci` and `npm test` run against an exported feature-branch tree, independent of concurrent legacy changes. The Node bridge also runs the focused Python suite. |
| Real Linux and Windows histories | Passed | Independent raw numeric oracles agree with normalized Codex, Claude Code and Copilot SQL counters on both devices. The Windows Codex fixture includes six compactions. No real transcript is copied into a test fixture. |
| Real Grok Build history | Passed | Seven measured turn-usage files match independent output-counter sums and observation counts. Native context signals have separate semantics. |
| Real AGY export | Correctly partial | Actual headless result exports parse. Cache-inclusive input semantics were not established by those exports, so ambiguous input and exact pricing stay unavailable. Wrapper footer lines are disclosed as malformed rather than treated as usage. |
| Broad local history | Passed | A full collection spanning more than one thousand source files completed and generated the three report formats. Unsupported records and unpriced work remain visible. This is a coverage trial, not an independent oracle for every historical request. |
| Offline Chrome | Passed | Summary numbers match JSON; agent/date filters, reset, theme, request multiplicity and session context ordering work. A 390-pixel viewport has no horizontal page overflow. Injected markup stays inert; no external HTTP requests occur. |
| Native quota read | Passed | The authenticated Codex app-server accepted the read-only rate-limit request, without a model turn or credential extraction. The observed buckets are preserved; missing five-hour metadata is not invented. |
| Skill behavior trial | Passed | A separate Codex session followed the skill against synthetic input and generated numerically matching JSON, Markdown and HTML. Root independently verified the browser output. |

## Regression cases added after independent code review

The review reproduced cross-import Copilot SQL/event double-counting and cross-file AGY cumulative double-counting. Both now reconcile globally, including separate ledger runs and repeated/reversed imports. Additional cases preserve Claude streamed blocks, select Codex children consistently, locate archived parents, fall back to SQL when event accounting is unusable, interpret the SQL store's UTC wall-clock timestamps, read UTF-8 task labels on Windows, update growing session metadata and isolate unrelated warnings.

Codex legacy snapshots can arrive before their matching native event. Tests retain only cumulative endpoints proven to precede the native boundary, including an earlier live ledger collection. Unproven overlap remains excluded and labeled as a lower bound. Share exports use per-report random pseudonyms; generic context categories stay readable.

## Practical limits

- Hidden prompts, live tool-schema state, multimodal retention and unlogged activity cannot be reconstructed exactly. Visible composition remains a bounded character-based estimate beside the measured anchor.
- Local token totals are not account-wide subscription consumption. Other devices, cloud tasks, deleted logs and delayed provider accounting can be absent. Quota calibration remains experimental and requires explicit complete-coverage eligibility.
- API-equivalent costs are a dated reference comparison, with unknown models unpriced and missing billing dimensions expressed as ranges. Used rate entries are embedded in report JSON.
- Task categories require an explicit mapping. Tool/skill sizes are visible-content proxies, not causal cost attribution. A source's schema can change after these observed contracts.
- Dedicated CI runs Python 3.11 and 3.14 on Linux and Windows. Its live PR results are the authority for the cross-platform matrix; local access to Windows histories alone is not a native Windows runtime test.
