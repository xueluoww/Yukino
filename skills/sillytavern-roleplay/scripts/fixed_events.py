"""Authored calendar facts and optional participation; shared schedules never teleport."""
import copy
from event_schema import identifier, number
from world_state import clock_time, location, read, put


def validate(events, definition):
    from map_runtime import get_locations
    places=get_locations(definition)
    if not isinstance(events, list) or len(events) > 64:
        raise ValueError('Fixed calendar must contain at most 64 events')
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) - {'id', 'title', 'description', 'day', 'minute', 'duration', 'location',
                                                      'participants', 'excluded', 'sources', 'date_basis', 'notice_locations', 'schedule_override', 'public_schedule','participation_policy'}:
            raise ValueError('Unknown fixed event field')
        identifier(event.get('id'))
        if event['id'] in seen:
            raise ValueError('Duplicate fixed event')
        seen.add(event['id'])
        for field, limit in (('title', 120), ('description', 1600), ('date_basis', 500)):
            if not isinstance(event.get(field), str) or not 1 <= len(event[field]) <= limit:
                raise ValueError('Fixed event requires bounded ' + field)
        number(event.get('day'), 1, 36500); number(event.get('minute'), 0, 1439)
        number(event.get('duration', 60), 1, 180)
        if event['minute'] + event.get('duration', 60) > 1440:
            raise ValueError('Fixed event cannot cross midnight')
        if event.get('location') not in places:
            raise ValueError('Fixed event needs actual location')
        for key in ('participants', 'excluded'):
            values = event.get(key, [])
            if not isinstance(values, list) or len(values) > 30 or set(values) - set(definition['characters']):
                raise ValueError('Fixed event participants must be NPCs, never player')
        if not isinstance(event.get('sources', []), list) or len(event.get('sources', [])) > 10 or any(not isinstance(s, str) or not s.startswith('https://') for s in event.get('sources', [])):
            raise ValueError('Invalid fixed event sources')
        if type(event.get('schedule_override', True)) is not bool:
            raise ValueError('Invalid schedule override')
        if type(event.get('public_schedule', False)) is not bool:
            raise ValueError('Invalid public schedule flag')
        if event.get('participation_policy','scheduled') not in ('scheduled','choice'):
            raise ValueError('Invalid event participation policy')
        if event.get('participation_policy')=='choice' and not event.get('public_schedule'):
            raise ValueError('Autonomous event choice needs a public announcement')
        notices = event.get('notice_locations', [event['location']])
        if not isinstance(notices, list) or set(notices) - set(places):
            raise ValueError('Invalid notice locations')


def forecast(state, definition, cursor=0, limit=50):
    """Read public author announcements, never private goals or future outcomes."""
    from world_presentation import place_name
    from school_calendar import forecast as school_forecast
    now=clock_time(state);rows=[]
    for e in definition['config'].get('fixed_events',[]):
        start=(e['day']-1)*1440+e['minute'];end=start+e.get('duration',60)
        if not e.get('public_schedule',False) or end<=now:continue
        rows.append({'id':'event-'+e['id'],'title':e['title'],'start':start,'end':end,
                     'description':'公开活动安排；是否参加由你决定。','category':'活动'})
    rows.extend(school_forecast(state,definition))
    rows.sort(key=lambda r:(r['start'],r['id']))
    for row in rows:
        def stamp(m):return '第 '+str(m//1440+1)+' 天 · '+f'{m%1440//60:02d}:{m%60:02d}'
        row['display_time']=stamp(row['start'])+' – '+stamp(row['end'])
        row['status_label']='正在进行' if row['start']<=now<row['end'] else '预计'
    cursor=max(0,int(cursor));limit=max(1,min(50,int(limit)))
    return {'view':'expected','total':len(rows),'entries':rows[cursor:cursor+limit],
            'next_cursor':cursor+limit if cursor+limit<len(rows) else None,
            'note':'公开排期，不是已经发生的记录；课程显示未来七天，活动及假期显示剧本已公布的安排。'}


def announcements(definition):
    """Author-declared common information, distinct from private schedules/results.

    Project from the frozen definition instead of duplicating dozens of cards
    per student. All actors receive the same public announcements.
    """
    cfg=definition['config'];school=cfg.get('school_calendar',{})
    return {'source':'剧本公开的学校/活动公告，所有人物可知；仅证明排期，不证明发生、出席或结果。',
            'events':[{'id':e['id'],'title':e['title'],'day':e['day'],'time':f'{e["minute"]//60:02d}:{e["minute"]%60:02d}',
                       'duration':e.get('duration',60),'location':e['location'],'participation_policy':e.get('participation_policy','scheduled')}
                      for e in cfg.get('fixed_events',[])if e.get('public_schedule',False)],
            'school_calendar':{k:copy.deepcopy(school[k])for k in ('start_weekday','school_weekdays','holidays','vacations','special_days','periods')if k in school}}


def entries(definition, actor, day):
    result = []
    for event in definition['config'].get('fixed_events', []):
        if event['day'] != day or actor not in event.get('participants', []) or actor in event.get('excluded', []):
            continue
        result.append({'id': 'fixed-' + event['id'], 'location_id': event['location'], 'window_start': event['minute'],
                       'window_end': min(1439, event['minute'] + 15), 'duration': event.get('duration', 60),
                       'purpose': event['title'], 'strength': 'routine' if event.get('participation_policy')=='choice' else 'commitment',
                       'activity_kind': 'stay', 'flexibility': 0,
                       **({'event_id':event['id'],'participation_policy':'choice'} if event.get('participation_policy')=='choice' else {})})
    return result


def override(definition, actor, day, ordinary):
    additions = entries(definition, actor, day)
    if not additions:
        return ordinary
    def keep(e):
        # An actual promise and critical personal exception retain their priority.
        if e.get('strength', 'routine') != 'routine':
            return True
        for fixed in additions:
            event = next(x for x in definition['config']['fixed_events'] if 'fixed-' + x['id'] == fixed['id'])
            if event.get('participation_policy')!='choice' and event.get('schedule_override', True) and e['window_start'] < fixed['window_start'] + fixed['duration'] and e['window_end'] >= fixed['window_start']:
                return False
        return True
    from npc_schedule import MAX_RUNTIME_ENTRIES
    # Optional opportunities cannot evict lessons, promises or the return home.
    protected=[e for e in ordinary if keep(e) and e.get('strength','routine')!='routine']
    required=[e for e in additions if e.get('participation_policy')!='choice']
    routine=[e for e in ordinary if keep(e) and e not in protected]
    optional=[e for e in additions if e.get('participation_policy')=='choice']
    return (protected+required+routine+optional)[:MAX_RUNTIME_ENTRIES]


def boundaries(tx, target):
    now = clock_time(tx.state)
    return [t for e in tx.definition['config'].get('fixed_events', [])
            for t in ((e['day'] - 1) * 1440 + e['minute'], (e['day'] - 1) * 1440 + e['minute'] + e.get('duration', 60))
            if now < t <= target]


def settle(tx):
    """Calendar occurrence is independent of player attendance and simulation budget."""
    now = clock_time(tx.state)
    for event in tx.definition['config'].get('fixed_events', []):
        start = (event['day'] - 1) * 1440 + event['minute']
        end = start + event.get('duration', 60)
        cid = 'fixed-event:' + event['id']
        existing = read(tx.state, cid)
        if existing is None and now >= start:
            old = copy.deepcopy(tx.state)
            places = event.get('notice_locations', [event['location']])
            observers = [a for a in [*tx.definition['characters'], 'player'] if location(tx.state, a) in places
                         and not read(tx.state, 'loc:' + a, {}).get('transit_to') and not read(tx.state, 'loc:' + a, {}).get('at_entrance')]
            # Late loading does not imply the character witnessed the past start.
            if now > start:
                observers = []
            value = {'id': event['id'], 'title': event['title'], 'description': event['description'], 'start': start, 'end': end,
                     'location': event['location'], 'status': 'ongoing' if now < end else 'ended', 'sources': event.get('sources', []),
                     'date_basis': event['date_basis'], 'participation': {}}
            put(tx.state, cid, 'fixed_event', value, [], observers)
            for actor in observers:
                put(tx.state, 'know:' + actor + ':calendar-' + event['id'], 'knowledge',
                    {'holder': actor, 'topic': 'calendar-' + event['id'], 'content': event['title'] + '：' + event['description'],
                     'belief': 'observed', 'source': {'kind': 'local_calendar_notice', 'at': now, 'event': event['id']}, 'disclose': True}, [actor], [actor])
            tx.record({'template': 'builtin.fixed_event', 'effects': [], 'title': event['title'], 'outcome': 'applied',
                       'participants': [], 'observers': observers, 'public': {'title': event['title'], 'text': event['description'],
                       'location': event['location'], 'started_at': start}, 'rule_id': 'calendar'}, old)
        value = read(tx.state, cid)
        if value and start<=now<end:
            # Entering during an ongoing public event is also an actual local
            # observation. It does not grant attendance at its earlier start.
            for observer in ['player',*tx.definition['characters']]:
                loc=read(tx.state,'loc:'+observer,{})
                if loc.get('location') not in event.get('notice_locations',[event['location']]) or loc.get('transit_to') or loc.get('at_entrance'):continue
                knowledge_id='know:'+observer+':calendar-'+event['id']
                if read(tx.state,knowledge_id) is not None:continue
                old=copy.deepcopy(tx.state)
                put(tx.state,knowledge_id,'knowledge',{'holder':observer,'topic':'calendar-'+event['id'],
                    'content':event['title']+'正在进行：'+event['description'],'belief':'observed',
                    'source':{'kind':'local_ongoing_notice','at':now,'event':event['id']},'disclose':True},[observer],[observer])
                tx.record({'template':'builtin.location_notice','effects':[],'title':'现场活动', 'outcome':'applied',
                    'participants':[observer],'observers':[observer],'public':{'text':'现场的活动通知显示，'+event['title']+'正在进行。'},'rule_id':'calendar'},old)
            candidates=list(tx.definition['characters']) if event.get('participation_policy')=='choice' else event.get('participants',[])
            def opted_in(actor):
                if event.get('participation_policy')!='choice':return True
                if any(e.get('event_id')==event['id'] and e.get('participation_decision')=='depart' for e in read(tx.state,'schedule:'+actor,{}).get('entries',[])):return True
                # An actual NPC adoption/promise can take up an invitation even
                # when not in the original candidate list. Mere player asking cannot.
                for c in tx.state['cards'].values():
                    v=c['value']
                    if c['template']=='goal' and v.get('owner')==actor and v.get('objective')=={'kind':'visit','target':event['location']} and v.get('source',{}).get('kind') in ('heard_language','event_choice') and v.get('source',{}).get('event')==event['id'] and start-1440<=v.get('created_at',-99999)<=now and v.get('status') in ('active','completed'):return True
                    if c['template']=='plan' and v.get('owner')==actor and v.get('kind')=='promise' and v.get('status')!='cancelled' and event['title'] in v.get('text','') and v.get('action')=={'type':'move','params':{'location':event['location']}} and type(v.get('due_at')) is int and start<=v['due_at']<end and c.get('source_event_ids'):return True
                return False
            participants=[a for a in candidates if opted_in(a) and a not in event.get('excluded',[]) and location(tx.state,a)==event['location']
                          and not read(tx.state,'loc:'+a,{}).get('transit_to') and not read(tx.state,'loc:'+a,{}).get('at_entrance')]
            if location(tx.state,'player')==event['location'] and not read(tx.state,'loc:player',{}).get('transit_to') and not read(tx.state,'loc:player',{}).get('at_entrance'):
                participants.append('player')
            for actor in participants:
                value=copy.deepcopy(read(tx.state,cid))
                if actor in value['participation']:continue
                old=copy.deepcopy(tx.state)
                value['participation'][actor]={'at':now,'basis':'actual_onsite_presence'}
                put(tx.state,cid,'fixed_event',value,[],tx.state['cards'][cid]['visibility'])
                record=tx.record({'template':'builtin.calendar_presence','effects':[],'title':event['title']+'实际在场', 'outcome':'recorded',
                                 'participants':[actor],'observers':[], 'public':{},'rule_id':'calendar'},old)
                # Only actual local contact, not everyone sharing an area ID.
                from scene_presence import can_hear
                from relation_policy import experience,settle as settle_relation
                for peer in participants:
                    if peer==actor or not can_hear(tx.state,tx.definition,actor,peer):continue
                    relation_id='rel:'+actor+':'+peer; rv=copy.deepcopy(read(tx.state,relation_id,{}))
                    key='calendar:'+event['id']
                    if key in rv.get('calendar_experiences',[]):continue
                    old=copy.deepcopy(tx.state)
                    experience(tx.state,actor,peer,record['event_id'],key)
                    rv=copy.deepcopy(read(tx.state,relation_id))
                    rv['calendar_experiences']=(rv.get('calendar_experiences',[])+[key])[-64:]
                    rv=settle_relation(tx.state,tx.definition,actor,peer,rv,{'affection':1,'trust':1,'familiarity':1},
                                      {'kind':'shared_experience','event_id':record['event_id']})
                    put(tx.state,relation_id,'relation',rv,[actor,peer],[actor])
                    tx.record({'template':'builtin.relation','effects':[],'title':'共同经历', 'outcome':'recorded',
                               'participants':[actor,peer],'observers':[],'public':{},'rule_id':'calendar'},old)
        if value and value['status'] != 'ended' and now >= end:
            old = copy.deepcopy(tx.state)
            value = copy.deepcopy(value); value['status'] = 'ended'
            put(tx.state, cid, 'fixed_event', value, [], tx.state['cards'][cid]['visibility'])
            tx.record({'template': 'builtin.calendar_end', 'effects': [], 'title': event['title'] + '结束', 'outcome': 'recorded',
                       'participants': [], 'observers': [], 'public': {}, 'rule_id': 'calendar'}, old)

