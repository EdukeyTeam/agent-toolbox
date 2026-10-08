# Setup and distribution

Use the native Rust mapper by default. Start with `setup_native.py status`, then install the pinned package when needed and run the verified program path. Python source and the frozen reference bundle are fallback routes; they share reference code, while native is a separately tested implementation.

| Way | Needs on the machine | Status |
| --- | --- | --- |
| Native binary, `legacy-repo-map` | Verified pinned binary; optional `git`; Windows 10+ with matching VC Redistributable | **Preferred/default mapper.** Experimental implementation; known query and platform limits apply. |
| Python source, `scripts/repo_map.py` | Python 3.12 to 3.14 and the pinned parser packages | Reference fallback for unsupported/blocked native execution, native failure or exact reference comparisons. |
| Standalone bundle, `legacy-tools` | Bundle; `git` for a git work tree; Windows 10+ with matching VC Redistributable | Frozen reference fallback when parser package installation is unavailable; also supplies auxiliary retrieval tools. |

None of them needs an LLM endpoint or an account to map local source. Generation writes to an external output directory. The separate [report export](repo-map.md#save-a-named-report) helper can then save user-facing maps inside `docs/repo-maps` or a user-selected destination. Downloading dependencies or binaries is explicit setup, not part of offline mapping. Read [binary delivery](distribution.md) for current artifact access, platform selection, readiness and signing limits.

## Native binary

A normal skill install includes `scripts/setup_native.py` and `tool-distribution.json`, not the binary. The installer uses only Python's standard library; no Rust compiler or parser packages are needed. Run status before setup:

```bash
python /path/to/skill/scripts/setup_native.py status
```

`ready` returns the verified `program` path. `needs-setup` (exit 1) means the package is missing or no longer verifies; `error` (exit 2), including unsupported platforms, reports the reason. `ready` exits 0. Status does not download anything. Install one pinned platform archive from GitHub Releases:

```bash
python /path/to/skill/scripts/setup_native.py install
```

This selects the executing OS/CPU, downloads the pinned release index and archive, verifies all packaged file hashes, preserves notices, smoke-tests grouped/all-definition mapping, then writes a receipt into the versioned user cache. Use `--cache-dir /path/to/tool-cache` for an isolated cache. Mapping remains offline. The first pinned `legacy-tools-v0.2.0` release is pending; an unavailable release produces a clear error and does not compile Rust or silently select an old build.

Before release publication, an authenticated `gh` installation can fetch a successful matching CI artifact whose index was produced by the updated test workflow:

```bash
python /path/to/skill/scripts/setup_native.py install --from-ci <successful-run-id> --expected-source <full-reviewed-build-commit-sha>
```

The installer verifies successful run status, its run ID/head SHA, the indexed build commit and the package contract. It rejects historical artifacts lacking the new index or carrying version 0.1.0. A PR run normally tests a merge checkout: `--expected-source` must name that reviewed build commit from the index/checkout log, while `ci_run_head_commit` binds the distinct branch head reported by GitHub. Push runs usually share both SHAs. This is an explicit testing route, not “latest.”

For a previously downloaded indexed artifact directory or package/archive plus its release index:

```bash
python /path/to/skill/scripts/setup_native.py install --local-package /path/to/artifact-directory --expected-source <full-source-sha>
```

Use `--manifest /path/to/legacy-tools-release.json` only with `--local-package` when the local index is separate. CI and release installs reject that override before fetching or touching the cache, so the authenticated index remains their provenance source. Local dirty-source packages are allowed only as explicit local development evidence; receipts expose `source_dirty`, and those packages cannot be promoted through CI/release aggregation. `--replace` explicitly replaces this version/platform after successful verification; failed verification preserves the prior installation.

`legacy-repo-map` maps locally without Python or a resource download once installed. It remains experimental because parser builds and captured tag sets can differ from the Python reference. If OS policy blocks execution or the platform is unsupported, use isolated Python source. Setup never changes PATH, security policy, quarantine metadata or installed instructions.

```bash
/path/returned/as/program /path/to/repository --output-dir /path/to/artifacts --budget 16384
```

## Python fallback

Use this route when the executing OS/CPU is unsupported, approved native delivery is unavailable, host policy blocks execution, native setup/mapping fails, or an exact Python reference comparison is required. Report the native failure and the selected fallback; do not silently claim native output. If comparing behavior, preserve separate staging/report names and the same source revision, scope and budget.

Install the pinned packages into an environment of their own. Do not install them into the legacy application's environment and do not create the environment inside the source repository.

```bash
python -m venv /path/to/tool-env
```

```bash
/path/to/tool-env/bin/python -m pip install -r /path/to/skill/requirements-map.txt
```

```bash
/path/to/tool-env/bin/python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/artifacts
```

On Windows the interpreter is `\path\to\tool-env\Scripts\python.exe`. Where `venv` is unavailable, install into a plain directory and put it on the import path:

```bash
python -m pip install --target /path/to/tool-deps -r /path/to/skill/requirements-map.txt
```

```bash
PYTHONPATH=/path/to/tool-deps python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/artifacts
```

Installation is the only step that downloads anything. The pinned parser package contains its grammars; later parser releases fetch grammars on first use, so keep the pins. `repo_map.py --inventory-only` and `check_citations.py` need only the standard library.

`scripts/legacy_tools.py` is one entry point for all tools and passes arguments through unchanged:

```bash
python /path/to/skill/scripts/legacy_tools.py map /path/to/repository --output-dir /path/to/artifacts
```

```bash
python /path/to/skill/scripts/legacy_tools.py check-citations /path/to/repository /path/to/artifacts/evidence.json
```

```bash
python /path/to/skill/scripts/legacy_tools.py index /path/to/repository --database /path/to/artifacts/index.sqlite --library-id /local/name
```

Its commands are `map`, `check-citations`, `index`, `query`, `serve`, `info` and `notices`.

### Standalone reference fallback

`legacy-tools` is the same `legacy_tools.py` frozen with PyInstaller. It contains a Python runtime, the pinned parser packages for the ten mapped languages, the tag queries, the tool scripts as readable source files and the license texts. Unpack the archive for your platform and run the program inside it:

```bash
/path/to/legacy-tools-<platform>/legacy-tools map /path/to/repository --output-dir /path/to/artifacts --budget 16384
```

```bash
/path/to/legacy-tools-<platform>/legacy-tools info
```

Keep the adjacent license and notice files with the program when copying or redistributing either bundle layout, including the single-file executable.

`info` prints the bundled Python and package versions and the SHA-256 of every bundled script, so you can check a bundle against the skill source it was built from. `notices` prints the attribution and lists the license files.

Bundles are built per operating system and CPU architecture; a Linux bundle does not run on macOS or Windows. No binaries are stored in the skill or the repository. Current binaries are retained as Actions artifacts by the [toolbox test workflow](https://github.com/EdukeyTeam/agent-toolbox/actions/workflows/test-skills.yml), not automatically installed with this skill. Choose a successful run matching the skill source and follow [binary delivery](distribution.md); do not treat a historical benchmark run as the current installation version. Verify the archive against its accompanying `SHA256SUMS`. The version-pinned native installer and maintainer release workflow are implemented; the first release still needs reviewed publication. CI setup requires an explicit matching source SHA. See [binary delivery](distribution.md) for the exact contract.

The bundle covers lexical retrieval completely. Semantic retrieval is not included: it needs Node.js, the pinned inference package and a downloaded model, set up as described under optional retrieval below, and the optional `sqlite-vec` vector engine is not bundled either.

## Build the standalone programs

Building needs the toolbox source repository, not just the installed skill: the Rust crate is in `src/legacy-repo-map/` and the build helper in `scripts/build-legacy-tools.py`. Run the helper on each platform you need. It writes nothing into the repository and refuses output, dependency and tool directories inside it.

```bash
python scripts/build-legacy-tools.py --output-dir /path/to/build-output --deps-dir /path/to/map-deps --tools-dir /path/to/build-tools --install --prepare-host-licenses
```

`--install` pip-installs the pinned map packages into `--deps-dir` and pinned PyInstaller build tools into `--tools-dir` when they are missing. Every selected distribution must have its declared version; a wrong version fails with its name and both versions. Use fresh target directories to replace mismatched packages. The helper never installs into the running interpreter's own environment. `--target python-bundle` or `--target rust` builds one program; the Rust target needs `cargo` 1.82 or newer and a C compiler. `--mode onefile` produces a single self-extracting program instead of a directory; it starts more slowly because it unpacks itself to a temporary directory on every run.

The helper then runs the built programs on a throwaway repository: mapping, citation checking, indexing, querying and serving through the bundle, mapping through the Rust binary, and a comparison of both maps. Results go to `build-manifest.json`; the output directory also holds one archive per program, `SHA256SUMS` and, inside each program directory, `BUILD-INFO.json` and the license files. For `legacy-tools`, `BUILD-INFO.json` lists each final packaged binary's archive name, final-image `sha256`, original Analysis-input `source_sha256`, component, version, license source and license hash, including binaries embedded in onefile builds. Final-image hashes cover processed onedir files or decompressed onefile archive entries. The onefile license directory stays beside its executable and is included in its archive; `notices` reads those adjacent files. The manifest contains no build-machine source paths. A failed check makes the helper exit with status 1; a difference between the two maps does so only with `--require-parity`, because the Rust program is experimental. The helper builds and verifies; it does not publish or upload anything.

The helper collects the CPython PSF text, pinned Python package texts, and notices for every binary in the final PyInstaller archive. On Debian-based Linux it uses the installed package's copyright file and referenced common license texts. On macOS and Windows, `--prepare-host-licenses` fetches official upstream or CPython distribution notices for the collected, recognized OpenSSL, SQLite, libffi, expat and zlib binaries. It also ships CPython's third-party summary, the matching bundled Expat COPYING when pyexpat is included, the complete runtime-version zlib header notice for its static or shared library, and the exact pinned libffi LICENSE on Windows. The summary does not replace these component notices. On Windows it reads CPython's matching build pins and includes the upstream bzip2 and XZ notices when their compression extensions are collected. Unknown binaries fail packaging. Versioned [Windows API-set contracts](https://learn.microsoft.com/en-us/windows/win32/apiindex/windows-apisets) are resolved by the OS loader and are omitted from the archive. Windows bundles omit app-local Microsoft VC runtime, Universal CRT and versioned Windows API-set forwarders. Use Windows 10 or later, which provides the [Universal CRT](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170), and install the latest [Microsoft Visual C++ v14 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) matching the artifact architecture before running; a GitHub Actions runner does not establish that a fresh Windows installation has it. For a manually supplied notice, use `--binary-license-dir /path/to/licenses`: `manifest.json` is keyed by binary filename, and each entry must contain `component`, `version`, `source` and the license file's `sha256`. The helper verifies every hash and fails when a component or notice is missing.

The build fails if PyInstaller picks up a Python package that is not on the helper's audited list, so that software which merely happens to be installed on the build machine is not shipped. Build in a clean environment or extend the exclusion list in the helper.

## Optional retrieval

Lexical indexing, querying and serving are separate Python auxiliary tools, available through source or the frozen reference bundle; they use only the standard library with SQLite FTS5. The native mapper does not provide retrieval. For semantic retrieval, create an isolated inference runtime outside the source repository:

1. Copy `scripts/retrieval/package.json`, `pnpm-workspace.yaml` and `pnpm-lock.yaml` into an empty directory.
2. Run `pnpm install --dir /path/to/inference-runtime --frozen-lockfile` with Node.js 24.
3. Pass that directory as `--embedding-runtime` and a model cache directory as `--model-cache`.

Only the explicit `index --embed-model` command downloads model files; querying and serving use local files. The optional `sqlite-vec` vector engine is a pinned Python package in `scripts/requirements-retrieval.txt`; install it into the tool environment, never globally. See [private retrieval](private-retrieval.md) for commands, models and limits.

The optional vector extension needs both its package and an extension-enabled Python `sqlite3` runtime. If the runtime cannot load extensions, use `--vector-engine stdlib` or explicit `auto` fallback, or a compatible Python build such as Homebrew Python 3.12 on macOS. See [runtime capability notes](private-retrieval.md#evaluate-semantic-retrieval-for-prose-paraphrases).

## Check a Python fallback installation

```bash
python /path/to/skill/scripts/legacy_tools.py info
```

```bash
python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/artifacts --inventory-only
```

The first prints the versions in use. The second lists what would be read without parsing anything. Then generate a map for one module and confirm that `map.meta.json` reports status `complete` and the coverage you expect.
