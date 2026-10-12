"""Native Codex images, isolated auth and validated local output."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from codex_image_auth import ImageAuthError, image_home, isolated_env, source_home, external_tokens

def public_image_error(error):
    value=str(error)
    if isinstance(error,ImageAuthError)or isinstance(error,ValueError)and value.startswith(('Codex','参考图片','画面','生图')):
        return value[:300]
    return '画面暂未就绪，故事可继续。'

class ImageService:
    def __init__(self,cli,root,env):
        self.cli=cli;self.root=Path(root);self.source_home=source_home(env)
        self.home=image_home(root);self.output_dir=self.home/'generated_images'
        self.env=isolated_env(root,env);self.auth_mode='';self.borrowed_account=None;self.access_fingerprint=''
        self.proc=None;self.counter=0;self.messages=queue.Queue();self.buffer=[]
        self.lock=threading.RLock();self.write_lock=threading.Lock();self.threads={}
        self.stderr=None;self.last_metrics={};self.reader_thread=None
    def clean_media(self,value):
        if isinstance(value,dict):
            if value.get('type')=='imageGeneration':
                encoded=value.pop('result',None)
                if encoded and not value.get('savedPath') and not value.get('failure') and value.get('status')=='completed':
                    try:
                        if not isinstance(encoded,str) or len(encoded)>45*1024*1024:raise ValueError('large image')
                        data=base64.b64decode(encoded.split(',',1)[-1],validate=True)
                        from image_backends import image_suffix
                        suffix=image_suffix(data);self.output_dir.mkdir(parents=True,exist_ok=True)
                        target=self.output_dir/(hashlib.sha256(data).hexdigest()+suffix)
                        target.write_bytes(data);value['savedPath']=str(target)
                    except (ValueError,OSError):value['decodeFailed']=True
            for child in value.values():self.clean_media(child)
        elif isinstance(value,list):
            for child in value:self.clean_media(child)
    def send(self,value):
        with self.write_lock:
            self.proc.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.proc.stdin.flush()
    def reader(self,process,messages):
        try:
            for line in process.stdout:
                try:message=json.loads(line)
                except ValueError:continue
                # No need to keep a second copy of image bytes in service logs.
                self.clean_media(message)
                messages.put(message)
        finally:messages.put({'_eof':True})
    def next(self,timeout):
        msg=self.messages.get(timeout=timeout)
        if msg.get('_eof'):raise OSError('Image service exited')
        if 'id' in msg and 'method' in msg:
            if msg['method']=='account/chatgptAuthTokens/refresh':
                try:
                    token=external_tokens(self.source_home)
                    previous=msg.get('params',{}).get('previousAccountId')
                    if previous and token['chatgptAccountId']!=previous or self.borrowed_account and token['chatgptAccountId']!=self.borrowed_account:
                        raise ImageAuthError('Codex账号已切换，请重新检测后再生图。')
                    fingerprint=hashlib.sha256(token['accessToken'].encode()).hexdigest()
                    if fingerprint==self.access_fingerprint:raise ImageAuthError('当前访问凭据失效；Yukino不会自行刷新共享凭据。')
                    self.access_fingerprint=fingerprint
                    token.pop('type',None)
                    self.send({'id':msg['id'],'result':token})
                except ImageAuthError:
                    self.send({'id':msg['id'],'error':{'code':-32001,'message':'Access token unavailable. Reauthenticate in Codex or sign in separately for Yukino. Shared refresh tokens are never used.'}})
                return msg
            # Never approve shell, dynamic tool execution or interactive requests.
            self.send({'id':msg['id'],'error':{'code':-32601,'message':'Only native image generation is enabled.'}})
        return msg
    def rpc(self,method,params,timeout=30):
        self.counter+=1;request_id=self.counter
        self.send({'id':request_id,'method':method,'params':params})
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            msg=self.next(max(.1,deadline-time.monotonic()))
            if msg.get('id')==request_id:
                if 'error' in msg:raise ValueError('Codex生图协议未接受'+method+'请求；请更新CLI或重新检测。')
                return msg.get('result',{})
            self.buffer.append(msg)
        raise TimeoutError()
    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:return
            self.close()
            self.messages=queue.Queue();self.buffer=[];self.threads={}
            folder=self.root/'browser/image-service';folder.mkdir(parents=True,exist_ok=True)
            self.home.mkdir(parents=True,exist_ok=True)
            private_auth=(self.home/'auth.json').is_file()
            token=None if private_auth else external_tokens(self.source_home)
            self.auth_mode='yukino_private' if private_auth else 'codex_readonly'
            args=[*(self.cli if isinstance(self.cli,(list,tuple)) else [self.cli]),'app-server','--listen','stdio://',
                  '-c','model_provider="openai"',
                  '-c','cli_auth_credentials_store="'+('file' if private_auth else 'ephemeral')+'"',
                  '-c','model_reasoning_effort="low"','-c','approval_policy="never"',
                  '-c','sandbox_mode="read-only"','-c','project_doc_max_bytes=0']
            args.extend(['--enable','image_generation'])
            for feature in ('shell_tool','apps','browser_use','computer_use','multi_agent','plugins','hooks','skill_search'):
                args.extend(['--disable',feature])
            self.proc=subprocess.Popen(args,cwd=folder,env=self.env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.reader_thread=threading.Thread(target=self.reader,args=(self.proc,self.messages),daemon=True)
            self.reader_thread.start()
            try:
                self.rpc('initialize',{'clientInfo':{'name':'yukima_native_images','title':'雪间画面服务','version':'4.1'},
                    'capabilities':{'experimentalApi':True}})
                self.send({'method':'initialized','params':{}})
                if token:
                    self.borrowed_account=token['chatgptAccountId']
                    self.access_fingerprint=hashlib.sha256(token['accessToken'].encode()).hexdigest()
                    self.rpc('account/login/start',token)
                account=self.rpc('account/read',{'refreshToken':False})
                if not account.get('account') or account['account'].get('type') not in ('chatgpt','chatgptAuthTokens'):
                    raise ImageAuthError('Codex生图需要ChatGPT登录；请为Yukino单独登录。')
            except Exception:
                self.close();raise
    def generate(self,instruction,references,scope,job,timeout=360):
        with self.lock:
            for reference in references:
                if not reference or not Path(reference).is_file():raise ValueError('参考图片缺失；未忽略参考图或提交生图请求。')
            Path(job).mkdir(parents=True,exist_ok=True)
            self.start();started=time.monotonic();pid=self.proc.pid
            # History is scoped to the story branch and visual subject. A CG is
            # never allowed to reuse a speculative-background conversation.
            thread=self.threads.get(scope)
            if not thread:
                result=self.rpc('thread/start',{'cwd':str(self.root/'browser/image-service'),
                    'modelProvider':'openai','approvalPolicy':'never','sandbox':'read-only',
                    'ephemeral':True,'environments':[],'dynamicTools':[],
                    'developerInstructions':'Generate images only with the native image generation tool. Each request requires one new image. Do not invoke shell, browser, apps, agents, MCP tools, or other APIs.',
                    'config':{'model_reasoning_effort':'low'}})
                thread=result['thread']['id'];self.threads[scope]=thread
            inputs=[{'type':'text','text':instruction,'text_elements':[]}]
            inputs.extend({'type':'localImage','path':str(Path(p).resolve())} for p in references if p and Path(p).is_file())
            turn=self.rpc('turn/start',{'threadId':thread,'input':inputs,'effort':'low','environments':[]})['turn']['id']
            pending=self.buffer[:];self.buffer=[];deadline=time.monotonic()+timeout
            paths=[];final=[];generated=False
            Path(job).mkdir(parents=True,exist_ok=True)
            with (Path(job)/'events.jsonl').open('w',encoding='utf-8') as log:
                while time.monotonic()<deadline:
                    try:msg=pending.pop(0) if pending else self.next(max(.01,min(1,deadline-time.monotonic())))
                    except queue.Empty:continue
                    params=msg.get('params',{})
                    if params.get('threadId') not in (None,thread):continue
                    log.write(json.dumps(msg,ensure_ascii=False)+'\n');log.flush()
                    method=msg.get('method','')
                    if method=='item/completed':
                        item=params.get('item',{})
                        if item.get('type')=='imageGeneration':
                            generated=bool(item.get('savedPath')) and not item.get('failure')
                            if generated:paths.append(item['savedPath'])
                        elif item.get('type')=='agentMessage':final.append(item.get('text',''))
                    elif method=='turn/completed' and params.get('turn',{}).get('id')==turn:
                        status=params['turn']['status']
                        self.last_metrics={'service_pid':pid,'thread_id':thread,'turn_id':turn,
                            'seconds':round(time.monotonic()-started,2),'status':status,'native_image_completed':generated}
                        if status!='completed':
                            self.threads.pop(scope,None)
                            error=params['turn'].get('error') or {}
                            code=error.get('codexErrorInfo') or ''
                            if isinstance(code,dict):code=next(iter(code),'')
                            self.last_metrics['error_code']=str(code)[:80]
                            if code in ('unauthorized','unauthorizedError'):raise ImageAuthError('Codex访问授权失效，请重新检测或单独登录；未刷新桌面Codex凭据。')
                            if code in ('usageLimitExceeded','rateLimitExceeded'):raise ValueError('Codex图片额度或速率限制，请稍后再试；已有画面保留。')
                            raise ValueError('Codex未完成本次生图，请检查登录、图片额度或模型支持；已有画面保留。')
                        if not paths:
                            # Older clients only return the generated path in the
                            # final message. Player still checks its allowed root.
                            paths=[s.strip().strip('`"') for s in final if s.strip().lower().endswith(('.png','.webp','.jpg','.jpeg'))]
                        valid=[]
                        for candidate in paths:
                            path=Path(candidate).resolve()
                            if path.is_relative_to(self.output_dir)and path.is_file():
                                from image_backends import image_suffix
                                image_suffix(path.read_bytes());valid.append(str(path))
                        self.last_metrics['native_image_completed']=bool(valid)
                        if not valid:raise ValueError('Codex回合结束但没有实际图片；不能把文本回复或握手当作出图成功。')
                        return valid
            try:self.rpc('turn/interrupt',{'threadId':thread,'turnId':turn},timeout=5)
            except Exception:pass
            self.threads.pop(scope,None)
            self.last_metrics={'status':'timeout','native_image_completed':False,'seconds':round(time.monotonic()-started,2)}
            raise ValueError('画面等待超时，已请求停止；保留已有画面，不自动再次提交。')
    def close(self):
        process=self.proc
        self.proc=None
        if process:
            try:process.stdin.close()
            except (OSError,AttributeError):pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
            if self.reader_thread:self.reader_thread.join(timeout=1)
            if process.stdout:process.stdout.close()
        self.reader_thread=None
        if self.stderr:self.stderr.close();self.stderr=None
