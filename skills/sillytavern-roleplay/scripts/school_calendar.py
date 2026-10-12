"""Authored expectations, sampled attendance and sourced teacher knowledge.

No forced player movement, no inferred exam results, no omniscient teachers.
Calendar days are story-relative; a reference calendar never sets the story era.
"""
import copy
from event_schema import identifier,number
from world_state import read,put,location,clock_time

def validate(config,definition):
    cfg=config.get('school_calendar')
    if cfg is None:return
    fields={'version','start_weekday','school_weekdays','holidays','vacations','periods','player_classroom',
            'teachers','notice_locations','basis','sources','consequence','special_days'}
    if not isinstance(cfg,dict) or set(cfg)-fields or cfg.get('version')!=1:raise ValueError('Invalid school calendar')
    number(cfg.get('start_weekday',0),0,6)
    weekdays=cfg.get('school_weekdays',[0,1,2,3,4])
    if not isinstance(weekdays,list) or len(weekdays)>7 or len(set(weekdays))!=len(weekdays):raise ValueError('Invalid school weekdays')
    for x in weekdays:number(x,0,6)
    from map_runtime import get_locations
    places=get_locations(definition)
    if cfg.get('player_classroom') is not None and cfg['player_classroom'] not in places:raise ValueError('Unknown player classroom')
    for key,limit in (('holidays',64),('vacations',8),('special_days',64),('periods',8)):
        rows=cfg.get(key,[])
        if not isinstance(rows,list) or len(rows)>limit:raise ValueError('Unbounded calendar '+key)
        seen=set()
        for r in rows:
            if not isinstance(r,dict):raise ValueError('Calendar row requires an object')
            if key=='periods':
                if set(r)-{'id','start','end','title'}:raise ValueError('Unknown lesson field')
                identifier(r.get('id'));number(r.get('start'),0,1439);number(r.get('end'),r['start']+1,min(1440,r['start']+180))
                if r['id'] in seen:raise ValueError('Duplicate lesson')
                seen.add(r['id'])
            elif key=='vacations':
                if set(r)-{'start','end','name'}:raise ValueError('Unknown vacation field')
                number(r.get('start'),1,36500);number(r.get('end'),r['start'],36500)
            else:
                if set(r)-({'day','name'} if key=='holidays' else {'day','name','classes'}):raise ValueError('Unknown calendar day field')
                number(r.get('day'),1,36500)
                if r['day'] in seen:raise ValueError('Duplicate calendar day')
                seen.add(r['day'])
                if key=='special_days' and type(r.get('classes')) is not bool:raise ValueError('Special day needs explicit classes flag')
            label=r.get('title' if key=='periods' else 'name')
            if not isinstance(label,str) or not 1<=len(label)<=120:raise ValueError('Calendar needs bounded label')
    spans=sorted((p['start'],p['end']) for p in cfg.get('periods',[]))
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('Lessons overlap')
    teachers=cfg.get('teachers',{})
    if not isinstance(teachers,dict) or set(teachers)-set(definition['characters']):raise ValueError('Unknown teacher')
    ids={p['id'] for p in cfg.get('periods',[])}
    for spec in teachers.values():
        if not isinstance(spec,dict) or set(spec)-{'location','periods'} or spec.get('location') not in places:raise ValueError('Unknown teaching location')
        if not isinstance(spec.get('periods'),list) or set(spec['periods'])-ids:raise ValueError('Unknown teaching period')
    if cfg.get('consequence','reminder') not in ('reminder','talk','trust'):raise ValueError('Invalid attendance consequence')
    notices=cfg.get('notice_locations',[])
    if not isinstance(notices,list) or set(notices)-set(places):raise ValueError('Unknown bell location')
    if not isinstance(cfg.get('sources',[]),list) or len(cfg.get('sources',[]))>10 or any(not isinstance(x,str) or len(x)>2000 or not x.startswith('https://') for x in cfg.get('sources',[])):raise ValueError('Invalid school sources')
    if not isinstance(cfg.get('basis',''),str) or len(cfg.get('basis',''))>1600:raise ValueError('Invalid school basis')

def day_info(state,definition,day=None):
    cfg=definition['config'].get('school_calendar')
    if not cfg:return None
    day=day or state['clock']['day']
    weekday=(cfg.get('start_weekday',0)+day-1)%7
    if state['clock'].get('date'):
        import datetime
        weekday=(datetime.date.fromisoformat(state['clock']['date'])+datetime.timedelta(days=day-state['clock']['day'])).weekday()
    special=next((r for r in cfg.get('special_days',[]) if r['day']==day),None)
    holiday=next((r for r in cfg.get('holidays',[]) if r['day']==day),None)
    vacation=next((r for r in cfg.get('vacations',[]) if r['start']<=day<=r['end']),None)
    classes=special['classes'] if special else not holiday and not vacation and weekday in cfg.get('school_weekdays',[0,1,2,3,4])
    label=(special or holiday or vacation or {}).get('name','上课日' if classes else '周末休息日')
    return {'day':day,'weekday':weekday,'classes':bool(classes),'label':label}

def view(state,definition):
    info=day_info(state,definition)
    if info is None:return {'enabled':False,'periods':[]}
    cfg=definition['config']['school_calendar'];dest=cfg.get('player_classroom')
    from world_presentation import place_name
    rows=[{**p,'location':place_name(definition,dest,state)} for p in cfg.get('periods',[])] if info['classes'] and dest else []
    return {'enabled':True,**info,'periods':rows,'attendance':copy.deepcopy(read(state,'attendance:player',{})),
            'note':'课表是安排，是否前往由你决定；考勤只记录实际检查的时刻，不推断整天的经历。'}

def npc_entries(tx,actor,day):
    info=day_info(tx.state,tx.definition,day)
    if not info or not info['classes']:return []
    cfg=tx.definition['config']['school_calendar'];profile=tx.definition['characters'][actor]
    dest=profile.get('classroom_id');teacher=cfg.get('teachers',{}).get(actor)
    result=[]
    for p in cfg.get('periods',[]):
        if teacher:
            if p['id'] not in teacher['periods']:continue
            dest=teacher['location']
        if not dest:continue
        result.append({'id':'lesson-'+p['id'],'location_id':dest,'window_start':p['start'],'window_end':p['end'],
                       'duration':p['end']-p['start'],'purpose':('授课：' if teacher else '课程安排：')+p['title'],
                       'strength':'commitment','activity_kind':'stay','timing':'arrival','flexibility':0,
                       'calendar_period':p['id']})
    return result

def lesson_end(definition,actor,entry,day):
    """Only shell-derived lessons have a fixed end; routine durations stay relative.

    calendar_period is internal metadata, absent from author/model entry fields.
    Read the frozen calendar rather than trusting a proposed execution deadline.
    """
    cfg=definition['config'].get('school_calendar',{})
    period=next((p for p in cfg.get('periods',[]) if p['id']==entry.get('calendar_period')),None)
    if period is None:return None
    teacher=cfg.get('teachers',{}).get(actor)
    dest=definition['characters'][actor].get('classroom_id')
    if teacher:
        if period['id'] not in teacher['periods']:return None
        dest=teacher['location']
    if entry['id']!='lesson-'+period['id'] or entry['location_id']!=dest:return None
    return (day-1)*1440+period['end']

def forecast(state,definition):
    cfg=definition['config'].get('school_calendar')
    if not cfg:return []
    now=clock_time(state);rows=[];day=state['clock']['day']
    if cfg.get('player_classroom'):
        for d in range(day,day+7):
            if not day_info(state,definition,d)['classes']:continue
            for p in cfg.get('periods',[]):
                start=(d-1)*1440+p['start'];end=(d-1)*1440+p['end']
                if end>now:rows.append({'id':f'lesson-{d}-{p["id"]}','title':p['title'],'start':start,'end':end,
                    'description':'课表安排；是否去上课由你决定。','category':'课程'})
    for key in ('holidays','vacations','special_days'):
        for e in cfg.get(key,[]):
            first=e.get('day',e.get('start'));last=e.get('day',e.get('end'));start=(first-1)*1440;end=last*1440
            if end<=now:continue
            rows.append({'id':key+'-'+str(first),'title':e['name'],'start':start,'end':end,
                         'description':'当天按特别安排上课。' if key=='special_days' and e['classes'] else '这段时间不安排普通正课。',
                         'category':'校历'})
    return rows

def boundaries(tx,target):
    cfg=tx.definition['config'].get('school_calendar')
    if not cfg:return []
    now=clock_time(tx.state);result=[]
    for d in range(now//1440+1,target//1440+2):
        if not day_info(tx.state,tx.definition,d)['classes']:continue
        result.extend((d-1)*1440+m for p in cfg.get('periods',[]) for m in (p['start'],p['end']) if now<(d-1)*1440+m<=target)
    midnight=(now//1440+1)*1440
    if midnight<=target:result.append(midnight)
    return result

def settle(tx):
    cfg=tx.definition['config'].get('school_calendar')
    if not cfg or not tx.definition['config'].get('world_mode') or getattr(tx,'schedule_gap',False):return
    info=day_info(tx.state,tx.definition);now=clock_time(tx.state);minute=tx.state['clock']['minute']
    dest=cfg.get('player_classroom');cid='attendance:player'
    previous=read(tx.state,cid)
    value=copy.deepcopy(previous) if previous and previous['day']==info['day'] else {'owner':'player',**info,'entries':[]}
    if info['classes'] and dest:
        for p in cfg.get('periods',[]):
            row=next((r for r in value['entries'] if r['id']==p['id']),None)
            if row is None:
                row={'id':p['id'],'title':p['title'],'window':[p['start'],p['end']], 'expected_location':dest,'status':'unknown'}
                value['entries'].append(row)
            if not p['start']<=minute<p['end']:continue
            loc=read(tx.state,'loc:player',{})
            present=location(tx.state,'player')==dest and not loc.get('transit_to') and not loc.get('at_entrance')
            if present:
                was_missing=row.get('status') in ('absent','late')
                row.setdefault('first_present',now)
                # A first observation midway through class cannot prove late arrival.
                row['status']='late' if was_missing else 'present'
            else:row['status']='left_early' if 'first_present' in row else 'absent'
            actual=location(tx.state,'player')
            sample={'actual_location':actual,'in_transit':bool(loc.get('transit_to')),'status':row['status']}
            if any(row.get(k)!=v for k,v in sample.items()):row.update(sample,observed_at=now)
            # A teacher can observe absence through an actual local roll call,
            # or see this student elsewhere. Neither implies a full day's absence.
            from scene_presence import visible_actor_ids
            for teacher,spec in cfg.get('teachers',{}).items():
                if p['id'] not in spec['periods']:continue
                teacher_loc=read(tx.state,'loc:'+teacher,{})
                if teacher_loc.get('transit_to') or teacher_loc.get('at_entrance'):continue
                roll=location(tx.state,teacher)==dest==spec['location']
                seen='player' in visible_actor_ids(tx.state,tx.definition,teacher)
                if not roll and not seen:continue
                topic='attendance-player-'+str(info['day'])+'-'+p['id'];kid='know:'+teacher+':'+topic
                # Never repeat punishment or overwrite the first sourced observation.
                if read(tx.state,kid):continue
                from world_presentation import place_name
                text=('这次课堂点名时，主角'+('在' if present else '不在')+place_name(tx.definition,dest,tx.state)+'。' if roll else
                      '正课时段，你看到主角在'+place_name(tx.definition,actual,tx.state)+'。')
                old=copy.deepcopy(tx.state)
                put(tx.state,kid,'knowledge',{'holder':teacher,'topic':topic,'content':text+'仅代表这次观察，不能推断整天缺勤。',
                    'belief':'observed','source':{'kind':'roll_call' if roll else 'see','at':now,'period':p['id'],'location':location(tx.state,teacher)},'disclose':True},[teacher],[teacher])
                rec=tx.record({'template':'builtin.attendance_observation','effects':[],'title':'课堂观察','outcome':'recorded',
                    'participants':[teacher],'observers':[],'public':{},'rule_id':'attendance'},old)
                missing=not present
                day_marker='attendance-consequence:'+teacher+':'+str(info['day'])
                if missing and not read(tx.state,day_marker) and cfg.get('consequence','reminder')!='reminder':
                    old=copy.deepcopy(tx.state);put(tx.state,day_marker,'attendance_consequence',{'at':now,'source':rec['event_id']},[teacher],[teacher])
                    tx.record({'template':'builtin.attendance_consequence','effects':[],'title':'出勤后续','outcome':'recorded','participants':[teacher],'observers':[],'public':{},'rule_id':'attendance'},old)
                    if cfg['consequence']=='trust':
                        from relationship_graph import update
                        update(tx,teacher,'player',trust=-1,source={'kind':'attendance_observation','event_id':rec['event_id']})
                    else:tx.apply({'template':'builtin.offer','id':'attendance-talk-'+teacher+'-'+str(info['day']), 'actor':teacher,'target':'player',
                                   'title':'关于课堂出勤的谈话邀请'},True,'来自老师实际观察的缺席','attendance')
            if minute==p['start'] and actual in cfg.get('notice_locations',[]) and not loc.get('transit_to'):
                marker='school-bell:'+str(info['day'])+':'+p['id']
                if not read(tx.state,marker):
                    old=copy.deepcopy(tx.state);put(tx.state,marker,'school_notice',{'at':now},['player'],['player'])
                    tx.record({'template':'builtin.location_notice','effects':[],'title':'上课铃','outcome':'applied','participants':['player'],'observers':['player'],
                               'public':{'text':'上课铃响了，接下来是'+p['title']+'。是否回教室由你决定。'},'rule_id':'school'},old)
    if value!=previous:
        old=copy.deepcopy(tx.state);put(tx.state,cid,'attendance',value,['player'],['player'])
        tx.record({'template':'builtin.attendance','effects':[],'title':'出勤记录','outcome':'recorded','participants':['player'],'observers':[], 'public':{},'rule_id':'attendance'},old)
