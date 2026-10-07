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

## Read the three outputs

| Output | Use |
| --- | --- |
| `repo-map.md` | Ranked original-source lines with relative paths and original line numbers. |
| `inventory.json` | Files, content hashes, language/kind, examined revision and working-copy fingerprint. |
| `map.meta.json` | Selection, limits, coverage, skipped files, parse failures, descriptors, truncation and dependency versions. |

Metadata `status` distinguishes `complete`, `inventory-only`, `in-progress` and `failed`. A failed inventory invalidates earlier artifacts and reports unknown coverage. A failed parse/rank/render retains the fresh inventory and records the failure stage, while replacing any old symbol map with a diagnostic. Do not use a map unless status is `complete`. A full graph is capped at 200,000 edges and 200,000 tags; map a subtree if either limit is reached.

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
