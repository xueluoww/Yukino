"""Story backgrounds and typed setting-card collections; snapshots are session-local."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from gameplay import ModuleStore, read_package

KINDS={'character','location','item','rule','event'}
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value):
        raise ValueError('设定 ID 只能包含英文、数字、横线和下划线。')
    return value

def text(value,limit=60000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('设定文本类型或长度不正确。')
    return value

def read(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('设定文件过大。')
    return json.loads(path.read_text(encoding='utf-8-sig'))

class WorldLibrary:
    def __init__(self,root,tavern):self.root=Path(root);self.tavern=tavern
    def load(self,kind,key):
        return read(self.root/kind/(identifier(key)+'.json'))
    def list(self):
        worlds=[read(p) for p in sorted((self.root/'worlds').glob('*.json'))]
        sets=[read(p) for p in sorted((self.root/'setting-sets').glob('*.json'))]
        bindings=read(self.root/'world-bindings.json') if (self.root/'world-bindings.json').exists() else {}
        return {'worlds':[{'id':w['id'],'name':w['name'],'background':w['background'],
                'setting_set_ids':w.get('setting_set_ids',[]),'primary_card_id':w.get('primary_card_id',''),
                'opening_scenes':w.get('opening_scenes',[]),'description':w.get('description',''),
                'default_protagonist_id':w.get('default_protagonist_id','hachiman')} for w in worlds],
                'setting_sets':[{'id':s['id'],'name':s['name'],'description':s.get('description',''),
                    'card_count':len(s['cards'])} for s in sets],'bindings':bindings}
    def import_set(self,raw,key=None):
        key=identifier(key or raw.get('id',''))
        name=text(raw.get('name',''),200)
        if not name.strip() or not isinstance(raw.get('cards'),list) or len(raw['cards'])>200:
            raise ValueError('设定集需要名称和最多 200 张卡片。')
        cards=[];seen=set();pending=[]
        for entry in raw['cards']:
            item=copy.deepcopy(entry)
            item['id']=identifier(item.get('id',''))
            if item['id'] in seen:raise ValueError('同一设定集的卡片 ID 不能重复。')
            seen.add(item['id'])
            if item.get('kind') not in KINDS:raise ValueError('卡片类型必须为人物、地点、物品、规则或事件。')
            item['name']=text(item.get('name',''),200)
            if not item['name'].strip():raise ValueError('卡片需要名称。')
            item['description']=text(item.get('description',''))
            item['appearance']=text(item.get('appearance',''),4000)
            if 'schedule_tendencies' in item:text(item['schedule_tendencies'],2000)
            if 'initial_relation' in item:
                if item['kind']!='character' or not isinstance(item['initial_relation'],dict) or len(item['initial_relation'])>30:raise ValueError('初始关系需要人物主角预设。')
                for protagonist,preset in item['initial_relation'].items():
                    identifier(protagonist)
                    if not isinstance(preset,dict) or any(type(preset.get(field))is not int or not 0<=preset[field]<=100 for field in ('trust','familiarity')):raise ValueError('初始信任与熟悉必须为 0–100。')
                    text(preset.get('identity',''),100)
            if 'initial_affinity' in item:
                presets=item['initial_affinity']
                if not isinstance(presets,dict) or len(presets)>30:raise ValueError('initial_affinity must be a bounded protagonist preset map')
                for protagonist,preset in presets.items():
                    identifier(protagonist)
                    if not isinstance(preset,dict) or type(preset.get('score'))is not int or not 0<=preset['score']<=100:raise ValueError('initial_affinity.score must be an integer in 0–100')
                    for field in ('basis','relationship'):
                        if field in preset:text(preset[field],2000)
                    if 'version' in preset and (type(preset['version'])is not int or preset['version']<1):raise ValueError('initial_affinity.version must be a positive integer')
            aliases=item.get('aliases',[])
            if not isinstance(aliases,list) or any(not isinstance(a,str) or len(a)>200 for a in aliases):
                raise ValueError('人物别名格式不正确。')
            if item.get('character_card') is not None:
                if item['kind']!='character':raise ValueError('只有人物卡可以包含酒馆角色卡。')
                card=self.tavern.normalize_card(item.pop('character_card'))
                card_id=identifier(item.get('card_id') or f'{key}-{item["id"]}')
                digest=hashlib.sha256(json.dumps(card,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                target=self.root/'cards'/(card_id+'.json')
                pending.append((target,{'id':card_id,'digest':digest,'imported_at':self.tavern.now(),
                            'source':'setting-set:'+key,'aliases':aliases+[item['name']],'card':card}))
                item['card_id']=card_id
            if item.get('card_id'):identifier(item['card_id'])
            cards.append(item)
        result={'id':key,'name':name,'description':text(raw.get('description','')),'cards':cards}
        with self.tavern.write_lock(self.root):
            for target,record in pending:
                if target.exists() and read(target)['digest']!=record['digest']:raise ValueError('角色卡 ID 已存在不同内容，请另选 ID。')
            for target,record in pending:
                if not target.exists():self.tavern.atomic_json(target,record)
            self.tavern.atomic_json(self.root/'setting-sets'/(key+'.json'),result)
        return result
    def import_world(self,raw,key=None):
        key=identifier(key or raw.get('id',''));name=text(raw.get('name',''),200)
        if not name.strip():raise ValueError('世界观需要名称。')
        sets=raw.get('setting_set_ids',[])
        if not isinstance(sets,list) or len(sets)>20:raise ValueError('设定集列表不正确。')
        for sid in sets:self.load('setting-sets',sid)
        result={'id':key,'name':name,'background':text(raw.get('background','')),
                'setting_set_ids':list(dict.fromkeys(sets)),'revision':1}
        result['world_gameplay']=copy.deepcopy(raw.get('world_gameplay',[]))
        for ref in result['world_gameplay']:ModuleStore(self.root,self.tavern).load(ref)
        for field in ('calendar','initial_items'):
            if field in raw:
                if not isinstance(raw[field],dict):raise ValueError(field+' 必须为对象。')
                result[field]=copy.deepcopy(raw[field])
        from story_engine import seed
        engine=seed(result)
        for iid,item in engine['items'].items():
            identifier(iid)
            if not isinstance(item,dict) or item.get('id')!=iid or type(item.get('quantity')) is not int or not 0<=item['quantity']<=999 or not isinstance(item.get('owner'),str) or not item['owner'] or not isinstance(item.get('name'),str):raise ValueError('初始物品格式不正确。')
        if 'visual_revision' in raw:result['visual_revision']=text(str(raw['visual_revision']),80)
        if 'visual_locations' in raw:
            locations=raw['visual_locations']
            if not isinstance(locations,dict) or len(locations)>100:raise ValueError('visual_locations must be a bounded location alias map')
            if any(not isinstance(v,list) or len(v)>30 or any(not isinstance(a,str) or len(a)>200 for a in v) for v in locations.values()):raise ValueError('Invalid location aliases')
            result['visual_locations']=copy.deepcopy(locations)
        for field in ('description','primary_card_id','default_protagonist_id'):
            if field in raw:result[field]=text(raw[field],2000 if field=='description' else 80)
        if result.get('primary_card_id'):self.tavern.find_record(self.root,'cards',result['primary_card_id'])
        scenes=raw.get('opening_scenes',[])
        if not isinstance(scenes,list) or len(scenes)>20:raise ValueError('剧本最多包含 20 个开场。')
        seen=set();clean=[]
        from turn_format import EXPRESSIONS,suggestion
        for scene in scenes:
            sid=identifier(scene.get('id',''))
            if sid in seen:raise ValueError('开场 ID 重复。')
            seen.add(sid)
            frames=scene.get('opening',[])
            if not isinstance(frames,list) or not 1<=len(frames)<=12:raise ValueError('剧本开场需要 1–12 个分镜。')
            for f in frames:
                if not isinstance(f,dict) or f.get('kind') not in {'dialogue','narration','thought'} or f.get('expression') not in EXPRESSIONS:raise ValueError('开场分镜类型或表情不正确。')
                if not text(f.get('text',''),8000).strip():raise ValueError('开场分镜不能为空。')
                text(f.get('speaker',''),200)
            choices=scene.get('choices',[])
            if not isinstance(choices,list) or len(choices)>3:raise ValueError('开场建议最多 3 条。')
            choices=[{'label':text(c['label'],100),'text':suggestion(text(c['text'],300))} for c in choices]
            item={'id':sid,'title':text(scene.get('title',''),100),'description':text(scene.get('description',''),2000),
                'background':identifier(scene.get('background','clubroom')),'opening':copy.deepcopy(frames),'choices':choices}
            if not item['title'].strip():raise ValueError('开场需要标题。')
            item['scene']=text(scene.get('scene',item['title']),2000)
            clean.append(item)
        if clean and not result.get('primary_card_id'):raise ValueError('剧本需要指定已导入的 primary_card_id。')
        result['opening_scenes']=clean
        with self.tavern.write_lock(self.root):
            target=self.root/'worlds'/(key+'.json')
            if target.exists():result['revision']=read(target).get('revision',0)+1
            self.tavern.atomic_json(target,result)
        return result
    def import_script(self,raw,validate_only=False):
        if not isinstance(raw,dict) or raw.get('spec')!='yukima_script_v1' or not isinstance(raw.get('world'),dict) or not isinstance(raw.get('setting_sets'),list):
            raise ValueError('剧本包需要 spec=yukima_script_v1、world 和 setting_sets。')
        import shutil,tempfile
        # Validate the complete package before mutating the shared catalogue.
        from contextlib import nullcontext
        if not validate_only:self.root.mkdir(parents=True,exist_ok=True)
        with (nullcontext() if validate_only else self.tavern.write_lock(self.root)):
            with tempfile.TemporaryDirectory(prefix='script-validation-') as folder:
                staged=Path(folder)
                for kind in ('cards','setting-sets','worlds','gameplay-modules'):
                    if (self.root/kind).exists():shutil.copytree(self.root/kind,staged/kind)
                if (self.root/'world-bindings.json').exists():shutil.copy2(self.root/'world-bindings.json',staged/'world-bindings.json')
                candidate=WorldLibrary(staged,self.tavern)
                for settings in raw['setting_sets']:candidate.import_set(settings)
                raw_world=copy.deepcopy(raw['world'])
                raw_world['world_gameplay']=ModuleStore(staged,self.tavern).install(raw_world['id'],raw.get('world_gameplay',[]))
                world=candidate.import_world(raw_world)
                if not world.get('primary_card_id'):raise ValueError('剧本需要 primary_card_id。')
                candidate.bind(world['primary_card_id'],world['id'],world['setting_set_ids'])
                snap=candidate.snapshot(world['primary_card_id'],world['id'])
                all_ids=set()
                for settings in snap['setting_sets']:
                    for card in settings['cards']:
                        if card['id'] in all_ids:raise ValueError('剧本设定卡 ID 跨集合重复。')
                        all_ids.add(card['id'])
                # Exercise initialization and public view before committing executable code.
                store=ModuleStore(staged,self.tavern)
                from story_engine import seed,apply_effect,module_context
                from cast import registry
                _,maincard=self.tavern.find_record(staged,'cards',world['primary_card_id'])
                actors=registry({'card_snapshot':maincard['card'],'card_id':world['primary_card_id'],'world_snapshot':snap,'facts':{}},{})
                initial_engine=seed(world)
                for ref in world['world_gameplay']:
                    context=module_context(initial_engine,world['opening_scenes'][0]['scene'] if world['opening_scenes'] else '',actors,'import-check')
                    initial=store.call(ref,'initialize',{},context)
                    store.call(ref,'view',initial['state'],context)
                    initial_engine['modules'][ref['id']]={'version':ref['version'],'sha256':ref['sha256'],'state':initial['state']}
                    for effect in initial.get('effects',[]):apply_effect(initial_engine,effect,actors)
                result={'script_id':world['id'],'name':world['name'],'opening_count':len(world['opening_scenes']),
                    'setting_set_ids':world['setting_set_ids'],'primary_card_id':world['primary_card_id'],
                    'modules':world['world_gameplay'],'validated':True,'written':not validate_only}
                if validate_only:return result
                changed=[];backup={}
                try:
                    for source in staged.rglob('*.json'):
                        relative=source.relative_to(staged);target=self.root/relative
                        if target.exists() and target.read_bytes()==source.read_bytes():continue
                        backup[target]=target.read_bytes() if target.exists() else None
                        changed.append(target);self.tavern.atomic_json(target,read(source))
                except OSError:
                    for target in reversed(changed):
                        if backup[target] is None:target.unlink(missing_ok=True)
                        else:target.write_bytes(backup[target])
                    raise
                return result
    def bind(self,card_id,world_id,setting_ids=None):
        self.tavern.find_record(self.root,'cards',card_id)
        world=self.load('worlds',world_id)
        sets=setting_ids if setting_ids is not None else world.get('setting_set_ids',[])
        for sid in sets:self.load('setting-sets',sid)
        with self.tavern.write_lock(self.root):
            target=self.root/'world-bindings.json'
            bindings=read(target) if target.exists() else {}
            bindings[card_id]={'world_id':world_id,'setting_set_ids':sets}
            self.tavern.atomic_json(target,bindings)
        return bindings[card_id]
    def snapshot(self,card_id,world_id=None,setting_ids=None):
        binding=self.list()['bindings'].get(card_id,{})
        world_id=world_id if world_id is not None else binding.get('world_id','')
        if world_id:world=copy.deepcopy(self.load('worlds',world_id))
        else:
            _,record=self.tavern.find_record(self.root,'cards',card_id)
            world={'id':'','name':'角色卡背景','background':record['card']['data'].get('scenario',''),'setting_set_ids':[]}
        defaults=binding.get('setting_set_ids',world.get('setting_set_ids',[])) if binding.get('world_id')==world_id else world.get('setting_set_ids',[])
        sets=setting_ids if setting_ids is not None else defaults
        world['setting_sets']=[copy.deepcopy(self.load('setting-sets',sid)) for sid in sets]
        for settings in world['setting_sets']:
            for entry in settings['cards']:
                if entry.get('card_id'):
                    _,record=self.tavern.find_record(self.root,'cards',entry['card_id'])
                    entry['card_snapshot']=copy.deepcopy(record['card'])
        return world
    def attach(self,session_id,world_id,setting_ids=None):
        with self.tavern.write_lock(self.root):
            target,session=self.tavern.find_record(self.root,'sessions',session_id)
            session['world_snapshot']=self.snapshot(session['card_id'],world_id,setting_ids)
            session['revision']+=1;session['updated_at']=self.tavern.now()
            self.tavern.atomic_json(target,session)
        return {'session_id':session_id,'world_id':world_id,'revision':session['revision']}

def engine_calendar(world):
    from story_engine import seed
    return seed(world)['calendar']

def world_context(snapshot,incoming='',recent=''):
    # Background is always present. Character/rule cards remain authoritative;
    # large location/item/event collections are selected by the current scene.
    cards=[];budget=20000
    haystack=incoming+'\n'+recent
    for settings in snapshot.get('setting_sets',[]):
        for card in settings['cards']:
            always=card['kind']=='rule'
            if not always and not any(name in haystack for name in [card['name'],*card.get('aliases',[])]):continue
            value={k:copy.deepcopy(v) for k,v in card.items() if k!='card_snapshot'}
            if card.get('card_snapshot'):
                data=card['card_snapshot']['data']
                value['profile']={k:data.get(k,'') for k in ('name','description','personality','scenario')}
            size=len(json.dumps(value,ensure_ascii=False))
            if size>budget:continue
            cards.append(value);budget-=size
    return {'id':snapshot.get('id',''),'name':snapshot.get('name',''),
            'background':snapshot.get('background',''),'setting_cards':cards,
            'meaning':'世界观是背景资料；设定卡不是玩家已经经历的剧情。'}

def main():
    from galgame import load_tavern
    tavern=load_tavern(Path(__file__).with_name('tavern.py'))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[3]/'database/roleplay-library'))
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('list')
    for kind in ('import-world','import-set','import-protagonist','import-script','validate-script'):
        p=commands.add_parser(kind);p.add_argument('file');p.add_argument('--id')
    for kind in ('bind','attach'):
        p=commands.add_parser(kind);p.add_argument('target');p.add_argument('world_id');p.add_argument('--set',action='append')
    args=parser.parse_args();library=WorldLibrary(args.root,tavern)
    if args.command=='list':result=library.list()
    elif args.command in {'import-script','validate-script'}:result=library.import_script(read_package(args.file),args.command=='validate-script')
    elif args.command=='import-protagonist':
        card=tavern.read_card(args.file);data=card['data']
        key=identifier(args.id or 'player-'+hashlib.sha256(data['name'].encode()).hexdigest()[:12])
        result={'id':key,'name':data['name'],'appearance':data.get('description',''),
                'description':data.get('personality',''),'card_snapshot':card}
        if Path(args.file).suffix.lower()=='.png':
            import shutil
            folder=Path(args.root)/'browser/assets';folder.mkdir(parents=True,exist_ok=True)
            filename='player-'+key+'-'+hashlib.sha256(Path(args.file).read_bytes()).hexdigest()[:12]+'.png'
            shutil.copy2(args.file,folder/filename)
            result['reference']='/media/browser/assets/'+filename
        with tavern.write_lock(Path(args.root)):tavern.atomic_json(Path(args.root)/'protagonists'/(key+'.json'),result)
    elif args.command=='import-set':result=library.import_set(read(args.file),args.id)
    elif args.command=='import-world':result=library.import_world(read(args.file),args.id)
    elif args.command=='bind':result=library.bind(args.target,args.world_id,args.set)
    else:result=library.attach(args.target,args.world_id,args.set)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
