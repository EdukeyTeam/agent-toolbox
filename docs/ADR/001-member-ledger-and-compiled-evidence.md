# ADR: Member ledger and compiled evidence for very large legacy files

**Date:** 2026-10-14
**Status:** Proposed. Accepted when the pull request that adds this file is merged.
**PRD:** None. This ADR belongs to the `legacy-codebase-workflows` skill: [skill entrypoint](../../skills/legacy-codebase-workflows/SKILL.md), [large files reference](../../skills/legacy-codebase-workflows/references/large-files.md), [compiled and runtime evidence reference](../../skills/legacy-codebase-workflows/references/compiled-and-runtime-evidence.md), [member ledger script](../../skills/legacy-codebase-workflows/scripts/member_ledger.py).

---

## 1. Context

The skill navigates a legacy repository with a ranked symbol map, scoped source packs and optional local retrieval. Those tools answer "where is it" and "what is related". They do not help with two problems that dominate work on very old Java code:

- **A single source file of 5,000 lines or more.** An agent asked to refactor it reads part of it, changes part of it and reports success. Nothing mechanical shows which members were handled, which were skipped and which were silently altered. A reviewer who wants certainty has to reread the whole file.
- **Facts that the source cannot settle.** The build no longer imports into a modern IDE, a third-party JAR has no source, the deployed artifact may differ from the checkout, and a syntax-only map cannot say whether a method is static or who really calls it.

[REA](https://github.com/morluto/rea) (Reverse Engineer Anything) became widely used while this was being considered, so it was examined as a possible addition. The review used commit `242e2b0001095524382183b771aa444310900942` of 2026-10-13, package `rea-agents` 6.4.0, MIT licensed.

## 2. What REA is, and what it is not

REA is an MCP server and CLI that puts one evidence contract in front of many reverse-engineering tools. It drives Hopper, Ghidra and IDA for native binaries, JADX and Apktool for Android packages, Rizin, Cutter, GNU objdump, GDB with pwndbg, LLDB, pwntools and Frida for lower-level and runtime work, Binwalk and Unblob for firmware, WABT for WebAssembly, TShark and sigrok for recordings, mitmproxy, HAR and Fiddler archives for network captures, and Playwright for browser observation. It has its own static analysis for JavaScript and Electron applications and for .NET assemblies.

Three facts decide how far it applies here:

- **Its own skill excludes this use.** The bundled instructions say to use normal repository tools for ordinary analysis of a complete source repository and not to run REA for it.
- **It has no route for JVM class files or JARs.** The JADX integration is the Android package path. A desktop or server Java application is not one of its targets.
- **Its analysis engines are not source tools.** Hopper, Ghidra and IDA disassemble and decompile native code. They matter to a Java codebase only where it ships native libraries without source, for example JNI libraries.

REA is therefore not a replacement for the map, pack and retrieval tools, and adding it as a dependency would add a large, fast-moving surface for a narrow benefit. What transfers is the way it works, not the tool.

## 3. Decisions

### D1. Do not make REA a dependency or a default step

The skill mentions REA only as an optional tool for the cases it actually covers: native libraries without source, recorded HTTP traffic of an old web application, and comparing two runs of a command-line program. Its documentation recommends `npx -y rea-agents@latest`; the skill tells readers to pin a version instead, because a setup that changes agent configuration should be reviewable and repeatable.

### D2. Summary first, then page by stable identity

REA returns a compact summary, keeps the complete record, and lets the agent request one section by identity instead of receiving everything or repeating the analysis. The same shape fits a giant source file. `member_ledger.py outline` prints one line per type and member with its line range and size, and `member_ledger.py slice` returns the exact lines of one member with the file hash and range. The agent never needs the whole file in context, and what it reads is addressable by a later citation.

REA's own measurements are a caution worth keeping: its summary views shrink tool replies substantially, but it does not claim model-token or latency savings from them, and one trial showed input tokens rising. The outline is adopted because it makes work addressable and checkable, not on a promise of lower cost.

### D3. A member ledger: every member is an obligation that must be accounted for

REA's reconstruction obligation ledger turns evidence into a list of claims. Each closes only when a verifier with comparable authority passes, and unknown, truncated or skipped never aggregates to pass. The refactoring equivalent is a list of the members a file had before the change.

`member_ledger.py baseline` records every member of the tracked files, plus the members that already exist in the directories where code may be moved. `member_ledger.py compare` then gives each recorded member exactly one status: `unchanged`, `moved`, `signature-changed`, `modified` or `missing`. It exits non-zero while a `missing` member has no recorded decision. With `--strict`, every member that is not unchanged or moved verbatim needs one.

This answers the review question directly. Members whose tokens are identical are proven to be the same text and need no rereading. The reviewer reads only the members reported as modified, signature-changed or missing.

### D4. Bounded negative results

REA treats missing coverage as unknown, not as absence. The ledger follows that rule. `missing` means "not found in the scope recorded at baseline", and the report always states that scope and every file that could not be scanned. A file that cannot be scanned fails the comparison, because a truncated or unbalanced file is exactly what an interrupted edit produces.

A member that already existed in the scope before the refactor is never accepted as the destination of a move. Without that rule a deleted field such as `private int count;` would be reported as moved to any unrelated class that happens to declare the same thing.

### D5. Compiled artifacts and runtime observation as evidence, through JDK tools

REA's central idea is to inspect what actually ships. For JVM code that needs no new tool: `javap` reads modifiers, signatures and bytecode call sites from class files, `jdeps` reports class and package dependencies and use of JDK-internal APIs, and `jdeprscan` reports deprecated API use. They work from compiled classes, so they do not need the project to import into an IDE. `jdb` gives an agent scripted breakpoints over JDWP where static evidence cannot answer a question. The skill documents these in a reference file and bundles nothing.

### D6. A dependency-free lexical scanner in Python, for Java only

The ledger needs every member with exact start and end lines. The bundled Tree-sitter Java query captures classes, interfaces and methods; it omits constructors, fields, initializers and enum constants, and the map keeps only what fits a budget. Extending the native mapper would also require a new binary release before anyone could use the feature.

The scanner is a Python standard-library script. It tokenizes Java (comments, string and character literals, text blocks), checks bracket balance for the whole file, and splits type bodies into members. It is not a parser: it does not resolve types, and it compares token sequences, so whitespace and comment changes are ignored while any change to code or literals is detected. Operators are tokenized by longest match, except that `>` is always a single token so that `List<List<String>>` and `List<List<String> >` compare equal.

Trade-off: Java only, and a lexical model that can misclassify unusual syntax. The scanner fails closed on anything it cannot balance, and its agreement with an independent parser on real code is recorded in section 5.

### D7. Legacy encodings are declared, never guessed

Old source is often in a single-byte encoding such as Windows-1250 or ISO-8859-2. The existing tools accept UTF-8 only. The ledger and the citation checker take an explicit `--encoding`; hashes are always computed over the original bytes. Nothing detects the encoding automatically, because a wrong guess between similar code pages decodes without error and produces wrong text.

## 4. Alternatives considered

| Alternative | Why not |
| --- | --- |
| Register REA's MCP server as part of the skill | Its own instructions exclude source-repository analysis, it has no JVM route, and its large tool catalog would be loaded into every session |
| Add member ranges and hashes to the native Rust mapper | Correct long-term home, but it needs grammar-query changes for constructors, fields and enum constants plus a new pinned release. Revisit if the ledger proves useful |
| `git diff --color-moved` | Useful for a human reading a diff, and the reference recommends it alongside the ledger. It gives no per-member accounting, no exit code and no rule for code that already existed elsewhere |
| A syntax-tree differencing tool such as GumTree | More precise edit scripts, at the cost of a JVM dependency and a build per language. The ledger's question is narrower: is every member accounted for |
| Type-resolved comparison through JDT LS or SCIP-Java | Needs real compiler inputs, which is the thing most often missing in these repositories. Already listed in the scale reference as a separately evaluated step |

## 5. Verification

Measured on 2026-10-14 with Python 3.14.4 on Linux.

**Automated tests.** `tests/test_legacy_members.py` covers the scanner, outline, slices, encodings, the ledger statuses, decisions, scope rules and the command line. The existing legacy Python suite passes with it.

**Agreement with an independent parser.** Every type and member the scanner reports (owner, kind, name, first line, last line) was compared with a Tree-sitter parse (`tree-sitter` 0.25.2, `tree-sitter-language-pack` 0.13.0) of the same file. A file counts as agreeing only when both sets are identical.

| Corpus | Files compared | Lines | Types | Members | Files of 5,000 lines or more | Files agreeing | Scan time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenJDK `java.lang`, `java.util`, `java.io`, `java.awt`, `javax.swing` at `f9533916e031` | 1,989 | 1,003,166 | 4,222 | 59,009 | 13 | 1,989 | 3.7 s |
| Apache Tomcat at `6029ea6073d2` | 2,937 | 726,078 | 4,881 | 53,506 | 4 | 2,937 | 3.5 s |

Eight further files (five and three) were excluded because Tree-sitter reported a parse error for them; the scanner accepted all eight, and its output for them is unchecked. The first run found one real defect, a method named like its class being reported as a constructor, which is fixed and covered by a test. The comparison harness is not part of the repository.

**Trial on a real file.** `javax/swing/JTable.java` has 9,850 lines and 386,066 bytes. Its outline is 554 lines and 30,848 bytes, about 8 percent of the file. A baseline recorded 551 members. After a scripted change that moved two methods to a new class, moved a third while changing `private` to `static`, deleted a fourth and edited one line inside a 132-line method, the comparison reported 546 unchanged, 2 moved, 1 signature-changed, 1 modified and 1 missing, and exited 1 until the deletion had a recorded decision. Cutting the file off after 5,000 bytes made the comparison fail with an unterminated-comment error instead of an outline.

**Not verified.** The `javap`, `jdeps`, `jdeprscan` and `jdb` commands in the reference file were checked against the Java SE 21 tool documentation, not executed: no JDK was available in the environment where this was written. The scanner has not been run on source in a legacy single-byte encoding beyond the unit test, or on a private production codebase.

## 6. Limits

- Token identity proves that a member's text is the same. It does not prove the same behavior in a new location: imports, enclosing fields, inheritance and overload resolution can differ. Characterization tests remain necessary.
- A method of two thousand lines is one member. The ledger narrows review to that method; it does not look inside it.
- Imports and package declarations are not tracked.
- The scanner does not process Unicode escapes outside literals, and it accepts LF and CRLF line endings only.
- `jdb` and decompiler output can contain production data. The reference tells readers to use a test environment and to check what may be sent to a model provider.
