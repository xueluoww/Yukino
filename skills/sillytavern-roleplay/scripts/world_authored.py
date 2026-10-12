"""Deterministic goal checks; no quotas or model-certified success."""
import copy
from event_rules import evaluate_condition
from event_schema import validate_condition
from world_state import clock_time

def settle_authored_free(tx,progress,window):
 progress=copy.deepcopy(progress);progress['free_turns']=progress.get('free_turns',0)+1;progress['frame_cursor']=0
 progress['free_minutes']=progress.get('free_minutes',0)+clock_time(tx.state)-clock_time(tx.initial)
 for item in window.get('goal',{}).get('criteria',[]):
  condition=item.get('event_condition')
  if condition:
   validate_condition(condition)
   if evaluate_condition(condition,tx.state):progress.setdefault('goal_evidence',{}).setdefault(item['id'],{'turn_id':tx.request_id,'event_ids':[r['event_id']for r in tx.records],
    'input_evidence':'结构化行动与状态','scene_evidence':'程序校验完成条件成立'})
   else:progress.setdefault('goal_evidence',{}).pop(item['id'],None)
 old=copy.deepcopy(tx.state);tx.state['authored']={k:copy.deepcopy(v)for k,v in progress.items()if k not in('frame_cursor','free_turns')}
 tx.record({'template':'builtin.authored_progress','effects':[],'title':'主线目标进度','outcome':'applied','participants':['player'],
  'observers':['player'],'public':{'completed_criteria':list(progress.get('goal_evidence',{}))},'rule_id':'authored'},old)
 return progress
