# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 1.000 | 0.432 | 0.885 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.263 | 0.410 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.443 | 0.590 |
| kind:config | 3 | 0 | 0 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | - | 0.478 | 0.534 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.375 | 0.375 |
| kind:docs-howto | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.371 | 0.442 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.671 | 0.885 |
| kind:paraphrase | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.339 | 0.408 |
| corpus:httpx | 13 | 2 | 0 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 1.000 | 0.432 | 0.885 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.769 | 0.769 | 0.105 |
| overall | 5000 | 0.769 | 0.769 | 0.097 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.086 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.086 |
| kind:config | 2000 | 0.667 | 0.667 | 0.070 |
| kind:config | 5000 | 0.667 | 0.667 | 0.062 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.286 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.286 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.059 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.050 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.196 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.172 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.061 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.061 |
| corpus:httpx | 2000 | 0.769 | 0.769 | 0.105 |
| corpus:httpx | 5000 | 0.769 | 0.769 | 0.097 |
