"""Application orchestration for source queries, expansion and local libraries."""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
from repo_files import split_source_lines
import sqlite3
import threading
from . import assemble, search, store
from .decode import read_source, secret_spans
from .discover import revision, safe_path
from .freshness import provider_for, refresh
from .units import EMPTY, RetrievalError, estimate, canonical


def database_path(con):
    return Path(con.execute("PRAGMA database_list").fetchone()[2])


def embedding_coverage(con, library, kind=None, language=None):
    if json.loads(library["embedding_json"]).get("config", {}).get("provider", "none") == "none":
        return 0.0
    filters, args = ["u.library_id=?", "u.searchable=1", "u.redacted=0"], [library["id"]]
    for column, value in (("f.kind", kind), ("u.language", language)):
        if value:
            filters.append(column + "=?")
            args.append(value)
    total, present = con.execute("SELECT count(*),count(v.unit_id) FROM units u JOIN files f ON f.id=u.file_id LEFT JOIN unit_vectors v ON v.unit_id=u.id WHERE " + " AND ".join(filters), args).fetchone()
    return present / total if total else 1.0


def query(con, question, mode="lexical", rerank=None, limit=5, vector_engine=None, *, library_id=None, kind=None, language=None, tokens=None, refresh_policy="auto", provider_cache=None, ablations=(), explain=False, output_format="json", pretty=True, newline=True, _restart=False):
    if not isinstance(question,str) or not question.strip() or len(question)>8000:
        raise RetrievalError("Query must contain 1-8000 characters")
    if mode not in {"lexical","semantic","hybrid"} or rerank not in {None,"lexical-symbol"}:
        raise RetrievalError("Cross-encoder is not supported in v1; use hybrid" if rerank=="cross-encoder" else "Unknown mode or reranker")
    if not 1 <= limit <= 50 or refresh_policy not in {"auto","off","strict"} or kind not in {None,"code","docs"}:
        raise RetrievalError("Invalid query limit, filter or refresh policy")
    if vector_engine not in {None,"auto","stdlib","numpy","sqlite-vec"}:
        raise RetrievalError("Unknown vector engine")
    if tokens is not None and not 256 <= tokens <= 32000:
        raise RetrievalError("Token budget must be 256..32000")
    provider, owned_provider, changed = None, False, set()
    caller_transaction = con.in_transaction
    try:
        with store.snapshot(con):
            lib = store.library(con,library_id)
            embedded = json.loads(lib["embedding_json"])
            config = embedded.get("config",{})
            if mode != "lexical" and config.get("provider") == "openai-compatible":
                from .embed import is_loopback_url
                if not is_loopback_url(config.get("base_url", "")):
                    raise RetrievalError("Remote embeddings are permitted only for explicit indexing; use lexical mode or configure a verified local embedder.", "remote_query_forbidden", 403)
            identity = lib["id"] + "/" + canonical({"config":config, "identity":embedded.get("identity")})
            existing_provider = provider_cache.get(identity) if provider_cache is not None else None
            coverage_key = (store.metadata(con)["database_uuid"], lib["id"], lib["generation"], kind, language)
            cached_coverage = getattr(existing_provider, "_retrieval_coverage", None) if existing_provider and not con.total_changes else None
            coverage = cached_coverage[1] if cached_coverage and cached_coverage[0] == coverage_key else embedding_coverage(con, lib, kind, language)
            if mode == "semantic" and coverage < 1 and config.get("provider", "none") != "none":
                raise RetrievalError("Embeddings are incomplete; refresh pending vectors or rebuild the index, or use lexical mode.", "embedding_incomplete", 409)
            if mode != "lexical":
                if config.get("provider","none") == "none":
                    raise RetrievalError("Embeddings are disabled for this library; use lexical", "model_unavailable",503)
                if provider_cache is not None:
                    prefix = lib["id"] + "/"
                    if identity not in provider_cache:
                        provider_cache[identity] = provider_for(config)
                        # Publication timestamps and truncation counters do not
                        # reload a warm model. A real identity/config change
                        # replaces and closes only this library's old provider.
                        for old_key in list(provider_cache):
                            if old_key.startswith(prefix) and old_key != identity:
                                provider_cache.pop(old_key).close()
                    provider = provider_cache[identity]
                else:
                    provider,owned_provider = provider_for(config),True
                if not con.total_changes:
                    provider._retrieval_coverage = (coverage_key, coverage)
            ranked,used_engine = search.candidates(con,lib,question,mode,vector_engine,kind,language,provider,ablations)
            # Bounded overfetch: no corpus inventory/stat sweep during a query.
            candidates = assemble.candidate_window(ranked, max(20,limit*3))
            items,changed,unavailable = assemble.verify(candidates,lib,refresh_policy)
            current_revisions,revision_cache = {},{}
            for root in json.loads(lib["roots_json"]):
                identity = str(Path(root.get("index_path") or root["path"]).resolve())
                if identity not in revision_cache:
                    revision_cache[identity] = revision(Path(root["path"]))
                current_revisions[root["id"]] = revision_cache[identity]
            revision_changed = any(current_revisions[r["id"]] != r["revision"] for r in json.loads(lib["roots_json"]))
            trigger_changed = False
            for root in json.loads(lib["roots_json"]):
                trigger = Path(root.get("index_path") or root["path"])
                try:
                    stamp = trigger.stat().st_mtime_ns
                    expected = root.get("index_mtime_ns",0) if root.get("index_path") else root.get("directory_mtime_ns",0)
                    trigger_changed |= bool(expected and stamp != expected)
                except OSError:
                    trigger_changed = True
            if (revision_changed or trigger_changed) and refresh_policy=="strict":
                raise RetrievalError("Repository revision changed; run refresh", "source_changed",409)
            response = assemble.pack(items,lib,mode,rerank,used_engine,limit,tokens,question,changed,unavailable)
            response["coverage"]["embeddingCoverage"] = coverage
            if mode == "hybrid" and coverage < 1:
                response["warnings"].append("Embeddings are incomplete; rebuild into a new database to restore full hybrid coverage.")
            if config.get("provider") == "openai-compatible" and coverage < 1:
                from .embed import is_loopback_url
                if not is_loopback_url(config.get("base_url")):
                    response["warnings"].append("Remote vectors pending; approve the endpoint and run an explicit refresh with --allow-remote-embeddings")
            if revision_changed or trigger_changed:
                response["warnings"].append("Repository change trigger fired; run refresh to update inventory and recorded revisions.")
                response["freshness"]["state"] = "stale"
            if explain:
                response["channels"] = {r["unit_uid"]:r["channels"] for r in candidates}
        if changed and refresh_policy=="auto" and len(changed)<=10 and not _restart and not caller_transaction:
            try:
                refresh(database_path(con),lib["id"],candidate_paths=changed,verify_all=True,timeout=con.execute("PRAGMA busy_timeout").fetchone()[0]/1000)
            except (RetrievalError,RuntimeError,sqlite3.Error):
                response["warnings"].append("Automatic candidate refresh unavailable; run refresh explicitly.")
            else:
                return query(con,question,mode,rerank,limit,vector_engine,library_id=lib["id"],kind=kind,language=language,tokens=tokens,refresh_policy=refresh_policy,provider_cache=provider_cache,ablations=ablations,explain=explain,output_format=output_format,pretty=pretty,newline=newline,_restart=True)
        return assemble.fit(response,tokens,question,limit,output_format,pretty=pretty,newline=newline)
    finally:
        if provider and owned_provider:
            provider.close()


def resolve(con, library_name, question="", limit=10):
    if not library_name or len(library_name)>500 or not 1<=limit<=50:
        raise RetrievalError("Library name and limit are required")
    store.validate(con)
    terms = set(library_name.casefold().split())
    result = []
    for row in con.execute(f"SELECT {store.LIBRARY_COLUMNS} FROM libraries ORDER BY id"):
        name = library_name.casefold()
        exact = row["id"].casefold()==name or row["title"].casefold()==name or row["id"].rsplit("/",1)[-1].casefold()==name
        score = 100*exact+sum(t in (row["id"]+" "+row["title"]+" "+row["description"]).casefold() for t in terms)
        if not score:
            continue
        count,total = con.execute("SELECT count(*),coalesce(sum(token_estimate),0) FROM units WHERE library_id=? AND searchable=1",(row["id"],)).fetchone()
        roots = json.loads(row["roots_json"])
        item = {"id":row["id"],"title":row["title"],"description":row["description"],"branch":roots[0]["revision"],"lastUpdateDate":row["refreshed_at"],"state":"finalized","totalTokens":total,"totalSnippets":count}
        result.append((score,item))
    return [r[1] for r in sorted(result,key=lambda r:(-r[0],r[1]["id"]))[:limit]]


def status(con, library_id=None, verify_all=False):
    meta = store.validate(con)
    libraries = [con.execute("SELECT * FROM libraries WHERE id=?",(store.library(con,library_id)["id"],)).fetchone()] if library_id else con.execute("SELECT * FROM libraries ORDER BY id").fetchall()
    result = []
    for lib in libraries:
        counts = dict(con.execute("SELECT status,count(*) FROM files WHERE library_id=? GROUP BY status",(lib["id"],)))
        row = {"id":lib["id"],"generation":lib["generation"],"roots":json.loads(lib["roots_json"]),"counts":counts,"scope":json.loads(lib["scope_json"]),"embedding":json.loads(lib["embedding_json"]),"lastReport":json.loads(lib["last_report_json"]),"capabilities":{"fts5":True,"parser":json.loads(lib["parser_json"])["tier"]},"freshness":"not-audited"}
        row["embeddingCoverage"] = embedding_coverage(con, lib)
        if verify_all:
            from .freshness import assert_fresh
            try:
                assert_fresh(con,{"library_id":lib["id"]})
                row["freshness"] = "fresh"
            except RetrievalError:
                row["freshness"] = "stale"
        result.append(row)
    return {"indexVersion":8,"databaseId":meta["database_uuid"],"libraries":result}


def expand(con, *, library_id=None, unit_id=None, path=None, root_id=None, start_line=None, end_line=None, tokens=4000, output_format="json", pretty=True, newline=True):
    with store.snapshot(con):
        lib = store.library(con,library_id)
        if unit_id and any(v is not None for v in (path,root_id,start_line,end_line)) or not unit_id and any(v is None for v in (path,root_id,start_line,end_line)):
            raise RetrievalError("Provide exactly a unit ID or root/path/start/end", "invalid_range")
        row = None
        if unit_id:
            row = con.execute("SELECT u.*,f.path,f.root_id,f.hash AS file_hash,f.kind AS provenance,f.encoding FROM units u JOIN files f ON f.id=u.file_id WHERE u.unit_uid=? AND u.library_id=?",(unit_id,lib["id"])).fetchone()
            if row is None:
                raise RetrievalError("Unit not found or replaced; query again", "unit_not_found",404)
            row = dict(row)
            path,root_id,start_line,end_line = row["path"],row["root_id"],row["start_line"],row["end_line"]
        if not 1<=start_line<=end_line or end_line-start_line+1>2000:
            raise RetrievalError("Invalid range or range exceeds 2000 lines", "range_too_large",413)
        file = con.execute("SELECT * FROM files WHERE library_id=? AND root_id=? AND path=?",(lib["id"],root_id,path)).fetchone()
        if file is None:
            raise RetrievalError("Indexed file not found", "unit_not_found",404)
        if con.execute("SELECT 1 FROM units WHERE file_id=? AND redacted=1 AND start_line<=? AND end_line>=? LIMIT 1", (file["id"],end_line,start_line)).fetchone():
            raise RetrievalError("Secret-bearing source range withheld", "secret_range",403)
        roots = {r["id"]:r for r in json.loads(lib["roots_json"])}
        scope = json.loads(lib["scope_json"])
        live = read_source(Path(roots[root_id]["path"]),path,scope["encodings"],scope["max_file_bytes"])
        if live.sha256!=file["hash"]:
            raise RetrievalError("Source changed; refresh and query again", "unit_stale",409)
        if not scope["no_secret_scan"] and any(a<=end_line and b>=start_line for a,b in secret_spans(live.text)):
            raise RetrievalError("Secret-bearing source range withheld", "secret_range",403)
        lines = split_source_lines(live.text)
        if end_line>len(lines):
            raise RetrievalError("End line exceeds source", "invalid_range")
        if row is None:
            row = {"unit_uid":"range", "kind":"code-block", "language":file["language"],"title":path,"description":"", "header_json":json.dumps({"text":path}),"header_spans_json":"[]", "start_line":start_line,"end_line":end_line,"text":"\n".join(lines[start_line-1:end_line]),"path":path,"root_id":root_id,"provenance":file["kind"],"file_hash":file["hash"],"encoding":file["encoding"],"transformed":False,"cell_index":None,"part_index":1,"part_count":1}
        if row.get("searchable") == 0 and not row.get("redacted"):
            row["text"] = "\n".join(lines[start_line-1:end_line])
        row["score"] = 1.
        if row.get("redacted"):
            raise RetrievalError("Secret-bearing source range withheld", "secret_range",403)
        item = assemble.native_item(row,lib,roots,live,"fresh")
        response = assemble.pack([item],lib,"lexical",None,None,1,tokens,"",(),0)
        response["expanded"] = True
        return assemble.fit(response,tokens,"",1,output_format,pretty=pretty,newline=newline,exact=True)
