# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.385 | 0.462 | 0.462 | 0.462 | 0.410 | 0.462 | 1.000 | 1.451 | 3.021 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 1.312 | 1.697 |
| kind:concept | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 0.999 | 3.021 |
| kind:config | 3 | 0 | 0 | 0.333 | 0.333 | 0.333 | 0.333 | 0.333 | 0.333 | - | 1.468 | 1.791 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.442 | 1.442 |
| kind:docs-howto | 3 | 0 | 0 | 0.333 | 0.667 | 0.667 | 0.667 | 0.444 | 0.667 | - | 1.597 | 2.034 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.451 | 2.149 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 1.149 | 1.193 |
| corpus:httpx | 13 | 2 | 0 | 0.385 | 0.462 | 0.462 | 0.462 | 0.410 | 0.462 | 1.000 | 1.451 | 3.021 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.462 | 0.462 | 0.067 |
| overall | 5000 | 0.462 | 0.462 | 0.051 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.000 | 0.000 | 0.000 |
| kind:concept | 5000 | 0.000 | 0.000 | 0.000 |
| kind:config | 2000 | 0.333 | 0.333 | 0.049 |
| kind:config | 5000 | 0.333 | 0.333 | 0.034 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.288 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.253 |
| kind:docs-howto | 2000 | 0.667 | 0.667 | 0.039 |
| kind:docs-howto | 5000 | 0.667 | 0.667 | 0.028 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.159 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.113 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:httpx | 2000 | 0.462 | 0.462 | 0.067 |
| corpus:httpx | 5000 | 0.462 | 0.462 | 0.051 |
