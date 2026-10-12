"""Small everyday trades with actual provenance, never narrative-only possessions."""
import copy
from event_schema import digest, number

CATALOG = {
    'daily-water': {'name': '瓶装水', 'capabilities': {'consume': {'portions': 20}}, 'price': 2},
    'daily-coffee': {'name': '罐装咖啡', 'capabilities': {'consume': {'portions': 10}}, 'price': 3},
    'daily-snack': {'name': '普通点心', 'capabilities': {'consume': {}}, 'price': 3},
    'daily-book': {'name': '普通书籍', 'capabilities': {'read': {'content': '这本普通书籍的具体正文尚未定义，不能推断书名、作者或内容。'}}, 'price': 10},
    'daily-ticket': {'name': '普通车票', 'capabilities': {}, 'price': 5},
}


def compile_items(world):
    """Only new frozen worlds opt in. Generic item definitions belong to the shell."""
    cfg = world['event_system']
    if not cfg.get('daily_life', {}).get('enabled'):
        return
    sets = world.setdefault('setting_sets', [])
    existing = {c['id'] for s in sets for c in s.get('cards', [])}
    cards = [{'id': iid, 'kind': 'item', 'description': '壳提供的普通日常物品；具体正文与稀有身份不由模型补造。',
              **{k: copy.deepcopy(v) for k, v in spec.items() if k != 'price'}}
             for iid, spec in CATALOG.items() if iid not in existing]
    if cards:
        sets.append({'id': 'shell-daily-items', 'name': '日常物品标准库', 'cards': cards})


def offers(state, definition, actor):
    from world_state import location
    from map_runtime import get_locations
    cfg = definition['config'].get('daily_life', {})
    if not cfg.get('enabled'):
        return []
    here = location(state, actor)
    allowed = cfg.get('services', {}).get(here, [])
    place = get_locations(definition, state).get(here, {})
    allowed = list(dict.fromkeys([*allowed, *place.get('daily_services', [])]))
    return [{'item': iid, 'name': definition['items'][iid]['name'], 'price': CATALOG[iid]['price']}
            for iid in allowed if iid in CATALOG and iid in definition['items']]


def validate_config(config, definition):
    cfg = config.get('daily_life')
    if cfg is None:
        return
    if not isinstance(cfg, dict) or set(cfg) - {'enabled', 'services', 'spending_limit', 'accounting'}:
        raise ValueError('Invalid daily life policy')
    if type(cfg.get('enabled', False)) is not bool or cfg.get('accounting', 'abstract') != 'abstract':
        raise ValueError('Unsupported daily accounting policy')
    if cfg.get('spending_limit') is not None:
        number(cfg['spending_limit'], 0, 1000000)
    from map_runtime import get_locations
    places=get_locations(definition)
    for lid, goods in cfg.get('services', {}).items():
        if lid not in places or not isinstance(goods, list) or set(goods) - set(CATALOG):
            raise ValueError('Daily service needs an actual declared place and shell goods')


def purchase(state, effect, definition):
    from world_state import location, read, put, clock_time
    actor, iid = effect['actor'], effect['item']
    here = location(state, actor)
    if read(state, 'loc:' + actor, {}).get('transit_to') or read(state, 'loc:' + actor, {}).get('at_entrance'):
        raise ValueError('尚未进入实际购买地点。')
    if not read(state, 'place:' + here, {}).get('open', True):
        raise ValueError('购买地点已经关闭。')
    offered = next((x for x in offers(state, definition, actor) if x['item'] == iid), None)
    if offered is None:
        raise ValueError('这里没有已确认的这项日常购买服务。')
    qty = effect.get('quantity', 1)
    cost = offered['price'] * qty
    cid = 'daily-expenses:' + actor
    ledger = copy.deepcopy(read(state, cid, {'owner': actor, 'total': 0, 'purchases': 0}))
    limit = definition['config']['daily_life'].get('spending_limit')
    if limit is not None and ledger['total'] + cost > limit:
        raise ValueError('这次购买超过了本档已设定的日常支出额度。')
    # An explicitly simulated currency must use the exact existing commerce path.
    if any(c['template'] == 'item' and c['value'].get('owner') == actor and c['value'].get('quantity', 0)
           and 'pay' in definition['items'][c['value']['item']].get('capabilities', {}) for c in state['cards'].values()):
        raise ValueError('本档已经模拟现金，请使用实际交易报价和货币结算，不能绕过资金。')
    sequence = ledger['purchases'] + 1
    instance = 'daily-' + digest([actor, iid, sequence, clock_time(state)])[:24]
    if 'item:' + instance in state['cards']:
        raise ValueError('Duplicate daily purchase')
    source = {'kind': 'purchase', 'actor': actor, 'location': here, 'at': clock_time(state), 'price': cost,
              'accounting': 'abstract_everyday_expense'}
    put(state, 'item:' + instance, 'item', {'item': iid, 'owner': actor, 'location': here, 'quantity': qty,
                                         'acquired_from': source}, [actor], [actor])
    ledger.update(total=ledger['total'] + cost, purchases=sequence, last=source)
    put(state, cid, 'daily_expenses', ledger, [actor], [actor])
    return {'actor': actor, 'item': iid, 'instance': instance, 'received_instance': instance,
            'quantity': qty, 'location': here, 'expense': cost, 'name': offered['name']}, {actor}

