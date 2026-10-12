"""Directed, owner-private relations; no mutual feelings inferred from one score."""
import copy
from world_state import read, put, clock_time
from event_schema import digest


def relation(state, actor, peer):
    return copy.deepcopy(read(state, 'rel:' + actor + ':' + peer,
        {'affection': 30, 'trust': 20, 'familiarity': 0, 'identity': '未建立关系'}))


def initialize(state, definition):
    actors = ['player', *definition['characters']]
    for actor in actors:
        for peer in actors:
            if actor == peer:
                continue
            cid = 'rel:' + actor + ':' + peer
            value = relation(state, actor, peer)
            put(state, cid, 'relation', value, [actor, peer], [actor])


def contact(state, speaker, audience, definition=None):
    day = state['clock']['day']
    for peer in audience:
        for actor, other in ((speaker, peer), (peer, speaker)):
            cid = 'rel:' + actor + ':' + other
            value = relation(state, actor, other)
            # Familiarity grows from actual encounters, at most once per day, no name unlock.
            if value.get('contact_day') != day:
                if definition:
                    from relation_policy import settle
                    value=settle(state,definition,actor,other,value,{'familiarity':1},{'kind':'actual_hearing','speaker':speaker})
                else:value['familiarity'] = min(100, value['familiarity'] + 1)
                value['contact_day'] = day
                value['contact_source'] = {'kind': 'actual_hearing', 'speaker': speaker, 'at': clock_time(state)}
                put(state, cid, 'relation', value, [actor, other], [actor])


def update(tx, actor, peer, affection=0, trust=0, familiarity=0, reason='实际交往', source=None):
    if actor == peer or actor not in {'player', *tx.definition['characters']} or peer not in {'player', *tx.definition['characters']}:
        raise ValueError('Unknown directed relation participant')
    old = copy.deepcopy(tx.state)
    value = relation(tx.state, actor, peer)
    for key, delta in (('affection', affection), ('trust', trust), ('familiarity', familiarity)):
        if type(delta) is not int or not -10 <= delta <= 10:
            raise ValueError('Relation change must be bounded')
    from relation_policy import settle
    value=settle(tx.state,tx.definition,actor,peer,value,{'affection':affection,'trust':trust,'familiarity':familiarity},source)
    value['last_reason'] = reason
    put(tx.state, 'rel:' + actor + ':' + peer, 'relation', value, [actor, peer], [actor])
    return tx.record({'template': 'builtin.relation', 'effects': [], 'title': '关系变化', 'outcome': 'applied',
                      'participants': [actor, peer], 'observers': [], 'public': {}, 'rule_id': 'relationship'}, old)

