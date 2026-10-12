"""Runtime incentives affect scheduling, never train the model or force success."""
import copy
from world_state import read, clock_time
from goal_sets import store_card


def ensure(tx, actor):
    cid = 'drive:' + actor
    if read(tx.state, cid) is None:
        store_card(tx, cid, 'motivation', {'owner': actor, 'mental_energy': 100, 'points': 0, 'settled_goals': []}, actor, '人物活动状态')
    return cid


def utility(tx, goal):
    value = goal['value']
    urgency = 0
    if value.get('deadline') is not None:
        remaining = value['deadline'] - clock_time(tx.state)
        urgency = max(0, 40 - remaining)
    plans=[c['value']for c in tx.state['cards'].values()if c['template']=='action_plan'and c['value']['goal_id']==goal['id']]
    assessed=plans[-1].get('importance',value.get('priority',30))if plans else value.get('priority',30)
    blocked=20 if plans and all(p['status']=='blocked'for p in plans)else 0
    points=read(tx.state,'drive:'+value['owner'],{}).get('points',0)
    return value.get('priority', 30) + urgency + min(20,assessed//5) - blocked + min(10,max(0,-points))


def spend(tx, actor, amount):
    cid = ensure(tx, actor)
    value = copy.deepcopy(read(tx.state, cid))
    if type(amount) is not int or not 0 <= amount <= value['mental_energy']:
        raise ValueError('Insufficient mental budget')
    value['mental_energy'] -= amount
    store_card(tx, cid, 'motivation', value, actor, '人物投入精力')


def reconcile(tx):
    for actor in tx.definition['characters']:
        cid = ensure(tx, actor)
        value = copy.deepcopy(read(tx.state, cid))
        changed = False
        for card in tx.state['cards'].values():
            g = card['value']
            if card['template'] != 'goal' or g.get('owner') != actor or card['id'] in value['settled_goals']:
                continue
            if g['status'] in ('completed', 'expired'):
                value['settled_goals'].append(card['id'])
                value['points'] = max(-100, min(100, value['points'] + (5 if g['status'] == 'completed' else -3)))
                changed = True
        if changed:
            store_card(tx, cid, 'motivation', value, actor, '人物目标结果反馈')

