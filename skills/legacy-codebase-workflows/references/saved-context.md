# Saved maps and source packs

Read this when exporting maps, publishing Repomix results for reuse, or offering repository instructions. Honor the user's destination and existing repository conventions.

## Keep agent-facing outputs easy to find

When repository writes are authorized, default to `docs/repo-maps/` for RepoMap and `docs/repomix/` for Repomix. Use the established spelling/case when those directories already exist. Announce the destination before generation.

Keep a short guide and the current primary outputs at the top level:

- RepoMap: overview, optional complete captured-definition index, and a readable structure inventory when useful.
- Repomix: the selected code pack, plus an original full-text reference only when requested or needed for comparison. Do not generate/publish every profile by default.

Create an `artifacts/` subdirectory for helper scripts, configs, custom comment policies, logs, raw maps, inventories, audits, comparison packs and historical evidence. Stage generation/caches outside the examined source tree; publish verified results to the chosen directory. The low-level map tools require external staging. Exclude all saved outputs and artifact descendants from future source scans with actual recursive globs, such as `docs/repo-maps/**` and `docs/repomix/**`; a bare directory name or one `*` does not exclude every descendant.

The guide identifies each primary file, examined revision/scope, content retained/omitted, token estimator and refresh command. Keep minimal provenance accessible, including scope, hashes and omissions needed to interpret the output. If moving helpers, update their repository-root calculations, configs, reproduction commands and links. Check that regeneration still places only primary outputs at the top level. Preserve recorded hashes or remeasure outputs after content changes; never relabel old measurements as new runs.

## Version outputs intended for the team

For an authorized team-sharing task, include current maps and selected packed-code files in the repository, together with the short guide and provenance/configuration needed to understand or reproduce them. Stage explicit paths. Follow the repository's commit/PR policy; generation alone does not authorize a push or public upload. Private source can be shared in an authorized private team repository, but must stay out of public history.

Bulky working artifacts usually do not need team distribution. They may be ignored with a scoped `.gitignore` rule, or `.git/info/exclude` for a local preference. For example, `docs/repomix/artifacts/**` excludes the entire support tree; narrow that rule or add exceptions if small manifests, maintained configs or helpers need to be shared. Avoid blanket rules for the primary output directory. Do not silently untrack previously shared evidence; ignore rules do not remove tracked files or historical commits.

For read-only or private local-only work, keep results in the authorized external/local destination and do not stage them. Respect explicit destination, tracking and sharing preferences already supplied.

## Offer repository instructions

After creating either a map or a source pack, prepare a short pointer and ask whether the user wants it added to `AGENTS.md`, unless they already authorized or declined that edit. For example: "Would you like me to add this short usage guide to AGENTS.md so future agents can find these files?" Show the proposed wording and actual relative paths. A pending answer does not block delivering the generated files; do not edit the instruction file without authorization or repeat a settled question.

Update one existing context/navigation section rather than adding duplicate instructions. Describe both what each file contains and the situations in which it helps:

| Trigger | Context to use |
|---|---|
| Understand overall architecture or system design; locate entry points and module ownership | RepoMap first for paths and captured declarations, then the relevant original bodies/configuration or full-code pack |
| Understand application workflows, cross-module behavior or the application's overall logic | Full-code Repomix for implementation across the selected scope, after RepoMap navigation; include resources/configuration separately when outside the pack |
| Find a class, enum, method or other declaration/signature | RepoMap overview, then search the complete captured-definition index if present |
| Inspect original comments/documentation or check filtered content | Original source or the full-text reference |

Example wording, adapted to the files actually generated:

> For architecture, system design, application workflows and symbol navigation, start with `docs/repo-maps/repo-map.rust.md`; search the full captured-definition index for omitted symbols. RepoMap is a small paths/declarations/signatures view without implementation bodies. For broad application-logic analysis across the documented source scope, use the selected full-code pack in `docs/repomix/`; its guide states whether comments are original, removed or selectively filtered. A full-text reference retains original code and comments when provided. Helpers and evidence are in `artifacts/`. Read only the context needed, verify original definitions/callers before edits, and refresh snapshots after relevant source changes.

Replace generic filenames with the actual overview, full index, structure inventory and selected pack paths. State any lossy structural pack's omissions explicitly; never call it complete application logic. RepoMap's budget/query limits also mean an overview is not an exhaustive definition list. Neither tool resolves runtime wiring or proves a working application.
