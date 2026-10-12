"""Build conservative world-mode data from existing content, only for a new save."""
import copy

def mode_options(world):
 if world.get('world_modes') is not None:return copy.deepcopy(world['world_modes'])
 if world.get('event_system'):return None
 if world.get('opening_scenes') and world.get('setting_set_ids'):
  return {'version':1,'default':'sandbox','enabled':['sandbox','world']}
 return None

def prepare_world(world,protagonist,opening):
 result=copy.deepcopy(world)
 if result.get('event_system'):return compile_features(result,protagonist)
 cards=[c for s in result.get('setting_sets',[])for c in s.get('cards',[])]
 player_id=protagonist.get('id','');player_name=protagonist.get('name','玩家')
 # The chosen protagonist is controlled by the player, not duplicated as an NPC.
 for settings in result.get('setting_sets',[]):
  settings['cards']=[c for c in settings['cards']if not(c.get('kind')=='character'and(c['id']==player_id or c['name']==player_name))]
 actors=[c for s in result.get('setting_sets',[])for c in s['cards']if c['kind']=='character']
 # Legacy inventory is explicit author data, not an inference from a background image.
 declared_items={c['id']:c for c in cards if c['kind']=='item'}
 for iid,item in result.get('initial_items',{}).items():
  if iid not in declared_items:
   name=item.get('name')
   if not name:raise ValueError('初始物品 '+iid+' 缺少定义和名称。')
   caps=copy.deepcopy(item.get('capabilities',{}))
   if '笔记本' in name and not caps:caps={'read':{'content':''},'write':{}}
   card={'id':iid,'kind':'item','name':name,'description':item.get('description','剧本明确声明的初始物品。'),'capabilities':caps}
   result['setting_sets'][0]['cards'].append(card);cards.append(card);declared_items[iid]=card
 locations={c['id']:{'name':c['name'],'description':c.get('description',''),'links':{}}for c in cards if c['kind']=='location'}
 for key,aliases in result.get('visual_locations',{}).items():
  locations.setdefault(key,{'name':aliases[0]if aliases else key,'description':'剧本中的地点。','links':{}})
 if not locations:raise ValueError('世界模式需要至少一个地点卡。')
 # Optional author links take precedence. Otherwise freeze a modest default map,
 # explicitly marked as a shell approximation, never as canonical floor numbers.
 declared={c['id']:c.get('links',{})for c in cards if c['kind']=='location'}
 hub='corridor'if'corridor'in locations else next(iter(locations))
 for lid,place in locations.items():
  place['links']={dest:minutes for dest,minutes in declared.get(lid,{}).items()if dest in locations}
 if not any(p['links']for p in locations.values()):
  for lid in locations:
   if lid!=hub:
    minutes=10 if lid in('street','station','shopping-street')else 3
    locations[hub]['links'][lid]=minutes;locations[lid]['links'][hub]=minutes
  if'clubroom'in locations and'club-door'in locations:
   locations['clubroom']['links']['club-door']=1;locations['club-door']['links']['clubroom']=1
 here=opening.get('location_id') or opening.get('background','')
 if here not in locations:
  variants=[key for key in locations if here.startswith(key+'-')]
  here=max(variants,key=len) if variants else next((key for key,aliases in result.get('visual_locations',{}).items()if any(alias in str(opening.get('scene',''))for alias in aliases)),hub)
 present={f.get('speaker')for f in opening.get('opening',[])if f.get('kind')=='dialogue'}
 positions={'player':here};initial=[]
 for card in actors:
  aid=card['id'];positions[aid]=here if card['name']in present else card.get('initial_location',card.get('classroom_id'))
  if positions[aid]not in locations:
   # Unspecified actors are offstage, not an invented crowd in the corridor.
   offstage='offstage-'+aid
   locations[offstage]={'name':'尚未入镜的活动范围','secret':True,'encounter_scope':'area','links':{hub:3}}
   positions[aid]=offstage
  preset=card.get('initial_relation',{}).get(player_id,{})
  affinity=card.get('initial_affinity',{}).get(player_id,card.get('initial_affinity',{}).get('default',{}))
  card['event_relation']={'affection':affinity.get('score',30),'trust':preset.get('trust',30),
   'familiarity':preset.get('familiarity',0),'identity':preset.get('identity','')}
  recognition=card.get('initial_recognition',{}).get(player_id,{})
  if recognition.get('knows_name'):
   initial.append({'template':'builtin.learn','actor':aid,'topic':'name-player','content':player_name,
    'source':{'kind':'script_initial_recognition'},'belief':'observed'})
  if player_name in card.get('aliases',[]):continue
  for fact in card.get('personal_background',{}).get('facts',[]):
   initial.append({'template':'builtin.learn','actor':aid,'topic':'background-'+fact['id'],'content':fact['text'],
     'source':{'kind':'script_personal_background','sources':fact.get('sources',[])},'belief':'observed'})
  # The player may identify a scripted opening speaker; this does not teach the
  # speaker the player's name or any off-screen plans.
  if card['name']in present:
   initial.append({'template':'builtin.learn','actor':'player','topic':'name-'+aid,'content':card['name'],
    'source':{'kind':'opening_cast'},'belief':'observed'})
 # Preserve factual item introductions in the selected opening; never create all
 # scenario items merely because an item card exists in the setting collection.
 opening_text=' '.join(f.get('text','')for f in opening.get('opening',[]))
 for card in[c for c in cards if c['kind']=='item']:
  if card['name']in opening_text:
   initial.append({'template':'builtin.spawn','item':card['id'],'instance':'opening-'+card['id'],
    'owner':here,'location':here,'quantity':1})
 result['world_modes']={'version':1,'default':'sandbox','enabled':['sandbox','world']}
 result['event_system']={'version':1,'builtin_version':1,'locations':locations,'actor_locations':positions,
  'initial':initial,'seed':result.get('id','')+'-world-v1','default_map':True,'shell_methods':True,
  'goal_sets':{'version':1,'generation':'shell','max_active':2,'max_pulses':12}}
 authored=result.get('world_defaults',{})
 result['event_system']['doors']=copy.deepcopy(authored.get('doors',{}))
 for lid,place in authored.get('locations',{}).items():
  locations.setdefault(lid,copy.deepcopy(place))
 for source,links in authored.get('links',{}).items():
  if source in locations:locations[source]['links'].update(copy.deepcopy(links))
 for actor,destination in authored.get('actor_locations',{}).items():
  if actor in positions and destination in locations and actor not in {c['id']for c in actors if c['name']in present}:
   positions[actor]=destination
 for entry in authored.get('initial',[]):
  if entry.get('opening_ids') and opening['id']not in entry['opening_ids']:continue
  effect=copy.deepcopy(entry['effect'])
  if effect.get('actor') not in (None,'player',*positions):continue
  if effect.get('owner') not in (None,'player',*positions,*locations):continue
  initial.append(effect)
 if authored.get('goal_sets'):
  cfg=copy.deepcopy(authored['goal_sets'])
  for window in cfg.get('windows',[]):window['actors']={a:g for a,g in window.get('actors',{}).items()if a in positions and a!='player'}
  result['event_system']['goal_sets']=cfg
 # Initial legacy inventory must also exist in the authoritative world state.
 for iid,item in result.get('initial_items',{}).items():
  owner=item.get('owner','player');destination=positions.get(owner,item.get('location',here))
  if destination not in locations:raise ValueError('初始物品 '+iid+' 的地点未声明。')
  if not any(e.get('template')=='builtin.spawn' and e.get('instance')==iid for e in initial):
   initial.append({'template':'builtin.spawn','item':iid,'instance':iid,'owner':owner,'location':destination,'quantity':item.get('quantity',1)})
 return compile_features(result,protagonist)


def compile_features(world,protagonist=None):
 """Called only while preparing a NEW frozen world, never on saved sessions."""
 config=world.get('event_system')
 if not config:return world
 features=world.get('features',config.get('features',[]))
 config['features']=copy.deepcopy(features)
 if 'map' in world:
  from map_schema import validate_map
  config['map']=validate_map(world['map'],flat=config['locations'])
  # Compatibility compiler output; runtime readers use map_runtime exclusively.
  config['locations']=copy.deepcopy(config['map']['nodes'])
 if 'schedules' in world:config['schedules']=copy.deepcopy(world['schedules'])
 for field in ('daily_life','relation_policy','fixed_events','opening_hours','school_calendar'):
  if field in world:config[field]=copy.deepcopy(world[field])
  elif field in world.get('world_defaults',{}):config[field]=copy.deepcopy(world['world_defaults'][field])
 from relation_policy import DEFAULT
 config.setdefault('relation_policy',copy.deepcopy(DEFAULT))
 from daily_life import compile_items
 config.setdefault('daily_life',{'enabled':True,'services':{},'accounting':'abstract'})
 compile_items(world)
 if config.get('fixed_events'):
  features=config['features']
  if 'npc_schedule_v1' not in features:features.append('npc_schedule_v1')
 if protagonist and ('map_v1' in features or 'exploration_v1' in features):
  defaults=world.get('protagonist_defaults',{}).get(protagonist.get('id'),{})
  config['player_location_bindings']={field:protagonist.get(field) or defaults.get(field) for field in ('home_id','classroom_id','room_id')}
  config['player_location_bindings']['home_id']=config['player_location_bindings'].get('home_id') or world.get('player_homes',{}).get(protagonist.get('id'))
 if config.get('school_calendar') and protagonist:
  defaults=world.get('protagonist_defaults',{}).get(protagonist.get('id'),{})
  config['school_calendar']['player_classroom']=protagonist.get('classroom_id') or defaults.get('classroom_id')
 return world
