from map_runtime import get_locations
"""Resolve local referents without inventing places, items or past actions."""
import copy,re
from world_state import read,location

class GroundingError(ValueError):pass

def player_context(session,definition):
 state=session['facts']['browser_world_state'];here=location(state,'player')
 world=session.get('world_snapshot')or session['facts'].get('browser_world_snapshot',{})
 me=session.get('protagonist_snapshot')or session['facts'].get('browser_protagonist_snapshot',{})
 recent=[]
 turns=session.get('turns',[])[-3:]
 for turn in turns:
  frames=session['facts'].get('browser_turn_frames',{}).get(turn['turn_id'],[])
  if turn['turn_id']=='opening':frames=session['facts'].get('browser_opening_frames',frames)
  for f in frames:
   # Only published local speech; no NPC thoughts, goals, global summary or other save.
   if f.get('kind')=='dialogue'and f.get('stage',{}).get('location')==here:
    recent.append({'speaker':f.get('speaker','眼前的人'),'text':f.get('text','')[:700]})
 places=get_locations(definition,state);name=places.get(here,{}).get('name',here)
 aliases=[name,*world.get('visual_locations',{}).get(here,[])]
 defaults=world.get('protagonist_defaults',{}).get(me.get('id'),{})
 bindings=definition['config'].get('player_location_bindings',{})
 classroom=(bindings.get('classroom_id') or definition['config'].get('school_calendar',{}).get('player_classroom')
            or me.get('classroom_id') or defaults.get('classroom_id'))
 from map_runtime import actor_locations
 known=actor_locations(state,definition,'player')
 home=me.get('home_id') or world.get('player_homes',{}).get(me.get('id')) or defaults.get('home_id')
 room=me.get('room_id') or defaults.get('room_id')
 return {'current_location':here,'current_location_name':name,'current_aliases':aliases,
         'recent_local_speech':recent[-5:],'own_classroom':classroom if classroom in known else None,'own_home':home if home in places else None,'own_room':room if room in places else None}

def classroom_destination(tx,text):
 """Resolve only a complete ordinary movement, never speech or a mixed action.

 Entering the room of an ongoing local conversation retains that referent;
 otherwise a bare classroom means the player's known, frozen class binding.
 """
 m=re.fullmatch(r'(?:我)?(?:现在|这就|直接)?(前往|走进|进入|回到|走到|去|回)\s*(教室|我们班|本班|班里|班上|自己的教室|自己的班级教室|自己班的教室|我们班的教室)[。！？!\s]*',text.strip())
 if not m:return None
 context=getattr(tx,'player_context',{})
 from map_runtime import actor_locations
 known=actor_locations(tx.state,tx.definition,'player')
 here=context.get('current_location',location(tx.state,'player'))
 local_name=known.get(here,{}).get('name','')
 if (m[2]=='教室' and m[1] in ('走进','进入','走到','去') and context.get('recent_local_speech')
     and re.search(r'教室|活动室|侍奉[部社]|clubroom',local_name+' '+str(here))):
  if re.search(r'门口|门外|门前',local_name):
   adjacent=[lid for lid in known.get(here,{}).get('links',{})
             if lid in known and known[lid].get('name') and known[lid]['name'] in local_name
             and not re.search(r'门口|门外|门前',known[lid]['name'])]
   return adjacent[0] if len(adjacent)==1 else None
  return here
 own=context.get('own_classroom')
 if own in known and known[own].get('walkable',True):return own
 return None

def explicit_place(text,definition,state=None):
 return [lid for lid,p in get_locations(definition,state).items()
         if p.get('name')and p['name']not in('教室','房间','活动室')and p['name']in text]

def ground_move(step,tx):
 if step.get('type')!='move':return
 text=step['evidence']
 # Resolve a demonstrative using the rest of this same action input, not an old model sentence.
 if re.search(r'那间|该教室|那间房间|那里',text):text=getattr(tx,'grounding_input',text)
 dest=step.get('params',{}).get('location');places=get_locations(tx.definition,tx.state)
 from map_references import DISCOVERY_REFERENCE,resolve_reference
 movement=re.fullmatch(r'(?:我)?(?:现在|然后|接着|再)?(?:前往|走进|进入|去|回到|走到)\s*(.+?)[。！？!，,\s]*',text.strip())
 reference=DISCOVERY_REFERENCE.fullmatch(movement[1])if movement else None
 if reference:
  binding=resolve_reference(tx.state,tx.definition,'player',reference.group())
  if binding and binding.get('destination'):
   from map_runtime import navigation_failure
   reason=navigation_failure(tx.state,tx.definition,'player',binding['destination'])
   if reason:raise GroundingError(reason)
   step['params']['location']=binding['destination'];return
  if binding:raise GroundingError(binding['question'])
 context=getattr(tx,'player_context',{});here=context.get('current_location',location(tx.state,'player'))
 classroom=classroom_destination(tx,text)
 if classroom is not None:
  from map_runtime import navigation_failure
  reason=navigation_failure(tx.state,tx.definition,'player',classroom)
  if reason:raise GroundingError(reason)
  step['params']['location']=classroom;return
 if re.search(r'(?:回|去|进入)(?:自己|我)(?:的)?房间',text):
  if not context.get('own_room'):raise GroundingError('你的房间还没有指定，请说明实际地点。')
  step['params']['location']=context['own_room'];return
 if re.search(r'回家|去自己(?:的)?家',text):
  if not context.get('own_home'):raise GroundingError('你的家还没有指定，请说明回家的目的地。')
  step['params']['location']=context['own_home'];return
 explicit=explicit_place(text,tx.definition,tx.state)
 from map_runtime import enabled as map_enabled
 if map_enabled(tx.definition):
  request=re.fullmatch(r'(?:我)?(?:现在|这就|直接)?(?:前往|走进|进入|回到|去)\s*([^，。！？]+)[。！？]?',text.strip())
  if request and not re.search(r'自己|我们班|这里|那里|这间|那间',request[1]):
   from map_exploration import resolve_intent
   binding=resolve_intent(tx.state,tx.definition,'player',request[1].strip())
   if binding.get('destination')!=dest:
    raise GroundingError(binding.get('question','目的地不唯一，请说明已知地点。'))
   from map_runtime import navigation_failure
   reason=navigation_failure(tx.state,tx.definition,'player',dest)
   if reason:raise GroundingError(reason)
   return
 if explicit and dest not in explicit:
  raise GroundingError('目的地与输入明确提到的地点不一致，请保留实际地点。')
 if not explicit and re.search(r'走进这里|进入这里|这间(?:教室|房间|活动室)',text)and dest!=here:
  raise GroundingError('“这里/这间房间”指向当前场景，不能无依据换成其他地点。')
 if not re.search(r'教室|房间|活动室',text)or explicit:return
 if re.search(r'自己(?:班|的)?|我们班|本班|回班|回到班',text):
  expected=context.get('own_classroom')
  if not expected:raise GroundingError('主角的班级教室尚未确定，请说明是哪间教室。')
  step['params']['location']=expected;return
 if re.search(r'其他|另一|别的|隔壁|某个|随便',text):
  raise GroundingError('这里有多个教室，请说明要去哪个班或哪个房间。')
 local_name=places.get(here,{}).get('name','')
 room=bool(re.search(r'教室|活动室|侍奉[部社]|clubroom',local_name+' '+str(here)))
 if room and context.get('recent_local_speech'):
  referent=here
  if re.search(r'门口|门外|门前',local_name)and re.search(r'进|进入',text):
   adjacent=[lid for lid in places.get(here,{}).get('links',{})
             if places[lid].get('name')and places[lid]['name']in local_name and not re.search(r'门口|门外|门前',places[lid]['name'])]
   if len(adjacent)==1:referent=adjacent[0]
   else:raise GroundingError('门口附近有多个房间，请说明要进入哪一间。')
  # A room mentioned during an ongoing local conversation refers to that scene.
  # Keep the model's proposal only when it matches; retry/clarify otherwise.
  if dest!=referent:raise GroundingError('当前交谈地点是'+local_name+'；“教室/房间”应结合这里的对话判断，不能无依据切换到另一间教室。')
  return
 if dest==here and room:return
 raise GroundingError('“教室”不能唯一确定目的地，请说明是当前房间、自己的班级教室还是其他教室。')

def validate_item_reference(action,text,state,definition):
 if action.get('type')not in('read','take','put_down','eat','give','use','observe','write'):return
 params=action.get('params',{});instance=params.get('instance',params.get('target',''))
 obj=read(state,'item:'+str(instance),{})
 if not obj:return
 item=definition.get('items',{}).get(obj.get('item'),{});name=item.get('name','')
 intended=[k for k,v in definition.get('items',{}).items()
           if v.get('name')and(v['name']in text or len(v['name'])>3 and v['name'][-2:]in text)]
 if len(intended)==1 and obj.get('item')!=intended[0]:
  raise GroundingError('动作对象与输入明确提到的物品不一致，不能替换物品。')
 # Reading capability does not make a notebook, form or letter a book.
 book=bool(re.search(r'(?:看|读|阅读)[^，。！？\n]{0,8}书|文库本|小说|这本书|那本书',text))
 explicit_actual=(name and name in text)or obj.get('item')in intended
 is_book=(item.get('category')=='book'or bool(re.search(r'书|小说|文库本',name)))and not re.search(r'笔记|申请|表格|信封|书包',name)
 if book and not explicit_actual and not is_book:
  raise GroundingError('你说的是书，不能把随身笔记本、表格或其他可读物品当成这本书。请确认实际要读或取得的书。')

def parser_context(tx,view):
 result=copy.deepcopy(view)
 result['scene_context']=copy.deepcopy(getattr(tx,'player_context',{}))
 result['pending_input']=copy.deepcopy(getattr(tx,'prior_pending',None))
 from map_references import recent_discoveries
 result['recent_discoveries']=recent_discoveries(tx.state,tx.definition,'player')
 return result
