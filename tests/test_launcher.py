"""Isolated launcher tests. No player library, real key or external API used."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
import urllib.error

OUT = Path(__file__).resolve().parent
PACKAGE = OUT.parent
sys.path.insert(0, str(PACKAGE / 'launcher'))
spec = importlib.util.spec_from_file_location('yukino_setup', PACKAGE / 'launcher/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
from service_control import PackageService, port_free, pick_port


class Engine:
    def __init__(self, root, provider='deepseek', version=setup.RUNTIME_ID, port=0, busy=False):
        owner = self
        self.requests = []
        self.busy = busy
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def send(self, data, status=200):
                body=json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Content-Type','application/json')
                self.end_headers();self.wfile.write(body)
            def do_GET(self):
                owner.requests.append(self.path)
                if self.path=='/health':self.send({'app':'galgame','root':str(root),'provider':provider,'app_version':version})
                elif self.path=='/api/session-token':self.send({'token':'synthetic-token'})
                else:self.send({},404)
            def do_POST(self):
                owner.requests.append(self.path)
                if self.path!='/api/shutdown':return self.send({},404)
                if owner.busy:return self.send({'error':'busy'},400)
                if self.headers.get('X-Session-Token')!='synthetic-token':return self.send({},403)
                self.send({'ok':True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self._serve,daemon=True)
        self.thread.start()
    def _serve(self):
        try:self.server.serve_forever(poll_interval=.02)
        finally:self.server.server_close()
    def close(self):
        if self.thread.is_alive():self.server.shutdown()
        self.thread.join(2)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='launcher-isolated-',dir=OUT)
        self.data=Path(self.tmp.name)/'中文 空格资料库'
        self.data.mkdir()
        self.stack=ExitStack()
        self.stack.enter_context(patch.object(setup,'DATA',self.data))
        self.stack.enter_context(patch.object(setup,'saved_key',return_value=''))
        self.stack.enter_context(patch.object(setup.Handler,'log_message',lambda *a:None))
        self.engines=[]
        self.run=Mock(side_effect=AssertionError('Unexpected engine launch'))
        self.svc=PackageService(PACKAGE/'skills/sillytavern-roleplay',self.data,setup.RUNTIME_ID,self.run)
    def tearDown(self):
        for engine in self.engines:engine.close()
        self.stack.close();self.tmp.cleanup()
    def engine(self, root=None, **kw):
        e=Engine(root or self.data,**kw);self.engines.append(e);return e
    def register(self,e,**override):
        f=self.data/'browser/server.json';f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps({'root':str(self.data),'url':f'http://127.0.0.1:{e.port}',**override}),encoding='utf-8')
    def http(self, fn):
        server=setup.make_server(0,12345)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:return fn(server)
        finally:server.shutdown();thread.join(2);server.server_close()
    def request(self,server,path='/api/key',body=None,method='POST',headers=None,raw=None):
        base=f'http://127.0.0.1:{server.server_port}'
        heads={'Origin':base,'X-Setup-Token':server.setup_token,'Content-Type':'application/json'}
        heads.update(headers or {})
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        conn.request(method,path,body=raw if raw is not None else json.dumps(body or {}),headers=heads)
        response=conn.getresponse();payload=response.read();status=response.status;response_headers=dict(response.getheaders());conn.close()
        return status,json.loads(payload),response_headers

    def test_reuses_registered_alternate_port(self):
        e=self.engine();self.register(e)
        self.assertEqual(self.svc.start(18767),(True,f'http://127.0.0.1:{e.port}'));self.run.assert_not_called()
    def test_stops_alternate_port_and_leaves_foreign_service(self):
        own=self.engine();foreign=self.engine(self.data/'other');self.register(own)
        self.assertTrue(self.svc.stop(foreign.port)[0]);self.assertIn('/api/shutdown',own.requests)
        self.assertTrue(foreign.thread.is_alive());self.assertNotIn('/api/shutdown',foreign.requests)
    def test_stale_registry_foreign_root_not_stopped(self):
        e=self.engine(self.data/'other');self.register(e)
        self.assertTrue(self.svc.stop(e.port)[0]);self.assertNotIn('/api/shutdown',e.requests)
    def test_registry_other_root_ignored(self):
        e=self.engine();self.register(e,root=str(self.data/'other'))
        self.assertIsNone(self.svc.recorded_port())
    def test_registry_remote_url_ignored(self):
        e=self.engine();self.register(e,url='https://evil.example:18767')
        self.assertIsNone(self.svc.recorded_port())
    def test_registry_userinfo_ignored(self):
        e=self.engine();self.register(e,url=f'http://name:password@127.0.0.1:{e.port}')
        self.assertIsNone(self.svc.recorded_port())
    def test_old_runtime_is_not_reused_or_duplicated(self):
        e=self.engine(version='old');self.register(e)
        self.assertFalse(self.svc.start(18767)[0]);self.run.assert_not_called()
    def test_wrong_provider_is_not_reused(self):
        e=self.engine(provider='bridge');self.register(e)
        self.assertFalse(self.svc.start(18767)[0]);self.run.assert_not_called()
    def test_launch_failure_cannot_be_hidden_by_health(self):
        with patch('service_control.port_free',return_value=True):
            self.run.side_effect=None;self.run.return_value=(7,'bad')
            self.assertFalse(self.svc.start(54321)[0])
    def test_start_timeout_reported(self):
        with patch('service_control.port_free',return_value=True):
            self.run.side_effect=subprocess.TimeoutExpired('synthetic',1)
            self.assertFalse(self.svc.start(54321)[0])
    def test_concurrent_launches_start_one_service(self):
        probe=self.engine(self.data/'foreign',port=pick_port(23000))
        launches=[]
        def run(args,**kw):
            port=int(args[args.index('--port')+1]);time.sleep(.1)
            e=self.engine(port=port);self.register(e);launches.append(e);return 0,''
        self.svc.run_python=run
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:self.svc.start(probe.port),range(2)))
        self.assertTrue(all(x[0] for x in result),result);self.assertEqual(result[0],result[1]);self.assertEqual(len(launches),1)
    def test_busy_service_not_force_killed(self):
        e=self.engine(busy=True);self.register(e)
        ok,message=self.svc.stop(e.port);self.assertFalse(ok);self.assertTrue(e.thread.is_alive());self.assertIn('取消',message)
    def test_crash_releases_os_lock(self):
        code="from service_control import PackageService;from pathlib import Path;import os,sys;s=PackageService(Path(sys.argv[1]),Path(sys.argv[2]),'test',None);c=s.operation();c.__enter__();os._exit(0)"
        done=subprocess.run([sys.executable,'-B','-c',code,str(PACKAGE/'skills/sillytavern-roleplay'),str(self.data)],cwd=PACKAGE/'launcher',timeout=5,capture_output=True)
        self.assertEqual(done.returncode,0)
        with self.svc.operation(timeout=.5):pass
    def test_check_mode_does_not_create_missing_library(self):
        absent=self.data/'not-created'
        with patch.object(sys,'argv',['setup.py','--check','--data-dir',str(absent)]),patch('sys.stdout',new_callable=io.StringIO) as stdout:
            self.assertEqual(setup.main(),1)
            self.assertTrue(json.loads(stdout.getvalue())['read_only'])
        self.assertFalse(absent.exists())
    def test_missing_world_in_populated_library_not_reimported(self):
        (self.data/'sessions').mkdir();save=self.data/'sessions/player.json';save.write_text('original')
        with patch.object(setup,'run_python') as run:
            self.assertFalse(setup.ensure_script()[0]);run.assert_not_called()
        self.assertEqual(save.read_text(),'original')
    def test_existing_world_not_upgraded(self):
        (self.data/'worlds').mkdir();f=self.data/'worlds/oregairu-campus.json'
        original=json.dumps({'id':'oregairu-campus','revision':1});f.write_text(original)
        self.assertTrue(setup.ensure_script()[0]);self.assertEqual(f.read_text(),original)
    def test_corrupt_world_not_overwritten(self):
        (self.data/'worlds').mkdir();f=self.data/'worlds/oregairu-campus.json';f.write_text('broken')
        self.assertFalse(setup.ensure_script()[0]);self.assertEqual(f.read_text(),'broken')
    def test_get_status_returns_token_but_never_key(self):
        def run(s):
            with patch.object(setup,'saved_key',return_value='sk-synthetic-secret'):
                status,body,_=self.request(s,'/api/status',method='GET')
            self.assertEqual(status,200);self.assertEqual(body['setup_token'],s.setup_token)
            self.assertNotIn('sk-synthetic-secret',json.dumps(body))
        self.http(run)
    def test_bad_host_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,'/api/status',method='GET',headers={'Host':'evil.example'})[0],403))
    def test_cross_site_status_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,'/api/status',method='GET',headers={'Sec-Fetch-Site':'cross-site'})[0],403))
    def test_missing_token_cannot_write_key(self):
        with patch.object(setup,'save_key') as store:
            self.http(lambda s:self.assertEqual(self.request(s,headers={'X-Setup-Token':''})[0],403));store.assert_not_called()
    def test_foreign_origin_cannot_launch(self):
        with patch.object(setup,'start_engine') as start:
            self.http(lambda s:self.assertEqual(self.request(s,'/api/launch',headers={'Origin':'https://evil.example'})[0],403));start.assert_not_called()
    def test_array_json_is_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,raw='[]')[0],400))
    def test_bad_json_is_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,raw='{broken')[0],400))
    def test_non_json_is_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,headers={'Content-Type':'text/plain'})[0],400))
    def test_bad_content_length_is_rejected(self):
        self.http(lambda s:self.assertEqual(self.request(s,headers={'Content-Length':'bad'})[0],400))
    def test_unknown_page_completes_404(self):
        self.http(lambda s:self.assertEqual(self.request(s,'/missing',method='GET')[0],404))
    def test_no_key_cannot_launch(self):
        with patch.object(setup,'start_engine') as start:
            self.http(lambda s:self.assertEqual(self.request(s,'/api/launch')[0],400));start.assert_not_called()
    def test_invalid_new_key_never_overwrites_old(self):
        with patch.object(setup,'verify_key',return_value=(False,'rejected')),patch.object(setup,'save_key') as store:
            def run(s):
                status,body,_=self.request(s,body={'key':'sk-synthetic-new'})
                self.assertEqual(status,400);self.assertFalse(body['saved'])
            self.http(run);store.assert_not_called()
    def test_valid_key_saved_only_after_verification(self):
        order=[]
        with patch.object(setup,'verify_key',side_effect=lambda k:(order.append('verify') or (True,'deepseek-flash'))),patch.object(setup,'save_key',side_effect=lambda k:(order.append('save') or (True,'saved'))):
            self.http(lambda s:self.assertTrue(self.request(s,body={'key':'sk-synthetic-new'})[1]['saved']))
        self.assertEqual(order,['verify','save'])
    def test_key_control_chars_rejected_without_network(self):
        with patch.object(setup,'verify_key') as verify:
            self.http(lambda s:self.assertEqual(self.request(s,body={'key':'sk-line\nsecret'})[0],400));verify.assert_not_called()
    def test_model_mismatch_fails_verification(self):
        with patch.object(setup.urllib.request,'urlopen',return_value=io.BytesIO(b'{"data":[{"id":"other"}]}')):
            self.assertFalse(setup.verify_key('sk-synthetic')[0])
    def test_upstream_error_body_not_echoed(self):
        err=urllib.error.HTTPError('https://api.deepseek.com/models',401,'invalid',{},io.BytesIO(b'sk-synthetic-secret'))
        with patch.object(setup.urllib.request,'urlopen',side_effect=err):
            ok,detail=setup.verify_key('sk-synthetic-secret');self.assertFalse(ok);self.assertNotIn('sk-synthetic-secret',detail)


if __name__=='__main__':
    with (OUT/'launcher-tests.txt').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LauncherTests))
    record={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful(),
            'real_api_calls':0,'player_library_used':False}
    (OUT/'launcher-tests.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record));sys.exit(0 if result.wasSuccessful() else 1)
