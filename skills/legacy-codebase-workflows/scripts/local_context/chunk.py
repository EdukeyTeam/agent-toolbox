"""Tier-0 and optional syntax chunking; all spans cite original whole lines."""
from __future__ import annotations
import ast
from bisect import bisect_left, bisect_right
from dataclasses import replace
import heapq
from html import unescape
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
            leading = leading_comments(lines, start)
            docstring = ast.get_docstring(node, clean=False) or ""
            doc = "\n".join(filter(None, (leading, docstring)))
            doc_node = node.body[0] if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else None
            header_end = doc_node.end_lineno if doc_node else max(node.lineno, body_start - 1)
            result.append(Definition(start, node.end_lineno, node.name, ".".join((*scope, node.name)), signature, scope, doc[:600], start-len(leading.splitlines()), header_end))
            child_scope = (*scope, node.name)
        stack.extend((child, child_scope) for child in ast.iter_child_nodes(node))
    return sorted(result, key=lambda d:(d.start, -d.end))


def leading_comments(lines, start):
    leading = []
    for line in reversed(lines[max(0, start - 65):start - 1]):
        if not line.strip().startswith("#"):
            break
        leading.append(line.strip())
    return "\n".join(reversed(leading))


_DECL = re.compile(r"^\s*(?:(?:export|default|public|private|protected|static|final|abstract|async|override|virtual|inline|suspend|open|sealed|partial|unsafe|friend|declare)\s+)*(?:(?:class|interface|enum|struct|trait|record|module|namespace|def|function|fn|sub|filter|procedure|package|program)\s+([\w.$:-]+)|(?:[\w<>\[\],.?*:&]+\s+)+([\w$]+)\s*\(|(?:const|let|var|val)\s+([\w$]+)\s*=.*(?:=>|function)|([\w.]+)\s*(?:<-|=)\s*function\s*\(|([\w-]+)\s*\(\)\s*\{)", re.I)
_SQL = re.compile(r"^\s*(?:create\s+(?:or\s+(?:replace|alter)\s+)?|alter\s+)?(?:procedure|function|trigger|view|package(?:\s+body)?)\s+([\w.\[\]]+)", re.I)
_COBOL = re.compile(r"^.{0,7}\s*([\w-]+)(?:\s+(?:DIVISION|SECTION))?\.\s*$", re.I)


def callable_prefix(value):
    """Recognize a direct callable initializer, balancing its parameters."""
    def balanced(at, opening, closing):
        depth = 0
        for position in range(at, len(value)):
            char = value[position]
            if char == opening:
                depth += 1
            elif char == closing and not (closing == ">" and position and value[position - 1] == "="):
                depth -= 1
                if depth == 0:
                    return position + 1
        return None
    function = re.match(r"(?:async\s+)?(?:function\b(?:\s+[\w$]+)?|fun\b|func\s*(?=\())", value)
    position = function.end() if function else 0
    if not function:
        asynchronous = re.match(r"async\s+", value)
        position = asynchronous.end() if asynchronous else 0
    while position < len(value) and value[position].isspace():
        position += 1
    if not function and position < len(value) and value[position] == "<":
        position = balanced(position, "<", ">")
        if position is None:
            return None
        while position < len(value) and value[position].isspace():
            position += 1
    if position < len(value) and value[position] == "(":
        position = balanced(position, "(", ")")
        if position is None:
            return None
    elif not function:
        parameter = re.match(r"[\w$]+", value[position:])
        if not parameter:
            return None
        position += parameter.end()
    else:
        return None
    if function:
        return position, False
    while position < len(value) and value[position].isspace():
        position += 1
    if value[position:position + 1] == ":":
        # A return type can itself contain nested generics and function types.
        stack = []
        position += 1
        pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
        while position < len(value):
            if not stack and value.startswith("=>", position):
                return position + 2, True
            char = value[position]
            if not stack and char in ";=":
                return None
            if char in pairs:
                stack.append(pairs[char])
            elif stack and char == stack[-1] and not (char == ">" and value[position - 1] == "="):
                stack.pop()
            position += 1
        return None
    return (position + 2, True) if value.startswith("=>", position) else None


def expression_binding(lines, start, language):
    """Bounded declaration recognition, never arbitrary callback assignments."""
    if language not in {"javascript", "typescript", "tsx", "kotlin", "go", "rust"}:
        return None
    header = re.match(r"^\s*(?:(?:export|default|declare|public|private|protected|readonly|static|override|pub(?:\([^)]*\))?)\s+)*(?:(?:const|let|var|val|static)\s+(?:mut\s+)?([\w$]+)|([\w$]+)\s*(?=[?:=]))", lines[start])
    if not header:
        return None
    window = "\n".join(lines[start:start+12])
    # Do not mistake an arrow in a function type for the initializer's equals.
    assignment = re.search(r"(?<![=<>!])=(?![=>])", lines[start][header.end():])
    if not assignment and header.group(2):
        assignment = re.match(r"\s*:", lines[start][header.end():])
    if not assignment:
        return None
    value_start = header.end() + assignment.end()
    value = window[value_start:].lstrip()
    offset = len(window[value_start:]) - len(value) + value_start
    callable_value = callable_prefix(value)
    container = language in {"javascript", "typescript", "tsx"} and value.startswith("{") and bool(re.match(r"\s*export\s+", lines[start]))
    constant = language == "rust" and bool(re.match(r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+", lines[start]))
    if not callable_value and not container and not constant:
        return None
    after = offset + (callable_value[0] if callable_value else 0)
    body = window.find("{", after) if callable_value else offset if value.startswith("{") else -1
    if callable_value and callable_value[1] and not window[after:].lstrip().startswith("{"):
        body = -1  # An object in a returned expression is not the function body.
    header_end = start + window[:body if body >= 0 else after].count("\n")
    return header.group(1) or header.group(2), header_end, body >= 0, container


def generic_definitions(text: str, language: str) -> list[Definition]:
    lines = split_source_lines(text)
    found = []
    expression_starts = set()
    # Remove comments and quoted literals before counting braces, retaining lines.
    hash_comment = r"|\#[^\n]*" if language in {"powershell", "php", "bash", "ruby", "perl", "r", "python"} else ""
    literals = r'''/\*[\s\S]*?\*/|//[^\n]*|"(?:\\[^\n]|[^"\\\n])*"|'(?:\\[^\n]|[^'\\\n])*'|`(?:\\[^\n]|[^`\\\n])*`'''
    cleaned = re.sub(literals + hash_comment, lambda m: ("0" if m[0].startswith(('"', "'", "`")) else "") + "\n" * m[0].count("\n"), text)
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
    scopes = []
    for i, line in enumerate(lines):
        while scopes and scopes[-1].end < i + 1:
            scopes.pop()
        if len(line)>2000:
            continue  # Indivisible long lines are still indexed by windows.
        binding = expression_binding(clean_lines, i, language)
        if binding and not binding[2]:
            expression_starts.add(i + 1)
        match = (_SQL.match(line) if language == "sql" else _COBOL.match(line) if language == "cobol" else _DECL.match(line))
        if language in {"javascript", "typescript", "tsx"} and match and (match.group(2) or match.group(3)) and not binding:
            # Typed-return declarations belong to C/Java-like languages. In JS
            # they mislabel `await foo(...)` and `return foo(...)` as definitions.
            match = None
        if language in {"javascript", "typescript", "tsx"} and not match:
            match = re.match(r"^\s*(?:export\s+)?(?:declare\s+)?type\s+([\w$]+)\b", line)
        if not match:
            # JavaScript/TypeScript methods lack a return type in many classes.
            match = re.match(r"^\s+(?:(?:public|private|async|static|get|set)\s+)*([\w$]+)\s*\([^;]*\)\s*(?::[^=]+)?\s*\{", line)
        if not match and not binding:
            continue
        name = binding[0] if binding else next((g for g in match.groups() if g), "")
        if name.lower() in {"if", "for", "while", "switch", "catch", "return", "else", "throw", "new", "try", "synchronized"}:
            continue
        signature_lines = [line.strip()]
        j = i
        while j + 1 < min(len(lines), i + 12) and (j < binding[1] if binding else not any(c in signature_lines[-1] for c in "{;:")):
            j += 1
            signature_lines.append(lines[j].strip())
        end = len(lines)
        if (binding and binding[2]) or (not binding and "{" in "\n".join(clean_lines[i:j + 1])):
            opening = j if binding else next((n for n in range(i,j+1) if "{" in clean_lines[n]),i)
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
        elif any(";" in value for value in signature_lines) and (language != "sql" or re.search(r"\bview\b", signature_lines[0], re.I)):
            end = j + 1
        scope = tuple(d.name for d in scopes)
        leading = []
        s = i - 1
        while s >= 0 and len(leading) < 64 and lines[s].strip().startswith(("//", "#", "*", "/*", "@", "'", "--")):
            leading.insert(0, lines[s].strip())
            s -= 1
        found.append(Definition(i + 1, max(i + 1, end), name, ".".join((*scope, name)), "\n".join(signature_lines)[:1000], scope, "\n".join(leading)[:600], s + 2, j + 1))
        if (binding and binding[3]) or re.search(r"\b(class|interface|struct|module|package)\b", found[-1].signature, re.I):
            scopes.append(found[-1])
    # Uncertain braceless blocks end at the next declaration at their own or
    # lesser indentation, with an enclosing brace boundary as an upper bound.
    bounded = list(found)
    pending = []
    openings = iter(sorted(brace_ends.items()))
    following = next(openings, None)
    containing = []
    for index, definition in enumerate(found):
        while following is not None and following[0] < definition.start - 1:
            heapq.heappush(containing, following[1])
            following = next(openings, None)
        while containing and containing[0] < definition.start:
            heapq.heappop(containing)
        indent = len(lines[definition.start-1]) - len(lines[definition.start-1].lstrip())
        while pending and pending[-1][0] >= indent:
            _, previous = pending.pop()
            bounded[previous] = replace(bounded[previous], end=min(bounded[previous].end, definition.start-1))
        if definition.end == len(lines) and (definition.start in expression_starts or "{" not in definition.signature):
            boundary = containing[0] if containing else len(lines)
            bounded[index] = replace(definition, end=min(definition.end, boundary))
            pending.append((indent, index))
    return bounded


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
            value = node.child_by_field_name("value")
            if value is not None and value.type == "expression_list" and len(value.named_children) == 1:
                value = value.named_children[0]
            if language == "kotlin" and node.type == "property_declaration":
                value = next((c for c in node.named_children if c.type == "anonymous_function"), value)
                variable = next((c for c in node.named_children if c.type == "variable_declaration"), None)
                if variable is not None and variable.named_children:
                    name_node = variable.named_children[0]
            expression = node.type in {"variable_declarator", "public_field_definition", "field_definition", "property_declaration", "property_definition", "pair", "var_spec"} and value is not None and value.type in {"arrow_function", "function_expression", "function", "func_literal", "anonymous_function"}
            container = node.type == "variable_declarator" and value is not None and value.type == "object" and node.parent is not None and node.parent.parent is not None and node.parent.parent.type == "export_statement"
            definition = definition or expression or container or node.type in {"type_alias_declaration", "const_item", "static_item"}
            if node.type == "pair":
                name_node = node.child_by_field_name("key")
            child_scope = scope
            if definition and name_node:
                name = name_node.text.decode("utf-8")
                body = value.child_by_field_name("body") if expression else value if container else node.child_by_field_name("body")
                if body is None and expression and language == "kotlin":
                    body = next((c for c in node.named_children if c.type == "function_body"), None)
                body_line = body.start_point.row + 1 if body else start
                signature = "\n".join(lines[start - 1:max(start, body_line)])[:1000]
                leading = []
                for line in reversed(lines[max(0, start - 64):start - 1]):
                    if line.strip().startswith(("//", "#", "/*", "*", "@")):
                        leading.insert(0, line.strip())
                    else:
                        break
                result.append(Definition(start, end, name, ".".join((*scope, name)), signature, scope, "\n".join(leading), max(1,start-len(leading)), max(start,body_line)))
                child_scope = (*scope, name)
            stack.extend((child, child_scope) for child in reversed(node.named_children))
        if error_lines:
            # Generic recognition is restricted to contiguous ERROR spans; valid
            # syntax definitions remain authoritative everywhere else.
            spans = []
            for number in sorted(error_lines):
                if spans and number == spans[-1][1] + 1:
                    spans[-1] = (spans[-1][0], number)
                else:
                    spans.append((number, number))
            result = [d for d in result if not any(a <= d.start <= b for a,b in spans)]
            for a,b in spans:
                cuts.update((a,b+1))
                partial = "\n".join(lines[a-1:b])
                for d in generic_definitions(partial, language):
                    result.append(replace(d, start=d.start+a-1, end=min(b,d.end+a-1), header_start=(d.header_start or d.start)+a-1, header_end=(d.header_end or d.start)+a-1))
        return result, cuts, "error-span-fallback" if error_lines else None
    except (ImportError, OSError, LookupError, ValueError, TypeError, RuntimeError, RecursionError):
        return None, (), "grammar-unavailable-or-failed"


def fitting_definitions(definitions, prefix, target):
    """Keep an entire fitting outer definition, including nested helpers."""
    fitting = {}
    for definition in definitions:
        if prefix[definition.end] - prefix[definition.start - 1] <= target:
            fitting.setdefault(definition.start, definition)
    return fitting


def attach_parents(units, spans):
    active = []
    pending = iter(sorted(spans))
    following = next(pending, None)
    for unit in units:
        while following is not None and following[0] <= unit.start:
            first, last, index = following
            heapq.heappush(active, (last - first, index, last))
            following = next(pending, None)
        while active and active[0][2] < unit.end:
            heapq.heappop(active)
        yield replace(unit, parent=active[0][1] if active else None)


def config_contexts(lines):
    current, source_line = "", 1
    contexts = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r'^(?:\[[^]]+\]|["\w.-]+["\']?\s*[:=]|<(?![!?/])[\w:.-]+)', stripped):
            current, source_line = stripped, number
        contexts.append((current or lines[0].strip(), source_line))
    return contexts


def code_units(text: str, path: str, language: str, target=1500, tier="0", kind="code-block"):
    lines = split_source_lines(text)
    if not lines:
        return [], None
    definitions = [] if kind == "config" or language == "text" else python_definitions(text) if language == "python" else generic_definitions(text, language)
    fallback, syntax_cuts = None, ()
    if tier == "1" and language != "sql":
        parsed, syntax_cuts, fallback = syntax_definitions(text, language,target)
        if parsed is not None:
            # Prefer complete stdlib Python AST metadata when available, but
            # keep valid syntax nodes when an ERROR prevents ast.parse().
            if language != "python" or not definitions:
                definitions = parsed
    definitions.sort(key=lambda d:(d.start, -d.end, d.name))
    starts = [d.start for d in definitions]
    prefix = [0]
    for line in lines:
        prefix.append(prefix[-1] + nonwhite(line))
    syntax_cuts = sorted(syntax_cuts)
    contexts = config_contexts(lines) if kind == "config" else None
    boundaries = {1, len(lines) + 1}
    for d in definitions:
        boundaries.update((d.start, min(len(lines) + 1, d.end + 1)))
    boundaries = sorted(boundaries)
    pieces = []
    active, next_definition = [], 0
    for first, after in zip(boundaries, boundaries[1:]):
        last = after - 1
        while next_definition < len(definitions) and definitions[next_definition].start <= first:
            heapq.heappush(active, (-next_definition, definitions[next_definition].end))
            next_definition += 1
        while active and active[0][1] < first:
            heapq.heappop(active)
        inner = definitions[-active[0][0]] if active else None
        header = "\n".join((path[:100],inner.qualified[:80],inner.signature[:100],inner.description[:160])) if inner else path[:MAX_HEADER]
        # Include original top-level config key/element in every part.
        if tier == "1" and syntax_cuts:
            cuts = [first, *syntax_cuts[bisect_right(syntax_cuts, first):bisect_right(syntax_cuts, last)], last + 1]
            segments = []
            group_first,group_last = first,first-1
            total = 0
            for a,b in zip(cuts,cuts[1:]):
                size = prefix[b - 1] - prefix[a - 1]
                if group_last>=group_first and total+size>target:
                    segments.extend(windows(lines,group_first,group_last,target))
                    group_first,total = a,0
                group_last,total = b-1,total+size
            if group_last>=group_first:
                segments.extend(windows(lines,group_first,group_last,target))
        else:
            segments = list(windows(lines,first,last,target))
        for part, (start, end) in enumerate(segments, 1):
            header_spans = ((inner.header_start or inner.start, inner.header_end or inner.start),) if inner else ()
            if contexts:
                key_line, key_number = contexts[start - 1]
                header = path + "\n" + key_line
                header_spans = ((key_number, key_number),)
            body = "\n".join(lines[start - 1:end])
            if not body.strip():
                continue
            own = tuple(definitions[bisect_left(starts, start):bisect_right(starts, end)])
            pieces.append(UnitDraft(start, end, body, "code-definition" if inner else kind, inner.qualified if inner else path, header[:MAX_HEADER].strip(), (inner.description[:200] if inner else ""), language, own, header_spans=header_spans, oversized=nonwhite(body) > target, part=part, parts=len(segments)))
    # Fitting definitions are kept whole, including their nested definitions.
    # Rebuild the partition choosing the innermost useful whole definition.
    fitting = fitting_definitions(definitions, prefix, target)
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
            nested_header = "\n".join(d.qualified + "\n" + d.signature[:100] + "\n" + d.description[:160] for d in children if d != declaration)
            header = (piece.header + "\n" + nested_header).strip()[:MAX_HEADER]
            spans = tuple((d.header_start or d.start, d.header_end or d.start) for d in children)
            merged.append(replace(piece, end=end, text=body, header=header, header_spans=spans or piece.header_spans, definitions=tuple(children), part=1, parts=1))
        else:
            merged.append(piece)
            i += 1
    parents = []
    parent_by_span = []
    for definition in definitions:
        if prefix[min(len(lines),definition.end)]-prefix[definition.start-1]>target:
            header = f"{path}\n{definition.qualified}\n{definition.signature}\n{definition.description}"[:MAX_HEADER]
            parent_by_span.append((definition.start,definition.end,len(parents)))
            parents.append(UnitDraft(definition.start,definition.end,None,"code-definition",definition.qualified,header,definition.description[:200],language,definitions=(definition,),header_spans=((definition.header_start or definition.start,definition.header_end or definition.start),),searchable=False))
    if parents:
        children = list(attach_parents(merged, parent_by_span))
        return parents+children,fallback
    return merged, fallback


def transformed_spans(text, target=1500):
    """Bound escaped JSON body size, preferring paragraphs, lines, then words.

    Whitespace counts too. Even an indivisible physical line can be split:
    transformed units cite enclosing raw lines rather than exact body lines.
    """
    target = max(1, min(target, 1500))
    start = 0
    while start < len(text):
        end, size = start, 0
        while end < len(text):
            char = text[end]
            weight = 2 if char in '\\"\b\f\n\r\t' else 6 if ord(char) < 32 else 1
            if size + weight > target and end > start:
                break
            size += weight
            end += 1
        if end < len(text):
            for boundary in ('\n\n', '\n'):
                cut = text.rfind(boundary, start, end)
                if cut >= start:
                    end = cut + len(boundary)
                    break
            else:
                cut = next((i for i in range(end - 1, start, -1) if text[i].isspace()), None)
                if cut is not None:
                    end = cut + 1
        yield start, end
        start = end


class SafeHTML(HTMLParser):
    def __init__(self, source):
        # Separate entity callbacks preserve their raw source line even when
        # an entity decodes to a newline (&#10; is still one source line).
        super().__init__(convert_charrefs=False)
        self.source_lines = source.split('\n')
        self.parts = []
        self.mapping = []
        self.length = 0
        self.headings = []
        self.heading = None
        self.skip = 0

    def append(self, value):
        line = self.getpos()[0]
        for piece in value.splitlines(keepends=True):
            self.parts.append(piece)
            self.mapping.append((self.length, self.length + len(piece), line))
            self.length += len(piece)
            line += piece.count('\n')

    def finish_heading(self):
        if self.heading is not None:
            offset, level, first = self.heading
            title = ' '.join(''.join(self.parts[first:]).split())[:MAX_HEADER]
            self.headings.append((offset, level, title))
            self.heading = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif not self.skip:
            if re.fullmatch(r'h[1-6]', tag):
                self.finish_heading()
                self.heading = (self.length, int(tag[1]), len(self.parts))
            if tag in {"p", "div", "br", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
                self.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip:
            if re.fullmatch(r'h[1-6]', tag):
                self.finish_heading()
            self.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.append(data)

    def handle_entityref(self, name):
        if not self.skip:
            line, column = self.getpos()
            raw = '&' + name
            if self.source_lines[line - 1].startswith(raw + ';', column):
                raw += ';'
            value = unescape(raw)
            self.parts.append(value)
            self.mapping.append((self.length, self.length + len(value), line))
            self.length += len(value)

    def handle_charref(self, name):
        self.handle_entityref('#' + name)


def html_units(text, path, target):
    parser = SafeHTML(text)
    parser.feed(text)
    parser.close()
    parser.finish_heading()
    body = ''.join(parser.parts)
    headings = {offset: (level, title) for offset, level, title in parser.headings}
    boundaries = sorted({0, *headings, len(body)})
    starts = [first for first, _, _ in parser.mapping]
    stack, result = [], []
    for start, after in zip(boundaries, boundaries[1:]):
        if start in headings:
            level, title = headings[start]
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        breadcrumb = tuple(title for _, title in stack) or (PurePosixPath(path).stem,)
        title = ' > '.join(breadcrumb)[:MAX_HEADER]
        section = body[start:after]
        spans = [(a, b) for a, b in transformed_spans(section, target) if section[a:b].strip()]
        for part, (first, last) in enumerate(spans, 1):
            # Strip synthetic boundaries before finding the contributing raw
            # lines; never count decoded lines as original HTML lines.
            value = section[first:last]
            first += len(value) - len(value.lstrip())
            last -= len(value) - len(value.rstrip())
            a, b = start + first, start + last
            left = max(0, bisect_right(starts, a) - 1)
            right = bisect_left(starts, b)
            source = parser.mapping[left:right]
            result.append(UnitDraft(min(p[2] for p in source), max(p[2] for p in source),
                                    body[a:b], 'doc-section', title, (path + '\n' + title)[:MAX_HEADER],
                                    language='html', breadcrumb=breadcrumb, transformed=True,
                                    part=part, parts=len(spans)))
    return result


def docs_units(text: str, path: str, fmt: str, target=1500):
    if fmt == "html":
        return html_units(text, path, target)
    lines = split_source_lines(text)
    headings = []
    fence = None
    literal_indent = literal_pending = None
    asciidoc_block = None
    markdown_code = markdown_paragraph = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if fmt == "asciidoc":
            if asciidoc_block is not None:
                if line == asciidoc_block:
                    asciidoc_block = None
                continue
            if re.fullmatch(r"(-{4,}|\.{4,}|\+{4,})", line):
                asciidoc_block = line
                continue
        if fmt == "markdown":
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
            if not stripped:
                markdown_paragraph = False
                continue  # Blank lines continue an existing indented block.
            if markdown_code:
                if indent >= 4:
                    continue
                markdown_code = False
            if not fence and indent >= 4 and not markdown_paragraph:
                markdown_code = True
                continue
        if fmt == "rst":
            indent = len(line.expandtabs(8)) - len(line.expandtabs(8).lstrip())
            if not stripped:
                continue
            if literal_pending is not None:
                if indent > literal_pending:
                    literal_indent = indent
                literal_pending = None
            if literal_indent is not None:
                if indent >= literal_indent:
                    continue
                literal_indent = None
            if stripped.endswith("::") or re.match(r"^\.\.\s+[\w-]+::", stripped):
                literal_pending = indent
                continue
        match = re.match(r"^(`{3,}|~{3,})", stripped) if fmt != "markdown" or indent < 4 else None
        if match:
            if fence is None:
                fence = (match[1][0], len(match[1]))
            elif match[1][0] == fence[0] and len(match[1]) >= fence[1] and not stripped[match.end():].strip():
                fence = None
            markdown_paragraph = False
            continue
        if fence:
            continue
        heading = (re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if fmt == "markdown" else
                   re.match(r"^(={1,6})\s+(.+?)\s*#*\s*$", line) if fmt == "asciidoc" else None)
        if heading:
            headings.append((i + 1, len(heading[1]), heading[2]))
            markdown_paragraph = False
        elif i + 1 < len(lines) and stripped and (fmt != "asciidoc" or not re.fullmatch(r"(-{4,}|\.{4,}|\+{4,})", lines[i + 1])) and (fmt != "markdown" or len(lines[i + 1].expandtabs(4)) - len(lines[i + 1].expandtabs(4).lstrip()) < 4) and re.fullmatch(r"([=\-])\1{2,}" if fmt == "markdown" else r"([=~^`:#*+\-])\1{2,}", lines[i + 1].strip()) and not re.match(r"^(`{3,}|~{3,})", lines[i + 1].strip()):
            chars = "=~-^\"`:+*#"
            level = (1 if lines[i + 1].strip()[0] == "=" else 2) if fmt == "markdown" else chars.find(lines[i + 1].strip()[0]) + 1
            headings.append((i + 1, max(1, level), stripped))
            markdown_paragraph = False
        elif fmt == "markdown":
            markdown_paragraph = not bool(re.fullmatch(r" {0,3}(?:[-*_]\s*){3,}", line))
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


def json_member_span(text, start, name):
    """Locate a direct object's value without matching nested keys/strings."""
    decoder = json.JSONDecoder()
    position, found = start + 1, None
    while True:
        while text[position].isspace() or text[position] == ',':
            position += 1
        if text[position] == '}':
            return found
        key, position = decoder.raw_decode(text, position)
        while text[position].isspace() or text[position] == ':':
            position += 1
        first = position
        _, position = decoder.raw_decode(text, position)
        if key == name:
            found = (first, position)  # Match json.loads' last-key-wins rule.


def notebook_units(text, path, target, tier):
    try:
        notebook = json.loads(text)
        cells = notebook["cells"]
        if not isinstance(cells, list):
            raise ValueError()
        language = notebook.get("metadata", {}).get("language_info", {}).get("name", "python")
        cell_position = json_member_span(text, len(text) - len(text.lstrip()), 'cells')[0] + 1
        decoder = json.JSONDecoder()
        newlines = [i for i, char in enumerate(text) if char == '\n']
        result = []
        for index, cell in enumerate(cells):
            while text[cell_position].isspace() or text[cell_position] == ',':
                cell_position += 1
            cell_start = cell_position
            _, cell_position = decoder.raw_decode(text, cell_position)
            source = cell.get("source", "")
            source = "".join(source) if isinstance(source, list) else source
            if not isinstance(source, str):
                raise ValueError()
            if source.strip():
                raw_start, raw_end = json_member_span(text, cell_start, 'source')
                first, last = bisect_left(newlines, raw_start) + 1, bisect_left(newlines, raw_end - 1) + 1
                spans = [(a, b) for a, b in transformed_spans(source, target) if source[a:b].strip()]
                for part, (a, b) in enumerate(spans, 1):
                    # Escaped cell text does not share the JSON file's lines.
                    # Every part cites the enclosing source value, not outputs.
                    result.append(UnitDraft(first, last, source[a:b], "notebook-cell", f"{path} cell {index}", f"{path}\ncell {index}", language=language if cell.get("cell_type") == "code" else "markdown", breadcrumb=(f"cell {index}",), cell_index=index, transformed=True, part=part, parts=len(spans)))
        return result, None
    except (ValueError, KeyError, TypeError, AttributeError):
        units, _ = code_units(text, path, "json", target, "0", "fallback")
        return units, "malformed-notebook"


def chunk_file(text, path, language, fmt, target=1500, tier="0", scan=True):
    if fmt in {"markdown", "rst", "asciidoc", "html", "text"}:
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
