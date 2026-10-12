"""Native Codex protocol/auth regression. No real account or inference calls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

PACKAGE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PACKAGE/'skills/sillytavern-roleplay/scripts'),str(PACKAGE/'launcher')]
from codex_image_auth import ImageAuthError,external_tokens,image_home,isolated_env
from image_service import ImageService,public_image_error
from image_setup import ImageSetup
from test_image_backends import PNG

FAKE=r'''
import base64,json,os,sys
from pathlib import Path
home=Path(os.environ['CODEX_HOME']); folder=home/'generated_images';folder.mkdir(parents=True,exist_ok=True)
mode=os.environ.get('YUKINO_TEST_FAKE_MODE','success')
log=Path(os.environ['YUKINO_TEST_RPC_LOG'])
def send(value):print(json.dumps(value),flush=True)
def note(value):
 with log.open('a',encoding='utf-8')as out:out.write(json.dumps(value)+'\n')
note({'argv':sys.argv[1:],'home':str(home),'has_openai_key':bool(os.environ.get('OPENAI_API_KEY'))})
for line in sys.stdin:
 request=json.loads(line);method=request.get('method','');rid=request.get('id');params=request.get('params',{})
 if 'error'in request:
  note({'rejected_request':rid,'code':request['error']['code']});continue
 if not method:continue
 note({'method':method,'provider':params.get('modelProvider'),'type':params.get('type'),'references':sum(x.get('type')=='localImage'for x in params.get('input',[]))})
 if rid is None:continue
 result={}
 if method=='account/read':result={'account':{'type':'chatgpt'}}
 if method=='thread/start':result={'thread':{'id':'thread-synthetic'}}
 if method=='turn/start':result={'turn':{'id':'turn-synthetic'}}
 send({'id':rid,'result':result})
 if method!='turn/start':continue
 if mode=='shell':send({'id':999,'method':'item/commandExecution/requestApproval','params':{'threadId':'thread-synthetic'}})
 if mode=='refresh':send({'id':999,'method':'account/chatgptAuthTokens/refresh','params':{'previousAccountId':'test-account'}})
 if mode=='switched':send({'id':999,'method':'account/chatgptAuthTokens/refresh','params':{'previousAccountId':'different-account'}})
 if mode in ('success','shell','refresh','switched','outside','base64'):
  target=Path(os.environ['YUKINO_TEST_OUTSIDE'])if mode=='outside'else folder/'synthetic.png'
  target.write_bytes(base64.b64decode(os.environ['YUKINO_TEST_PNG']))
  item={'type':'imageGeneration','id':'image-synthetic','status':'completed','result':os.environ['YUKINO_TEST_PNG'],'savedPath':None if mode=='base64'else str(target)}
  send({'method':'item/completed','params':{'threadId':'thread-synthetic','item':item}})
 status='failed'if mode=='limit'else'completed'
 send({'method':'turn/completed','params':{'threadId':'thread-synthetic','turn':{'id':'turn-synthetic','status':status,'error':{'codexErrorInfo':'usageLimitExceeded'}if mode=='limit'else None}}})
'''

class NativeImages(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='yukino-native-test-')
        self.root=Path(self.temp.name);self.source=self.root/'desktop-auth';self.source.mkdir()
        payload={'exp':int(time.time())+7200,'https://api.openai.com/auth':{'chatgpt_plan_type':'test'}}
        token='synthetic.'+base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')+'.signature'
        self.auth={'auth_mode':'chatgpt','tokens':{'access_token':token,'account_id':'test-account','refresh_token':'synthetic-refresh-never-use'}}
        self.write_auth(self.auth)
        self.original=(self.source/'auth.json').read_bytes()
        self.data=self.root/'data';self.rpc_log=self.root/'rpc.jsonl';self.server=self.root/'server.py';self.server.write_text(FAKE,encoding='utf-8')
        self.env={**os.environ,'CODEX_HOME':str(self.source),'OPENAI_API_KEY':'synthetic-openai-key','DEEPSEEK_API_KEY':'synthetic-text-key',
            'YUKINO_TEST_RPC_LOG':str(self.rpc_log),'YUKINO_TEST_PNG':base64.b64encode(PNG).decode(),'YUKINO_TEST_OUTSIDE':str(self.root/'outside.png')}
        self.services=[]
    def write_auth(self,auth):(self.source/'auth.json').write_text(json.dumps(auth),encoding='utf-8')
    def service(self,mode='success'):
        service=ImageService([sys.executable,'-B',str(self.server)],self.data,{**self.env,'YUKINO_TEST_FAKE_MODE':mode})
        self.services.append(service);return service
    def run_image(self,service,refs=None):return service.generate('Synthetic scene only',refs or [],'test-branch',self.data/'browser/image-jobs/test',timeout=5)
    def records(self):return [json.loads(x)for x in self.rpc_log.read_text(encoding='utf-8').splitlines()]
    def tearDown(self):
        for service in self.services:service.close()
        self.temp.cleanup()
    def test_readonly_access_never_returns_shared_refresh_token(self):
        token=external_tokens(self.source)
        self.assertNotIn('refresh',json.dumps(token));self.assertEqual((self.source/'auth.json').read_bytes(),self.original)
    def test_expired_access_is_refused_without_refresh_or_write(self):
        self.auth['tokens']['access_token']='synthetic.'+base64.urlsafe_b64encode(json.dumps({'exp':1}).encode()).decode().rstrip('=')+'.signature'
        self.write_auth(self.auth);before=(self.source/'auth.json').read_bytes()
        with self.assertRaises(ImageAuthError):external_tokens(self.source)
        self.assertEqual((self.source/'auth.json').read_bytes(),before)
    def test_api_key_login_cannot_be_misreported_as_chatgpt(self):
        self.auth['auth_mode']='apikey';self.write_auth(self.auth)
        with self.assertRaises(ImageAuthError):external_tokens(self.source)
    def test_native_provider_and_auth_home_are_isolated(self):
        service=self.service();paths=self.run_image(service);service.close()
        records=self.records();args=records[0]['argv']
        self.assertIn('model_provider="openai"',args);self.assertNotIn('visual_service',' '.join(args))
        self.assertIn('image_generation',args);self.assertFalse(records[0]['has_openai_key'])
        self.assertTrue(any(x.get('type')=='chatgptAuthTokens'for x in records))
        self.assertTrue(Path(paths[0]).is_relative_to(image_home(self.data)))
        self.assertFalse((image_home(self.data)/'auth.json').exists());self.assertEqual((self.source/'auth.json').read_bytes(),self.original)
    def test_reference_is_forwarded_and_missing_reference_is_not_dropped(self):
        ref=self.root/'reference.png';ref.write_bytes(PNG);service=self.service();self.run_image(service,[str(ref)])
        self.assertEqual(next(x for x in self.records()if x.get('method')=='turn/start')['references'],1)
        with self.assertRaisesRegex(ValueError,'参考图片缺失'):self.run_image(service,[str(self.root/'missing.png')])
    def test_base64_only_image_is_saved_and_not_logged(self):
        service=self.service('base64');path=Path(self.run_image(service)[0]);self.assertEqual(path.read_bytes(),PNG)
        self.assertNotIn(base64.b64encode(PNG).decode(),(self.data/'browser/image-jobs/test/events.jsonl').read_text())
    def test_completed_text_without_image_is_failure(self):
        with self.assertRaisesRegex(ValueError,'没有实际图片'):self.run_image(self.service('no-image'))
    def test_outside_path_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'没有实际图片'):self.run_image(self.service('outside'))
    def test_quota_error_has_specific_feedback(self):
        with self.assertRaisesRegex(ValueError,'额度'):self.run_image(self.service('limit'))
    def test_shell_approval_is_rejected(self):
        service=self.service('shell');self.run_image(service);service.close()
        self.assertTrue(any(x.get('code')==-32601 for x in self.records()))
    def test_unauthorized_does_not_refresh_shared_token(self):
        service=self.service('refresh');self.run_image(service);service.close()
        self.assertTrue(any(x.get('code')==-32001 for x in self.records()))
        self.assertEqual((self.source/'auth.json').read_bytes(),self.original)
    def test_switched_account_is_not_injected_mid_turn(self):
        service=self.service('switched');self.run_image(service);service.close()
        self.assertTrue(any(x.get('code')==-32001 for x in self.records()))
    def test_private_login_uses_only_its_own_file(self):
        home=image_home(self.data);home.mkdir(parents=True);(home/'auth.json').write_text(json.dumps(self.auth))
        service=self.service();self.run_image(service);service.close()
        self.assertEqual(service.auth_mode,'yukino_private')
        self.assertFalse(any(x.get('method')=='account/login/start'for x in self.records()))
        self.assertIn('cli_auth_credentials_store="file"',self.records()[0]['argv'])
    def test_login_ui_launches_with_private_home(self):
        setup=ImageSetup(PACKAGE/'skills/sillytavern-roleplay',self.data,PACKAGE)
        with patch.object(setup.backends,'resolve_codex',return_value=['codex-test']),patch('image_setup.subprocess.Popen')as launch:
            setup.login_codex()
        self.assertEqual(Path(launch.call_args.kwargs['env']['CODEX_HOME']),image_home(self.data))
        self.assertNotIn('OPENAI_API_KEY',launch.call_args.kwargs['env'])
        self.assertEqual((self.source/'auth.json').read_bytes(),self.original)
    def test_detection_never_uses_global_login_command_or_inference(self):
        setup=ImageSetup(PACKAGE/'skills/sillytavern-roleplay',self.data,PACKAGE)
        fake=Mock(auth_mode='codex_readonly')
        with patch.object(setup.backends,'resolve_codex',return_value=['codex-test']),patch('image_setup.hidden_run',return_value=Mock(stdout='test-version'))as run,patch('image_service.ImageService',return_value=fake):
            value=setup.codex_check()
        self.assertTrue(value['logged_in']);self.assertFalse(value['generation_verified'])
        self.assertEqual(run.call_args.args[0],['codex-test','--version']);fake.generate.assert_not_called()
    def test_login_and_quota_feedback_is_kept_without_echoing_unknown_secrets(self):
        self.assertIn('登录',public_image_error(ImageAuthError('请为Yukino单独登录。')))
        self.assertIn('额度',public_image_error(ValueError('Codex图片额度不足。')))
        self.assertNotIn('synthetic-secret',public_image_error(OSError('synthetic-secret')))
    def test_trial_confirmation_requires_an_actual_image(self):
        setup=ImageSetup(PACKAGE/'skills/sillytavern-roleplay',self.data,PACKAGE)
        output=image_home(self.data)/'generated_images';output.mkdir(parents=True);image=output/'trial.png';image.write_bytes(PNG)
        fake=Mock(output_dir=output,auth_mode='codex_readonly');fake.generate.return_value=[str(image)]
        with patch.object(setup.backends,'resolve_codex',return_value=['codex-test']),patch('image_service.ImageService',return_value=fake):
            setup.test_codex_image()
        self.assertTrue(setup.last_codex_check['generation_verified']);fake.generate.assert_called_once()
        self.assertEqual((self.source/'auth.json').read_bytes(),self.original)
    def test_failed_trial_clears_previous_generation_confirmation(self):
        setup=ImageSetup(PACKAGE/'skills/sillytavern-roleplay',self.data,PACKAGE);setup.last_codex_check={'generation_verified':True}
        fake=Mock(output_dir=image_home(self.data)/'generated_images',auth_mode='codex_readonly');fake.generate.return_value=[]
        with patch.object(setup.backends,'resolve_codex',return_value=['codex-test']),patch('image_service.ImageService',return_value=fake):
            with self.assertRaises(ValueError):setup.test_codex_image()
        self.assertFalse(setup.last_codex_check['generation_verified'])

if __name__=='__main__':unittest.main()
