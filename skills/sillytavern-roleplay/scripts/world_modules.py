"""Script API2 hooks and a conservative API1 effect bridge."""
import copy
from world_state import read,put,clock_time,location
from event_rules import evaluate_condition

def module_context(tx,module):
 reads=module.get('event_reads',[])
 if not isinstance(reads,list)or len(reads)>100:raise ValueError('Invalid module event reads')
 return {'story_time':clock_time(tx.state),'clock':copy.deepcopy(tx.state['clock']),
  'cards':{cid:copy.deepcopy(tx.state['cards'][cid])for cid in reads if cid in tx.state['cards']},
  'turn_id':tx.request_id,'basic_interfaces_version':1}

def run_hooks(tx,store,refs,mode='world_evaluate'):
 for ref in refs:
  from runtime_budget import consume
  consume(budget=tx.budget)
  module=store.load(ref)
  if module.get('api_version')!=2:continue
  entry=tx.state['module_states'].get(ref['id'],{'version':ref['version'],'sha256':ref['sha256'],'state':{}})
  if entry['sha256']!=ref['sha256']:raise ValueError('Frozen module version mismatch')
  context=module_context(tx,module)
  from runtime_budget import ACTIVE
  # ModuleStore counts calls through ACTIVE in the browser; explicit transactions count here too.
  if ACTIVE.get() is None:consume('module',tx.budget)
  if mode=='world_initialize':reply=store.call(ref,mode,entry['state'],context)
  else:
   candidate=store.call(ref,'world_evaluate',entry['state'],context)
   proposals=candidate.get('proposals',[])
   if not isinstance(proposals,list)or len(proposals)>16:raise ValueError('Too many module world proposals')
   if not proposals:continue
   if ACTIVE.get() is None:consume('module',tx.budget)
   reply=store.call(ref,'world_apply',entry['state'],context,{'proposals':proposals})
  old=copy.deepcopy(tx.state)
  tx.state['module_states'][ref['id']]={**entry,'state':reply['state']}
  tx.record({'template':'builtin.module','effects':[],'title':module['name']+' · 玩法结算','outcome':'applied',
   'participants':[],'observers':[],'public':{},'rule_id':'module:'+ref['id']},old)
  for effect in reply.get('effects',[]):
   if effect['type']=='events':tx.apply(effect['event'],True,'玩法模块已验证','module:'+ref['id'])
   else:apply_legacy_effect(tx,effect)

def apply_legacy_effect(tx,effect,bindings=None):
 bindings=bindings or {};actors={v:k for k,v in bindings.items()};kind=effect['type']
 if kind=='time':
  from event_schema import number
  number(effect.get('minutes'),0,10080)
  if effect.get('date')or effect.get('minute')is not None:raise ValueError('Module cannot overwrite canonical story clock')
  from world_heartbeat import advance_until
  advance_until(tx,effect['minutes']);return
 if kind=='relations':
  actor=actors.get(effect['actor_id'],effect['actor_id'])
  event={'template':'builtin.relation','actor':actor,'target':'player','trust':effect.get('trust',0),'familiarity':effect.get('familiarity',0),'reason':effect.get('reason','')}
  if effect.get('identity'):event.update(identity=effect['identity'],consent=effect.get('mutual_consent',False))
  tx.apply(event,True,effect.get('reason',''));return
 if kind=='items':
  # API1 cannot invent an unregistered special object. Authors must declare it.
  cid='item:'+effect['id'];value=read(tx.state,cid)
  if effect.get('delta',0)>0:
   if value:raise ValueError('API1 item increase needs explicit checked spawn/transfer through API2')
   tx.apply({'template':'builtin.spawn','instance':effect['id'],'item':effect['id'],'owner':actors.get(effect['owner'],effect['owner']),
    'location':effect.get('location')or location(tx.state,'player'),'quantity':effect['delta']},True,effect['reason']);return
  if not value or value['owner']!=actors.get(effect['owner'],effect['owner'])or value['quantity']+effect['delta']<0:raise ValueError('API1 item debit violates ownership')
  old=copy.deepcopy(tx.state);v=copy.deepcopy(value);v['quantity']+=effect['delta'];put(tx.state,cid,'item',v,[v['owner']],[v['owner']])
  tx.record({'template':'builtin.item_consumed','effects':[],'title':'物品使用','outcome':'applied','participants':[v['owner']],
   'observers':[v['owner']],'public':{'item':v['item'],'quantity':-effect['delta']},'rule_id':'legacy-module'},old);return
 if kind=='threads':
  status={'open':'offered','active':'accepted','resolved':'resolved','cancelled':'declined'}[effect['status']]
  old=copy.deepcopy(tx.state);put(tx.state,'module-task:'+effect['id'],'module_task',{'title':effect['title'],'status':status,'note':effect.get('note','')},['player'],['player'])
  tx.record({'template':'builtin.module_task','effects':[],'title':effect['title'],'outcome':'applied','participants':['player'],
   'observers':['player'],'public':{'status':status},'rule_id':'legacy-module'},old);return
 raise ValueError('Unsupported API1 capability in event mode')
