# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.692 | 0.692 | 0.692 | 0.692 | 0.692 | 0.692 | 1.000 | 0.490 | 0.656 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.235 | 0.426 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.370 | 0.654 |
| kind:config | 3 | 0 | 0 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | 0.667 | - | 0.553 | 0.656 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.543 | 0.543 |
| kind:docs-howto | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.483 | 0.556 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.421 | 0.614 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 0.439 | 0.613 |
| corpus:httpx | 13 | 2 | 0 | 0.692 | 0.692 | 0.692 | 0.692 | 0.692 | 0.692 | 1.000 | 0.490 | 0.656 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.692 | 0.692 | 0.093 |
| overall | 5000 | 0.692 | 0.692 | 0.083 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.094 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.094 |
| kind:config | 2000 | 0.667 | 0.667 | 0.070 |
| kind:config | 5000 | 0.667 | 0.667 | 0.058 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.248 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.234 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.059 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.047 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.196 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.172 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:httpx | 2000 | 0.692 | 0.692 | 0.093 |
| corpus:httpx | 5000 | 0.692 | 0.692 | 0.083 |
