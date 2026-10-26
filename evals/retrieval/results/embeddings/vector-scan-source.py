import importlib.util
import json
import math
import os
from pathlib import Path
import random
import resource
import statistics
import sys
import time

root=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('scan_vectors',root/'skills/legacy-codebase-workflows/scripts/local_context/vectors.py')
vectors=importlib.util.module_from_spec(spec);spec.loader.exec_module(vectors)
rng=random.Random(166)
blobs=[vectors.pack(vectors.normalize([rng.gauss(0,1) for _ in range(256)])) for _ in range(128)]
query=vectors.normalize([rng.gauss(0,1) for _ in range(256)])
path=root/'evals/retrieval/results/embeddings/vector-scan.json'
result=json.loads(path.read_text()) if len(sys.argv)>1 and path.exists() else {'vectors':100000,'dimension':256,'top_k':10,'batch_size':4096,'python':sys.version,'engines':{}}
result['numpy_validation_for_sqlite_vec']=True
for engine in (sys.argv[1:] or vectors.available_engines()):
    samples=[]
    for _ in range(3):
        t0=time.perf_counter()
        found=vectors.top_k(query,((i,blobs[i%len(blobs)]) for i in range(100000)),10,engine)
        samples.append((time.perf_counter()-t0)*1000)
    result['engines'][engine]={'ms_samples':samples,'ms_median':statistics.median(samples),'ids':[i for i,_ in found]}
    print('SCAN',engine,result['engines'][engine],flush=True)
result['process_peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
path.write_text(json.dumps(result,indent=2)+'\n')
