"""A cited private source is not an utterance; addressed person is not all listeners."""
import re

def named_addressees(definition,text):
 """Recognize a vocative, not a third-person mention or a private known identity."""
 names={}
 for actor,card in definition['characters'].items():
  aliases=card.get('aliases',[])
  # An author-confirmed short given name permits its complementary surname;
  # no hardcoded franchise name list or guessed Western surname is needed.
  families=[card['name'][:-len(a)]for a in aliases if 1<=len(a)<=3 and card['name'].endswith(a) and len(card['name'])>len(a) and not re.search(r'[A-Za-z\s]',a)]
  for name in [card['name'],*aliases,*families]:
   if not name:continue
   for form in (name,name+'同学',name+'さん',name+'君',name+'老师'):
    names.setdefault(form,set()).add(actor)
 head=text.strip().lstrip('“「')
 head=re.sub(r'^(?:我想问(?:一下)?|想问(?:一下)?|请问|问(?:一下)?|我转向|我对)','',head).strip()
 # Prefer the complete, longest address; a shared surname remains ambiguous.
 for form in sorted(names,key=len,reverse=True):
  if re.match(re.escape(form)+r'(?:[，,。:：\s]|[？?！!]|$)',head):return sorted(names[form])
 return []

def addressed_repliers(definition,speech):
 """Restrict a leading explicit vocative. Everyone present can still hear."""
 audience=speech['audience'];text=speech['text'].strip().lstrip('“「')
 explicit=named_addressees(definition,text)
 if explicit:return [a for a in explicit if a in audience]
 head=re.split(r'[，,。:：]',text,1)[0]
 matches=[a for a in audience if a!='player' and head in [definition['characters'][a]['name'],*definition['characters'][a].get('aliases',[])]]
 if matches:return matches
 if len(head)>=2:
  partial=[a for a in audience if a!='player' and definition['characters'][a]['name'].startswith(head)]
  if len(partial)==1:return partial
 if head=='老师':
  matches=[a for a in audience if a!='player' and ('老师'in definition['characters'][a]['name'] or '教师'in str(definition['characters'][a].get('school','')))]
  if len(matches)==1:return matches
 return [a for a in audience if a!='player'][:3]

def known_addresses(state,definition,observer):
 """Aliases are offered only for locally seen people whose identity was learned."""
 from scene_presence import visible_actor_ids
 from world_state import read
 result=[]
 for actor in visible_actor_ids(state,definition,observer):
  card=definition['characters'].get(actor)
  if not card:continue
  name=read(state,'know:'+observer+':name-'+actor,{}).get('content')
  if not name:continue
  addresses=[name]
  if name==card['name']:
   aliases=card.get('aliases',[])
   families=[name[:-len(a)]for a in aliases if 1<=len(a)<=3 and name.endswith(a)and len(name)>len(a)and not re.search(r'[A-Za-z\s]',a)]
   addresses.extend([*aliases,*families])
   addresses.extend(n+'同学'for n in [name,*aliases,*families]if not re.search(r'[A-Za-z\s]',n))
  result.append({'id':actor,'name':name,'addresses':list(dict.fromkeys(addresses))})
 return result
