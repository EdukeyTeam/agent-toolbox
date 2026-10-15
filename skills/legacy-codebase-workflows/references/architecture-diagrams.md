# Architecture diagrams from verified source context

Use this workflow to document an existing application's components, interactions,
state or deployment. Keep an observed architecture separate from a proposed one.
Creating documentation does not authorize changing application behavior.

## Contents

- [Choose the smallest useful preparation](#choose-the-smallest-useful-preparation)
- [Install the companion skill](#install-the-companion-skill)
- [Build an evidence ledger before drawing](#build-an-evidence-ledger-before-drawing)
- [Select and review the views](#select-and-review-the-views)
- [Avoid sequence syntax failures](#avoid-sequence-syntax-failures)
- [Validate, render and publish](#validate-render-and-publish)
- [Handle tooling failures honestly](#handle-tooling-failures-honestly)
- [Refresh and report](#refresh-and-report)

## Choose the smallest useful preparation

Start with existing repository instructions, architecture documents and saved
context. Check their source scope, revision, hashes, omissions and freshness.
Do not load entire packs or graph dumps for a bounded question.

| Question | Useful preparation |
| --- | --- |
| One known interaction | Original entry point, callers and collaborators; no new map required |
| An unfamiliar subsystem | A scoped RepoMap, then original definitions and configuration |
| Several workflows or the whole application | RepoMap for orientation, selected full-code Repomix sections for implementation, bounded graph queries for specific relationships |
| A disputed edge or missing relationship | Original source, dynamic/configuration wiring and dependency definitions; graph absence is insufficient |

Generate missing context only when it answers a concrete question. RepoMap,
Repomix and a graph are complementary tools, not three mandatory setup stages.
Use [repository maps](repo-map.md), [Repomix](repomix.md) and
[code graphs](code-graphs.md) for their respective workflows. A compressed pack
cannot establish behavior. A graph may omit reflection, callback dispatch or
resources, and may connect the wrong anonymous worker.

Follow the repository's snapshot policy. When immutable snapshots are required,
publish a new change-labelled snapshot and preserve earlier products. Never
overwrite original evidence or relabel an old snapshot with a newer revision.
Documentation alone does not require regenerating unchanged application context.

## Install the companion skill

Use the separate `design-doc-mermaid` skill for diagram-specific guides,
templates and rendering. This workflow supplies evidence discipline; it does
not vendor or duplicate that skill. If already installed, read its actual
`SKILL.md` and relevant guides instead of reinstalling it.

The upstream source is
[SpillwaveSolutions/design-doc-mermaid](https://github.com/SpillwaveSolutions/design-doc-mermaid);
its [skills.sh entry](https://skills.sh/spillwavesolutions/design-doc-mermaid/design-doc-mermaid)
identifies the skill name as `design-doc-mermaid`.

Use the [skills CLI](https://github.com/vercel-labs/skills) from a shell with
Node.js and npx. First inspect available skills without installing:

```bash
npx --yes skills@latest add https://github.com/SpillwaveSolutions/design-doc-mermaid --list
```

For a project installation, run from the intended repository root:

```bash
npx --yes skills@latest add https://github.com/SpillwaveSolutions/design-doc-mermaid --skill design-doc-mermaid --agent codex --yes
npx --yes skills@latest list --agent codex
```

The CLI's `--yes` skips its installation prompts after scope and agent selection
are authorized; npx's separate `--yes` only approves fetching the CLI package.
For a user installation, add `--global` to `add` and `list`. Replace `codex`
with the intended supported agent; do not guess that every agent is wanted.
Use the package runner required by local policy. Do not use `--all`, install
every skill, or add hooks, MCP servers or repository instructions as a side
effect. Apply existing installation authorization; establish scope only when
it is unresolved.

Verify the installed skill path and read its references for code-to-diagram,
architecture, sequence and the destination format as needed. Invoke it in the
agent prompt, for example: "Use design-doc-mermaid to document the verified
current architecture from these source references." A UI may namespace that
name; it is not a separate `skills use` shell command.

Windows and WSL installations are separate. Run installation inside each
intended environment, preserve its existing agent targets and inspect copies,
symlinks or junctions before replacing anything. Do not merge the two agent
homes or assume a Windows installation updated Linux. For a targeted refresh
of this skill after an upstream merge, re-add only `legacy-codebase-workflows`
from `EdukeyTeam/agent-toolbox` at the existing scope, then verify the installed
files against the merged source. Avoid a broad update of unrelated skills.

## Build an evidence ledger before drawing

For each important node and relationship, record the original file, inclusive
line range, revision or hash, a short supporting quotation, and whether the
claim is observed, inferred or unknown. Read original bodies and actual callers;
follow resource/configuration wiring and external dependency boundaries.

Check uncertain relationships before drafting. When delegation is requested or
permitted by applicable instructions, give a reviewer bounded questions and
explicit read-only scope: verify originals rather than repeat the saved maps.
Examples include startup ordering, worker completion callbacks, reflection,
error/abort paths and persistence. Integrate corrections and retain unresolved
limits. A reviewer model is a task choice, not a dependency of this workflow.

Do not invent queues, services, databases or synchronization because they look
familiar. An array processed sequentially by a worker is not evidence of a job
queue. A method calling asynchronous disconnect before connect does not prove
disconnect completed first. Separate dependency edges from chronological calls.

## Select and review the views

Use only views needed to answer the user's questions:

| View | Evidence required |
| --- | --- |
| Component/context flowchart | Owned responsibilities, dependency boundaries and actual external systems |
| Startup or interaction sequence | Entry points, call order, worker/EDT or event-loop boundaries and error branches |
| Activity/transfer flow | Decisions, loops, recursion, cancellation and cleanup |
| Persistence or deployment | Actual paths/formats, data ownership, configuration and runtime boundaries |
| Class, state or ER | Verified type relationships, transitions or data relationships; do not invent a database |

Prefer portable Mermaid types supported by the destination. A component
flowchart is useful architecture documentation without being formal UML.
Keep each view focused, usually around 16 nodes or fewer. State abstractions
and omitted paths. Label synchronous/asynchronous transitions, conditional
behavior and external internals that were not inspected. Do not draw a callback
as guaranteed if an uncaught failure can prevent it.

Review the drafts against the evidence ledger before publication. Recheck the
parts simplified by layout, especially ordering, completion, cancellation and
exception handling. If an independent reviewer is available within the task's
authorization, have them inspect both the original files and draft diagrams.

## Avoid sequence syntax failures

In a `sequenceDiagram`, a raw semicolon can terminate an instruction even
inside a note or message. Text after it can be interpreted as a new statement,
leading to an error reported at the next newline or arrow. Inspect the
preceding note/message, not only the line named by the error.

Use commas, separate messages or `<br/>` for line breaks. If a literal semicolon
is necessary, use Mermaid's `#59;` entity. For example, these are text examples
of valid sequence statements, not instructions to execute:

```text
Note over App,Worker: Initialize session<br/>Start asynchronous listing
Worker-->>App: Listing ready, update the view
App->>App: First step#59; second step
```

The rule and entity are documented in
[Mermaid sequence escaping](https://mermaid.js.org/syntax/sequenceDiagram.html#entity-codes-to-escape-characters).
Inspect every sequence file after finding this mistake once. Do not replace
semicolons globally across diagram types, CSS, configuration or valid entities.

Keep identifiers simple; put punctuation, Unicode or reserved-looking words in
display labels using syntax supported by the diagram type. Sequence participant
aliases differ from quoted flowchart labels. Close every `alt`, `opt`, `loop`
and other block explicitly. Avoid beta syntax and initialization directives
when the target plugin does not support them.

## Validate, render and publish

1. Save standalone `.mmd` files under the repository's chosen diagram directory.
2. Record the target plugin/host and its Mermaid version when discoverable.
   Check the renderer's actual `--version` and `--help`; passing in a newer
   parser does not establish compatibility with an older plugin.
3. Parse every final source with an actual Mermaid parser. A text scan or
   successful process launch is not syntax validation. After fixing a syntax
   mistake, rerun the affected files and check siblings for the same pattern.
4. Render each source locally, for example with a verified Mermaid CLI:

   ```bash
   mmdc -i docs/diagrams/app-components.mmd -o docs/diagrams/app-components.svg
   ```

5. Inspect the SVG/PNG output for clipped notes, overlapping arrows, unreadable
   labels and contrast. Use explicit text colors with light fills. Rendering
   does not prove the relationships match the application.
6. Only then embed the validated source in Markdown. Compare every fence with
   its standalone `.mmd` after newline normalization; update exports together.
7. Verify links, source citations and output/source hashes. Record exact
   commands, versions, executed diagram counts and remaining limitations.

Use fenced Mermaid for GitHub. Supply an image as well for destinations that
cannot render Mermaid. Keep primary sources, selected exports and provenance
Git-visible unless publication policy says otherwise; local browser profiles,
tool caches, previews and logs belong in ignored artifacts. Add an entry-point
link where appropriate without changing agent instructions implicitly.

## Handle tooling failures honestly

Consult the installed version's help instead of copying old flags: a flag such
as viewport width can change between CLI majors. A skill install also does not
prove that its documented rendering helper exists; inspect the installed files.
Use an existing supported Chromium executable via Puppeteer configuration when
appropriate, with an isolated synthetic profile. Keep rendering dependencies
out of application dependencies.

Diagnose package-runner, native filesystem, temporary-directory and browser
launch failures separately from Mermaid parse failures. A cache or temporary
directory in a managed shell may disappear between invocations; finish dependent
steps in one invocation or use an authorized stable artifact location. Do not
turn a session-specific Node monkey patch, global sandbox change or browser
security workaround into default skill setup.

If the browser cannot run, report parser validation separately and leave visual
export unverified. If the parser also cannot run, deliver clearly labelled
unvalidated drafts and the exact blocker. Do not claim plugin compatibility,
image inspection or passing validation from syntax reasoning alone. A required
image/export remains incomplete until the relevant prerequisite works.

## Refresh and report

Report the documented revision, views produced, source review, parser results,
render/visual results and anything unverified. Diagram documentation does not
require launching the application; runtime claims need separate execution
evidence under repository policy. Preserve personal state and keep private
source out of hosted tools unless explicitly authorized.

After source changes, follow the applicable snapshot workflow, recheck the
affected edges against original code, and update diagrams, fences, exports and
evidence together. Do not present a source hash or successful rendering as
proof of complete application behavior.
