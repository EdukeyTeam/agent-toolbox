"""AST declaration headers and bounded rendering for offline repository maps.

Tree-sitter is imported only during extraction; inventory-only stays stdlib.
Declaration spans are transient, never trusted from or added to tag caches.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass

from repo_files import contains_control_characters

HEADER = "# Repository map\n\n"
EMPTY_MESSAGE = "No supported definitions found in selected files. See inventory.json for descriptors, unsupported files and skips.\n"
DECLARATION_LINE_LIMIT = 80
DECLARATION_CHARACTER_LIMIT = 8000
CONTEXT_TYPES = {
    "class", "class_declaration", "abstract_class_declaration", "class_definition",
    "class_specifier", "struct_specifier", "interface_declaration", "enum_declaration",
    "namespace_definition", "namespace_declaration", "module", "module_definition",
    "impl_item", "trait_item", "mod_item", "struct_item", "enum_item", "union_item",
    "function_definition", "function_declaration", "function_item", "method_declaration",
    "method_definition", "type_spec",
}
BODY_TYPES = {
    "block", "statement_block", "compound_statement", "class_body", "interface_body",
    "enum_body", "declaration_list", "field_declaration_list", "enum_variant_list",
    "object_type", "struct_type", "interface_type",
}


class BudgetExceeded(ValueError):
    def __init__(self, required_estimated_tokens, budget):
        self.required_estimated_tokens = required_estimated_tokens
        super().__init__(f"all-definitions requires {required_estimated_tokens} estimated tokens; budget is {budget}. Increase --budget to at least {required_estimated_tokens}, or choose a narrower subtree.")


def sanitize(line):
    return "".join(" " if character != "\t" and contains_control_characters(character) else character for character in line)


def _body(node):
    if node.type in {"struct_type", "interface_type"}:
        opener = next((token for token in node.children if token.type == "{"), None)
        if opener is not None:
            return opener
    body = node.child_by_field_name("body")
    if body is not None:
        if body.type in {"struct_type", "interface_type"}:
            return _body(body) or body
        return body
    for child in node.named_children:
        if child.type in BODY_TYPES:
            if child.type in {"struct_type", "interface_type"}:
                return _body(child) or child
            return child
    if node.type in {"export_statement", "lexical_declaration", "variable_declaration"}:
        for child in node.named_children:
            if child.type in {"function_declaration", "class_declaration", "lexical_declaration", "variable_declaration", "variable_declarator"}:
                body = _body(child)
                if body is not None:
                    return body
    # Wrappers around arrow functions and Go named struct/interface types.
    for field in ("value", "right", "type"):
        child = node.child_by_field_name(field)
        if child is not None:
            if child.type in BODY_TYPES:
                if child.type in {"struct_type", "interface_type"}:
                    return _body(child) or child
                return child
            if child.type in {"arrow_function", "function_expression", "generator_function", "struct_type", "interface_type"}:
                return _body(child)
    return None



def _owner(name, declarations):
    node = name.parent
    while node is not None and node.id not in declarations:
        node = node.parent
    if node is None:
        node = name.parent
    if node is None:
        return name
    if node.type == "function_declarator":
        parent = node.parent
        while parent is not None and parent.type not in {"function_definition", "declaration", "field_declaration"}:
            parent = parent.parent
        if parent is not None:
            node = parent
    # Keep variable_declarators distinct: their lexical declaration can contain
    # several functions, and its first function body is not their common header.
    return node


class _SourceColumns(list):
    """Sparse UTF-8 byte/character index; conversions decode at most 1 KiB."""
    def __init__(self, data):
        super().__init__([0, *(index + 1 for index, character in enumerate(data) if character == 10)])
        self.data = data
        self.byte_starts = [0]
        self.character_starts = [0]
        previous = 0
        characters = 0
        for byte in range(1024, len(data), 1024):
            while byte > previous and data[byte] & 0xC0 == 0x80:
                byte -= 1
            characters += len(data[previous:byte].decode("utf-8"))
            self.byte_starts.append(byte)
            self.character_starts.append(characters)
            previous = byte

    def _characters_before(self, byte):
        checkpoint = bisect.bisect_right(self.byte_starts, byte) - 1
        return self.character_starts[checkpoint] + len(self.data[self.byte_starts[checkpoint]:byte].decode("utf-8"))

    def column(self, row, byte):
        return self._characters_before(byte) - self._characters_before(self[row - 1])


def _range_span(start, end, data, line_starts, name_line, name=None):
    while end > start and data[end - 1:end] in (b" ", b"\t", b"\r", b"\n"):
        end -= 1
    start_line = bisect.bisect_right(line_starts, start)
    end_line = bisect.bisect_right(line_starts, max(start, end - 1))
    span = {
        "line": name_line, "start_line": start_line, "end_line": end_line,
        "start_column": line_starts.column(start_line, start),
        "end_column": line_starts.column(end_line, end),
    }
    if name is not None:
        name_start_line = name.start_point.row + 1
        name_end_line = name.end_point.row + 1
        if name_start_line != name_end_line:
            raise ValueError("a definition name spans multiple source lines")
        span["identity"] = (
            name_start_line,
            line_starts.column(name_start_line, name.start_byte),
            line_starts.column(name_start_line, name.end_byte),
        )
    return span


def _span(node, data, line_starts, name_line, name=None):
    start = node.start_byte
    if node.parent is not None and node.parent.type == "decorated_definition":
        start = node.parent.start_byte
    previous = node.prev_named_sibling
    while previous is not None and previous.type == "attribute_item":
        start = previous.start_byte
        previous = previous.prev_named_sibling
    body = _body(node)
    end = node.end_byte
    if body is not None:
        end = body.start_byte + 1 if data[body.start_byte:body.start_byte + 1] == b"{" else body.start_byte
    return _range_span(start, end, data, line_starts, name_line, name)


def _prefixes(owner, data, line_starts):
    """Separate const/export prefixes contain no sibling function bodies."""
    result = []
    child = owner
    parent = owner.parent
    while parent is not None and parent.type in {"lexical_declaration", "variable_declaration", "export_statement", "type_declaration", "var_declaration", "const_declaration"}:
        first = next((node for node in parent.named_children if node.type != "comment"), child)
        if first.start_byte > parent.start_byte:
            result.append(_range_span(parent.start_byte, first.start_byte, data, line_starts, parent.start_point.row + 1))
        child, parent = parent, parent.parent
    return result


def extract_declarations(text, parser, query, path, tags, *, strict_syntax=False):
    """Attach current AST ranges; raw captures also validate complete-mode claims."""
    from tree_sitter import QueryCursor

    data = text.encode("utf-8")
    tree = parser.parse(data)
    if strict_syntax and tree.root_node.has_error:
        raise ValueError("all-definitions requires syntax-clean selected source; parser reported syntax errors")
    captures = QueryCursor(query).captures(tree.root_node)
    declarations = {node.id: node for capture, nodes in captures.items() if capture.startswith("definition.") for node in nodes}
    captured_names = sorted(
        (node for capture, nodes in captures.items() if capture.startswith("name.definition.") for node in nodes),
        key=lambda node: (node.start_byte, node.end_byte),
    )
    names = {}
    positions = defaultdict(set)
    for node in captured_names:
        name = node.text.decode("utf-8", "replace")
        key = (node.start_point.row + 1, name)
        if strict_syntax and (not name or len(name) > 512):
            raise ValueError(f"definition name at {path}:L{key[0]} exceeds the 512-character name limit; complete mapping cannot silently filter it")
        positions[key].add((node.start_byte, node.end_byte))
        if strict_syntax and len(positions[key]) > 1:
            raise ValueError(f"ambiguous definition identity at {path}:L{key[0]} for {name!r}: distinct capture positions share the legacy line/name key")
        names.setdefault(key, node)
    if strict_syntax:
        expected = set(names)
        actual = {(tag["line"], tag["name"]) for tag in tags if tag["kind"] == "def"}
        if expected != actual:
            raise ValueError(f"current AST definitions differ from the cached definition inventory in {path}; complete mapping cannot omit captured definitions")

    line_starts = _SourceColumns(data)
    span_cache = {}

    def span(node, name_line, name=None):
        key = (node.id, name.id if name is not None else None)
        if key not in span_cache:
            span_cache[key] = _span(node, data, line_starts, name_line, name)
        return span_cache[key]

    result = []
    for tag in tags:
        if tag["kind"] != "def":
            result.append(tag)
            continue
        name = names.get((tag["line"], tag["name"]))
        if name is None:
            raise ValueError(f"cached definition has no current AST declaration: {path}:L{tag['line']}")
        owner = _owner(name, declarations)
        spans = [span(owner, tag["line"], name), *_prefixes(owner, data, line_starts)]
        parent = owner.parent
        while parent is not None:
            if parent.parent is not None and parent.type in CONTEXT_TYPES:
                parent_name = parent.child_by_field_name("name")
                parent_line = parent_name.start_point.row + 1 if parent_name is not None else parent.start_point.row + 1
                spans.append(span(parent, parent_line, parent_name))
            parent = parent.parent
        result.append({**tag, "declaration_spans": spans})
    return result


def _whitespace_range(source, start, end):
    # Avoid copying or sanitizing an unrelated minified body just to discover
    # that the first character of a gap is not whitespace.
    return start < end and all(
        source[index].isspace() or (source[index] != "\t" and contains_control_characters(source[index]))
        for index in range(start, end)
    )


@dataclass(frozen=True)
class LineFragments:
    # Retain only selected payloads, with coordinates in the original line.
    # Original source is consulted transiently when merging shared ranges.
    value: str
    intervals: tuple[tuple[int, int], ...]
    payloads: tuple[tuple[int, int], ...]

    @classmethod
    def _from_source(cls, source, intervals):
        chunks = []
        payloads = []
        length = 0
        previous = None
        for start, end in intervals:
            if previous is None and start:
                separator = " … "
            elif previous is not None:
                separator = sanitize(source[previous:start]) if _whitespace_range(source, previous, start) else " … "
            else:
                separator = ""
            chunks.append(separator)
            length += len(separator)
            payload = sanitize(source[start:end])
            payloads.append((length, length + len(payload)))
            chunks.append(payload)
            length += len(payload)
            previous = end
        return cls("".join(chunks), tuple(intervals), tuple(payloads))

    @classmethod
    def excerpt(cls, source, start, end):
        # Sanitization preserves character coordinates. Do not sanitize/copy
        # the unrelated physical-line body merely to excerpt a short header.
        if start and _whitespace_range(source, 0, start):
            start = 0
        return cls._from_source(source, ((start, end),))

    def merge(self, other, source):
        ranges = []
        for start, end in sorted((*self.intervals, *other.intervals)):
            whitespace = ranges and _whitespace_range(source, ranges[-1][1], start)
            if ranges and (start <= ranges[-1][1] or whitespace):
                ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
            else:
                ranges.append((start, end))
        return LineFragments._from_source(source, ranges)

    def characters(self):
        return sum(end - start for start, end in self.intervals)

    def bounded(self, available):
        chunks = []
        ranges = []
        payloads = []
        previous_end = None
        length = 0
        for (start, end), (first, last) in zip(self.intervals, self.payloads):
            taken = min(available, end - start)
            if taken or start == end:
                separator = self.value[previous_end:first] if previous_end is not None else " … " if start else ""
                chunks.append(separator)
                length += len(separator)
                payload = self.value[first:first + taken]
                payloads.append((length, length + len(payload)))
                chunks.append(payload)
                length += len(payload)
                ranges.append((start, start + taken))
                previous_end = last
            available -= taken
        return LineFragments("".join(chunks), tuple(ranges), tuple(payloads))

    def contains(self, start, end):
        return any(first <= start and last >= end for first, last in self.intervals)

    def rendered_characters(self):
        return len(self.value)

    def text(self):
        return self.value


def _clip_span(span, source_lines, path):
    start, end = span["start_line"], span["end_line"]
    if start < 1 or end > len(source_lines) or end < start:
        raise ValueError(f"source span vanished while rendering: {path}")
    name_line = span["line"]
    retained = list(range(start, min(end + 1, start + DECLARATION_LINE_LIMIT)))
    line_clipped = end - start + 1 > DECLARATION_LINE_LIMIT
    if start <= name_line <= end and name_line not in retained:
        retained[-1] = name_line
        retained.sort()
    prepared = {}
    for number in retained:
        first = span["start_column"] if number == start else 0
        last = span["end_column"] if number == end else len(source_lines[number - 1])
        prepared[number] = LineFragments.excerpt(source_lines[number - 1], first, last)
    snippets = {}
    characters_left = DECLARATION_CHARACTER_LIMIT
    character_clipped = False
    reserve_name = min(prepared[name_line].characters(), DECLARATION_CHARACTER_LIMIT) if name_line in prepared else 0
    for number, fragment in prepared.items():
        reserve = reserve_name if number < name_line else 0
        available = max(0, characters_left - reserve)
        if number == name_line:
            available = characters_left
        if fragment.characters() > available:
            character_clipped = True
        bounded = fragment.bounded(available)
        if bounded.intervals:
            snippets[number] = bounded
        characters_left -= bounded.characters()
    if "identity" in span:
        line, first, last = span["identity"]
        if line not in snippets or not snippets[line].contains(first, last):
            raise ValueError(f"definition identifier at {path}:L{line} exceeds the declaration character limit; a hidden name cannot count as rendered")
    reason = "line and character limits" if line_clipped and character_clipped else "line limit" if line_clipped else "character limit" if character_clipped else None
    record = {"path": path, "line": name_line, "start_line": start, "end_line": end, "reason": reason} if reason else None
    return snippets, record


def _record_key(record):
    return (record["path"], record["line"], record["start_line"], record["end_line"], record["reason"])


def _file_text(path, lines, clipping):
    result = [f"## {path}\n\n```text\n"]
    previous = None
    for number, snippet in sorted(lines.items()):
        if previous is not None and number > previous + 1:
            result.append("  ...\n")
        result.append(f"L{number}: {snippet.text()}\n")
        previous = number
    for record in sorted(clipping.values(), key=_record_key):
        result.append(f"  ... [declaration clipped: L{record['start_line']}-L{record['end_line']}; {record['reason']}]\n")
    result.append("```\n\n")
    return "".join(result)


def _file_characters(path, lines, clipping):
    """Count the exact Markdown without creating declaration/output strings."""
    characters = len(f"## {path}\n\n```text\n") + len("```\n\n")
    previous = None
    for number, snippet in sorted(lines.items()):
        if previous is not None and number > previous + 1:
            characters += len("  ...\n")
        characters += len(f"L{number}: ") + snippet.rendered_characters() + 1
        previous = number
    for record in clipping.values():
        characters += len(f"  ... [declaration clipped: L{record['start_line']}-L{record['end_line']}; {record['reason']}]\n")
    return characters


def _render_complete_grouped(ranked, source_lines, budget):
    # One file's ranges at a time; sanitized source is held only by these
    # transient fragments and the independently byte-bounded source cache.
    # Retained output never exceeds the configured character budget, even when
    # an exact required-token diagnostic must count every remaining definition.
    ranked = list(ranked)
    by_file = defaultdict(list)
    for tag in ranked:
        by_file[tag["path"]].append(tag)
    chunks = [HEADER]
    retained_records = []
    total_characters = len(HEADER)
    limit = budget * 4
    overflowing = False
    for path, tags in sorted(by_file.items()):
        original_lines = source_lines(path)
        selected = {}
        clipping = {}
        for tag in tags:
            for span in tag["declaration_spans"]:
                snippets, record = _clip_span(span, original_lines, path)
                for number, snippet in snippets.items():
                    selected[number] = selected[number].merge(snippet, original_lines[number - 1]) if number in selected else snippet
                if record:
                    clipping[_record_key(record)] = record
        total_characters += _file_characters(path, selected, clipping)
        if total_characters > limit:
            overflowing = True
            chunks.clear()
            retained_records.clear()
        elif not overflowing:
            chunks.append(_file_text(path, selected, clipping))
            retained_records.extend(clipping.values())
        # Do not keep a completed file's source ranges while counting the next.
        selected.clear()
        clipping.clear()
    if not ranked and total_characters + len(EMPTY_MESSAGE) <= limit:
        chunks.append(EMPTY_MESSAGE)
        total_characters += len(EMPTY_MESSAGE)
    required = math.ceil(total_characters / 4)
    if required > budget:
        raise BudgetExceeded(required, budget)
    return "".join(chunks), ranked, sorted(retained_records, key=_record_key)


def render_grouped(ranked, source_lines, budget, *, all_definitions=False):
    if all_definitions:
        return _render_complete_grouped(ranked, source_lines, budget)
    files = {}
    clipping = {}
    costs = {}
    included = []
    total_characters = len(HEADER)
    for tag in ranked:
        path = tag["path"]
        original_lines = source_lines(path)
        additions = {}
        records = {}
        for span in tag["declaration_spans"]:
            snippets, record = _clip_span(span, original_lines, path)
            for line, snippet in snippets.items():
                additions[line] = additions[line].merge(snippet, original_lines[line - 1]) if line in additions else snippet
            if record:
                records[_record_key(record)] = record
        candidate = dict(files.get(path, {}))
        for line, snippet in additions.items():
            candidate[line] = candidate[line].merge(snippet, original_lines[line - 1]) if line in candidate else snippet
        candidate_records = {**clipping.get(path, {}), **records}
        candidate_cost = len(_file_text(path, candidate, candidate_records))
        new_total = total_characters - costs.get(path, 0) + candidate_cost
        if new_total <= budget * 4:
            files[path] = candidate
            clipping[path] = candidate_records
            costs[path] = candidate_cost
            total_characters = new_total
            included.append(tag)
    text = HEADER + "".join(_file_text(path, files[path], clipping[path]) for path in sorted(files))
    if not included and len(text) + len(EMPTY_MESSAGE) <= budget * 4:
        text += EMPTY_MESSAGE
    records = sorted((record for per_file in clipping.values() for record in per_file.values()), key=_record_key)
    return text, included, records


def render_lines(ranked, source_lines, budget, *, all_definitions=False):
    chunks = [HEADER]
    total_characters = len(HEADER)
    overflowing = False
    remaining = budget * 4 - len(HEADER)
    included = []
    seen = set()
    for tag in ranked:
        key = (tag["path"], tag["line"])
        if all_definitions:
            identity = tag["declaration_spans"][0]["identity"]
            line, first, last = identity
            original = source_lines(tag["path"])
            cleaned = sanitize(original[line - 1])
            leading = len(cleaned) - len(cleaned.lstrip())
            if first < leading or last - leading > 240:
                raise ValueError(f"all-definitions cannot show the full identifier at {tag['path']}:L{line} within legacy lines' 240-character limit; use --format grouped")
        if key in seen:
            included.append(tag)
            continue
        lines = source_lines(tag["path"])
        if tag["line"] > len(lines):
            raise ValueError(f"source line vanished while rendering: {tag['path']}")
        snippet = sanitize(lines[tag["line"] - 1]).strip()
        line = f"{tag['path']}:L{tag['line']}: {snippet[:240]}\n"
        if all_definitions or len(line) <= remaining:
            total_characters += len(line)
            if all_definitions and total_characters > budget * 4:
                overflowing = True
                chunks.clear()
            elif not overflowing:
                chunks.append(line)
            remaining -= len(line)
            included.append(tag)
            seen.add(key)
    if not included and len(EMPTY_MESSAGE) <= remaining:
        chunks.append(EMPTY_MESSAGE)
        total_characters += len(EMPTY_MESSAGE)
    required = math.ceil(total_characters / 4)
    if all_definitions and required > budget:
        raise BudgetExceeded(required, budget)
    text = "".join(chunks)
    return text, included, []


def rendering_metadata(map_format, clipping=()):
    return {
        "format": map_format, "declaration_line_limit": DECLARATION_LINE_LIMIT,
        "declaration_character_limit": DECLARATION_CHARACTER_LIMIT,
        "clipped_declarations": list(clipping),
    }
