"""Directed growth accounting from settled encounters; privacy/consent stay separate."""
import copy
from event_schema import number

DEFAULT = {'daily_gain_cap': 6, 'per_source_cap': 2, 'repeat_item_cap': 0,
           'stage_gate': {'affection': 60, 'shared_experiences': 3}}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) - set(DEFAULT):
        raise ValueError('Invalid relationship growth policy')
    for key in ('daily_gain_cap', 'per_source_cap', 'repeat_item_cap'):
        number(policy.get(key, DEFAULT[key]), 0, 100)
    gate = policy.get('stage_gate', DEFAULT['stage_gate'])
    if not isinstance(gate, dict) or set(gate) != {'affection', 'shared_experiences'}:
        raise ValueError('Invalid relationship stage gate')
    number(gate['affection'], 0, 100); number(gate['shared_experiences'], 0, 100)


def settle(state, definition, actor, peer, value, deltas, source=None):
    """No reciprocal changes, no net-delta tricks, and no fabricated event source."""
    from world_state import clock_time
    cfg = definition['config'].get('relation_policy', DEFAULT if definition['config'].get('world_mode') else None)
    result = copy.deepcopy(value)
    if cfg is None:
        for field, delta in deltas.items():
            result[field] = max(0, min(100, result[field] + delta))
        return result
    policy = {**DEFAULT, **cfg}
    day = state['clock']['day']
    growth = copy.deepcopy(result.get('growth', {}))
    if growth.get('day') != day:
        growth = {'day': day, 'gains': {}, 'sources': {}}
    category = (source or {}).get('kind', 'unverified')
    # Unverified proposal can reduce scores, but cannot add positive feelings.
    grounded = category in ('actual_hearing', 'actual_expression', 'actual_gift', 'shared_experience', 'script_event')
    for field, delta in deltas.items():
        if delta > 0:
            amount = min(delta, max(0, policy['daily_gain_cap'] - growth['gains'].get(field, 0)),
                         max(0, policy['per_source_cap'] - growth['sources'].get(category + ':' + field, 0))) if grounded else 0
            if category == 'actual_gift' and (source or {}).get('repeat'):
                amount = min(amount, policy['repeat_item_cap'])
            gate = policy['stage_gate']
            if field == 'affection' and result.get('shared_experiences', 0) < gate['shared_experiences']:
                amount = min(amount, max(0, gate['affection'] - result[field]))
            amount = min(amount, 100 - result[field])
            growth['gains'][field] = growth['gains'].get(field, 0) + amount
            growth['sources'][category + ':' + field] = growth['sources'].get(category + ':' + field, 0) + amount
            delta = amount
        result[field] = max(0, min(100, result[field] + delta))
    result['growth'] = growth
    result['last_growth_source'] = {**copy.deepcopy(source or {}), 'at': clock_time(state)}
    if result.get('identity') in ('', '未建立关系', '初次相识', '初次见面', '尚不熟悉', '逐渐熟悉', '熟人'):
        if result.get('familiarity', 0) >= 20:result['identity'] = '熟人'
        elif result.get('familiarity', 0) >= 5:result['identity'] = '逐渐熟悉'
    return result


def experience(state, actor, peer, event_id, kind):
    """Count meaningful actual shared actions once, at most one of each kind/day."""
    from world_state import read, put
    for owner, other in ((actor, peer), (peer, actor)):
        cid = 'rel:' + owner + ':' + other
        value = copy.deepcopy(read(state, cid))
        if value is None:
            continue
        key = str(state['clock']['day']) + ':' + kind
        keys = value.get('experience_keys', [])
        if key in keys:
            continue
        value['experience_keys'] = (keys + [key])[-64:]
        value['shared_experiences'] = value.get('shared_experiences', 0) + 1
        value['last_experience'] = {'event_id': event_id, 'kind': kind}
        put(state, cid, 'relation', value, [owner, other], [owner])


def from_record(state, definition, record):
    """Automatic deltas come only from completed physical exchanges or tasks."""
    import re
    from world_state import read, put
    if not definition['config'].get('world_mode') or record.get('outcome') != 'applied':return
    effect=next(iter(record.get('effects', [])), {})
    actor, peer=effect.get('actor'), effect.get('target')
    kind=record['template']; source=None; deltas={}
    if kind=='builtin.say' and actor in definition['characters']:
        # The recorded reply itself can express acceptance/appreciation. A wish
        # stated by the player, a monologue or overhearing cannot award feelings.
        dialogue=read(state,'dialogue:'+actor,{}).get('turns',[])
        prior=next((d for d in reversed(dialogue)if d['speaker']!=actor and actor in d.get('addressees',[])),None)
        text=record.get('public',{}).get('text','')
        if not prior or prior['speaker'] not in record.get('observers',[]) or record['story_time']-prior['at']>2:return
        if not re.search(r'谢谢|感谢|愿意|很高兴|挺好|可以一起|答应你',text) or re.search(r'不愿意|不需要|不想|拒绝|不会答应|没必要|不要再|不(?:是|会|太)?(?:很高兴|挺好)|不(?:能|可以)一起|不用(?:谢|感谢)',text):return
        peer=prior['speaker'];value=copy.deepcopy(read(state,'rel:'+actor+':'+peer))
        if value is None:return
        source={'kind':'actual_expression','event_id':record['event_id']}
        result=settle(state,definition,actor,peer,value,{'affection':1,'trust':1,'familiarity':1},source)
        result['last_reason']='实际对话中表达感谢或愿意相处'
        put(state,'rel:'+actor+':'+peer,'relation',result,[actor,peer],[actor])
        return
    if kind=='builtin.transfer' and actor and peer:
        value=copy.deepcopy(read(state,'rel:'+peer+':'+actor))
        if value is None:return
        gifted=bool(re.search(r'送|礼物',record.get('evidence','')))
        if gifted:
            iid=record['public']['item']; gifts=value.get('gift_types',[])
            source={'kind':'actual_gift','repeat':iid in gifts,'item':iid,'event_id':record['event_id']}
            value['gift_types']=(gifts+([iid] if iid not in gifts else []))[-64:]
            deltas={'affection':1,'trust':1,'familiarity':1}
        else:
            source={'kind':'shared_experience','event_id':record['event_id']};deltas={'trust':1,'familiarity':1}
    elif kind=='builtin.complete' and actor:
        offer=read(state,'offer:'+effect.get('id',''),{})
        peer=offer.get('owner')
        if not peer or peer==actor:return
        value=copy.deepcopy(read(state,'rel:'+peer+':'+actor))
        if value is None:return
        source={'kind':'shared_experience','event_id':record['event_id']};deltas={'affection':1,'trust':2,'familiarity':1}
    else:return
    # Recipient -> giver, never assume the giver has identical feelings.
    result=settle(state,definition,peer,actor,value,deltas,source)
    result['last_reason']='实际收到礼物' if source['kind']=='actual_gift' else '实际完成交接或委托'
    put(state,'rel:'+peer+':'+actor,'relation',result,[peer,actor],[peer])

