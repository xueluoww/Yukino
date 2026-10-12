"""Shell-owned basic event contract. Script definitions contain references, not implementations."""
import copy, hashlib, json, re

VERSION=1
BASE={
 'move':({'actor','location'},{'minutes'}),'wait':({'minutes'},set()),
 'say':({'actor','text'},{'audience','whisper','claims'}),
 'observe':({'actor','target'},{'sense'}),'learn':({'actor','topic','content','source'},{'belief','truth','disclose','source_event'}),
 'goal':({'actor','id','title'},{'status','deadline','criteria','target'}),
 'offer':({'id','title','actor'},{'target','deadline','criteria','methods'}),
 'accept':({'id','actor'},set()),'decline':({'id','actor'},set()),'complete':({'id','actor'},{'method'}),
 'spawn':({'item','instance','owner','location','quantity'},set()),
 'transfer':({'instance','actor','target'},{'quantity','consent'}),
 'relation':({'actor','target'},{'affection','trust','familiarity','reason','identity','consent'}),
 'emotion':({'actor','name'},{'intensity','reason'}),
 'availability':({'location','open'},set()),
 'schedule':({'id','at','effects'},set()),'cancel':({'id'},set()),'noop':(set(),{'title'})}
BASE.update({'take':({'actor','instance'},{'quantity'}),'put_down':({'actor','instance'},set()),
 'read':({'actor','instance'},set()),'consume':({'actor','instance'},{'quantity','portion'}),
 'use':({'actor','instance','target'},set()),'search':({'actor'},{'target'}),'conceal':({'actor','text'},set())})
BASE.update({'knock':({'actor','location'},set()),'sit':({'actor'},set()),'stand':({'actor'},set()),
 'gesture':({'actor','text'},set()),'write':({'actor','instance','text'},set())})
BASE.update({'open':({'actor','id'},set()),'close':({'actor','id'},set())})
BASE.update({'open_item':({'actor','instance'},set()),'close_item':({'actor','instance'},set()),
 'sit_up':({'actor'},set()),'lie_down':({'actor'},set())})
BASE['explore']=({'actor','scope'},set())
BASE['buy']=({'actor','item'},{'quantity'})

def digest(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def identifier(value):
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,120}',value):raise ValueError('Invalid stable event/entity id')
 return value
def number(value,lo=0,hi=10080):
 if type(value)is not int or not lo<=value<=hi:raise ValueError('Integer outside contract')
 return value
def list_basic_templates():return [{'id':'builtin.'+k,'version':VERSION,'required':sorted(v[0]),'optional':sorted(v[1])} for k,v in BASE.items()]
def resolve_basic_template(name):
 if not isinstance(name,str) or not name.startswith('builtin.') or name[8:] not in BASE:raise ValueError('Unknown shell event interface: '+str(name))
 return BASE[name[8:]]
def validate_effect(effect):
 if not isinstance(effect,dict):raise ValueError('Effect must be an object')
 required,optional=resolve_basic_template(effect.get('template'))
 if set(effect)-{'template'}-required-optional or not required<=set(effect):raise ValueError('Event parameters do not match basic interface')
 for k in ('actor','target','location','id','instance','item','scope'):
  if k in effect:identifier(effect[k])
 if 'minutes' in effect:number(effect['minutes'])
 if 'quantity' in effect:number(effect['quantity'],1,999)
 if 'portion' in effect and effect['portion'] not in ('small','all'):raise ValueError('Invalid consumption portion')
 if effect.get('portion')=='small' and effect.get('quantity',1)!=1:raise ValueError('A small portion acts on one held unit')
 if 'at' in effect:number(effect['at'],0,52560000)
 if 'open' in effect and type(effect['open'])is not bool:raise ValueError('Availability requires boolean')
 if 'audience' in effect and (not isinstance(effect['audience'],list) or len(effect['audience'])>30):raise ValueError('Audience must be bounded ids')
 for recipient in effect.get('audience',[]):identifier(recipient)
 if 'text'in effect and(not isinstance(effect['text'],str)or not effect['text'].strip()or len(effect['text'])>3000):raise ValueError('Text must be a nonempty bounded string')
 if 'effects' in effect:
  if not isinstance(effect['effects'],list) or len(effect['effects'])>32:raise ValueError('Scheduled effects too large')
  for e in effect['effects']:validate_effect(e)
 return copy.deepcopy(effect)

OPS={'all','any','not','eq','ne','lt','lte','gt','gte','exists','known_by','located_at','within_region','goal_status','due','module_result'}
def validate_condition(c,depth=0):
 if not isinstance(c,dict) or len(c)!=1 or depth>12:raise ValueError('Invalid condition expression')
 op,args=next(iter(c.items()))
 if op not in OPS:raise ValueError('Unsupported condition operator')
 if op in ('all','any'):
  if not isinstance(args,list) or len(args)>40:raise ValueError('Conditions too large')
  for a in args:validate_condition(a,depth+1)
 elif op=='not':validate_condition(args,depth+1)
 elif op in {'eq','ne','lt','lte','gt','gte'}:
  if not isinstance(args,list) or len(args)!=2:raise ValueError('Comparison takes path and value')
  if not isinstance(args[0],str) or '__' in args[0]:raise ValueError('Invalid state path')
 elif op=='due':number(args,0,52560000)
 elif op in('known_by','located_at','within_region','goal_status'):
  if not isinstance(args,list)or len(args)!=2 or not all(isinstance(x,str)and x for x in args):raise ValueError('Condition needs two declared names')
 elif op=='module_result':
  if not isinstance(args,list)or len(args)!=3:raise ValueError('Module condition needs module, field and value')
 elif op=='exists':
  if not isinstance(args,str)or '__'in args:raise ValueError('Invalid state path')

def validate_definition(world,setting_sets):
 config=world.get('event_system')
 if config is None:return None
 if not isinstance(config,dict) or config.get('version')!=VERSION:raise ValueError('Unsupported event system version')
 if config.get('builtin_version',VERSION)!=VERSION:raise ValueError('Unavailable shell event interface version')
 if 'card_language'in config and type(config['card_language'])is not bool:raise ValueError('Experimental card language switch must be boolean')
 if 'card_refinement'in config and type(config['card_refinement'])is not bool:raise ValueError('Card refinement switch must be boolean')
 locations=config.get('locations',{})
 if not locations:raise ValueError('Event world needs declared locations')
 for lid,l in locations.items():
  identifier(lid)
  if 'encounter_scope'in l and l['encounter_scope']not in('room','area'):raise ValueError('Location encounter_scope must be room or area')
  for dest,minutes in l.get('links',{}).items():
   if dest not in locations:raise ValueError('Missing linked location')
   number(minutes,0,1440)
 cards=[copy.deepcopy(c) for s in setting_sets for c in s.get('cards',[])]
 ids=[identifier(c['id']) for c in cards]
 if len(ids)!=len(set(ids)):raise ValueError('Duplicate setting id')
 items={c['id']:c for c in cards if c.get('kind')=='item'}
 from item_rules import validate_item
 for item in items.values():validate_item(item)
 rules=[]
 for card in cards:
  if card.get('kind')!='event' or not card.get('event'):continue
  rule=copy.deepcopy(card['event']);rule['id']=card['id'];rule.setdefault('title',card.get('name',card['id']))
  if rule['id'].startswith('builtin.'):raise ValueError('Scripts cannot redefine shell interfaces')
  if rule.get('version',VERSION)!=VERSION:raise ValueError('Unsupported event card version')
  validate_condition(rule.get('conditions',{'all':[]}))
  effects=rule.get('effects',[])
  if not isinstance(effects,list) or not effects or len(effects)>32:raise ValueError('Rule needs bounded effects')
  for effect in effects:validate_effect(effect)
  trigger=rule.get('trigger',{'type':'state'})
  if trigger.get('type')not in {'state','time','probability','manual'}:raise ValueError('Invalid trigger')
  if trigger.get('type')=='probability':
   if type(trigger.get('probability'))not in (float,int) or not 0<=trigger['probability']<=1:raise ValueError('Probability outside [0,1]')
   number(trigger.get('window',10),1,1440)
  if trigger.get('type')=='time':number(trigger.get('at'),0,52560000)
  if trigger.get('repeat')is not None:number(trigger['repeat'],1,52560000)
  rules.append(rule)
 result={'version':VERSION,'builtin_version':VERSION,'config':copy.deepcopy(config),'rules':rules,'items':items,
         'characters':{c['id']:c for c in cards if c.get('kind')=='character'},'definition_hash':''}
 result['dated_facts']=[c for c in cards if c.get('temporal')and c.get('kind')!='character']
 actors=set(result['characters'])|{'player'}
 instances=set()
 def collect(e):
  if e['template']=='builtin.spawn':instances.add(e['instance'])
  for sub in e.get('effects',[]):collect(sub)
 for e in config.get('initial',[]):collect(e)
 for rule in rules:
  for e in rule['effects']:collect(e)
 for door_id,door in config.get('doors',{}).items():
  identifier(door_id);identifier(door['lock_id'])
  if door['location']not in locations or door['destination']not in locations[door['location']].get('links',{}):raise ValueError('Door must bind a declared adjacent route')
  if type(door.get('locked',True))is not bool:raise ValueError('Door lock must be boolean')
 for offer_id,offer in config.get('commerce',{}).items():
  identifier(offer_id);identifier(offer['currency']);number(offer['price'],1,999)
  if offer['seller']not in actors or offer['location']not in locations or offer['instance']not in instances:raise ValueError('Trade offer must bind declared seller, location and stock')
 def check(e):
  if e['template'] in ('builtin.open','builtin.close') and e['id'] not in config.get('doors',{}):raise ValueError('Missing declared door')
  if 'actor'in e and e['actor']not in actors:raise ValueError('Missing effect actor: '+e['actor'])
  if 'owner'in e and e['owner']not in actors|set(locations):raise ValueError('Missing item owner')
  if 'target'in e:
   allowed=actors|instances if e['template']=='builtin.observe'else set(config.get('doors',{}))|set(config.get('commerce',{}))if e['template']=='builtin.use'else actors
   if e['target']not in allowed:raise ValueError('Missing effect target: '+e['target'])
  if 'location'in e and e['location']not in locations:raise ValueError('Missing effect location')
  if 'item'in e and e['item']not in items:raise ValueError('Missing item setting card')
  for sub in e.get('effects',[]):check(sub)
 for rule in rules:
  for e in rule['effects']:check(e)
 for e in config.get('initial',[]):validate_effect(e);check(e)
 for aid,loc in config.get('actor_locations',{}).items():
  if aid not in actors or loc not in locations:raise ValueError('Invalid initial actor position')
 from map_schema import validate_map
 from daily_life import validate_config
 validate_config(config,result)
 from place_hours import validate as validate_hours
 validate_hours(config)
 from relation_policy import validate_policy
 if config.get('relation_policy') is not None:validate_policy(config['relation_policy'])
 from fixed_events import validate as validate_calendar
 validate_calendar(config.get('fixed_events',[]),result)
 from school_calendar import validate as validate_school
 validate_school(config,result)
 features=config.get('features',[])
 if not isinstance(features,list)or len(features)!=len(set(features))or set(features)-{'map_v1','exploration_v1','npc_schedule_v1'}:raise ValueError('Invalid optional world features')
 if config.get('map') is not None:validate_map(config['map'],actors=actors)
 if config.get('schedules') is not None:
  from npc_schedule import validate_schedule
  validate_schedule(config['schedules'],result)
 if config.get('world_mode'):
  from goal_sets import config as validate_goal_sets
  validate_goal_sets(result)
 result['definition_hash']=digest({k:v for k,v in result.items()if k!='definition_hash'})
 return result

def validate_state(state):
 if state.get('schema_version')!=VERSION or state.get('mode')!='event-v1':raise ValueError('Invalid world state mode')
 number(state['clock']['minute'],0,1439);number(state['clock']['day'],1,36500)
 for cid,card in state['cards'].items():
  identifier(cid)
  if card['template']=='item':number(card['value']['quantity'],0,999)
  if card['template']=='relation':
   for k in ('affection','trust','familiarity'):number(card['value'][k],0,100)
 return True
def validate_record(record):
 for field in ('event_id','request_id','step_index','story_time','template','before_hash','after_hash','effects','observers'):
  if field not in record:raise ValueError('Incomplete event record')
 return True
def normalize_legacy_definition(card):return {'id':card['id'],'text':card.get('description',''),'executable':False}
