# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.308 | 0.462 | 0.538 | 0.692 | 0.419 | 0.654 | 1.000 | 8.029 | 10.857 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 5.439 | 6.341 |
| kind:concept | 3 | 0 | 0 | 0.000 | 0.333 | 0.667 | 0.667 | 0.250 | 0.667 | - | 8.340 | 9.145 |
| kind:config | 2 | 0 | 0 | 0.000 | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | - | 7.727 | 10.857 |
| kind:cross-file | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 1.000 | 0.100 | 0.500 | - | 9.665 | 9.665 |
| kind:docs-howto | 3 | 0 | 0 | 0.333 | 0.333 | 0.333 | 0.667 | 0.367 | 0.667 | - | 8.029 | 8.452 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 6.527 | 9.313 |
| kind:paraphrase | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 6.311 | 9.901 |
| corpus:vite | 13 | 2 | 0 | 0.308 | 0.462 | 0.538 | 0.692 | 0.419 | 0.654 | 1.000 | 8.029 | 10.857 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.538 | 0.538 | 0.051 |
| overall | 5000 | 0.692 | 0.654 | 0.048 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.667 | 0.667 | 0.086 |
| kind:concept | 5000 | 0.667 | 0.667 | 0.066 |
| kind:config | 2000 | 0.500 | 0.500 | 0.013 |
| kind:config | 5000 | 0.500 | 0.500 | 0.009 |
| kind:cross-file | 2000 | 0.000 | 0.000 | 0.000 |
| kind:cross-file | 5000 | 1.000 | 0.500 | 0.055 |
| kind:docs-howto | 2000 | 0.333 | 0.333 | 0.049 |
| kind:docs-howto | 5000 | 0.667 | 0.667 | 0.059 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.041 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.034 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.075 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.053 |
| corpus:vite | 2000 | 0.538 | 0.538 | 0.051 |
| corpus:vite | 5000 | 0.692 | 0.654 | 0.048 |
