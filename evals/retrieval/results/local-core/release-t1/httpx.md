# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 1.000 | 0.433 | 1.036 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.433 | 0.489 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.379 | 0.597 |
| kind:config | 3 | 0 | 0 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | - | 0.525 | 0.532 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.870 | 0.870 |
| kind:docs-howto | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.431 | 1.036 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.394 | 0.431 |
| kind:paraphrase | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.326 | 0.724 |
| corpus:httpx | 13 | 2 | 0 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 0.769 | 1.000 | 0.433 | 1.036 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.769 | 0.769 | 0.104 |
| overall | 5000 | 0.769 | 0.769 | 0.096 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.087 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.087 |
| kind:config | 2000 | 0.667 | 0.667 | 0.070 |
| kind:config | 5000 | 0.667 | 0.667 | 0.062 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.286 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.286 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.059 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.049 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.196 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.172 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.056 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.056 |
| corpus:httpx | 2000 | 0.769 | 0.769 | 0.104 |
| corpus:httpx | 5000 | 0.769 | 0.769 | 0.096 |
