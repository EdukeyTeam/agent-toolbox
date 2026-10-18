# Evaluation on full Payload CMS and Next.js repositories

Date: 2026-10-18. Corpora: full shallow clones of `payloadcms/payload` at `d5b01b40d81cd32621aa883cc8a3cc78ce13bf2d` (9,760 tracked files, MDX docs) and `vercel/next.js` at `bb63c72077ad7b81b2319f74a7ef3b00c1751483` (34,271 tracked files, `next@16.5.0-canary.17`, MDX docs, Rust crates and many test fixtures). Hardware: 7 vCPU AMD EPYC, no GPU, WSL2 on ext4.

## Question set

GLM-5.3 wrote 30 questions per repository (exact-symbol, concept, paraphrase, config, docs-howto, cross-file, absent; about half rated hard) from the repositories alone. Gemini 4 Argon then reviewed every question against the source: it kept 5, fixed 44 (ranges, missing alternative answer locations, identifier leakage) and replaced 11 weak questions with harder ones. The engine's implementer (gpt-6.1 Sol) never saw the questions. Like the small-corpus held-out set, the questions are kept outside the repository. One caveat applies: the orchestrator inspected failures on this set and turned two generic patterns into fix requests (build-directory excludes, JavaScript arrow-function symbols), so the "after" numbers are not a fully blind measurement.

## Indexing at full scale

| Repository | Lane | Index time | Peak RSS | Index size (before -> after fixes) |
| --- | --- | ---: | ---: | --- |
| Payload | lexical Tier 0 | 2:01 | 53 MB | 338 MB |
| Payload | Tier 1 (tree-sitter) | 4:19 | 94 MB | 278 MB |
| Payload | hybrid (Model2Vec) | 4:14 | 159 MB | 434 MB |
| Next.js | lexical Tier 0 | 6:59 | 166 MB | 981 -> 784 MB |
| Next.js | Tier 1 | 9:07 | 205 MB | 928 MB |
| Next.js | hybrid | 10:36 | 271 MB | 1,246 -> 1,018 MB |

The old backend (commit d551ebd) refuses both repositories: `Chunk limit 30000 exceeded; index a smaller subtree`.

## Retrieval quality (hit@5 over positive questions; one question is about 3.4 points)

| Lane | Payload before fixes | Payload after | Next.js before | Next.js after | Next.js p50 after |
| --- | ---: | ---: | ---: | ---: | --- |
| Lexical Tier 0 | 72% | 62% | 45% | 55% | 1.5 s CLI |
| Tier 1 | 59% | 66% | 59% | 69% | 1.6 s CLI |
| Hybrid | 83% | 76% | 48% | 62% | 3.9 s CLI with model load; 0.5 s warm `serve` |

"Before" is commit a5a310a/c47a7eb on the first big-repo indexes; "after" is commit 61beb39 on rebuilt indexes. The fixes restored 289 Next.js build source files that a name-based exclude had dropped and added JavaScript/TypeScript arrow-function definitions as symbols, which lifted Next.js by 10-14 points. On Payload the same changes shifted several near-miss answers from ranks 1-5 to ranks 6-10 (hybrid hit@10 rose from 90% to 93%), crowded out by multiple units from one file and import-only header units. On the small-corpus held-out set the same commit moved lexical Tier 0 from 57.4% to 58.8%, Tier 1 from 63.2% to 60.3% and hybrid from 73.5% to 69.1% hit@5, while MRR rose for Tier 0 and hybrid.

What it means for users: on large modern monorepos the engine answers roughly six to seven of ten hard questions in the top five with tree-sitter or hybrid search, exact-symbol questions are reliable, documentation how-to questions are near perfect, and paraphrased questions without shared vocabulary remain the weakest category (hybrid helps). Small question counts make single-digit differences noise; the direction across lanes and repositories is the meaningful signal.
