# Continuous integration scope

Validation uses separate workflows with GitHub's built-in `paths` filters. GitHub decides whether to create a run before allocating a runner: documentation-only changes outside packaged skills start no validation workflow. There is no changed-file script, preliminary routing job or aggregate completion job.

## Workflows and their inputs

| Workflow | Run when |
|---|---|
| [Node tests](../.github/workflows/test-skills.yml) | Skill metadata, non-legacy skill runtime code/assets, Node tests/dependencies, plugin manifests or workflow configuration changes. Runs once on Linux. Skill references and legacy runtime inputs are excluded. |
| [Legacy Python](../.github/workflows/test-python.yml) | Legacy runtime/vendor/parser/distribution inputs, Python tests or standalone-build/release-index helpers change. Preserves the three-OS, three-Python-version matrix. Skill instructions, references and intake templates are excluded. |
| [Semantic retrieval](../.github/workflows/test-semantic.yml) | Retrieval scripts/runtime/locks, shared discovery/inference helpers or retrieval tests change. Mapper-only scripts are excluded. Preserves real Linux/Windows inference checks. |
| [Native artifacts](../.github/workflows/test-native.yml) | Rust code/locks/embedded notices, bundled legacy runtime/vendor/license/distribution inputs, standalone builders, native tests or the native release workflow change. Preserves three-platform builds and artifact retention. Contributor README, skill instructions, references and intake templates are excluded. |
| [Plugin package](../.github/workflows/test-plugin.yml) | Any skill payload, plugin manifests, root license or ZIP builder changes. Skill Markdown is packaged, so its changes need this inexpensive Linux packaging check. |
| [Workflow validation](../.github/workflows/validate-workflows.yml) | Workflow YAML or path-filter regression tests change. Uses checksum-pinned actionlint. |

Each workflow also includes its own YAML, `.gitattributes` and `.gitignore`. The same ordered pattern list is shared by its PR and main-push triggers using a YAML anchor. `*` and `**` are glob patterns; an ordered `!` entry excludes a path. When at least one changed path remains included, the workflow runs. Shared inputs appear in every workflow that depends on them.

Typical cases:

- Root/repository documentation (`README.md`, `AGENTS.md`, `docs/**`): no validation runs.
- Skill `SKILL.md`: one Node metadata/behavior run plus one plugin packaging run.
- Skill references or legacy intake templates: plugin packaging only.
- Runtime Markdown templates under `skills/write-agents-md/assets/`: Node tests and plugin packaging.
- Rust-only code changes: three native builds; no Python matrix or embedding downloads.
- Mapper-only Python changes: Python/native validation and plugin packaging; no real semantic inference.

Do not exclude all Markdown: runtime templates and bundled notices/licenses are genuine inputs. Add new executable/input directories to their dependent workflow filters in the same change. Positive inclusion lists deliberately do not run for unrelated files; the old fallback that tested every unknown path has been removed.

## Runs and verification

PR filters use GitHub's complete three-dot comparison, so code changes remain included when a later commit changes only docs. Main pushes use a two-dot comparison. These are GitHub-native comparisons, not custom Git diff logic. Each workflow can be dispatched manually to run its complete suite; dispatch the individual workflows when full validation is needed.

New commits cancel superseded runs of the same workflow/PR. Concurrency includes the workflow name so independent suites cannot cancel one another. Main runs are not cancelled. The native release workflow retains its existing tag/manual publication triggers.

Native CI artifacts now come from `test-native.yml`. A documentation-only PR creates no new native artifacts; use a successful native run matching the explicit source SHA for `setup_native.py install --from-ci`.

The repository currently has no required-status protection or rulesets. If those are introduced, account for workflows omitted by path filters: requiring their checks unconditionally can leave docs-only PRs pending. This change does not alter protection settings.

Validate changes with `npm ci`, `npm test` and the workflow's pinned actionlint version. [Path-filter regression tests](../tests/workflow-filters.test.cjs) cover skipped documentation, required shared inputs, ordered exclusions, PR/push consistency and manual runs. They check configuration locally; GitHub remains responsible for creating runs. Verify CI at the current PR head SHA before merging.

References: [GitHub path filters and diff behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore), [YAML anchors](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#yaml-anchors-and-aliases).
