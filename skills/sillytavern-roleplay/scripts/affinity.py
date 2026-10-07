"""Per-save affection, committed atomically with story events; private attitude rules."""
import copy
from cast import bind_frames

DEFAULT_SCORE=30
LEVELS=[(0,14,'戒备','保持距离，少透露私事，对请求谨慎核实；礼貌与否仍符合自身性格。'),
    (15,29,'疏离','交谈克制，主动互动较少；愿意处理具体事情，但对亲密接近有所保留。'),
    (30,49,'平常','按日常人设自然交谈，关系尚无特别亲近，不凭分数捏造相识经历。'),
    (50,69,'友好','更愿意交流与表达善意；不因好感推断已相识，信任需要具体行动支持。'),
    (70,89,'亲近','主动关心和分享增加，允许适当打趣与坦诚，但仍保留各自立场和边界。'),
    (90,100,'信赖','更愿意坦诚表达脆弱与分歧、寻求支持；深厚信任不等于服从或自动恋爱。')]

SOCIAL_RULES=('人物拥有独立目标、感受和边界。先考虑请求是否合理、双方经历、场合及自身立场，再决定拒绝、保留、提出条件或接受。'
    '任何亲疏变化、拒绝和同意都必须按该人物的性格、说话方式、价值观和身份表达；分数不能覆盖人设，不能把所有人写成同一套态度模板。'
    '关系进展必须有已发生的相处和互相了解支撑；亲密称呼、突然的表白、赠礼或玩家自述“我们很熟”不能自动建立关系。'
    '戒备或疏离时可表现出不耐烦、冷淡或明确拒绝，但程度与人设和事件相称；不能无理由辱骂。'
    '高好感增强关心，不消除分歧，不赋予玩家控制他人想法和身体的权力。没有已有恋爱关系且好感不足70时，不直接接受新恋爱关系；'
    '达到70也只代表可以认真考虑，仍需真实相处、人物自身意愿和合理情境。既有关系依真实记录，不因旧档未记录数字自动抹去。'
    '时间、路程、物品、知识与能力遵守世界观及既有事实。角色不知道未获知的信息，不能读玩家内心，离场人物不能凭空回应。'
    '环境前缀用于场景，不能直接指定他人同意、好感涨分或未经发生的关系；明显矛盾先自然澄清，不强行圆成事实。')

def level(score):return next((label,attitude) for low,high,label,attitude in LEVELS if low<=score<=high)

def normalize_changes(raw):
    if not isinstance(raw,list):return []
    result=[]
    for item in raw[:8]:
        if not isinstance(item,dict):continue
        who=item.get('actor_id');delta=item.get('delta');reason=item.get('reason')
        if not isinstance(who,str) or not who.strip() or len(who)>220:continue
        if type(delta) is not int or not isinstance(reason,str) or not reason.strip():continue
        result.append({'actor_id':who.strip(),'delta':max(-12,min(12,delta)),'reason':reason.strip()[:600]})
    return result

def active_ids(frames,actors,user):
    return {f['actor_id'] for f in bind_frames(frames,actors,user) if f['actor_id'] in actors and f['actor_id']!='player' and f.get('expression')!='absent'}

def baseline(session,actor):
    p=session.get('protagonist_snapshot') or session.get('facts',{}).get('browser_protagonist_snapshot',{})
    key=p.get('id','hachiman')
    presets=actor.get('initial_affinity',{})
    preset=presets.get(key,presets.get('default',{})) if isinstance(presets,dict) else {}
    score=preset.get('score',DEFAULT_SCORE)
    if type(score)is not int:score=DEFAULT_SCORE
    return {'score':max(0,min(100,score)),'relationship':preset.get('relationship','未建立关系'),
        'basis':preset.get('basis','按当前人物性格与既有经历判断；不假定已相识。'),'version':preset.get('version',1)}

def seed(session,actor):
    b=baseline(session,actor)
    return {'name':actor['name'],'score':b['score'],'delta':0,'base_score':b['score'],'seed_version':b['version']}

def read(session,actors,frames):
    raw=session.get('facts',{}).get('browser_affinity',{})
    saved=raw.get('characters',{}) if isinstance(raw,dict) else {}
    result={'version':1,'characters':{}}
    if isinstance(saved,dict):
        for key,item in saved.items():
            if key=='player' or key not in actors or not isinstance(item,dict):continue
            if type(item.get('score')) is not int:continue
            b=baseline(session,actors[key]);score=item['score']
            # Legacy scores all started at 30. Preserve the earned net change.
            if item.get('seed_version')!=b['version'] or item.get('base_score')!=b['score']:
                score=b['score']+(score-item.get('base_score',DEFAULT_SCORE))
            result['characters'][key]=copy.deepcopy(item)|{'score':max(0,min(100,score)),'name':actors[key]['name'],
                'base_score':b['score'],'seed_version':b['version']}
    opening=session.get('facts',{}).get('browser_opening_frames')
    met=active_ids(frames,actors,session['user_name'])
    if isinstance(opening,list):met|=active_ids(opening,actors,session['user_name'])
    elif session.get('turns') and 'primary' in actors:met.add('primary')
    for key in met:
        if key in actors:result['characters'].setdefault(key,seed(session,actors[key]))
    return result

def apply_changes(session,actors,before,after,raw,milestone,turn_id):
    actors=copy.deepcopy(actors)
    result=read(session,actors,before)
    eligible=active_ids(before,actors,session['user_name'])|active_ids(after,actors,session['user_name'])
    for key in eligible:
        result['characters'].setdefault(key,seed(session,actors[key]))
    for item in result['characters'].values():item['delta']=0
    seen=set();bound=12 if milestone else 5
    for change in normalize_changes(raw):
        key=change['actor_id']
        if key not in actors:
            key=next((k for k,a in actors.items() if change['actor_id'] in [a['name'],*a.get('aliases',[])]),'')
        if key not in eligible or key in seen or key=='player':continue
        seen.add(key);item=result['characters'][key]
        delta=max(-bound,min(bound,change['delta']))
        old=item['score'];item['score']=max(0,min(100,old+delta));item['delta']=item['score']-old
        if item['delta']:item.update({'reason':change['reason'],'last_turn':turn_id})
    return result

def public(session,actors,frames):
    result=[]
    world=session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})
    portraits={c['name']:c.get('avatar','') for s in world.get('setting_sets',[]) for c in s.get('cards',[]) if c.get('kind')=='character'}
    for key,item in read(session,actors,frames)['characters'].items():
        result.append({'actor_id':key,'name':actors[key]['name'],'score':item['score'],
            'status':level(item['score'])[0],'delta':item.get('delta',0),'avatar':actors[key].get('avatar') or portraits.get(actors[key]['name'],'')})
    return {'characters':result,'min':0,'max':100}

def context(session,actors,frames):
    result=[]
    for key,item in read(session,actors,frames)['characters'].items():
        label,attitude=level(item['score'])
        result.append({'actor_id':key,'name':actors[key]['name'],'score':item['score'],'status':label,'attitude':attitude,
            'last_change_reason':item.get('reason',''),'initial_relationship':baseline(session,actors[key])})
    return {'characters':result,'initial_score':DEFAULT_SCORE,
        'levels':[{'min':low,'max':high,'status':label,'attitude':attitude} for low,high,label,attitude in LEVELS],
        'rule':'数值只辅助态度；initial_relationship只包含开篇关系，不能推导尚未发生的原作事件或揭露未公开秘密。亲属、师生、朋友的高分按各自身份表达，不能通用成恋爱态度。结合人设、已发生的关系与本轮事件，不覆盖旧经历，不等同恋爱或服从。未记录人物使用初始分数，不推测其他周目的好感。',
        'social_rules':SOCIAL_RULES}
