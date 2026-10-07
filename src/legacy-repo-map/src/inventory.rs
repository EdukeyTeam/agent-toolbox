//! Bounded, read-only file selection. Mirrors `scan_repository` and
//! `read_safe_text` in `scripts/repo_files.py`, reading every file once.

use std::collections::HashSet;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::rc::Rc;

use ignore::gitignore::{Gitignore, GitignoreBuilder};
use sha2::{Digest, Sha256};

use crate::policy;

#[cfg(windows)]
const NULL_DEVICE: &str = "NUL";
#[cfg(not(windows))]
const NULL_DEVICE: &str = "/dev/null";

pub struct FileEntry {
    pub path: String,
    pub sha256: String,
    pub size: u64,
    pub language: Option<&'static str>,
    pub kind: &'static str,
}

pub struct Skip {
    pub path: String,
    pub reason: String,
}

pub struct Inventory {
    pub git: bool,
    pub revision: Option<String>,
    pub dirty: Option<bool>,
    pub git_notes: Vec<String>,
    pub source_notes: Vec<String>,
    pub fingerprint: String,
    pub files: Vec<FileEntry>,
    pub skipped: Vec<Skip>,
    pub candidates_seen: usize,
}

pub struct ScanOptions<'a> {
    pub subtrees: &'a [String],
    pub excludes: &'a [String],
    pub max_files: usize,
    pub max_file_bytes: u64,
}

pub fn sha256_hex(data: &[u8]) -> String {
    let digest = Sha256::digest(data);
    let mut text = String::with_capacity(64);
    for byte in digest {
        text.push_str(&format!("{byte:02x}"));
    }
    text
}

fn git_command(root: &Path) -> Command {
    let mut command = Command::new("git");
    // Inherited GIT_* variables could point git at another repository or
    // inject configuration; none of them is passed on.
    for (name, _) in std::env::vars_os() {
        if name.to_string_lossy().to_uppercase().starts_with("GIT_") {
            command.env_remove(name);
        }
    }
    command
        .arg("-c")
        .arg("core.fsmonitor=false")
        .arg("-c")
        .arg(format!("core.hooksPath={NULL_DEVICE}"))
        .arg("-C")
        .arg(root)
        .env("GIT_CONFIG_GLOBAL", NULL_DEVICE)
        .env("GIT_CONFIG_SYSTEM", NULL_DEVICE)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_OPTIONAL_LOCKS", "0")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_LITERAL_PATHSPECS", "1")
        .stdin(Stdio::null())
        .stderr(Stdio::null());
    command
}

/// Run a read-only git query; `None` when git is missing or the query fails.
fn git_output(root: &Path, args: &[&str]) -> Option<Vec<u8>> {
    let output = git_command(root).args(args).stdout(Stdio::piped()).output().ok()?;
    output.status.success().then_some(output.stdout)
}

fn git_text(root: &Path, args: &[&str]) -> Option<String> {
    git_output(root, args).map(|bytes| String::from_utf8_lossy(&bytes).trim().to_string())
}

struct GitState {
    git: bool,
    revision: Option<String>,
    dirty: Option<bool>,
    /// Notes shared word for word with the Python tool's inventory.
    git_notes: Vec<String>,
    /// Further observations that only this implementation reports.
    source_notes: Vec<String>,
}

fn git_state(root: &Path) -> Result<GitState, String> {
    let mut git_notes = Vec::new();
    let mut source_notes = Vec::new();
    // An ordinary module inherits the enclosing work tree's ignore and HEAD.
    let toplevel = git_text(root, &["rev-parse", "--show-toplevel"]).filter(|text| !text.is_empty());
    let enclosing = toplevel.as_deref().and_then(|path| fs::canonicalize(path).ok());
    let inside = enclosing.as_ref().is_some_and(|path| root.starts_with(path));
    let ignored_root = if inside && enclosing.as_deref() != Some(root) {
        // check-ignore accepts filenames rather than Git pathspecs.
        let status = git_command(root)
            .env_remove("GIT_LITERAL_PATHSPECS")
            .args(["check-ignore", "-q", "."])
            .stdout(Stdio::null())
            .status()
            .map_err(|_| "cannot safely inspect enclosing Git ignore policy".to_string())?;
        match status.code() {
            Some(0) => true,
            Some(1) => false,
            _ => return Err("cannot safely inspect enclosing Git ignore policy".to_string()),
        }
    } else {
        false
    };
    if !inside || ignored_root {
        if ignored_root {
            source_notes.push(
                "the supplied source directory is ignored by its enclosing git work tree; files were selected by directory walk"
                    .to_string(),
            );
        } else if root.join(".git").exists() {
            source_notes.push(
                "a .git entry exists but git is missing or did not accept this directory as a work tree; files were selected by directory walk"
                    .to_string(),
            );
        }
        return Ok(GitState {
            git: false,
            revision: None,
            dirty: None,
            git_notes,
            source_notes,
        });
    }
    let revision = git_text(root, &["rev-parse", "--verify", "HEAD"]).filter(|text| !text.is_empty());
    if revision.is_none() {
        source_notes.push("HEAD does not resolve to a commit; revision is null".to_string());
    }
    // `git status` can run clean/process filter commands named in repository
    // configuration. Reading configuration executes nothing, so check first:
    // exit status 0 means a filter is configured, 1 means none.
    let filters = git_command(root)
        .args([
            "config",
            "--name-only",
            "--get-regexp",
            r"^filter\..*\.(clean|process)$",
        ])
        .stdout(Stdio::null())
        .status()
        .ok()
        .and_then(|status| status.code());
    let mut dirty = None;
    match filters {
        Some(1) => {
            let arguments = [
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=all",
                "--",
                ".",
            ];
            match git_output(root, &arguments) {
                Some(bytes) => dirty = Some(!bytes.is_empty()),
                None => git_notes.push("dirty state unavailable: git status failed".to_string()),
            }
        }
        Some(0) => git_notes
            .push("dirty state not checked: Git clean/process filters can execute repository commands".to_string()),
        _ => git_notes.push("dirty state unavailable: cannot safely inspect Git filter configuration".to_string()),
    }
    Ok(GitState {
        git: true,
        revision,
        dirty,
        git_notes,
        source_notes,
    })
}

/// `strerror`-style text, matching the reason strings of the Python tool.
fn os_reason(error: &std::io::Error) -> String {
    let text = error.to_string();
    let message = match text.find(" (os error ") {
        Some(index) => text[..index].to_string(),
        None => text,
    };
    format!("cannot read file: {message}")
}

#[cfg(unix)]
fn open_regular(path: &Path) -> std::io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
}

#[cfg(not(unix))]
fn open_regular(path: &Path) -> std::io::Result<File> {
    File::open(path)
}

/// Read one repository file under the safety policy. Returns the reason
/// string used in `skipped` when the file must not be read.
pub fn read_safe(root: &Path, relative: &str, max_file_bytes: u64) -> Result<(Vec<u8>, String), String> {
    let relative = policy::safe_relative(relative)?;
    if policy::is_secret(&relative) {
        return Err("secret-looking file".to_string());
    }
    let mut path = root.to_path_buf();
    let mut last = None;
    for part in relative.split('/') {
        path.push(part);
        match fs::symlink_metadata(&path) {
            Ok(metadata) if metadata.file_type().is_symlink() => return Err("symlink excluded".to_string()),
            Ok(metadata) => last = Some(metadata),
            Err(_) => return Err("missing or outside source".to_string()),
        }
    }
    let metadata = last.ok_or_else(|| "missing or outside source".to_string())?;
    if !metadata.is_file() {
        return Err("missing or outside source".to_string());
    }
    match fs::canonicalize(&path) {
        Ok(resolved) if resolved.starts_with(root) => {}
        Ok(_) => return Err("missing or outside source".to_string()),
        Err(error) => return Err(os_reason(&error)),
    }
    if metadata.len() > max_file_bytes {
        return Err("file exceeds max_file_bytes".to_string());
    }
    let file = open_regular(&path).map_err(|error| {
        if fs::symlink_metadata(&path).is_ok_and(|current| current.file_type().is_symlink()) {
            "symlink excluded".to_string()
        } else {
            os_reason(&error)
        }
    })?;
    let opened = file.metadata().map_err(|error| os_reason(&error))?;
    if !opened.is_file() {
        return Err("missing or outside source".to_string());
    }
    let mut data = Vec::with_capacity(opened.len().min(max_file_bytes) as usize + 1);
    file.take(max_file_bytes + 1)
        .read_to_end(&mut data)
        .map_err(|error| os_reason(&error))?;
    if data.len() as u64 > max_file_bytes {
        return Err("file exceeds max_file_bytes".to_string());
    }
    if data.contains(&0) {
        return Err("binary file".to_string());
    }
    if std::str::from_utf8(&data).is_err() {
        return Err("non-UTF-8 file".to_string());
    }
    let digest = sha256_hex(&data);
    Ok((data, digest))
}

/// C0/C1 controls and Unicode line separators could forge lines in the map and
/// in terminal output; `contains_control_characters` in `repo_files.py`.
fn has_control_character(path: &str) -> bool {
    path.chars()
        .any(|character| character.is_control() || matches!(character, '\u{2028}' | '\u{2029}'))
}

/// Path as the content of a JSON string, as `safe_path_display` in
/// `repo_files.py`: control characters, quotes and backslashes are escaped,
/// other Unicode text is kept, and a JSON parser restores the original.
pub fn safe_path_display(path: &str) -> String {
    let quoted = serde_json::to_string(path).unwrap_or_default();
    let content = quoted
        .strip_prefix('"')
        .and_then(|text| text.strip_suffix('"'))
        .unwrap_or(&quoted);
    // JSON leaves DEL, C1 controls and separators raw; display them safely.
    content.chars().fold(String::new(), |mut shown, character| {
        if matches!(character, '\u{7f}'..='\u{9f}' | '\u{2028}' | '\u{2029}') {
            shown.push_str(&format!("\\u{:04x}", character as u32));
        } else {
            shown.push(character);
        }
        shown
    })
}

fn in_subtrees(relative: &str, subtrees: &[String]) -> bool {
    subtrees.is_empty()
        || subtrees.iter().any(|subtree| {
            relative == subtree
                || relative
                    .strip_prefix(subtree.as_str())
                    .is_some_and(|rest| rest.starts_with('/'))
        })
}

/// Candidate paths in the order the Python tool visits them.
enum Candidate {
    Path(String),
    Unusable { display: String, reason: &'static str },
}

struct GitCandidates {
    child: Child,
    reader: BufReader<std::process::ChildStdout>,
    seen: HashSet<String>,
    failed: bool,
}

impl GitCandidates {
    fn start(root: &Path, subtrees: &[String]) -> Result<Self, String> {
        let mut command = git_command(root);
        command.args(["ls-files", "-z", "--cached", "--others", "--exclude-standard"]);
        if !subtrees.is_empty() {
            command.arg("--").args(subtrees);
        }
        let mut child = command
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|error| format!("cannot run git ls-files: {error}"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "cannot read git ls-files output".to_string())?;
        Ok(Self {
            child,
            reader: BufReader::new(stdout),
            seen: HashSet::new(),
            failed: false,
        })
    }

    fn next(&mut self) -> Option<Candidate> {
        loop {
            let mut raw = Vec::new();
            match self.reader.read_until(0, &mut raw) {
                Ok(0) => return None,
                Ok(_) => {}
                Err(_) => {
                    self.failed = true;
                    return None;
                }
            }
            if raw.last() == Some(&0) {
                raw.pop();
            }
            if raw.is_empty() {
                continue;
            }
            match String::from_utf8(raw) {
                Ok(name) => {
                    let name = if cfg!(windows) { name.replace('\\', "/") } else { name };
                    // Unmerged index entries are listed once per stage.
                    if self.seen.insert(name.clone()) {
                        return Some(Candidate::Path(name));
                    }
                }
                Err(error) => {
                    return Some(Candidate::Unusable {
                        display: String::from_utf8_lossy(error.as_bytes()).into_owned(),
                        reason: "non-UTF-8 path",
                    })
                }
            }
        }
    }

    /// Stop the listing; `completed` says whether all output was consumed.
    fn finish(mut self, completed: bool) -> Result<(), String> {
        if !completed {
            let _ = self.child.kill();
            let _ = self.child.wait();
            return Ok(());
        }
        let status = self
            .child
            .wait()
            .map_err(|error| format!("git ls-files failed: {error}"))?;
        if self.failed || !status.success() {
            return Err("git ls-files failed".to_string());
        }
        Ok(())
    }
}

/// One directory-level `.gitignore`, kept with its ancestors.
struct IgnoreChain {
    matcher: Option<Gitignore>,
    parent: Option<Rc<IgnoreChain>>,
}

impl IgnoreChain {
    fn load(
        directory: &Path,
        parent: Option<Rc<IgnoreChain>>,
        total_bytes: &mut u64,
    ) -> Result<Rc<IgnoreChain>, String> {
        let matcher = if let Some(text) = read_gitignore(directory, total_bytes)? {
            let mut builder = GitignoreBuilder::new(directory);
            for line in text.lines() {
                let _ = builder.add_line(None, line);
            }
            Some(
                builder
                    .build()
                    .map_err(|error| format!("cannot parse .gitignore: {error}"))?,
            )
        } else {
            None
        };
        Ok(Rc::new(IgnoreChain { matcher, parent }))
    }

    /// The nearest `.gitignore` with an opinion decides, as in git.
    fn ignored(&self, path: &Path, is_dir: bool) -> bool {
        let mut current = Some(self);
        while let Some(chain) = current {
            if let Some(matcher) = &chain.matcher {
                let decision = matcher.matched(path, is_dir);
                if decision.is_ignore() {
                    return true;
                }
                if decision.is_whitelist() {
                    return false;
                }
            }
            current = chain.parent.as_deref();
        }
        false
    }
}

/// Read `.gitignore` text without following a link or reading a huge file.
fn read_gitignore(directory: &Path, total_bytes: &mut u64) -> Result<Option<String>, String> {
    let path = directory.join(".gitignore");
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("cannot inspect .gitignore: {error}")),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Ok(None);
    }
    if metadata.len() > policy::MAX_GITIGNORE_BYTES {
        return Err(format!(
            "ignore file exceeds {} bytes; select a smaller source tree",
            policy::MAX_GITIGNORE_BYTES
        ));
    }
    let mut data = Vec::new();
    open_regular(&path)
        .map_err(|error| format!("cannot read .gitignore: {error}"))?
        .take(policy::MAX_GITIGNORE_BYTES + 1)
        .read_to_end(&mut data)
        .map_err(|error| format!("cannot read .gitignore: {error}"))?;
    if data.len() as u64 > policy::MAX_GITIGNORE_BYTES {
        return Err(format!(
            "ignore file exceeds {} bytes; select a smaller source tree",
            policy::MAX_GITIGNORE_BYTES
        ));
    }
    *total_bytes += data.len() as u64;
    if *total_bytes > policy::MAX_IGNORE_TOTAL_BYTES {
        return Err(format!(
            "ignore-file byte limit exceeded ({}); select a smaller source tree",
            policy::MAX_IGNORE_TOTAL_BYTES
        ));
    }
    String::from_utf8(data)
        .map(Some)
        .map_err(|_| "cannot read .gitignore: non-UTF-8 file".to_string())
}

/// Pre-order directory walk for non-git sources: a directory's files in
/// name order, then its subdirectories in name order. Links are not followed.
struct WalkCandidates {
    pending: Vec<WalkStep>,
    subtrees: Vec<String>,
    visited: usize,
    ignore_bytes: u64,
}

enum WalkStep {
    Directory(PathBuf, String, Option<Rc<IgnoreChain>>),
    Candidate(Candidate),
}

impl WalkCandidates {
    fn start(root: &Path, subtrees: &[String]) -> Self {
        Self {
            pending: vec![WalkStep::Directory(root.to_path_buf(), String::new(), None)],
            subtrees: subtrees.to_vec(),
            visited: 0,
            ignore_bytes: 0,
        }
    }

    fn selected(&self, relative: &str) -> bool {
        self.subtrees.is_empty()
            || self.subtrees.iter().any(|scope| {
                relative == scope
                    || relative.starts_with(&format!("{scope}/"))
                    || scope.starts_with(&format!("{relative}/"))
            })
    }

    fn next(&mut self) -> Result<Option<Candidate>, String> {
        loop {
            let Some(step) = self.pending.pop() else {
                return Ok(None);
            };
            let (directory, prefix, parent_chain) = match step {
                WalkStep::Candidate(candidate) => return Ok(Some(candidate)),
                WalkStep::Directory(directory, prefix, parent_chain) => (directory, prefix, parent_chain),
            };
            let chain = IgnoreChain::load(&directory, parent_chain, &mut self.ignore_bytes).map_err(|message| {
                format!(
                    "cannot inventory directory {}: {message}",
                    if prefix.is_empty() { "." } else { &prefix }
                )
            })?;
            let entries = fs::read_dir(&directory).map_err(|error| {
                format!(
                    "cannot read directory {}: {error}",
                    if prefix.is_empty() { "." } else { &prefix }
                )
            })?;
            let mut entries_by_name = Vec::new();
            for entry in entries {
                self.visited += 1;
                if self.visited > policy::MAX_DISCOVERY_ENTRIES {
                    return Err(format!(
                        "filesystem discovery entry limit exceeded ({}); select a smaller source tree",
                        policy::MAX_DISCOVERY_ENTRIES
                    ));
                }
                let entry = entry.map_err(|error| {
                    format!(
                        "cannot enumerate directory {}: {error}",
                        if prefix.is_empty() { "." } else { &prefix }
                    )
                })?;
                let file_type = entry.file_type().map_err(|error| {
                    format!(
                        "cannot inspect directory entry in {}: {error}",
                        if prefix.is_empty() { "." } else { &prefix }
                    )
                })?;
                let name = match entry.file_name().into_string() {
                    Ok(name) => name,
                    Err(raw) => {
                        entries_by_name.push((
                            raw.to_string_lossy().into_owned(),
                            WalkStep::Candidate(Candidate::Unusable {
                                display: format!("{prefix}{}", raw.to_string_lossy()),
                                reason: "non-UTF-8 path",
                            }),
                        ));
                        continue;
                    }
                };
                let relative = format!("{prefix}{name}");
                if !self.selected(&relative) {
                    continue;
                }
                if file_type.is_dir() {
                    if !policy::IGNORED_DIRS.contains(&name.as_str()) && !policy::is_secret(&relative) {
                        let absolute = directory.join(&name);
                        if !chain.ignored(&absolute, true) {
                            entries_by_name.push((
                                name.clone(),
                                WalkStep::Directory(absolute, format!("{prefix}{name}/"), Some(Rc::clone(&chain))),
                            ));
                        }
                    }
                } else {
                    let absolute = directory.join(&name);
                    if !chain.ignored(&absolute, false) {
                        entries_by_name.push((
                            name.clone(),
                            WalkStep::Candidate(Candidate::Path(format!("{prefix}{name}"))),
                        ));
                    }
                }
            }
            entries_by_name.sort_by(|left, right| {
                let left_dir = matches!(left.1, WalkStep::Directory(..));
                let right_dir = matches!(right.1, WalkStep::Directory(..));
                left_dir.cmp(&right_dir).then(left.0.cmp(&right.0))
            });
            for (_, step) in entries_by_name.into_iter().rev() {
                self.pending.push(step);
            }
        }
    }
}

enum Candidates {
    Git(GitCandidates),
    Walk(WalkCandidates),
}

impl Candidates {
    fn next(&mut self) -> Result<Option<Candidate>, String> {
        match self {
            Candidates::Git(git) => Ok(git.next()),
            Candidates::Walk(walk) => walk.next(),
        }
    }
}

/// Select files and hand each readable one to `visit` together with the
/// bytes that were hashed, so later stages never read the source again.
pub fn scan<F>(root: &Path, options: &ScanOptions, mut visit: F) -> Result<Inventory, String>
where
    F: FnMut(&FileEntry, &[u8]),
{
    let state = git_state(root)?;
    let mut candidates = if state.git {
        Candidates::Git(GitCandidates::start(root, options.subtrees)?)
    } else {
        Candidates::Walk(WalkCandidates::start(root, options.subtrees))
    };
    let mut files = Vec::new();
    let mut skipped = Vec::new();
    let mut seen = 0usize;
    let mut completed = true;
    while let Some(candidate) = candidates.next()? {
        let display = match &candidate {
            Candidate::Path(relative) => relative,
            Candidate::Unusable { display, .. } => display,
        };
        if !in_subtrees(display, options.subtrees) {
            continue;
        }
        seen += 1;
        if seen > options.max_files {
            skipped.push(Skip {
                path: "*".to_string(),
                reason: format!("max_files exceeded ({}); map a subtree", options.max_files),
            });
            completed = false;
            break;
        }
        let relative = match candidate {
            Candidate::Path(relative) => relative,
            Candidate::Unusable { display, reason } => {
                skipped.push(Skip {
                    path: safe_path_display(&display),
                    reason: reason.to_string(),
                });
                continue;
            }
        };
        // Refused before any exclusion match or read, and never mapped.
        if has_control_character(&relative) {
            skipped.push(Skip {
                path: safe_path_display(&relative),
                reason: "control character in path".to_string(),
            });
            continue;
        }
        let name = policy::file_name(&relative);
        if options
            .excludes
            .iter()
            .any(|pattern| policy::fnmatch(&relative, pattern) || policy::fnmatch(name, pattern))
        {
            skipped.push(Skip {
                path: relative,
                reason: "explicit exclusion".to_string(),
            });
            continue;
        }
        let (data, sha256) = match read_safe(root, &relative, options.max_file_bytes) {
            Ok(read) => read,
            Err(reason) => {
                skipped.push(Skip { path: relative, reason });
                continue;
            }
        };
        let language = policy::language_for(&relative);
        let entry = FileEntry {
            kind: policy::kind_for(&relative, language),
            language,
            sha256,
            size: data.len() as u64,
            path: relative,
        };
        visit(&entry, &data);
        files.push(entry);
    }
    if let Candidates::Git(git) = candidates {
        git.finish(completed)?;
    }
    let mut hasher = Sha256::new();
    let mut first = true;
    let mut feed = |text: String| {
        if !first {
            hasher.update(b"\n");
        }
        first = false;
        hasher.update(text.as_bytes());
    };
    for entry in &files {
        feed(format!("{}\0{}", entry.path, entry.sha256));
    }
    for skip in &skipped {
        feed(format!("SKIP\0{}\0{}", skip.path, skip.reason));
    }
    let digest = hasher.finalize();
    let fingerprint = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    Ok(Inventory {
        git: state.git,
        revision: state.revision,
        dirty: state.dirty,
        git_notes: state.git_notes,
        source_notes: state.source_notes,
        fingerprint,
        files,
        skipped,
        candidates_seen: seen,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn control_characters_are_detected_like_the_python_tool() {
        for path in [
            "a\0b",
            "a\nb",
            "a\tb",
            "a\u{1f}b",
            "a\u{7f}b",
            "a\u{80}b",
            "a\u{9f}b",
            "a\u{2028}b",
            "a\u{2029}b",
            "dir\r/File.java",
        ] {
            assert!(has_control_character(path), "{path:?}");
        }
        // Ordinary spaces and Unicode letters remain valid.
        for path in ["a b", "a~b", "zażółć/Jaźń.java"] {
            assert!(!has_control_character(path), "{path:?}");
        }
    }

    #[test]
    fn path_display_is_escaped_and_reversible() {
        let cases = [
            ("src/Line\nBreak.java", r"src/Line\nBreak.java"),
            ("a\tb\rc\u{8}d\u{c}e", r"a\tb\rc\bd\fe"),
            ("nul\0esc\u{1b}[2Jus\u{1f}", r"nul\u0000esc\u001b[2Jus\u001f"),
            ("del\u{7f}ete", r"del\u007fete"),
            ("c1\u{80}nel\u{85}end\u{9f}", r"c1\u0080nel\u0085end\u009f"),
            ("line\u{2028}para\u{2029}", r"line\u2028para\u2029"),
            ("quote\"back\\slash", r#"quote\"back\\slash"#),
            ("zażółć gęślą/Jaźń \u{fffd}.java", "zażółć gęślą/Jaźń \u{fffd}.java"),
        ];
        for (path, expected) in cases {
            let shown = safe_path_display(path);
            assert_eq!(shown, expected);
            assert!(!has_control_character(&shown), "{shown:?}");
            let restored: String = serde_json::from_str(&format!("\"{shown}\"")).unwrap();
            assert_eq!(restored, path);
        }
    }

    #[test]
    fn walk_refuses_excess_discovery_and_oversized_ignore_files() {
        let source = tempfile::tempdir().unwrap();
        fs::write(source.path().join("one.java"), "class One {}\n").unwrap();
        let mut walk = WalkCandidates::start(source.path(), &[]);
        walk.visited = policy::MAX_DISCOVERY_ENTRIES;
        assert!(walk.next().err().unwrap().contains("filesystem discovery entry limit"));

        fs::write(
            source.path().join(".gitignore"),
            vec![b'x'; policy::MAX_GITIGNORE_BYTES as usize + 1],
        )
        .unwrap();
        let mut walk = WalkCandidates::start(source.path(), &[]);
        assert!(walk.next().err().unwrap().contains("ignore file exceeds"));
    }

    #[test]
    fn walk_prunes_unselected_directories_before_descent() {
        let source = tempfile::tempdir().unwrap();
        fs::create_dir(source.path().join("chosen")).unwrap();
        fs::create_dir(source.path().join("other")).unwrap();
        fs::write(source.path().join("chosen/one.java"), "class One {}\n").unwrap();
        fs::write(
            source.path().join("other/.gitignore"),
            vec![b'x'; policy::MAX_GITIGNORE_BYTES as usize + 1],
        )
        .unwrap();
        let mut walk = WalkCandidates::start(source.path(), &["chosen".to_string()]);
        assert!(matches!(walk.next().unwrap(), Some(Candidate::Path(path)) if path == "chosen/one.java"));
        assert!(walk.next().unwrap().is_none());
    }

    #[test]
    fn walk_refuses_aggregate_ignore_bytes() {
        let source = tempfile::tempdir().unwrap();
        let mut directory = source.path().to_path_buf();
        for depth in 0..8 {
            let mut comment = vec![b'x'; policy::MAX_GITIGNORE_BYTES as usize];
            comment[0] = b'#';
            fs::write(directory.join(".gitignore"), comment).unwrap();
            directory.push(format!("level-{depth}"));
            fs::create_dir(&directory).unwrap();
        }
        let mut walk = WalkCandidates::start(source.path(), &[]);
        let failure = loop {
            match walk.next() {
                Ok(Some(_)) => continue,
                Ok(None) => panic!("walk ended before exceeding the ignore-file limit"),
                Err(message) => break message,
            }
        };
        assert!(failure.contains("ignore-file byte limit exceeded"));
    }
}
