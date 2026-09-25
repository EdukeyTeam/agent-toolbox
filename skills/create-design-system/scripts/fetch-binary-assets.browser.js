// ============================================================================
// fetch-binary-assets.browser.js
// ----------------------------------------------------------------------------
// Run this INSIDE the page via mcp__playwright__browser_evaluate, and ALWAYS
// pass a `filename` arg (e.g. "binary-assets.json") so the (large) base64 result
// is written to a file and does NOT flood the agent's context.
//
//   mcp__playwright__browser_evaluate({
//     function: <contents of this file>,
//     filename: "binary-assets.json"
//   })
//
// It returns an OBJECT mapping  "<subdir>/<filename>" -> base64 string, covering:
//   - self-hosted @font-face fonts (woff2/woff/ttf/otf) under "fonts/<family>/..."
//   - the favicon under "favicon.ico" (or the right extension)
//
// ----------------------------------------------------------------------------
// WHY AN OBJECT, NOT JSON.stringify(...) ?  (read this — it caused a real incident)
// The browser_evaluate `filename` sink JSON-encodes the return value EXACTLY ONCE.
//   - Return an OBJECT  -> file is a normal JSON object -> JSON.parse() once = object. GOOD.
//   - Return a STRING (e.g. JSON.stringify(obj)) -> file is a JSON *string of JSON*
//     (double-encoded) -> JSON.parse() once yields a STRING, and iterating that
//     string with Object.entries() gives one entry PER CHARACTER. A naive decoder
//     then writes hundreds of thousands of 0-byte files named "0","1","2",...
// So: return the object directly. The companion decode-binary-assets.js also
// defends against the double-encoding just in case, but don't rely on luck.
// ----------------------------------------------------------------------------
// SAME-ORIGIN ONLY: in-page fetch() can read the site's OWN assets. Cross-origin
// font CDNs (e.g. fonts.gstatic.com, Adobe Typekit) are usually CORS-blocked and
// will come back as "ERR:..." — that's expected; don't try to work around it.
// ============================================================================

async () => {
  const result = {};

  // ---- 1. Self-hosted @font-face fonts -------------------------------------
  const faces = [];
  for (const sheet of document.styleSheets) {
    const base = sheet.href || location.href;
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; } // cross-origin stylesheet
    for (const rule of rules) {
      if (rule.type !== CSSRule.FONT_FACE_RULE) continue;
      const fam = rule.style.getPropertyValue("font-family").replace(/["']/g, "").trim();
      const src = rule.style.getPropertyValue("src");
      // first real font-file url; prefer modern formats by trying them in order
      const m =
        src.match(/url\(["']?([^"')]+\.woff2)(?:\?[^"')]*)?["']?\)/i) ||
        src.match(/url\(["']?([^"')]+\.woff)(?:\?[^"')]*)?["']?\)/i) ||
        src.match(/url\(["']?([^"')]+\.(?:ttf|otf))(?:\?[^"')]*)?["']?\)/i);
      if (!m) continue;
      let url;
      try { url = new URL(m[1], base).href.split("?")[0]; } catch (e) { continue; }
      faces.push({ fam, url });
    }
  }
  // de-duplicate by url
  const seenUrl = new Set();
  const fonts = faces.filter(f => (seenUrl.has(f.url) ? false : (seenUrl.add(f.url), true)));

  const toB64 = (bytes) => {
    let bin = "";
    const CHUNK = 0x8000; // chunk to avoid call-stack overflow on big buffers
    for (let i = 0; i < bytes.length; i += CHUNK) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(bin);
  };

  for (const { fam, url } of fonts) {
    const slug = (fam.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")) || "font";
    const file = url.split("/").pop();
    const key = `fonts/${slug}/${file}`;
    try {
      const res = await fetch(url);
      if (!res.ok) { result[key] = "ERR:" + res.status; continue; }
      result[key] = toB64(new Uint8Array(await res.arrayBuffer()));
    } catch (e) {
      result[key] = "ERR:" + (e && e.message);
    }
  }

  // ---- 2. Favicon ----------------------------------------------------------
  const iconEl = document.querySelector('link[rel*="icon"]');
  if (iconEl && iconEl.href) {
    try {
      const url = iconEl.href.split("?")[0];
      const ext = (url.split(".").pop() || "ico").toLowerCase();
      const res = await fetch(url);
      if (res.ok) {
        result["favicon." + (/(ico|png|svg)/.test(ext) ? ext : "ico")] =
          toB64(new Uint8Array(await res.arrayBuffer()));
      } else {
        result["favicon.ico"] = "ERR:" + res.status;
      }
    } catch (e) {
      result["favicon.ico"] = "ERR:" + (e && e.message);
    }
  }

  // Return the OBJECT (NOT a stringified string). See header note.
  return result;
}
