from map_runtime import get_locations
from scene_presence import visible_actor_ids
"""Actual data minimization BEFORE a model request; reader UI is deliberately separate."""
import copy,re
from world_state import location,clock_time,colocated

def build_actor_view(state,definition,actor,observations=(),recent=()):
 if actor not in definition['characters']and actor!='player':raise ValueError('Unknown actor')
 me=definition['characters'].get(actor,{'name':'玩家'})
 profile={k:copy.deepcopy(me[k])for k in ('name','personality','appearance','description','personal_background')if k in me}
 eligible=[c for c in state['cards'].values()if actor in c['visibility']]
 from scene_presence import visible_actor_ids
 present=set(visible_actor_ids(state,definition,actor))|{actor}
 def local_item(c):
  v=c['value']
  return v.get('quantity',0)>0 and (v.get('owner')==actor or v.get('location')==location(state,actor) and v.get('owner') in present|{location(state,actor)})
 cards=[copy.deepcopy(c)for c in eligible if c['template']not in('observation','personal_memory') and (c['template']!='item' or local_item(c))]+[copy.deepcopy(c)for c in eligible if c['template']=='observation'][-12:]
 for c in cards:
  if c['template']=='item':c['value']=visible_item_value(state,c,actor)
 # A public rule needs its location to be known; actual remote positions are never included.
 rules=[{'id':c['id'],'value':copy.deepcopy(c['value'])}for c in state['cards'].values()if'public_rule'in c['visibility']and c['subjects']==[location(state,actor)]]
 known_names={c['value']['topic'][5:]:c['value']['content']for c in cards if c['template']=='knowledge'and c['value']['topic'].startswith('name-')}
 local=[{'id':a,'name':known_names.get(a,'眼前的人')}for a in [*definition['characters'],'player']if a in visible_actor_ids(state,definition,actor)]
 result={'actor_id':actor,'character':profile,'story_time':clock_time(state),'state_revision':state['state_revision'],
  'location':location(state,actor),'local_people':local,'cards':cards,'local_rules':rules,
  'observations':[{k:copy.deepcopy(o[k])for k in ('event_id','template','story_time','public','outcome')if k in o}for o in observations if actor in o.get('observers',[])],
  'heard_dialogue':[copy.deepcopy(r)for r in recent if actor in r.get('audience',[])or r.get('actor')==actor]}
 result['current_time']={'date':state['clock'].get('date'),'day':state['clock']['day'],'hour':state['clock']['minute']//60,'minute':state['clock']['minute']%60,'display':f"{state['clock']['minute']//60:02d}:{state['clock']['minute']%60:02d}"}
 result['occupancy']={'other_people':len(local),'including_self':len(local)+1,'people':copy.deepcopy(local),'rule':'这是当前实际可见的人数；名字未知用描述，不把未知的人遗漏。'}
 place=get_locations(definition,state).get(location(state,actor),{})
 result['location_name']=place.get('name',location(state,actor));result['location_description']=place.get('description','')
 from map_runtime import enabled as map_enabled,known_map
 if map_enabled(definition):result['known_map']=known_map(state,definition,actor)
 from npc_schedule import enabled as schedules_enabled,temporal_issues
 if schedules_enabled(definition):
  invalid={i['card'] for i in temporal_issues(state)}
  result['cards']=[c for c in result['cards']if c['id']not in invalid]
 from story_time import horizon,available
 temporal_engine={'calendar':state['clock'],**state.get('legacy_time',{})}
 result['knowledge_horizon']=horizon(temporal_engine,me.get('knowledge_origin'))
 from fixed_events import announcements
 public=announcements(definition)
 if public['events'] or public['school_calendar']:result['public_schedule']=public
 result['dated_facts']=[{k:copy.deepcopy(c[k])for k in ('id','name','description','temporal')if k in c}
  for c in definition.get('dated_facts',[])if available(c,temporal_engine,me.get('knowledge_origin'))and actor in c.get('visible_to',[])]
 # Player's unpublished chosen identity is never included through local_people.
 return result

def visible_item_value(state,card,actor):
 value=copy.deepcopy(card['value'])
 if 'written_by' in value and value.get('written_by')!=actor:
  if not any(c['template']=='knowledge' and actor in c['visibility'] and c['value'].get('source',{}).get('kind')=='read' and c['value']['source'].get('target')==card['id'][5:] for c in state['cards'].values()):
   value.pop('written_content',None)
 return value
def build_player_view(state,definition,observations=()):return build_actor_view(state,definition,'player',observations)
def build_parser_view(state,definition):
 view=build_player_view(state,definition)
 from map_runtime import actor_locations
 view['possible_locations']=[{'id':k,'name':v.get('name',k)}for k,v in actor_locations(state,definition,'player').items()]
 view['input_interfaces']=['move','wait','say','observe','accept','decline','complete','transfer','think']
 view['action_targets']={'items':[{'instance':c['id'][5:],'name':definition['items'][c['value']['item']]['name']}for c in view['cards']if c['template']=='item'and c['value']['quantity']],
  'opportunities':[{'id':c['id'][6:],'title':c['value']['title'],'status':c['value']['status']}for c in view['cards']if c['template']=='opportunity']}
 return view

def event_description(record,definition,reader=True,state=None):
 p=record.get('public',{});kind=record['template'];names={k:c['name']for k,c in definition['characters'].items()}|{'player':'主角'}
 effect=next((e for e in record.get('effects',[])if e.get('template')==kind),{})
 actor=p.get('actor',effect.get('actor'))
 place=lambda lid:get_locations(definition,state).get(lid,{}).get('name',lid or'途中')
 who=lambda actor:names.get(actor,actor or'人物')if reader else'眼前的人'if actor!='player'else'你'
 if record.get('outcome')=='rejected':
  from player_feedback import readable
  return '这次尝试没有完成：'+readable(p.get('reason','条件未满足'))
 if p.get('already_owned'):return who(p.get('actor'))+'已经持有这件物品，无须再次拿取。'
 if p.get('already_here'):return who(p.get('actor'))+'仍在'+place(p.get('location'))+'。'
 if kind=='builtin.move':return who(p.get('actor'))+'离开了'+place(p.get('departure'))+'。'
 if kind=='builtin.arrival':return who(p.get('actor'))+'到达'+place(p.get('location'))+('。'if p.get('entered')else'门外；此处已关闭。')
 if kind=='builtin.say':
  from speech_channels import split_text
  text=p.get('text','')
  try:text=split_text(text)[0]
  except ValueError:pass
  return who(p.get('actor'))+'：'+text
 if kind=='builtin.offer':return who(actor)+'向'+who(effect.get('target','player'))+'提出邀请：'+p.get('title',record['title'])+'。'
 if kind in('builtin.accept','builtin.decline','builtin.complete'):
  verb={'builtin.accept':'接下了','builtin.decline':'谢绝了','builtin.complete':'完成了'}[kind]
  return who(actor)+verb+p.get('title',record['title']).rsplit(' · ',1)[0]+'。'
 if kind=='builtin.transfer':return who(actor)+'将'+definition['items'].get(p.get('item'),{}).get('name',p.get('item','物品'))+'交给'+who(effect.get('target'))+'。'
 if kind=='builtin.observe':
  return who(actor)+'看着'+p.get('target_name','眼前的人' if p.get('target') in definition['characters'] else '眼前的对象')+'。'
 if kind in('builtin.knock','builtin.sit','builtin.stand','builtin.sit_up','builtin.lie_down','builtin.gesture','builtin.write'):
  verb={'builtin.knock':'敲了敲门','builtin.sit':'坐了下来','builtin.stand':'站起身','builtin.sit_up':'从躺姿坐起身','builtin.lie_down':'躺了下来','builtin.gesture':'作出示意','builtin.write':'写下记录','builtin.observe':'观察周围'}[kind]
  detail=p.get('text',effect.get('text',''))if kind in('builtin.gesture','builtin.write')else''
  return who(actor)+verb+('：'+detail if detail else'。')
 if kind in('builtin.take','builtin.put_down','builtin.read','builtin.consume','builtin.use'):
  if kind=='builtin.consume' and p.get('portion')=='small':
   name=definition['items'].get(p.get('item'),{}).get('name','随身的食物')
   verb='喝了一小口' if re.search('水|咖啡|饮|茶',name) else '吃了一小口'
   return who(actor)+verb+name+'。'+('这一份已经用完。' if p.get('finished_unit') else '还剩一些。')
  verb={'builtin.take':'拿起了','builtin.put_down':'放下了','builtin.read':'阅读了','builtin.consume':'食用了','builtin.use':'使用了'}[kind]
  return who(p.get('actor'))+verb+definition['items'].get(p.get('item'),{}).get('name',p.get('item','物品'))+'。'+(p.get('content','')if kind=='builtin.read'else'')
 if kind=='builtin.search':return who(p.get('actor'))+'进行了搜索，'+('发现了可观察的物品。'if p.get('found')else'没有发现目标。')
 if kind=='builtin.explore':return who(p.get('actor'))+'查看了眼前的区域，'+('发现'+p['name']+'的入口。'if p.get('discovered')else'没有发现新的通路。')
 if kind=='builtin.buy':return who(p.get('actor'))+'买到了'+p.get('name','普通日常物品')+'。'
 if kind=='builtin.fixed_event':return p.get('title','活动')+'：'+p.get('text','')
 if kind=='builtin.location_notice':return p.get('text','')
 if kind in ('builtin.open','builtin.close'):return who(actor)+('打开了门。' if kind=='builtin.open' else '关上了门。')
 if kind in ('builtin.open_item','builtin.close_item'):
  return who(actor)+('翻开了' if kind=='builtin.open_item' else '合上了')+definition['items'].get(p.get('item'),{}).get('name','手边的材料')+'。'
 if kind=='builtin.visible_activity':
  if p.get('action')=='consume' and p.get('portion')=='small':return who(actor)+'尝了一小口随身的食物或饮品。'
  return who(actor)+{'read':'翻阅了手边的材料。','write':'在手边的材料上写了些字。','consume':'吃掉了随身的食物。'}.get(p.get('action'),'做了眼前的事情。')
 if kind=='builtin.activity':return who(actor)+{'visit':'到达了'+place(p.get('location'))+'。','read':'读完了手头的材料。','rest':'结束了片刻休息。','obtain':'拿到了要找的物品。','inquire':'结束了一次询问。'}.get(p.get('kind'),'完成了眼前的活动。')
 if kind=='builtin.availability':return place(p.get('location'))+('开放了。'if p.get('open')else'关闭了。')
 if kind=='builtin.learn'and reader:return '\n'.join(e.get('content','')for e in record.get('effects',[]))
 if record.get('outcome')=='rejected':return '这次尝试没有完成：'+p.get('reason','条件未满足')
 return record['title']if reader else p.get('title','身边的状态发生了变化。')

def export_events(packets,definition,view='protagonist',format='txt'):
 if format not in('txt','md'):raise ValueError('Unsupported event export format')
 rows=[];cursor=0
 while True:
  part=build_event_reader_view(packets,definition,view,cursor,100);rows.extend(part['entries'])
  if part['next_cursor']is None:break
  cursor=part['next_cursor']
 title='世界事件记录'if view=='world'else'主角事件记录'
 lines=[('# 'if format=='md'else'')+title,'读者视角；查看此文档不会令人物获得其中的信息。','']
 for row in reversed(rows):lines.extend([row['display_time']+' · '+row['title'],row['description'],''if row['protagonist_knows']else'主角尚未获知',''])
 return '\n'.join(lines).encode('utf-8')
STORY_EVENTS=frozenset('builtin.'+kind for kind in (
 'move','arrival','say','observe','offer','accept','decline','complete','transfer',
 'take','put_down','read','consume','use','search','knock','sit','stand','sit_up','lie_down','gesture','write','open','close','open_item','close_item','visible_activity','explore','buy','fixed_event','location_notice'))

def is_story_event(record):
 """Default-deny engine bookkeeping, including future diagnostic templates."""
 return (record.get('template')in STORY_EVENTS and record.get('outcome')=='applied'
         and not record.get('public',{}).get('already_owned')and not record.get('public',{}).get('already_here'))

def build_event_reader_view(packets,definition,view='protagonist',cursor=0,limit=50):
 if view not in('world','protagonist'):raise ValueError('Unknown event view')
 limit=max(1,min(int(limit),100));cursor=max(0,int(cursor))
 states={r['event_id']:p.get('state_after') for p in packets for r in p['records']}
 records=[r for p in packets for r in p['records']if is_story_event(r)]
 if view=='protagonist':records=[r for r in records if'player'in r.get('participants',[])or'player'in r.get('observers',[])]
 rows=[]
 for r in reversed(records):
  row={k:copy.deepcopy(r.get(k))for k in ('event_id','story_time','template','outcome','participants')}
  row['protagonist_knows']='player'in r.get('observers',[]);rows.append(row)
  minute=r['story_time'];row['display_time']=f'第 {minute//1440+1} 天 · {minute%1440//60:02d}:{minute%60:02d}'
  row['description']=event_description(r,definition,state=states.get(r['event_id']))
  row['title']=row['description'][:70]+('…'if len(row['description'])>70 else'')
  row['status_label']={'applied':'已发生','rejected':'未完成','quiet':'平静','deferred':'暂缓'}.get(r['outcome'],'已记录')
 return {'view':view,'total':len(rows),'entries':rows[cursor:cursor+limit],'next_cursor':cursor+limit if cursor+limit<len(rows)else None}
def authorize_claims(view,claims,text):
 ids={c['id']:c for c in view['cards']if c['template']=='knowledge'}
 for cid in claims:
  if cid not in ids:raise ValueError('Unauthorized referenced knowledge')
  if ids[cid]['value'].get('disclose')is False:raise ValueError('Known but forbidden to disclose')
 return True
def forbidden_literals(state,actor,disclosure=False,known_literals=()):
 known=set(known_literals)|{c['value']['content'] for c in state['cards'].values()
  if c['template']=='knowledge' and actor in c['visibility'] and (not disclosure or c['value'].get('disclose',True))}
 values=[c['value']['content']for c in state['cards'].values()if c['template']=='knowledge'and
  ((actor not in c['visibility'] and c['value']['content'] not in known)or
   disclosure and actor in c['visibility'] and not c['value'].get('disclose',True))and len(c['value']['content'])>3]
 return list({term for value in values for term in [value,*re.findall(r'(?<!\d)\d{4,}(?!\d)|\b[A-Z]{2,}[-_][A-Z0-9]{3,}\b',value)]})
def validate_no_literal_leak(state,actor,text,disclosure=False,known_literals=()):
 if any(s in text for s in forbidden_literals(state,actor,disclosure,known_literals)):raise ValueError('Registered secret leaked in generated text')
 return True
