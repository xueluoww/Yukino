"""Per-listener dialogue context. Hearing does not imply being addressed or consenting."""
import copy,re
from event_schema import digest
from world_state import put,read,colocated
from speech_rules import addressed_repliers,named_addressees

def response_targets(tx,speech):
 audience=[a for a in speech['audience']if a!='player'];text=speech['text']
 old=addressed_repliers(tx.definition,speech)
 named=named_addressees(tx.definition,text)
 if named:return [a for a in named if a in audience]
 # Explicit single name/title handled by the previous rule.
 if len(old)==1 and len(audience)>1:return old
 if re.search(r'你们|大家|各位|各自',text):return audience[:3]
 context=read(tx.state,'dialogue:'+speech['actor'],{})
 last=context.get('last_addressee')
 if last in audience and colocated(tx.state,speech['actor'],last):return[last]
 # One foreground partner in ambiguous ordinary chatter; no automatic chorus.
 return old[:1]

def record_speech(tx,speech,addressees=None):
 targets=list(addressees if addressees is not None else response_targets(tx,speech));speaker=speech['actor']
 old=copy.deepcopy(tx.state);cid='utterance:'+digest([speaker,speech['text'],len(tx.records),tx.request_id])[:18]
 entry={'id':cid,'speaker':speaker,'text':speech['text'],'addressees':targets,'audience':list(speech['audience']),'at':__import__('world_state').clock_time(tx.state)}
 for actor in [speaker,*speech['audience']]:
  key='dialogue:'+actor;value=copy.deepcopy(read(tx.state,key,{'owner':actor,'turns':[]}));value['turns']=(value['turns']+[entry])[-8:]
  if actor==speaker and len(targets)==1:value['last_addressee']=targets[0]
  elif actor in targets:value['last_addressee']=speaker
  if '?'in speech['text']or'？'in speech['text']:
   if actor in targets:value['pending_question']={'utterance':cid,'from':speaker,'text':speech['text']}
  elif actor==speaker:value.pop('pending_question',None)
  put(tx.state,key,'dialogue',value,[actor],[actor])
 tx.record({'template':'builtin.dialogue_context','effects':[],'title':'交流语境','outcome':'recorded','participants':[speaker],
  'observers':[],'public':{},'rule_id':'dialogue'},old)
 from world_activity import heard
 heard(tx,speech,targets)
 return targets

def actor_dialogue(tx,actor,heard,listener):
 own=read(tx.state,'dialogue:'+actor,{})
 return {'role':'direct_recipient','answer_to':listener,'heard_now':copy.deepcopy(heard),'recent':copy.deepcopy(own.get('turns',[]))[-5:],
  'pending_question':copy.deepcopy(own.get('pending_question')),'rule':'知道自己是谁；被问的是你，不要把问题当作问别人。只回答实际问题，旁听不等于受托。'}

def classify_reply(text,new_topics=(),system_error=False):
 if system_error:return'system_error'
 if re.search('不能说|不会告诉|不想说|不帮|拒绝|不愿意',text):return'refused'
 if new_topics:return'partial_information'
 if '？'in text or '?'in text:return'needs_clarification'
 return'no_information'
