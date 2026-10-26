# report.md structure

`report.md` is the source of truth. Coding agents will implement the fixes from it, so every claim needs a number, a source run and a way to re-check it. `report.html` is rendered from `report-data.json` and must say the same things.

## Header

Include the page URL, the date, tool versions (Chrome, Lighthouse, DevTools MCP/CLI), and the audience.

## 1. Executive summary

Five to seven numbered findings, each one sentence plus its key number, then a one-paragraph verdict naming the top 2-3 fixes.

Open with the field verdict ("real users are fine / failing"), so that nobody reads a poor lab score as a production incident.

## 2. Methodology and conditions

Give the run matrix (see [methodology](methodology.md)) and the visitor states. Also state:

- what could not be measured, and why (for example, a logged-in area on a separate app)
- which runs were discarded, and why (for example, extensions)

## 3. Scorecard

- **Field table:** metric x phone/desktop, p75 value, threshold, status.
- **Lab table:** median [min-max] for score, FCP, LCP, TBT, CLS, Speed Index and TTFB, for mobile and desktop.
- **Field vs lab interpretation:**

| Field | Lab | Interpretation |
|---|---|---|
| Poor | Poor | Reproducible user problem; fix the dominant bottleneck |
| Poor | Good | The lab missed real conditions; add RUM, test real devices and states |
| Good | Poor | Fragile on slow devices or in score-based tools; do not claim users are failing |
| Unavailable | Any | Lab only; recommend RUM |

## 4. LCP deep dive

Name the LCP element (selector and resource), then give a subparts table for every context (field phone, field desktop, each lab run). CrUX p75 subparts are independent percentiles and do not add up to the p75 LCP, so give each field row its measured p75 LCP (`lcp` in `report-data.json`), and never present the subpart sum as field LCP or a subpart's share of it. Compare field subparts in milliseconds only. Lab subparts come from one trace and do add up, so give the share of render delay for lab runs. Write the root cause as **verified** or as a **hypothesis**, and include the experiment that decided it.

## 5. JavaScript, main thread, third parties

- main-thread breakdown table
- top scripts by CPU
- longest tasks
- third-party table comparing visitor states (transfer size and main-thread time)
- tag-manager observations, such as duplicate tag loads or an outlier pixel

## 6. Payload vs budget

Give a budget table (budget, actual, % over, uncompressed size), then a "specific waste" table (item, evidence, saving).

## 7. Interactivity (INP)

Give a per-interaction table: duration, input delay, processing, presentation, status. Follow it with the diagnosis, naming the forced-reflow sources (file:line).

## 8. Memory

Give a before/after table (JS heap used, snapshot total, delta, detached DOM, DOM size). State the leak verdict, then the largest retained classes and what they imply.

## 9. Prioritized to-do

Priority = (impact on the failing metric x confidence) / effort.

- **P0:** do first
- **P1:** high value
- **P2:** worthwhile
- **P3:** hygiene, observability, guardrails

Start with a summary table: ID, task, metric(s), expected lab impact, effort (XS-L), owner. Then give each P0-P2 item its own subsection:

- **Evidence:** numbers, file names, insight names.
- **How:** numbered steps plus copy-paste code for the project's stack. Use real handle and file names where you know them, and mark guesses ("check the real handle name").
- **Verify:** the exact re-measurement and threshold that proves the fix worked, plus a manual QA list for anything the change could break.

Never write "optimize images". Write "serve `hero.png` (450 KiB) as AVIF at 1280 px".

## 10. Verification plan

Describe the before/after protocol: the same runs, 3x, compared by median. A fix counts only if the new median is outside the old range. Then add:

- a budgets table: today, target after P0, target after P1
- a reminder that the field window is about 28 days

## 11. Reproduce

List where the raw files are (git-ignored), the exact commands, and the sources and skills used.

## Writing rules

- Plain, specific sentences. No marketing tone.
- Tables carry the numbers; prose carries the reasoning.
- Each unit appears once per number (`1,906 ms`, `259 KiB`).
- Never include cookie values, analytics IDs, personal data or anything copied from the user's logged-in session.
