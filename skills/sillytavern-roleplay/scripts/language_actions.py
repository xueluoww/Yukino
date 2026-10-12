from map_runtime import get_locations
"""Speech is an utterance; detected actions are separately checked proposals."""
import copy,re
from basic_cards import expand,vocabulary,normalize_action
from world_state import clock_time,location,colocated,read,put
from event_schema import digest

DETECTOR='''你是语言行动检测器，仅JSON {"candidates":[]}。只分析speaker本人这段原文，不当导演。区分kind：immediate(现在执行的本人行动)、plan(未来打算)、promise(承诺)、request(请求别人)、conditional(条件/假设)、past(过去陈述)、quoted(引用/玩笑)、unsupported(无接口)。普通闲聊无候选。每项必须有evidence逐字连续原文，actor必须speaker。action={"type":词表ID,"params":参数}。params只能用view声明的实体，不能添加actor/consent或自行生成物品。说“你去”只是request不是对方move。“我想/打算/准备”是plan而不是完成；“我现在去”可immediate。“已经成功”是past，不造历史。未来计划可due_in正整数分钟（只在原文有明确时间时）；否则不填。假设、条件、引用、玩笑不自动执行；内心不公开。动作原语参数：move(location)、give(instance,target)、take/put_down/read/eat(instance)、use(instance,target)、search(target可省略)、observe(target)、wait/rest(minutes)、agree/refuse/complete(id)、conceal(text)。欺骗可提出compound但必须已有配方，不保证别人相信。不把本次语言再转say造成重复。最多4项。'''
KINDS={'immediate','plan','promise','request','conditional','past','quoted','unsupported','cancel'}
DETECTOR+=' 公开活动邀请不是opportunity任务。说“可以、答应参加”不能凭空构造agree(id)，只有view明确收到的opportunity才可agree。本人答应未来前往某活动且原文有时间时，将承诺与前往合并为一项promise(move)，evidence覆盖包含承诺、时间和目的地的完整连续原文；不要把同一承诺拆成无id的agree加普通plan。例如“可以，我答应参加阅读日，十分钟后到活动室。”→kind=promise, actor=speaker, action={type:move,params:{location:活动室ID}}, due_in=10。due_in必须在candidate顶层，不是params.minutes；移动耗时由实际路线结算。只有愿意但没有前往/时间时可以无动作候选，目标意向交给后续本人目标判断，不捏造时间。'

def validate_candidates(answer,text,speaker,state,definition):
 candidates=answer.get('candidates')
 if not isinstance(candidates,list)or len(candidates)>4:raise ValueError('Invalid detector result')
 for c in candidates:
  if not isinstance(c,dict)or set(c)-{'kind','actor','evidence','action','due_in','condition','target','plan_id'}:raise ValueError('Unknown detector fields')
  if c.get('kind')not in KINDS or c.get('actor')!=speaker:raise ValueError('Speech cannot control another actor')
  span=c.get('evidence')
  if not isinstance(span,str)or not span or span not in text:raise ValueError('Detector needs exact source span')
  if c.get('due_in')is not None and(type(c['due_in'])is not int or not 1<=c['due_in']<=10080):raise ValueError('Invalid future time')
  if c['kind']in('plan','promise') and c.get('action',{}).get('type')=='move' and re.search(r'(?:\d+|[一二三四五六七八九十百]+)分钟后',span) and c.get('due_in')is None:raise ValueError('明确几分钟后前往的计划必须在candidate顶层提供due_in，不把未来等待写成移动耗时')
  if c.get('action')and c['kind']in('immediate','plan','promise'):c['action']=normalize_action(c['action'],state,definition,speaker)
  if c['kind']=='immediate':
   if speaker=='player' and not re.search(r'我(?:现在|这就|马上|立即|立刻)',span):
    c['kind']='plan'
    c.pop('due_in',None)
    continue
   if re.search(r'昨天|刚才|已经|如果|假如|要是|明天|后天|下周|打算|我想|我可以|也许|不去|不想|准备|计划|“|”|「|」',span):raise ValueError('Non-current language cannot execute immediately')
   if c.get('action',{}).get('type')in('say','ask','answer'):raise ValueError('Detector cannot recursively emit speech')
   expand(c.get('action',{}),state,speaker)
  if c['kind']in('plan','promise')and c.get('action'):expand(c['action'],state,speaker)
  action=c.get('action',{})
  if action:
   from input_grounding import validate_item_reference
   validate_item_reference(action,span,state,definition)
  if action.get('type')in('agree','refuse','complete'):
   offer=state['cards'].get('offer:'+str(action.get('params',{}).get('id','')),{})
   if offer.get('template')!='opportunity'or speaker not in offer.get('visibility',[]):raise ValueError('Agreement/refusal must reference a received opportunity')
  if c['kind']=='cancel':
   card=state['cards'].get(c.get('plan_id'),{})
   if card.get('template')!='plan'or card['value']['owner']!=speaker:raise ValueError('Cannot cancel foreign/missing plan')
 return copy.deepcopy(candidates)

def detect(gateway,text,speaker,state,definition,view):
 if not text.strip():return []
 if gateway:
  from world_turn import validated_request
  answer=validated_request(gateway,'detect:'+speaker,DETECTOR+' 请求别人的动作仍填actor=speaker；target才是被请求者，不要把target当施事。取消已有计划用kind=cancel和plan_id。',{'speaker':speaker,'utterance':text,'view':view,'vocabulary':vocabulary()},
   lambda a:validate_candidates(a,text,speaker,state,definition),700)
  return validate_candidates(answer,text,speaker,state,definition)
 # Offline is deliberately narrow and identified as such in tests.
 if re.search('如果|假如|昨天|已经|明天|后天|我想|打算|“|”',text):return []
 destination=next((k for k,v in get_locations(definition,state).items()if v.get('name',k)in text),None)
 if destination and re.search('我(?:现在|这就|马上)(?:去|前往|走去)',text):
  return [{'kind':'immediate','actor':speaker,'evidence':text,'action':{'type':'move','params':{'location':destination}}}]
 return []

def record_language(tx,candidate,speaker):
 old=copy.deepcopy(tx.state);kind=candidate['kind'];cid='plan:'+digest([speaker,candidate['evidence'],tx.request_id])[:20]
 if kind=='cancel':
  cid=candidate['plan_id'];value=copy.deepcopy(read(tx.state,cid));value['status']='cancelled';put(tx.state,cid,'plan',value,[speaker],[speaker])
 elif kind in('plan','promise','conditional','request'):
  value={'owner':speaker,'kind':kind,'text':candidate['evidence'],'action':candidate.get('action'),
   'status':'pending','due_at':clock_time(tx.state)+candidate['due_in']if candidate.get('due_in')else None,
   'condition':candidate.get('condition'),'target':candidate.get('target'),'origin_location':location(tx.state,speaker)}
  put(tx.state,cid,'plan',value,[speaker],[speaker])
 detection_record=tx.record({'template':'builtin.language_detection','effects':[],'title':'语言中的'+{'plan':'计划','promise':'承诺','request':'请求','conditional':'条件意图','cancel':'取消计划'}.get(kind,'陈述'),
  'outcome':'proposed'if kind=='immediate'else'recorded','participants':[speaker],'observers':[speaker],
  'public':{'kind':kind},'candidate':copy.deepcopy(candidate),'rule_id':'language-detector'},old)
 from schedule_runtime import change_from_speech
 change_from_speech(tx,candidate,speaker,cid,detection_record)
 return cid
