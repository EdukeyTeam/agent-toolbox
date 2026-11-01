# Retrieval dev set 2

Second development question set for the local retrieval engine. It is independent of `*.dev.jsonl` and exists so tuning is not fit to a single dev set. Each line is one JSON object. `path` is relative to the corpus root. `start` and `end` are inclusive 1-based line numbers in the current checkout. Up to three ranges are listed when the answer really lives in more than one place, and any one of them counts as a hit. Absent questions use `expected: []` and an `absentIdentifier` field. The identifier also appears in backticks in the question.

Corpora are read-only checkouts at a caller-selected corpus directory (pass it to the evaluator with `--corpus-root`). jftp questions use `src/` and `README.md` only. The jftp `docs/` tree was written by agents and is not cited.

## Counts

| Corpus | Questions | exact-symbol | concept | paraphrase | config | docs-howto | cross-file | absent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| httpx | 20 | 2 | 4 | 4 | 2 | 2 | 4 | 2 |
| vite | 20 | 2 | 4 | 4 | 2 | 2 | 4 | 2 |
| jftp | 20 | 2 | 6 | 4 | 2 | 0 | 4 | 2 |
| django | 15 | 1 | 4 | 4 | 1 | 0 | 4 | 1 |

## Why the mix differs from the base aim

The base aim is 4 exact-symbol, 4 concept, 3 paraphrase, 2 config, 3 docs-howto, 2 cross-file, and 2 absent, which sums to 20. This set also keeps a floor of 4 concept, 4 paraphrase, and 4 cross-file on every corpus, including django. A cross-file question cites at least two ranges in different files.

For httpx and vite the three extra floor slots come from exact-symbol (4 down to 2) and docs-howto (3 down to 2).

jftp has no documentation this set is allowed to use, so its two docs-howto slots are concept questions. That is 6 concept and 0 docs-howto.

Django has 15 questions. After the three floors, three slots remain: 1 exact-symbol, 1 config, and 1 absent. There is no pure docs-howto question. Documentation is still in the set through `django-d2-13`, a cross-file triple: `docs/topics/security.txt` 203-211 names `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, and `SECURE_HSTS_PRELOAD`; `django/middleware/security.py` 11-15 copies those settings; lines 35-46 write `Strict-Transport-Security`. Django docs are reStructuredText (`.txt`). Those lines are the ground truth even if a baseline indexer skips `.txt`.

`django-d2-04` has two ranges in the same file (`Paginator.page` and `Paginator.num_pages`). It is concept, not cross-file, because both methods are the orphan-row behavior.

## Verification

Every cited span was read in the checkout and kept to the function, method, branch, or doc section that answers the question. A Python check then parsed every line and required `id`, `corpus`, `kind`, `question`, `expected`, and `notes`. Absent rows also have a single-token `absentIdentifier` and an empty `expected`. The check confirmed each path exists, each start and end is inside the file, no cited span begins or ends on a blank line, no two spans in the same file overlap, each cross-file question names at least two files, questions and notes are ASCII, and no question text or line span is reused from `*.dev.jsonl`.

The same check walked each corpus, skipping `.git`, `node_modules`, and virtualenv directories, and found no occurrence of the absent identifiers: `HTTP3Transport`, `iter_sse`, `experimentalEdgeRuntime`, `prefetchModuleGraph`, `WebSocketTransfer`, `FtpKeepAliveDaemon`, `soft_delete_cascade`.

Edited spans were checked again for a distinctive string inside the range: `encode_json` for the JSON request path, the Basic auth header return, `manifest: true` and `@vite/client` in the backend guide, `stripBase` in the base middleware, `client.abort()` in the abort action, `deleteRemoteFiles()` in the delete action, and both `SECURE_HSTS_SECONDS` and `Strict-Transport-Security` in the HSTS middleware.

## Short ranges

These are the whole method or the whole relevant block, so they are shorter than the usual 5-80 line guide:

- `vite-d2-16` installs the host check in six lines (`packages/vite/src/node/server/index.ts` 1015-1020). The middleware that explains a blocked host is the other range.
- `jftp-d2-07` `dataTransferAborted` is the whole method, seven lines (`FTPSession.java` 560-566).
- `jftp-d2-18` `KeyStoreManager.getServerCertificateStore` is the whole method, seven lines (60-66).
- `django-d2-04` `page` is eight lines (170-177) and `num_pages` is six lines (188-193).
- `django-d2-11` the CSRF exempt early return is eight lines (`csrf.py` 416-423).
- `django-d2-13` the three HSTS settings are copied in five lines (`security.py` 11-15).
- `httpx-d2-08` covers `WSGITransport.__init__` and `handle_request` in one 73-line span (`wsgi.py` 77-149).

`vite-d2-05` cites `compileCSS` through the Lightning CSS or PostCSS call (`css.ts` 1504-1556). The function continues with its return. The cited lines are the preprocessor step and the transform that follows it.

## Unsure

`jftp-d2-16` is two calls deep. `DeleteRemoteFileAction.actionPerformed` (lines 50-56) calls `FTPSession.deleteRemoteFiles` (lines 1206-1247). That method asks for confirmation and then calls the private `delete(RemoteFile)` at lines 1249-1278, which lists the directory, deletes each child, and then deletes the directory. The confirming method is not an expected range. A retriever that stops there misses both expected spans. It was left out because it does not itself remove children before the directory, and any one expected range counts as a hit, so including it would have scored the confirmation dialog as the answer.

`vite-d2-12` points at the `json.stringify` docs (`docs/config/shared-options.md` 464-471), including the roughly 10kB `auto` cutoff. In this checkout the plugin is `viteJsonPlugin` from `rolldown/experimental`, invoked as `nativeJsonPlugin` in `packages/vite/src/node/plugins/index.ts`. There is no local transform body that states the cutoff, so the doc section is the ground truth.
