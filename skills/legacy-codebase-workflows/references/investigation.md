# Investigation and documentation

Start from the question, not a predetermined documentation tree. For a new repository, establish language/runtime, build descriptors, entry points, dependency manifests, modules, tests and integration boundaries. Record the examined commit and working-copy changes. Inventory counts must come from commands or tool metadata.

Treat skipped source as a coverage gap. For non-UTF-8 text, confirm its encoding from build configuration and inspect the original with that decoder. Record the encoding and original byte hash, and verify its line ranges manually: the bundled map, index and citation checker accept UTF-8 only.

## Find behavior across an undocumented framework

1. Locate the application's entry point, feature handler or service and trace its actual caller.
2. Find the internal framework definitions it invokes. Map that framework separately if it is a different repository; keep each repository's revision and provenance distinct.
3. Search configuration and resource wiring: XML descriptors, properties, registration code, annotations, reflection, generated sources and plugin discovery. A declaration without a reachable caller does not prove active use.
4. Read the relevant implementations, types and error paths. Use tests or an authorized runtime observation to distinguish a likely path from verified behavior.
5. Save a small evidence card for each reusable API or convention: purpose; definition; working example; parameters; lifecycle; side effects/errors; supporting source; unknowns.

For a focused answer, a few evidence cards may suffice. For repository documentation, choose artifacts that reduce future source rediscovery: module map, startup/build assumptions, request/data flow, framework API examples, external integrations and unresolved questions. Include code examples from real callers rather than imagined usage.

Do not describe dormant/dead code as active without wiring evidence. Mark historical intent as unknown if code/history cannot establish it. Preserve existing documentation; repair inaccuracies with source evidence rather than replacing everything.

## Context handoff

A useful handoff names the question, examined revision, relevant files/symbols, cross-module edges, evidence and unknowns. Map summaries omit implementation detail: fetch the original body before changing a condition, concurrency behavior, persistence operation or error path.

Read only the source needed to resolve the next uncertainty. A repository fitting in a large context window is not a reason to load it all; irrelevant text can obscure the behavior under investigation.

## Keep generated knowledge current

Store original paths/line ranges and content hashes with evidence. Refresh cards for changed or removed definitions and callers; distinguish application code from framework code. Verify retrieval snippets against the current source. A successful lookup from an old index is not proof that the API still exists.
