# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.615 | 0.769 | 0.923 | 0.923 | 0.727 | 0.885 | 1.000 | 1.117 | 2.440 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 1.453 | 2.440 |
| kind:concept | 3 | 0 | 0 | 0.667 | 0.667 | 1.000 | 1.000 | 0.733 | 1.000 | - | 1.257 | 1.273 |
| kind:config | 2 | 0 | 0 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | - | 0.585 | 1.592 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 1.221 | 1.221 |
| kind:docs-howto | 3 | 0 | 0 | 0.667 | 1.000 | 1.000 | 1.000 | 0.833 | 1.000 | - | 0.898 | 0.993 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.749 | 0.931 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.500 | 1.000 | 1.000 | 0.375 | 0.750 | - | 0.497 | 1.681 |
| corpus:vite | 13 | 2 | 0 | 0.615 | 0.769 | 0.923 | 0.923 | 0.727 | 0.885 | 1.000 | 1.117 | 2.440 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.923 | 0.885 | 0.081 |
| overall | 5000 | 0.923 | 0.885 | 0.063 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.136 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.109 |
| kind:config | 2000 | 0.500 | 0.500 | 0.009 |
| kind:config | 5000 | 0.500 | 0.500 | 0.008 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.107 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.084 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.073 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.055 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.041 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.028 |
| kind:paraphrase | 2000 | 1.000 | 0.750 | 0.110 |
| kind:paraphrase | 5000 | 1.000 | 0.750 | 0.082 |
| corpus:vite | 2000 | 0.923 | 0.885 | 0.081 |
| corpus:vite | 5000 | 0.923 | 0.885 | 0.063 |
