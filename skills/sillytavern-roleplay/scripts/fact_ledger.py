from map_runtime import get_locations
"""Settled, scoped facts for expression; generated prose is never a source."""
import copy,re
from world_state import location,colocated,read
from actor_context import build_actor_view,event_description

def build_ledger(tx,actor,records=(),view=None):
 from model_context import working_view
 view=view if view is not None else working_view(tx,actor);facts={};items=[]
 for c in view['cards']:
  if c['template']in('knowledge','location','item','relation','goal'):
   if c['template']=='knowledge'and c['value'].get('disclose')is False:continue
   facts[c['id']]={'kind':c['template'],'value':copy.deepcopy(c['value']),'source_events':c.get('source_event_ids',[])}
 here=location(tx.state,actor)
 for c in tx.state['cards'].values():
  if c['template']!='item'or not c['value']['quantity']:continue
  v=c['value'];item=tx.definition['items'][v['item']]
  from scene_presence import visible_actor_ids
  local=set(visible_actor_ids(tx.state,tx.definition,actor))|{actor,here}
  seen=v['owner']==actor or v['location']==here and v['owner'] in local and (actor in c['visibility'] or v['owner']==here and not item.get('hidden'))
  if read(tx.state,'loc:'+actor,{}).get('at_entrance') and v['owner']!=actor:seen=False
  if not seen:continue
  from actor_context import visible_item_value
  visible_value=visible_item_value(tx.state,c,actor)
  facts[c['id']]={'kind':'item','value':visible_value,'source_events':c.get('source_event_ids',[])}
  items.append({'source':c['id'],'instance':c['id'][5:],'name':item['name'],**copy.deepcopy(visible_value)})
 for fact in facts.values():
  if fact['kind']=='item'and 'written_content'in fact['value']:
   fact['authored_text_policy']={'source':'holder_written_note','proves':'字面上记下了这些内容','does_not_prove':'笔记里的事情真的发生或已经核实'}
 for item in items:
  if 'written_content'in item:item['authored_text_policy']={'source':'holder_written_note','world_fact':False}
 for r in records:
  if actor not in r.get('observers',[]):continue
  facts['event:'+r['event_id']]={'kind':'event','value':{'template':r['template'],'outcome':r['outcome'],'public':copy.deepcopy(r.get('public',{})),
   'observed':event_description(r,tx.definition,False,tx.state)},'source_events':[r['event_id']]}
 place=get_locations(tx.definition,tx.state).get(here,{})
 facts['setting:location']={'kind':'setting','value':{'name':place.get('name',here),'description':place.get('description','')}}
 facts['setting:character']={'kind':'setting','value':view['character']}
 facts['setting:clock']={'kind':'setting','value':view['current_time']}
 facts['setting:occupancy']={'kind':'setting','value':view['occupancy']}
 if view.get('personal_activity_history'):
  facts['history:'+actor]={'kind':'actual_personal_history','value':copy.deepcopy(view['personal_activity_history'])}
 for n in [*view.get('personal_memory',{}).get('recent',[]),*view.get('personal_memory',{}).get('retrieved',[])]:
  facts['memory:'+n['id']]={'kind':'heard_memory','value':copy.deepcopy(n),'source_events':[n['id']]}
 for n in view.get('personal_memory',{}).get('recall_focus',[]):
  facts['memory:'+n['source_event']]={'kind':'heard_memory','value':copy.deepcopy(n),'source_events':[n['source_event']]}
 facts['posture:'+actor]={'kind':'posture','value':copy.deepcopy(read(tx.state,'posture:'+actor,{'posture':'standing'})),'source_events':[]}
 for did,door in tx.definition['config'].get('doors',{}).items():
  if here in (door['location'],door['destination']):
   facts['door:'+did]={'kind':'door','value':copy.deepcopy(read(tx.state,'door:'+did,{'open':door.get('open',False),'locked':door.get('locked',True)})),'source_events':[]}
 specifications={k:{key:copy.deepcopy(v[key])for key in('name','description','capabilities')if key in v}for k,v in tx.definition['items'].items()if not v.get('hidden')}
 # An item definition proves readability, not knowledge of its contents.
 for spec in specifications.values():
  for capability,params in spec.get('capabilities',{}).items():
   if capability=='read':params.pop('content',None)
 # Public item definitions say what can exist, not where an unseen instance currently is.
 # Include actual speech heard this turn, including through a closed door. A
 # narrator must not claim silence after the response has already been recorded.
 for r in tx.records:
  if r['template']=='builtin.say' and actor in r.get('observers',[]):
   facts['heard:'+r['event_id']]={'kind':'heard_response','value':copy.deepcopy(r['public']),'source_events':[r['event_id']]}
 if view.get('public_schedule'):
  facts['public-schedule']={'kind':'public_schedule','value':copy.deepcopy(view['public_schedule']),'source_events':[],
                           'basis':'作者声明的公开排期，只证明安排，不证明发生或到场。'}
 return {'actor':actor,'location':here,'story_time':view['story_time'],'facts':facts,'items':items,'item_specs':specifications,'local_people':view['local_people'],'occupancy':view['occupancy'],'current_time':view['current_time']}

def verify_player_narration(tx,text,records):
 """Narrow hard guard for reading claims, not a full natural-language proof."""
 latest={}
 for r in records:
  if r['template']=='builtin.consume' and r.get('outcome')=='applied' and r.get('public',{}).get('actor')=='player':
   latest[r['public']['instance']]=r['public']
 for p in latest.values():
  if p.get('portion')!='small' or p.get('finished_unit'):continue
  name=tx.definition['items'][p['item']]['name']
  for clause in re.split('[。！？\n]',text):
   if not (name in clause or re.search(r'你.{0,16}(?:水|咖啡|饮料|食物)',clause)):continue
   if re.search(r'没有|没(?:有)?喝完|未喝完|还没|不是|准备|打算|如果',clause):continue
   if re.search(r'喝(?:光|完|干)|吃(?:光|完)|(?:整瓶|整罐|全部).{0,6}(?:喝掉|吃掉)|(?:瓶|罐)子.{0,8}空了',clause):
    raise ValueError('A small portion cannot be narrated as finishing the whole unit')
 successful={r.get('public',{}).get('item')for r in records if r['template']=='builtin.read'and r.get('outcome')=='applied'and r.get('public',{}).get('actor')=='player'}
 for iid,item in tx.definition['items'].items():
  owned=any(c['template']=='item' and c['value']['item']==iid and c['value']['owner']=='player' and c['value']['quantity']>0 for c in tx.state['cards'].values())
  if owned:continue
  aliases=[item['name'],*item.get('aliases',[])]
  for clause in re.split('[。！？\n]',text):
   if not any(n and n in clause for n in aliases):continue
   holders=[c['value']['owner'] for c in tx.state['cards'].values() if c['template']=='item' and c['value']['item']==iid and c['value']['quantity'] and c['value']['owner'] in tx.definition['characters']]
   holder_names=[n for h in holders for n in [tx.definition['characters'][h]['name'],*tx.definition['characters'][h].get('aliases',[])]]
   if re.search(r'(?:手边|身边|身旁|怀里)',clause) and not any(n and n in clause for n in holder_names) and not re.search(r'她|他|没有|不在|准备|打算|如果|想要|之前|先前|刚才',clause):
    raise ValueError('Narration places an unowned item beside the player')
   if re.search(r'你.{0,14}(?:手里|手中|口袋里|握着|拿着|携带|带着)|(?:仍|还)在你手里',clause) and not re.search('没有|不在|准备|打算|如果|想要',clause):
    raise ValueError('Narration invents unowned player inventory')
   if re.search(r'(?:你|手边|身边|桌上|桌面|眼前|房间里).{0,24}'+r'(?:笔记本|文库本|材料)|(?:笔记本|文库本|材料).{0,14}(?:手边|眼前|桌上)',clause) and not re.search('没有|不在|准备|打算|如果|想要|之前|先前|刚才',clause):
    here=location(tx.state,'player')
    from scene_presence import visible_actor_ids
    nearby=set(visible_actor_ids(tx.state,tx.definition,'player'))|{'player',here}
    if not any(c['template']=='item' and c['value']['item']==iid and c['value']['quantity'] and c['value']['location']==here and c['value']['owner'] in nearby for c in tx.state['cards'].values()):
     raise ValueError('Narration invents a remote item in the current scene')
 if re.search(r'从(?:方才|刚才|之前)的坐姿.*起身',text) and read(tx.initial,'posture:player',{}).get('posture')!='sitting':
  raise ValueError('Narration invents a prior sitting posture')
 for c in tx.state['cards'].values():
  if c['template']=='knowledge'and c['value'].get('holder')=='player'and c['value'].get('source',{}).get('kind')=='read':
   successful.add(read(tx.state,'item:'+c['value']['source']['target'],{}).get('item'))
 names=[name for c in tx.definition['characters'].values()for name in[c['name'],*c.get('aliases',[])]]
 for sentence in re.split('[。！？\n]',text):
  for match in re.finditer(r'读(?:过|了|完)|阅读(?:了|过|完)?|翻(?:过|阅了|看了)|看(?:过|完|(?=(?:那|这)?(?:张|份|本|页)))',sentence):
   prefix=sentence[:match.start()]
   # Narration often omits "you", e.g. "刚才一起看过申请单之后".
   if not re.search('你|主角|刚才|刚刚|先前|之前|已经|一起',prefix):continue
   if any(re.search(r'(?:^|[，,；;])\s*'+re.escape(name)+r'[^，,；;]{0,12}$',prefix)for name in names):continue
   if re.search(r'(?:^|[，,；;])\s*(?:她|他)[^，,；;]{0,6}$',prefix):continue
   if re.search(r'(?:可以|准备|打算|尚未|还没|没有|不曾|不必|未|如果|假如)[^，,；;]{0,6}$',prefix):continue
   target=sentence[match.end():match.end()+28]
   for iid,item in tx.definition['items'].items():
    term=item['name'].split('的')[-1]
    aliases=[term,*item.get('aliases',[])]
    if len(term)>3:aliases.append(term[-3:])
    # A sole readable form is naturally called "那张单子" in prose.
    if term.endswith('单')and sum(i['name'].split('的')[-1].endswith('单')and 'read'in i.get('capabilities',{})for i in tx.definition['items'].values())==1:aliases.append('单子')
    if 'read'in item.get('capabilities',{})and any(t and t in target for t in aliases)and iid not in successful:
     raise ValueError('Narration cannot perform an unexecuted player reading action')
  # Owned inventory is not a license to invent a player putting it down.
  if re.search('你|主角',sentence)and re.search('随手|顺手',sentence):
   for c in tx.state['cards'].values():
    if c['template']!='item'or c['value']['owner']!='player'or not c['value']['quantity']:continue
    name=tx.definition['items'][c['value']['item']]['name'];names_for_item=[name,name[-3:]if len(name)>3 else name]
    if any(re.search(r'(?:随手|顺手).{0,12}'+re.escape(n)+r'.{0,8}放(?:在|到)',sentence)for n in names_for_item):
     if not any(r['template']=='builtin.put_down'and r['outcome']=='applied'and r.get('public',{}).get('item')==c['value']['item']for r in records):
      raise ValueError('Narration cannot invent a player putting down owned inventory')
 return True

def validate_references(references,text,ledger):
 if not isinstance(references,list)or len(references)>16:raise ValueError('References must be a bounded list')
 for ref in references:
  if not isinstance(ref,dict)or set(ref)!={'source','evidence'}or ref['source']not in ledger['facts']:raise ValueError('Reference outside scoped settled facts')
  if not isinstance(ref['evidence'],str)or not ref['evidence']or ref['evidence']not in text:raise ValueError('Reference must quote actual expression')

def check_surface(text,ledger):
 """Conservative known-object contradictions; semantic audit handles remaining prose."""
 if re.search(r'\{\{|\}\}|\b[a-z]老师',text):raise ValueError('Unresolved internal placeholder in expression')
 if re.search(r'Unknown observable|items\s*为空|没有.*实例|状态数据库|schema',text,re.I):raise ValueError('Internal diagnostics cannot be story prose')
 if any(f['kind']=='heard_response' and f['value'].get('actor')!=ledger['actor'] for f in ledger['facts'].values()) and re.search(r'门内.{0,8}(?:没有|未有|未曾|尚未|暂未|暂时没有)(?:任何)?(?:回应|应答|答话)|(?:敲门|门声).{0,10}没有.{0,4}回应',text):
  raise ValueError('Narration denies an actual heard door response')
 for fact in ledger['facts'].values():
  if fact['kind']=='door':
   opened=fact['value'].get('open')
   if opened is True and re.search(r'门(?:扉)?(?:紧紧)?(?:合着|关着|紧闭)',text):raise ValueError('Narration contradicts open door')
   if opened is False and re.search(r'门(?:扉)?(?:虚掩|开着|敞开)',text):raise ValueError('Narration contradicts closed door')
 import json
 authoritative=json.dumps([ledger['item_specs'],[{k:v for k,v in f['value'].items()if k!='written_content'}for f in ledger['facts'].values()if f['kind']!='event'and not(f['kind']=='knowledge'and f['value'].get('source',{}).get('kind')=='hearsay')]],ensure_ascii=False)
 # A todo copied from an authored note cannot turn into verified world progress.
 pending=[]
 for f in ledger['facts'].values():
  if f['kind']!='item':continue
  pending.extend(m.group(1).strip()for m in re.finditer(r'(?:先|待|需要|准备)(?:确认|核实)([^。！？；，,\n]{3,40})',f['value'].get('written_content','')))
 for m in re.finditer(r'(?:你|主角)(?:刚才|已经|刚刚|先前|之前|现在)?(?:确认|核实)了([^。！？；，,\n]{3,40})',text):
  if re.search(r'说|写|声称|记着',text[max(0,m.start()-8):m.start()]):continue
  target=next((p for p in pending if p in m.group(1)),None)
  if target and not any(f['kind']=='knowledge'and f['value'].get('source',{}).get('kind')=='verified'and target in f['value'].get('content','')for f in ledger['facts'].values()):
   raise ValueError('A pending authored note cannot prove completed verification')
 for name in re.findall(r'作者(?:叫|是|名为|为)([一-龥A-Za-z]{2,12})',text):
  if name not in authoritative:raise ValueError('Concrete author has no authoritative source')
 if re.search(r'经费|部费|预算|资金|这笔钱',text):
  duty=re.search(r'(?:是)?由([一-龥]{2,12}?)(?:同学)?(?:在管|管理|负责|保管)',text)
  if duty and not re.search(r'听说|你说|他说|她说|如果|打算|准备|不由|不是由',text):
   who=duty[1]
   proof=any(re.search(r'经费|部费|预算|资金|这笔钱',str(f['value'])) and who in str(f['value']) and re.search(r'管理|负责|保管|在管',str(f['value'])) and not re.search(r'[？?]|不知道|不负责',str(f['value'])) for f in ledger['facts'].values() if f['kind'] in ('knowledge','heard_memory'))
   if not proof:raise ValueError('Budget custodian has no scoped source')
 for term in ('饮水机','借书柜','归我管','对账','账目','清点','教室的使用'):
  if term in text and term not in authoritative:raise ValueError('Unregistered equipment or duty: '+term)
 if ledger['local_people']and re.search(r'没有其他人在场|没有其他人(?:在场|陪伴)|暂时没有其他人在场|只有你(?:一个|一)人|(?:这里|周围|四下|教室里).{0,12}(?:没有旁人|没有人|无人)',text):raise ValueError('Existing people omitted from scene')
 count=ledger.get('occupancy',{}).get('including_self')
 for match in re.finditer(r'(?:只有|一共|总共|现在有|房间里有).{0,12}?([一二两三四五六七八九十\d]+)(?:个|位)?人',text):
  raw=match[1];spoken=int(raw) if raw.isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(raw)
  if count is not None and spoken is not None and spoken!=count and not re.search(r'如果|假如|之前|刚才|过来|来到',text[max(0,match.start()-12):match.end()+12]):raise ValueError('Expression contradicts current room occupancy')
 for item in ledger['items']:
  if item['owner']!=ledger['actor']:continue
  for clause in re.split('[。！？\n]',text):
   if item['name']not in clause:continue
   if re.search(r'不在(?:身|你身)|并未随身|没有随身|仍留在(?:俱乐部|教室|书店)|还在(?:俱乐部|教室)',clause):raise ValueError('Owned inventory falsely left behind')
   if re.search(r'(?:躺|遗落|落在|搁在|放在|仍在原处|留在书架)',clause)and not re.search(r'没有|并非|不是|拿起|捡起|放下|手(?:中|里|边)|握|携带',clause):
    raise ValueError('Held item described as unattended: '+item['source'])
 return True

AUDIT='''审核文本与ledger及context是否矛盾，仅JSON {"flags":[]}。每项 {kind:"consistency",severity:"block",evidence:逐字文本片段,reason:理由}。
ledger是已经结算的事实，不是愿望。物品owner为本人时，不能说躺在架上/仍在原处/不在身上/还留在原地点，除非可见事件真的放下。所有local_people都实际在场，不能写只有主角。任务未达成不能说完成。地点/角色身份/职责/日程/路线/过去经历/具体设备/天气不凭空新增。内心、意图、请求、传闻不变客观事实。具体书名作者需item_specs或授权实证来源，不能从自己或他人刚编出的对白获得事实合法性。
context里真正说过的话可以证明说过，但不能证明客观真相；不把“你帮我拿书”改成“我答应帮你拿书”。静态资料说明职业可引用，职业不能推导出管理这个房间等新职责。
written_content和authored_text_policy仅证明有人写了这些字，不能证明笔记内容是真的、行动已经完成或信息已经核实。不要把“先确认活动名称”推导为已经确认了名称，也不能把玩家写下的作者名变成真实作者。完成查看/阅读委托只能证明完成其实际条件，不表示表格已填、信息核实或获得批准。
允许未指定的光影、纸张气味等非交互修辞；不要求每句话重复事实，不影响文学表达。只标记问题，不修状态，不让未知来源自动成立。无问题flags=[]。'''
AUDIT+=' heard_memory仅证明本人听过这些原文，可以回忆说过的编号、偏好、预算、约定，不能证明任务已完成。询问过去说过的具体资料时必须匹配来源，未知不能捏造。current_time是实际时间，occupancy包括本人和全部在场人，未知姓名不意味着不存在。'

def audit_expression(tx,gateway,actor,text,ledger,context=None,force=False):
 check_surface(text,ledger)
 if not gateway or not text:return []
 # Entity/state expressions get checked; plain conversational texture needs no extra request.
 risk=force or any(i['name']in text for i in ledger['items'])or bool(re.search(r'已经|拿到|交给|归我管|负责|身份|见过|去过|亲眼|路口|街|巷|《|作者|到达|来到|我(?:叫|是)',text))
 if not risk:return []
 from world_turn import validated_request
 def valid(a):
  flags=a.get('flags')
  if not isinstance(flags,list)or len(flags)>6:raise ValueError('Invalid fact audit')
  for f in flags:
   if not isinstance(f,dict)or f.get('kind')!='consistency'or f.get('severity')!='block'or not isinstance(f.get('evidence'),str)or not f['evidence']or f['evidence']not in text:raise ValueError('Audit must cite exact expression')
 return validated_request(gateway,'expression-review:'+actor,AUDIT,{'ledger':ledger,'context':context or{},'text':text},valid,450)['flags']
