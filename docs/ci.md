# Continuous integration scope

Most validation uses separate workflows with GitHub's built-in `paths` filters. GitHub decides whether to create these runs before allocating a runner: documentation-only changes outside packaged skills skip the build/test matrices. The fast native release contract check runs on every PR, and every main push checks publication, so path filtering cannot hide an unpublished pin. The release workflow plans its own build and publication jobs; other validation workflows have no routing dependencies.

## Workflows and their inputs

| Workflow | Run when |
|---|---|
| [Node tests](../.github/workflows/test-skills.yml) | Skill metadata, non-legacy skill runtime code/assets, Node tests/dependencies, plugin manifests or workflow configuration changes. Runs once on Linux. Skill references and legacy runtime inputs are excluded. |
| [Legacy Python](../.github/workflows/test-python.yml) | Legacy runtime/vendor/parser/distribution inputs, Python tests or standalone-build/release-index helpers change. Runs the three-Python-version matrix on Linux and Windows; macOS is opt-in (a manual run with `include_macos`, or the repository variable `TEST_MACOS=true`). Skill instructions, references and intake templates are excluded. |
| [Semantic retrieval](../.github/workflows/test-semantic.yml) | Retrieval scripts/runtime/locks, shared discovery/inference helpers or retrieval tests change. Mapper-only scripts are excluded. Preserves real Linux/Windows inference checks. |
| [Native artifacts](../.github/workflows/test-native.yml) | Rust code/locks/embedded notices, bundled legacy runtime/vendor/license/distribution inputs, standalone builders, native tests or the native release workflow change. Builds on Linux and Windows and keeps artifact retention; the macOS build is opt-in the same way (`include_macos` or `TEST_MACOS=true`). The release workflow still builds all three platforms. Contributor README, skill instructions, references and intake templates are excluded. |
| [Plugin package](../.github/workflows/test-plugin.yml) | Any skill payload, plugin manifests, root license, ZIP builder or its regression tests change. Skill Markdown is packaged, so its changes need this inexpensive Linux packaging check. The builder rejects every skill folder without `SKILL.md`; reference-only additions therefore cannot silently bypass entrypoint validation. |
| [Workflow validation](../.github/workflows/validate-workflows.yml) | Workflow YAML or path-filter regression tests change. Uses checksum-pinned actionlint. |
| [Native release contract and publication](../.github/workflows/release-legacy-tools.yml) | Every PR checks version/contract pins. Every main push checks for a missing pinned release and publishes only after all three platform builds pass; main-only manual recovery is available. This workflow deliberately has no path filter. |

Each filtered workflow also includes its own YAML. A root `.gitignore` change alone starts only the native release contract/publication check. Only Python and native matrix validation include `.gitattributes`: its current rules preserve the exact vendor/license bytes checked against provenance manifests. If attribute rules expand to other runtime inputs, update the affected workflow filters. The same ordered pattern list is shared by each filtered workflow's PR and main-push triggers using a YAML anchor. `*` and `**` are glob patterns; an ordered `!` entry excludes a path. When at least one changed path remains included, the workflow runs. Shared inputs appear in every workflow that depends on them.

Typical cases:

- Root/repository documentation (`README.md`, `AGENTS.md`, `docs/**`): only the fast native release contract/publication check runs.
- Skill `SKILL.md`: one Node metadata/behavior run plus one plugin packaging run.
- Skill references or legacy intake templates: plugin packaging only.
- Runtime Markdown templates under `skills/write-agents-md/assets/`: Node tests and plugin packaging.
- Rust-only code changes: two native builds (three with the macOS opt-in); no Python matrix or embedding downloads.
- Mapper-only Python changes: Python/native validation and plugin packaging; no real semantic inference.

Do not exclude all Markdown: runtime templates and bundled notices/licenses are genuine inputs. Add new executable/input directories to their dependent workflow filters in the same change. Positive inclusion lists deliberately do not run for unrelated files; the old fallback that tested every unknown path has been removed.

## Runs and verification

PR filters use GitHub's complete three-dot comparison, so code changes remain included when a later commit changes only docs. Main pushes use a two-dot comparison. These are GitHub-native comparisons, not custom Git diff logic. Each workflow can be dispatched manually to run its complete suite; dispatch the individual workflows when full validation is needed.

GitHub evaluates at most the first 3,000 changed files for path filters. A larger PR can omit a relevant suite if its matching file falls outside that list. For such PRs, split the changes into smaller PRs or manually dispatch all six validation workflows on the PR's head branch (`gh workflow run <workflow-file> --ref <head-branch>`). Check that each run's head SHA equals the current PR head; a dispatch on `main` does not validate the PR. This is an explicit manual safeguard, not an automatic fallback router.

New commits cancel superseded matrix-validation runs of the same workflow/PR. Concurrency includes the workflow name so independent suites cannot cancel one another. Running main workflows are not cancelled by newer commits. Native release builds are grouped by triggering commit and publication is serialized per pinned tag, so queued builds of different versions cannot displace one another.

Native CI artifacts now come from `test-native.yml`. A documentation-only PR creates no new native artifacts; use a successful native run matching the explicit source SHA for `setup_native.py install --from-ci`.

The repository currently has no required-status protection or rulesets. If those are introduced, account for workflows omitted by path filters: requiring their checks unconditionally can leave docs-only PRs pending. This change does not alter protection settings.

Validate changes with `npm ci`, `npm test` and the workflow's pinned actionlint version. [Path-filter regression tests](../tests/workflow-filters.test.cjs) cover skipped documentation, required shared inputs, ordered exclusions, PR/push consistency and manual runs. They check configuration locally; GitHub remains responsible for creating runs. Verify CI at the current PR head SHA before merging.

References: [GitHub path filters and diff behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore), [YAML anchors](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#yaml-anchors-and-aliases).

The plugin workflow runs [actual-builder regression tests](../tests/test-plugin-builder.ps1) before packaging. Run them locally with `pwsh -NoProfile -File tests/test-plugin-builder.ps1`: valid skills/references must appear in the ZIP, while a missing entrypoint must fail clearly and leave no ZIP, both with and without other valid skills. Tests use isolated temporary source/output folders.

## Automatic native releases

Every main push checks the release tag in `skills/legacy-codebase-workflows/tool-distribution.json`, including pushes that only change documentation. The version gate compares the merged tree directly with the push's previous main SHA, including force pushes; a missing previous commit is fetched explicitly or fails the gate. An all-zero previous SHA means branch creation, so only pin validation applies before release planning. If its release is absent, the same workflow builds, tests and verifies Linux x86-64, Windows x86-64 and macOS ARM64 packages, then creates an immutable tag and release. It uses the default `GITHUB_TOKEN` without depending on a second workflow being triggered by the new tag. The source is the triggering main commit, or an existing ancestor tag with identical release inputs. An existing published release with all required assets is a successful no-op only after validating its tag identity and comparing its release inputs with HEAD. This comparison runs again inside the per-version serialized publisher, so a release published while another build runs cannot hide changed inputs. A draft, prerelease or incomplete publication is reported for human recovery. Existing tags and release assets are never moved or overwritten. Only the publishing job has `contents: write`.

Every PR runs a fast version/contract check; existing native artifact CI remains responsible for PR builds and never publishes. Changes to native source, lockfiles, embedded queries/notices, Python map reference and its shared helpers/dependencies, distribution policy, or packaging helpers require an increased matching Cargo package/lock version and policy version/tag. The boundary also covers every legacy script and retrieval resource staged by the shared builder, the skill's license/notice texts, and `setup_native.py`, which the release-manifest helper imports. Directory coverage includes new and deleted inputs. The policy contract must agree with the Rust baseline and Python reference version. Workflow orchestration alone does not require a binary version bump. Documentation pins must agree with the policy. This PR coordinates a bump to 0.3.1 because its existing installer changes are now correctly covered; the reference contract remains 1.2.0. Future fixes therefore publish automatically after the versioned source is merged.

Recovery uses `workflow_dispatch` on `main`: an empty `release_tag` selects the current policy, an explicit tag must match it, and `publish_release: false` builds reviewable artifacts without creating a tag or release. `publish_release: true` follows the same immutable publication path as a main push. Dispatches from other branches or tags cannot publish. Publication verifies that the selected source is an ancestor of main and that its release inputs match the checked-out policy before creating anything.

### Corrections Log

| Date | ID | Change | Before | Why |
| --- | --- | --- | --- | --- |
| 2026-10-26 | legacy-auto-release | Publish missing pinned native releases after main merges; enforce consistent version bumps and explicit fallback acknowledgment. | Publication required a separately pushed tag or manual action; download failure could lead agents to Python without user acknowledgment. | The skill pinned v0.3.0 while only v0.2.0 was published. |
| 2026-10-26 | pr30-merged-release-gate | Recheck merged inputs against previous main and validate published tag inputs before accepting a no-op, including publisher rechecks. | Only PR bases enforced bumps, and complete releases bypassed source comparison. | Concurrent PRs could merge different inputs under the same immutable version. |
| 2026-10-26 | pr30-release-input-audit | Cover repo_render.py, all staged scripts/retrieval resources, skill license/notice texts and the manifest helper's setup_native.py dependency; coordinate pin 0.3.1. | The allowlist omitted rendering behavior and other build inputs, and treated consumer setup as outside the gate. | The shared builder stages these files, and release-index generation imports installer code already changed in this PR. |

Legacy Python checks also run when retrieval evaluation helper scripts or Markdown instructions change, because relocation/path regressions inspect those files.
