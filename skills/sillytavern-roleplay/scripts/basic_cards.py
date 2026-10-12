from map_runtime import get_locations
"""Versioned shell vocabulary. Runtime recipes compile to existing capabilities only."""
import copy,re
from event_schema import digest,validate_effect,identifier

VERSION=1
ATOMS={
 'move':'move','observe':'observe','give':'transfer','take':'take','put_down':'put_down',
 'read':'read','eat':'consume','use':'use','say':'say','ask':'say','answer':'say',
 'wait':'wait','rest':'wait','search':'search','agree':'accept','refuse':'decline',
 'conceal':'conceal','complete':'complete'}
ATOMS.update({'knock':'knock','sit':'sit','stand':'stand','gesture':'gesture','write':'write'})
ATOMS.update({'open':'open','close':'close'})
ATOMS.update({'open_item':'open_item','close_item':'close_item','sit_up':'sit_up','lie_down':'lie_down'})
ATOMS['explore']='explore'
ATOMS['buy']='buy'
ALIASES_EXPLORE={'探索':'explore','探索地点':'explore'}
ALIASES={'移动':'move','观察':'observe','给予':'give','拿取':'take','放下':'put_down','阅读':'read',
 '食用':'eat','使用':'use','说话':'say','询问':'ask','回答':'answer','等待':'wait','休息':'rest',
 '搜索':'search','同意':'agree','拒绝':'refuse','隐藏意图':'conceal','完成':'complete'}
ALIASES.update({'敲门':'knock','坐下':'sit','起身':'stand','站起':'stand','示意':'gesture','记录':'write','写下':'write',
 '问候':'say','道谢':'say','道歉':'say','请求':'ask','借阅请求':'ask'})
ALIASES.update({'开门':'open','关门':'close'})
ALIASES.update({'坐起':'sit_up','坐起身':'sit_up','躺下':'lie_down','翻开':'open_item','合上':'close_item'})
ALIASES.update(ALIASES_EXPLORE)
ALIASES['购买']='buy'
FORBIDDEN={'spawn','learn','goal','offer','relation','availability','schedule','cancel','emotion'}

def vocabulary():
 from event_schema import BASE
 return [{'id':k,'version':VERSION,'effect':'builtin.'+v,'required':sorted(BASE[v][0]-{'actor'}),'optional':sorted(BASE[v][1]-{'consent'})}for k,v in ATOMS.items()]

def validate_recipe(recipe):
 if not isinstance(recipe,dict)or set(recipe)-{'id','name','steps','failure_policy'}:raise ValueError('Invalid composite definition')
 identifier(recipe.get('id'))
 if recipe['id'].startswith('builtin.'):raise ValueError('Cannot redefine shell atom')
 steps=recipe.get('steps')
 if not isinstance(steps,list)or not 1<=len(steps)<=8:raise ValueError('Composite must contain 1..8 atomic steps')
 if recipe.get('failure_policy','stop')not in('stop','continue'):raise ValueError('Invalid failure policy')
 for step in steps:
  if not isinstance(step,dict)or set(step)!={'atom','params'}or step['atom']not in ATOMS:raise ValueError('Composite can reference fixed atoms only')
  if not isinstance(step['params'],dict):raise ValueError('Atomic params must be object')
  if set(step['params'])&{'actor','system','consent'}:raise ValueError('Composite cannot supply actor or consent')
  probe={k:('x'if isinstance(v,str)and v.startswith('$')else v)for k,v in step['params'].items()}
  effect={'template':'builtin.'+ATOMS[step['atom']],**probe}
  if ATOMS[step['atom']]!='wait':effect.setdefault('actor','x')
  validate_effect(effect)
 return copy.deepcopy(recipe)

def register_recipe(tx,recipe,source='model'):
 from world_state import put
 recipe=validate_recipe(recipe);body=digest(recipe);cid='recipe:'+recipe['id'];old_card=tx.state['cards'].get(cid)
 if old_card:
  if old_card['value']['digest']!=body:raise ValueError('Registered composite is immutable')
  return old_card['value']
 existing=[c for c in tx.state['cards'].values()if c['template']=='recipe']
 if len(existing)>=32:raise ValueError('Branch recipe budget exhausted')
 old=copy.deepcopy(tx.state);value={'recipe':recipe,'digest':body,'version':VERSION,'source':source}
 put(tx.state,cid,'recipe',value,['player'],['player'])
 tx.record({'template':'builtin.recipe_registration','effects':[],'title':'组合方法登记','outcome':'applied',
  'participants':[],'observers':[],'public':{}},old)
 return value

def expand(action,state,actor):
 """No actor, privileges, code or variable path may be supplied by the recipe."""
 if not isinstance(action,dict)or not isinstance(action.get('type'),str)or not isinstance(action.get('params',{}),dict):raise ValueError('Action requires string type and object params')
 if set(action)-{'type','params','recipe','bindings','evidence'}:raise ValueError('Unexpected atomic action fields')
 if action.get('type')=='compound':
  value=state['cards'].get('recipe:'+action.get('recipe',''),{}).get('value')
  if not value:raise ValueError('Unregistered composite')
  recipe=validate_recipe(value['recipe']);bindings=action.get('bindings',{})
  if not isinstance(bindings,dict)or len(bindings)>16:raise ValueError('Invalid bindings')
  effects=[]
  for step in recipe['steps']:
   params={}
   for k,v in step['params'].items():
    if k in('actor','system','consent'):raise ValueError('Composite cannot supply actor or consent')
    if isinstance(v,str)and v.startswith('$'):
     name=v[1:]
     if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,40}',name)or name not in bindings:raise ValueError('Missing atomic binding')
     v=bindings[name]
    params[k]=v
   effect={'template':'builtin.'+ATOMS[step['atom']],**params}
   if step['atom']not in('wait','rest'):effect['actor']=actor
   effects.append(validate_effect(effect))
  return effects,recipe.get('failure_policy','stop')
 kind=ALIASES.get(action.get('type'),action.get('type'))
 if kind not in ATOMS:raise ValueError('Unknown atom: custom gameplay capability required')
 effect={'template':'builtin.'+ATOMS[kind],**copy.deepcopy(action.get('params',{}))}
 if 'actor'in effect or 'consent'in effect:raise ValueError('Input cannot supply actor/consent')
 if ATOMS[kind]!='wait':effect['actor']=actor
 return [validate_effect(effect)],'stop'

def normalize_action(action,state,definition,actor):
 """Resolve known display labels, never fabricate entities or acquire capabilities."""
 if not isinstance(action,dict):raise ValueError('Action must be object')
 a=copy.deepcopy(action);kind=a.get('type')
 if not isinstance(kind,str):raise ValueError('Action type must be string')
 a['type']=ALIASES.get(kind,kind);params=a.get('params',{})
 evidence=a.get('evidence','')
 # A model's choice of verb never changes the explicitly named object or direction.
 if a['type']=='sit' and re.search(r'坐起(?:身)?',evidence):a['type']='sit_up'
 if a['type'] in ('open','close') and re.search(r'笔记本|文库本|这本书|那本书',evidence) and not re.search(r'开门|关门|推门|门板',evidence):
  from input_grounding import GroundingError
  raise GroundingError('这里是翻开或合上书本，不是开关门；请保持实际物品对象。')
 if a['type']=='observe' and params.get('target') in ('四周','周围','环境','附近','around','surroundings'):
  a['type']='search';params={};a['params']=params
 if not isinstance(params,dict):raise ValueError('Action params must be object')
 from world_state import location
 for field,value in list(params.items()):
  if not isinstance(value,str)or value.startswith('$'):continue
  if field=='target'and a['type']=='give':
   from speech_rules import known_addresses
   matches=[p['id']for p in known_addresses(state,definition,actor)if value in p['addresses']]
   if len(matches)==1:params[field]=matches[0]
  if field=='location':
   from map_runtime import actor_locations
   ids=[k for k,v in actor_locations(state,definition,actor).items()if value in [k,v.get('name'),*v.get('aliases',[])]]
   if len(ids)==1:params[field]=ids[0]
   from map_runtime import enabled as map_enabled
   if map_enabled(definition):
    from map_exploration import resolve_intent
    result=resolve_intent(state,definition,actor,params[field])
    if result['classification']in('known_exact','known_container'):params[field]=result['destination']
    else:
     from input_grounding import GroundingError
     raise GroundingError(result.get('question','目的地有多个对应地点，请说明具体是哪一处。'))
  if field=='target'and a['type']=='search':
   instance=state['cards'].get('item:'+value,{})
   if definition['config'].get('card_refinement')and instance.get('template')=='item':
    params[field]=instance['value']['item'];continue
   # A local search area is not an entity id and does not create a shelf/furniture.
   if value in('书架','四周','周围','附近'):
    params.pop(field,None);continue
   ids=[k for k,v in definition['items'].items()if v.get('name')==value]
   if len(ids)==1:params[field]=ids[0]
  if field in('instance','target')and a['type']in('take','put_down','read','eat','give','use','observe','open_item','close_item','write'):
   ids=[c['id'][5:]for c in state['cards'].values()if c['template']=='item'and c['value']['quantity']and c['value']['location']==location(state,actor)
    and definition['items'][c['value']['item']].get('name')==value and not definition['items'][c['value']['item']].get('hidden')]
   if len(ids)==1:params[field]=ids[0]
  if field=='id'and a['type']in('agree','refuse','complete'):params[field]=value.removeprefix('offer:')
 a['params']=params;return a
