# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 47 | 8 | 0 | 0.298 | 0.426 | 0.468 | 0.511 | 0.372 | 0.479 | 1.000 | 4.431 | 14.113 |
| kind:absent | 0 | 8 | 0 | - | - | - | - | - | - | 1.000 | 3.832 | 14.054 |
| kind:concept | 8 | 0 | 0 | 0.125 | 0.250 | 0.500 | 0.500 | 0.244 | 0.500 | - | 5.019 | 12.349 |
| kind:config | 10 | 0 | 0 | 0.100 | 0.500 | 0.500 | 0.500 | 0.283 | 0.500 | - | 3.733 | 13.370 |
| kind:cross-file | 4 | 0 | 0 | 0.250 | 0.500 | 0.500 | 0.750 | 0.400 | 0.500 | - | 4.060 | 13.017 |
| kind:docs-howto | 9 | 0 | 0 | 0.444 | 0.444 | 0.444 | 0.556 | 0.456 | 0.556 | - | 3.562 | 15.545 |
| kind:exact-symbol | 8 | 0 | 0 | 0.750 | 0.750 | 0.750 | 0.750 | 0.750 | 0.688 | - | 4.431 | 16.702 |
| kind:paraphrase | 8 | 0 | 0 | 0.125 | 0.125 | 0.125 | 0.125 | 0.125 | 0.125 | - | 4.248 | 14.113 |
| corpus:django | 8 | 2 | 0 | 0.125 | 0.500 | 0.625 | 0.625 | 0.317 | 0.562 | 1.000 | 13.017 | 16.702 |
| corpus:httpx | 13 | 2 | 0 | 0.615 | 0.692 | 0.692 | 0.692 | 0.654 | 0.692 | 1.000 | 1.444 | 3.426 |
| corpus:jftp | 13 | 2 | 0 | 0.077 | 0.077 | 0.077 | 0.077 | 0.077 | 0.038 | 1.000 | 3.837 | 5.019 |
| corpus:vite | 13 | 2 | 0 | 0.308 | 0.462 | 0.538 | 0.692 | 0.419 | 0.654 | 1.000 | 8.029 | 10.857 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.468 | 0.447 | 0.051 |
| overall | 5000 | 0.511 | 0.479 | 0.040 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.059 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.043 |
| kind:config | 2000 | 0.500 | 0.500 | 0.046 |
| kind:config | 5000 | 0.500 | 0.500 | 0.038 |
| kind:cross-file | 2000 | 0.500 | 0.375 | 0.117 |
| kind:cross-file | 5000 | 0.750 | 0.500 | 0.094 |
| kind:docs-howto | 2000 | 0.444 | 0.444 | 0.038 |
| kind:docs-howto | 5000 | 0.556 | 0.556 | 0.035 |
| kind:exact-symbol | 2000 | 0.750 | 0.688 | 0.064 |
| kind:exact-symbol | 5000 | 0.750 | 0.688 | 0.046 |
| kind:paraphrase | 2000 | 0.125 | 0.125 | 0.019 |
| kind:paraphrase | 5000 | 0.125 | 0.125 | 0.013 |
| corpus:django | 2000 | 0.625 | 0.562 | 0.048 |
| corpus:django | 5000 | 0.625 | 0.562 | 0.040 |
| corpus:httpx | 2000 | 0.692 | 0.692 | 0.104 |
| corpus:httpx | 5000 | 0.692 | 0.692 | 0.072 |
| corpus:jftp | 2000 | 0.077 | 0.038 | 0.002 |
| corpus:jftp | 5000 | 0.077 | 0.038 | 0.001 |
| corpus:vite | 2000 | 0.538 | 0.538 | 0.051 |
| corpus:vite | 5000 | 0.692 | 0.654 | 0.048 |
