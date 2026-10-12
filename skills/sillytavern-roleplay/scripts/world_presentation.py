from map_runtime import get_locations
"""Grounded titles and location labels; old saves are projected, never rewritten."""
import copy,re

GENERIC_TITLES={'世界里的下一刻','已发生的片段','故事片段'}

def place_name(definition,location,state=None):
 return get_locations(definition,state).get(location,{}).get('name',location or '')

def short(text,limit=26):
 text=re.sub(r'【[^】]+】','',str(text)).strip().replace('\n',' ')
 return text if len(text)<=limit else text[:limit-1]+'…'

def turn_title(turn,definition):
 """Only this turn's confirmed, player-visible events may name its progress."""
 from actor_context import is_story_event,event_description
 records=turn.get('world_packet',{}).get('records',[])
 state=turn.get('world_packet',{}).get('state_after')
 visible=[r for r in records if is_story_event(r)and 'player'in r.get('observers',[])]
 own=[r for r in visible if r.get('public',{}).get('actor')=='player']
 actions=[r for r in own if r['template']!='builtin.say']
 if actions:
  last=actions[-1];p=last.get('public',{})
  if last['template']=='builtin.arrival':return '来到'+place_name(definition,p.get('location'),state)
  if last['template']=='builtin.read':
   state=turn.get('world_packet',{}).get('state_after',{})
   instance=p.get('instance',next((e.get('instance')for e in last.get('effects',[])if e.get('instance')),None))
   item=state.get('cards',{}).get('item:'+str(instance),{}).get('value',{}).get('item')
   return short('阅读'+definition.get('items',{}).get(item,{}).get('name','手中的资料'))
  return short(event_description(last,definition,False,state).rstrip('。'))
 speeches=[r.get('public',{}).get('text','')for r in own if r['template']=='builtin.say']
 if speeches:
  text=speeches[-1]
  if re.search(r'(?:名字|姓名|怎么称呼|如何称呼)',text)and re.search(r'吗|什么|可以|请问|怎么|如何|？|\?',text):return '询问姓名'
  return short(text.rstrip('。！？?'))
 if visible:return short(event_description(visible[-1],definition,False,state).rstrip('。'))
 frames=turn.get('frames',[])
 if any(f.get('system_feedback')for f in frames)or any(r.get('template')=='builtin.input_rejection'for r in records):return '行动尚未执行 · '+short(turn.get('user',''),16)
 return short(turn.get('user','')) or '片刻停留'

def story_text(text,definition,state=None):
 """Registered location IDs are implementation details, even in fallback prose."""
 for lid in sorted(get_locations(definition,state),key=len,reverse=True):
  label=place_name(definition,lid,state)
  if label!=lid:text=re.sub(r'(?<![A-Za-z0-9_-])'+re.escape(lid)+r'(?![A-Za-z0-9_-])',lambda _:label,text)
 return text

def story_projection(session,story):
 definition=session.get('facts',{}).get('browser_world_definition')
 if not definition:return copy.deepcopy(story)
 result=copy.deepcopy(story);turns={t['turn_id']:t for t in session.get('turns',[])}
 for node in result.get('nodes',[]):
  if node.get('title')in GENERIC_TITLES or not node.get('title'):
   t=turns.get(node.get('id'))
   if t:node['title']=turn_title(t,definition)
  t=turns.get(node.get('id'),{})
  node['scene']=place_name(definition,node.get('scene',''),t.get('world_packet',{}).get('state_after'))
 if result.get('thread')in GENERIC_TITLES and result.get('nodes'):result['thread']=result['nodes'][-1]['title']
 return result

def save_projection(session):
 definition=session.get('facts',{}).get('browser_world_definition')
 if not definition:return {}
 story=story_projection(session,session.get('facts',{}).get('browser_story',{}))
 latest=story.get('nodes',[])
 title=latest[-1].get('title','')if latest else ''
 world=session.get('world_snapshot')or session.get('facts',{}).get('browser_world_snapshot',{})
 scenario=session.get('facts',{}).get('browser_scenario')
 opening=next((o for o in world.get('opening_scenes',[])if o.get('id')==scenario),{})
 expected=session.get('save_title_generated')
 if not expected and world.get('name')and opening.get('title'):
  expected=f"{world['name']} · {opening['title']} · {session.get('user_name','')}"
 custom=session.get('save_title_custom',False)or not expected or session.get('title')!=expected
 scene=place_name(definition,session.get('scene',''),session.get('facts',{}).get('browser_world_state'))
 # The metadata name remains available to the editor and family header.
 return {'display_title':session.get('title','')if custom else title or session.get('title',''),
         'latest_event':title,'scene':scene,'summary':' · '.join(x for x in (scene,title)if x)}

def visual_location(world,definition,physical,previous,state=None):
 visuals=world.get('visual_locations',{})
 exact=next((key for key,aliases in visuals.items()if physical==key or physical in aliases),None)
 if exact:return exact
 from map_runtime import ancestors
 for parent in ancestors(definition,state,physical)[1:]:
  inherited=next((key for key,aliases in visuals.items()if parent==key or parent in aliases),None)
  if inherited:return inherited
 name=place_name(definition,physical,state)
 # Generic old classroom IDs still need a classroom picture, not the prior club.
 if physical=='classroom' or name=='教室':
  return next((key for key in visuals if key.startswith('classroom')),'classroom')
 return physical if physical in get_locations(definition,state) else previous
