"""Versioned branch-local shared capabilities. All updates are pure until commit."""
import copy
import datetime
import hashlib
import json
import re
import story_time

def bounded(value,lo,hi,label):
    if type(value) is not int or not lo<=value<=hi:raise ValueError(label+'超出范围。')
    return value

def short(value,limit=1000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('状态文本不正确或过长。')
    return value

def seed(world,actors=None,legacy=False):
    calendar=copy.deepcopy(world.get('calendar',{})) if not legacy else {}
    if calendar.get('date'):datetime.date.fromisoformat(calendar['date'])
    minute=calendar.get('minute',None if legacy else 960)
    if minute is not None:bounded(minute,0,1439,'起始时间')
    result={'version':1,'calendar':{'date':calendar.get('date'),'day':1,'minute':minute},
            'relations':{},'items':copy.deepcopy(world.get('initial_items',{})) if not legacy else {},
            'threads':{},'modules':{},'plot':{'phase':'开场' if not legacy else '沿用已有剧情','beat':'setup','focus':''},'applied_turns':[]}
    if not legacy:
        timed=story_time.seed(world)
        if timed:result.update(timed)
    return result

def current(session):
    state=copy.deepcopy(session.get('facts',{}).get('browser_engine') or seed({},legacy=True))
    state.setdefault('plot',{'phase':'沿用已有剧情','beat':'development','focus':''})
    return state

def public(engine):
    clock=engine['calendar']
    return {**story_time.public(engine),'calendar':copy.deepcopy(clock),'plot':copy.deepcopy(engine['plot']),'items':list(engine['items'].values()),
            'threads':list(engine['threads'].values()),'relations':[
                {'actor_id':aid,'trust':r.get('trust'),'familiarity':r.get('familiarity'),
                 'identity':r.get('identity','尚未形成明确关系')} for aid,r in engine['relations'].items()]}

def apply_effect(engine,effect,actors,interacted=None,milestone=False,time_store=None):
    """Host capabilities never execute file operations or arbitrary state patches."""
    kind=effect.get('type');reason=short(effect.get('reason',''))
    if not reason.strip():raise ValueError('状态变化需要实际事件依据。')
    if kind=='time':
        story_time.advance(engine,effect,time_store)
    elif kind=='items':
        iid=short(effect.get('id',''),80);owner=short(effect.get('owner',''),100)
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',iid) or not owner:raise ValueError('物品需要稳定 ID 与持有者。')
        delta=bounded(effect.get('delta'),-999,999,'物品数量');item=engine['items'].get(iid)
        if item and item['owner']!=owner:raise ValueError('物品持有者不匹配，不能直接拿走他人物品。')
        quantity=(item or {}).get('quantity',0)+delta
        if quantity<0:raise ValueError('没有足够物品，不能扣除。')
        if not item and delta<=0:raise ValueError('物品尚不存在。')
        engine['items'][iid]={'id':iid,'name':short(effect.get('name') or (item or {}).get('name',''),100),
            'owner':owner,'quantity':quantity,'location':short(effect.get('location',''),200),'note':reason}
    elif kind=='relations':
        aid=effect.get('actor_id')
        if aid not in actors or (interacted is not None and aid not in interacted):raise ValueError('只能更新实际互动人物的关系。')
        baseline=actors[aid].get('relation_baseline',{})
        relation=engine['relations'].setdefault(aid,{'trust':baseline.get('trust'),'familiarity':baseline.get('familiarity'), 'identity':baseline.get('identity',''),'reason':''})
        relation.setdefault('familiarity_basis','initial-relation-v2')
        for field in ('trust','familiarity'):
            limit=6 if milestone else 3
            delta=bounded(effect.get(field,0),-limit,limit,f'world_updates.relations.{field} 本轮增减量（整数 -{limit} 至 {limit}，不是0–100总分）')
            # Unknown old relations are explicitly anchored at neutral, not derived from affection.
            if delta:
                base=relation[field] if relation[field] is not None else baseline.get(field,0 if field=='familiarity' else 30)
                relation[field]=max(0,min(100,base+delta))
        identity=short(effect.get('identity',''),100)
        if identity:
            if any(word in identity for word in ('恋人','情侣','夫妻','未婚')) and effect.get('mutual_consent') is not True:
                raise ValueError('亲密关系必须由明确的双方共识建立，不能由关系更新直接指定。')
            relation['identity']=identity
        relation['reason']=reason
    elif kind=='threads':
        iid=short(effect.get('id',''),80)
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',iid):raise ValueError('事件 ID 不正确。')
        status=effect.get('status')
        if status not in {'open','active','resolved','cancelled'}:raise ValueError('事件状态不正确。')
        old=engine['threads'].get(iid,{})
        if not old and status in {'resolved','cancelled'}:raise ValueError('尚未建立的事件不能直接结束。')
        engine['threads'][iid]={'id':iid,'title':short(effect.get('title') or old.get('title',''),200),
            'status':status,'note':short(effect.get('note',''),1000),'reason':reason,
            'deadline':short(effect.get('deadline',''),100)}
    else:raise ValueError('未知世界状态能力。')

def module_context(engine,scene,actors,turn_id):
    return {'calendar':copy.deepcopy(engine['calendar']),'items':copy.deepcopy(engine['items']),
        'relations':copy.deepcopy(engine['relations']),'threads':copy.deepcopy(engine['threads']),
        'scene':scene,'actors':[{'id':k,'name':v.get('name',k)} for k,v in actors.items()],
        'modules':{k:copy.deepcopy(v['state']) for k,v in engine['modules'].items()},
        'turn_id':turn_id,'roll':int(hashlib.sha256(turn_id.encode()).hexdigest()[:8],16)%100+1}

def proposal_schema():
    s={'type':'string'}
    def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
    def arr(p,n=8):return {'type':'array','maxItems':n,'items':obj(p)}
    result=obj({'elapsed_minutes':{'type':'integer','minimum':0,'maximum':1440},'time_reason':s,
        'relations':arr({'actor_id':s,'trust':{'type':'integer','minimum':-6,'maximum':6,'description':'本轮信任增减量，不是总分。普通回合整数-3至3；story.milestone=true时最多-6至6；不变填0。'},
            'familiarity':{'type':'integer','minimum':-6,'maximum':6,'description':'本轮熟悉增减量，不是总分。普通回合整数-3至3；story.milestone=true时最多-6至6；不变填0。'},'identity':s,'reason':s}),
        'items':arr({'id':s,'name':s,'owner':s,'delta':{'type':'integer','minimum':-999,'maximum':999},'location':s,'reason':s}),
        'threads':arr({'id':s,'title':s,'status':{'type':'string','enum':['open','active','resolved','cancelled']},'note':s,'deadline':s,'reason':s}),
        'module_events':arr({'module_id':s,'action_id':s,'evidence':s},4)})
    result['properties']['phase']=s
    return result

PHASE_RULE='world_updates.phase 是可选的简短剧情阶段名称，仅在真实进入新阶段时填写；普通问答不强制换阶段，未完事件可并行，不预设结局。'

RULES='''世界状态规则：story_state 是当前存档已确认的时间、关系、物品和未完事件，不将预测素材或未选建议作为事实。world_updates 只记录本轮确已发生的变化；没有变化使用0和空数组。elapsed_minutes依据真实行动和距离估计，内心/一句台词可以0，休息或跨日可较长，未设定旧存档时间时用0。world_updates.relations中的trust和familiarity必须填写本轮整数增减量，不能填写story_state.relations中0–100的当前总分；无变化用relations=[]。普通回合story.milestone=false时范围-3至3，真实转折story.milestone=true时范围-6至6。关系变化按每个人自身性格与真实互动，信任、熟悉、好感并非同一件事；默认±1至3，真实转折最多±6；称呼变化不自动成为恋人。物品的负数为消耗，持有者必须一致；转移先扣原ID数量，再新增接收者独立ID，不能凭空发奖励。事件/承诺以稳定ID记录实际进展和期限，不强迫高潮或结局。gameplay 显示剧本定义的动作和规则；玩家选中的玩法结果已由规则结算，应如实描写，不能改写成不同结果。module_events仅用于本轮明确实施、且在对应玩法允许列表内的动作；evidence必须复制本轮输入或可观察对白/旁白中的真实依据，不能把猜测、推荐选项或人物心声当成事件。schedule_tendencies仅是习惯倾向，可以依剧情变化，不是必须出现的时间表；不能无理由瞬移人物。'''
