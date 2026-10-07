# legacy-repo-map

Experimental native build of the repository map from the [legacy-codebase-workflows](../../skills/legacy-codebase-workflows/SKILL.md) skill. It is a single program with the grammars and tag queries compiled in: no Python, no parser download and no network access at run time.

The Python tool `skills/legacy-codebase-workflows/scripts/repo_map.py` is the reference implementation. This crate mirrors its command line, selection policy, ranking and output files, and the test suite compares both on the same inputs. Read [native tooling](../../skills/legacy-codebase-workflows/references/native-tooling.md) for the measured results and the known differences before choosing it over the Python tool.

## Use

```bash
legacy-repo-map /path/to/repository --output-dir /path/to/artifacts --budget 4096 --subtree src --focus-symbol ExampleService
```

The program writes `repo-map.md`, `inventory.json` and `map.meta.json` to the output directory, which must be outside the source directory. Use the map only when `map.meta.json` reports status `complete`. Run `legacy-repo-map --help` for every option, `--notices` for the embedded license texts and `--print-policy` for the selection tables as JSON.

It reads the source directory and never writes to it. A module root inside a git work tree inherits the enclosing revision and ignore rules, while returned paths remain relative to that module. A supplied root that its enclosing repository ignores is treated as an independent directory. Git queries disable hooks, file-system monitors and inherited `GIT_*` configuration; dirty state is scoped to the supplied root. Outside a git work tree, the program walks files first, then sorted subdirectories, prunes ignored and secret directories, and applies local `.gitignore` files. Discovery stops with failed metadata after 100,000 entries or 2,000,000 bytes of ignore files; each ignore file is capped at 256,000 bytes. It never runs a build tool.

## Build and test

Rust 1.82 or newer and a C compiler are required; the grammar crates compile generated C parsers. Keep build output outside the repository:

```bash
CARGO_TARGET_DIR=/path/outside/the/repository cargo build --release --locked --manifest-path src/legacy-repo-map/Cargo.toml
```

```bash
CARGO_TARGET_DIR=/path/outside/the/repository cargo test --release --locked --manifest-path src/legacy-repo-map/Cargo.toml
```

`cargo test` runs unit tests and `tests/cli.rs`, which executes the built binary on throwaway repositories. `tests/test_legacy_native.py` in the repository root compares the binary with the Python tool. `scripts/build-legacy-tools.py` builds a release artifact with license files and runs smoke tests. For the combined Python/Rust build, use `--prepare-host-licenses` for macOS and Windows (inert on Linux). Windows artifacts target Windows 10 or later with the system Universal CRT and require the matching-architecture [Microsoft Visual C++ v14 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170); these DLLs are not included in the archive.

## Sources and versions

Tree-sitter's [Rust binding](https://github.com/tree-sitter/tree-sitter/blob/master/lib/binding_rust/README.md) ([API documentation](https://docs.rs/tree-sitter/0.25.10/tree_sitter/)) parses the source and runs the queries. Versions are pinned exactly in `Cargo.toml` and `Cargo.lock`:

| Crate | Version | Role |
| --- | --- | --- |
| `tree-sitter` | 0.25.10 | parser runtime and query engine |
| `tree-sitter-java` | 0.23.5 | Java grammar |
| `tree-sitter-python` | 0.25.0 | Python grammar |
| `tree-sitter-javascript` | 0.25.0 | JavaScript grammar |
| `tree-sitter-typescript` | 0.23.2 | TypeScript and TSX grammars |
| `tree-sitter-c` | 0.24.2 | C grammar |
| `tree-sitter-cpp` | 0.23.4 | C++ grammar |
| `tree-sitter-c-sharp` | 0.23.5 | C# grammar |
| `tree-sitter-go` | 0.25.0 | Go grammar |
| `tree-sitter-rust` | 0.24.2 | Rust grammar |
| `ignore` | 0.4 | `.gitignore` matching for directories that are not git work trees |
| `sha2`, `serde_json`, `libc` | see `Cargo.lock` | hashing, JSON output, no-follow file opening on Unix |

The tag queries are not copied into this crate. `src/tags.rs` embeds the files under `skills/legacy-codebase-workflows/vendor/queries/` at compile time, so both implementations use the same query text, and `map.meta.json` records each query's SHA-256.

## Attribution

`src/rank.rs` is a port of `skills/legacy-codebase-workflows/vendor/aider_rank.py`, which adapts the ranking in [Aider's repository map](https://aider.chat/2023/10/22/repomap.html) (`aider/repomap.py` at revision `5dc9490bb35f9729ef2c95d00a19ccd30c26339c`, Apache License 2.0). The port keeps the graph weighting, personalization and PageRank rank distribution, and reimplements the pure-Python PageRank of networkx 3.4.2 (BSD-3-Clause) step by step so that both tools order definitions identically. `Cargo.toml` declares Apache-2.0 for this crate because of that derivation; the declaration covers this crate only, not the rest of the toolbox. See [THIRD_PARTY.md](../../skills/legacy-codebase-workflows/THIRD_PARTY.md) for the full attribution and the tag-query licenses. `legacy-repo-map --notices` prints the Aider license, the grammar projects' MIT licenses and the Tree-sitter runtime's MIT license. The `tree-sitter` crate package ships no license file, so `licenses/tree-sitter-LICENSE.txt` is an unmodified copy of the [upstream file at tag v0.25.10](https://github.com/tree-sitter/tree-sitter/blob/v0.25.10/LICENSE) (SHA-256 `5f9cf9fb6acb1972b35ae29119ce563bb60ec097656bc4b69b9bac2d04c7a147`).

## Limits

- Experimental. Ship the Python tool or its standalone bundle as the default.
- The ranking matches bare identifier text between definitions and references. It is not a type-resolved call graph and does not see reflection, configuration or dependency-injection wiring.
- Ten languages have queries: Java, Python, JavaScript, TypeScript, TSX, C, C++, C#, Go and Rust. Other files are listed in the inventory only.
- No cache: every run reads, hashes and parses the selected files.
- The grammar builds differ from the ones in the Python tool's parser package, so tag sets can differ; the documented case is Python module-level constants.
- No parse timeout. Input is bounded by `--max-files`, `--max-file-bytes`, 100,000 discovered filesystem entries outside Git, 256,000 bytes per ignore file, 2,000,000 aggregate ignore bytes, 20,000 tags per file, 200,000 tags and 200,000 graph edges in total. Cap and read failures leave `map.meta.json` at `failed` with an explicit stage.
