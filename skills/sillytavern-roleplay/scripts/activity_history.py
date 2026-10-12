"""Personal itinerary evidence. Unknown intervals are not invented visits."""
import copy


def observe(state, record):
    from world_state import put, read, clock_time
    kind = record['template']
    if kind not in ('builtin.arrival', 'builtin.simulation_gap'):
        return
    actors = record.get('participants', []) if kind == 'builtin.arrival' else [c['subjects'][0] for c in state['cards'].values() if c['template'] == 'location']
    for actor in actors:
        cid = 'activity-history:' + actor
        value = copy.deepcopy(read(state, cid, {'owner': actor, 'start': clock_time(state), 'visits': [], 'gaps': []}))
        if kind == 'builtin.arrival':
            value['visits'] = (value['visits'] + [{'location': record['public']['location'], 'at': record['story_time'],
                                                'source_event': record['event_id']}])[-128:]
        else:
            gap=read(state,'simulation:'+record['request_id'],record.get('public',{}))
            value['gaps'] = (value['gaps'] + [copy.deepcopy(gap)])[-32:]
        put(state, cid, 'activity_history', value, [actor], [actor])


def view(state, definition, actor, archive=()):
    from world_state import read, clock_time, location
    from map_runtime import actor_locations
    value = copy.deepcopy(read(state, 'activity-history:' + actor, {'owner': actor, 'start': clock_time(state), 'visits': [], 'gaps': []}))
    # Read-only recovery for frozen saves created before personal itineraries.
    # Only own actual arrivals from this branch, never other people's journals.
    visits={v.get('source_event'):v for v in value['visits']}
    for turn in archive:
        for record in turn.get('world_packet',{}).get('records',[]):
            if record.get('template')!='builtin.arrival' or record.get('outcome')!='applied':continue
            if record.get('public',{}).get('actor')!=actor or record.get('story_time',clock_time(state)+1)>clock_time(state):continue
            visits.setdefault(record['event_id'],{'location':record['public']['location'],'at':record['story_time'],'source_event':record['event_id']})
    value['visits']=sorted(visits.values(),key=lambda v:v['at'])[-128:]
    places = actor_locations(state, definition, actor)
    value['visits'] = [{**v, 'name': places.get(v['location'], {}).get('name', '某处')} for v in value['visits'][-24:]]
    value.update(current_location=location(state, actor), current_time=clock_time(state),
                 policy='实际到场是证据；背景可说明开场前经历；未模拟空白不能补造旅行。没有记录不能断言从未去过。')
    return value


def check_past_claim(state, definition, actor, text, archive=()):
    """Narrow local check. General semantic claims still use the sourced verifier."""
    import re
    history = view(state, definition, actor, archive)
    me = definition['characters'].get(actor, {})
    background = ' '.join(f.get('text', '') for f in me.get('personal_background', {}).get('facts', []))
    if not re.search(r'昨天|这几天|最近几天|之前|上次|去过|去了|偶尔|经常', text):
        return
    allowed = {v['location'] for v in history['visits']} | {history['current_location']}
    for lid, place in __import__('map_runtime').actor_locations(state, definition, actor).items():
        name = place.get('name', '')
        if not name or name not in text or name in background:
            continue
        # Negative, uncertain and planned remarks do not assert a past visit.
        for clause in re.split(r'[。！？；]', text):
            if name not in clause or not re.search(r'(?:去|到|待在|走走|散步|逛|住)', clause):
                continue
            if re.search(r'没去|未去|没到|不记得|不能确认|不确定|不知道|打算|准备|如果|没有记录|没法确认', clause):
                continue
            if lid not in allowed:
                raise ValueError('Past location claim lacks personal arrival or static background evidence')
            if '昨天' in clause:
                day_start=(state['clock']['day']-1)*1440
                if not any(v['location']==lid and day_start-1440<=v['at']<day_start for v in history['visits']):
                    raise ValueError('Yesterday visit lacks time-matching personal evidence')
            if re.search(r'偶尔|经常|每天', clause) and sum(v['location'] == lid for v in history['visits']) < 2 and name not in background:
                raise ValueError('Recurring past visit lacks repeated personal evidence')

