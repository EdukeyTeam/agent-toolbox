# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.385 | 0.769 | 0.769 | 0.846 | 0.564 | 0.846 | 1.000 | 3.096 | 6.309 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 4.294 | 4.742 |
| kind:concept | 2 | 0 | 0 | 0.000 | 0.500 | 0.500 | 1.000 | 0.250 | 1.000 | - | 3.075 | 3.096 |
| kind:config | 3 | 0 | 0 | 0.000 | 0.333 | 0.333 | 0.333 | 0.167 | 0.333 | - | 2.957 | 3.732 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 3.838 | 3.838 |
| kind:docs-howto | 3 | 0 | 0 | 0.333 | 1.000 | 1.000 | 1.000 | 0.611 | 1.000 | - | 2.992 | 3.095 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 4.008 | 6.309 |
| kind:paraphrase | 2 | 0 | 0 | 0.500 | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | - | 2.393 | 3.466 |
| corpus:httpx | 13 | 2 | 0 | 0.385 | 0.769 | 0.769 | 0.846 | 0.564 | 0.846 | 1.000 | 3.096 | 6.309 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.846 | 0.846 | 0.097 |
| overall | 5000 | 0.846 | 0.846 | 0.076 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.085 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.061 |
| kind:config | 2000 | 0.333 | 0.333 | 0.041 |
| kind:config | 5000 | 0.333 | 0.333 | 0.029 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.313 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.254 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.059 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.046 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.151 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.107 |
| kind:paraphrase | 2000 | 1.000 | 1.000 | 0.087 |
| kind:paraphrase | 5000 | 1.000 | 1.000 | 0.088 |
| corpus:httpx | 2000 | 0.846 | 0.846 | 0.097 |
| corpus:httpx | 5000 | 0.846 | 0.846 | 0.076 |
