# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.385 | 0.692 | 0.923 | 0.923 | 0.554 | 0.923 | 1.000 | 0.648 | 0.785 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.615 | 0.642 |
| kind:concept | 3 | 0 | 0 | 0.000 | 0.333 | 1.000 | 1.000 | 0.261 | 1.000 | - | 0.617 | 0.648 |
| kind:config | 2 | 0 | 0 | 0.000 | 1.000 | 1.000 | 1.000 | 0.417 | 1.000 | - | 0.583 | 0.752 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.742 | 0.742 |
| kind:docs-howto | 3 | 0 | 0 | 0.667 | 1.000 | 1.000 | 1.000 | 0.778 | 1.000 | - | 0.756 | 0.785 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.660 | 0.671 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.500 | 0.500 | 0.125 | 0.500 | - | 0.634 | 0.702 |
| corpus:vite | 13 | 2 | 0 | 0.385 | 0.692 | 0.923 | 0.923 | 0.554 | 0.923 | 1.000 | 0.648 | 0.785 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.923 | 0.923 | 0.079 |
| overall | 5000 | 0.923 | 0.923 | 0.065 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.135 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.115 |
| kind:config | 2000 | 1.000 | 1.000 | 0.040 |
| kind:config | 5000 | 1.000 | 1.000 | 0.027 |
| kind:cross-file | 2000 | 1.000 | 1.000 | 0.094 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.069 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.073 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.061 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.029 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.024 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.089 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.076 |
| corpus:vite | 2000 | 0.923 | 0.923 | 0.079 |
| corpus:vite | 5000 | 0.923 | 0.923 | 0.065 |
