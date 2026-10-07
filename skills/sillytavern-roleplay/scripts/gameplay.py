"""Generic script-owned executable modules and immutable version storage."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from gameplay_worker import check

API = 1
CAPABILITIES = {'time','items','relations','threads'}

def key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):
        raise ValueError('玩法 ID 格式不正确。')
    return value

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def validate_actions(actions):
    if not isinstance(actions,list) or len(actions)>30:raise ValueError('玩法动作列表不正确或过大。')
    seen=set()
    for action in actions:
        if not isinstance(action,dict):raise ValueError('玩法动作必须是对象。')
        aid=key(action.get('id'))
        if aid in seen or not all(isinstance(action.get(k),str) and 0<len(action[k])<=300 for k in ('label','text')):raise ValueError('玩法动作格式不正确。')
        if not action['text'].startswith(('【语言】','【动作】','【环境】')):raise ValueError('玩法动作必须使用玩家输入前缀。')
        seen.add(aid)

def validate_view(view):
    if not isinstance(view,dict) or not isinstance(view.get('cards',[]),list) or len(view.get('cards',[]))>100:raise ValueError('玩法界面格式不正确。')
    validate_actions(view.get('actions',[]))
    for card in view.get('cards',[]):
        if not isinstance(card,dict) or any(not isinstance(card.get(f,''),str) or len(card.get(f,''))>3000 for f in ('title','text','status')):raise ValueError('玩法卡片字段格式不正确。')
        details=card.get('details',[])
        if not isinstance(details,list) or len(details)>30 or any(not isinstance(v,str) or len(v)>3000 for v in details):raise ValueError('玩法卡片记录格式不正确。')

def read_package(path):
    """Folder manifests resolve only paths inside the package; JSON may embed code."""
    path=Path(path).resolve()
    if path.is_dir():path=path/'manifest.json'
    if path.stat().st_size>8*1024*1024:raise ValueError('剧本包过大。')
    raw=json.loads(path.read_text(encoding='utf-8-sig'))
    def load(relative,as_text=False):
        target=(path.parent/relative).resolve()
        if not target.is_relative_to(path.parent) or not target.is_file() or target.stat().st_size>8*1024*1024:
            raise ValueError('剧本引用越界、缺失或过大：'+str(relative))
        value=target.read_text(encoding='utf-8-sig')
        return value if as_text else json.loads(value)
    if isinstance(raw.get('world'),str):raw['world']=load(raw['world'])
    raw['setting_sets']=[load(x) if isinstance(x,str) else x for x in raw.get('setting_sets',[])]
    if isinstance(raw.get('world'),dict):
        raw['world']['storylines']=[load(x) if isinstance(x,str) else x for x in raw['world'].get('storylines',[])]
    modules=[]
    for entry in raw.get('world_gameplay',[]):
        module=load(entry) if isinstance(entry,str) else copy.deepcopy(entry)
        # entry paths are relative to the root manifest, including code paths.
        if 'code_file' in module:module['source']=load(module.pop('code_file'),True)
        modules.append(module)
    if modules:raw['world_gameplay']=modules
    return raw

class ModuleStore:
    def __init__(self,root,tavern):self.root=Path(root);self.tavern=tavern
    def prepare(self,modules):
        if not isinstance(modules,list) or len(modules)>12:raise ValueError('每个剧本最多 12 个玩法模块。')
        result=[];seen=set()
        for raw in modules:
            if not isinstance(raw,dict):raise ValueError('玩法描述必须是对象。')
            module=copy.deepcopy(raw);module['id']=key(module.get('id'))
            if module['id'] in seen:raise ValueError('玩法 ID 重复。')
            seen.add(module['id'])
            if module.get('api_version')!=API or module.get('runtime')!='python-restricted-v1':
                raise ValueError('不兼容的玩法 API 或运行时。')
            if not isinstance(module.get('version'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',module['version']):raise ValueError('玩法版本格式不正确。')
            if not isinstance(module.get('name'),str) or not 1<=len(module['name'])<=100:raise ValueError('玩法需要名称。')
            caps=module.get('capabilities',[])
            if not isinstance(caps,list) or not set(caps)<=CAPABILITIES:raise ValueError('不支持的玩法能力。')
            if not isinstance(module.get('config',{}),dict) or len(json.dumps(module.get('config',{})))>32768:raise ValueError('玩法配置不正确或过大。')
            check(module.get('source'))
            dependencies=module.get('dependencies',{})
            if not isinstance(dependencies,dict):raise ValueError('玩法依赖需要 ID/version 字典。')
            module['sha256']=digest({k:v for k,v in module.items() if k!='sha256'})
            result.append(module)
        by_id={m['id']:m for m in result}
        def visit(mid,path):
            if mid in path:raise ValueError('玩法依赖出现循环。')
            for dep,version in by_id[mid].get('dependencies',{}).items():
                if dep not in by_id or by_id[dep]['version']!=version:raise ValueError('玩法依赖缺失或版本不匹配：'+dep)
                visit(dep,path+[mid])
        for mid in by_id:visit(mid,[])
        # Topological execution order, independent of manifest order.
        ordered=[]
        def add(mid):
            if any(m['id']==mid for m in ordered):return
            for dep in by_id[mid].get('dependencies',{}):add(dep)
            ordered.append(by_id[mid])
        for mid in by_id:add(mid)
        return ordered
    def install(self,script_id,modules):
        refs=[]
        for module in self.prepare(modules):
            ref={'id':module['id'],'name':module['name'],'version':module['version'],'sha256':module['sha256'],'script_id':key(script_id)}
            target=self.path(ref)
            if target.exists() and json.loads(target.read_text(encoding='utf-8'))!=module:raise ValueError('玩法版本校验失败。')
            if not target.exists():self.tavern.atomic_json(target,module)
            refs.append(ref)
        return refs
    def path(self,ref):
        sha=ref.get('sha256','')
        if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('玩法哈希不正确。')
        return self.root/'gameplay-modules'/key(ref['script_id'])/key(ref['id'])/sha/'module.json'
    def load(self,ref):
        module=json.loads(self.path(ref).read_text(encoding='utf-8'))
        if module.get('id')!=ref['id'] or module.get('version')!=ref['version'] or digest({k:v for k,v in module.items() if k!='sha256'})!=ref['sha256']:raise ValueError('玩法文件被修改，不能继续结算。')
        return module
    def call(self,ref,mode,state,context,event=None):
        module=self.load(ref)
        context=copy.deepcopy(context)
        context['modules']={k:v for k,v in context.get('modules',{}).items() if k in module.get('dependencies',{})}
        request={'mode':mode,'state':copy.deepcopy(state),'config':module.get('config',{}),
                 'context':copy.deepcopy(context),'event':event or {}}
        payload=json.dumps({'source':module['source'],'request':request},ensure_ascii=False,allow_nan=False).encode('utf-8')
        if len(payload)>512*1024:raise ValueError('玩法输入过大。')
        # No provider credentials, host Python path or home configuration in the worker.
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'}}
        try:
            process=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('gameplay_worker.py'))],
                input=payload,capture_output=True,timeout=3,env=env,cwd=Path(__file__).parent,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except subprocess.TimeoutExpired as exc:raise ValueError('玩法计算超时，本轮未结算。') from exc
        if process.returncode:raise ValueError('玩法无法结算：'+process.stderr.decode('utf-8',errors='replace')[:500])
        if len(process.stdout)>128*1024:raise ValueError('玩法输出过大。')
        result=json.loads(process.stdout)
        if not isinstance(result,dict) or not isinstance(result.get('state'),dict) or not isinstance(result.get('effects',[]),list):raise ValueError('玩法返回格式错误。')
        if mode in {'view','context'} and (result['state']!=state or result.get('effects')):raise ValueError('查看玩法不能修改存档。')
        if mode=='view':validate_view(result.get('view',{}))
        if mode=='context' and isinstance(result.get('context'),dict):validate_actions(result['context'].get('natural_actions',[]))
        for effect in result.get('effects',[]):
            if not isinstance(effect,dict) or effect.get('type') not in module.get('capabilities',[]):raise ValueError('玩法调用了未声明的能力。')
        return result
