//! Tag extraction with the tag queries vendored in the skill. The query text
//! is compiled into the binary, so nothing is downloaded or read at run time.

use std::collections::{BTreeMap, BTreeSet};

use crate::render::{self, Declaration, SourceText};

use tree_sitter::{Language, Parser, Query, QueryCursor, StreamingIterator};

use crate::inventory::sha256_hex;
use crate::policy;

macro_rules! vendored_query {
    ($path:literal) => {
        include_str!(concat!(
            "../../../skills/legacy-codebase-workflows/vendor/queries/",
            $path
        ))
    };
}

pub struct LanguageSpec {
    pub name: &'static str,
    pub query_path: &'static str,
    pub query_source: &'static str,
    pub grammar_crate: &'static str,
    language: fn() -> Language,
}

pub const LANGUAGE_SPECS: &[LanguageSpec] = &[
    LanguageSpec {
        name: "java",
        query_path: "tree-sitter-language-pack/java-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/java-tags.scm"),
        grammar_crate: "tree-sitter-java",
        language: || tree_sitter_java::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "python",
        query_path: "tree-sitter-language-pack/python-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/python-tags.scm"),
        grammar_crate: "tree-sitter-python",
        language: || tree_sitter_python::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "javascript",
        query_path: "tree-sitter-language-pack/javascript-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/javascript-tags.scm"),
        grammar_crate: "tree-sitter-javascript",
        language: || tree_sitter_javascript::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "typescript",
        query_path: "tree-sitter-languages/typescript-tags.scm",
        query_source: vendored_query!("tree-sitter-languages/typescript-tags.scm"),
        grammar_crate: "tree-sitter-typescript",
        language: || tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
    },
    LanguageSpec {
        name: "tsx",
        query_path: "tree-sitter-languages/typescript-tags.scm",
        query_source: vendored_query!("tree-sitter-languages/typescript-tags.scm"),
        grammar_crate: "tree-sitter-typescript",
        language: || tree_sitter_typescript::LANGUAGE_TSX.into(),
    },
    LanguageSpec {
        name: "c",
        query_path: "tree-sitter-language-pack/c-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/c-tags.scm"),
        grammar_crate: "tree-sitter-c",
        language: || tree_sitter_c::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "cpp",
        query_path: "tree-sitter-language-pack/cpp-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/cpp-tags.scm"),
        grammar_crate: "tree-sitter-cpp",
        language: || tree_sitter_cpp::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "c_sharp",
        query_path: "tree-sitter-language-pack/csharp-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/csharp-tags.scm"),
        grammar_crate: "tree-sitter-c-sharp",
        language: || tree_sitter_c_sharp::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "go",
        query_path: "tree-sitter-language-pack/go-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/go-tags.scm"),
        grammar_crate: "tree-sitter-go",
        language: || tree_sitter_go::LANGUAGE.into(),
    },
    LanguageSpec {
        name: "rust",
        query_path: "tree-sitter-language-pack/rust-tags.scm",
        query_source: vendored_query!("tree-sitter-language-pack/rust-tags.scm"),
        grammar_crate: "tree-sitter-rust",
        language: || tree_sitter_rust::LANGUAGE.into(),
    },
];

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Kind {
    Def,
    Ref,
}

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub struct Tag {
    pub line: usize,
    pub kind: Kind,
    pub name: String,
}

pub struct FileTags {
    /// Sorted by line, kind, name without duplicates.
    pub tags: Vec<Tag>,
    pub has_syntax_errors: bool,
    /// Ephemeral AST-derived headers; tag identity/ranking stays unchanged.
    pub declarations: BTreeMap<(usize, String), Declaration>,
}

struct Loaded {
    parser: Parser,
    query: Query,
    /// Per capture index: definition, reference, or not a name capture.
    capture_kinds: Vec<Option<Kind>>,
    declaration_captures: Vec<bool>,
}

/// Lazily compiled parser and query per language.
pub struct Extractor {
    loaded: Vec<Option<Result<Loaded, String>>>,
}

pub fn spec_for(language: &str) -> Option<(usize, &'static LanguageSpec)> {
    LANGUAGE_SPECS
        .iter()
        .enumerate()
        .find(|(_, spec)| spec.name == language)
}

pub fn query_sha256(spec: &LanguageSpec) -> String {
    sha256_hex(spec.query_source.as_bytes())
}

fn load(spec: &LanguageSpec) -> Result<Loaded, String> {
    let language = (spec.language)();
    let mut parser = Parser::new();
    parser
        .set_language(&language)
        .map_err(|error| format!("grammar {} is incompatible: {error}", spec.grammar_crate))?;
    let query = Query::new(&language, spec.query_source)
        .map_err(|error| format!("tag query {} does not compile: {error}", spec.query_path))?;
    let capture_kinds = query
        .capture_names()
        .iter()
        .map(|name| {
            if name.starts_with("name.definition.") {
                Some(Kind::Def)
            } else if name.starts_with("name.reference.") {
                Some(Kind::Ref)
            } else {
                None
            }
        })
        .collect();
    let declaration_captures = query
        .capture_names()
        .iter()
        .map(|name| name.starts_with("definition."))
        .collect();
    Ok(Loaded {
        declaration_captures,
        parser,
        query,
        capture_kinds,
    })
}

/// Outcome of extraction: a per-file failure is reported and skipped, a
/// limit stops the whole run.
pub enum ExtractError {
    File(String),
    Limit(String),
}

impl Extractor {
    pub fn new() -> Self {
        Self {
            loaded: LANGUAGE_SPECS.iter().map(|_| None).collect(),
        }
    }

    #[cfg(test)]
    pub fn extract(&mut self, language: &str, path: &str, source: &[u8]) -> Result<FileTags, ExtractError> {
        self.extract_with_declarations(language, path, source, false, false)
    }

    pub fn extract_with_declarations(
        &mut self,
        language: &str,
        path: &str,
        source: &[u8],
        grouped: bool,
        all_definitions: bool,
    ) -> Result<FileTags, ExtractError> {
        let (index, spec) =
            spec_for(language).ok_or_else(|| ExtractError::File(format!("no tag query for {language}")))?;
        let loaded = self.loaded[index].get_or_insert_with(|| load(spec));
        let loaded = loaded.as_mut().map_err(|error| ExtractError::File(error.clone()))?;
        loaded.parser.reset();
        let tree = loaded
            .parser
            .parse(source, None)
            .ok_or_else(|| ExtractError::File("parser returned no tree".to_string()))?;
        let mut cursor = QueryCursor::new();
        let mut matches = cursor.matches(&loaded.query, tree.root_node(), source);
        let mut found = BTreeSet::new();
        let text = String::from_utf8_lossy(source);
        let source_text = (grouped || all_definitions).then(|| SourceText::new(&text));
        let mut declarations = BTreeMap::new();
        let mut definition_positions: BTreeMap<(usize, String), BTreeSet<(usize, usize)>> = BTreeMap::new();
        while let Some(found_match) = matches.next() {
            for capture in found_match.captures {
                let Some(kind) = loaded.capture_kinds[capture.index as usize] else {
                    continue;
                };
                let name = String::from_utf8_lossy(&source[capture.node.byte_range()]).into_owned();
                let line = capture.node.start_position().row + 1;
                if name.is_empty() || name.chars().count() > policy::MAX_NAME_CHARS {
                    if all_definitions && kind == Kind::Def {
                        return Err(ExtractError::Limit(format!(
                            "definition name at {path}:L{line} exceeds the {}-character name limit; complete mapping cannot silently filter it",
                            policy::MAX_NAME_CHARS
                        )));
                    }
                    continue;
                }
                if all_definitions && kind == Kind::Def {
                    if !grouped
                        && !source_text
                            .as_ref()
                            .expect("all mode loads source coordinates")
                            .legacy_identifier_visible(capture.node)
                    {
                        return Err(ExtractError::Limit(format!(
                            "all-definitions cannot show the full identifier at {path}:L{line} within legacy lines' {}-character limit; use --format grouped",
                            policy::MAX_SNIPPET_CHARS
                        )));
                    }
                    let positions = definition_positions.entry((line, name.clone())).or_default();
                    positions.insert((capture.node.start_byte(), capture.node.end_byte()));
                    if positions.len() > 1 {
                        return Err(ExtractError::Limit(format!(
                            "ambiguous definition identity at {path}:L{line} for {name:?}: distinct capture positions share the legacy line/name key"
                        )));
                    }
                }
                if kind == Kind::Def {
                    if let Some(source_text) = source_text.as_ref().filter(|_| grouped) {
                        let owner = found_match
                            .captures
                            .iter()
                            .filter(|candidate| {
                                loaded.declaration_captures[candidate.index as usize]
                                    && candidate.node.start_byte() <= capture.node.start_byte()
                                    && candidate.node.end_byte() >= capture.node.end_byte()
                            })
                            .min_by_key(|candidate| candidate.node.end_byte() - candidate.node.start_byte())
                            .map(|candidate| candidate.node)
                            .unwrap_or_else(|| render::fallback_owner(capture.node));
                        let key = (line, name.clone());
                        if !declarations.contains_key(&key) {
                            let declaration = source_text
                                .declaration(capture.node, owner)
                                .map_err(|message| ExtractError::Limit(format!("{path}: {message}")))?;
                            declarations.insert(key, declaration);
                        }
                    }
                }
                found.insert(Tag { line, kind, name });
                if found.len() > policy::MAX_TAGS_PER_FILE {
                    return Err(ExtractError::Limit(format!(
                        "tag limit exceeded in {path}; map a narrower subtree"
                    )));
                }
            }
        }
        Ok(FileTags {
            tags: found.into_iter().collect(),
            has_syntax_errors: tree.root_node().has_error(),
            declarations,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(language: &str, source: &str, kind: Kind) -> Vec<(usize, String)> {
        let mut extractor = Extractor::new();
        let Ok(tags) = extractor.extract(language, "fixture", source.as_bytes()) else {
            panic!("extraction failed for {language}");
        };
        tags.tags
            .into_iter()
            .filter(|tag| tag.kind == kind)
            .map(|tag| (tag.line, tag.name))
            .collect()
    }

    #[test]
    fn every_vendored_query_compiles_against_its_pinned_grammar() {
        for spec in LANGUAGE_SPECS {
            if let Err(error) = load(spec) {
                panic!("{}: {error}", spec.name);
            }
        }
    }

    #[test]
    fn java_definitions_and_references_keep_original_lines() {
        let source = "package a;\n\npublic class Transfer extends Base implements Runnable {\n    void run() {\n        helper.connect();\n        new Session();\n    }\n}\ninterface Port {}\n";
        assert_eq!(
            names("java", source, Kind::Def),
            vec![
                (3, "Transfer".to_string()),
                (4, "run".to_string()),
                (9, "Port".to_string())
            ]
        );
        let references = names("java", source, Kind::Ref);
        for expected in ["Base", "Runnable", "connect", "Session"] {
            assert!(references.iter().any(|(_, name)| name == expected), "{expected}");
        }
    }

    #[test]
    fn each_language_yields_a_real_definition() {
        let cases = [
            (
                "python",
                "class Ledger:\n    def post(self):\n        audit()\n",
                "post",
            ),
            ("javascript", "class Cart {\n  total() { return sum(1); }\n}\n", "total"),
            (
                "typescript",
                "export interface Port { open(): void }\nexport function start(p: Port) {}\n",
                "start",
            ),
            (
                "tsx",
                "export function View(): JSX.Element { return <div/>; }\n",
                "View",
            ),
            (
                "c",
                "struct node { int v; };\nint walk(struct node *n) { return 0; }\n",
                "walk",
            ),
            (
                "cpp",
                "class Engine { public: void start(); };\nvoid Engine::start() {}\n",
                "Engine",
            ),
            ("c_sharp", "namespace N { class Service { void Run() {} } }\n", "Run"),
            ("go", "package main\n\nfunc Serve() {}\n", "Serve"),
            ("rust", "struct Pool;\nfn acquire() {}\n", "acquire"),
        ];
        for (language, source, expected) in cases {
            let definitions = names(language, source, Kind::Def);
            assert!(
                definitions.iter().any(|(_, name)| name == expected),
                "{language}: {definitions:?}"
            );
        }
    }

    #[test]
    fn crlf_and_non_ascii_sources_keep_line_numbers() {
        let source = "class Zażółć {\r\n    void gęślą() {}\r\n}\r\n";
        assert_eq!(
            names("java", source, Kind::Def),
            vec![(1, "Zażółć".to_string()), (2, "gęślą".to_string())]
        );
    }

    #[test]
    fn broken_source_is_flagged_and_still_tagged() {
        let mut extractor = Extractor::new();
        let Ok(tags) = extractor.extract("java", "Broken.java", b"class Ok { void fine() {} }\nclass {{{ \n") else {
            panic!("extraction failed");
        };
        assert!(tags.has_syntax_errors);
        assert!(tags.tags.iter().any(|tag| tag.name == "fine"));
    }

    #[test]
    fn per_file_tag_limit_stops_the_run() {
        let mut source = String::from("class Big {\n");
        for index in 0..=policy::MAX_TAGS_PER_FILE {
            source.push_str(&format!("void m{index}() {{}}\n"));
        }
        source.push_str("}\n");
        let mut extractor = Extractor::new();
        assert!(matches!(
            extractor.extract("java", "Big.java", source.as_bytes()),
            Err(ExtractError::Limit(_))
        ));
    }
}
