"""Real loopback HTTP contract tests, including pinned-client response shapes."""
from __future__ import annotations
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import queue
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRIPTS=Path(__file__).resolve().parents[1]/"skills/legacy-codebase-workflows/scripts"
sys.path.insert(0,str(SCRIPTS))
import context7_backend as backend
from local_context import http_api,store,engine,freshness
from local_context.units import RetrievalError,estimate


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve()
        self.root=self.base/"src"
        self.docs=self.base/"docs"
        self.root.mkdir()
        self.docs.mkdir()
        (self.root/"service.py").write_text('def retry_transfer():\n    """Retry the failed transfer."""\n    return "transfer"\n')
        (self.docs/"usage.md").write_text('# Retry guide\nUse retry_transfer for a failed transfer.\n')
        self.db=self.base/"index.sqlite"
        backend.index(self.root,self.db,"/local/demo",self.docs,parser="0")
        ready=queue.Queue()
        class ReportingServer(ThreadingHTTPServer):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                ready.put(self)
        def run():
            http_api.serve(self.db,"127.0.0.1",0,server_factory=ReportingServer,diagnostic=lambda *a,**k:None)
        self.worker=threading.Thread(target=run,daemon=True)
        self.worker.start()
        self.server=ready.get(timeout=5)
        self.url=f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.stop)
    def stop(self):
        self.server.shutdown()
        self.worker.join(timeout=5)
        self.assertFalse(self.worker.is_alive())
    def get(self,route="/api/v2/context",headers=None,**params):
        target=self.url+route+("?"+urlencode(params) if params else "")
        request=Request(target,headers=headers or {})
        try:
            with urlopen(request,timeout=5) as response:
                raw=response.read().decode()
                return response.status,json.loads(raw) if response.headers.get_content_type()=="application/json" else raw
        except HTTPError as error:
            payload=json.loads(error.read())
            error.close()
            return error.code,payload
    def test_library_contract(self):
        status,payload=self.get("/api/v2/libs/search",libraryName="demo",query="retry")
        self.assertEqual(status,200)
        row=payload["results"][0]
        self.assertEqual(row["id"],"/local/demo")
        self.assertTrue({"title","description","branch","lastUpdateDate","state","totalTokens","totalSnippets"}<=row.keys())
        self.assertNotIn("trustScore",row)
    def test_default_json_code_and_info_shapes(self):
        status,payload=self.get(libraryId="/local/demo",query="retry_transfer")
        self.assertEqual(status,200)
        self.assertTrue(payload["codeSnippets"])
        row=payload["codeSnippets"][0]
        self.assertEqual(row["codeTokens"],estimate("\n".join(c["code"] for c in row["codeList"])))
        self.assertIn("sha256:",row["codeDescription"])
        self.assertTrue(row["codeId"].startswith("local-context://"))
        status,payload=self.get(libraryId="/local/demo",query="retry guide",kind="docs")
        self.assertEqual(status,200)
        info=payload["infoSnippets"][0]
        self.assertTrue({"pageId","breadcrumb","pageTitle","description","content","contentTokens"}<=info.keys())
        self.assertEqual(info["contentTokens"],estimate(info["content"]))
    def test_pinned_mcp_header_selects_text(self):
        status,payload=self.get(headers={"X-Context7-Source":"mcp-server","X-Context7-Server-Version":"4.0.3"},libraryId="/local/demo",query="retry_transfer")
        self.assertEqual(status,200)
        self.assertIsInstance(payload,str)
        self.assertIn("Source: service.py:L",payload)
        self.assertIn("Quoted source data",payload)
        status,payload=self.get(headers={"X-Context7-Source":"mcp-server"},libraryId="/local/demo",query="retry_transfer",type="json")
        self.assertIsInstance(payload,dict)
    def test_host_origin_and_port_validation(self):
        for headers in ({"Host":"evil.example"},{"Host":"127.0.0.1:1"},{"Host":"user@127.0.0.1"},{"Origin":"https://evil.example"},{"Origin":"null"}):
            status,payload=self.get(headers=headers,libraryId="/local/demo",query="retry_transfer")
            self.assertEqual(status,403,headers)
            self.assertEqual(payload["code"],"loopback_required")
        for host in (f"localhost:{self.server.server_port}",f"127.0.0.1:{self.server.server_port}"):
            self.assertEqual(self.get(headers={"Host":host},libraryId="/local/demo",query="retry")[0],200)
    def test_duplicate_parameters_malformed_type_and_size(self):
        for suffix,expected in (("?libraryId=/local/demo&query=x&query=y",400),("?libraryId=/local/demo&query=x&type=broken",400),("?"+"x"*16385,413)):
            request=Request(self.url+"/api/v2/context"+suffix)
            with self.assertRaises(HTTPError) as raised:
                urlopen(request,timeout=5)
            self.assertEqual(raised.exception.code,expected)
            raised.exception.close()
    def test_new_library_stale_visibility_and_current_refresh(self):
        (self.root/"service.py").write_text('def retry_transfer():\n    return "updated"\n')
        status,payload=self.get(libraryId="/local/demo",query="retry_transfer",refresh="off")
        self.assertEqual(status,200)
        self.assertIn("STALE",json.dumps(payload))
        self.assertEqual(self.get(libraryId="/local/demo",query="retry_transfer",refresh="strict")[0],409)
        status,payload=self.get(libraryId="/local/demo",query="retry_transfer")
        self.assertEqual(status,200)
        self.assertIn("updated",json.dumps(payload))
        self.assertNotIn("STALE",json.dumps(payload))
    def test_replaced_database_uuid_is_rejected(self):
        with backend.connect(self.db) as con:
            store.put_meta(con,"database_uuid","f"*32)
        status,payload=self.get(libraryId="/local/demo",query="retry")
        self.assertEqual(status,409)
        self.assertEqual(payload["code"],"index_replaced")
    def test_expand_status_and_safe_errors(self):
        status,payload=self.get("/api/v2/local/status",libraryId="/local/demo",verifyAll="1")
        self.assertEqual(status,200)
        self.assertEqual(payload["libraries"][0]["freshness"],"fresh")
        status,payload=self.get("/api/v2/local/expand",libraryId="/local/demo",rootId="r0",path="service.py",startLine="1",endLine="3")
        self.assertEqual(status,200)
        self.assertTrue(payload["expanded"])
        status,payload=self.get(libraryId="/remote/missing",query="retry")
        self.assertEqual(status,404)
        self.assertIn("error",payload)
        self.assertEqual(payload["codeSnippets"],[])
    def test_long_request_and_warm_hybrid_provider_lifecycle(self):
        class Provider:
            identity={"provider":"fake","model":"warm-test","dimension":2}
            truncated=0
            calls=0
            closed=False
            def embed_documents(self,texts):return [[1.,0.] for _ in texts]
            def embed_query(self,text):
                self.calls+=1
                return [1.,0.]
            def close(self):self.closed=True
        indexer=Provider()
        with mock.patch.object(freshness,"provider_for",return_value=indexer):
            freshness.index(self.root,self.db,"/local/demo",self.docs,parser="0",_saved={"provider":"fake"})
        provider=Provider()
        with mock.patch.object(engine,"provider_for",return_value=provider) as loader:
            for _ in range(2):
                status,payload=self.get(libraryId="/local/demo",query="retry_transfer "+"transfer "*100,mode="hybrid",vectorEngine="stdlib")
                self.assertEqual(status,200)
                self.assertTrue(payload["codeSnippets"])
                with store.connect(self.db) as con:
                    embedded=json.loads(store.library(con)["embedding_json"])
                    embedded["truncated"]=999
                    embedded["consent"]["recordedAt"]="republished-metadata"
                    con.execute("UPDATE libraries SET embedding_json=?",(json.dumps(embedded),))
            self.assertEqual(loader.call_count,1)
            self.assertEqual(provider.calls,2)
            self.assertFalse(provider.closed)
            self.stop()
            self.assertTrue(provider.closed)

    def test_nonloopback_binding_and_bad_defaults_fail_before_bind(self):
        for options in ({"host":"0.0.0.0"},{"default_rerank":"cross-encoder"},{"tokens":1}):
            with self.assertRaises(RetrievalError):
                http_api.serve(self.db,**options)


if __name__=="__main__":
    unittest.main()
