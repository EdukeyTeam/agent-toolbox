"""Atomic streaming indexing and candidate-only query refresh."""
from __future__ import annotations
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from . import store
from .chunk import chunk_file, parser_tier
from .decode import read_source
from .discover import Root, inventory, normalize_excludes, roots_for, revision
from .units import DEFAULT_CHUNK_CHARS, RetrievalError, canonical, digest


def provider_for(config, *, download=False):
    if not config or config.get("provider", "none") == "none":
        return None
    try:
        from .embed import EmbedConfig, create_provider
        clean = {k:v for k,v in config.items() if k in EmbedConfig.__dataclass_fields__}
        clean["allow_download"] = bool(download)
        return create_provider(EmbedConfig(**clean))
    except (ImportError, OSError) as exc:
        raise RetrievalError("Optional embedding provider unavailable; use lexical mode", "provider_unavailable", 503) from exc
    except RuntimeError as exc:
        raise RetrievalError(str(exc), "consent_required" if "consent" in str(exc).lower() else "model_unavailable", 403) from exc


def embedding_config(embed_model=None, model_revision=None, model_cache=None, embedding_runtime=None, **kwargs):
    enabled = kwargs.get("embed_provider") or ("transformers-js" if embed_model else "none")
    if enabled == "none":
        return {"provider":"none"}
    try:
        from .embed import EmbedConfig, config_from_env
        # Environment supplies defaults only after an explicit enablement.
        base = config_from_env(EmbedConfig(provider=enabled))
        if kwargs.get("embed_base_url") is not None and kwargs["embed_base_url"] != base.base_url and kwargs.get("embed_api_key_env") is None:
            base = replace(base, api_key_env=None)
        replacements = {"model":embed_model, "revision":model_revision, "cache_dir":str(model_cache) if model_cache else None, "runtime_dir":str(embedding_runtime) if embedding_runtime else None, "base_url":kwargs.get("embed_base_url"), "api_key_env":kwargs.get("embed_api_key_env"), "model_dir":str(kwargs["model_dir"]) if kwargs.get("model_dir") else None}
        base = replace(base, **{k:v for k,v in replacements.items() if v is not None}, provider=enabled, allow_remote=bool(kwargs.get("allow_remote_embeddings")), allow_download=False)
        if enabled == "transformers-js" and base.model == "Xenova/all-MiniLM-L6-v2" and not base.revision:
            base = replace(base,revision="751bff37182d3f1213fa05d7196b954e230abad9")
        return asdict(base)
    except (ImportError, OSError, RuntimeError) as exc:
        raise RetrievalError("Embedding configuration unavailable", "provider_unavailable", 503) from exc


def index(root, database, library_id, docs_root=None, embed_model=None, model_cache=None, embedding_runtime=None, *, model_revision=None, vector_engine="stdlib", reranker_model=None, reranker_revision=None, chunk_chars=DEFAULT_CHUNK_CHARS, excludes=(), docs_roots=(), includes=(), encodings=(), no_secret_scan=False, parser="auto", max_files=0, max_units=0, max_file_bytes=2_000_000, discovery_limit=2_000_000, title=None, description=None, jobs=1, verify_all=False, _timeout=5.0, _candidate_paths=None, _saved=None, **kwargs):
    started = time.monotonic()
    if _candidate_paths is not None:
        _candidate_paths = set(_candidate_paths)
    if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", library_id):
        raise RetrievalError("Library ID must be /namespace/name")
    if not 128 <= chunk_chars <= 12000 or max_file_bytes < 1 or discovery_limit < 1 or jobs < 1 or max_files < 0 or max_units < 0:
        raise RetrievalError("Invalid chunk or resource bounds")
    if reranker_model or reranker_revision:
        raise RetrievalError("Cross-encoder is not supported in v1; use hybrid")
    if vector_engine not in {"stdlib", "auto", "numpy", "sqlite-vec"}:
        raise RetrievalError("Unknown vector engine")
    excludes, includes = normalize_excludes(excludes), normalize_excludes(includes)
    if isinstance(encodings, str):
        encodings = tuple(s.strip() for s in encodings.split(",") if s.strip())
    import codecs
    for encoding in encodings:
        try:
            codecs.lookup(encoding)
        except LookupError as exc:
            raise RetrievalError("Unknown configured encoding") from exc
    roots = roots_for(Path(root) if root is not None else None, [*([Path(docs_root)] if docs_root else []), *(Path(p) for p in docs_roots)])
    database = Path(database).resolve()
    for source in roots:
        boundary = Path(source.path)
        for location in (database, model_cache, embedding_runtime, kwargs.get("model_dir")):
            if location and Path(location).resolve().is_relative_to(boundary):
                raise RetrievalError("Database, models and runtime must be outside indexed roots", "invalid_scope")
    config = _saved if _saved is not None else embedding_config(embed_model, model_revision, model_cache, embedding_runtime, **kwargs)
    scope = {"excludes":list(excludes), "includes":list(includes), "encodings":list(encodings), "no_secret_scan":no_secret_scan, "chunk_chars":chunk_chars, "max_file_bytes":max_file_bytes, "discovery_limit":discovery_limit, "max_files":max_files, "max_units":max_units, "vector_engine":vector_engine, "parser":parser}
    tier = parser_tier(parser)
    parser_config = {"version":8, "chunker_revision":2, "tier":tier, "chunk_chars":chunk_chars, "encodings":list(encodings), "scan":not no_secret_scan}
    fingerprint = digest(canonical(parser_config).encode())
    if database.exists():
        with store.connect(database) as check:
            # A failed first publication rolls back the schema, but SQLite
            # still leaves an empty database file. It is safe to initialize.
            if check.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                store.validate(check)
    database.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(database, timeout=_timeout, isolation_level=None)
    con.row_factory = sqlite3.Row
    provider = None
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("BEGIN IMMEDIATE")
        store.initialize(con)
        old = con.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
        if old:
            old_roots = json.loads(old["roots_json"])
            if [(r["path"],r["role"]) for r in old_roots] != [(r.path,r.role) for r in roots]:
                raise RetrievalError("Library roots differ; use a new library ID", "invalid_scope")
            if _candidate_paths is not None:
                roots = [Root(**r) for r in old_roots]
            if _saved is None and embed_model is None and not kwargs.get("embed_provider"):
                config = json.loads(old["embedding_json"]).get("config", {"provider":"none"})
        embedding_changed = old is None or json.loads(old["embedding_json"]).get("config", {"provider":"none"}) != config
        embedding_enabled = config.get("provider", "none") != "none"
        defer_embeddings = embedding_enabled and _candidate_paths is not None
        if embedding_enabled and embedding_changed and not defer_embeddings:
            provider = provider_for(config, download=kwargs.get("download_model", False))
        stamp = store.now()
        generation = old["generation"] if old else 1
        initial = (library_id,title or (old["title"] if old else library_id.rsplit("/",1)[-1]), description if description is not None else old["description"] if old else "Local source and documentation", "mixed" if len({r.role for r in roots}) > 1 else roots[0].role, canonical([asdict(r) for r in roots]),canonical(scope),canonical(parser_config),old["embedding_json"] if old and not embedding_changed else canonical({"config":config}),generation,"",old["indexed_at"] if old else stamp,stamp,"{}")
        con.execute("INSERT INTO libraries(id,title,description,kind,roots_json,scope_json,parser_json,embedding_json,generation,corpus_hash,indexed_at,refreshed_at,last_report_json) VALUES(" + ",".join("?" for _ in initial) + ") ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,roots_json=excluded.roots_json,scope_json=excluded.scope_json,parser_json=excluded.parser_json,embedding_json=excluded.embedding_json", initial)
        store.create_library_fts(con, library_id)
        changed, added, deleted, metadata_only, eligible, counters = 0, 0, 0, 0, 0, {}
        seen, actions, pending = set(), [], []
        truncated = 0
        dimension = json.loads(old["embedding_json"]).get("identity",{}).get("dimension") if old and not embedding_changed else None
        identity = None
        def flush():
            nonlocal truncated, dimension, identity, provider
            if not pending:
                return
            if provider is None:
                provider = provider_for(config,download=kwargs.get("download_model",False))
            from .vectors import pack, normalize
            vectors = provider.embed_documents([text for _,text in pending])
            if len(vectors) != len(pending):
                raise RetrievalError("Embedding count mismatch", "embedding_invalid", 409)
            for (uid,text), vector in zip(pending,vectors,strict=True):
                blob = pack(normalize(vector))
                if dimension is not None and len(blob) != dimension * 4:
                    raise RetrievalError("Embedding dimension changed", "embedding_invalid", 409)
                dimension = len(blob)//4
                con.execute("INSERT OR REPLACE INTO unit_vectors VALUES(?,?,?,?,?,?)", (uid,blob,digest(text.encode()),None,int(len(text)>config.get("max_input_chars",8000)),stamp))
            identity = dict(provider.identity)
            truncated = provider.truncated
            pending.clear()
        if _candidate_paths is None:
            candidates = inventory(roots, excludes, includes, discovery_limit, counters)
        else:
            from .discover import classify, safe_path
            def changed_candidates():
                for root_id, rel in _candidate_paths:
                    owner = next(r for r in roots if r.id == root_id)
                    try:
                        path = safe_path(Path(owner.path),rel)
                        if path.is_file():
                            kind,language,fmt = classify(rel,owner.role)
                            yield owner,rel,kind,language,fmt,path.stat()
                    except (RetrievalError, OSError):
                        continue
            candidates = changed_candidates()
        for owner, rel, kind, language, fmt, stat in candidates:
            eligible += 1
            if eligible % 500 == 0:
                import sys
                print(f"Indexing {library_id}: {eligible} files processed",file=sys.stderr,flush=True)
            seen.add((owner.id,rel))
            previous = con.execute("SELECT * FROM files WHERE library_id=? AND root_id=? AND path=?", (library_id,owner.id,rel)).fetchone()
            same_parser = previous is not None and previous["parser_fingerprint"] == fingerprint
            vectors_pending = previous is not None and previous["embedding_status"] in {"pending", "error"}
            stat_same = previous is not None and previous["size"] == stat.st_size and previous["mtime_ns"] == stat.st_mtime_ns
            if stat_same and same_parser and not embedding_changed and not vectors_pending and not verify_all:
                continue
            decoded, drafts, reason, status, fallback = None, [], None, "indexed", None
            try:
                decoded = read_source(Path(owner.path),rel,encodings,max_file_bytes)
                if Path(rel).suffix.lower() == ".txt" and owner.role == "code" and (re.search(r"(?m)^\.\.\s+\w+::", decoded.text) or re.search(r"(?m)^\S[^\n]*\n(?:={3,}|-{3,}|~{3,})\s*$", decoded.text)):
                    kind, language, fmt = "docs", "rst", "rst"
                if previous is not None and decoded.sha256 == previous["hash"] and same_parser and not embedding_changed and not vectors_pending:
                    con.execute("UPDATE files SET size=?,mtime_ns=? WHERE id=?",(stat.st_size,stat.st_mtime_ns,previous["id"]))
                    metadata_only += 1
                    actions.append({"rootId":owner.id,"path":rel,"action":"metadata-only"})
                    continue
                large = stat.st_size > max_file_bytes
                drafts, fallback = chunk_file(decoded.text,rel,"text" if large else language,"code" if large else fmt,chunk_chars,"0" if large else tier,not no_secret_scan)
                if large:
                    fallback = "large-file-window-split"
                    drafts = [replace(u, language=language) for u in drafts]
                status = "redacted" if any(u.redacted for u in drafts) else "indexed"
            except RetrievalError as exc:
                status = "binary" if exc.code == "binary" else "unreadable" if exc.code == "source_unreadable" else "skipped"
                reason = str(exc)
            if previous:
                store.delete_file(con,library_id,previous["id"])
                changed += 1
            else:
                added += 1
            action = "changed" if previous else "added"
            actions.append({"rootId":owner.id,"path":rel,"action":action,"status":status})
            file_tier = tier if decoded is not None and fmt == "code" and language not in {"text", "sql"} and fallback in {None, "error-span-fallback"} else "0"
            file_reason = reason or fallback
            if decoded is not None and decoded.assumed:
                file_reason = ((file_reason + "; ") if file_reason else "") + "assumed-encoding:" + decoded.encoding
            file_id = con.execute("INSERT INTO files(library_id,root_id,kind,path,hash,size,mtime_ns,encoding,language,format,status,status_reason,parser_tier,parser_fingerprint,embedding_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(library_id,owner.id,kind,rel,decoded.sha256 if decoded else None,stat.st_size,stat.st_mtime_ns,decoded.encoding if decoded else None,language,fmt,status,file_reason,file_tier,fingerprint,"pending" if defer_embeddings else "complete" if embedding_enabled else "disabled")).lastrowid
            try:
                store.insert_units(con,library_id,owner.id,file_id,rel,decoded.sha256 if decoded else "",drafts,fingerprint)
            except sqlite3.IntegrityError as exc:
                raise RetrievalError(f"Unit storage invariant failed at {owner.id}:{rel}: {exc}","index_invalid",409) from exc
            if embedding_enabled and not defer_embeddings:
                for row in con.execute("SELECT id,header_json,description,text FROM units WHERE file_id=? AND redacted=0 AND searchable=1",(file_id,)).fetchall():
                    pending.append((row["id"], json.loads(row["header_json"])["text"] + "\n" + row["description"] + "\n" + (row["text"] or "")))
                    if len(pending) >= config.get("batch_size",32):
                        flush()
        deletion_rows = con.execute("SELECT id,root_id,path FROM files WHERE library_id=?",(library_id,)).fetchall() if _candidate_paths is None else (con.execute("SELECT id,root_id,path FROM files WHERE library_id=? AND root_id=? AND path=?", (library_id, root_id, path)).fetchone() for root_id,path in _candidate_paths - seen)
        for row in deletion_rows:
            if row is None:
                continue
            key = (row["root_id"],row["path"])
            if key not in seen and (_candidate_paths is None or key in _candidate_paths):
                store.delete_file(con,library_id,row["id"])
                deleted += 1
                actions.append({"rootId":key[0],"path":key[1],"action":"removed"})
        flush()
        if provider:
            previous_embedding = json.loads(old["embedding_json"]) if old else {}
            identity = identity or previous_embedding.get("identity") or dict(provider.identity)
            con.execute("UPDATE libraries SET embedding_json=? WHERE id=?",(canonical({"config":config,"identity":identity,"consent":{"endpoint":config.get("base_url"),"allowRemote":config.get("allow_remote",False),"recordedAt":stamp},"truncated":truncated}),library_id))
        corpus = hashlib.sha256(canonical([[r.id,r.path,r.role,r.revision] for r in roots]).encode())
        for row in con.execute("SELECT root_id,path,hash,status FROM files WHERE library_id=? ORDER BY root_id,path",(library_id,)):
            corpus.update(canonical(tuple(row)).encode())
        corpus_id = corpus.hexdigest()
        modified = old is None or old["corpus_hash"] != corpus_id or canonical(scope) != old["scope_json"] or canonical(parser_config) != old["parser_json"] or embedding_changed
        if old and modified:
            generation += 1
        indexed = con.execute("SELECT count(*) FROM files WHERE library_id=? AND status IN ('indexed','redacted')",(library_id,)).fetchone()[0]
        total = con.execute("SELECT count(*) FROM files WHERE library_id=?",(library_id,)).fetchone()[0]
        chunks = con.execute("SELECT count(*) FROM units WHERE library_id=? AND searchable=1",(library_id,)).fetchone()[0]
        skipped = [dict(r) for r in con.execute("SELECT root_id AS rootId,kind,path,status_reason AS reason FROM files WHERE library_id=? AND status NOT IN ('indexed','redacted') ORDER BY root_id,path LIMIT 20",(library_id,))]
        def counts(field):
            return {str(k) if k is not None else "unknown":v for k,v in con.execute(f"SELECT {field},count(*) FROM files WHERE library_id=? GROUP BY {field}",(library_id,))}
        report = {"libraryId":library_id,"indexVersion":8,"generation":generation,"revision":roots[0].revision,"revisions":{r.id:r.revision for r in roots},"corpusId":corpus_id,"files":indexed,"indexed":indexed,"discovered":counters.get("discovered",total),"eligible":total,"chunks":chunks,"changed":changed+added,"added":added,"deleted":deleted,"metadataOnly":metadata_only,"refreshed":bool(modified),"skippedCount":total-indexed,"skipped":skipped,"redactedCount":con.execute("SELECT count(*) FROM files WHERE library_id=? AND status='redacted'",(library_id,)).fetchone()[0],"chunkChars":chunk_chars,"oversizedChunks":con.execute("SELECT count(*) FROM units WHERE library_id=? AND oversized=1",(library_id,)).fetchone()[0],"excludes":list(excludes),"byFormat":counts("format"),"byEncoding":counts("encoding"),"byTier":counts("parser_tier"),"discovery":counters,"discoveryLimit":discovery_limit,"actions":actions,"elapsedSeconds":time.monotonic()-started,"warnings":[],"embeddingModel":config.get("model"),"vectorEngine":vector_engine}
        report["splitFiles"] = [dict(r) for r in con.execute("SELECT root_id AS rootId,path FROM files WHERE library_id=? AND status_reason LIKE 'large-file-window-split%' ORDER BY root_id,path", (library_id,))]
        report["assumedEncodingFiles"] = [dict(r) for r in con.execute("SELECT root_id AS rootId,path,encoding FROM files WHERE library_id=? AND status_reason LIKE '%assumed-encoding:%' ORDER BY root_id,path", (library_id,))]
        if max_files and total > max_files or max_units and chunks > max_units:
            report["warnings"].append("Soft resource threshold exceeded; all eligible files were accounted for")
        con.execute("UPDATE libraries SET generation=?,roots_json=?,corpus_hash=?,refreshed_at=?,last_report_json=? WHERE id=?",(generation,canonical([asdict(r) for r in roots]),corpus_id,stamp,old["last_report_json"] if old and _candidate_paths is not None else canonical(report),library_id))
        primary = store.metadata(con).get("library_id")
        if primary is None or primary == library_id:
            for key,value in {"root":roots[0].path if roots[0].role == "code" else "", "docs_root":next((r.path for r in roots if r.role=="docs"),""),"library_id":library_id,"revision":roots[0].revision,"corpus_id":corpus_id,"chunk_chars":chunk_chars,"excludes":canonical(excludes),"embed_model":config.get("model") or "","model_revision":config.get("revision") or "","vector_engine":vector_engine,"model_cache":config.get("cache_dir") or "","embedding_runtime":config.get("runtime_dir") or "","oversized_chunks":report["oversizedChunks"]}.items():
                store.put_meta(con,key,value)
        con.commit()
        return report
    except sqlite3.OperationalError as exc:
        con.rollback()
        raise RetrievalError("Index database busy or unavailable; retry explicitly", "index_busy", 409) from exc
    except BaseException:
        con.rollback()
        raise
    finally:
        if provider:
            provider.close()
        con.close()


def refresh(database, library_id=None, *, verify_all=False, candidate_paths=None, timeout=5.0):
    with store.connect(database) as con:
        lib = store.library(con,library_id)
        roots = json.loads(lib["roots_json"])
        scope = json.loads(lib["scope_json"])
        config = json.loads(lib["embedding_json"]).get("config",{})
        library_id = lib["id"]
    code = next((r["path"] for r in roots if r["role"]=="code"),None)
    docs = [r["path"] for r in roots if r["role"]=="docs"]
    return index(code,database,library_id,docs_roots=docs,_saved=config,_candidate_paths=candidate_paths,verify_all=verify_all,_timeout=timeout,**scope)


def assert_fresh(con, meta):
    lib = store.library(con,meta.get("library_id"))
    roots = [Root(**r) for r in json.loads(lib["roots_json"])]
    scope = json.loads(lib["scope_json"])
    if any(revision(Path(r.path)) != r.revision for r in roots):
        raise RetrievalError("Repository revision changed; refresh before querying", "source_changed", 409)
    seen = set()
    for owner,rel,*_ in inventory(roots,scope["excludes"],scope.get("includes",()),scope["discovery_limit"]):
        row = con.execute("SELECT hash FROM files WHERE library_id=? AND root_id=? AND path=?",(lib["id"],owner.id,rel)).fetchone()
        seen.add((owner.id,rel))
        if row is None:
            raise RetrievalError("Indexed files appeared; refresh", "source_changed", 409)
        try:
            source = read_source(Path(owner.path),rel,scope["encodings"],scope["max_file_bytes"])
        except RetrievalError:
            if row["hash"] is None:
                continue
            raise
        if source.sha256 != row["hash"]:
            raise RetrievalError("Indexed files changed; refresh", "source_changed", 409)
    existing = {(r[0],r[1]) for r in con.execute("SELECT root_id,path FROM files WHERE library_id=?",(lib["id"],))}
    if seen != existing:
        raise RetrievalError("Indexed files disappeared; refresh", "source_changed", 409)
