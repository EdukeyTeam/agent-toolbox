# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.077 | 0.077 | 0.077 | 0.077 | 0.077 | 0.038 | 1.000 | 3.837 | 5.019 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 3.151 | 3.832 |
| kind:concept | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 4.337 | 5.019 |
| kind:config | 3 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 3.733 | 4.056 |
| kind:cross-file | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 4.060 | 4.060 |
| kind:docs-howto | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 3.007 | 3.562 |
| kind:exact-symbol | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.250 | - | 3.835 | 4.431 |
| kind:paraphrase | 3 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 4.248 | 4.598 |
| corpus:jftp | 13 | 2 | 0 | 0.077 | 0.077 | 0.077 | 0.077 | 0.077 | 0.038 | 1.000 | 3.837 | 5.019 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.077 | 0.038 | 0.002 |
| overall | 5000 | 0.077 | 0.038 | 0.001 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.000 | 0.000 | 0.000 |
| kind:concept | 5000 | 0.000 | 0.000 | 0.000 |
| kind:config | 2000 | 0.000 | 0.000 | 0.000 |
| kind:config | 5000 | 0.000 | 0.000 | 0.000 |
| kind:cross-file | 2000 | 0.000 | 0.000 | 0.000 |
| kind:cross-file | 5000 | 0.000 | 0.000 | 0.000 |
| kind:docs-howto | 2000 | 0.000 | 0.000 | 0.000 |
| kind:docs-howto | 5000 | 0.000 | 0.000 | 0.000 |
| kind:exact-symbol | 2000 | 0.500 | 0.250 | 0.011 |
| kind:exact-symbol | 5000 | 0.500 | 0.250 | 0.008 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:jftp | 2000 | 0.077 | 0.038 | 0.002 |
| corpus:jftp | 5000 | 0.077 | 0.038 | 0.001 |
