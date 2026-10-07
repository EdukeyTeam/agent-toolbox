# Setup and distribution

The tools run in three ways. The first two run the same code and produce identical output; the third is a separate implementation that is checked against them.

| Way | Needs on the machine | Status |
| --- | --- | --- |
| Python source, `scripts/repo_map.py` | Python 3.12 to 3.14 and the pinned parser packages | Default. Reference implementation. |
| Standalone bundle, `legacy-tools` | Nothing besides the bundle; `git` when the source is a git work tree | Same Python tools frozen into a program. Use it where installing Python packages is not possible. |
| Native binary, `legacy-repo-map` | Nothing besides the binary; `git` is optional | Experimental. Repository map only. Read [native tooling](native-tooling.md) first. |

None of them needs an LLM endpoint, an account or network access at run time. All of them write only to the output directory you name, which must be outside the source repository.

## Python source

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

## Standalone bundle

`legacy-tools` is the same `legacy_tools.py` frozen with PyInstaller. It contains a Python runtime, the pinned parser packages for the ten mapped languages, the tag queries, the tool scripts as readable source files and the license texts. Unpack the archive for your platform and run the program inside it:

```bash
/path/to/legacy-tools-<platform>/legacy-tools map /path/to/repository --output-dir /path/to/artifacts --budget 4096
```

```bash
/path/to/legacy-tools-<platform>/legacy-tools info
```

`info` prints the bundled Python and package versions and the SHA-256 of every bundled script, so you can check a bundle against the skill source it was built from. `notices` prints the attribution and lists the license files.

Bundles are built per operating system and CPU architecture; a Linux bundle does not run on macOS or Windows. No binaries are stored in the skill or the repository. Take a bundle from the build artifacts of the toolbox repository when its maintainers publish them, or build one from the toolbox source as described below. Check the archive against the `SHA256SUMS` file that is produced with it.

The bundle covers lexical retrieval completely. Semantic retrieval is not included: it needs Node.js, the pinned inference package and a downloaded model, set up as described under optional retrieval below, and the optional `sqlite-vec` vector engine is not bundled either.

## Native binary

`legacy-repo-map` takes the same arguments as `repo_map.py` and writes the same three files. It is a single program without a cache or resource files. It is experimental: use it when start-up time matters or nothing else can be installed, and prefer the Python tool or bundle when results must match the reference exactly. Differences are listed in [native tooling](native-tooling.md).

```bash
/path/to/legacy-repo-map /path/to/repository --output-dir /path/to/artifacts --budget 4096
```

## Build the standalone programs

Building needs the toolbox source repository, not just the installed skill: the Rust crate is in `src/legacy-repo-map/` and the build helper in `scripts/build-legacy-tools.py`. Run the helper on each platform you need. It writes nothing into the repository and refuses output, dependency and tool directories inside it.

```bash
python scripts/build-legacy-tools.py --output-dir /path/to/build-output --deps-dir /path/to/map-deps --tools-dir /path/to/build-tools --install
```

`--install` pip-installs the pinned map packages into `--deps-dir` and pinned PyInstaller build tools into `--tools-dir` when they are missing. Every selected distribution must have its declared version; a wrong version fails with its name and both versions. Use fresh target directories to replace mismatched packages. The helper never installs into the running interpreter's own environment. `--target python-bundle` or `--target rust` builds one program; the Rust target needs `cargo` 1.82 or newer and a C compiler. `--mode onefile` produces a single self-extracting program instead of a directory; it starts more slowly because it unpacks itself to a temporary directory on every run.

The helper then runs the built programs on a throwaway repository: mapping, citation checking, indexing, querying and serving through the bundle, mapping through the Rust binary, and a comparison of both maps. Results go to `build-manifest.json`; the output directory also holds one archive per program, `SHA256SUMS` and, inside each program directory, `BUILD-INFO.json` and the license files. `BUILD-INFO.json` lists each collected binary's archive name, SHA-256, component and license path, including binaries embedded in onefile builds. It contains no build-machine source paths. A failed check makes the helper exit with status 1; a difference between the two maps does so only with `--require-parity`, because the Rust program is experimental. The helper builds and verifies; it does not publish or upload anything.

The helper collects the CPython PSF text, pinned Python package texts, and license notices for every binary in PyInstaller's Analysis. On Debian-based Linux it uses the installed package's copyright file and any common license text that file references. On other hosts, or when a local license is missing, place verified license texts in a separate directory named for each collected binary and pass `--binary-license-dir /path/to/licenses`. That directory needs a `manifest.json` object keyed by binary filename; each entry has nonempty `component` and `source` strings identifying where its license text came from. Packaging fails and names the binary if required text or provenance is unavailable.

The build fails if PyInstaller picks up a Python package that is not on the helper's audited list, so that software which merely happens to be installed on the build machine is not shipped. Build in a clean environment or extend the exclusion list in the helper.

## Optional retrieval

Lexical indexing, querying and serving use only the standard library with SQLite FTS5 and work in all three Python-based ways above. For semantic retrieval, create an isolated inference runtime outside the source repository:

1. Copy `scripts/retrieval/package.json`, `pnpm-workspace.yaml` and `pnpm-lock.yaml` into an empty directory.
2. Run `pnpm install --dir /path/to/inference-runtime --frozen-lockfile` with Node.js 24.
3. Pass that directory as `--embedding-runtime` and a model cache directory as `--model-cache`.

Only the explicit `index --embed-model` command downloads model files; querying and serving use local files. The optional `sqlite-vec` vector engine is a pinned Python package in `scripts/requirements-retrieval.txt`; install it into the tool environment, never globally. See [private retrieval](private-retrieval.md) for commands, models and limits.

## Check an installation

```bash
python /path/to/skill/scripts/legacy_tools.py info
```

```bash
python /path/to/skill/scripts/repo_map.py /path/to/repository --output-dir /path/to/artifacts --inventory-only
```

The first prints the versions in use. The second lists what would be read without parsing anything. Then generate a map for one module and confirm that `map.meta.json` reports status `complete` and the coverage you expect.
