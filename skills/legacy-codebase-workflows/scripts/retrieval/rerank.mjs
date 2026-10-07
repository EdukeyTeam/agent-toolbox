// Optional local cross-encoder. stdout is reserved for bounded JSON score batches.
import { pathToFileURL } from 'node:url';
import { resolve, join } from 'node:path';

const [modelId, revision, cache, runtime, policy] = process.argv.slice(2);
if (!modelId || !/^[a-f0-9]{40}$/.test(revision) || !cache || !runtime || !['download', 'offline'].includes(policy)) {
  throw new Error('Expected model, immutable 40-character revision, cache, runtime, and download|offline');
}
const modulePath = pathToFileURL(join(resolve(runtime), 'node_modules', '@huggingface', 'transformers', 'src', 'transformers.js')).href;
const { AutoTokenizer, AutoModelForSequenceClassification, env } = await import(modulePath);
env.cacheDir = resolve(cache);
env.allowRemoteModels = policy === 'download';
env.allowLocalModels = true;
env.remoteHost = 'https://huggingface.co/';
if (policy === 'offline') {
  globalThis.fetch = async () => { throw new Error('Network access is disabled for local reranking queries'); };
}
const options = { revision, dtype: 'q8', device: 'cpu', local_files_only: policy === 'offline' };
const tokenizer = await AutoTokenizer.from_pretrained(modelId, options);
const model = await AutoModelForSequenceClassification.from_pretrained(modelId, options);
const labelCount = model.config.num_labels ?? Object.keys(model.config.id2label ?? {}).length;
if (labelCount !== 1) {
  throw new Error('Reranker requires a single-logit sequence-classification model');
}
async function scoreLine(line) {
  const request = JSON.parse(line);
  const { query, passages } = request;
  if (typeof query !== 'string' || query.length > 500 || !Array.isArray(passages) || passages.length < 1 || passages.length > 8 || passages.some(p => typeof p !== 'string' || p.length > 256_000)) {
    throw new Error('Reranker input exceeds query, passage, or batch limit');
  }
  const features = await tokenizer(Array(passages.length).fill(query), { text_pair: passages, padding: true, truncation: true, max_length: 512 });
  const logits = (await model(features)).logits;
  if (!Array.isArray(logits.dims) || logits.dims.length !== 2 || logits.dims[0] !== passages.length || logits.dims[1] !== 1 || logits.data.length !== passages.length) {
    throw new Error('Reranker output must contain one scalar logit per passage');
  }
  const scores = Array.from(logits.data);
  if (!scores.every(Number.isFinite)) throw new Error('Reranker returned a non-finite score');
  process.stdout.write(`${JSON.stringify(scores)}\n`);
}

// Bound memory before decoding a line. The Python caller sends at most eight
// 256 KB passages; JSON escapes can expand their encoded size.
const maxLineBytes = 13_000_000;
let pending = Buffer.alloc(0);
for await (const chunk of process.stdin) {
  let start = 0;
  while (start < chunk.length) {
    const newline = chunk.indexOf(10, start);
    const end = newline < 0 ? chunk.length : newline;
    const segment = chunk.subarray(start, end);
    if (pending.length + segment.length > maxLineBytes) throw new Error('Reranker input exceeds size limit');
    pending = Buffer.concat([pending, segment]);
    if (newline < 0) break;
    await scoreLine(pending.toString('utf8'));
    pending = Buffer.alloc(0);
    start = newline + 1;
  }
}
if (pending.length) throw new Error('Reranker input ended without a newline');
