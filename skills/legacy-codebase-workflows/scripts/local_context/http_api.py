"""Loopback-only Context7 routes, with request-owned SQLite snapshots."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit
from . import assemble, engine, store
from .units import RetrievalError

HTTP_SQLITE_TIMEOUT = 1.
MAX_REQUEST = 16 * 1024


def valid_authority(authority, expected_port, *, origin=False):
    try:
        if not authority or any(ord(c)<33 or ord(c)==127 for c in authority) or "\\" in authority:
            return False
        parts = urlsplit(authority if origin else "//"+authority)
        if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment or parts.hostname not in {"localhost","127.0.0.1","::1"}:
            return False
        if origin and parts.scheme not in {"http","https"}:
            return False
        return parts.port in {None,expected_port}
    except ValueError:
        return False


def serve(database, host="127.0.0.1", port=8765, default_mode="lexical", default_rerank=None, default_vector_engine=None, *, default_library=None, tokens=4000, refresh_policy="auto", server_factory=ThreadingHTTPServer, diagnostic=print):
    if type(port) is not int or not 0<=port<=65535:
        raise RetrievalError("Port must be 0..65535")
    if host not in {"127.0.0.1","::1","localhost"}:
        raise RetrievalError("HTTP service requires loopback", "loopback_required",403)
    if default_mode not in {"lexical","semantic","hybrid"} or default_rerank not in {None,"lexical-symbol"} or default_vector_engine not in {None,"stdlib","auto","numpy","sqlite-vec"} or not 256<=tokens<=32000 or refresh_policy not in {"auto","strict","off"}:
        raise RetrievalError("Invalid server default; cross-encoder is not supported")
    with store.connect(database) as con:
        database_uuid = store.validate(con)["database_uuid"]
        if default_library:
            store.library(con,default_library)
    provider_cache = {}
    provider_lock = threading.Lock()
    provider_slots = threading.BoundedSemaphore(8)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def send(self,status,body,content_type="application/json"):
            raw = body.encode("utf-8") if isinstance(body,str) else json.dumps(body,ensure_ascii=False,separators=(",",":")).encode()
            self.send_response(status)
            self.send_header("Content-Type",content_type+"; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            try:
                if len(self.path.encode("utf-8"))>MAX_REQUEST:
                    raise RetrievalError("Request target exceeds the server limit of 16 KiB; shorten the URL", "request_too_large",413)
                if len(self.headers.get_all("Host",[]))!=1 or not valid_authority(self.headers.get("Host"),self.server.server_port) or (self.headers.get("Origin") and not valid_authority(self.headers["Origin"],self.server.server_port,origin=True)):
                    raise RetrievalError("Only local loopback authority is allowed", "loopback_required",403)
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc:
                    raise RetrievalError("Absolute request targets are not supported")
                params = parse_qs(parsed.query,keep_blank_values=True)
                if any(len(v)!=1 for v in params.values()):
                    raise RetrievalError("Duplicate singleton query parameter")
                p = {k:v[0] for k,v in params.items()}
                def integer(name,default):
                    try:
                        return int(p[name]) if name in p else default
                    except ValueError as exc:
                        raise RetrievalError("Invalid integer parameter: "+name) from exc
                with store.connect(database,timeout=HTTP_SQLITE_TIMEOUT) as con:
                    if store.validate(con)["database_uuid"]!=database_uuid:
                        raise RetrievalError("Index database replaced; restart the local service", "index_replaced",409)
                    lib = p.get("libraryId") or default_library
                    if parsed.path=="/api/v2/libs/search":
                        self.send(200,{"results":engine.resolve(con,p.get("libraryName",""),p.get("query",""),integer("limit",10))})
                    elif parsed.path=="/api/v2/context":
                        output = p.get("type", "txt" if self.headers.get("X-Context7-Source")=="mcp-server" else "json")
                        if output not in {"json","txt"}:
                            raise RetrievalError("type must be json or txt")
                        mode = p.get("mode",default_mode)
                        def run():
                            return engine.query(con,p.get("query",""),mode,p.get("rerank",default_rerank),integer("limit",5),p.get("vectorEngine",default_vector_engine),library_id=lib,kind=p.get("kind"),language=p.get("language"),tokens=integer("tokens",tokens),refresh_policy=p.get("refresh",refresh_policy),provider_cache=provider_cache,output_format="text" if output=="txt" else "context7-json",pretty=False,newline=False)
                        if mode!="lexical":
                            if not provider_slots.acquire(blocking=False):
                                raise RetrievalError("Embedding request queue full; retry explicitly", "provider_unavailable",503)
                            try:
                                with provider_lock:
                                    result = run()
                            finally:
                                provider_slots.release()
                        else:
                            result = run()
                        self.send(200,assemble.serialize(result,"text" if output=="txt" else "context7-json",pretty=False,newline=False),"text/plain" if output=="txt" else "application/json")
                    elif parsed.path=="/api/v2/local/status":
                        self.send(200,engine.status(con,lib,p.get("verifyAll")=="1"))
                    elif parsed.path=="/api/v2/local/expand":
                        self.send(200,engine.expand(con,library_id=lib,unit_id=p.get("unitId"),path=p.get("path"),root_id=p.get("rootId"),start_line=integer("startLine",None),end_line=integer("endLine",None),tokens=integer("tokens",tokens),pretty=False,newline=False))
                    else:
                        raise RetrievalError("Unknown local route", "route_not_found",404)
            except MemoryError:
                self.send(413,{"error":"Memory resource limit exceeded; scope the corpus","code":"resource_limit","codeSnippets":[],"infoSnippets":[]})
            except RetrievalError as exc:
                self.send(exc.status,{"error":str(exc),"code":exc.code,"message":str(exc),"codeSnippets":[],"infoSnippets":[]})
            except sqlite3.Error:
                self.send(409,{"error":"Database busy or invalid; restore the index or retry explicitly","code":"index_busy","codeSnippets":[],"infoSnippets":[]})
            except (OSError,ValueError,RuntimeError,TypeError,KeyError):
                self.send(503,{"error":"Local retrieval capability unavailable; check status","code":"provider_unavailable","codeSnippets":[],"infoSnippets":[]})
    factory = server_factory
    if host=="::1" and factory is ThreadingHTTPServer:
        class IPv6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        factory = IPv6Server
    server = factory((host,port),Handler)
    try:
        diagnostic(f"Local Context7 listening on http://{host}:{server.server_port}",flush=True)
        server.serve_forever()
    finally:
        server.server_close()
        for provider in provider_cache.values():
            provider.close()
