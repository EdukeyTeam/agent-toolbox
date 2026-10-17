"""Command-line adapter. Indexing is explicit; lexical queries stay offline."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from . import assemble, engine, freshness, store
from .units import DEFAULT_CHUNK_CHARS, RetrievalError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    for name in ("index","refresh","query","serve","resolve","expand","status"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--database",type=Path,required=True)
        cmd.add_argument("--library-id")
        if name=="index":
            cmd.add_argument("root",type=Path,nargs="?")
            cmd.add_argument("--docs-root",type=Path,action="append",default=[])
            cmd.add_argument("--title")
            cmd.add_argument("--description")
            cmd.add_argument("--chunk-chars",type=int,default=DEFAULT_CHUNK_CHARS)
            cmd.add_argument("--exclude",action="append",default=[])
            cmd.add_argument("--include",action="append",default=[])
            cmd.add_argument("--encodings",default="")
            cmd.add_argument("--parser",choices=("auto","0","1"),default="auto")
            cmd.add_argument("--no-secret-scan",action="store_true")
            for flag,default in (("max-files",0),("max-units",0),("max-file-bytes",2_000_000),("discovery-limit",2_000_000),("jobs",1)):
                cmd.add_argument("--"+flag,type=int,default=default)
            for flag in ("embed-model","model-revision","embed-provider","embed-base-url","embed-api-key-env","reranker-model","reranker-revision"):
                cmd.add_argument("--"+flag)
            for flag in ("model-cache","embedding-runtime","model-dir"):
                cmd.add_argument(*(["--model-cache", "--cache-dir"] if flag == "model-cache" else ["--"+flag]), dest=flag.replace("-", "_"), type=Path)
            for flag in ("download-model","allow-remote-embeddings"):
                cmd.add_argument("--"+flag,action="store_true")
            cmd.add_argument("--vector-engine",default="stdlib")
        elif name=="query":
            cmd.add_argument("--query",required=True)
            cmd.add_argument("--mode",choices=("lexical","semantic","hybrid"),default="lexical")
            cmd.add_argument("--rerank",choices=("lexical-symbol","cross-encoder"))
            cmd.add_argument("--vector-engine")
            cmd.add_argument("--limit",type=int,default=5)
            cmd.add_argument("--tokens",type=int)
            cmd.add_argument("--refresh",choices=("auto","off","strict"),default="auto")
            cmd.add_argument("--format",choices=("json","text","context7-json"),default="json")
            cmd.add_argument("--kind",choices=("code","docs"))
            cmd.add_argument("--language")
            cmd.add_argument("--explain",action="store_true")
            cmd.add_argument("--ablate",action="append",default=[],choices=("symbols","paths","shadow","coverage","history","tests","generated","docs","references","config-behavior"),help="Development ablation: symbols, paths, shadow, coverage, history, tests, generated, docs")
        elif name=="serve":
            cmd.add_argument("--host",default="127.0.0.1")
            cmd.add_argument("--port",type=int,default=8765)
            cmd.add_argument("--default-mode",default="lexical")
            cmd.add_argument("--default-rerank")
            cmd.add_argument("--default-vector-engine")
            cmd.add_argument("--tokens",type=int,default=4000)
            cmd.add_argument("--refresh",default="auto")
        elif name=="resolve":
            cmd.add_argument("--library-name",required=True)
            cmd.add_argument("--query",default="")
            cmd.add_argument("--limit",type=int,default=10)
        elif name=="expand":
            cmd.add_argument("--unit-id")
            cmd.add_argument("--path")
            cmd.add_argument("--root-id")
            cmd.add_argument("--start-line",type=int)
            cmd.add_argument("--end-line",type=int)
            cmd.add_argument("--tokens",type=int,default=4000)
            cmd.add_argument("--format",choices=("json","text","context7-json"),default="json")
        else:
            cmd.add_argument("--verify-all",action="store_true")
            if name=="refresh":
                cmd.add_argument("--all",action="store_true")
                cmd.add_argument("--jobs",type=int,default=1)
    args = parser.parse_args(argv)
    try:
        if args.command=="index":
            if not args.library_id:
                raise RetrievalError("index requires --library-id")
            options = vars(args).copy()
            for key in ("command","root","database","library_id","docs_root","exclude","include"):
                options.pop(key)
            result = freshness.index(args.root,args.database,args.library_id,docs_roots=args.docs_root,excludes=args.exclude,includes=args.include,**options)
        elif args.command=="refresh":
            if args.jobs<1:
                raise RetrievalError("jobs must be positive; v1 indexes in one process")
            if args.all:
                if args.library_id:
                    raise RetrievalError("--all and --library-id are mutually exclusive")
                with store.connect(args.database) as con:
                    ids = [r[0] for r in con.execute("SELECT id FROM libraries ORDER BY id")]
                result = {"libraries":[freshness.refresh(args.database,i,verify_all=args.verify_all) for i in ids]}
            else:
                result = freshness.refresh(args.database,args.library_id,verify_all=args.verify_all)
        elif args.command=="serve":
            from .http_api import serve
            serve(args.database,args.host,args.port,args.default_mode,args.default_rerank,args.default_vector_engine,default_library=args.library_id,tokens=args.tokens,refresh_policy=args.refresh)
            return 0
        else:
            with store.connect(args.database) as con:
                if args.command=="query":
                    result = engine.query(con,args.query,args.mode,args.rerank,args.limit,args.vector_engine,library_id=args.library_id,kind=args.kind,language=args.language,tokens=args.tokens,refresh_policy=args.refresh,ablations=args.ablate,explain=args.explain)
                elif args.command=="expand":
                    result = engine.expand(con,library_id=args.library_id,unit_id=args.unit_id,path=args.path,root_id=args.root_id,start_line=args.start_line,end_line=args.end_line,tokens=args.tokens)
                elif args.command=="resolve":
                    result = {"results":engine.resolve(con,args.library_name,args.query,args.limit)}
                else:
                    result = engine.status(con,args.library_id,args.verify_all)
        fmt = getattr(args,"format","json")
        if fmt=="text":
            print(assemble.text_payload(result))
        else:
            print(json.dumps(assemble.context_payload(result) if fmt=="context7-json" else result,ensure_ascii=False,indent=2))
        return 0
    except MemoryError:
        print(json.dumps({"error":"Memory resource limit exceeded; scope the corpus or reduce limits","code":"resource_limit"}),file=sys.stderr)
        return 4
    except RetrievalError as exc:
        print(json.dumps({"error":str(exc),"code":exc.code}),file=sys.stderr)
        return 3 if exc.code.startswith("index_") and exc.code!="index_busy" else 5 if exc.code in {"consent_required","model_unavailable","provider_unavailable","vector_adapter_unavailable","embedding_invalid"} else 4 if exc.status in {409,413} else 2
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error) as exc:
        print(json.dumps({"error":"Local retrieval failed; check source paths, provider and database","code":"runtime_error"}),file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        return 130
