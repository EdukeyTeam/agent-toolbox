# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.231 | 0.308 | 0.385 | 0.462 | 0.297 | 0.462 | 1.000 | 7.063 | 8.506 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 7.704 | 8.469 |
| kind:concept | 3 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 6.764 | 7.513 |
| kind:config | 2 | 0 | 0 | 0.000 | 0.500 | 0.500 | 1.000 | 0.306 | 1.000 | - | 6.487 | 6.625 |
| kind:cross-file | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 6.669 | 6.669 |
| kind:docs-howto | 3 | 0 | 0 | 0.000 | 0.000 | 0.333 | 0.333 | 0.083 | 0.333 | - | 7.814 | 8.506 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 6.815 | 7.063 |
| kind:paraphrase | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 6.660 | 8.428 |
| corpus:vite | 13 | 2 | 0 | 0.231 | 0.308 | 0.385 | 0.462 | 0.297 | 0.462 | 1.000 | 7.063 | 8.506 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.385 | 0.385 | 0.033 |
| overall | 5000 | 0.462 | 0.462 | 0.031 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.000 | 0.000 | 0.000 |
| kind:concept | 5000 | 0.000 | 0.000 | 0.000 |
| kind:config | 2000 | 0.500 | 0.500 | 0.013 |
| kind:config | 5000 | 1.000 | 1.000 | 0.025 |
| kind:cross-file | 2000 | 0.000 | 0.000 | 0.000 |
| kind:cross-file | 5000 | 0.000 | 0.000 | 0.000 |
| kind:docs-howto | 2000 | 0.333 | 0.333 | 0.049 |
| kind:docs-howto | 5000 | 0.333 | 0.333 | 0.037 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.041 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.034 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.088 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.088 |
| corpus:vite | 2000 | 0.385 | 0.385 | 0.033 |
| corpus:vite | 5000 | 0.462 | 0.462 | 0.031 |
