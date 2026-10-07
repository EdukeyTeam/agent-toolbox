# Third-party components in this skill

This skill contains an attributed adaptation of Aider's repository-map code and copies of selected tag queries. The toolbox's other skills are outside this notice.

## Aider

- Source: [Aider-AI/aider `aider/repomap.py`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py), revision `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` (last changed in `94bd7abd17cdbcdab91b445b3ab165ecd2220938`).
- License: Apache License 2.0; the upstream [LICENSE.txt](vendor/LICENSE.txt) is included.
- Adaptation: [aider_rank.py](vendor/aider_rank.py) retains Aider's definition/reference graph weighting, personalization, PageRank rank distribution, and fallback of definitions lacking reference captures. It removes chat-file exclusion, UI/model imports, sampled model token counts, and source-tree pickle/SQLite caches. [repo_map.py](scripts/repo_map.py) adapts Aider's tag-query extraction to a bounded offline command. Rendering uses original source lines with explicit line numbers and a fixed character budget for checkable citations.
- The complete upstream `repomap.py` is not bundled. [manifest.json](vendor/manifest.json) records its SHA-256 and each copied file's upstream blob and SHA-256.

## Tag queries

The `.scm` files under `vendor/queries/` are unmodified copies from the pinned Aider revision. Aider's [language-pack query credits](vendor/queries/tree-sitter-language-pack/README.md) and [older query credits](vendor/queries/tree-sitter-languages/README.md) point to the grammar projects. The copied queries are for Java, Python, JavaScript, TypeScript/TSX, C, C++, C#, Go, and Rust. Their grammar projects use the MIT license; their individual license texts, including copyright notices, are under `vendor/licenses/`.

| Query | Grammar source | License copy |
| --- | --- | --- |
| C | [tree-sitter-c](https://github.com/tree-sitter/tree-sitter-c) | [MIT](vendor/licenses/c-LICENSE.txt) |
| C++ | [tree-sitter-cpp](https://github.com/tree-sitter/tree-sitter-cpp) | [MIT](vendor/licenses/cpp-LICENSE.txt) |
| C# | [tree-sitter-c-sharp](https://github.com/tree-sitter/tree-sitter-c-sharp) | [MIT](vendor/licenses/csharp-LICENSE.txt) |
| Go | [tree-sitter-go](https://github.com/tree-sitter/tree-sitter-go) | [MIT](vendor/licenses/go-LICENSE.txt) |
| Java | [tree-sitter-java](https://github.com/tree-sitter/tree-sitter-java) | [MIT](vendor/licenses/java-LICENSE.txt) |
| JavaScript | [tree-sitter-javascript](https://github.com/tree-sitter/tree-sitter-javascript) | [MIT](vendor/licenses/javascript-LICENSE.txt) |
| Python | [tree-sitter-python](https://github.com/tree-sitter/tree-sitter-python) | [MIT](vendor/licenses/python-LICENSE.txt) |
| Rust | [tree-sitter-rust](https://github.com/tree-sitter/tree-sitter-rust) | [MIT](vendor/licenses/rust-LICENSE.txt) |
| TypeScript/TSX | [tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript) | [MIT](vendor/licenses/typescript-LICENSE.txt) |

The runtime parser grammars are supplied by the pinned `tree-sitter-language-pack` dependency, not copied into this skill. The query credits are provenance for query text; see each dependency's own package license for its binaries.

## Optional inference (downloaded separately)

The scripts use the pinned Apache-2.0 [Transformers.js](https://github.com/huggingface/transformers.js) package. Node.js, that runtime, ONNX model weights and sqlite-vec are not included in the standalone bundle. Explicit indexing can download the following models into a separate cache; no model weights are redistributed here.

| Model | Immutable revision | Provenance |
| --- | --- | --- |
| `Xenova/all-MiniLM-L6-v2` | `751bff37182d3f1213fa05d7196b954e230abad9` | [Converted model](https://huggingface.co/Xenova/all-MiniLM-L6-v2), Apache-2.0 model card. |
| `Xenova/ms-marco-MiniLM-L-6-v2` | `a09144355adeed5f58c8ed011d209bf8ee5a1fec` | [Converted model](https://huggingface.co/Xenova/ms-marco-MiniLM-L-6-v2) identifies the original [Apache-2.0 cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2). The converted card has no separate license declaration; upstream provenance is the basis for this optional use. |
