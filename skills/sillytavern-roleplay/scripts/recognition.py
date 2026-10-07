"""Separate affection, acquaintance and sourced personal knowledge."""
import copy,re
from cast import resolve_actor

RULES=('导演资料中的主角姓名、全局摘要、旁白、任务、卡片和其他人物知识不是每个人的知识。'
 '先查 actor_recognition：认识外貌、知道姓名、实际交流、知道所属社团和来意分别判断。'
 '同班最多可眼熟，不自动知道名字、社团、委托或私事；低好感不抹去真实相识，高好感不创造相识。'
 '人物自己的无依据旧台词不能证明其知道该事实。NPC对白/心声只使用个人已获知的事实和本轮确实感知的内容。'
 '初次接触可以礼貌、审视、冷淡或询问来意，须符合性格；可以猜测但明确作为疑问，不能把猜测当已知。'
 '玩家纠正“我还没告诉你”等认识错误时停止沿用旧猜测，自然澄清，不强行维护旧台词。')

def cards(session):
 world=session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})
 return {c['name']:c for s in world.get('setting_sets',[]) for c in s.get('cards',[]) if c.get('kind')=='character'}

def preset(session,actor):
 protagonist=session.get('protagonist_snapshot') or session.get('facts',{}).get('browser_protagonist_snapshot',{})
 key=protagonist.get('id','hachiman');card=cards(session).get(actor['name'],{})
 raw=card.get('initial_recognition',{})
 explicit=raw.get(key,raw.get('default')) if isinstance(raw,dict) else None
 if explicit is not None:return copy.deepcopy(explicit)
 relation=card.get('initial_affinity',{}).get(key,{})
 baseline=card.get('initial_relation',{}).get(key,{})
 identity=baseline.get('identity') or relation.get('relationship','')
 authored=session.get('facts',{}).get('browser_authored',{})
 world=session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})
 route=next((r for r in world.get('storylines',[]) if r.get('id')==authored.get('id')),None)
 established=bool(route and actor['name'] in route.get('initial_relations',{})) or bool(re.search('兄妹|妹妹|兄弟|师生|指导老师|朋友|长期|多次合作|熟识',identity))
 face=established or '同班' in identity
 return {'stage':'acquainted' if established else 'face_known' if face else 'stranger','knows_name':established,'known_facts':[]}

def aliases(session):
 p=session.get('protagonist_snapshot') or session.get('facts',{}).get('browser_protagonist_snapshot',{})
 names=[session['user_name'],p.get('name',''),*p.get('aliases',[])]
 if p.get('name')=='比企谷八幡':names+=['比企谷','八幡']
 return list(dict.fromkeys(n for n in names if len(n)>1 and n not in ('玩家','主角')))

def disclosures(text,session,from_player=True):
 """Only explicit positive self-disclosures, never intentions or negations."""
 result=[]
 for clause in re.split('[。！？；\n]',text):
  if re.search('没(?:有)?(?:说|告诉|提)|不是|并非|不属于|不认识|还不认识|如果|假如|假设|梦|想象|听说|猜',clause):continue
  if from_player:
   if any(re.search(r'(?:我叫|我的名字是|名字叫|叫我|我是)\s*'+re.escape(name),clause) for name in aliases(session)):result.append('player_name')
   if re.search(r'(?:我是|我来自|我属于|我在|我加入|我也是|我是负责)[^，,]{0,18}(?:侍奉部|侍奉社|活动室|社团|学生会)',clause):result.append('player_affiliation')
   if re.search(r'(?:我来|我想找你|我是来|我找你|来找你|我这次来)[^，,]{0,30}(?:委托|任务|活动|名单|核对|确认|帮忙|询问|商量|想问)',clause):result.append('player_purpose')
  for name in aliases(session):
   if re.search(r'(?:这位是|他叫|名字是)\s*'+re.escape(name),clause):result.append('player_name')
   if re.search(re.escape(name)+r'(?:是|在|来自|属于)[^，,]{0,14}(?:侍奉部|侍奉社|活动室|社团|学生会)',clause):result+=['player_name','player_affiliation']
 return set(result)

def observed_sources(session,actor):
 entries=session.get('facts',{}).get('browser_actor_knowledge',{}).get(actor['id'],[])
 valid=[]
 for e in entries:
  # Legacy own speech is circular evidence, even if it was accidentally stored as hearing.
  if e.get('source_speaker') in [actor['name'],*actor.get('aliases',[])]:continue
  if e.get('source_speaker') and e['source_speaker'] not in aliases(session) and not e.get('epistemic_verified'):continue
  if e.get('sense') not in ('hear','read'):continue
  valid.append(copy.deepcopy(e))
 return valid

def context(session,actors):
 result={}
 for aid,actor in actors.items():
  if aid=='player':continue
  p=preset(session,actor);known=set(p.get('known_facts',[]));sources=observed_sources(session,actor)
  if p.get('knows_name'):known.add('player_name')
  evidence=[]
  for entry in sources:
   topics=disclosures(entry.get('observed',''),session,entry.get('part_index') is not None or entry.get('source_speaker') in aliases(session))
   if topics:
    known|=topics;evidence.append({'turn_id':entry['turn_id'],'topics':sorted(topics),'observed':entry['observed'][:500]})
  interactions={e.get('turn_id') for e in session.get('facts',{}).get('browser_actor_knowledge',{}).get(aid,[]) if e.get('part_index') is not None}
  stage=p.get('stage','stranger')
  if interactions and stage in ('stranger','face_known'):stage='brief_contact'
  if 'player_name' in known and stage in ('stranger','face_known'):stage='name_known'
  result[aid]={'stage':stage,'knows_player_name':'player_name' in known,'known_personal_topics':sorted(known),'evidence':evidence[-6:],
   'meaning':'眼熟与名字、交情、社团、来意分开；没有证据的背景保持未知，不按好感或熟悉分数补齐。'}
 return result

def new_sources(reply,parts,actors,user):
 result={}
 for event in reply['scene_state']['input_events']:
  part=parts[event['part_index']]
  for o in event['observations']:
   if o['sense'] in ('hear','read'):result.setdefault(o['actor_id'],[]).append((o['observable_excerpt'],True))
 return result

def claims(text,session):
 result=set()
 for clause in re.split('[。！？；\n]',text):
  if re.search('我猜|猜测|也许|可能是|不确定|我不知道|还不知道',clause):continue
  # A question about an unknown identity is permitted; a presupposition is not.
  if re.search(r'(?:你是|您是)(?:不是)?[^，,]{0,14}(?:侍奉部|侍奉社|活动室|社团|学生会)[^，,]{0,8}(?:吗|么)',clause) and not re.search('你那边|你们|你的',clause):continue
  if re.search(r'(?:你那边的|你们的|你所在的|你的|你们(?:侍奉|社团|活动室)|你(?:在|是|属于))[^，,]{0,16}(?:侍奉部|侍奉社|活动室|社团|学生会)|(?:侍奉部|侍奉社|活动室|社团|学生会)[^，,]{0,10}(?:的你|派你|让你来)',clause):result.add('player_affiliation')
  if re.search(r'你(?:是来|来找我|来问|又来|这次来)[^，,]{0,28}(?:委托|任务|名单|核对|活动安排)|(?:你们|你的)[^，,]{0,10}(?:委托|任务)',clause) and not re.search('什么|是不是|吗|么',clause):result.add('player_purpose')
 return result

def validate(session,reply,parts,actors,user):
 scopes=context(session,actors);fresh=new_sources(reply,parts,actors,user)
 for frame in reply['frames']:
  if frame['kind'] not in ('dialogue','thought'):continue
  aid=resolve_actor(frame.get('speaker',''),actors,user)
  if not aid or aid=='player':continue
  scope=scopes[aid];known=set(scope['known_personal_topics'])
  for text,from_player in fresh.get(aid,[]):known|=disclosures(text,session,from_player)
  text=frame['text'];claimed=claims(text,session)
  if 'player_name' not in known and any(name in text for name in aliases(session)):
   if not any(text.strip('“”" ') in source or source in text for source,_ in fresh.get(aid,[]) if source.strip()):
    claimed.add('player_name')
  unsupported=claimed-known
  if unsupported:raise ValueError('actor_knowledge.'+aid+': '+','.join(sorted(unsupported))+'没有本人获知依据；导演旁白、旧的自说自话和同班身份不能提供该事实。按当前接触程度询问，不继续旧猜测。')
  # Trusted NPC relay is limited to frames they actually heard earlier this turn.
  if frame['kind']=='dialogue':
   local=frame['stage']['present_actor_ids']
   for listener in frame.get('audience_ids',local if aid in local else []):
    if listener!=aid:fresh.setdefault(listener,[]).append((text,False))
 return scopes

FAMILIAR_LEVELS=[(0,4,'陌生'),(5,19,'眼熟'),(20,39,'初识'),(40,64,'相识'),(65,84,'熟悉'),(85,100,'熟知')]

def corrected_relation(session,actor):
 relation=copy.deepcopy(session.get('facts',{}).get('browser_engine',{}).get('relations',{}).get(actor['id'],{}))
 baseline=actor.get('relation_baseline',{})
 value=relation.get('familiarity')
 entries=session.get('facts',{}).get('browser_actor_knowledge',{}).get(actor['id'],[])
 turns={e.get('turn_id') for e in entries if e.get('part_index') is not None}
 # Narrow, read-only repair of the old neutral-30 first-contact bug; never infer
 # a past relationship for an archive with no reliable evidence.
 if 'familiarity_basis' not in relation and type(value)is int and type(baseline.get('familiarity'))is int and re.search('第一次|初次|此前无交情',relation.get('reason','')) and 0<len(turns)<=3 and abs(value-30)<=3:
  relation['familiarity']=max(0,min(100,baseline['familiarity']+value-30))
  relation['familiarity_basis']='initial-relation-v2'
 return relation

def public_familiarity(session,actors,affinity):
 portrait={c['actor_id']:c.get('avatar','') for c in affinity.get('characters',[])}
 result=[]
 for aid in portrait:
  actor=actors.get(aid)
  if not actor:continue
  relation=corrected_relation(session,actor);value=relation.get('familiarity',actor.get('relation_baseline',{}).get('familiarity'))
  if value is None:
   sources=session.get('facts',{}).get('browser_actor_knowledge',{}).get(aid,[])
   value=min(4,len({e.get('turn_id') for e in sources if e.get('part_index') is not None}))
  label=next(name for lo,hi,name in FAMILIAR_LEVELS if lo<=value<=hi)
  result.append({'actor_id':aid,'name':actor['name'],'score':value,'status':label,'avatar':portrait[aid]})
 return {'characters':result,'min':0,'max':100}
