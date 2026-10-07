# Binary delivery, local readiness and platform limits

The native Rust mapper is the default repository-map path. Read this for delivery limits or release publishing; follow [native setup](setup.md#native-binary) for status/install. Source installation, program installation and local readiness are separate states.

## What is available now

This skill installation includes source/scripts, a pinned `tool-distribution.json` and the standard-library `scripts/setup_native.py` installer, not executables. The policy names release `legacy-tools-v0.2.0` in `EdukeyTeam/agent-toolbox`, native version 0.2.0 and reference contract `repo_map.py 1.1.0`. The first release is pending publication. The installer reads the policy immediately; agents do not need release discovery or a “latest” search.

The [test workflow](https://github.com/EdukeyTeam/agent-toolbox/actions/workflows/test-skills.yml) builds both programs and retains platform artifacts for 14 days. Updated artifacts also contain a per-platform `legacy-tools-release.json` with source commit, archive/file hashes and notices. See [native setup](setup.md#native-binary) for `status`, release `install`, `--from-ci` and local artifact commands. Historical 0.1.0 artifacts cannot satisfy this new contract. A CI run's source SHA must be supplied explicitly and its success is checked before download.

| Pinned build platform | Archive/program | Boundaries |
| --- | --- | --- |
| Windows x86-64 | `legacy-repo-map-windows-x86_64.zip` / `legacy-repo-map.exe` | Windows 10+ and documented VC runtime; unsigned. |
| Linux x86-64 | `legacy-repo-map-linux-x86_64.tar.gz` / `legacy-repo-map` | Includes WSL Linux; distro/libc compatibility must be established separately. |
| macOS arm64 | `legacy-repo-map-macos-arm64.tar.gz` / `legacy-repo-map` | Runner execution is not Gatekeeper/notarization validation. |

Use the executing environment's OS/architecture: WSL selects Linux, not Windows. Do not promise Windows ARM64, Linux ARM64, Intel macOS or Alpine/musl compatibility without corresponding builds and consumer tests. The reference bundle uses the same platform suffixes. Preserve archive executable modes and adjacent notices.

## Versioned publishing and updates

Keep evolving binaries out of Git source history. The maintainer workflow `.github/workflows/release-legacy-tools.yml` builds/tests all three platforms, preserves notices, prepares indexes with `scripts/create-legacy-release-manifest.py`, verifies common source provenance and publishes the resulting archives/index/checksums as versioned [GitHub Release assets](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). Review and merge the source first, then explicitly authorize a release tag or manual publication run. A successful PR build does not publish a release, merge a PR or install tools across a fleet.

The installed policy pins the release tag, versions, supported platforms and archive names. The release index provides the immutable reviewed source SHA and final archive/package hashes. Checksums fetched from the same GitHub release detect corruption and mismatch; they are not a code-signing identity or an independent supply-chain attestation. Setup verifies before extraction, rejects unsafe archive members, bounds downloads and smoke-tests the staged executable before replacing an existing version/platform.

Updating the skill updates its pinned contract. Run explicit setup to install the new version; ordinary mapping never downloads, upgrades or resolves “latest.” Retain old version directories for rollback. The installer does not edit the repository, global PATH, shell security settings or installed instructions. No binaries enter Git history.

For a local maintainer smoke check, package the current platform with the existing build helper, then generate an index outside the source checkout:

```bash
python scripts/create-legacy-release-manifest.py prepare --artifact-dir /path/to/build-output --output-dir /path/to/indexed-artifact --source-commit <full-source-sha>
```

Use `--source-dirty` only for explicitly local uncommitted builds. A direct native package directory containing `BUILD-INFO.json` and notices can use `--package-dir` instead of `--artifact-dir`. Final release aggregation rejects dirty source indexes, mismatched source commits, duplicate/missing platforms and archive checksum mismatches.

## Readiness belongs to the machine

Do not mutate shared `SKILL.md` to say “To do” or “Ready”: that state differs across machines and is lost on reinstall. `setup_native.py status` reports `ready` (exit 0), `needs-setup` for a missing or invalid package (exit 1), or JSON `error` for invalid configuration/unsupported platforms (exit 2), plus platform/version and the program path when verified. It rehashes the whole package, validates the receipt/source contract and probes `--version`; a receipt alone is insufficient. Fresh install also exercises a small grouped/all-definition map.

For the [Python reference fallback](setup.md#python-fallback), readiness remains separate: `legacy_tools.py info` reports versions but does not prove parser availability. Install the pinned packages in an isolated environment, then run inventory and a small map. Standard-library fallback inventory alone needs no parser setup.

## Signing and consumer execution

**Windows:** unsigned native EXEs can run on a host that permits them. This does not imply friction-free distribution: browser downloads may invoke SmartScreen reputation checks, enterprise policy may block execution, and Smart App Control can apply beyond downloaded files. Signing identifies the publisher and supports reputation continuity but does not guarantee that new releases avoid warnings. See [Microsoft's current guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation). Do not disable these controls, strip download-origin metadata or instruct an agent to click through automatically. If policy blocks an unsigned build, use isolated Python source or obtain an approved deployment route. Signing infrastructure is optional future distribution work, not a prerequisite for the existing permitted-host test.

**macOS:** the compiled ARM64 tool can be built and run on CI, but that does not establish consumer trust for downloaded software. For broad external delivery, follow [Apple's Developer ID signing guidance](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/) and [notarization workflow](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution). Test a quarantined download on a clean consumer Mac before advertising seamless native installation. Until that check exists, label native consumer delivery unverified and offer Python source if execution is blocked. Do not disable Gatekeeper or automatically remove quarantine.

**Linux:** there is no common desktop signing gate equivalent to those Windows/macOS checks. Verify checksums and provenance anyway; executable mode, CPU architecture, loader/libc compatibility and local security policy still matter. A Linux CI build does not establish every distribution's compatibility.

## Languages: grammar support versus parity

The native source links pinned existing Tree-sitter grammars and embeds the skill's vendored definition/reference queries. It does not implement each language parser from scratch. Supported query/grammar categories are Java, Python, JavaScript/JSX, TypeScript, TSX, C, C++, C#, Go and Rust. Extension policy is explicit in `src/legacy-repo-map/src/policy.rs`; for example `.h` selects C, and `.pyi`, `.mts`, `.cts` and `.hxx` are not currently symbol-parsed. Descriptors remain inventoried for direct reading.

Tags identify definitions and bare-name references, then adapted Aider/NetworkX PageRank selects captured definitions within a budget; the default renderer groups files and includes enclosing declarations and multiline signatures. The custom logic covers admission, orchestration, ranking and safe output. It cannot resolve types, overloads, imports, reflection or framework wiring into a compiler call graph.

Fixture support for a grammar is not full real-world validation. Additional corpus checks performed on 2026-10-07:

| Corpus category | Parsed files | Definition count, Python / Rust | Result |
| --- | ---: | ---: | --- |
| Java desktop application | 182 | 1586 / 1586 | Map bytes and fingerprints match. |
| TypeScript/TSX application | 416 | 740 / 740 | Map bytes and fingerprints match. |
| Flask 3.1.2, `src/flask` | 24 | 416 / 502 | Both run; map bytes differ. Rust captures 86 additional module assignments. At a sufficient budget it includes every Python-captured definition plus those assignments; compact selection can differ. |
| Mapper's own Rust crate | 6 | 182 / 182 | Map bytes and fingerprints match. |

This is scoped corpus evidence, not a language certification. Python navigation works but reference parity does not; choose the reference implementation when exact reference behavior matters. Other languages retain fixture-level or earlier documented corpus evidence. See [native tooling](native-tooling.md) for historical tests and known differences.

## Token estimates

Retain the named `ceil(Unicode characters / 4)` heuristic as the default budget/statistic. It is a size estimate, not a claim about a model's tokenizer. Exported reports distinguish raw map estimates from whole-report estimates including their headers.

GitHub's [`bpe-openai`](https://github.com/github/rust-gems/tree/main/crates/bpe-openai) provides efficient offline counts for named `cl100k_base` and `o200k_base` dictionaries; see [GitHub's introduction](https://github.blog/ai-and-ml/llms/so-many-tokens-so-little-time-introducing-a-faster-more-flexible-byte-pair-tokenizer/). It is a candidate for an optional exact-tokenizer statistic. Do not change selection budgets or claim a binary-size/startup cost without before/after builds and parity checks. A named-tokenizer count still excludes other tokenizers and request-envelope overhead. No tokenizer dependency is added; both implementations retain the same named character-based estimator.
