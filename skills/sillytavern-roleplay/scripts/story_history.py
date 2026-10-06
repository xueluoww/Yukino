"""Read/export one branch's recorded story without replaying or altering it."""
import copy,json,re
from pathlib import Path
from branch_store import metadata

def same_prefix(snapshot,session,index):
    a=snapshot.get('turns',[]);b=session.get('turns',[])[:index+1]
    return len(a)==len(b) and all(all(x.get(k)==y.get(k) for k in ('turn_id','user','assistant')) for x,y in zip(a,b))

def history(root,session):
    result=[];facts=session.get('facts',{});stored=facts.get('browser_turn_frames',{})
    for index,t in enumerate(session.get('turns',[])):
        tid=t['turn_id'];frames=stored.get(tid)
        if tid=='opening':frames=facts.get('browser_opening_frames') or frames
        if not frames and index==len(session['turns'])-1:
            candidate=facts.get('browser_latest_frames',[])
            canonical='\n\n'.join('“'+f['text'].strip()+'”' if f['kind']=='dialogue' else '*'+f['text'].strip()+'*' for f in candidate if f.get('kind')!='thought' and f.get('text','').strip())
            if canonical==t['assistant']:frames=candidate
        if not frames and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',tid):
            # Fork creation copies only its own inherited checkpoints. No scan
            # of sibling saves; verify the full prefix even inside this folder.
            path=Path(root)/'browser/checkpoints'/session['id']/(tid+'.json')
            try:
                checkpoint=json.loads(path.read_text(encoding='utf-8-sig'))
                if checkpoint.get('id')==session['id'] and same_prefix(checkpoint,session,index):
                    frames=checkpoint.get('facts',{}).get('browser_latest_frames')
            except (OSError,ValueError):pass
        public=[copy.deepcopy(f) for f in (frames or []) if f.get('kind')!='thought']
        result.append({k:t.get(k,'') for k in ('turn_id','user','assistant','saved_at')}|
            {'frames':public,'structured':bool(public)})
    return result

def export(session,turns,scope='story',format='txt'):
    if scope not in {'story','plot','thoughts','all'} or format not in {'txt','md'}:raise ValueError('Invalid export scope/format')
    md=format=='md';lines=[]
    def heading(text,level=2):lines.extend([('#'*level+' ' if md else '')+text,''])
    heading(session.get('title') or '故事存档',1)
    lines.extend([f"剧本：{session.get('facts',{}).get('browser_world_snapshot',{}).get('name','角色卡剧本')}",
        f"存档：{session['id']} · {metadata(session)['label']}",f"玩家：{session['user_name']}",
        '按故事发生顺序导出；仅包含此存档已记录的内容。',''])
    if scope in {'story','all'}:
        heading('故事回看')
        for index,t in enumerate(turns):
            heading(('开场' if index==0 else f'第 {index} 回合')+((' · '+t['saved_at']) if t.get('saved_at') else ''),3)
            if t['user']:lines.extend([session['user_name']+'：',t['user'],''])
            if t['frames']:
                for f in t['frames']:
                    lines.extend([('旁白' if f['kind']=='narration' else f.get('speaker') or '未标注人物')+'：',f['text'],''])
            else:lines.extend(['历史文本（原记录未保存分镜署名）：',t['assistant'],''])
    if scope in {'plot','all'}:
        heading('剧情脉络')
        for i,n in enumerate(session.get('facts',{}).get('browser_story',{}).get('nodes',[])):
            heading(f"{i+1}. {n['title']}",3);lines.extend([n.get('story_time',''),n.get('scene',''),''])
        thread=session.get('facts',{}).get('browser_story',{}).get('thread')
        if thread:lines.extend(['当前线索：'+thread,''])
        state=session.get('facts',{}).get('browser_engine')
        if state:
            from story_engine import public,current
            world_state=public(current(session))
            lines.extend(['故事时间：'+world_state['clock'],'剧情阶段：'+world_state['plot']['phase'],''])
            for event in world_state['threads']:lines.extend([event['title']+' · '+event['status'],event['note'],''])
    if scope in {'thoughts','all'}:
        heading('人物心声（独立附录）')
        for e in session.get('facts',{}).get('browser_inner_thoughts',[]):
            lines.extend([e.get('name','')+' · '+e.get('scene',''),e['text'],''])
    return '\n'.join(lines).encode('utf-8-sig')

def waiting_ids(scene,parts,actors):
    """Conservative feedback, not a promise that any person will respond."""
    from perception import cues
    constraints=cues(parts,actors)
    if constraints['unaccompanied_departure'] or not parts:return []
    if any(p['kind']=='thought' or i in constraints['private_part_indexes'] for i,p in enumerate(parts)):return []
    # A director's setting and actions alone do not identify a reply addressee.
    if not any(p['kind']=='speech' for p in parts):return []
    candidates=list(dict.fromkeys(scene.get('present_actor_ids',[])+[c['actor_id'] for c in scene.get('contacts',[])]))
    if not candidates:return []
    text='\n'.join(p['text'] for p in parts if p['kind']=='speech')
    named=[k for k in candidates if any(n and re.search(r'(?:对(?:着)?|问|向|叫住|喊)\s*'+re.escape(n),text) for n in [actors.get(k,{}).get('name'),*actors.get(k,{}).get('aliases',[])])]
    return named or candidates

def cg_cue(session,visual,cache,tasks):
    turns=session.get('turns',[])
    if not turns:return {}
    tid=turns[-1]['turn_id'];node=next((n for n in reversed(session.get('facts',{}).get('browser_story',{}).get('nodes',[])) if n['id']==tid),{})
    key=node.get('cg_asset') if node else visual.get('cg_asset')
    if not key:return {}
    url=cache.get(key,{}).get('url','')
    return {'turn_id':tid,'key':key,'title':node.get('title','这一幕'),'url':url,
        'status':'ready' if url else tasks.get(key,{}).get('status','failed')}
