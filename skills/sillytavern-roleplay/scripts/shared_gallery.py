"""Script-scoped confirmed artwork; branch refs are the only gallery unlocks."""
import copy, hashlib, json, re, time
from pathlib import Path

FIELDS=('location','time','weather','season','layout','state')
def scene_schema():
    props={k:{'type':'string','pattern':r'^[a-zA-Z0-9_-]{0,80}$'} for k in FIELDS}
    for key,values in {'time':['','morning','noon','afternoon','dusk','night'],
        'weather':['','clear','cloudy','rain','snow','fog'],'season':['','spring','summer','autumn','winter']}.items():
        props[key]={'type':'string','enum':values}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
ALIASES={
 'clubroom':('clubroom','service-club','service_club','侍奉部活动室','侍奉部室','侍奉社活动室'),
 'corridor':('corridor','hallway','走廊','走道'),
 'playground':('playground','school-ground','school_ground','操场'),
 'courtyard':('courtyard','庭院','中庭'),
 'shopping-street':('shopping-street','shopping_street','商店街','商业街'),
 'station':('station','车站'),
}
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
def world_of(session):return session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})
def script_scope(session):
    w=world_of(session)
    # Display metadata, affection and the catalogue import counter cannot alter art.
    visual=w.get('visual_revision') or digest({'background':w.get('background',''),
        'places':[c for s in w.get('setting_sets',[]) for c in s.get('cards',[]) if c.get('kind')=='location']})
    return (w.get('id') or 'card-'+session['card_id'])+':'+str(visual)
def background_identity(session,background,identity=None):
    identity=identity or {};w=world_of(session);catalog=w.get('visual_locations',{})
    location=identity.get('location') or background
    terms=location.casefold()
    for key,names in catalog.items():
        if terms==key or terms in [str(n).casefold() for n in names]:location=key;break
    else:
        for key,names in ALIASES.items():
            if any(terms==n or terms.startswith(n+'-') or terms.startswith(n+'_') for n in names):location=key;break
    # Legacy keys retain unknown qualifiers. Never collapse different weather/light.
    known=location!=background or background in ALIASES
    value={k:str(identity.get(k) or '') for k in FIELDS}
    value['location']=location
    aliases={'time':{'放学后午后':'afternoon','午后':'afternoon','下午':'afternoon','早晨':'morning','中午':'noon','黄昏':'dusk','傍晚':'dusk','晚间':'night','夜晚':'night','evening':'dusk','sunset':'dusk'},
        'weather':{'晴':'clear','晴天':'clear','sunny':'clear','阴':'cloudy','阴天':'cloudy','雨':'rain','雨天':'rain','rainy':'rain','雪':'snow'},
        'season':{'春':'spring','夏':'summer','秋':'autumn','冬':'winter','fall':'autumn'}}
    for field,options in aliases.items():value[field]=options.get(value[field],value[field])
    if not value['layout'] or value['layout'] in {location,identity.get('location')} or value['layout'] in catalog.get(location,[]):value['layout']='standard'
    if not value['state']:value['state']='normal'
    if known:
        for key,options in {'time':{'dusk':('dusk','sunset','evening'),'afternoon':('afternoon',),'night':('night',),'morning':('morning',)},
            'weather':{'rain':('rain','rainy'),'clear':('clear','sunny')},'season':{'autumn':('autumn','fall'),'spring':('spring',),'winter':('winter',),'summer':('summer',)}}.items():
            if not value[key]:
                value[key]=next((label for label,words in options.items() if any(re.search(r'(?:^|[-_])'+word+r'(?:$|[-_])',background) for word in words)),'')
        if not identity and background!=location:value['state']=background # Conservative legacy fallback.
    return value
def person_identity(actor,appearance='',expression=''):
    return {'identity':actor.get('card_id') or actor.get('name') or actor.get('id'),
        'appearance_description':actor.get('appearance',''),'reference':actor.get('reference',''),
        'outfit':appearance or actor.get('default_appearance','school-uniform'),'expression':expression}
def visual_key(session,kind,background='',identity=None,actor=None,appearance='',expression='',event='',participants=None,protagonist=None):
    scope=script_scope(session)
    if kind=='background':value=[scope,background_identity(session,background,identity)];prefix='bg'
    elif kind=='portrait':value=[scope,person_identity(actor or {},appearance,expression)];prefix='portrait'
    else:
        value=[scope,background_identity(session,background,identity),event,
            sorted(participants or [],key=lambda a:json.dumps(a,sort_keys=True)),protagonist or {}];prefix='cg'
    return prefix+'-'+digest(value)
def branch_refs(session):
    facts=session.get('facts',{});refs=set(facts.get('browser_gallery_refs',[]))
    visual=facts.get('browser_visual',{})
    refs.update(v for k,v in visual.items() if k in {'background_asset','cg_asset'} and v)
    refs.update(n.get('cg_asset') for n in facts.get('browser_story',{}).get('nodes',[]) if n.get('cg_asset'))
    refs.update(f['stage']['background_asset'] for f in facts.get('browser_latest_frames',[]) if f.get('stage',{}).get('background_asset'))
    return refs

class SharedGallery:
    def __init__(self,root,tavern):
        self.root=Path(root);self.tavern=tavern;self.path=self.root/'browser/shared-gallery.json'
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'version':1,'scripts':{}}
    def flush(self):
        for attempt in range(5):
            try:self.tavern.atomic_json(self.path,self.data);return
            except PermissionError:
                if attempt==4:raise
                time.sleep(.025*(2**attempt))
    def register(self,session,key,entry,persist=True):
        if entry.get('kind') not in {'background','cg'} or entry.get('speculative') or not entry.get('url'):return
        scope=script_scope(session);pool=self.data['scripts'].setdefault(scope,{})
        value={k:copy.deepcopy(v) for k,v in entry.items() if k in {'kind','url','path','name','background','background_identity','visual_key','revision_of','participant_visuals','protagonist_visual','event_key'}}|{'key':key}
        if pool.get(key)==value:return
        pool[key]=value
        if persist:self.flush()
    def find(self,session,key):
        pool=self.data['scripts'].get(script_scope(session),{})
        return next(((k,e) for k,e in pool.items() if k==key or e.get('visual_key')==key),None)
    def unlocked(self,session):
        pool=self.data['scripts'].get(script_scope(session),{})
        return [(key,pool[key]) for key in branch_refs(session) if key in pool]
    def bootstrap(self,cache):
        # Only saved/checkpoint artwork is confirmed. Never expose queued guesses.
        before=copy.deepcopy(self.data);sessions={}
        for p in (self.root/'sessions').glob('*.json'):
            s=json.loads(p.read_text(encoding='utf-8-sig'));sessions[s['id']]=s
        snapshots=list(sessions.values())
        for p in (self.root/'browser/checkpoints').glob('*/*.json'):
            snapshots.append(json.loads(p.read_text(encoding='utf-8-sig')))
        for s in snapshots:
            for key in branch_refs(s):
                entry=cache.get(key)
                if not entry or entry.get('speculative'):continue
                if entry.get('kind')=='background':
                    entry.setdefault('visual_key',visual_key(s,'background',background=entry.get('background',''),identity=entry.get('background_identity')))
                self.register(s,key,entry,persist=False)
        if self.data!=before:self.flush()
