# Continuous integration scope

`Test skills` starts on pull-request opening, reopening and new commits, on pushes to `main`, and on manual dispatch. A changed-path router then selects jobs. A title/body edit alone does not trigger the default PR event types.

## Jobs and their inputs

| Job | Run when |
|---|---|
| `checks` | Always: determine scope, install the small Node test dependency, validate skill frontmatter/plugin manifests. Run all Node behavior tests only when their code, runtime templates, manifests, dependencies or tests change. |
| `workflow-validation` | Workflow YAML or CI routing changes. Uses pinned actionlint. |
| `test` (3 OS x 3 Python versions) | Legacy Python scripts/tests, parser/vendor inputs, distribution policy, bundled notices or standalone-build/release-index helpers change. Node tests no longer run nine times here. |
| `semantic-retrieval` (Linux/Windows) | Retrieval backend, shared discovery/inference helpers, runtime files/locks, vector dependencies or retrieval tests change. New shared Python helpers conservatively select this job until classified. |
| `native-artifacts` (3 OS) | Rust code/locks/embedded notices, bundled Python scripts/runtime/vendor files/licenses, parser requirements, distribution policy, standalone-build/release-index helpers, native tests or the release workflow change. |
| `plugin-package` (Linux) | Any skill payload, plugin manifest or ZIP-builder change. Skill Markdown is copied into the plugin, so documentation changes still need this inexpensive packaging check. |
| `ci-status` | Always: require `checks` and every selected job to succeed. Unselected jobs may be skipped; failed, cancelled or missing selected jobs fail this status. |

Routing lives in [ci-changes.cjs](../scripts/ci-changes.cjs), with [behavioral tests](../tests/ci-changes.test.cjs). Update its dependency rules when adding test/runtime inputs. Test-workflow/router changes, unknown source inputs and uncertain comparisons select all jobs. The separate native release workflow still runs only for its existing tag/manual publication events; this change does not alter publication.

Typical cases:

- Root/repository documentation: `checks` and `ci-status`, two Linux jobs.
- Skill instructions/references: those two plus `plugin-package`, three Linux jobs. No Python matrix, embedding downloads or native compilation.
- Rust-only changes: the baseline plus three native builds; no Python-version matrix or embedding downloads.
- Mapper-only Python: baseline plus Python/native validation and plugin packaging; no real semantic inference unless a shared retrieval dependency changes.
- CI routing/test-workflow changes: full validation of the newly wired pipeline.

File extension alone is insufficient. A Markdown runtime template under `skills/write-agents-md/assets/` feeds Node tests; `THIRD_PARTY.md` and vendor documentation/notices are bundled into native artifacts. They select the corresponding tests even though they are Markdown.

## Comparison and completion rules

Pull requests use the complete three-dot base/head comparison against the merge base. A PR containing code changes still runs their tests when its latest commit changes only docs; otherwise an earlier failing code commit could receive a green result without being checked. Main pushes use the event's before/after two-dot comparison, including every commit in the push.

The checkout includes full history. Git's NUL-separated diff includes deleted paths and both sides of renames without REST pagination or the workflow path-filter 300-file limit. Initial/force pushes with missing history, malformed event data or unknown events fall back to all checks. Manual dispatch deliberately runs everything. All emitted outputs are Boolean flags, not shell-interpolated filenames.

Job-level conditions skip unnecessary work without suppressing the whole workflow. `ci-status` provides a stable completion check; if required-status rules are configured later, use that aggregate rather than every matrix instance. Repository protection settings are not changed by this workflow update.

A newer commit cancels superseded runs of the same PR. Main runs are not cancelled. Selected groups/counts appear in the job summary. Generation of native CI artifacts happens only when native validation is selected; a docs-only run is not a source for `setup_native.py install --from-ci` packages.

Run locally after changing routing:

```bash
npm ci
```

```bash
npm test
```

Validate the resulting workflow with the pinned actionlint version used in the workflow. On GitHub, bind results to the current PR head SHA; previous-run success is not evidence for new changes.
