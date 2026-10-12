from map_runtime import get_locations
from scene_presence import visible_actor_ids,can_hear
"""Experimental language/action transactions; no installed production changes."""
import copy,json,re
from event_schema import digest
from basic_cards import vocabulary,expand,register_recipe,normalize_action
from world_state import read,put,location,colocated,clock_time
from world_heartbeat import Transaction,advance_until,settle,choose_presentation
from actor_context import build_actor_view,build_parser_view,build_player_view,authorize_claims,event_description
from language_actions import detect,record_language
from card_validation import preflight,soft_review,verify_prose
from goal_feedback import active_goals,planning_view,add_feedback

INPUT='''解释玩家自由输入，仅JSON {"steps":[],"recipes":[]}。steps逐项{type,params,evidence}，evidence必须输入逐字片段。type为词表ID或think或compound；compound用recipe/bindings。recipes仅可提出固定原语组成的配方，不造物品/角色/原语/代码/世界事实。按输入顺序解释，完整保留【语言】为say(text)，语言中的动作交给后续检测，不在steps再次执行。内心与自语think(text)，绝不say。【动作】表达尝试，不保证成功；环境里无证据的对象不能生成。不要替玩家接任务。没有实现接口的动作type=unsupported,params={text:原文}，不改成think悄悄吞掉。多种同义自由表达可使用复合方法。仅用view的实体ID，原语params禁止actor、consent。最多12步。'''
PERSON='''扮演view.actor_id本人，输出JSON {"text":"","expression":"neutral","claims":[],"thought":"","actions":[]}。按静态性格与本人的知识回应。只使用view，陌生人未知姓名不用姓名；内心不说出口。claims列出本句实际引用的知识卡ID，可把可披露的已知线索告诉询问者，传闻标明不确定。禁披露知识不说。不替玩家同意/行动。text可以自然包含本人下一步行动，程序检测并执行；actions仅作text没有表达的本人动作，使用{type,params}词表格式，不重复。不虚构具体书名作者、物品、身份、过去经历，缺来源就询问或泛称。可以拒绝、暂缓、安静。禁止声称未结算的交接/到达/任务完成已经成功。最多2个actions。'''
PLAN='''只规划view本人活跃目标，JSON {"choice":null,"action":null,"reason":"quiet"}。可选opportunities的id作为choice，或提出一个{type,params}action。选询问时action要含ask的text/audience/claims；text按性格自然组织，围绕本人的目标。不重复goal_feedback中同条件已试的方法。没有合理行动可quiet，reason为quiet/blocked/no_opportunity/rest。对已有线索可行动，不等玩家指挥。不替玩家接任务，不猜你不知的书名作者或远处位置。候选只提供机会，不要求必选。'''

def parser_view(state,d):
 view=build_parser_view(state,d)
 here=location(state,'player');items=[]
 for cid,c in state['cards'].items():
  if c['template']=='item'and c['value']['quantity']and c['value']['location']==here:
   if d['config'].get('world_mode')and read(state,'loc:player',{}).get('at_entrance')and c['value']['owner']!='player':continue
   item=d['items'][c['value']['item']]
   if not item.get('hidden'):items.append({'instance':cid[5:],'name':item['name'],'owner':c['value']['owner'],'capabilities':list(item.get('capabilities',{}))})
 view['action_targets']['items']=items;view['vocabulary']=vocabulary()
 from speech_rules import known_addresses
 view['action_targets']['people']=known_addresses(state,d,'player')
 if 'exploration_v1'not in d['config'].get('features',[]):view['vocabulary']=[x for x in view['vocabulary']if x['id']!='explore']
 else:
  from map_runtime import known_map,ancestors
  view['map']=known_map(state,d,'player');view['exploration_scopes']=ancestors(d,state,here)
 view['doors']=[{'id':k,'name':v.get('name','门'),'destination':v['destination'] if v['location']==here else v['location'],**read(state,'door:'+k,{})}for k,v in d['config'].get('doors',{}).items()if here in (v['location'],v['destination'])]
 view['trade_offers']=[{'id':k,'price':v['price'],'currency':v['currency'],'instance':v['instance']}for k,v in d['config'].get('commerce',{}).items()if v['location']==here]
 from daily_life import offers
 view['daily_offers']=offers(state,d,'player')
 return view

def validate_input(answer,text,tx):
 from galgame import parse_input
 recipes=answer.get('recipes',[]);steps=answer.get('steps')
 if not isinstance(recipes,list)or len(recipes)>4 or not isinstance(steps,list)or len(steps)>12:raise ValueError('Invalid input program')
 from basic_cards import validate_recipe
 temporary=copy.deepcopy(tx.state)
 for recipe in recipes:
  r=validate_recipe(recipe);temporary['cards']['recipe:'+r['id']]={'value':{'recipe':r}}
 for index,step in enumerate(steps):
  if isinstance(step,dict)and step.get('type')not in('think','unsupported','compound'):
   step=normalize_action(step,tx.state,tx.definition,'player');steps[index]=step
  if not isinstance(step,dict)or set(step)-{'type','params','evidence','recipe','bindings'}:raise ValueError('Unexpected input fields')
  span=step.get('evidence')
  if not isinstance(span,str)or not span or span not in text:raise ValueError('Input action needs exact source')
  kind=step.get('type');params=step.get('params',{})
  if kind=='think':continue
  if kind=='unsupported':
   if not isinstance(params.get('text'),str):raise ValueError('Unsupported action needs description')
   continue
  expand(step,temporary,'player')
  if kind in('say','ask','answer'):
   if params.get('text')not in span:raise ValueError('Speech must preserve source')
   if any(p['kind']=='thought'and span in p['text']for p in parse_input(text)['parts']):raise ValueError('Inner cannot become public')
 for p in parse_input(text)['parts']:
  if p['kind']=='speech'and not any(s.get('type')in('say','ask','answer')and s.get('params',{}).get('text')==p['text']for s in steps):raise ValueError('Public utterance omitted or rewritten')
 return copy.deepcopy(steps)

def diag(tx,actor,stage,error):
 if tx.definition['config'].get('world_mode'):
  from diagnostic_system import record
  return record(tx,actor,stage,error)
 old=copy.deepcopy(tx.state)
 return tx.record({'template':'builtin.system_diagnostic','effects':[],'title':'生成阶段需修正','outcome':'error',
  'participants':[actor],'observers':[],'public':{},'diagnostic':{'stage':stage,'error':type(error).__name__},'rule_id':'system'},old)

def scoped_claims(claims,view):
 if isinstance(claims,list):claims=[c['id']if isinstance(c,dict)and set(c)<={'id','topic'}and isinstance(c.get('id'),str)else c for c in claims]
 if not isinstance(claims,list)or len(claims)>12 or any(not isinstance(c,str)for c in claims):raise ValueError('Claims must be strings from permitted knowledge ids')
 cards={c['id']:c for c in view['cards']if c['template']=='knowledge'};result=[]
 for claim in claims:
  if claim not in cards:
   ids=[k for k,c in cards.items()if claim==c['value']['topic']]
   if len(ids)!=1:raise ValueError('Claim not in permitted knowledge ids: '+','.join(cards))
   claim=ids[0]
  result.append(claim)
 return result

def parse_steps(tx,gateway,text):
 """Explicit channels are program-owned. Only free action/environment spans need interpretation."""
 if tx.definition['config'].get('card_refinement'):
  from card_refinement import parse_steps as refined_parse
  return refined_parse(tx,gateway,text)
 from galgame import parse_input
 from world_turn import validated_request
 steps=[];recipes=[]
 for part in parse_input(text)['parts']:
  content=part['text'];kind=part['kind']
  if kind=='thought'or '自言自语'in content:steps.append({'type':'think','params':{'text':content},'evidence':content});continue
  if kind=='speech':steps.append({'type':'say','params':{'text':content},'evidence':content});continue
  source='【动作】'+content
  answer=validated_request(gateway,'parser',INPUT,{'input':source,'view':parser_view(tx.state,tx.definition)},lambda a:validate_input(a,source,tx),1300)
  steps.extend(validate_input(answer,source,tx));recipes.extend(answer.get('recipes',[]))
  if len(steps)>12 or len(recipes)>4:raise ValueError('Input program exceeds bounded complexity')
 return steps,recipes

def execute(tx,action,actor,evidence,gateway=None,review=True):
 effects,policy=expand(action,tx.state,actor);results=[]
 journey_target=None
 # A destination is a request to travel by declared routes, not to teleport.
 if actor=='player' and len(effects)==1 and effects[0]['template']=='builtin.move':
  e=effects[0];origin=location(tx.state,actor)
  from map_runtime import enabled as map_enabled,navigation_failure
  if map_enabled(tx.definition):
   reason=navigation_failure(tx.state,tx.definition,actor,e['location'])
   if reason:return [tx.failure(e,ValueError(reason),evidence)]
  if e['location']!=origin and e['location']not in get_locations(tx.definition,tx.state).get(origin,{}).get('links',{}):
   from goal_planner import routes
   path=routes(tx,origin,e['location'],actor=actor)
   if path:
    effects=[{**e,'location':destination}for destination in path];policy='stop'
    from map_runtime import enabled as map_enabled
    if map_enabled(tx.definition) and len(path)>1:journey_target=e['location']
 from world_activity import enabled,action_activity,advance as world_advance
 if enabled(tx)and actor!='player'and action.get('type')in('wait','rest'):
  action_activity(tx,actor,action);return [tx.records[-1]]
 # Physical failures are checked without spending a verifier request.
 if review and any(e['template'][8:]in('transfer','take','consume','use','complete','accept')for e in effects):
  try:preflight(tx,effects,evidence)
  except ValueError as error:
   return [tx.failure(effects[0],error,evidence)]
  try:r=soft_review(tx,gateway,actor,effects,build_actor_view(tx.state,tx.definition,actor,tx.records),evidence)
  except (ValueError,TypeError,KeyError) as error:return [diag(tx,actor,'review',error)]
  if r['decision']=='hold':
   old=copy.deepcopy(tx.state)
   return [tx.record({'template':'builtin.review_hold','effects':[],'title':'行动尚待确认','outcome':'held',
    'participants':[actor],'observers':[actor],'public':{'reason':'当前条件下还不能确定这一行动'},'review':r,'rule_id':'review'},old)]
 for segment,e in enumerate(effects):
  try:
   segment_start=len(tx.records)
   before_visible=set(visible_actor_ids(tx.state,tx.definition,actor)) if journey_target else set()
   if e['template']=='builtin.explore':
    from map_exploration import explore
    results.append(explore(tx,actor,e['scope'],gateway))
   elif e['template']=='builtin.wait':
    start=len(tx.records)
    if enabled(tx):world_advance(tx,e['minutes'],gateway,getattr(tx,'world_frames',[]))
    else:advance_until(tx,e['minutes'])
    results.extend(tx.records[start:])
   else:
    rec=tx.apply(e,evidence=evidence);results.append(rec)
    if enabled(tx)and actor!='player':action_activity(tx,actor,action)
    if actor=='player'and e['template']=='builtin.move':
     duration=max(0,read(tx.state,'loc:player',{}).get('arrive_at',clock_time(tx.state))-clock_time(tx.state))
     if enabled(tx):world_advance(tx,duration,gateway,getattr(tx,'world_frames',[]))
     else:advance_until(tx,duration)
     if journey_target and segment<len(effects)-1:
      significant=[r for r in tx.records[segment_start:] if 'player' in r.get('observers',[]) and r['template'] in ('builtin.offer','builtin.arrival') and r.get('public',{}).get('actor')!='player']
      if set(visible_actor_ids(tx.state,tx.definition,actor))-before_visible:
       significant.extend(r for r in tx.records[segment_start:] if r['template']=='builtin.arrival' and r.get('public',{}).get('actor')=='player')
      if significant:
       from goal_sets import store_card
       store_card(tx,'journey:player','journey',{'owner':'player','status':'paused','target':journey_target,'at':location(tx.state,'player'),'source_events':[r['event_id'] for r in significant]},'player','途中出现可注意的变化，是否继续由玩家决定')
       break
     if read(tx.state,'journey:player',{}).get('status')=='paused' and location(tx.state,'player')==read(tx.state,'journey:player',{})['target']:
      from goal_sets import store_card
      store_card(tx,'journey:player','journey',{**read(tx.state,'journey:player'),'status':'completed'},'player','实际到达行程目的地')
    elif e['template']in('builtin.search','builtin.observe','builtin.read','builtin.consume','builtin.write','builtin.buy'):
     if not(enabled(tx)and actor!='player'):advance_until(tx,1)
    else:settle(tx,True)
  except ValueError as error:
   results.append(tx.failure(e,error,evidence))
   if policy=='stop':break
 return results

def language_effects(tx,gateway,actor,text,candidates=None):
 view=parser_view(tx.state,tx.definition)if actor=='player'else build_actor_view(tx.state,tx.definition,actor,tx.records)
 # NPC's own item and locally observed identities only. Never all inventory/knowledge.
 if actor!='player':
  view['action_targets']={'items':[{'instance':c['id'][5:],'name':tx.definition['items'][c['value']['item']]['name']}for c in view['cards']if c['template']=='item'and c['value']['quantity']],
   'locations':[{'id':k,'name':get_locations(tx.definition,tx.state)[k].get('name',k)}for k in get_locations(tx.definition,tx.state).get(location(tx.state,actor),{}).get('links',{})if not get_locations(tx.definition,tx.state)[k].get('secret')]}
 if candidates is None:
  try:
   from card_refinement import action_language
   candidates=[]if tx.definition['config'].get('card_refinement')and not action_language(text)else detect(gateway,text,actor,tx.state,tx.definition,view)
  except (ValueError,TypeError,KeyError) as error:
   diag(tx,actor,'detector',error)
   if not tx.definition['config'].get('world_mode'):return []
   candidates=[] # Independent explicit refusal survives an unavailable language detector.
 if actor=='player':
  from input_grounding import ground_move,GroundingError
  grounded=[]
  for candidate in candidates:
   action=candidate.get('action')
   try:
    if action and candidate.get('kind')in('immediate','plan','promise'):
     ground_move({'type':action['type'],'params':action.get('params',{}),'evidence':candidate['evidence']},tx)
    grounded.append(candidate)
   except GroundingError as error:diag(tx,actor,'detector',error)
  candidates=grounded
 # A clearly expressed refusal to the sole received offer is a player decision, not a forced choice.
 if actor=='player'and re.search(r'(?:不接|不接受|拒绝).{0,10}(?:委托|任务)',text)and not re.search('如果|假如|昨天|“|”',text):
  offers=[c for c in tx.state['cards'].values()if c['template']=='opportunity'and actor in c['visibility']and c['value']['target']==actor and c['value']['status']=='offered']
  if len(offers)==1 and not any(c.get('action',{}).get('type')=='refuse'for c in candidates):
   candidates.append({'kind':'immediate','actor':actor,'evidence':text,'action':{'type':'refuse','params':{'id':offers[0]['id'][6:]}}})
 records=[];seen=set()
 for c in candidates:
  record_language(tx,c,actor)
  if c['kind']=='immediate':
   key=digest(c['action'])
   if key in seen:continue
   seen.add(key)
   try:records.extend(execute(tx,c['action'],actor,c['evidence'],gateway))
   except (ValueError,TypeError,KeyError) as error:records.append(diag(tx,actor,'detected-action',error))
 return records

def actor_reply(tx,gateway,actor,heard,frames,listener='player'):
 if tx.definition['config'].get('card_refinement'):
  from card_refinement import actor_reply as refined_reply
  return refined_reply(tx,gateway,actor,heard,frames,listener)
 if actor=='player'or not can_hear(tx.state,tx.definition,actor,listener):return
 from world_turn import validated_request,actor_frame,stage_feedback
 view=build_actor_view(tx.state,tx.definition,actor,tx.records,heard)
 def valid(a):
  from speech_channels import separate_response
  separate_response(a)
  if not isinstance(a.get('text'),str)or not isinstance(a.get('thought',''),str)or not isinstance(a.get('claims',[]),list):raise ValueError('Invalid actor prose')
  a['claims']=scoped_claims(a.get('claims',[]),view)
  authorize_claims(view,a['claims'],a['text']);verify_prose(tx,actor,a['text']);verify_prose(tx,actor,a.get('thought',''),private=True)
  from prose_facts import check_facts
  flags=check_facts(tx,gateway,actor,a['text'],view)
  if flags:raise ValueError('Scoped factual prose needs rewrite: '+json.dumps(flags,ensure_ascii=False))
  if not isinstance(a.get('actions',[]),list)or len(a.get('actions',[]))>2:raise ValueError('Too many NPC actions')
  for i,action in enumerate(a.get('actions',[])):
   action=normalize_action(action,tx.state,tx.definition,actor);a['actions'][i]=action;expand(action,tx.state,actor)
 if not gateway:return
 stage_feedback(gateway,'actor:'+actor,tx,actor)
 try:answer=validated_request(gateway,'actor:'+actor,PERSON+' claims仅使用view.cards中template=knowledge的id；听者只会获得text实际说出的信息，不继承被引用卡的完整内容。根据性格愿意透露线索时，请用自然话明确说出实际线索，不能只说有点印象却想让听者知道位置。听到的玩家话不需要伪造knowledge引用。',{'view':view,'vocabulary':vocabulary()},valid,900)
 except (ValueError,TypeError,KeyError) as error:diag(tx,actor,'actor',error);return
 text=answer['text'];claims=answer.get('claims',[])
 # Detect BEFORE speaking/rendering; failed detection cannot silently promise an executed action.
 try:candidates=detect(gateway,text,actor,tx.state,tx.definition,view)if text else[]
 except (ValueError,TypeError,KeyError) as error:
  diag(tx,actor,'detector',error);return
 proposed=[c['action']for c in candidates if c['kind']=='immediate']+answer.get('actions',[])
 for action in proposed:
  try:
   effects,_=expand(action,tx.state,actor);preflight(tx,effects,text)
  except ValueError:
   if re.search('已经(?:把|拿到|到达|完成)|成功(?:交给|拿到|完成)|递到你手里',text):
    # No false completed utterance is written to the speech ledger or taught to listeners.
    diag(tx,actor,'prose-preflight',ValueError('Completed prose without feasible action'));return
 # Spoken-stage frame is frozen before movement; subsequent frames describe actual outcomes.
 frame=actor_frame(actor,text,answer.get('expression','neutral'),tx.state,tx.definition)
 rec=None
 if text:
  rec=tx.apply({'template':'builtin.say','actor':actor,'text':text,'claims':claims,'audience':list(dict.fromkeys([listener]))},evidence=text)
  # Utterance must precede movement, so people hear a departure but not its remote aftermath.
  start=len(tx.records);outcomes=language_effects(tx,gateway,actor,text,candidates)
  detected=[r.get('candidate',{}).get('action')for r in tx.records[start:]if r['template']=='builtin.language_detection']
  for action in answer.get('actions',[]):
   if action not in detected:outcomes.extend(execute(tx,action,actor,text,gateway))
  if 'player'in rec['observers']:
   try:verify_prose(tx,actor,text,outcomes)
   except ValueError:
    # Hold contradicted rendering and retain truthful event outcome; speech ledger is explicitly marked.
    old=copy.deepcopy(tx.state);rec['render_held']=True
    tx.record({'template':'builtin.prose_alignment','effects':[],'title':'表达与行动结果对齐','outcome':'held',
     'participants':[actor],'observers':[],'public':{},'rule_id':'render'},old)
   else:frames.append(frame)
 if answer.get('thought')and colocated(tx.state,actor,'player'):
  frames.append(actor_frame(actor,answer['thought'],'thinking',tx.state,tx.definition,True))

def plans_due(tx,gateway):
 for cid,card in list(tx.state['cards'].items()):
  if card['template']!='plan':continue
  value=card['value'];actor=value['owner']
  if value['status']!='pending'or value.get('due_at')is None or value['due_at']>clock_time(tx.state):continue
  if actor=='player'or value['kind']in('request','conditional')or not value.get('action'):continue
  old=copy.deepcopy(tx.state);v=copy.deepcopy(value);v['status']='checking';put(tx.state,cid,'plan',v,[actor],[actor])
  tx.record({'template':'builtin.plan_due','effects':[],'title':'人物计划到期检查','outcome':'recorded','participants':[actor],'observers':[actor],'public':{}},old)
  results=execute(tx,value['action'],actor,value['text'],gateway)
  old=copy.deepcopy(tx.state);v['status']='executed'if results and all(r['outcome']=='applied'for r in results)else'blocked'
  put(tx.state,cid,'plan',v,[actor],[actor]);tx.record({'template':'builtin.plan_result','effects':[],'title':'计划执行结果','outcome':v['status'],
   'participants':[actor],'observers':[actor],'public':{}},old)

def background(tx,gateway,frames):
 if not gateway or not tx.definition['config'].get('background_planning'):return
 if tx.definition['config'].get('world_mode'):
  from goal_planner import background as persistent_background
  return persistent_background(tx,gateway,frames)
 from world_turn import validated_request,actor_frame
 now=clock_time(tx.state);interval=tx.definition['config'].get('planning_interval',5)
 for actor in list(tx.definition['characters'])[:8]:
  if read(tx.state,'activity:'+actor,{}).get('busy_until',0)>now or read(tx.state,'loc:'+actor,{}).get('transit_to')or not active_goals(tx.state,actor)or now-tx.state.get('planning_times',{}).get(actor,clock_time(tx.initial))<interval:continue
  view,opportunities,scope=planning_view(tx,actor)
  def valid(a):
   if set(a)-{'choice','action','reason'}:raise ValueError('Unknown planning field')
   if tx.definition['config'].get('card_refinement')and a.get('action')and a.get('choice')is not None and str(a['choice'])not in {c['id']for c in opportunities}:a['choice']=None
   if a.get('choice')is not None and str(a['choice'])not in {c['id']for c in opportunities}:raise ValueError('Unknown opportunity')
   if a.get('action'):
    a['action']=normalize_action(a['action'],tx.state,tx.definition,actor)
    expand(a['action'],tx.state,actor)
    if a['action']['type']in('ask','say','answer'):
     params=a['action']['params'];params['claims']=scoped_claims(params.get('claims',[]),view);authorize_claims(view,params['claims'],params.get('text',''));verify_prose(tx,actor,params.get('text',''))
     if tx.definition['config'].get('card_refinement'):
      from fact_ledger import build_ledger,audit_expression
      flags=audit_expression(tx,gateway,actor,params.get('text',''),build_ledger(tx,actor),force=True)
     else:
      from prose_facts import check_facts
      flags=check_facts(tx,gateway,actor,params.get('text',''),view)
     if flags:raise ValueError('Planner prose needs sourced facts: '+json.dumps(flags,ensure_ascii=False))
   if a.get('choice')is not None and not a.get('action')and next(c for c in opportunities if c['id']==str(a['choice']))['action']['type']=='ask':raise ValueError('Inquiry needs model-written utterance')
  old=copy.deepcopy(tx.state);tx.state.setdefault('planning_times',{})[actor]=now
  tx.record({'template':'builtin.decision','effects':[],'title':'人物考虑目标','outcome':'recorded','participants':[actor],'observers':[actor],'public':{}},old)
  if tx.definition['config'].get('card_refinement'):
   from model_context import stable_contract,working_view
   compact=working_view(tx,actor)
   compact.update({k:view[k]for k in('goal_feedback','opportunities','scope_key')if k in view})
   contract=stable_contract(PLAN+' claims只能为[]或view.cards里实际knowledge的id，不能写目标名称。choice是数字字符串，不是动作名称；自己提出action时choice可以null。');payload={'view':compact}
  else:contract=PLAN;payload={'view':view,'vocabulary':vocabulary()}
  try:a=validated_request(gateway,'planner:'+actor,contract,payload,valid,550)
  except (ValueError,TypeError,KeyError) as error:diag(tx,actor,'planner',error);continue
  action=a.get('action')
  if not action and a.get('choice')is not None:action=next(c['action']for c in opportunities if c['id']==str(a['choice']))
  goal=active_goals(tx.state,actor)[0]['id'][5:]
  if not action:add_feedback(tx,actor,goal,{'type':'quiet','params':{}},'quiet',scope,a.get('reason','quiet'));continue
  from goal_feedback import signature,action_guard
  guard=action_guard(tx.state,{**action,'_actor':actor})
  from goal_feedback import blocks_retry
  if any(blocks_retry(t,action,scope,guard,tx.definition['config'].get('card_refinement',False))for c in view.get('goal_feedback',[])for t in c['attempts']):
   add_feedback(tx,actor,goal,action,'held',scope,'重复方法且条件未改变');continue
  before_topics={c['id']for c in tx.state['cards'].values()if c['template']=='knowledge'and actor in c['visibility']}
  spoken_frame=None
  if action['type']in('ask','say','answer'):spoken_frame=actor_frame(actor,action['params'].get('text',''),'neutral',tx.state,tx.definition)
  try:results=execute(tx,action,actor,'本人目标与局部可行机会',gateway)
  except (ValueError,TypeError,KeyError) as error:diag(tx,actor,'planner-action',error);continue
  rec=next((r for r in results if r.get('speech')),None)
  replies=[]
  if rec:
   if tx.definition['config'].get('card_refinement'):
    from dialogue_state import record_speech
    record_speech(tx,rec['speech'],rec['speech']['audience'])
   if 'player'in rec['observers']and spoken_frame:frames.append(spoken_frame)
   for peer in rec['speech']['audience']:
    reply=actor_reply(tx,gateway,peer,[rec['speech']],frames,actor)
    if reply:replies.append(reply)
  after_topics={c['id']for c in tx.state['cards'].values()if c['template']=='knowledge'and actor in c['visibility']}
  status='rejected'if any(r['outcome']=='rejected'for r in results)else'applied'
  if rec and not after_topics-before_topics:status='no_evidence'
  reply_status=next((s for s in('partial_information','needs_clarification','refused','system_error','no_information')if any(r['status']==s for r in replies)),None)
  if reply_status=='system_error':status='system_error'
  reasons='; '.join(r.get('public',{}).get('reason','')for r in results if r['outcome']in('rejected','held'))
  add_feedback(tx,actor,goal,action,status,scope,reason=reasons,new_topics=after_topics-before_topics,guard=guard,reply_status=reply_status)
  settle(tx,True)

def prepare_card_turn(session,definition,text,request_id,gateway=None,actions=None,module_store=None,module_refs=(),pending=None,authored=None):
 from world_turn import validated_request
 prior=session['facts']['browser_world_state'];existing=next((t for t in session['turns']if t['turn_id']==request_id),None)
 if existing:
  if existing['user']!=text:raise ValueError('Request id reused for different content')
  return {'already_saved':True,'packet':existing.get('world_packet')}
 tx=Transaction(prior,definition,request_id);tx.module_store=module_store;tx.module_refs=module_refs;frames=[];tx.world_frames=frames
 from world_memory import bind
 bind(tx,session)
 from action_guard import protagonist,precheck,refusal_turn
 tx.protagonist=protagonist(session)
 from input_grounding import player_context
 tx.player_context=player_context(session,definition)
 tx.previous_narration=[f['text'] for turn in session.get('turns',[])[-2:] for f in session['facts'].get('browser_turn_frames',{}).get(turn['turn_id'],[]) if f.get('kind')=='narration' and not f.get('system_feedback')]
 tx.prior_pending=next((copy.deepcopy(c['value']) for c in reversed(list(tx.state['cards'].values())) if c['template']=='pending_input' and c['value']['status']=='needs_clarification'),None)
 if tx.prior_pending:
  from galgame import parse_input
  parts=parse_input(text)['parts']
  if re.search(r'^(?:【[^】]+】)?\s*(?:取消|算了|不去了|不做了|放弃)',text):
   for c in tx.state['cards'].values():
    if c['template']=='pending_input' and c['value']['status']=='needs_clarification':
     old=copy.deepcopy(tx.state);c['value']['status']='cancelled'
     tx.record({'template':'builtin.input_followup','effects':[],'title':'取消待确认行动','outcome':'recorded','participants':['player'],'observers':[],'public':{},'rule_id':'input'},old)
   frames=[{'kind':'narration','speaker':'系统','system_feedback':True,'text':'已取消刚才待确认的行动，你仍在当前地点。','expression':'absent','stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}}]
   packet=tx.snapshot_packet()
   return {'already_saved':False,'state':copy.deepcopy(tx.state),'packet':packet,'frames':frames,'actions':[],'calls':[],'visible_events':[]}
  if re.search(r'教室|房间|去哪|目的地',str(tx.prior_pending.get('questions',[]))) and re.search(r'座位|桌里|抽屉|教室里还有',text) and not re.search(r'前往|走进|回到|去自己的|去.*教室',text):
   return refusal_turn(tx,{'reason':'刚才的移动还没有执行，你仍在'+tx.player_context['current_location_name']+'。请先说明要去的教室，或取消刚才的行动。','evidence':text},gateway,'needs_clarification')
 tx.require_action_review=bool(session.get('game_mode')=='world' or session.get('protagonist_snapshot'))
 if definition['config'].get('world_mode') and actions is None:
  from world_input_checks import check
  engine_request=check(tx,text)
  if engine_request:
   result=refusal_turn(tx,{'reason':engine_request['text'],'evidence':text},gateway,engine_request['kind'])
   if engine_request['kind']=='read_only':
    result['frames'][0]['text']=engine_request['text']
    if engine_request.get('narrator'):
     result['frames'][0].update(speaker='旁白',system_feedback=False)
   return result
 refusal=precheck(tx,text)if actions is None else None
 if refusal:return refusal_turn(tx,refusal,gateway)
 # Admission occurs before any bootstrap, module effect or background simulation.
 parsed=None
 if actions is None and gateway and definition['config'].get('world_mode'):
  parsed=parse_steps(tx,gateway,text)
  if getattr(tx,'input_refusal',None):
   return refusal_turn(tx,tx.input_refusal,gateway,'rejected'if tx.input_refusal['decision']=='reject'else'needs_clarification')
  if getattr(tx,'pending_input',None) and not getattr(tx,'partial_input',False):
   return refusal_turn(tx,{'reason':'\n'.join(q['question']for q in tx.pending_input['questions']),'evidence':text},gateway,'needs_clarification')
  unresolved=next((s for s in parsed[0]if s['type']=='unsupported'),None)
  if unresolved:
   return refusal_turn(tx,{'reason':'当前基础卡或剧本玩法没有这项行动的执行接口。这段输入未执行；设定允许的特殊能力也需要对应的玩法入口。','evidence':unresolved['evidence']},gateway,'needs_clarification')
 elif actions is None and not gateway and tx.require_action_review and definition['config'].get('world_mode'):
  from galgame import parse_input
  if any(p['kind']not in('speech','thought')for p in parse_input(text)['parts']):
   return refusal_turn(tx,{'reason':'当前模型审查接口尚未连接，不能执行未经审查的行动。','evidence':text},None,'needs_clarification')
 if definition['config'].get('world_mode'):
  from goal_sets import select_goals
  select_goals(tx,gateway)
 if pending:
  from world_modules import apply_legacy_effect
  old=copy.deepcopy(tx.state);tx.state['module_states'][pending['module_id']]=copy.deepcopy(pending['module_entry'])
  tx.record({'template':'builtin.module','effects':[],'title':'玩法结算','outcome':'applied','participants':['player'],'observers':['player'],'public':{}},old)
  for e in pending.get('effects',[]):
   if e['type']=='events':tx.apply(e['event'],True,'玩家玩法选择')
   else:apply_legacy_effect(tx,e,pending.get('bindings'))
 if actions is not None:
  # Explicit old action fixtures remain usable, without interpreting test inputs as real model results.
  steps=[{'type':{'transfer':'give'}.get(a['type'],a['type']), 'params':{k:v for k,v in a.items()if k not in('type','evidence')},'evidence':a['evidence']}for a in actions];recipes=[]
 elif parsed is not None:steps,recipes=parsed
 elif gateway:
  steps,recipes=parse_steps(tx,gateway,text)
 else:
  from world_turn import parse_intent
  steps=[{'type':a['type'],'params':{k:v for k,v in a.items()if k not in('type','evidence')},'evidence':a['evidence']}for a in parse_intent(text,prior,definition,None)];recipes=[]
 for recipe in recipes:register_recipe(tx,recipe)
 if getattr(tx,'input_refusal',None):
  return refusal_turn(tx,tx.input_refusal,gateway,'rejected'if tx.input_refusal['decision']=='reject'else'needs_clarification')
 if getattr(tx,'pending_input',None) and not getattr(tx,'partial_input',False):
  frames=[{'kind':'narration','speaker':'旁白','text':'\n'.join(q['question']for q in tx.pending_input['questions']),'expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}}]
  packet=tx.snapshot_packet()
  return {'already_saved':False,'state':copy.deepcopy(tx.state),'packet':packet,'frames':frames,'actions':[],
   'calls':copy.deepcopy(gateway.calls)if gateway else[],'visible_events':[],'authored_progress':None,'input_status':'needs_clarification'}
 current_pending_id='input:'+digest([tx.request_id,tx.pending_input['input']])[:20] if getattr(tx,'pending_input',None) else None
 if definition['config'].get('card_refinement') and any(s['type'] not in ('think','say','ask','answer') for s in steps):
  for cid,c in list(tx.state['cards'].items()):
   if c['template']=='pending_input'and c['value']['status']=='needs_clarification' and cid!=current_pending_id:
    old=copy.deepcopy(tx.state);value=copy.deepcopy(c['value']);value.update(status='superseded_by_new_input',next_request=request_id)
    put(tx.state,cid,'pending_input',value,['player'],['player']);tx.record({'template':'builtin.input_followup','effects':[],'title':'继续说明行动','outcome':'recorded','participants':['player'],'observers':[],'public':{},'rule_id':'input'},old)
 step_results={}
 for step_index,step in enumerate(steps):
  start=len(tx.records);kind=step['type']
  if definition['config'].get('card_refinement'):
   from input_program import condition_passes,record_skipped,resolve_result_step
   if not condition_passes(step,step_results):step_results[step_index]=[record_skipped(tx,step)];continue
   step=resolve_result_step(step,step_results,tx)
  if kind=='think':continue
  if kind=='unsupported':
   diag(tx,'player','unavailable-capability',ValueError('No checked primitive/module'))
   if definition['config'].get('card_refinement'):
    frames.append({'kind':'narration','speaker':'系统','system_feedback':True,'text':'未执行：当前基础卡或剧本玩法没有这项行动的执行接口。可以使用剧本提供的玩法入口，或说明自己的具体行动步骤。','expression':'absent','reaction_to':[],
     'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
   continue
  action={k:v for k,v in step.items()if k!='when'}
  results=execute(tx,action,'player',step['evidence'],gateway);step_results[step_index]=results
  from world_input_checks import execution_feedback
  message=execution_feedback(tx,step,results)
  if message and not any(f.get('system_feedback') and f.get('text')==message for f in frames) and not any(r['template']=='builtin.system_diagnostic'and r.get('diagnostic',{}).get('stage')=='review'for r in results):
   frames.append({'kind':'narration','speaker':'系统','system_feedback':True,'text':message,'expression':'absent','reaction_to':[],
    'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
  # A later stage receives actual outcomes, never an expectation of success.
  if kind=='explore':
   for discovered in (r.get('public',{}) for r in results if r['template']=='builtin.explore' and r['outcome']=='applied'):
    if discovered.get('discovered'):
     frames.append({'kind':'narration','speaker':'旁白','text':'你发现了'+discovered['name']+'的入口。入口就在眼前，你记住了这处地方的位置。',
      'expression':'absent','reaction_to':[],'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
  tx.execution_results=getattr(tx,'execution_results',[])+[{'index':step_index,'type':kind,'results':[{'template':r['template'],'outcome':r['outcome'],'observers':r.get('observers',[]),'public':copy.deepcopy(r.get('public',{}))}for r in results]}]
  if definition['config'].get('world_mode')and any(r['template']=='builtin.system_diagnostic'and r.get('diagnostic',{}).get('stage')=='review'for r in results):
   failed=refusal_turn(tx,{'reason':'本步行动的同意或一致性审查没有完成，这一步未执行。已有成功结果保留；可以重新说明这一步后重试。','evidence':step['evidence']},gateway,'needs_clarification')
   failed['frames']=frames+failed['frames'];failed['actions']=steps[:step_index]
   return failed
  if kind in('say','ask','answer'):
   rec=next((r for r in results if r.get('speech')),None)
   if rec:
    from read_permissions import from_speech
    from_speech(tx,gateway,rec)
    # Give recipients their actual heard utterance before actor departs; no future destination leakage.
    from speech_rules import addressed_repliers
    targets=addressed_repliers(definition,rec['speech'])
    if definition['config'].get('card_refinement'):
     from dialogue_state import record_speech
     targets=record_speech(tx,rec['speech'])
    if not rec['speech']['audience']:
     from world_presentation import place_name
     from player_feedback import no_listener
     frames.append({'kind':'narration','speaker':'旁白','text':no_listener(tx),'expression':'absent','reaction_to':[],
      'stage':{'location':location(tx.state,'player'),'present_actor_ids':[]}})
    for actor in targets:
     reply=actor_reply(tx,gateway,actor,[rec['speech']],frames)
     if reply and reply.get('status')=='system_error':
      frames.append({'kind':'narration','speaker':'系统','system_feedback':True,'text':'你的话已经说出口，但人物回应未生成成功。可以重试这句话。','expression':'absent','reaction_to':[],
       'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
    language_effects(tx,gateway,'player',rec['speech']['text']);advance_until(tx,1)
  elif kind=='knock':
   rec=next((r for r in results if r['template']=='builtin.knock' and r['outcome']=='applied'),None)
   if rec:
    for actor in [a for a in rec['observers'] if a in definition['characters']][:1]:
     actor_reply(tx,gateway,actor,[{'actor':'player','text':'门口传来敲门声。','audience':[actor],'kind':'sound','source_event':rec['event_id']}],frames)
  elif kind=='search' and re.search(r'环顾|四周|周围|附近的人',step['evidence']):
   from scene_presence import notice
   notice(tx)
  elif kind=='gesture' and re.search(r'招呼|问候',step['evidence']):
   rec=next((r for r in results if r['template']=='builtin.gesture' and r['outcome']=='applied'),None)
   if rec:
    targets=[actor for actor in rec['observers'] if actor in definition['characters']][:1]
    for actor in targets:
     actor_reply(tx,gateway,actor,[{'actor':'player','text':'眼前的人向你作出了一个简短的问候示意；没有给出具体台词。','audience':[actor],'kind':'observed_greeting','source_event':rec['event_id']}],frames)
  elif kind=='compound':
   for rec in results:
    if rec.get('speech'):
     from read_permissions import from_speech
     from_speech(tx,gateway,rec)
     from speech_rules import addressed_repliers
     targets=addressed_repliers(definition,rec['speech'])
     if definition['config'].get('card_refinement'):
      from dialogue_state import record_speech
      targets=record_speech(tx,rec['speech'])
     for actor in targets:actor_reply(tx,gateway,actor,[rec['speech']],frames)
  visible=[r for r in tx.records[start:]if'player'in r['observers']and r['template']not in('builtin.say','builtin.language_detection','builtin.goal_feedback','builtin.dialogue_context')]
  description=render_events(tx,gateway,visible)
  if description:frames.append({'kind':'narration','speaker':'旁白','text':description,'expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 # Accepted observations and stationary actions still occupy a brief moment.
 # They never prescribe NPC behaviour; refused/ambiguous inputs return above.
 idle_start=len(tx.records)
 if definition['config'].get('world_mode') and clock_time(tx.state)==clock_time(prior) and not any(s.get('type') in ('wait','rest') for s in steps):
  from galgame import parse_input
  if any(p['kind']!='thought' and '自言自语' not in p['text'] for p in parse_input(text)['parts']):
   execute(tx,{'type':'wait','params':{'minutes':1}},'player',text,gateway)
 idle_visible=[r for r in tx.records[idle_start:] if 'player' in r['observers'] and r['template'] in
  ('builtin.move','builtin.arrival','builtin.take','builtin.transfer','builtin.use','builtin.search','builtin.visible_activity','builtin.location_notice','builtin.fixed_event')]
 if idle_visible:
  description=render_events(tx,gateway,idle_visible)
  if description:frames.append({'kind':'narration','speaker':'旁白','text':description,'expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 background_start=len(tx.records);plans_due(tx,gateway)
 if definition['config'].get('world_mode'):
  from world_activity import pulse
  pulse(tx,gateway,frames)
 else:background(tx,gateway,frames)
 for rec in tx.records if definition['config'].get('card_refinement')else[]:
  if rec['template']=='builtin.system_diagnostic'and rec.get('diagnostic',{}).get('stage')in('detector','intent')and rec.get('participants')==['player']:
   if definition['config'].get('world_mode')and any(r['template']=='builtin.decline'and r['outcome']=='applied'and 'player'in r['participants']for r in tx.records):continue
   frames.append({'kind':'narration','speaker':'旁白','text':'话已经说出口，相关行动还没有完成。你可以再说明打算怎样行动。','expression':'absent','reaction_to':[],
    'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 skipped=[r for r in tx.records if r['template']=='builtin.condition_skipped']
 if skipped:frames.append({'kind':'narration','speaker':'旁白','text':'前置条件未成立，你没有继续执行后续行动。','expression':'absent','reaction_to':[],
  'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 observed_background=[r for r in tx.records[background_start:]if'player'in r['observers']and r['template']in('builtin.move','builtin.arrival','builtin.take','builtin.transfer','builtin.use','builtin.search','builtin.visible_activity','builtin.location_notice','builtin.fixed_event')]
 if observed_background:
  description=render_events(tx,gateway,observed_background)
  if description:frames.append({'kind':'narration','speaker':'旁白','text':description,'expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 if not frames:
  from card_refinement import render_events as describe
  quiet=describe(tx,gateway,[],allow_quiet=True) if definition['config'].get('world_mode') else '周围暂时安静下来。'
  frames=[{'kind':'narration','speaker':'旁白','text':quiet,'expression':'absent','reaction_to':[],
  'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}}]
 if getattr(tx,'partial_input',False):
  for cid,c in list(tx.state['cards'].items()):
   if cid==current_pending_id and c['template']=='pending_input'and c['value']['status']=='needs_clarification':
    old=copy.deepcopy(tx.state);value=copy.deepcopy(c['value'])
    value['completed_prefix']=[s['evidence'] for i,s in enumerate(steps) if step_results.get(i) and all(r['outcome']=='applied' for r in step_results[i])]
    put(tx.state,cid,'pending_input',value,['player'],['player'])
    tx.record({'template':'builtin.input_followup','effects':[],'title':'独立动作已执行，后续待说明','outcome':'recorded','participants':['player'],'observers':[],'public':{},'rule_id':'input'},old)
  frames.append({'kind':'narration','speaker':'系统','system_feedback':True,'text':'后续部分尚未执行：'+'；'.join(q['question']for q in tx.pending_input['questions']),
                 'expression':'absent','stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 progress=None
 if authored:
  from world_authored import settle_authored_free
  progress=settle_authored_free(tx,*authored)
 long_wait=any(s.get('type')in('wait','rest') and s.get('params',{}).get('minutes',0)>=240 for s in steps)
 if long_wait:
  clock=tx.state['clock'];gaps=[c for c in tx.state['cards'].values() if c['template']=='simulation_gap' and c['id']=='simulation:'+tx.request_id]
  note=f"时间已推进到第 {clock['day']} 天 · {clock['minute']//60:02d}:{clock['minute']%60:02d}。"
  if gaps:note+='这段较长的等待没有逐一演出全部人物活动；未实际结算的目标不会因此视为完成。'
  frames.append({'kind':'narration','speaker':'系统','system_feedback':True,'text':note,'expression':'absent','reaction_to':[],
   'stage':{'location':location(tx.state,'player'),'present_actor_ids':visible_actor_ids(tx.state,definition)}})
 packet=tx.snapshot_packet()
 return {'already_saved':False,'state':copy.deepcopy(tx.state),'packet':packet,'frames':frames,'actions':steps,
  'calls':copy.deepcopy(gateway.calls)if gateway else[],'visible_events':choose_presentation(tx.records),'authored_progress':progress,
  **({'input_status':'needs_clarification'} if getattr(tx,'partial_input',False) else {})}

def render_events(tx,gateway,records):
 if tx.definition['config'].get('card_refinement'):
  from card_refinement import render_events as refined_render
  return refined_render(tx,gateway,records)
 records=[r for r in records if r['template']not in('builtin.time','builtin.rule_activation','builtin.rule_deferred','builtin.system_diagnostic')]
 fallback='；'.join(event_description(r,tx.definition,False,tx.state)for r in records)
 if not records or not gateway:return fallback
 from world_turn import validated_request,NARRATOR
 visible=[{'template':r['template'],'outcome':r['outcome'],'observed':event_description(r,tx.definition,False,tx.state),'public':r.get('public',{})}for r in records]
 def valid(a):
  if not isinstance(a.get('text'),str):raise ValueError('Narrator needs string text')
  verify_prose(tx,'player',a['text'],records)
 try:return validated_request(gateway,'narrator',NARRATOR,{'view':build_player_view(tx.state,tx.definition),'visible_events':visible},valid,550)['text']
 except (ValueError,TypeError,KeyError) as error:diag(tx,'player','narrator',error);return fallback
