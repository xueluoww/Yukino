"""Source-owned free programs and result guards; ambiguity never becomes silent success."""
import copy,re
from event_schema import digest
from basic_cards import normalize_action,expand,validate_recipe
from world_state import put,read

PROMPT='''解释input的自由行动，JSON {"steps":[],"recipes":[],"clarifications":[]}。steps每项 {type,params,source,when可选}，when在步骤顶层，不在params里；source是sources实际原句片段编号，不能引用旧对白。也接受evidence逐字连续原文。
不要造人、物品、地点或权限；只提出本人尝试，不保证成功。普通身体/环境动作没有实现接口时unsupported并保留原文，不能改成think吞掉。
动作、对象、范围、条件分开。沿书架/周围寻找是search，target仅物品类型ID或省略；不是新增家具。“寻找X，找到后拿起”是search(target物品类型ID)后take(instance实例ID)，尚未发现实例可instance="found:物品类型ID"，壳只从本轮真实搜索结果绑定实例。take加when={after:前一个search的0起始索引,outcome:"found"}。其它明确先成功再下一步用outcome:"applied"。不执行未满足条件。不将物品所有权、未来意图当已完成事实。
无法唯一确定重要目标时clarifications=[{question:简短问清目标的问题,source:对应编号}]，不要乱挑。未实现的自然语言条件也需澄清，不能先执行。内心不公开，语言不改写，配方只能已有原语，无执行代码。最多12步、4配方、3澄清。'''
PROMPT+=' complete(id)是已有接口：明确要完成已接受委托时，用view.action_targets.opportunities中匹配的accepted委托ID；不需要模型保证条件已满足，壳会结算。仅有一个匹配已接受委托时不要再问是否指它；不能把接下/核对/已完成混为一谈。'
PROMPT+=' 地点必须按view.scene_context.current_location和recent_local_speech审查语义。交谈时“走进教室/进入教室”可指眼前活动室，不能仅因为词库有classroom就切换过去；“自己的班级教室/我们班/本班”使用已知的own_classroom。单独“前往教室/回教室”在没有具体其他房间指代时，也使用已知own_classroom；未知或仍有歧义才澄清，不能随机选择别人的班。阅读对象要符合输入的物品类型，书不等于笔记本或申请单；没有可取得的书时先澄清，不用其他可读物品替代。'
PROMPT+=' input_kind区分action与environment。环境里的光线、安静、时间流逝是局部观察，不是强制改变别人；review.category=observation允许steps=[]，不新增人物状态。时间流逝可wait(minutes=1)，明确时长才使用该时长，不能改日期或强迫人物沉默。坐着/坐下用sit(params={})，看着笔记本封面用observe(target实例ID)，翻开阅读才用read(instance实例ID)；不能给sit附加chair/location/minutes。普通手势用gesture(text原文)。合法动作使用固定合同中的required/optional字段；不知道确切阅读对象时问清是哪本，不以unsupported掩盖对象不明确。'
PROMPT+=' 环顾四周/观察周围用search(params={})，不要observe(target=周围/环境)。open/close只用于门(id=view.doors中id)。翻开/合上笔记本或书页用open_item/close_item(instance)，不等于read，不取得内容知识；明确读内容才read。写笔记可open_item后write，不要求读旧内容。坐起身用sit_up而不是sit；必须此前躺下，躺下用lie_down。早上醒来不是凭空从夜晚推进到早晨。敲门knock(location=门内房间)。view.pending_input是尚未执行的行动；本轮回答其问题时可补全那个行动，对象必须仍有效且动作证据来自本轮说明。玩家可取消或改变行动；未确认移动前不能在目的地做动作。'
PROMPT+=' 普通身体动作（点头、招手、清嗓子、轻敲桌面、打招呼但没写具体台词）用gesture(text=逐字动作片段)，可以顺序组合，不需要新增能力。敲桌子不是敲门。“坐下并打招呼”拆sit和gesture，不能unsupported。明确写出“说：你好”或引号里的具体台词才可say(text=逐字实际台词)，不为“打招呼/说一句问候”编造问候内容。后续交接引用先前物品，执行时仍检查真实持有人；不要预先宣称成功。'
PROMPT+=' pending_input.completed_prefix是先前已成功执行的独立步骤，回答澄清时只补全尚未执行的部分，不重复这些步骤。'
PROMPT+=' view.exploration_scopes存在时，明确探索当前区域用explore(scope其中的ID)，不是搜索物品search；首次提到的地点不能造ID。父区域移动使用本人已知唯一入口；未定位就澄清，不凭名称创建新楼或房间。没有exploration_scopes时保持既有动作接口。'
PROMPT+=' “刚发现的那个房间/刚才发现的那间”按view.recent_discoveries绑定，只有一个匹配时使用其id，不要求玩家背地名；多个匹配才澄清。该列表只含本人实际探索发现，不是全世界地点。移动失败仍由壳检查路线和入口，不假设已经进去。'
PROMPT+=' 寻找附近的房间、门口或通路，包括“沿着通道看看有没有其他房间”，是explore而非物品search；scope使用当前所在可探索父区域的ID，不创造目标房间ID。不把单纯看物品改成探索地点。'
PROMPT+=' 日常小额购买仅用view.daily_offers，buy(item=报价中的类型ID,quantity=实际数量)，不需要造商贩或贩卖机。地点没有报价就不能买。买普通书不推断具体书名和正文。买后递给别人：buy后give(instance="purchased:类型ID",target=真实在场人物)，give.when={after:buy步骤的0起始索引,outcome:"applied"}；程序绑定本轮实际购买实例，不能提前宣称收到。具体现金交易仍用trade_offers与pay物品。乘公交等普通交通用move(location=已知真实目的地)，过程可简写，实际路线耗时仍执行，车票不赋予不存在的路线。'
PROMPT+=' 喝一口/抿一口/吃一口用eat(instance=实际持有实例,portion="small",quantity=1)，不是消耗整瓶或整件。明确喝完/吃掉才portion="all"。拒绝或澄清使用玩家能理解的自然语言，不说daily_offers、报价、日常售卖处，不编店铺数量或来访经历。'

def literal_purchase(tx,text):
 """Only a complete generic purchase, backed by a currently declared offer.

 Specific titles, destinations, conditions, speech and mixed actions remain
 model-reviewed. Ownership, opening hours and money still execute in the shell.
 """
 m=re.fullmatch(r'(?:我)?(?:再|再来|继续)?(?:买|购买)([一二两三四五六七八九十]|[1-9][0-9]?)(本(?:普通)?(?:书|书籍)|瓶(?:瓶装)?水|罐(?:罐装)?咖啡|份(?:普通)?点心|张(?:普通)?车票)[。！!\s]*',text.strip())
 if not m:return None
 goods={'本书':'daily-book','本普通书':'daily-book','本书籍':'daily-book','本普通书籍':'daily-book',
        '瓶水':'daily-water','瓶瓶装水':'daily-water','罐咖啡':'daily-coffee','罐罐装咖啡':'daily-coffee',
        '份点心':'daily-snack','份普通点心':'daily-snack','张车票':'daily-ticket','张普通车票':'daily-ticket'}
 iid=goods[m[2]]
 from daily_life import offers
 if iid not in {o['item'] for o in offers(tx.state,tx.definition,'player')}:return None
 qty=int(m[1]) if m[1].isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}[m[1]]
 return {'steps':[{'type':'buy','params':{'item':iid,'quantity':qty},'evidence':text}], 'recipes':[], 'clarifications':[],
         'review':{'decision':'allow','category':'own_action','reason':'普通物品类别已有购买来源，具体条件由程序结算。','evidence':text}}

def literal_wait(text):
 """Complete grammar only; no mixed action, hypothetical, speech or coerced result."""
 m=re.fullmatch(r'(?:我)?(?:在这里|原地|安静地|继续)?(?:等待|等|休息)\s*([+-]?\d+)\s*(分钟|小时|天)[。！!\s]*',text.strip())
 if not m:return None
 minutes=int(m[1])*{'分钟':1,'小时':60,'天':1440}[m[2]]
 if not 0<=minutes<=10080:raise ValueError('等待时间必须为0到10080分钟。')
 return {'steps':[{'type':'wait','params':{'minutes':minutes},'evidence':text}], 'recipes':[],'clarifications':[],
  'review':{'decision':'allow','category':'own_action','reason':'纯等待时长由程序规则校验，不由模型增设上限。','evidence':text}}

def completion_candidate(tx,text):
 """Resolve an explicit single completion intent, not a wish or arbitrary objective."""
 if len(sources(text))!=1 or not re.match(r'^(?:我)?(?:完成|交差)',text)or re.search(r'如果|假如|打算|准备|想|不|别|没有',text):return None
 if not re.search(r'委托|任务',text):return None
 offers=[c for c in tx.state['cards'].values()if c['template']=='opportunity'and 'player'in c['visibility']and c['value'].get('status')=='accepted']
 matches=[]
 for c in offers:
  title=c['value']['title'];terms=[c['id'][6:],title]
  for item in tx.definition['items'].values():
   name=item['name'].split('的')[-1]
   for term in [name,*item.get('aliases',[]),name[-3:]if len(name)>3 else name]:
    if term and term in title:terms.append(term)
  if any(term in text for term in terms):matches.append(c)
 if len(matches)!=1:return None
 return {'type':'complete','params':{'id':matches[0]['id'][6:]},'evidence':text}

def sources(text):
 parts=[];offset=0
 for m in re.finditer(r'[^，,；;。！？\n]+[，,；;。！？\n]?',text):
  piece=m.group().strip();start=m.start()+len(m.group())-len(m.group().lstrip())
  if piece:parts.append({'id':len(parts),'text':piece,'start':start,'end':start+len(piece)})
 return parts or[{'id':0,'text':text,'start':0,'end':len(text)}]

def ordinary_gesture(text):
 if re.fullmatch(r'(?:我)?(?:然后|接着|随后)?(?:问(?:一句|声)?好|说(?:一句|声)你好|打(?:个|声)招呼)[。！!，,\s]*',text):return True
 return bool(re.fullmatch(r'(?:我)?(?:然后|接着|随后)?(?:轻轻|轻|很安静地)?(?:清(?:了清|清)?(?:嗓子|喉咙)|(?:打个|打|说出一句(?:很短的)?|说一句(?:简短的)?)(?:招呼|问候)|点(?:了点)?头|挥(?:了挥)?手|招(?:了招)?手|敲(?:了)?(?:三下|几下|一下|两下)?(?:桌子|桌面))[。！!，,\s]*',text))

def resolve_gesture_review(tx,text,answer,review):
 # A question about the wording of a generic greeting can be resolved as a
 # nonliteral social signal. Never override model rejection, ability/ownership
 # review, object ambiguity or any action outside this complete small grammar.
 if review['decision']=='clarify' and review['category'] in ('own_action','uncertain') and re.search('台词|原话|问候',review['reason']) and all(ordinary_gesture(p['text'])for p in sources(text)):
  program=validate_program(answer,text,tx)
  if program['steps'] and not program['clarifications'] and all(s['type']=='gesture' for s in program['steps']):
   return {'decision':'allow','category':'own_action','evidence':text,'reason':'普通身体动作与问候示意可由原语结算；不编造主角的具体台词。'}
 return review

def independent_gesture_prefix(tx,text,answer,review):
 # Only bounded ordinary gestures before the unresolved clause, never a rejection
 # or a condition depending on it. The pending remainder cannot execute yet.
 if review['decision']!='clarify' or review['category']not in ('own_action','uncertain'):return None
 if not ordinary_gesture(sources(text)[0]['text']):return None
 if re.search(r'如果|假如|只有|否则|等到|才能|才会|之前必须',text):return None
 program=validate_program(answer,text,tx)
 if not program['clarifications']:return None
 boundary=min(text.find(q['evidence']) for q in program['clarifications'])
 prefix=[]
 for step in program['steps']:
  if step['type']!='gesture' or step.get('when') or not ordinary_gesture(step['evidence']) or text.find(step['evidence'])>=boundary:break
  prefix.append(step)
 if not prefix:return None
 program['steps']=prefix;program['recipes']=[];program['partial']=True
 program['review']={'decision':'allow','category':'own_action','evidence':text,'reason':'只执行已审查的独立普通示意，后续未确定部分仍须澄清。'}
 return program

def validate_program(answer,text,tx):
 tx.grounding_input=text
 spans=sources(text);steps=copy.deepcopy(answer.get('steps'));recipes=answer.get('recipes',[]);questions=copy.deepcopy(answer.get('clarifications',[]))
 if not isinstance(steps,list)or len(steps)>12 or not isinstance(recipes,list)or len(recipes)>4 or not isinstance(questions,list)or len(questions)>3:raise ValueError('Unbounded input program')
 # One source ID wrapped in a singleton array has exactly the same provenance.
 # Multi-source arrays remain invalid: they cannot collapse separated clauses.
 for node in [*steps,*questions]:
  if isinstance(node,dict) and isinstance(node.get('source'),str) and re.fullmatch(r'0|[1-9][0-9]*',node['source']):
   node['source']=int(node['source'])
  elif isinstance(node,dict) and isinstance(node.get('source'),str):
   literal=node['source']
   matches=[p for p in spans if literal and literal in p['text']]
   if len(matches)==1 and text.count(literal)==1:
    if node in steps:
     if node.get('evidence',literal)!=literal:raise ValueError('Conflicting source evidence')
     node.pop('source');node['evidence']=literal
    else:node['source']=matches[0]['id']
  if isinstance(node,dict) and isinstance(node.get('source'),list):
   if len(node['source'])!=1 or type(node['source'][0])is not int:raise ValueError('Source must identify one original clause')
   node['source']=node['source'][0]
 temporary=copy.deepcopy(tx.state)
 # A generic greeting is a social signal, not a licence to invent a quoted player
 # utterance. Resolve only a complete, explicitly benign source clause. Objects,
 # conditions and literal speech still require their normal clarification checks.
 unresolved_questions=[]
 for q in questions:
  index=q.get('source') if isinstance(q,dict) else None
  earlier=all((s.get('source',0) if type(s.get('source',0))is int else 0)<=index for s in steps) if type(index)is int else False
  if type(index)is int and 0<=index<len(spans) and earlier and ordinary_gesture(spans[index]['text']):
   evidence=spans[index]['text']
   if not any(s.get('evidence')==evidence or s.get('source')==index for s in steps):
    steps.append({'type':'gesture','params':{'text':evidence},'source':index})
  else:unresolved_questions.append(q)
 questions=unresolved_questions
 for recipe in recipes:
  r=validate_recipe(recipe);temporary['cards']['recipe:'+r['id']]={'value':{'recipe':r}}
 for index,s in enumerate(steps):
  if not isinstance(s,dict)or set(s)-{'type','params','source','evidence','when','recipe','bindings'}:raise ValueError('Unexpected step fields')
  if 'source'in s:
   n=s.pop('source')
   if type(n)is not int or not 0<=n<len(spans):raise ValueError('Invalid original-source id')
   s['evidence']=spans[n]['text']
  evidence=s.get('evidence')
  if not isinstance(evidence,str)or not evidence or evidence not in text:raise ValueError('Source must be actual input')
  # Lossless schema normalization: retaining the guard is safer than discarding a valid attempt.
  if isinstance(s.get('params'),dict)and 'when'in s['params']:
   nested=s['params'].pop('when')
   if 'when'in s and s['when']!=nested:raise ValueError('Conflicting result guards')
   s['when']=nested
  if s.get('type')=='unsupported':
   unresolved=s.get('params',{}).get('text','')
   if isinstance(unresolved,str) and unresolved in evidence and ordinary_gesture(unresolved):
    s['type']='gesture';s['params']={'text':unresolved}
  if s.get('type')in('say','ask','answer') and ordinary_gesture(evidence) and isinstance(s.get('params',{}).get('text'),str) and s['params']['text'] and s['params']['text']in evidence:
   # A generic greeting names a social signal, not literal speech. Normalize
   # only this complete benign clause; never invent what the player said.
   s['type']='gesture';s['params']={'text':evidence}
  if s.get('type')=='eat' and re.search(r'(?:喝|抿|吃|咬|尝)(?:了)?一(?:小)?口',evidence):
   s.setdefault('params',{}).update(portion='small',quantity=1)
  elif s.get('type')=='eat' and re.search(r'喝完|喝掉|吃完|吃掉',evidence):
   s.setdefault('params',{})['portion']='all'
  when=s.pop('when',None)
  if when=={} and not re.search(r'如果|假如|找到后|成功后|完成后|之后再|才',evidence):when=None
  if s.get('type')=='take'and isinstance(when,dict)and when.get('outcome')=='found':
   value=s.get('params',{}).get('instance')
   types=[k for k,v in tx.definition['items'].items()if value==v['name']and not v.get('hidden')]
   if len(types)==1:s['params']['instance']='found:'+types[0]
   value=s.get('params',{}).get('instance','')
   if not isinstance(value,str):raise ValueError('Discovered item binding must be a string')
   if value.startswith('found:')and value[6:]not in tx.definition['items']:raise ValueError('Unknown discovered item type')
  if s.get('type')not in('unsupported','think','compound'):s=normalize_action(s,tx.state,tx.definition,'player');steps[index]=s
  from input_grounding import ground_move,validate_item_reference
  ground_move(s,tx);validate_item_reference(s,evidence,tx.state,tx.definition)
  if s.get('type')in('read','take','put_down','eat','give','use','observe'):
   intended=[k for k,item in tx.definition['items'].items()if item['name']in evidence or len(item['name'])>3 and item['name'][-2:]in evidence]
   instance=read(tx.state,'item:'+s.get('params',{}).get('instance',s.get('params',{}).get('target','')),{})
   if len(intended)==1 and instance and instance.get('item')!=intended[0]:raise ValueError('Parsed action changed the explicitly named item type')
  if s.get('type')in('say','ask','answer'):
   utterance=s.get('params',{}).get('text')
   if not isinstance(utterance,str) or not utterance or utterance not in evidence or not re.search(r'说[：:]|说道[：:]|[“"].+[”"]',evidence):
    raise ValueError('Free action parsing must not create public utterances without literal spoken content')
  if s.get('type')=='gesture' and s.get('params',{}).get('text','') not in evidence:
   raise ValueError('Gesture must preserve an actual action excerpt')
  if s.get('type')in('think','unsupported'):
   if not isinstance(s.get('params',{}).get('text'),str):raise ValueError('Unresolved intent needs text')
  else:
   effects,_=expand(s,temporary,'player')
   if s.get('type')=='compound':
    for e in effects:
     leaf={'type':e['template'].removeprefix('builtin.'),'params':{k:v for k,v in e.items()if k not in('template','actor')},'evidence':evidence}
     original=leaf['params'].get('location');ground_move(leaf,tx)
     if leaf['params'].get('location')!=original:raise ValueError('组合方法的目的地不符合当前语境，须重新拆解。')
     validate_item_reference(leaf,evidence,tx.state,tx.definition)
  # A narrow evidence excerpt cannot remove a condition attached to its source clause.
  source_clause=next((p['text']for p in spans if evidence in p['text']),evidence)
  if re.search('找到(?:后|了再)|找到了就|若找到',source_clause)and when is None:
   prior=[i for i in range(index)if steps[i].get('type')=='search']
   if not prior:raise ValueError('Found condition needs a preceding search')
   when={'after':prior[-1],'outcome':'found'}
  if re.search(r'如果|假如|要是',source_clause)and not re.search('找到|成功|完成',source_clause)and not questions:raise ValueError('Unimplemented natural condition cannot execute')
  if re.search(r'如果|假如|要是',source_clause)and when is None and not questions:raise ValueError('Unresolved condition cannot execute')
  if when is not None:
   if not isinstance(when,dict)or set(when)!={'after','outcome'}or type(when['after'])is not int or not 0<=when['after']<index or when['outcome']not in('found','applied'):raise ValueError('Condition must bind a prior result')
   if when['outcome']=='found'and steps[when['after']].get('type')!='search':raise ValueError('Found guard requires search')
   s['when']=when
  purchased=s.get('params',{}).get('instance','')
  if isinstance(purchased,str) and purchased.startswith('purchased:'):
   if not when or when['outcome']!='applied' or steps[when['after']].get('type')!='buy' or steps[when['after']].get('params',{}).get('item')!=purchased[10:]:
    raise ValueError('Purchase variable must bind its exact prior successful buy')
 for q in questions:
  if not isinstance(q,dict)or not isinstance(q.get('question'),str)or not q['question'].strip()or len(q['question'])>180:raise ValueError('Invalid clarification')
  n=q.get('source',0)
  if type(n)is not int or not 0<=n<len(spans):raise ValueError('Clarification needs real source')
  q['evidence']=spans[n]['text']
 # Questions suspend the whole dependent action span. No confident prefix executed before clarification.
 return {'steps':steps,'recipes':copy.deepcopy(recipes),'clarifications':questions}

def parse_free(tx,gateway,text,view,input_kind='action'):
 if tx.definition['config'].get('world_mode') and input_kind in ('action','environment'):
  wait=literal_wait(text)
  if wait:return wait
  if input_kind=='action':
   purchase=literal_purchase(tx,text)
   if purchase:return purchase
   from input_grounding import classroom_destination
   destination=classroom_destination(tx,text)
   if destination is not None:
    # Complete ordinary movement only. Existing execution still checks route,
    # doors, travel time and actual arrival; no teleport or forced NPC action.
    program=validate_program({'steps':[{'type':'move','params':{'location':destination},'evidence':text}],
                              'recipes':[],'clarifications':[]},text,tx)
    program['review']={'decision':'allow','category':'own_action','reason':'已知班级或眼前教室的本人移动，路线与入口由程序核验。','evidence':text}
    return program
 from world_turn import validated_request
 from model_context import stable_contract
 from action_guard import CONTRACT,validate_review
 from input_grounding import parser_context,GroundingError
 tx.input_kind=input_kind
 view=parser_context(tx,view)
 v={k:copy.deepcopy(v)for k,v in view.items()if k not in('observations','heard_dialogue','state_revision','vocabulary')}
 v['cards']=[c for c in v.get('cards',[])if c['template']in('item','location','opportunity','goal','relation')]
 v['searchable_types']=[{'id':k,'name':item['name']}for k,item in tx.definition['items'].items()if not item.get('hidden')]
 grounding_error=None
 def valid(a):
  nonlocal grounding_error
  if tx.definition['config'].get('world_mode'):
   review=validate_review(tx,text,a)
   if review['decision']!='allow':return
   if review.get('execution')=='requires_ability_interface':return
  try:validate_program(a,text,tx)
  except GroundingError as error:
   grounding_error=error;raise
 payload={'input':text,'input_kind':input_kind,'sources':sources(text),'view':v}
 world=tx.definition['config'].get('world_mode')
 candidate=completion_candidate(tx,text)if world else None
 if world:payload['protagonist']=copy.deepcopy(getattr(tx,'protagonist',{}))
 if candidate:payload['resolved_completion_attempt']=copy.deepcopy(candidate)
 contract=PROMPT+(CONTRACT if world else'')
 if world:
  contract='输出对象必须同时包含review、steps、recipes、clarifications。即使steps为空，review仍必填；审查与动作解析是同一响应。\n'+contract
 try:ans=validated_request(gateway,'parser',stable_contract(contract),payload,valid,1500)
 except (ValueError,TypeError,KeyError):
  # A subsequent malformed repair must not hide an already identified referent problem.
  if grounding_error is not None:raise grounding_error
  raise
 if world:
  review=validate_review(tx,text,ans)
  review=resolve_gesture_review(tx,text,ans,review)
  if candidate and review['category']in('own_action','uncertain')and review['decision']in('allow','clarify')and not ans.get('steps'):
   # The shell resolves the target only; existing completion conditions still execute normally.
   review={'decision':'allow','category':'own_action','evidence':text,'reason':'唯一匹配的已接受委托，完成条件由壳校验。'}
   ans={'steps':[candidate],'recipes':[],'clarifications':[]}
  if review['decision']!='allow':
   partial=independent_gesture_prefix(tx,text,ans,review)
   if partial:return partial
   return {'steps':[],'recipes':[],'clarifications':[],'review':review}
  if review.get('execution')=='requires_ability_interface':
   return {'steps':[{'type':'unsupported','params':{'text':text},'evidence':text}],'recipes':[],'clarifications':[],'review':review}
 result=validate_program(ans,text,tx)
 if world and result['clarifications']:
  partial=independent_gesture_prefix(tx,text,ans,{**review,'decision':'clarify'})
  if partial:return partial
 if world:result['review']=review
 return result

def condition_passes(step,results):
 when=step.get('when')
 if not when:return True
 prior=results.get(when['after'],[])
 if when['outcome']=='applied':return bool(prior)and all(r['outcome']=='applied'for r in prior)
 found=[instance for r in prior if r['template']=='builtin.search'and r['outcome']=='applied'for instance in r.get('public',{}).get('found',[])]
 wanted=step.get('params',{}).get('instance')
 return wanted in found if wanted else bool(found)

def resolve_result_step(step,results,tx):
 """A discovery variable can only bind an actual item from the referenced search."""
 step=copy.deepcopy(step);value=step.get('params',{}).get('instance','');when=step.get('when',{})
 if isinstance(value,str)and value.startswith('found:'):
  if when.get('outcome')!='found':raise ValueError('Discovery binding requires search-result guard')
  found=[x for r in results.get(when['after'],[])if r['template']=='builtin.search'and r['outcome']=='applied'for x in r.get('public',{}).get('found',[])]
  matches=[x for x in found if read(tx.state,'item:'+x,{}).get('item')==value[6:]]
  if len(matches)==1:step['params']['instance']=matches[0]
  # No arbitrary choice when several instances qualify; leave guard false.
 if isinstance(value,str)and value.startswith('purchased:'):
  if when.get('outcome')!='applied':raise ValueError('Purchase binding requires successful prior buy')
  matches=[r['public']['received_instance']for r in results.get(when['after'],[])if r['template']=='builtin.buy'and r['outcome']=='applied'and r['public']['item']==value[10:]]
  if len(matches)!=1:raise ValueError('本轮没有唯一成功购买的对应物品。')
  step['params']['instance']=matches[0]
 return step

def record_clarification(tx,text,questions):
 old=copy.deepcopy(tx.state);cid='input:'+digest([tx.request_id,text])[:20]
 value={'owner':'player','status':'needs_clarification','input':text,'questions':copy.deepcopy(questions)}
 put(tx.state,cid,'pending_input',value,['player'],['player'])
 tx.record({'template':'builtin.input_clarification','effects':[],'title':'行动尚待澄清','outcome':'needs_clarification','participants':['player'],
  'observers':['player'],'public':{'questions':[q['question']for q in questions]},'rule_id':'input'},old)
 return value

def record_skipped(tx,step):
 old=copy.deepcopy(tx.state)
 return tx.record({'template':'builtin.condition_skipped','effects':[],'title':'后续行动条件未成立','outcome':'not_triggered','participants':['player'],
  'observers':['player'],'public':{'reason':'前置条件未成立，后续行动没有发生'},'evidence':step['evidence'],'rule_id':'input'},old)
