"""One format-8 SQLite authority, WAL snapshots and explicit FTS ownership."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid
from .units import INDEX_VERSION, RetrievalError, canonical, digest, estimate
from .symbols import searchable_tokens, words, stem, properties_shadow

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE libraries(id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,kind TEXT NOT NULL,roots_json TEXT NOT NULL,scope_json TEXT NOT NULL,parser_json TEXT NOT NULL,embedding_json TEXT NOT NULL,reranker_json TEXT NOT NULL DEFAULT '{}',generation INTEGER NOT NULL CHECK(generation>=1),corpus_hash TEXT NOT NULL,indexed_at TEXT NOT NULL,refreshed_at TEXT NOT NULL,last_report_json TEXT NOT NULL);
CREATE TABLE files(id INTEGER PRIMARY KEY AUTOINCREMENT,library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,root_id TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('code','docs')),path TEXT NOT NULL,hash TEXT,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,encoding TEXT,language TEXT NOT NULL,format TEXT NOT NULL,status TEXT NOT NULL,status_reason TEXT,parser_tier TEXT NOT NULL,parser_fingerprint TEXT NOT NULL,embedding_status TEXT NOT NULL,UNIQUE(library_id,root_id,path),UNIQUE(id,library_id));
CREATE INDEX files_scope ON files(library_id,kind,language,status);
CREATE TABLE units(id INTEGER PRIMARY KEY AUTOINCREMENT,unit_uid TEXT UNIQUE NOT NULL,library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,file_id INTEGER NOT NULL,kind TEXT NOT NULL,language TEXT NOT NULL,start_line INTEGER NOT NULL CHECK(start_line>=1),end_line INTEGER NOT NULL CHECK(end_line>=start_line),symbol TEXT,qualified_name TEXT,signature TEXT,scope_chain_json TEXT NOT NULL,breadcrumb_json TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,text TEXT, parent_unit_id INTEGER REFERENCES units(id) ON DELETE CASCADE,token_estimate INTEGER NOT NULL CHECK(token_estimate>=0),header_json TEXT NOT NULL,header_spans_json TEXT NOT NULL,cell_index INTEGER,part_index INTEGER NOT NULL,part_count INTEGER NOT NULL,searchable INTEGER NOT NULL,redacted INTEGER NOT NULL,oversized INTEGER NOT NULL,text_hash TEXT,transformed INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(file_id,library_id) REFERENCES files(id,library_id) ON DELETE CASCADE,CHECK(part_index>=1 AND part_index<=part_count));
CREATE INDEX units_file_span ON units(file_id,start_line,end_line);
CREATE INDEX units_scope ON units(library_id,kind,language,searchable);
CREATE TABLE symbols(id INTEGER PRIMARY KEY,library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,name TEXT NOT NULL,name_fold TEXT NOT NULL,qualified_name TEXT NOT NULL,qualified_fold TEXT NOT NULL,kind TEXT NOT NULL,unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,path TEXT NOT NULL,line INTEGER NOT NULL,UNIQUE(unit_id,qualified_name,kind,line));
CREATE INDEX symbols_name ON symbols(library_id,name_fold);
CREATE INDEX symbols_qualified ON symbols(library_id,qualified_fold);
CREATE TABLE unit_vectors(unit_id INTEGER PRIMARY KEY REFERENCES units(id) ON DELETE CASCADE,embedding BLOB NOT NULL,input_hash TEXT NOT NULL,input_tokens INTEGER,truncated INTEGER NOT NULL,embedded_at TEXT NOT NULL);
CREATE VIEW chunks AS SELECT u.id,f.kind,f.path,u.start_line AS start,u.end_line AS end,u.text AS body,coalesce(u.qualified_name,'') AS symbols FROM units u JOIN files f ON f.id=u.file_id WHERE u.searchable=1;
CREATE VIEW chunk_vectors AS SELECT unit_id AS chunk_id,embedding FROM unit_vectors;
"""
# The logical format is still 8, but older writers do not maintain external
# FTS content. Their fingerprint check must reject a newly published layout.
STORAGE_FINGERPRINT = digest((SCHEMA + "\n-- external-content FTS v1\n").encode())


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path, *, timeout=5.0):
    path = Path(path).resolve()
    if not path.is_file():
        raise RetrievalError("Database does not exist; run index", "index_invalid", 409)
    con = sqlite3.connect(path, timeout=timeout, isolation_level=None, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    # Share hot index pages through the OS cache instead of repeatedly copying
    # a gigabyte-scale FTS index through SQLite's small per-connection cache.
    # SQLite may decline mmap on unsupported builds; WAL snapshots still apply.
    con.execute("PRAGMA mmap_size=1073741824")
    return con


def fts_name(library_id):
    return "fts_" + digest(library_id.encode())[:24]


def fts_payload_name(con, library_id):
    name = fts_name(library_id)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return name + "_source" if sql and "content=" in sql[0] else name


def create_library_fts(con, library_id):
    name = fts_name(library_id)
    try:
        old = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        migrate = bool(old and ("tokenchars" not in old[0] or "content=" not in old[0]))
        if migrate:
            con.execute(f"CREATE TEMP TABLE {name}_saved AS SELECT rowid AS id,* FROM {name}")
            con.execute(f"DROP TABLE {name}")
        if old is None or migrate:
            # The source body already belongs to units. Keep only search
            # shadows here, exposing the exact original FTS body through a view.
            con.execute(f"CREATE TABLE IF NOT EXISTS {name}_source(rowid INTEGER PRIMARY KEY REFERENCES units(id) ON DELETE CASCADE,title_symbols TEXT NOT NULL,identifier_tokens TEXT NOT NULL,path_tokens TEXT NOT NULL,stemmed TEXT NOT NULL)")
            con.execute(f"CREATE VIEW IF NOT EXISTS {name}_view AS SELECT s.rowid,s.title_symbols,s.identifier_tokens,s.path_tokens,CASE WHEN u.redacted=1 THEN 'Redacted source content' ELSE json_extract(u.header_json,'$.text')||char(10)||u.description||char(10)||coalesce(u.text,'') END AS body,s.stemmed FROM {name}_source s JOIN units u ON u.id=s.rowid")
        external = f",content='{name}_view',content_rowid='rowid'" if old is None or migrate else ""
        con.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING fts5(title_symbols,identifier_tokens,path_tokens,body,stemmed,tokenize=\"unicode61 remove_diacritics 2 tokenchars '_'\"{external})")
        if migrate:
            con.execute(f"DELETE FROM {name}_source")
            con.execute(f"INSERT INTO {name}_source(rowid,title_symbols,identifier_tokens,path_tokens,stemmed) SELECT id,title_symbols,identifier_tokens,path_tokens,stemmed FROM {name}_saved")
            con.execute(f"INSERT INTO {name}(rowid,title_symbols,identifier_tokens,path_tokens,body,stemmed) SELECT id,title_symbols,identifier_tokens,path_tokens,body,stemmed FROM {name}_saved")
            con.execute(f"DROP TABLE {name}_saved")
        put_meta(con, "schema_fingerprint", STORAGE_FINGERPRINT)
    except sqlite3.OperationalError as exc:
        raise RetrievalError("SQLite FTS5 unavailable; use a Python runtime compiled with FTS5", "fts5_unavailable", 503) from exc


def metadata(con):
    try:
        return dict(con.execute("SELECT key,value FROM meta"))
    except sqlite3.Error as exc:
        raise RetrievalError("Database is not a recognized retrieval index; use a new database path", "index_invalid", 409) from exc


def validate(con):
    meta = metadata(con)
    if meta.get("index_version") != INDEX_VERSION:
        raise RetrievalError(f"Index version {meta.get('index_version', 'unknown')} unsupported; reindex required into a new database path (format 8)", "index_version_unsupported", 409)
    if not re.fullmatch(r"[a-f0-9]{32}", meta.get("database_uuid", "")) or con.execute("PRAGMA user_version").fetchone()[0] != 8:
        raise RetrievalError("Invalid index metadata; restore or reindex into a new database path", "index_invalid", 409)
    if meta.get("schema_fingerprint") not in {digest(SCHEMA.encode()), STORAGE_FINGERPRINT}:
        raise RetrievalError("Index schema fingerprint changed; reindex required", "index_invalid", 409)
    try:
        con.execute("SELECT id,roots_json,scope_json FROM libraries LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        raise RetrievalError("Incomplete index schema; reindex required", "index_invalid", 409) from exc
    return meta


def initialize(con):
    existing = con.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if existing:
        validate(con)
    else:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute("PRAGMA user_version=8")
        con.executemany("INSERT INTO meta VALUES(?,?)", [("index_version", INDEX_VERSION), ("database_uuid", uuid.uuid4().hex), ("schema_fingerprint", STORAGE_FINGERPRINT)])
    # An auxiliary performance index, safe to add to existing format-8 stores.
    # Without it every ON DELETE parent cascade scans the entire units table.
    con.execute("CREATE INDEX IF NOT EXISTS units_parent ON units(parent_unit_id)")


LIBRARY_COLUMNS = "id,title,description,kind,roots_json,scope_json,parser_json,embedding_json,reranker_json,generation,corpus_hash,indexed_at,refreshed_at"

def library(con, library_id=None):
    validate(con)
    if library_id:
        row = con.execute(f"SELECT {LIBRARY_COLUMNS} FROM libraries WHERE id=?", (library_id,)).fetchone()
        if row is None:
            raise RetrievalError("Library not found; resolve a local library first", "library_not_found", 404)
        validate_library(row)
        return row
    rows = con.execute(f"SELECT {LIBRARY_COLUMNS} FROM libraries ORDER BY id LIMIT 2").fetchall()
    if len(rows) != 1:
        raise RetrievalError("Select --library-id for a multi-library database", "library_required")
    validate_library(rows[0])
    return rows[0]


def validate_library(row):
    def require(condition):
        if not condition:
            raise ValueError()
    try:
        roots = json.loads(row["roots_json"])
        scope = json.loads(row["scope_json"])
        parser = json.loads(row["parser_json"])
        embedding = json.loads(row["embedding_json"])
        require(isinstance(roots,list) and roots)
        require(len({r["id"] for r in roots})==len(roots))
        for root in roots:
            require(isinstance(root,dict) and root["role"] in {"code","docs"})
            require(isinstance(root["path"],str) and Path(root["path"]).is_absolute())
            require(isinstance(root["revision"],str) and re.fullmatch(r"r[0-9]+",root["id"]))
        require(isinstance(scope,dict) and isinstance(scope["encodings"],list))
        require(all(isinstance(e,str) for e in scope["encodings"]))
        require(type(scope["no_secret_scan"]) is bool)
        require(type(scope["chunk_chars"]) is int and 128<=scope["chunk_chars"]<=12000)
        require(type(scope["max_file_bytes"]) is int and scope["max_file_bytes"]>0)
        require(type(scope["discovery_limit"]) is int and scope["discovery_limit"]>0)
        require(isinstance(scope["excludes"],list) and all(isinstance(v,str) for v in scope["excludes"]))
        require(isinstance(scope.get("includes",[]),list))
        require(isinstance(parser,dict) and parser["tier"] in {"0","1"})
        require(isinstance(embedding,dict) and isinstance(embedding.get("config"),dict))
        require(type(row["generation"]) is int and row["generation"]>=1)
        require(re.fullmatch(r"[a-f0-9]{64}",row["corpus_hash"]))
    except (AssertionError,ValueError,TypeError,KeyError):
        raise RetrievalError("Invalid library metadata; restore or reindex into a new database path","index_invalid",409) from None

@contextmanager
def snapshot(con):
    # A caller-owned transaction stays pinned across nested query operations.
    owned = not con.in_transaction
    if owned:
        con.execute("BEGIN")
    try:
        validate(con)  # first read pins the WAL snapshot
        yield
    finally:
        if owned:
            con.rollback()


def put_meta(con, key, value):
    con.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def indexed_metadata(con):
    validate(con)
    return metadata(con)


def delete_file(con, library_id, file_id):
    name = fts_name(library_id)
    con.execute(f"DELETE FROM {name} WHERE rowid IN (SELECT id FROM units WHERE file_id=?)", (file_id,))
    con.execute("DELETE FROM files WHERE id=? AND library_id=?", (file_id, library_id))


def insert_units(con, library_id, root_id, file_id, path, file_hash, drafts, fingerprint):
    name = fts_name(library_id)
    payload = fts_payload_name(con, library_id)
    inserted = []
    for unit in drafts:
        definition = unit.definitions[0] if unit.definitions else None
        uid = digest(canonical([library_id, root_id, path, file_hash, unit.kind, unit.start, unit.end, unit.cell_index, unit.part, unit.searchable, unit.title, fingerprint]).encode())
        header = {"text":unit.header, "truncated":len(unit.header)>=400}
        values = (uid,library_id,file_id,unit.kind,unit.language,unit.start,unit.end,definition.name if definition else None,definition.qualified if definition else None,definition.signature if definition else None,canonical(definition.scope if definition else ()),canonical(unit.breadcrumb),unit.title,unit.description,unit.text,estimate(unit.header+unit.description+(unit.text or "")),canonical(header),canonical(unit.header_spans),unit.cell_index,unit.part,unit.parts,int(unit.searchable),int(unit.redacted),int(unit.oversized),digest((unit.text or "").encode()),int(unit.transformed))
        cur = con.execute("INSERT INTO units(unit_uid,library_id,file_id,kind,language,start_line,end_line,symbol,qualified_name,signature,scope_chain_json,breadcrumb_json,title,description,text,token_estimate,header_json,header_spans_json,cell_index,part_index,part_count,searchable,redacted,oversized,text_hash,transformed) VALUES(" + ",".join("?" for _ in values) + ") ON CONFLICT(unit_uid) DO NOTHING",values)
        duplicate = cur.rowcount == 0
        if duplicate:
            previous = con.execute("SELECT id,text FROM units WHERE unit_uid=?",(uid,)).fetchone()
            if previous["text"] != unit.text:
                raise RetrievalError("Conflicting text for one physical source envelope","index_invalid",409)
            unit_id = previous["id"]
        else:
            unit_id = cur.lastrowid
        if unit.parent is not None and not duplicate:
            if not 0<=unit.parent<len(inserted):
                raise RetrievalError("Invalid parent unit ordering", "index_invalid",409)
            con.execute("UPDATE units SET parent_unit_id=? WHERE id=?",(inserted[unit.parent],unit_id))
        inserted.append(unit_id)
        if unit.searchable and not duplicate:
            body = unit.header + "\n" + unit.description + "\n" + (unit.text or "")
            title = " ".join([unit.title, *unit.breadcrumb, *(d.qualified + " " + d.signature for d in unit.definitions)]) if not unit.redacted else "Redacted source content"
            searchable = body
            if unit.language == "properties" and not unit.redacted:
                # Search shadow only: source text and cited line offsets stay raw.
                searchable = properties_shadow(searchable)
            split = searchable_tokens(searchable) if not unit.redacted else ""
            shadow = " ".join(stem(w) for w in words(split)) if not unit.redacted else ""
            if payload != name:
                con.execute(f"INSERT INTO {payload}(rowid,title_symbols,identifier_tokens,path_tokens,stemmed) VALUES(?,?,?,?,?)", (unit_id,title,split,path + " " + searchable_tokens(path),shadow))
            con.execute(f"INSERT INTO {name}(rowid,title_symbols,identifier_tokens,path_tokens,body,stemmed) VALUES(?,?,?,?,?,?)", (unit_id,title,split,path + " " + searchable_tokens(path),body if not unit.redacted else "Redacted source content",shadow))
        for d in unit.definitions:
            con.execute("INSERT OR IGNORE INTO symbols(library_id,name,name_fold,qualified_name,qualified_fold,kind,unit_id,path,line) VALUES(?,?,?,?,?,'definition',?,?,?)",(library_id,d.name,d.name.casefold(),d.qualified,d.qualified.casefold(),unit_id,path,d.start))
