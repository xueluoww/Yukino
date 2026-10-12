"""Explicit conservative upgrade; old archives are never rewritten or guessed."""
import copy
from event_schema import validate_definition,digest
from world_state import initialize,put

def inspect_legacy(session):
 return {'session_id':session['id'],'mode':'event-v1'if session.get('facts',{}).get('browser_world_state')else'legacy',
  'has_time':bool(session.get('facts',{}).get('browser_engine',{}).get('calendar')),
  'knowledge_records':sum(len(v)for v in session.get('facts',{}).get('browser_actor_knowledge',{}).values()),
  'history_reconstructed':False}
def plan_upgrade(session,definition):
 return {'source_session':session['id'],'definition_hash':definition['definition_hash'],'new_branch_required':True,
  'warnings':['过去未记录的后台历史不会补造','未验证来源的知识不继承'],'eligible':bool(definition)}
def upgrade_fork(session,definition,new_id):
 result=copy.deepcopy(session);old=session.get('facts',{});world=session.get('world_snapshot',old.get('browser_world_snapshot',{}))
 state=initialize(definition,world)
 if old.get('browser_engine',{}).get('calendar'):
  for key in ('date','day','minute'):
   if key in old['browser_engine']['calendar']:state['clock'][key]=old['browser_engine']['calendar'][key]
 for actor,entries in old.get('browser_actor_knowledge',{}).items():
  if actor not in definition['characters']:continue
  for entry in entries:
   if not entry.get('epistemic_verified')or entry.get('source_speaker')==definition['characters'][actor].get('name'):continue
   topic=digest(entry)[:18]
   put(state,'know:'+actor+':legacy-'+topic,'knowledge',{'holder':actor,'topic':'legacy-'+topic,'content':entry['observed'],
    'source':{'kind':'legacy_verified','record':topic},'belief':'reported','disclose':True},[actor],[actor])
 result['id']=result['memory_scope']=new_id;result['revision']=0;result['status']='paused'
 result['branch']={'parent_id':session['id'],'root_id':session.get('branch',{}).get('root_id',session['id']),
   'node_id':session['turns'][-1]['turn_id'],'kind':'world-upgrade','label':'事件系统升级分支'}
 result['facts']['browser_world_state']=state;result['facts']['browser_world_definition']=copy.deepcopy(definition)
 result['facts']['browser_world_origin']={'source_session':session['id'],'source_revision':session['revision'],'history_complete_from':'upgrade'}
 return result
def validate_checkpoint(snapshot):
 from event_schema import validate_state
 if snapshot.get('facts',{}).get('browser_world_state'):validate_state(snapshot['facts']['browser_world_state'])
 return True
