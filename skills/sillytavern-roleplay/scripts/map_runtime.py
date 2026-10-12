"""One authority: frozen geometry + branch overlay; actor knowledge is a projection."""
import copy, heapq
from event_schema import digest

# world_state is a consumer; defer imports to avoid a second state implementation.
def read(*args):
    from world_state import read as fn
    return fn(*args)

def location(*args):
    from world_state import location as fn
    return fn(*args)

def clock_time(*args):
    from world_state import clock_time as fn
    return fn(*args)

def put(*args):
    from world_state import put as fn
    return fn(*args)

def enabled(definition):
    return definition.get('config', {}).get('world_mode') is True and bool(
        {'map_v1', 'exploration_v1'} & set(definition['config'].get('features', [])))

def get_locations(definition, state=None):
    """The only runtime reader of raw config locations. No mutation, no model calls."""
    config = definition.get('config', {})
    places = copy.deepcopy(config.get('map', {}).get('nodes', config.get('locations', {}))) if enabled(definition) else copy.deepcopy(config.get('locations', {}))
    if enabled(definition) and state:
        for c in state['cards'].values():
            if c['template'] == 'map_node':
                places[c['value']['id']] = copy.deepcopy(c['value']['node'])
        for c in state['cards'].values():
            if c['template'] == 'map_edge':
                e = c['value']
                places[e['source']].setdefault('links', {})[e['destination']] = e['minutes']
    return places

def get_node(definition, state, lid):
    return get_locations(definition, state).get(lid)

def ancestors(definition, state, lid):
    places = get_locations(definition, state)
    chain = []
    while lid and lid in places:
        if lid in chain or len(chain) >= 8:
            raise ValueError('Invalid map containment')
        chain.append(lid)
        lid = places[lid].get('parent_id')
    return chain

def in_region(definition, state, lid, region):
    return region in ancestors(definition, state, lid)

def actor_locations(state, definition, actor):
    places = get_locations(definition, state)
    if not enabled(definition):
        profile=definition['config'].get('player_location_bindings',{}) if actor=='player' else definition['characters'].get(actor,{})
        private={profile.get(f)for f in ('home_id','room_id','classroom_id')}|{location(state,actor)}
        return {k: v for k, v in places.items() if not v.get('secret') or k in private}
    known = {c['value']['node'] for c in state['cards'].values() if c['template'] == 'map_knowledge'
             and actor in c['visibility'] and (c['value'].get('name_known') or c['value'].get('entry_known')) and c['valid_from'] <= clock_time(state)}
    known.add(location(state, actor))
    result={k:v for k,v in places.items()if k in known}
    for lid,place in result.items():
        knowledge=read(state,'map-known:'+actor+':'+lid,{})
        if knowledge.get('entry_known') and not knowledge.get('name_known'):
            place.update(name=knowledge['entry_label'],aliases=[],description='',daily_services=[])
    return result

def known_map(state, definition, actor='player'):
    places = actor_locations(state, definition, actor)
    geometry = get_locations(definition, state)
    nodes = []
    for lid, place in sorted(places.items()):
        knowledge = read(state, 'map-known:' + actor + ':' + lid, {})
        nodes.append({'id': lid, 'name': place.get('name', lid), 'parent_id': place.get('parent_id') if place.get('parent_id') in places else None,
                      'kind': place.get('kind', 'room'), 'walkable': place.get('walkable', True),
                      'visited': knowledge.get('visited', False), 'route_known': route(state, definition, location(state, actor), lid, actor, _places=geometry, _allowed=places) is not None,
                      'links': {k: v for k, v in place.get('links', {}).items() if k in places and edge_known(state, definition, actor, lid, k, known=places)},
                      'description': place.get('description', '') if knowledge.get('visited') or not enabled(definition) else ''})
    return {'enabled': enabled(definition), 'location': location(state, actor), 'nodes': nodes}

def edge_known(state, definition, actor, source, dest, known=None):
    if not enabled(definition) or actor is None:
        return True
    v = read(state, 'map-known:' + actor + ':' + dest, {})
    return source in v.get('routes_from', []) or v.get('route_known') and source in (known if known is not None else actor_locations(state, definition, actor))

def route(state, definition, origin, target, actor=None, *, _places=None, _allowed=None, _ignore_obstacles=False):
    # Projection callers reuse a read-only snapshot within one request. No global
    # cache: a movement, door change, rollback or another branch must get fresh data.
    places = _places if _places is not None else get_locations(definition, state)
    if origin not in places or target not in places:
        return None
    if not places[target].get('walkable', True):
        target = places[target].get('entry_node')
    if target not in places:
        return None
    if not enabled(definition):
        if actor is not None:
            allowed=actor_locations(state,definition,actor)
            places={k:v for k,v in places.items()if k in allowed}
            if origin not in places or target not in places:return None
        # Compatibility is behavioral: old saves retain the former minimum-edge route.
        queue, seen = [(origin, [])], {origin}
        while queue:
            here, path = queue.pop(0)
            if here == target:
                return path
            for dest in places[here].get('links', {}):
                if dest in places and dest not in seen and (actor is not None or not places[dest].get('secret')):
                    seen.add(dest)
                    queue.append((dest, path + [dest]))
        return None
    allowed = _allowed if _allowed is not None else (actor_locations(state, definition, actor) if actor is not None else places)
    heap, best = [(0, (), origin)], {}
    while heap:
        cost, path, here = heapq.heappop(heap)
        if here in best:
            continue
        best[here] = cost
        if here == target:
            return list(path)
        for dest, minutes in sorted(places[here].get('links', {}).items()):
            if dest in best or dest not in allowed or not edge_known(state, definition, actor, here, dest, known=allowed):
                continue
            if not _ignore_obstacles and state and not read(state, 'place:' + dest, {}).get('open', places[dest].get('open', True)):
                continue
            locked = not _ignore_obstacles and any({d['location'], d['destination']} == {here, dest}
                         and read(state, 'door:' + did, {'locked': d.get('locked', True)}).get('locked')
                         for did, d in definition['config'].get('doors', {}).items()) if state else False
            if not locked:
                heapq.heappush(heap, (cost + minutes, path + (dest,), dest))
    return None

def navigation_failure(state, definition, actor, target):
    """Only acquired geography is used; unknown names do not confirm hidden places."""
    known = actor_locations(state, definition, actor)
    if target not in known:
        return '你还不能确定这个地点在哪里，移动未执行。可以先向身边的人问路，或探索眼前的区域。'
    if not known[target].get('walkable', True):
        return '这个名称指的是一个区域，请先确认它的入口，再前往具体地点。'
    origin = location(state, actor)
    if route(state, definition, origin, target, actor) is not None:
        return None
    if route(state, definition, origin, target, actor, _ignore_obstacles=True) is not None:
        return '当前已知路线暂时无法通行。可以先确认入口是否开放，或寻找其他路线。'
    return '你知道这个地点的名字，但还不知道从这里怎么走。可以先向身边的人问路，或探索眼前的通路。'

def learn(state, definition, actor, lid, source, visited=False, from_node=None, route_known=False):
    if not enabled(definition):
        return
    place = get_node(definition, state, lid)
    if place is None:
        raise ValueError('Cannot learn a nonexistent location')
    cid = 'map-known:' + actor + ':' + lid
    value = copy.deepcopy(read(state, cid, {'owner': actor, 'node': lid, 'name_known': False, 'visited': False, 'route_known': False, 'routes_from': []}))
    first=not value.get('name_known')
    value.update(name_known=True, visited=value['visited'] or visited, route_known=value['route_known'] or route_known)
    if first:value.update(source=copy.deepcopy(source),learned_at=clock_time(state))
    value.setdefault('first_source',copy.deepcopy(value.get('source',source)))
    value.setdefault('first_learned_at',value.get('learned_at',clock_time(state)))
    value['last_confirmed_source']=copy.deepcopy(source)
    value['last_confirmed_at']=clock_time(state)
    if from_node and from_node not in value['routes_from']:
        value['routes_from'].append(from_node)
    put(state, cid, 'map_knowledge', value, [actor], [actor])

def discover_local(state, definition, actor, source):
    if not enabled(definition):
        return
    places = get_locations(definition, state)
    here = location(state, actor)
    if read(state,'loc:'+actor,{}).get('at_entrance'):
        return []  # Being stopped at a closed entrance is not an inside visit.
    learn(state, definition, actor, here, source, visited=True)
    for ancestor in ancestors(definition, state, here)[1:]:
        learn(state, definition, actor, ancestor, source)
    notices=[]
    for index,dest in enumerate(places[here].get('links', {}),1):
        place=places[dest]
        if place.get('secret') or place.get('entry_visible') is False:continue
        old=read(state,'map-known:'+actor+':'+dest,{})
        if old.get('name_known') or place.get('name_visibility','on_visit')=='signposted':
            observed={**copy.deepcopy(source),'kind':'visible_sign'if not old.get('name_known')else source.get('kind'),'from_node':here}
            learn(state,definition,actor,dest,observed,from_node=here)
            if not old.get('name_known'):notices.append({'id':dest,'name':place['name'],'source':observed})
        elif place.get('name_visibility','on_visit')!='hidden':
            cid='map-known:'+actor+':'+dest
            value=copy.deepcopy(old or {'owner':actor,'node':dest,'name_known':False,'visited':False,'route_known':False,'routes_from':[]})
            ordinals=('一','二','三','四','五','六','七','八','九','十','十一','十二','十三','十四','十五','十六')
            suffix='无挂牌入口' if index==1 else '另一处无挂牌入口' if index==2 else '第'+(ordinals[index-1] if index<=16 else str(index))+'处无挂牌入口'
            value.update(entry_known=True,entry_label=places[here]['name']+'旁的'+suffix,entry_source=copy.deepcopy(source))
            if here not in value['routes_from']:value['routes_from'].append(here)
            put(state,cid,'map_knowledge',value,[actor],[actor])
    return notices

def initialize_knowledge(state, definition):
    if not enabled(definition):
        return
    places = get_locations(definition, state)
    for actor in [*definition['characters'], 'player']:
        for lid, place in places.items():
            who = place.get('initial_known_by', [])
            if actor in who or 'all' in who:
                learn(state, definition, actor, lid, {'kind': 'script_map'}, route_known=True)
        profile = definition['config'].get('player_location_bindings', {}) if actor == 'player' else definition['characters'].get(actor, {})
        for field in ('home_id', 'classroom_id', 'room_id'):
            lid = profile.get(field)
            if lid in places:
                learn(state, definition, actor, lid, {'kind': 'identity_binding', 'field': field}, route_known=True)
        if location(state, actor):
            discover_local(state, definition, actor, {'kind': 'opening_location'})

def learn_spoken(state, definition, record, event_id):
    """An actual heard place name grants a name, never a route or past visit."""
    if not enabled(definition): return
    speech = record.get('speech', {})
    speaker, text = speech.get('actor'), speech.get('text', '')
    places = actor_locations(state, definition, speaker)
    for lid, place in places.items():
        name = place.get('name', '')
        if not name or name not in text: continue
        if sum(p.get('name') == name for p in places.values()) != 1: continue
        for audience in speech.get('audience', []):
            learn(state, definition, audience, lid, {'kind': 'heard_name', 'event_id': event_id, 'speaker': speaker, 'belief': 'reported'})

def register_node(tx, parent, slot_id, node_spec):
    """System-only call. All overlay/occupancy/routes become a single journal mutation."""
    from map_schema import validate_map
    if not enabled(tx.definition) or 'exploration_v1' not in tx.definition['config'].get('features', []):
        raise ValueError('Exploration is not enabled')
    places = get_locations(tx.definition, tx.state)
    p = places.get(parent, {})
    slot = next((s for s in p.get('slots', []) if s['id'] == slot_id), None)
    if not slot or p.get('expansion') != 'bounded':
        raise ValueError('Slot outside frozen map boundary')
    cid = 'map-slot:' + digest([parent, slot_id])[:24]
    existing = read(tx.state, cid)
    if existing:
        return existing['node']
    lid = 'place-' + digest([tx.definition['definition_hash'], parent, slot_id])[:24]
    if lid in places or set(node_spec) - {'name', 'description', 'aliases'}:
        raise ValueError('Description cannot change geometry or state')
    node = {**copy.deepcopy(node_spec), 'parent_id': parent, 'kind': slot['kind'], 'walkable': True,
            'encounter_scope': 'room' if slot['kind'] == 'room' else 'area', 'expansion': 'fixed',
            'links': copy.deepcopy(slot['links']), 'provenance': {'kind': 'branch_slot', 'slot': slot_id}}
    proposed = copy.deepcopy(places)
    proposed[lid] = node
    # The occupied slot no longer contributes another prospective physical node.
    occupied = {(c['value']['parent'], c['value']['slot']) for c in tx.state['cards'].values() if c['template'] == 'map_slot'} | {(parent, slot_id)}
    for pid, info in proposed.items():
        info['slots'] = [s for s in info.get('slots', []) if (pid, s['id']) not in occupied]
    validate_map({'version': 1, 'nodes': proposed})
    old = copy.deepcopy(tx.state)
    try:
        put(tx.state, 'map-node:' + lid, 'map_node', {'id': lid, 'node': node}, [], [])
        put(tx.state, cid, 'map_slot', {'parent': parent, 'slot': slot_id, 'node': lid}, [], [])
        put(tx.state, 'place:' + lid, 'availability', {'open': True}, [lid], ['public_rule'])
        for dest, minutes in slot['links'].items():
            eid = 'map-edge:' + digest([dest, lid])[:24]
            put(tx.state, eid, 'map_edge', {'source': dest, 'destination': lid, 'minutes': minutes}, [], [])
        tx.record({'template': 'builtin.place_registration', 'effects': [], 'title': '有限空间登记', 'outcome': 'recorded',
                   'participants': [], 'observers': [], 'public': {}, 'rule_id': 'map'}, old)
    except Exception:
        tx.state = old
        raise
    return lid
