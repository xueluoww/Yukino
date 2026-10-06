"""Explicit, backed-up metadata migration; never runs on opening a save."""
import copy,json
import re
from pathlib import Path
from cast import registry
from affinity import read as affection
from shared_gallery import branch_refs,digest,script_scope,visual_key,background_identity

def update_metadata(session,settings,world):
    result=copy.deepcopy(session)
    for snapshot in [result.get('world_snapshot'),result.get('facts',{}).get('browser_world_snapshot')]:
        if not snapshot or snapshot.get('id')!=world['id']:continue
        for k in ('visual_revision','visual_locations'):snapshot[k]=copy.deepcopy(world[k])
        # Only the relationship policy changes; preserve all frozen world details.
        snapshot['background']=snapshot.get('background','').replace(
            '玩家默认只借用比企谷八幡的外貌，可以自行导入主角卡；原作玩家关系须经明确选择或实际相处建立。',
            '默认主角为比企谷八幡时采用第一季开篇既有关系，不继承后续事件；替换主角不继承八幡关系，剧情仍由玩家决定。')
        for s in snapshot.get('setting_sets',[]):
            if s['id']!=settings['id']:continue
            entries={c['id']:c for c in settings['cards'] if c.get('kind')=='character'}
            for c in s['cards']:
                new=entries.get(c['id'])
                if new:
                    for k in ('age','initial_affinity'):c[k]=copy.deepcopy(new[k])
    for p in [result.get('protagonist_snapshot'),result.get('facts',{}).get('browser_protagonist_snapshot')]:
        if p and p.get('id')=='hachiman':p['age']='16岁（第一季开篇）'
    if (result.get('world_snapshot') or result.get('facts',{}).get('browser_world_snapshot',{})).get('id')==world['id']:
        actors=registry(result,{})
        p=result.get('protagonist_snapshot') or result['facts'].get('browser_protagonist_snapshot',{})
        for k in [k for k,a in actors.items() if a.get('role')=='protagonist' and a['name']==p.get('name')]:actors.pop(k)
        frames=result.get('facts',{}).get('browser_latest_frames',[])
        result['facts']['browser_affinity']=affection(result,actors,frames)
    return result

def migrate(root,tavern,settings,world,descriptors,backup):
    root=Path(root);backup=Path(backup);changed=[]
    paths=list((root/'sessions').glob('*.json'))+list((root/'browser/checkpoints').glob('*/*.json'))
    documents={p:update_metadata(json.loads(p.read_text(encoding='utf-8-sig')),settings,world) for p in paths}
    def static(s):
        d=descriptors.get(s['card_id'],{});visual=s.get('facts',{}).get('browser_visual',{});bg=visual.get('background')
        if bg not in d.get('backgrounds',{}):return None
        identity=background_identity(s,bg,visual.get('background_identity'))
        key='builtin-'+digest([script_scope(s),bg,d['backgrounds'][bg]])
        return key,{'kind':'background','name':d.get('background_descriptions',{}).get(bg,'故事场景'),
            'url':d['backgrounds'][bg],'background':bg,'background_identity':identity,
            'visual_key':visual_key(s,'background',background=bg,identity=identity)}
    cachepath=root/'browser/asset-cache.json';cache=json.loads(cachepath.read_text(encoding='utf-8')) if cachepath.exists() else {}
    # Historical turn IDs are globally unique; opening snapshots remain save-local.
    history={}
    for s in documents.values():
        forkey=static(s)
        if forkey:cache[forkey[0]]=forkey[1]
        refs=branch_refs(s)|({forkey[0]} if forkey else set())
        last=(s.get('turns') or [{}])[-1].get('turn_id')
        if last and last!='opening':history.setdefault(last,set()).update(refs)
    for path,s in documents.items():
        refs=branch_refs(s);current=static(s)
        if current:refs.add(current[0])
        for t in s.get('turns',[]):refs.update(history.get(t.get('turn_id'),set()))
        # An opening node belongs to this save's own checkpoint, not another root.
        opening=documents.get(root/'browser/checkpoints'/s['id']/'opening.json')
        if opening:
            initial=static(opening)
            if initial:refs.add(initial[0])
        s['facts']['browser_gallery_refs']=sorted(refs)
        original=json.loads(path.read_text(encoding='utf-8-sig'))
        if s==original:continue
        target=backup/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():target.write_bytes(path.read_bytes())
        tavern.atomic_json(path,s);changed.append(str(path.relative_to(root)))
    cachebackup=backup/'browser/asset-cache.json';cachebackup.parent.mkdir(parents=True,exist_ok=True)
    if cachepath.exists() and not cachebackup.exists():cachebackup.write_bytes(cachepath.read_bytes())
    tavern.atomic_json(cachepath,cache)
    # Repair existing reservations in place. They keep their occupied slots and
    # images; no unused picture is discarded just to generate another one.
    taskpath=root/'browser/image-tasks.json'
    tasks=json.loads(taskpath.read_text(encoding='utf-8')) if taskpath.exists() else {}
    sessions={s['id']:s for p,s in documents.items() if p.parent==root/'sessions'}
    for index in (root/'browser/prediction-library').glob('*/index.json'):
        pool=json.loads(index.read_text(encoding='utf-8'));entries={}
        for key,e in pool['entries'].items():
            session=sessions.get(e.get('session_id'));newkey=key
            if session and e['status']!='used' and e['kind'] in {'background','portrait'}:
                actors=registry(session,descriptors.get(session['card_id'],{}))
                for a in actors.values():
                    d=descriptors.get(a.get('card_id'),{})
                    a.update({k:d[k] for k in ('reference','default_appearance') if k in d})
                if e['kind']=='portrait' and e.get('actor_id') in actors:
                    a=actors[e['actor_id']];outfit=e.get('appearance','')
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',outfit):
                        outfit='casual' if re.search(r'日常服|日常便服|便服|居家服',outfit) else a.get('default_appearance','school-uniform')
                    e['appearance']=outfit;e['actor']=a
                    newkey=visual_key(session,'portrait',actor=a,appearance=outfit,expression=e.get('expression','neutral'))
                else:
                    e['background_identity']=background_identity(session,e.get('background',''),e.get('background_identity'))
                    newkey=visual_key(session,'background',background=e.get('background',''),identity=e['background_identity'])
                e['key']=newkey;e['visual_key']=newkey;e['world_scope']=script_scope(session)
                if key in tasks:
                    task=tasks.pop(key);task.update({k:e[k] for k in ('key','appearance','actor','background_identity','visual_key','world_scope') if k in e});tasks[newkey]=task
            if newkey in entries:raise ValueError('Prediction identity collision; preserve both and inspect before deployment')
            entries[newkey]=e
        pool['entries']=entries
        saved=backup/index.relative_to(root);saved.parent.mkdir(parents=True,exist_ok=True)
        if not saved.exists():saved.write_bytes(index.read_bytes())
        tavern.atomic_json(index,pool)
    if taskpath.exists():
        saved=backup/'browser/image-tasks.json';saved.parent.mkdir(parents=True,exist_ok=True)
        if not saved.exists():saved.write_bytes(taskpath.read_bytes())
        tavern.atomic_json(taskpath,tasks)
    return changed
