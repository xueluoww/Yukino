from map_runtime import get_locations
"""Single authoritative dynamic state. All mutations occur in private transaction copies."""
import copy, datetime
from event_schema import digest,validate_state,validate_effect,number,identifier

def clock_time(state):return (state['clock']['day']-1)*1440+state['clock']['minute']
def state_hash(state):return digest({k:v for k,v in state.items()if k!='journal_head'})
def read(state,cid,default=None):return state['cards'].get(cid,{}).get('value',default)
def location(state,actor):return read(state,'loc:'+actor,{}).get('location')
def colocated(state,a,b):
 va=read(state,'loc:'+a,{});vb=read(state,'loc:'+b,{})
 return va.get('location')is not None and va.get('location')==vb.get('location') and not va.get('transit_to')and not vb.get('transit_to')and va.get('at_entrance',False)==vb.get('at_entrance',False)
def put(state,cid,kind,value,subjects=(),visible=()):
 old=state['cards'].get(cid,{})
 state['cards'][cid]={'id':cid,'template':kind,'subjects':list(subjects),'value':copy.deepcopy(value),'status':'active',
  'valid_from':clock_time(state),'source_event_ids':[],'visibility':list(visible),'revision':old.get('revision',0)+1}

def initialize(definition,world):
 config=definition['config'];start=world.get('time',{}).get('start',{})
 state={'schema_version':1,'mode':'event-v1','definition_hash':definition['definition_hash'],
  'clock':{'date':start.get('date'),'day':1,'minute':start.get('minute',960),'elapsed_minutes':0},
  'cards':{},'module_states':{},'plot':{'phase':'开场'},'authored':{},'scheduled':{},
  'rng':{'seed':config.get('seed','world-v1'),'samples':{}},'fired':{},'cooldowns':{},'journal_head':'','state_revision':0}
 for lid,info in get_locations(definition).items():
  from place_hours import is_open
  windows=config.get('opening_hours',{}).get(lid)
  opened=is_open(windows,state['clock']['minute'])if windows is not None else info.get('open',True)
  put(state,'place:'+lid,'availability',{'open':opened},[lid],['public_rule'])
 for actor,loc in config.get('actor_locations',{}).items():put(state,'loc:'+actor,'location',{'location':loc},[actor],[actor])
 for door_id,door in config.get('doors',{}).items():
  put(state,'door:'+door_id,'door',{'locked':door.get('locked',True),'open':door.get('open',False)},[door['location'],door['destination']],['public_rule'])
 for actor in definition['characters']:
  card=definition['characters'][actor]
  baseline=card.get('event_relation',{})
  put(state,'rel:'+actor+':player','relation',{'affection':baseline.get('affection',30),'trust':baseline.get('trust',30),
   'familiarity':baseline.get('familiarity',0),'identity':baseline.get('identity','')},[actor,'player'],[actor,'player'])
 for effect in config.get('initial',[]):apply_one(state,effect,definition,system=True)
 if config.get('world_mode'):
  from relationship_graph import initialize as initialize_relations
  initialize_relations(state,definition)
 if config.get('card_refinement'):
  # Person-owned inventory is carried. Stored objects need a place/container owner.
  for cid,c in list(state['cards'].items()):
   if c['template']=='item'and c['value']['owner']in set(definition['characters'])|{'player'}:
    owner=c['value']['owner'];v=copy.deepcopy(c['value']);v['location']=location(state,owner)
    put(state,cid,'item',v,[owner],[owner])
 from map_runtime import initialize_knowledge
 initialize_knowledge(state,definition)
 if config.get('world_mode'):
  for actor,place in config.get('actor_locations',{}).items():
   put(state,'activity-history:'+actor,'activity_history',{'owner':actor,'start':clock_time(state),
    'visits':[{'location':place,'at':clock_time(state),'source_event':'opening_position'}],'gaps':[]},[actor],[actor])
 validate_state(state)
 return state

def apply_one(state,effect,definition,system=False,evidence=''):
 e=validate_effect(effect);kind=e['template'][8:];actor=e.get('actor');cards=state['cards'];before=state_hash(state)
 participants=set(x for x in (actor,e.get('target'))if x and x in set(definition['characters'])|{'player'})
 observers=set(participants);title=e.get('title','');outcome='applied';public={};spoken=None
 if actor and actor not in set(definition['characters'])|{'player'}:raise ValueError('Undeclared actor')
 if actor and read(state,'vital:'+actor,{}).get('alive')is False:raise ValueError('Dead actor cannot act')
 if kind=='move':
  put(state,'posture:'+actor,'posture',{'posture':'standing'},[actor],[actor])
  if read(state,'loc:'+actor,{}).get('transit_to'):raise ValueError('Actor already travelling')
  origin=location(state,actor);dest=e['location'];info=get_locations(definition,state)
  if origin==dest and not read(state,'loc:'+actor,{}).get('at_entrance'):
   return {'template':e['template'],'title':'仍在当前房间','outcome':'applied','participants':[actor],
    'observers':[actor],'public':{'actor':actor,'departure':origin,'location':dest,'already_here':True},
    'speech':None,'effects':[e],'before_hash':before,'after_hash':before}
  from map_runtime import enabled as map_enabled,actor_locations,edge_known
  if not system and info.get(dest,{}).get('secret') and dest not in actor_locations(state,definition,actor):raise ValueError('目的地属于未知的私人范围，不能直接进入。')
  if not info.get(dest,{}).get('walkable',True):raise ValueError('Container is not a physical stop; choose its entry')
  if map_enabled(definition) and not system and (dest not in actor_locations(state,definition,actor) or origin!=dest and not edge_known(state,definition,actor,origin,dest)):raise ValueError('Destination/route not known to this actor')
  if origin!=dest and dest not in info.get(origin,{}).get('links',{}):raise ValueError('Unreachable destination')
  if not read(state,'place:'+dest,{}).get('open',True):raise ValueError('Destination closed')
  for door_id,door in definition['config'].get('doors',{}).items():
   if {door.get('location'),door.get('destination')}=={origin,dest}:
    value=copy.deepcopy(read(state,'door:'+door_id,{'locked':door.get('locked',True),'open':door.get('open',False)}))
    if value.get('locked'):raise ValueError('门锁着，暂时不能通过。')
    value['open']=True;put(state,'door:'+door_id,'door',value,[origin,dest],['public_rule'])
  from scene_presence import visible_actor_ids
  local=set(visible_actor_ids(state,definition,actor))|{actor}
  minutes=e.get('minutes',info.get(origin,{}).get('links',{}).get(dest,0))
  if minutes<info.get(origin,{}).get('links',{}).get(dest,0):raise ValueError('Travel cannot be faster than declared route')
  put(state,'loc:'+actor,'location',{'location':origin,'transit_to':dest,'arrive_at':clock_time(state)+minutes},[actor],[actor])
  if minutes:
   state['scheduled']['arrival:'+actor]={'at':clock_time(state)+minutes,'effects':[],
       'arrival':{'actor':actor,'location':dest},'origin':origin}
  else:
   # Even a zero-minute move is settled through the arrival journal.
   state['scheduled']['arrival:'+actor]={'at':clock_time(state),'effects':[], 'arrival':{'actor':actor,'location':dest},'origin':origin}
  observers|=local;title=actor+'离开'+origin;public={'departure':origin,'actor':actor}
  # Inventory travels with its holder, never remains as an observable duplicate.
  for cid,card in list(cards.items()):
   if card['template']=='item'and card['value']['owner']==actor and card['value']['quantity']:
    v=copy.deepcopy(card['value']);v['location']=None if minutes else dest
    put(state,cid,'item',v,[actor],[actor])
 elif kind in ('open','close'):
  door=definition['config'].get('doors',{}).get(e['id'])
  if not door or location(state,actor) not in (door['location'],door['destination']):raise ValueError('这扇门不在伸手可及的位置。')
  value=copy.deepcopy(read(state,'door:'+e['id'],{'locked':door.get('locked',True),'open':door.get('open',False)}))
  if kind=='open' and value['locked']:raise ValueError('门锁着，暂时打不开。')
  value['open']=kind=='open';put(state,'door:'+e['id'],'door',value,[door['location'],door['destination']],['public_rule'])
  title='打开门' if kind=='open' else '关上门';public={'actor':actor,'door':e['id'],'open':value['open']}
 elif kind=='wait':raise ValueError('Wait belongs to heartbeat, not state mutation')
 elif kind=='say':
  text=e['text']
  if not isinstance(text,str)or not text.strip()or len(text)>3000:raise ValueError('Invalid utterance')
  from scene_presence import can_hear
  peers={a for a in [*definition['characters'],'player']if a!=actor and can_hear(state,definition,actor,a)}
  requested=e.get('audience',sorted(peers))
  if not set(requested)<=peers:raise ValueError('Audience outside physical hearing range')
  for claim in e.get('claims',[]):
   source=cards.get(claim)
   if not source or source['template']!='knowledge' or actor not in source['visibility']:raise ValueError('Unauthorized knowledge claim')
   if source['value'].get('disclose')is False:raise ValueError('Disclosure forbidden')
  observers=set(requested)|{actor};spoken={'actor':actor,'text':text,'audience':requested,'claims':e.get('claims',[])}
  put(state,'speech:'+digest([actor,clock_time(state),text])[:20],'observation',spoken,sorted(observers),sorted(observers))
  for peer in requested:
   for claim in e.get('claims',[]):
    v=copy.deepcopy(cards[claim]['value']);v.update(source={'kind':'hearsay','actor':actor,'evidence':text},holder=peer,belief='reported')
    if definition['config'].get('card_language'):
     # The recipient knows only the utterance, never the cited full private source.
     # Keep a separate heard unit so an imprecise reply cannot overwrite precise old knowledge.
     v['content']=text;v['topic']='heard-'+digest([actor,text])[:18]
    put(state,'know:'+peer+':'+v['topic'],'knowledge',v,[peer],[peer])
   import re
   introduction=re.match(r'^(?:你好[，,。 ]*)?我(?:叫|的名字是)([^，,。！？\s]{1,20})',text)
   if not introduction:
    named=re.match(r'^(?:你好[，,。 ]*)?我是([^，,。！？\s]{1,20})',text)
    known=[c['name'] for c in definition['characters'].values()]
    # "我是来找人/普通人/雪乃男朋友" is not a self-introduction. Unknown names
    # use the unambiguous existing "我叫" form, rather than guessing grammar.
    if named and (named[1] in known or re.fullmatch(r'[\u4e00-\u9fff]{2,8}',named[1]) and not re.search(r'来|人|学生|老师|朋友|男友|女友|哥哥|妹妹|同学|社长|主角|普通|新|负责',named[1])):introduction=named
   if introduction:
    put(state,'know:'+peer+':name-'+actor,'knowledge',{'holder':peer,'topic':'name-'+actor,'content':introduction[1],
     'belief':'reported','source':{'kind':'self_introduction','actor':actor,'evidence':text},'disclose':True},[peer],[peer])
   if peer!='player'and actor=='player'and not definition['config'].get('world_mode'):
    cid='rel:'+peer+':player';rel=copy.deepcopy(read(state,cid));rel['familiarity']=min(100,rel['familiarity']+1)
    put(state,cid,'relation',rel,[peer,'player'],[peer,'player'])
  if definition['config'].get('world_mode'):
   from relationship_graph import contact
   contact(state,actor,requested,definition)
  title='交谈';public={'text':text,'actor':actor}
 elif kind=='observe':
  target=e['target']
  if target in definition['characters']or target=='player':
   if not colocated(state,actor,target):raise ValueError('Target cannot be observed here')
   from map_runtime import enabled as map_enabled
   if map_enabled(definition):
    from scene_presence import visible_actor_ids
    if target not in visible_actor_ids(state,definition,actor):raise ValueError('尚未实际注意到这个人物，请先观察附近。')
   put(state,'know:'+actor+':position-'+target,'knowledge',{'holder':actor,'topic':'position-'+target,
    'content':target+'在'+location(state,target),'belief':'observed','source':{'kind':'see','target':target},'disclose':True},[actor],[actor])
  elif 'item:'+target in cards:
   item=read(state,'item:'+target)
   if not item['quantity']:raise ValueError('Item is no longer present')
   if item['location']!=location(state,actor)and item['owner']!=actor:raise ValueError('Item cannot be observed here')
   if definition['config'].get('world_mode')and read(state,'loc:'+actor,{}).get('at_entrance')and item['owner']!=actor:raise ValueError('Cannot observe an inside item through a closed entrance')
   put(state,'know:'+actor+':item-'+target,'knowledge',{'holder':actor,'topic':'item-'+target,'content':item['item']+'在'+item['location'],
    'belief':'observed','source':{'kind':'see','target':target},'disclose':True},[actor],[actor])
  else:raise ValueError('Unknown observable entity')
  title='观察';public={'actor':actor,'target':target};observers={actor}
  if 'item:'+target in cards:
   public['target_name']=definition['items'][read(state,'item:'+target)['item']]['name']
 elif kind=='buy':
  from daily_life import purchase
  public,observers=purchase(state,e,definition);title='日常购买'
 elif kind in {'take','put_down','read','consume','use','write','open_item','close_item'}:
  from item_rules import apply_item
  public,observers=apply_item(state,e,definition);title={'take':'拿取物品','put_down':'放下物品','read':'阅读物品','consume':'食用物品','use':'使用物品','write':'记录文字','open_item':'翻开物品','close_item':'合上物品'}[kind]
 elif kind in {'knock','sit','stand','gesture','sit_up','lie_down'}:
  here=location(state,actor)
  if not here or read(state,'loc:'+actor,{}).get('transit_to'):raise ValueError('Action requires a settled location')
  if kind=='knock':
   if e['location']!=here and e['location']not in get_locations(definition,state)[here].get('links',{}):raise ValueError('Door is not within reach')
   hearing={here,e['location']}
   for door in definition['config'].get('doors',{}).values():
    if door.get('location')==here and e['location']==here:hearing.add(door['destination'])
   observers={a for a in [*definition['characters'],'player']if location(state,a)in hearing and not read(state,'loc:'+a,{}).get('transit_to')}
   title='敲门';public={'actor':actor,'location':e['location']}
   for peer in observers-{actor}:
    put(state,'doorcontact:'+actor+':'+peer,'door_contact',{'actors':[actor,peer],'locations':{a:location(state,a) for a in (actor,peer)},'expires':clock_time(state)+2},[actor,peer],[actor,peer])
  else:
   observers={a for a in [*definition['characters'],'player']if colocated(state,a,actor)}
   if kind=='sit_up' and read(state,'posture:'+actor,{}).get('posture')!='lying':raise ValueError('你目前没有躺下，不能把“坐起身”当作“坐下”。')
   if kind in('sit','stand','sit_up','lie_down'):
    posture={'sit':'sitting','stand':'standing','sit_up':'sitting','lie_down':'lying'}[kind]
    put(state,'posture:'+actor,'posture',{'posture':posture},[actor],list(observers))
   title={'sit':'坐下','stand':'起身','sit_up':'坐起身','lie_down':'躺下','gesture':'示意'}[kind];public={'actor':actor,**({'text':e['text']}if kind=='gesture'else{})}
 elif kind=='search':
  here=location(state,actor)
  if read(state,'loc:'+actor,{}).get('transit_to'):raise ValueError('Cannot search during travel')
  found=[]
  for cid,card in list(cards.items()):
   if card['template']!='item'or not card['value']['quantity']or card['value']['location']!=here:continue
   if definition['config'].get('world_mode')and read(state,'loc:'+actor,{}).get('at_entrance')and card['value']['owner']!=actor:continue
   if e.get('target')and e['target']not in(cid,cid[5:],card['value']['item']):continue
   # Secret/hidden items require script-specific discovery rather than omniscient search.
   if definition['items'][card['value']['item']].get('hidden'):continue
   instance=cid[5:];found.append(instance)
   put(state,'know:'+actor+':item-'+instance,'knowledge',{'holder':actor,'topic':'item-'+instance,
    'content':definition['items'][card['value']['item']]['name']+'在'+here,'belief':'observed',
    'source':{'kind':'search','target':instance},'disclose':True},[actor],[actor])
  title='搜索';public={'actor':actor,'found':found};observers={actor}
 elif kind=='conceal':
  put(state,'intent:'+actor+':'+digest(e['text'])[:16],'intent',{'owner':actor,'text':e['text'],'status':'private'},[actor],[actor])
  title='保留意图';public={};observers={actor}
 elif kind=='learn':
  if not system:raise ValueError('Knowledge acquisition requires checked observer/source')
  if e.get('belief','observed')not in {'observed','reported','guess','corrected'}:raise ValueError('Unknown belief type')
  put(state,'know:'+actor+':'+e['topic'],'knowledge',{'holder':actor,'topic':e['topic'],'content':e['content'],
   'belief':e.get('belief','observed'),'source':copy.deepcopy(e['source']),'disclose':e.get('disclose',True)},[actor],[actor])
  title='获知信息';public={'actor':actor,'topic':e['topic']};observers={actor}
 elif kind=='goal':
  if actor=='player'and not system and not evidence:raise ValueError('Player goal needs actual decision')
  put(state,'goal:'+e['id'],'goal',{'owner':actor,'title':e['title'],'status':e.get('status','active'),
   'criteria':e.get('criteria',[]),'deadline':e.get('deadline'),'target':e.get('target')},[actor],[actor])
  title='目标变化';observers={actor};public={'actor':actor}
 elif kind=='offer':
  target=e.get('target','player');cid='offer:'+e['id']
  if cid in cards:raise ValueError('Opportunity already exists')
  put(state,cid,'opportunity',{'owner':actor,'target':target,'title':e['title'],'status':'offered','criteria':e.get('criteria',[]),
    'deadline':e.get('deadline'),'methods':e.get('methods',[])},[actor,target],[actor,target]if colocated(state,actor,target)else[actor])
  title=e['title'];participants.add(target);observers=set(cards[cid]['visibility']);public={'title':title}
 elif kind in {'accept','decline','complete'}:
  cid='offer:'+e['id'];offer=read(state,cid)
  if not offer or offer['target']!=actor:raise ValueError('Opportunity is not addressed to this actor')
  if actor not in cards[cid]['visibility']:raise ValueError('Actor has not received this opportunity')
  if kind in {'accept','decline'}and offer['status']!='offered':raise ValueError('Opportunity is not pending')
  if kind=='accept'and not evidence:raise ValueError('Acceptance needs expressed intent')
  if kind=='complete':
   if offer['status']not in {'accepted','active'}:raise ValueError('Cannot complete an unaccepted task')
   from event_rules import evaluate_condition
   if not all(evaluate_condition(c,state) for c in offer['criteria']):raise ValueError('Completion condition not satisfied')
  v=copy.deepcopy(offer);v['status']={'accept':'accepted','decline':'declined','complete':'resolved'}[kind]
  if kind=='complete':v['method']=e.get('method',evidence)
  put(state,cid,'opportunity',v,[offer['owner'],actor],cards[cid]['visibility']);title=v['title']+' · '+v['status'];public={'title':title}
 elif kind=='spawn':
  if not system:raise ValueError('Items cannot be created by free text')
  if e['item']not in definition['items']:raise ValueError('Item definition missing')
  cid='item:'+e['instance']
  if cid in cards:raise ValueError('Item instance already exists')
  put(state,cid,'item',{'item':e['item'],'owner':e['owner'],'location':e['location'],'quantity':e['quantity']},[e['owner']],[e['owner']])
  title='物品出现';public={'item':e['item']}
 elif kind=='transfer':
  cid='item:'+e['instance'];item=read(state,cid)
  if not item or item['owner']!=actor or item['quantity']<e.get('quantity',1):raise ValueError('Item ownership/quantity mismatch')
  if not colocated(state,actor,e['target']):raise ValueError('Transfer needs actual proximity')
  from map_runtime import enabled as map_enabled
  if map_enabled(definition):
   from scene_presence import visible_actor_ids
   if e['target'] not in visible_actor_ids(state,definition,actor):raise ValueError('尚未与接收者实际接触，不能远距离交接。')
  if e['target']=='player'and actor!='player'and not e.get('consent'):raise ValueError('Cannot force player to receive')
  qty=e.get('quantity',1);v=copy.deepcopy(item);v['quantity']-=qty;v.pop('remaining_portions',None);put(state,cid,'item',v,[actor],[actor])
  dest='item:'+e['instance']+':'+e['target'];old=read(state,dest)
  if old and old['item']!=item['item']:raise ValueError('Instance collision')
  value={**copy.deepcopy(item),'owner':e['target'],'location':location(state,actor),'quantity':qty+(old['quantity']if old else 0)}
  from item_rules import merge_portions
  merge_portions(value,old)
  if value.get('written_content'):value.setdefault('written_by',None)
  put(state,dest,'item',value,[e['target']],sorted(participants));title='物品交接';observers=participants;public={'item':item['item'],'quantity':qty}
 elif kind=='relation':
  if not evidence and not system:raise ValueError('Relation needs event evidence')
  cid='rel:'+actor+':'+e['target'];v=copy.deepcopy(read(state,cid,{'affection':30,'trust':30,'familiarity':0,'identity':''}))
  for field in ('affection','trust','familiarity'):
   delta=e.get(field,0)
   if type(delta)is not int or abs(delta)>6:raise ValueError('Relation delta out of bounds')
  from relation_policy import settle as settle_relation
  v=settle_relation(state,definition,actor,e['target'],v,{f:e.get(f,0)for f in('affection','trust','familiarity')},
    {'kind':'script_event'}if system else None)
  if 'identity'in e:
   if any(x in e['identity']for x in ('恋人','情侣','夫妻'))and not e.get('consent'):raise ValueError('Intimate identity needs mutual consent')
   v['identity']=e['identity']
  put(state,cid,'relation',v,[actor,e['target']],[actor]if definition['config'].get('world_mode')else[actor,e['target']]);title='关系变化';public={'reason':e.get('reason',evidence)}
 elif kind=='emotion':
  put(state,'emotion:'+actor,'emotion',{'name':e['name'],'intensity':number(e.get('intensity',50),0,100),'reason':e.get('reason',evidence)},[actor],[actor])
  title='情绪变化';observers={actor};public={'actor':actor}
 elif kind=='availability':
  if not system:raise ValueError('World rules require rule capability')
  put(state,'place:'+e['location'],'availability',{'open':e['open']},[e['location']],['public_rule'])
  observers={a for a in [*definition['characters'],'player']if location(state,a)==e['location']};title='场所'+('开放'if e['open']else'关闭');public={'location':e['location'],'open':e['open']}
 elif kind=='schedule':
  if not system:raise ValueError('Schedule requires rule capability')
  if e['at']<clock_time(state):raise ValueError('Cannot schedule in past')
  state['scheduled'][e['id']]={'at':e['at'],'effects':e['effects']};title='安排活动';observers=set()
 elif kind=='cancel':
  if not system:raise ValueError('Cancel requires rule capability')
  state['scheduled'].pop(e['id'],None);title='取消安排';observers=set()
 else:title=e.get('title','平静的片刻');observers=set()
 validate_state(state)
 return {'template':e['template'],'title':title,'outcome':outcome,'participants':sorted(participants),'observers':sorted(observers),
  'public':public,'speech':spoken,'effects':[e],'before_hash':before,'after_hash':state_hash(state)}

def advance_clock(state,minutes):
 number(minutes,0,10080);old=state['clock']['minute'];days,minute=divmod(old+minutes,1440)
 if state['clock']['date']:state['clock']['date']=(datetime.date.fromisoformat(state['clock']['date'])+datetime.timedelta(days=days)).isoformat()
 state['clock']['day']+=days;state['clock']['minute']=minute;state['clock']['elapsed_minutes']+=minutes

def apply_batch(state,effects,definition,system=False,evidence=''):
 work=copy.deepcopy(state);records=[apply_one(work,e,definition,system,evidence)for e in effects];state.clear();state.update(work);return records

def project_player(state):
 return {'clock':copy.deepcopy(state['clock']),'cards':[copy.deepcopy(c)for c in state['cards'].values()if'player'in c['visibility']]}
def project_legacy(state):
 relations={};items={};threads={};knowledge={};positions={};affinity={}
 for c in state['cards'].values():
  v=c['value'];k=c['template']
  if k=='location':positions[c['subjects'][0]]=v['location']
  elif k=='relation'and c['subjects'][1]=='player':
   a=c['subjects'][0];relations[a]={k:v[k]for k in ('trust','familiarity','identity')};affinity[a]={'score':v['affection'],'history':[]}
  elif k=='item':items[c['id']]={'id':c['id'],'name':v['item'],**v}
  elif k=='opportunity':threads[c['id']]={'id':c['id'],'title':v['title'],'status':{'offered':'open','accepted':'active','declined':'cancelled','expired':'cancelled','resolved':'resolved'}.get(v['status'],v['status']),'note':'','deadline':str(v.get('deadline')or'')}
  elif k=='knowledge':knowledge.setdefault(v['holder'],[]).append({'observed':v['content'],'source':v['source'],'story_time':c['valid_from'],'epistemic_verified':True})
 return {'browser_engine':{'version':1,**copy.deepcopy(state.get('legacy_time',{})),'calendar':{k:state['clock'][k]for k in ('date','day','minute')},'relations':relations,'items':items,'threads':threads,
   'modules':copy.deepcopy(state['module_states']),'plot':copy.deepcopy(state['plot']),'applied_turns':[]},
   'browser_actor_locations':positions,'browser_actor_knowledge':knowledge,'browser_affinity':affinity}
