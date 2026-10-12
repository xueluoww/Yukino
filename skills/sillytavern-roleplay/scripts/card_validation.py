"""Validators report flags; the shell makes bounded decisions, never the validator."""
import copy,re
from world_state import read

HIGH_RISK={'transfer','take','consume','use','complete','accept'}
REVIEW='''仅JSON {"flags":[]}。检查当前actor可见的view和拟执行action是否存在人物性格/同意/事实一致性问题。只给标记，不执行、不改变状态、不生成台词，不猜未知秘密。flags每项包含kind(personality/consent/consistency)、severity(warning/block)、evidence(引用view或action中的实际内容)、reason。不能要求玩家必须接受任务，不因拒绝或绕路惩罚。没有实际依据不标记。'''

def soft_review(tx,gateway,actor,effects,view,intent=''):
 if not gateway or not any(e['template'][8:]in HIGH_RISK for e in effects):return {'decision':'pass','flags':[]}
 from world_turn import validated_request
 def valid(answer):
  flags=answer.get('flags')
  if not isinstance(flags,list)or len(flags)>6:raise ValueError('Invalid review flags')
  source=__import__('json').dumps({'view':view,'actions':effects,'intent':intent},ensure_ascii=False)
  for f in flags:
   if not isinstance(f,dict)or f.get('kind')not in('personality','consent','consistency')or f.get('severity')not in('warning','block'):raise ValueError('Invalid flag')
   if not isinstance(f.get('evidence'),str)or not f['evidence']or f['evidence']not in source:raise ValueError('Unsupported soft flag')
 answer=validated_request(gateway,'review:'+actor,REVIEW,{'view':view,'actions':effects,'intent':intent},valid,400)
 flags=answer['flags'];decision='hold'if any(f['severity']=='block'for f in flags)else'pass'
 return {'decision':decision,'flags':copy.deepcopy(flags)}

def verify_prose(tx,actor,text,execution=(),private=False):
 from actor_context import validate_no_literal_leak
 from world_turn import validate_temporal_text
 me=tx.definition['characters'].get(actor,{})
 if actor!='player' and tx.definition['config'].get('world_mode'):
  from activity_history import check_past_claim
  check_past_claim(tx.state,tx.definition,actor,text,getattr(tx,'memory_history',()))
 from world_memory import recall
 memory=recall(tx,actor)
 heard_literals=[n['text']for n in memory['recent']+memory['retrieved']]
 validate_no_literal_leak(tx.state,actor,text,actor!='player'and not private,
  ([me['name']] if me.get('name') else [])+heard_literals);validate_temporal_text(tx.state,tx.definition,actor,text)
 # Registered aliases can be hard checked. General unknown titles use scoped source review.
 for forbidden in tx.definition['config'].get('unregistered_fact_probes',[]):
  if forbidden in text:raise ValueError('Unregistered concrete fact probe')
 allowed=' '.join(c['name']for c in tx.definition['items'].values())+' '+ ' '.join(c['value']['content']for c in tx.state['cards'].values()if c['template']=='knowledge'and actor in c['visibility'])
 for title in re.findall(r'《([^》]{1,80})》',text):
  if title not in allowed:raise ValueError('Concrete title has no scoped source')
 if execution and any(r.get('outcome')in('rejected','held','error')for r in execution):
  if re.search('已经(?:把|拿到|到达|完成)|成功(?:交给|拿到|完成)|递到你手里',text):raise ValueError('Failed action narrated as success')
 return True

def preflight(tx,effects,evidence):
 """Physical dry-run on a copy, not an authoritative commit."""
 from world_state import apply_one
 from world_heartbeat import Transaction,advance_until
 probe=Transaction(tx.state,tx.definition,'preflight')
 for e in effects:
  if e['template']=='builtin.wait':advance_until(probe,e['minutes'])
  else:probe.apply(e,evidence=evidence)
 return True
