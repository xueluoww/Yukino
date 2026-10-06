"""Save metadata, recoverable deletion and portable one-branch bundles."""
import base64
import copy
import io
import json
from pathlib import Path
import re
import shutil
import uuid
import zipfile
from gameplay import ModuleStore,key
from long_memory import MemoryStore

LIMIT=32*1024*1024

class SaveManager:
    def __init__(self,root,tavern):self.root=Path(root).resolve();self.tavern=tavern
    def session(self,sid):
        return self.tavern.find_record(self.root,'sessions',key(sid))[1]
    def edit(self,sid,title,note):
        if not isinstance(title,str) or not title.strip() or len(title)>200 or not isinstance(note,str) or len(note)>3000:
            raise ValueError('存档名称或备注格式不正确。')
        with self.tavern.write_lock(self.root):
            session=self.session(sid);session['title']=title.strip();session['save_note']=note
            session['updated_at']=self.tavern.now();session['revision']+=1
            self.tavern.atomic_json(self.root/'sessions'/(sid+'.json'),session)
        return session
    def recycle_list(self):
        result=[]
        for path in (self.root/'recycle-bin').glob('*/manifest.json'):
            record=json.loads(path.read_text(encoding='utf-8'))
            result.append({k:record[k] for k in ('id','deleted_at','saves')})
        return sorted(result,key=lambda r:r['deleted_at'],reverse=True)
    def delete(self,sid,subtree=False):
        key(sid)
        with self.tavern.write_lock(self.root):
            sessions={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in (self.root/'sessions').glob('*.json')}
            if sid not in sessions:raise ValueError('存档不存在。')
            selected={sid}
            if subtree:
                changed=True
                while changed:
                    changed=False
                    for iid,s in sessions.items():
                        parent=(s.get('branch') or {}).get('parent_id')
                        if parent in selected and iid not in selected:selected.add(iid);changed=True
            token=uuid.uuid4().hex[:16];folder=self.root/'recycle-bin'/token;folder.mkdir(parents=True)
            mappings=[]
            for iid in selected:
                for relative in (Path('sessions')/(iid+'.json'),Path('browser/checkpoints')/iid,Path('memory')/iid):
                    source=(self.root/relative).resolve()
                    if not source.is_relative_to(self.root):raise ValueError('存档路径越界。')
                    if source.exists():mappings.append(str(relative).replace('\\','/'))
            record={'id':token,'deleted_at':self.tavern.now(),'saves':[{'id':iid,'title':sessions[iid]['title'],'branch':sessions[iid].get('branch',{})} for iid in sorted(selected)],'paths':mappings}
            self.tavern.atomic_json(folder/'manifest.json',record)
            moved=[]
            try:
                for relative in mappings:
                    dest=folder/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.move(str(self.root/relative),str(dest));moved.append(relative)
            except OSError:
                for relative in reversed(moved):shutil.move(str(folder/relative),str(self.root/relative))
                raise
            # Parent metadata remains a tombstone; descendants keep their real parent IDs.
            for iid in selected:
                self.tavern.atomic_json(self.root/'save-tombstones'/(iid+'.json'),record['saves'][sorted(selected).index(iid)])
            return record
    def restore(self,token):
        key(token);folder=self.root/'recycle-bin'/token
        with self.tavern.write_lock(self.root):
            record=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            for relative in record['paths']:
                source=(folder/relative).resolve();target=(self.root/relative).resolve()
                if not source.is_relative_to(folder.resolve()) or not target.is_relative_to(self.root) or target.exists():raise ValueError('恢复路径冲突。')
            restored=[]
            try:
                for relative in record['paths']:
                    target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.move(str(folder/relative),str(target));restored.append(relative)
            except OSError:
                for relative in reversed(restored):shutil.move(str(self.root/relative),str(folder/relative))
                raise
            for save in record['saves']:
                tombstone=self.root/'save-tombstones'/(save['id']+'.json')
                if tombstone.exists():tombstone.unlink()
            (folder/'manifest.json').unlink()
        return {'restored':record['saves']}
    def export(self,sid):
        session=self.session(sid);out=io.BytesIO();store=ModuleStore(self.root,self.tavern)
        world=session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})
        snapshots=[]
        for path in (self.root/'browser/checkpoints'/sid).glob('*.json'):
            snapshots.append(json.loads(path.read_text(encoding='utf-8')))
        refs={}
        for snap in [session,*snapshots]:
            snapworld=snap.get('world_snapshot') or snap.get('facts',{}).get('browser_world_snapshot',{})
            for ref in snapworld.get('world_gameplay',[]):refs[ref['sha256']]=ref
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('manifest.json',json.dumps({'spec':'yukima_save_v1','session_id':sid,'includes':'one branch, checkpoints, memory, frozen module code; no credentials or generated media'},ensure_ascii=False))
            bundle.writestr('session.json',json.dumps(session,ensure_ascii=False))
            for ref in refs.values():
                bundle.writestr('modules/'+ref['sha256']+'.json',json.dumps(store.load(ref),ensure_ascii=False))
            for kind,folder in [('checkpoints',self.root/'browser/checkpoints'/sid),('memory',self.root/'memory'/sid)]:
                for path in folder.glob('*.json'):
                    bundle.writestr(kind+'/'+path.name,path.read_bytes())
        return out.getvalue()
    def import_bundle(self,raw):
        if len(raw)>LIMIT:raise ValueError('存档包最多 32 MiB。')
        files={}
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            if len(bundle.infolist())>2000 or sum(i.file_size for i in bundle.infolist())>LIMIT:raise ValueError('存档解压数据过大。')
            for info in bundle.infolist():
                name=info.filename
                if name in files or not re.fullmatch(r'(manifest|session)\.json|(?:modules|checkpoints|memory)/[A-Za-z0-9_-]+\.json',name):raise ValueError('存档包含不允许的路径。')
                files[name]=json.loads(bundle.read(info).decode('utf-8-sig'))
        if files.get('manifest.json',{}).get('spec')!='yukima_save_v1':raise ValueError('存档包类型不正确。')
        session=files.get('session.json');original=session.get('id') if isinstance(session,dict) else None
        key(original)
        if not isinstance(session.get('turns'),list) or not session['turns'] or not isinstance(session.get('facts'),dict) or not isinstance(session.get('card_snapshot'),dict):raise ValueError('存档结构不完整。')
        if len({t['turn_id'] for t in session['turns']})!=len(session['turns']):raise ValueError('存档回合 ID 重复。')
        for turn in session['turns']:
            key(turn['turn_id'])
            if any(not isinstance(turn.get(f),str) for f in ('user','assistant')):raise ValueError('存档回合格式不正确。')
        new_id=uuid.uuid4().hex[:16];session=copy.deepcopy(session);session['id']=session['memory_scope']=new_id
        session['revision']=0;session['title']=str(session.get('title','导入故事'))[:180]+' · 导入'
        session['updated_at']=self.tavern.now();session['status']='paused';session['imported_from']=original
        session['branch']={'root_id':new_id,'parent_id':'','node_id':'','label':'主线','kind':'root'}
        session['facts'].pop('browser_branch',None)
        world=session.get('world_snapshot') or session['facts'].get('browser_world_snapshot',{})
        store=ModuleStore(self.root,self.tavern)
        validated={}
        def validate_world(snapworld):
            refs=snapworld.get('world_gameplay',[]);modules=[]
            for ref in refs:
                store.path(ref) # Validate the destination reference before any writes.
                module=files.get('modules/'+ref['sha256']+'.json')
                if not module:raise ValueError('缺少存档对应玩法代码。')
                modules.append(module)
            clean=store.prepare(modules)
            if any(m['sha256']!=r['sha256'] or m['id']!=r['id'] or m['version']!=r['version'] for m,r in zip(clean,refs)):raise ValueError('玩法版本不一致。')
            for ref,module in zip(refs,clean):validated[ref['sha256']]=(ref,module)
        validate_world(world)
        checkpoints={};memories={}
        ids={t['turn_id'] for t in session['turns']}
        for name,record in files.items():
            if name.startswith('checkpoints/'):
                tid=Path(name).stem
                if tid not in ids or record.get('id')!=original:raise ValueError('回溯快照不属于存档。')
                count=len(record.get('turns',[]))
                if record.get('turns')!=session['turns'][:count] or not count or record['turns'][-1]['turn_id']!=tid:raise ValueError('回溯快照包含不同剧情。')
                record['id']=record['memory_scope']=new_id;record['branch']=copy.deepcopy(session['branch']);record['facts'].pop('browser_branch',None)
                # Frozen modules on earlier snapshots must be shipped too.
                snapworld=record.get('world_snapshot') or record['facts'].get('browser_world_snapshot',{})
                validate_world(snapworld)
                checkpoints[tid]=record
            elif name.startswith('memory/'):
                if record.get('scope')!=original:raise ValueError('记忆不属于存档。')
                record['scope']=new_id;memories[Path(name).stem]=record
        with self.tavern.write_lock(self.root):
            for ref,module in validated.values():
                target=store.path(ref)
                if not target.exists():self.tavern.atomic_json(target,module)
            # Register only the frozen main card if absent, so existing restore paths work.
            target=self.root/'cards'/(key(session['card_id'])+'.json')
            if not target.exists():
                from gameplay import digest
                self.tavern.atomic_json(target,{'id':session['card_id'],'digest':digest(session['card_snapshot']),
                    'imported_at':self.tavern.now(),'source':'save-bundle','aliases':[],'card':session['card_snapshot']})
            for tid,record in checkpoints.items():self.tavern.atomic_json(self.root/'browser/checkpoints'/new_id/(tid+'.json'),record)
            for iid,record in memories.items():self.tavern.atomic_json(self.root/'memory'/new_id/(key(iid)+'.json'),record)
            self.tavern.atomic_json(self.root/'sessions'/(new_id+'.json'),session)
        return {'session_id':new_id,'title':session['title']}
