"""Tier-0 and optional syntax chunking; all spans cite original whole lines."""
from __future__ import annotations
import ast
from dataclasses import replace
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import PurePosixPath
import re
from .decode import secret_spans
from repo_files import split_source_lines
from .units import Definition, UnitDraft

MAX_HEADER = 400
_PARSERS = {}


def nonwhite(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def windows(lines, start, end, target):
    first = start
    size = 0
    for number in range(start, end + 1):
        weight = nonwhite(lines[number - 1])
        if number > first and size + weight > target:
            yield first, number - 1
            first, size = number, 0
        size += weight
    if first <= end:
        yield first, end


def python_definitions(text: str) -> list[Definition]:
    lines = split_source_lines(text)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return []
    result = []
    stack = [(tree, ())]
    while stack:
        node, scope = stack.pop()
        child_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            body_start = node.body[0].lineno if node.body else node.lineno + 1
            signature = "\n".join(lines[node.lineno - 1:max(node.lineno, body_start - 1)])[:1000]
            doc = ast.get_docstring(node, clean=False) or ""
            result.append(Definition(start, node.end_lineno, node.name, ".".join((*scope, node.name)), signature, scope, doc[:600]))
            child_scope = (*scope, node.name)
        stack.extend((child, child_scope) for child in ast.iter_child_nodes(node))
    return sorted(result, key=lambda d:(d.start, -d.end))


_DECL = re.compile(r"^\s*(?:(?:export|default|public|private|protected|static|final|abstract|async|override|virtual|inline|suspend|open|sealed|partial|unsafe|friend|declare)\s+)*(?:(?:class|interface|enum|struct|trait|record|module|namespace|def|function|fn|sub|filter|procedure|package|program)\s+([\w.$:-]+)|(?:[\w<>\[\],.?*:&]+\s+)+([\w$]+)\s*\(|(?:const|let|var|val)\s+([\w$]+)\s*=.*(?:=>|function)|([\w.]+)\s*(?:<-|=)\s*function\s*\(|([\w-]+)\s*\(\)\s*\{)", re.I)
_SQL = re.compile(r"^\s*(?:create\s+(?:or\s+(?:replace|alter)\s+)?|alter\s+)?(?:procedure|function|trigger|view|package(?:\s+body)?)\s+([\w.\[\]]+)", re.I)
_COBOL = re.compile(r"^.{0,7}\s*([\w-]+)(?:\s+(?:DIVISION|SECTION))?\.\s*$", re.I)


def generic_definitions(text: str, language: str) -> list[Definition]:
    lines = split_source_lines(text)
    found = []
    # Remove comments and quoted literals before counting braces, retaining lines.
    cleaned = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', lambda m:"\n" * m[0].count("\n"), text)
    clean_lines = cleaned.split("\n")
    depths, depth = [], 0
    for line in clean_lines:
        depths.append(depth)
        depth += line.count("{") - line.count("}")
    brace_ends, brace_stack = {}, []
    for line_number, clean in enumerate(clean_lines):
        for char in clean:
            if char == "{":
                brace_stack.append(line_number)
            elif char == "}" and brace_stack:
                opening = brace_stack.pop()
                brace_ends[opening] = max(brace_ends.get(opening,0),line_number+1)
    for i, line in enumerate(lines):
        if len(line)>2000:
            continue  # Indivisible long lines are still indexed by windows.
        match = (_SQL.match(line) if language == "sql" else _COBOL.match(line) if language == "cobol" else _DECL.match(line))
        if not match:
            # JavaScript/TypeScript methods lack a return type in many classes.
            match = re.match(r"^\s+(?:(?:public|private|async|static|get|set)\s+)*([\w$]+)\s*\([^;]*\)\s*(?::[^=]+)?\s*\{", line)
        if not match:
            continue
        name = next((g for g in match.groups() if g), "")
        if name.lower() in {"if", "for", "while", "switch", "catch", "return", "else", "throw", "new", "try", "synchronized"}:
            continue
        signature_lines = [line.strip()]
        j = i
        while j + 1 < min(len(lines), i + 12) and not any(c in signature_lines[-1] for c in "{;:"):
            j += 1
            signature_lines.append(lines[j].strip())
        end = len(lines)
        if "{" in "\n".join(clean_lines[i:j + 1]):
            opening = next((n for n in range(i,j+1) if "{" in clean_lines[n]),i)
            end = brace_ends.get(opening,len(lines))
        elif language in {"vb", "pascal", "ruby"}:
            for k in range(i + 1, len(lines)):
                if re.match(r"^\s*(?:end\s*(?:sub|function|class|property)?|end;)\s*$", lines[k], re.I):
                    end = k + 1
                    break
        elif language == "python":
            indent = len(line) - len(line.lstrip())
            for k in range(i + 1, len(lines)):
                if lines[k].strip() and len(lines[k]) - len(lines[k].lstrip()) <= indent:
                    end = k
                    break
        scope = tuple(d.name for d in found if d.start < i + 1 <= d.end and re.search(r"\b(class|interface|struct|module|package)\b", d.signature, re.I))
        leading = []
        s = i - 1
        while s >= 0 and len(leading) < 64 and lines[s].strip().startswith(("//", "#", "*", "/*", "@", "'", "--")):
            leading.insert(0, lines[s].strip())
            s -= 1
        found.append(Definition(i + 1, max(i + 1, end), name, ".".join((*scope, name)), "\n".join(signature_lines)[:1000], scope, "\n".join(leading)[:600]))
    # Declarations without braces end at the next sibling declaration.
    return found


def parser_tier(preference="auto") -> str:
    if preference == "0":
        return "0"
    from importlib.metadata import version,PackageNotFoundError
    try:
        if version("tree-sitter") != "0.25.2" or version("tree-sitter-language-pack") != "0.13.0":
            return "0"
        import tree_sitter_language_pack
        return "1"
    except (ImportError,OSError,PackageNotFoundError):
        return "0"


def syntax_definitions(text: str, language: str, target=1500):
    if parser_tier("1") != "1":
        return None,(),"pinned-grammar-runtime-unavailable"
    try:
        from tree_sitter_language_pack import get_parser
        if language not in _PARSERS:
            _PARSERS[language] = get_parser({"c_sharp":"csharp","bash":"bash"}.get(language,language))
        tree = _PARSERS[language].parse(text.encode("utf-8"))
        result, cuts, error_lines = [], set(), set()
        source_lines = split_source_lines(text)
        prefix = [0]
        for line in source_lines:
            prefix.append(prefix[-1]+nonwhite(line))
        pending = [tree.root_node]
        while pending:
            current = pending.pop()
            start = current.start_point.row+1
            end = min(len(source_lines),current.end_point.row+(1 if current.end_point.column else 0))
            if start>end:
                continue
            if prefix[end]-prefix[start-1]>target and current.children:
                pending.extend(reversed(current.children))
            else:
                cuts.update((start,end+1))
        stack = [(tree.root_node, ())]
        lines = split_source_lines(text)
        while stack:
            node, scope = stack.pop()
            start = node.start_point.row + 1
            end = node.end_point.row + (1 if node.end_point.column else 0)
            end = max(start, min(len(lines), end))
            if node.type == "ERROR":
                error_lines.update(range(start, end + 1))
            name_node = node.child_by_field_name("name")
            definition = re.search(r"(?:function|method|constructor|class|interface|struct|enum|trait|module|procedure|package).*(?:definition|declaration|item)$", node.type)
            child_scope = scope
            if definition and name_node:
                name = name_node.text.decode("utf-8")
                body = node.child_by_field_name("body")
                body_line = body.start_point.row + 1 if body else start
                signature = "\n".join(lines[start - 1:max(start, body_line)])[:1000]
                leading = []
                for line in reversed(lines[max(0, start - 64):start - 1]):
                    if line.strip().startswith(("//", "#", "/*", "*", "@")):
                        leading.insert(0, line.strip())
                    else:
                        break
                result.append(Definition(start, end, name, ".".join((*scope, name)), signature, scope, "\n".join(leading)))
                child_scope = (*scope, name)
            stack.extend((child, child_scope) for child in reversed(node.named_children))
        if len(error_lines) > max(1, len(lines)) * .2:
            return None, (), "parse-error-over-20-percent"
        return result, cuts, None
    except (ImportError, OSError, LookupError, ValueError, TypeError, RuntimeError, RecursionError):
        return None, (), "grammar-unavailable-or-failed"


def code_units(text: str, path: str, language: str, target=1500, tier="0", kind="code-block"):
    lines = split_source_lines(text)
    if not lines:
        return [], None
    definitions = [] if kind == "config" or language == "text" else python_definitions(text) if language == "python" else generic_definitions(text, language)
    fallback, syntax_cuts = None, ()
    if tier == "1":
        parsed, syntax_cuts, fallback = syntax_definitions(text, language,target)
        if parsed:
            # Stdlib AST supplies Python docstrings, missing from generic nodes.
            if language != "python":
                definitions = parsed
    definitions.sort(key=lambda d:(d.start, -d.end, d.name))
    boundaries = {1, len(lines) + 1}
    for d in definitions:
        boundaries.update((d.start, min(len(lines) + 1, d.end + 1)))
    boundaries = sorted(boundaries)
    pieces = []
    for first, after in zip(boundaries, boundaries[1:]):
        last = after - 1
        enclosing = [d for d in definitions if d.start <= first <= d.end]
        inner = enclosing[-1] if enclosing else None
        header = "\n".join((path[:100],inner.qualified[:80],inner.signature[:100],inner.description[:160])) if inner else path[:MAX_HEADER]
        # Include original top-level config key/element in every part.
        if kind == "config":
            header += lines[first - 1].strip()
        if tier == "1" and syntax_cuts:
            cuts = sorted({first,*(n for n in syntax_cuts if first<n<=last),last+1})
            segments = []
            group_first,group_last = first,first-1
            total = 0
            for a,b in zip(cuts,cuts[1:]):
                size = sum(nonwhite(line) for line in lines[a-1:b-1])
                if group_last>=group_first and total+size>target:
                    segments.extend(windows(lines,group_first,group_last,target))
                    group_first,total = a,0
                group_last,total = b-1,total+size
            if group_last>=group_first:
                segments.extend(windows(lines,group_first,group_last,target))
        else:
            segments = list(windows(lines,first,last,target))
        for part, (start, end) in enumerate(segments, 1):
            body = "\n".join(lines[start - 1:end])
            if not body.strip():
                continue
            own = tuple(d for d in definitions if start <= d.start <= end)
            pieces.append(UnitDraft(start, end, body, "code-definition" if inner else kind, inner.qualified if inner else path, header[:MAX_HEADER].strip(), (inner.description[:200] if inner else ""), language, own, header_spans=((max(1,inner.start-len(inner.description.split("\n"))),min(len(lines),inner.start+len(inner.description.split("\n")))),) if inner else (), oversized=nonwhite(body) > target, part=part, parts=len(segments)))
    # Fitting definitions are kept whole, including their nested definitions.
    # Rebuild the partition choosing the innermost useful whole definition.
    prefix = [0]
    for line in lines:
        prefix.append(prefix[-1]+nonwhite(line))
    fitting = {d.start:d for d in definitions if prefix[min(len(lines),d.end)]-prefix[d.start-1]<=target and not any(child.start>d.start and child.end<=d.end for child in definitions)}
    merged = []
    i = 0
    while i < len(pieces):
        piece = pieces[i]
        declaration = fitting.get(piece.start)
        if declaration:
            end = declaration.end
            children = []
            while i < len(pieces) and pieces[i].start <= end:
                children.extend(pieces[i].definitions)
                i += 1
            body = "\n".join(lines[piece.start - 1:end])
            merged.append(replace(piece, end=end, text=body, definitions=tuple(children), part=1, parts=1))
        else:
            merged.append(piece)
            i += 1
    parents = []
    parent_by_span = []
    for definition in definitions:
        if prefix[min(len(lines),definition.end)]-prefix[definition.start-1]>target:
            header = f"{path}\n{definition.qualified}\n{definition.signature}\n{definition.description}"[:MAX_HEADER]
            parent_by_span.append((definition.start,definition.end,len(parents)))
            parents.append(UnitDraft(definition.start,definition.end,None,"code-definition",definition.qualified,header,definition.description[:200],language,definitions=(definition,),header_spans=((max(1,definition.start-len(definition.description.split("\n"))),min(len(lines),definition.start+len(definition.description.split("\n")))),),searchable=False))
    if parents:
        children = []
        for unit in merged:
            enclosing = [p for p in parent_by_span if p[0]<=unit.start and p[1]>=unit.end]
            parent = min(enclosing,key=lambda p:p[1]-p[0])[2] if enclosing else None
            children.append(replace(unit,parent=parent))
        return parents+children,fallback
    return merged, fallback


class SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif tag in {"p", "div", "br", "pre", "h1", "h2", "h3", "h4", "li"}:
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        else:
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def docs_units(text: str, path: str, fmt: str, target=1500):
    if fmt == "html":
        parser = SafeHTML()
        parser.feed(text)
        body = "".join(parser.parts).strip()
        # Raw HTML source mapping is deliberately a file envelope, never a
        # claim that entity-decoded text matches raw source lines.
        count = max(1, len(split_source_lines(text)))
        return [UnitDraft(1, count, body, "doc-section", path, path, language="html", transformed=True)] if body else []
    lines = split_source_lines(text)
    headings = []
    fence = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r"^(`{3,}|~{3,})", stripped)
        if match:
            if fence is None:
                fence = match[1][0]
            elif match[1][0] == fence:
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^(#{1,6}|={1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            headings.append((i + 1, len(heading[1]), heading[2]))
        elif i + 1 < len(lines) and stripped and re.fullmatch(r"([=~^`:#*+\-])\1{2,}", lines[i + 1].strip()):
            chars = "=~-^\"`:+*#"
            level = chars.find(lines[i + 1].strip()[0]) + 1
            headings.append((i + 1, max(1, level), stripped))
    boundaries = sorted({1, *(h[0] for h in headings), len(lines) + 1})
    stack = []
    result = []
    for start, after in zip(boundaries, boundaries[1:]):
        end = after - 1
        heading = next((h for h in headings if h[0] == start), None)
        if heading:
            while stack and stack[-1][0] >= heading[1]:
                stack.pop()
            stack.append((heading[1], heading[2]))
        breadcrumb = tuple(h[1] for h in stack) or (PurePosixPath(path).stem,)
        header = (path + "\n" + " > ".join(breadcrumb))[:MAX_HEADER]
        section = "\n".join(lines[start - 1:end])
        segments = [(start, end)] if nonwhite(section) <= target else list(windows(lines, start, end, target))
        # A4: keep explanation and code together. Oversized sections split on
        # whole lines; nearby preceding prose is retained as description.
        for part, (first, last) in enumerate(segments, 1):
            body = "\n".join(lines[first - 1:last])
            if not body.strip():
                continue
            prose = "\n".join(l for l in lines[max(start - 1, first - 4):first - 1] if l.strip() and not l.strip().startswith(("```", "~~~")))[:300] if first > start else ""
            result.append(UnitDraft(first, last, body, "doc-section", " > ".join(breadcrumb), header, prose, fmt, breadcrumb=breadcrumb, oversized=nonwhite(body) > target, part=part, parts=len(segments)))
    return result


def notebook_units(text, path, target, tier):
    try:
        notebook = json.loads(text)
        cells = notebook["cells"]
        if not isinstance(cells, list):
            raise ValueError()
        language = notebook.get("metadata", {}).get("language_info", {}).get("name", "python")
        result = []
        for index, cell in enumerate(cells):
            source = cell.get("source", "")
            source = "".join(source) if isinstance(source, list) else source
            if not isinstance(source, str):
                raise ValueError()
            if source.strip():
                # Cell strings may span one JSON physical line. Use raw-file
                # envelope and label transformed, preserving cell-local text.
                result.append(UnitDraft(1, max(1, len(split_source_lines(text))), source, "notebook-cell", f"{path} cell {index}", f"{path}\ncell {index}", language=language if cell.get("cell_type") == "code" else "markdown", cell_index=index, transformed=True, oversized=nonwhite(source) > target))
        return result, None
    except (ValueError, KeyError, TypeError, AttributeError):
        units, _ = code_units(text, path, "json", target, "0", "fallback")
        return units, "malformed-notebook"


def chunk_file(text, path, language, fmt, target=1500, tier="0", scan=True):
    if fmt in {"markdown", "rst", "asciidoc", "html"}:
        units, fallback = docs_units(text, path, fmt, target), None
    elif fmt == "notebook":
        units, fallback = notebook_units(text, path, target, tier)
    else:
        units, fallback = code_units(text, path, language, target, tier, "config" if fmt == "config" else "fallback" if language == "text" else "code-block")
    spans = secret_spans(text) if scan else []
    safe = []
    for unit in units:
        affected = any((a <= unit.end and b >= unit.start) or any(a<=he and b>=hs for hs,he in unit.header_spans) for a, b in spans)
        derived = (unit.text or "") + unit.header + unit.description
        if scan and (affected or secret_spans(derived)):
            unit = replace(unit, text=None, title="Redacted source content", header=path, description="Redacted source content", definitions=(), breadcrumb=(), header_spans=(), redacted=True)
        safe.append(unit)
    return safe, fallback
