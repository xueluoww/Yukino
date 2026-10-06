"""One persistent Codex app-server; isolated visual threads for each story branch."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

class ImageService:
    def __init__(self,cli,root,env):
        self.cli=cli;self.root=Path(root);self.env=env.copy()
        self.env.pop('DEEPSEEK_API_KEY',None)
        self.proc=None;self.counter=0;self.messages=queue.Queue();self.buffer=[]
        self.lock=threading.RLock();self.write_lock=threading.Lock();self.threads={}
        self.stderr=None;self.last_metrics={}
    def send(self,value):
        with self.write_lock:
            self.proc.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.proc.stdin.flush()
    def reader(self,process,messages):
        try:
            for line in process.stdout:
                try:message=json.loads(line)
                except ValueError:continue
                # No need to keep a second copy of image bytes in service logs.
                item=message.get('params',{}).get('item',{})
                if item.get('type')=='imageGeneration':item.pop('result',None)
                messages.put(message)
        finally:messages.put({'_eof':True})
    def next(self,timeout):
        msg=self.messages.get(timeout=timeout)
        if msg.get('_eof'):raise OSError('Image service exited')
        if 'id' in msg and 'method' in msg:
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
                if 'error' in msg:raise ValueError('生图服务未接受请求。')
                return msg.get('result',{})
            self.buffer.append(msg)
        raise TimeoutError()
    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:return
            self.close()
            self.messages=queue.Queue();self.buffer=[];self.threads={}
            folder=self.root/'browser/image-service';folder.mkdir(parents=True,exist_ok=True)
            args=[self.cli,'app-server','--listen','stdio://',
                  '-c','model_provider="visual_service"',
                  '-c','model_providers.visual_service={name="OpenAI",wire_api="responses",requires_openai_auth=true,supports_websockets=false}',
                  '-c','model_reasoning_effort="low"','-c','approval_policy="never"',
                  '-c','sandbox_mode="read-only"','-c','project_doc_max_bytes=0']
            for feature in ('shell_tool','apps','browser_use','computer_use','multi_agent'):
                args.extend(['--disable',feature])
            self.stderr=(folder/'service.log').open('a',encoding='utf-8')
            self.proc=subprocess.Popen(args,cwd=folder,env=self.env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=self.stderr,text=True,encoding='utf-8',errors='replace',bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            threading.Thread(target=self.reader,args=(self.proc,self.messages),daemon=True).start()
            try:
                self.rpc('initialize',{'clientInfo':{'name':'yukima_native_images','title':'雪间画面服务','version':'4.1'},
                    'capabilities':{'experimentalApi':True}})
                self.send({'method':'initialized','params':{}})
            except Exception:
                self.close();raise
    def generate(self,instruction,references,scope,job,timeout=360):
        with self.lock:
            self.start();started=time.monotonic();pid=self.proc.pid
            # History is scoped to the story branch and visual subject. A CG is
            # never allowed to reuse a speculative-background conversation.
            thread=self.threads.get(scope)
            if not thread:
                result=self.rpc('thread/start',{'cwd':str(self.root/'browser/image-service'),
                    'modelProvider':'visual_service','approvalPolicy':'never','sandbox':'read-only',
                    'ephemeral':True,'environments':[],'dynamicTools':[],
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
                            raise ValueError('画面暂未完成，将保留已有画面。')
                        if not paths:
                            # Older clients only return the generated path in the
                            # final message. Player still checks its allowed root.
                            paths=[s.strip().strip('`"') for s in final if s.strip().lower().endswith(('.png','.webp','.jpg','.jpeg'))]
                        return paths
            try:self.rpc('turn/interrupt',{'threadId':thread,'turnId':turn},timeout=5)
            except Exception:pass
            self.threads.pop(scope,None)
            raise ValueError('画面等待超时，将保留已有画面。')
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
        if self.stderr:self.stderr.close();self.stderr=None
