"""World-mode pulses and heard-language goal proposals. No model controls another actor."""
import copy,re
from world_state import read,put,clock_time,colocated
from event_schema import digest
from goal_sets import config,select_goals,reconcile,store_card,activate_goal,validate_goals,allowed_targets

REACTOR='''判断view本人是否因实际听见的语言调整自己的目标，只JSON {"decision":"keep|adopt|decline|defer","goal":null,"evidence":""}。只读取view自己的知识、环境、目标和dialogue；evidence为dialogue内某句语言的逐字片段。可保持、拒绝或暂缓。请求不等于同意；结合自己的性格、手头目标与实际回复决定，不能无视自己已经说出的拒绝。adopt时提供一项目标{id,kind,target,title,probability,priority}；kind为obtain/read/visit/inquire/rest，target限allowed_targets。只能增添自己的目标，不能改变他人目标、玩家动作、物品、关系或世界事实。"已经完成"不是完成凭据。'''

def enabled(tx):return tx.definition['config'].get('world_mode')is True

def heard(tx,speech,targets):
 if not enabled(tx)or not re.search(r'帮|请|想要|打算|准备|要去|去找|需要|能不能|愿意|邀请|一起|陪我|要不要|来不来|别|不要|不接|拒绝',speech['text']):return
 # Only actual intended NPC recipients; overhearing alone cannot assign a job.
 for actor in targets:
  if actor=='player'or actor==speech['actor']or actor not in speech['audience']:continue
  if not colocated(tx.state,actor,speech['actor']):continue
  cid='goalcue:'+digest([tx.request_id,speech['actor'],actor,speech['text'],len(tx.records)])[:24]
  store_card(tx,cid,'goal_cue',{'owner':actor,'speaker':speech['actor'],'text':speech['text'],'status':'pending'},actor,'人物收到可考虑的请求')

def react(tx,gateway):
 if not gateway:return
 from world_turn import validated_request
 from model_context import working_view
 for cid,c in list(tx.state['cards'].items()):
  if c['template']!='goal_cue'or c['value']['status']!='pending':continue
  actor=c['value']['owner'];value=copy.deepcopy(c['value'])
  if getattr(tx,'world_reactions',0)>=6:break
  tx.world_reactions=getattr(tx,'world_reactions',0)+1
  turns=read(tx.state,'dialogue:'+actor,{}).get('turns',[])[-5:];allowed=allowed_targets(tx,actor)
  invitations=[e for e in tx.definition['config'].get('fixed_events',[]) if e.get('public_schedule') and e.get('participation_policy')=='choice'
               and e['title'] in value['text'] and clock_time(tx.state)<(e['day']-1)*1440+e['minute']+e.get('duration',60)]
  existing_intent=any(x['template']=='goal' and x['value'].get('owner')==actor and x['value'].get('source',{}).get('event') in {e['id']for e in invitations}
                      and x['value'].get('status') in ('active','completed') for x in tx.state['cards'].values())
  def validate(answer):
   if set(answer)-{'decision','goal','evidence','event_id','event_decision'}or answer.get('decision')not in('keep','adopt','decline','defer'):raise ValueError('Invalid goal reaction')
   evidence=answer.get('evidence','')
   if not isinstance(evidence,str)or not evidence or not any(evidence in t['text']for t in turns):raise ValueError('Goal change needs actual heard/spoken evidence')
   if len(invitations)==1 and not existing_intent:
    if answer.get('event_decision') not in ('join','decline','undecided'):raise ValueError('公开活动邀请须返回本人event_decision=join|decline|undecided，与实际回复一致')
    if answer['event_decision']=='join' and answer['decision']!='adopt':raise ValueError('本人决定参加且尚无该活动目标，必须adopt建立自己的活动目标')
    if answer['event_decision']!='join' and answer['decision']=='adopt' and answer.get('event_id')==invitations[0]['id']:raise ValueError('本人拒绝或未决定时不能建立参加目标')
   if answer['decision']=='adopt':
    own=[t['text']for t in turns if t['speaker']==actor]
    if own and re.search(r'不帮|不愿意|不接|不能帮|拒绝|不参加|不去|不想去',own[-1]):raise ValueError('Cannot adopt immediately after own explicit refusal')
    validate_goals([answer['goal']],tx.definition,actor,allowed,tx.state)
    mentioned=[e for e in tx.definition['config'].get('fixed_events',[])if e.get('public_schedule') and e['title'] in value['text']
               and answer['goal']['kind']=='visit' and answer['goal'].get('target')==e['location']
               and clock_time(tx.state)<(e['day']-1)*1440+e['minute']+e.get('duration',60)]
    if len(mentioned)==1 and answer.get('event_id')!=mentioned[0]['id']:raise ValueError('本人采纳了明确的活动邀请，必须返回event_id='+mentioned[0]['id'])
   elif answer.get('goal')is not None:raise ValueError('Only adoption may create a goal')
   if answer.get('event_id') is not None:
    event=next((e for e in tx.definition['config'].get('fixed_events',[])if e['id']==answer['event_id'] and e.get('public_schedule')),None)
    if answer['decision']!='adopt' or not event or answer['goal']['kind']!='visit' or answer['goal']['target']!=event['location']:raise ValueError('Event invitation must adopt own visit to the announced venue')
  try:
   result=validated_request(gateway,'goal-reaction:'+actor,REACTOR+' 活动邀请结合本人的好感、熟悉、信任、目标与安排，可拒绝或改约。invited_public_events非空时额外返回event_decision=join|decline|undecided，体现本人的实际意向，与自己已说出的答复一致。本人已明确答应未来参加、但view没有该活动目标或承诺卡时，应adopt为本人建立目标；当前已经在会场也不等于未来参与意向已经记录。参加公开活动时额外返回event_id=public_schedule活动id，adopt目标只能是本人visit该活动场地；不将玩家邀请当作本人承诺。',{'view':working_view(tx,actor),'heard_request':value['text'],'dialogue':turns,'allowed_targets':allowed,'invited_public_events':[{'id':e['id'],'title':e['title'],'location':e['location']}for e in invitations]},validate,650)
   value.update(status=result['decision'],evidence=result['evidence'])
   if result.get('event_decision'):value['event_decision']=result['event_decision']
   if result['decision']=='adopt':
    new=activate_goal(tx,actor,result['goal'],{'kind':'heard_language','cue':cid,'speaker':value['speaker'],'evidence':result['evidence'],**({'event':result['event_id']}if result.get('event_id')else{})})
    value['goal_id']=new;value['status']='adopted'if new else'deferred_capacity_or_duplicate'
  except (ValueError,TypeError,KeyError)as error:
   from card_runtime import diag
   diag(tx,actor,'goal-reaction',error);value['status']='error'
  store_card(tx,cid,'goal_cue',value,actor,'人物对请求作出判断')

def pulse(tx,gateway,frames):
 if not enabled(tx):return
 from schedule_runtime import evaluate_due
 evaluate_due(tx,gateway,frames)
 select_goals(tx,gateway);reconcile(tx);react(tx,gateway)
 if getattr(tx,'world_pulses',0)>=config(tx.definition).get('max_pulses',12):return
 tx.world_pulses=getattr(tx,'world_pulses',0)+1
 if not gateway:return
 from card_runtime import background
 background(tx,gateway,frames);reconcile(tx)
 from goal_motivation import reconcile as reconcile_motivation
 from goal_planner import synchronize
 reconcile_motivation(tx);synchronize(tx)

def advance(tx,minutes,gateway,frames):
 """Advance story time in bounded pulses, never spin on real time or silently claim full simulation."""
 from world_heartbeat import advance_until
 from schedule_runtime import evaluate_due
 tx.schedule_gateway=gateway
 target=clock_time(tx.state)+minutes
 tx.schedule_allowed_days={tx.state['clock']['day'],target//1440+1}
 evaluate_due(tx,gateway,frames)
 interval=tx.definition['config'].get('planning_interval',5)
 if type(interval)is not int or not 1<=interval<=60:raise ValueError('World planning interval must be 1..60 minutes')
 while clock_time(tx.state)<target and getattr(tx,'world_pulses',0)<config(tx.definition).get('max_pulses',12):
  advance_until(tx,min(interval,target-clock_time(tx.state)));pulse(tx,gateway,frames)
 if clock_time(tx.state)<target:
  start=clock_time(tx.state);tx.schedule_gap=True
  try:advance_until(tx,target-start)
  finally:tx.schedule_gap=False
  from schedule_runtime import evaluate_due
  evaluate_due(tx,gateway,frames,execute=False)
  select_goals(tx,gateway);reconcile(tx)
  store_card(tx,'simulation:'+tx.request_id,'simulation_gap',{'owner':'player','start':start,'end':target,'reason':'planning_budget','fully_simulated':False},'player','这段长时间仅结算既定事件，未完整模拟人物活动')
 tx.schedule_allowed_days={tx.state['clock']['day']}

def action_activity(tx,actor,action):
 """NPC durations are concurrent; a NPC cannot consume the player's world clock."""
 kind=action.get('type');value=copy.deepcopy(read(tx.state,'activity:'+actor,{'owner':actor}))
 if kind in('rest','wait'):
  minutes=action.get('params',{}).get('minutes',5)
  if type(minutes)is not int or not 0<=minutes<=10080:raise ValueError('Invalid rest duration')
  value.update(rest_since=clock_time(tx.state),busy_until=clock_time(tx.state)+minutes)
 else:
  value.pop('rest_since',None);value['busy_until']=clock_time(tx.state)+(1 if kind in('search','observe','read','eat')else 0)
 store_card(tx,'activity:'+actor,'activity',value,actor,'人物活动耗时')
