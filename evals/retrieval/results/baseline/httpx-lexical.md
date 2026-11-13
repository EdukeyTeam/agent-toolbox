# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.615 | 0.692 | 0.692 | 0.692 | 0.654 | 0.692 | 1.000 | 1.444 | 3.426 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 1.636 | 2.436 |
| kind:concept | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 1.316 | 1.444 |
| kind:config | 3 | 0 | 0 | 0.333 | 0.667 | 0.667 | 0.667 | 0.500 | 0.667 | - | 1.412 | 2.450 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 3.426 | 3.426 |
| kind:docs-howto | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.387 | 2.471 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.174 | 1.193 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 1.780 | 3.354 |
| corpus:httpx | 13 | 2 | 0 | 0.615 | 0.692 | 0.692 | 0.692 | 0.654 | 0.692 | 1.000 | 1.444 | 3.426 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.692 | 0.692 | 0.104 |
| overall | 5000 | 0.692 | 0.692 | 0.072 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 0.500 | 0.500 | 0.078 |
| kind:concept | 5000 | 0.500 | 0.500 | 0.053 |
| kind:config | 2000 | 0.667 | 0.667 | 0.103 |
| kind:config | 5000 | 0.667 | 0.667 | 0.071 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.370 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.254 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.064 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.047 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.159 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.113 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:httpx | 2000 | 0.692 | 0.692 | 0.104 |
| corpus:httpx | 5000 | 0.692 | 0.692 | 0.072 |
