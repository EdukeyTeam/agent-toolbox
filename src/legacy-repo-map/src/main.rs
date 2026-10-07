//! Experimental native repository map for the legacy-codebase-workflows
//! skill. It follows the contract of the skill's `scripts/repo_map.py`:
//! same selection policy, tag queries, ranking and output files.

mod inventory;
mod policy;
mod rank;
mod tags;

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::process::ExitCode;
use std::time::Instant;

use serde_json::{json, Value};

use inventory::{FileEntry, ScanOptions};
use tags::{ExtractError, Extractor, Kind, Tag};

const TOOL: &str = "legacy-codebase-workflows legacy-repo-map";
const VERSION: &str = env!("CARGO_PKG_VERSION");
/// `VERSION` of the Python `repo_map.py` whose behavior this build mirrors.
const BASELINE_CONTRACT: &str = "repo_map.py 1.0.0";
const ESTIMATOR: &str = "ceil(Unicode characters / 4); a size estimate, not a model tokenizer";
const FINGERPRINT_SCOPE: &str =
    "selected readable files and skip reasons, from current bytes; ignored files and secret contents are excluded";
const RANKING: &str = "Aider-derived PageRank over identifier definitions and references; bare identifier text is matched, not a resolved call graph";
const HEADER: &str = "# Repository map\n\n";
const DIAGNOSTIC: &str =
    "# Repository inventory\n\nNo symbol map generated. Inspect inventory.json and choose a subtree.\n";
const EMPTY_MESSAGE: &str =
    "No supported definitions found in selected files. See inventory.json for descriptors, unsupported files and skips.\n";

/// Exact crate versions pinned in Cargo.toml; a test checks them against
/// Cargo.lock.
const DEPENDENCIES: &[(&str, &str)] = &[
    ("tree-sitter", "0.25.10"),
    ("tree-sitter-c", "0.24.2"),
    ("tree-sitter-c-sharp", "0.23.5"),
    ("tree-sitter-cpp", "0.23.4"),
    ("tree-sitter-go", "0.25.0"),
    ("tree-sitter-java", "0.23.5"),
    ("tree-sitter-javascript", "0.25.0"),
    ("tree-sitter-python", "0.25.0"),
    ("tree-sitter-rust", "0.24.2"),
    ("tree-sitter-typescript", "0.23.2"),
];

const USAGE: &str = "\
Usage: legacy-repo-map <repository> --output-dir <dir> [options]

Experimental native build of the legacy-codebase-workflows repository map.
The source directory is only read; all output goes to --output-dir, which
must be outside the source directory.

Options:
  --output-dir <dir>       artifact directory outside the source (required)
  --inventory-only         write the file inventory without parsing or ranking
  --budget <n>             estimated tokens, ceil(Unicode characters / 4),
                           64..1000000 (default 4096)
  --subtree <path>         relative module or subtree; repeatable
  --focus-file <path>      relative file to prioritize; repeatable
  --focus-symbol <name>    identifier to prioritize; repeatable
  --exclude <glob>         path or basename glob to exclude; repeatable
  --max-files <n>          maximum candidate files, 1..100000 (default 10000)
  --max-file-bytes <n>     maximum bytes per file, 1..20000000 (default 2000000)
  --timings                add phase timings to the summary on stdout
  --debug-tags             also write tags.debug.json (every definition and
                           reference tag) for comparing implementations
  --notices                print third-party notices and exit
  --print-policy           print the selection policy as JSON and exit
  --version                print the version and exit
  -h, --help               print this help and exit

Writes repo-map.md, inventory.json and map.meta.json. Use the map only when
map.meta.json reports status complete. No cache is kept.
";

const NOTICE_HEADER: &str = "\
legacy-repo-map: third-party notices

The ranking in this program is ported from an adaptation of Aider's
repository map (https://github.com/Aider-AI/aider, aider/repomap.py at
5dc9490bb35f9729ef2c95d00a19ccd30c26339c), licensed under the Apache License
2.0. The embedded tag queries are unmodified copies from that Aider revision
and derive from the tree-sitter grammar projects below, each under the MIT
license. The program links the tree-sitter runtime and grammar crates (MIT)
and other Rust crates whose license texts ship beside the binary in the
release artifact.
";

macro_rules! vendored {
    ($path:literal) => {
        include_str!(concat!("../../../skills/legacy-codebase-workflows/vendor/", $path))
    };
}

const NOTICES: &[(&str, &str)] = &[
    ("Aider (Apache License 2.0)", vendored!("LICENSE.txt")),
    (
        "Aider query credits: tree-sitter-language-pack",
        vendored!("queries/tree-sitter-language-pack/README.md"),
    ),
    (
        "Aider query credits: tree-sitter-languages",
        vendored!("queries/tree-sitter-languages/README.md"),
    ),
    ("tree-sitter (MIT)", include_str!("../licenses/tree-sitter-LICENSE.txt")),
    ("tree-sitter-c (MIT)", vendored!("licenses/c-LICENSE.txt")),
    ("tree-sitter-cpp (MIT)", vendored!("licenses/cpp-LICENSE.txt")),
    ("tree-sitter-c-sharp (MIT)", vendored!("licenses/csharp-LICENSE.txt")),
    ("tree-sitter-go (MIT)", vendored!("licenses/go-LICENSE.txt")),
    ("tree-sitter-java (MIT)", vendored!("licenses/java-LICENSE.txt")),
    (
        "tree-sitter-javascript (MIT)",
        vendored!("licenses/javascript-LICENSE.txt"),
    ),
    ("tree-sitter-python (MIT)", vendored!("licenses/python-LICENSE.txt")),
    ("tree-sitter-rust (MIT)", vendored!("licenses/rust-LICENSE.txt")),
    (
        "tree-sitter-typescript (MIT)",
        vendored!("licenses/typescript-LICENSE.txt"),
    ),
];

#[derive(Default)]
struct Arguments {
    repository: Option<String>,
    output_dir: Option<String>,
    budget: Option<usize>,
    subtrees: Vec<String>,
    focus_files: Vec<String>,
    focus_symbols: Vec<String>,
    excludes: Vec<String>,
    max_files: Option<usize>,
    max_file_bytes: Option<u64>,
    timings: bool,
    debug_tags: bool,
    inventory_only: bool,
}

enum Invocation {
    Run(Arguments),
    Print(String),
}

fn parse_arguments(raw: Vec<String>) -> Result<Invocation, String> {
    let mut arguments = Arguments::default();
    let mut iterator = raw.into_iter();
    let mut positional_only = false;
    while let Some(argument) = iterator.next() {
        if positional_only || !argument.starts_with('-') || argument == "-" {
            if arguments.repository.replace(argument).is_some() {
                return Err("exactly one repository path is expected".to_string());
            }
            continue;
        }
        let (name, inline) = match argument.split_once('=') {
            Some((name, value)) if name.starts_with("--") => (name.to_string(), Some(value.to_string())),
            _ => (argument.clone(), None),
        };
        let mut value = |name: &str| -> Result<String, String> {
            inline
                .clone()
                .or_else(|| iterator.next())
                .ok_or_else(|| format!("{name} needs a value"))
        };
        fn number<T: std::str::FromStr>(name: &str, text: String) -> Result<T, String> {
            text.parse()
                .map_err(|_| format!("{name} needs a whole number, got {text:?}"))
        }
        match name.as_str() {
            "--" => positional_only = true,
            "-h" | "--help" => return Ok(Invocation::Print(USAGE.to_string())),
            "--version" => return Ok(Invocation::Print(format!("legacy-repo-map {VERSION} (experimental)\n"))),
            "--notices" => return Ok(Invocation::Print(notices())),
            "--print-policy" => return Ok(Invocation::Print(format!("{}\n", policy_json()))),
            "--timings" => arguments.timings = true,
            "--inventory-only" => arguments.inventory_only = true,
            "--debug-tags" => arguments.debug_tags = true,
            "--output-dir" => arguments.output_dir = Some(value(&name)?),
            "--budget" => arguments.budget = Some(number(&name, value(&name)?)?),
            "--subtree" => arguments.subtrees.push(value(&name)?),
            "--focus-file" => arguments.focus_files.push(value(&name)?),
            "--focus-symbol" => arguments.focus_symbols.push(value(&name)?),
            "--exclude" => arguments.excludes.push(value(&name)?),
            "--max-files" => arguments.max_files = Some(number(&name, value(&name)?)?),
            "--max-file-bytes" => arguments.max_file_bytes = Some(number(&name, value(&name)?)?),
            _ => return Err(format!("unknown option {name}; see --help")),
        }
    }
    Ok(Invocation::Run(arguments))
}

fn notices() -> String {
    let mut text = String::from(NOTICE_HEADER);
    for (title, body) in NOTICES {
        text.push_str(&format!("\n==== {title} ====\n\n{}\n", body.trim_end()));
    }
    text
}

fn policy_json() -> String {
    let strings = |values: &[&str]| -> Value { values.iter().map(|value| json!(value)).collect() };
    let languages: BTreeMap<&str, &str> = policy::LANGUAGES.iter().copied().collect();
    let queries: BTreeMap<&str, Value> = tags::LANGUAGE_SPECS
        .iter()
        .map(|spec| {
            (
                spec.name,
                json!({"path": spec.query_path, "sha256": tags::query_sha256(spec)}),
            )
        })
        .collect();
    let value = json!({
        "languages": languages,
        "descriptor_suffixes": strings(policy::DESCRIPTOR_SUFFIXES),
        "descriptor_names": strings(policy::DESCRIPTOR_NAMES),
        "secret_names": strings(policy::SECRET_NAMES),
        "secret_part_prefixes": strings(policy::SECRET_PART_PREFIXES),
        "secret_dirs": strings(policy::SECRET_DIRS),
        "secret_suffixes": strings(policy::SECRET_SUFFIXES),
        "secret_name_pattern": policy::secret_name_pattern(),
        "ignored_dirs": strings(policy::IGNORED_DIRS),
        "queries": queries,
        "limits": {
            "default_max_files": policy::DEFAULT_MAX_FILES,
            "default_max_file_bytes": policy::DEFAULT_MAX_FILE_BYTES,
            "hard_max_files": policy::HARD_MAX_FILES,
            "hard_max_file_bytes": policy::HARD_MAX_FILE_BYTES,
            "max_tags_per_file": policy::MAX_TAGS_PER_FILE,
            "max_total_tags": policy::MAX_TOTAL_TAGS,
            "max_edges": policy::MAX_EDGES,
            "min_budget": policy::MIN_BUDGET,
            "max_budget": policy::MAX_BUDGET,
            "default_budget": policy::DEFAULT_BUDGET,
        },
        "baseline_contract": BASELINE_CONTRACT,
        "dependencies": DEPENDENCIES.iter().copied().collect::<BTreeMap<_, _>>(),
    });
    pretty(&value)
}

fn pretty(value: &Value) -> String {
    serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".to_string())
}

/// Path text without the Windows verbatim prefix.
fn display(path: &Path) -> String {
    let text = path.to_string_lossy();
    text.strip_prefix(r"\\?\").unwrap_or(&text).to_string()
}

/// Resolve a path that may not exist yet: links in its existing part are
/// followed, the remainder is appended.
fn resolve_lenient(path: &Path) -> Result<PathBuf, String> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| format!("cannot read the working directory: {error}"))?
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                let resolved = fs::canonicalize(&normalized).unwrap_or_else(|_| normalized.clone());
                normalized = resolved.parent().map(Path::to_path_buf).unwrap_or(resolved);
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    let mut missing = Vec::new();
    let mut existing = normalized.as_path();
    loop {
        if let Ok(resolved) = fs::canonicalize(existing) {
            let mut result = resolved;
            for part in missing.iter().rev() {
                result.push(part);
            }
            return Ok(result);
        }
        match (existing.parent(), existing.file_name()) {
            (Some(parent), Some(name)) => {
                missing.push(name.to_os_string());
                existing = parent;
            }
            _ => return Ok(normalized),
        }
    }
}

/// Replace `name` in `directory` without writing through an existing link.
fn write_atomic(directory: &Path, name: &str, content: &str) -> Result<(), String> {
    let target = directory.join(name);
    let temporary = directory.join(format!(".{name}.{}.tmp", std::process::id()));
    let _ = fs::remove_file(&temporary);
    let failed = |error: std::io::Error| format!("cannot write {}: {error}", display(&target));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(failed)?;
    file.write_all(content.as_bytes()).map_err(failed)?;
    drop(file);
    fs::rename(&temporary, &target).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        failed(error)
    })
}

/// Python `str.strip()`: Unicode whitespace plus the ASCII separators
/// U+001C..U+001F.
fn python_strip(text: &str) -> &str {
    text.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// One map line's source text: stripped, bounded, and free of line
/// separators and other control characters that would break the map's
/// one-definition-per-line format (a form feed, a lone carriage return).
fn snippet(line: &str) -> String {
    let cleaned: String = line
        .chars()
        .map(|c| {
            if (c.is_control() && c != '\t') || matches!(c, '\u{2028}' | '\u{2029}') {
                ' '
            } else {
                c
            }
        })
        .collect();
    python_strip(&cleaned).chars().take(policy::MAX_SNIPPET_CHARS).collect()
}

struct ParsedFile {
    path: String,
    tags: Vec<Tag>,
    /// Definition line number to stripped, bounded source line.
    snippets: BTreeMap<usize, String>,
}

fn run(arguments: Arguments) -> Result<String, String> {
    let started = Instant::now();
    let repository = arguments
        .repository
        .ok_or("a repository path is required; see --help")?;
    let output_dir = arguments.output_dir.ok_or("--output-dir is required")?;
    let budget = arguments.budget.unwrap_or(policy::DEFAULT_BUDGET);
    let max_files = arguments.max_files.unwrap_or(policy::DEFAULT_MAX_FILES);
    let max_file_bytes = arguments.max_file_bytes.unwrap_or(policy::DEFAULT_MAX_FILE_BYTES);

    let root =
        fs::canonicalize(&repository).map_err(|error| format!("cannot open repository {repository:?}: {error}"))?;
    if !root.is_dir() {
        return Err("repository path is not a directory".to_string());
    }
    let mut output = resolve_lenient(Path::new(&output_dir))?;
    if output.starts_with(&root) {
        return Err("output directory must be outside the source repository".to_string());
    }
    if !(policy::MIN_BUDGET..=policy::MAX_BUDGET).contains(&budget) {
        return Err(format!(
            "budget must be {}..{} estimated tokens",
            policy::MIN_BUDGET,
            policy::MAX_BUDGET
        ));
    }
    if !(1..=policy::HARD_MAX_FILES).contains(&max_files)
        || !(1..=policy::HARD_MAX_FILE_BYTES).contains(&max_file_bytes)
    {
        return Err(format!(
            "limits must be 1..{} files and 1..{} bytes",
            policy::HARD_MAX_FILES,
            policy::HARD_MAX_FILE_BYTES
        ));
    }
    let relative_list = |values: &[String]| -> Result<Vec<String>, String> {
        values
            .iter()
            .map(|value| {
                policy::safe_relative(value).map_err(|_| format!("focus/subtree path must be relative: {value}"))
            })
            .collect()
    };
    let selected_subtrees = arguments.subtrees.clone();
    let subtrees: Vec<String> = relative_list(&arguments.subtrees)?
        .into_iter()
        .filter(|path| path != ".")
        .collect();
    let focus_files = relative_list(&arguments.focus_files)?;
    let focus_symbols = arguments.focus_symbols;
    let excludes = arguments.excludes;

    fs::create_dir_all(&output).map_err(|error| format!("cannot create output directory: {error}"))?;
    output = fs::canonicalize(&output).map_err(|error| format!("cannot open output directory: {error}"))?;
    if output.starts_with(&root) {
        return Err("output directory must be outside the source repository".to_string());
    }

    let selection = json!({
        "subtrees": selected_subtrees,
        "focus_files": focus_files,
        "focus_symbols": focus_symbols,
        "excludes": excludes,
    });
    // Metadata written before the map is complete; `status` tells readers
    // not to use repo-map.md from an unfinished or failed run.
    let partial = |status: &str, extra: Value| -> Value {
        let mut value = json!({
            "tool": TOOL,
            "implementation": "rust (experimental)",
            "version": VERSION,
            "baseline_contract": BASELINE_CONTRACT,
            "status": status,
            "source_root": display(&root),
            "selection": selection,
            "estimated_tokens": 0,
            "map_sha256": Value::Null,
        });
        if let (Some(target), Value::Object(fields)) = (value.as_object_mut(), extra) {
            target.extend(fields);
        }
        value
    };
    // Invalidate artifacts of an earlier run before reading any source.
    let _ = fs::remove_file(output.join("inventory.json"));
    write_atomic(&output, "repo-map.md", DIAGNOSTIC)?;
    write_atomic(
        &output,
        "map.meta.json",
        &format!("{}\n", pretty(&partial("in-progress", json!({})))),
    )?;

    let mut extractor = Extractor::new();
    let mut parsed: Vec<ParsedFile> = Vec::new();
    let mut parse_failures: Vec<Value> = Vec::new();
    let mut syntax_error_files: Vec<String> = Vec::new();
    let mut total_tags = 0usize;
    let mut parse_time = std::time::Duration::ZERO;
    // A safety limit stops parsing; selection continues so the inventory
    // that explains the failure is complete.
    let mut failure: Option<(&str, String)> = None;
    let inventory_only = arguments.inventory_only;
    let options = ScanOptions {
        subtrees: &subtrees,
        excludes: &excludes,
        max_files,
        max_file_bytes,
    };
    let inventory = inventory::scan(&root, &options, |entry: &FileEntry, data: &[u8]| {
        let Some(language) = entry.language else {
            return;
        };
        if inventory_only || failure.is_some() || tags::spec_for(language).is_none() {
            return;
        }
        let parse_started = Instant::now();
        let outcome = extractor.extract(language, &entry.path, data);
        parse_time += parse_started.elapsed();
        match outcome {
            Ok(file_tags) => {
                if file_tags.has_syntax_errors {
                    syntax_error_files.push(entry.path.clone());
                }
                total_tags += file_tags.tags.len();
                // Bytes were validated as UTF-8 when the file was read.
                let text = String::from_utf8_lossy(data);
                let lines: Vec<&str> = text.split('\n').collect();
                let snippets = file_tags
                    .tags
                    .iter()
                    .filter(|tag| tag.kind == Kind::Def)
                    .filter_map(|tag| {
                        let line = lines.get(tag.line - 1)?;
                        Some((tag.line, snippet(line)))
                    })
                    .collect();
                parsed.push(ParsedFile {
                    path: entry.path.clone(),
                    tags: file_tags.tags,
                    snippets,
                });
                if total_tags > policy::MAX_TOTAL_TAGS {
                    failure = Some((
                        "parsing",
                        format!("total tag limit exceeded ({}); map a subtree", policy::MAX_TOTAL_TAGS),
                    ));
                }
            }
            Err(ExtractError::File(reason)) => {
                parse_failures.push(json!({"path": entry.path, "reason": reason}));
            }
            Err(ExtractError::Limit(message)) => failure = Some(("parsing", message)),
        }
    });
    let inventory = match inventory {
        Ok(inventory) => inventory,
        Err(message) => {
            let failure = json!({"stage": "inventory", "message": message});
            write_atomic(
                &output,
                "map.meta.json",
                &format!(
                    "{}\n",
                    pretty(&partial(
                        "failed",
                        json!({
                            "failure": failure,
                        })
                    ))
                ),
            )?;
            write_atomic(
                &output,
                "inventory.json",
                &format!(
                    "{}\n",
                    pretty(&json!({
                        "root": display(&root), "status": "failed", "files": [], "failure": failure,
                    }))
                ),
            )?;
            return Err(message);
        }
    };
    let scan_elapsed = started.elapsed();

    let skipped: Vec<Value> = inventory
        .skipped
        .iter()
        .map(|skip| json!({"path": skip.path, "reason": skip.reason}))
        .collect();
    let limit_hit = inventory.skipped.iter().any(|skip| skip.path == "*");
    let inventory_json = json!({
        "root": display(&root),
        "git": inventory.git,
        "revision": inventory.revision,
        "dirty": inventory.dirty,
        "git_notes": inventory.git_notes,
        "fingerprint": inventory.fingerprint,
        "files": inventory.files.iter().map(|entry| json!({
            "path": entry.path,
            "sha256": entry.sha256,
            "size": entry.size,
            "language": entry.language,
            "kind": entry.kind,
        })).collect::<Vec<_>>(),
        "skipped": skipped,
        "totals": {
            "candidates_seen": inventory.candidates_seen,
            "selected_files": inventory.files.len(),
            "skipped_files": inventory.skipped.len(),
        },
    });
    write_atomic(&output, "inventory.json", &format!("{}\n", pretty(&inventory_json)))?;
    // Counts by language and by leading directory, for choosing a subtree.
    let mut languages: BTreeMap<&str, usize> = BTreeMap::new();
    let mut groups: BTreeMap<String, usize> = BTreeMap::new();
    for entry in &inventory.files {
        *languages.entry(entry.language.unwrap_or(entry.kind)).or_default() += 1;
        let parts: Vec<&str> = entry.path.split('/').collect();
        let group = match parts.len() {
            1 => "<root>".to_string(),
            2 => parts[0].to_string(),
            _ => parts[..2].join("/"),
        };
        *groups.entry(group).or_default() += 1;
    }
    let mut modules: Vec<(&String, &usize)> = groups.iter().collect();
    modules.sort_by(|left, right| right.1.cmp(left.1).then(left.0.cmp(right.0)));
    let inventory_summary = json!({
        "languages": languages,
        "modules": modules.iter().take(20).map(|(path, files)| json!({"path": path, "files": files})).collect::<Vec<_>>(),
        "modules_omitted": groups.len().saturating_sub(20),
    });
    let provenance = json!({
        "inventory_summary": inventory_summary,
        "git": inventory.git,
        "git_notes": inventory.git_notes,
        "source_notes": inventory.source_notes,
        "revision": inventory.revision,
        "dirty": inventory.dirty,
        "working_copy_fingerprint": inventory.fingerprint,
        "fingerprint_scope": FINGERPRINT_SCOPE,
        "skipped": skipped,
    });
    let summarize = |status: &str, coverage: &Value, estimated_tokens: usize, truncated: bool| -> Value {
        json!({
            "status": status,
            "map": display(&output.join("repo-map.md")),
            "metadata": display(&output.join("map.meta.json")),
            "coverage": coverage,
            "inventory_summary": inventory_summary,
            "estimated_tokens": estimated_tokens,
            "truncated": truncated,
        })
    };
    let unfinished = |status: &str, failure: Option<&(&str, String)>| -> Result<Value, String> {
        let coverage = json!({
            "candidates_seen": inventory.candidates_seen,
            "selected_files": inventory.files.len(),
            "parsed_files": Value::Null,
            "definitions_found": Value::Null,
        });
        let mut extra = provenance.clone();
        extra["coverage"] = coverage.clone();
        extra["truncated"] = json!(limit_hit);
        if let Some((stage, message)) = failure {
            extra["failure"] = json!({"stage": stage, "message": message});
        }
        write_atomic(
            &output,
            "map.meta.json",
            &format!("{}\n", pretty(&partial(status, extra))),
        )?;
        Ok(summarize(status, &coverage, 0, limit_hit))
    };
    if inventory_only {
        return Ok(format!("{}\n", unfinished("inventory-only", None)?));
    }
    if let Some(failed) = &failure {
        unfinished("failed", Some(failed))?;
        return Err(failed.1.clone());
    }

    let rank_started = Instant::now();
    parsed.sort_by(|left, right| left.path.cmp(&right.path));
    let rank_files: Vec<rank::RankFile> = parsed
        .iter()
        .map(|file| rank::RankFile {
            path: &file.path,
            tags: &file.tags,
        })
        .collect();
    let ranked = match rank::rank_definitions(&rank_files, &focus_files, &focus_symbols, policy::MAX_EDGES) {
        Ok(ranked) => ranked,
        Err(message) => {
            unfinished("failed", Some(&("ranking", message.clone())))?;
            return Err(message);
        }
    };
    let rank_elapsed = rank_started.elapsed();

    // One output line per source line: definitions sharing a line count as
    // included once that line is in the map.
    let mut map_text = String::from(HEADER);
    let mut remaining = (budget * 4).saturating_sub(HEADER.chars().count());
    let mut included = 0usize;
    let mut included_lines: std::collections::HashSet<(usize, usize)> = Default::default();
    let mut verified_sources = std::collections::HashSet::new();
    for definition in &ranked {
        if included_lines.contains(&(definition.file, definition.line)) {
            included += 1;
            continue;
        }
        let file = &parsed[definition.file];
        if verified_sources.insert(file.path.as_str()) {
            let expected = inventory
                .files
                .iter()
                .find(|entry| entry.path == file.path)
                .expect("parsed file has an inventory entry");
            let current = inventory::read_safe(&root, &file.path, max_file_bytes)
                .map_err(|reason| format!("source changed while rendering: {}: {reason}", file.path));
            let changed = match current {
                Ok((_, digest)) => digest != expected.sha256,
                Err(message) => {
                    unfinished("failed", Some(&("rendering", message.clone())))?;
                    return Err(message);
                }
            };
            if changed {
                let message = format!("source changed while rendering: {}", file.path);
                unfinished("failed", Some(&("rendering", message.clone())))?;
                return Err(message);
            }
        }
        let Some(snippet) = file.snippets.get(&definition.line) else {
            let message = format!("source line vanished while rendering: {}", file.path);
            unfinished("failed", Some(&("rendering", message.clone())))?;
            return Err(message);
        };
        let line = format!("{}:L{}: {}\n", file.path, definition.line, snippet);
        let length = line.chars().count();
        if length <= remaining {
            map_text.push_str(&line);
            remaining -= length;
            included += 1;
            included_lines.insert((definition.file, definition.line));
        }
    }
    if included == 0 && EMPTY_MESSAGE.chars().count() <= remaining {
        map_text.push_str(EMPTY_MESSAGE);
    }

    let files_with_definitions = {
        let mut files: Vec<usize> = ranked.iter().map(|definition| definition.file).collect();
        files.sort_unstable();
        files.dedup();
        files.len()
    };
    let truncated = included < ranked.len() || limit_hit;
    let defined: std::collections::HashSet<&str> = ranked.iter().map(|definition| definition.name).collect();
    let parsed_paths: std::collections::HashSet<&str> = parsed.iter().map(|file| file.path.as_str()).collect();
    let mut unsupported: Vec<&str> = inventory
        .files
        .iter()
        .filter(|entry| {
            entry.language.is_none()
                && entry.kind == "other"
                && !policy::suffix_lower(policy::file_name(&entry.path)).is_empty()
        })
        .map(|entry| entry.path.as_str())
        .collect();
    unsupported.sort_unstable();
    unsupported.dedup();
    let mut descriptors: Vec<&str> = inventory
        .files
        .iter()
        .filter(|entry| entry.kind == "descriptor")
        .map(|entry| entry.path.as_str())
        .collect();
    descriptors.sort_unstable();
    syntax_error_files.sort_unstable();
    let coverage = json!({
        "candidates_seen": inventory.candidates_seen,
        "selected_files": inventory.files.len(),
        "parsed_files": parsed.len(),
        "files_with_definitions": files_with_definitions,
        "definitions_found": ranked.len(),
        "definitions_in_map": included,
    });
    let estimated_tokens = map_text.chars().count().div_ceil(4);
    let queries: BTreeMap<&str, Value> = tags::LANGUAGE_SPECS
        .iter()
        .map(|spec| {
            (
                spec.name,
                json!({"path": spec.query_path, "sha256": tags::query_sha256(spec)}),
            )
        })
        .collect();
    let mut details = provenance.clone();
    let complete = json!({
        "focus_not_found": {
            "files_not_parsed": focus_files.iter().filter(|path| !parsed_paths.contains(path.as_str())).collect::<Vec<_>>(),
            "symbols_without_definitions": focus_symbols.iter().filter(|name| !defined.contains(name.as_str())).collect::<Vec<_>>(),
        },
        "limits": {
            "budget": budget,
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "max_tags_per_file": policy::MAX_TAGS_PER_FILE,
            "max_total_tags": policy::MAX_TOTAL_TAGS,
            "max_edges": policy::MAX_EDGES,
        },
        "coverage": coverage,
        "parse_failures": parse_failures,
        "syntax_error_files": syntax_error_files,
        "unsupported_languages": unsupported,
        "descriptors": descriptors,
        "truncated": truncated,
        "estimated_tokens": estimated_tokens,
        "estimator": ESTIMATOR,
        "map_sha256": inventory::sha256_hex(map_text.as_bytes()),
        "ranking": RANKING,
        "cache": "none; every run reads and parses the selected files",
        "dependencies": DEPENDENCIES.iter().copied().collect::<BTreeMap<_, _>>(),
        "queries": queries,
    });
    if let (Some(target), Value::Object(fields)) = (details.as_object_mut(), complete) {
        target.extend(fields);
    }
    let metadata = partial("complete", details);

    let write_started = Instant::now();
    if let Err(message) = write_atomic(&output, "repo-map.md", &map_text) {
        unfinished("failed", Some(&("publication", message.clone())))?;
        return Err(message);
    }

    if arguments.debug_tags {
        let tags: BTreeMap<&str, Vec<Value>> = parsed
            .iter()
            .map(|file| {
                let tags = file
                    .tags
                    .iter()
                    .map(|tag| json!({"line": tag.line, "kind": if tag.kind == Kind::Def { "def" } else { "ref" }, "name": tag.name}))
                    .collect();
                (file.path.as_str(), tags)
            })
            .collect();
        if let Err(message) = write_atomic(&output, "tags.debug.json", &format!("{}\n", pretty(&json!(tags)))) {
            unfinished("failed", Some(&("publication", message.clone())))?;
            return Err(message);
        }
    }
    if let Err(message) = write_atomic(&output, "map.meta.json", &format!("{}\n", pretty(&metadata))) {
        let _ = unfinished("failed", Some(&("publication", message.clone())));
        return Err(message);
    }

    let mut summary = summarize("complete", &coverage, estimated_tokens, truncated);
    if arguments.timings {
        let milliseconds = |duration: std::time::Duration| (duration.as_secs_f64() * 1_000_000.0).round() / 1000.0;
        summary["timings_ms"] = json!({
            "select_read_hash_parse": milliseconds(scan_elapsed),
            "parse_and_query_only": milliseconds(parse_time),
            "rank": milliseconds(rank_elapsed),
            "write": milliseconds(write_started.elapsed()),
            "total": milliseconds(started.elapsed()),
        });
    }
    Ok(format!("{summary}\n"))
}

fn main() -> ExitCode {
    let outcome = parse_arguments(std::env::args().skip(1).collect()).and_then(|invocation| match invocation {
        Invocation::Print(text) => Ok(text),
        Invocation::Run(arguments) => run(arguments),
    });
    match outcome {
        Ok(text) => {
            // A closed pipe is not an error worth a diagnostic.
            let _ = std::io::stdout().write_all(text.as_bytes());
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("legacy-repo-map: {message}");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reported_dependency_versions_match_the_lockfile() {
        let lock = include_str!("../Cargo.lock").replace("\r\n", "\n");
        for (name, version) in DEPENDENCIES {
            let entry = format!("name = \"{name}\"\nversion = \"{version}\"");
            assert!(lock.contains(&entry), "Cargo.lock does not pin {name} {version}");
        }
    }

    #[test]
    fn strip_matches_python() {
        assert_eq!(python_strip("\t  void run() {\r"), "void run() {");
        assert_eq!(python_strip("\u{1c}x\u{a0}"), "x");
        assert_eq!(python_strip("\u{feff}class A"), "\u{feff}class A");
    }

    #[test]
    fn snippets_stay_on_one_line() {
        assert_eq!(snippet("    void run() {\r"), "void run() {");
        assert_eq!(
            snippet("\u{c}int second(void) { return 2; }"),
            "int second(void) { return 2; }"
        );
        assert_eq!(
            snippet("class Old {\r    void legacy() {}\r}"),
            "class Old {     void legacy() {} }"
        );
        assert_eq!(snippet("a\tb\u{2028}c"), "a\tb c");
        assert_eq!(snippet(&"x".repeat(500)).chars().count(), policy::MAX_SNIPPET_CHARS);
    }

    #[test]
    fn option_parsing_accepts_both_value_forms() {
        let raw = [
            "repo",
            "--output-dir=out",
            "--subtree",
            "a",
            "--subtree=b",
            "--budget",
            "128",
        ];
        let Ok(Invocation::Run(arguments)) = parse_arguments(raw.iter().map(|s| s.to_string()).collect()) else {
            panic!("arguments were rejected");
        };
        assert_eq!(arguments.repository.as_deref(), Some("repo"));
        assert_eq!(arguments.output_dir.as_deref(), Some("out"));
        assert_eq!(arguments.subtrees, ["a", "b"]);
        assert_eq!(arguments.budget, Some(128));
        assert!(parse_arguments(vec!["a".into(), "b".into()]).is_err());
        assert!(parse_arguments(vec!["--budget".into(), "many".into()]).is_err());
        assert!(parse_arguments(vec!["--nope".into()]).is_err());
    }
}
