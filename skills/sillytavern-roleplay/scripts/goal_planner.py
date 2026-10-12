from map_runtime import get_locations
"""Persistent, variant-preserving action methods; execution remains shell-owned."""
import copy
import json
from action_methods import DEFAULTS, validate, cache
from goal_feedback import active_goals, planning_view, scope_key, add_feedback
from goal_sets import store_card, reconcile as reconcile_goals, goal_satisfied
from world_state import read, location, colocated, clock_time
from goal_motivation import utility, ensure, spend
from event_schema import digest

BUILD = '''为view本人当前goal构造可持续执行的方案，仅JSON {steps:[操作名],reason:"",mental_cost:整数0..100,importance:整数0..100,commitment:"ordinary|important"}。
操作仅ask_local(询问线索)、borrow_local(向实际持有者借阅)、move_route(按本人已知线索/公开目标走路径)、observe_local、take_local、read_owned、search_local、rest。
steps为1..8项，按因果顺序。取得目标最后take_local；阅读最后read_owned；访问最后move_route；询问最后ask_local；休息最后rest。
不在本人的知识/局部视野内的物品位置不能猜。不替别人同意或写动作，不替玩家行动。借阅失败不能强拿。根据history换方法，不重复同条件下受阻的方案。精神代价和重要性是提案，不能覆盖路径、所有权或期限。'''
REVIEW = '''独立评估方案是否符合goal真正要求、view本人的性格/意愿和已有知识，只JSON {approved:布尔,reason:"简短原因"}。
不执行、不修改目标。检查终点是否真正满足目标，步骤依赖是否正确，是否强迫别人/玩家同意，是否使用未知秘密。
合法受阻不意味着自动成功，普通目标可安静；重要性不保证成功。'''
SPEECH = '''只为view本人生成当前action的自然询问，JSON {text:"",claims:[]}。围绕本人目标或请求借用实际物品，按性格和有向关系。
不命令对方必同意，不把请求说成已得到，不编未知位置和过去经历。只可引用view内可披露knowledge的ID，借阅需要对方自己决定。'''


def routes(tx, start, target, actor=None):
    from map_runtime import route
    return route(tx.state, tx.definition, start, target, actor)


def context(tx, actor, goal):
    from model_context import working_view
    view = working_view(tx, actor)
    # Public map is geometry, not remote NPC positions or inventories.
    from map_runtime import known_map
    view['public_routes'] = {n['id']: n['links'] for n in known_map(tx.state,tx.definition,actor)['nodes']}
    return {'view': view, 'goal': goal['value']}


def create(tx, gateway, actor, goal):
    kind = goal['value']['objective']['kind']
    prior = [c for c in tx.state['cards'].values() if c['template'] == 'action_plan' and c['value']['goal_id'] == goal['id']]
    if len(prior) >= 4:
        return None
    current_scope=scope_key(context(tx,actor,goal)['view'])
    search_id='methodsearch:'+digest([goal['id'],current_scope])[:24]
    searched=copy.deepcopy(read(tx.state,search_id,{'owner':actor,'goal_id':goal['id'],'attempts':0}))
    if searched['attempts']>=2:return None
    searched['attempts']+=1
    store_card(tx,search_id,'method_search',searched,actor,'方案搜索预算')
    payload = context(tx, actor, goal)
    from action_methods import COMPATIBLE
    payload['method_contract']={'allowed_operators':sorted(COMPATIBLE[kind]),'must_end_with':{'obtain':'take_local','read':'read_owned','visit':'move_route','inquire':'ask_local','rest':'rest'}[kind],
                                'read_owned_includes_actual_owner_issued_onsite_reading_permission':True}
    payload['history'] = [{'steps': c['value']['steps'], 'status': c['value']['status'], 'reason': c['value'].get('blocked_reason', '')} for c in prior]
    proposal = None; source = 'shell';from_library=False
    if not prior:
        for card in reversed(list(tx.state['cards'].values())):
            if card['template']!='method'or card['value']['kind']!=kind:continue
            candidate={'steps':card['value']['steps'],'mental_cost':1,'importance':goal['value'].get('priority',30),'commitment':'ordinary','reason':'已审核的壳方法模板，重新绑定本人目标'}
            local=local_items(tx,actor,goal['value']['objective'].get('target'))
            # A cached owner-reading method cannot silently bypass borrowing.
            if kind=='read'and any(c['value']['owner']!=actor and c['value']['owner']!=location(tx.state,actor)for c in local)and'borrow_local'not in candidate['steps']:continue
            proposal=candidate;from_library=True;break
    owned=local_items(tx,actor,goal['value']['objective'].get('target')) if kind=='read' else []
    low_risk=tx.definition['config'].get('shell_methods') and (kind in ('visit','rest') or kind=='read' and owned and all(c['value']['owner']==actor for c in owned))
    if low_risk:
        proposal={'steps':DEFAULTS[kind],'mental_cost':1,'importance':goal['value'].get('priority',30),'commitment':'ordinary','reason':'壳内已定义的本人低风险行动，每步重新校验真实状态'}
        source='shell-validated'
    if gateway and not low_risk:
        from world_turn import validated_request
        try:
            if proposal is None:proposal = validated_request(gateway, 'method-builder:' + actor, BUILD, payload, lambda a: validate(a, kind), 650)
            def checked(a):
                if set(a) != {'approved', 'reason'} or type(a['approved']) is not bool or not isinstance(a['reason'], str):
                    raise ValueError('Invalid method reviewer')
            verdict = validated_request(gateway, 'method-review:' + actor, REVIEW, {**payload, 'proposal': proposal}, checked, 350)
            if not verdict['approved']:
                raise ValueError('Method reviewer rejected proposal')
            source = 'library-reviewed'if from_library else'model-reviewed'
        except (ValueError, TypeError, KeyError) as error:
            from diagnostic_system import record
            record(tx, actor, 'method-generation', error, {'goal_id': goal['id']}, 'shell-method-fallback')
            proposal = None
    if proposal is None:
        proposal = {'steps': DEFAULTS[kind], 'mental_cost': 1, 'importance': goal['value'].get('priority', 30), 'commitment': 'ordinary', 'reason': '壳内目标类型对应的基本方法'}
    proposal = validate(proposal, kind)
    current_scope = scope_key(context(tx, actor, goal)['view'])
    if any(c['value']['steps'] == proposal['steps'] and c['value'].get('blocked_scope') == current_scope for c in prior):
        return None
    method = cache(tx, kind, proposal, source)
    cid = 'actionplan:' + digest([actor, goal['id'], method, len(prior)])[:24]
    value = {'owner': actor, 'goal_id': goal['id'], 'method_id': method, 'steps': proposal['steps'], 'cursor': 0,
             'status': 'active', 'source': source, 'created_at': clock_time(tx.state), 'last_progress_at': clock_time(tx.state),
             'attempts': [], 'asked': [], 'mental_cost': proposal.get('mental_cost', 1),
             'importance': proposal.get('importance', 30), 'commitment': proposal.get('commitment', 'ordinary')}
    store_card(tx, cid, 'action_plan', value, actor, '人物建立行动方案')
    return cid


def local_items(tx, actor, target):
    from actor_context import build_actor_view
    allowed = {c['id'] for c in build_actor_view(tx.state, tx.definition, actor)['cards'] if c['template'] == 'item'}
    here = location(tx.state, actor)
    return [c for c in tx.state['cards'].values() if c['template'] == 'item' and c['value']['item'] == target and c['value']['quantity'] > 0
            and (c['id'] in allowed or c['value']['location'] == here and not read(tx.state, 'loc:' + actor, {}).get('at_entrance')
                 and not tx.definition['items'][target].get('hidden'))]


def known_destination(tx, actor, goal):
    objective = goal['value']['objective']
    if objective['kind'] == 'visit':
        return objective['target']
    from model_context import working_view
    item_name=tx.definition['items'].get(objective.get('target'),{}).get('name','')
    known = ' '.join(c['value'].get('content', '') for c in working_view(tx, actor)['cards'] if c['template'] == 'knowledge' and (not item_name or item_name in c['value'].get('content','')))
    for lid, info in get_locations(tx.definition,tx.state).items():
        if not info.get('secret') and (lid in known or info.get('name', lid) in known):
            if location(tx.state, actor) != lid:
                return lid
    return None


def next_action(tx, actor, goal, plan):
    op = plan['steps'][plan['cursor']]; target = goal['value']['objective'].get('target')
    items = local_items(tx, actor, target) if target in tx.definition['items'] else []
    owned = next((c for c in items if c['value']['owner'] == actor), None)
    public = next((c for c in items if c['value']['owner'] == location(tx.state, actor)), None)
    if op == 'read_owned':
        from read_permissions import valid as may_read
        readable=owned or next((c for c in items if may_read(tx.state,tx.definition,actor,c['id'][5:])),None)
        return ({'type': 'read', 'params': {'instance': readable['id'][5:]}} if readable else None), False
    if op == 'take_local':
        if owned:
            return None, True
        return ({'type': 'take', 'params': {'instance': public['id'][5:]}} if public else None), False
    if op == 'observe_local':
        return ({'type': 'observe', 'params': {'target': (owned or public or items[0])['id'][5:]}} if items else None), False
    if op == 'move_route':
        if items and goal['value']['objective']['kind'] != 'visit':
            return None, True
        dest = known_destination(tx, actor, goal)
        if dest == location(tx.state, actor) and not read(tx.state, 'loc:' + actor, {}).get('at_entrance'):
            return None, True
        path = routes(tx, location(tx.state, actor), dest, actor=actor) if dest else None
        return ({'type': 'move', 'params': {'location': path[0]}} if path else None), False
    if op in ('ask_local', 'borrow_local'):
        from read_permissions import valid as may_read
        if op=='borrow_local'and any(may_read(tx.state,tx.definition,actor,c['id'][5:])for c in items):return None,True
        if owned or public or op == 'ask_local' and known_destination(tx, actor, goal):
            return None, True
        from actor_context import build_actor_view
        peers = [p['id'] for p in build_actor_view(tx.state, tx.definition, actor)['local_people'] if p['id'] not in plan['asked']]
        if op == 'borrow_local':
            peers = [p for p in peers if any(c['value']['owner'] == p for c in items)]
        if goal['value']['objective']['kind'] == 'inquire':
            peers = [p for p in peers if p == target]
        return ({'type': 'ask', 'params': {'audience': [peers[0]]}} if peers else None), False
    if op == 'rest':
        return {'type': 'rest', 'params': {'minutes': 5}}, False
    if op == 'search_local':
        return {'type': 'search', 'params': {'target': target}} if target in tx.definition['items'] else {'type': 'search', 'params': {}}, False
    return None, False


def important_visit(tx, actor, goal, plan):
    """Off-screen visits can avoid repeated model decisions; no teleport or forced entry."""
    value = goal['value']
    if plan['commitment'] != 'important' or value['objective']['kind'] != 'visit' or value.get('deadline') is None:
        return None
    path = routes(tx, location(tx.state, actor), value['objective']['target'], actor=actor)
    if not path:
        return None
    places = {location(tx.state, actor), *path}
    if any(location(tx.state, peer) in places for peer in ['player', *tx.definition['characters']] if peer != actor):
        return None
    elapsed = 0; here = location(tx.state, actor)
    if read(tx.state,'vital:'+actor,{}).get('alive')is False or read(tx.state,'loc:'+actor,{}).get('transit_to'):
        return None
    for dest in path:
        if not read(tx.state, 'place:' + dest, {}).get('open', False):
            return None
        for door_id,door in tx.definition['config'].get('doors',{}).items():
            if door.get('location')==here and door.get('destination')==dest and read(tx.state,'door:'+door_id,{'locked':door.get('locked',True)}).get('locked'):
                return None
        elapsed += get_locations(tx.definition,tx.state)[here]['links'][dest]; here = dest
    if clock_time(tx.state) + elapsed > value['deadline'] or plan['mental_cost'] > read(tx.state, ensure(tx, actor))['mental_energy']:
        return None
    return {'path': path, 'time_cost': elapsed, 'material_cost': 0, 'mental_cost': plan['mental_cost']}


def step(tx, gateway, actor, goal, cid, frames):
    from card_runtime import execute, actor_reply
    from world_turn import validated_request, actor_frame
    from actor_context import authorize_claims
    from card_runtime import scoped_claims
    from dialogue_state import record_speech
    from card_validation import verify_prose
    value = copy.deepcopy(read(tx.state, cid))
    if value.get('macro') is None:
        macro = important_visit(tx, actor, goal, value)
        if macro:
            spend(tx, actor, macro['mental_cost']); value['macro'] = macro; value['macro']['started'] = True
    action = None
    for _ in range(8):
        if value['cursor'] >= len(value['steps']):
            break
        action, satisfied = next_action(tx, actor, goal, value)
        if not satisfied:
            break
        value['cursor'] += 1; value['last_progress_at'] = clock_time(tx.state)
    if action and action['type'] == 'ask':
        payload = context(tx, actor, goal)
        payload['action'] = {'kind': value['steps'][value['cursor']], 'audience': action['params']['audience']}
        payload['allowed_claim_ids']=[c['id']for c in payload['view']['cards']if c['template']=='knowledge'and c['value'].get('disclose',True)]
        def valid(a):
            if set(a) != {'text', 'claims'} or not isinstance(a['text'], str) or not a['text'].strip():
                raise ValueError('Invalid goal inquiry speech')
            a['claims'] = scoped_claims(a['claims'], payload['view']); authorize_claims(payload['view'], a['claims'], a['text']); verify_prose(tx, actor, a['text'])
        try:
            answer = validated_request(gateway, 'method-speech:' + actor, SPEECH+' claims只能是allowed_claim_ids中的字符串；没有引用已知事实就[]，关系分数不是knowledge，不写relation引用。', payload, valid, 450)
            action['params'].update(answer)
        except (ValueError, TypeError, KeyError) as error:
            from diagnostic_system import record
            record(tx, actor, 'method-speech', error, {'goal_id': goal['id'], 'plan_id': cid, 'cursor': value['cursor']}, 'retry-speech-only')
            value['last_error'] = 'speech-output'; store_card(tx, cid, 'action_plan', value, actor, '行动表达待修正'); return
    if action is None:
        value.update(status='blocked', blocked_reason='当前步骤缺少真实条件', blocked_scope=scope_key(context(tx, actor, goal)['view']))
        store_card(tx, cid, 'action_plan', value, actor, '行动方案受阻'); return
    start = len(tx.records)
    try:
        results = execute(tx, action, actor, '本人目标的持续行动方案', gateway)
    except (ValueError, TypeError, KeyError) as error:
        from diagnostic_system import record
        record(tx, actor, 'method-action', error, {'goal_id': goal['id'], 'plan_id': cid, 'cursor': value['cursor']}, 'held')
        results = []
    ok = bool(results) and all(r['outcome'] == 'applied' for r in results)
    rec = next((r for r in results if r.get('speech')), None)
    if rec:
        record_speech(tx, rec['speech'], rec['speech']['audience'])
        if 'player' in rec['observers']:
            frames.append(actor_frame(actor, rec['speech']['text'], 'neutral', tx.state, tx.definition))
        for peer in rec['speech']['audience']:
            if peer == 'player':continue
            actor_reply(tx, gateway, peer, [rec['speech']], frames, actor)
        value['asked'].extend(rec['speech']['audience'])
    value['attempts'] = (value['attempts'] + [{'at': clock_time(tx.state), 'cursor': value['cursor'], 'action': action, 'applied': ok}])[-24:]
    if ok:
        value['last_progress_at'] = clock_time(tx.state)
        # Movement traverses all edges before its step is complete.
        if action['type'] != 'move':
            value['cursor'] += 1
    else:
        value.update(status='blocked', blocked_reason='动作未通过或条件改变', blocked_scope=scope_key(context(tx, actor, goal)['view']))
    reconcile_goals(tx)
    if goal_satisfied(tx.state, goal['value']):
        value['status'] = 'completed'
    elif value['cursor'] >= len(value['steps']):
        value.update(status='blocked', blocked_reason='方案已走完但目标并未达成', blocked_scope=scope_key(context(tx, actor, goal)['view']))
    store_card(tx, cid, 'action_plan', value, actor, '行动方案进度')


def background(tx, gateway, frames):
    if not gateway:
        return
    now = clock_time(tx.state); interval = tx.definition['config'].get('planning_interval', 5)
    for actor in tx.definition['characters']:
        if read(tx.state, 'activity:' + actor, {}).get('busy_until', 0) > now or read(tx.state, 'loc:' + actor, {}).get('transit_to'):
            continue
        from schedule_runtime import active_actor
        if active_actor(tx.state,actor):continue
        goals = sorted(active_goals(tx.state, actor), key=lambda g: -utility(tx, g))
        if not goals or now - tx.state.get('planning_times', {}).get(actor, clock_time(tx.initial)) < interval:
            continue
        old = copy.deepcopy(tx.state); tx.state.setdefault('planning_times', {})[actor] = now
        tx.record({'template': 'builtin.decision', 'effects': [], 'title': '人物考虑自己的目标', 'outcome': 'recorded',
                   'participants': [actor], 'observers': [], 'public': {}, 'rule_id': 'method-planner'}, old)
        goal = goals[0]
        existing = [c for c in tx.state['cards'].values() if c['template'] == 'action_plan' and c['value']['goal_id'] == goal['id'] and c['value']['status'] == 'active']
        if not existing:
            current_scope=scope_key(context(tx,actor,goal)['view'])
            resumable=[c for c in tx.state['cards'].values()if c['template']=='action_plan'and c['value']['goal_id']==goal['id']and c['value']['status']=='blocked'and c['value'].get('blocked_scope')!=current_scope and c['value']['cursor']<len(c['value']['steps'])]
            for candidate in reversed(resumable):
                action,satisfied=next_action(tx,actor,goal,candidate['value'])
                if action or satisfied:
                    v=copy.deepcopy(candidate['value']);v['status']='active';v['resumed_at']=now
                    store_card(tx,candidate['id'],'action_plan',v,actor,'条件改变后恢复行动方案')
                    existing=[tx.state['cards'][candidate['id']]];break
        cid = existing[-1]['id'] if existing else create(tx, gateway, actor, goal)
        if cid:
            step(tx, gateway, actor, goal, cid, frames)
        else:
            from diagnostic_system import record
            # Once per identical goal/context; no infinite calls on an unchanged blockage.
            marker = 'stalled:' + digest([goal['id'], scope_key(context(tx, actor, goal)['view'])])[:24]
            if not read(tx.state, marker):
                store_card(tx, marker, 'stalled_goal', {'owner': actor, 'goal_id': goal['id'], 'status': 'blocked'}, actor, '目标等待条件变化')
                record(tx, actor, 'goal-progress', ValueError('No progress under unchanged preconditions'), {'goal_id': goal['id']}, 'waiting-for-state-change')


def synchronize(tx):
    for cid,card in list(tx.state['cards'].items()):
        if card['template']!='action_plan' or card['value']['status']not in('active','blocked'):continue
        goal=read(tx.state,card['value']['goal_id'],{})
        if goal.get('status') in('completed','expired'):
            value=copy.deepcopy(card['value']);value['status']=goal['status']
            store_card(tx,cid,'action_plan',value,value['owner'],'方案随目标结算')


def macro_due(tx):
    """Continue prevalidated off-screen visits at actual arrival boundaries, no LLM or time jump."""
    for cid,card in list(tx.state['cards'].items()):
        value=copy.deepcopy(card['value'])
        if card['template']!='action_plan' or value.get('status')!='active' or not value.get('macro'):continue
        actor=value['owner'];goal=read(tx.state,value['goal_id'],{})
        if goal.get('status')!='active' or read(tx.state,'loc:'+actor,{}).get('transit_to'):continue
        target=goal['objective']['target']
        if location(tx.state,actor)==target:
            continue
        path=routes(tx,location(tx.state,actor),target,actor=actor)
        if not path:continue
        if any(colocated(tx.state,actor,peer)for peer in ['player',*tx.definition['characters']]if peer!=actor):
            value['macro']['paused_for_interaction']=True
            store_card(tx,cid,'action_plan',value,actor,'后台行程遇到人物，恢复具体互动');continue
        try:
            tx.apply({'template':'builtin.move','actor':actor,'location':path[0]},evidence='已审核后台访问行程',rule_id='macro-goal')
        except ValueError as error:
            value.update(status='blocked',blocked_reason='后台行程条件改变',blocked_scope=scope_key(context(tx,actor,{'value':goal})['view']))
            store_card(tx,cid,'action_plan',value,actor,'后台行程被打断')
            from diagnostic_system import record
            record(tx,actor,'macro-precondition',error,{'goal_id':value['goal_id'],'plan_id':cid},'blocked-no-success')

