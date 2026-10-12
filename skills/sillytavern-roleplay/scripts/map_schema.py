"""Finite containment and independent routes. Author input is data, never code."""
import copy
from event_schema import identifier, number

KINDS = {'region', 'campus', 'building', 'floor', 'room', 'outdoor', 'connector'}
CHILDREN = {'region': KINDS - {'region', 'floor', 'room'}, 'campus': {'building', 'outdoor', 'connector'},
            'building': {'floor', 'room', 'connector'}, 'floor': {'room', 'connector'},
            'room': set(), 'outdoor': {'outdoor', 'connector'}, 'connector': set()}
MAX_NODES, MAX_DEPTH = 256, 8

def ordinary_room_name(parent_name, index):
    """Distinct descriptions without inventing a room's function."""
    ordinals = ('一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二', '十三', '十四', '十五', '十六')
    suffix = '无挂牌房间' if index == 1 else '另一间无挂牌房间' if index == 2 else '第' + ordinals[index - 1] + '间无挂牌房间'
    return parent_name[:70] + '旁的' + suffix
NODE_FIELDS = {'name', 'description', 'aliases', 'parent_id', 'kind', 'walkable', 'entry_node', 'encounter_scope',
               'expansion', 'slots', 'links', 'open', 'secret', 'initial_known_by', 'provenance', 'preset', 'availability_policy',
               'name_visibility', 'entry_visible', 'daily_services'}

def validate_node(lid, node):
    identifier(lid)
    if not isinstance(node, dict) or set(node) - NODE_FIELDS:
        raise ValueError('map.nodes.' + lid + ': unknown fields')
    if not isinstance(node.get('name'), str) or not 1 <= len(node['name']) <= 100:
        raise ValueError('map.nodes.' + lid + ': bounded name required')
    if node.get('kind', 'room') not in KINDS or node.get('expansion', 'fixed') not in ('fixed', 'bounded'):
        raise ValueError('map.nodes.' + lid + ': unsupported kind/expansion')
    if node.get('encounter_scope', 'room') not in ('room', 'area'):
        raise ValueError('map.nodes.' + lid + ': invalid encounter scope')
    if node.get('name_visibility','on_visit') not in ('signposted','on_visit','hidden'):
        raise ValueError('Invalid name visibility')
    if 'daily_services' in node and (not isinstance(node['daily_services'],list) or set(node['daily_services'])-set(__import__('daily_life').CATALOG)):
        raise ValueError('Invalid daily services')
    for field in ('walkable', 'secret', 'open', 'entry_visible'):
        if field in node and type(node[field]) is not bool:
            raise ValueError('map.nodes.' + lid + ': boolean required')
    if not isinstance(node.get('description', ''), str) or len(node.get('description', '')) > 1200:
        raise ValueError('map.nodes.' + lid + ': bounded description required')
    for field in ('aliases', 'initial_known_by'):
        values = node.get(field, [])
        if not isinstance(values, list) or len(values) > 32 or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in values):
            raise ValueError('map.nodes.' + lid + ': invalid ' + field)
    slots = node.get('slots', [])
    if not isinstance(slots, list) or len(slots) > 16 or slots and node.get('expansion') != 'bounded':
        raise ValueError('map.nodes.' + lid + ': slots require bounded expansion')
    seen = set()
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {'id', 'kind', 'name', 'links'}:
            raise ValueError('map.nodes.' + lid + ': invalid slot schema')
        identifier(slot['id'])
        if slot['id'] in seen or slot['kind'] not in ('room', 'outdoor') or slot['kind'] not in CHILDREN[node.get('kind', 'room')]:
            raise ValueError('map.nodes.' + lid + ': invalid slot type or duplicate')
        if not isinstance(slot['name'], str) or not 1 <= len(slot['name']) <= 100:
            raise ValueError('Slot needs bounded shell name')
        seen.add(slot['id'])
    return copy.deepcopy(node)

def validate_map(raw, flat=None, actors=()):
    if not isinstance(raw, dict) or set(raw) - {'version', 'nodes', 'preset', 'description_generation'} or raw.get('version') != 1:
        raise ValueError('Invalid map version/fields')
    nodes = {**copy.deepcopy(flat or {}), **copy.deepcopy(raw.get('nodes', {}))}
    if raw.get('preset'):
        preset = compile_preset(raw['preset'])
        overlap = set(preset) & set(nodes)
        if overlap:
            raise ValueError('Preset collides with authored ids: ' + str(sorted(overlap)))
        nodes.update(preset)
    if not nodes or len(nodes) > MAX_NODES:
        raise ValueError('Map node count outside finite limit')
    if raw.get('description_generation', 'none') not in ('none', 'model'):
        raise ValueError('Invalid map description generation')
    for lid, node in nodes.items():
        validate_node(lid, node)
        parent = node.get('parent_id')
        if parent and parent not in nodes:
            raise ValueError('Missing map parent: ' + lid)
        if parent and node.get('kind', 'room') not in CHILDREN[nodes[parent].get('kind', 'room')]:
            raise ValueError('Illegal containment type: ' + lid)
        chain, cursor = [], lid
        while cursor:
            if cursor in chain or len(chain) >= MAX_DEPTH:
                raise ValueError('Cyclic or too deep containment: ' + lid)
            chain.append(cursor)
            cursor = nodes[cursor].get('parent_id')
        entry = node.get('entry_node')
        if entry:
            if entry not in nodes or not nodes[entry].get('walkable', True):
                raise ValueError('Invalid container entry: ' + lid)
            ancestry, cursor = [], entry
            while cursor:
                if cursor in ancestry or len(ancestry) >= MAX_DEPTH:
                    raise ValueError('Cyclic or too deep entry containment: ' + lid)
                ancestry.append(cursor)
                if cursor not in nodes:
                    raise ValueError('Missing entry ancestor: ' + lid)
                cursor = nodes[cursor].get('parent_id')
            if lid not in ancestry:
                raise ValueError('Entry must be contained by region: ' + lid)
        if actors and set(node.get('initial_known_by', [])) - set(actors) - {'all'}:
            raise ValueError('Unknown map knowledge actor')
        for dest, minutes in node.get('links', {}).items():
            if dest not in nodes or not nodes[dest].get('walkable', True) or not node.get('walkable', True):
                raise ValueError('Route needs actual walkable nodes')
            number(minutes, 0, 1440)
        for slot in node.get('slots', []):
            for dest, minutes in slot['links'].items():
                if dest not in nodes or not nodes[dest].get('walkable', True):
                    raise ValueError('Slot route must attach to existing walkable point')
                number(minutes, 1, 1440)
    if len(nodes) + sum(len(n.get('slots', [])) for n in nodes.values()) > MAX_NODES:
        raise ValueError('Map including slots exceeds finite limit')
    return {'version': 1, 'nodes': nodes, 'description_generation': raw.get('description_generation', 'none')}

def compile_preset(spec):
    """Small shell approximation; no assertion about a source work's exact floorplan."""
    from pathlib import Path
    import json
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'assets/world-templates/location-presets.json').read_text(encoding='utf-8'))
    if not isinstance(spec, dict) or set(spec) - {'type', 'id', 'name', 'floors', 'rooms_per_floor', 'buildings'}:
        raise ValueError('Invalid preset request')
    kind = spec.get('type')
    if kind not in catalog['presets']:
        raise ValueError('Unknown shell preset')
    root = identifier(spec.get('id'))
    name = spec.get('name', '普通区域')
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        raise ValueError('Invalid preset name')
    floors, rooms, buildings = spec.get('floors', 2), spec.get('rooms_per_floor', 2), spec.get('buildings', 1)
    limits = catalog['presets'][kind]
    number(floors, 1, limits.get('max_floors', 4))
    number(rooms, 1, limits.get('max_rooms_per_floor', 8))
    number(buildings, 1, limits.get('max_buildings', 2))
    nodes = {}
    def building(bid, label, parent=None):
        nodes[bid] = {'name': label, 'kind': 'building', 'walkable': False, 'entry_node': bid + '-entry', 'parent_id': parent,
                      'provenance': 'shell_approximation_v1', 'links': {}}
        nodes[bid + '-entry'] = {'name': label + '入口', 'kind': 'connector', 'parent_id': bid, 'links': {bid + '-floor-1': 1}, 'encounter_scope': 'area'}
        for floor in range(1, floors + 1):
            lid = bid + '-floor-' + str(floor)
            links = {bid + '-entry': 1} if floor == 1 else {bid + '-floor-' + str(floor - 1): 2}
            if floor < floors:
                links[bid + '-floor-' + str(floor + 1)] = 2
            nodes[lid] = {'name': label + str(floor) + '层通道', 'kind': 'floor', 'parent_id': bid, 'links': links,
                          'encounter_scope': 'area', 'expansion': 'bounded', 'slots': [
                              {'id': 'room-' + str(i), 'kind': 'room', 'name': ordinary_room_name(label + str(floor) + '层通道', i), 'links': {lid: 1}}
                              for i in range(1, rooms + 1)]}
    if kind == 'building':
        building(root, name)
    elif kind == 'campus':
        nodes[root] = {'name': name, 'kind': 'campus', 'walkable': False, 'entry_node': root + '-gate', 'links': {}, 'provenance': 'shell_approximation_v1'}
        nodes[root + '-gate'] = {'name': name + '入口', 'kind': 'connector', 'parent_id': root, 'links': {}, 'encounter_scope': 'area'}
        for i in range(1, buildings + 1):
            bid = root + '-building-' + str(i)
            building(bid, name + '建筑' + str(i), root)
            nodes[root + '-gate']['links'][bid + '-entry'] = 3
            nodes[bid + '-entry']['links'][root + '-gate'] = 3
    elif kind == 'home':
        building(root, name)
    else:
        nodes[root] = {'name': name, 'kind': 'outdoor', 'encounter_scope': 'area', 'expansion': 'fixed', 'links': {}, 'provenance': 'shell_approximation_v1'}
    return nodes
