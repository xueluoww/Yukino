"""Private daily arrangements, built lazily; candidates are never actual activity."""
import copy
from event_schema import identifier, number
from world_state import read, location, clock_time
from goal_sets import store_card

FEATURE = 'npc_schedule_v1'
STRENGTHS = ('routine', 'commitment', 'critical')
TERMINAL = ('completed', 'missed', 'cancelled', 'declined')
# Author/model input stays capped at eight/four. Derived lessons, public choices
# and actual promises share a separate bounded runtime card.
MAX_RUNTIME_ENTRIES = 16
PROMPT = '''只为view本人提出今天余下空档的常规安排，JSON {entries:[]}，最多4项。
每项{id,location_id,window_start,window_end,duration,purpose,activity_kind,strength,flexibility,timing可选}。
timing为arrival（到达并开始活动的窗口，默认）或departure（出发窗口，例如回家）；不能把一般返家安排当作必须提前到家的约定。
activity_kind仅stay/rest；strength必须routine；flexibility为整数分钟0..120。
地点只用allowed_locations。window_start/end为今天0..1439分钟，duration为1..180。
不能改已有安排、设他人目标、编未确认社团/家庭/考试、强制玩家参加。可空集。
arrangements只是计划，不是实际出发、到达或完成；无effects/actions/owner/status。'''

def enabled(definition):
    return definition['config'].get('world_mode') is True and FEATURE in definition['config'].get('features', [])

def validate_entries(entries, definition, actor, generated=False, state=None):
    from map_runtime import get_locations, actor_locations
    places = get_locations(definition, state)
    allowed = actor_locations(state, definition, actor) if state else places
    if actor not in definition['characters']:
        raise ValueError('Schedule owner must be NPC')
    if not isinstance(entries, list) or len(entries) > 8:
        raise ValueError('Schedule entries must be bounded')
    result, seen = [], set()
    fields = {'id', 'location_id', 'window_start', 'window_end', 'duration', 'purpose', 'activity_kind', 'strength', 'flexibility', 'weekdays', 'day','timing','event_id','participation_policy','school_days_only'}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - fields:
            raise ValueError('Unknown schedule field')
        e = copy.deepcopy(entry)
        identifier(e.get('id'))
        if e['id'] in seen:
            raise ValueError('Duplicate schedule id')
        seen.add(e['id'])
        dest = e.get('location_id')
        if dest not in places or not places[dest].get('walkable', True) or generated and dest not in allowed:
            raise ValueError('Schedule destination outside known walkable map')
        number(e.get('window_start'), 0, 1439)
        number(e.get('window_end'), e['window_start'], 1439)
        number(e.get('duration'), 1, 180)
        number(e.get('flexibility', 0), 0, 120)
        if not isinstance(e.get('purpose'), str) or not 1 <= len(e['purpose']) <= 160:
            raise ValueError('Schedule purpose must be bounded')
        if e.get('activity_kind', 'stay') not in ('stay', 'rest'):
            raise ValueError('Reading/transfer needs an actual action, not schedule completion')
        if e.get('strength', 'routine') not in STRENGTHS or generated and e.get('strength', 'routine') != 'routine':
            raise ValueError('Model cannot create a commitment or critical schedule')
        if 'day' in e:
            number(e['day'], 1, 36500)
        if 'school_days_only' in e:
            if generated or type(e['school_days_only']) is not bool:
                raise ValueError('School-day restriction must be authored as a boolean')
            if e['school_days_only'] and not definition['config'].get('school_calendar'):
                raise ValueError('School-day restriction needs an authored school calendar')
        if 'weekdays' in e and (not isinstance(e['weekdays'], list) or not e['weekdays'] or any(type(x) is not int or not 0 <= x <= 6 for x in e['weekdays'])):
            raise ValueError('Invalid schedule weekdays')
        e.setdefault('activity_kind', 'stay')
        if 'participation_policy' in e:
            if generated or e['participation_policy']!='choice':raise ValueError('Model cannot invent calendar choice entries')
            identifier(e.get('event_id'))
            if e['event_id'] not in {x['id']for x in definition['config'].get('fixed_events',[])if x.get('participation_policy')=='choice'}:raise ValueError('Choice entry needs an authored event')
        if e.get('timing','arrival') not in ('arrival','departure'):
            raise ValueError('Schedule timing must be arrival or departure')
        e.setdefault('strength', 'routine')
        e.setdefault('flexibility', 0)
        result.append(e)
    return result

def validate_schedule(raw, definition):
    if not isinstance(raw, dict) or set(raw) - {'version', 'generation', 'actors'} or raw.get('version') != 1:
        raise ValueError('Invalid schedules contract')
    if raw.get('generation', 'shell') not in ('shell', 'model', 'none'):
        raise ValueError('Invalid schedules generation')
    actors = raw.get('actors', {})
    if not isinstance(actors, dict) or set(actors) - set(definition['characters']):
        raise ValueError('Unknown schedule actor')
    for actor, entries in actors.items():
        validate_entries(entries, definition, actor)
    return copy.deepcopy(raw)

def shell_candidates(tx, actor):
    """Only explicit identity/location bindings; no invented job or club."""
    from map_runtime import actor_locations
    known = actor_locations(tx.state, tx.definition, actor)
    profile = tx.definition['characters'][actor]
    result = []
    for field, start, end, duration, purpose in (
        ('classroom_id', 480, 500, 30, '到自己的教室准备上课'),
        ('home_id', 1050, 1110, 20, '回家休息'),
    ):
        from school_calendar import day_info
        info=day_info(tx.state,tx.definition)
        if field=='classroom_id' and info is not None and not info['classes']:continue
        dest = profile.get(field)
        if dest in known:
            result.append({'id': field, 'location_id': dest, 'window_start': start, 'window_end': end,
                           'duration': duration, 'purpose': purpose, 'strength': 'routine', 'activity_kind': 'stay',
                           'timing':'departure' if field=='home_id' else 'arrival'})
    return result

def generate_candidates(tx, actor, day, gateway):
    from world_turn import validated_request
    from model_context import working_view
    from map_runtime import actor_locations
    from feature_budget import LimitedGateway
    allowed = actor_locations(tx.state, tx.definition, actor)
    limited = LimitedGateway(tx, gateway, 'schedule-generator', actor, daily=1)
    payload = {'view': working_view(tx, actor), 'day': day, 'allowed_locations': [{'id': k, 'name': v.get('name', k)} for k, v in allowed.items()]}
    def validate(a):
        if set(a) != {'entries'}:
            raise ValueError('Schedule generator requires entries only')
        validate_entries(a['entries'], tx.definition, actor, True, tx.state)
    answer = validated_request(limited, 'schedule-generator:' + actor, PROMPT, payload, validate, 800)
    return validate_entries(answer['entries'], tx.definition, actor, True, tx.state)

def build_day(tx, actor, day=None, gateway=None):
    if not enabled(tx.definition):
        return None
    day = day or tx.state['clock']['day']
    if day != tx.state['clock']['day']:
        raise ValueError('Only current day may be built')
    if day not in getattr(tx, 'schedule_allowed_days', {day}):
        return None
    # Same transaction builds at most initial and destination day; never intermediate ghost days.
    built = getattr(tx, 'schedule_days', set())
    if day not in built and len(built) >= 2:
        return None
    built.add(day)
    tx.schedule_days = built
    cid = 'schedule:' + actor
    previous = read(tx.state, cid, {})
    if previous.get('day') == day:
        return cid
    # Unfinished previous-day entries cannot leave immortal goals or busy flags.
    if previous:
        for entry in previous.get('entries', []):
            gid = entry.get('linked_goal_id')
            goal = read(tx.state, gid, {}) if gid else {}
            if goal.get('status') == 'active':
                store_card(tx, gid, 'goal', {**goal, 'status': 'expired'}, actor, '旧日安排已结束')
        activity = read(tx.state, 'activity:' + actor, {})
        if activity.get('schedule') and activity.get('busy_until', 0) <= clock_time(tx.state):
            store_card(tx, 'activity:' + actor, 'activity', {'owner': actor, 'busy_until': clock_time(tx.state)}, actor, '既有活动时段已结束')
    raw = tx.definition['config'].get('schedules', {'version': 1})
    entries = raw.get('actors', {}).get(actor)
    source = 'author' if entries is not None else 'shell'
    if entries is None and raw.get('generation') == 'model' and gateway:
        try:
            entries = generate_candidates(tx, actor, day, gateway)
            source = 'model'
        except (ValueError, TypeError, KeyError) as error:
            from diagnostic_system import record
            record(tx, actor, 'schedule-generation', error, {}, 'shell-fallback')
    if entries is None:
        entries = [] if raw.get('generation') == 'none' else shell_candidates(tx, actor)
    entries = validate_entries(entries, tx.definition, actor, source == 'model', tx.state)
    from school_calendar import npc_entries
    school=npc_entries(tx,actor,day)
    # Explicit critical/promise exceptions survive. Calendar lessons replace the
    # shell's preparatory classroom visit when their slot budget would overflow.
    if school:
        protected=[e for e in entries if e.get('strength','routine')!='routine']
        remaining=[e for e in entries if e not in protected and e['id']!='classroom_id']
        entries=(protected+school+remaining)[:MAX_RUNTIME_ENTRIES]
    from fixed_events import override
    entries = override(tx.definition, actor, day, entries)
    weekday = None
    from school_calendar import day_info
    info=day_info(tx.state,tx.definition,day)
    if info is not None:weekday=info['weekday']
    if tx.state['clock'].get('date'):
        import datetime
        weekday = datetime.date.fromisoformat(tx.state['clock']['date']).weekday()
    current = [{**copy.deepcopy(e), 'schedule_day': previous['day']} for e in previous.get('entries', [])
               if e.get('status') == 'occupying' and e.get('finish_due', 0) >= clock_time(tx.state)]
    for entry in entries:
        if entry.get('day', day) != day or 'weekdays' in entry and weekday not in entry['weekdays']:
            continue
        if entry.get('school_days_only') and (info is None or not info['classes']):
            continue
        e = {**entry, 'owner': actor, 'status': 'planned', 'source': source, 'revision': 1}
        # An arrangement already gone before first construction isn't past participation.
        if e['window_end'] + e['flexibility'] < tx.state['clock']['minute']:
            e.update(status='missed', blocked_reason='首次构建时可开始窗口已经过去')
        if len(current) < MAX_RUNTIME_ENTRIES: current.append(e)
    # Preserve actual dated promises from yesterday; never invent a future day early.
    for plan in list(tx.state['cards'].values()):
        v = plan['value']
        due = v.get('due_at') if isinstance(v, dict) else None
        action = v.get('action') or {} if isinstance(v, dict) else {}
        if plan['template'] != 'plan' or v.get('owner') != actor or v.get('status') != 'pending' or v.get('kind') != 'promise': continue
        if type(due) is not int or due // 1440 + 1 != day or action.get('type') != 'move' or not plan.get('source_event_ids'): continue
        dest = action.get('params', {}).get('location')
        if len(current) >= MAX_RUNTIME_ENTRIES or any(e.get('source_plan') == plan['id'] for e in current): continue
        e = {'id': plan['id'].replace(':', '-'), 'owner': actor, 'location_id': dest, 'window_start': due % 1440,
             'window_end': due % 1440, 'duration': 1, 'purpose': v['text'], 'activity_kind': 'stay', 'strength': 'commitment',
             'flexibility': 0, 'source': 'spoken_promise', 'source_plan': plan['id'], 'source_event_ids': plan['source_event_ids'], 'revision': 1,
             'status': 'missed' if due < clock_time(tx.state) else 'planned'}
        validate_entries([{k:v for k,v in e.items() if k in {'id','location_id','window_start','window_end','duration','purpose','activity_kind','strength','flexibility'}}], tx.definition, actor, state=tx.state)
        current.append(e)
    # A fixed per-actor card bounds active storage. Past actuals remain in immutable packets.
    store_card(tx, cid, 'daily_schedule', {'owner': actor, 'day': day, 'entries': current}, actor, '人物当天安排')
    return cid

def disclose_view(state, definition, actor='player'):
    """Only actual sourced public statements, never remote daily schedules."""
    return [copy.deepcopy(c['value']) for c in state['cards'].values()
            if c['template'] == 'schedule_notice' and actor in c['visibility'] and c['valid_from'] <= clock_time(state)]

def temporal_issues(state):
    """Read-only check: invalid actuals are quarantined, authority is never silently rewritten."""
    now = clock_time(state)
    issues = []
    for cid, c in state['cards'].items():
        if c['template'] != 'daily_schedule':
            continue
        for e in c['value']['entries']:
            for key in ('actual_departed', 'actual_started', 'actual_finished', 'completed_at'):
                value = e.get(key)
                if value is not None and (type(value) is not int or value > now):
                    issues.append({'card': cid, 'entry': e['id'], 'field': key, 'reason': 'future_or_invalid_actual'})
            if e.get('status') == 'completed' and e.get('completed_at') is None:
                issues.append({'card': cid, 'entry': e['id'], 'reason': 'completion_without_actual'})
    return issues
