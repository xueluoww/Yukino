"""Stable prompt contracts and scoped working views, never merge actor secrets."""
import copy,json
from actor_context import build_actor_view
from basic_cards import vocabulary

class ContextBudgetError(ValueError):
 pass

def bound_payload(payload,budget):
 """Trim derived recall and duplicate knowledge only; never time/permission/actor rules."""
 size=lambda value:len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
 if size(payload)<=budget:return payload
 result=copy.deepcopy(payload);view=result.get('view',{});ledger=result.get('ledger',{})
 # The ledger already contains complete knowledge sources. Keep claim IDs in the view.
 if ledger.get('facts'):
  for c in view.get('cards',[]):
   if c.get('template')=='knowledge'and c['id'] in ledger['facts']:
    c['value']={k:c['value'][k]for k in('topic','holder','disclose')if k in c['value']}
 while size(result)>budget:
  memory=view.get('personal_memory',{});candidates=memory.get('retrieved',[])
  if candidates:
   removed=candidates.pop();ledger.get('facts',{}).pop('memory:'+removed['id'],None);continue
  recent=memory.get('recent',[])
  if len(recent)>2:
   removed=recent.pop(0);ledger.get('facts',{}).pop('memory:'+removed['id'],None);continue
  # No silent deletion of rules or authoritative state. A pathological script must
  # explicitly reduce its working set; retrying the same oversized prompt cannot fix it.
  raise ContextBudgetError('CONTEXT_BUDGET: essential current-scene context exceeds byte budget')
 return result

def stable_contract(instructions):
 return instructions+'\n固定动作合同：'+json.dumps(vocabulary(),ensure_ascii=False,sort_keys=True,separators=(',',':'))

def working_view(tx,actor,recent=()):
 v=build_actor_view(tx.state,tx.definition,actor,tx.records,recent)
 # No source history snapshots, hashed revisions, full event logs or registered recipes in prose context.
 v.pop('state_revision',None);v.pop('observations',None)
 cards=[]
 for c in v['cards']:
  if c['template']not in('knowledge','location','relation','goal','item','emotion','plan','intent'):continue
  cards.append({k:copy.deepcopy(c[k])for k in('id','template','value')})
 knowledge=[c for c in cards if c['template']=='knowledge'];other=[c for c in cards if c['template']!='knowledge']
 # Keep name/facts/active plans; old raw heard passages can be bounded independently of authoritative cards.
 stable=[c for c in knowledge if not c['value'].get('topic','').startswith('heard-')]
 heard=[c for c in knowledge if c['value'].get('topic','').startswith('heard-')][-6:]
 v['cards']=other+stable+heard
 if tx.definition['config'].get('world_mode'):
  from school_calendar import view as school_view,day_info
  info=day_info(tx.state,tx.definition)
  if info is not None:v['school_day']=info
  if actor=='player':v['school_timetable']=school_view(tx.state,tx.definition)
  from world_memory import recall
  query='\n'.join(r.get('text','') for r in recent if actor in r.get('audience',[]) or r.get('actor')==actor)
  if not query:
   from world_state import read
   query='\n'.join(n['text'] for n in read(tx.state,'dialogue:'+actor,{}).get('turns',[])[-2:])
  v['personal_memory']=recall(tx,actor,query)
  if __import__('re').search(r'昨天|这几天|最近|之前|上次|做了什么|去过',query):
   from activity_history import view as history_view
   v['personal_activity_history']=history_view(tx.state,tx.definition,actor,getattr(tx,'memory_history',()))
  v['execution_results']=[{'index':r['index'],'type':r['type'],'results':[{k:val for k,val in x.items() if k!='observers'} for x in r['results'] if actor in x.get('observers',[])]}for r in getattr(tx,'execution_results',[])[-4:] if any(actor in x.get('observers',[]) for x in r['results'])]
 return v
