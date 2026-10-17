"""Provider contracts and exact vector engines. No downloads or external calls."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import random
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import URLError

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/legacy-codebase-workflows/scripts/local_context'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


embed = load('test_local_embed_module', SCRIPTS / 'embed.py')
vectors = load('test_local_vectors_module', SCRIPTS / 'vectors.py')


class VectorTests(unittest.TestCase):
    def test_float32_little_endian_roundtrip(self):
        self.assertEqual(vectors.pack([1.0, -2.5]), b'\x00\x00\x80?\x00\x00 \xc0')
        self.assertEqual(vectors.unpack(vectors.pack([1.25, -3.5])), [1.25, -3.5])
        for value in (b'', b'x', struct.pack('<f', float('nan'))):
            with self.assertRaises(ValueError):
                vectors.unpack(value)
        with self.assertRaises(ValueError):
            vectors.pack([1e300])

    def test_normalization_validation(self):
        self.assertEqual(vectors.normalize([3, 4]), [0.6, 0.8])
        self.assertEqual(vectors.normalize([1e300, 0]), [1, 0])
        for value in ([], [0, 0], [float('inf')], [float('nan')], [True], ['1'], [10**400]):
            with self.assertRaises(ValueError):
                vectors.normalize(value)

    def oracle_case(self, engine):
        rng = random.Random(101)
        q = vectors.normalize([rng.uniform(-1, 1) for _ in range(9)])
        rows = [(i, vectors.pack(vectors.normalize([rng.uniform(-1, 1) for _ in q]))) for i in range(8203)]
        oracle = [(i, math.fsum(a*b for a,b in zip(q, vectors.normalize(vectors.unpack(blob))))) for i,blob in rows]
        oracle.sort(key=lambda pair: (-round(pair[1], 6), pair[0]))
        actual = vectors.top_k(q, iter(rows), 17, engine)
        self.assertEqual([i for i,_ in actual], [i for i,_ in oracle[:17]])
        for (_,score), (_,expected) in zip(actual,oracle):
            self.assertAlmostEqual(score, expected, places=6)

    def test_stdlib_matches_float64_oracle_across_batches(self):
        self.oracle_case('stdlib')

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional numpy is missing')
    def test_numpy_matches_float64_oracle_across_batches(self):
        import numpy
        self.assertEqual(vectors.normalize(numpy.asarray([3,4],dtype=numpy.float32)),[0.6,0.8])
        self.oracle_case('numpy')

    @unittest.skipUnless(importlib.util.find_spec('sqlite_vec'), 'optional sqlite-vec is missing')
    def test_sqlite_vec_matches_float64_oracle_across_batches(self):
        self.oracle_case('sqlite-vec')

    def test_top_k_validation_and_ties(self):
        rows = [(9,vectors.pack([1,0])), (3,vectors.pack([1,0])), (5,vectors.pack([-1,0]))]
        for engine in vectors.available_engines():
            self.assertEqual(vectors.top_k([1,0],rows,9,engine), [(3,1.0),(9,1.0),(5,-1.0)])
            self.assertEqual(vectors.top_k([1,0],rows,0,engine), [])
            # Partitioning must retain small IDs tied at its cutoff, including
            # when the next scan batch contains all the smallest IDs.
            tied=[(i,vectors.pack([1,0])) for i in reversed(range(5001))]
            self.assertEqual(vectors.top_k([1,0],tied,7,engine),[(i,1.0) for i in range(7)])
            for bad in ([(1,vectors.pack([1]))], [(1,vectors.pack([0,0]))], [(1,struct.pack('<2f',1,float('nan')))]):
                with self.assertRaises(ValueError): vectors.top_k([1,0],bad,1,engine)
        for kwargs in ({'k':-1}, {'k':True}, {'k':1,'engine':'approximate'}):
            with self.assertRaises(ValueError): vectors.top_k([1,0], rows, **kwargs)
        for bad in ([(1,vectors.pack([1]))], [(1,vectors.pack([0,0]))], [(True,vectors.pack([1,0]))]):
            with self.assertRaises(ValueError): vectors.top_k([1,0],bad,1,'stdlib')

    def test_stdlib_does_not_import_optional_runtimes(self):
        original = vectors.importlib.import_module
        def guarded(name, *args):
            self.assertNotIn(name, ['numpy','sqlite_vec','fastembed','model2vec'])
            return original(name,*args)
        with patch.object(vectors.importlib,'import_module',side_effect=guarded):
            self.assertEqual(vectors.top_k([1],[(1,vectors.pack([2]))],1,'stdlib'),[(1,1.0)])


class ConfigTests(unittest.TestCase):
    def test_none_and_environment_preserve_consent(self):
        self.assertIsNone(embed.create_provider(embed.EmbedConfig()))
        values = {'LEGACY_EMBED_PROVIDER':'openai-compatible','LEGACY_EMBED_MODEL':'demo',
                  'LEGACY_EMBED_BASE_URL':'https://remote.example/v1','LEGACY_EMBED_API_KEY_ENV':'MY_KEY',
                  'LEGACY_EMBED_MODEL_DIR':'/a/model','LEGACY_EMBED_ALLOW_REMOTE':'true','LEGACY_EMBED_ALLOW_DOWNLOAD':'true'}
        with patch.dict(os.environ,values,clear=True):
            c = embed.config_from_env()
        self.assertEqual(c.api_key_env,'MY_KEY')
        self.assertEqual(c.model_dir,'/a/model')
        self.assertFalse(c.allow_remote)
        self.assertFalse(c.allow_download)
        with self.assertRaises(embed.ConsentRequired): embed.create_provider(c)

    def test_loopback_spelling_and_invalid_urls(self):
        for url in ['http://127.0.0.1:123/v1','https://[::1]/v1','http://LOCALHOST/v1']:
            self.assertTrue(embed.is_loopback_url(url),url)
        for url in ['http://127.1','http://127.0.0.2','http://2130706433','http://localhost.example','http://[::ffff:127.0.0.1]',
                    'http://alias.local','file:///a','http://u:secret@localhost','http://localhost?key=secret','http://localhost/#secret',
                    'http://localhost:999999', 'http://localhost\n.evil']:
            self.assertFalse(embed.is_loopback_url(url),url)

    def test_remote_consent_before_network(self):
        with patch.object(socket,'getaddrinfo',side_effect=AssertionError('network attempted')):
            with self.assertRaises(embed.ConsentRequired):
                embed.create_provider(embed.EmbedConfig(provider='openai-compatible',model='m',base_url='https://remote.example/v1'))
            p=embed.create_provider(embed.EmbedConfig(provider='openai-compatible',model='m',base_url='https://remote.example/v1',allow_remote=True))
            self.assertTrue(p.identity['allow_remote'])
            p.close()

    def test_invalid_configuration(self):
        for changes in ({'provider':'unknown'}, {'provider':'local-python','batch_size':0}, {'provider':'local-python','max_input_chars':True},
                        {'provider':'local-python','allow_remote':'false'}, {'provider':'local-python','allow_download':'false'}):
            with self.assertRaises(embed.EmbeddingError): embed.create_provider(embed.EmbedConfig(**changes))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.requests=[]
        self.reply=None
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.requests.append((self.path,request,dict(self.headers)))
                if outer.reply:
                    code,body,headers=outer.reply(request)
                else:
                    code,body,headers=200,{'data':[{'index':i,'embedding':[len(t)+1,2,3]} for i,t in reversed(list(enumerate(request['input']))) ]},{}
                self.send_response(code)
                for k,v in headers.items(): self.send_header(k,v)
                self.end_headers()
                self.wfile.write(body if isinstance(body,bytes) else json.dumps(body).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.02),daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/v1'
        self.provider=embed.create_provider(embed.EmbedConfig(provider='openai-compatible',base_url=self.url,model='test',batch_size=2,max_input_chars=5))

    def tearDown(self):
        self.provider.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_batches_order_normalization_truncation_and_empty(self):
        result=self.provider.embed_documents(['abcdef','b','cccc'])
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[0][0],'/v1/embeddings')
        self.assertEqual(self.requests[0][1],{'model':'test','input':['abcde','b']})
        self.assertEqual(result[0],embed._normalized([6,2,3]))
        self.assertEqual(result[1],embed._normalized([2,2,3]))
        self.assertEqual(self.provider.truncated,1)
        self.assertEqual(self.provider.identity['dimension'],3)
        self.assertEqual(self.provider.embed_documents([]),[])
        self.assertEqual(self.provider.embed_query('x'),embed._normalized([2,2,3]))
        unicode_provider=embed.create_provider(embed.replace(self.provider.config,max_input_chars=8000))
        unicode_provider.embed_query('\U0001f600'*7000)
        self.assertEqual(len(self.requests[-1][1]['input'][0]),7000)
        self.assertEqual(unicode_provider.truncated,0)
        unicode_provider.close()
        self.provider.close()
        with self.assertRaises(embed.EmbeddingError): self.provider.embed_query('x')

    def test_malformed_vectors_and_indexes(self):
        bad_responses=[{}, {'data':[]}, {'data':[{'index':True,'embedding':[1]}]},
                       {'data':[{'index':0,'embedding':[0,0]}]}, {'data':[{'index':0,'embedding':[float('inf')]}]},
                       {'data':[{'index':0,'embedding':[True]}]}, {'data':[{'index':0,'embedding':[10**400]}]},
                       {'data':[{'index':0,'embedding':[]}]}, b'not JSON']
        for body in bad_responses:
            with self.subTest(body=body):
                self.reply=lambda request:(200,body,{})
                with self.assertRaises(embed.EmbeddingError): self.provider.embed_query('x')
        self.reply=lambda request:(200,{'data':[{'index':0,'embedding':[1]},{'index':0,'embedding':[2]}]}, {})
        with self.assertRaises(embed.EmbeddingError): self.provider.embed_documents(['a','b'])

    def test_dimension_changes_fail(self):
        self.provider.embed_query('x')
        self.reply=lambda request:(200,{'data':[{'index':0,'embedding':[1,2]}]}, {})
        with self.assertRaises(embed.EmbeddingError): self.provider.embed_query('x')

    def test_nomic_task_prefixes_are_asymmetric_and_bounded(self):
        provider=embed.create_provider(embed.replace(self.provider.config,model='nomic-embed-text:v1.5',max_input_chars=32))
        provider.embed_documents(['hello','search_document: already'])
        provider.embed_query('hello')
        self.assertEqual(self.requests[0][1]['input'],['search_document: hello','search_document: already'])
        self.assertEqual(self.requests[1][1]['input'],['search_query: hello'])
        provider.embed_query('x'*100)
        self.assertEqual(len(self.requests[-1][1]['input'][0]),32)
        self.assertEqual(provider.truncated,1)
        provider.close()

    def test_error_bodies_and_transport_details_never_exposed(self):
        secret='sk-test-do-not-echo-this'
        self.reply=lambda request:(401,{'error':secret,'source':'private source text'}, {})
        with self.assertRaises(embed.EmbeddingError) as caught: self.provider.embed_query('x')
        self.assertNotIn(secret,str(caught.exception))
        self.assertNotIn('private source',str(caught.exception))
        self.assertIn('HTTP 401',str(caught.exception))
        with patch.object(self.provider._opener,'open',side_effect=URLError(secret)):
            with self.assertRaises(embed.EmbeddingError) as caught: self.provider.embed_query('x')
        self.assertNotIn(secret,str(caught.exception))
        with patch.object(self.provider._opener,'open',side_effect=IncompleteRead(secret.encode())):
            with self.assertRaises(embed.EmbeddingError) as caught: self.provider.embed_query('x')
        self.assertNotIn(secret,str(caught.exception))

    def test_redirects_are_refused(self):
        for location in [self.url+'/elsewhere','https://other.example/v1/embeddings']:
            before=len(self.requests)
            self.reply=lambda request:(307,b'',{'Location':location})
            with self.assertRaises(embed.EmbeddingError): self.provider.embed_query('x')
            self.assertEqual(len(self.requests),before+1)

    def test_no_ambient_proxy_and_auth_name_only(self):
        config=embed.EmbedConfig(provider='openai-compatible',base_url=self.url,model='test',api_key_env='TEST_EMBED_KEY')
        with patch.dict(os.environ,{'TEST_EMBED_KEY':'test-secret','HTTP_PROXY':'http://invalid.example:1','HTTPS_PROXY':'http://invalid.example:1'},clear=True):
            provider=embed.create_provider(config)
            provider.embed_query('x')
            provider.close()
        self.assertEqual(self.requests[-1][2]['Authorization'],'Bearer test-secret')
        self.assertNotIn('test-secret',json.dumps(provider.identity))
        with self.assertRaises(embed.EmbeddingError): embed.create_provider(embed.replace(config,api_key_env='literal-key-with-hyphens'))

    def test_localhost_resolution_must_stay_local(self):
        provider=embed.create_provider(embed.replace(self.provider.config,base_url=self.url.replace('127.0.0.1','localhost')))
        with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.1',80))]):
            with self.assertRaises(embed.EmbeddingError): provider.embed_query('x')
        self.assertFalse(self.requests)
        provider.close()

    def test_request_and_response_limits(self):
        # Force splitting with a small bound, without sending large fixtures.
        provider=embed.create_provider(embed.replace(self.provider.config,batch_size=8))
        with patch.object(embed,'_MAX_REQUEST',48):
            self.assertEqual(len(provider.embed_documents(['abcde']*4)),4)
        self.assertGreater(len(self.requests),1)
        self.reply=lambda request:(200,b'X'*101,{})
        with patch.object(embed,'_MAX_RESPONSE',100):
            with self.assertRaises(embed.EmbeddingError): provider.embed_query('x')
        provider.close()


class LocalTests(unittest.TestCase):
    def test_fastembed_offline_contract_telemetry_and_task_methods(self):
        calls=[]
        class FakeEmbedding:
            embedding_size=2
            model=types.SimpleNamespace(tokenizer=types.SimpleNamespace(truncation={'max_length':512},
                  encode_batch=lambda texts:[types.SimpleNamespace(overflowing=(['overflow'] if len(t)>3 else [])) for t in texts]))
            @classmethod
            def list_supported_models(cls):
                return [{'model':'org/model','sources':{'hf':'org/onnx'},'model_file':'onnx/model.onnx','additional_files':[]}]
            def __init__(self,**kwargs):
                calls.append(('load',kwargs))
                self.assert_offline=kwargs['local_files_only']
            def passage_embed(self,texts,**kwargs):
                calls.append(('passage',texts));return [[1,2] for _ in texts]
            def query_embed(self,texts,**kwargs):
                calls.append(('query',texts));return [[2,1] for _ in texts]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            for name in ['onnx/model.onnx','config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json']:
                file=path/name;file.parent.mkdir(exist_ok=True,parents=True);file.write_text('{}')
            ort=types.SimpleNamespace(disable_telemetry_events=lambda:calls.append(('telemetry-off',)))
            with patch.dict(sys.modules,{'fastembed':types.SimpleNamespace(TextEmbedding=FakeEmbedding),'onnxruntime':ort}):
                p=embed.create_provider(embed.EmbedConfig(provider='local-python',model='org/model',model_dir=directory,max_input_chars=5))
                self.assertEqual(calls[0],('telemetry-off',))
                self.assertTrue(calls[1][1]['local_files_only'])
                self.assertEqual(calls[1][1]['providers'],['CPUExecutionProvider'])
                p.embed_documents(['long','longer-than-character-cap'])
                self.assertEqual(p.truncated,2)  # One token truncation, one char truncation, no double counting.
                self.assertEqual(p.embed_query('x'),embed._normalized([2,1]))
                self.assertEqual([c[0] for c in calls[-2:]],['passage','query'])
                p.close()

    def fake_model2vec(self):
        class Model:
            embedding=types.SimpleNamespace(shape=(5,2))
            @classmethod
            def from_pretrained(cls,path,**kwargs):
                self.assertTrue(Path(path).is_dir())
                self.assertIsNone(kwargs['max_length'])
                self.assertFalse(kwargs['force_download'])
                return cls()
            def encode(self,texts,**kwargs): return [[len(t)+1,2] for t in texts]
        return types.SimpleNamespace(StaticModel=Model)

    def model_files(self,path):
        path.mkdir(parents=True,exist_ok=True)
        for name in ['config.json','model.safetensors','tokenizer.json']:
            (path/name).write_text('{}')

    def test_local_path_no_network_manifest_and_queries(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'model2vec':self.fake_model2vec()}), patch.object(socket,'create_connection',side_effect=AssertionError('network attempted')):
            path=Path(directory)
            self.model_files(path)
            p=embed.create_provider(embed.EmbedConfig(provider='local-python',model_dir=directory,max_input_chars=4))
            self.assertEqual(p.embed_query('abcde'),embed._normalized([5,2]))
            self.assertEqual(p.truncated,1)
            self.assertEqual(p.identity['dimension'],2)
            self.assertEqual(len(p.identity['manifest_sha256']),3)
            self.assertEqual(p.identity['revision'],embed.DEFAULT_REVISION)
            p.close()
            with self.assertRaises(embed.EmbeddingError): p.embed_query('x')

    def test_missing_cache_requires_consent_and_download_requires_pin(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'model2vec':self.fake_model2vec()}), patch.object(socket,'create_connection',side_effect=AssertionError('network attempted')):
            config=embed.EmbedConfig(provider='local-python',model='minishlab/potion-code-16M-v2',cache_dir=directory,revision='a'*40)
            with self.assertRaises(embed.ConsentRequired): embed.create_provider(config)
            with self.assertRaises(embed.ConsentRequired): embed.create_provider(embed.replace(config,revision='main',allow_download=True))
            path=Path(directory)/'minishlab--potion-code-16M-v2'/('a'*40)
            self.model_files(path)
            p=embed.create_provider(config)
            self.assertEqual(len(p.embed_documents(['x'])),1)
            p.close()

    def test_incomplete_manual_files_never_download(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'model2vec':self.fake_model2vec()}), patch.object(socket,'create_connection',side_effect=AssertionError('network attempted')):
            with self.assertRaises(embed.EmbeddingError):
                embed.create_provider(embed.EmbedConfig(provider='local-python',model_dir=directory,allow_download=True))

    def test_download_uses_exact_revision_and_manifest_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'model2vec':self.fake_model2vec()}):
            def download(repo,**kwargs):
                self.assertEqual(kwargs['revision'],'a'*40)
                self.assertFalse(kwargs['token'])
                self.assertEqual(set(kwargs['allow_patterns']),{'config.json','model.safetensors','tokenizer.json'})
                self.model_files(Path(kwargs['local_dir']))
            with patch.dict(sys.modules,{'huggingface_hub':types.SimpleNamespace(snapshot_download=download)}):
                p=embed.create_provider(embed.EmbedConfig(provider='local-python',model='model2vec:minishlab/test',cache_dir=directory,revision='a'*40,allow_download=True))
                self.assertEqual(p.identity['model'],'minishlab/test')
                p.close()

    @unittest.skipUnless(os.environ.get('LEGACY_TEST_POTION_DIR'), 'set LEGACY_TEST_POTION_DIR to test real offline model')
    def test_real_model2vec_offline(self):
        with patch.object(socket,'create_connection',side_effect=AssertionError('network attempted')):
            p=embed.create_provider(embed.EmbedConfig(provider='local-python',model_dir=os.environ['LEGACY_TEST_POTION_DIR']))
            self.assertEqual(len(p.embed_query('Where is the HTTP client implemented?')),256)
            self.assertAlmostEqual(math.hypot(*p.embed_query('read file')),1)
            p.close()

    @unittest.skipUnless(os.environ.get('LEGACY_TEST_FASTEMBED_DIR'), 'set LEGACY_TEST_FASTEMBED_DIR to test real offline model')
    def test_real_fastembed_offline(self):
        with patch.object(socket,'create_connection',side_effect=AssertionError('network attempted')):
            p=embed.create_provider(embed.EmbedConfig(provider='local-python',model='BAAI/bge-small-en-v1.5',model_dir=os.environ['LEGACY_TEST_FASTEMBED_DIR']))
            self.assertEqual(len(p.embed_query('read file')),384)
            self.assertAlmostEqual(math.hypot(*p.embed_query('read file')),1)
            p.close()


class JSTests(unittest.TestCase):
    def helper(self, directory, code):
        runtime=Path(directory)/'runtime'
        entry=runtime/'node_modules/@huggingface/transformers/src/transformers.js'
        entry.parent.mkdir(parents=True)
        entry.write_text('')
        cache=Path(directory)/'cache';cache.mkdir()
        config=embed.EmbedConfig(provider='transformers-js',model='Xenova/test',revision='a'*40,cache_dir=str(cache),runtime_dir=str(runtime),batch_size=2,max_input_chars=4)
        real_popen=subprocess.Popen
        def launch(argv,**kwargs):
            self.assertEqual(argv[-1],'offline')
            self.assertNotIn('TEST_EMBED_SECRET',kwargs['env'])
            self.assertNotIn('NODE_OPTIONS',kwargs['env'])
            return real_popen([sys.executable,'-u','-c',code],**kwargs)
        with patch.object(embed.shutil,'which',return_value=sys.executable), patch.object(embed.subprocess,'Popen',side_effect=launch):
            return embed.create_provider(config)

    def test_persistent_worker_batches_sanitized_environment_and_close(self):
        code='import sys,json\nfor line in sys.stdin:\n texts=json.loads(line);print(json.dumps([[len(t)+1,2] for t in texts]),flush=True)'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'TEST_EMBED_SECRET':'do not inherit','NODE_OPTIONS':'--invalid'}):
            p=self.helper(directory,code)
            pid=p._process.pid
            try:
                self.assertEqual(len(p.embed_documents(['a','abcdef','b'])),3)
                self.assertEqual(p.embed_query('x'),embed._normalized([2,2]))
                self.assertEqual(p._process.pid,pid)
                self.assertIsNone(p._process.poll())
                self.assertEqual(p.truncated,1)
                p.config=embed.replace(p.config,max_input_chars=12000)
                self.assertEqual(p.embed_query('\U0001f600'*7000),embed._normalized([6001,2]))
                self.assertEqual(p.truncated,2)
                p.embed_query('\U0001f600'*13000)
                self.assertEqual(p.truncated,3)  # Char and UTF-16 caps count this input once.
                self.assertEqual(p.embed_query('a'+'\U0001f600'*7000),embed._normalized([6001,2]))
                self.assertEqual(p.truncated,4)
            finally: p.close()
            self.assertIsNotNone(p._process.poll())
            self.assertFalse(p._reader.is_alive())

    def test_timeout_reaps_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.helper(directory,'import time; time.sleep(10)')
            with patch.object(embed,'_TIMEOUT',.02):
                with self.assertRaises(embed.EmbeddingError): p.embed_query('x')
            self.assertIsNotNone(p._process.poll())
            p.close()

    def test_blocked_pipe_write_is_timed_out_and_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.helper(directory,'import time; time.sleep(10)')
            p.config=embed.replace(p.config,max_input_chars=12000,batch_size=32)
            with patch.object(embed,'_TIMEOUT',.02):
                with self.assertRaises(embed.EmbeddingError): p.embed_documents(['a'*12000]*32)
            self.assertIsNotNone(p._process.poll())
            self.assertFalse(any(t.name=='embedding-js-writer' and t.is_alive() for t in threading.enumerate()))

    def test_invalid_helper_output_reaps_process(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.helper(directory,'import sys;sys.stdin.readline();print("secret invalid output",flush=True)')
            with self.assertRaises(embed.EmbeddingError) as caught: p.embed_query('x')
            self.assertNotIn('secret invalid',str(caught.exception))
            self.assertIsNotNone(p._process.poll())


if __name__ == '__main__':
    unittest.main()
