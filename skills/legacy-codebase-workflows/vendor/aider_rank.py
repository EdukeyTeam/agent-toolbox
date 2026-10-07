"""Aider RepoMap ranking adapted for bounded, standalone local maps.

Source: Aider-AI/aider, aider/repomap.py at
5dc9490bb35f9729ef2c95d00a19ccd30c26339c (Apache-2.0).
The graph weighting, personalization and PageRank rank distribution are
retained. Chat-file exclusion, UI callbacks, and unbounded fallback listings
are removed. See ../THIRD_PARTY.md and LICENSE.txt.
"""

from collections import Counter, defaultdict
from pathlib import PurePosixPath
import math


def rank_tags(tags_by_file: dict, *, focus_files=(), focus_symbols=(), max_edges=200_000):
    """Return definition tags in Aider-derived PageRank order, then unranked defs."""
    import networkx as nx
    from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python

    defines = defaultdict(set)
    references = defaultdict(list)
    definitions = defaultdict(list)
    files = sorted(tags_by_file)
    if not files:
        return []
    focused = set(focus_files)
    symbols = set(focus_symbols)
    personalization = {}
    personalize = 100 / len(files)
    for fname in files:
        basename = PurePosixPath(fname).stem
        components = set(PurePosixPath(fname).parts) | {basename, PurePosixPath(fname).name}
        score = 0.0
        if fname in focused:
            score = personalize
        if components & symbols:
            score += personalize
        if score:
            personalization[fname] = score
        for tag in tags_by_file[fname]:
            name = tag["name"]
            if tag["kind"] == "def":
                defines[name].add(fname)
                definitions[(fname, name)].append(tag)
            elif tag["kind"] == "ref":
                references[name].append(fname)
    if not references:
        references = {name: sorted(fnames) for name, fnames in defines.items()}
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(files)
    edge_count = 0
    for ident in sorted(defines):
        definers = sorted(defines[ident])
        if ident not in references:
            for definer in definers:
                if edge_count >= max_edges:
                    raise ValueError(f"ranking edge limit exceeded ({max_edges}); map a subtree")
                graph.add_edge(definer, definer, weight=0.1, ident=ident)
                edge_count += 1
            continue
        mul = 1.0
        is_snake = "_" in ident and any(c.isalpha() for c in ident)
        is_kebab = "-" in ident and any(c.isalpha() for c in ident)
        is_camel = any(c.isupper() for c in ident) and any(c.islower() for c in ident)
        if ident in symbols:
            mul *= 10
        if (is_snake or is_kebab or is_camel) and len(ident) >= 8:
            mul *= 10
        if ident.startswith("_"):
            mul *= 0.1
        if len(definers) > 5:
            mul *= 0.1
        for referencer, num_refs in sorted(Counter(references[ident]).items()):
            for definer in definers:
                if edge_count >= max_edges:
                    raise ValueError(f"ranking edge limit exceeded ({max_edges}); map a subtree")
                use_mul = mul * (50 if referencer in focused else 1)
                graph.add_edge(referencer, definer, weight=use_mul * math.sqrt(num_refs), ident=ident)
                edge_count += 1
    try:
        ranked = _pagerank_python(graph, weight="weight", personalization=personalization or None, dangling=personalization or None)
    except (ZeroDivisionError, nx.PowerIterationFailedConvergence):
        ranked = {fname: 1 / len(files) for fname in files}
    ranked_definitions = defaultdict(float)
    for src in sorted(graph.nodes):
        edges = list(graph.out_edges(src, data=True))
        total = sum(data["weight"] for _source, _dest, data in edges)
        if not total:
            continue
        for _source, dst, data in edges:
            ranked_definitions[(dst, data["ident"])] += ranked[src] * data["weight"] / total
    result = []
    seen = set()
    for (fname, ident), _score in sorted(ranked_definitions.items(), key=lambda item: (-item[1], item[0])):
        for tag in sorted(definitions[(fname, ident)], key=lambda t: (t["line"], t["name"])):
            key = (fname, tag["line"], tag["name"])
            if key not in seen:
                result.append(tag)
                seen.add(key)
    for fname in files:
        for tag in tags_by_file[fname]:
            if tag["kind"] != "def":
                continue
            key = (fname, tag["line"], tag["name"])
            if key not in seen:
                result.append(tag)
                seen.add(key)
    # Focus symbols stay visible even if graph rank is low.
    ordered = sorted(enumerate(result), key=lambda pair: (pair[1]["name"] not in symbols, pair[1]["path"] not in focused, pair[0]))
    return [tag for _index, tag in ordered]
