"""Bounded discovery. A first-mentioned name never creates geometry or a route."""
import copy, re
from world_state import location, read, clock_time
from map_runtime import get_locations, actor_locations, ancestors, register_node, learn, discover_local, route

DESCRIPTION = '''为壳已选的普通空间补描述，仅JSON {name,description,aliases:[]}。
name必须使用slot.name，aliases最多3个普通称呼。描述≤300字，只写空间光线、墙面等。
不新增楼层/连接/物品/人物/库存/秘密/任务/权限/特殊能力。壳已冻结容量及类型，不得改。
这里是游戏近似，不声称是原著准确建筑。'''

def resolve_intent(state, definition, actor, query):
    from map_references import resolve_reference
    reference = resolve_reference(state, definition, actor, query)
    if reference is not None:
        return reference
    places = actor_locations(state, definition, actor)
    matches = [lid for lid, p in places.items() if query in [lid, p.get('name'), *p.get('aliases', [])]]
    if len(matches) > 1:
        return {'classification': 'ambiguous', 'candidates': matches, 'question': '这个称呼对应不止一处已知地点，请说明完整地名。'}
    if matches:
        lid = matches[0]
        if not places[lid].get('walkable', True):
            entry = places[lid].get('entry_node')
            if entry in places:
                return {'classification': 'known_container', 'destination': entry}
            return {'classification': 'unresolved', 'question': '这个区域的入口尚未确定。'}
        return {'classification': 'known_exact', 'destination': lid}
    # Do not reveal global unknown names through classification.
    return {'classification': 'unresolved', 'question': '你还不能确定这个地点在哪里，移动未执行。可以先向身边的人问路，或探索眼前的区域。'}

def eligible_slots(tx, actor, scope):
    places = get_locations(tx.definition, tx.state)
    here = location(tx.state, actor)
    if scope not in ancestors(tx.definition, tx.state, here):
        raise ValueError('只能探索目前所在的区域，不能远程探索。')
    result = []
    for parent in ancestors(tx.definition, tx.state, here):
        if scope not in ancestors(tx.definition, tx.state, parent):
            continue
        for slot in places[parent].get('slots', []):
            occupied = any(c['template'] == 'map_slot' and c['value']['parent'] == parent and c['value']['slot'] == slot['id'] for c in tx.state['cards'].values())
            if not occupied and here in slot['links']:
                result.append((parent, slot))
    return sorted(result, key=lambda pair: (pair[0], pair[1]['id']))

def validate_proposal(answer, slot):
    if not isinstance(answer, dict) or set(answer) != {'name', 'description', 'aliases'}:
        raise ValueError('Place description fields only')
    if answer['name'] != slot['name'] or not isinstance(answer['description'], str) or len(answer['description']) > 300:
        raise ValueError('Cannot change frozen ordinary slot name or oversized description')
    aliases = answer['aliases']
    if not isinstance(aliases, list) or len(aliases) > 3 or any(not isinstance(a, str) or not 1 <= len(a) <= 30 for a in aliases):
        raise ValueError('Invalid place aliases')
    if re.search(r'传送|秘密基地|金库|武器|密码|钥匙|奖励|库存|宝藏|地下城|魔法', str(answer)):
        raise ValueError('Description cannot create special interactive facts')
    return copy.deepcopy(answer)

def propose_description(tx, actor, slot, gateway):
    from world_turn import validated_request
    from feature_budget import LimitedGateway
    limited = LimitedGateway(tx, gateway, 'place-description', actor, daily=2, local=1)
    answer = validated_request(limited, 'place-description', DESCRIPTION,
                               {'slot': {k: slot[k] for k in ('name', 'kind')}, 'local_light': '未指定'},
                               lambda a: validate_proposal(a, slot), 400)
    return validate_proposal(answer, slot)

def explore(tx, actor, scope, gateway=None):
    if 'exploration_v1' not in tx.definition['config'].get('features', []) or not tx.definition['config'].get('world_mode'):
        raise ValueError('地点探索尚未启用。')
    if read(tx.state, 'loc:' + actor, {}).get('transit_to') or read(tx.state, 'loc:' + actor, {}).get('at_entrance'):
        raise ValueError('请先完成移动或进入房间再探索。')
    candidates = eligible_slots(tx, actor, scope)
    here = location(tx.state, actor)
    spec = None
    if candidates:
        parent, slot = candidates[0]
        slot = copy.deepcopy(slot)
        legacy_name = slot['name']
        if slot['kind'] == 'room' and re.fullmatch(r'普通房间\s*\d+|room-\d+', legacy_name):
            from map_schema import ordinary_room_name
            place = get_locations(tx.definition, tx.state)[parent]
            index = next(i for i, s in enumerate(place['slots'], 1) if s['id'] == slot['id'])
            slot['name'] = ordinary_room_name(place['name'], index)
        spec = {'name': slot['name'], 'description': '门口没有显示用途，里面的情况还需要进入后观察。', 'aliases': []}
        if gateway and tx.definition['config'].get('map', {}).get('description_generation') == 'model':
            try:
                spec = propose_description(tx, actor, slot, gateway)
            except (ValueError, TypeError, KeyError) as error:
                from diagnostic_system import record
                record(tx, actor, 'place-description', error, {}, 'ordinary-shell-description')
        if legacy_name != slot['name']:
            spec['aliases'] = list(dict.fromkeys([legacy_name, *spec['aliases']]))[:3]
    # Exploration doesn't teleport. New slot is a door/sign discovery from the corridor.
    from world_activity import advance
    from world_heartbeat import advance_until
    if actor == 'player':
        advance(tx, 2, gateway, getattr(tx, 'world_frames', []))
    else:
        from world_activity import action_activity
        action_activity(tx, actor, {'type': 'wait', 'params': {'minutes': 2}})
    if location(tx.state, actor) != here:
        raise ValueError('探索期间实际位置改变，尚未登记新地点。')
    lid = register_node(tx, parent, slot['id'], spec) if spec else None
    old = copy.deepcopy(tx.state)
    discover_local(tx.state, tx.definition, actor, {'kind': 'explore', 'request': tx.request_id})
    if lid:
        learn(tx.state, tx.definition, actor, lid, {'kind': 'explore', 'request': tx.request_id}, from_node=here)
        from world_state import put
        value = copy.deepcopy(read(tx.state, 'map-known:' + actor + ':' + lid))
        value['discovery'] = {'at': clock_time(tx.state), 'from_node': here, 'request': tx.request_id}
        put(tx.state, 'map-known:' + actor + ':' + lid, 'map_knowledge', value, [actor], [actor])
    return tx.record({'template': 'builtin.explore', 'effects': [], 'title': '探索眼前区域', 'outcome': 'applied',
                      'participants': [actor], 'observers': [actor],
                      'public': {'actor': actor, 'scope': scope, 'discovered': lid, 'name': spec['name'] if spec else None}, 'rule_id': 'exploration'}, old)
