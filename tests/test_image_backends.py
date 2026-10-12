"""Image setup/provider regression using synthetic keys and local fake services."""
import base64
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import zlib

OUT=Path(__file__).resolve().parent
PACKAGE=OUT.parent
sys.path[:0]=[str(PACKAGE/'launcher'),str(PACKAGE/'skills/sillytavern-roleplay/scripts')]
import image_backends as backends
from image_setup import ImageSetup, KlingConnection
from service_control import PackageService

def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
PNG=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x01\x02\x03\x04'))+chunk(b'IEND',b'')

class FakeAPI:
    def __init__(self):
        owner=self;self.calls=[];self.mode='image';self.port=0
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,value,status=200):
                data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                owner.calls.append((self.path,self.headers.get('Authorization'),None))
                if self.path=='/v1/models':return self.send({'data':[{'id':'image-test'}]})
                return self.send({},404)
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                owner.calls.append((self.path,self.headers.get('Authorization'),body))
                if owner.mode=='reject':return self.send({'error':'DO NOT ECHO SECRET'},401)
                if owner.mode=='bad':return self.send({'data':[{'b64_json':'bm90LWFuLWltYWdl'}]})
                if owner.mode=='url':return self.send({'data':[{'url':'https://images.example.test/a.png?signature=private'}]})
                self.send({'data':[{'b64_json':base64.b64encode(PNG).decode()}]})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def config(self,**extra):return {'provider':'api','base_url':f'http://127.0.0.1:{self.port}/v1','model':'image-test',**extra}
    def posts(self):return [x for x in self.calls if x[2] is not None]

class Images(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='image-isolated-',dir=OUT)
        self.root=Path(self.tmp.name);self.data=self.root/'data';self.data.mkdir()
        self.stack=ExitStack();self.stack.enter_context(patch.dict(os.environ,{'YUKINO_IMAGE_API_KEY':'sk-synthetic-image-test'}))
        self.api=FakeAPI();self.stack.callback(self.api.close)
        self.setup=ImageSetup(PACKAGE/'skills/sillytavern-roleplay',self.data,PACKAGE)
        self.stack.callback(self.setup.close)
    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def job(self,name='test'):return self.data/'browser/image-jobs'/name
    def service(self,**extra):return backends.ApiImageService(self.data,self.api.config(**extra))
    def test_models_check_never_generates(self):
        value=backends.check_api(self.api.config(),'sk-synthetic-only')
        self.assertTrue(value['connected']);self.assertFalse(value['generation_verified']);self.assertEqual(len(self.api.posts()),0)
    def test_generation_returns_real_local_png(self):
        path=Path(self.service().generate('A background',[], 'branch-A',self.job())[0])
        self.assertEqual(path.read_bytes(),PNG);self.assertTrue(path.is_relative_to(self.job()))
        payload=json.loads(self.api.posts()[0][2]);self.assertEqual(payload['n'],1);self.assertEqual(payload['size'],'1536x1024')
    def test_same_job_ready_reuses_without_charge(self):
        s=self.service();a=s.generate('Background',[],'A',self.job());b=s.generate('Background',[],'A',self.job())
        self.assertEqual(a,b);self.assertEqual(len(self.api.posts()),1)
    def test_references_use_edits_and_preserve_bytes(self):
        reference=self.root/'reference.png';reference.write_bytes(PNG)
        self.service().generate('TRANSPARENT character',[reference],'A',self.job())
        path,key,body=self.api.posts()[0];self.assertEqual(path,'/v1/images/edits');self.assertIn(PNG,body)
        self.assertIn(b'transparent',body);self.assertIn(b'1024x1536',body)
    def test_unsupported_references_never_ignored(self):
        p=self.root/'ref.png';p.write_bytes(PNG)
        with self.assertRaisesRegex(ValueError,'参考图'):self.service(reference_mode='none').generate('Character',[p],'A',self.job())
        self.assertEqual(len(self.api.posts()),0)
    def test_missing_reference_never_submits(self):
        with self.assertRaises(ValueError):self.service().generate('Sprite',[self.root/'missing.png'],'A',self.job())
        self.assertEqual(len(self.api.posts()),0)
    def test_output_cannot_escape_image_jobs(self):
        with self.assertRaisesRegex(ValueError,'越界'):self.service().generate('Test',[],'A',self.root/'outside')
        self.assertEqual(len(self.api.posts()),0)
    def test_unknown_charge_never_automatically_repeated(self):
        s=self.service()
        with patch.object(backends,'json_request',side_effect=ValueError('connection lost')) as call:
            with self.assertRaises(ValueError):s.generate('Test',[],'A',self.job())
            with self.assertRaisesRegex(ValueError,'扣费'):s.generate('Test',[],'A',self.job())
            self.assertEqual(call.call_count,1)
    def test_known_rejection_can_retry_without_echoing_body(self):
        self.api.mode='reject';s=self.service()
        with self.assertRaises(ValueError) as error:s.generate('Test',[],'A',self.job())
        self.assertNotIn('SECRET',str(error.exception));self.api.mode='image'
        self.assertTrue(Path(s.generate('Test',[],'A',self.job())[0]).is_file())
    def test_download_failure_retries_download_not_generation(self):
        self.api.mode='url';s=self.service()
        with patch.object(backends,'download_image',side_effect=[ValueError('download failed'),PNG]) as download:
            with self.assertRaises(ValueError):s.generate('Test',[],'A',self.job())
            self.assertTrue(Path(s.generate('Test',[],'A',self.job())[0]).is_file())
            self.assertEqual(download.call_count,2)
        self.assertEqual(len(self.api.posts()),1)
    def test_bad_image_is_not_success_and_not_recharged(self):
        self.api.mode='bad';s=self.service()
        for i in range(2):
            with self.assertRaises(ValueError):s.generate('Test',[],'A',self.job())
        self.assertEqual(len(self.api.posts()),1)
    def test_cdn_local_and_credential_urls_rejected(self):
        for url in ['http://127.0.0.1/a.png','https://key:secret@cdn.example/a.png']:
            with self.assertRaises(ValueError):backends.download_image(url)
    def test_invalid_provider_no_silent_fallback(self):
        backends.config_path(self.data).parent.mkdir(exist_ok=True)
        backends.config_path(self.data).write_text('{"provider":"unknown"}')
        with self.assertRaisesRegex(ValueError,'回退'):backends.make_image_service(self.data,'codex',{})
    def test_api_needs_no_codex_cli(self):
        backends.write_config(self.data,self.api.config())
        self.assertIsInstance(backends.make_image_service(self.data,None,{}),backends.ApiImageService)
    def test_off_does_not_construct_service(self):
        backends.write_config(self.data,{'provider':'off'})
        self.assertIsNone(backends.make_image_service(self.data,None,{}))
    def test_codex_choice_needs_actual_preflight(self):
        with self.assertRaisesRegex(ValueError,'握手'):self.setup.save_choice({'provider':'codex'})
        self.assertFalse(backends.config_path(self.data).exists())
    def test_model_failure_keeps_old_key_and_config(self):
        backends.write_config(self.data,{'provider':'off'})
        before=backends.config_path(self.data).read_bytes()
        with self.assertRaisesRegex(ValueError,'模型'):self.setup.save_choice(self.api.config(model='missing',key='synthetic'))
        self.assertEqual(backends.config_path(self.data).read_bytes(),before);self.assertFalse(backends.credential_path(self.data).exists())
    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_key_dpapi_binding_does_not_send_to_new_host(self):
        backends.store_api_key(self.data,'synthetic-key',self.api.config()['base_url'])
        with patch.dict(os.environ,{'YUKINO_IMAGE_API_KEY':''}):
            self.assertEqual(backends.load_api_key(self.data,self.api.config()['base_url']),'synthetic-key')
            with self.assertRaises(ValueError):backends.load_api_key(self.data,'https://different.example/v1')
        self.assertNotIn('synthetic-key',backends.credential_path(self.data).read_text())
    def test_key_write_failure_restores_previous_config(self):
        backends.write_config(self.data,{'provider':'off'});before=backends.config_path(self.data).read_bytes()
        with patch.object(backends,'store_api_key',side_effect=OSError('write failure')):
            with self.assertRaises(OSError):self.setup.save_choice(self.api.config(key='new-synthetic'))
        self.assertEqual(backends.config_path(self.data).read_bytes(),before)
    def test_loopback_no_key_only_local(self):
        backends.validate_config(self.api.config(local_no_key=True))
        with self.assertRaises(ValueError):backends.validate_config({'provider':'api','base_url':'https://remote.example/v1','model':'image-test','local_no_key':True})
    def test_install_pinned_private_not_global(self):
        with patch('image_setup.shutil.which',return_value='node-test'),patch('image_setup.hidden_run',return_value=Mock(returncode=0)) as run:
            self.setup.install('@openai/codex@0.160.1','codex')
            command=run.call_args.args[0];self.assertIn('--prefix',command);self.assertIn('--ignore-scripts',command);self.assertNotIn('-g',command)
    def test_running_service_cannot_claim_new_image_provider(self):
        backends.write_config(self.data,self.api.config());s=PackageService(PACKAGE/'skills/sillytavern-roleplay',self.data,'5.7.10-world-trial',Mock())
        h={'app':'galgame','root':str(self.data),'provider':'deepseek','app_version':'5.7.10-world-trial','image_provider':'codex','dynamic_images':False}
        with patch.object(s,'find',return_value=(20000,h)):
            ok,message=s.start(20000)
        self.assertFalse(ok);self.assertIn('停止',message);s.run_python.assert_not_called()
    def test_invalid_url_rejects_credentials_and_cleartext_remote(self):
        for value in ['http://remote.example/v1','https://user:secret@example.com/v1','https://example.com/v1?api_key=secret']:
            with self.assertRaises(ValueError):backends.validate_base(value)
    def test_kling_fixture_discovers_only_readonly_tools(self):
        child=self.root/'mcp.py';log=self.root/'calls.jsonl'
        child.write_text('import sys,json\nfrom pathlib import Path\nlog=Path(sys.argv[1])\nfor line in sys.stdin:\n r=json.loads(line)\n with log.open("a") as f:f.write(r["method"]+"\\n")\n if "id" not in r:continue\n v={"tools":[{"name":"who_am_i","inputSchema":{}},{"name":"text_to_image"}]} if r["method"]=="tools/list" else {}\n print(json.dumps({"jsonrpc":"2.0","id":r["id"],"result":v}),flush=True)\n',encoding='utf-8')
        connection=KlingConnection([sys.executable,'-B',str(child),str(log)])
        try:
            value=connection.connect();self.assertTrue(value['authorized']);self.assertFalse(value['generation_enabled'])
        finally:connection.close()
        self.assertEqual(log.read_text().splitlines(),['initialize','notifications/initialized','tools/list','tools/call'])

if __name__=='__main__':
    with (OUT/'image-tests.txt').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Images))
    value={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
           'successful':result.wasSuccessful(),'real_image_api_calls':0,'player_save_used':False}
    (OUT/'image-tests.json').write_text(json.dumps(value,indent=2),encoding='utf-8');print(json.dumps(value))
    sys.exit(0 if result.wasSuccessful() else 1)
