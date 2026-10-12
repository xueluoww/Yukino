"""Discovery referents from this actor's branch-local acquired knowledge only."""
import re
from map_runtime import actor_locations, enabled, clock_time

DISCOVERY_REFERENCE = re.compile(r'(?:刚(?:刚|才)?(?:发现|找到|探索到)|新发现|刚才看到)的?(?:(?:那个|这个|那|这)?(?:房间|小室|地方)|(?:那间|这间)(?:房间|小室)?)')


def recent_discoveries(state, definition, actor='player'):
    if not enabled(definition):
        return []
    known = actor_locations(state, definition, actor)
    candidates = []
    for card in state['cards'].values():
        if card['template'] != 'map_knowledge' or actor not in card['visibility']:
            continue
        value = card['value']
        lid = value.get('node')
        if value.get('owner') != actor or lid not in known:
            continue
        discovery = value.get('discovery')
        # Old experimental saves remain readable without migration. An explore
        # source alone is insufficient: current/adjacent nodes are also learned.
        provenance = known[lid].get('provenance', {})
        if not discovery and value.get('source', {}).get('kind') == 'explore' and isinstance(provenance, dict) and provenance.get('kind') == 'branch_slot':
            discovery = {'at': value.get('learned_at'), 'request': value['source'].get('request')}
        if not isinstance(discovery, dict) or type(discovery.get('at')) is not int or discovery['at'] > clock_time(state):
            continue
        candidates.append({'id': lid, 'name': known[lid]['name'], 'kind': known[lid].get('kind'), 'discovered_at': discovery['at']})
    if not candidates:
        return []
    latest = max(c['discovered_at'] for c in candidates)
    return sorted((c for c in candidates if c['discovered_at'] == latest), key=lambda c: c['id'])


def resolve_reference(state, definition, actor, query):
    if not DISCOVERY_REFERENCE.fullmatch(query.strip()):
        return None
    candidates = recent_discoveries(state, definition, actor)
    if re.search(r'房间|小室|那间|这间', query):
        candidates = [c for c in candidates if c['kind'] == 'room']
    if len(candidates) == 1:
        return {'classification': 'recent_discovery', 'destination': candidates[0]['id']}
    if candidates:
        return {'classification': 'ambiguous', 'candidates': [c['id'] for c in candidates],
                'question': '刚才发现了不止一处地点，请说明是' + '、'.join(c['name'] for c in candidates) + '中的哪一处。'}
    return {'classification': 'unresolved', 'question': '还不能确定你指的是哪处发现，请说明地名，或先探索眼前的区域。'}
