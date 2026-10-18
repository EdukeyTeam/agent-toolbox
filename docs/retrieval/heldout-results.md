# Held-out evaluation of the local retrieval engine

Date: 2026-10-17. The held-out set has 74 questions over the same four pinned corpora as the development sets (httpx, vite, jFTP, Django): 68 with source-range answers and 6 absent-API questions. It was written by GLM-5.3, a different model family from the engine's implementer (gpt-6.1 Sol), from the corpora alone, without access to the engine, its code or the development questions; a second pass re-checked every range. The engine authors never saw it, and it was run only by the orchestrator. One absent question was dropped before scoring because its "absent" token (`download`) occurs in httpx. The questions are kept outside this repository so later tuning cannot read them.

Scoring uses the shipped `skills/legacy-codebase-workflows/scripts/eval_retrieval.py` unchanged: a hit is any same-path line overlap with an expected range; latency is CLI wall time per query including process start and freshness checks.

| Engine and lane | Hit@1 | Hit@5 | MRR@10 | httpx | vite | jFTP | Django | p50 per corpus (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Old backend (d551ebd), lexical | 25.0% | 48.5% | 0.340 | 61% | 56% | 33% | 43% | 0.66 / 4.17 / 2.23 / 12.41 |
| New engine round 1, lexical Tier 0 | 35.3% | 50.0% | 0.439 | 50% | 56% | 44% | 50% | 0.59 / 1.04 / 1.03 / 1.93 |
| New engine round 2, lexical Tier 0 (stdlib only) | 36.8% | 57.4% | 0.455 | 61% | 56% | 50% | 64% | 0.28 / 0.41 / 0.53 / 0.72 |
| New engine round 2, lexical Tier 1 (tree-sitter) | 44.1% | 63.2% | 0.522 | 61% | 78% | 50% | 64% | 0.30 / 0.40 / 0.45 / 0.67 |
| New engine round 2, hybrid (Model2Vec potion-code-16M-v2) | 48.5% | 70.6% | 0.573 | 72% | 83% | 67% | 57% | 1.57 / 1.60 / 1.73 / 2.53 |
| Final (after review fixes), lexical Tier 0 | 36.8% | 57.4% | 0.457 | 61% | 56% | 50% | 64% | 0.35 / 0.42 / 0.54 / 1.00 |
| Final, lexical Tier 1 | 44.1% | 63.2% | 0.522 | 61% | 78% | 50% | 64% | 0.33 / 0.38 / 0.45 / 0.75 |
| Final, hybrid | 48.5% | 73.5% | 0.578 | 72% | 89% | 67% | 64% | 1.51 / 1.72 / 1.81 / 2.75 |

Hit@5 by question kind (pooled over corpora):

| Lane | exact-symbol | concept | paraphrase | config | docs-howto | cross-file |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Old backend | 14/15 | 6/18 | 2/11 | 3/8 | 2/8 | 6/8 |
| Round 1 lexical | 15/15 | 8/18 | 2/11 | 4/8 | 4/8 | 1/8 |
| Round 2 lexical Tier 0 | 15/15 | 9/18 | 2/11 | 4/8 | 5/8 | 4/8 |
| Round 2 lexical Tier 1 | 15/15 | 9/18 | 2/11 | 6/8 | 5/8 | 6/8 |
| Round 2 hybrid | 13/15 | 11/18 | 5/11 | 6/8 | 7/8 | 6/8 |
| Final hybrid | 15/15 | 11/18 | 5/11 | 6/8 | 7/8 | 6/8 |

What this shows: round 1 reached 76.6% hit@5 on the development set but only 50.0% held-out, so most of its gain was tuning to the development questions; round 2 added a second development set from another model family and re-checked every heuristic against both, which moved held-out lexical hit@5 to 57.4% (Tier 0) and 63.2% (Tier 1) with large latency gains. Hybrid search is the largest single improvement, especially for paraphrase and documentation questions, but in round 2 it lost two exact-symbol hits; the final review-fix round keeps exact symbol and path hits ahead of dense-only candidates, which restored 15/15 and lifted hybrid to 73.5%. The final runs reuse the round-2 indexes (query-side changes only), so chunking fixes from the review round are not reflected in these numbers. CLI hybrid latency includes loading the model in every process; a warm `serve` process avoids that. Small per-kind counts (8-18 questions) make differences of one or two questions noise; treat the direction, not the decimals, as the result.
