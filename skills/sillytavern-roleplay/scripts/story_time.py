"""Frozen script time policy, deterministic action costs and dated knowledge gates.

Legacy saves deliberately keep their original clock. No wall clock is consulted.
"""
import copy
import datetime as dt
import re

DEFAULT_COSTS = {'speech': 1, 'thought': 0, 'action': 5, 'environment': 0, 'travel': 10}


def integer(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(label + '必须是范围内的整数。')
    return value


def date(value):
    if value is not None:
        if not isinstance(value, str): raise ValueError('日期必须为 YYYY-MM-DD 或 null。')
        return dt.date.fromisoformat(value).isoformat()
    return None


def policy(raw, refs=()):
    if not isinstance(raw, dict): raise ValueError('time 必须是对象。')
    if set(raw) - {'version','start','era','durations','max_turn_minutes','module_id','allow_time_travel','provenance'}:
        raise ValueError('time 包含未知字段，请检查拼写。')
    if raw.get('version', 1) != 1: raise ValueError('不支持的时间协议版本。')
    start = copy.deepcopy(raw.get('start', {}))
    if not isinstance(start, dict) or set(start) - {'date','minute','label'}: raise ValueError('time.start 格式不正确。')
    start['date'] = date(start.get('date'))
    start['minute'] = integer(start.get('minute',960),0,1439,'开场时刻')
    start['label'] = start.get('label','')
    if not isinstance(start['label'],str) or len(start['label'])>200: raise ValueError('开场时间说明过长。')
    era = copy.deepcopy(raw.get('era',{}))
    if not isinstance(era,dict) or set(era)-{'label','knowledge_cutoff'}: raise ValueError('time.era 格式不正确。')
    era['knowledge_cutoff'] = date(era.get('knowledge_cutoff'))
    era['label'] = era.get('label','')
    if not isinstance(era['label'],str) or len(era['label'])>200: raise ValueError('时代说明不正确。')
    costs = dict(DEFAULT_COSTS)
    supplied = raw.get('durations',{})
    if not isinstance(supplied,dict) or set(supplied)-set(costs): raise ValueError('行动耗时字段不正确。')
    for key,value in supplied.items(): costs[key]=integer(value,0,1440,'行动耗时')
    travel = raw.get('allow_time_travel',False)
    if type(travel) is not bool: raise ValueError('allow_time_travel 必须为布尔值。')
    result = {'version':1,'start':start,'era':era,'durations':costs,
              'max_turn_minutes':integer(raw.get('max_turn_minutes',10080),1,525600,'单次时间上限'),
              'allow_time_travel':travel,'module_id':raw.get('module_id'),
              'provenance':copy.deepcopy(raw.get('provenance',{}))}
    if not isinstance(result['provenance'],dict) or len(str(result['provenance']))>4000: raise ValueError('时间来源说明不正确。')
    if result['module_id'] is not None:
        ref=next((r for r in refs if r['id']==result['module_id']),None)
        if ref is None: raise ValueError('自定义时间模块未随剧本导入。')
        result['module_ref']=copy.deepcopy(ref)
    return result


def seed(world):
    # Old packages without time are compatible; newly authored policy is opt-in.
    if 'time' not in world: return None
    rules=policy(world['time'],world.get('world_gameplay',[]))
    clock={'date':rules['start']['date'],'minute':rules['start']['minute'],'day':1}
    return {'time_policy':rules,'calendar':clock,'time_runtime':{'elapsed_minutes':0,'module_state':{}}}


def public(engine):
    rules=engine.get('time_policy');clock=engine['calendar'];minute=clock.get('minute')
    label=clock.get('date')
    if not label:
        origin=(rules or {}).get('start',{}).get('label','')
        label=(origin+' · ' if origin else '')+('第 '+str(clock.get('day',1))+' 天' if minute is not None else '故事时间未设定')
    weekday=dt.date.fromisoformat(clock['date']).weekday() if clock.get('date') else None
    period=('night' if minute is None or minute<300 or minute>=1140 else 'morning' if minute<660 else 'noon' if minute<780 else 'afternoon' if minute<1020 else 'dusk')
    return {'clock':label+(' · %02d:%02d'%(minute//60,minute%60) if minute is not None else ''),
            'time':{'locked':bool(rules),'era':(rules or {}).get('era',{}).get('label',''),
                    'origin_label':(rules or {}).get('start',{}).get('label',''),
                    'weekday':weekday,'period':period,
                    'date_precision':'day' if clock.get('date') else 'relative',
                    'can_set_clock':not bool(rules)}}


def add(clock, minutes):
    if clock.get('minute') is None:
        if minutes: raise ValueError('旧存档的故事时间未设定，请先设置时间。')
        return
    days,minute=divmod(clock['minute']+minutes,1440)
    newdate=(dt.date.fromisoformat(clock['date'])+dt.timedelta(days=days)).isoformat() if clock.get('date') else None
    clock.update(day=clock.get('day',1)+days,minute=minute,date=newdate)


def initialize(engine,store):
    rules=engine.get('time_policy',{})
    if not rules.get('module_ref'):return
    result=store.call(rules['module_ref'],'time_initialize',{},
                      {'calendar':copy.deepcopy(engine['calendar']),'time_policy':rules,'modules':{}})
    if result.get('effects') or result.get('target_date') is not None:raise ValueError('时间初始化不能产生世界效果或改写起始日期。')
    engine['time_runtime']['module_state']=result['state']


def advance(engine,effect,store=None):
    rules=engine.get('time_policy')
    if not rules:
        minutes=integer(effect.get('minutes'),0,10080,'经过时间')
        clock=copy.deepcopy(engine['calendar'])
        if 'date' in effect: clock['date']=date(effect['date'])
        if effect.get('minute') is not None: clock['minute']=integer(effect['minute'],0,1439,'时间')
        add(clock,minutes);engine['calendar']=clock;return minutes
    if 'date' in effect or 'minute' in effect: raise ValueError('剧本时间已固定，不能直接改写日期或时刻。')
    minutes=integer(effect.get('minutes'),0,rules['max_turn_minutes'],'经过时间')
    runtime=copy.deepcopy(engine.get('time_runtime',{'elapsed_minutes':0,'module_state':{}}))
    clock=copy.deepcopy(engine['calendar'])
    target=None
    if rules.get('module_ref'):
        if store is None: raise ValueError('自定义时间模块需要壳提供的受限运行接口。')
        result=store.call(rules['module_ref'],'time_advance',runtime['module_state'],
                          {'calendar':clock,'time_policy':rules,'modules':{}},
                          {'minutes':minutes,'reason':effect.get('reason',''),
                           'parts':copy.deepcopy(effect.get('parts',[])),
                           'scene':effect.get('scene','')})
        if result.get('rejected'):raise ValueError(str(result['rejected'])[:300])
        if result.get('effects'): raise ValueError('时间模块应返回耗时，不能递归发送世界效果。')
        minutes=integer(result.get('elapsed_minutes'),0,rules['max_turn_minutes'],'时间模块耗时')
        runtime['module_state']=result['state']
        target=result.get('target_date')
        if target is not None:
            if not rules['allow_time_travel']: raise ValueError('剧本没有开放时间穿越。')
            target=date(target)
    add(clock,minutes)
    if target is not None: clock['date']=target
    runtime['elapsed_minutes']+=minutes
    engine['calendar']=clock;engine['time_runtime']=runtime
    return minutes


def duration(engine,parts):
    """Player-visible acts determine costs; a model's elapsed_minutes is only legacy input."""
    rules=engine.get('time_policy')
    if not rules: return None
    costs=rules['durations'];values=[]
    for part in parts:
        kind=part['kind'];text=part['text']
        if kind=='thought': values.append(costs['thought']);continue
        # Environment assertions cannot change time. Use an explicit player action.
        if kind=='environment': values.append(costs['environment']);continue
        explicit=[]
        if kind=='action':
            for number,unit in re.findall(r'(?<!\d)(\d{1,6})\s*(分钟|小时|天)',text):
                explicit.append(int(number)*{'分钟':1,'小时':60,'天':1440}[unit])
            for word,unit in re.findall(r'(?<![第一两二三四五六七八九十百千万])([一两二三四五六七八九十]{1,3}|半)\s*(分钟|小时|天)',text):
                digits={'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'半':.5}
                if '十' in word:
                    tens,ones=word.split('十');n=digits.get(tens,1)*10+digits.get(ones,0)
                else:n=digits.get(word)
                if n is None:raise ValueError('请用阿拉伯数字明确行动耗时。')
                explicit.append(int(n*{'分钟':1,'小时':60,'天':1440}[unit]))
            if re.search(r'睡.*(?:明天|次日|第二天)|(?:等待|休息).*到(?:明天|次日|第二天)',text):
                explicit.append(1440-engine['calendar']['minute']+420)
            if explicit: values.append(sum(explicit));continue
            if re.search(r'前往|走到|走向|回到|离开|赶往|出发|返回',text): values.append(costs['travel']);continue
        values.append(costs[kind])
    # Mixed prefixes describe one concurrent turn, not an extra fee per prefix.
    value=max(values,default=0)
    return integer(value,0,rules['max_turn_minutes'],'本轮行动耗时')


def validate_temporal(card):
    temporal=card.get('temporal',{})
    if not isinstance(temporal,dict) or set(temporal)-{'available_from','available_until','available_day','aliases'}: raise ValueError('temporal 字段不正确。')
    for key in ('available_from','available_until'):date(temporal.get(key))
    if temporal.get('available_day') is not None:integer(temporal['available_day'],1,100000,'出现日')
    aliases=temporal.get('aliases',[])
    if not isinstance(aliases,list) or len(aliases)>30 or any(not isinstance(a,str) or not a or len(a)>100 for a in aliases): raise ValueError('时间事实别名不正确。')
    origin=card.get('knowledge_origin')
    if origin is not None:
        if card.get('kind')!='character' or not isinstance(origin,dict) or set(origin)-{'date','reason'} or not origin.get('date') or not isinstance(origin.get('reason'),str) or not origin['reason'].strip():raise ValueError('穿越人物需要来源日期与原因。')
        date(origin['date'])


def horizon(engine,origin=None):
    if origin: return date(origin['date'])
    values=[d for d in (engine['calendar'].get('date'),engine.get('time_policy',{}).get('era',{}).get('knowledge_cutoff')) if d]
    return min(values) if values else None


def available(card,engine,origin=None):
    temporal=card.get('temporal',{});limit=horizon(engine,origin)
    if temporal.get('available_day',1)>engine['calendar'].get('day',1): return False
    if temporal.get('available_from') and (limit is None or temporal['available_from']>limit): return False
    # 'until' controls existence in the scene, rather than erasing historical knowledge.
    return True


def context(engine,world,actors):
    cards=[c for s in world.get('setting_sets',[]) for c in s['cards']]
    origins={a:next((c.get('knowledge_origin') for c in cards if c.get('card_id',c['id'])==a or c['name']==actor['name']),None) for a,actor in actors.items()}
    eligible={a:[c['id'] for c in cards if c.get('temporal') and available(c,engine,origin)] for a,origin in origins.items()}
    used={iid for values in eligible.values() for iid in values};facts={};budget=16000
    for card in cards:
        if card['id'] not in used:continue
        value={k:copy.deepcopy(card[k]) for k in ('name','kind','temporal') if k in card}
        value['description']=card.get('description','')[:2000]
        size=len(str(value))
        if size>budget:continue
        facts[card['id']]=value;budget-=size
    return {'clock':public(engine)['clock'],'calendar':copy.deepcopy(engine['calendar']),
            'period':public(engine)['time']['period'],
            'era':copy.deepcopy(engine.get('time_policy',{}).get('era',{})),
            'action_costs':engine.get('time_policy',{}).get('durations'),
            'actor_horizons':{a:horizon(engine,origin) for a,origin in origins.items()},
            'dated_facts':facts,
            'actor_dated_knowledge':eligible,
            'rules':'故事时钟由程序按已确认行动结算。不得自行改日期、宣布跨日或替玩家完成等待。普通人物只使用本人的时间知识范围；明确登记的穿越来源仅对该人物有效。未来资料不能由旁白、其他人心声或玩家内心泄露。'}


def validate_reply(reply,engine,world,actors):
    if not engine.get('time_policy'): return
    cards=[c for s in world.get('setting_sets',[]) for c in s['cards']]
    extra=[{'kind':'narration','text':reply.get(k,'')} for k in ('scene','summary')]
    # Summaries/remembered facts must not smuggle unregistered future knowledge back in.
    extra += [{'kind':'narration','text':m} for m in reply.get('memories',[]) if isinstance(m,str)]
    extra += [{'kind':'narration','text':f.get('value','')} for f in reply.get('facts',[]) if isinstance(f,dict) and isinstance(f.get('value'),str)]
    for frame in reply.get('frames',[])+extra:
        actor=actors.get(frame.get('actor_id')) or next((a for a in actors.values() if a['name']==frame.get('speaker')),None)
        origin=next((c.get('knowledge_origin') for c in cards if actor and c['name']==actor['name']),None) if frame.get('kind')!='narration' else None
        if engine.get('time_policy'):
            # Calendar claims, not ordinary plans for future appointments.
            for y,m,d in re.findall(r'(?:今天|当前|此刻|此时|现在|日期是)[^。！？\n]{0,12}?([12]\d{3})[-年](\d{1,2})[-月](\d{1,2})(?:日)?',frame.get('text','')):
                claimed=date('%04d-%02d-%02d'%(int(y),int(m),int(d)))
                if claimed!=engine['calendar'].get('date'):raise ValueError('回应改写了当前日期，请使用程序给出的故事时间；日期未设定时不能虚构具体年月日。')
        for card in cards:
            if available(card,engine,origin):continue
            terms=[card['name'],*card.get('temporal',{}).get('aliases',[])]
            if any(term in frame.get('text','') for term in terms):raise ValueError('回应提及尚未可知的时间事实：'+card['id']+'。请在当前时代范围内重写。')
        if actor:
            own=next((c for c in cards if c['name']==actor['name']),None)
            if own:
                stamp=engine['calendar'].get('date')
                until=own.get('temporal',{}).get('available_until')
                if not available(own,engine) or until and stamp and stamp>until:raise ValueError('该人物在当前故事时间不能出场。')
