from map_runtime import get_locations
"""Goal-set interface: authors, shell defaults, and replaceable scoped model proposals.

Proposals contain no effects, executable code, arbitrary conditions or actor overrides.
Completion is compiled by the shell; models cannot certify success.
"""
import copy
from event_schema import identifier,number,digest
from world_state import read,put,location,clock_time
from model_context import working_view
from actor_context import validate_no_literal_leak

KINDS={'obtain','read','visit','inquire','rest'}
GENERATOR='''为view本人提出当前时段的候选目标集，只JSON {"goals":[]}，最多3项，每项{id,kind,target,title,probability,priority}，可选deadline_after。kind仅obtain/read/visit/inquire/rest。target只能用allowed_targets对应类型；rest目标不需要target。目标不是动作脚本，无actions/effects/criteria/actor。结合本人静态性格、已知事实和时间；不把不知的远处物品位置当线索，不替其他人或玩家设目标、不知道未来/旁白/内心。可以空集，已有目标不重复。title简短写本人想完成的具体事情；probability为0到1的倾向；priority为0到100。生成候选不代表自动成功或强制玩家帮忙。'''

def config(definition):
 if len(definition['characters'])>32:raise ValueError('World trial currently supports at most 32 NPCs')
 raw=definition['config'].get('goal_sets',{'version':1})
 if not isinstance(raw,dict)or set(raw)-{'version','generation','windows','max_active','max_pulses'}or raw.get('version')!=1:raise ValueError('Invalid goal set contract')
 if raw.get('generation','shell')not in('shell','model'):raise ValueError('Unknown goal generator')
 number(raw.get('max_active',2),1,3);number(raw.get('max_pulses',12),1,48)
 windows=raw.get('windows',[{'id':'daytime','start':0,'end':1440,'actors':{}}])
 if not isinstance(windows,list)or not 1<=len(windows)<=8:raise ValueError('Bounded goal windows required')
 seen=set();spans=[]
 for window in windows:
  if set(window)-{'id','start','end','actors','school_days_only'}:raise ValueError('Unknown goal window field')
  if 'school_days_only' in window and type(window['school_days_only']) is not bool:raise ValueError('School-day window requires boolean')
  identifier(window['id']);number(window['start'],0,1439);number(window['end'],1,1440)
  if window['id']in seen or window['start']>=window['end']:raise ValueError('Invalid goal window')
  seen.add(window['id'])
  if any(window['start']<b and window['end']>a for a,b in spans):raise ValueError('Overlapping goal windows')
  spans.append((window['start'],window['end']))
  if not isinstance(window.get('actors',{}),dict)or set(window.get('actors',{}))-set(definition['characters']):raise ValueError('Goal set owner must be a script NPC')
  for actor,goals in window.get('actors',{}).items():validate_goals(goals,definition,actor)
 return {**copy.deepcopy(raw),'windows':copy.deepcopy(windows)}

def allowed_targets(tx,actor):
 view=working_view(tx,actor);known=' '.join(c['value'].get('content','')for c in view['cards']if c['template']=='knowledge')
 known+=' '+' '.join(t['text']for t in read(tx.state,'dialogue:'+actor,{}).get('turns',[]))
 local=set(c['value']['item']for c in view['cards']if c['template']=='item'and c['value']['quantity'])
 local.update(c['value']['objective']['target']for c in view['cards']if c['template']=='goal'and c['value'].get('objective',{}).get('kind')in('obtain','read'))
 for c in tx.state['cards'].values():
  if c['template']=='item'and c['value']['quantity']and c['value']['location']==location(tx.state,actor)and not read(tx.state,'loc:'+actor,{}).get('at_entrance')and not tx.definition['items'][c['value']['item']].get('hidden'):local.add(c['value']['item'])
 items=[{'id':iid,'name':item['name']}for iid,item in tx.definition['items'].items()if iid in local or item['name']in known]
 from map_runtime import actor_locations
 locations=[{'id':lid,'name':p.get('name',lid)}for lid,p in actor_locations(tx.state,tx.definition,actor).items()]
 return {'obtain':items,'read':[i for i in items if 'read'in tx.definition['items'][i['id']].get('capabilities',{})],
  'visit':locations,'inquire':view['local_people'],'rest':[]}

def validate_goals(goals,definition,actor,allowed=None,state=None):
 if actor not in definition['characters']or not isinstance(goals,list)or len(goals)>3:raise ValueError('Bounded NPC goal list required')
 clean=[];seen=set()
 for goal in goals:
  if not isinstance(goal,dict)or set(goal)-{'id','kind','target','title','probability','priority','deadline_after'}:raise ValueError('Goal proposal cannot write actions, criteria or state')
  identifier(goal['id']);kind=goal['kind']
  if goal['id']in seen or kind not in KINDS:raise ValueError('Duplicate or unknown goal')
  seen.add(goal['id']);title=goal.get('title')
  if not isinstance(title,str)or not title.strip()or len(title)>180:raise ValueError('Goal title must be bounded')
  if state:validate_no_literal_leak(state,actor,title)
  probability=goal.get('probability',1)
  if type(probability)not in(int,float)or not 0<=probability<=1:raise ValueError('Invalid goal probability')
  number(goal.get('priority',30),0,100)
  if 'deadline_after'in goal:number(goal['deadline_after'],1,10080)
  if kind!='rest':
   target=identifier(goal.get('target'))
   valid=set(definition['items'])if kind in('obtain','read')else set(get_locations(definition,state))if kind=='visit'else set(definition['characters'])|{'player'}
   if target not in valid:raise ValueError('Unknown goal target')
   if kind=='read'and 'read'not in definition['items'][target].get('capabilities',{}):raise ValueError('Goal item cannot be read')
   if kind=='inquire'and target==actor:raise ValueError('Cannot inquire of self')
   if allowed is not None and target not in {x['id']for x in allowed[kind]}:raise ValueError('Goal target outside actor knowledge/view')
  elif goal.get('target')is not None:raise ValueError('Rest has no target')
  clean.append(copy.deepcopy(goal))
 return clean

def generate_goal_set(tx,actor,window,gateway):
 """Public replaceable interface. Does not write state; caller validates and stores proposals."""
 if gateway is None:raise ValueError('Model goal generator requires a gateway')
 from world_turn import validated_request
 allowed=allowed_targets(tx,actor)
 answer=validated_request(gateway,'goal-generator:'+actor,GENERATOR,
  {'view':working_view(tx,actor),'window':{k:window[k]for k in('id','start','end')},'allowed_targets':allowed},
  lambda answer:validate_goals(answer.get('goals'),tx.definition,actor,allowed,tx.state),900)
 return validate_goals(answer['goals'],tx.definition,actor,allowed,tx.state)

def shell_goal_set(tx,actor):
 """Small safe fallback, not a universal AI personality scheduler."""
 allowed=allowed_targets(tx,actor);profile=tx.definition['characters'][actor];description=' '.join(str(profile.get(k,''))for k in('personality','description'))
 # An owned/local readable object can motivate reading; no remote hidden inventory is inspected.
 if allowed['read']:
  item=allowed['read'][0];return [{'id':'read-local','kind':'read','target':item['id'],'title':'阅读'+item['name'],'probability':0.75,'priority':25}]
 if allowed['obtain']and any(word in description for word in('书','阅读','收集','寻找')):
  item=allowed['obtain'][0];return [{'id':'find-known','kind':'obtain','target':item['id'],'title':'寻找'+item['name'],'probability':0.7,'priority':30}]
 return [{'id':'quiet-rest','kind':'rest','title':'留些时间休息','probability':0.65,'priority':10}]

def store_card(tx,cid,kind,value,actor,title,outcome='recorded'):
 old=copy.deepcopy(tx.state);put(tx.state,cid,kind,value,[actor],[actor])
 return tx.record({'template':'builtin.'+kind,'effects':[],'title':title,'outcome':outcome,'participants':[actor],'observers':[],'public':{},'rule_id':'world-mode'},old)

def bootstrap(tx,gateway=None):
 """Lazy per-day/window bootstrap. Authored empty lists explicitly suppress fallback."""
 cfg=config(tx.definition);minute=tx.state['clock']['minute'];day=tx.state['clock']['day']
 window=next((w for w in cfg['windows']if w['start']<=minute<w['end']),None)
 if not window:return None
 if window.get('school_days_only'):
  from school_calendar import day_info
  info=day_info(tx.state,tx.definition)
  if info is None or not info['classes']:return None
 for actor in tx.definition['characters']:
  cid=f'goalset:{actor}:{day}:{window["id"]}'
  if read(tx.state,cid)is not None:continue
  source='author';goals=window.get('actors',{}).get(actor)
  if goals is None:
   source='shell'
   if cfg.get('generation')=='model'and gateway:
    try:goals=generate_goal_set(tx,actor,window,gateway);source='model'
    except (ValueError,TypeError,KeyError)as error:
     from card_runtime import diag
     diag(tx,actor,'goal-generation',error);source='shell-fallback'
   goals=shell_goal_set(tx,actor)if goals is None else goals
  # Author goals may intentionally contain distant objectives but do not reveal their solutions.
  goals=validate_goals(goals,tx.definition,actor,state=tx.state)
  store_card(tx,cid,'goal_set',{'owner':actor,'day':day,'window':window['id'],'source':source,'goals':goals,'sampled':False},actor,'人物时段目标集')
 return window

def select_goals(tx,gateway=None):
 window=bootstrap(tx,gateway)
 if not window:return
 cfg=config(tx.definition);day=tx.state['clock']['day']
 for actor in tx.definition['characters']:
  cid=f'goalset:{actor}:{day}:{window["id"]}';value=copy.deepcopy(read(tx.state,cid));
  activity=read(tx.state,'activity:'+actor,{})
  if activity.get('schedule') and activity.get('busy_until',0)>clock_time(tx.state):continue
  # Defer sampling while busy, rather than overwrite or lose existing commitments.
  active=[c for c in tx.state['cards'].values()if c['template']=='goal'and c['value']['owner']==actor and c['value']['status']=='active']
  if len(active)>=cfg.get('max_active',2):continue
  seed=tx.state['rng']['seed'];samples=value.get('samples',[])
  if not value['sampled']:
   for goal in value['goals']:
    roll=int(digest([seed,actor,day,window['id'],goal['id']])[:13],16)/float(16**13)
    samples.append({'id':goal['id'],'roll':roll,'probability':goal.get('probability',1)})
   value.update(sampled=True,samples=samples,activated=[])
   store_card(tx,cid,'goal_set',value,actor,'时段目标抽样')
  eligible=[goal for goal in value['goals']if goal['id']not in value.get('activated',[])and next(s for s in samples if s['id']==goal['id'])['roll']<goal.get('probability',1)
   and not any(g['value'].get('objective')=={k:goal[k]for k in('kind','target')if k in goal}for g in active)]
  if not eligible:continue
  goal=max(eligible,key=lambda g:(g.get('priority',30),-next(x['roll']for x in samples if x['id']==g['id'])))
  if activate_goal(tx,actor,goal,{'kind':'goal_set','card':cid}):
   value.setdefault('activated',[]).append(goal['id']);store_card(tx,cid,'goal_set',value,actor,'目标候选进入活动状态')

def activate_goal(tx,actor,goal,source):
 objective={k:goal[k]for k in('kind','target')if k in goal}
 active=[c for c in tx.state['cards'].values()if c['template']=='goal'and c['value']['owner']==actor and c['value']['status']=='active']
 if any(g['value'].get('objective')==objective for g in active):return None
 if len(active)>=config(tx.definition).get('max_active',2):return None
 cid='goal:wm-'+digest([actor,goal['id'],source])[:24]
 value={'owner':actor,'title':goal['title'],'status':'active','criteria':[],'deadline':clock_time(tx.state)+goal['deadline_after']if goal.get('deadline_after')else None,
  'target':None,'objective':objective,'created_at':clock_time(tx.state),'source':source,'priority':goal.get('priority',30)}
 value['previous_dialogue']=[t['id']for t in read(tx.state,'dialogue:'+actor,{}).get('turns',[])]
 value['previous_read']={cid:c['revision']for cid,c in tx.state['cards'].items()if c['template']=='knowledge'and c['value'].get('source',{}).get('kind')=='read'and actor in c['visibility']}
 store_card(tx,cid,'goal',value,actor,'人物确定目标','applied');return cid

def goal_satisfied(state,value):
 goal=value['objective'];actor=value['owner'];kind=goal['kind'];target=goal.get('target')
 if kind=='visit':return location(state,actor)==target and not read(state,'loc:'+actor,{}).get('transit_to')and not read(state,'loc:'+actor,{}).get('at_entrance')
 if kind=='obtain':return any(c['template']=='item'and c['value']['item']==target and c['value']['owner']==actor and c['value']['quantity']>0 for c in state['cards'].values())
 if kind=='read':return any(c['template']=='knowledge'and c['value']['holder']==actor and c['value'].get('source',{}).get('kind')=='read'and read(state,'item:'+c['value']['source']['target'],{}).get('item')==target and c['revision']>value.get('previous_read',{}).get(c['id'],0)for c in state['cards'].values())
 if kind=='rest':return read(state,'activity:'+actor,{}).get('rest_since',-1)>=value['created_at']and clock_time(state)-read(state,'activity:'+actor,{}).get('rest_since',clock_time(state))>=5
 if kind=='inquire':
  turns=read(state,'dialogue:'+actor,{}).get('turns',[]);asked=False
  for t in turns:
   if t['id']in value.get('previous_dialogue',[]):continue
   if t['speaker']==actor and target in t['addressees']and any(word in t['text']for word in('？','?','请问','哪里','哪儿','怎么','能不能','有没有')):asked=True
   if asked and t['speaker']==target and actor in t['addressees']:return True
  return False
 return False

def reconcile(tx):
 for cid,c in list(tx.state['cards'].items()):
  value=c['value']
  if c['template']=='goal'and value.get('objective')and value['status']=='active'and goal_satisfied(tx.state,value):
   value=copy.deepcopy(value);value.update(status='completed',completed_at=clock_time(tx.state))
   store_card(tx,cid,'goal',value,value['owner'],'人物目标实际达成','applied')
