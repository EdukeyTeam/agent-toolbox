---
name: create-design-system
description: Extract a design system from any website URL by driving a real browser with the Playwright CLI. Produces design tokens (JSON), brand assets (logo SVG, favicon), a homepage screenshot, and a design-guidelines.md document. Use when the user wants to clone, match, or stay consistent with an external brand.
allowed-tools: Bash(playwright-cli:*), Bash(pnpm exec playwright-cli:*), Bash(node:*), Read, Write
---

# Create Design System from Website

Extract design tokens and brand assets from any website and save them as structured files for use by agents building UIs consistent with that brand.

---

## Prerequisites

This skill drives `playwright-cli`, not the Playwright MCP server: the CLI writes big
results (snapshots, evaluation output) to files instead of the context window, which is
the difference between a cheap run and an expensive one.

Use the installed `playwright-cli` with one named session so commands share a browser.
The examples use `playwright-cli -s=design`. If the project provides its own copy,
use its runner (for example, `pnpm exec playwright-cli -s=design`) in each command.
Do not rely on a shell alias persisting between agent calls. Close the session with
`playwright-cli -s=design close` when finished.

---

## Process

### Step 1 — Prepare output directories

Create the required directories before starting:

```bash
mkdir -p assets docs
```

### Step 2 — Navigate and dismiss overlays

> ⚠️ **MUST DO — dismiss every cookie banner / modal / overlay covering the page BEFORE you screenshot or extract styles.** This is the single most common failure of this skill. An overlay both skews computed styles and ruins the screenshot.

Open the browser on the URL. Use `--browser=chrome` if system Chrome is installed;
otherwise use the browser configured for Playwright CLI:

```bash
playwright-cli -s=design open <URL> --browser=chrome
```

**Cookie/consent banners frequently load on a DELAY and are NOT present in the first snapshot.** (Real example: a banner appeared only several seconds after load and silently ended up in the screenshot.) So:

1. Wait for a delayed banner to mount. There is no `wait` command; use `run-code`:
   ```bash
   playwright-cli -s=design run-code "async page => await page.waitForTimeout(3000)"
   ```
2. Search for the banner instead of reading a whole snapshot. `find` returns only matching nodes with context, which costs a fraction of the tokens:
   ```bash
   playwright-cli -s=design find --regex "/cookie|consent|accept|akceptuj|zgadzam/i"
   ```
3. Snapshot just the banner region by its ref to see the exact buttons:
   ```bash
   playwright-cli -s=design snapshot e945
   ```
4. Click the accept button by ref. Common labels: "Accept", "Accept all", "Accept All Cookies", "OK", "I agree", "Allow all", and Polish: "Akceptuj", "Akceptuj wszystkie", "Zgadzam się", "Rozumiem".
   ```bash
   playwright-cli -s=design click e955
   ```
5. **Confirm it is gone** before continuing — re-run `find` for the button label and expect no matches:
   ```bash
   playwright-cli -s=design find --regex "/Accept All Cookies/i"
   ```
6. Also dismiss any tooltip / onboarding / newsletter popups that appear after consent.

Every command prints a snapshot link (`.playwright-cli/page-<timestamp>.yml`) rather than the snapshot itself. Read or grep that file only if `find` was not enough.

### Step 3 — Take the homepage screenshot

> 🛑 **STOP — re-check for overlays first (yes, again).** Before this screenshot, take one more snapshot and confirm NO cookie banner, modal, or popup is covering content. Banners load on a delay, so even if the page looked clean in Step 2 one may have appeared since. If anything is covering the page, dismiss it (Step 2) and only then screenshot.

```bash
playwright-cli -s=design screenshot --filename=assets/homepage.png --full-page
```

After saving, **open `assets/homepage.png` with an available image viewer and visually verify** there is no banner/overlay strip across it. If there is, dismiss it and retake — do not move on with a polluted screenshot.

### Step 4 — Extract design tokens via eval (run in multiple small calls)

Each call below is a JavaScript arrow function passed to `playwright-cli -s=design eval`. Keep the three calls separate: a single mega-call is hard to debug and its output is hard to read.

Small results can print inline; anything sizeable should go to a file with `--filename` so it never enters the context window:

```bash
playwright-cli -s=design eval "<the arrow function below>" --filename=tokens-a.json
```

`--filename` writes the returned value as real JSON (an object stays an object), so inspect it with the agent's file-reading tool or `node -e`.

#### Call A — Core element styles

```js
() => {
  const getStyles = (el) => {
    if (!el) return null;
    const s = getComputedStyle(el);
    return {
      color: s.color,
      backgroundColor: s.backgroundColor,
      fontFamily: s.fontFamily,
      fontSize: s.fontSize,
      fontWeight: s.fontWeight,
      padding: s.padding,
      margin: s.margin,
      borderRadius: s.borderRadius,
      lineHeight: s.lineHeight,
    };
  };
  return {
    body: getStyles(document.body),
    header: getStyles(document.querySelector('header') || document.querySelector('[class*="header"]')),
    nav: getStyles(document.querySelector('nav')),
    h1: getStyles(document.querySelector('h1')),
    h2: getStyles(document.querySelector('h2')),
    link: getStyles(document.querySelector('a')),
  };
}
```

#### Call B — Colors, radius, buttons

```js
() => {
  const allEls = document.querySelectorAll('*');
  const bgColors = new Set(), textColors = new Set(), borderRadii = new Set();
  for (let i = 0; i < Math.min(allEls.length, 500); i++) {
    const s = getComputedStyle(allEls[i]);
    if (s.backgroundColor !== 'rgba(0, 0, 0, 0)') bgColors.add(s.backgroundColor);
    textColors.add(s.color);
    if (s.borderRadius !== '0px') borderRadii.add(s.borderRadius);
  }

  // Buttons with non-transparent backgrounds
  const btnStyles = [];
  for (const btn of document.querySelectorAll('button, [class*="btn"], a[class*="button"]')) {
    const s = getComputedStyle(btn);
    if (s.backgroundColor !== 'rgba(0, 0, 0, 0)') {
      btnStyles.push({
        text: btn.innerText?.trim().substring(0, 30),
        bg: s.backgroundColor, color: s.color,
        borderRadius: s.borderRadius, padding: s.padding,
        fontSize: s.fontSize, fontWeight: s.fontWeight,
        border: s.border
      });
      if (btnStyles.length >= 5) break;
    }
  }
  return {
    uniqueBackgrounds: [...bgColors],
    uniqueTextColors: [...textColors],
    uniqueBorderRadii: [...borderRadii],
    btnStyles
  };
}
```

#### Call C — Logo, favicon, fonts

```js
() => {
  // Logo: look in header .logo or [class*="logo"] — NOT country flag selectors
  const logoEl = document.querySelector('header .logo') ||
                 document.querySelector('[class*="header"] [class*="logo"]');
  const logoSVG = logoEl?.innerHTML?.trim() ?? null;

  // Favicon href
  const favicon = document.querySelector('link[rel*="icon"]');

  // Font faces from CSS rules
  const fontFaces = [];
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) {
        if (rule.type === CSSRule.FONT_FACE_RULE) {
          fontFaces.push(rule.cssText.substring(0, 300));
        }
      }
    } catch(e) {}
  }

  // Nav links
  const navLinks = [...document.querySelectorAll('nav a')].slice(0, 5).map(a => ({
    text: a.innerText?.trim().substring(0, 30),
    color: getComputedStyle(a).color,
    fontWeight: getComputedStyle(a).fontWeight,
    textTransform: getComputedStyle(a).textTransform,
  }));

  return {
    logoSVG: logoSVG?.substring(0, 3000),
    faviconHref: favicon?.href ?? null,
    fontFaces: fontFaces.slice(0, 8),
    navLinks
  };
}
```

### Step 5 — Save brand assets

**Logo SVG:** If `logoSVG` was found, save it directly:

```js
Write({ file_path: "assets/logo.svg", content: `<svg ...>...</svg>` })
```

**Favicon + custom fonts (binary assets):** Download these with the in-page fetch helper, NOT with shell downloaders.

> Use the browser helper in **Step 5b** to fetch same-origin assets when direct downloads are unavailable. Respect the permissions of the agent environment and the site's asset rights.

To grab just the favicon you can run the helper (it also handles fonts — see Step 5b) and keep `favicon.*` from its output.

### Step 5b — Download custom/self-hosted fonts (only if the site provides them)

**When to do this:** ONLY when the site serves its **own custom fonts** via self-hosted `@font-face` rules (font files on the site's origin, e.g. `…/themes/site/fonts/Brand-Regular.woff2`). Skip it when the site only uses:
- generic system fonts (`Arial`, `-apple-system`, `Segoe UI`, …), or
- a third-party CDN you can't fetch same-origin (e.g. `fonts.gstatic.com`, Adobe Typekit) — these are CORS-blocked and not "fonts provided by the website" to redistribute.

If the `fontFaces` you collected in Step 4 / Call C point at real font files on the site's domain, download them:

1. **Fetch all binary assets in-page** (fonts + favicon), writing the base64 to a FILE so it never floods context. Locate the installed directory containing this `SKILL.md` and replace `/absolute/path/to/create-design-system` below with that directory; do not assume the skill is installed inside the project. Pass the helper script straight into `eval`:
   ```bash
   playwright-cli -s=design eval "$(cat "/absolute/path/to/create-design-system/scripts/fetch-binary-assets.browser.js")" --filename=binary-assets.json
   ```
   The script **returns an object** `{ "fonts/<family>/<file>": "<base64>", "favicon.ico": "<base64>" }`.

2. **Decode to real files** with the Node helper (run in the FOREGROUND so you see its output):
   ```bash
   node "/absolute/path/to/create-design-system/scripts/decode-binary-assets.cjs" binary-assets.json assets
   ```
   It writes `assets/fonts/<family>/*` and `assets/favicon.*`, then prints how many files it wrote.

3. **Verify and clean up:**
   ```bash
   find assets/fonts -name '*.woff2' -o -name '*.ttf' -o -name '*.otf' -o -name '*.woff' | wc -l
   ls -la assets/fonts/*/    # sizes should be tens–hundreds of KB, never 0 bytes
   ```
   Delete the temporary `binary-assets.json` when done.

> 🧨 **Learn from this incident — read before writing your own decode loop.** If the in-page code returns a *string* (e.g. `JSON.stringify(obj)`), the saved file can end up **double-encoded** (a JSON string of JSON). A naive `JSON.parse(file)` then yields a *string*, and `Object.entries(string)` iterates **one entry per character** — a previous run wrote **~600,000 zero-byte files** named `0`,`1`,`2`,… into `assets/fonts/`. The provided helpers prevent this two ways: (a) `fetch-binary-assets.browser.js` returns an **object**, not a stringified string; (b) `decode-binary-assets.cjs` re-parses if it still sees a string AND **refuses to write** if there are >200 entries, numeric keys, or values too short to be a font. **Always prefer the helpers. If you must hand-roll, replicate those guards, and never run the decoder in the background.**

> 📜 **Tell the user about asset rights (REQUIRED).** Custom fonts and logos may be licensed. In your final response to the user, identify the downloaded fonts and logos and ask them to verify usage rights before using or redistributing those assets. Do not assume fonts, logos, or other brand assets are free to reuse or redistribute.

### Step 6 — Build design-tokens.json

Map the extracted values into a structured JSON. Follow this schema:

```json
{
  "colors": {
    "brand": { "primary": "#...", "accent": "#...", "error": "#...", "success": "#..." },
    "background": { "default": "#fff", "light": "#...", "overlay": "rgba(...)" },
    "text": { "primary": "#...", "secondary": "#...", "muted": "#...", "onDark": "#fff" }
  },
  "typography": {
    "fontFamily": { "primary": "\"Font Name\", Arial, sans-serif" },
    "fontWeights": { "regular": 400, "medium": 500, "semibold": 600, "bold": 700 },
    "fontSize": { "sm": "12px", "base": "14px", "md": "16px", "lg": "20px", "xl": "24px" },
    "lineHeight": { "tight": "1.2", "base": "1.4", "relaxed": "1.6" }
  },
  "spacing": {
    "1": "4px", "2": "8px", "3": "12px", "4": "16px",
    "5": "20px", "6": "24px", "7": "28px", "8": "32px"
  },
  "borderRadius": {
    "none": "0px", "sm": "4px", "md": "8px", "lg": "16px",
    "full": "999px", "circle": "50%"
  },
  "components": {
    "button": { "primary": { "backgroundColor": "#...", "color": "#...", "padding": "...", "borderRadius": "..." } },
    "header": { "backgroundColor": "#...", "padding": "...", "fontSize": "..." },
    "nav": { "color": "#...", "fontSize": "...", "fontWeight": "..." }
  }
}
```

Save as `assets/design-tokens.json`.

### Step 7 — Write docs/design-guidelines.md

The guidelines document must include:

1. **Assets table** — links to all saved files relative to `docs/`
2. **Colors section** — token name, hex, usage
3. **Typography section** — font family (with @font-face details), weight scale, size scale. **If custom fonts were downloaded (Step 5b), list each downloaded file and its repo path under `assets/fonts/…`** so agents know the fonts exist locally and can be used in the app — and add a one-line note that their license must be verified before use.
4. **Spacing section** — base unit and common values
5. **Border radius section** — all radii with usage context
6. **Components section** — header, nav, button, inputs, promo bar etc.
7. **Logo usage** — how/where to use the SVG, inverted variant on dark bg
8. **Visual style summary** — 3–5 sentences describing the brand personality

Save as `docs/design-guidelines.md`.

### Step 8 — Verify and hand off

Delete temporary files (e.g. `binary-assets.json`, snapshot dumps), confirm no junk slipped into `assets/`, and review the generated files with the user. In a Git repository, check `git status --short` so unrelated changes are not included. Commit only when the user requested a commit and the repository's contribution process permits it.

---

## Common Pitfalls and Fixes

| Issue | Fix |
|---|---|
| `eval` result floods the context | Add `--filename=<file>.json` and read the file back, rather than printing it |
| Logo selector returns country flag image | Use `header .logo` or `[class*="header"] [class*="logo"]` — the wordmark is usually an inline SVG, not `<img>` |
| No `wait` command in the CLI | Use `playwright-cli -s=design run-code "async page => await page.waitForTimeout(3000)"` |
| `eval` fails with `SyntaxError: Unexpected token ';'` | The argument must be an *expression*. A script file ending in `};` breaks it — the helper script deliberately ends in `}` with no semicolon |
| Decoder dies with `require is not defined in ES module scope` | In projects using ES modules, run the provided `.cjs` helper rather than changing its extension |
| Snapshot too large to read | Use `playwright-cli -s=design find "<text>"` or `playwright-cli -s=design find --regex "/pattern/i"` — it returns only matching nodes with context |
| Direct asset downloads are denied | Fetch same-origin assets in-page with `scripts/fetch-binary-assets.browser.js`, then decode with `scripts/decode-binary-assets.cjs` |
| Cookie banner missed — ends up in the screenshot | It loads on a **delay** and is absent from the first snapshot. Wait 3s → `find` the banner → dismiss → `find` again and expect no matches, THEN screenshot. Also visually inspect the saved PNG to confirm it is clean. |
| Cookie consent dialog never dismissed | Always check for and click "Accept all" / "OK" / "Akceptuj wszystkie" before extracting styles — overlays produce incorrect computed styles |
| Decode created hundreds of thousands of 0-byte files | The `filename` sink double-encodes a *string* return. Return an **object** from the in-page script; the decoder must re-parse a string AND refuse >200 entries / numeric keys. Use the provided helpers; never `run_in_background` the decoder. |
| Verifying only the subfolders you expected | After downloading fonts, check the **parent** dir too (`find assets/fonts -maxdepth 1 -type f | wc -l`). Junk files land at the top level and a subfolder-only `ls` hides them. |
| Computed style returns `rgba(0, 0, 0, 0)` for bg | This means transparent — skip these when building color palettes |
| Fonts show as `Arial` instead of brand font | Check `@font-face` rules in stylesheets — the brand font may load as a custom alias (e.g., `Euclid` = Euclid Circular B) |

---

## Output Files

All files are saved to the project root:

```
assets/
  homepage.png           # Full-page screenshot (no overlays!)
  logo.svg               # Brand wordmark (extracted from DOM)
  favicon.ico            # Favicon binary
  design-tokens.json     # Structured design tokens
  fonts/                 # Self-hosted custom fonts (only if the site provides them)
    <family>/            #   e.g. brygada-1918/, libre-franklin/
      *.woff2 / *.ttf    #   downloaded font files
docs/
  design-guidelines.md   # Human-readable design system reference
```
