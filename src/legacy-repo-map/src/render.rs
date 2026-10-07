//! Grouped declaration excerpts from existing Tree-sitter nodes.
//! Header spans stop at a body opener; enclosing headers supply context.

use std::collections::{BTreeMap, BTreeSet};
use std::ops::Bound::{Excluded, Unbounded};
use std::rc::Rc;
use tree_sitter::Node;

pub const DECLARATION_LINE_LIMIT: usize = 80;
pub const DECLARATION_CHARACTER_LIMIT: usize = 8000;
const HEADER: &str = "# Repository map\n\n";

#[derive(Debug)]
struct LineContent {
    source: String,
    offsets: Vec<usize>,
}
impl LineContent {
    fn new(source: &str) -> Self {
        let source = sanitize(source);
        let mut offsets: Vec<usize> = source.char_indices().map(|(index, _)| index).collect();
        offsets.push(source.len());
        Self { source, offsets }
    }
    fn slice(&self, start: usize, end: usize) -> &str {
        &self.source[self.offsets[start]..self.offsets[end]]
    }
    fn whitespace(&self, start: usize, end: usize) -> bool {
        start < end && self.slice(start, end).chars().all(char::is_whitespace)
    }
}
#[derive(Clone, Debug)]
pub struct SourceLine {
    pub text: String,
    source: Rc<LineContent>,
    ranges: Vec<(usize, usize)>,
}
impl SourceLine {
    fn new(source: Rc<LineContent>, ranges: Vec<(usize, usize)>) -> Self {
        let mut text = String::new();
        let mut previous = None;
        for (start, end) in &ranges {
            if let Some(previous) = previous {
                if source.whitespace(previous, *start) {
                    text.push_str(source.slice(previous, *start));
                } else {
                    text.push_str(" … ");
                }
            } else if *start > 0 {
                text.push_str(" … ");
            }
            text.push_str(source.slice(*start, *end));
            previous = Some(*end);
        }
        Self { text, source, ranges }
    }
    fn excerpt(source: Rc<LineContent>, mut start: usize, end: usize) -> Self {
        if source.whitespace(0, start) {
            start = 0;
        }
        Self::new(source, vec![(start, end)])
    }
    fn source_characters(&self) -> usize {
        self.ranges.iter().map(|(start, end)| end - start).sum()
    }
    fn merge(&self, other: &Self) -> Self {
        debug_assert_eq!(self.source.source, other.source.source);
        let mut inputs = self.ranges.clone();
        inputs.extend(&other.ranges);
        inputs.sort_unstable();
        let mut ranges: Vec<(usize, usize)> = Vec::new();
        for (start, end) in inputs {
            if let Some(last) = ranges.last_mut() {
                if start <= last.1 || self.source.whitespace(last.1, start) {
                    last.1 = last.1.max(end);
                    continue;
                }
            }
            ranges.push((start, end));
        }
        Self::new(self.source.clone(), ranges)
    }
    fn bounded(&self, mut available: usize) -> Self {
        let mut ranges = Vec::new();
        for (start, end) in &self.ranges {
            let taken = available.min(end - start);
            if taken > 0 || start == end {
                ranges.push((*start, start + taken));
            }
            available -= taken;
        }
        Self::new(self.source.clone(), ranges)
    }
    fn contains(&self, start: usize, end: usize) -> bool {
        self.ranges.iter().any(|(first, last)| *first <= start && *last >= end)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct Clipping {
    pub line: usize,
    pub start_line: usize,
    pub end_line: usize,
    pub reason: String,
}
impl Clipping {
    fn marker(&self) -> String {
        format!(
            "  ... [declaration clipped: L{}-L{}; {}]\n",
            self.start_line, self.end_line, self.reason
        )
    }
}

#[derive(Default, Clone, Debug)]
pub struct Declaration {
    pub lines: BTreeMap<usize, SourceLine>,
    pub clipped: BTreeSet<Clipping>,
}

pub struct SourceText<'a> {
    text: &'a str,
    line_starts: Vec<usize>,
    source_lines: Vec<Rc<LineContent>>,
}
impl<'a> SourceText<'a> {
    pub fn new(text: &'a str) -> Self {
        let mut line_starts = vec![0];
        line_starts.extend(text.match_indices('\n').map(|(index, _)| index + 1));
        let source_lines = text
            .split('\n')
            .map(|line| Rc::new(LineContent::new(line.strip_suffix('\r').unwrap_or(line))))
            .collect();
        Self {
            text,
            line_starts,
            source_lines,
        }
    }

    fn header(&self, node: Node<'_>, anchor: usize) -> Declaration {
        let owner = extend_declaration(node);
        let mut start = owner.start_byte();
        // Rust attributes are declaration-list siblings.
        let mut previous = owner.prev_named_sibling();
        while let Some(sibling) = previous {
            if sibling.kind() != "attribute_item" {
                break;
            }
            start = sibling.start_byte();
            previous = sibling.prev_named_sibling();
        }
        self.range_header(start, header_end(owner, self.text).max(start), anchor)
    }

    fn range_header(&self, start: usize, mut end: usize, anchor: usize) -> Declaration {
        while end > start && self.text.as_bytes()[end - 1].is_ascii_whitespace() {
            end -= 1;
        }
        let start_line = self.line_starts.partition_point(|offset| *offset <= start);
        let end_line = self
            .line_starts
            .partition_point(|offset| *offset <= end.saturating_sub(1).max(start));
        let mut lines = Vec::new();
        for line in start_line..=end_line {
            let offset = self.line_starts[line - 1];
            let mut physical_end = self
                .line_starts
                .get(line)
                .map(|next| next - 1)
                .unwrap_or(self.text.len());
            if physical_end > offset && self.text.as_bytes()[physical_end - 1] == b'\r' {
                physical_end -= 1;
            }
            let limit = physical_end.min(end);
            let first = if line == start_line { start } else { offset };
            if first > limit {
                continue;
            }
            let start_column = self.text[offset..first].chars().count();
            let end_column = self.text[offset..limit].chars().count();
            lines.push((
                line,
                SourceLine::excerpt(self.source_lines[line - 1].clone(), start_column, end_column),
            ));
        }
        let line_clipped = lines.len() > DECLARATION_LINE_LIMIT;
        if line_clipped {
            let anchor_line = lines.iter().find(|(line, _)| *line == anchor).cloned();
            lines.truncate(DECLARATION_LINE_LIMIT);
            if anchor > lines.last().map(|(line, _)| *line).unwrap_or(0) {
                if let Some(anchor_line) = anchor_line {
                    lines.pop();
                    lines.push(anchor_line);
                }
            }
        }
        // Reserve the identifier's line so long decorators do not hide it.
        let mut reserved = 0;
        let mut result = Declaration::default();
        let mut character_clipped = false;
        if let Some((line, source)) = lines.iter().find(|(line, _)| *line == anchor) {
            let (bounded, clipped) = bound_line(source, DECLARATION_CHARACTER_LIMIT);
            reserved = bounded.source_characters();
            character_clipped |= clipped;
            result.lines.insert(*line, bounded);
        }
        for (line, source) in lines {
            if result.lines.contains_key(&line) {
                continue;
            }
            let available = DECLARATION_CHARACTER_LIMIT.saturating_sub(reserved);
            if available == 0 {
                character_clipped = true;
                continue;
            }
            let (bounded, clipped) = bound_line(&source, available);
            reserved += bounded.source_characters();
            character_clipped |= clipped;
            result.lines.insert(line, bounded);
        }
        if line_clipped || character_clipped {
            let reason = match (line_clipped, character_clipped) {
                (true, true) => "line and character limits",
                (true, false) => "line limit",
                _ => "character limit",
            };
            result.clipped.insert(Clipping {
                line: anchor,
                start_line,
                end_line,
                reason: reason.to_string(),
            });
        }
        result
    }

    pub fn legacy_identifier_visible(&self, name: Node<'_>) -> bool {
        let row = name.start_position().row;
        let offset = self.line_starts[row];
        let start = self.text[offset..name.start_byte()].chars().count();
        let end = self.text[offset..name.end_byte()].chars().count();
        let leading = self.source_lines[row]
            .source
            .chars()
            .take_while(|c| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(c))
            .count();
        start >= leading && end.saturating_sub(leading) <= crate::policy::MAX_SNIPPET_CHARS
    }

    fn check_identifier(&self, declaration: &Declaration, name: Node<'_>) -> Result<(), String> {
        let row = name.start_position().row;
        let offset = self.line_starts[row];
        let start = self.text[offset..name.start_byte()].chars().count();
        let end = self.text[offset..name.end_byte()].chars().count();
        if !declaration
            .lines
            .get(&(row + 1))
            .is_some_and(|line| line.contains(start, end))
        {
            return Err(format!(
                "definition identifier at L{} exceeds the {}-character declaration limit; cannot include a hidden name",
                row + 1,
                DECLARATION_CHARACTER_LIMIT
            ));
        }
        Ok(())
    }

    pub fn declaration(&self, name: Node<'_>, owner: Node<'_>) -> Result<Declaration, String> {
        let mut result = self.header(owner, name.start_position().row + 1);
        self.check_identifier(&result, name)?;
        let mut parent = owner.parent();
        while let Some(node) = parent {
            if !matches!(
                node.kind(),
                "lexical_declaration"
                    | "variable_declaration"
                    | "export_statement"
                    | "type_declaration"
                    | "var_declaration"
                    | "const_declaration"
            ) {
                break;
            }
            let mut cursor = node.walk();
            let first = node.named_children(&mut cursor).find(|child| child.kind() != "comment");
            if let Some(first) = first {
                if first.start_byte() > node.start_byte() {
                    let prefix =
                        self.range_header(node.start_byte(), first.start_byte(), node.start_position().row + 1);
                    merge(&mut result, prefix);
                }
            }
            parent = node.parent();
        }
        let mut current = owner.parent();
        while let Some(node) = current {
            if node.parent().is_some() && is_context(node.kind()) {
                let context_name = node.child_by_field_name("name");
                let anchor = context_name
                    .map(|name| name.start_position().row + 1)
                    .unwrap_or(node.start_position().row + 1);
                let context = self.header(node, anchor);
                if let Some(context_name) = context_name {
                    self.check_identifier(&context, context_name)?;
                }
                merge(&mut result, context);
            }
            current = node.parent();
        }
        Ok(result)
    }
}

fn sanitize(text: &str) -> String {
    text.chars()
        .map(|c| {
            if (c.is_control() && c != '\t') || matches!(c, '\u{2028}' | '\u{2029}') {
                ' '
            } else {
                c
            }
        })
        .collect()
}
fn bound_line(source: &SourceLine, available: usize) -> (SourceLine, bool) {
    if source.source_characters() <= available {
        return (source.clone(), false);
    }
    (source.bounded(available), true)
}
fn merge(target: &mut Declaration, other: Declaration) {
    for (line, source) in other.lines {
        let existing = target.lines.entry(line).or_insert_with(|| source.clone());
        *existing = existing.merge(&source);
    }
    target.clipped.extend(other.clipped);
}
fn is_context(kind: &str) -> bool {
    matches!(
        kind,
        "class_definition"
            | "class"
            | "class_declaration"
            | "abstract_class_declaration"
            | "interface_declaration"
            | "enum_declaration"
            | "struct_specifier"
            | "union_specifier"
            | "class_specifier"
            | "namespace_definition"
            | "namespace_declaration"
            | "module"
            | "impl_item"
            | "trait_item"
            | "mod_item"
            | "function_definition"
            | "function_declaration"
            | "function_item"
            | "function_expression"
            | "struct_item"
            | "enum_item"
            | "union_item"
            | "type_spec"
            | "method_definition"
            | "method_declaration"
    )
}
fn extend_declaration(mut node: Node<'_>) -> Node<'_> {
    if node.kind() == "function_declarator" {
        let mut current = node.parent();
        while let Some(parent) = current {
            if matches!(
                parent.kind(),
                "function_definition" | "declaration" | "field_declaration"
            ) {
                node = parent;
                break;
            }
            if is_context(parent.kind()) || matches!(parent.kind(), "translation_unit" | "compound_statement") {
                break;
            }
            current = parent.parent();
        }
    }
    while let Some(parent) = node.parent() {
        if parent.kind() == "decorated_definition" {
            node = parent;
        } else {
            break;
        }
    }
    node
}
fn body(node: Node<'_>) -> Option<Node<'_>> {
    if matches!(node.kind(), "struct_type" | "interface_type") {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if child.kind() == "{" {
                return Some(child);
            }
            if child.kind() == "field_declaration_list" {
                let mut fields_cursor = child.walk();
                let opener = child.children(&mut fields_cursor).find(|token| token.kind() == "{");
                if let Some(opener) = opener {
                    return Some(opener);
                }
            }
        }
    }
    if let Some(body_node) = node.child_by_field_name("body") {
        if matches!(body_node.kind(), "struct_type" | "interface_type") {
            return body(body_node).or(Some(body_node));
        }
        return Some(body_node);
    }
    let mut cursor = node.walk();
    for child in node.named_children(&mut cursor) {
        if matches!(
            child.kind(),
            "block"
                | "statement_block"
                | "compound_statement"
                | "class_body"
                | "interface_body"
                | "enum_body"
                | "declaration_list"
                | "field_declaration_list"
                | "enum_variant_list"
                | "object_type"
                | "struct_type"
                | "interface_type"
        ) {
            if matches!(child.kind(), "struct_type" | "interface_type") {
                return body(child).or(Some(child));
            }
            return Some(child);
        }
    }
    for field in ["value", "right", "type"] {
        if let Some(child) = node.child_by_field_name(field) {
            if let Some(body) = body(child) {
                return Some(body);
            }
        }
    }
    if matches!(
        node.kind(),
        "decorated_definition"
            | "export_statement"
            | "expression_statement"
            | "lexical_declaration"
            | "variable_declaration"
            | "declaration"
            | "field_declaration"
    ) {
        let mut cursor = node.walk();
        for child in node.named_children(&mut cursor) {
            if let Some(body) = body(child) {
                return Some(body);
            }
        }
    }
    None
}
fn header_end(node: Node<'_>, source: &str) -> usize {
    let Some(body) = body(node) else {
        return node.end_byte();
    };
    let rest = &source[body.start_byte()..body.end_byte()];
    if rest.starts_with('{') {
        body.start_byte() + 1
    } else if rest.starts_with("=>") {
        body.start_byte() + 2
    } else {
        // Python block begins at its first statement; keep the preceding colon.
        let mut end = body.start_byte();
        while end > node.start_byte() && source.as_bytes()[end - 1].is_ascii_whitespace() {
            end -= 1;
        }
        end
    }
}
/// Query patterns without a full declaration capture use the nearest AST owner.
pub fn fallback_owner(mut node: Node<'_>) -> Node<'_> {
    while let Some(parent) = node.parent() {
        node = parent;
        if is_context(node.kind())
            || matches!(
                node.kind(),
                "assignment"
                    | "variable_declarator"
                    | "assignment_expression"
                    | "pair"
                    | "type_definition"
                    | "type_spec"
                    | "package_clause"
                    | "var_spec"
                    | "const_spec"
                    | "type_alias_declaration"
                    | "enum_specifier"
                    | "struct_item"
                    | "enum_item"
                    | "union_item"
                    | "type_item"
                    | "macro_definition"
                    | "function_signature"
                    | "method_signature"
                    | "abstract_method_signature"
                    | "function_declarator"
            )
        {
            return node;
        }
    }
    node
}

#[derive(Default)]
struct SelectedFile {
    lines: BTreeMap<usize, SourceLine>,
    clipped: BTreeSet<Clipping>,
}
pub struct Grouped {
    files: BTreeMap<usize, SelectedFile>,
    characters: usize,
}
impl Grouped {
    pub fn new() -> Self {
        Self {
            files: BTreeMap::new(),
            characters: HEADER.chars().count(),
        }
    }
    pub fn tokens(&self) -> usize {
        self.characters.div_ceil(4)
    }

    /// Transactional addition measures actual Markdown, including shared context,
    /// headings, fences, gap markers and clipping notices; an overflow rolls back.
    pub fn add(&mut self, index: usize, path: &str, declaration: &Declaration, limit: usize) -> bool {
        let before = self.characters;
        let is_new = !self.files.contains_key(&index);
        if is_new {
            self.characters += format!("## {path}\n\n\x60\x60\x60text\n\x60\x60\x60\n\n")
                .chars()
                .count();
        }
        let file = self.files.entry(index).or_default();
        let mut changed = Vec::new();
        let mut added_clips = Vec::new();
        for (line, source) in &declaration.lines {
            let added;
            if let Some(existing) = file.lines.get(line) {
                added = existing.merge(source);
                if added.ranges == existing.ranges {
                    continue;
                }
                self.characters = self.characters - existing.text.chars().count() + added.text.chars().count();
                changed.push((*line, Some(existing.clone())));
            } else {
                added = source.clone();
                let previous = file.lines.range(..*line).next_back().map(|(n, _)| *n);
                let next = file.lines.range((Excluded(*line), Unbounded)).next().map(|(n, _)| *n);
                if previous.zip(next).is_some_and(|(a, b)| b > a + 1) {
                    self.characters -= "  ...\n".len();
                }
                if previous.is_some_and(|n| *line > n + 1) {
                    self.characters += "  ...\n".len();
                }
                if next.is_some_and(|n| n > *line + 1) {
                    self.characters += "  ...\n".len();
                }
                self.characters += format!("L{line}: {}\n", source.text).chars().count();
                changed.push((*line, None));
            }
            file.lines.insert(*line, added);
        }
        for clip in &declaration.clipped {
            if file.clipped.insert(clip.clone()) {
                self.characters += clip.marker().chars().count();
                added_clips.push(clip.clone());
            }
        }
        if self.characters <= limit {
            return true;
        }
        for (line, previous) in changed.into_iter().rev() {
            match previous {
                Some(previous) => {
                    file.lines.insert(line, previous);
                }
                None => {
                    file.lines.remove(&line);
                }
            }
        }
        for clip in added_clips {
            file.clipped.remove(&clip);
        }
        if is_new {
            self.files.remove(&index);
        }
        self.characters = before;
        false
    }

    pub fn render(&self, paths: &[&str]) -> String {
        let mut text = String::from(HEADER);
        for (index, file) in &self.files {
            text.push_str(&format!("## {}\n\n\x60\x60\x60text\n", paths[*index]));
            let mut previous = None;
            for (line, source) in &file.lines {
                if previous.is_some_and(|n| *line > n + 1) {
                    text.push_str("  ...\n");
                }
                text.push_str(&format!("L{line}: {}\n", source.text));
                previous = Some(*line);
            }
            for clip in &file.clipped {
                text.push_str(&clip.marker());
            }
            text.push_str("\x60\x60\x60\n\n");
        }
        debug_assert_eq!(text.chars().count(), self.characters);
        text
    }

    pub fn clips(&self) -> impl Iterator<Item = (usize, &Clipping)> {
        self.files
            .iter()
            .flat_map(|(index, file)| file.clipped.iter().map(move |clip| (*index, clip)))
    }
}
