# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.615 | 0.692 | 0.692 | 0.846 | 0.678 | 0.846 | 1.000 | 3.813 | 5.406 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 3.813 | 4.061 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 2.986 | 3.663 |
| kind:config | 3 | 0 | 0 | 0.333 | 0.667 | 0.667 | 0.667 | 0.500 | 0.667 | - | 3.608 | 3.797 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 4.122 | 4.122 |
| kind:docs-howto | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 3.973 | 4.339 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 3.045 | 3.897 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 1.000 | 0.155 | 1.000 | - | 4.554 | 5.406 |
| corpus:httpx | 13 | 2 | 0 | 0.615 | 0.692 | 0.692 | 0.846 | 0.678 | 0.846 | 1.000 | 3.813 | 5.406 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.846 | 0.846 | 0.105 |
| overall | 5000 | 0.846 | 0.846 | 0.085 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.063 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.044 |
| kind:config | 2000 | 0.667 | 0.667 | 0.090 |
| kind:config | 5000 | 0.667 | 0.667 | 0.074 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.313 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.254 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.059 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.045 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.151 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.143 |
| kind:paraphrase | 2000 | 1.000 | 1.000 | 0.087 |
| kind:paraphrase | 5000 | 1.000 | 1.000 | 0.062 |
| corpus:httpx | 2000 | 0.846 | 0.846 | 0.105 |
| corpus:httpx | 5000 | 0.846 | 0.846 | 0.085 |
