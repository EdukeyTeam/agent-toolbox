//! Grouped declaration excerpts from existing Tree-sitter nodes.
//! Header spans stop at a body opener; enclosing headers supply context.

use std::collections::{BTreeMap, BTreeSet};
use std::ops::Bound::{Excluded, Unbounded};
use std::rc::Rc;
use tree_sitter::Node;

pub const DECLARATION_LINE_LIMIT: usize = 80;
pub const DECLARATION_CHARACTER_LIMIT: usize = 8000;
const HEADER: &str = "# Repository map\n\n";

const CHARACTER_CHECKPOINT: usize = 256;
pub const SOURCE_CACHE_BYTES: usize = 32 * 1024 * 1024;
const CACHE_ENTRY_ALLOWANCE: usize = 2048;

#[derive(Debug)]
struct CharacterIndex {
    checkpoints: Vec<usize>,
    characters: usize,
}
impl CharacterIndex {
    fn new(text: &str) -> Self {
        let mut checkpoints = Vec::new();
        let mut characters = 0;
        for (character, (byte, _)) in text.char_indices().enumerate() {
            if character % CHARACTER_CHECKPOINT == 0 {
                checkpoints.push(byte);
            }
            characters = character + 1;
        }
        if checkpoints.is_empty() {
            checkpoints.push(0);
        }
        Self {
            checkpoints,
            characters,
        }
    }
    fn byte(&self, text: &str, character: usize) -> usize {
        assert!(character <= self.characters);
        if character == self.characters {
            return text.len();
        }
        let checkpoint = character / CHARACTER_CHECKPOINT;
        let remainder = character % CHARACTER_CHECKPOINT;
        let first = self.checkpoints[checkpoint];
        first
            + text[first..]
                .char_indices()
                .nth(remainder)
                .map(|(byte, _)| byte)
                .unwrap_or(0)
    }
    fn character(&self, text: &str, byte: usize) -> usize {
        if byte == text.len() {
            return self.characters;
        }
        let checkpoint = self
            .checkpoints
            .partition_point(|first| *first <= byte)
            .saturating_sub(1);
        checkpoint * CHARACTER_CHECKPOINT + text[self.checkpoints[checkpoint]..byte].chars().count()
    }
}

#[derive(Debug)]
struct LineContent {
    source: String,
    offsets: CharacterIndex,
}
impl LineContent {
    #[cfg(test)]
    fn new(source: &str) -> Self {
        Self::prepared(sanitize(source))
    }
    fn prepared(source: String) -> Self {
        let offsets = CharacterIndex::new(&source);
        Self { source, offsets }
    }
    fn slice(&self, start: usize, end: usize) -> &str {
        &self.source[self.offsets.byte(&self.source, start)..self.offsets.byte(&self.source, end)]
    }
}

#[derive(Clone, Copy)]
struct SourceView<'a> {
    content: &'a LineContent,
    first: usize,
    end: usize,
}
impl SourceView<'_> {
    fn slice(&self, start: usize, end: usize) -> &str {
        assert!(end <= self.end - self.first);
        self.content.slice(self.first + start, self.first + end)
    }
    fn whitespace(&self, start: usize, end: usize) -> bool {
        start < end && self.slice(start, end).chars().all(char::is_whitespace)
    }
}

/// One current source file. Sparse Unicode offsets keep indexed source storage
/// proportional to input bytes rather than one usize per source character.
pub struct RenderSource {
    content: LineContent,
    line_characters: Vec<usize>,
}
impl RenderSource {
    pub fn new(text: &str) -> Self {
        let mut cleaned = String::with_capacity(text.len());
        let mut line_characters = Vec::new();
        let mut characters = 0;
        for (row, line) in text.split('\n').enumerate() {
            if row > 0 {
                cleaned.push('\n');
                characters += 1;
            }
            line_characters.push(characters);
            let line = sanitize(line.strip_suffix('\r').unwrap_or(line));
            characters += line.chars().count();
            cleaned.push_str(&line);
        }
        Self {
            content: LineContent::prepared(cleaned),
            line_characters,
        }
    }
    fn line(&self, row: usize) -> SourceView<'_> {
        SourceView {
            content: &self.content,
            first: self.line_characters[row],
            end: self
                .line_characters
                .get(row + 1)
                .map(|next| next - 1)
                .unwrap_or(self.content.offsets.characters),
        }
    }
    fn retained_bytes(&self) -> usize {
        std::mem::size_of::<Self>()
            + self.content.source.capacity()
            + self.content.offsets.checkpoints.capacity() * std::mem::size_of::<usize>()
            + self.line_characters.capacity() * std::mem::size_of::<usize>()
    }
}

struct CachedSource {
    source: Rc<RenderSource>,
    bytes: usize,
    touched: u64,
}
pub struct SourceCache {
    entries: BTreeMap<usize, CachedSource>,
    order: BTreeSet<(u64, usize)>,
    limit: usize,
    retained_bytes: usize,
    clock: u64,
}
impl SourceCache {
    pub fn new(limit: usize) -> Self {
        Self {
            entries: BTreeMap::new(),
            order: BTreeSet::new(),
            limit,
            retained_bytes: 0,
            clock: 0,
        }
    }
    pub fn get(
        &mut self,
        index: usize,
        load: impl FnOnce() -> Result<RenderSource, String>,
    ) -> Result<Rc<RenderSource>, String> {
        self.clock += 1;
        if let Some(entry) = self.entries.get_mut(&index) {
            self.order.remove(&(entry.touched, index));
            entry.touched = self.clock;
            self.order.insert((entry.touched, index));
            return Ok(entry.source.clone());
        }
        let source = Rc::new(load()?);
        // Conservative per-entry allowance covers sparsely occupied B-tree nodes,
        // the Rc allocation and cache bookkeeping; allocator/process overhead
        // and the active single-file parsing/loading workspace are separate.
        let bytes = source.retained_bytes().saturating_add(CACHE_ENTRY_ALLOWANCE);
        if bytes > self.limit {
            return Ok(source);
        }
        while self.retained_bytes + bytes > self.limit {
            let (_, oldest) = self.order.pop_first().expect("nonempty cache exceeds its budget");
            let entry = self.entries.remove(&oldest).expect("LRU entry exists");
            self.retained_bytes -= entry.bytes;
        }
        self.retained_bytes += bytes;
        self.entries.insert(
            index,
            CachedSource {
                source: source.clone(),
                bytes,
                touched: self.clock,
            },
        );
        self.order.insert((self.clock, index));
        Ok(source)
    }
}

#[derive(Clone, Debug)]
pub struct SourceLine {
    pub text: String,
    ranges: Vec<(usize, usize)>,
    // Byte ranges of selected payloads within compact text, never original bodies.
    payloads: Vec<(usize, usize)>,
}
impl SourceLine {
    fn new(source: SourceView<'_>, ranges: Vec<(usize, usize)>) -> Self {
        Self::from_ranges(source, ranges, true)
    }
    fn from_ranges(source: SourceView<'_>, ranges: Vec<(usize, usize)>, whitespace: bool) -> Self {
        let mut text = String::new();
        let mut payloads = Vec::new();
        let mut previous = None;
        for (start, end) in &ranges {
            if let Some(previous) = previous {
                if whitespace && source.whitespace(previous, *start) {
                    text.push_str(source.slice(previous, *start));
                } else {
                    text.push_str(" … ");
                }
            } else if *start > 0 {
                text.push_str(" … ");
            }
            let first = text.len();
            text.push_str(source.slice(*start, *end));
            payloads.push((first, text.len()));
            previous = Some(*end);
        }
        Self { text, ranges, payloads }
    }
    #[cfg(test)]
    fn excerpt(source: Rc<LineContent>, start: usize, end: usize) -> Self {
        Self::excerpt_view(
            SourceView {
                content: &source,
                first: 0,
                end: source.offsets.characters,
            },
            start,
            end,
            Format::Grouped,
        )
    }
    fn excerpt_view(source: SourceView<'_>, mut start: usize, end: usize, format: Format) -> Self {
        if format == Format::Compact {
            // Trim before declaration quota/identity checks, keeping coordinates
            // in the original physical line. Never charge discarded indentation.
            start += source
                .slice(start, end)
                .chars()
                .take_while(|c| c.is_whitespace())
                .count();
        } else if source.whitespace(0, start) {
            start = 0;
        }
        Self::new(source, vec![(start, end)])
    }
    fn source_characters(&self) -> usize {
        self.ranges.iter().map(|(start, end)| end - start).sum()
    }
    fn merge_compact(&self, other: &Self, source: SourceView<'_>) -> Self {
        // Parsing stores selected headers only. Whitespace between disjoint
        // headers is accounted/materialized later through the bounded cache.
        self.merge_ranges(other, source, false)
    }
    fn merge_ranges(&self, other: &Self, source: SourceView<'_>, whitespace: bool) -> Self {
        let mut inputs = self.ranges.clone();
        inputs.extend(&other.ranges);
        inputs.sort_unstable();
        let mut ranges: Vec<(usize, usize)> = Vec::new();
        for (start, end) in inputs {
            if let Some(last) = ranges.last_mut() {
                if start <= last.1 || (whitespace && source.whitespace(last.1, start)) {
                    last.1 = last.1.max(end);
                    continue;
                }
            }
            ranges.push((start, end));
        }
        Self::from_ranges(source, ranges, whitespace)
    }
    fn bounded(&self, mut available: usize) -> Self {
        let mut text = String::new();
        let mut ranges = Vec::new();
        let mut payloads = Vec::new();
        let mut previous = None;
        for ((start, end), (first, last)) in self.ranges.iter().zip(&self.payloads) {
            let taken = available.min(end - start);
            if taken > 0 || start == end {
                if let Some(previous) = previous {
                    text.push_str(&self.text[previous..*first]);
                } else if *start > 0 {
                    text.push_str(" … ");
                }
                let payload = &self.text[*first..*last];
                let limit = payload
                    .char_indices()
                    .nth(taken)
                    .map(|(byte, _)| byte)
                    .unwrap_or(payload.len());
                let beginning = text.len();
                text.push_str(&payload[..limit]);
                payloads.push((beginning, text.len()));
                ranges.push((*start, start + taken));
                previous = Some(*last);
            }
            available -= taken;
        }
        Self { text, ranges, payloads }
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
    source_lines: RenderSource,
    raw_offsets: CharacterIndex,
    original_line_characters: Vec<usize>,
    format: Format,
}
impl<'a> SourceText<'a> {
    pub fn new(text: &'a str) -> Self {
        Self::with_format(text, Format::Grouped)
    }
    pub fn with_format(text: &'a str, format: Format) -> Self {
        let mut line_starts = vec![0];
        let mut original_line_characters = vec![0];
        for (character, (byte, value)) in text.char_indices().enumerate() {
            if value == '\n' {
                line_starts.push(byte + 1);
                original_line_characters.push(character + 1);
            }
        }
        Self {
            text,
            line_starts,
            source_lines: RenderSource::new(text),
            raw_offsets: CharacterIndex::new(text),
            original_line_characters,
            format,
        }
    }

    fn column(&self, row: usize, byte: usize) -> usize {
        self.raw_offsets.character(self.text, byte) - self.original_line_characters[row]
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
            let start_column = self.column(line - 1, first);
            let end_column = self.column(line - 1, limit);
            lines.push((
                line,
                SourceLine::excerpt_view(self.source_lines.line(line - 1), start_column, end_column, self.format),
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
        let start = self.column(row, name.start_byte());
        let end = self.column(row, name.end_byte());
        let physical = self.source_lines.line(row);
        let leading = physical
            .slice(0, physical.end - physical.first)
            .chars()
            .take_while(|c| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(c))
            .count();
        start >= leading && end.saturating_sub(leading) <= crate::policy::MAX_SNIPPET_CHARS
    }

    fn check_identifier(&self, declaration: &Declaration, name: Node<'_>) -> Result<(), String> {
        let row = name.start_position().row;
        let start = self.column(row, name.start_byte());
        let end = self.column(row, name.end_byte());
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
                    merge(&mut result, prefix, &self.source_lines);
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
                merge(&mut result, context, &self.source_lines);
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
fn merge(target: &mut Declaration, other: Declaration, original: &RenderSource) {
    for (line, source) in other.lines {
        let existing = target.lines.entry(line).or_insert_with(|| source.clone());
        *existing = existing.merge_compact(&source, original.line(line - 1));
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

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Grouped,
    Compact,
}
impl Format {
    fn heading(self, path: &str) -> String {
        match self {
            Self::Grouped => format!("## {path}\n\n```text\n"),
            Self::Compact => format!("## {path}\n\n"),
        }
    }
    fn ending(self) -> &'static str {
        match self {
            Self::Grouped => "```\n\n",
            Self::Compact => "\n",
        }
    }
}

#[derive(Clone)]
struct RenderedLine {
    text: String,
    ranges: CountedLine,
}
impl RenderedLine {
    fn new(ranges: CountedLine, source: SourceView<'_>, format: Format) -> Self {
        let mut text = String::new();
        ranges.append(source, format, &mut text);
        Self { text, ranges }
    }
}

#[derive(Default)]
struct SelectedFile {
    lines: BTreeMap<usize, RenderedLine>,
    clipped: BTreeSet<Clipping>,
}
pub struct Grouped {
    files: BTreeMap<usize, SelectedFile>,
    characters: usize,
    format: Format,
}
impl Grouped {
    pub fn new() -> Self {
        Self::with_format(Format::Grouped)
    }
    pub fn with_format(format: Format) -> Self {
        Self {
            files: BTreeMap::new(),
            characters: HEADER.chars().count(),
            format,
        }
    }
    pub fn tokens(&self) -> usize {
        self.characters.div_ceil(4)
    }

    /// Transactional addition measures actual Markdown, including shared context,
    /// headings, fences, gap markers and clipping notices; an overflow rolls back.
    pub fn add(
        &mut self,
        index: usize,
        path: &str,
        declaration: &Declaration,
        limit: usize,
        original: &RenderSource,
    ) -> bool {
        let before = self.characters;
        let is_new = !self.files.contains_key(&index);
        if is_new {
            self.characters += self.format.heading(path).chars().count() + self.format.ending().chars().count();
        }
        let file = self.files.entry(index).or_default();
        let mut changed = Vec::new();
        let mut added_clips = Vec::new();
        for (line, source) in &declaration.lines {
            let added;
            if let Some(existing) = file.lines.get(line) {
                let mut ranges = existing.ranges.clone();
                ranges.merge(source, original.line(*line - 1), self.format);
                if ranges.ranges == existing.ranges.ranges {
                    continue;
                }
                added = RenderedLine::new(ranges, original.line(*line - 1), self.format);
                self.characters = self.characters - existing.text.chars().count() + added.text.chars().count();
                changed.push((*line, Some(existing.clone())));
            } else {
                added = RenderedLine::new(CountedLine::from_line(source), original.line(*line - 1), self.format);
                let previous = file.lines.range(..*line).next_back().map(|(n, _)| *n);
                let next = file.lines.range((Excluded(*line), Unbounded)).next().map(|(n, _)| *n);
                if self.format == Format::Grouped && previous.zip(next).is_some_and(|(a, b)| b > a + 1) {
                    self.characters -= "  ...\n".len();
                }
                if self.format == Format::Grouped && previous.is_some_and(|n| *line > n + 1) {
                    self.characters += "  ...\n".len();
                }
                if self.format == Format::Grouped && next.is_some_and(|n| n > *line + 1) {
                    self.characters += "  ...\n".len();
                }
                self.characters += format!("L{line}: {}\n", added.text).chars().count();
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
            text.push_str(&self.format.heading(paths[*index]));
            let mut previous = None;
            for (line, source) in &file.lines {
                if self.format == Format::Grouped && previous.is_some_and(|n| *line > n + 1) {
                    text.push_str("  ...\n");
                }
                text.push_str(&format!("L{line}: {}\n", source.text));
                previous = Some(*line);
            }
            for clip in &file.clipped {
                text.push_str(&clip.marker());
            }
            text.push_str(self.format.ending());
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

#[derive(Clone)]
struct CountedLine {
    ranges: Vec<(usize, usize)>,
}
impl CountedLine {
    fn from_line(line: &SourceLine) -> Self {
        Self {
            ranges: line.ranges.clone(),
        }
    }
    fn merge(&mut self, line: &SourceLine, source: SourceView<'_>, format: Format) {
        let mut inputs = self.ranges.clone();
        inputs.extend(&line.ranges);
        inputs.sort_unstable();
        self.ranges.clear();
        for (start, end) in inputs {
            if let Some(previous) = self.ranges.last_mut() {
                if start <= previous.1 || (format == Format::Grouped && source.whitespace(previous.1, start)) {
                    previous.1 = previous.1.max(end);
                    continue;
                }
            }
            self.ranges.push((start, end));
        }
    }
    /// Visit selected original intervals without copying omitted source. Compact
    /// removes leading whitespace and normalizes only omitted whitespace gaps;
    /// inline literal content inside a selected interval is left untouched.
    fn pieces(&self, source: SourceView<'_>, format: Format, mut emit: impl FnMut(&str)) {
        let mut previous = None;
        for (start, end) in &self.ranges {
            if let Some(previous) = previous {
                if source.whitespace(previous, *start) {
                    if format == Format::Compact {
                        emit(" ");
                    } else {
                        emit(source.slice(previous, *start));
                    }
                } else {
                    emit(" … ");
                }
            } else if *start > 0 && (format == Format::Grouped || !source.whitespace(0, *start)) {
                emit(" … ");
            }
            let payload = source.slice(*start, *end);
            emit(if previous.is_none() && format == Format::Compact {
                payload.trim_start()
            } else {
                payload
            });
            previous = Some(*end);
        }
    }
    fn characters(&self, source: SourceView<'_>, format: Format) -> usize {
        let mut count = 0;
        self.pieces(source, format, |piece| count += piece.chars().count());
        count
    }
    fn append(&self, source: SourceView<'_>, format: Format, text: &mut String) {
        self.pieces(source, format, |piece| text.push_str(piece));
    }
}

pub struct CompleteGrouped {
    pub text: Option<String>,
    pub characters: usize,
    pub clipped: Vec<(usize, Clipping)>,
    #[cfg(test)]
    peak_retained_characters: usize,
}

impl Grouped {
    /// Count/merge one file's ranges at a time, without copying source payloads.
    /// Output is retained only while it fits the declared character budget.
    /// After overflow, discard it and keep counting for an exact diagnostic.
    #[cfg(test)]
    pub fn complete<'a>(
        paths: &[&str],
        declarations: impl IntoIterator<Item = (usize, &'a Declaration)>,
        limit: usize,
        load: &mut impl FnMut(usize) -> Result<Rc<RenderSource>, String>,
    ) -> Result<CompleteGrouped, String> {
        Self::complete_with_format(paths, declarations, limit, load, Format::Grouped)
    }

    pub fn complete_with_format<'a>(
        paths: &[&str],
        declarations: impl IntoIterator<Item = (usize, &'a Declaration)>,
        limit: usize,
        load: &mut impl FnMut(usize) -> Result<Rc<RenderSource>, String>,
        format: Format,
    ) -> Result<CompleteGrouped, String> {
        let mut by_file: BTreeMap<usize, Vec<&Declaration>> = BTreeMap::new();
        for (index, declaration) in declarations {
            by_file.entry(index).or_default().push(declaration);
        }
        let mut result = CompleteGrouped {
            text: (HEADER.chars().count() <= limit).then(|| String::from(HEADER)),
            characters: HEADER.chars().count(),
            clipped: Vec::new(),
            #[cfg(test)]
            peak_retained_characters: if HEADER.chars().count() <= limit {
                HEADER.chars().count()
            } else {
                0
            },
        };
        for (index, declarations) in by_file {
            let original = load(index)?;
            let mut lines: BTreeMap<usize, CountedLine> = BTreeMap::new();
            let mut clipping = BTreeSet::new();
            for declaration in declarations {
                for (number, source) in &declaration.lines {
                    if let Some(existing) = lines.get_mut(number) {
                        existing.merge(source, original.line(*number - 1), format);
                    } else {
                        lines.insert(*number, CountedLine::from_line(source));
                    }
                }
                clipping.extend(declaration.clipped.iter().cloned());
            }
            let heading = format.heading(paths[index]);
            result.characters += heading.chars().count() + format.ending().chars().count();
            let mut previous = None;
            for (number, source) in &lines {
                if format == Format::Grouped && previous.is_some_and(|n| *number > n + 1) {
                    result.characters += "  ...\n".len();
                }
                result.characters +=
                    format!("L{number}: ").len() + source.characters(original.line(*number - 1), format) + 1;
                previous = Some(*number);
            }
            for clip in &clipping {
                result.characters += clip.marker().chars().count();
            }
            if result.characters > limit {
                result.text = None;
            }
            if let Some(text) = result.text.as_mut() {
                text.push_str(&heading);
                let mut previous = None;
                for (number, source) in &lines {
                    if format == Format::Grouped && previous.is_some_and(|n| *number > n + 1) {
                        text.push_str("  ...\n");
                    }
                    text.push_str(&format!("L{number}: "));
                    source.append(original.line(*number - 1), format, text);
                    text.push('\n');
                    previous = Some(*number);
                }
                for clip in &clipping {
                    text.push_str(&clip.marker());
                }
                text.push_str(format.ending());
                debug_assert_eq!(text.chars().count(), result.characters);
                #[cfg(test)]
                {
                    result.peak_retained_characters = result.characters;
                }
            }
            result.clipped.extend(clipping.into_iter().map(|clip| (index, clip)));
        }
        Ok(result)
    }
}

#[cfg(test)]
mod complete_tests {
    use super::*;

    #[test]
    fn singleton_source_cache_accounts_for_container_overhead_before_admission() {
        let physical = "class Tiny {}";
        let payload = RenderSource::new(physical).retained_bytes();
        let mut refused = SourceCache::new(payload + 256);
        let source = refused.get(0, || Ok(RenderSource::new(physical))).unwrap();
        assert_eq!(source.line(0).slice(0, 5), "class");
        assert!(refused.entries.is_empty());
        assert!(refused.order.is_empty());
        assert_eq!(refused.retained_bytes, 0);
        let mut admitted = SourceCache::new(payload + CACHE_ENTRY_ALLOWANCE);
        admitted.get(0, || Ok(RenderSource::new(physical))).unwrap();
        assert_eq!(admitted.retained_bytes, payload + CACHE_ENTRY_ALLOWANCE);
        assert_eq!(admitted.entries.len(), 1);
        assert_eq!(admitted.order.len(), 1);
    }

    #[test]
    fn stored_ast_declarations_leave_large_whitespace_gaps_lazy() {
        let physical = format!("class Tiny {{ {}void selected() {{}} }}", " ".repeat(150_000));
        let mut extractor = crate::tags::Extractor::new();
        let parsed = match extractor.extract_with_declarations(
            "java",
            "Tiny.java",
            physical.as_bytes(),
            Some(Format::Grouped),
            true,
        ) {
            Ok(parsed) => parsed,
            Err(crate::tags::ExtractError::File(error) | crate::tags::ExtractError::Limit(error)) => panic!("{error}"),
        };
        let retained: usize = parsed
            .declarations
            .values()
            .flat_map(|declaration| declaration.lines.values())
            .map(|fragment| fragment.text.chars().count())
            .sum();
        assert!(
            retained <= 2 * DECLARATION_CHARACTER_LIMIT + 64,
            "compact AST declarations retained {retained} characters from an unselected whitespace gap"
        );
    }

    #[test]
    fn sparse_unicode_offsets_match_original_coordinates_without_per_character_storage() {
        let text = "aα💡\u{85}\t".repeat(800);
        let index = CharacterIndex::new(&text);
        for (character, (byte, _)) in text.char_indices().enumerate() {
            assert_eq!(index.byte(&text, character), byte);
            assert_eq!(index.character(&text, byte), character);
        }
        assert_eq!(index.byte(&text, index.characters), text.len());
        assert!(index.checkpoints.len() <= index.characters / CHARACTER_CHECKPOINT + 1);
        let source = RenderSource::new(&("x".repeat(140_000)));
        assert!(
            source.retained_bytes() < 160_000,
            "sparse indexing retains excessive source metadata"
        );
    }

    #[test]
    fn source_cache_evicts_by_retained_bytes_and_leaves_oversized_sources_uncached() {
        let small = "💡".repeat(50_000);
        let huge = "💡".repeat(150_000);
        let limit = RenderSource::new(&small).retained_bytes() + CACHE_ENTRY_ALLOWANCE;
        let mut cache = SourceCache::new(limit);
        let mut reads = [0; 3];
        for file in [0, 0, 1, 0, 2, 2, 0] {
            let source = cache
                .get(file, || {
                    reads[file] += 1;
                    Ok(RenderSource::new(if file == 2 { &huge } else { &small }))
                })
                .unwrap();
            assert_eq!(source.line(0).slice(0, 1), "💡");
            assert!(cache.retained_bytes <= limit);
        }
        assert_eq!(reads, [2, 1, 2]);
        assert_eq!(cache.entries.len(), 1);
        assert!(cache.entries.contains_key(&0));
    }

    #[test]
    fn bounded_fragments_release_large_physical_source_lines_across_files() {
        let mut stored = Vec::new();
        let mut originals = Vec::new();
        for file in 0..20 {
            let header = format!("class Tiny{file} {{");
            let physical = format!(
                "{header}void method() {{ String hidden = \"{}\"; }}}}",
                "BODY_MUST_NOT_RETAIN".repeat(7000)
            );
            let source = Rc::new(LineContent::new(&physical));
            originals.push(Rc::downgrade(&source));
            stored.push(SourceLine::excerpt(source, 0, header.chars().count()).bounded(DECLARATION_CHARACTER_LIMIT));
        }
        let retained = originals
            .iter()
            .filter_map(|source| source.upgrade())
            .map(|line| line.source.len())
            .sum::<usize>();
        assert_eq!(
            retained, 0,
            "bounded declaration fragments retained {retained} physical-source bytes"
        );
        assert_eq!(stored.len(), 20);
        assert!(stored.iter().all(|fragment| fragment.text.starts_with("class Tiny")));
    }

    #[test]
    fn large_complete_rejection_counts_exactly_without_retaining_oversized_output() {
        let paths = ["src/Śervice0.py", "src/Śervice1.py", "src/Śervice2.py"];
        let mut declarations = Vec::new();
        let mut originals = Vec::new();
        for file in 0..3 {
            let mut physical = String::from("class Shared:\n");
            let context = SourceLine::excerpt(Rc::new(LineContent::new("class Shared:")), 0, 13);
            for method in 0..120 {
                let source = format!("    def operation{method:03}({}value):", " ".repeat(3000));
                physical.push_str(&source);
                physical.push_str("\n        return value\n");
                let length = source.chars().count();
                let fragment = SourceLine::excerpt(Rc::new(LineContent::new(&source)), 4, length);
                let mut declaration = Declaration::default();
                declaration.lines.insert(1, context.clone());
                declaration.lines.insert(method * 2 + 2, fragment);
                declarations.push((file, declaration));
            }
            originals.push(Rc::new(RenderSource::new(&physical)));
        }
        for format in [Format::Grouped, Format::Compact] {
            let mut load = |file: usize| Ok(originals[file].clone());
            // Unbounded reference rendering is intentional only in this test,
            // outside the measured production complete-mode budget path.
            let mut reference = Grouped::with_format(format);
            for (file, declaration) in &declarations {
                assert!(reference.add(*file, paths[*file], declaration, usize::MAX, &originals[*file]));
            }
            let expected = reference.render(&paths);
            let required = expected.chars().count();
            let rejected = Grouped::complete_with_format(
                &paths,
                declarations.iter().map(|(file, d)| (*file, d)),
                256,
                &mut load,
                format,
            )
            .unwrap();
            assert!(rejected.text.is_none());
            assert_eq!(rejected.characters, required);
            assert!(rejected.peak_retained_characters <= 256);
            let exact = Grouped::complete_with_format(
                &paths,
                declarations.iter().map(|(file, d)| (*file, d)),
                required.div_ceil(4) * 4,
                &mut load,
                format,
            )
            .unwrap();
            assert_eq!(exact.text.as_deref(), Some(expected.as_str()));
            assert_eq!(exact.characters, required);
            assert!(exact.peak_retained_characters <= required.div_ceil(4) * 4);
        }
    }

    #[test]
    fn complete_count_deduplicates_clips_and_merges_inline_unicode_ranges_before_admission() {
        let source = Rc::new(LineContent::new("α.β"));
        let mut pieces = Vec::new();
        for range in [(0, 1), (2, 3), (1, 2)] {
            let mut declaration = Declaration::default();
            declaration
                .lines
                .insert(1, SourceLine::excerpt(source.clone(), range.0, range.1));
            declaration.clipped.insert(Clipping {
                line: 1,
                start_line: 1,
                end_line: 91,
                reason: "line limit".to_string(),
            });
            pieces.push(declaration);
        }
        let paths = ["Śhared.py"];
        let expected = format!("{HEADER}## Śhared.py\n\n\x60\x60\x60text\nL1: α.β\n  ... [declaration clipped: L1-L91; line limit]\n\x60\x60\x60\n\n");
        let original = Rc::new(RenderSource::new("α.β"));
        let mut load = |_file: usize| Ok(original.clone());
        let complete = Grouped::complete(
            &paths,
            pieces.iter().map(|declaration| (0, declaration)),
            expected.chars().count(),
            &mut load,
        )
        .unwrap();
        assert_eq!(complete.text.as_deref(), Some(expected.as_str()));
        assert_eq!(complete.characters, expected.chars().count());
        assert_eq!(complete.clipped.len(), 1);
    }
}
