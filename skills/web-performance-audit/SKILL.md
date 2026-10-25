---
name: web-performance-audit
description: Measure and report the performance of a live web page with Chrome DevTools (CLI and MCP) and Lighthouse - field vs lab Core Web Vitals, LCP subparts, main-thread and third-party cost, payload budgets, INP per interaction and a heap-snapshot leak check - and deliver an agent-ready Markdown report plus an interactive HTML report in the project's docs/ folder. Use when asked to audit, measure or explain a site's speed, Lighthouse/PageSpeed score, Core Web Vitals, slow LCP/INP, heavy third-party tags or memory use, or to produce a performance report with prioritized fixes.
---

# Web Performance Audit

Produce two deliverables for one URL, always saved in the project's `docs/` folder:

```text
docs/<site-slug>-performance/
  report.md          # source of truth, written for coding agents: evidence, code, verification
  report.html        # rendered from report-data.json for human reviewers (tabs, charts, filterable to-do)
  report-data.json   # the numbers and findings both reports are built from
  .gitignore         # ignores raw/
  raw/               # Lighthouse JSON/HTML, traces, heap snapshots, QA screenshots (never committed)
```

`<site-slug>` is the bare host, e.g. `example-com-performance`. If the project has no `docs/` folder, create it. Never commit `raw/`: it is hundreds of MB, and traces from a real browser profile contain cookie IDs and pixel query strings.

## Prerequisites

You need Node.js 22.19+ (required by current Lighthouse; on older Node pass `--lighthouse 12` to the runner), Google Chrome 144+, the `chrome-devtools` CLI from the `chrome-devtools-mcp` package, and ideally the Chrome DevTools MCP server and its upstream skills. Check with `chrome-devtools --version`. If anything is missing, follow [setup](references/setup.md) once, then continue.

## Rules that keep the numbers honest

- **Field first, lab for diagnosis.** CrUX p75 (28 days) says whether users have a problem; traces and Lighthouse say why. Never claim users fail Core Web Vitals from lab data alone, and never claim a field improvement right after a deploy.
- **The DevTools MCP `lighthouse_audit` tool excludes the Performance category.** Take the Performance score and metrics from the Lighthouse CLI ([scripts/run-lighthouse.mjs](scripts/run-lighthouse.mjs)); use `lighthouse_audit` only for accessibility, SEO and best practices.
- **At least 3 runs per form factor; report median and range.** Run Lighthouse sequentially, and keep the user's browser idle while it runs.
- **State conditions for every number**: browser profile, device and throttling, cold or warm cache, consent and login state.
- **Browser extensions pollute traces.** A trace in the user's own profile attributes extension work (`chrome-extension://<id>` in ThirdParties) to the page. Re-measure in an isolated context (`new_page --isolatedContext <name>`) and use the real-profile run only for contrast.
- **Background tabs are throttled.** Bring the measurement tab to the front (`select_page <id> --bringToFront true`) before tracing.
- **Verify the root cause before recommending a fix.** If an insight suggests a cause (for example, a slider hiding the LCP image), test it with a small experiment (see the LCP candidate logger in [methodology](references/methodology.md)) before you write it down. A plausible but wrong P0 wastes a team's sprint.
- **Never enter credentials.** If the audit needs a logged-in state, the user logs in in their own Chrome first and you attach with `--autoConnect`.

## Workflow

Track progress with this checklist:

```text
Audit progress:
- [ ] 1. Scope: URL, states to compare (anonymous / consented / logged in), output folder
- [ ] 2. Lab baseline: Lighthouse CLI 3x mobile + 3x desktop, clean headless profile
- [ ] 3. Field data + traces: cold and warm reload traces, desktop and throttled mobile
- [ ] 4. Diagnose: insights for failing metrics only; verify the root cause
- [ ] 5. Interactions (INP) and memory (heap snapshots before/after repeated interactions)
- [ ] 6. Write report-data.json, then report.md
- [ ] 7. Render report.html, check it in a browser, publish if asked
```

### 1. Scope

Ask only if unclear: which URL, which visitor states matter, and whether the user's real Chrome profile may be used. Create `docs/<site-slug>-performance/raw/` and the `.gitignore` (one line: `raw/`).

### 2. Lab baseline (Lighthouse CLI)

```bash
node <skill-dir>/scripts/run-lighthouse.mjs --url https://example.com/ --out docs/example-com-performance/raw/lighthouse --runs 3
node <skill-dir>/scripts/summarize-lighthouse.mjs docs/example-com-performance/raw/lighthouse docs/example-com-performance/raw/lighthouse-summary.json
```

On WSL the runner launches Linux Chrome itself, because Lighthouse's own launcher breaks there ([setup](references/setup.md#wsl)); never run `lighthouse` directly in WSL. The summary prints medians and ranges, failing audits with estimated savings, main-thread breakdown, bootup time per script, third parties, resource totals by type and host, and LCP subparts. Run it in the background and do nothing CPU-heavy meanwhile.

### 3. Field data and traces (DevTools CLI)

Use the CLI for scripted steps and the MCP tools for interactive exploration; they share the same tool names. Full command patterns, emulation presets and the consent-state technique are in [methodology](references/methodology.md).

```bash
chrome-devtools new_page "https://example.com/" --isolatedContext perf
chrome-devtools performance_start_trace <pageId> --reload true --autoStop true --ignoreCache true --filePath raw/traces/desktop-cold.json.gz
```

The trace summary includes CrUX p75 field data (URL or origin scope) when Google has it. The form factor follows the emulated device: a desktop trace returns desktop field data, and a mobile-emulated trace returns phone field data. Record both.

For throttled mobile traces the CLI client can time out before the page settles. Use `--autoStop false`, wait about 45 s, then `performance_stop_trace <pageId> --filePath ...`.

### 4. Diagnose

Call `performance_analyze_insight` only for insights tied to a failing or suspicious metric: `LCPBreakdown`, `RenderBlocking`, `NetworkDependencyTree`, `ThirdParties`, `DOMSize`, `ForcedReflow`, `Cache`, `ImageDelivery`, `INPBreakdown`, `CLSCulprits`. Save each output under `raw/traces/`. Use the insight-set ID printed by the trace (`NAVIGATION_0`, `NAVIGATION_1` or `NO_NAVIGATION`); do not assume it is `NAVIGATION_0`.

Pick the bottleneck LCP subpart first (TTFB, load delay, load duration, render delay). Recommend fixes for that subpart only, and verify the cause with an experiment before writing it up.

### 5. Interactions and memory

- **INP:** install an Event Timing observer, click the real UI controls (menu, search, slider, accordion) at 4x CPU, and read input delay, processing and presentation per interaction. Also record one interaction trace for `INPBreakdown`.
- **Memory:** take a heap snapshot after load, repeat a set of interactions 10 times, and take a second snapshot. Element UIDs change after a reload, so take a fresh `take_snapshot` before scripted clicks. Then use `compare_heapsnapshots`, `get_heapsnapshot_details --filterName objectsRetainedByDetachedDomNodes`, and `close_heapsnapshot` for each file. Report "no leak" when the delta is flat; heavy-but-stable heaps are a separate finding.

### 6. Write report-data.json, then report.md

Collect every number once in `report-data.json` (schema and example in [assets/report-data.example.json](assets/report-data.example.json)). Then write `report.md` following [report structure](references/report-structure.md):

1. executive summary
2. method and conditions
3. scorecard (field, lab, field vs lab)
4. LCP deep dive
5. JS / main thread / third parties
6. payload vs budget
7. INP
8. memory
9. prioritized to-do (P0-P3: evidence, how with code, verify)
10. verification plan with budgets
11. reproduce

Mark every untested idea as a hypothesis.

### 7. Render and check the HTML report

```bash
node <skill-dir>/scripts/render-html-report.mjs docs/example-com-performance/report-data.json docs/example-com-performance/report.html
```

The output is one self-contained file: light and dark themes, tabs, SVG charts with tooltips and table views, a priority-filterable to-do list with copy buttons. Open it in a browser and check:

- no console errors
- every tab switches
- no horizontal scroll at 390 px width

If the user wants it shared and an artifact or publishing tool is available, publish the rendered page and give them the link.

## Finish

- Close every tab you opened and run `chrome-devtools stop`.
- Leave the user's own tabs untouched.
- Tell the user where the reports are, what was measured, which states could not be measured, and the top three fixes.
- Commit only the report files (never `raw/`), and only if the user asks.
