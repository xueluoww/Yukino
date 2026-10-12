from map_runtime import get_locations
"""Local opportunities and causal attempts, not a forced quest walkthrough."""
import copy,json
from event_schema import digest
from world_state import location,colocated,read,put,clock_time
from actor_context import build_actor_view

def active_goals(state,actor):return sorted([c for c in state['cards'].values()if c['template']=='goal'and c['value']['owner']==actor and c['value']['status']=='active'],key=lambda c:-c['value'].get('priority',30))

def scope_key(view):
 relevant=[{'id':c['id'],'value':c['value']}for c in view['cards']if c['template']in('knowledge','item','location','goal','availability','door')]
 # A new reply can justify a clarification; own rewritten questions cannot reopen a method.
 heard=[c['value']for c in view['cards']if c['template']=='observation'and c['value'].get('actor')!=view['actor_id']and view['actor_id']in c['value'].get('audience',[])][-3:]
 return digest([view['location'],[p['id']for p in view['local_people']],relevant,view['local_rules'],heard])

def signature(action):
 a=copy.deepcopy(action);params=a.get('params',{})
 # Semantic request identity is independent of wording.
 if a.get('type')in('ask','say','answer'):
  a['type']='say';params.pop('text',None);params.pop('claims',None)
 if a.get('type')=='move':params.pop('minutes',None)
 return digest(a)

def action_guard(state,action):
 kind=action.get('type');p=action.get('params',{});actor=action.get('_actor')
 if kind=='move':return digest([read(state,'loc:'+actor,{}),read(state,'place:'+p.get('location',''),{}),
  [c['value']for c in state['cards'].values()if c['template']=='door'],read(state,'vital:'+actor,{})])
 if kind in('observe','take','give','read','eat','use'):
  instance=p.get('instance',p.get('target',''));return digest([read(state,'loc:'+actor,{}),read(state,'item:'+instance,{}),
   read(state,'know:'+actor+':item-'+instance,{})])
 if kind in('ask','say','answer'):return digest([read(state,'loc:'+actor,{}),sorted(p.get('audience',[])),
  [read(state,'rel:'+a+':'+actor,{})for a in p.get('audience',[])]])
 return None

def add_feedback(tx,actor,goal_id,action,outcome,scope,reason='',new_topics=(),guard=None,reply_status=None):
 cid='goalwork:'+goal_id;old=copy.deepcopy(tx.state);v=copy.deepcopy(read(tx.state,cid,{'owner':actor,'goal_id':goal_id,'attempts':[]}))
 if v['owner']!=actor:raise ValueError('Goal feedback owner mismatch')
 v['attempts']=(v['attempts']+[{'signature':signature(action),'scope':scope,'guard':guard,'action':copy.deepcopy(action),
  'outcome':outcome,'reply_status':reply_status,'reason':reason,'new_topics':list(new_topics),'at':clock_time(tx.state)}])[-24:]
 v['status']=reply_status if reply_status in('system_error','needs_clarification','refused')else'progress'if new_topics or outcome=='applied'else'blocked'if outcome=='rejected'else'quiet'
 put(tx.state,cid,'goal_feedback',v,[actor],[actor])
 tx.record({'template':'builtin.goal_feedback','effects':[],'title':'目标行动反馈','outcome':'recorded','participants':[actor],
  'observers':[actor],'public':{},'rule_id':'goal-feedback'},old)

def blocks_retry(attempt,action,scope,guard,refined=False):
 if attempt['signature']!=signature(action):return False
 if refined:
  if attempt['outcome']=='system_error'or attempt.get('reply_status')=='system_error':return False
  if attempt.get('reply_status')=='refused':return guard is not None and attempt.get('guard')==guard
  if action.get('type')in('ask','say','answer'):return attempt['scope']==scope
 elif action.get('type')in('ask','say','answer'):return attempt['scope']==scope
 return attempt['scope']==scope or guard is not None and attempt.get('guard')==guard

def planning_view(tx,actor):
 view=build_actor_view(tx.state,tx.definition,actor,tx.records);scope=scope_key(view);goals=active_goals(tx.state,actor)
 recent=[c['value']for c in view['cards']if c['template']=='goal_feedback']
 candidates=[]
 def offer(action,why):
  guard=action_guard(tx.state,{**action,'_actor':actor})
  blocked=any(blocks_retry(a,action,scope,guard,tx.definition['config'].get('card_refinement',False))for f in recent for a in f['attempts'])
  if not blocked and not any(signature(c['action'])==signature(action)for c in candidates):
   candidates.append({'id':str(len(candidates)),'action':action,'reason':why})
 if not goals:return view,[],scope
 goaltext=' '.join(g['value']['title']for g in goals)
 objectives=[g['value'].get('objective',{})for g in goals]
 known=[c['value']['content']for c in view['cards']if c['template']=='knowledge'and c['value'].get('belief')in('observed','reported','corrected')]
 here=location(tx.state,actor)
 for c in tx.state['cards'].values():
  if c['template']!='item'or not c['value']['quantity']or c['value']['location']!=here:continue
  if tx.definition['config'].get('world_mode')and read(tx.state,'loc:'+actor,{}).get('at_entrance')and c['value']['owner']!=actor:continue
  item=tx.definition['items'][c['value']['item']]
  if item.get('hidden'):continue
  # Only public local appearances, never remote inventory.
  if item['name']in goaltext or c['value']['item']in goaltext or any(g.get('target')==c['value']['item']for g in objectives):
   offer({'type':'observe','params':{'target':c['id'][5:]}},'眼前有目标相关物品，可先确认')
   if c['value']['owner']==here:offer({'type':'take','params':{'instance':c['id'][5:]}},'目标物品为当地可拿取物品')
   if c['value']['owner']==actor and 'read'in item.get('capabilities',{})and any(g.get('kind')=='read'and g.get('target')==c['value']['item']for g in objectives):offer({'type':'read','params':{'instance':c['id'][5:]}},'本人持有目标读物，可以阅读')
 for goal in objectives:
  if goal.get('kind')=='rest':offer({'type':'rest','params':{'minutes':5}},'可以自行休息；时间与其他人物活动并行')
  if goal.get('kind')=='visit':
   # Declared public routes can support a known destination; never use remote item positions.
   queue=[(here,[])];seen={here}
   while queue:
    lid,path=queue.pop(0)
    if lid==goal.get('target'):
     if path:offer({'type':'move','params':{'location':path[0]}},'公共路径通往本人想去的地点')
     break
    for nxt in get_locations(tx.definition,tx.state).get(lid,{}).get('links',{}):
     if nxt not in seen and not get_locations(tx.definition,tx.state)[nxt].get('secret'):seen.add(nxt);queue.append((nxt,path+[nxt]))
 for lid in get_locations(tx.definition,tx.state).get(here,{}).get('links',{}):
  name=get_locations(tx.definition,tx.state)[lid].get('name',lid)
  if not get_locations(tx.definition,tx.state)[lid].get('secret')and any(name in k or lid in k for k in known):
   offer({'type':'move','params':{'location':lid}},'本人已有线索指向相邻地点；仍须物理校验')
 # Provide inquiry opportunity, not a prewritten dialogue or guaranteed clue.
 for peer in view['local_people']:
  if peer['id']!='player':offer({'type':'ask','params':{'audience':[peer['id']]}},'可向眼前人物询问目标线索，答复不保证成功')
 view['goal_feedback']=recent;view['opportunities']=candidates;view['scope_key']=scope
 return view,candidates,scope
