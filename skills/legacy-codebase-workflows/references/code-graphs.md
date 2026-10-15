# Optional local code graphs

Use a graph when repeated caller or change-impact questions cross files and direct search or a scoped repository map keeps rediscovering the same relationships. Keep direct search for a known symbol and the map for initial orientation; read bodies, resources and selected full-source packs for behavior. A graph adds navigation, not permission to delete code or change an API.

## Choose the pilot

Start with **codebase-memory-mcp (CBM)** for bounded caller and impact queries, especially when a legacy project cannot import or build. **Graphify code-only** is an alternative for exploring relationships and architecture. When Java imports correctly with its real dependencies, prefer resolved references from the IDE or an approved IDE MCP integration; evaluate **Serena with Eclipse JDT LS** for agent navigation. Compiler-produced SCIP-Java indexes are another option if a suitable consumer already exists.

CBM's Java `lsp` strategy identifies its own resolver, not execution of JDT LS or javac. Neither that label nor an edge's numeric confidence proves Java overload, receiver or runtime dispatch correctness. Type-resolved navigation also depends on a correct project import and classpath; it cannot establish every reflective or external call. See the [CBM Java resolver](https://github.com/DeusData/codebase-memory-mcp/blob/v0.11.0/internal/cbm/lsp/java_lsp.c) and [Serena Java integration](https://github.com/oraios/serena/blob/main/src/solidlsp/language_servers/eclipse_jdtls.py).

The reference baseline is CBM **0.11.0** and Graphify **0.9.91**, examined on 2026-10-14 in a small public Java project. This was a Linux navigation trial, not a production-scale benchmark, corporate Windows approval or runtime behavior test. Recheck commands and licenses when choosing another version; do not assume current upstream documentation describes an older released binary exactly.

## Prepare CBM without client registration

Download the platform archive and `checksums.txt` from the [pinned v0.11.0 release](https://github.com/DeusData/codebase-memory-mcp/releases/tag/v0.11.0). Match the archive's SHA-256 to its exact checksum entry before extracting or executing it; record the version, asset name, digest and platform. Keep the complete extracted runtime together in a dedicated tools directory. Do not run the client auto-configuration install scripts or the binary's `install` command: the pilot needs the verified binary, not registered MCP entries, agent instructions or hooks.

Set `CBM_CACHE_DIR` to a new private directory outside the source checkout, and use that same directory for configuration, indexing, queries and cleanup. In that pilot cache, disable the UI with `config set ui_enabled false`. Do not launch the UI, watchers, auto-indexing or a persistent MCP server as part of this workflow. An isolated cache does not isolate CBM's per-account coordination: active processes can reject a different cache root or build. If another session is using CBM, coordinate with its owner rather than stopping it or replacing its installation.

Provision the binary and any dependencies online separately from reading private source. Then index and query within the approved local boundary, with network access denied if offline operation is required. In the baseline trial, fresh indexing from an empty cache worked with IPv4/IPv6 sockets denied and local IPC allowed. A cache path or a tool's local-processing claim is not an offline test. Returning code to a hosted coding agent is a separate disclosure even when extraction is local.

With the verified executable and isolated cache selected, index the absolute repository path:

```bash
CBM_CACHE_DIR=/path/to/pilot-cache /path/to/codebase-memory-mcp cli index_repository --repo-path /path/to/repository
```

Use `cli list_projects` to obtain the indexed project name; do not guess it from the directory. Check index status, scope, skipped files, parse errors/timeouts and dependency coverage before querying. Overall `indexed` status is not proof of complete extraction; the baseline fresh offline index had a resource parse timeout and fewer nodes than the earlier index.

## Ask a bounded question, then verify

Resolve the exact indexed symbol with `search_graph`, selecting the project, label and a narrow name pattern. Distinguish overloads and class methods from dependency methods with similar names. Inspect graph schema or a file outline if necessary. An absent symbol may indicate omission, unsupported syntax or missing dependency source, not absent code.

For a signature change, trace inbound callers of the selected symbol, starting at depth 1 and increasing only for the required transitive impact. Request evidence and record relationship kind, source locations and resolver/confidence fields. The JSON argument form below follows the released-binary trial; replace both identifiers with exact values returned by your index:

```bash
CBM_CACHE_DIR=/path/to/pilot-cache /path/to/codebase-memory-mcp cli trace_path '{"project":"PROJECT_NAME","function_name":"EXACT_INDEXED_SYMBOL","direction":"inbound","depth":2,"include_evidence":true,"format":"json"}'
```

Set a small result limit, such as 20, on searches and a row `LIMIT` on graph queries. Inspect pagination and truncation fields before making completeness claims; page only as needed for the stated scope. Keep depth, examined modules, result count and response size with the answer. If a trace cannot bound its fan-out, narrow the target or inspect a bounded direct-caller query instead of loading an entire graph into context. Stop when the question has enough verified evidence; a graph's disk size is not prompt size or a token-savings measurement.

Reject synthetic file/container nodes as executable callers. Read every reported call site and receiver in the original checkout, including constructor bodies, anonymous workers, callbacks, listeners, reflection, XML/properties and build configuration where relevant. For impact, report direct callers separately from transitive handlers, and state the boundary for missing libraries or external consumers. A zero-degree class is a candidate for investigation, never a deletion decision.

For every result used in the answer, create citation cards using original repository-relative `path`, byte `sha256`, inclusive one-based `start_line`/`end_line` and an exact `quote`. Record revision, working-copy changes, claim and observed/inferred status alongside them. Use the existing [citation workflow](repo-map.md#verify-citations):

```bash
python /path/to/skill/scripts/check_citations.py /path/to/repository /path/to/artifacts/graph-evidence.json
```

Require a nonempty set and inspect the result: exit 0 means citations match current source, 1 means invalid/stale evidence, and 2 means malformed input or an operational error. The checker cannot prove the claim follows from the quote or that a caller search is complete; verify those by reading the cited code and wiring. Keep maps, graph responses and source evidence under the existing [saved-context policy](saved-context.md), with private indexes outside public history.

## Graphify code-only alternative

Use the PyPI package `graphifyy`, pinned to the baseline version, through `uvx`; do not install its agent skill or register integrations for this pilot. Provision dependencies first into dedicated `UV_CACHE_DIR` and `UV_TOOL_DIR` directories outside the checkout. After provisioning, use `--offline` and deny network access when required:

```bash
UV_CACHE_DIR=/path/to/uv-cache UV_TOOL_DIR=/path/to/uv-tools uvx --offline --from graphifyy==0.9.91 graphify extract /path/to/repository --code-only --force --out /path/to/graph-artifacts
```

Select the exact node using a bounded `query`, then use `explain` for relationships or `affected` for reverse impact traversal. Pass `--graph /path/to/graph-artifacts/graphify-out/graph.json` explicitly; begin with a small query budget and depth 1 or 2. For example:

```bash
UV_CACHE_DIR=/path/to/uv-cache UV_TOOL_DIR=/path/to/uv-tools uvx --offline --from graphifyy==0.9.91 graphify affected EXACT_NODE_ID --depth 2 --relation calls --graph /path/to/graph-artifacts/graphify-out/graph.json
```

If clustering is useful, run `cluster-only` with the explicit graph path and `--no-label --no-viz`. Keep document/media extraction, remote community labeling, watch mode and hosted services outside this code-only pilot. Inspect EXTRACTED/INFERRED relationships and missing files; INFERRED can describe deterministic heuristics, not necessarily LLM output. Non-code resources and files with no extracted symbols still require direct inspection. Apply the same original-source citation checks. See the [Graphify CLI documentation](https://github.com/Graphify-Labs/graphify/tree/v8).

## Freshness and cleanup

Record repository revision, dirty-file state, indexing time, tool version and extraction warnings. After an edit, branch switch, regeneration or dependency/classpath change, refresh the affected index and repeat source checks before reusing its results. A one-shot CLI index is a snapshot; do not assume active-session watcher documentation makes it continuously fresh. Graphify's `--force` extraction provides a fresh baseline; incremental/watch behavior was not tested in the trial.

Check processes and cache logs after CBM commands finish. The tested CLI binary used temporary coordination daemons; pinned and current upstream descriptions differ, so verify actual behavior rather than promising daemon-free operation. If an owned pilot daemon remains and no other session needs it, use the same verified binary and cache with `daemon status`, then `daemon stop`, and verify exit and background children. Never stop another owner's daemon or delete a live cache. Graphify's one-shot trial used no daemon; any separately authorized server/watch job still needs an owner and cleanup. No server, hook or daemon is bundled or automatically enabled by this skill.

## Acceptance and regression questions

On an authorized representative repository, answer five bounded questions and compare graph outputs with source: who calls a selected connection/login entry; what changes if that entry's signature changes; how the GUI/main entry creates its window; which apparently unused classes have an actual searched-reference scope; and what a compact architecture sketch can establish. Record partial and unsupported answers rather than converting missing edges into negative facts.

Use these failures from the public [jFTP](https://github.com/sai-pullabhotla/jftp/tree/14e62ceba4e371c2a0b955604b10f065f46f4f7d) trial as regression questions, or reproduce their patterns in a project fixture:

- Does the inbound trace for `FTPSession.connect(RemoteHost)` return the three concrete callers (`ConnectAction`, `FavoritesDlg` and `FTPSession.reconnect`) while rejecting the extra `__file__` edge as a Java caller?
- Does GUI startup resolve `jftp.setVisible(true)` to the actual frame and `JFTP.prefs.getLookAndFeelClassName()` to preferences, rather than the trial's erroneous `SplashWindow` and `UIPrefsPanel` receivers? Is `new JFTP()` found in the constructor, which Graphify omitted?
- Does dead-class investigation reject `ImageCellRenderer`, nested `ThreadVar` and the local/remote transferables when their constructor call sites are present? Does it record Java/resource search scope and unknown reflective/external uses for any remaining candidate?
- Does the answer distinguish the session entry from the worker's lower-level FTP library `connect/login` calls and the reflective dependency instantiation? Neither tested graph established the absent library's implementation.

These are navigation regression checks, not application behavior tests. Preserve characterization tests, original-source review and large-file member accounting when carrying out an authorized change; a cross-file graph replaces none of them.

## Licenses

CBM uses MIT and Graphify uses Apache-2.0; retain notices if separately redistributing them. Serena's current application license is GPL-3.0-or-later, with SolidLSP separately MIT; check the exact version and component terms before redistribution. GitNexus uses PolyForm Noncommercial 1.0.0, so do not recommend it as an unrestricted corporate default without suitable permission. Consult the upstream [CBM license](https://github.com/DeusData/codebase-memory-mcp/blob/v0.11.0/LICENSE), [Graphify license](https://github.com/Graphify-Labs/graphify/blob/v8/LICENSE), [Serena licensing overview](https://github.com/oraios/serena/blob/main/LICENSE) and [GitNexus license](https://github.com/abhigyanpatwari/GitNexus/blob/main/LICENSE). This reference adds guidance only, not third-party software or a dependency on those tools.
