# Retrieval evaluation

Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.

| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 8 | 2 | 0 | 0.750 | 0.875 | 0.875 | 0.875 | 0.812 | 0.812 | 1.000 | 0.744 | 1.431 |
| kind:absent | 0 | 2 | 0 | - | - | - | - | - | - | 1.000 | 0.733 | 0.744 |
| kind:concept | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.563 | 0.563 |
| kind:config | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.842 | 1.431 |
| kind:cross-file | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | - | 0.880 | 0.880 |
| kind:docs-howto | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | - | 0.758 | 0.758 |
| kind:exact-symbol | 2 | 0 | 0 | 0.500 | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | - | 0.716 | 0.889 |
| kind:paraphrase | 1 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | - | 0.744 | 0.744 |
| corpus:django | 8 | 2 | 0 | 0.750 | 0.875 | 0.875 | 0.875 | 0.812 | 0.812 | 1.000 | 0.744 | 1.431 |

Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.

| Group | Budget | Any expected hit | Range recall | Character precision |
| --- | ---: | ---: | ---: | ---: |
| overall | 2000 | 0.875 | 0.812 | 0.063 |
| overall | 5000 | 0.875 | 0.812 | 0.047 |
| kind:absent | 2000 | - | - | - |
| kind:absent | 5000 | - | - | - |
| kind:concept | 2000 | 1.000 | 1.000 | 0.048 |
| kind:concept | 5000 | 1.000 | 1.000 | 0.037 |
| kind:config | 2000 | 1.000 | 1.000 | 0.076 |
| kind:config | 5000 | 1.000 | 1.000 | 0.046 |
| kind:cross-file | 2000 | 1.000 | 0.500 | 0.033 |
| kind:cross-file | 5000 | 1.000 | 0.500 | 0.024 |
| kind:docs-howto | 2000 | 1.000 | 1.000 | 0.094 |
| kind:docs-howto | 5000 | 1.000 | 1.000 | 0.047 |
| kind:exact-symbol | 2000 | 1.000 | 1.000 | 0.089 |
| kind:exact-symbol | 5000 | 1.000 | 1.000 | 0.088 |
| kind:paraphrase | 2000 | 0.000 | 0.000 | 0.000 |
| kind:paraphrase | 5000 | 0.000 | 0.000 | 0.000 |
| corpus:django | 2000 | 0.875 | 0.812 | 0.063 |
| corpus:django | 5000 | 0.875 | 0.812 | 0.047 |
