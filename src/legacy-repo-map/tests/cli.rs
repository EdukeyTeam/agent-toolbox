//! Behavioral tests that run the built `legacy-repo-map` binary on
//! throwaway repositories.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use serde_json::Value;
use sha2::{Digest, Sha256};
use tempfile::TempDir;

const BINARY: &str = env!("CARGO_BIN_EXE_legacy-repo-map");

const SERVICE: &str = "package app;\n\npublic class TransferService extends BaseService {\n    public void startTransfer() {\n        channel.openChannel();\n    }\n}\n";
const CHANNEL: &str =
    "package app;\n\npublic class Channel {\n    public void openChannel() {}\n\n    void rarelyUsedHelper() {}\n}\n";

struct Fixture {
    _directory: TempDir,
    source: PathBuf,
    output: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let directory = TempDir::new().unwrap();
        // Canonical paths keep comparisons stable where the temp dir is a link.
        let base = fs::canonicalize(directory.path()).unwrap();
        let source = base.join("source tree");
        fs::create_dir(&source).unwrap();
        Self {
            output: base.join("artifacts"),
            source,
            _directory: directory,
        }
    }

    fn java() -> Self {
        let fixture = Self::new();
        fixture.write("src/app/TransferService.java", SERVICE);
        fixture.write("src/app/Channel.java", CHANNEL);
        fixture
    }

    fn write(&self, relative: &str, content: &str) {
        self.write_bytes(relative, content.as_bytes());
    }

    fn write_bytes(&self, relative: &str, content: &[u8]) {
        let path = self.source.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, content).unwrap();
    }

    fn map(&self, extra: &[&str]) -> Output {
        let mut command = Command::new(BINARY);
        command
            .arg(&self.source)
            .arg("--output-dir")
            .arg(&self.output)
            .args(extra);
        command.stdin(Stdio::null()).output().unwrap()
    }

    fn map_ok(&self, extra: &[&str]) -> Value {
        let output = self.map(extra);
        assert!(
            output.status.success(),
            "exit {:?}: {}",
            output.status.code(),
            String::from_utf8_lossy(&output.stderr)
        );
        serde_json::from_slice(&output.stdout).unwrap()
    }

    fn map_text(&self) -> String {
        fs::read_to_string(self.output.join("repo-map.md")).unwrap()
    }

    fn json(&self, name: &str) -> Value {
        serde_json::from_slice(&fs::read(self.output.join(name)).unwrap()).unwrap()
    }

    fn artifacts(&self) -> String {
        ["repo-map.md", "inventory.json", "map.meta.json"]
            .iter()
            .map(|name| fs::read_to_string(self.output.join(name)).unwrap())
            .collect()
    }

    /// Commit named fixture files with a hermetic identity. False when git is absent.
    fn git_commit(&self) -> bool {
        if !self.git(&["init", "-q"]) {
            return false;
        }
        let mut paths = Vec::new();
        let mut directories = vec![self.source.clone()];
        while let Some(directory) = directories.pop() {
            for item in fs::read_dir(directory).unwrap() {
                let path = item.unwrap().path();
                if path.file_name().is_some_and(|name| name == ".git") {
                    continue;
                }
                if path.is_dir() {
                    directories.push(path);
                } else {
                    let relative = path.strip_prefix(&self.source).unwrap().to_string_lossy().into_owned();
                    if !self.git(&["check-ignore", "-q", "--", &relative]) {
                        paths.push(relative);
                    }
                }
            }
        }
        paths.sort();
        let mut add = vec!["add", "--"];
        add.extend(paths.iter().map(String::as_str));
        assert!(self.git(&add));
        assert!(self.git(&["commit", "-q", "-m", "fixture"]));
        true
    }

    fn git(&self, arguments: &[&str]) -> bool {
        let null = if cfg!(windows) { "NUL" } else { "/dev/null" };
        Command::new("git")
            .arg("-C")
            .arg(&self.source)
            .args(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"])
            .args(["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"])
            .args(arguments)
            .env("GIT_CONFIG_GLOBAL", null)
            .env("GIT_CONFIG_SYSTEM", null)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success())
    }
}

fn sha256(data: &[u8]) -> String {
    Sha256::digest(data).iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Every file under `root` with its content hash, links by their target.
fn snapshot(root: &Path) -> BTreeMap<String, String> {
    let mut result = BTreeMap::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let key = path.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            let key = if cfg!(windows) { key.replace('\\', "/") } else { key };
            let file_type = entry.file_type().unwrap();
            if file_type.is_symlink() {
                result.insert(key, format!("link:{}", fs::read_link(&path).unwrap().display()));
            } else if file_type.is_dir() {
                result.insert(format!("{key}/"), String::new());
                pending.push(path);
            } else {
                result.insert(key, sha256(&fs::read(&path).unwrap()));
            }
        }
    }
    result
}

fn paths(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["path"].as_str().unwrap().to_string())
        .collect()
}

fn skip_reason(inventory: &Value, path: &str) -> Option<String> {
    inventory["skipped"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["path"] == path)
        .map(|item| item["reason"].as_str().unwrap().to_string())
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn maps_definitions_with_original_paths_and_lines() {
    let fixture = Fixture::java();
    let summary = fixture.map_ok(&[]);
    let map = fixture.map_text();
    assert!(map.starts_with("# Repository map\n\n"));
    assert!(
        map.contains("src/app/Channel.java:L4: public void openChannel() {}\n"),
        "{map}"
    );
    assert!(map.contains("src/app/TransferService.java:L3: public class TransferService extends BaseService {\n"));
    assert_eq!(summary["coverage"]["definitions_found"], 5);
    assert_eq!(summary["coverage"]["definitions_in_map"], 5);
    assert_eq!(summary["truncated"], false);
    assert_eq!(summary["status"], "complete");
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["status"], "complete");
    assert_eq!(metadata["implementation"], "rust (experimental)");
    assert_eq!(metadata["git"], false);
    assert_eq!(metadata["revision"], Value::Null);
    assert_eq!(metadata["map_sha256"], sha256(map.as_bytes()));
    assert!(metadata["ranking"]
        .as_str()
        .unwrap()
        .contains("not a resolved call graph"));
    // The summary points at the files that were written.
    assert_eq!(
        fs::canonicalize(Path::new(summary["map"].as_str().unwrap())).unwrap(),
        fs::canonicalize(fixture.output.join("repo-map.md")).unwrap()
    );
}

#[cfg(unix)]
#[test]
fn literal_backslash_paths_keep_distinct_current_byte_identities() {
    let fixture = Fixture::new();
    let files = [
        ("a\\b.java", "class LiteralBackslash {}\n"),
        ("a/b.java", "class NestedIdentity {}\n"),
        ("..\\literal.java", "class LegitimateLiteral {}\n"),
    ];
    for (path, contents) in files {
        fixture.write(path, contents);
    }
    for state in 0..3 {
        if state == 1 && !fixture.git(&["init", "-q"]) {
            return;
        }
        if state == 2 {
            assert!(fixture.git_commit());
        }
        let before = snapshot(&fixture.source);
        fixture.map_ok(&[]);
        let inventory = fixture.json("inventory.json");
        let entries = inventory["files"].as_array().unwrap();
        assert_eq!(entries.len(), files.len());
        for (path, contents) in files {
            let entry = entries.iter().find(|entry| entry["path"] == path).unwrap();
            assert_eq!(entry["sha256"], sha256(contents.as_bytes()), "{path}");
            assert!(fixture.map_text().contains(&format!("{path}:L1: {}", contents.trim())));
        }
        fixture.map_ok(&["--subtree", "a", "--focus-file", "a\\b.java"]);
        let inventory = fixture.json("inventory.json");
        assert_eq!(inventory["files"].as_array().unwrap().len(), 1);
        assert_eq!(inventory["files"][0]["path"], "a/b.java");
        assert_eq!(snapshot(&fixture.source), before, "source files changed");
    }
}

#[test]
fn source_snippet_controls_are_sanitized_without_changing_bytes_or_lines() {
    let fixture = Fixture::new();
    let controls: String = (1..32)
        .chain(127..160)
        .chain([0x2028, 0x2029])
        .filter(|value| *value != 10)
        .map(|value| char::from_u32(value).unwrap())
        .collect();
    let source = format!("class Hostile {{\tvoid run() {{}} }} // żółć{controls} marker\r\n\nclass After {{}}\n");
    fixture.write("Hostile.java", &source);
    let before = snapshot(&fixture.source);
    let meta = fixture.map_ok(&["--budget", "128"]);
    let text = fixture.map_text();
    assert!(text.contains("Hostile.java:L1: class Hostile {\tvoid run() {} } // żółć"));
    assert!(text.contains("Hostile.java:L3: class After {}"));
    assert!(!text
        .chars()
        .any(|c| (c.is_control() && c != '\t' && c != '\n') || matches!(c, '\u{2028}' | '\u{2029}')));
    assert!(meta["estimated_tokens"].as_u64().unwrap() <= 128);
    let inventory = fixture.json("inventory.json");
    assert_eq!(inventory["files"][0]["sha256"], sha256(source.as_bytes()));
    assert_eq!(snapshot(&fixture.source), before);
}

#[test]
fn inventory_hashes_are_the_current_bytes_and_the_fingerprint_tracks_content() {
    let fixture = Fixture::java();
    fixture.map_ok(&[]);
    let inventory = fixture.json("inventory.json");
    let files = inventory["files"].as_array().unwrap();
    assert_eq!(files.len(), 2);
    for file in files {
        let bytes = fs::read(fixture.source.join(file["path"].as_str().unwrap())).unwrap();
        assert_eq!(file["sha256"], sha256(&bytes));
        assert_eq!(file["size"], bytes.len());
        assert_eq!(file["language"], "java");
        assert_eq!(file["kind"], "source");
    }
    let first = inventory["fingerprint"].as_str().unwrap().to_string();
    assert_eq!(
        fixture.json("map.meta.json")["working_copy_fingerprint"],
        first.as_str()
    );

    // Same length, different bytes: a size or timestamp check would miss it.
    fixture.write("src/app/Channel.java", &CHANNEL.replace("openChannel", "shutChannel"));
    fixture.map_ok(&[]);
    let changed = fixture.json("inventory.json");
    assert_ne!(changed["fingerprint"], first.as_str());
    let map = fixture.map_text();
    assert!(
        map.contains("shutChannel") && !map.contains("public void openChannel"),
        "{map}"
    );

    fs::remove_file(fixture.source.join("src/app/Channel.java")).unwrap();
    fixture.map_ok(&[]);
    assert!(!fixture.map_text().contains("Channel.java"));
    assert_eq!(fixture.json("inventory.json")["files"].as_array().unwrap().len(), 1);
}

#[test]
fn repeated_runs_are_byte_identical_and_leave_the_source_untouched() {
    let fixture = Fixture::java();
    fixture.write("pom.xml", "<project/>\n");
    let before = snapshot(&fixture.source);
    fixture.map_ok(&["--budget", "64", "--focus-symbol", "openChannel"]);
    let first = fixture.artifacts();
    fixture.map_ok(&["--budget", "64", "--focus-symbol", "openChannel"]);
    assert_eq!(first, fixture.artifacts());
    assert_eq!(before, snapshot(&fixture.source));
    // No cache or temporary file is left beside the three artifacts.
    let mut written: Vec<String> = fs::read_dir(&fixture.output)
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .collect();
    written.sort();
    assert_eq!(written, ["inventory.json", "map.meta.json", "repo-map.md"]);
}

#[cfg(unix)]
#[test]
fn unmerged_non_utf8_paths_are_deduplicated_before_decoding() {
    use std::io::Write;
    let fixture = Fixture::new();
    fixture.write("z.java", "class LaterValid {}\n");
    assert!(fixture.git(&["init", "-q"]));
    assert!(fixture.git(&["add", "--", "z.java"]));
    let blob = Command::new("git")
        .arg("-C")
        .arg(&fixture.source)
        .args(["hash-object", "z.java"])
        .output()
        .unwrap();
    assert!(blob.status.success());
    let hash = String::from_utf8(blob.stdout).unwrap();
    let raw = b"a-\xff.java";
    let mut records = Vec::new();
    for stage in 1..=3 {
        records.extend_from_slice(format!("100644 {} {stage}\t", hash.trim()).as_bytes());
        records.extend_from_slice(raw);
        records.push(0);
    }
    let mut child = Command::new("git")
        .arg("-C")
        .arg(&fixture.source)
        .args(["update-index", "-z", "--index-info"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(&records).unwrap();
    let changed = child.wait_with_output().unwrap();
    assert!(changed.status.success(), "{}", String::from_utf8_lossy(&changed.stderr));
    let listed = Command::new("git")
        .arg("-C")
        .arg(&fixture.source)
        .args(["ls-files", "-z"])
        .output()
        .unwrap();
    assert!(listed.status.success());
    assert_eq!(
        listed
            .stdout
            .split(|byte| *byte == 0)
            .filter(|path| *path == raw)
            .count(),
        3
    );
    let before = snapshot(&fixture.source);
    for options in [vec![], vec!["--max-files", "2"]] {
        let meta = fixture.map_ok(&options);
        let inventory = fixture.json("inventory.json");
        assert_eq!(meta["coverage"]["candidates_seen"], 2);
        assert_eq!(meta["coverage"]["selected_files"], 1);
        assert_eq!(meta["truncated"], false);
        assert_eq!(
            inventory["skipped"],
            serde_json::json!([{"path": "a-\u{fffd}.java", "reason": "non-UTF-8 path"}])
        );
        assert!(fixture.map_text().contains("z.java:L1: class LaterValid {}"));
        assert_eq!(snapshot(&fixture.source), before);
    }
}

#[test]
fn optional_debug_tags_are_current_or_absent_on_every_run() {
    let fixture = Fixture::java();
    fixture.map_ok(&["--debug-tags"]);
    let debug = fixture.output.join("tags.debug.json");
    assert!(fs::read_to_string(&debug).unwrap().contains("openChannel"));
    fixture.write(
        "src/app/Channel.java",
        &CHANNEL.replace("openChannel", "updatedChannel"),
    );
    fixture.map_ok(&[]);
    assert!(!debug.exists());
    assert!(fixture.map_text().contains("updatedChannel"));
    fixture.map_ok(&["--debug-tags"]);
    let tags = fixture.json("tags.debug.json");
    let names: Vec<&str> = tags["src/app/Channel.java"]
        .as_array()
        .unwrap()
        .iter()
        .map(|tag| tag["name"].as_str().unwrap())
        .collect();
    assert!(names.contains(&"updatedChannel") && !names.contains(&"openChannel"));
    fixture.map_ok(&["--inventory-only"]);
    assert!(!debug.exists());
    fixture.map_ok(&["--debug-tags"]);
    assert!(fixture.git(&["init", "-q"]));
    fs::write(fixture.source.join(".git/index"), b"invalid fixture index").unwrap();
    let before = snapshot(&fixture.source);
    let failed = fixture.map(&[]);
    assert_eq!(failed.status.code(), Some(2));
    assert!(!debug.exists());
    assert_ne!(fixture.json("map.meta.json")["status"], "complete");
    assert_eq!(snapshot(&fixture.source), before);
}

#[test]
fn unremovable_old_debug_tags_prevent_complete_publication() {
    let fixture = Fixture::java();
    fixture.map_ok(&[]);
    fs::create_dir(fixture.output.join("tags.debug.json")).unwrap();
    let before = snapshot(&fixture.source);
    let failed = fixture.map(&[]);
    assert_eq!(failed.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&failed.stderr).contains("cannot invalidate old debug tags"));
    assert_ne!(fixture.json("map.meta.json")["status"], "complete");
    assert!(!fixture.map_text().contains("openChannel"));
    assert_eq!(snapshot(&fixture.source), before);
}

#[test]
fn budget_is_enforced_with_the_declared_estimator() {
    let fixture = Fixture::java();
    let summary = fixture.map_ok(&["--budget", "64"]);
    let map = fixture.map_text();
    let estimated = map.chars().count().div_ceil(4);
    assert!(estimated <= 64, "{estimated}");
    assert_eq!(summary["estimated_tokens"], estimated);
    assert_eq!(summary["truncated"], true);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["limits"]["budget"], 64);
    assert!(metadata["estimator"]
        .as_str()
        .unwrap()
        .starts_with("ceil(Unicode characters / 4)"));
    let coverage = &metadata["coverage"];
    assert!(coverage["definitions_in_map"].as_u64() < coverage["definitions_found"].as_u64());

    for bad in ["63", "1000001"] {
        let output = fixture.map(&["--budget", bad]);
        assert_eq!(output.status.code(), Some(2));
        assert!(String::from_utf8_lossy(&output.stderr).contains("budget must be 64..1000000"));
    }
}

#[test]
fn focus_keeps_requested_definitions_first_and_reports_absent_names() {
    let fixture = Fixture::java();
    fixture.map_ok(&["--focus-symbol", "rarelyUsedHelper"]);
    let map = fixture.map_text();
    assert_eq!(
        map.lines().nth(2).unwrap(),
        "src/app/Channel.java:L6: void rarelyUsedHelper() {}"
    );

    fixture.map_ok(&["--focus-file", "src/app/TransferService.java"]);
    let map = fixture.map_text();
    assert!(
        map.lines()
            .nth(2)
            .unwrap()
            .starts_with("src/app/TransferService.java:L"),
        "{map}"
    );

    // A symbol that does not exist is reported, never invented.
    fixture.map_ok(&[
        "--focus-symbol",
        "resumeBrokenUpload",
        "--focus-file",
        "src/app/Missing.java",
    ]);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(
        strings(&metadata["focus_not_found"]["symbols_without_definitions"]),
        ["resumeBrokenUpload"]
    );
    assert_eq!(
        strings(&metadata["focus_not_found"]["files_not_parsed"]),
        ["src/app/Missing.java"]
    );
    assert!(!fixture.map_text().contains("resumeBrokenUpload"));
    assert!(!fixture.map_text().contains("Missing.java"));
}

#[test]
fn secrets_binaries_and_oversized_files_are_listed_but_never_read() {
    let fixture = Fixture::java();
    fixture.write(".env", "API_TOKEN=do-not-leak-1\n");
    fixture.write("config/.env.production", "API_TOKEN=do-not-leak-2\n");
    fixture.write("deploy/id_rsa", "do-not-leak-3\n");
    fixture.write("certs/server.pem", "do-not-leak-4\n");
    fixture.write("ops/db-credentials.yaml", "password: do-not-leak-5\n");
    fixture.write("secrets/Vault.java", "class DoNotLeak6 {}\n");
    fixture.write_bytes("lib/tool.bin", b"\0\x01\x02 binary");
    fixture.write_bytes("docs/latin1.txt", b"caf\xe9\n");
    fixture.write(
        "src/app/Huge.java",
        &format!("class Huge {{}}\n// {}\n", "x".repeat(4096)),
    );
    fixture.map_ok(&["--max-file-bytes", "2048"]);
    let inventory = fixture.json("inventory.json");
    for path in [
        ".env",
        "config/.env.production",
        "deploy/id_rsa",
        "certs/server.pem",
        "ops/db-credentials.yaml",
    ] {
        assert_eq!(
            skip_reason(&inventory, path).as_deref(),
            Some("secret-looking file"),
            "{path}"
        );
    }
    // Secret directories are pruned before their entries become candidates.
    assert_eq!(skip_reason(&inventory, "secrets/Vault.java"), None);
    assert_eq!(skip_reason(&inventory, "lib/tool.bin").as_deref(), Some("binary file"));
    assert_eq!(
        skip_reason(&inventory, "docs/latin1.txt").as_deref(),
        Some("non-UTF-8 file")
    );
    assert_eq!(
        skip_reason(&inventory, "src/app/Huge.java").as_deref(),
        Some("file exceeds max_file_bytes")
    );
    let artifacts = fixture.artifacts();
    assert!(!artifacts.contains("do-not-leak") && !artifacts.contains("DoNotLeak6"));
    assert!(!artifacts.contains("class Huge"));
    assert_eq!(paths(&inventory["files"]).len(), 2);
}

#[cfg(unix)]
#[test]
fn links_are_not_followed_out_of_or_around_the_source() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::java();
    let outside = fixture.source.parent().unwrap().join("outside");
    fs::create_dir(&outside).unwrap();
    fs::write(outside.join("Outside.java"), "class EscapedOutside {}\n").unwrap();
    symlink(outside.join("Outside.java"), fixture.source.join("src/app/Linked.java")).unwrap();
    symlink(&outside, fixture.source.join("linked-dir")).unwrap();
    symlink("Channel.java", fixture.source.join("src/app/Alias.java")).unwrap();
    symlink("missing-target", fixture.source.join("src/app/Dangling.java")).unwrap();
    symlink("..", fixture.source.join("src/loop")).unwrap();
    fixture.map_ok(&[]);
    let inventory = fixture.json("inventory.json");
    for path in ["src/app/Linked.java", "src/app/Alias.java", "src/app/Dangling.java"] {
        assert_eq!(
            skip_reason(&inventory, path).as_deref(),
            Some("symlink excluded"),
            "{path}"
        );
    }
    let listed = paths(&inventory["files"]);
    assert_eq!(listed, ["src/app/Channel.java", "src/app/TransferService.java"]);
    assert!(!fixture.artifacts().contains("EscapedOutside"));
}

#[cfg(unix)]
#[test]
fn special_files_do_not_block_the_scan() {
    let fixture = Fixture::java();
    let pipe = fixture.source.join("src/app/pipe.java");
    let made = Command::new("mkfifo")
        .arg(&pipe)
        .status()
        .is_ok_and(|status| status.success());
    if !made {
        return;
    }
    fixture.map_ok(&[]);
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        skip_reason(&inventory, "src/app/pipe.java").as_deref(),
        Some("missing or outside source")
    );
}

/// Paths that would forge map lines or drive a terminal, with the escaped
/// text the inventory must show instead.
#[cfg(unix)]
const CONTROL_PATHS: &[(&str, &str)] = &[
    (
        "src/app/Line\nsrc/app/Forged.java:L1: class Forged {}\n.java",
        r"src/app/Line\nsrc/app/Forged.java:L1: class Forged {}\n.java",
    ),
    ("src/app/Tab\tStop.java", r"src/app/Tab\tStop.java"),
    ("src/app/Del\u{7f}ete.java", r"src/app/Del\u007fete.java"),
    ("src/app/Nel\u{85}line.java", r"src/app/Nel\u0085line.java"),
    ("src/app/Line\u{2028}break.java", r"src/app/Line\u2028break.java"),
    ("src/app/Para\u{2029}break.java", r"src/app/Para\u2029break.java"),
    ("src/new\rline dir/Inside.java", r"src/new\rline dir/Inside.java"),
    (
        "src/app/Esc\u{1b}[2J \"q\" b\\s ż.java",
        r#"src/app/Esc\u001b[2J \"q\" b\\s ż.java"#,
    ),
];

#[cfg(unix)]
fn assert_control_paths_are_skipped(fixture: &Fixture, git: bool) {
    let summary = fixture.map_ok(&[]);
    assert_eq!(summary["status"], "complete");
    assert_eq!(summary["truncated"], false);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["status"], "complete");
    assert_eq!(metadata["git"], git);
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        paths(&inventory["files"]),
        ["src/app/Channel.java", "src/app/TransferService.java"]
    );
    // Refused candidates still count, and nothing else was skipped.
    assert_eq!(inventory["totals"]["candidates_seen"], 2 + CONTROL_PATHS.len());
    assert_eq!(inventory["totals"]["skipped_files"], CONTROL_PATHS.len());
    assert_eq!(metadata["skipped"], inventory["skipped"]);
    for (raw, shown) in CONTROL_PATHS {
        assert_eq!(
            skip_reason(&inventory, shown).as_deref(),
            Some("control character in path"),
            "{shown}"
        );
        let restored: String = serde_json::from_str(&format!("\"{shown}\"")).unwrap();
        assert_eq!(&restored, raw);
    }
    // The safe files are mapped as usual; the refused ones were never read.
    let map = fixture.map_text();
    assert!(
        map.contains("src/app/Channel.java:L4: public void openChannel() {}\n"),
        "{map}"
    );
    assert!(map.contains("src/app/TransferService.java:L3: public class TransferService extends BaseService {\n"));
    assert_eq!(summary["coverage"]["definitions_found"], 5);
    assert!(!map.contains("Forged") && !map.contains("Hostile"), "{map}");
    let artifacts = fixture.artifacts();
    assert!(!artifacts.contains("Hostile"));
    let raw_control = artifacts
        .chars()
        .find(|character| character.is_control() && *character != '\n');
    assert_eq!(raw_control, None, "raw control character in an artifact");
    let stdout = String::from_utf8(fixture.map(&[]).stdout).unwrap();
    assert!(!stdout
        .chars()
        .any(|character| character.is_control() && character != '\n'));
}

#[cfg(unix)]
#[test]
fn control_characters_in_paths_are_skipped_and_escaped() {
    let fixture = Fixture::java();
    for (index, (raw, _)) in CONTROL_PATHS.iter().enumerate() {
        fixture.write(raw, &format!("class Hostile{index} {{ void injected() {{}} }}\n"));
    }
    let before = snapshot(&fixture.source);
    assert_control_paths_are_skipped(&fixture, false);
    assert_eq!(before, snapshot(&fixture.source));
    // The same paths as untracked and as committed files of a work tree.
    if !fixture.git(&["init", "-q"]) {
        return;
    }
    assert_control_paths_are_skipped(&fixture, true);
    assert!(fixture.git_commit());
    assert_control_paths_are_skipped(&fixture, true);
}

#[test]
fn output_inside_the_source_is_refused_before_anything_is_written() {
    let fixture = Fixture::java();
    let before = snapshot(&fixture.source);
    for inside in [
        fixture.source.clone(),
        fixture.source.join("out"),
        fixture.source.join("src/../maps"),
    ] {
        let output = Command::new(BINARY)
            .arg(&fixture.source)
            .arg("--output-dir")
            .arg(&inside)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(String::from_utf8_lossy(&output.stderr).contains("outside the source repository"));
    }
    assert_eq!(before, snapshot(&fixture.source));
}

#[cfg(unix)]
#[test]
fn output_links_cannot_redirect_writes_into_the_source() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::java();
    // A link that resolves into the source is the source.
    let disguised = fixture.source.parent().unwrap().join("disguised");
    symlink(fixture.source.join("src"), &disguised).unwrap();
    let output = Command::new(BINARY)
        .arg(&fixture.source)
        .arg("--output-dir")
        .arg(&disguised)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));

    // A planted link named like an artifact is replaced, not written through.
    fs::create_dir(&fixture.output).unwrap();
    symlink(
        fixture.source.join("src/app/Channel.java"),
        fixture.output.join("repo-map.md"),
    )
    .unwrap();
    let before = snapshot(&fixture.source);
    fixture.map_ok(&[]);
    assert_eq!(before, snapshot(&fixture.source));
    assert!(fs::symlink_metadata(fixture.output.join("repo-map.md"))
        .unwrap()
        .is_file());
    assert!(fixture.map_text().starts_with("# Repository map"));
}

#[test]
fn file_and_size_limits_are_explicit() {
    let fixture = Fixture::java();
    let summary = fixture.map_ok(&["--max-files", "1"]);
    assert_eq!(summary["truncated"], true);
    assert_eq!(summary["coverage"]["candidates_seen"], 2);
    assert_eq!(summary["coverage"]["selected_files"], 1);
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        skip_reason(&inventory, "*").as_deref(),
        Some("max_files exceeded (1); map a subtree")
    );

    for arguments in [
        ["--max-files", "0"],
        ["--max-files", "100001"],
        ["--max-file-bytes", "20000001"],
    ] {
        let output = fixture.map(&arguments);
        assert_eq!(output.status.code(), Some(2), "{arguments:?}");
        assert!(String::from_utf8_lossy(&output.stderr).contains("limits must be"));
    }
}

#[test]
fn subtree_exclusion_and_escape_attempts() {
    let fixture = Fixture::java();
    fixture.write("legacy/old/Old.java", "class OldThing {}\n");
    fixture.write("legacy/gen/Generated.java", "class GeneratedThing {}\n");
    let summary = fixture.map_ok(&["--subtree", "legacy", "--exclude", "legacy/gen/*"]);
    assert_eq!(summary["coverage"]["candidates_seen"], 2);
    let inventory = fixture.json("inventory.json");
    assert_eq!(paths(&inventory["files"]), ["legacy/old/Old.java"]);
    assert_eq!(
        skip_reason(&inventory, "legacy/gen/Generated.java").as_deref(),
        Some("explicit exclusion")
    );
    let map = fixture.map_text();
    assert!(map.contains("OldThing") && !map.contains("GeneratedThing") && !map.contains("TransferService"));

    // A sibling directory sharing the prefix is not part of the subtree.
    fixture.write("legacy-archive/Archived.java", "class Archived {}\n");
    fixture.map_ok(&["--subtree", "legacy/"]);
    assert!(!fixture.map_text().contains("Archived"));

    for arguments in [
        ["--subtree", "../outside"],
        ["--focus-file", "/etc/passwd"],
        ["--subtree", "a/../.."],
    ] {
        let output = fixture.map(&arguments);
        assert_eq!(output.status.code(), Some(2), "{arguments:?}");
        assert!(String::from_utf8_lossy(&output.stderr).contains("must be relative"));
    }
}

#[test]
fn descriptors_and_unsupported_files_stay_visible_without_fake_symbols() {
    let fixture = Fixture::new();
    fixture.write("pom.xml", "<project><artifactId>demo</artifactId></project>\n");
    fixture.write("conf/app.properties", "handler.class=app.Handler\n");
    fixture.write("Makefile", "all:\n\techo build\n");
    fixture.write("web/page.jsp", "<% out.print(1); %>\n");
    fixture.write("app/Main.kt", "class KotlinMain\n");
    fixture.write("README", "plain\n");
    let summary = fixture.map_ok(&[]);
    assert_eq!(summary["coverage"]["parsed_files"], 0);
    assert_eq!(summary["coverage"]["definitions_found"], 0);
    let map = fixture.map_text();
    assert!(
        map.contains("No supported definitions found in selected files."),
        "{map}"
    );
    assert!(!map.contains("KotlinMain"));
    let metadata = fixture.json("map.meta.json");
    assert_eq!(
        strings(&metadata["descriptors"]),
        ["Makefile", "conf/app.properties", "pom.xml"]
    );
    assert_eq!(
        strings(&metadata["unsupported_languages"]),
        ["app/Main.kt", "web/page.jsp"]
    );
    let inventory = fixture.json("inventory.json");
    let kinds: BTreeMap<String, String> = inventory["files"]
        .as_array()
        .unwrap()
        .iter()
        .map(|file| {
            (
                file["path"].as_str().unwrap().to_string(),
                file["kind"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    assert_eq!(kinds["pom.xml"], "descriptor");
    assert_eq!(kinds["README"], "other");
}

#[test]
fn crlf_unicode_paths_and_several_languages() {
    let fixture = Fixture::new();
    fixture.write(
        "src/zażółć gęślą/Jaźń Service.java",
        "package a;\r\n\r\npublic class JaznService {\r\n    void obsłuż() {}\r\n}\r\n",
    );
    fixture.write(
        "py/ledger.py",
        "class Ledger:\n    def post_entry(self):\n        pass\n",
    );
    fixture.write(
        "web/cart.ts",
        "export interface CartPort {}\nexport function totalPrice(): number { return 1; }\n",
    );
    fixture.write("web/View.tsx", "export function CartView() { return <div/>; }\n");
    fixture.write("native/pool.c", "int acquire_slot(void) { return 0; }\n");
    fixture.map_ok(&[]);
    let map = fixture.map_text();
    for line in [
        "src/zażółć gęślą/Jaźń Service.java:L3: public class JaznService {\n",
        "src/zażółć gęślą/Jaźń Service.java:L4: void obsłuż() {}\n",
        "py/ledger.py:L2: def post_entry(self):\n",
        "web/cart.ts:L2: export function totalPrice(): number { return 1; }\n",
        "web/View.tsx:L1: export function CartView() { return <div/>; }\n",
        "native/pool.c:L1: int acquire_slot(void) { return 0; }\n",
    ] {
        assert!(map.contains(line), "missing {line:?} in {map}");
    }
    assert!(!map.contains('\r'));
}

#[test]
fn unusual_line_separators_do_not_break_map_lines() {
    let fixture = Fixture::new();
    fixture.write_bytes(
        "src/page.c",
        b"int first(void) { return 1; }\n\x0c\nint second(void) { return 2; }\n\nint third(void) { return 3; }\n",
    );
    fixture.write_bytes("src/Old.java", b"class OldMac {\r    void legacy() {}\r}\r");
    fixture.map_ok(&[]);
    let map = fixture.map_text();
    assert!(
        map.contains("src/page.c:L3: int second(void) { return 2; }\n"),
        "{map:?}"
    );
    assert!(
        map.contains("src/page.c:L5: int third(void) { return 3; }\n"),
        "{map:?}"
    );
    assert!(!map.contains('\r') && !map.contains('\u{c}'), "{map:?}");
    // Every line after the header is one `path:Lnumber: text` entry.
    for line in map.lines().skip(2) {
        assert!(line.starts_with("src/") && line.contains(":L"), "{line:?}");
    }
}

#[test]
fn broken_source_is_reported_and_partially_mapped() {
    let fixture = Fixture::new();
    fixture.write("src/Broken.java", "class Usable { void stillFound() {} }\nclass {{{ \n");
    fixture.map_ok(&[]);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(strings(&metadata["syntax_error_files"]), ["src/Broken.java"]);
    assert!(fixture.map_text().contains("stillFound"));
}

#[test]
fn directory_walk_honors_gitignore_files_without_git() {
    let fixture = Fixture::java();
    fixture.write(".gitignore", "*.log\n/dist\nbuild/\n!keep.log\n");
    fixture.write("src/.gitignore", "tmp/\n");
    fixture.write("app.log", "noise\n");
    fixture.write("keep.log", "kept\n");
    fixture.write("dist/Bundle.java", "class Bundled {}\n");
    fixture.write("src/dist/Nested.java", "class NestedDist {}\n");
    fixture.write("build/Out.java", "class BuiltOutput {}\n");
    fixture.write("src/tmp/Scratch.java", "class Scratch {}\n");
    fixture.write("node_modules/dep/index.js", "function vendored() {}\n");
    fixture.write(".git/config", "[core]\n");
    fixture.map_ok(&[]);
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        paths(&inventory["files"]),
        [
            ".gitignore",
            "keep.log",
            "src/.gitignore",
            "src/app/Channel.java",
            "src/app/TransferService.java",
            "src/dist/Nested.java",
        ]
    );
    assert_eq!(fixture.json("map.meta.json")["git"], false);
}

#[test]
fn git_selection_revision_and_dirty_state() {
    let fixture = Fixture::java();
    fixture.write(".gitignore", "ignored/\n*.tmp\n");
    fixture.write(".env", "TOKEN=tracked-secret-value\n");
    if !fixture.git_commit() {
        return;
    }
    fixture.write("ignored/Hidden.java", "class HiddenIgnored {}\n");
    fixture.write("scratch.tmp", "x\n");
    let index_before = fs::read(fixture.source.join(".git/index")).unwrap();
    fixture.map_ok(&[]);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["git"], true);
    assert_eq!(metadata["dirty"], false);
    assert_eq!(metadata["revision"].as_str().unwrap().len(), 40);
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        paths(&inventory["files"]),
        [".gitignore", "src/app/Channel.java", "src/app/TransferService.java"]
    );
    // Tracked secrets are listed as skipped and never read.
    assert_eq!(skip_reason(&inventory, ".env").as_deref(), Some("secret-looking file"));
    assert!(!fixture.artifacts().contains("tracked-secret-value"));
    assert!(!fixture.artifacts().contains("HiddenIgnored"));

    // Untracked, unignored files are part of the working copy.
    fixture.write("src/app/Fresh.java", "class FreshUntracked {}\n");
    fs::remove_file(fixture.source.join("src/app/Channel.java")).unwrap();
    fixture.map_ok(&[]);
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["dirty"], true);
    let inventory = fixture.json("inventory.json");
    assert!(paths(&inventory["files"]).contains(&"src/app/Fresh.java".to_string()));
    assert_eq!(
        skip_reason(&inventory, "src/app/Channel.java").as_deref(),
        Some("missing or outside source")
    );
    assert!(fixture.map_text().contains("FreshUntracked"));
    assert_eq!(index_before, fs::read(fixture.source.join(".git/index")).unwrap());
}

#[cfg(unix)]
#[test]
fn repository_configured_commands_are_not_executed() {
    use std::os::unix::fs::PermissionsExt;
    let fixture = Fixture::java();
    if !fixture.git_commit() {
        return;
    }
    let base = fixture.source.parent().unwrap().to_path_buf();
    let marker = base.join("executed");
    let hook = base.join("hook.sh");
    fs::write(&hook, format!("#!/bin/sh\ntouch '{}'\n", marker.display())).unwrap();
    fs::set_permissions(&hook, fs::Permissions::from_mode(0o755)).unwrap();
    let hook_text = hook.to_string_lossy().to_string();

    assert!(fixture.git(&["config", "core.fsmonitor", &hook_text]));
    fixture.map_ok(&[]);
    assert!(!marker.exists(), "core.fsmonitor command was executed");
    assert_eq!(fixture.json("map.meta.json")["dirty"], false);

    // A clean filter would run during `git status`; status is skipped instead.
    assert!(fixture.git(&["config", "--unset", "core.fsmonitor"]));
    assert!(fixture.git(&["config", "filter.planted.clean", &hook_text]));
    fs::write(fixture.source.join(".git/info/attributes"), "*.java filter=planted\n").unwrap();
    fixture.write(
        "src/app/Channel.java",
        &CHANNEL.replace("rarelyUsedHelper", "renamedHelper"),
    );
    fixture.map_ok(&[]);
    assert!(!marker.exists(), "filter command was executed");
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["dirty"], Value::Null);
    assert!(strings(&metadata["git_notes"])
        .iter()
        .any(|note| note.contains("filters can execute")));
    assert_eq!(fixture.json("inventory.json")["git_notes"], metadata["git_notes"]);
    assert!(fixture.map_text().contains("renamedHelper"));
}

#[test]
fn definitions_on_one_source_line_produce_one_map_line() {
    let fixture = Fixture::new();
    fixture.write(
        "src/Compact.java",
        "class Compact { void first() {} void second() {} }\n",
    );
    let summary = fixture.map_ok(&[]);
    let map = fixture.map_text();
    assert_eq!(map.matches("src/Compact.java:L1: ").count(), 1, "{map}");
    assert_eq!(summary["coverage"]["definitions_found"], 3);
    assert_eq!(summary["coverage"]["definitions_in_map"], 3);
    assert_eq!(summary["truncated"], false);
}

#[test]
fn inventory_only_lists_files_without_a_symbol_map() {
    let fixture = Fixture::java();
    fixture.write(".env", "TOKEN=inventory-secret\n");
    let summary = fixture.map_ok(&["--inventory-only"]);
    assert_eq!(summary["status"], "inventory-only");
    assert_eq!(summary["coverage"]["selected_files"], 2);
    assert_eq!(summary["coverage"]["definitions_found"], Value::Null);
    assert!(fixture.map_text().starts_with("# Repository inventory"));
    assert!(!fixture.map_text().contains("openChannel"));
    let inventory = fixture.json("inventory.json");
    assert_eq!(
        paths(&inventory["files"]),
        ["src/app/Channel.java", "src/app/TransferService.java"]
    );
    assert_eq!(skip_reason(&inventory, ".env").as_deref(), Some("secret-looking file"));
    assert_eq!(fixture.json("map.meta.json")["status"], "inventory-only");
}

#[test]
fn a_safety_limit_fails_the_run_and_replaces_the_previous_map() {
    let fixture = Fixture::java();
    fixture.map_ok(&[]);
    assert!(fixture.map_text().contains("openChannel"));

    let mut source = String::from("class Enormous {\n");
    for index in 0..=20_000 {
        source.push_str(&format!("void m{index}() {{}}\n"));
    }
    source.push_str("}\n");
    fixture.write("src/app/Enormous.java", &source);
    let output = fixture.map(&[]);
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("tag limit exceeded in src/app/Enormous.java"));
    // The stale map is gone, the inventory is complete, the failure is recorded.
    assert!(fixture.map_text().starts_with("# Repository inventory"));
    assert!(!fixture.map_text().contains("openChannel"));
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["status"], "failed");
    assert_eq!(metadata["failure"]["stage"], "parsing");
    assert_eq!(fixture.json("inventory.json")["files"].as_array().unwrap().len(), 3);
}

#[test]
fn a_directory_ignored_by_an_enclosing_repository_is_still_mapped() {
    let fixture = Fixture::new();
    fixture.write(".gitignore", "scratch/\n");
    fixture.write("Outer.java", "class OuterTracked {}\n");
    fixture.write(
        "scratch/project/src/Inner.java",
        "class InnerProject { void innerWork() {} }\n",
    );
    fixture.write("scratch/project/.gitignore", "*.gen.java\n");
    fixture.write("scratch/project/src/Made.gen.java", "class MadeByGenerator {}\n");
    if !fixture.git_commit() {
        return;
    }
    let inner = fixture.source.join("scratch/project");
    let output = Command::new(BINARY)
        .arg(&inner)
        .arg("--output-dir")
        .arg(&fixture.output)
        .output()
        .unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    let map = fixture.map_text();
    assert!(map.contains("src/Inner.java:L1: class InnerProject"), "{map}");
    assert!(!map.contains("MadeByGenerator") && !map.contains("OuterTracked"));
    let metadata = fixture.json("map.meta.json");
    assert_eq!(metadata["git"], false);
    assert_eq!(metadata["revision"], Value::Null);
    assert!(strings(&metadata["source_notes"])
        .iter()
        .any(|note| note.contains("ignored by its enclosing git work tree")));
}

#[test]
fn usage_errors_and_informational_flags() {
    let run = |arguments: &[&str]| {
        Command::new(BINARY)
            .args(arguments)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    };
    let missing = run(&["/definitely/not/a/repository", "--output-dir", "unused-output"]);
    assert_eq!(missing.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&missing.stderr).starts_with("legacy-repo-map: cannot open repository"));
    assert!(!Path::new("unused-output").exists());
    assert_eq!(run(&[]).status.code(), Some(2));
    assert_eq!(run(&["--unknown"]).status.code(), Some(2));

    let version = run(&["--version"]);
    assert!(version.status.success());
    assert!(String::from_utf8_lossy(&version.stdout).contains("experimental"));
    assert!(String::from_utf8_lossy(&run(&["--help"]).stdout).contains("--focus-symbol"));

    let notices = String::from_utf8(run(&["--notices"]).stdout).unwrap();
    assert!(notices.contains("Apache License") && notices.contains("Version 2.0"));
    assert!(notices.contains("Aider-AI/aider"));
    assert!(notices.matches("Permission is hereby granted").count() >= 10);
    assert!(notices.contains("==== tree-sitter (MIT) ===="));

    let policy: Value = serde_json::from_slice(&run(&["--print-policy"]).stdout).unwrap();
    assert_eq!(policy["languages"][".java"], "java");
    assert_eq!(policy["queries"].as_object().unwrap().len(), 10);
    assert!(strings(&policy["secret_names"]).contains(&".env".to_string()));
}
