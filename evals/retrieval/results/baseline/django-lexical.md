# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 8 | 2 | 0 | 0.125 | 0.500 | 0.625 | 0.625 | 0.317 | 0.562 | 1.000 | 13.017 | 16.702 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 10.904 | 14.054 |
| kind:concept | 1 | 0 | 0 | 0.000 | 0.000 | 1.000 | 1.000 | 0.200 | 1.000 | - | 12.349 | 12.349 |
| kind:config | 2 | 0 | 0 | 0.000 | 1.000 | 1.000 | 1.000 | 0.417 | 1.000 | - | 11.957 | 13.370 |
| kind:cross-file | 1 | 0 | 0 | 0.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.500 | - | 13.017 | 13.017 |
| kind:docs-howto | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 15.545 | 15.545 |
| kind:exact-symbol | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 11.520 | 16.702 |
| kind:paraphrase | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 14.113 | 14.113 |
| corpus:django | 8 | 2 | 0 | 0.125 | 0.500 | 0.625 | 0.625 | 0.317 | 0.562 | 1.000 | 13.017 | 16.702 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.625 | 0.562 | 0.048 |
| overall | 5000 | 0.625 | 0.562 | 0.040 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.062 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.043 |
| kind:config | 2000 | 1.000 | 1.000 | 0.064 |
| kind:config | 5000 | 1.000 | 1.000 | 0.073 |
| kind:cross-file | 2000 | 1.000 | 0.500 | 0.099 |
| kind:cross-file | 5000 | 1.000 | 0.500 | 0.069 |
| kind:docs-howto | 2000 | 0.000 | 0.000 | 0.000 |
| kind:docs-howto | 5000 | 0.000 | 0.000 | 0.000 |
| kind:exact-symbol | 2000 | 0.500 | 0.500 | 0.046 |
| kind:exact-symbol | 5000 | 0.500 | 0.500 | 0.031 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:django | 2000 | 0.625 | 0.562 | 0.048 |
| corpus:django | 5000 | 0.625 | 0.562 | 0.040 |
