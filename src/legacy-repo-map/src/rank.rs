//! Definition ranking ported from `vendor/aider_rank.py`, which adapts
//! `aider/repomap.py` from Aider-AI/aider at
//! 5dc9490bb35f9729ef2c95d00a19ccd30c26339c (Apache-2.0).
//!
//! Files are graph nodes. An identifier defined in one file and mentioned in
//! another adds a weighted edge from the mentioning file to the defining
//! file, and personalized PageRank spreads rank over those edges. Matching
//! is by bare identifier text: it is not a resolved call graph.
//!
//! The arithmetic follows the Python code operation by operation, including
//! the compensated summation that CPython 3.12+ uses in `sum()`, so both
//! implementations order definitions the same way.
//!
//! `pagerank` adapts `_pagerank_python` in
//! `networkx/algorithms/link_analysis/pagerank_alg.py` from networkx 3.4.2
//! (networkx/networkx at 2acf1590f82757c01a57b81b8c5dfb79e60aa416,
//! BSD-3-Clause). `licenses/networkx-LICENSE.txt` is the upstream license and
//! `--notices` prints it in full.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use crate::tags::{Kind, Tag};

const ALPHA: f64 = 0.85;
const MAX_ITERATIONS: usize = 100;
const TOLERANCE: f64 = 1.0e-6;

pub struct RankFile<'a> {
    pub path: &'a str,
    pub tags: &'a [Tag],
}

#[derive(Debug, PartialEq)]
pub struct RankedDefinition<'a> {
    pub file: usize,
    pub line: usize,
    pub name: &'a str,
}

struct Edge {
    destination: usize,
    weight: f64,
    identifier: usize,
}

/// CPython's `sum()` over floats (Neumaier compensated summation).
fn py_sum(values: impl Iterator<Item = f64>) -> f64 {
    let (mut total, mut compensation) = (0.0f64, 0.0f64);
    for value in values {
        let next = total + value;
        if total.abs() >= value.abs() {
            compensation += (total - next) + value;
        } else {
            compensation += (value - next) + total;
        }
        total = next;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total + compensation
    } else {
        total
    }
}

/// Name without its extension, as `PurePosixPath.stem`.
fn stem(name: &str) -> &str {
    match name.rfind('.') {
        Some(index) if index > 0 && index + 1 < name.len() => &name[..index],
        _ => name,
    }
}

/// networkx `_pagerank_python` on a weighted multigraph whose out-edges are
/// listed per node in insertion order. `None` when it does not converge.
fn pagerank(out: &[Vec<Edge>], personalization: &[(usize, f64)]) -> Option<Vec<f64>> {
    let count = out.len();
    let count_f = count as f64;
    let normalized: Vec<Vec<f64>> = out
        .iter()
        .map(|edges| {
            let degree = py_sum(edges.iter().map(|edge| edge.weight));
            edges
                .iter()
                .map(|edge| if degree == 0.0 { 0.0 } else { edge.weight / degree })
                .collect()
        })
        .collect();
    let mut preference = vec![0.0f64; count];
    if personalization.is_empty() {
        preference.fill(1.0 / count_f);
    } else {
        let total = py_sum(personalization.iter().map(|(_, score)| *score));
        for (node, score) in personalization {
            preference[*node] = score / total;
        }
    }
    let dangling: Vec<usize> = (0..count).filter(|node| out[*node].is_empty()).collect();
    let mut rank = vec![1.0 / count_f; count];
    for _ in 0..MAX_ITERATIONS {
        let last = rank;
        rank = vec![0.0f64; count];
        let dangle_sum = ALPHA * py_sum(dangling.iter().map(|node| last[*node]));
        for node in 0..count {
            for (edge, weight) in out[node].iter().zip(&normalized[node]) {
                rank[edge.destination] += ALPHA * last[node] * weight;
            }
            rank[node] += dangle_sum * preference[node] + (1.0 - ALPHA) * preference[node];
        }
        let error = py_sum((0..count).map(|node| (rank[node] - last[node]).abs()));
        if error < count_f * TOLERANCE {
            return Some(rank);
        }
    }
    None
}

/// Order definitions by graph rank. `files` must be sorted by path.
pub fn rank_definitions<'a>(
    files: &[RankFile<'a>],
    focus_files: &[String],
    focus_symbols: &[String],
    max_edges: usize,
) -> Result<Vec<RankedDefinition<'a>>, String> {
    if files.is_empty() {
        return Ok(Vec::new());
    }
    let focused: HashSet<&str> = focus_files.iter().map(String::as_str).collect();
    let symbols: HashSet<&str> = focus_symbols.iter().map(String::as_str).collect();
    let personalize = 100.0 / files.len() as f64;

    let mut defines: BTreeMap<&'a str, BTreeSet<usize>> = BTreeMap::new();
    let mut references: HashMap<&'a str, Vec<usize>> = HashMap::new();
    let mut definitions: HashMap<(usize, &'a str), Vec<usize>> = HashMap::new();
    let mut personalization = Vec::new();
    for (index, file) in files.iter().enumerate() {
        let name = file.path.rsplit('/').next().unwrap_or(file.path);
        let mut score = 0.0;
        if focused.contains(file.path) {
            score = personalize;
        }
        if file.path.split('/').any(|part| symbols.contains(part)) || symbols.contains(stem(name)) {
            score += personalize;
        }
        if score != 0.0 {
            personalization.push((index, score));
        }
        for tag in file.tags {
            match tag.kind {
                Kind::Def => {
                    defines.entry(tag.name.as_str()).or_default().insert(index);
                    definitions
                        .entry((index, tag.name.as_str()))
                        .or_default()
                        .push(tag.line);
                }
                Kind::Ref => references.entry(tag.name.as_str()).or_default().push(index),
            }
        }
    }
    if references.is_empty() {
        for (identifier, definers) in &defines {
            references.insert(identifier, definers.iter().copied().collect());
        }
    }

    // Out-edges grouped by destination in first-insertion order, the order a
    // networkx MultiDiGraph iterates them.
    let mut order: Vec<Vec<usize>> = vec![Vec::new(); files.len()];
    let mut grouped: Vec<HashMap<usize, Vec<(f64, usize)>>> = vec![HashMap::new(); files.len()];
    let mut edge_count = 0usize;
    // Every insertion passes through here, so no edge escapes the limit.
    let mut add_edge = |source: usize, destination: usize, weight: f64, identifier: usize| {
        if edge_count >= max_edges {
            return Err(format!("ranking edge limit exceeded ({max_edges}); map a subtree"));
        }
        let bucket = grouped[source].entry(destination).or_insert_with(|| {
            order[source].push(destination);
            Vec::new()
        });
        bucket.push((weight, identifier));
        edge_count += 1;
        Ok(())
    };
    let identifiers: Vec<&'a str> = defines.keys().copied().collect();
    for (identifier_index, identifier) in identifiers.iter().enumerate() {
        let definers = &defines[identifier];
        let Some(referencers) = references.get(identifier) else {
            for definer in definers {
                add_edge(*definer, *definer, 0.1, identifier_index)?;
            }
            continue;
        };
        let mut multiplier = 1.0f64;
        let has_alpha = identifier.chars().any(char::is_alphabetic);
        let is_snake = identifier.contains('_') && has_alpha;
        let is_kebab = identifier.contains('-') && has_alpha;
        let is_camel = identifier.chars().any(char::is_uppercase) && identifier.chars().any(char::is_lowercase);
        if symbols.contains(identifier) {
            multiplier *= 10.0;
        }
        if (is_snake || is_kebab || is_camel) && identifier.chars().count() >= 8 {
            multiplier *= 10.0;
        }
        if identifier.starts_with('_') {
            multiplier *= 0.1;
        }
        if definers.len() > 5 {
            multiplier *= 0.1;
        }
        let mut counts: BTreeMap<usize, u64> = BTreeMap::new();
        for referencer in referencers {
            *counts.entry(*referencer).or_default() += 1;
        }
        for (referencer, references_here) in counts {
            for definer in definers {
                let boosted = multiplier
                    * if focused.contains(files[referencer].path) {
                        50.0
                    } else {
                        1.0
                    };
                add_edge(
                    referencer,
                    *definer,
                    boosted * (references_here as f64).sqrt(),
                    identifier_index,
                )?;
            }
        }
    }
    let out: Vec<Vec<Edge>> = order
        .iter()
        .zip(&grouped)
        .map(|(destinations, buckets)| {
            destinations
                .iter()
                .flat_map(|destination| {
                    buckets[destination].iter().map(|(weight, identifier)| Edge {
                        destination: *destination,
                        weight: *weight,
                        identifier: *identifier,
                    })
                })
                .collect()
        })
        .collect();

    let ranked = pagerank(&out, &personalization).unwrap_or_else(|| vec![1.0 / files.len() as f64; files.len()]);

    let mut scores: HashMap<(usize, usize), f64> = HashMap::new();
    for (source, edges) in out.iter().enumerate() {
        let total = py_sum(edges.iter().map(|edge| edge.weight));
        if total == 0.0 {
            continue;
        }
        for edge in edges {
            *scores.entry((edge.destination, edge.identifier)).or_insert(0.0) += ranked[source] * edge.weight / total;
        }
    }
    // Identifier indexes follow sorted identifier text and file indexes follow
    // sorted paths, so index order is the tie-break order of the original.
    let mut scored: Vec<((usize, usize), f64)> = scores.into_iter().collect();
    scored.sort_by(|left, right| right.1.total_cmp(&left.1).then(left.0.cmp(&right.0)));

    let mut result = Vec::new();
    let mut seen: HashSet<(usize, usize, &'a str)> = HashSet::new();
    for ((file, identifier), _) in scored {
        let name = identifiers[identifier];
        let Some(lines) = definitions.get(&(file, name)) else {
            continue;
        };
        let mut lines = lines.clone();
        lines.sort_unstable();
        for line in lines {
            if seen.insert((file, line, name)) {
                result.push(RankedDefinition { file, line, name });
            }
        }
    }
    for (index, file) in files.iter().enumerate() {
        for tag in file.tags {
            if tag.kind == Kind::Def && seen.insert((index, tag.line, tag.name.as_str())) {
                result.push(RankedDefinition {
                    file: index,
                    line: tag.line,
                    name: tag.name.as_str(),
                });
            }
        }
    }
    // Focus symbols and focus files stay visible even when graph rank is low.
    result.sort_by_key(|definition| {
        (
            !symbols.contains(definition.name),
            !focused.contains(files[definition.file].path),
        )
    });
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tag(line: usize, kind: Kind, name: &str) -> Tag {
        Tag {
            line,
            kind,
            name: name.to_string(),
        }
    }

    fn order(files: &[(&str, Vec<Tag>)], focus_files: &[&str], focus_symbols: &[&str]) -> Vec<String> {
        let focus_files: Vec<String> = focus_files.iter().map(|s| s.to_string()).collect();
        let focus_symbols: Vec<String> = focus_symbols.iter().map(|s| s.to_string()).collect();
        capped(files, &focus_files, &focus_symbols, 1000).unwrap()
    }

    fn capped(
        files: &[(&str, Vec<Tag>)],
        focus_files: &[String],
        focus_symbols: &[String],
        max_edges: usize,
    ) -> Result<Vec<String>, String> {
        let inputs: Vec<RankFile> = files.iter().map(|(path, tags)| RankFile { path, tags }).collect();
        Ok(rank_definitions(&inputs, focus_files, focus_symbols, max_edges)?
            .into_iter()
            .map(|d| format!("{}:{}:{}", inputs[d.file].path, d.line, d.name))
            .collect())
    }

    fn fixture() -> Vec<(&'static str, Vec<Tag>)> {
        vec![
            (
                "a/Caller.java",
                vec![tag(1, Kind::Def, "Caller"), tag(3, Kind::Ref, "openChannel")],
            ),
            (
                "b/Other.java",
                vec![tag(1, Kind::Def, "Other"), tag(4, Kind::Ref, "openChannel")],
            ),
            (
                "c/Target.java",
                vec![tag(1, Kind::Def, "Target"), tag(2, Kind::Def, "openChannel")],
            ),
            (
                "d/Lonely.java",
                vec![tag(1, Kind::Def, "Lonely"), tag(9, Kind::Def, "unused")],
            ),
        ]
    }

    // Expected orders were produced by `vendor/aider_rank.py` on this fixture
    // with networkx 3.4.2 and CPython 3.14.
    #[test]
    fn order_matches_the_python_reference() {
        assert_eq!(
            order(&fixture(), &[], &[]),
            [
                "c/Target.java:1:Target",
                "d/Lonely.java:1:Lonely",
                "d/Lonely.java:9:unused",
                "c/Target.java:2:openChannel",
                "a/Caller.java:1:Caller",
                "b/Other.java:1:Other",
            ]
        );
    }

    #[test]
    fn focus_symbol_and_focus_file_move_to_the_front() {
        assert_eq!(
            order(&fixture(), &[], &["unused"]),
            [
                "d/Lonely.java:9:unused",
                "c/Target.java:1:Target",
                "d/Lonely.java:1:Lonely",
                "c/Target.java:2:openChannel",
                "a/Caller.java:1:Caller",
                "b/Other.java:1:Other",
            ]
        );
        assert_eq!(
            order(&fixture(), &["d/Lonely.java"], &[]),
            [
                "d/Lonely.java:1:Lonely",
                "d/Lonely.java:9:unused",
                "c/Target.java:1:Target",
                "c/Target.java:2:openChannel",
                "a/Caller.java:1:Caller",
                "b/Other.java:1:Other",
            ]
        );
    }

    #[test]
    fn ranking_is_deterministic() {
        assert_eq!(order(&fixture(), &[], &[]), order(&fixture(), &[], &[]));
    }

    #[test]
    fn edge_limit_is_reported() {
        let files = fixture();
        let inputs: Vec<RankFile> = files.iter().map(|(path, tags)| RankFile { path, tags }).collect();
        let error = rank_definitions(&inputs, &[], &[], 1).unwrap_err();
        assert!(error.contains("edge limit"), "{error}");
    }

    // `Alpha` is referenced from another file (one weighted edge); `Zeta` is
    // never referenced, so it gets a self-edge on its defining file.
    fn mixed() -> Vec<(&'static str, Vec<Tag>)> {
        vec![
            (
                "a/Defs.java",
                vec![tag(1, Kind::Def, "Alpha"), tag(2, Kind::Def, "Zeta")],
            ),
            ("b/User.java", vec![tag(1, Kind::Ref, "Alpha")]),
        ]
    }

    // No definition is referenced, but the reference table is not empty, so
    // every definition takes the self-edge path.
    fn unreferenced() -> Vec<(&'static str, Vec<Tag>)> {
        vec![
            (
                "a/One.java",
                vec![tag(1, Kind::Def, "One"), tag(5, Kind::Ref, "elsewhere")],
            ),
            ("b/Two.java", vec![tag(1, Kind::Def, "Two"), tag(2, Kind::Def, "Three")]),
        ]
    }

    fn assert_limit(files: &[(&str, Vec<Tag>)], max_edges: usize) {
        let error = capped(files, &[], &[], max_edges).unwrap_err();
        assert_eq!(
            error,
            format!("ranking edge limit exceeded ({max_edges}); map a subtree")
        );
    }

    #[test]
    fn edge_limit_covers_a_self_edge_after_a_referenced_identifier() {
        // The referenced `Alpha` fills the limit of one; `Zeta` must not slip past it.
        assert_limit(&mixed(), 1);
        assert_limit(&mixed(), 0);
    }

    #[test]
    fn edge_limit_covers_definitions_that_are_never_referenced() {
        assert_limit(&unreferenced(), 0);
        assert_limit(&unreferenced(), 1);
        assert_limit(&unreferenced(), 2);
    }

    // Expected orders were produced by `vendor/aider_rank.py` with networkx
    // 3.4.2, which accepts the same exact limits and refuses one edge fewer.
    #[test]
    fn exact_edge_limit_is_accepted_and_keeps_the_order() {
        let expected_mixed = ["a/Defs.java:2:Zeta", "a/Defs.java:1:Alpha"];
        assert_eq!(capped(&mixed(), &[], &[], 2).unwrap(), expected_mixed);
        assert_eq!(order(&mixed(), &[], &[]), expected_mixed);
        let expected_unreferenced = ["a/One.java:1:One", "b/Two.java:2:Three", "b/Two.java:1:Two"];
        assert_eq!(capped(&unreferenced(), &[], &[], 3).unwrap(), expected_unreferenced);
        assert_eq!(order(&unreferenced(), &[], &[]), expected_unreferenced);
        // The main fixture has two referenced edges and five self-edges.
        assert_eq!(capped(&fixture(), &[], &[], 7).unwrap(), order(&fixture(), &[], &[]));
        assert_limit(&fixture(), 6);
    }

    #[test]
    fn compensated_sum_matches_cpython() {
        // CPython 3.12+: sum([0.1] * 10) == 1.0 and sum([1e100, 1.0, -1e100]) == 1.0
        assert_eq!(py_sum(std::iter::repeat_n(0.1, 10)), 1.0);
        assert_eq!(py_sum([1e100, 1.0, -1e100].into_iter()), 1.0);
        assert_eq!(py_sum(std::iter::empty()), 0.0);
    }
}
