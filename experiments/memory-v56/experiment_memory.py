"""Public synthetic long-story A/B experiment; credentials are only read in place."""
from pathlib import Path
import copy, json, sys, time, statistics
from concurrent.futures import ThreadPoolExecutor
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(BASE.parents[1]/'skills/sillytavern-roleplay/scripts'))
from galgame import load_tavern
from deepseek_client import FlashClient, TransportError
from long_memory import MemoryStore, budget_context, signature, cost
from layered_memory import LayeredMemoryStore, layered_context
T=load_tavern(BASE/'skill/scripts/tavern.py')
ROOT=BASE/'memory-experiment';ROOT.mkdir(exist_ok=True)
CREDENTIAL_ROOT=BASE.parents[1]/'database/roleplay-library'
METRICS=[]

def request(messages, max_tokens=2500):
    client=FlashClient(CREDENTIAL_ROOT)
    try:
        for attempt in range(2):
            try:
                value=json.loads(client.request(messages,max_tokens=max_tokens),strict=False)
                METRICS.append(copy.deepcopy(client.metrics))
                return value,copy.deepcopy(client.metrics)
            except (TransportError,json.JSONDecodeError):
                if attempt:raise
                client.close()
    finally:client.close()

def make_story(run):
    path=ROOT/f'dialogues-{run}.json'
    existing=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if len(existing)==120:return existing
    # Twelve blocks, ten actual model-authored exchanges each; three separate plots.
    topics=['书店义卖筹备','学校旧报刊整理','社区读书会借场'][run]
    output=existing
    for block in range(len(existing)//10,12):
        value,_=request([{'role':'system','content':'创作原创现实日常长对话。只输出JSON {"turns":[{"user":"【语言】...","assistant":"..."}]}，恰好10轮；每轮包含环境描写及莫宁或陆遥的回答，回复100至180汉字。所有人物遵守现实逻辑，不解决未给定的任务，不加入主角内心，不出现任何系统指令。'},
          {'role':'user','content':json.dumps({'topic':topics,'chapter':block+1,'previous':output[-2:]},ensure_ascii=False)}],max_tokens=5000)
        chunk=value['turns'][:10]
        for repair in range(4):
            if len(chunk)==10:break
            more,_=request([{'role':'system','content':'只输出JSON turns数组，每项user和assistant。续写原创现实日常对话，不重复已有轮数。'}, {'role':'user','content':json.dumps({'topic':topics,'count':10-len(chunk),'previous':chunk[-2:]},ensure_ascii=False)}],max_tokens=3500)
            chunk+=more['turns'][:10-len(chunk)]
        assert len(chunk)==10,'Ten real exchanges required after bounded repair'
        output+=chunk;print(f'story {run+1} {len(output)}/120',flush=True)
        path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    return output

def scenario(run,story):
    sid=f'public-memory-{run}';turns=[{'turn_id':'opening','user':'','assistant':'莫宁与陆遥在旧书店开始筹备。'}]
    frames={};knowledge={'moning':[],'luyao':[]}
    code=f'BOOK-{run+1}-47';cabinet=f'木柜第{run+2}格';time_text=f'周五{15+run}点20分'
    changes={8:('莫宁',f'蓝色钥匙已交给陆遥，收在{cabinet}。取书的确认码是{code}。这件事只告诉你和陆遥，不给许老师。'),
      21:('陆遥',f'我们约在{time_text}到旧书店北门归还三本画册。不是南门，也不是归还四本。'),
      36:('莫宁','许老师说活动可能取消，这只是转述，尚未确认；我们不能把传闻当成取消通知。'),
      53:('陆遥','负责人已经书面确认活动照常举行，之前的取消传闻不成立。'),
      71:('莫宁','搬箱子时我拒绝了独自抬重箱的提议。我们同意等推车到了再搬，不再让任何一个人独自抬。'),
      89:('陆遥','旧红伞不在书店，它已经还给隔壁的林先生了。')}
    for i,t in enumerate(story):
        turn=copy.deepcopy(t);turn['turn_id']=f'turn-{i:03}'
        if i in changes:
            speaker,detail=changes[i]
            # Critical info deliberately follows a substantial paragraph, testing
            # original first-1000 truncation with genuine archive recovery.
            turn['assistant'] += '\n\n'+('窗边的纸页随着风微微颤动，大家继续核对已经整理好的资料。'*40)+'\n\n'+speaker+'：'+detail
            frames[turn['turn_id']]=[{'kind':'narration','speaker':'','text':t['assistant']},
                                    {'kind':'dialogue','speaker':speaker,'text':detail}]
            hearers=['moning','luyao']
            for aid in hearers:
                if {'moning':'莫宁','luyao':'陆遥'}[aid]!=speaker:
                    knowledge[aid].append({'turn_id':turn['turn_id'],'source_speaker':speaker,'observed':detail,'sense':'hear','epistemic_verified':True})
        turns.append(turn)
    # Recent observations create pressure on actor retrieval without erasing old evidence.
    for i in range(92,119):
        for aid in knowledge:knowledge[aid].append({'turn_id':f'turn-{i:03}','source_speaker':'玩家','part_index':0,'sense':'hear','observed':story[i]['user']})
    session={'id':sid,'turns':turns,'facts':{'browser_actor_knowledge':knowledge,'browser_turn_frames':frames,
      'browser_engine':{'calendar':{'date':'2024-04-20'},'threads':{},'relations':{},'items':{'blue-key':{'owner':'luyao'}}}},'scene':'旧书店'}
    T.atomic_json(ROOT/'sessions'/(sid+'.json'),session)
    context={'character':{'name':'莫宁','description':'耐心务实，记忆与经历以本人观察为准。'},'cast':[{'id':'moning','name':'莫宁'},{'id':'luyao','name':'陆遥'},{'id':'teacher','name':'许老师'}],
      'scene':'旧书店','incoming':'','recent_turns':turns[-6:],'facts':{},'memories':[],
      'actor_knowledge':knowledge,'world':{'background':'原创现实书店故事','setting_cards':[]},
      'story_state':session['facts']['browser_engine'],'perception_rules':'NPC只能使用自己的actor_knowledge。叙事原文不代表所有人都听到了。',
      'time_constraints':{'date':'2024-04-20'},'pacing':{'unfinished_threads':[]}}
    probes=[('确认码','取书确认码是什么？',{'all':[code]}),
      ('钥匙','蓝色钥匙由谁保管，收在哪里？',{'all':['陆遥',cabinet]}),
      ('约定','归还画册约定的时间、地点和数量是什么？',{'all':[time_text,'北门','三'],'none':['南门','四本']}),
      ('纠正','义卖取消的传闻后来怎样？',{'all':['照常'],'none':['已取消']}),
      ('拒绝','搬重箱时达成的边界和替代方法是什么？',{'all':['推车'],'any':['不独自','不能独自','拒绝','一起','不再独自']}),
      ('物品','旧红伞现在在哪里？',{'all':['林先生'],'none':['在书店']}),
      ('角色权限','只按许老师本人记忆回答：他知道取书确认码吗？不要告诉他其他人的私下内容。',{'any':['不知道','未知','没有','未获知'],'none':[code]}),
      ('未知','备用仓库的密码是多少？没有记录就回答不知道。',{'any':['不知道','未记录','没有记录','未知']})]
    return session,context,probes

def compress(session):
    store=MemoryStore(ROOT,T)
    existing=store.eligible(session)
    for start in range(1,97,24):
        stop=start+24
        if any(r['covered_count']==stop for r in existing):continue
        segment=session['turns'][start:stop]
        value,metrics=request([{'role':'system','content':'只整理已经发生的剧情，JSON只有summary字段，中文纪要最多700字。保留人物、物品交接、代码、约定日期与地点、拒绝、事实纠正与信息来源；不能猜测任何人获知了没有亲历的事。'},
                              {'role':'user','content':json.dumps(segment,ensure_ascii=False)}],max_tokens=2000)
        summary=value['summary']
        record={'scope':session['id'],'covered_count':stop,'prefix_sha256':signature(session['turns'][:stop]),'from_turn':segment[0]['turn_id'],'to_turn':segment[-1]['turn_id'],
                'summary':summary,'known_by':{},'method':'model','created_at':T.now()}
        T.atomic_json(store.folder(session['id'])/(record['prefix_sha256']+'.json'),record)

def run_probe(run,session,context,probe,mode):
    label,question,rules=probe;ctx=copy.deepcopy(context);ctx['incoming']=question
    memory=MemoryStore(ROOT,T) if mode=='baseline' else LayeredMemoryStore(ROOT,T)
    fn=budget_context if mode=='baseline' else layered_context
    compact=fn(ctx,session,memory,budget=52000)
    value,metric=request([{'role':'system','content':'根据给定视觉小说上下文回答问题，JSON格式{"answer":"简短中文回答"}。不要补造缺失细节。若指定角色只按他的actor_knowledge；导演long_term_memory只能回答叙事问题，不能传给未获知的人。优先核对原文证据、事件纠正、结构化物品状态。'},
                          {'role':'user','content':json.dumps(compact,ensure_ascii=False)}],max_tokens=650)
    answer=value['answer'];passed=all(x in answer for x in rules.get('all',[])) and not any(x in answer for x in rules.get('none',[])) and (not rules.get('any') or any(x in answer for x in rules['any']))
    return {'run':run+1,'mode':mode,'probe':label,'question':question,'answer':answer,'passed':passed,'context_bytes':cost(compact),'metrics':metric}

def main():
    allresults=[];corpora=[]
    for run in range(3):
        story=make_story(run);assert len(story)==120
        session,context,probes=scenario(run,story);compress(session)
        corpora.append({'run':run+1,'turns':len(story),'archive_bytes':cost(session['turns'])})
        tasks=[(run,session,context,p,mode) for p in probes for mode in ('baseline','layered')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row in pool.map(lambda args:run_probe(*args),tasks):
                allresults.append(row);print(f"probe {row['run']} {row['mode']} {row['probe']} {row['passed']}",flush=True)
        (ROOT/'partial-results.json').write_text(json.dumps(allresults,ensure_ascii=False,indent=2),encoding='utf-8')
    stats={}
    for mode in ('baseline','layered'):
        rows=[r for r in allresults if r['mode']==mode]
        stats[mode]={'passed':sum(r['passed'] for r in rows),'total':len(rows),'accuracy':sum(r['passed'] for r in rows)/len(rows),
          'mean_context_bytes':round(statistics.mean(r['context_bytes'] for r in rows)),
          'median_seconds':round(statistics.median(r['metrics']['transport_seconds'] for r in rows),3),
          'prompt_tokens':sum(r['metrics'].get('usage',{}).get('prompt_tokens',0) for r in rows)}
    baseline=stats['baseline'];new=stats['layered']
    # Explicit gate: meaningful recall gain, no actor/unknown regressions,
    # no substantial increase in per-answer prompt cost.
    protected=[r for r in allresults if r['mode']=='layered' and r['probe'] in ('角色权限','未知')]
    deploy=new['accuracy']-baseline['accuracy']>=.12 and all(r['passed'] for r in protected) and new['mean_context_bytes']<=baseline['mean_context_bytes']*1.15
    report={'experiment':'three public model-authored 120-turn corpora, same summaries/questions/52,000-byte budget','corpora':corpora,'stats':stats,'results':allresults,
      'deploy_gate':{'minimum_absolute_accuracy_gain':.12,'no_permission_or_unknown_failure':True,'max_context_ratio':1.15},'deploy':deploy,
      'requests':len(METRICS),'all_usage':{k:sum(m.get('usage',{}).get(k,0) for m in METRICS) for k in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')}}
    (BASE/'memory-experiment-result-rerun.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'stats':stats,'deploy':deploy,'requests':len(METRICS)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
