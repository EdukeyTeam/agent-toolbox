"""Source verification, overlap removal, evidence budgets and wire formats."""
from __future__ import annotations
from dataclasses import replace
import json
import math
from pathlib import Path
from repo_files import split_source_lines
import re
from urllib.parse import quote
from .decode import read_source, secret_spans
from .units import EMPTY, RetrievalError, estimate
from . import store


def citation(item):
    s = item["source"]
    return f"Source: {s['path']}:L{s['startLine']}-L{s['endLine']}; library:{s['libraryId']}; root:{s['rootId']}; kind:{s['kind']}; sha256:{s['fileSha256']}; revision:{s['revision']}; freshness:{s['freshness']}; unit:{item['unitId']}"


def evidence(item):
    # A8 charges emitted source evidence only, once. JSON metadata keys and the
    # envelope are deliberately outside this budget.
    return "\n".join((item["header"].get("text", ""),item["description"],item["text"],citation(item)))


def native_item(row, library, roots, live, freshness):
    root = roots[row["root_id"]]
    provenance = "docs" if root["role"]=="docs" else "repo-docs" if row["provenance"]=="docs" else "code"
    description = row["description"]
    if freshness == "stale":
        description = "STALE indexed source; run refresh. " + description
    return {"unitId":row["unit_uid"],"unitKind":row["kind"],"language":row["language"],"title":row["title"],"description":description,"header":json.loads(row["header_json"]),"headerSpans":json.loads(row["header_spans_json"]),"text":row["text"] or "","score":row["score"],"source":{"libraryId":library["id"],"rootId":row["root_id"],"kind":provenance,"path":row["path"],"startLine":row["start_line"],"endLine":row["end_line"],"fileSha256":row["file_hash"],"liveFileSha256":live.sha256,"revision":root["revision"],"corpusId":library["corpus_hash"],"freshness":freshness,"verifiedAt":store.now(),"encoding":row["encoding"],"encodingAssumed":live.assumed if freshness=="fresh" else row["encoding"] in {"latin-1","iso-8859-1"},"lineMapping":"approximate" if row["transformed"] else "exact","cellIndex":row["cell_index"],"redacted":False},"partIndex":row["part_index"],"partCount":row["part_count"]}


def verify(rows, library, refresh_policy):
    roots = {r["id"]:r for r in json.loads(library["roots_json"])}
    scope = json.loads(library["scope_json"])
    cache, scans, source_lines, changed, unavailable = {}, {}, {}, set(), 0
    result = []
    for row in rows:
        key = (row["root_id"],row["path"])
        if key not in cache:
            try:
                live = read_source(Path(roots[key[0]]["path"]),key[1],scope["encodings"],scope["max_file_bytes"])
                cache[key] = live
                source_lines[key] = split_source_lines(live.text)
                scans[key] = secret_spans(live.text) if not scope["no_secret_scan"] else []
            except (RetrievalError, OSError):
                cache[key] = None
        live = cache[key]
        if live is None:
            changed.add(key)
            unavailable += 1
            continue
        state = "fresh" if live.sha256 == row["file_hash"] else "stale"
        if state == "stale":
            changed.add(key)
        # A newly introduced strict key cannot leak via a cached ancestor/header.
        if not scope["no_secret_scan"] and (scans[key] and (state == "stale" or any(a <= row["end_line"] and b >= row["start_line"] for a,b in scans[key]))):
            unavailable += 1
            continue
        if state == "fresh" and not row["transformed"]:
            lines = source_lines[key]
            if row["end_line"]>len(lines) or row["text"] != "\n".join(lines[row["start_line"]-1:row["end_line"]]):
                raise RetrievalError("Stored unit does not match verified source lines; reindex","index_invalid",409)
        result.append(native_item(row,library,roots,live,state))
    if changed and refresh_policy == "strict":
        raise RetrievalError("Candidate sources changed or disappeared; run refresh", "source_changed",409)
    return result, changed, unavailable


def excerpt(item, chars, question):
    if item["source"]["lineMapping"] != "exact":
        return None
    lines = split_source_lines(item["text"])
    overhead = len(evidence({**item,"text":""})) + 80
    room = chars-overhead
    if room < 1:
        return None
    from .symbols import analyze, words, stem
    terms,_ = analyze(question)
    weights = []
    for i,line in enumerate(lines):
        tokens = {stem(w) for w in words(line)}
        weights.append((sum(stem(t) in tokens for t in terms),i))
    pivot = max(weights,key=lambda r:(r[0],-r[1]))[1] if weights else 0
    if not lines or len(lines[pivot]) > room:
        return None
    first,last,size = pivot,pivot,len(lines[pivot])
    while True:
        possibilities = []
        if first > 0:
            possibilities.append((first-1,len(lines[first-1])+1,"first"))
        if last+1 < len(lines):
            possibilities.append((last+1,len(lines[last+1])+1,"last"))
        fitting = [p for p in possibilities if size+p[1] <= room]
        if not fitting:
            break
        p = fitting[0] if len(fitting)==1 else min(fitting,key=lambda p:abs(p[0]-pivot))
        if p[2]=="first":
            first = p[0]
        else:
            last = p[0]
        size += p[1]
    source = {**item["source"],"startLine":item["source"]["startLine"]+first,"endLine":item["source"]["startLine"]+last}
    return {**item,"text":"\n".join(lines[first:last+1]),"source":source,"excerpt":True,"description":item["description"]+" [Whole-line excerpt; use expand for more.]"}


def pack(items, library, mode, rerank, vector_engine, limit, tokens, question, changed=(), unavailable=0):
    if tokens is not None and not 256 <= tokens <= 32000:
        raise RetrievalError("Token budget must be 256..32000")
    selected, per_file, omitted, used = [], {}, 0, 0
    for item in items:
        key = (item["source"]["rootId"],item["source"]["path"])
        if per_file.get(key,0) >= 3:
            continue
        if any(key==(r["source"]["rootId"],r["source"]["path"]) and item["source"]["cellIndex"] == r["source"]["cellIndex"] and max(0,min(item["source"]["endLine"],r["source"]["endLine"])-max(item["source"]["startLine"],r["source"]["startLine"])+1) >= .8*min(item["source"]["endLine"]-item["source"]["startLine"]+1,r["source"]["endLine"]-r["source"]["startLine"]+1) for r in selected):
            continue
        cost = len(evidence(item))
        if tokens is not None and math.ceil((used+cost)/4)>tokens:
            item = excerpt(item,tokens*4-used,question)
            if item is None or math.ceil((used+len(evidence(item)))/4)>tokens:
                omitted += 1
                continue
            cost = len(evidence(item))
        selected.append(item)
        used += cost
        per_file[key] = per_file.get(key,0)+1
        if len(selected)>=limit:
            break
    stale = bool(changed)
    warnings = (["Source changed; stale evidence is marked. Run refresh."] if stale else [])
    if omitted:
        warnings.append(f"{omitted} evidence units omitted for budget; use expand or raise tokens.")
    if unavailable:
        warnings.append("Missing, unreadable or unsafe candidate bodies withheld; run refresh.")
    return {"indexVersion":8,"libraryId":library["id"],"mode":mode,"reranker":rerank,"vectorEngine":vector_engine,"corpusId":library["corpus_hash"],"generation":library["generation"],"revisions":{r["id"]:r["revision"] for r in json.loads(library["roots_json"])},"freshness":{"state":"stale" if stale else "fresh","changedFiles":len(changed)},"budget":{"requestedTokens":tokens,"usedEstimatedTokens":math.ceil(used/4),"characters":used,"estimator":"ceil(evidence characters/4)"},"coverage":{"returned":len(selected),"omittedForBudget":omitted,"unavailable":unavailable},"warnings":warnings,"results":selected,"message":None if selected else EMPTY,"reason":None if selected else "stale_omitted" if unavailable else "budget_omitted" if omitted else "no_match"}


def context_payload(result):
    code,info = [],[]
    for item in result["results"]:
        s = item["source"]
        uri = "local-context://" + quote(s["libraryId"],safe="/") + "/" + s["rootId"] + "/" + quote(s["path"],safe="/") + f"#L{s['startLine']}-L{s['endLine']}"
        body = "\n".join(filter(None,(item["header"]["text"],item["text"])))
        if item["unitKind"]=="doc-section":
            content = body + "\n" + item["description"] + "\n" + citation(item)
            info.append({"pageId":uri,"breadcrumb":item["title"],"pageTitle":s["path"],"description":item["description"],"content":content,"contentTokens":estimate(content)})
        else:
            code.append({"codeTitle":item["title"],"codeDescription":item["description"]+"\n"+citation(item),"codeLanguage":item["language"],"codeTokens":estimate(body),"codeId":uri,"pageTitle":s["path"],"codeList":[{"language":item["language"],"code":body}]})
    return {"codeSnippets":code,"infoSnippets":info,"message":result.get("message"),"local":{"budget":result["budget"],"freshness":result["freshness"],"warnings":result["warnings"],"coverage":result["coverage"],"reason":result.get("reason")}}


def text_payload(result):
    blocks = []
    if result["warnings"]:
        blocks.extend(result["warnings"])
    for item in result["results"]:
        body = item["text"]
        fence = "`" * max(3,1+max((len(m[0]) for m in re.finditer(r"`+",body)),default=0))
        blocks.append(f"### {item['title']}\n{citation(item)}\n{item['header']['text']}\n{item['description']}\nQuoted source data:\n{fence}{item['language']}\n{body}\n{fence}\n---")
    return "\n\n".join(blocks) if blocks else result.get("message") or EMPTY
