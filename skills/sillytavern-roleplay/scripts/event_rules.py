"""Typed condition evaluator and shell rule dependency index; no eval or story-specific code."""
import copy
from world_state import read,location,clock_time

def path_value(state,path):
 if path.startswith('cards/'):
  bits=path.split('/',2);card=state['cards'].get(bits[1]);value=card.get('value') if card else None
  for bit in bits[2].split('/')if len(bits)>2 else []:value=value.get(bit)if isinstance(value,dict)else None
  return value
 value=state
 for bit in path.split('/'):
  if not isinstance(value,dict):return None
  value=value.get(bit)
 return value

def evaluate_condition(c,state,definition=None):
 op,args=next(iter(c.items()))
 if op=='all':return all(evaluate_condition(a,state,definition)for a in args)
 if op=='any':return any(evaluate_condition(a,state,definition)for a in args)
 if op=='not':return not evaluate_condition(args,state,definition)
 if op=='exists':return path_value(state,args)is not None
 if op=='known_by':
  actor,topic=args;return read(state,'know:'+actor+':'+topic)is not None
 if op=='located_at':return location(state,args[0])==args[1]
 if op=='within_region':
  from map_runtime import enabled,in_region
  return bool(definition and enabled(definition) and in_region(definition,state,location(state,args[0]),args[1]))
 if op=='goal_status':return read(state,'goal:'+args[0],{}).get('status')==args[1]
 if op=='due':return clock_time(state)>=args
 if op=='module_result':return path_value(state,'module_states/'+args[0]+'/'+args[1])==args[2]
 left=path_value(state,args[0]);right=args[1]
 if op=='eq':return left==right
 if op=='ne':return left!=right
 if left is None:return False
 if op=='lt':return left<right
 if op=='lte':return left<=right
 if op=='gt':return left>right
 if op=='gte':return left>=right
 raise ValueError('Unknown condition')

def dependencies(c):
 op,args=next(iter(c.items()))
 if op in ('all','any'):return set().union(*(dependencies(a)for a in args))
 if op=='not':return dependencies(args)
 if op in ('eq','ne','lt','lte','gt','gte'):return {args[0].split('/')[1]if args[0].startswith('cards/')else'@'+args[0].split('/')[0]}
 if op=='exists':return {args.split('/')[1]if args.startswith('cards/')else'@'+args.split('/')[0]}
 if op=='known_by':return {'know:'+args[0]+':'+args[1]}
 if op in('located_at','within_region'):return {'loc:'+args[0]}
 if op=='goal_status':return {'goal:'+args[0]}
 return {'@clock'if op=='due'else'@module_states'}

def compile_rules(definition):
 index={};rules={}
 for rule in definition['rules']:
  rule=copy.deepcopy(rule);deps=dependencies(rule.get('conditions',{'all':[]}))|set(rule.get('reads',[]))
  for effect in rule['effects']:
   if effect['template']in('builtin.move','builtin.transfer','builtin.observe','builtin.say','builtin.offer'):
    if effect.get('actor'):deps.add('loc:'+effect['actor'])
    if effect.get('target'):deps.add('loc:'+effect['target'])
    if effect.get('instance'):deps.add('item:'+effect['instance'])
  if rule.get('trigger',{}).get('type')in('time','probability'):deps.add('@clock')
  if not deps:deps={'*'}
  rule['compiled_reads']=sorted(deps);rules[rule['id']]=rule
  for d in deps:index.setdefault(d,set()).add(rule['id'])
 return {'rules':rules,'index':index}
def affected_rules(compiled,changed):
 ids=set(compiled['index'].get('*',set()))
 for key in changed:ids|=compiled['index'].get(key,set())
 return [compiled['rules'][key]for key in sorted(ids)]
def evaluate(rule,state,definition=None):return evaluate_condition(rule.get('conditions',{'all':[]}),state,definition)
def validate_effects(rule,definition):
 from event_schema import validate_effect
 return [validate_effect(e)for e in rule['effects']]
