from map_runtime import get_locations
"""Mandatory observable room arrivals. Shared large-area IDs alone are insufficient."""
import re
from world_state import read,colocated,location
from world_presentation import place_name

def small_space(definition,lid,state=None):
 p=get_locations(definition,state).get(lid,{})
 if p.get('encounter_scope')in('room','area'):return p['encounter_scope']=='room'
 name=p.get('name','')+' '+str(lid)
 if re.search(r'操场|庭院|中庭|街|公园|广场|车站|学校|高中|走廊|playground|courtyard|corridor|station|street|school',name):return False
 return bool(re.search(r'教室|活动室|侍奉[部社]|书店|图书馆|房间|办公室|学生会|家|club|classroom|room|bookshop|library|home|council',name))

def observable_arrival(state,definition,observer,actor,lid):
 if observer==actor:return True
 if not colocated(state,observer,actor):return False
 if small_space(definition,lid,state):return True
 # Large areas need a prior local interaction/observation, not a global location match.
 dialogue=read(state,'dialogue:'+observer,{})
 return any(actor in (r.get('actor'),r.get('speaker')) for r in dialogue.get('turns',[])[-3:])

def arrival_mentions(tx,records):
 """Use each event's observed after-state, never later/future presence or private names."""
 mentions=[]
 from actor_context import build_actor_view
 # Names known to the player are sourced cards, never a relation score or narrator guess.
 cards=build_actor_view(tx.initial,tx.definition,'player')['cards']
 names={c['value']['topic'][5:]:c['value']['content']for c in cards
        if c['template']=='knowledge'and c['value'].get('topic','').startswith('name-')}
 for r in records:
  p=r.get('public',{});lid=p.get('location');actor=p.get('actor')
  if r.get('template')!='builtin.arrival'or r.get('outcome')!='applied'or 'player'not in r.get('observers',[]):continue
  if not p.get('entered')or not small_space(tx.definition,lid,tx.state):continue
  if actor=='player':
   others=[a for a in r['observers']if a!='player'and a in tx.definition['characters']]
   if others:
    labels=[names.get(a,'一位同学')for a in others]
    unknown=labels.count('一位同学');numbers={1:'一位',2:'两位',3:'三位',4:'四位'}
    combined=[label for label in labels if label!='一位同学']+([numbers.get(unknown,str(unknown)+'位')+'同学'] if unknown else [])
    text='走进'+place_name(tx.definition,lid,tx.state)+'，你看见'+('、'.join(combined))+'在里面。'
    labels=combined
    mentions.append((text,labels))
  else:
   name=names.get(actor,'一位同学')
   mentions.append((name+'走进了'+place_name(tx.definition,lid,tx.state)+'。',[name]))
 return mentions

def ensure_arrivals(tx,records,text):
 # No extra LLM call: always keep a short factual notice if its prose omitted arrival.
 mentions=arrival_mentions(tx,records)
 for index,(notice,labels)in enumerate(mentions):
  ambiguous=len(mentions)>1 and any(label=='一位同学'for label in labels)
  if ambiguous and index:notice=notice.replace('一位同学','另一位同学',1)
  if ambiguous or not all(label in text for label in labels)or not re.search(r'进|到|来|门|里面|房间|已经在|站在|坐在',text):
   text=notice+('\n'+text if text else '')
 # Observable departures are actual movement, not a disclosure of private
 # schedules or destination. Names use only player knowledge at the boundary.
 names={c['value']['topic'][5:]:c['value']['content'] for c in tx.initial['cards'].values()
        if c['template']=='knowledge' and 'player' in c['visibility'] and c['value'].get('holder')=='player'
        and c['value'].get('topic','').startswith('name-')}
 for r in records:
  p=r.get('public',{});actor=p.get('actor')
  if r.get('template')!='builtin.move' or r.get('outcome')!='applied' or actor=='player' or p.get('already_here') or 'player' not in r.get('observers',[]):continue
  if not small_space(tx.definition,p.get('departure'),tx.state):continue
  name=names.get(actor,'一位同学')
  if name not in text or not re.search(r'离开|走出|出门|走了',text):
   text=name+'离开了'+place_name(tx.definition,p['departure'],tx.state)+'。'+('\n'+text if text else '')
 for r in records:
  if r.get('template')=='builtin.fixed_event' and r.get('outcome')=='applied' and 'player' in r.get('observers',[]):
   title=r.get('public',{}).get('title','')
   if title and title not in text:text='现场活动开始：'+title+'。'+('\n'+text if text else '')
 return text
