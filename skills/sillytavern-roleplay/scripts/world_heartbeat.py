"""Story-time boundaries, deterministic probability and bounded background simulation."""
import copy
from event_schema import digest
from event_rules import compile_rules,affected_rules,evaluate
from world_state import apply_one,clock_time,advance_clock,read,location,put,state_hash

class Transaction:
 def __init__(self,state,definition,request_id):
  self.initial=copy.deepcopy(state);self.state=copy.deepcopy(state);self.definition=definition;self.request_id=request_id
  self.records=[];self.changed=set(state['cards'])|{'@clock'};self.compiled=compile_rules(definition);self.rule_count=0
  from runtime_budget import ACTIVE,WorkBudget
  self.budget=ACTIVE.get() or WorkBudget()
 def record(self,record,old):
  eid=digest([self.request_id,len(self.records),record['template'],record.get('effects',[])])[:32]
  if self.definition['config'].get('world_mode') and record.get('template')=='builtin.say':
   from world_memory import remember
   remember(self.state,{**record,'event_id':eid,'story_time':clock_time(self.state)},self.request_id)
   from map_runtime import learn_spoken
   learn_spoken(self.state,self.definition,record,eid)
  for key,c in self.state['cards'].items():
   if c!=old['cards'].get(key):
    self.changed.add(key);c['source_event_ids']=(c.get('source_event_ids',[])+[eid])[-16:]
  self.state['state_revision']+=1
  record.update(event_id=eid,request_id=self.request_id,step_index=len(self.records),story_time=clock_time(self.state),
   definition_hash=self.definition['definition_hash'],before_hash=state_hash(old),after_hash=state_hash(self.state))
  self.records.append(record)
  if self.definition['config'].get('world_mode'):
   from activity_history import observe
   observe(self.state,record)
   from relation_policy import experience,from_record
   from_record(self.state,self.definition,record)
   if record['template'] in ('builtin.transfer','builtin.complete','builtin.read','builtin.visible_activity') and record.get('outcome')=='applied':
    actor=record.get('public',{}).get('actor') or next((e.get('actor') for e in record.get('effects',[]) if e.get('actor')),None)
    if actor:
     for peer in record.get('observers',[]):
      if peer!=actor and peer in {'player',*self.definition['characters']}:experience(self.state,actor,peer,eid,record['template'])
   # Derived history/counters belong to the same record and packet hash.
   for key,c in self.state['cards'].items():
    if c!=old['cards'].get(key):
     self.changed.add(key)
     if eid not in c.get('source_event_ids',[]):c['source_event_ids']=(c.get('source_event_ids',[])+[eid])[-16:]
   record['after_hash']=state_hash(self.state)
  limit=min(2048,max(256,self.definition['config'].get('max_events_per_turn',512)))
  if len(self.records)>limit:raise ValueError('World transaction exceeds event budget; nothing committed')
  return record
 def apply(self,effect,system=False,evidence='',rule_id='player'):
  old=copy.deepcopy(self.state)
  try:record=apply_one(self.state,effect,self.definition,system,evidence)
  except Exception:
   self.state=old;raise
  record.update(rule_id=rule_id,evidence=evidence)
  result=self.record(record,old)
  from world_observations import record_visible
  record_visible(self,result)
  return result
 def failure(self,effect,error,evidence=''):
  old=copy.deepcopy(self.state)
  return self.record({'template':effect.get('template','builtin.noop'),'title':'尝试未完成','outcome':'rejected',
   'effects':[],'attempted_effect':effect,'participants':[effect.get('actor','player')],'observers':[effect.get('actor','player')],
   'public':{'reason':str(error)},'evidence':evidence,'rule_id':'player'},old)
 def snapshot_packet(self):
  state=copy.deepcopy(self.state)
  packet={'version':1,'request_id':self.request_id,'before_hash':state_hash(self.initial),
    'after_hash':state_hash(state),'previous_head':self.initial['journal_head'],'records':copy.deepcopy(self.records),'state_after':state}
  packet['head']=digest(packet);self.state=copy.deepcopy(state);self.state['journal_head']=packet['head']
  return packet

def next_boundary(tx,target):
 now=clock_time(tx.state);points=[target]
 points += [s['at']for s in tx.state['scheduled'].values()if now<s['at']<=target]
 for r in tx.definition['rules']:
  trigger=r.get('trigger',{'type':'state'});kind=trigger['type']
  if kind=='time':
   at=trigger['at'];repeat=trigger.get('repeat')
   if repeat and at<=now:at+=((now-at)//repeat+1)*repeat
   if now<at<=target:points.append(at)
  if kind=='probability':
   window=trigger.get('window',10);at=(now//window+1)*window
   if at<=target:points.append(at)
 for c in tx.state['cards'].values():
  v=c['value'];d=v.get('deadline')if isinstance(v,dict)else None
  if c['template']in('goal','opportunity')and type(d)is int and now<d<=target:points.append(d)
 from schedule_runtime import boundaries
 points.extend(boundaries(tx,target))
 from fixed_events import boundaries as calendar_boundaries
 points.extend(calendar_boundaries(tx,target))
 from place_hours import boundaries as hours_boundaries
 points.extend(hours_boundaries(tx,target))
 from school_calendar import boundaries as school_boundaries
 points.extend(school_boundaries(tx,target))
 return min(points)

def eligible(tx,rule,manual=False):
 s=tx.state;now=clock_time(s);t=rule.get('trigger',{'type':'state'});kind=t['type'];rid=rule['id']
 if kind=='manual'and not manual:return False,None
 if not evaluate(rule,s,tx.definition):return False,None
 if kind=='time':
  at=t['at'];repeat=t.get('repeat')
  if now<at or repeat and (now-at)%repeat:return False,None
  key=str((now-at)//repeat)if repeat else'once'
 elif kind=='probability':
  window=t.get('window',10)
  if now%window:return False,None
  key=str(now//window)
 elif rule.get('repeat_on_change'):
  from event_rules import path_value
  key=digest([path_value(s,'cards/'+p)for p in rule['compiled_reads']])[:20]
 else:key='once'
 marker=rid+':'+key
 if marker in s['fired']:return False,None
 if s['cooldowns'].get(rid,0)>now:return False,None
 if kind=='probability':
  sample=int(digest([s['rng']['seed'],rid,key])[:13],16)/float(16**13)
  s['rng']['samples'][marker]=sample;s['fired'][marker]=now
  if sample>=t['probability']:return False,None
  return True,{'marker':marker,'sample':sample}
 return True,{'marker':marker}

def settle(tx,all_rules=False,hard_only=False):
 for cycle in range(64):
  dirty=tx.changed|{'@clock'}
  if not hard_only:tx.changed=set()
  rules=list(tx.compiled['rules'].values())if all_rules else affected_rules(tx.compiled,dirty)
  progressed=False
  if hard_only:rules=[r for r in rules if r.get('trigger',{}).get('type')=='time'and all(e['template']=='builtin.availability'for e in r['effects'])]
  for rule in sorted(rules,key=lambda r:(-r.get('priority',0),r['id'])):
   before_check=copy.deepcopy(tx.state)
   yes,sample=eligible(tx,rule)
   if tx.state!=before_check:
    tx.record({'template':'builtin.probability_sample','effects':[],'title':'概率条件结算','outcome':'applied'if yes else'quiet',
     'participants':[],'observers':[],'public':{},'rule_id':rule['id']},before_check)
   if not yes:continue
   old=copy.deepcopy(tx.state);count=len(tx.records);old_changed=set(tx.changed)
   try:
    tx.state['fired'][sample['marker']]=clock_time(tx.state)
    tx.state['cooldowns'][rule['id']]=clock_time(tx.state)+rule.get('cooldown',0)
    tx.record({'template':'builtin.rule_activation','effects':[],'title':'规则条件结算','outcome':'applied','participants':[],
     'observers':[],'public':{},'rule_id':rule['id']},old)
    for e in rule['effects']:
     rec=tx.apply(e,True,'剧本条件已满足',rule['id']);rec['title']=rule.get('title',rec['title']);rec['rng_sample']=sample.get('sample')
    progressed=True;tx.rule_count+=1
   except ValueError:
    tx.state=copy.deepcopy(old);tx.records=tx.records[:count];tx.changed=old_changed
    # Unsatisfied effect (occupied resource, unreachable route) remains a candidate, not a fact.
    tx.state['cooldowns'][rule['id']]=clock_time(tx.state)+1
    tx.record({'template':'builtin.rule_deferred','effects':[],'title':'活动条件暂不满足','outcome':'deferred','participants':[],
      'observers':[],'public':{},'rule_id':rule['id']},old)
  if not progressed:return
 raise ValueError('World rule cycle exceeded budget; nothing committed')

def settle_due(tx):
 now=clock_time(tx.state)
 from place_hours import settle as settle_hours
 settle_hours(tx)
 from fixed_events import settle as settle_calendar
 settle_calendar(tx)
 for sid,event in sorted(list(tx.state['scheduled'].items()),key=lambda pair:(pair[1]['at'],pair[0])):
  if event['at']>now:continue
  old=copy.deepcopy(tx.state);del tx.state['scheduled'][sid]
  if event.get('arrival'):
   a=event['arrival'];opened=read(tx.state,'place:'+a['location'],{}).get('open',True)
   put(tx.state,'loc:'+a['actor'],'location',{'location':a['location'],**({}if opened else{'at_entrance':True})},[a['actor']],[a['actor']])
   for cid,c in list(tx.state['cards'].items()):
    if c['template']=='item'and c['value']['owner']==a['actor']and c['value']['quantity']:
     value=copy.deepcopy(c['value']);value['location']=a['location'];put(tx.state,cid,'item',value,[a['actor']],[a['actor']])
   from map_runtime import discover_local
   notices=discover_local(tx.state,tx.definition,a['actor'],{'kind':'arrival','request':tx.request_id,'at':now}) or []
   from world_state import colocated
   from room_presence import observable_arrival
   observers={x for x in [*tx.definition['characters'],'player']if observable_arrival(tx.state,tx.definition,x,a['actor'],a['location'])}
   tx.record({'template':'builtin.arrival','effects':[],'title':a['actor']+'到达'+a['location'],'outcome':'applied',
    'participants':[a['actor']],'observers':sorted(observers),'public':dict(a,entered=opened),'rule_id':'arrival'},old)
   if notices:
    old=copy.deepcopy(tx.state)
    tx.record({'template':'builtin.location_notice','effects':[],'title':'看见入口标识','outcome':'applied',
     'participants':[a['actor']],'observers':[a['actor']],
     'public':{'actor':a['actor'],'text':'入口的标识写着：'+'、'.join(n['name']for n in notices)+'。','sources':notices},'rule_id':'local-sign'},old)
  else:
   tx.record({'template':'builtin.schedule_due','effects':[],'title':'计划到期','outcome':'applied','participants':[],
    'observers':[],'public':{},'rule_id':sid},old)
   for e in event['effects']:tx.apply(e,True,'已安排的活动到期',sid)
 # Calendar participation must see arrivals settled at this same boundary,
 # including actors arriving exactly when an event starts.
 settle_calendar(tx)
 if tx.definition['config'].get('world_mode'):
  # Arrival at the exact deadline is checked before expiry; there is no invented success.
  from goal_sets import reconcile
  reconcile(tx)
 from schedule_runtime import evaluate_due
 evaluate_due(tx,gateway=getattr(tx,'schedule_gateway',None),execute=not getattr(tx,'schedule_gap',False))
 from school_calendar import settle as settle_school
 settle_school(tx)
 for cid,c in list(tx.state['cards'].items()):
  v=c['value'];deadline=v.get('deadline')if isinstance(v,dict)else None
  if c['template']in('goal','opportunity')and type(deadline)is int and now>=deadline and v.get('status')in('offered','accepted','active'):
   old=copy.deepcopy(tx.state);v=copy.deepcopy(v);v['status']='expired';put(tx.state,cid,c['template'],v,c['subjects'],c['visibility'])
   tx.record({'template':'builtin.expiry','effects':[],'title':v['title']+' · 机会结束','outcome':'applied','participants':c['subjects'],
    'observers':c['visibility'],'public':{'title':v['title']},'rule_id':'deadline'},old)
 from world_state import colocated
 for cid,c in list(tx.state['cards'].items()):
  v=c['value']
  if c['template']=='opportunity'and v['status']=='offered'and v['target']not in c['visibility']and colocated(tx.state,v['owner'],v['target']):
   old=copy.deepcopy(tx.state);c['visibility'].append(v['target'])
   tx.record({'template':'builtin.offer_delivery','effects':[],'title':v['title'],'outcome':'applied','participants':c['subjects'],
    'observers':c['visibility'],'public':{'title':v['title']},'rule_id':'meeting'},old)

def advance_until(tx,minutes):
 from event_schema import number
 from runtime_budget import consume
 number(minutes,0,10080);consume(budget=tx.budget)
 target=clock_time(tx.state)+minutes;settle(tx,False,True);settle_due(tx);settle(tx)
 while clock_time(tx.state)<target:
  consume('boundary',tx.budget)
  old=copy.deepcopy(tx.state);boundary=next_boundary(tx,target);advance_clock(tx.state,boundary-clock_time(tx.state))
  tx.record({'template':'builtin.time','effects':[],'title':'时间流逝','outcome':'applied','participants':[],
    'observers':[],'public':{'elapsed':boundary-clock_time(old)},'rule_id':'clock'},old)
  settle(tx,False,True);settle_due(tx);settle(tx)
  if tx.definition['config'].get('world_mode'):
   from goal_planner import macro_due
   macro_due(tx)
  if getattr(tx,'module_store',None)and not getattr(tx,'hook_running',False):
   from world_modules import run_hooks
   tx.hook_running=True
   try:run_hooks(tx,tx.module_store,tx.module_refs);settle(tx,True)
   finally:tx.hook_running=False
 return tx.state

def choose_world_action(tx,actor):
 # Script rules produce legal actions. Open semantic planning is optional, actor scoped.
 return [r for r in tx.records if actor in r.get('participants',[])and r.get('rule_id')!='player']
def choose_presentation(records,player='player',limit=1):
 candidates=[r for r in records if player in r.get('observers',[])and r['template']not in('builtin.time','builtin.schedule')]
 def score(r):return (3*(player in r.get('participants',[]))+2*(r['template']=='builtin.offer')+int(r['outcome']=='rejected'),r['story_time'],r['event_id'])
 return sorted(candidates,key=score,reverse=True)[:limit]
