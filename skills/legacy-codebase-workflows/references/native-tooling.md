# Native tooling

The native Rust mapper is the default for repository maps. Read this for implementation differences, historical comparisons or distribution decisions. Start with [native setup](setup.md#native-binary); local compilation is maintainer work.

For platform setup, unsigned executable behavior and the version-pinned release design, read [binary delivery](distribution.md). For named saved reports and repeatable timing, read [repository maps](repo-map.md#save-a-named-report).

## What is native already

In the Python tool, parsing and query matching already run in compiled C: Tree-sitter is a C library and the grammars are generated C parsers. Python drives them and does the rest: start-up and imports, file selection and hashing, the tag cache, and the ranking, which is a pure-Python PageRank. A rewrite in another language can remove interpreter start-up and the Python-side work. It cannot make the parsers themselves faster, and it changes nothing about what a syntax-level map can know. The [Aider article](https://aider.chat/2023/10/22/repomap.html) describes the technique; Tree-sitter publishes an official [Rust binding](https://github.com/tree-sitter/tree-sitter/blob/master/lib/binding_rust/README.md) that runs the same grammars and query files.

## Two programs

| Program | Contents | Status |
| --- | --- | --- |
| `legacy-repo-map` | A Rust implementation of the repository map only. Grammars and tag queries are compiled in. | **Preferred/default mapper.** Experimental; known grammar/query and consumer-platform limits remain. |
| `legacy-tools` | The skill's Python tools, a Python runtime and the pinned parser packages, frozen with PyInstaller 6.22.3. Commands: `map`, `check-citations`, `index`, `query`, `serve`, `info`, `notices`. | Frozen reference fallback and auxiliary tooling. Runs the reference code unchanged. |

Neither executable is stored in Git or the installed skill. The skill includes a pinned policy and native setup script; see [setup](setup.md#native-binary). Both programs are built per platform from the toolbox source by `scripts/build-legacy-tools.py`, which checks the Python dependency pins and locked Cargo versions, licenses the final collected binaries, writes checksums and runs smoke tests. The Python bundle archive includes `BUILD-INFO.json` with final processed-image `sha256`, original Analysis-input `source_sha256`, component versions and license text hashes and sources. The onefile archive keeps its notices beside the executable. macOS and Windows CI prepares upstream or CPython distribution notices for recognized host libraries; unknown components fail the build. Windows 10 or later provides the [Universal CRT](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170) and requires the latest [Microsoft Visual C++ v14 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) matching the artifact architecture; the bundle omits app-local VC, Universal CRT and versioned Windows API-set forwarders. A fresh Windows runtime is not established by a successful GitHub runner build.

The Rust program embeds the same query files the Python tool reads from `vendor/queries/`, uses the same selection policy and limits, ports the Aider-derived ranking operation by operation, and writes the same three output files. Its metadata adds `implementation`, `git`, `source_notes`, `syntax_error_files`, `queries` and `ranking`, and lists Rust crate versions under `dependencies`. It keeps no cache.

## Historical measurements on three sources (legacy line format)

These pre-0.2.0 measurements describe the historical line renderer, not the current grouped renderer or default budget. One Linux x86-64 machine, 7 cores, shared with other work during the runs. Wall time of the whole command, median of 5 runs, default budget of 4096 estimated tokens. "Cold" is an empty output directory, so the Python tag cache is empty; "warm" repeats the run in the same output directory. The operating-system file cache was warm throughout, so first-run disk reads are not measured. The Rust program has no cache, so its two columns do the same work.

| Source | Files seen / read / parsed | Definitions found / in map | Python source cold / warm | Bundle cold / warm | Rust cold / warm |
| --- | --- | --- | --- | --- | --- |
| jFTP, Java, revision `14e62ce` | 576 / 437 / 182 | 1586 / 159 | 1.72 s / 1.55 s | 2.16 s / 2.17 s | 0.35 s / 0.33 s |
| Payload CMS `packages/payload/src`, TypeScript, revision `ea6a103` | 892 / 892 / 889 | 2041 / 158 | 3.08 s / 2.12 s | 3.38 s / 2.64 s | 0.92 s / 0.86 s |
| Payload CMS `packages/ui/src`, TypeScript and TSX, revision `ea6a103` | 1358 / 1355 / 1010 | 1132 / 165 | 3.17 s / 2.32 s | 3.92 s / 2.96 s | 1.57 s / 1.09 s |

In the earlier retained profiling runs, peak memory was about 50 to 55 MB for the Python tool and bundle and about 20 MB for the Rust program. In the Rust runs, parsing and querying took 170 ms, 672 ms and 752 ms of the totals; ranking took under 7 ms. The frozen bundle is slower than the Python source it contains, by 0.1 to 1.3 s per run here.

These are three small inputs on one machine. They show that the Rust program removes most of the fixed cost on small and medium modules and that, once it does, native parsing is the bulk of what remains. They do not predict behavior on a repository of hundreds of thousands of files, on cold disks, on Windows or on macOS, and they say nothing about languages other than Java and TypeScript. Do not quote a general speed-up factor from them.

In every run the three tools produced byte-identical `repo-map.md` files and identical working-copy fingerprints. With the budget raised so that every definition is listed, the Python and Rust orderings were identical for all 1586, 2041 and 1132 lines. The sources were unchanged after the runs.

## Where the two implementations agree

The comparison is automated in `tests/test_legacy_native.py`: historical cases explicitly use `--format lines`, and a separate grouped/all-definition fixture verifies enclosing classes, multiline signatures and exclusion of method bodies. It runs both tools on the same throwaway repositories, with and without git: default, small budget, focus symbol, focus file, subtree, dot-prefixed subtree, exclusion, file-count cap, file-size cap, absent symbol, an ordinary module root under an enclosing work tree, an explicitly parent-ignored root, a dirty work tree with a deleted tracked file, and links that leave the source. It compares map bytes, inventory entries and skip reasons, fingerprint, coverage, truncation and estimator. Other tests cover Git trace injection, a corrupt index, invalid UTF-8 path bounds, bounded discovery and ignore files, and an unreadable POSIX directory. It also checks that the Rust program's policy tables equal the Python modules' tables and that its embedded queries hash to the vendored files. `src/legacy-repo-map/tests/cli.rs` covers the built binary alone.

Extracted tags were compared file by file on public code:

| Language | Corpus | Tags compared | Difference |
| --- | --- | --- | --- |
| Java | jFTP | 11,223 | none |
| TypeScript, TSX, JavaScript | Payload `packages/payload/src` and `packages/ui/src` | 9,448 | none |
| JavaScript, TypeScript declarations | `yaml` npm package | 4,796 | none |
| Rust, C | `tree-sitter` 0.25.10 crate source | 2,234 | none |
| Python | `networkx` 3.4.2 | 55,745 | 454 tags found only by the Rust program |
| C++, C#, Go | small fixtures only | | not compared on a real corpus |

## Known differences

Each of these was reproduced with both tools on the same input; the scripts and their output are kept with the build research, not in the skill.

- **Python module-level constants.** The vendored Python query tags `NAME = value` at module level. The grammar in the Rust crate `tree-sitter-python` 0.25.0 matches it; the grammar build inside `tree-sitter-language-pack` 0.13.0 produces a different tree shape for that statement and does not. On networkx the Rust program reported 454 more definitions out of 7,963, all of this kind. Maps of Python code therefore differ between the two tools.
- **Directories that are not git work trees.** Both programs prune ignored, secret and unselected directories before descent, count every discovered entry toward a hard 100,000-entry cap, and bound ignore-file reads to 256,000 bytes each and 2,000,000 bytes total. The Rust program applies `.gitignore` files with full gitignore semantics. The Python fallback honors basic scoped patterns, directory rules such as `target/`, leading-slash anchors such as `/dist`, and negations. It remains a simplified matcher: escaped patterns, significant trailing spaces and full Git wildcard semantics can differ from Rust. Both fail with unknown coverage if admission fails.
- **Control characters in a mapped line.** Both tools take line numbers from the parser, split lines on line feeds, and replace control characters and Unicode line/paragraph separators in displayed snippets with spaces. Original source hashes and citation text remain unchanged. An earlier implementation differed here; this is no longer a current difference.
- **Cache.** The Python tool keeps a JSON tag cache in the output directory. The Rust program parses every time.
- **Unreadable directories.** The Rust walker reports an inventory failure and leaves `map.meta.json` at `failed`. The Python walker also fails when it cannot enumerate a directory. Neither output claims complete coverage.
- **Extra metadata.** The Rust program adds `source_notes` for an explicitly parent-ignored root, an unusable `.git` entry or a missing commit, and the fields listed above. Ordinary module roots use the enclosing Git revision and ignore policy with module-relative paths. Fields that both tools write have equal values.

None of these changes the output on the Java and TypeScript sources measured above. Both tools skip `git status` when the repository configures clean or process filter commands, because `git status` would execute them, and report `dirty` as `null` with a note.

## Recommendation

Use `legacy-repo-map` as the default mapper through the pinned status/install workflow. It avoids installing parser packages and reduces the fixed mapping cost on the historical inputs measured here. This workflow preference does not imply identical captured tags across grammar builds or consumer validation on every supported platform.

Keep its experimental label and inspect coverage. Its Python-language output differs from the reference, and grammar support for all ten query categories is not real-corpus certification. Use the [Python reference fallback](setup.md#python-fallback) for unsupported/blocked native execution, unavailable native delivery, native failures or exact reference comparisons; use the frozen bundle if isolated parser installation is unavailable. [Native CI](https://github.com/EdukeyTeam/agent-toolbox/actions/runs/37575414253) builds and tests both programs on Linux x86-64, macOS arm64 and Windows x86-64, including map parity, unchanged sources, license inventory and archive checks. Platform-specific fixtures report unsupported POSIX permissions or invalid-byte filenames explicitly. This historical CI run is evidence for its own source version, not readiness for the current 0.2.0 package. Expand current consumer and corpus verification before claiming broader compatibility or removing the experimental label.

## Retrieval is not ported

The retrieval backend stays in Python. Its lexical search is SQLite FTS5, which is compiled C, and its optional semantic search spends its time in ONNX model inference inside the Node.js runtime, which is also native code. The Python part is orchestration. A Rust port would have to reproduce indexing, freshness checks and the HTTP contract to save little of the total; profile indexing, vector search, embedding start-up and reranking separately on a real corpus before considering one. The bundle includes lexical retrieval. It does not include Node.js, the inference package, a model or the optional `sqlite-vec` extension.

## Limits that apply to both

A compact map selects definitions using identifier relationships and PageRank-derived ranking within its budget. The default grouped renderer includes enclosing declarations and multiline signatures. `--all-definitions` bypasses ranked-prefix selection, but still enforces admission, parsing and safety budgets; the queries do not capture every language construct. Names are matched as text: overloads, same-named methods in unrelated classes, reflection, XML or properties wiring and dependency injection are not resolved. Ten languages have queries; everything else appears in the inventory only. Standalone programs are specific to an operating system and CPU architecture, are not code-signed, and contain system libraries from the machine that built them; `BUILD-INFO.json` beside each program records what went in.

## Reusing a build output directory

A successful build replaces the current platform's managed `legacy-tools-<platform>` and `legacy-repo-map-<platform>` outputs. Selecting one target removes the omitted target's artifact directory and both managed archive formats before publishing fresh checksums and manifest. Switching bundle layouts also replaces its archive. Work directories, caches, unrelated files and builds for other platforms remain; Use separate output directories for different platforms. Cleanup unlinks symlinks without deleting their targets and fails the build if a managed output cannot be removed.
