"""Shell method vocabulary and branch-local abstract method cache, no entity bindings."""
import copy
from event_schema import digest
from goal_sets import store_card

OPS = {'ask_local', 'borrow_local', 'move_route', 'observe_local', 'take_local', 'read_owned', 'rest', 'search_local'}
DEFAULTS = {
    'obtain': ['ask_local', 'move_route', 'observe_local', 'take_local'],
    'read': ['borrow_local', 'read_owned'],
    'visit': ['move_route'],
    'inquire': ['ask_local'],
    'rest': ['rest'],
}
COMPATIBLE = {
    'obtain': OPS - {'rest', 'read_owned', 'borrow_local'},
    'read': OPS - {'rest'}, 'visit': {'move_route'}, 'inquire': {'ask_local'}, 'rest': {'rest'},
}


def validate(answer, kind):
    if not isinstance(answer, dict) or set(answer) - {'steps', 'reason', 'mental_cost', 'importance', 'commitment'}:
        raise ValueError('Method cannot carry code, bindings or state effects')
    steps = answer.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8 or any(type(s) is not str or s not in COMPATIBLE[kind] for s in steps):
        raise ValueError('Allowed operators for '+kind+': '+','.join(sorted(COMPATIBLE[kind]))+'; no rest suffix unless objective is rest')
    if any(a == b for a, b in zip(steps, steps[1:])):
        raise ValueError('Adjacent repeated step cannot advance a method')
    for field, default in (('mental_cost', 1), ('importance', 30)):
        value = answer.get(field, default)
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError('Invalid assessed cost/importance')
    if answer.get('commitment', 'ordinary') not in ('ordinary', 'important'):
        raise ValueError('Invalid commitment')
    if not isinstance(answer.get('reason', ''), str) or len(answer.get('reason', '')) > 300:
        raise ValueError('Invalid method rationale')
    required = {'obtain': 'take_local', 'read': 'read_owned', 'visit': 'move_route', 'inquire': 'ask_local', 'rest': 'rest'}[kind]
    if required not in steps or steps[-1] != required:
        raise ValueError('Method lacks terminal objective step')
    if 'read_owned' in steps and 'take_local' in steps and steps.index('take_local') > steps.index('read_owned'):
        raise ValueError('Read cannot precede acquisition')
    return copy.deepcopy(answer)


def cache(tx, kind, proposal, source):
    proposal = validate(proposal, kind)
    cid = 'method:' + digest([1, kind, proposal['steps']])[:24]
    if cid not in tx.state['cards']:
        # Shared within this branch only; no text, actor, location or secret in the template.
        old = copy.deepcopy(tx.state)
        from world_state import put
        put(tx.state, cid, 'method', {'version': 1, 'kind': kind, 'steps': proposal['steps'], 'source': source}, [], ['system'])
        tx.record({'template': 'builtin.method_cached', 'effects': [], 'title': '行动方法登记', 'outcome': 'recorded',
                   'participants': [], 'observers': [], 'public': {}, 'rule_id': 'method-library'}, old)
    return cid

