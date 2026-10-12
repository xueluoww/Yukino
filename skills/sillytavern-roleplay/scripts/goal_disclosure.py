"""Goal disclosure is a separate scoped decision, not a shared private goal card."""
import copy
import json
import re
from relationship_graph import relation
from goal_sets import store_card
from world_state import read

ASK = re.compile(r'你.{0,12}(?:想|打算|准备|计划|目的|目标|找什么|去哪)|(?:为什么|为何).{0,12}(?:找|去|想)|有什么(?:打算|计划)|忙什么')
DECIDE = '''只决定view本人是否向listener透露目标，JSON {level:"none|summary|full",goal_ids:[]}。
结合本人性格、对listener的有向关系、提问原因、目标敏感性。关系高也可以拒绝。level不超过ceiling；none时goal_ids=[]。
summary仅允许泛称正在处理自己的事，full才允许goal_ids里的目标名称；不透露行动方案、物品秘密、他人目标或知识。'''


def permitted(tx, actor, listener, heard, gateway):
    goals = [c for c in tx.state['cards'].values() if c['template'] == 'goal' and c['value'].get('owner') == actor and c['value']['status'] == 'active']
    queried = any(ASK.search(t.get('text', '')) for t in heard)
    rel = relation(tx.state, actor, listener)
    ceiling = 'none'
    if queried and rel['familiarity'] >= 5 and rel['trust'] >= 20:
        ceiling = 'summary'
    if queried and rel['familiarity'] >= 10 and rel['trust'] >= 30 and rel['affection'] >= 35:
        ceiling = 'full'
    safe = [c for c in goals if not re.search(r'秘密|暗号|确认码|机密|隐瞒', c['value']['title'])]
    result = {'level': 'none', 'goal_ids': []}
    if ceiling != 'none' and safe and gateway:
        from world_turn import validated_request
        payload = {'character': {k: tx.definition['characters'][actor].get(k, '') for k in ('name', 'personality')},
                   'listener': listener, 'relation': rel, 'heard': heard, 'ceiling': ceiling,
                   'goals': [{'id': c['id'], 'title': c['value']['title']} for c in safe]}
        def valid(a):
            rank = {'none': 0, 'summary': 1, 'full': 2}
            if set(a) != {'level', 'goal_ids'} or a.get('level') not in rank or rank[a['level']] > rank[ceiling]:
                raise ValueError('Disclosure outside permitted scope')
            if not isinstance(a['goal_ids'], list) or not set(a['goal_ids']) <= {c['id'] for c in safe}:
                raise ValueError('Unknown private goal')
            if a['level'] == 'none' and a['goal_ids']:
                raise ValueError('Refusal cannot expose goal')
        try:
            result = validated_request(gateway, 'goal-disclosure:' + actor, DECIDE, payload, valid, 350)
        except (ValueError, TypeError, KeyError) as error:
            from diagnostic_system import record
            record(tx, actor, 'goal-disclosure', error, disposition='withheld')
    cid = 'disclosure:' + actor + ':' + listener
    store_card(tx, cid, 'disclosure', {**result, 'owner': actor, 'listener': listener, 'ceiling': ceiling}, actor, '人物决定透露范围')
    return {**result, 'ceiling': ceiling}


def filter_reply(tx, actor, view, ledger, policy):
    allowed = set(policy['goal_ids']) if policy['level'] == 'full' else set()
    view = copy.deepcopy(view)
    ledger = copy.deepcopy(ledger)
    private = {'goal', 'goal_set', 'action_plan', 'plan', 'intent', 'motivation', 'daily_schedule', 'feature_budget'}
    view['cards'] = [c for c in view['cards'] if c['template'] not in private or c['template'] == 'goal' and c['id'] in allowed]
    ledger['facts'] = {cid: fact for cid, fact in ledger['facts'].items() if fact['kind'] not in private or cid in allowed}
    if policy['level']!='full':
        # Own memories of an undisclosed intention must not reintroduce the removed goal.
        intent=lambda c:c.get('template',c.get('kind'))=='knowledge'and bool(re.search(r'我(?:想|打算|准备|的目标)|我的计划',c['value'].get('content','')))
        view['cards']=[c for c in view['cards']if not intent(c)]
        ledger['facts']={cid:f for cid,f in ledger['facts'].items()if not intent(f)}
        # Personal recall must not reinsert an intention removed from the current disclosure view.
        private_statement=lambda n:n.get('speaker')==actor and bool(re.search(r'我(?:想|打算|准备|的目标)|我的计划',n.get('text','')))
        for field in ('recent','retrieved','recall_focus'):
            if 'personal_memory' in view:view['personal_memory'][field]=[n for n in view['personal_memory'].get(field,[]) if not private_statement(n)]
        ledger['facts']={cid:f for cid,f in ledger['facts'].items() if f['kind']!='heard_memory' or not private_statement(f['value'])}
    view['disclosure_policy'] = policy
    return view, ledger


def check_text(tx, actor, text, policy):
    allowed = set(policy['goal_ids']) if policy['level'] == 'full' else set()
    for cid, card in tx.state['cards'].items():
        if card['template'] != 'goal' or card['value'].get('owner') != actor or cid in allowed:
            continue
        title = card['value']['title']
        if title and title in text:
            raise ValueError('Private goal title outside disclosure scope')
        for token in re.findall(r'\b[A-Z]{2,}[-_][A-Z0-9]{3,}\b|\b\d{4,}\b', title):
            if token in text:
                raise ValueError('Private goal probe outside disclosure scope')
        target=tx.definition['items'].get(card['value'].get('objective',{}).get('target'),{}).get('name')
        if target and any(target in clause and re.search(r'我(?:的目标|在找|要找|打算找|准备找|想找|正在寻找|想(?:看|读|阅读)|打算(?:看|读|阅读)|计划(?:找|去|看|读))',clause)for clause in re.split('[。！？\n]',text)):
            raise ValueError('Private goal detail outside disclosure scope')


def record_shared(tx, actor, listener, policy, text):
    # Store only what was actually spoken, with provenance; do not copy objective/goal card.
    if policy['level'] == 'full' and text and any(read(tx.state, cid, {}).get('title', '\0') in text for cid in policy['goal_ids']):
        tx.apply({'template': 'builtin.learn', 'actor': listener, 'topic': 'shared-goal-' + actor,
                  'content': text, 'source': {'kind': 'disclosed_statement', 'actor': actor}, 'belief': 'reported'}, True)

