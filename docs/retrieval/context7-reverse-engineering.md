# Context7 reverse engineering and lessons for offline code retrieval

Research date: 2026-10-17 UTC. Scope: public source inspection, first-party documentation and announcements, and anonymous HTTP observations. No Context7 account, API key, saved login, or cloud credentials were used. No private code was submitted. The research checkouts are under `<external-workspace>/research-src/`.

Evidence convention: **Observed** means directly visible in inspected source, an anonymous response, or an identified first-party statement. A vendor statement is evidence of what the vendor reports, not independent verification of its implementation or performance. **Inferred** marks interpretation, recommendations, and hypotheses. Source references resolve to immutable commits where possible. Negative findings mean "not established by this investigation", not "does not exist".

## Executive summary

- **Observed:** Context7's open repository contains clients and documentation, not the hosted parser and retrieval server. MCP 4.0.3 and ctx7 0.5.13 already use the query-based v2 contract; inspected HEAD reports MCP 4.4.2 and ctx7 0.8.0. [C-api] [C-pinned-cli] [C-packages]
- **Observed:** Historical clients progressed from `topic` plus token budget, through paginated code/info modes, to natural-language query and server-side selection. The newer `/api/v3/search` also chooses libraries in one request. [C-old] [C-middle] [C-search]
- **Observed:** Context7 primarily extracts documentation examples and explanations. Current documentation describes source-code fallback when documentation is scarce; it does not describe exhaustively indexing all source alongside existing docs. [C-ingest]
- **Observed:** Upstash publicly describes LLM enrichment, embeddings, reranking, and Redis caching. January 2026 changes added fast server-side reranking; June 2026 research adds asynchronously generated answers from repository inspection. [B-launch] [B-rerank] [B-research]
- **Observed:** Library resolution uses Redis Search with weighted lexical fields and filters. This is distinct from semantic retrieval of snippets; neither proves the hosted snippet store's current product or model. [B-redis]
- **Observed:** Reputation, library benchmark score, historical c7score, and per-query reranker relevance are different measurements. Their names should not be collapsed into one score. [B-quality] [S-options]
- **Observed:** The original c7score repository and npm package returned unavailable/404 during this research. A public archive with original repository metadata exposes concrete historical scoring logic, but its identity with later production code is unverified. [S-package] [S-app]
- **Observed:** Six alternatives were inspected: docs-mcp-server, claude-context, Serena, GitMCP, CocoIndex, and Aider. Their useful mechanisms include structured chunks, hybrid fusion, symbol navigation, incremental indexing, and bounded repo maps. [D-store] [Z-context] [R-symbol] [G-vector] [X-example] [A-map]
- **Inferred:** Prioritize evidence coverage, structure-aware chunks, candidate recall, precise provenance, and context assembly before replacing storage. Add local embeddings and a reranker as measured options, not prerequisites for every corpus.
- **Inferred:** "Context7-level quality" needs a fixed workload and budget. A documentation service's aggregate score does not establish quality on Java execution paths, XML configuration, or cross-module source questions.

## 1. Public contract

### 1.1 Inspected versions and compatibility boundaries

**Observed:** The Context7 checkout was pinned to `6b636d3c35e051a1a653a236afb7f612c02a1ad3`; its package manifests report MCP 4.4.2 and ctx7 0.8.0. Tags were fetched without changing that checkout: MCP 4.0.3 resolves to `05796c74259a768f45a3f508ae8583df1467a6dd`, ctx7 0.5.13 to `f2eef4f49da71a758c91cf6cb97640c8b262ef81`, v1.0.5 to `5fef38842b0cc842cef34edf1edcd925d7d8856b`, and v1.0.30 to `f35c002beeada90ed6fdddf19c0345f9f41cccdb`. "Latest" below means inspected repository HEAD on this date, not a verified npm dist-tag. [C-packages] [C-api] [C-pinned-cli] [C-old] [C-middle]

**Observed:** There are three layers to distinguish: REST wire objects, MCP tool text, and SDK-normalized objects. MCP formats library JSON for an agent and forwards context as text. The SDK's `getContext` transforms the raw arrays into `{title, content, source}` objects; that normalized array is not the REST response. [C-mcp] [C-utils] [C-format]

### 1.2 Retrieval endpoint inventory

**Observed:** The following table describes calls present in inspected client code. Optional parameters are optional in the relevant caller, not a promise that every hosted deployment accepts every historical combination. [C-api] [C-pinned-cli] [C-cli-api] [C-old] [C-middle] [C-search]

| Caller or period | HTTP endpoint | Request parameters | Response handling |
|---|---|---|---|
| v1.0.5 library resolution | `GET /api/v1/search` | `query`, containing the library name | JSON search response |
| v1.0.5 documentation | `GET /api/v1/{libraryId}` | `type=txt`, optional `tokens`, `topic`, `folders` | Plain text; tool name `get-library-docs` |
| v1.0.30 library resolution | `GET /api/v2/search` | `query` | JSON library results |
| v1.0.30 documentation | `GET /api/v2/docs/{mode}/{owner}/{repo}[/{tag}]` | `type=txt`, optional `topic`, `page`, `limit`; mode is code/info | Plain text; separate retrieval mode |
| MCP 4.0.3 and inspected HEAD | `GET /api/v2/libs/search` | Required `libraryName`, `query` | JSON `{results, error?, searchFilterApplied?}` |
| MCP 4.0.3 | `GET /api/v2/context` | Required `libraryId`, `query` | Calls `response.text()`; no explicit `type` |
| MCP inspected HEAD | Same context endpoint | Required `libraryId`, `query`; optional `language` | Calls `response.text()` |
| ctx7 0.5.13 and HEAD library command | Same search endpoint | Required library name, optional query in CLI/helper | JSON; `--json` prints the results array |
| ctx7 0.5.13 docs command | Same context endpoint | `libraryId`, `query`, explicit `type=json` or `txt` | JSON object or text |
| ctx7 inspected HEAD docs command | Same context endpoint | Same, plus optional `language` | JSON object or text |
| New SDK search command | `GET /api/v3/search` | `query`, `type`; repeated `library` hints, optional `version`, `language` | Raw code/info response, or text |

**Observed:** The original v1.0.5 MCP tool accepts `context7CompatibleLibraryID`, optional `topic`, and optional `tokens`; the tool validates a minimum of 5,000 tokens and defaults to 5,000. Its helper can extract `?folders=` embedded in the ID. v1.0.30 instead has a default result limit of 10 and explicit documentation mode. These are separate historical contracts, not extra knobs on the pinned query-based client. [C-old-tool] [C-middle-tool]

**Observed:** In the query-based MCP, `resolve-library-id` receives `{libraryName, query}` and calls library search. `query-docs` receives `{libraryId, query}` in the pinned version, with optional `language` at HEAD. The current tool describes language as a ranking preference, advises resolving first unless an exact ID is supplied, and limits repeated calls in its description. Those are instructions to the agent; the description is not a server-enforced call counter. [C-pinned-mcp] [C-mcp]

**Observed:** Current documentation describes IDs for repositories, websites, llms.txt sources, packages, and uploaded documents. Version pins can use a slash suffix or `@version`; branch versions also appear in real responses. The new search API allows up to four library hints and requires at least one hint when using `version`. It returns `404 no_documentation_found` for no match and documents `503 search_failed` for temporary failure. [C-guide]

**Inferred:** Implement the two pinned v2 routes first and test actual client behavior. Historical `tokens`, `topic`, modes, or v3 discovery should be explicit compatibility targets rather than silently mixed into a supposedly universal contract.

### 1.3 Exact response shapes

**Observed:** The MCP search interface declares `id`, `title`, `description`, `branch`, `lastUpdateDate`, `state`, `totalTokens`, and `totalSnippets`, with optional `stars`, `trustScore`, `benchmarkScore`, `versions`, and, at HEAD, `source`. State is `initial | finalized | error | delete`. Search can include `searchFilterApplied`. CLI types are a narrower projection and do not list every field. [C-types] [C-pinned-types]

**Observed:** The pinned CLI context interfaces declare this shape; actual responses may contain extra metadata. [C-pinned-types]

```typescript
interface CodeSnippet {
  codeTitle: string;
  codeDescription: string;
  codeLanguage: string;
  codeTokens: number;
  codeId: string;
  pageTitle: string;
  codeList: { language: string; code: string }[];
}
interface InfoSnippet {
  pageId?: string;
  breadcrumb?: string;
  content: string;
  contentTokens: number;
}
interface ContextResponse {
  codeSnippets: CodeSnippet[];
  infoSnippets: InfoSnippet[];
  error?: string;
  message?: string;
  redirectUrl?: string;
}
```

**Observed:** `codeId` functions as a source URL in observed responses and SDK normalization; it should not be assumed to be a globally unique snippet identity. A code item can contain several blocks and several languages. An anonymous React result contained JavaScript and CSS together and an extra `generationDate`. The v3 response additionally attributed items with `libraryId`. [C-format] [P-v2] [P-v3]

**Observed:** Anonymous probes on 2026-10-17 produced: search 200 with JSON library metadata; v2 JSON and text 200 using `/reactjs/react.dev`; v3 search 200 with structured snippets; unknown library 404 with `{error:"library_not_found",message:...}`; and `/facebook/react` 301 with `{error:"library_redirected",message:...,redirectUrl:"/react/react"}`. The redirect response had no observed `Location` header, so generic redirect following alone would not resolve it. The v2 success contained five code snippets and an empty info array. [P-search] [P-v2] [P-text] [P-v3] [P-redirect] [P-invalid]

**Observed:** Current text output is Markdown: level-three title, `Source:` URL, explanation, language-tagged fenced blocks, and a horizontal separator. This differs from the historical all-caps `TITLE / DESCRIPTION / SOURCE / LANGUAGE / CODE` format parsed by archived c7score. The example probe demonstrates one response shape, not all possible content types. [P-text] [S-text]

### 1.4 Headers, defaults, errors, and caching

**Observed:** MCP 4.0.3 emits `X-Context7-Source: mcp-server`, `X-Context7-Server-Version`, optional Bearer authorization, session ID, IDE/version, transport, and an encrypted `mcp-client-ip` value when available. HEAD replaces the IP field with `mcp-client-ip-assertion` using an authenticated timestamped AES-GCM assertion and adds optional plugin attribution. Those hosted transport details do not require a local single-user server to implement IP assertions. [C-pinned-headers] [C-headers]

**Observed:** CLI requests carry `X-Context7-Source: cli`, `X-Context7-Client-IDE: ctx7-cli`, client version, and `X-Context7-Transport: cli`. Its helper chooses an environment API key before an OAuth access token. HEAD's SDK constructor requires explicit credentials or the corresponding environment key; the direct HTTP endpoints successfully handled the anonymous research calls. Documentation itself simultaneously says all requests require authentication and describes lower anonymous limits. Therefore anonymous availability is observed, not a stable authentication guarantee. [C-cli-api] [C-sdk] [C-guide] [P-search]

**Observed:** The MCP API helper imposes a 60-second request timeout. It prefers the server's JSON `message`, then status-specific fallbacks for 429, 404, and 401. Pinned MCP helpers return errors as text-bearing objects; HEAD additionally tracks outcome and marks context errors at the MCP protocol level. CLI errors contain empty code/info arrays, an error string, and optional message; a 301 additionally preserves `redirectUrl`. Empty successful text becomes a documentation-not-found message in MCP. [C-api] [C-mcp] [C-cli-api]

**Observed:** The enterprise OpenAPI snapshot declares required query strings of length 1-500 and 400/401/404/500 responses as applicable. It omits newer cloud features such as v3 and some formatting options. The API guide documents 429 and `Retry-After`, `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset`. This is documentation evidence; the low-volume probes did not induce throttling or server failures. [C-openapi] [C-guide]

**Observed:** Current MCP clients have no documentation-result cache in `lib/api.ts`; the SDK defaults fetch caching to `no-store`, which is distinct from server caching. Upstash's launch article described Redis response caching. Cache key composition, TTLs, invalidation, and whether all current retrieval paths use that same cache were not found in the public clients or current docs inspected. [C-api-head] [C-sdk] [B-launch]

### 1.5 Non-retrieval calls made by the clients

**Observed:** The following inventory matters for an offline compatibility layer even though these calls do not retrieve repository evidence. No authentication or account mutation was executed during research. [C-cli-auth] [C-cli-setup] [C-cli-deployment] [C-cli-tracking] [C-jwt] [C-oauth-check]

| Endpoint or external destination | Observed purpose and shape |
|---|---|
| `POST /api/oauth/device/code` | Form `client_id`, optional `hostname`; returns device authorization information |
| `POST /api/oauth/device/token` | Form device-code grant, `device_code`, `client_id`; returns OAuth tokens or pending/slow-down/denied/expired errors |
| `POST /api/oauth/token` | Form refresh-token grant, `client_id`, `refresh_token`; returns refreshed tokens or OAuth errors |
| `GET /api/dashboard/whoami` | CLI account identity, using authorization |
| `POST /api/dashboard/api-keys` | Setup creates a named API key using an authorized JSON request; response includes `data.apiKey` |
| `GET /api/auth/mcp` | Custom-deployment discovery; expects JSON `{enabled:boolean}`; refuses redirects |
| `POST /api/v2/cli/events` | Telemetry JSON `{event,data}`; skipped for a custom base URL or disabled telemetry |
| `GET /api/v2/auth/check` | HEAD hosted MCP validates opaque OAuth tokens; explicit invalid-token response is distinguished from temporary unavailability |
| `GET /api/v2/entra/config/{audience}` | HEAD obtains external identity-provider verification configuration |
| `/.well-known/oauth-authorization-server` and issuer key discovery | Hosted MCP proxies/discovers OAuth metadata and verifies identity tokens |
| npm registry and public GitHub raw/API URLs | CLI update checks, setup templates, and historical skill downloads; unrelated to local retrieval |

**Observed:** Pinned ctx7 0.5.13 also includes deprecated Skill Hub calls: `GET /api/v2/skills` with `project`, `skill`, or `query`; `POST /api/v2/skills/suggest` with dependencies; `GET /api/v2/skills/quota`; `POST /api/v2/skills/questions` with libraries and motivation; and `POST /api/v2/skills/generate` with motivation, libraries, answers, and optional previous content/feedback. Responses include skill/file metadata, quota, questions, and newline-delimited generation events (`progress`, `tool_result`, `complete`, `error`). They are absent from HEAD's retrieval helper. [C-pinned-cli] [C-pinned-types]

**Observed:** The REST guide additionally lists refresh, policies, metrics, repository submission, website, OpenAPI, llms.txt, Confluence, and Notion ingestion endpoints. These are documented server administration APIs, not calls performed by the inspected MCP's two retrieval tools. The guide's inventory is broader than the client compatibility target. [C-guide]

**Inferred:** Keep an offline client's configuration and credentials isolated, use a local base URL, disable telemetry, and verify network isolation separately. API response compatibility alone cannot guarantee offline operation if setup, update checks, or authentication still access the network.

## 2. Ingestion pipeline

### 2.1 Sources and file selection

**Observed:** Current ingestion documentation lists `.md`, `.mdx`, `.markdown`, `.rst`, `.txt`, and `.ipynb`. It says source files such as Python, TypeScript, and Go are not indexed when documentation is present. Public repositories with little documentation automatically fall back to generating examples from source; private repositories require an explicit Generate docs choice or `generateDocs` flag. Documentation and raw-code indexing are therefore not interchangeable descriptions of Context7. [C-ingest]

**Observed:** The owner guide describes repository-root `context7.json`, default-branch selection unless `branch` is supplied, folder scoping, file exclusions, reusable rules, tag versions, and branch versions. It says root Markdown files are always included, exclusions take priority over inclusions, and existing metadata survives removal of an override. Accepted title/description changes take effect on refresh and undergo checks against instructions or promotional content. [C-owner]

**Observed:** Configuration has a public specification mismatch: the checked-in JSON schema recognizes `projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, and `previousVersions`, but rejects additional properties. The owner guide also documents `branch`, `branchVersions`, and `$schema` in examples. The schema requires a version title while the guide's example supplies only a tag. Its folder descriptions mention regex and full paths while the guide describes globs and simple names. This report cannot establish the closed server's precise parser semantics from either alone. [C-schema] [C-owner]

| Configuration field | Observed intent and relevant caveat |
|---|---|
| `projectTitle`, `description` | Display metadata; schema bounds 100 and 500 characters, respectively; description has a minimum length |
| `branch` | Branch to parse according to owner guide; absent from inspected schema |
| `folders` | Restrict documentation locations; empty means whole repository; guide preserves root Markdown |
| `excludeFolders` | Exclusion patterns; guide says exclusions win; exact pattern dialect differs between public artifacts |
| `excludeFiles` | Basenames, not full paths, according to schema and guide; no regex in schema description |
| `rules` | Library guidance returned with context; schema allows strings of 5-200 characters |
| `previousVersions` | Tagged snapshots; tag/title requirements differ between schema and guide |
| `branchVersions` | Branch-based versions in guide; absent from inspected schema |

**Observed:** The owner guide's default exclusions cover changelogs, license Markdown, code-of-conduct files, archived/old/deprecated/legacy content, and many translated documentation folders. It conditions these defaults on not specifying exclusions. An explicit empty array should not be assumed identical to omission without a server test. For our target, blindly excluding anything named legacy would be especially inappropriate. [C-owner]

**Observed:** Websites, llms.txt, and OpenAPI are separately documented sources. The crawler policy says it respects robots.txt, noindex, and rate limits. Exact crawler extraction, browser rendering decisions, canonical URL normalization, link-follow depth, and website deduplication are not exposed by the client repository. [C-guide] [B-crawler]

### 2.2 Snippet extraction and enrichment

**Observed:** The launch article describes extracting documentation examples, adding explanations and metadata with LLMs, embedding, reranking, and caching. The later quality article explicitly says snippet descriptions are enriched using multiple LLM models. This establishes model involvement in enrichment, but not the current prompt, model mix, or whether every title is generated rather than copied. [B-launch] [B-quality]

**Observed:** Historical c7score expects title, description, source, language, and code fields separated into snippet records. Current responses instead expose semantic JSON fields and Markdown with multiple code fences per item. Info snippets provide prose with optional breadcrumbs and source identifiers. The format can represent explanations without executable code; do not force every retrieved source chunk into a tutorial example. [S-text] [C-pinned-types] [P-text]

**Inferred:** Code plus its nearby explanatory paragraph and heading is a useful retrieval unit because the paragraph contains intent words absent from syntax. For source repositories, equivalent deterministic context can include package, class, signature, doc comment, annotations, enclosing symbol, and configuration references. This can improve representation without generating new claims at index time.

**Observed:** Exact indexing chunk sizes, code/prose alignment heuristics, overlap, normalizing transformations, embedding input template, and content-level deduplication algorithm were not found in `packages/mcp`, `packages/cli`, `packages/sdk`, the owner guide, schema, or enterprise docs examined. Multi-block outputs prove grouping exists; they do not reveal how grouping was computed. [C-types] [C-schema] [P-v2]

### 2.3 Versions, refresh, and researched content

**Observed:** Current refresh documentation describes request-triggered background refresh: popularity ranks top 100, top 1,000, top 5,000, and the remainder have repository thresholds of 1, 15, 30, and 45 days. Websites have slightly higher thresholds. Requests receive the existing index while refresh runs. Private libraries require manual refresh; repositories reparse the configured branch, websites recrawl, and OpenAPI re-fetches. Owner-triggered refresh and a GitHub Action are also documented. These values are time-sensitive vendor documentation, not guarantees observed in the probes. [C-refresh]

**Observed:** Upstash's 2026-06-05 research article describes poor benchmark responses triggering repository inspection in a sandbox and saving the resulting evidence into a separate dynamic-context vector index. It reports roughly 17% of served snippets from that index and a hard-question benchmark increase from 4.0 to 6.4 out of 10. Earlier synchronous research reportedly cost about 30 times search/reranking and introduced minutes of latency. Entries expire and are researched again. These are vendor-reported measurements on their workload, not reproduced results. [B-research]

**Inferred:** This is a second knowledge-production pipeline, not just another vector-store feature. Matching it offline without a generative model cannot reproduce newly authored answers to undocumented questions. A local system can still retrieve the underlying code and let the consuming agent perform the investigation.

## 3. Retrieval, ranking, budgeting, and unknowns

### 3.1 Library search differs from snippet search

**Observed:** A June 2026 engineering article identifies Redis Search for library discovery. It describes JSON documents containing library metadata, weighted title/description fields, exact untokenized fields, prefix handling, stemming choices, and policy filters. Default resolution reranks and deduplicates using an external service; a fast mode skips that step. These observations concern finding the library, not full-text matching inside every documentation chunk. [B-redis]

**Observed:** The January 2026 architecture article describes vector retrieval followed by fast reranking models for both library and context queries. It reports average context tokens dropping from about 9,700 to 3,300, duration from 24 to 15 seconds, tool calls from 3.95 to 2.96, and a small quality improvement. Both search and context APIs receive the natural-language question to support selection. The reported duration is not evidence that a single vector query takes 15 seconds. [B-rerank]

**Inferred:** Passing only a generic topic discards the specific intent needed by a reranker. Resolve a library using name plus task, then preserve the task when selecting evidence. The January change supports query-aware selection, but does not prove an unrestricted chat model writes every online retrieval response.

### 3.2 Embeddings and stores

**Observed:** Upstash documents semantic vector retrieval, but the exact hosted embedding model, dimensions, index algorithm, candidate counts, and reranker architecture are not present in public client code. The launch article says the service runs on Upstash infrastructure; this alone is insufficient evidence to assert the current hosted snippet store is specifically Upstash Vector. [B-launch] [B-rerank] [C-api-head]

**Observed:** Newly inspected on-premise documentation is more concrete: its default embedded store is LanceDB; pgvector and Milvus are supported alternatives; automatic selection uses pgvector when a PostgreSQL vector connection is available. It describes HNSW/cosine, automatic dimension discovery from the model, and reindexing after changing embeddings. These are observations about the enterprise product's documented deployment, not proof of hosted production internals. [C-stores]

**Observed:** No public implementation of BM25/RRF over hosted documentation chunks, a specific dense/sparse weighting, cross-encoder checkpoint, LLM selection prompt, or universal relevance threshold was found. The lexical library resolver and vector snippet retriever should not be conflated to claim a verified hybrid snippet engine. [B-redis] [B-rerank] [C-api-head]

### 3.3 Budget and final assembly

**Observed:** Query-based pinned MCP tools do not expose `tokens`, `page`, `mode`, or `limit`. The current SDK and CLI retrieval helpers likewise do not send a hard token ceiling. Structured snippets contain token counts, but no inspected response promises that those counts include headings, source URLs, explanations, separators, or client wrappers. The January announcement presents fewer, more relevant snippets as a service-side decision. [C-api] [C-pinned-cli] [C-search] [C-types] [B-rerank]

**Observed:** The SDK concatenates code description plus fenced blocks and maps `codeId` to `source`; info maps `breadcrumb` to title and `pageId` to source. The MCP forwards server text, while CLI `docs` normally explicitly requests text. Thus token expansion can occur after retrieval, and different integrations consume different wrappers. [C-format] [C-mcp] [C-cli-docs]

**Inferred:** Define an internal hard budget over the final serialized response, including provenance and fences. Retrieve more candidates than fit, deduplicate overlapping evidence, score relevance and marginal coverage, then pack coherent units. A result-count limit is not a context budget; a five-result response can still contain five huge classes.

### 3.4 What remains closed

**Observed:** Not found after inspecting current/pinned clients, schema, SDK, API and enterprise docs, plus launch, quality, reranking, Redis Search, and research announcements: exact hosted model names for embeddings/reranking; parse prompts; title-generation policy; all ingestion deduplication rules; candidate pool sizes; snippet lexical fusion; post-rerank cutoff; hard context token caps; current response cache keys/TTLs; and invalidation guarantees tying researched entries to commits. These gaps prevent a literal server reconstruction.

**Inferred:** Treat Context7 as evidence for a layered design, not a fully disclosed reference implementation. A local engine's design must be justified by its own retrieval measurements where those internals are unknown.

## 4. Quality measurement

### 4.1 Reputation and benchmark score

**Observed:** Source reputation concerns the organization/source: the quality article names organization age, repository count and total stars, followers, contributors, website referrals, and lower scores for cloned repositories. Client formatting maps numeric `trustScore >= 7` to High, `>= 4` to Medium, lower nonnegative values to Low, and absent/negative values to Unknown. Exact reputation weights and anti-clone detection are not public in inspected material. [B-quality] [C-utils]

**Observed:** The same article describes library benchmark score as average jury-model assessment of answers to common product questions after parsing; owners can customize questions. It separately describes model-quality evaluation and injection screening. This report does not assume that the present production benchmark formula is identical to archived c7score. [B-quality]

**Inferred:** Local provenance should be explicit corpus identity and revision, not a fabricated public reputation score. Retrieval quality needs query-specific evidence labels; source authority and answer coverage should remain separate.

### 4.2 c7score availability and provenance caveat

**Observed:** `git clone https://github.com/upstash/c7score.git` failed with repository not found. The public npm registry endpoints, including encoded scoped-package metadata, and unpkg's package manifest returned 404. The Context7 monorepo contained no c7score implementation in the searched paths. The original Upstash announcement remains available and describes the package. These findings are dated 2026-10-17 and do not establish why the original became unavailable. [B-score]

**Observed:** Public repository search found `MaTriXy/c7score`; it was cloned as `c7score-archive`, commit `efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f`, dated 2025-08-31. Its package metadata names Shannon Rumsey, version 2.2.10 of `@shannonrumsey/context-trace`, and the original `github.com/upstash/c7score` repository. It is not marked as a GitHub fork. This is an identifiable historical source artifact, not verified current official code. Its manifest declares ISC, but no standalone license file was found in the inspected listing; do not assume that settles reuse rights. [S-package]

### 4.3 Concrete historical metrics

**Observed:** In that archive, `getScore` identifies the product, loads or generates reusable questions, generates search topics, fetches contexts, performs question evaluation and collection-level LLM evaluation, computes three deterministic text scores, and combines five components. Default weights are question 0.80 and LLM/formatting/metadata/initialization 0.05 each. The weighted-sum helper validates matching keys and weights summing to one; final reporting rounds scores. [S-app] [S-options] [S-utils]

| Historical component | Observed implementation | Limitation for our evaluation |
|---|---|---|
| Question score | Generate 15 questions, 10 common plus 5 edge cases; generate 5 search topics each; query legacy API with `tokens=10000`; keep first snippet per topic; ask model for score | This evaluates a multi-query expansion procedure, not one modern query |
| Question rubric | Relevance 50%, practical applicability 15%, requested-feature coverage 35% | Model judgment, not verified file/symbol recall |
| Collection LLM score | Unique information 30%, clarity 30%, syntax 40% | No execution or typechecking; prompt also favors English |
| Formatting | Percentage without missing category markers, fewer-than-five-word code, descriptive/non-language labels, or list-like code | Penalizes valid short commands and depends on obsolete serialization |
| Metadata | Percentage not classified as citations, license content, or directory structure | Directory structure may be exactly the answer to a codebase question |
| Initialization | Percentage not classified as trivial imports or one-line installation/initialization | Query-independent penalties can reject requested setup evidence |

**Observed:** Source details behind the table: `TextEvaluator` splits on a 40-hyphen delimiter; formatting uses four Boolean checks, not every helper defined in `textMetrics.ts`. The question scorer builds 75 topic requests and takes only the first snippet from each response. Model calls use Gemini 2.5 Pro with configurable generation parameters; defaults include temperature 1.0. Search-grounded question generation and cached question files are visible. The generation prompt is strongly oriented toward UI examples such as cards, responsive layout, and dark mode. [S-text] [S-metrics] [S-questions] [S-prompts] [S-llm]

**Inferred:** Reuse the categories of relevance, coverage, clarity, duplication, and structural correctness. Do not reuse the old score as a headline measure for legacy Java. Its UI question bias, query expansion, English-only preference, and penalties for structural metadata would distort the task. Exact current c7score weights and their connection to the live `benchmarkScore` remain unverified.

### 4.4 A suitable local evaluation

**Inferred:** Build a fixed, independently labeled set spanning exact-symbol lookup, paraphrased behavior, multi-file flows, configuration-driven behavior, documentation-only concepts, version-specific answers, and unsupported questions. Every question should identify acceptable files, symbols, and line regions plus required supporting evidence. Retain the original six questions as regressions, but add held-out questions before tuning ranking.

**Inferred:** Measure candidate recall before reranking, final evidence Recall@k, reciprocal rank of the first relevant result, multi-hop evidence coverage, and citation validity. For a budgeted agent interface, also measure required-evidence coverage per 1,000 returned tokens, duplicate/irrelevant token proportion, p50/p95 warm/cold latency, index size, incremental refresh cost, and peak memory. Evaluate final answers separately with a fixed prompt and cited-evidence rubric so changes in the answer model do not masquerade as retrieval gains.

**Inferred:** Record ablations: current line chunks versus structural chunks; lexical versus dense versus fused; fusion with/without reranker; expansion on/off; several context budgets. Include fresh/deleted/renamed files, wrong version, similar class names across modules, generated/minified assets, and no-answer cases. Keep judge model and rubric pinned when a model is used; prefer deterministic source-location checks wherever possible.

## 5. Source-inspected alternatives

### 5.1 arabold/docs-mcp-server

**Observed:** At `c180d7c2679d7886d14d42eed36a827d9befe5d3`, documentation passes through `SemanticMarkdownSplitter`: headings establish section paths, then text, code, lists, and tables use different splitters. Defaults include preferred 1,500 and maximum 5,000 chunk sizes in characters. Code and tables preferentially stay intact. A separate Tree-sitter splitter extracts source boundaries; concrete registry parsers include Python and TypeScript, with text fallback for unsupported content. This is structural "semantic" splitting, not evidence of an LLM deciding boundaries. [D-split] [D-tree] [D-config]

**Observed:** Storage is SQLite with FTS5 and sqlite-vec. `findByContent` filters by library/version, obtains vector and BM25 candidates, and fuses ranks with `weightVec/(60+rank)` plus `weightFts/(60+rank)`. Defaults use equal weights, overfetch factor 2, and a further vector-candidate multiplier 10. When vectors are unavailable it uses full-text search. Its embedding factory supports OpenAI-compatible, Azure, Gemini/Vertex, and Bedrock adapters; an entirely local embedding route depends on compatible endpoint configuration rather than an inherent local model bundled by this code. [D-store] [D-embedding] [D-config]

**Observed:** `DocumentRetrieverService` groups hits by URL and clusters nearby chunks. Markdown assembly adds parents, preceding/subsequent siblings, and children, then emits source order. Hierarchical assembly for structured source/JSON follows parent chains and can reconstruct a structural ancestor's subtree. The public tool defaults to five results with a maximum requested limit of 100. No final tokenizer-based response ceiling or cross-encoder was found in the inspected search/assembly path; broader expansion can enlarge output substantially. [D-retrieve] [D-assembly] [D-hierarchy] [D-tool]

**Inferred:** This is the closest architectural comparison for local documentation, especially its narrow retrieval plus type-aware assembly. Copy the distinction between candidate chunks and output context; do not copy unbounded expansion or assume its Python/TypeScript parsers provide Java/XML coverage.

### 5.2 zilliztech/claude-context

**Observed:** At `6fc318b4e3ce58e2898b00a9c3538ead9e24dee5`, `AstCodeSplitter` uses Tree-sitter for JavaScript, TypeScript, Python, Java, C/C++, Go, Rust, C#, and Scala. Default chunk size is 2,500 characters with 300-character overlap. It recursively collects recognized class/function/method nodes, subdivides oversized chunks, and falls back to a LangChain splitter. Parent and child symbols can both produce chunks, so AST-aware does not imply no duplication. [Z-split]

**Observed:** Embedding adapters include OpenAI, Voyage, Gemini, and Ollama. Milvus is the storage backend; hybrid collections store dense vectors and text with a BM25-generated sparse vector. `semanticSearch` defaults to top five and threshold 0.5; the hybrid path combines dense and sparse search with RRF `k=100`, then deduplicates results. RRF is labeled reranking in this implementation, but it is rank fusion rather than a learned query-passage cross-encoder. [Z-context] [Z-store] [Z-ollama]

**Observed:** MCP output includes relative path, start/end line, language, and snippet text; `handlers.ts` truncates each result's content to 5,000 characters. This is a per-result character cap, not a total response token budget. Local Ollama plus a local Milvus deployment can avoid inference/data-store cloud calls after provisioning; cloud-backed defaults and other tooling still require explicit configuration review. [Z-handler] [Z-ollama]

**Inferred:** Borrow structural Java units, dense/lexical complementarity, and source coordinates. Investigate nested-symbol duplication and overlap empirically rather than assuming AST extraction alone fixes relevance.

### 5.3 Serena

**Observed:** At `d9e4c796fae0207ba6848d1df4b331122a5567b5`, Serena's inspected tools expose symbol overview, name-path search, referencing symbols, implementations, declaration lookup, bounded file reads, and regex search. Symbol operations use a language-server manager through SolidLSP. `include_body` permits a small discovery result before fetching source bodies; kind/path/depth and result limits help disambiguate. No embedding store or vector ranking is involved in these specific source-navigation paths. [R-symbol] [R-file] [R-core]

**Observed:** Output controls use `max_answer_chars`, with compact or progressively shortened results described by the tools. These are character-oriented controls rather than a shared tokenizer budget. Local operation depends on installed language servers, language runtime/project setup, and caches. Licensing at the inspected commit is component-specific: SolidLSP MIT, Serena GPL-3.0-or-later, and the combined application subject to GPL terms. Older descriptions of Serena as wholly MIT would be inaccurate here. [R-symbol] [R-file] [R-license]

**Inferred:** Serena answers a different need from semantic docs search: after locating a class or method, navigate actual references and implementations. For legacy Java, this is an important fallback when the answer depends on indirect calls, inherited behavior, or wiring that isolated text chunks cannot establish.

### 5.4 GitMCP

**Observed:** At `c487a29895dcfcb5b672247e646426a56e2051c1`, the code has two materially different documentation paths. Its AutoRAG route calls Cloudflare search with query rewriting, up to 12 results, score threshold 0.4, and a repository-folder filter. Its fallback discovers llms.txt or README content and uses local chunking logic plus Cloudflare Vectorize. These paths should not be described as one transparent, uniform semantic engine. [G-tools]

**Observed:** In the fallback, `getEmbeddings` implements a normalized 1,024-dimensional hash/keyword construction, explicitly described in code as simplified/demo embedding. Heading/paragraph-aware chunking preserves code blocks and handles llms.txt list/link entries. Vector results are rescored as 0.6 normalized vector score plus 0.4 keyword score, with heading/proximity boosts and license/badge penalties. Default search limit is five, with a one-day timestamp eligibility filter. This is not a learned embedding model. [G-vector]

**Observed:** Code search is delegated to GitHub's code-search API with pagination; it is not the fallback vector documentation index. Hosted AutoRAG's internal embedding model, chunking, and reranker are not visible in this repository. No total token cap was found in the inspected formatter/search functions. The repository is Apache-2.0. [G-github] [G-tools] [G-license]

**Inferred:** Useful lessons are source discovery, repository isolation, and separating code from docs search. The demo vector construction is unsuitable evidence for Context7-level paraphrase retrieval; GitMCP's popularity or MCP interface does not establish comparable offline quality.

### 5.5 CocoIndex code embedding examples

**Observed:** At `d3a84b16b390aa51b7042a647d401bae1c6510b4`, the current Python example walks selected source/documentation extensions, detects language, splits, embeds using local Sentence Transformers `all-MiniLM-L6-v2`, and exports to pgvector. A sibling example uses local LanceDB. Functions are memoized and the pipeline can watch for changes; output records include filename, content, embedding, and start/end lines. The examples inspected are the current API, not older tutorial snippets. [X-example] [X-lance]

**Observed:** The example requests chunk size 1,000, minimum 300, and overlap 300. The Python API explicitly documents these units as bytes. Rust's recursive splitter uses Tree-sitter syntax when available and prioritized separator rules otherwise, with costs for poor structural boundaries, missing overlap, and undersized chunks. This is more specific than calling the algorithm a generic recursive text splitter. [X-text] [X-recursive]

**Observed:** The pgvector query embeds the question, sorts cosine distance, and returns top five. The inspected examples contain neither lexical fusion nor a reranker nor final response-budget packing. The local model and local database can operate offline after dependencies/model assets are provisioned. The framework repository is Apache-2.0. [X-example] [X-lance] [X-license]

**Inferred:** CocoIndex is strongest as an incremental ingestion framework to study, not a complete evidence-selection solution. Its default example model is a baseline to measure, not proof that a small general sentence encoder captures Java code behavior well.

### 5.6 Aider repo map

**Observed:** At `5dc9490bb35f9729ef2c95d00a19ccd30c26339c`, `aider/repomap.py` extracts Tree-sitter definition/reference tags and builds a weighted file graph. PageRank redistributes importance to definitions. Explicit identifier mentions, mentioned files, chat files, distinctive identifiers, and frequency adjustments affect ranking. Ambiguous identifier-name matching is graph evidence, not compiler-resolved calls. The mapping path needs no embeddings or generative index-time summaries. [A-map]

**Observed:** It caches tags by file modification time, plus trees/rendered maps. The map targets a token allowance, default 1,024 in `RepoMap`, and binary-searches a ranked-tag prefix to approach the limit. Its token counter samples larger texts and the selection tolerates approximately 15% error, so this is approximate budgeting rather than a strict ceiling. TreeContext renders compact source structure instead of every body. Licensing is Apache-2.0. [A-map] [A-license]

**Inferred:** Keep Aider's repo map as orientation alongside targeted evidence retrieval. A globally important definition need not answer a local behavioral question; replace neither exact source search nor symbol navigation with PageRank alone.

### 5.7 Comparison

**Observed:** All rows summarize the inspected paths above. "No model" means no embedding model in that path. "Not found" is scoped to inspected retrieval/assembly code. "Offline" assumes dependencies and models are pre-provisioned, network routes disabled, and any required local services running.

| Tool | Chunking/unit | Embedding | Store | Lexical component | Rerank/fusion | Output budget | Offline? | License at inspected commit |
|---|---|---|---|---|---|---|---|---|
| Context7 hosted | Enriched docs examples + info; undisclosed boundaries | Undisclosed model | Hosted vector DB undisclosed; Redis for library discovery/cache claims | Verified library lexical resolver; snippet lexical fusion unknown | Fast models, implementation unknown | Server selection; token counts; hard cap unknown | Hosted no; enterprise is separate | Open clients MIT; server not provided |
| docs-mcp-server | Markdown structure; source/JSON hierarchy | Configurable providers/endpoints | SQLite FTS5 + sqlite-vec | BM25 | Weighted RRF, k=60 | Result limit + related chunks; total token cap not found | Yes in FTS mode; local embedding endpoint conditional | MIT |
| claude-context | Tree-sitter units, fallback splitting, overlap | OpenAI/Voyage/Gemini/Ollama | Milvus | BM25 sparse fields in hybrid mode | RRF, k=100; dedup | Top-k + 5,000-character cap per result | Yes with local model/Milvus | MIT |
| Serena | LSP symbols, refs, source ranges | No model in inspected paths | Files and language-server caches | Name-path/regex search | Symbol/path constraints, no vector rerank | Character bounds and progressive summaries | Yes, with local language servers | Serena GPL-3.0-or-later; SolidLSP MIT |
| GitMCP | Docs/llms.txt headings and entries; AutoRAG internals opaque | Hash demo in fallback; AutoRAG model unknown | Cloudflare Vectorize/AutoRAG; GitHub API for code | Keyword rescoring; GitHub code search | Heuristic weighted score or opaque service | Count limits; total token cap not found | No in inspected service paths | Apache-2.0 |
| CocoIndex examples | Syntax-aware recursive chunks, byte bounds | Local MiniLM Sentence Transformer | pgvector or LanceDB | None in inspected example query | Cosine ordering, no reranker | Top five; no context packer | Yes with provisioned local assets/services | Apache-2.0 |
| Aider map | Tree-sitter tags and compact structure | No embedding model | Tag/tree/map caches | Symbol/file mentions | Personalized weighted PageRank | Approximate token target | Map generation yes | Apache-2.0 |

## 6. Lessons for a local engine

### 6.1 What can be reproduced without an indexing LLM

**Inferred:** Reproduce provenance, version isolation, typed chunks, headings, doc/code pairing, identifier indexing, BM25, optional vector fusion, duplicate suppression, neighbor/parent expansion, and final output packing. Code units can have deterministic titles such as `package.Class.method(args)` and descriptions drawn from existing comments. If no description exists, say so rather than inventing semantics.

**Inferred:** Give every evidence unit a stable internal identity distinct from its display source. Preserve corpus, revision, path, byte/line span, enclosing symbol, language, content kind, content hash, and parent/neighbor relations. Keep raw text as authoritative; derived fields can support retrieval without replacing source evidence. Multi-file examples and configuration/declaration links should remain related items rather than flattened prose.

**Inferred:** Treat source and documentation as complementary corpora. Documentation search needs intent/usage explanations; source search needs ownership, calls, implementation, tests, and configuration. A shared interface can combine them, but one line splitter and one ranking formula need not serve every content type equally.

### 6.2 Optional models and diminishing returns

**Inferred:** Local embeddings help when natural-language questions and source identifiers use different vocabulary. Local cross-encoders can reorder a sufficiently broad candidate set; they cannot recover an absent candidate or restore context discarded at indexing. Index-time LLM summaries may help undocumented behavior but add cost, staleness, and unsupported-claim risk. Make them an independently versioned optional layer with source citations and invalidation.

**Inferred:** Context7's asynchronous research suggests a later feedback loop: retain failed questions, investigate with an agent, review the resulting note, and index it with precise supporting sources. Keep researched interpretation distinguishable from copied documentation. Do not run a repository-wide agent for every lookup or promise its learned answers remain correct after source changes.

**Inferred:** Avoid copying public-popularity heuristics, cloud deployment complexity, historical c7score UI biases, hidden auto-refresh that can return stale source silently, and demo hash embeddings. Storage choice does not establish retrieval quality. Huge codebases eventually need measured candidate-search and incremental-update scaling, but distributing a low-recall index only makes weak answers faster.

### 6.3 Corrections to the brief's premises

**Observed:** The brief describes the local engine as primitive and reports one correct location out of six Java questions; that trial was not rerun here. The current backend already implements lexical/semantic/hybrid modes, RRF, an optional local cross-encoder, freshness checks, per-file hashes, and exact-source verification. Its `chunks_for` still splits by a character target over lines, and `context_payload` repeats provenance as the code title/description rather than supplying useful semantic labels. Recommendations must acknowledge the existing machinery rather than propose adding it as though absent. [L-backend]

**Observed:** The backend's info JSON uses `pageTitle`, `content`, and `description`, while the inspected CLI/SDK info contract expects `pageId`, `breadcrumb`, and token metadata. Its text path preserves provenance separately, so behavior differs by integration. This is a concrete compatibility issue to validate, independent of retrieval quality; changing it was outside this report's scope. [L-backend] [C-pinned-types] [C-format]

**Inferred:** A better architecture question is: "Which changes improve held-out source-evidence coverage and agent answers within a fixed token, latency, memory, and offline envelope?" Matching Context7's endpoint names or selecting its presumed database cannot answer that. Separate compatibility, documentation quality, code navigation, and retrieval evaluation into measurable concerns.

## Design recommendations for our local engine, ranked by expected impact

1. **Inferred - highest impact: establish the evidence benchmark before architecture selection.** Preserve the six reported failures, add diverse held-out Java/configuration/documentation questions, label required evidence, and capture current stage-by-stage retrieval. Diagnose whether failure comes from absent files, bad boundaries, candidate recall, ranking, assembly, or serialization. Expected payoff: prevents optimizing a component unrelated to the failures.
2. **Inferred - high impact: structural chunks and deterministic context.** Add Java class/method/constructor units, imports/package/annotations/doc comments, Markdown heading/code relationships, and explicit XML/properties/configuration handling. Preserve exact spans and fallback coverage. Expected payoff: query terms and answer evidence coexist, with less arbitrary truncation. Evidence: docs-mcp-server, claude-context, and CocoIndex structural pipelines. [D-split] [Z-split] [X-recursive]
3. **Inferred - high impact: candidate recall and symbol/path retrieval.** Combine exact identifier and path channels, normalized camel/snake tokens, prose BM25, and optional dense candidates. Measure union recall before reranking and retain module/version filters. The backend already has fusion and reranking; improve their inputs and configuration first. Expected payoff: finds natural-language and exact-code questions without allowing embedding similarity to dominate exact ownership. [L-backend] [Z-context]
4. **Inferred - high impact: separate retrieval units from answer context.** Expand selected hits into bounded enclosing context and necessary neighbors, merge overlapping ranges, preserve doc explanations, and expose referenced configuration/tests. Expected payoff: complete evidence for behavioral questions without returning every adjacent file. Evidence: docs-mcp-server assembly and Serena's staged body/reference retrieval. [D-assembly] [D-hierarchy] [R-symbol]
5. **Inferred - high impact: repair response semantics and enforce a real final budget.** Match pinned JSON/text contracts; use useful symbol titles and real source identifiers for info snippets; count final serialized tokens with a stated tokenizer or conservative bound. Preserve citations when shortening and distinguish "no evidence" from failures. Expected payoff: better consuming-agent behavior and predictable context costs. [C-pinned-types] [C-format] [L-backend]
6. **Inferred - medium/high impact: evaluate the existing local reranker properly.** Use a broader candidate union, pass meaningful symbol/doc context, measure reranker truncation, and compare against lexical/dense/fused baselines at equal output budgets. Expected payoff: precision improvements once recall is adequate. Context7's reported gains motivate testing, not an assumption that our model will reproduce them. [B-rerank]
7. **Inferred - medium impact, essential at scale: incremental structure and model-aware invalidation.** Cache parsing/embeddings by content plus parser/model configuration; update changed/deleted units and relationships transactionally. Keep version/corpus isolation and existing freshness/source verification. Benchmark scan latency, memory and index amplification before choosing an ANN backend. Expected payoff: reliable large-corpus operation without reprocessing everything. [X-example] [L-backend]
8. **Inferred - medium impact for complex Java: add a navigation escape hatch.** Offer reference/implementation/declaration lookup or explicit handoff to a local language server when a text result cannot establish behavior. Retain a repo map for orientation. Expected payoff: supports multi-hop questions that no single snippet answers. This is integration advice, not a recommendation to copy GPL Serena application code. [R-symbol] [R-license] [A-map]
9. **Inferred - later: reviewed research notes for recurring misses.** Use failed-query evidence to prioritize targeted agent research and produce source-backed notes with revision and expiration/invalidation. Evaluate separately from raw source retrieval and avoid training/evaluation leakage. Expected payoff depends on repeated questions and documentation gaps. [B-research]

**Inferred:** The minimal useful redesign is not "replace SQLite with a vector database". It is a measured evidence pipeline that preserves source structure, searches complementary representations, assembles sufficient context, and keeps its answer budget and provenance explicit. Database changes should follow measured limits rather than precede those improvements.

## Source list and reproducibility

**Observed:** Checkouts inspected, all shallow and retained under the research directory: Context7 `6b636d3c35e051a1a653a236afb7f612c02a1ad3`; docs-mcp-server `c180d7c2679d7886d14d42eed36a827d9befe5d3`; claude-context `6fc318b4e3ce58e2898b00a9c3538ead9e24dee5`; Serena `d9e4c796fae0207ba6848d1df4b331122a5567b5`; GitMCP `c487a29895dcfcb5b672247e646426a56e2051c1`; CocoIndex `d3a84b16b390aa51b7042a647d401bae1c6510b4`; Aider `5dc9490bb35f9729ef2c95d00a19ccd30c26339c`; c7score archive `efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f`. No dependencies were installed and no benchmark or model inference was executed.

**Observed:** The inspected local backend has SHA-256 `f6fff9f6ca7ec067e129c0d606953924ee42cd7b241ddccd145bf3eb1635d97b`. Its source link is a local path because the report assesses the working source as observed, independently of later changes.

**Observed:** Probe artifacts are saved in `<external-workspace>/research-src/context7-probes/`. Each records URL, status, selected non-sensitive headers, and raw response body. They establish shapes on this date, not correctness or stability of every returned snippet. Research did not execute login, submission, refresh, policy mutation, or account creation.

### First-party Context7 publications

- [Introducing Context7, 2025-03-31][B-launch]: original pipeline and Redis caching statement.
- [Better Context7 Output Quality with Code Scoring, 2025-09-01][B-score]: c7score's published purpose and evaluation categories.
- [Inside Context7's Quality Stack, 2025-12-08][B-quality]: reputation, benchmark, enrichment, and screening.
- [Context7 Without Context Bloat, 2026-01-07][B-rerank]: query-driven reranking and reported token/call reductions.
- [How Context7 Researches Its Own Weak Spots, 2026-06-05][B-research]: asynchronous researched context and reported tradeoffs.
- [How Redis Search Powers Millions of Searches in Context7, 2026-06-24][B-redis]: library resolver implementation description.
- [Context7 Search, 2026-09-22][B-search]: one-call grounding API introduction.
- [Context7 crawler policy][B-crawler]: website indexing policy, observed 2026-10-17.

### Public source entry points

- Context7: [pinned MCP HTTP implementation][C-api], [pinned CLI implementation][C-pinned-cli], [current tool implementation][C-mcp], [current API guide][C-guide], [ingestion][C-ingest], [owner configuration][C-owner], [schema][C-schema], [refresh][C-refresh], and [enterprise vector stores][C-stores].
- docs-mcp-server: [store/search][D-store], [splitter][D-split], [retriever][D-retrieve], [Markdown assembly][D-assembly], and [hierarchical assembly][D-hierarchy].
- claude-context: [splitter][Z-split], [retrieval][Z-context], [Milvus adapter][Z-store], and [MCP response formatting][Z-handler].
- Serena: [symbol tools][R-symbol], [file tools][R-file], and [component licensing][R-license].
- GitMCP: [retrieval dispatch][G-tools], [fallback embedding and search][G-vector], and [GitHub code search][G-github].
- CocoIndex: [pgvector example][X-example], [LanceDB example][X-lance], [Python splitter API][X-text], and [Rust recursive algorithm][X-recursive].
- Aider: [repo map][A-map]. Historical c7score archive: [orchestrator][S-app], [metric definitions][S-metrics], [text scoring][S-text], and [model prompts][S-prompts].

[B-launch]: https://upstash.com/blog/context7-llmtxt-cursor
[B-score]: https://upstash.com/blog/better-context7-output
[B-quality]: https://upstash.com/blog/context7-quality
[B-rerank]: https://upstash.com/blog/new-context7
[B-research]: https://upstash.com/blog/context7-research
[B-redis]: https://upstash.com/blog/how-redis-search-powers-context7
[B-search]: https://upstash.com/blog/context7-search
[B-crawler]: https://context7.com/crawler
[C-packages]: https://github.com/upstash/context7/tree/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages
[C-api]: https://github.com/upstash/context7/blob/05796c74259a768f45a3f508ae8583df1467a6dd/packages/mcp/src/lib/api.ts
[C-api-head]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/api.ts
[C-types]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/types.ts
[C-pinned-types]: https://github.com/upstash/context7/blob/f2eef4f49da71a758c91cf6cb97640c8b262ef81/packages/cli/src/types.ts
[C-pinned-cli]: https://github.com/upstash/context7/blob/f2eef4f49da71a758c91cf6cb97640c8b262ef81/packages/cli/src/utils/api.ts
[C-cli-api]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/utils/api.ts
[C-cli-docs]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/commands/docs.ts
[C-pinned-mcp]: https://github.com/upstash/context7/blob/05796c74259a768f45a3f508ae8583df1467a6dd/packages/mcp/src/index.ts
[C-mcp]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/index.ts
[C-utils]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/utils.ts
[C-headers]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/encryption.ts
[C-pinned-headers]: https://github.com/upstash/context7/blob/05796c74259a768f45a3f508ae8583df1467a6dd/packages/mcp/src/lib/encryption.ts
[C-old]: https://github.com/upstash/context7/blob/5fef38842b0cc842cef34edf1edcd925d7d8856b/src/lib/api.ts
[C-old-tool]: https://github.com/upstash/context7/blob/5fef38842b0cc842cef34edf1edcd925d7d8856b/src/index.ts
[C-middle]: https://github.com/upstash/context7/blob/f35c002beeada90ed6fdddf19c0345f9f41cccdb/src/lib/api.ts
[C-middle-tool]: https://github.com/upstash/context7/blob/f35c002beeada90ed6fdddf19c0345f9f41cccdb/src/index.ts
[C-search]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/sdk/src/commands/search/index.ts
[C-sdk]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/sdk/src/client.ts
[C-format]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/sdk/src/utils/format.ts
[C-guide]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/api-guide.mdx
[C-openapi]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/openapi-enterprise.json
[C-ingest]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/adding-libraries.mdx
[C-owner]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/library-owners.mdx
[C-schema]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/schema/context7.json
[C-refresh]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/library-updates.mdx
[C-stores]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/docs/enterprise/deployment/vector-stores.mdx
[C-cli-auth]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/utils/auth.ts
[C-cli-setup]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/setup/auth.ts
[C-cli-deployment]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/setup/deployment.ts
[C-cli-tracking]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/cli/src/utils/tracking.ts
[C-jwt]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/jwt.ts
[C-oauth-check]: https://github.com/upstash/context7/blob/6b636d3c35e051a1a653a236afb7f612c02a1ad3/packages/mcp/src/lib/oauth-token-validation.ts
[D-store]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/store/DocumentStore.ts
[D-split]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/splitter/SemanticMarkdownSplitter.ts
[D-tree]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/splitter/treesitter/TreesitterSourceCodeSplitter.ts
[D-config]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/utils/config.ts
[D-embedding]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/store/embeddings/EmbeddingFactory.ts
[D-retrieve]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/store/DocumentRetrieverService.ts
[D-assembly]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/store/assembly/strategies/MarkdownAssemblyStrategy.ts
[D-hierarchy]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/store/assembly/strategies/HierarchicalAssemblyStrategy.ts
[D-tool]: https://github.com/arabold/docs-mcp-server/blob/c180d7c2679d7886d14d42eed36a827d9befe5d3/src/tools/SearchTool.ts
[Z-split]: https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/core/src/splitter/ast-splitter.ts
[Z-context]: https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/core/src/context.ts
[Z-store]: https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/core/src/vectordb/milvus-vectordb.ts
[Z-ollama]: https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/core/src/embedding/ollama-embedding.ts
[Z-handler]: https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/mcp/src/handlers.ts
[R-symbol]: https://github.com/oraios/serena/blob/d9e4c796fae0207ba6848d1df4b331122a5567b5/src/serena/tools/symbol_tools.py
[R-file]: https://github.com/oraios/serena/blob/d9e4c796fae0207ba6848d1df4b331122a5567b5/src/serena/tools/file_tools.py
[R-core]: https://github.com/oraios/serena/blob/d9e4c796fae0207ba6848d1df4b331122a5567b5/src/serena/symbol.py
[R-license]: https://github.com/oraios/serena/blob/d9e4c796fae0207ba6848d1df4b331122a5567b5/LICENSE
[G-tools]: https://github.com/idosal/git-mcp/blob/c487a29895dcfcb5b672247e646426a56e2051c1/src/api/tools/commonTools.ts
[G-vector]: https://github.com/idosal/git-mcp/blob/c487a29895dcfcb5b672247e646426a56e2051c1/src/api/utils/vectorStore.ts
[G-github]: https://github.com/idosal/git-mcp/blob/c487a29895dcfcb5b672247e646426a56e2051c1/src/api/utils/githubClient.ts
[G-license]: https://github.com/idosal/git-mcp/blob/c487a29895dcfcb5b672247e646426a56e2051c1/LICENSE
[X-example]: https://github.com/cocoindex-io/cocoindex/blob/d3a84b16b390aa51b7042a647d401bae1c6510b4/examples/code_embedding/main.py
[X-lance]: https://github.com/cocoindex-io/cocoindex/blob/d3a84b16b390aa51b7042a647d401bae1c6510b4/examples/code_embedding_lancedb/main.py
[X-text]: https://github.com/cocoindex-io/cocoindex/blob/d3a84b16b390aa51b7042a647d401bae1c6510b4/python/cocoindex/ops/text.py
[X-recursive]: https://github.com/cocoindex-io/cocoindex/blob/d3a84b16b390aa51b7042a647d401bae1c6510b4/rust/ops_text/src/split/recursive.rs
[X-license]: https://github.com/cocoindex-io/cocoindex/blob/d3a84b16b390aa51b7042a647d401bae1c6510b4/LICENSE
[A-map]: https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py
[A-license]: https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/LICENSE.txt
[S-package]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/package.json
[S-app]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/app/getScore.ts
[S-options]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/config/options.ts
[S-utils]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/lib/utils.ts
[S-text]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/lib/textEval.ts
[S-metrics]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/lib/textMetrics.ts
[S-questions]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/services/questionEval.ts
[S-prompts]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/services/prompts/templates.ts
[S-llm]: https://github.com/MaTriXy/c7score/blob/efe4bad8f9e3c6b7aa2476333e33299dfc8fe75f/src/services/llmUtils.ts
[L-backend]: ../../skills/legacy-codebase-workflows/scripts/context7_backend.py
[P-search]: <external-workspace>/research-src/context7-probes/search.json
[P-v2]: <external-workspace>/research-src/context7-probes/resolved-json.json
[P-text]: <external-workspace>/research-src/context7-probes/resolved-txt.json
[P-v3]: <external-workspace>/research-src/context7-probes/v3.json
[P-redirect]: <external-workspace>/research-src/context7-probes/context-json.json
[P-invalid]: <external-workspace>/research-src/context7-probes/invalid.json
