# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 13 | 2 | 0 | 0.385 | 0.692 | 0.846 | 0.923 | 0.560 | 0.923 | 1.000 | 0.654 | 0.982 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.538 | 0.815 |
| kind:concept | 3 | 0 | 0 | 0.000 | 0.333 | 0.667 | 1.000 | 0.289 | 1.000 | - | 0.628 | 0.656 |
| kind:config | 2 | 0 | 0 | 0.000 | 1.000 | 1.000 | 1.000 | 0.417 | 1.000 | - | 0.472 | 0.982 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.601 | 0.601 |
| kind:docs-howto | 3 | 0 | 0 | 0.667 | 1.000 | 1.000 | 1.000 | 0.778 | 1.000 | - | 0.658 | 0.786 |
| kind:exact-symbol | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.595 | 0.757 |
| kind:paraphrase | 2 | 0 | 0 | 0.000 | 0.000 | 0.500 | 0.500 | 0.125 | 0.500 | - | 0.654 | 0.684 |
| corpus:vite | 13 | 2 | 0 | 0.385 | 0.692 | 0.846 | 0.923 | 0.560 | 0.923 | 1.000 | 0.654 | 0.982 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.923 | 0.885 | 0.077 |
| overall | 5000 | 0.923 | 0.923 | 0.063 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.135 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.113 |
| kind:config | 2000 | 1.000 | 1.000 | 0.040 |
| kind:config | 5000 | 1.000 | 1.000 | 0.027 |
| kind:cross-file | 2000 | 1.000 | 0.500 | 0.064 |
| kind:cross-file | 5000 | 1.000 | 1.000 | 0.069 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.073 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.061 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.029 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.025 |
| kind:paraphrase | 2000 | 0.500 | 0.500 | 0.089 |
| kind:paraphrase | 5000 | 0.500 | 0.500 | 0.064 |
| corpus:vite | 2000 | 0.923 | 0.885 | 0.077 |
| corpus:vite | 5000 | 0.923 | 0.923 | 0.063 |
