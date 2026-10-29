# Very large source files

Read this for a Java source file that is too large to load whole, or for a refactor where someone must be able to show that nothing was skipped. A file of a few hundred lines needs none of it: read the file and review the diff.

`scripts/member_ledger.py` needs only the Python standard library. It supports Java source and no other language. Run it from the installed skill; it is not part of the pinned prebuilt mapper.

```bash
python /path/to/skill/scripts/member_ledger.py --help
```

It is a lexical scanner, not a compiler. It finds every type, field, constructor, method, initializer and enum constant with exact line ranges, and it refuses a file whose brackets, comments or string literals do not balance. It does not resolve types.

## Outline first, then read one member at a time

Do not load a file of several thousand lines to find out what is in it. Print its outline:

```bash
python /path/to/skill/scripts/member_ledger.py outline /path/to/repository src/app/Orders.java
```

The first lines give the path, line count, SHA-256 of the file bytes, the number of types and members by kind, and the largest members. Then each type is followed by one line per member: line range, line count, kind, identifier and modifiers. The modifiers answer questions such as "is this method static" from the source instead of from memory. Add `--json /path/to/artifacts/outline.json` to keep the complete outline, including the header and a token hash of every member.

Read a member by its identifier. A bare name works when it is unique in the file:

```bash
python /path/to/skill/scripts/member_ledger.py slice /path/to/repository src/app/Orders.java --member "tax(int)"
```

The output starts with the path, the line range, the file hash and the member id, followed by the numbered lines. That header is everything a citation card needs. `--with-doc` includes the comment block directly above the member. A member longer than 400 lines is cut and the last line names the `--lines` range that continues it; `--max-lines 0` prints everything. Use `--lines 120-180` for a range that is not a member.

Plan the work from the outline. Group members that belong together, choose the order, and fetch only the members a step needs. A method of two thousand lines is still one member: the outline shows that it dominates the file, and it has to be read in pages.

## Legacy encodings

Old source is often not UTF-8. The tool then stops and asks for an encoding; it never guesses one, because similar code pages decode without error and produce wrong text. Find the encoding in the build configuration: the `encoding` attribute of an Ant `javac` task, `project.build.sourceEncoding` in Maven, or `.settings/org.eclipse.core.resources.prefs` in an Eclipse project. Then pass it to every command:

```bash
python /path/to/skill/scripts/member_ledger.py outline /path/to/repository src/app/Faktura.java --encoding cp1250
```

Hashes are always computed over the original bytes. `check_citations.py` accepts the same `--encoding`, or an `"encoding"` field on a single card.

An editing tool that assumes UTF-8 can silently rewrite such a file and corrupt every non-ASCII string literal in it. Before editing, check how your tool writes the file. After editing, confirm that the file still decodes with the declared encoding and that the diff contains only the intended lines. The repository map and the retrieval index still accept UTF-8 only.

## Refactor with a ledger

The ledger turns "I refactored the file" into a list that can be checked. Every member the file had before the change must end up accounted for.

**1. Record a baseline before the first edit.** Track the file being refactored and name the directories where code may be moved:

```bash
python /path/to/skill/scripts/member_ledger.py baseline /path/to/repository --track src/app/Orders.java --scope src/app --output /path/to/artifacts/orders.baseline.json
```

`--track` and `--scope` can be repeated. The scope is scanned now so that code which already exists there is known. It holds at most 2,000 Java files by default (`--max-files`, up to 20,000); choose the destination packages, not the whole repository. Keep the baseline with the other artifacts, outside the scanned source.

**2. Work in small batches, and move before you change.** Move members verbatim in one commit and change them in a later one. A verbatim move is proven identical by its tokens and needs no rereading; a move mixed with edits has to be reviewed line by line.

**3. Compare after every batch.**

```bash
python /path/to/skill/scripts/member_ledger.py compare /path/to/repository /path/to/artifacts/orders.baseline.json
```

Each baseline member gets exactly one status:

| Status | Meaning | What to do |
| --- | --- | --- |
| `unchanged` | Same place, same tokens | Nothing |
| `moved` | The same tokens now exist at a new place in the scope | Nothing, unless the report says the origin is still present with different content; then read what was left behind |
| `signature-changed` | The body is identical but the header differs, for example `private` became `public static` | Read the header change; it can alter visibility, dispatch or thread safety |
| `modified` | Still there under the same identifier, with different tokens | Read this member in full |
| `missing` | Not found in the tracked files or the scope | Find it, restore it, or record a decision |

Whitespace and comment changes never change a status. Any change to code or to a string literal does. The report also lists `added` members and every file it could not scan.

Exit code 0 means every member is accounted for. Exit code 1 means a `missing` member has no decision, or a file in the tracked set or scope cannot be scanned. A truncated file or an unbalanced bracket therefore fails the comparison instead of passing quietly. Exit code 2 is a usage or input error.

**4. Record decisions for what was removed on purpose.**

```json
{"decisions": [{"member": "src/app/Orders.java::Orders#audit(String)", "disposition": "deleted", "reason": "No callers in the repository or in the deployment descriptors; confirmed with the module owner."}]}
```

Pass the file with `--decisions`. The disposition is `deleted`, `merged`, `replaced` or `intentional-change`, and the reason must say why, with the evidence. Copy the member key from the report. A decision that matches no baseline member is reported as unused.

**5. Use `--strict` when nothing was supposed to change.** For a pure restructuring, `--strict` also requires a decision for every `modified` and `signature-changed` member, so an unplanned edit cannot pass unnoticed.

## Reviewing someone else's refactor

The ledger also works after the fact. Export the base revision to a temporary directory outside the repository, for example with `git archive`, and record the baseline there. Paths are relative to the directory you pass, so that baseline compares directly against the working tree with the change:

```bash
python /path/to/skill/scripts/member_ledger.py compare /path/to/repository /path/to/artifacts/orders.baseline.json --strict --json /path/to/artifacts/orders.ledger.json
```

Review the `missing`, `modified`, `signature-changed` and `added` members. The `unchanged` and verbatim `moved` members are the part of the diff that does not need to be read. `git diff --color-moved=dimmed-zebra` shows the same moves visually and complements the ledger; it does not produce an accounting or an exit code.

## What the ledger does not prove

- **Behavior.** Identical tokens in a new class can behave differently: an unqualified name may now resolve to another field, an import may select another class, an overload may bind differently, and a method that became static no longer dispatches virtually. Compile, and run characterization tests for the affected behavior as described in [changes and modernization](changes.md).
- **Absence.** `missing` means "not found in the tracked files and the recorded scope". Code moved outside the scope is reported as missing; record a new baseline from the base revision with the right scope.
- **Anything outside members.** Package and import statements are not tracked. Anonymous and local classes are part of the member that contains them.
- **Unusual source.** Unicode escapes outside literals are not interpreted, and only LF and CRLF line endings are supported.

Member identifiers are `Owner#name(parameter types)` for methods and constructors, `Owner#field:name` for fields, `Owner#constant:NAME` for enum constants, `Owner#<static-init>` and `Owner#<init>` for initializers, and `Owner#<type>` for a type's own header. A statement that declares several fields is one member, named after the first.
