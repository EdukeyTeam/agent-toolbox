# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 47 | 8 | 0 | 0.234 | 0.340 | 0.404 | 0.447 | 0.301 | 0.426 | 1.000 | 3.581 | 11.759 |
| kind:absent | 0 | 8 | 0 | - | - | - | - | - | - | 1.000 | 2.882 | 11.162 |
| kind:concept | 8 | 0 | 0 | 0.000 | 0.000 | 0.125 | 0.125 | 0.031 | 0.125 | - | 3.109 | 11.140 |
| kind:config | 10 | 0 | 0 | 0.100 | 0.400 | 0.400 | 0.500 | 0.244 | 0.500 | - | 3.581 | 12.975 |
| kind:cross-file | 4 | 0 | 0 | 0.250 | 0.500 | 0.500 | 0.500 | 0.375 | 0.375 | - | 2.610 | 9.284 |
| kind:docs-howto | 9 | 0 | 0 | 0.111 | 0.222 | 0.444 | 0.556 | 0.216 | 0.556 | - | 3.434 | 11.759 |
| kind:exact-symbol | 8 | 0 | 0 | 0.875 | 0.875 | 0.875 | 0.875 | 0.875 | 0.812 | - | 4.307 | 11.985 |
| kind:paraphrase | 8 | 0 | 0 | 0.125 | 0.125 | 0.125 | 0.125 | 0.125 | 0.125 | - | 2.932 | 11.176 |
| corpus:django | 8 | 2 | 0 | 0.250 | 0.625 | 0.750 | 0.750 | 0.448 | 0.688 | 1.000 | 11.162 | 12.975 |
| corpus:httpx | 13 | 2 | 0 | 0.385 | 0.462 | 0.462 | 0.462 | 0.410 | 0.462 | 1.000 | 1.451 | 3.021 |
| corpus:jftp | 13 | 2 | 0 | 0.077 | 0.077 | 0.154 | 0.231 | 0.105 | 0.192 | 1.000 | 2.978 | 4.307 |
| corpus:vite | 13 | 2 | 0 | 0.231 | 0.308 | 0.385 | 0.462 | 0.297 | 0.462 | 1.000 | 7.063 | 8.506 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.426 | 0.404 | 0.045 |
| overall | 5000 | 0.447 | 0.426 | 0.038 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.125 | 0.125 | 0.008 |
| kind:concept | 5000 | 0.125 | 0.125 | 0.005 |
| kind:config | 2000 | 0.400 | 0.400 | 0.030 |
| kind:config | 5000 | 0.500 | 0.500 | 0.030 |
| kind:cross-file | 2000 | 0.500 | 0.375 | 0.097 |
| kind:cross-file | 5000 | 0.500 | 0.375 | 0.080 |
| kind:docs-howto | 2000 | 0.556 | 0.556 | 0.068 |
| kind:docs-howto | 5000 | 0.556 | 0.556 | 0.058 |
| kind:exact-symbol | 2000 | 0.875 | 0.812 | 0.071 |
| kind:exact-symbol | 5000 | 0.875 | 0.812 | 0.051 |
| kind:paraphrase | 2000 | 0.125 | 0.125 | 0.022 |
| kind:paraphrase | 5000 | 0.125 | 0.125 | 0.022 |
| corpus:django | 2000 | 0.750 | 0.688 | 0.054 |
| corpus:django | 5000 | 0.750 | 0.688 | 0.044 |
| corpus:httpx | 2000 | 0.462 | 0.462 | 0.067 |
| corpus:httpx | 5000 | 0.462 | 0.462 | 0.051 |
| corpus:jftp | 2000 | 0.231 | 0.192 | 0.029 |
| corpus:jftp | 5000 | 0.231 | 0.192 | 0.026 |
| corpus:vite | 2000 | 0.385 | 0.385 | 0.033 |
| corpus:vite | 5000 | 0.462 | 0.462 | 0.031 |
