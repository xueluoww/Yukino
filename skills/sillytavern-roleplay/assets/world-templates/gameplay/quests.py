"""Script-owned service-club commission rules. The engine has no quest-specific code."""
def run(r):
    mode=r['mode']; state=r['state']; config=r['config']; effects=[]; outcome=''
    if mode=='initialize':
        state={'tasks':{q['id']:{'status':'available','notes':[]} for q in config.get('tasks',[])}}
    if mode=='event':
        event=r['event']; parts=event.get('action_id','').split('-'); verb=parts[0]; iid='-'.join(parts[1:])
        task=state.get('tasks',{}).get(iid)
        setting=None
        for q in config.get('tasks',[]):
            if q['id']==iid:setting=q
        if not task or not setting:return {'state':state,'effects':[],'rejected':'这项委托尚未开放。'}
        if verb=='accept' and task['status']=='available':
            task['status']='active';outcome='接下了“'+setting['title']+'”。'
            effects.append({'type':'threads','id':'quest-'+iid,'title':setting['title'],'status':'active','note':setting['description'],'deadline':'','reason':outcome})
        elif verb=='record' and task['status']=='active':
            frames=event.get('frames',[])
            evidence=[]
            for frame in frames:
                if frame.get('kind')=='dialogue' and frame.get('text'):evidence.append(frame['speaker']+'：'+frame['text'])
            if not evidence:return {'state':state,'effects':[],'rejected':'还没有可以记录的实际交谈内容，请先询问相关人物。'}
            note=' / '.join(evidence)[:1200]
            if note not in task['notes']:task['notes'].append(note)
            task['notes']=task['notes'][-10:];outcome='记下了本轮交谈中的委托信息。'
        elif verb=='submit' and task['status']=='active':
            if len(task['notes'])<setting.get('required_notes',2):return {'state':state,'effects':[],'rejected':'记录还不完整，先向相关人物了解情况。'}
            task['status']='reported';outcome='整理并提交了已有记录，等待委托人确认；尚未自动判定解决。'
            effects.append({'type':'threads','id':'quest-'+iid,'title':setting['title'],'status':'active','note':outcome,'deadline':'','reason':outcome})
        elif verb=='confirm' and task['status']=='reported':
            confirmed=False
            names=setting.get('reviewers',[])
            for frame in event.get('frames',[]):
                if frame.get('kind')=='dialogue' and frame.get('speaker') in names and any(w in frame.get('text','') for w in ('确认完成','委托完成','这件事解决了','辛苦了，已经可以了')):confirmed=True
            if not confirmed:return {'state':state,'effects':[],'rejected':'需要委托人明确确认结果。'}
            task['status']='completed';outcome='委托人确认了这项委托的结果。'
            effects.append({'type':'threads','id':'quest-'+iid,'title':setting['title'],'status':'resolved','note':outcome,'deadline':'','reason':outcome})
        elif verb=='cancel' and task['status'] in ['active','reported']:
            task['status']='cancelled';outcome='决定不再继续这项委托。'
            effects.append({'type':'threads','id':'quest-'+iid,'title':setting['title'],'status':'cancelled','note':outcome,'deadline':'','reason':outcome})
        else:return {'state':state,'effects':[],'rejected':'当前进度不能执行这个动作。'}
    cards=[];actions=[];natural=[]
    labels={'available':'尚未接取','active':'进行中','reported':'等待确认','completed':'已完成','cancelled':'已放下'}
    for q in config.get('tasks',[]):
        task=state['tasks'][q['id']];iid=q['id'];status=task['status']
        cards.append({'title':q['title'],'text':q['description'],'status':labels[status],'details':task['notes']})
        if status=='available':actions.append({'id':'accept-'+iid,'label':'接下委托','text':'【动作】在委托记录中接下“'+q['title']+'”，准备向相关人物了解情况。'})
        if status=='active':
            # Recording requires same-turn real NPC dialogue; text engine may propose it after conversation.
            natural.append({'id':'record-'+iid,'label':'记录实际交谈','text':'【动作】把刚刚了解到的委托信息记入笔记。'})
            if len(task['notes'])>=q.get('required_notes',2):actions.append({'id':'submit-'+iid,'label':'整理并提交记录','text':'【动作】整理“'+q['title']+'”的已有记录，交给委托人确认。'})
        if status=='reported':natural.append({'id':'confirm-'+iid,'label':'确认委托结果','text':'【语言】这份结果是否已经解决了你的委托？'})
        if status in ['active','reported']:actions.append({'id':'cancel-'+iid,'label':'放下委托','text':'【动作】决定不再继续“'+q['title']+'”，并向委托人说明。'})
    return {'state':state,'effects':effects,'outcome':outcome,
        'view':{'cards':cards,'actions':actions},
        'context':{'rules':'委托进展基于实际交谈和行动，不自动发好感。接取仅代表准备开展；资料记录至少来自两次真实交谈，提交后由委托人确认。record仅记录当前同场NPC的实际对白；confirm仅在委托人明确认可结果时成立。未接受的委托只是可选背景，不能强制发生。',
                   'progress':state,'natural_actions':natural}}
