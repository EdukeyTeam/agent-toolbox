"""Reproducible fixed-window development proxy; never reads heldout/."""
import collections
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import statistics
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[4]
OUTPUT = REPO / 'evals/retrieval/results/embeddings'
# Set LEGACY_EVAL_CORPORA for checkouts stored outside this repository.
CORPORA = Path(os.environ.get('LEGACY_EVAL_CORPORA', REPO / 'evals/retrieval/corpora')).resolve()
spec = importlib.util.spec_from_file_location('embedding_bench_provider', REPO / 'skills/legacy-codebase-workflows/scripts/local_context/embed.py')
embed = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = embed
spec.loader.exec_module(embed)

MODELS = {
    'potion': ('minishlab/potion-code-16M-v2', 'minishlab/potion-code-16M-v2'),
    'bge': ('BAAI/bge-small-en-v1.5', 'Qdrant/bge-small-en-v1.5-onnx-Q'),
    'jina': ('jinaai/jina-embeddings-v2-base-code', 'jinaai/jina-embeddings-v2-base-code'),
}
SUFFIXES = {'.py','.pyi','.js','.ts','.tsx','.jsx','.mjs','.cjs','.java','.md','.mdx','.c','.h','.cpp','.rs','.go','.sh','.css','.html','.vue','.svelte','.kt','.rb','.php','.cs'}

def windows(name):
    result = []
    root = CORPORA / name
    # Prune dependency and git trees before walking; never follow directory links.
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', 'node_modules'} and not (Path(directory)/d).is_symlink())
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.is_symlink() or path.suffix.lower() not in SUFFIXES or path.stat().st_size > 1_000_000:
                continue
            data = path.read_bytes()
            if b'\0' in data:
                continue
            try:
                lines = data.decode('utf-8').splitlines()
            except UnicodeError:
                continue
            relative = path.relative_to(root).as_posix()
            for start in range(0, len(lines), 45):
                end = min(start + 60, len(lines))
                result.append({'path': relative, 'start': start+1, 'end': end, 'text': relative + '\n' + '\n'.join(lines[start:end]), 'file_sha256': hashlib.sha256(data).hexdigest()})
                if end == len(lines):
                    break
    return result

def tokens(text):
    # Preserve full identifiers and add snake/camel components; no stopwords.
    output = []
    for term in re.findall(r'\w+', text):
        output.append(term.casefold())
        parts = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', term).replace('_',' ').casefold().split()
        if parts != [term.casefold()]:
            output.extend(parts)
    return output

def lexical_rank(wins, questions):
    counts = [collections.Counter(tokens(w['text'])) for w in wins]
    lengths = [sum(c.values()) for c in counts]
    average = statistics.mean(lengths)
    postings = collections.defaultdict(list)
    for i, count in enumerate(counts):
        for term, n in count.items():
            postings[term].append((i,n))
    output = []
    for question in questions:
        scores = collections.defaultdict(float)
        for term in set(tokens(question['question'])):
            entries = postings[term]
            idf = math.log(1+(len(wins)-len(entries)+0.5)/(len(entries)+0.5))
            for i, n in entries:
                scores[i] += idf*n*2.2/(n+1.2*(0.25+0.75*lengths[i]/average))
        output.append(sorted(scores, key=lambda i:(-scores[i],i)))
    return output

def hit(window, expected):
    return any(window['path']==e['path'] and window['start']<=e['end'] and window['end']>=e['start'] for e in expected)

def score(ranks, wins, questions):
    details = []
    for order, question in zip(ranks, questions):
        first = next((r for r,i in enumerate(order,1) if hit(wins[i],question['expected'])),None)
        details.append({'id':question['id'],'kind':question['kind'],'first_hit_rank':first,
                        'top10':[{'path':wins[i]['path'],'start':wins[i]['start'],'end':wins[i]['end']} for i in order[:10]]})
    return {**{f'hit@{k}':sum(d['first_hit_rank'] is not None and d['first_hit_rank']<=k for d in details)/len(details) for k in [1,5,10]},
            'mrr':statistics.mean(1/d['first_hit_rank'] if d['first_hit_rank'] else 0 for d in details),'questions':len(details),'per_question':details}

def footprint():
    distributions = []
    seen=set()
    total=0
    for dist in importlib.metadata.distributions():
        size=0
        for f in dist.files or []:
            p=Path(dist.locate_file(f))
            if p.is_file() and p not in seen:
                seen.add(p);size+=p.stat().st_size
        total+=size
        distributions.append({'name':dist.metadata['Name'],'version':dist.version,'installed_bytes':size})
    return {'total_bytes':total,'packages':sorted(distributions,key=lambda p:p['name'].lower())}

def percentile(values,p):
    return sorted(values)[min(len(values)-1, math.ceil(len(values)*p)-1)]

def main():
    key = sys.argv[1]
    name, repo = MODELS[key]
    manifest = next(m for m in json.loads((ROOT/'downloads.json').read_text()) if m['repo']==repo and (key!='jina' or m.get('variant')=='official-int8'))
    batch_size=1 if key=='jina' else 16
    t0=time.perf_counter()
    provider=embed.create_provider(embed.EmbedConfig(provider='local-python',model=name,revision=manifest['revision'],model_dir=manifest['directory'],batch_size=batch_size))
    result={'model':name,'revision':manifest['revision'],'identity':provider.identity,'load_seconds':time.perf_counter()-t0,
            'download_bytes':manifest['bytes'],'runtime':footprint(),'cpu_count':os.cpu_count(),'cpu_affinity':sorted(os.sched_getaffinity(0)),
            'batch_size':batch_size,'max_input_chars':8000,'weight_variant':manifest.get('variant','supported-default'),'corpora':{}}
    for corpus in ['httpx','vite','jftp']:
        wins=windows(corpus)
        questions=[json.loads(line) for line in (REPO/f'evals/retrieval/questions/{corpus}.dev.jsonl').read_text().splitlines() if line.strip()]
        questions=[q for q in questions if q['kind']!='absent' and q['expected']]
        print('INDEX',key,corpus,len(wins),flush=True)
        t0=time.perf_counter(); before=provider.truncated
        pieces=[]
        work_block=32 if key=='jina' else 128
        for start in range(0,len(wins),work_block):
            pieces.extend(provider.embed_documents([w['text'] for w in wins[start:start+work_block]]))
            print('PROGRESS',key,corpus,min(start+work_block,len(wins)),round(time.perf_counter()-t0,2),flush=True)
        seconds=time.perf_counter()-t0
        trunc=provider.truncated-before
        matrix=np.asarray(pieces,dtype=np.float32)
        del pieces
        dense=[];latencies=[];scan_times=[]
        for question in questions:
            t0=time.perf_counter();q=provider.embed_query(question['question']);latencies.append(time.perf_counter()-t0)
            t0=time.perf_counter();scores=matrix@np.asarray(q,dtype=np.float32)
            dense.append(np.lexsort((np.arange(len(wins)),-scores)).tolist());scan_times.append(time.perf_counter()-t0)
        lexical=lexical_rank(wins,questions)
        hybrid=[]
        for d,l in zip(dense,lexical):
            fused=collections.defaultdict(float)
            for order in (d,l):
                for rank,i in enumerate(order,1): fused[i]+=1/(60+rank)
            hybrid.append(sorted(fused,key=lambda i:(-fused[i],i)))
        output={'windows':len(wins),'files':len(set(w['path'] for w in wins)), 'questions':len(questions),
                'source_fingerprint':hashlib.sha256(json.dumps([(w['path'],w['start'],w['end'],w['file_sha256']) for w in wins],separators=(',',':')).encode()).hexdigest(),
                'unreachable_questions':[q['id'] for q in questions if not any(hit(w,q['expected']) for w in wins)],
                'index_seconds':seconds,'windows_per_second':len(wins)/seconds,'truncated_windows':trunc,
                'query_embed_ms_p50':statistics.median(latencies)*1000,'query_embed_ms_p95':percentile(latencies,.95)*1000,
                'rank_scan_ms_p50':statistics.median(scan_times)*1000,'query_embed_ms_samples':[t*1000 for t in latencies],
                'dense':score(dense,wins,questions),'bm25':score(lexical,wins,questions),'hybrid_rrf60':score(hybrid,wins,questions)}
        result['corpora'][corpus]=output
        result['peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/f'{key}.json').write_text(json.dumps(result,indent=2)+'\n')
        print('RESULT',key,corpus,{mode:{k:v for k,v in output[mode].items() if k!='per_question'} for mode in ['dense','bm25','hybrid_rrf60']},'windows/s',round(len(wins)/seconds,2),flush=True)
    provider.close()
    print('FINISHED',key,flush=True)

if __name__=='__main__': main()
