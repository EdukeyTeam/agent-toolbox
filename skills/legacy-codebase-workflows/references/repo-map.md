# Local repository map

The source command is `scripts/repo_map.py`; first read [setup](setup.md). It requires no Aider chat session, LLM endpoint or model credentials. Runtime parsing uses installed native Tree-sitter grammars. The Aider-derived ranking favors definitions referenced elsewhere and lets focus affect priority.

```bash
python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/artifacts --budget 4096 --subtree src --focus-symbol ExampleService
```

For a large repository, start with inventory only. This needs only Python's standard library, not parser dependencies:

```bash
python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/inventory --inventory-only
```

Read the bounded `inventory_summary` on stdout (language counts and up to 20 module groups), rather than loading the full inventory into the agent context. Then choose a module from `inventory.json` and generate its symbol map. Inventory respects the same source, ignore and file-size policy. An ordinary Git module passed as the root retains its enclosing revision and ignore rules. A supplied root that its enclosing repository ignores entirely is treated as an independent source tree.

`--subtree`, `--focus-file`, `--focus-symbol` and `--exclude` are repeatable. CLI focus/subtree paths are relative to the repository; `./` prefixes and backslashes normalize to repository-relative slash paths. Discovered file paths and citation paths retain their literal identities: a POSIX filename `a\b.py` is distinct from `a/b.py`. Copy citation paths from inventory without normalizing them. Complete metadata lists focus files that were not parsed and focus symbols without definitions under `focus_not_found`. Focus prioritizes definitions; it does not prove the symbol exists or resolve overloads. Use direct source search when the map does not contain the target.

`--max-files` and `--max-file-bytes` bound inventory. Non-Git discovery additionally caps visited filesystem entries, including directories and ignored entries, at 100,000. It prunes ignored, secret and nonselected directories and bounds ignore files at 256 KB each and 2 MB total. The fallback supports scoped basic glob/negation rules: `target/` at any depth, `/dist` only at its ignore-file root, and nested ignore files within their own directories. An excluded parent is pruned, so a child negation cannot restore it without restoring the parent. Single-segment wildcards do not cross directory separators: `/*.java` matches only root Java files, and `docs/*.txt` matches only direct files in `docs`. Directory negations admit traversal without unignoring separately excluded children; `*`, `!*/`, `!*.java` admits only Java files. Recursive `**`, escaped patterns and significant trailing spaces remain unsupported. Git discovery de-duplicates index entries locally, without requiring `git ls-files --deduplicate`. Exceeding these discovery limits fails with unknown coverage instead of publishing a partial complete scan. Candidates with non-UTF-8 paths are counted, skipped before reading and reported with a lossy safe display; that display cannot be used as an exact original-path citation. Paths containing C0/C1 controls (0-31 or 127-159), NEL, or Unicode line/paragraph separators (U+2028/U+2029) are also counted and skipped before reading; their skip records use reversible JSON string-content escapes. They never enter map lines or tag caches. Inspect truncation/skips and narrow the subtree when limits apply. For a monorepo, map relevant modules separately and investigate edges between them. Output and caches must be outside the source repository.

## Save a named report

Both low-level implementations currently accept `--output-dir`, not `--output-file`, and write fixed `repo-map.md`, `inventory.json` and `map.meta.json` names. Separate staging directories avoid collisions. They reject generation inside the examined source tree; preserve that boundary.

After a complete map is generated, export it with the standard-library helper:

```bash
python /path/to/skill/scripts/export_repo_map.py /path/to/repository --artifact-dir /path/to/python-staging --implementation python --elapsed-seconds 1.23
```

The default is `<repository>/docs/repo-maps/repo-map.python.md`. Rust uses `--implementation rust`. Give an explicit path/name when saving multiple corpora or modules:

```bash
python /path/to/skill/scripts/export_repo_map.py /path/to/repository --artifact-dir /path/to/rust-staging --implementation rust --output-file /path/to/repository/docs/repo-maps/browser.rust.md --elapsed-seconds 0.42
```

These seconds are examples: supply the measured wall time of that particular generation, or omit the flag to report "not measured". The exporter does not measure a previous command retroactively. Export needs Python's standard library, even when the map itself was generated with the standalone Rust program. Use an existing interpreter; no parser packages are required for export.

The readable report includes examined revision, implementation, selected/parsed files, definitions found/included, budget, truncation, UTF-8 bytes, characters, estimated tokens for raw map and whole report, and supplied generation wall time. It saves adjacent `.raw.md`, `.meta.json` and `.inventory.json` copies. Original `map_sha256` continues to describe the raw map; report-specific details are namespaced under `export`. Existing destinations require explicit `--force`; a failed/incomplete-status map is not exported.

Publication is per file, not a transaction across the four-file evidence set. Hard-link publication and replacement are atomic per file; when hard links are unsupported, exclusive creation prevents overwriting but exposes partial bytes while copying. A forced update stages all data, removes the old report before replacing sidecars, and publishes the report last. If publication fails, regenerate or explicitly replace the incomplete export before relying on it. Concurrent exports to the same destination are unsupported.

Honor user destination overrides. For read-only repositories ask for a writable destination. Report exact output paths instead of leaving the human to find temporary files. Exclude `docs/repo-maps` (or another in-repository export directory) from subsequent root inventories with `--exclude docs/repo-maps/*`, or select only the application subtree. Exported reports are snapshots; fingerprints and revisions must be refreshed after source changes. If committing reports, preserve generated bytes with scoped Git attributes (for example, disable text conversion for the report and raw map) and verify their hashes after checkout; automatic newline conversion invalidates saved hashes.

### Compare generation time honestly

Measure the entire subprocess with a monotonic clock, including imports, source reads, parsing, ranking and writes. Record implementation/version, source revision, scope, budget and machine/platform. Run at least five samples per implementation and alternate execution order. Use a fresh output directory per cold-output sample, then rerun that directory for a warm-output sample; Rust has no tag cache. State that this does not flush OS filesystem caches. Compare medians, give the sample count and range, and calculate `Python median / Rust median` separately for cold and warm runs. Do not compare a Python run on one platform against Rust on another as a speed claim.

Rust's `--timings` adds internal phase times to stdout; it does not put timing in the current map metadata. Python currently has no equivalent CLI timing flag. Keep raw measurements in a separate benchmark JSON and supply the matching individual wall time to each export. Header overhead makes the whole report's character estimate larger than the raw map's selection-budget estimate.

## Read the three outputs

| Output | Use |
| --- | --- |
| `repo-map.md` | Ranked original-source lines with relative paths and original line numbers. |
| `inventory.json` | Files, content hashes, language/kind, examined revision and working-copy fingerprint. |
| `map.meta.json` | Selection, limits, coverage, skipped files, parse failures, descriptors, truncation and dependency versions. |

Metadata `status` distinguishes `complete`, `inventory-only`, `in-progress` and `failed`. `complete` means processing succeeded, not that the map is exhaustive: a budget-limited map omits definitions, and `--max-files` is a soft selection cap that returns complete/truncated with a wildcard skip reason. Hard discovery/ignore-file limits fail instead. Check coverage, skips and truncation independently of status. A failed inventory invalidates earlier artifacts and reports unknown coverage. A failed parse/rank/render retains the fresh inventory and records the failure stage, while replacing any old symbol map with a diagnostic. Do not use a map unless status is `complete`. A full graph is capped at 200,000 edges and 200,000 tags; map a subtree if either limit is reached.

Map snippets replace control characters and Unicode line/paragraph separators with spaces; tabs and LF-based original line numbers are preserved. This display cleanup leaves original source hashes and citation text unchanged.

Budget units are estimated tokens using `ceil(Unicode characters / 4)`. This enforces a text-size bound, not a model's tokenizer count or billing cost. Check the metadata's estimator. A short map deliberately omits definitions; it is not a complete repository index.

The audited queries cover Java, Python, JavaScript, TypeScript/TSX, C/C++, C#, Go and Rust. Unsupported text remains visible in inventory where eligible. XML/properties/build descriptors have separate inventory entries; inspect them directly for registration, reflection and resource wiring. Syntax queries do not establish a resolved runtime call graph.

JSON tag caches are outside source and keyed by content/query hashes and actual parser package versions. C# additionally uses the separately installed `tree-sitter-c-sharp` version; upgrading that grammar invalidates C# tags independently of the language-pack version. Recreate artifacts after source or revision changes; a map is a snapshot, not a live view. Generation leaves target source and its existing caches untouched.

## Verify citations

Create a JSON evidence file with a `citations` array. Each card has `path` (relative original source), `sha256` (original file bytes), `start_line`, `end_line` (inclusive, one-based), and `quote` (a short exact quotation from those lines). A claim/observed-or-inferred field can accompany the card for human review.

```bash
python /path/to/skill/scripts/check_citations.py /path/to/repository /path/to/artifacts/evidence.json
```

The checker counts LF/CRLF source lines and normalizes CRLF quotations to LF while hashing the original bytes. The citation array must be nonempty.

Exit 0 means the checked citations match current source; exit 1 means at least one is invalid/stale; exit 2 means malformed input or an operational error. Read the machine-readable output. An empty citation set supplies no evidence. Matching quotations do not prove a claim or search completeness.

Before editing, inspect original bodies and callers for the affected behavior. To state that an API is absent, record the actual search command, directories and relevant configuration/dependencies searched. Do not infer absence from a budgeted map.
