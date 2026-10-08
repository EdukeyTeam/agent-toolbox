# Local repository map

Use `legacy-repo-map`, the native Rust mapper, by default. First run [native setup](setup.md#native-binary) and use the verified `program` path returned by `setup_native.py status`; the paths below represent that program, not an assumed PATH installation. It needs no Aider chat session, LLM endpoint, model credentials or Python parser environment. Embedded Tree-sitter grammars parse source; Aider-derived ranking favors definitions referenced elsewhere and lets focus affect priority.

```bash
/path/returned/as/program /path/to/repository --output-dir /path/to/artifacts --budget 16384 --subtree src --focus-symbol ExampleService
```

For a large repository, start with inventory only. The native command needs no additional dependencies:

```bash
/path/returned/as/program /path/to/repository --output-dir /path/to/inventory --inventory-only
```

Read the bounded `inventory_summary` on stdout (language counts and up to 20 module groups), rather than loading the full inventory into the agent context. Then choose a module from `inventory.json` and generate its symbol map. Inventory respects the same source, ignore and file-size policy. An ordinary Git module passed as the root retains its enclosing revision and ignore rules. A supplied root that its enclosing repository ignores entirely is treated as an independent source tree.

`--subtree`, `--focus-file`, `--focus-symbol` and `--exclude` are repeatable. CLI focus/subtree paths are relative to the repository; `./` prefixes and backslashes normalize to repository-relative slash paths. Discovered file paths and citation paths retain their literal identities: a POSIX filename `a\b.py` is distinct from `a/b.py`. Copy citation paths from inventory without normalizing them. Complete metadata lists focus files that were not parsed and focus symbols without definitions under `focus_not_found`. Focus prioritizes definitions; it does not prove the symbol exists or resolve overloads. Use direct source search when the map does not contain the target.

`--max-files` and `--max-file-bytes` bound inventory. Non-Git discovery additionally caps visited filesystem entries, including directories and ignored entries, at 100,000. It prunes ignored, secret and nonselected directories and bounds ignore files at 256 KB each and 2 MB total. The fallback supports scoped basic glob/negation rules: `target/` at any depth, `/dist` only at its ignore-file root, and nested ignore files within their own directories. An excluded parent is pruned, so a child negation cannot restore it without restoring the parent. Single-segment wildcards do not cross directory separators: `/*.java` matches only root Java files, and `docs/*.txt` matches only direct files in `docs`. Directory negations admit traversal without unignoring separately excluded children; `*`, `!*/`, `!*.java` admits only Java files. Recursive `**`, escaped patterns and significant trailing spaces remain unsupported. Git discovery de-duplicates index entries locally, without requiring `git ls-files --deduplicate`. Exceeding these discovery limits fails with unknown coverage instead of publishing a partial complete scan. Candidates with non-UTF-8 paths are counted, skipped before reading and reported with a lossy safe display; that display cannot be used as an exact original-path citation. Paths containing C0/C1 controls (0-31 or 127-159), NEL, or Unicode line/paragraph separators (U+2028/U+2029) are also counted and skipped before reading; their skip records use reversible JSON string-content escapes. They never enter map lines or tag caches. Inspect truncation/skips and narrow the subtree when limits apply. For a monorepo, map relevant modules separately and investigate edges between them. Output and caches must be outside the source repository.

## Extraction, selection and readable context

A definition is a query-captured symbol declaration: a class, function/method, or an eligible variable/constant/type alias. An assignment such as `request_started = signal(...)` defines a name; it is not another function. `definitions_found` counts extracted, admitted tags. `definitions_in_map` counts selected declarations actually represented. Graph rank favors referenced identifiers and their files, then explicit focus; it is a navigation heuristic, not a measure of architectural correctness.

The default `--format grouped` renders one file heading, enclosing declarations/base types, and complete multiline signatures through their body opener. Original line labels identify the source; gaps are explicit. Declaration snippets are bounded at 80 lines/8000 characters and clipping is recorded. Class-purpose docstrings and method bodies are not supplied as a substitute for source reading. `--format lines` preserves the earlier one-line diagnostic format for comparisons.

The default budget is **16,384 estimated tokens**. Both implementations accept budgets up to 1,000,000; this is a text-size safety limit, not a declaration that a model has that much available context. A compact map deliberately omits definitions. Raising the budget or mapping a module includes more; it does not repair missing parser/query support. For a complete captured-definition index:

```bash
/path/returned/as/program /path/to/repository --subtree src --output-dir /path/to/full-staging --all-definitions --budget 65536
```

Complete-definition mode fails if the rendered result exceeds its budget or the scan/parse cannot establish its contract; use the reported required estimate to select a sufficient budget. Every capture eligible under the declared policy is required, while unsupported languages/constructs remain outside that claim. Captured identifiers above the 512-character safety limit and distinct declarations that collide under the historical same-file/line/name identity are rejected in complete mode instead of silently disappearing. Complete mode also rejects captured names hidden by the legacy format’s first-line/240-character limit; select grouped rendering in that case. For example the current TypeScript query does not capture `const` arrow functions. Check inventory and query limitations before making absence claims.

This is an adaptation of Aider, not its complete implementation. Aider's original [source](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py) uses `grep_ast.TreeContext`, chat-aware focus, tokenizer-based budget estimates and ranked-prefix search. This tool retains adapted PageRank/query ideas but uses explicit focus, bounded local policy, deterministic ordering and a character budget. Its grouped renderer is implemented locally using the existing Tree-sitter ASTs; it does not claim byte parity with Aider output. [Aider's documentation](https://aider.chat/docs/repomap.html) shows parent context and explains why its examples also omit less relevant definitions.

## Save a named report

Both low-level implementations currently accept `--output-dir`, not `--output-file`, and write fixed `repo-map.md`, `inventory.json` and `map.meta.json` names. Separate staging directories avoid collisions. They reject generation inside the examined source tree; preserve that boundary.

After a complete map is generated, export it with the standard-library helper:

```bash
python /path/to/skill/scripts/export_repo_map.py /path/to/repository --artifact-dir /path/to/rust-staging --implementation rust --elapsed-seconds 0.42
```

With `--implementation rust`, the default is `<repository>/docs/repo-maps/repo-map.rust.md`. Give an explicit path/name when saving multiple corpora or modules:

```bash
python /path/to/skill/scripts/export_repo_map.py /path/to/repository --artifact-dir /path/to/rust-staging --implementation rust --output-file /path/to/repository/docs/repo-maps/browser.rust.md --elapsed-seconds 0.42
```

These seconds are examples: supply the measured wall time of that particular generation, or omit the flag to report "not measured". The exporter does not measure a previous command retroactively. Export needs Python's standard library, even when the map itself was generated with the standalone Rust program. Use an existing interpreter; no parser packages are required for export.

The readable report includes examined revision, implementation, selected/parsed files, definitions found/included, budget, truncation, UTF-8 bytes, characters, estimated tokens for raw map and whole report, and supplied generation wall time. It keeps the readable report at the chosen path and saves `.raw.md`, `.meta.json` and `.inventory.json` under `<report-parent>/artifacts/<report-stem>/`. Use `--evidence-dir` to override that evidence destination (including adjacent sidecars for a legacy layout); report paths identify the saved evidence. The evidence directory cannot overlap generation staging. Original `map_sha256` continues to describe the raw map; report-specific details are namespaced under `export`. Existing destinations require explicit `--force`; a failed/incomplete-status map is not exported.

Publication is per file, not a transaction across the four-file evidence set. Hard-link publication and replacement are atomic per file; when hard links are unsupported, exclusive creation prevents overwriting but exposes partial bytes while copying. A forced update stages all data, removes the old report before replacing sidecars, and publishes the report last. If publication fails, regenerate or explicitly replace the incomplete export before relying on it. Concurrent exports to the same destination are unsupported.

Honor user destination overrides. For read-only repositories ask for a writable destination. Report exact output paths instead of leaving the human to find temporary files. Exclude `docs/repo-maps` (or another in-repository export directory) from subsequent root inventories with `--exclude docs/repo-maps/*`, or select only the application subtree. Exported reports are snapshots; fingerprints and revisions must be refreshed after source changes. If committing reports, preserve generated bytes with scoped Git attributes (for example, disable text conversion for the report and raw map) and verify their hashes after checkout; automatic newline conversion invalidates saved hashes.

### Compare generation time honestly

Measure the entire subprocess with a monotonic clock, including imports, source reads, parsing, ranking and writes. Record implementation/version, source revision, scope, budget and machine/platform. Run at least five samples per implementation and alternate execution order. Use a fresh output directory per cold-output sample, then rerun that directory for a warm-output sample; Rust has no tag cache. State that this does not flush OS filesystem caches. Compare medians, give the sample count and range, and calculate `Python median / Rust median` separately for cold and warm runs. Do not compare a Python run on one platform against Rust on another as a speed claim.

Rust's `--timings` adds internal phase times to stdout; it does not put timing in the current map metadata. Python currently has no equivalent CLI timing flag. Keep raw measurements in a separate benchmark JSON and supply the matching individual wall time to each export. Header overhead makes the whole report's character estimate larger than the raw map's selection-budget estimate.

## Use the map for the task

Keep one current overview in `docs/repo-maps`, plus a larger complete-definition index when useful. Place historical comparisons, raw maps, sidecars and review notes in `artifacts`. When repository instruction edits are authorized, add a short `AGENTS.md` pointer after first generation, for example: "For unfamiliar source navigation, read `docs/repo-maps/repo-map.rust.md`; use the full index for omitted symbols, then verify original bodies/callers before editing. Refresh these snapshots after path/signature changes." Adapt the scope/name to the actual report and update the existing pointer rather than duplicating it.

Next, use the map to locate entry points, ownership and likely neighboring modules. Read those definitions, callers and wiring for the user's question. For an authorized documentation task, write or update only the relevant architecture/workflow pages with source evidence. For implementation, select the smallest change slice and follow the repository's test/verification instructions. Repomix can then pack that public or permitted source slice; local retrieval can search bodies/docs. A map can shorten discovery but cannot prove behavior from signatures or replace every file read with a global summary.

Keep private maps and packed source out of public Git history. A gitignore addition does not untrack earlier files or remove an already committed ancestor; fix local unpublished history before publishing, preserving the user's files.

## Read the three outputs

| Output | Use |
| --- | --- |
| `repo-map.md` | Grouped original declaration snippets, enclosing context, relative paths and original line numbers; legacy lines remain explicit. |
| `inventory.json` | Files, content hashes, language/kind, examined revision and working-copy fingerprint. |
| `map.meta.json` | Selection, limits, coverage, skipped files, parse failures, descriptors, truncation and dependency versions. |

Metadata `status` distinguishes `complete`, `inventory-only`, `in-progress` and `failed`. `complete` means processing succeeded, not that the map is exhaustive: a budget-limited map omits definitions, and `--max-files` is a soft selection cap that returns complete/truncated with a wildcard skip reason. Hard discovery/ignore-file limits fail instead. Check coverage, skips and truncation independently of status. A failed inventory invalidates earlier artifacts and reports unknown coverage. A failed parse/rank/render retains the fresh inventory and records the failure stage, while replacing any old symbol map with a diagnostic. Do not use a map unless status is `complete`. A full graph is capped at 200,000 edges and 200,000 tags; map a subtree if either limit is reached.

Map snippets replace control characters and Unicode line/paragraph separators with spaces; tabs and LF-based original line numbers are preserved. This display cleanup leaves original source hashes and citation text unchanged.

Budget units are estimated tokens using `ceil(Unicode characters / 4)`. This enforces a text-size bound, not a model's tokenizer count or billing cost. Check the metadata's estimator. A short map deliberately omits definitions; it is not a complete repository index.

The audited queries cover Java, Python, JavaScript, TypeScript/TSX, C/C++, C#, Go and Rust. Unsupported text remains visible in inventory where eligible. XML/properties/build descriptors have separate inventory entries; inspect them directly for registration, reflection and resource wiring. Syntax queries do not establish a resolved runtime call graph.

The native mapper keeps no tag cache. In the Python fallback, JSON tag caches are outside source and keyed by content/query hashes and actual parser package versions. Its C# parser additionally uses the separately installed `tree-sitter-c-sharp` version; upgrading that grammar invalidates C# tags independently of the language-pack version. Recreate artifacts after source or revision changes; a map is a snapshot, not a live view. Generation leaves target source and its existing caches untouched.

## Python reference fallback

Use the [isolated Python fallback setup](setup.md#python-fallback) when native delivery/execution is unavailable, unsupported or policy-blocked, when native mapping fails, or for an exact reference comparison. Keep the same scope and budget when comparing; grammar builds and non-Git ignore matching can differ. The fallback map command is:

```bash
/path/to/tool-env/bin/python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/python-staging --budget 16384 --subtree src
```

On Windows use the environment’s `Scripts/python.exe`. The same inventory, format and all-definition flags apply. Export with `--implementation python`, which defaults to `docs/repo-maps/repo-map.python.md`; keep comparison artifacts separate from native staging. Python-only inventory and citation checking need only the standard library. Parser/package readiness must be tested with a small complete map; `legacy_tools.py info` alone does not prove it.

## Verify citations

Create a JSON evidence file with a `citations` array. Each card has `path` (relative original source), `sha256` (original file bytes), `start_line`, `end_line` (inclusive, one-based), and `quote` (a short exact quotation from those lines). A claim/observed-or-inferred field can accompany the card for human review.

```bash
python /path/to/skill/scripts/check_citations.py /path/to/repository /path/to/artifacts/evidence.json
```

The checker counts LF/CRLF source lines and normalizes CRLF quotations to LF while hashing the original bytes. The citation array must be nonempty.

Exit 0 means the checked citations match current source; exit 1 means at least one is invalid/stale; exit 2 means malformed input or an operational error. Read the machine-readable output. An empty citation set supplies no evidence. Matching quotations do not prove a claim or search completeness.

Before editing, inspect original bodies and callers for the affected behavior. To state that an API is absent, record the actual search command, directories and relevant configuration/dependencies searched. Do not infer absence from a budgeted map.
