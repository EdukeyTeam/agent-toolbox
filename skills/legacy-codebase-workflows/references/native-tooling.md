# Native tooling

Read this when deciding how to distribute the tools or whether to use the Rust build. For installation and build commands read [setup](setup.md).

## What is native already

In the Python tool, parsing and query matching already run in compiled C: Tree-sitter is a C library and the grammars are generated C parsers. Python drives them and does the rest: start-up and imports, file selection and hashing, the tag cache, and the ranking, which is a pure-Python PageRank. A rewrite in another language can remove interpreter start-up and the Python-side work. It cannot make the parsers themselves faster, and it changes nothing about what a syntax-level map can know. The [Aider article](https://aider.chat/2023/10/22/repomap.html) describes the technique; Tree-sitter publishes an official [Rust binding](https://github.com/tree-sitter/tree-sitter/blob/master/lib/binding_rust/README.md) that runs the same grammars and query files.

## Two programs

| Program | Contents | Status |
| --- | --- | --- |
| `legacy-tools` | The skill's Python tools, a Python runtime and the pinned parser packages, frozen with PyInstaller 6.22.3. Commands: `map`, `check-citations`, `index`, `query`, `serve`, `info`, `notices`. | Default standalone distribution. Runs the reference code unchanged. |
| `legacy-repo-map` | A Rust implementation of the repository map only. Grammars and tag queries are compiled in. | Experimental. |

Neither is stored in the skill. Both are built per platform from the toolbox source by `scripts/build-legacy-tools.py`, which checks exact dependency pins, collects license files, writes checksums and runs smoke tests on the built programs. Each bundle archive includes `BUILD-INFO.json` with the names and hashes of collected binaries and their license text paths and sources. The onefile archive keeps these notices beside its executable.

The Rust program embeds the same query files the Python tool reads from `vendor/queries/`, uses the same selection policy and limits, ports the Aider-derived ranking operation by operation, and writes the same three output files. Its metadata adds `implementation`, `git`, `source_notes`, `focus_not_found`, `syntax_error_files`, `queries` and `ranking`, and lists Rust crate versions under `dependencies`. It keeps no cache.

## Measured on three sources

One Linux x86-64 machine, 7 cores, shared with other work during the runs. Wall time of the whole command, median of 5 runs, default budget of 4096 estimated tokens. "Cold" is an empty output directory, so the Python tag cache is empty; "warm" repeats the run in the same output directory. The operating-system file cache was warm throughout, so first-run disk reads are not measured. The Rust program has no cache, so its two columns do the same work.

| Source | Files seen / read / parsed | Definitions found / in map | Python source cold / warm | Bundle cold / warm | Rust cold / warm |
| --- | --- | --- | --- | --- | --- |
| jFTP, Java, revision `14e62ce` | 576 / 437 / 182 | 1586 / 159 | 1.64 s / 1.33 s | 2.71 s / 1.91 s | 0.24 s / 0.25 s |
| Payload CMS `packages/payload/src`, TypeScript, revision `ea6a103` | 892 / 892 / 889 | 2041 / 158 | 2.83 s / 1.91 s | 4.13 s / 2.68 s | 0.93 s / 0.91 s |
| Payload CMS `packages/ui/src`, TypeScript and TSX, revision `ea6a103` | 1358 / 1355 / 1010 | 1132 / 165 | 3.63 s / 2.36 s | 3.73 s / 2.93 s | 0.98 s / 0.98 s |

Peak memory was about 50 to 55 MB for the Python tool and bundle and about 20 MB for the Rust program. In the Rust runs, parsing and querying took 170 ms, 672 ms and 752 ms of the totals; ranking took under 7 ms. The frozen bundle is slower than the Python source it contains, by 0.1 to 1.3 s per run here.

These are three small inputs on one machine. They show that the Rust program removes most of the fixed cost on small and medium modules and that, once it does, native parsing is the bulk of what remains. They do not predict behavior on a repository of hundreds of thousands of files, on cold disks, on Windows or on macOS, and they say nothing about languages other than Java and TypeScript. Do not quote a general speed-up factor from them.

In every run the three tools produced byte-identical `repo-map.md` files and identical working-copy fingerprints. With the budget raised so that every definition is listed, the Python and Rust orderings were identical for all 1586, 2041 and 1132 lines. The sources were unchanged after the runs.

## Where the two implementations agree

The comparison is automated in `tests/test_legacy_native.py`, which runs both tools on the same throwaway repositories, with and without git: default, small budget, focus symbol, focus file, subtree, exclusion, file-count cap, file-size cap, absent symbol, a dirty work tree with a deleted tracked file, and links that leave the source. It compares the map bytes, the inventory entries and skip reasons, the fingerprint, coverage, truncation and the estimator. Other tests cover Git trace injection, a corrupt index, invalid UTF-8 path bounds and an unreadable POSIX directory. It also checks that the Rust program's policy tables equal the Python modules' tables and that its embedded queries hash to the vendored files, so a change on one side fails the test until the other follows. `src/legacy-repo-map/tests/cli.rs` covers the built binary alone.

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
- **Directories that are not git work trees.** The Rust program applies `.gitignore` files with full gitignore semantics. The Python tool uses a simplified matcher; for example it does not honor a leading-slash pattern such as `/dist`, so it reads files that the Rust program leaves out.
- **Control characters in a mapped line.** Both tools take line numbers from the parser and split lines on line feeds. The Rust program replaces remaining control characters in the line text with spaces. The Python tool copies them, so a file with lone carriage returns as line endings puts carriage returns inside a map line.
- **Cache.** The Python tool keeps a JSON tag cache in the output directory. The Rust program parses every time.
- **Unreadable directories.** The Rust walker reports an inventory failure and leaves `map.meta.json` at `failed`. The Python walker also fails when it cannot enumerate a directory. Neither output claims complete coverage.
- **Extra metadata.** The Rust program adds `source_notes` when the source is inside a larger git work tree or has no commit yet, and the fields listed above. Fields that both tools write have equal values.

None of these changes the output on the Java and TypeScript sources measured above. Both tools skip `git status` when the repository configures clean or process filter commands, because `git status` would execute them, and report `dirty` as `null` with a note.

## Recommendation

Ship the Python source as the default and the `legacy-tools` bundle where Python packages cannot be installed. The bundle runs the reference code, so it needs no separate validation of results, at the cost of a 15 MB archive and slower start-up.

Keep `legacy-repo-map` experimental. It is faster on the inputs measured, needs nothing installed, and passed every shared safety check, but it is a second implementation whose Python-language output already differs from the reference, three of its ten languages have not been compared on real code, and it has been built and run on Linux x86-64 only. Promote it when the grammar difference is resolved in one direction, the remaining languages are compared, and the test suite passes on macOS and Windows.

## Retrieval is not ported

The retrieval backend stays in Python. Its lexical search is SQLite FTS5, which is compiled C, and its optional semantic search spends its time in ONNX model inference inside the Node.js runtime, which is also native code. The Python part is orchestration. A Rust port would have to reproduce indexing, freshness checks and the HTTP contract to save little of the total; profile indexing, vector search, embedding start-up and reranking separately on a real corpus before considering one. The bundle includes lexical retrieval. It does not include Node.js, the inference package, a model or the optional `sqlite-vec` extension.

## Limits that apply to both

A map lists definitions ranked by how often their names are referenced elsewhere. Names are matched as text: overloads, same-named methods in unrelated classes, reflection, XML or properties wiring and dependency injection are not resolved. Ten languages have queries; everything else appears in the inventory only. Standalone programs are specific to an operating system and CPU architecture, are not code-signed, and contain system libraries from the machine that built them; `BUILD-INFO.json` beside each program records what went in.
