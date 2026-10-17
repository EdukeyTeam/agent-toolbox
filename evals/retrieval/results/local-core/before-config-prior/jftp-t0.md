# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.385 | 0.462 | 0.538 | 0.615 | 0.453 | 0.538 | 1.000 | 0.725 | 1.024 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.523 | 0.566 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 1.000 | 1.000 | 0.625 | 1.000 | - | 0.668 | 0.936 |
| kind:config | 3 | 0 | 0 | 0.333 | 0.667 | 0.667 | 0.667 | 0.500 | 0.667 | - | 0.724 | 0.725 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | - | 0.973 | 0.973 |
| kind:docs-howto | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.500 | 0.071 | 0.500 | - | 0.701 | 0.842 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.750 | - | 0.695 | 0.788 |
| kind:paraphrase | 3 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 1.021 | 1.024 |
| corpus:jftp | 13 | 2 | 0 | 0.385 | 0.462 | 0.538 | 0.615 | 0.453 | 0.538 | 1.000 | 0.725 | 1.024 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.538 | 0.462 | 0.037 |
| overall | 5000 | 0.615 | 0.538 | 0.036 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.116 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.093 |
| kind:config | 2000 | 0.667 | 0.667 | 0.045 |
| kind:config | 5000 | 0.667 | 0.667 | 0.035 |
| kind:cross-file | 2000 | 1.000 | 0.500 | 0.030 |
| kind:cross-file | 5000 | 1.000 | 0.500 | 0.017 |
| kind:docs-howto | 2000 | 0.000 | 0.000 | 0.000 |
| kind:docs-howto | 5000 | 0.500 | 0.500 | 0.042 |
| kind:exact-symbol | 2000 | 1.000 | 0.750 | 0.043 |
| kind:exact-symbol | 5000 | 1.000 | 0.750 | 0.036 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:jftp | 2000 | 0.538 | 0.462 | 0.037 |
| corpus:jftp | 5000 | 0.615 | 0.538 | 0.036 |
