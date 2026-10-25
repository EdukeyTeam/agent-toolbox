# Measurement methodology

## Run matrix

Plan the runs before starting and record them in the report's method table. A typical public marketing or content page:

| Run | Profile | Device + throttling | Cache | Visitor state | Purpose |
|---|---|---|---|---|---|
| A | Lighthouse CLI x3, clean headless | Mobile (default: 4x CPU, 150 ms RTT, ~1.6 Mbps simulated) | Cold | Anonymous | Score, budgets, opportunities |
| B | Lighthouse CLI x3, clean headless | `--preset=desktop` | Cold | Anonymous | Desktop baseline |
| C | DevTools trace, user's Chrome (`--autoConnect`) | Desktop, no throttling | Cold + warm | Real (consented / logged in) | Returning visitor |
| E | DevTools trace, isolated context | Mobile 412x915, Slow 4G, 4x CPU | Cold | Real state recreated (cookies) | State cost without extension noise |
| F | Event Timing + interaction trace | Mobile, 4x CPU | Warm | Real state | INP per interaction |
| G | Heap snapshots x2 | Mobile viewport | Warm | Real state | Leak check |

If a site has no logged-in mode, the meaningful difference between visitors is often **cookie consent**: after consent, marketing tags can multiply third-party cost. Measure both states.

## Emulation presets

```bash
chrome-devtools emulate <pageId> --viewport "412x915x2.625,mobile,touch" --networkConditions "Slow 4G" --cpuThrottlingRate 4
chrome-devtools emulate <pageId> --viewport "1350x940x1"
chrome-devtools emulate <pageId>
```

DevTools "Slow 4G" roughly matches Lighthouse's mobile network. The last command (no flags) resets emulation. Always reset before switching profiles, and before you close a tab in the user's browser.

## Recreating a visitor state in an isolated context

Extensions do not run in isolated contexts, so this is how you measure the real state cleanly.

1. In the user's tab, read only the names and values of the state cookies you need, such as the consent manager's category cookies. Do not copy analytics IDs or session tokens, and never print them in the report.
2. Open `new_page <url> --isolatedContext perf-consented`, then set those cookies with `evaluate_script` (`document.cookie = 'name=value; path=/; max-age=31536000; SameSite=Lax'`).
3. Trace with `--reload true --ignoreCache true`.

Logged-in states cannot be recreated this way without handling session tokens. Trace them in the user's own profile, and say that extensions may inflate the numbers.

## Traces

```bash
chrome-devtools performance_start_trace <pageId> --reload true --autoStop true --ignoreCache true --filePath raw/traces/<name>.json.gz > raw/traces/<name>.md
```

```bash
chrome-devtools performance_start_trace <pageId> --reload true --autoStop false --ignoreCache true
chrome-devtools performance_stop_trace <pageId> --filePath raw/traces/<name>.json.gz > raw/traces/<name>.md
```

Use the second form for slow throttled loads: wait about 45 s between the two commands.

The summary (`.md`) lists:

- lab metrics and LCP subparts
- CrUX field metrics and their scope
- insight-set IDs and available insight names

Then, for each relevant insight:

```bash
chrome-devtools performance_analyze_insight <pageId> <insightSetId> <InsightName> > raw/traces/insight-<run>-<InsightName>.md
```

Open saved traces in DevTools > Performance > Load profile to review them visually.

### LCP subparts and what fixes them

| Dominant subpart | Typical cause | Fix family |
|---|---|---|
| TTFB | Slow origin, no HTML caching, redirects | CDN/edge HTML cache, backend work |
| Resource load delay | LCP resource discovered late (CSS background, JS-inserted, lazy-loaded) | Plain `<img>` in HTML, `fetchpriority="high"`, preload only if discovery is late |
| Resource load duration | Large file, competing high-priority downloads | Modern format, responsive sizes, fewer high-priority competitors (fonts, other slides) |
| Element render delay | Main thread busy (render-blocking CSS/JS, long tasks), or element hidden until JS runs | Smaller and critical CSS, defer JS, delay tags, render in HTML |

### Verifying an LCP root cause

Render delay has two very different causes, and they need different fixes: the element is hidden until JS runs, or the main thread is busy. Distinguish them with an init script that logs every LCP candidate, FCP, and the moment a suspected component initializes:

```bash
chrome-devtools navigate_page <pageId> --url <url> --ignoreCache true --initScript "window.__lcpInitSelector = '.slick-initialized'; $(cat <skill-dir>/scripts/lcp-candidates.init.js)"
chrome-devtools evaluate_script "() => window.__lcpLog" --pageId <pageId>
```

Replace `.slick-initialized` with the selector that marks the suspected component as initialized. The default covers slick, Swiper and `[data-initialized]`. Interpret the log like this:

- **LCP equals FCP** and is earlier than component init: the component is not gating LCP.
- **LCP is well after FCP** but before component init: main-thread contention.
- **LCP lands right after component init**: JS gating. Fix the markup or CSS so the first state renders without JS.

Run this on desktop unthrottled and on mobile at 4x CPU.

## Lighthouse

- Run sequentially, never in parallel, and never while you are tracing in another browser.
- Use the median run (closest to the median LCP) as the representative run for details.
- Read `render-blocking-insight`, `unused-css-rules`, `unused-javascript`, `bootup-time`, `mainthread-work-breakdown`, `third-parties-insight` (`third-party-summary` before Lighthouse 13), `network-dependency-tree-insight`, `cache-insight`, `forced-reflow-insight`, `legacy-javascript-insight`, `bf-cache`, `long-tasks` and `network-requests`. The summarizer extracts these.
- Don't prioritize anything with 0 ms estimated impact, but do list it as hygiene.

## Payload budget (starting guardrails for a content page)

| Resource | Budget (transfer) |
|---|---|
| Total page weight | 1,500 KiB |
| JavaScript | 300 KiB |
| CSS | 100 KiB |
| Fonts | 100 KiB |
| Above-the-fold images | 500 KiB |
| Third-party | 200 KiB |
| DOM elements | 1,500 |

Also compare the uncompressed sizes of CSS, JS and HTML. Style recalculation and parse cost scale with raw size, not gzip size.

## INP per interaction

```js
() => {
  window.__evt = [];
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) if (e.interactionId) window.__evt.push({
      name: e.name, dur: Math.round(e.duration),
      inputDelay: Math.round(e.processingStart - e.startTime),
      processing: Math.round(e.processingEnd - e.processingStart),
      presentation: Math.round(e.startTime + e.duration - e.processingEnd),
      mark: window.__mark,
    });
  }).observe({ type: 'event', buffered: false, durationThreshold: 16 });
  return 'ok';
}
```

Before each click, set `window.__mark = '<interaction name>'`, then read `window.__evt` and keep the worst event per mark. Interactions under 16 ms are not recorded, so report them as good. If presentation delay dominates, the fix is DOM size, CSS size and forced reflows, not faster handlers.

## Memory

- Snapshots are 50-100 MB each. Never read them as text. Use the CLI memory tools (`get_heapsnapshot_summary`, `compare_heapsnapshots`, `get_heapsnapshot_details`), which require the `--memoryDebugging` server flag, enabled by default in the CLI.
- **Leak verdict:** look at the delta after N repeated interactions. Growth only in `Performance*Timing` entries or accessibility-tree objects is tool overhead.
- **Heavy baseline:** look at the largest classes by retained size, for example `StyleRule`/`CSSStyleRule` (oversized CSS) or compiled code (too much JS). Mark guesses about which library owns an object shape as hypotheses.
- `close_heapsnapshot` every file at the end.

## Common pitfalls (seen in practice)

- Element UIDs from `take_snapshot` go stale after a reload or navigation. Clicks by an old UID fail silently inside loops. Re-snapshot first, and count failures.
- `chrome-devtools` client timeouts are not tool failures. Check whether the trace file was written and query the daemon (`performance_analyze_insight`) before re-running.
- Insight-set IDs are not always `NAVIGATION_0`. After `about:blank` or when tracing without reload, they are `NAVIGATION_1` or `NO_NAVIGATION`.
- Field data in a trace summary follows the emulated form factor. Do not mix phone and desktop numbers.
