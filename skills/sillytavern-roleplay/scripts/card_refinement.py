"""Opt-in refinement, retaining shell cards and branch authority. No production installation."""
import copy,json,re
from world_state import read,put,colocated,location,clock_time
from actor_context import event_description,authorize_claims,build_actor_view
from basic_cards import expand,normalize_action
from fact_ledger import build_ledger,validate_references,audit_expression
from model_context import working_view,stable_contract
from dialogue_state import record_speech,actor_dialogue,classify_reply,response_targets
from language_actions import detect,validate_candidates
from card_validation import verify_prose,preflight

PERSON='''扮演view本人，仅JSON {text,thought,expression,claims:[],actions:[],candidates:[],references:[]}。
按性格自然回答dialogue.heard_now的问题，dialogue.answer_to是你答话的对象，不是另一个扮演者。你知道自己静态身份，但不能捏造管理职责。陌生人可以拒绝、问明来意、安静，不替玩家决定。
text只填写实际说出口的台词，不用引号包裹台词再穿插第一人称叙述；“我重复了一遍、我抬眼、我心想”等不得放进text。保留语气、停顿和观点，短答可以自然短答，不为凑字编造事件。
thought填写本人当下没有说出口的内心独白，独立保存到人物心声；有真实想法时填写，没有时可为空。它不是对白、没有听众，也不是已执行动作。动作只通过actions或candidates提议，不在text夹写动作旁白。
claims使用本人可披露knowledge ID，只说明引用；听者仅获得text实际说出的信息。references项{source:ledger事实ID,evidence:逐字text片段}；过去经历、人物身份、实物变化、路线需实际来源，普通语气无需引用。
actions最多2个{type,params}，仅本人未在text表达的动作。candidates按语言行动协议最多4项{kind,actor:view.actor_id,evidence:逐字text,action:{type,params}}，未来计划可due_in。普通对白candidates=[]。请求别人用request，不控制别人。过去/如果/未来不即时执行。不说未结算交接/到达已成功。找不到来源可询问或承认不知道，不必逐字背知识卡。'''
NARRATOR='''仅JSON {text,references:[]}，根据ledger与events写玩家可见的环境和真实行动结果。references项{source:ledger事实ID,evidence:逐字text片段}。source必须完整使用ledger.facts中的键（包括event:前缀），evidence必须逐字出现在本次text，不是事件摘要；不确定时references=[]，文字仍会核对事实。
允许自然、连贯的文学描写和光影/气味等非交互修辞，不改变持有者、位置、数量、人物在场、门状态或任务结果。物品拿在主角手里不能又躺在架上。未指定天气不擅自下雨；不新增可互动物品、房间、声音来源人物。不补写玩家心理或他人秘密。失败/未触发条件如实表达。一般约80—160字，安静时可短些，不输出系统解释。'''
NARRATOR+=' 接受阅读邀请不表示已经阅读或正在阅读；只有真实read事件或read来源的知识证明阅读。不要顺手/随手替主角放下、拿起或交接物品，主角互动行动必须有实际结算事件。'
NARRATOR+=' 笔记的written_content只是主角写的字，不是客观事实来源；先确认不等于已经确认，完成阅读不等于已经填表、核实或批准。'
PERSON+=' personal_memory是本人听过的原文，优先按问题查retrieved，不因recent中没有就忘记。区分对方自述与客观事实。别人说“交给你保管”不证明实际收到物品，实际owner以ledger为准。未知偏好、家庭、日期不猜。current_time为权威时钟，不虚构手机/钟表；occupancy包含自己，回答在场问题要算上所有人，姓名未知就用描述。expression只填写neutral/thinking/soft/annoyed/sad/surprised等表情代号，不填表情描写。references.source须完整使用ledger.facts中的键，包括memory:前缀，原文序号不是source。'
PERSON+=' recall_focus是按本次问题匹配的实际听闻原句。回答过去的信息时先核对原句，不能只因没有接受约定或没有管理职责就忽略对方说过的日期/经费；可以回答“你说过X，但我没答应/没有核实”。经费、部费、预算可指同一个话题。不凭空指定另一人物管理经费。人物可主动拒绝透露，但不要把有来源的记忆说成从未听过。'
PERSON+=' personal_activity_history提供本人实际到场与模拟空白。回答“这几天做了什么”只陈述实际记录或明确开场背景，不因性格推断曾去庭院散步；空白可说无法确认，没有记录也不能说从未发生。'
PERSON+=' public_schedule是所有人可知的公告，不需等待现场观察才知道时间；它只证明公开安排，不证明参加或结果。引用公告使用references.source="public-schedule"，不要放入仅允许knowledge卡ID的claims。把时间写成自然时刻，不向玩家报内部分钟数。别人邀请参加活动时，结合本人目标、日程、好感、熟悉程度、信任自主决定，可拒绝或改约；同意时用candidates表达本人去现场的计划，不替邀请者做决定。'
NARRATOR+=' 不向玩家描述系统关系分数、信任熟悉初始值、校验、判定、目标卡或数据状态；关系只能通过实际可见的态度呈现。'
NARRATOR+=' 不逐项朗读ledger，不写“主人是你”“实际听到了她的名字”“没有事情被推动”等数据说明；安静时简短描写眼前的光线与可见人物即可。observe必须保留实际观察对象，看笔记本不等于环顾四周、翻开阅读或放下笔记本。'

def action_language(text):
 return bool(re.search(r'(?:我|你|咱们|我们).{0,22}(?:现在|马上|这就|去|前往|离开|拿|递|交给|放下|读|使用|吃|搜索|寻找|休息|等待|打算|准备|答应|拒绝|接受|帮|攻击|防御)|(?:不接|不接受|接受|拒绝).{0,8}(?:委托|任务)',text))

def parse_steps(tx,gateway,text):
 from galgame import parse_input
 from card_runtime import parser_view,diag
 from input_program import parse_free,record_clarification
 steps=[];recipes=[];questions=[]
 for p in parse_input(text)['parts']:
  content=p['text']
  if p['kind']=='thought'or'自言自语'in content:steps.append({'type':'think','params':{'text':content},'evidence':content});continue
  if p['kind']=='speech':steps.append({'type':'say','params':{'text':content},'evidence':content});continue
  try:program=parse_free(tx,gateway,content,parser_view(tx.state,tx.definition),p['kind'])
  except (ValueError,TypeError,KeyError)as e:
   diag(tx,'player','parser',e)
   from input_grounding import GroundingError
   if isinstance(e,GroundingError):
    tx.pending_input=record_clarification(tx,text,[{'question':str(e),'evidence':content}])
    tx.input_refusal={'decision':'clarify','category':'uncertain','reason':str(e),'evidence':content};return [],[]
   if tx.definition['config'].get('world_mode'):
    tx.input_refusal={'decision':'clarify','category':'uncertain','reason':'行动解析或能力审查暂未完成，这段输入未执行。可以重新说明自己的行动后再试。','evidence':content};return [],[]
   questions.append({'question':'你准备对哪个对象做什么？请把这段行动再说明一下。','evidence':content});continue
  if program.get('review',{}).get('decision')in('reject','clarify'):
   if program['review']['decision']=='clarify':
    tx.pending_input=record_clarification(tx,text,[{'question':program['review']['reason'],'evidence':content}])
   tx.input_refusal=program['review'];return [],[]
  if program['clarifications']:
   questions.extend(program['clarifications'])
   if program.get('partial'):
    steps.extend(program['steps']);tx.partial_input=True;break
   continue
  base=len(steps)
  for s in program['steps']:
   if 'when'in s:s['when']['after']+=base
  steps.extend(program['steps']);recipes.extend(program['recipes'])
 if questions:tx.pending_input=record_clarification(tx,text,questions[:3])
 if len(steps)>12 or len(recipes)>4:raise ValueError('Input exceeds bounded complexity')
 return steps,recipes

def actor_reply(tx,gateway,actor,heard,frames,listener='player'):
 from scene_presence import can_hear,visible_actor_ids
 if not gateway or actor=='player'or not can_hear(tx.state,tx.definition,actor,listener):return None
 from world_turn import validated_request,actor_frame,stage_feedback
 from card_runtime import scoped_claims,diag,execute,language_effects
 view=working_view(tx,actor,heard);dialogue=actor_dialogue(tx,actor,heard,listener);ledger=build_ledger(tx,actor,tx.records,view=view)
 disclosure=None
 if tx.definition['config'].get('world_mode'):
  from goal_disclosure import permitted,filter_reply
  disclosure=permitted(tx,actor,listener,heard,gateway)
  view,ledger=filter_reply(tx,actor,view,ledger,disclosure)
 def valid(a):
  from speech_channels import separate_response
  separate_response(a)
  from world_memory import validate_recall_answer
  validate_recall_answer(view,dialogue,a.get('text',''))
  if not isinstance(a.get('text'),str)or not isinstance(a.get('thought',''),str):raise ValueError('Invalid actor text')
  a['claims']=scoped_claims(a.get('claims',[]),view);authorize_claims(view,a['claims'],a['text'])
  verify_prose(tx,actor,a['text']);verify_prose(tx,actor,a.get('thought',''),private=True)
  if disclosure is not None:
   from goal_disclosure import check_text
   check_text(tx,actor,a['text'],disclosure)
  a['_reference_error']=False
  try:validate_references(a.get('references',[]),a['text'],ledger)
  except ValueError:a['_reference_error']=True;a['references']=[]
  recall_question=any(re.search(r'昨天|这几天|最近|做了什么|去过|记得|编号|经费|之前|上次|约好|约定|我(?:喜欢|喝|叫什么)|我说|几个人|都有谁|有谁|几点|现在的时间',r.get('text',''))for r in heard)
  flags=audit_expression(tx,gateway,actor,a['text'],ledger,dialogue,force=a['_reference_error'] or recall_question)
  if flags:raise ValueError('Expression contradicts settled sources: '+json.dumps(flags,ensure_ascii=False))
  a['_intent_error']=None
  try:
   actions=a.get('actions',[])
   if not isinstance(actions,list)or len(actions)>2:raise ValueError('Unbounded actions')
   a['actions']=[normalize_action(x,tx.state,tx.definition,actor)for x in actions]
   for x in a['actions']:expand(x,tx.state,actor)
   if 'candidates'in a:a['candidates']=validate_candidates({'candidates':a['candidates']},a['text'],actor,tx.state,tx.definition)
  except (ValueError,TypeError,KeyError)as e:
   a['_intent_error']=type(e).__name__;a['actions']=[];a['candidates']=[]
 stage_feedback(gateway,'actor:'+actor,tx,actor)
 try:a=validated_request(gateway,'actor:'+actor,stable_contract(PERSON+' 对view.disclosure_policy允许范围之外的目标不透露，不主动说自己的目标；summary只泛称处理自己的事；没有获准目标资料时可以含蓄拒绝询问，不猜自己的隐私。'),{'view':view,'dialogue':dialogue,'ledger':ledger},valid,1300)
 except (ValueError,TypeError,KeyError)as e:diag(tx,actor,'actor',e);return {'status':'system_error','text':''}
 text=a['text'];candidates=a.get('candidates',[]);intent_error=a.get('_intent_error')
 thought_frame=actor_frame(actor,a['thought'],'thinking',tx.state,tx.definition,True)if a.get('thought')and colocated(tx.state,actor,'player')else None
 if a.get('_reference_error'):diag(tx,actor,'reference-format',ValueError('Invalid annotation removed; scoped semantic review passed'))
 if intent_error:diag(tx,actor,'intent',ValueError('Action proposal invalid; speech isolated'))
 elif action_language(text)and not candidates:
  try:candidates=detect(gateway,text,actor,tx.state,tx.definition,view)
  except (ValueError,TypeError,KeyError)as e:diag(tx,actor,'detector',e);intent_error=type(e).__name__
 # Actions and expression are independent. Preserve safe speech if an intent detector fails.
 proposed=[c['action']for c in candidates if c['kind']=='immediate']+a.get('actions',[])
 completed=bool(proposed or intent_error)and bool(re.search(r'已经.{0,12}(?:拿到|交给|到达|完成|吃完|放下)|成功(?:交给|拿到|完成)|递到你手里',text))
 if completed:
  # Do not publish completed prose before settlement. Unsupported completion gets a local rewrite.
  outcomes=[]
  if not intent_error:
   for action in proposed:outcomes.extend(execute(tx,action,actor,text,gateway))
  ledger_after=build_ledger(tx,actor,tx.records)
  try:
   if intent_error or not proposed:raise ValueError('Completed action lacks execution evidence')
   verify_prose(tx,actor,text,outcomes)
   if audit_expression(tx,gateway,actor,text,ledger_after,dialogue,True):raise ValueError('Completion expression needs correction')
  except (ValueError,TypeError,KeyError):
   def correction(x):
    from speech_channels import separate_response
    separate_response(x)
    if not isinstance(x.get('text'),str):raise ValueError('Correction needs text')
    verify_prose(tx,actor,x['text'],outcomes)
    if audit_expression(tx,gateway,actor,x['text'],ledger_after,dialogue,True):raise ValueError('Correction not grounded')
   try:text=validated_request(gateway,'expression-rewrite:'+actor,'只修正对白text，不提新动作、不修改世界。保留人物口吻，未发生不能说已经完成。JSON {text}。',{'ledger':ledger_after,'dialogue':dialogue,'original':text,'outcomes':[r['outcome']for r in outcomes]},correction,900)['text']
   except (ValueError,TypeError,KeyError)as e:diag(tx,actor,'expression-rewrite',e);text='这件事还没有做成。'if outcomes else'我还不能确认这件事。'
  candidates=[];a['actions']=[]
 before={c['id']for c in tx.state['cards'].values()if c['template']=='knowledge'and listener in c['visibility']}
 if tx.definition['config'].get('world_mode'):
  from spoken_sources import recover
  a['claims']=recover(tx,gateway,actor,text,view,a['claims'])
 frame=actor_frame(actor,text,a.get('expression','neutral'),tx.state,tx.definition)
 if text and can_hear(tx.state,tx.definition,actor,listener):
  audience=[peer for peer in[*tx.definition['characters'],'player']if peer!=actor and can_hear(tx.state,tx.definition,actor,peer)]
  # Approved private disclosure is physically addressed quietly to the checked listener.
  quiet_disclosure=disclosure is not None and disclosure['level']in('summary','full')
  if quiet_disclosure:audience=[listener]
  rec=tx.apply({'template':'builtin.say','actor':actor,'text':text,'claims':a['claims'],'audience':audience,**({'whisper':True}if quiet_disclosure else{})},evidence=text)
  if disclosure is not None:
   from goal_disclosure import record_shared
   for recipient in audience:record_shared(tx,actor,recipient,disclosure if recipient==listener else {'level':'none','goal_ids':[]},text)
  record_speech(tx,rec['speech'],[listener])
  if tx.definition['config'].get('world_mode'):
   from read_permissions import from_speech
   from_speech(tx,gateway,rec)
  if 'player'in rec['observers']:frames.append(frame)
  if not intent_error:
   language_effects(tx,gateway,actor,text,candidates)
   detected=[c['action']for c in candidates if c['kind']=='immediate']
   for action in a.get('actions',[]):
    if action not in detected:execute(tx,action,actor,text,gateway)
 if thought_frame:frames.append(thought_frame)
 after={c['id']for c in tx.state['cards'].values()if c['template']=='knowledge'and listener in c['visibility']}
 return {'status':classify_reply(text,after-before),'text':text,'new_topics':list(after-before),'intent_status':'error'if intent_error else'ready'}

def render_events(tx,gateway,records,allow_quiet=False):
 from card_runtime import diag
 from world_turn import validated_request
 records=[r for r in records if r['template']not in('builtin.time','builtin.rule_activation','builtin.rule_deferred','builtin.system_diagnostic','builtin.dialogue_context')]
 # Engine refusal belongs to explicit feedback, never a narrator's imagined scene.
 records=[r for r in records if r.get('outcome') not in ('rejected','held','error')]
 from scene_presence import visible_actor_ids
 nearby=set(visible_actor_ids(tx.state,tx.definition,'player'))
 records=[r for r in records if r['template'] not in ('builtin.offer','builtin.accept','builtin.decline','builtin.complete')
          or r.get('public',{}).get('actor') in nearby|{'player'}]
 if not records and not allow_quiet:return ''
 ledger=build_ledger(tx,'player',records)
 from actor_context import is_story_event
 fallback='\n'.join(dict.fromkeys('你没有继续执行尚未满足条件的后续行动。'if r['template']=='builtin.condition_skipped'else event_description(r,tx.definition,False,tx.state)
                   for r in records if is_story_event(r) or r['outcome']=='rejected' or r['template']=='builtin.condition_skipped'))
 from world_presentation import story_text
 fallback=story_text(fallback,tx.definition,tx.state)
 if not records:fallback='片刻过去，眼前没有新的动静。'
 from room_presence import ensure_arrivals
 if not gateway:return ensure_arrivals(tx,records,fallback)
 def valid(a):
  if not isinstance(a.get('text'),str):raise ValueError('Narrator requires text')
  a['text']=story_text(a['text'],tx.definition,tx.state)
  if a['text'] in getattr(tx,'previous_narration',[]):raise ValueError('Do not repeat the previous narration verbatim; describe only the present settled change')
  if re.search(r'目标卡|状态数据库|系统(?:判断|校验)|(?:信任|熟悉|好感).{0,12}(?:初始值|初始位置|最初的位置|数值|分数)',a['text']):raise ValueError('Narrator must describe observable story, not internal relationship or validation state')
  verify_prose(tx,'player',a['text'],records)
  from fact_ledger import verify_player_narration
  verify_player_narration(tx,a['text'],records)
  a['_reference_error']=False
  try:validate_references(a.get('references',[]),a['text'],ledger)
  except ValueError:a['_reference_error']=True;a['references']=[]
  flags=audit_expression(tx,gateway,'player',a['text'],ledger,{'events':[f for k,f in ledger['facts'].items()if k.startswith('event:')]},True)
  if flags:raise ValueError('Narration conflicts with settled facts: '+json.dumps(flags,ensure_ascii=False))
 try:
  answer=validated_request(gateway,'narrator',NARRATOR,{'ledger':ledger,'events':[{'id':r['event_id'],'outcome':r['outcome'],'template':r['template']}for r in records],'avoid_repeating':getattr(tx,'previous_narration',[])},valid,900)
  if answer.get('_reference_error'):diag(tx,'player','reference-format',ValueError('Invalid annotation removed; scoped semantic review passed'))
  return ensure_arrivals(tx,records,answer['text'])
 except (ValueError,TypeError,KeyError)as e:diag(tx,'player','narrator',e);return ensure_arrivals(tx,records,fallback)
