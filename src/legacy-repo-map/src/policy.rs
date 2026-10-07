//! Selection policy tables. They mirror `scripts/repo_files.py` in the
//! legacy-codebase-workflows skill; `--print-policy` exposes them so a test
//! can detect drift between the two implementations.

pub const DEFAULT_MAX_FILES: usize = 10_000;
pub const DEFAULT_MAX_FILE_BYTES: u64 = 2_000_000;
pub const HARD_MAX_FILES: usize = 100_000;
pub const HARD_MAX_FILE_BYTES: u64 = 20_000_000;
pub const MAX_TAGS_PER_FILE: usize = 20_000;
pub const MAX_TOTAL_TAGS: usize = 200_000;
pub const MAX_EDGES: usize = 200_000;
pub const MIN_BUDGET: usize = 64;
pub const MAX_BUDGET: usize = 1_000_000;
pub const DEFAULT_BUDGET: usize = 4096;
pub const MAX_NAME_CHARS: usize = 512;
pub const MAX_SNIPPET_CHARS: usize = 240;
pub const MAX_GITIGNORE_BYTES: u64 = 256_000;
pub const MAX_IGNORE_TOTAL_BYTES: u64 = 2_000_000;
pub const MAX_DISCOVERY_ENTRIES: usize = 100_000;

pub const LANGUAGES: &[(&str, &str)] = &[
    (".py", "python"),
    (".java", "java"),
    (".js", "javascript"),
    (".jsx", "javascript"),
    (".mjs", "javascript"),
    (".cjs", "javascript"),
    (".ts", "typescript"),
    (".tsx", "tsx"),
    (".c", "c"),
    (".h", "c"),
    (".cc", "cpp"),
    (".cpp", "cpp"),
    (".cxx", "cpp"),
    (".hpp", "cpp"),
    (".hh", "cpp"),
    (".cs", "c_sharp"),
    (".go", "go"),
    (".rs", "rust"),
];
pub const DESCRIPTOR_SUFFIXES: &[&str] = &[
    ".xml",
    ".properties",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".gradle",
    ".mod",
    ".csproj",
    ".sln",
    ".vcxproj",
    ".props",
    ".targets",
];
pub const DESCRIPTOR_NAMES: &[&str] = &[
    "pom.xml",
    "gradlew",
    "build.gradle",
    "settings.gradle",
    "build.gradle.kts",
    "settings.gradle.kts",
    "makefile",
    "cmakelists.txt",
    "dockerfile",
    "gemfile",
    "cargo.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "requirements.txt",
];
pub const SECRET_NAMES: &[&str] = &[
    ".env",
    ".envrc",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "credentials",
    "credentials.json",
    "service-account.json",
    "secrets.json",
];
pub const SECRET_PART_PREFIXES: &[&str] = &[".env.", ".env-"];
pub const SECRET_DIRS: &[&str] = &[".ssh", ".aws", ".azure", ".kube", "secrets"];
pub const SECRET_SUFFIXES: &[&str] = &[
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".keystore",
    ".jks",
    ".asc",
    ".gpg",
    ".p8",
    ".pkcs8",
    ".kdbx",
];
/// A file name is secret-looking when one of these words stands alone
/// between separators, as in `db-credentials.yaml` or `client_secret.json`.
pub const SECRET_NAME_WORDS: &[&str] = &["credential", "credentials", "secret", "secrets"];
pub const SECRET_NAME_SEPARATORS: &str = "-_.";
pub const IGNORED_DIRS: &[&str] = &[
    ".git",
    ".aider.tags.cache",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
];

/// Final-component suffix with the leading dot, lowercased; empty when the
/// name has no extension (`.env`, `Makefile`, `name.`).
pub fn suffix_lower(name: &str) -> String {
    match name.rfind('.') {
        Some(index) if index > 0 && index + 1 < name.len() => name[index..].to_lowercase(),
        _ => String::new(),
    }
}

pub fn file_name(relative: &str) -> &str {
    relative.rsplit('/').next().unwrap_or(relative)
}

pub fn language_for(relative: &str) -> Option<&'static str> {
    let suffix = suffix_lower(file_name(relative));
    LANGUAGES
        .iter()
        .find(|(extension, _)| *extension == suffix)
        .map(|(_, language)| *language)
}

pub fn kind_for(relative: &str, language: Option<&str>) -> &'static str {
    if language.is_some() {
        return "source";
    }
    let name = file_name(relative).to_lowercase();
    let suffix = suffix_lower(&name);
    if DESCRIPTOR_SUFFIXES.contains(&suffix.as_str()) || DESCRIPTOR_NAMES.contains(&name.as_str()) {
        "descriptor"
    } else {
        "other"
    }
}

pub fn is_secret(relative: &str) -> bool {
    for part in relative.split('/') {
        let lowered = part.to_lowercase();
        if SECRET_NAMES.contains(&lowered.as_str())
            || SECRET_PART_PREFIXES.iter().any(|prefix| lowered.starts_with(prefix))
            || SECRET_DIRS.contains(&lowered.as_str())
        {
            return true;
        }
    }
    let name = file_name(relative).to_lowercase();
    SECRET_SUFFIXES.contains(&suffix_lower(&name).as_str()) || has_secret_word(&name)
}

fn has_secret_word(name: &str) -> bool {
    let separator = |c: Option<char>| c.is_none_or(|c| SECRET_NAME_SEPARATORS.contains(c));
    SECRET_NAME_WORDS.iter().any(|word| {
        name.match_indices(word).any(|(start, _)| {
            separator(name[..start].chars().next_back()) && separator(name[start + word.len()..].chars().next())
        })
    })
}

/// The name rule as the regular expression the Python tool uses.
pub fn secret_name_pattern() -> String {
    format!(
        "(?:^|[{0}])(?:{1})(?:$|[{0}])",
        SECRET_NAME_SEPARATORS,
        SECRET_NAME_WORDS.join("|")
    )
}

/// Normalize deliberate CLI focus/subtree input, independently of source identity.
pub fn cli_relative(relative: &str) -> Result<String, String> {
    safe_relative(&relative.replace('\\', "/"))
}

/// Validate a literal repository-relative identity with `/` separators.
/// A backslash is an ordinary POSIX filename character, not traversal.
pub fn safe_relative(relative: &str) -> Result<String, String> {
    let normalized = relative;
    let unsafe_path = || format!("unsafe relative path: {relative:?}");
    if normalized.is_empty()
        || normalized.starts_with('/')
        || normalized.contains('\0')
        || (cfg!(windows) && normalized.contains('\\'))
    {
        return Err(unsafe_path());
    }
    let mut parts = Vec::new();
    for part in normalized.split('/') {
        match part {
            "" => continue,
            "." => continue,
            ".." => return Err(unsafe_path()),
            _ if cfg!(windows) && part.contains(':') => return Err(unsafe_path()),
            _ => parts.push(part),
        }
    }
    Ok(if parts.is_empty() {
        ".".to_string()
    } else {
        parts.join("/")
    })
}

/// Case-sensitive shell-style match equivalent to Python's
/// `fnmatch.fnmatchcase`: `*` and `?` also match `/`.
pub fn fnmatch(name: &str, pattern: &str) -> bool {
    let name: Vec<char> = name.chars().collect();
    let pattern: Vec<char> = pattern.chars().collect();
    let (mut n, mut p) = (0usize, 0usize);
    let mut backtrack: Option<(usize, usize)> = None;
    while n < name.len() {
        let mut advanced = false;
        if p < pattern.len() {
            match pattern[p] {
                '*' => {
                    backtrack = Some((p, n));
                    p += 1;
                    continue;
                }
                '?' => {
                    n += 1;
                    p += 1;
                    advanced = true;
                }
                '[' => match class_match(&pattern, p, name[n]) {
                    Some((true, next)) => {
                        n += 1;
                        p = next;
                        advanced = true;
                    }
                    Some((false, _)) => {}
                    None => {
                        if name[n] == '[' {
                            n += 1;
                            p += 1;
                            advanced = true;
                        }
                    }
                },
                literal => {
                    if literal == name[n] {
                        n += 1;
                        p += 1;
                        advanced = true;
                    }
                }
            }
        }
        if advanced {
            continue;
        }
        match backtrack {
            Some((star, consumed)) => {
                backtrack = Some((star, consumed + 1));
                p = star + 1;
                n = consumed + 1;
            }
            None => return false,
        }
    }
    pattern[p..].iter().all(|c| *c == '*')
}

/// Match one character against the bracket expression starting at `start`.
/// Returns `None` when the bracket is unterminated and therefore literal.
fn class_match(pattern: &[char], start: usize, candidate: char) -> Option<(bool, usize)> {
    let mut index = start + 1;
    let negated = index < pattern.len() && pattern[index] == '!';
    if negated {
        index += 1;
    }
    let first = index;
    let mut matched = false;
    loop {
        if index >= pattern.len() {
            return None;
        }
        let current = pattern[index];
        if current == ']' && index > first {
            break;
        }
        if index + 2 < pattern.len() && pattern[index + 1] == '-' && pattern[index + 2] != ']' {
            if current <= candidate && candidate <= pattern[index + 2] {
                matched = true;
            }
            index += 3;
        } else {
            if current == candidate {
                matched = true;
            }
            index += 1;
        }
    }
    Some((matched != negated, index + 1))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fnmatch_follows_python_semantics() {
        assert!(fnmatch("src/gen/a.java", "src/gen/*"));
        assert!(fnmatch("src/gen/deep/a.java", "src/*"));
        assert!(fnmatch("a.min.js", "*.min.js"));
        assert!(fnmatch("file1.txt", "file?.txt"));
        assert!(fnmatch("fileA.txt", "file[A-C].txt"));
        assert!(!fnmatch("fileD.txt", "file[A-C].txt"));
        assert!(fnmatch("fileD.txt", "file[!A-C].txt"));
        assert!(fnmatch("a[b", "a[b"));
        assert!(!fnmatch("A.java", "a.java"));
        assert!(!fnmatch("abc", "ab"));
        assert!(fnmatch("", "*"));
        assert!(fnmatch("x]", "x[]]"));
    }

    #[test]
    fn secret_and_kind_classification() {
        for path in [
            ".env",
            "config/.env.production",
            "deploy/id_rsa",
            "certs/server.pem",
            "k8s/db-credentials.yaml",
            ".aws/config",
            "secrets/readme.md",
            "A/.ENV",
        ] {
            assert!(is_secret(path), "{path}");
        }
        for path in [
            "conf/client_secret.json",
            "x/app.secrets.toml",
            "a/Credential.java",
            "k/store.kdbx",
        ] {
            assert!(is_secret(path), "{path}");
        }
        for path in [
            "src/Env.java",
            "docs/environment.md",
            "src/keys.ts",
            "src/Secretary.java",
            "src/CredentialsHelper.java",
            "docs/secretless.md",
        ] {
            assert!(!is_secret(path), "{path}");
        }
        assert_eq!(language_for("src/A.JAVA"), Some("java"));
        assert_eq!(language_for("x/y.tsx"), Some("tsx"));
        assert_eq!(kind_for("pom.xml", None), "descriptor");
        assert_eq!(kind_for("Makefile", None), "descriptor");
        assert_eq!(kind_for("docs/a.html", None), "other");
        assert_eq!(suffix_lower(".gitignore"), "");
        assert_eq!(suffix_lower("a.tar.GZ"), ".gz");
    }

    #[test]
    fn relative_paths_are_bounded() {
        assert_eq!(cli_relative("src\\main/A.java").unwrap(), "src/main/A.java");
        #[cfg(unix)]
        {
            assert_eq!(safe_relative("src\\main/A.java").unwrap(), "src\\main/A.java");
            assert_eq!(safe_relative("..\\literal.java").unwrap(), "..\\literal.java");
        }
        assert!(cli_relative("..\\outside.java").is_err());
        assert_eq!(safe_relative("src/").unwrap(), "src");
        assert_eq!(safe_relative("./a/./b/").unwrap(), "a/b");
        assert_eq!(safe_relative(".").unwrap(), ".");
        for bad in ["", "/etc/passwd", "../x", "a/../b", "a/\0b"] {
            assert!(safe_relative(bad).is_err(), "{bad:?}");
        }
    }
}
