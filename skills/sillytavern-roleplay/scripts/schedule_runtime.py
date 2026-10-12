"""Schedule state machine runs through existing goals, plans, movement and activity."""
import copy
from world_state import clock_time, location, read
from npc_schedule import enabled, build_day, TERMINAL, temporal_issues
from goal_sets import activate_goal, store_card

DECISION = '''只为view本人选择是否开始自己的arrangement，JSON {decision:"depart|defer",reason:"",delay:整数0..30}。
结合自己的正在进行的交流与目标，可延期普通安排；强约束不能无依据取消。不给别人/玩家做决定。
这只是本人选择，不是移动完成，不更改地点、物品、关系或时间。'''

def active_actor(state, actor):
    c = read(state, 'schedule:' + actor, {})
    return any(e.get('status') in ('ready', 'travelling', 'occupying', 'delayed') for e in c.get('entries', []))


def resume_deferred(tx, actor):
    """Keep a routine's unfinished goal/plan, resume after the timed arrangement."""
    from goal_sets import config
    capacity=config(tx.definition).get('max_active',2)
    active=[c for c in tx.state['cards'].values() if c['template']=='goal' and c['value'].get('owner')==actor and c['value'].get('status')=='active']
    schedule=read(tx.state,'schedule:'+actor,{})
    for cid,c in list(tx.state['cards'].items()):
        v=c['value']
        if c['template']!='goal' or v.get('owner')!=actor or v.get('status')!='paused_schedule':continue
        lease=v.get('schedule_pause',{})
        entry=next((e for e in schedule.get('entries',[]) if e['id']==lease.get('entry')),None)
        if schedule.get('day')==lease.get('day') and entry and entry['status'] not in TERMINAL:continue
        value=copy.deepcopy(v)
        if value.get('deadline') is not None and value['deadline']<clock_time(tx.state):
            value['status']='expired'
        else:
            if len(active)>=capacity or any(x['value'].get('objective')==value.get('objective') for x in active):continue
            value['status']='active';active.append(c)
        value.pop('schedule_pause',None)
        store_card(tx,cid,'goal',value,actor,'定时安排结束，恢复原来的未完成目标')


def reserve_slot(tx, actor, entry, day):
    """A timed arrangement may pause a lower-priority ordinary goal, never erase it."""
    from goal_sets import config
    active=[c for c in tx.state['cards'].values() if c['template']=='goal' and c['value'].get('owner')==actor and c['value'].get('status')=='active']
    if len(active)<config(tx.definition).get('max_active',2):return None
    priority=90 if entry['strength']!='routine' else 55
    candidates=[c for c in active if c['value'].get('priority',30)<priority and c['value'].get('source',{}).get('kind')=='goal_set'
                and c['value'].get('deadline') is None]
    if not candidates:return None
    chosen=min(candidates,key=lambda c:(c['value'].get('priority',30),c['id']))
    old=copy.deepcopy(chosen['value']);value=copy.deepcopy(old)
    value.update(status='paused_schedule',schedule_pause={'day':day,'entry':entry['id']})
    store_card(tx,chosen['id'],'goal',value,actor,'低优先级日常目标暂缓，为定时安排保留执行容量')
    return chosen['id'],old

def boundaries(tx, target):
    if not enabled(tx.definition):
        return []
    now = clock_time(tx.state)
    from school_calendar import lesson_end
    result = []
    for c in tx.state['cards'].values():
        if c['template'] != 'daily_schedule' or c['value']['day'] != tx.state['clock']['day']:
            continue
        base = (c['value']['day'] - 1) * 1440
        for e in c['value']['entries']:
            if e['status'] in TERMINAL:
                continue
            fixed_end = lesson_end(tx.definition, c['value']['owner'], e, e.get('schedule_day', c['value']['day']))
            result.extend(t for t in (e.get('departure_due', base + e['window_start']), fixed_end,
                                     base + e['window_end'] + e['flexibility'] + 1,
                                     e.get('finish_due'), e.get('retry_at'))
                          if type(t) is int and now < t <= target)
    return result

def arbitrate(tx, actor, entry, gateway=None):
    """API exhaustion falls back to priorities, not a fabricated physical obstruction."""
    dialogue = read(tx.state, 'dialogue:' + actor, {}).get('turns', [])
    chatting = any(t.get('at', -100) >= clock_time(tx.state) - 2 for t in dialogue[-3:])
    optional=entry.get('participation_policy')=='choice'
    if optional and not gateway:return {'decision':'defer','reason':'等待本人的参加判断，不默认接受','delay':5}
    if not optional and (not chatting or not gateway):
        return {'decision': 'depart', 'reason': '现有安排与当前条件可执行', 'delay': 0}
    from world_turn import validated_request
    from feature_budget import LimitedGateway
    from model_context import working_view
    limited = LimitedGateway(tx, gateway, 'event-choice-'+entry['event_id'] if optional else 'schedule-decision', actor, daily=2 if optional else 1)
    def validate(a):
        from event_schema import number
        if set(a) != {'decision', 'reason', 'delay'} or a['decision'] not in (('depart','defer','decline') if optional else ('depart','defer')) or not isinstance(a['reason'], str) or len(a['reason'])>500:
            raise ValueError('Invalid schedule decision')
        number(a['delay'], 0, 30)
        if a['decision'] == 'defer' and (a['delay'] == 0 or entry['strength'] == 'critical'):
            raise ValueError('Invalid schedule deferral')
    try:
        instruction=DECISION if not optional else '''只为view本人决定是否参加公开活动，JSON {decision:"depart|decline|defer",reason:"",delay:整数0..30}。depart表示本人愿意前往，decline表示不参加，defer表示稍后再考虑。结合性格、情绪、活跃目标、当天安排、身体状态、路程与实际关系（好感/熟悉/信任），不因作者列为候选就必须参加，也不因玩家邀请就必须同意。拒绝可有自然理由，不替玩家决定。reason仅供本人内部考虑，不自动对外说出。defer时delay为1..30。不能宣布到场、完成竞赛或改变任何人状态。'''
        return validated_request(limited, 'schedule-decision:' + actor, instruction,
                                 {'view': working_view(tx, actor), 'arrangement': entry,
                                  'own_arrangements':read(tx.state,'schedule:'+actor,{}).get('entries',[])}, validate, 350)
    except (ValueError, TypeError, KeyError) as error:
        from feature_budget import FeatureQuota
        if optional and isinstance(error,FeatureQuota):
            return {'decision':'defer','reason':'本轮保留尚未决定的意向，仍可回应实际邀请','delay':30}
        from diagnostic_system import record
        record(tx, actor, 'schedule-decision', error, {}, 'pending-intent' if optional else 'deterministic-priority')
        return {'decision':'defer','reason':'本人尚未决定，不自动接受活动','delay':5} if optional else {'decision': 'depart', 'reason': '保留有效安排，不因新增请求额度耗尽阻止活动', 'delay': 0}

def evaluate_due(tx, gateway=None, frames=None, execute=True):
    if not enabled(tx.definition):
        return
    if temporal_issues(tx.state):
        raise ValueError('Invalid future schedule actuals; load requires explicit recovery')
    from goal_planner import routes, create, step
    from school_calendar import lesson_end
    frames = frames if frames is not None else getattr(tx, 'world_frames', [])
    now = clock_time(tx.state)
    for actor in tx.definition['characters']:
        resume_deferred(tx, actor)
        cid = build_day(tx, actor, gateway=gateway if execute else None)
        if not cid:
            continue
        value = copy.deepcopy(read(tx.state, cid))
        base = (value['day'] - 1) * 1440
        original = copy.deepcopy(value)
        ranked = sorted(value['entries'], key=lambda e: (-('routine', 'commitment', 'critical').index(e['strength']), e['window_start'], e['id']))
        for e in ranked:
            base = (e.get('schedule_day', value['day']) - 1) * 1440
            if e['status'] in TERMINAL:
                continue
            goal_id = e.get('linked_goal_id')
            fixed_end = lesson_end(tx.definition, actor, e, e.get('schedule_day', value['day']))
            occupied = e['status'] == 'occupying'
            if occupied:
                if location(tx.state, actor) != e['location_id'] or read(tx.state, 'loc:' + actor, {}).get('transit_to'):
                    e.update(status='blocked', blocked_reason='活动中离开了实际地点', retry_at=now + 5)
                    e.pop('actual_started', None)
                    e.pop('finish_due', None)
                elif now >= e['finish_due']:
                    e.update(status='completed', actual_finished=e['finish_due'], completed_at=now)
                continue
            in_transit = bool(read(tx.state, 'loc:' + actor, {}).get('transit_to'))
            if in_transit and fixed_end is None:
                continue  # Preserve ordinary travel-window behavior.
            end = base + e['window_end'] + e['flexibility']
            # Departure-window routines may arrive after the window closes.
            # Only an actual on-time departure earns this allowance.
            departed_on_time = e.get('timing','arrival')=='departure' and type(e.get('actual_departed')) is int and e['actual_departed']<=end
            if (fixed_end is not None and now >= fixed_end) or (now > end and not departed_on_time):
                e.update(status='missed', blocked_reason='可开始窗口已过，未补写参与')
                goal = read(tx.state, goal_id, {}) if goal_id else {}
                if goal.get('status') == 'active':
                    store_card(tx, goal_id, 'goal', {**goal, 'status': 'expired'}, actor, '安排窗口已结束')
                continue
            if in_transit:
                continue
            path = routes(tx, location(tx.state, actor), e['location_id'], actor=actor)
            from map_runtime import get_locations
            places = get_locations(tx.definition, tx.state)
            origin, travel = location(tx.state, actor), 0
            for dest in path or []:
                travel += places[origin]['links'][dest]
                origin = dest
            e['departure_due'] = base + e['window_start'] - (travel if e.get('timing','arrival')=='arrival' else 0)
            if now < e['departure_due'] or now < e.get('retry_at', 0) or not execute:
                continue
            if path is None or read(tx.state, 'vital:' + actor, {}).get('alive') is False:
                e.update(status='blocked', blocked_reason='没有可执行的路线或人物不能行动', retry_at=now + 5)
                continue
            if read(tx.state, 'activity:' + actor, {}).get('busy_until', 0) > now:
                e.update(status='delayed', blocked_reason='仍在进行另一项活动', retry_at=read(tx.state, 'activity:' + actor)['busy_until'])
                continue
            if not read(tx.state, 'place:' + e['location_id'], {}).get('open', True) or read(tx.state, 'loc:' + actor, {}).get('at_entrance'):
                e.update(status='blocked', blocked_reason='目的地关闭或尚未进入', retry_at=now + 5)
                continue
            if e.get('participation_policy')=='choice' and not goal_id:
                verdict=({'decision':'depart','reason':e.get('decision_reason','本人已决定参加'),'delay':0}
                         if e.get('participation_decision')=='depart' else arbitrate(tx,actor,e,gateway))
                e.update(participation_decision=verdict['decision'],decision_reason=verdict['reason'])
                if verdict['decision']=='decline':e.update(status='declined',declined_at=now);continue
                if verdict['decision']=='defer':e.update(status='delayed',retry_at=now+verdict['delay']);continue
                goal_id=activate_goal(tx,actor,{'id':'event-'+e['event_id'],'kind':'visit','target':e['location_id'],
                    'title':'前往'+e['purpose']+'的现场','priority':55},{'kind':'event_choice','event':e['event_id'],'day':value['day']})
                if not goal_id:e.update(status='delayed',retry_at=now+5,blocked_reason='本人目标容量暂满');continue
                e['linked_goal_id']=goal_id
            if location(tx.state, actor) == e['location_id']:
                if now < base + e['window_start']:
                    continue
                # Late arrivals occupy only the remaining lesson. They do not
                # restart a full lesson or extend it into the next period.
                finish_due = fixed_end if fixed_end is not None else now + e['duration']
                e.update(status='occupying', actual_started=now, finish_due=finish_due)
                store_card(tx, 'activity:' + actor, 'activity', {'owner': actor, 'busy_until': e['finish_due'], 'schedule': e['id']}, actor, '人物开始已安排的活动')
                break
            if not goal_id:
                verdict = arbitrate(tx, actor, e, gateway)
                if verdict['decision'] == 'defer':
                    e.update(status='delayed', retry_at=now + verdict['delay'], blocked_reason=verdict['reason'])
                    continue
                suspended=reserve_slot(tx,actor,e,value['day'])
                goal_id = activate_goal(tx, actor, {'id': 'schedule-' + e['id'], 'kind': 'visit', 'target': e['location_id'],
                                                  'title': e['purpose'], 'priority': 90 if e['strength'] != 'routine' else 55},
                                        {'kind': 'schedule', 'day': value['day'], 'entry': e['id'], 'card': cid})
                if not goal_id:
                    if suspended:store_card(tx,suspended[0],'goal',suspended[1],actor,'安排未启动，保留原来的目标')
                    e.update(status='delayed', blocked_reason='当前已有目标尚未腾出执行容量', retry_at=now + 5)
                    continue
                e['linked_goal_id'] = goal_id
            goal = tx.state['cards'][goal_id]
            plan_id = e.get('plan_id') or create(tx, None, actor, goal)
            if plan_id:
                e['plan_id'] = plan_id
                plan = read(tx.state, plan_id)
                if plan['status'] == 'blocked':
                    store_card(tx, plan_id, 'action_plan', {**plan, 'status': 'active'}, actor, '重审安排路线')
                step(tx, None, actor, goal, plan_id, frames)
                if read(tx.state, 'loc:' + actor, {}).get('transit_to'):
                    e.update(status='travelling', actual_departed=e.get('actual_departed', now))
                else:
                    e.update(status='blocked', blocked_reason=read(tx.state, plan_id).get('blocked_reason', '本段行动未执行'), retry_at=now + 5)
            break
        if value != original:
            store_card(tx, cid, 'daily_schedule', value, actor, '人物日程结算')

def change_from_speech(tx, candidate, speaker, plan_id, detection_record):
    """Consumes only the existing checked detector, never invents a second parser."""
    if not enabled(tx.definition) or speaker == 'player':
        return
    kind = candidate['kind']
    if kind == 'cancel':
        value = copy.deepcopy(read(tx.state, 'schedule:' + speaker, {}))
        for e in value.get('entries', []):
            if e.get('source_plan') == candidate['plan_id'] and e['status'] not in TERMINAL:
                e.update(status='cancelled', cancelled_at=clock_time(tx.state), cancellation_source=detection_record['event_id'])
                gid = e.get('linked_goal_id')
                goal = read(tx.state, gid, {}) if gid else {}
                if goal.get('status') == 'active':
                    store_card(tx, gid, 'goal', {**goal, 'status': 'expired'}, speaker, '本人已取消约定目标')
        if value:
            store_card(tx, 'schedule:' + speaker, 'daily_schedule', value, speaker, '人物取消本人已表达的安排')
        return
    action = candidate.get('action', {})
    if kind != 'promise' or action.get('type') != 'move' or not candidate.get('due_in'):
        return
    from map_runtime import actor_locations
    dest = action['params']['location']
    if dest not in actor_locations(tx.state, tx.definition, speaker):
        return
    build_day(tx, speaker)
    cid = 'schedule:' + speaker
    value = copy.deepcopy(read(tx.state, cid))
    due = clock_time(tx.state) + candidate['due_in']
    record_notice(tx, candidate, speaker, plan_id, detection_record, due, dest)
    # A checked, actually spoken future promise can reconsider a prior decline.
    # Record this intent even if the speaker is already at the venue; being there
    # alone was never consent to take part in its later public activity.
    event=next((e for e in tx.definition['config'].get('fixed_events',[]) if e.get('participation_policy')=='choice'
                and e['location']==dest and e['title'] in candidate['evidence']
                and (e['day']-1)*1440+e['minute']<=due<(e['day']-1)*1440+e['minute']+e.get('duration',60)
                and speaker not in e.get('excluded',[])),None)
    if event:
        goal_id=activate_goal(tx,speaker,{'id':'event-'+event['id'],'kind':'visit','target':dest,
            'title':'前往'+event['title']+'的现场','priority':55},
            {'kind':'event_choice','event':event['id'],'promise':plan_id,'source_event':detection_record['event_id']})
        for entry in value['entries']:
            if entry.get('event_id')==event['id'] and entry['status'] not in ('occupying','completed'):
                entry.update(participation_decision='depart',decision_reason='本人实际表达参加承诺',status='planned')
                entry.pop('retry_at',None)
                if goal_id:entry['linked_goal_id']=goal_id
        store_card(tx,cid,'daily_schedule',value,speaker,'本人承诺更新了参加意向')
    from npc_schedule import MAX_RUNTIME_ENTRIES
    if due // 1440 + 1 != value['day'] or len(value['entries']) >= MAX_RUNTIME_ENTRIES:
        return  # Future dated promise remains in sourced plan; no unsupported fake day card.
    e = {'id': plan_id.replace(':', '-'), 'owner': speaker, 'location_id': dest, 'window_start': due % 1440,
         'window_end': due % 1440, 'duration': 1, 'purpose': candidate['evidence'], 'activity_kind': 'stay',
         'strength': 'commitment', 'flexibility': 0, 'source': 'spoken_promise', 'source_plan': plan_id,
         'source_event_ids': [detection_record['event_id']], 'revision': 1, 'status': 'planned'}
    value['entries'].append(e)
    store_card(tx, cid, 'daily_schedule', value, speaker, '本人实际表达的约定')
def record_notice(tx, candidate, speaker, plan_id, detection_record, due, dest):
    heard = [r for r in tx.records if r.get('speech', {}).get('actor') == speaker and candidate['evidence'] in r['speech']['text']]
    if not heard: return
    audience = sorted(set(a for r in heard for a in r['speech']['audience']))
    from world_state import put
    old = copy.deepcopy(tx.state)
    put(tx.state, 'schedule-notice:' + plan_id, 'schedule_notice',
        {'owner': speaker, 'location_id': dest, 'due_at': due, 'text': candidate['evidence'], 'source_event': detection_record['event_id']},
        [speaker], [speaker, *audience])
    tx.record({'template': 'builtin.schedule_notice', 'effects': [], 'title': '实际表达的安排', 'outcome': 'recorded',
               'participants': [speaker], 'observers': [], 'public': {}, 'rule_id': 'schedule'}, old)
