import hashlib
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent
MODELS = [
    ("minishlab/potion-code-16M-v2", "e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b", ["config.json", "model.safetensors", "tokenizer.json", "modules.json", "README.md"]),
    ("Qdrant/bge-small-en-v1.5-onnx-Q", "aa8f8b060edb00e03bfdd08813a2949946c8ba55", ["config.json", "model_optimized.onnx", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "README.md"]),
    ("jinaai/jina-embeddings-v2-base-code", "516f4baf13dec4ddddda8631e019b5737c8bc250", ["config.json", "onnx/model.onnx", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "README.md"]),
]
manifest = []
for repo, revision, files in MODELS:
    local = ROOT / "models" / repo.replace("/", "--") / revision
    print("DOWNLOAD", repo, revision, flush=True)
    snapshot_download(repo, revision=revision, local_dir=local, allow_patterns=files, token=False)
    hashes = {}
    for name in files:
        p = local / name
        if p.exists():
            hashes[name] = {"bytes": p.stat().st_size, "sha256": hashlib.file_digest(p.open("rb"), "sha256").hexdigest()}
    item = {"repo": repo, "revision": revision, "directory": str(local), "files": hashes, "bytes": sum(x["bytes"] for x in hashes.values())}
    manifest.append(item)
    (ROOT / "downloads.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("READY", repo, item["bytes"], flush=True)
