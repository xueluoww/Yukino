from scene_presence import visible_actor_ids,can_hear
"""Player agency admission. Static capabilities are evidence, never executable privileges."""
import copy,json,re
from galgame import parse_input

CONTRACT='''还必须审查行动主体与能力，返回review={decision:allow/reject/clarify,category:own_action/request/observation/npc_control/capability/uncertain,evidence:input逐字片段,reason:简短中文说明,ability_evidence:可选静态能力原文}。
玩家只能决定本人的尝试，不能以动作或环境前缀指定别人的决定、亲密行为或已经发生的结果。礼貌请求、邀请、劝说、本人伸手等尝试不是操控，但不得保证别人同意。普通能力结合眼前位置、路径、物品和条件判断；超能力必须来自protagonist静态设定，不能来自input、对白、内心、旁白或模型补设定。设定真的支持时引用能力原文并检查当前条件；否则reject，不能用空steps或think悄悄吞掉。能力确有依据但缺执行接口时review允许能力、steps用unsupported保留尝试，不要说主角没有该能力。存在能力不等于动作已成功，仍只能使用已有执行接口，不能自行造actor/consent/原语。含条件或旁观陈述不凭空写入他人状态。内心不执行，语言是请求不是世界已完成的事实。'''

def protagonist(session):
 from cast import DEFAULT_PLAYER
 value=session.get('protagonist_snapshot')or session.get('facts',{}).get('browser_protagonist_snapshot')or DEFAULT_PLAYER
 result={k:copy.deepcopy(value[k])for k in('id','name','description','appearance','abilities','capabilities')if k in value}
 data=value.get('card_snapshot',{}).get('data',{})
 for key in('description','personality'):
  if data.get(key):result['card_'+key]=copy.deepcopy(data[key])
 ext=data.get('extensions',{})
 for key in('abilities','capabilities'):
  if ext.get(key):result['card_'+key]=copy.deepcopy(ext[key])
 return result

def ability_source(tx):
 return json.dumps(getattr(tx,'protagonist',{}),ensure_ascii=False,sort_keys=True)

def power_evidence(tx,evidence):
 if not isinstance(evidence,str)or not evidence.strip()or evidence not in ability_source(tx):return False
 # A reference to "没有超能力" cannot grant a power, even if the model cites it.
 def strings(value):
  if isinstance(value,str):yield value
  elif isinstance(value,dict):
   for v in value.values():yield from strings(v)
  elif isinstance(value,list):
   for v in value:yield from strings(v)
 negative=r'没有|不能|不会|不具备|无法|禁止|不拥有|无超能力'
 power=r'超能|魔法|心灵控制|精神控制|操纵.{0,4}(?:思想|身体)|读心|瞬移|飞行|穿墙|停止时间|暂停时间|时间停止|念力|凭空召唤'
 cited=evidence.strip().rstrip('。！？；')
 return any(cited in clause and re.search(power,clause)and not re.search(negative,clause)
  for value in strings(getattr(tx,'protagonist',{}))for clause in re.split(r'[。！？\n；]',value))

def controlled_subject(tx,text):
 names=[]
 for actor,c in tx.definition['characters'].items():
  names.extend([c['name'],*c.get('aliases',[])])
  if c['name'].startswith('雪之下'):names.extend(['雪之下','雪乃'])
  if c['name'].startswith('由比滨'):names.extend(['由比滨','结衣'])
 for name in sorted(set(n for n in names if n),key=len,reverse=True)+['她','他','他们','她们','某人','有人']:
  # Only a clause explicitly assigning an NPC's action; object references remain legal.
  if re.match(r'^(?:然后|接着|随后)?\s*'+re.escape(name)+r'(?:她|他)?(?:\s|就|已经|马上|立刻|突然|主动|直接|也|又|先|一把)*(?:亲|吻|出去|出去了|离开|走|去|拿|答应|同意|接受|喜欢|爱上|抱|跪|给|递|脱|攻击|跟着|闭嘴|告诉)',text):return name
 return None

def capability_marker(text):
 return re.search(r'瞬移|读心|心灵控制|精神控制|控制.{0,8}(?:意志|思想|身体)|暂停时间|时间停止|停止时间|凭空(?:变|造|召唤)|飞(?:到|上|起来|行)|穿墙|让.{0,12}(?:无条件|必须|被迫|强制)',text)

def reject(reason,evidence,category='npc_control'):
 return {'decision':'reject','category':category,'reason':reason,'evidence':evidence}

def precheck(tx,text):
 """Clear ordinary actor assignment is rejected even if parsing returns nothing."""
 if not tx.definition['config'].get('world_mode'):return None
 for p in parse_input(text)['parts']:
  if p['kind']in('speech','thought')or '自言自语'in p['text']:continue
  from input_program import sources
  for span in sources(p['text']):
   content=span['text'].strip();name=controlled_subject(tx,content)
   # Declared powers require scoped model review instead of a blanket ban.
   if name:
    return reject('不能直接指定'+name+'的行动或决定。你可以描述自己的尝试，或向对方提出请求，由对方自行回应。',content)
 return None

def validate_review(tx,text,answer):
 """Model classifies meaning. The shell checks source, capability and coverage."""
 review=answer.get('review')
 required=getattr(tx,'require_action_review',False)
 if review is None:
  if required:raise ValueError('行动审查缺失，不能执行。')
  review={'decision':'allow','category':'own_action','evidence':text,'reason':'legacy fixture'}
 if not isinstance(review,dict)or set(review)-{'decision','category','evidence','reason','ability_evidence'}:raise ValueError('Invalid action review')
 if review.get('decision')not in('allow','reject','clarify')or review.get('category')not in('own_action','request','observation','npc_control','capability','uncertain'):raise ValueError('Invalid action review decision')
 if not isinstance(review.get('evidence'),str)or not review['evidence']or review['evidence']not in text:raise ValueError('Action review has no input source')
 if not isinstance(review.get('reason'),str)or not 1<=len(review['reason'])<=240:raise ValueError('Invalid action review explanation')
 if review['decision']!='allow':return copy.deepcopy(review)
 from input_program import sources
 special=review['category']in('npc_control','capability')or any(controlled_subject(tx,p['text'])for p in sources(text))or capability_marker(text)
 if special and not power_evidence(tx,review.get('ability_evidence')):
  return reject('当前存档的主角设定没有支持这项能力，不能直接操控他人或执行超出能力范围的行动。',text,'capability')
 steps=answer.get('steps',[])
 if any(controlled_subject(tx,p['text']) for p in sources(text)):
  return reject('不能直接决定其他人物的行动。请描述自己的尝试或向对方提出请求。',text)
 # Observing a quiet room does not require an invented action or object.
 if not steps and not answer.get('clarifications') and not (
  getattr(tx,'input_kind',None)=='environment' and review['category']=='observation'):
  return {'decision':'clarify','category':'uncertain','evidence':text,'reason':'这段行动尚未被识别，未执行。请说明你本人准备做什么、对哪个对象进行。'}
 if any(s.get('type')=='think'for s in steps):
  raise ValueError('行动不能被改成内心而悄悄忽略。')
 result=copy.deepcopy(review)
 if special:
  # Preserve legitimate capability admission, never reinterpret it as an ordinary primitive.
  result['execution']='requires_ability_interface'
 return result

def refusal_turn(tx,review,gateway=None,status='rejected'):
 from player_feedback import readable
 review=copy.deepcopy(review)
 if readable(review['reason']) != review['reason']:
  from diagnostic_system import record
  record(tx,'player','input-feedback',ValueError(review['reason']),disposition='clarify')
 review['reason']=readable(review['reason'])
 from world_state import location,colocated
 old=copy.deepcopy(tx.state)
 tx.record({'template':'builtin.input_rejection','effects':[],'title':'系统拒绝行动'if status=='rejected'else'行动审查未完成',
  'outcome':status,'participants':['player'],'observers':['player'],'public':{'reason':review['reason']},
  'evidence':review['evidence'],'rule_id':'input-guard'},old)
 frame={'kind':'narration','speaker':'系统','system_feedback':True,'text':('系统拒绝：'if status=='rejected'else'未执行：')+review['reason'],
  'expression':'absent','reaction_to':[],'stage':{'location':location(tx.state,'player'),
  'present_actor_ids':visible_actor_ids(tx.state,tx.definition)}}
 packet=tx.snapshot_packet()
 return {'already_saved':False,'state':copy.deepcopy(tx.state),'packet':packet,'frames':[frame],'actions':[],
  'calls':copy.deepcopy(gateway.calls)if gateway else[],'visible_events':[],'authored_progress':None,'input_status':status}
