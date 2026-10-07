# Binary delivery, local readiness and platform limits

Read this for first-time native setup or release publishing. Source installation, program installation and local readiness are separate states.

## What is available now

This skill installation includes source/scripts, not executables. `legacy-repo-map` is the experimental Rust mapper; `legacy-tools` is the frozen Python reference tool. The [test workflow](https://github.com/EdukeyTeam/agent-toolbox/actions/workflows/test-skills.yml) builds both and retains their archives, `SHA256SUMS` and `build-manifest.json` as Actions artifacts for 14 days. It does not currently publish releases or provide an automatic native installer. An old CI link is benchmark provenance, not an installation version.

For current artifacts, identify a successful run whose source matches the installed skill, download that run's platform artifact, verify archive hashes and unpack the program together with notices. For an authenticated local `gh` installation:

```bash
gh run download <matching-run-id> --repo EdukeyTeam/agent-toolbox --name legacy-tools-windows-latest --dir /path/to/downloads
```

Artifact container names use runner labels; the enclosed manifest gives the actual platform. `legacy-tools-windows-latest` contains both Windows program archives. Linux/macOS use `legacy-tools-ubuntu-latest` and `legacy-tools-macos-latest`. Record the run/source commit and compare the reference bundle's `info` script hashes with the installed source. If there is no matching retained build, use the isolated Python setup; do not build Rust implicitly or assume the latest successful run is compatible.

| Published build platform | Archive/program | Boundaries |
| --- | --- | --- |
| Windows x86-64 | `legacy-repo-map-windows-x86_64.zip` / `legacy-repo-map.exe` | Windows 10+ and documented VC runtime; unsigned. |
| Linux x86-64 | `legacy-repo-map-linux-x86_64.tar.gz` / `legacy-repo-map` | Includes WSL Linux; distro/libc compatibility must be established separately. |
| macOS arm64 | `legacy-repo-map-macos-arm64.tar.gz` / `legacy-repo-map` | Runner execution is not Gatekeeper/notarization validation. |

Use the executing environment's OS/architecture: WSL selects Linux, not Windows. Do not promise Windows ARM64, Linux ARM64, Intel macOS or Alpine/musl compatibility without corresponding builds and consumer tests. The reference bundle uses the same platform suffixes. Preserve archive executable modes and adjacent notices.

## Preferred publishing design

Keep evolving binaries out of Git source history. Publish archives as versioned [GitHub Release assets](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), together with notices, checksums and a generated machine-readable distribution manifest. CI should build/test a pinned source commit on each supported platform, collect final hashes, and publish only after the release is authorized. Source/skill changes use branches and reviewed PRs; build success does not authorize merging, releasing or installing across a fleet.

Include a small version-pinned `tool-distribution.json` with the installed skill. Its entries should specify source commit, tool version, OS/architecture, archive URL/hash, executable hash/path, notices, runtime prerequisites and validation status. A setup script can read that manifest, select one platform, download one archive, verify before extraction, validate members remain within its cache, unpack into a versioned user cache, and smoke-test the program. It should never alter the target repository, global PATH, shell policy or installed instructions. These manifest/setup/launcher components are a **design proposal**, not existing commands in this release.

Prefer immutable URLs from the installed manifest to a runtime "latest" lookup. Latest binaries may contain different queries, policy or grammar behavior from the skill source. Updating the skill updates its manifest; an explicit setup/update operation installs the new pinned version. A separately requested `--latest` mode could resolve a release once during setup, record its receipt and compatibility, and pin subsequent runs. Ordinary mapping stays offline and never silently upgrades.

## Readiness belongs to the machine

Do not mutate shared `SKILL.md` to say "To do" or "Ready": that state becomes wrong on another machine and is lost on reinstall. Keep the installation contract in the entrypoint, and a machine-local receipt/status under the versioned tool cache. A future `status` check should return `missing`, `ready`, `stale` or `unsupported`, along with selected platform, tool/source version, verification result and executable path. Revalidate existence/hash/version before claiming ready; a receipt alone is insufficient.

Today, use the selected executable's `--version`/`--help`, or the Python entrypoint's `info`, followed by an inventory and small-map smoke check. `info` reports versions; absent packages appear as null, and successful exit does not prove mapping works. Source setup requires all pinned packages, including the separate C# grammar. Use a standard-library inventory without setup when that alone answers the request.

## Signing and consumer execution

**Windows:** unsigned native EXEs can run on a host that permits them. This does not imply friction-free distribution: browser downloads may invoke SmartScreen reputation checks, enterprise policy may block execution, and Smart App Control can apply beyond downloaded files. Signing identifies the publisher and supports reputation continuity but does not guarantee that new releases avoid warnings. See [Microsoft's current guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation). Do not disable these controls, strip download-origin metadata or instruct an agent to click through automatically. If policy blocks an unsigned build, use isolated Python source or obtain an approved deployment route. Signing infrastructure is optional future distribution work, not a prerequisite for the existing permitted-host test.

**macOS:** the compiled ARM64 tool can be built and run on CI, but that does not establish consumer trust for downloaded software. For broad external delivery, follow [Apple's Developer ID signing guidance](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/) and [notarization workflow](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution). Test a quarantined download on a clean consumer Mac before advertising seamless native installation. Until that check exists, label native consumer delivery unverified and offer Python source if execution is blocked. Do not disable Gatekeeper or automatically remove quarantine.

**Linux:** there is no common desktop signing gate equivalent to those Windows/macOS checks. Verify checksums and provenance anyway; executable mode, CPU architecture, loader/libc compatibility and local security policy still matter. A Linux CI build does not establish every distribution's compatibility.

## Languages: grammar support versus parity

The native source links pinned existing Tree-sitter grammars and embeds the skill's vendored definition/reference queries. It does not implement each language parser from scratch. Supported query/grammar categories are Java, Python, JavaScript/JSX, TypeScript, TSX, C, C++, C#, Go and Rust. Extension policy is explicit in `src/legacy-repo-map/src/policy.rs`; for example `.h` selects C, and `.pyi`, `.mts`, `.cts` and `.hxx` are not currently symbol-parsed. Descriptors remain inventoried for direct reading.

Tags identify definitions and bare-name references, then adapted Aider/NetworkX PageRank selects useful original lines within a budget. The custom logic covers admission, orchestration, ranking and safe output. It cannot resolve types, overloads, imports, reflection or framework wiring into a compiler call graph.

Fixture support for a grammar is not full real-world validation. Additional corpus checks performed on 2026-10-07:

| Corpus category | Parsed files | Definition count, Python / Rust | Result |
| --- | ---: | ---: | --- |
| Java desktop application | 182 | 1586 / 1586 | Map bytes and fingerprints match. |
| TypeScript/TSX application | 416 | 740 / 740 | Map bytes and fingerprints match. |
| Flask 3.1.2, `src/flask` | 24 | 416 / 502 | Both run; map bytes differ. Rust extracts 86 additional assignment definitions. |
| Mapper's own Rust crate | 6 | 182 / 182 | Map bytes and fingerprints match. |

This is scoped corpus evidence, not a language certification. Python navigation works but reference parity does not; choose the reference implementation when exact reference behavior matters. Other languages retain fixture-level or earlier documented corpus evidence. See [native tooling](native-tooling.md) for historical tests and known differences.

## Token estimates

Retain the named `ceil(Unicode characters / 4)` heuristic as the default budget/statistic. It is a size estimate, not a claim about a model's tokenizer. Exported reports distinguish raw map estimates from whole-report estimates including their headers.

GitHub's [`bpe-openai`](https://github.com/github/rust-gems/tree/main/crates/bpe-openai) provides efficient offline counts for named `cl100k_base` and `o200k_base` dictionaries; see [GitHub's introduction](https://github.blog/ai-and-ml/llms/so-many-tokens-so-little-time-introducing-a-faster-more-flexible-byte-pair-tokenizer/). It is a candidate for an optional exact-tokenizer statistic. Do not change selection budgets or claim a binary-size/startup cost without before/after builds and parity checks. A named-tokenizer count still excludes other tokenizers and request-envelope overhead. No tokenizer dependency is added by this guidance update.
