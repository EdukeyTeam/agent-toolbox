// Optional local inference helper. stdout is reserved for JSON vectors.
import { pathToFileURL } from 'node:url';
import { resolve, join } from 'node:path';
import { createInterface } from 'node:readline';

const [model, revision, cache, runtime, policy] = process.argv.slice(2);
if (!model || !/^[a-f0-9]{40}$/.test(revision) || !cache || !runtime || !['download', 'offline'].includes(policy)) {
  throw new Error('Expected model, immutable 40-character revision, cache, runtime, and download|offline');
}
const modulePath = pathToFileURL(join(resolve(runtime), 'node_modules', '@huggingface', 'transformers', 'src', 'transformers.js')).href;
const { pipeline, env } = await import(modulePath);
env.cacheDir = resolve(cache);
env.allowRemoteModels = policy === 'download';
env.allowLocalModels = true;
env.remoteHost = 'https://huggingface.co/';
if (policy === 'offline') {
  globalThis.fetch = async () => { throw new Error('Network access is disabled for local retrieval queries'); };
}
const extractor = await pipeline('feature-extraction', model, { dtype: 'q8', device: 'cpu', revision, local_files_only: policy === 'offline' });
for await (const line of createInterface({ input: process.stdin })) {
  const texts = JSON.parse(line);
  if (!Array.isArray(texts) || texts.length > 32 || texts.some(text => typeof text !== 'string' || text.length > 12000)) {
    throw new Error('Embedding input exceeds batch or text limit');
  }
  const output = await extractor(texts, { pooling: 'mean', normalize: true });
  process.stdout.write(`${JSON.stringify(output.tolist())}\n`);
}
