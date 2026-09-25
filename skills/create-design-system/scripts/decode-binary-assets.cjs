#!/usr/bin/env node
// ============================================================================
// decode-binary-assets.js
// ----------------------------------------------------------------------------
// Decodes the base64 JSON produced by fetch-binary-assets.browser.js into real
// binary files (fonts, favicon) on disk.
//
//   node decode-binary-assets.js <input.json> [outDir=assets]
//
// Run it in the FOREGROUND (never with run_in_background) so you SEE its output
// and catch problems immediately. It is fast — there is no reason to background it.
// ----------------------------------------------------------------------------
// This script is deliberately PARANOID. A previous run created ~600k 0-byte junk
// files because a double-encoded input was iterated character-by-character. The
// guards below make that outcome impossible: anything that doesn't look like a
// small map of "<path> -> base64-font" is REFUSED before a single file is written.
// ============================================================================

const fs = require("fs");
const path = require("path");

const inputFile = process.argv[2];
const outDir = process.argv[3] || "assets";
if (!inputFile) {
  console.error("Usage: node decode-binary-assets.js <input.json> [outDir=assets]");
  process.exit(1);
}

let data = JSON.parse(fs.readFileSync(inputFile, "utf8"));

// The browser_evaluate `filename` sink JSON-encodes the return value once. If the
// in-page code mistakenly returned a STRING (e.g. via JSON.stringify), the file is
// DOUBLE-encoded and one parse yields a string — parse again to recover the object.
if (typeof data === "string") data = JSON.parse(data);

// ---- SAFETY GUARDS -------------------------------------------------------
if (data === null || typeof data !== "object" || Array.isArray(data)) {
  console.error("ABORT: parsed input is not an object map (got " + typeof data + ").");
  process.exit(1);
}
const entries = Object.entries(data);
if (entries.length === 0) {
  console.error("ABORT: input object is empty.");
  process.exit(1);
}
// A real asset map has a handful of entries. Hundreds = almost certainly a
// mis-encoded string being iterated char-by-char. Refuse rather than spew junk.
if (entries.length > 200) {
  console.error(
    "ABORT: " + entries.length + " entries — far more than expected for assets. " +
    "The input is almost certainly mis-encoded (a string iterated character-by-character). " +
    "Nothing written."
  );
  process.exit(1);
}
for (const [key, val] of entries) {
  if (/^\d+$/.test(key)) {
    console.error('ABORT: key "' + key + '" is a bare number — mis-encoded input. Nothing written.');
    process.exit(1);
  }
  if (typeof val !== "string") {
    console.error('ABORT: value for "' + key + '" is not a string. Nothing written.');
    process.exit(1);
  }
  if (!val.startsWith("ERR:") && val.length < 64) {
    console.error('ABORT: value for "' + key + '" is too short to be a real asset (' + val.length + ' chars). Nothing written.');
    process.exit(1);
  }
}

// ---- WRITE ---------------------------------------------------------------
// Font/icon magic numbers for a sanity check (warn-only; we still write).
const FONT_SIGS = new Set([0x00010000, 0x4f54544f /*OTTO*/, 0x74727565 /*true*/, 0x774f4646 /*wOFF*/, 0x774f4632 /*wOF2*/]);

let written = 0, skipped = 0;
for (const [rel, b64] of entries) {
  if (b64.startsWith("ERR:")) {
    console.warn("SKIP (fetch error): " + rel + " -> " + b64);
    skipped++;
    continue;
  }
  const dest = path.join(outDir, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const buf = Buffer.from(b64, "base64");

  if (buf.length < 100) {
    console.warn("WARN: " + rel + " decoded to only " + buf.length + " bytes — looks wrong, skipping.");
    skipped++;
    continue;
  }
  // Validate fonts by magic bytes (favicons/PNG/SVG are exempt).
  const isFont = /\.(woff2?|ttf|otf)$/i.test(rel);
  if (isFont && buf.length >= 4 && !FONT_SIGS.has(buf.readUInt32BE(0))) {
    console.warn("WARN: " + rel + " has no known font signature (0x" + buf.readUInt32BE(0).toString(16) + ") — writing anyway, verify it.");
  }
  fs.writeFileSync(dest, buf);
  written++;
}

console.log("Done. Wrote " + written + " file(s), skipped " + skipped + ", into " + outDir + "/");
