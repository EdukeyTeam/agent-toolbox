"""Filtered lexical/symbol/path retrieval, measured priors and weighted RRF."""
from __future__ import annotations
import json
import math
from pathlib import PurePosixPath
import re
import sqlite3
from . import store
from .symbols import analyze, words, folded_text, split_identifier, stem, GENERIC
from .units import RetrievalError

DEPTH = 300
W_SYMBOL, W_PATH, W_FTS, W_SHADOW, W_VECTOR = 1., 1.5, 1., .55, 2.
# Ablation switches are explicit engine inputs, never corpus/question rules.
DEFAULT_ABLATIONS = frozenset()
COVERAGE_BASE, COVERAGE_SCALE, COVERAGE_POWER = .5, 1.5, 1.0
W_DOC_REFERENCE = 2.0
W_CONFIG_BEHAVIOR = .8
FTS_WEIGHTS = (4., 1.5, 1., 1., 0.)
_SOURCE_COMMENTS = re.compile(r"/\*[\s\S]*?\*/|//[^\n]*")


def comment_fragment(text, language):
    if language not in {"javascript", "typescript", "tsx", "java", "c", "cpp", "c_sharp", "go", "rust", "kotlin", "swift", "scala", "groovy", "dart"} or not text.strip():
        return False
    remaining = _SOURCE_COMMENTS.sub("", text).strip()
    if not remaining:
        return True
    lines = [line.strip() for line in remaining.splitlines() if line.strip()]
    return lines[-1] == "*/" and all(line.startswith("*") for line in lines)


def prior(path, provenance, doc_intent, exact, disabled):
    p = path.lower()
    value = 1.
    if "history" not in disabled and (re.search(r"(?:^|/)(?:changelog|changes|news|history|release[-_]notes)(?:[./_-]|$)",p) or "/repo-maps/" in "/"+p or re.search(r"(?:^|/)(?:reports?|artifacts|repomix|repo-mix|releases)/",p)):
        value *= .4
    if "tests" not in disabled and re.search(r"(?:^|/)(?:tests?|__tests__|fixtures?|playground)(?:/|_)|(?:\.test|\.spec)\.",p):
        value *= .6
    if "generated" not in disabled and (re.search(r"(?:^|/)(?:vendor|vendored|generated|node_modules)(?:/|$)",p) or re.search(r"\.min\.(?:js|css)$",p)):
        value *= .4
    if "docs" not in disabled and provenance == "docs" and doc_intent and not exact:
        value *= 1.25
    return value


def preserve_exact_window(ranked, protected):
    """Rescue displaced exact evidence without reordering a valid fused window."""
    from .assemble import candidate_window
    protected_ids = {r["id"] for r in protected}
    if protected_ids <= {r["id"] for r in candidate_window(ranked, 5)}:
        return ranked
    preferred = protected + [r for r in ranked if r["id"] not in protected_ids]
    chosen = {r["id"] for r in candidate_window(preferred, 5)}
    lexical = [r for r in ranked if r["lexical_score"] > 0]
    dense_only = [r for r in ranked if r["lexical_score"] <= 0]
    return [r for r in lexical if r["id"] in chosen] + [r for r in lexical if r["id"] not in chosen] + dense_only


def fts_candidates(con, name, expression, where, args, weights):
    """Let FTS stop at top-k, preserving the original deterministic tie order."""
    columns = ",".join(str(w) for w in weights)
    rows = con.execute(f"SELECT u.id,rank AS bm,f.path,u.start_line,u.unit_uid FROM {name} JOIN units u ON u.id={name}.rowid JOIN files f ON f.id=u.file_id WHERE {name} MATCH ? AND rank MATCH 'bm25({columns})' AND {where} ORDER BY rank LIMIT ?", (expression, *args, DEPTH + 1)).fetchall()
    if len(rows) > DEPTH and rows[DEPTH - 1]["bm"] == rows[DEPTH]["bm"]:
        # A cutoff through an equal-score group needs the full tie breaker.
        # This is uncommon, and avoids corpus-size-dependent ranking changes.
        return con.execute(f"SELECT u.id,bm25({name},{columns}) AS bm FROM {name} JOIN units u ON u.id={name}.rowid JOIN files f ON f.id=u.file_id WHERE {name} MATCH ? AND {where} ORDER BY bm,f.path,u.start_line,u.unit_uid LIMIT ?", (expression, *args, DEPTH)).fetchall()
    rows = rows[:DEPTH]
    rows.sort(key=lambda r: (r["bm"], r["path"], r["start_line"], r["unit_uid"]))
    return rows


def candidates(con, library, question, mode="lexical", vector_engine=None, kind=None, language=None, provider=None, ablations=()):
    disabled = frozenset(ablations)
    library_id = library["id"]
    name = store.fts_name(library_id)
    payload_name = store.fts_payload_name(con, library_id)
    original, secondary = analyze(question)
    filters = ["u.library_id=?", "u.searchable=1", "u.redacted=0"]
    args = [library_id]
    if kind:
        filters.append("f.kind=?")
        args.append(kind)
    if language:
        filters.append("u.language=?")
        args.append(language)
    where = " AND ".join(filters)
    original_set = set(original)
    identifiers = re.findall(r"(?<![\w])(?:[\w]+[.:][\w.:]+|[A-Za-z_]*[a-z][A-Z][\w]*|[A-Z][A-Za-z]*[A-Z][\w]*|[A-Z][a-z]{2,}|[\w]+_[\w]+)(?![\w])",question)
    identifiers = [i for i in identifiers if i.casefold() not in {"where","how","what","why","which","trace","http","ftp"}]
    if re.fullmatch(r"[\w$]+",question.strip()):
        identifiers = list(dict.fromkeys([*identifiers,question.strip()]))
    identifiers = list(dict.fromkeys(identifiers))[:32]
    explicit_names = set(re.findall(r"`+([\w.:$]+)(?:\(\))?`+", question))
    identifiers = list(dict.fromkeys([*identifiers, *sorted(explicit_names)]))[:32]
    single_name = bool(re.fullmatch(r"[\w$]+", question.strip()))
    exact_rows = []
    for ident in identifiers:
        leaf = re.split(r"[.:]",ident)[-1]
        explicit = single_name or ident in explicit_names or bool(re.search(r"[_:.]|[a-z][A-Z]", ident))
        matched = False
        # Indexed equality paths are cheap; qualified suffix matching occurs on
        # the bounded result set for this leaf, never arbitrary LIKE substrings.
        rows = con.execute(f"SELECT DISTINCT u.id,u.file_id,s.qualified_name,s.name,s.line FROM symbols s JOIN units u ON u.id=s.unit_id JOIN files f ON f.id=u.file_id WHERE {where} AND s.library_id=? AND s.name_fold=? ORDER BY s.line,s.path,u.unit_uid LIMIT ?",(*args,library_id,leaf.casefold(),DEPTH)).fetchall()
        matched_files = set()
        for row in rows:
            # An acronym in prose is not a case-insensitive API reference.
            # Explicit code notation still supports case-folded lookup.
            prose_capital = ident.istitle() and question.lstrip().startswith(ident)
            if (ident.isupper() or prose_capital) and row["name"] != leaf and not explicit:
                continue
            matched = True
            matched_files.add(row["file_id"])
            qualified = row["qualified_name"]
            score = 0 if qualified == ident else 1 if qualified.casefold() == ident.casefold() else 2 if qualified.endswith("."+ident) else 3 if row["name"] == ident else 4
            exact_rows.append((row["id"],score, row["line"]))
        # A class/name query anchors descendant parts as well as its declaration.
        # Otherwise a tiny class header outranks the implementing constructor.
        if not matched:
            continue
        prefix = ident.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        anchored = con.execute(f"SELECT u.id,u.title,u.start_line FROM units u INDEXED BY units_file_span JOIN files f ON f.id=u.file_id WHERE {where} AND u.file_id IN (" + ",".join("?" for _ in matched_files) + ") AND u.kind='code-definition' AND (u.title=? OR u.title LIKE ? ESCAPE '\\') ORDER BY u.start_line,f.path,u.unit_uid LIMIT ?",(*args,*sorted(matched_files),ident,prefix+".%",DEPTH)).fetchall()
        exact_rows.extend((row["id"],4,row["start_line"]) for row in anchored)
    exact_rows.sort(key=lambda r:(r[1],r[2],r[0]))
    exact = bool(exact_rows)
    doc_intent = bool(re.search(r"\b(example|usage|tutorial|guide|configure|install)\b|how (?:do i|can i|to)\b",question,re.I))
    ranks = {}
    def add(channel, rows, weight):
        for rank, row in enumerate(rows,1):
            uid = row[0]
            entry = ranks.setdefault(uid,{"score":0.,"channels":{}})
            if channel not in entry["channels"]:
                entry["score"] += weight/(60+rank)
                entry["channels"][channel] = rank
    if mode != "semantic":
        if "symbols" not in disabled:
            add("symbol",exact_rows,W_SYMBOL)
        if original:
            expression = " OR ".join('"'+w.replace('"','')+'"' for w in original)
            rows = fts_candidates(con, name, expression, where, args, FTS_WEIGHTS)
            add("fts",rows,W_FTS)
            if "shadow" not in disabled:
                shadow = list(dict.fromkeys(stem(w) for w in [*original,*secondary] if w not in GENERIC))
                expression = "stemmed : (" + " OR ".join('"'+w.replace('"','')+'"' for w in shadow) + ")" if shadow else None
                if expression:
                    rows = fts_candidates(con, name, expression, where, args, (0.,0.,0.,0.,1.))
                    add("shadow",rows,W_SHADOW)
        if "paths" not in disabled:
            path_tokens = [p.removeprefix("./").strip(".") for p in re.findall(r"[\w./-]+",question)]
            paths = list(dict.fromkeys(p for p in path_tokens if p and ("/" in p or "." in p or p in explicit_names or single_name)))[:16]
            for path in paths:
                # Resolve paths over files first, not once per unit in a large
                # library. The span index then fetches only matching files.
                rows = con.execute(f"SELECT u.id,f.path FROM files f JOIN units u INDEXED BY units_file_span ON u.file_id=f.id WHERE {where} AND f.library_id=? AND (f.path=? OR f.path LIKE ? ESCAPE '\\') ORDER BY length(f.path),u.id LIMIT ?",(*args,library_id,path,"%/"+path.replace("\\","\\\\").replace("%","\\%").replace("_","\\_"),DEPTH)).fetchall()
                add("path",rows,W_PATH)
    elif exact_rows:
        add("symbol",exact_rows,W_SYMBOL)
    used_engine = None
    if mode in {"semantic","hybrid"}:
        if provider is None:
            raise RetrievalError("Semantic mode requires explicitly enabled embeddings; index with a provider or use lexical", "model_unavailable", 503)
        from .vectors import top_k, cached_top_k, available_engines
        vector = provider.embed_query(question)
        embedded = json.loads(library["embedding_json"])
        if embedded.get("identity") != provider.identity:
            raise RetrievalError("Embedding identity changed; reindex with this identity", "model_identity_mismatch",409)
        def vector_rows():
            return con.execute(f"SELECT v.unit_id,v.embedding FROM unit_vectors v JOIN units u ON u.id=v.unit_id JOIN files f ON f.id=u.file_id WHERE {where}",args)
        try:
            selected_engine = vector_engine or "auto"
            if selected_engine == "auto":
                engines = available_engines()
                selected_engine = "sqlite-vec" if "sqlite-vec" in engines else engines[-1]
            if selected_engine == "numpy":
                # The model already lives for the server's lifetime. Cache its
                # immutable, exact vector snapshot under the published generation.
                key = (store.metadata(con)["database_uuid"], library_id, library["generation"], kind, language)
                dense = cached_top_k(vector, vector_rows, DEPTH, provider, key, cache=not con.total_changes)
            else:
                dense = top_k(vector, vector_rows(), DEPTH, selected_engine)
        except (ImportError,OSError,AttributeError,ValueError,sqlite3.Error) as exc:
            raise RetrievalError("Vector scan unavailable or invalid; restore the selected adapter or use lexical mode","vector_adapter_unavailable",503) from exc
        add("vector",dense,W_VECTOR)
        used_engine = vector_engine or "auto"
    if not ranks:
        return [], used_engine
    # Retrieve only this library's bounded candidate union, in batches under
    # SQLite's conservative variable limit (Windows older builds included).
    rows = []
    ids = sorted(ranks)
    for first in range(0,len(ids),400):
        batch = ids[first:first+400]
        rows.extend(con.execute(f"SELECT u.*,f.path,f.root_id,f.hash AS file_hash,f.kind AS provenance,f.encoding,f.status,f.mtime_ns,f.size,ft.identifier_tokens AS split_tokens,ft.stemmed AS stem_tokens FROM units u JOIN files f ON f.id=u.file_id JOIN {payload_name} ft ON ft.rowid=u.id WHERE u.id IN ("+",".join("?" for _ in batch)+") AND u.library_id=?",(*batch,library_id)).fetchall())
    result = []
    query_stems = {t: stem(t) for t in original_set}
    query_pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in sorted(original_set)) + r")(?!\w)") if original_set else None
    for row in rows:
        item = dict(row)
        item.update(ranks[row["id"]])
        split = set(row["split_tokens"].split())
        stems = set(row["stem_tokens"].split())
        # Only unresolved query terms need raw whole-word checks. Constructing
        # every token of a large generated/minified unit dominated query time.
        missing = original_set - split
        raw = folded_text((row["text"] or "") + " " + row["title"] + " " + json.loads(row["header_json"])["text"] + " " + row["description"]) if missing else ""
        tokens = set(query_pattern.findall(raw)) if missing else set()
        coverage = sum(1. if t in tokens or t in split else .8 if query_stems[t] in stems else 0 for t in original_set) / max(1,len(original_set))
        # Preserve the complete lexical pipeline before fusing dense evidence.
        # Dense-only rows must neither acquire a lexical coverage penalty nor
        # disable the lexical documentation-to-definition reference channel.
        dense_score = W_VECTOR / (60 + item["channels"]["vector"]) if "vector" in item["channels"] else 0.
        item["score"] = max(0., item["score"] - dense_score)
        if "coverage" not in disabled:
            item["score"] *= COVERAGE_BASE + COVERAGE_SCALE*coverage**COVERAGE_POWER
        bias = prior(row["path"],row["provenance"],doc_intent,exact,disabled)
        if "comments" not in disabled and not exact and not doc_intent and row["provenance"] == "code" and re.match(r"(?:where|trace)\b", question, re.I) and comment_fragment(row["text"] or "", row["language"]):
            # New declaration boundaries can isolate JSDoc from its field.
            # Location/flow questions need implementing code ahead of these
            # fragments; exact-symbol and usage questions keep normal evidence.
            bias *= .5
        item["score"] *= bias
        item["vector_score"] = dense_score * bias
        if "config-behavior" not in disabled and row["kind"]=="config" and re.match(r"(?:where|trace)\b",question,re.I):
            # Labels/settings are useful context, but a location/flow question
            # should not bury executable behavior beneath resource-bundle labels.
            item["score"] *= W_CONFIG_BEHAVIOR
            item["vector_score"] *= W_CONFIG_BEHAVIOR
        item["coverage"] = coverage
        result.append(item)
    result.sort(key=lambda r:(-r["score"],r["path"],r["start_line"],r["unit_uid"]))
    lexical_result = [r for r in result if r["score"] > 0]
    if mode != "semantic" and not exact and not doc_intent and kind != "docs" and "references" not in disabled and not any(r["kind"]=="code-definition" for r in lexical_result[:3]):
        # Explicit names in relevant documentation bridge prose intent to code.
        # Import/preamble windows are not definition evidence and must not block
        # the bridge merely because their file has code provenance.
        # No inferred names or corpus-specific vocabulary: the referenced symbol
        # must exist in this library. Keep this bounded and independently ablatable.
        referenced = set()
        by_id = {r["id"]:r for r in result}
        docs = [r for r in lexical_result if r["provenance"]=="docs"][:3]
        for doc_rank,doc in enumerate(docs,1):
            for token in re.findall(r"`+([^`\n]+)`+",(doc["text"] or "")[:1400]):
                token = token.removesuffix("()")
                if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[\w$]+)*",token) or not ("_" in token or any(c.isupper() for c in token)):
                    continue
                leaf = token.rsplit(".",1)[-1]
                if leaf in referenced or len(referenced)>=6:
                    continue
                referenced.add(leaf)
                refs = con.execute("SELECT DISTINCT s.qualified_name,s.unit_id,u.file_id FROM symbols s JOIN units u ON u.id=s.unit_id WHERE s.library_id=? AND s.name_fold=? ORDER BY s.qualified_name LIMIT 3",(library_id,leaf.casefold())).fetchall()
                for ref in refs:
                    ref_name = ref["qualified_name"]
                    escaped = ref_name.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
                    related = con.execute(f"SELECT u.*,f.path,f.root_id,f.hash AS file_hash,f.kind AS provenance,f.encoding,f.status,f.mtime_ns,f.size,ft.identifier_tokens AS split_tokens,ft.stemmed AS stem_tokens FROM units u JOIN files f ON f.id=u.file_id JOIN {payload_name} ft ON ft.rowid=u.id WHERE {where} AND u.file_id=? AND (u.id=? OR u.title=? OR u.title LIKE ? ESCAPE '\\') LIMIT 200",(*args,ref["file_id"],ref["unit_id"],ref_name,escaped+".%")).fetchall()
                    scored = []
                    for row in related:
                        item = dict(row)
                        tokens = set(row["split_tokens"].split()) | set(words(row["title"]))
                        stems = set(row["stem_tokens"].split())
                        cov = sum(1. if t in tokens else .8 if query_stems[t] in stems else 0 for t in original_set)/max(1,len(original_set))
                        score = W_DOC_REFERENCE * doc["score"] * (.5+cov) / doc_rank
                        if row["qualified_name"] and row["title"] != ref_name:
                            score *= 1.5
                        score *= prior(row["path"],row["provenance"],False,False,disabled)
                        scored.append((score,item,cov))
                    for score,item,cov in sorted(scored,key=lambda x:(-x[0],x[1]["path"],x[1]["start_line"]))[:3]:
                        if item["id"] in by_id:
                            item = by_id[item["id"]]
                            item["score"] = max(item["score"],score)
                            item["channels"]["doc-reference"] = doc_rank
                        else:
                            item.update(score=score,coverage=cov,channels={"doc-reference":doc_rank})
                            result.append(item)
                            by_id[item["id"]] = item
        result.sort(key=lambda r:(-r["score"],r["path"],r["start_line"],r["unit_uid"]))
    anchored = mode == "hybrid" and any("symbol" in r["channels"] or "path" in r["channels"] for r in result)
    protected = []
    if anchored:
        from .assemble import candidate_window
        # Reserve the named source evidence in the default five-result lexical
        # window. Unbounded class descendants must not fill the entire prefix.
        protected = [r for r in candidate_window((r for r in result if r["score"] > 0), 5) if "symbol" in r["channels"] or "path" in r["channels"]]
    for item in result:
        item["lexical_score"] = item["score"]
        item["score"] += item.get("vector_score", 0.)
    # Named source evidence precedes dense-only neighbors. Within that bound,
    # keep fusion order unless it actually displaces a leading exact hit.
    result.sort(key=lambda r:((0 if r["lexical_score"] > 0 else 1) if anchored else 0, -r["score"],r["path"],r["start_line"],r["unit_uid"]))
    if protected:
        result = preserve_exact_window(result, protected)
    return result, used_engine
