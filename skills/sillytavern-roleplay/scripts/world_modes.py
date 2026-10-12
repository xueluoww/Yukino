"""New-save mode selection. Never reinterpret an existing save or modify a library world."""
import copy

MODES=('sandbox','world')

def validate_modes(world):
 config=world.get('world_modes')
 if config is None:return None
 if not isinstance(config,dict)or set(config)-{'version','default','enabled'}or config.get('version')!=1:raise ValueError('Invalid world modes contract')
 enabled=config.get('enabled',['sandbox','world'])
 if not isinstance(enabled,list)or not enabled or len(set(enabled))!=len(enabled)or any(x not in MODES for x in enabled):raise ValueError('Invalid enabled modes')
 if config.get('default','sandbox')not in enabled:raise ValueError('Default mode must be enabled')
 if 'world'in enabled and not world.get('event_system'):raise ValueError('World mode requires declared locations and event contract')
 return copy.deepcopy(config)

def freeze_mode(world,mode=None):
 """Explicit experiment scripts default sandbox. Legacy experiments remain compatible."""
 result=copy.deepcopy(world);config=validate_modes(result)
 if config is None:
  if mode=='world':raise ValueError('This script has no world mode contract')
  if mode not in (None,'sandbox'):raise ValueError('Unknown game mode')
  # Existing event test archives retain their original experimental behavior.
  chosen='legacy-event'if mode is None and result.get('event_system')else'sandbox'
 else:
  chosen=mode or config.get('default','sandbox')
  if chosen not in config.get('enabled',MODES):raise ValueError('Mode is not available in this script')
 result['game_mode']=chosen
 if chosen=='sandbox':
  result.pop('event_system',None);result.pop('event_system_snapshot',None)
 elif chosen=='world':
  result['event_system'].update(world_mode=True,card_language=True,card_refinement=True,background_planning=True)
 return result

def assert_mode(session):
 frozen=session.get('game_mode');snapshot=session.get('world_snapshot',{}).get('game_mode')
 if frozen is not None and snapshot!=frozen:raise ValueError('Save mode differs from frozen script snapshot')
 state=session.get('facts',{}).get('browser_world_state')
 if frozen=='sandbox'and state:raise ValueError('Sandbox save cannot contain an event runtime')
 if frozen=='world'and (not state or not session['facts']['browser_world_definition']['config'].get('world_mode')):raise ValueError('World save requires its frozen event runtime')
 return frozen or ('legacy-event'if state else'sandbox')
