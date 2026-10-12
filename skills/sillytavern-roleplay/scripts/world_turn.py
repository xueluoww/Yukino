from map_runtime import get_locations
from scene_presence import visible_actor_ids,can_hear
"""Staged free input, per-actor requests and immutable transaction packets."""
import copy,json,re,time
from event_schema import digest,validate_effect
from world_state import location,colocated,read,state_hash,clock_time
from world_heartbeat import Transaction,advance_until,settle,choose_presentation
from actor_context import build_parser_view,build_actor_view,build_player_view,authorize_claims,validate_no_literal_leak

PARSER='''你是输入解释器，仅输出JSON对象actions数组。不是导演，不编造发生的事件。把原文按先后拆为意图：move(location),wait(minutes),say(text,audience可省略),observe(target),accept(id),decline(id),complete(id,method),transfer(instance,target),think(text)。每项必须含evidence，为输入里的逐字连续片段。动作必须源于输入，不添加后续行为。不替玩家接任务。内心和自言自语用think；语言是发声但不能传给不在场的人。目标只用view声明的ID。不要输出actor/template或改写世界字段。'''
PARSER+=' 【语言】和其他语言前缀必须保留为say，不能因为是陈述句就变成think。明确拒绝某个已收到的机会可以在say之外添加decline。accept/decline/complete的id及物品instance使用view.action_targets中的短ID，不使用状态卡前缀。'
ACTOR='''你只扮演view中的本人，输出JSON：text字符串、expression(neutral/thinking/soft/annoyed/sad/surprised)、claims数组(使用的knowledge卡ID)、thought字符串、actions数组。只使用本人的view。未知信息可以询问或承认不知道，不能假设认识眼前的人。不知道名字不用姓名。不扮演玩家、不替玩家接任务或决定内心。按本人性格回应，可拒绝、沉默或协商。无话可说text为空。actions只提出本人合法行为：say/observe/move，不能写任意世界数据；没有动作就[]。不把thought写进text。不要额外引入NPC。'''
ACTOR=ACTOR.replace('say/observe/move','move/observe（发言只填写text，不要在actions重复）')+' 对标记disclose=false的知识，不能在text透露，claims也不能引用；可以拒绝请求，不能假装不知道自己确实知道的事。'
NARRATOR='''只输出JSON：text字符串。用view与visible_events写一小段玩家能观察的环境或动作结果，不包含他人内心、未观察秘密或离场人物活动，不替玩家决定或补写心理。不要改变已结算事实，失败如实描述。不要逐轮强行制造事件，不写系统解释。'''
PLANNER='''只为view本人考虑眼前的活跃目标，不扮演玩家。输出JSON {"actions":[]}，最多一个动作，type只能move(location)、observe(target)或say(text,audience,claims)。可根据本人确知的线索尝试行动，也可以没有动作；不要猜未知秘密或新增目标。只使用view.available_routes与眼前可观察对象。交谈只向local_people里的同场人物，不重复刚说过的请求，不替玩家接受任务。claims只能使用本人的knowledge卡ID，禁止披露的信息不能引用或说出。没有合理行动填[]。不能控制其他人，不强行与玩家搭话。'''

class ModelGateway:
 def __init__(self,client,record=None):self.client=client;self.calls=[];self.outputs=[];self.record=record
 def ask(self,role,instructions,payload,max_tokens=900):
  from runtime_budget import consume
  consume('model')
  from model_protocol import schema,decode
  from prompt_cache import COMMON_CONTRACT,text_context
  instructions=COMMON_CONTRACT+instructions
  instructions+='\n阶段输出结构（另须满足上述语义规则）：'+json.dumps(schema(role,payload),ensure_ascii=False,separators=(',',':'))
  from model_context import bound_payload
  payload=bound_payload(payload,52000-len(instructions.encode('utf-8')))
  payload=text_context(payload)
  messages=[{'role':'system','content':instructions},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
  if self.record:self.record(role,copy.deepcopy(messages))
  started=time.monotonic()
  from deepseek_client import TransportError
  for attempt in range(2):
   try:
    if attempt:consume('model')
    else:consume()
    from feature_budget import consume_request
    consume_request()
    with self.client.lock:
     consume()
     raw=self.client.request(messages,max_tokens=max_tokens);metrics=copy.deepcopy(self.client.metrics)
    break
   except TransportError as error:
    self.calls.append({'role':role,'failed':True,'error_class':'TransportError','seconds':round(time.monotonic()-started,3)})
    if not error.retryable or attempt:raise
  self.calls.append({'role':role,'seconds':round(time.monotonic()-started,3),**metrics})
  result=decode(raw)
  self.outputs.append({'role':role,'result':copy.deepcopy(result)})
  return result

def validated_request(gateway,role,instructions,payload,validator,max_tokens=900):
 from diagnostic_system import validation_attempt
 for attempt in range(2):
  try:
   from runtime_budget import consume
   if not isinstance(gateway,ModelGateway):consume('model')
   from model_protocol import normalize
   answer=normalize(role,gateway.ask(role,instructions,payload,max_tokens),payload);validator(answer);validation_attempt(gateway,role,attempt);return answer
  except (ValueError,TypeError,KeyError) as error:
   validation_attempt(gateway,role,attempt,error)
   from model_context import ContextBudgetError
   if isinstance(error,ContextBudgetError):raise
   if attempt:raise
   from model_protocol import feedback
   payload=copy.deepcopy(payload);payload['validation_feedback']=feedback(role,error)

def stage_feedback(gateway,role,tx,actor=None):
 callback=getattr(gateway,'stage_callback',None)
 if callback:callback(role,actor if actor and colocated(tx.state,actor,'player') else None)

def parse_intent(text,state,definition,gateway=None):
 if gateway:
  parsed=validated_request(gateway,'parser',PARSER+' 所有actions元素必须有type键，type只能来自声明的input_interfaces；任务完成用complete，独自感叹用think。',
   {'view':build_parser_view(state,definition),'input':text},lambda answer:validate_intents(answer.get('actions',[]),text,state,definition),1200)
  actions=parsed.get('actions',[])
 else:
  from galgame import parse_input
  actions=[]
  for part in parse_input(text)['parts']:
   content=part['text'];kind=part['kind']
   if kind=='thought'or re.search('自言自语|心里|暗想',content):actions.append({'type':'think','text':content,'evidence':content});continue
   if kind=='speech':actions.append({'type':'say','text':content,'evidence':content});continue
   wait=re.search(r'(?:等待|等|休息)\s*(\d+)\s*分钟',content)
   target=next((lid for lid,v in get_locations(definition,state).items()if re.search('去|走|前往|回到|来到|进入',content)and(v.get('name',lid)in content or lid in content)),None)
   if wait:actions.append({'type':'wait','minutes':int(wait[1]),'evidence':content})
   elif target:actions.append({'type':'move','location':target,'evidence':content})
   else:actions.append({'type':'think','text':content,'evidence':content})
 return validate_intents(actions,text,state,definition)

def validate_intents(actions,text,state,definition):
 if not isinstance(actions,list)or len(actions)>12:raise ValueError('Too many action steps')
 actions=copy.deepcopy(actions)
 allowed={'move','wait','say','observe','accept','decline','complete','transfer','think'}
 for a in actions:
  if not isinstance(a,dict)or a.get('type')not in allowed:raise ValueError('Unsupported free input action')
  evidence=a.get('evidence','')
  if not isinstance(evidence,str)or not evidence or evidence not in text:raise ValueError('Intent has no exact source evidence')
  if a['type']=='move'and a.get('location')not in get_locations(definition,state):raise ValueError('Undeclared destination')
  if a['type']=='say'and re.search('【内心】|自言自语',evidence):raise ValueError('Private input cannot become public speech')
  if a['type']=='say':
   from galgame import parse_input
   if any(p['kind']=='thought'and evidence in p['text']for p in parse_input(text)['parts']):raise ValueError('Private span cannot become speech')
  if a['type']=='say'and not a.get('text'):raise ValueError('Empty speech')
  if a['type']=='say'and a['text']not in evidence:raise ValueError('Speech text must preserve actual input')
  if a['type']=='wait'and (type(a.get('minutes'))is not int or not 0<=a['minutes']<=10080):raise ValueError('Illegal waiting duration')
  if a['type']in('accept','decline','complete')and isinstance(a.get('id'),str):a['id']=a['id'].removeprefix('offer:')
  if a['type']=='observe'and isinstance(a.get('target'),str):a['target']=a['target'].removeprefix('item:')
  if a['type']=='transfer'and isinstance(a.get('instance'),str):a['instance']=a['instance'].removeprefix('item:')
 from galgame import parse_input
 for part in parse_input(text)['parts']:
  if part['kind']=='speech'and not re.search('自言自语',part['text'])and not any(a['type']=='say'and a.get('text')==part['text']for a in actions):
   raise ValueError('Public speech prefix must preserve the whole utterance as say')
 return copy.deepcopy(actions)

def actor_frame(actor,text,expression,state,definition,thought=False):
 here=location(state,'player');present=visible_actor_ids(state,definition)
 return {'kind':'thought'if thought else'dialogue','speaker':definition['characters'][actor]['name'],'actor_id':actor,'text':text,
   'expression':{'annoyed':'displeased','thinking':'serious','worried':'troubled','surprised':'surprised'}.get(expression,expression),'reaction_to':[],'stage':{'location':here,'present_actor_ids':present,'visible_actor_ids':present}}

def validate_temporal_text(state,definition,actor,text):
 from story_time import available
 origin=definition['characters'].get(actor,{}).get('knowledge_origin')
 engine={'calendar':state['clock'],**state.get('legacy_time',{})}
 for card in definition.get('dated_facts',[]):
  if not available(card,engine,origin) and any(term in text for term in [card['name'],*card.get('temporal',{}).get('aliases',[])]):
   raise ValueError('Generated text uses a registered future fact: '+card['id'])
 return True

def generate_actor_frames(tx,gateway,actors,heard,frames,listener_source='player'):
 for actor in list(dict.fromkeys(actors))[:3]:
  if actor=='player' or not colocated(tx.state,actor,listener_source):continue
  view=build_actor_view(tx.state,tx.definition,actor,tx.records,heard)
  if gateway:
   def validate(answer):
    from speech_channels import separate_response
    separate_response(answer)
    if not isinstance(answer.get('text'),str)or not isinstance(answer.get('thought',''),str)or not isinstance(answer.get('claims',[]),list):raise ValueError('Invalid actor response')
    authorize_claims(view,answer.get('claims',[]),answer['text']);validate_no_literal_leak(tx.state,actor,answer['text'],True)
    validate_no_literal_leak(tx.state,actor,answer.get('thought',''))
    validate_temporal_text(tx.state,tx.definition,actor,answer['text']+'\n'+answer.get('thought',''))
    if not isinstance(answer.get('actions',[]),list)or any(not isinstance(a,dict)or a.get('type')not in{'move','observe'}for a in answer.get('actions',[])):raise ValueError('NPC actions only support move/observe; speech belongs in text')
   stage_feedback(gateway,'actor:'+actor,tx,actor)
   answer=validated_request(gateway,'actor:'+actor,ACTOR,{'view':view},validate,900)
   text=answer.get('text','');thought=answer.get('thought','');claims=answer.get('claims',[])
   if not isinstance(text,str)or not isinstance(thought,str)or not isinstance(claims,list):raise ValueError('Invalid actor response')
   authorize_claims(view,claims,text);validate_no_literal_leak(tx.state,actor,text,True);validate_no_literal_leak(tx.state,actor,thought)
  else:answer={'text':'','thought':'','claims':[]};text='';thought='';claims=[]
  if text:
   rec=tx.apply({'template':'builtin.say','actor':actor,'text':text,'claims':claims},evidence=text)
   heard.append(rec['speech'])
   if 'player' in rec['observers']:frames.append(actor_frame(actor,text,answer.get('expression','neutral'),tx.state,tx.definition))
  if thought and colocated(tx.state,actor,'player'):frames.append(actor_frame(actor,thought,answer.get('expression','thinking'),tx.state,tx.definition,True))
  for action in answer.get('actions',[]):
   if not isinstance(action,dict)or action.get('type')not in {'move','observe'}:raise ValueError('Unsupported NPC proposed action')
   effect={'template':'builtin.'+action['type'],'actor':actor,**{k:v for k,v in action.items()if k in('location','target')}}
   try:
    tx.apply(effect,evidence=text)
   except ValueError as error:
    from diagnostic_system import record
    record(tx,actor,'actor-action',error,disposition='not_executed')

def plan_background(tx,gateway,frames=None):
 if not gateway or not tx.definition['config'].get('background_planning'):return
 now=clock_time(tx.state);interval=tx.definition['config'].get('planning_interval',15)
 last=tx.state.get('planning_times',{})
 actors=[a for a in tx.definition['characters']if not read(tx.state,'loc:'+a,{}).get('transit_to')and
  now-last.get(a,clock_time(tx.initial))>=interval and any(c['template']=='goal'and c['value'].get('owner')==a and c['value'].get('status')=='active'for c in tx.state['cards'].values())]
 for actor in actors[:2]:
  view=build_actor_view(tx.state,tx.definition,actor,tx.records)
  view['available_routes']=[{'id':lid,'name':get_locations(tx.definition,tx.state)[lid].get('name',lid)}
   for lid in get_locations(tx.definition,tx.state).get(location(tx.state,actor),{}).get('links',{})if not get_locations(tx.definition,tx.state)[lid].get('secret')]
  def valid(answer):
   acts=answer.get('actions',[])
   if not isinstance(acts,list)or len(acts)>1 or any(not isinstance(a,dict)or a.get('type')not in('move','observe','say')for a in acts):raise ValueError('Background planner may propose one own movement, observation or local conversation')
   for action in acts:
    if action['type']=='say':
     if not isinstance(action.get('text'),str):raise ValueError('Conversation requires text')
     authorize_claims(view,action.get('claims',[]),action['text']);validate_no_literal_leak(tx.state,actor,action['text'],True)
     validate_temporal_text(tx.state,tx.definition,actor,action['text'])
     if not isinstance(action.get('audience'),list)or not action['audience']or any(not colocated(tx.state,actor,a)or a==actor for a in action['audience']):raise ValueError('Background speech needs present recipients')
  stage_feedback(gateway,'planner:'+actor,tx)
  from deepseek_client import TransportError
  try:answer=validated_request(gateway,'planner:'+actor,PLANNER,{'view':view},valid,450)
  except (ValueError,TransportError) as error:
   old=copy.deepcopy(tx.state);tx.state.setdefault('planning_times',{})[actor]=now
   tx.record({'template':'builtin.decision','effects':[],'title':'人物的下一步暂未形成','outcome':'quiet','participants':[actor],
    'observers':[actor],'public':{},'rule_id':'actor-planner'},old)
   gateway.calls.append({'role':'planner-fallback:'+actor,'fallback':True,'error_class':type(error).__name__})
   continue
  old=copy.deepcopy(tx.state);tx.state.setdefault('planning_times',{})[actor]=now
  tx.record({'template':'builtin.decision','effects':[],'title':'人物考虑下一步','outcome':'applied'if answer.get('actions')else'quiet','participants':[actor],
   'observers':[actor],'public':{},'rule_id':'actor-planner'},old)
  for action in answer.get('actions',[]):
   effect={'template':'builtin.'+action['type'],'actor':actor,**{k:v for k,v in action.items()if k in('location','target','text','audience','claims')}}
   try:
    rec=tx.apply(effect,evidence='本人活跃目标与已有线索',rule_id='actor-planner')
    if action['type']=='say':
     target_frames=frames if frames is not None else[]
     if 'player' in rec['observers']:target_frames.append(actor_frame(actor,action['text'],'neutral',tx.state,tx.definition))
     generate_actor_frames(tx,gateway,rec['speech']['audience'],[rec['speech']],target_frames,listener_source=actor)
    settle(tx,True)
   except ValueError as error:tx.failure(effect,error,'本人尝试')

def prepare_turn(session,definition,text,request_id,gateway=None,actions=None,module_store=None,module_refs=(),pending=None,authored=None):
 if definition['config'].get('card_language'):
  from card_runtime import prepare_card_turn
  return prepare_card_turn(session,definition,text,request_id,gateway,actions,module_store,module_refs,pending,authored)
 previous=session['facts']['browser_world_state'];existing=next((t for t in session['turns']if t['turn_id']==request_id),None)
 if existing:
  if existing['user']!=text:raise ValueError('Same request id cannot carry different text')
  return {'already_saved':True,'packet':existing.get('world_packet')}
 tx=Transaction(previous,definition,request_id);frames=[];heard=[];initial_state=copy.deepcopy(tx.state)
 tx.module_store=module_store;tx.module_refs=module_refs
 if pending:
  from world_modules import apply_legacy_effect
  old=copy.deepcopy(tx.state);tx.state['module_states'][pending['module_id']]=copy.deepcopy(pending['module_entry'])
  tx.record({'template':'builtin.module','effects':[],'title':'玩法操作已结算','outcome':'applied','participants':['player'],
   'observers':['player'],'public':{'outcome':pending.get('outcome','')},'rule_id':'module:'+pending['module_id']},old)
  for e in pending.get('effects',[]):
   if e['type']=='events':tx.apply(e['event'],True,'玩家选择的玩法操作')
   else:apply_legacy_effect(tx,e,pending.get('bindings'))
 steps=validate_intents(actions,text,previous,definition)if actions is not None else parse_intent(text,previous,definition,gateway)
 for a in steps:
  kind=a['type'];evidence=a['evidence'];start=len(tx.records)
  if kind=='think':continue
  effect={'template':'builtin.'+kind,**{k:v for k,v in a.items()if k not in('type','evidence')}}
  if kind!='wait':effect['actor']='player'
  if kind=='wait':advance_until(tx,a['minutes'])
  else:
   prior=copy.deepcopy(tx.state)
   try:rec=tx.apply(effect,evidence=evidence)
   except ValueError as error:
    tx.state=prior;tx.failure(effect,error,evidence);rec=None
   if rec:
    if kind=='say':
     heard.append(rec['speech']);generate_actor_frames(tx,gateway,rec['speech']['audience'],heard,frames);advance_until(tx,1)
    elif kind=='move':
     value=read(tx.state,'loc:player');advance_until(tx,value.get('arrive_at',clock_time(tx.state))-clock_time(tx.state))
    else:settle(tx,True)
  plan_background(tx,gateway,frames)
  # Every action step has its own player-visible narration before the next step.
  from actor_context import event_description
  visible=[{'template':r['template'],'public':r.get('public',{}),'outcome':r['outcome'],'observed':event_description(r,definition,False,tx.state)}for r in tx.records[start:]if'player'in r['observers']]
  if visible:
   view=build_player_view(tx.state,definition)
   if gateway:
    stage_feedback(gateway,'narrator',tx)
    def valid_narration(answer):
     if not isinstance(answer.get('text'),str):raise ValueError('Narration must be text')
     validate_no_literal_leak(tx.state,'player',answer['text'])
     validate_temporal_text(tx.state,definition,'player',answer['text'])
    try:description=validated_request(gateway,'narrator',NARRATOR,{'view':view,'visible_events':visible},valid_narration,550)['text']
    except ValueError as error:
     # This read-only prose stage may fail independently of the validated world transaction.
     # Fall back to actual visible records, never to global rule titles or invented dialogue.
     description='；'.join(r['observed']for r in visible if r['template']!='builtin.say')
     if not description:description='周围暂时安静下来。'
     validate_no_literal_leak(tx.state,'player',description);validate_temporal_text(tx.state,definition,'player',description)
     gateway.calls.append({'role':'narrator-fallback','fallback':True,'error_class':type(error).__name__})
   else:description='；'.join(r['observed']for r in visible)
   if not isinstance(description,str):raise ValueError('Narration must be text')
   validate_no_literal_leak(tx.state,'player',description)
   if description:frames.append({'kind':'narration','speaker':'旁白','text':description,'expression':'absent','reaction_to':[],
    'stage':{'location':location(tx.state,'player'),'present_actor_ids':[x for x in definition['characters']if colocated(tx.state,x,'player')]}})
 if not frames:
  frames=[{'kind':'narration','speaker':'旁白','text':'眼前的场景保持着原来的模样。','expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':[x for x in definition['characters']if colocated(tx.state,x,'player')]}}]
 progress=None
 if authored:
  from world_authored import settle_authored_free
  progress=settle_authored_free(tx,*authored)
 packet=tx.snapshot_packet()
 return {'already_saved':False,'state':copy.deepcopy(tx.state),'packet':packet,'frames':frames,'actions':steps,
  'calls':copy.deepcopy(gateway.calls)if gateway else[],'visible_events':choose_presentation(tx.records),'authored_progress':progress}

def validate_packet(packet,previous=None):
 from storage_codec import unpack_state
 packet['state_after']=unpack_state(packet['state_after'])
 from event_schema import validate_state,validate_record
 if packet.get('version')!=1:raise ValueError('Unsupported world packet')
 head=packet.get('head');body={k:v for k,v in packet.items()if k!='head'}
 if digest(body)!=head:raise ValueError('World packet checksum mismatch')
 if state_hash(packet['state_after'])!=packet['after_hash']:raise ValueError('World state checksum mismatch')
 if previous and (packet['before_hash']!=state_hash(previous)or packet['previous_head']!=previous['journal_head']):raise ValueError('World packet ancestry mismatch')
 validate_state(packet['state_after'])
 prior=packet['before_hash']
 for r in packet['records']:
  validate_record(r)
  if r['before_hash']!=prior:raise ValueError('World event chain mismatch')
  prior=r['after_hash']
 if prior!=packet['after_hash']:raise ValueError('Unjournaled world mutation')
 return True

def build_packet(session,prepared,text,request_id):
 if prepared['already_saved']:return None
 from world_state import project_legacy
 state=prepared['state'];facts=project_legacy(state);facts['browser_world_state']=state
 frame=prepared['frames'][-1];here=location(state,'player');present=visible_actor_ids(state,session['facts']['browser_world_definition'])
 facts['browser_latest_frames']=prepared['frames'];facts['browser_scene_state']={'location':here,'present_actor_ids':present,'contacts':[],'arrivals':[],'input_events':[]}
 if prepared.get('authored_progress'):facts['browser_authored']=prepared['authored_progress']
 return {'turn_id':request_id,'expected_revision':session['revision'],'user':text,
  'assistant':'\n'.join(f['text']for f in prepared['frames']if f['kind']!='thought')or'片刻的安静。',
  'world_packet':prepared['packet'],'update':{'scene':here,'facts':facts,'summary':session.get('summary',''),'memories':[],'relationships':{}}}

class WorldRuntime:
 """Mixin for the existing player, opt-in by frozen event_system only."""
 def initialize_engine(self):
  super().initialize_engine()
  world=self.world_snapshot()
  if not world.get('event_system'):return
  from event_schema import validate_definition
  from world_state import initialize
  definition=validate_definition(world,world['setting_sets'])
  self.current['facts']['browser_world_definition']=definition
  state=initialize(definition,world)
  state['clock'].update({k:v for k,v in self.current['facts']['browser_engine']['calendar'].items()if k in('date','day','minute')})
  state['module_states']=copy.deepcopy(self.current['facts']['browser_engine'].get('modules',{}))
  state['legacy_time']={k:copy.deepcopy(v)for k,v in self.current['facts']['browser_engine'].items()if k in ('time_policy','time_runtime')}
  from world_modules import run_hooks
  tx=Transaction(state,definition,'opening-world');run_hooks(tx,self.modules,world.get('world_gameplay',[]),'world_initialize')
  if definition['config'].get('world_mode'):
   from goal_sets import select_goals
   gateway=getattr(self,'world_test_gateway',None)
   if gateway is None and self.provider=='deepseek':gateway=ModelGateway(self.flash)
   select_goals(tx,gateway)
   self.current['facts']['browser_goal_bootstrap_calls']=copy.deepcopy(gateway.calls)if gateway else[]
  state=tx.state # Opening is the explicit initial snapshot, not a fabricated past journal.
  self.current['facts']['browser_world_state']=state
  self.current['facts']['browser_world_origin']={'history_complete_from':'opening'}
  if definition['config'].get('world_mode'):
   here=location(state,'player');bindings=self.event_bindings();present=[bindings[a] for a in visible_actor_ids(state,definition)]
   self.current['scene']=here
   self.current['facts']['browser_scene_state']={'location':here,'present_actor_ids':present,'contacts':[],'arrivals':[],'input_events':[]}
   for frame in self.frames:
    frame['stage']={'location':here,'present_actor_ids':present,'visible_actor_ids':present}
   self.current['facts']['browser_opening_frames']=copy.deepcopy(self.frames)
   self.visual['background']=next((key for key,aliases in world.get('visual_locations',{}).items()if here==key or here in aliases),self.visual.get('background','clubroom'))
 def event_bindings(self):
  definition=self.current['facts']['browser_world_definition'];actors=self.actors()
  return {k:next((aid for aid,a in actors.items()if a['name']==c['name']),k)for k,c in definition['characters'].items()}
 def set_story_clock(self,session_id,date,minute):
  if self.current.get('facts',{}).get('browser_world_state'):raise ValueError('事件世界的时间只能由实际行动推进。')
  return super().set_story_clock(session_id,date,minute)
 def authored_prepare(self,route,progress,turn_id):
  if not self.current.get('facts',{}).get('browser_world_state'):return super().authored_prepare(route,progress,turn_id)
  node,frames,visual,facts=super().authored_prepare(route,progress,turn_id)
  definition=self.current['facts']['browser_world_definition'];tx=Transaction(self.current['facts']['browser_world_state'],definition,turn_id)
  if node['scene']not in get_locations(definition,tx.state):raise ValueError('事件预制线节点需要声明的地点ID，不能使用未映射自由场景名称。')
  tx.module_store=self.modules;tx.module_refs=self.world_snapshot().get('world_gameplay',[])
  from world_modules import apply_legacy_effect
  for e in node.get('world_events',[]):tx.apply(e,True,'作者定义的主线节点')
  for e in node.get('effects',[]):apply_legacy_effect(tx,e,self.event_bindings())
  if location(tx.state,'player')!=node['scene']:
   tx.apply({'template':'builtin.move','actor':'player','location':node['scene']},evidence='玩家选择进入下一幕')
   advance_until(tx,read(tx.state,'loc:player').get('arrive_at',clock_time(tx.state))-clock_time(tx.state))
  bindings=self.event_bindings();reverse={v:k for k,v in bindings.items()}
  for f in frames:
   if f['kind']=='dialogue':
    actor='player'if f['speaker']==self.current['user_name']else reverse.get(f.get('actor_id'))
    if not actor:raise ValueError('Authored actor cannot bind to event definition')
    validate_no_literal_leak(tx.state,actor,f['text'],True)
    tx.apply({'template':'builtin.say','actor':actor,'text':f['text'],'audience':[reverse.get(a,a)for a in f.get('audience_ids',[])if reverse.get(a,a)!=actor]},True,'作者对白')
   else:validate_no_literal_leak(tx.state,'player',f['text'])
  from world_state import project_legacy
  old=copy.deepcopy(tx.state);tx.state['plot']={'phase':node['title'],'beat':node.get('beat','development'),'focus':node.get('thread','')}
  tx.state['authored']={k:copy.deepcopy(v)for k,v in progress.items()if k not in('frame_cursor','free_turns')}
  tx.record({'template':'builtin.authored_node','effects':[],'title':node['title'],'outcome':'applied','participants':['player'],
   'observers':['player'],'public':{'node_id':progress['node_id']},'rule_id':'authored'},old)
  packet=tx.snapshot_packet();facts.update(project_legacy(tx.state));facts['browser_world_state']=tx.state
  facts['browser_world_packet_pending']=packet
  for field in ('browser_actor_locations','browser_actor_knowledge','browser_affinity'):
   facts[field]={bindings.get(k,k):v for k,v in facts[field].items()}
  facts['browser_affinity']={'version':1,'characters':facts['browser_affinity'],'applied_turns':[turn_id]}
  facts['browser_engine']['relations']={bindings.get(k,k):v for k,v in facts['browser_engine']['relations'].items()}
  for name in node['present']:
   actor=next((a for a,c in definition['characters'].items()if c['name']==name),None)
   if not actor or not colocated(tx.state,actor,'player'):raise ValueError('Authored scene requires a person who is currently absent; author must supply an arrival or alternate node')
  return node,frames,visual,facts
 def initialize_authored(self,storyline_id):
  if self.current['facts'].get('browser_world_state'):
   route=next((r for r in self.world_snapshot().get('storylines',[])if r['id']==storyline_id),None)
   if route:
    from world_state import put
    state=self.current['facts']['browser_world_state'];definition=self.current['facts']['browser_world_definition']
    if route.get('time_start'):
     policy=copy.deepcopy(state['legacy_time'].get('time_policy',{}));policy['start']=copy.deepcopy(route['time_start'])
     seeded=__import__('story_time').seed({'time':policy,'world_gameplay':self.world_snapshot().get('world_gameplay',[])})
     state['clock'].update(seeded['calendar']);state['legacy_time']['time_policy']=policy
    for actor,card in definition['characters'].items():
     name=card['name'];cid='rel:'+actor+':player';value=copy.deepcopy(read(state,cid))
     value.update(route.get('initial_relations',{}).get(name,{}))
     if name in route.get('initial_affinity',{}):value['affection']=route['initial_affinity'][name]
     put(state,cid,'relation',value,[actor,'player'],[actor,'player'])
  super().initialize_authored(storyline_id)
  packet=self.current['facts'].pop('browser_world_packet_pending',None)
  if packet:self.current['turns'][0]['world_packet']=packet
 def world_events(self,sid,view='protagonist',cursor=0,limit=50):
  from actor_context import build_event_reader_view
  with self.lock:
   if sid==self.current['id']:session=copy.deepcopy(self.current)
   else:_,session=self.tavern.find_record(self.root,'sessions',sid)
  if view=='expected':
   facts=session['facts'];canonical=facts.get('browser_world_state');definition=facts.get('browser_world_definition')
   if not canonical or not definition:return {'view':view,'total':0,'entries':[],'next_cursor':None,'legacy':True,'title':session['title']}
   from fixed_events import forecast
   result=forecast(canonical,definition,cursor,limit)
   result.update(session_id=session['id'],title=session['title'],revision=session['revision']);return result
  if not session['facts'].get('browser_world_state'):return {'view':view,'total':0,'entries':[],'next_cursor':None,'legacy':True,'title':session['title']}
  result=build_event_reader_view([t['world_packet']for t in session['turns']if t.get('world_packet')],session['facts']['browser_world_definition'],view,cursor,limit)
  result.update(session_id=session['id'],title=session['title'],revision=session['revision']);return result
 def world_navigation(self,sid,revision=None):
  """Read-only, current-branch projection; never build today's cards on a GET."""
  from map_runtime import known_map
  from npc_schedule import disclose_view
  from school_calendar import view as school_view
  with self.lock:
   if not self.current or sid!=self.current['id']:raise ValueError('只可查看当前存档的地图与约定。')
   session=copy.deepcopy(self.current)
  if revision is not None and int(revision)!=session['revision']:raise ValueError('存档已更新，请重新打开地图。')
  facts=session.get('facts',{});definition=facts.get('browser_world_definition');canonical=facts.get('browser_world_state')
  if not canonical:return {'enabled':False,'session_id':sid,'revision':session['revision'],'map':{'nodes':[]},'appointments':[]}
  features=definition['config'].get('features',[])
  return {'enabled':bool(features),'features':features,'session_id':sid,'revision':session['revision'],
          'map':known_map(canonical,definition,'player'),'appointments':disclose_view(canonical,definition),'school':school_view(canonical,definition),
          'exploration': 'exploration_v1' in features,'current_time':clock_time(canonical),
          'journey':copy.deepcopy(read(canonical,'journey:player',{}))}
 def state(self):
  result=super().state()
  if self.current:
   from world_modes import assert_mode
   result['game_mode']=assert_mode(self.current)
   result['revision']=self.current['revision']
  if self.current and self.current.get('facts',{}).get('browser_world_state'):
   from speech_channels import reader_frames,reader_thoughts
   projected=reader_frames(result['frames'])
   result['frames']=[f for f in projected if f['kind']!='thought']
   result['inner_thoughts']=reader_thoughts(self.current)
   tid=self.current['turns'][-1]['turn_id']
   for f in projected:
    if f['kind']=='thought'and not any(e.get('turn_id')==tid and e['text']==f['text']and e.get('actor_id')==f.get('actor_id')for e in result['inner_thoughts']):result['inner_thoughts'].append({'turn_id':tid,'name':f.get('speaker',''),'actor_id':f.get('actor_id'),'text':f['text'],'scene':f.get('stage',{}).get('location','')})
   if not result['frames']:result['frames']=[{'kind':'narration','text':'片刻的安静。','expression':'absent'}]
   from world_state import project_player
   result['event_mode']='event-v1';result['world_public']=project_player(self.current['facts']['browser_world_state'])
   result['navigation_features']=copy.deepcopy(self.current['facts']['browser_world_definition']['config'].get('features',[]))
   from world_memory import status
   result['memory_status']=status(self.current['facts']['browser_world_state'])
   # The ordinary game state must not broadcast hidden NPC knowledge or full dynamic state.
   for key in ('actor_knowledge','actor_locations','prepared_visuals'):result.pop(key,None)
   canonical=self.current['facts']['browser_world_state'];bindings=self.event_bindings()
   here=location(canonical,'player');result['scene']=get_locations(self.current['facts']['browser_world_definition'],canonical)[here].get('name',here)
   result['location']=result['scene']
   from world_presentation import visual_location
   definition=self.current['facts']['browser_world_definition'];world=self.world_snapshot()
   expected_bg=visual_location(world,definition,here,self.visual.get('background'),canonical)
   if self.visual.get('background')!=expected_bg:
    result['visual']=copy.deepcopy(result['visual']);result['visual']['background']=expected_bg;result['visual'].pop('background_asset',None)
    result['background']=self.descriptor().get('backgrounds',{}).get(expected_bg,'')
    result['world_background_missing']=not bool(result['background'])
    for f in result['frames']:
     f['background']=result['background'];f.get('stage',{}).pop('background_asset',None)
   result['story_state']['items']=[i for i in result['story_state'].get('items',[])if i.get('owner')=='player']
   result['story_state']['threads']=[t for t in result['story_state'].get('threads',[])if any(c['value'].get('title')==t.get('title')and 'player'in c['visibility']for c in canonical['cards'].values())]
   from recognition import FAMILIAR_LEVELS
   portraits={c['actor_id']:c.get('avatar','')for c in result.get('affinity',{}).get('characters',[])}
   result['familiarity']={'characters':[{'actor_id':bindings.get(c['subjects'][0],c['subjects'][0]),'name':self.current['facts']['browser_world_definition']['characters'][c['subjects'][0]]['name'],
    'score':c['value']['familiarity'],'status':next(label for lo,hi,label in FAMILIAR_LEVELS if lo<=c['value']['familiarity']<=hi),'avatar':portraits.get(bindings.get(c['subjects'][0],c['subjects'][0]),'')}
    for c in canonical['cards'].values()if c['template']=='relation'and c['subjects'][1]=='player'],'min':0,'max':100}
  return result
 def module_step(self,state,ref,action_id,text,turn_id,frames=None):
  if not self.current.get('facts',{}).get('browser_world_state'):return super().module_step(state,ref,action_id,text,turn_id,frames)
  import story_engine
  entry=state['modules'][ref['id']];reply=self.modules.call(ref,'event',entry['state'],story_engine.module_context(state,self.current['scene'],self.actors(),turn_id),
   {'action_id':action_id,'input':text,'frames':[]})
  if reply.get('rejected'):raise ValueError(reply['rejected'])
  entry['state']=reply['state']
  return {'module_id':ref['id'],'action_id':action_id,'effects':reply.get('effects',[]),'outcome':reply.get('outcome',''),
   'module_entry':copy.deepcopy(entry),'bindings':self.event_bindings()}
 def respond(self,text,request_id):
  from world_modes import assert_mode
  assert_mode(self.current)
  if not self.current.get('facts',{}).get('browser_world_state'):return self.legacy_respond(text,request_id)
  started=time.monotonic();committed=False;job=self.root/'browser/jobs'/self.current['id']/request_id
  from runtime_budget import ACTIVE,WorkBudget,consume
  budget=WorkBudget(getattr(self,'cancel_turn',None));budget_token=ACTIVE.set(budget)
  try:
   with self.lock:
    if self.persistent:
     _,self.current=self.tavern.find_record(self.root,'sessions',self.current['id'])
    if self.current.get('status')!='active':raise ValueError('存档已经暂停或切换，请重新读取。')
    snapshot=copy.deepcopy(self.current);self.activity['stage']='composing';self.activity['waiting_actor_ids']=[]
   gateway=getattr(self,'world_test_gateway',None)
   if gateway is None and self.provider=='deepseek':gateway=ModelGateway(self.flash)
   if gateway:
    bindings_for_feedback=self.event_bindings()
    def feedback(role,actor):
     with self.lock:self.activity['waiting_actor_ids']=[bindings_for_feedback.get(actor,actor)]if actor else[]
    gateway.stage_callback=feedback
   definition=snapshot['facts']['browser_world_definition'];pending=self._engine_pending.get(request_id)
   window,progress=self.authored_window()
   prepared=prepare_turn(snapshot,definition,text,request_id,gateway,module_store=self.modules,module_refs=self.world_snapshot().get('world_gameplay',[]),
    pending=pending['result']if pending else None,authored=(progress,window)if window else None)
   if prepared['already_saved']:
    self.activity['stage']='complete';return
   payload=build_packet(snapshot,prepared,text,request_id);bindings=self.event_bindings();facts=payload['update']['facts']
   for f in prepared['frames']:
    if f.get('actor_id'):f['actor_id']=bindings.get(f['actor_id'],f['actor_id'])
    for field in ('present_actor_ids','visible_actor_ids'):
     if field in f['stage']:f['stage'][field]=[bindings.get(a,a)for a in f['stage'][field]]
   for field in ('browser_actor_locations','browser_actor_knowledge','browser_affinity'):
    facts[field]={bindings.get(k,k):v for k,v in facts[field].items()}
   facts['browser_affinity']={'characters':facts['browser_affinity'],'version':1,'applied_turns':[request_id]}
   facts['browser_engine']['relations']={bindings.get(k,k):v for k,v in facts['browser_engine']['relations'].items()}
   facts['browser_scene_state']['present_actor_ids']=[bindings.get(a,a)for a in facts['browser_scene_state']['present_actor_ids']]
   facts['browser_inner_thoughts']=snapshot['facts'].get('browser_inner_thoughts',[])+[
    {'name':f['speaker'],'text':f['text'],'scene':payload['update']['scene'],'turn_id':request_id,'actor_id':f.get('actor_id')}for f in prepared['frames']if f['kind']=='thought']
   if pending:facts['browser_gameplay_receipts']=snapshot['facts'].get('browser_gameplay_receipts',{})|{request_id:{'module_id':pending['result']['module_id'],'action_id':pending['result']['action_id']}}
   facts['browser_turn_frames']=snapshot['facts'].get('browser_turn_frames',{})|{request_id:prepared['frames']}
   present=facts['browser_scene_state']['present_actor_ids'];visual=copy.deepcopy(self.visual)
   visual['expression']=next((f['expression']for f in reversed(prepared['frames'])if f['kind']=='dialogue'),'absent'if not present else'neutral')
   visuals=self.world_snapshot().get('visual_locations',{});physical=payload['update']['scene']
   from world_presentation import visual_location,turn_title,place_name
   background=visual_location(self.world_snapshot(),definition,physical,visual.get('background','clubroom'),facts['browser_world_state'])
   if background!=visual.get('background'):
    visual.pop('background_asset',None);visual.pop('background_identity',None)
   visual['background']=background
   place=get_locations(definition,facts['browser_world_state']).get(physical,{})
   visual['background_prompt']='视觉小说校园或世界场景背景，不绘制人物。地点：'+place.get('name',physical)+'。'+place.get('description','')+'。忠于剧本环境与当前故事时间，不擅自改变场所。'
   facts['browser_visual']=visual
   title=turn_title({'user':text,'world_packet':prepared['packet'],'frames':prepared['frames']},definition)
   payload['update']['summary']=place_name(definition,physical,facts['browser_world_state'])+' · '+title
   from world_choices import generate_choices
   from action_guard import protagonist
   choices,choice_status=generate_choices(prepared['state'],definition,prepared['frames'],gateway,prepared.get('input_status'),protagonist(snapshot))
   facts['browser_choice_state']={'version':1,'turn_id':request_id,'status':choice_status}
   prepared['calls']=copy.deepcopy(gateway.calls)if gateway else[]
   timeline=copy.deepcopy(snapshot['facts'].get('browser_story',{'nodes':[]}));timeline['choices']=choices;timeline['nodes'].append({'id':request_id,'title':title,'beat':'development','milestone':False,
    'scene':physical,'turn_index':len(snapshot['turns']),'story_time':str(prepared['state']['clock'])});facts['browser_story']=timeline
   validate_packet(payload['world_packet'],snapshot['facts']['browser_world_state'])
   job.mkdir(parents=True,exist_ok=True);self.tavern.atomic_json(job/'turn.json',payload)
   with self.lock:
    self.activity['stage']='saving'
    consume()
    if self.persistent:
     self.command('commit',snapshot['id'],job/'turn.json');_,self.current=self.tavern.find_record(self.root,'sessions',snapshot['id'])
    else:
     for k,v in payload['update'].items():
      if k in('facts','relationships'):self.current[k].update(v)
      else:self.current[k]=v
     self.current['turns'].append({'turn_id':request_id,'user':text,'assistant':payload['assistant'],'world_packet':payload['world_packet']});self.current['revision']+=1
    committed=True;self.frames=prepared['frames'];self.visual=visual;self.version+=1
    self.metrics={'last_response_seconds':round(time.monotonic()-started,3),'world_calls':prepared['calls'],'world_events':len(prepared['packet']['records'])}
    self.checkpoint();self._engine_pending.pop(request_id,None);self.activity['stage']='complete';self.error=''
    from job_retention import retain
    retain(self.root,snapshot['id'],request_id)
    if self.dynamic_images:
     visual_reply={'frames':self.frames,'visual':self.visual,'scene':self.current['scene'],'story':{'title':title},'illustration':{'recommended':False,'prompt':''}}
     try:self.queue_images(self.plan_images(visual_reply),self.current['id'],self.current['card_id'])
     except (OSError,ValueError):self.image_error='画面尚未就绪，故事已保存。'
  except Exception as error:
   with self.lock:
    self.error=''if committed else str(error);self.activity['stage']='complete'if committed else'failed'
    job.mkdir(parents=True,exist_ok=True);self.tavern.atomic_json(job/'diagnostic.json',{'error_class':type(error).__name__,'error':str(error),'committed':committed})
  finally:
   ACTIVE.reset(budget_token)
   with self.lock:self.busy=False
