"""Story-scoped cast and replaceable player appearance. No inferred NPC faces."""
import copy
import hashlib
import json
import re
from pathlib import Path

DEFAULT_PLAYER = {'id': 'hachiman', 'name': '比企谷八幡', 'age': '16岁（高二）', 'appearance': '瘦削男高中生，短黑发、略翘发梢与呆毛，细长而倦怠的眼睛，深色男式校服。', 'description': '外貌参考比企谷八幡；既有关系按所选世界观与当前存档确定，不替玩家决定行为。', 'source': 'https://www.tbs.co.jp/anime/oregairu/character/chara01.html', 'avatar': '/images/oregairu/hachiman-label.svg', 'display_profile': {'age': '16岁（高二）', 'biography': '总武高中二年级学生，惯于独来独往。观察群体时常带怀疑与自嘲，对人际关系有自己的判断。', 'summary': '独来独往，观察敏锐，带着自嘲的幽默。', 'personality': '独来独往，观察敏锐，带着自嘲的幽默。', 'appearance': '瘦削男高中生，短黑发、略翘发梢与呆毛，细长而倦怠的眼睛，深色男式校服。', 'avatar': '/images/oregairu/hachiman-label.svg'}}

def player_cards(root):
    result={DEFAULT_PLAYER['id']:copy.deepcopy(DEFAULT_PLAYER)}
    for p in sorted((Path(root)/'protagonists').glob('*.json')):
        data=json.loads(p.read_text(encoding='utf-8-sig'));result[data['id']]=data
    return list(result.values())

def player_snapshot(root,key=None):
    for card in player_cards(root):
        if card['id']==(key or 'hachiman'):return copy.deepcopy(card)
    raise ValueError('找不到这张主角卡。')

def registry(session,descriptor):
    data=session['card_snapshot']['data'];name=descriptor.get('name',data['name'])
    primary={'id':'primary','name':name,'aliases':[data['name'],name,*descriptor.get('aliases',[])],
        'card_id':session['card_id'],'appearance':data.get('description','')[:5000],
        'sprites':descriptor.get('sprites',{}),'avatar':descriptor.get('avatar',''),'reference':descriptor.get('reference',''),
        'default_appearance':descriptor.get('default_appearance','school-uniform')}
    actors={'primary':primary}
    world=session.get('world_snapshot') or session['facts'].get('browser_world_snapshot',{})
    for settings in world.get('setting_sets',[]):
        for item in settings.get('cards',[]):
            if item.get('kind')!='character':continue
            if item.get('card_id')==session['card_id'] or item['name'] in primary['aliases']:
                primary['initial_affinity']=copy.deepcopy(item.get('initial_affinity',{}))
                primary['initial_relation']=copy.deepcopy(item.get('initial_relation',{}))
                primary['initial_recognition']=copy.deepcopy(item.get('initial_recognition',{}))
                primary.update({f:copy.deepcopy(item.get(f,'')) for f in ('school','class_name','classroom_location')});continue
            key='world-'+settings['id']+'-'+item['id']
            card=item.get('card_snapshot',{}).get('data',{})
            actors[key]={'id':key,'name':item['name'],'aliases':item.get('aliases',[])+[card.get('name','')],
                'card_id':item.get('card_id',''),'appearance':item.get('appearance') or card.get('description','')[:5000],
                'role':item.get('role','character'),'initial_affinity':copy.deepcopy(item.get('initial_affinity',{})),
                'initial_relation':copy.deepcopy(item.get('initial_relation',{})),'initial_recognition':copy.deepcopy(item.get('initial_recognition',{})),
                'sprites':{},'avatar':item.get('avatar',''),'reference':'','default_appearance':'school-uniform',
                **{f:copy.deepcopy(item.get(f,'')) for f in ('school','class_name','classroom_location')}}
    actors.update(copy.deepcopy(session['facts'].get('browser_cast',{})))
    protagonist=(session.get('protagonist_snapshot') or session['facts'].get('browser_protagonist_snapshot',{})).get('id','hachiman')
    for actor in actors.values():
        presets=actor.get('initial_relation',{})
        actor['relation_baseline']=copy.deepcopy(presets.get(protagonist,presets.get('default',{})))
    progress=session['facts'].get('browser_authored',{})
    route=next((r for r in world.get('storylines',[]) if r.get('id')==progress.get('id')),None)
    if route:
        # Route-era baselines belong only to this frozen new save, never to the catalogue or old branches.
        for actor in actors.values():
            score=route.get('initial_affinity',{}).get(actor['name'])
            if type(score)is int:actor['initial_affinity']={session.get('protagonist_snapshot',{}).get('id','hachiman'):{'score':score,'version':1,'basis':'预制线开场已确立的相处经历','relationship':route.get('initial_relations',{}).get(actor['name'],{}).get('identity','已有相处经历')}}
    return actors

def resolve_actor(value,actors,user=''):
    """Accept unambiguous catalogue names/short IDs, never guess an NPC's face."""
    if not isinstance(value,str):return None
    value=value.strip()
    if value=='player' or value in {user,'玩家','你'}:return 'player'
    if value in actors:return value
    matches=[]
    for key,a in actors.items():
        names=[a['name'],*a.get('aliases',[])]
        # World IDs have a stable setting-set prefix; models occasionally emit
        # the card ID or its final slug instead of the full world actor ID.
        variants=[key,key.removeprefix('world-'),a.get('card_id','')]
        if key.startswith('world-'):variants.append(key.rsplit('-',1)[-1])
        if value.casefold() in {s.casefold() for s in names+variants if s}:matches.append(key)
    return matches[0] if len(set(matches))==1 else None

def register_arrivals(state,actors,user):
    """Silent newcomers can be named in arrival metadata before any dialogue."""
    for entry in (state or {}).get('arrivals',[]):
        name=entry.get('name') or entry.get('actor_id','')
        known=resolve_actor(name,actors,user)
        if known:
            if entry.get('name') and name in entry.get('evidence',''):entry['actor_id']=known
            continue
        if not isinstance(name,str) or not re.fullmatch(r'[\u4e00-\u9fff·]{2,16}|[A-Za-z][A-Za-z .\'-]{1,60}',name):continue
        if name not in entry.get('evidence',''):continue
        key='guest-'+hashlib.sha256(name.encode()).hexdigest()[:16]
        actors[key]={'id':key,'name':name,'aliases':[],'appearance':'','sprites':{},'avatar':'','reference':'','provisional':True}
        entry['name']=name
        entry['actor_id']=key

def bind_frames(frames,actors,user,scene_state=None):
    register_arrivals(scene_state,actors,user)
    result=copy.deepcopy(frames);last='primary'
    for f in result:
        speaker=f.get('speaker','').strip()
        if f.get('kind')=='narration' and speaker.lower() in {'旁白','叙述','narrator','narration','场景'}:speaker=''
        if speaker in {user,'玩家','你'}:key='player'
        elif speaker:
            key=resolve_actor(speaker,actors,user)
            if key is None:
                key='guest-'+hashlib.sha256(speaker.encode()).hexdigest()[:16]
                actors[key]={'id':key,'name':speaker,'aliases':[],'appearance':'','sprites':{},'avatar':'','reference':'','provisional':True}
            elif key!='player':f['speaker']=actors[key]['name']
        else:
            present=f.get('stage',{}).get('present_actor_ids')
            if isinstance(present,list):present=[resolve_actor(v,actors,user) or v for v in present]
            key=last if present is None or last in present else (present[0] if present else 'narrator')
        f['actor_id']=key
        if isinstance(f.get('stage'),dict):
            f['stage']['present_actor_ids']=[resolve_actor(v,actors,user) or v for v in f['stage'].get('present_actor_ids',[])]
        if key!='player':last=key
    return result

def asset_key(session,kind,background='',actor=None,appearance='',expression='',action=''):
    from shared_gallery import visual_key
    return visual_key(session,kind,background=background,actor=actor,appearance=appearance,expression=expression,event=action)
