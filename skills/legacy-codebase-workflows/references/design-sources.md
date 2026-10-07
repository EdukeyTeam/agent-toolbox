# Workflow sources and design choices

This skill combines investigation with optional execution routes. It is authored here; install third-party skills from their authors rather than maintaining duplicate copies.

| Source | Useful idea | Choice here |
| --- | --- | --- |
| [Aider repository-map article](https://aider.chat/2023/10/22/repomap.html) | Parse definitions/references, rank relationships and select useful context within a budget. | Bundle an attributed adaptation with a standalone CLI, coverage metadata and original-source verification. |
| [Official Repomix explorer](https://github.com/yamadashy/repomix/blob/main/skills/repomix-explorer/SKILL.md) | Pack and search selected repository content; use direct search for known symbols. | Optional scoped packing; full bodies for behavior and compression for structure. Pin versions and measure reductions. |
| [Documenting legacy codebases](https://github.com/riekelt/technical-writer/blob/main/plugins/technical-writer/skills/documenting-legacy-codebases/SKILL.md) | Inventory actual behavior, entry points and wiring; distinguish evidence from historical intent. | Task-sized evidence cards, real framework callers and refreshable source provenance. No mandatory documentation tree. |
| [Legacy modernizer](https://github.com/jeffallan/claude-skills/blob/main/skills/legacy-modernizer/SKILL.md) | Characterize behavior and modernize incrementally with a working baseline. | An optional change route. No universal coverage percentage, traffic ramp or architectural replacement. |
| Original jFTP modernization exercise | Inventory/docs, behavior tests, minimum startup, incremental upgrades. | Preserve the progression when modernization is requested; handle startup blockers before claiming a tested baseline, and omit unrelated stages for investigation. |

The default path should reduce uncertainty rather than produce paperwork. Generated summaries and retrieval results need current-source checks; citations establish where evidence came from, while the coordinator verifies what it means. Config and reflection wiring need explicit investigation because syntax-only maps are incomplete.

Native parser bindings are available in Python, Rust and Node. Sharing queries requires compatible grammar/runtime versions and parity checks. Language choice alone does not improve map coverage, embedding relevance or reranking quality.
