"""Glue for script modules, shared state, archival memory and save management."""
import base64
import copy
import json
import uuid
from gameplay import ModuleStore,digest
from long_memory import MemoryStore,budget_context
from save_manager import SaveManager
import story_engine as engine

class ModuleInputError(ValueError):
    retry_as_text=True

class EngineV5:
    def init_engine(self):
        self.modules=ModuleStore(self.root,self.tavern)
        self.memory=MemoryStore(self.root,self.tavern)
        self.saves=SaveManager(self.root,self.tavern)
        self._engine_pending={};self._module_view_key=None;self._module_views=[]
        from deepseek_client import FlashClient
        self.memory_client=FlashClient(self.root) if self.provider=='deepseek' else None
    def initialize_engine(self):
        world=self.world_snapshot();state=engine.seed(world)
        ctx=engine.module_context(state,self.current['scene'],self.actors(),'opening')
        for ref in world.get('world_gameplay',[]):
            ctx=engine.module_context(state,self.current['scene'],self.actors(),'opening')
            result=self.modules.call(ref,'initialize',{},ctx)
            state['modules'][ref['id']]={'version':ref['version'],'sha256':ref['sha256'],'state':result['state']}
            for effect in result.get('effects',[]):engine.apply_effect(state,effect,self.actors())
        for settings in world.get('setting_sets',[]):
            for card in settings['cards']:
                initial=card.get('initial_relation',{}).get(self.protagonist()['id'])
                if initial:
                    from story_engine import bounded,short
                    from cast import resolve_actor
                    actor_id=resolve_actor(card['name'],self.actors(),self.current['user_name'])
                    if not actor_id:continue
                    state['relations'][actor_id]={
                        'trust':bounded(initial.get('trust',30),0,100,'初始信任'),
                        'familiarity':bounded(initial.get('familiarity',0),0,100,'初始熟悉'),
                        'identity':short(initial.get('identity',''),100),'reason':'剧本初始关系'}
        self.current['facts']['browser_engine']=state
    def views(self,state=None):
        state=state or engine.current(self.current)
        cachekey=(self.current['id'],self.current['revision'],digest(state))
        if self._module_view_key==cachekey:return copy.deepcopy(self._module_views)
        result=[];ctx=engine.module_context(state,self.current['scene'],self.actors(),self.current['turns'][-1]['turn_id'])
        for ref in self.world_snapshot().get('world_gameplay',[]):
            entry=state['modules'].get(ref['id'])
            if not entry or entry.get('sha256')!=ref['sha256']:raise ValueError('存档玩法状态和代码版本不一致。')
            reply=self.modules.call(ref,'view',entry['state'],ctx)
            view=reply.get('view',{})
            if not isinstance(view,dict) or not isinstance(view.get('cards',[]),list) or not isinstance(view.get('actions',[]),list):raise ValueError('玩法界面格式不正确。')
            actions=view.get('actions',[]);seen=set()
            if len(actions)>30 or len(view.get('cards',[]))>100:raise ValueError('玩法界面过大。')
            for action in actions:
                from gameplay import key
                aid=key(action.get('id'))
                if aid in seen or not all(isinstance(action.get(k),str) and 0<len(action[k])<=300 for k in ('label','text')):raise ValueError('玩法动作格式不正确。')
                if not action['text'].startswith(('【语言】','【动作】','【环境】')):raise ValueError('玩法动作必须使用玩家输入前缀。')
                seen.add(aid)
            result.append({'id':ref['id'],'name':ref['name'],'version':ref['version'],'view':copy.deepcopy(view)})
        self._module_view_key=cachekey;self._module_views=copy.deepcopy(result)
        return result
    def state(self):
        with self.lock:
            result=super().state();state=engine.current(self.current)
            result['story_state']=engine.public(state)
            try:result['gameplay']=self.views(state)
            except (OSError,ValueError,KeyError):result['gameplay']=[];result['gameplay_unavailable']=True
            catalog=self.worlds.list()['worlds'];world=next((w for w in catalog if w['id']==self.world_snapshot().get('id')),None)
            # Catalog version may be enabled only on a new fork, never injected into old saves.
            if world:
                latest=self.worlds.load('worlds',world['id'])
                result['gameplay_upgrade_available']=bool(latest.get('world_gameplay') and latest.get('world_gameplay')!=self.world_snapshot().get('world_gameplay',[]))
            result['memory_status']={'scope':self.current['id'],'summaries':len(self.memory.eligible(self.current)),'organizing':self.current['id'] in self.memory.running}
            return result
    def compact_context(self,context):
        result=super().compact_context(context);state=engine.current(self.current)
        pending=self._engine_pending.get(self.activity.get('id'))
        if pending:
            state=copy.deepcopy(pending['engine']);result['settled_gameplay']=copy.deepcopy(pending['result'])
        result['story_state']=copy.deepcopy(state)
        # Receipt ledger and opaque module internals don't belong to the text model.
        result['story_state'].pop('applied_turns',None);result['story_state'].pop('modules',None)
        nodes=self.current['facts'].get('browser_story',{}).get('nodes',[])
        result['pacing']={'phase':state['plot']['phase'],'recent_beats':[n.get('beat') for n in nodes[-5:]],
            'unfinished_threads':[t for t in state['threads'].values() if t['status'] in {'open','active'}],
            'guidance':'根据实际目标与未解问题推进，允许平静日常或停顿；持续重复时给真实的新信息或可尝试的行动，不强制转折、不预设结局。'}
        result['gameplay']=[]
        ctx=engine.module_context(state,self.current['scene'],self.actors(),self.activity.get('id','context'))
        for ref in self.world_snapshot().get('world_gameplay',[]):
            entry=state['modules'].get(ref['id'])
            if not entry:continue
            reply=self.modules.call(ref,'context',entry['state'],ctx)
            result['gameplay'].append({'id':ref['id'],'name':ref['name'],'rules':reply.get('context',''),
                'actions':next((v['view'].get('actions',[]) for v in self.views(state) if v['id']==ref['id']),[])})
        result['schedule_tendencies']=[{'actor_id':c.get('card_id',c['id']),'name':c['name'],'tendencies':c['schedule_tendencies']}
            for s in self.world_snapshot().get('setting_sets',[]) for c in s['cards'] if c.get('schedule_tendencies')]
        # Retrieve old character observations only from that character's own branch-local knowledge.
        query=result.get('incoming','')+' '+result.get('scene','')
        import re
        words=set(re.findall(r'[\u4e00-\u9fff]{2,4}|[A-Za-z]{2,}',query))
        for aid,entries in self.current.get('facts',{}).get('browser_actor_knowledge',{}).items():
            retrieved=[e for e in entries[:-12] if any(w in e.get('observed','') for w in words)][-6:]
            result['actor_knowledge'][aid]=copy.deepcopy(retrieved+entries[-12:])
        return budget_context(result,self.current,self.memory)
    def module_step(self,state,ref,action_id,text,turn_id,frames=None):
        entry=state['modules'].get(ref['id'])
        if not entry or entry.get('sha256')!=ref['sha256']:raise ValueError('玩法版本不匹配。')
        ctx=engine.module_context(state,self.current['scene'],self.actors(),turn_id)
        event={'action_id':action_id,'input':text,'frames':[{k:f.get(k,'') for k in ('kind','speaker','text')} for f in (frames or []) if f['kind']!='thought']}
        reply=self.modules.call(ref,'event',entry['state'],ctx,event)
        if reply.get('rejected'):raise ValueError(str(reply['rejected'])[:300])
        for effect in reply.get('effects',[]):engine.apply_effect(state,effect,self.actors())
        entry['state']=reply['state']
        return {'module_id':ref['id'],'action_id':action_id,'outcome':reply.get('outcome',''),'effects':reply.get('effects',[])}
    def submit_module(self,module_id,action_id,request_id,session_id,text=None):
        with self.lock:
            if session_id!=self.current['id']:raise ValueError('剧情已切换，请重新打开玩法页面。')
            completed=next((t for t in self.current['turns'] if t['turn_id']==request_id),None)
            if completed:
                if text is not None and text!=completed['user']:raise ValueError('相同请求不能用于不同内容。')
                ledger=self.current.get('facts',{}).get('browser_gameplay_receipts',{}).get(request_id)
                if ledger!={'module_id':module_id,'action_id':action_id}:raise ValueError('相同请求不能用于不同玩法动作。')
                return {'accepted':True,'already_saved':True}
            if self.busy:
                if self.activity.get('id')==request_id:return {'accepted':True,'request_id':request_id}
                raise ValueError('请等当前回应结束。')
            view=next((v for v in self.views() if v['id']==module_id),None)
            action=next((a for a in (view or {}).get('view',{}).get('actions',[]) if a['id']==action_id),None)
            if not action:
                receipts=self.current.get('facts',{}).get('browser_gameplay_receipts',{})
                previous=next((t for t in reversed(self.current['turns']) if receipts.get(t['turn_id'])=={'module_id':module_id,'action_id':action_id}),None)
                if text is not None and previous and text!=previous['user']:
                    raise ModuleInputError('玩法操作与输入内容不一致，请作为普通消息重新发送。')
                raise ValueError('这个玩法动作目前不可使用。')
            if text is not None and text!=action['text']:raise ModuleInputError('玩法操作与输入内容不一致，请重新选择操作或作为普通消息发送。')
            ref=next(r for r in self.world_snapshot()['world_gameplay'] if r['id']==module_id)
            state=engine.current(self.current)
            outcome=self.module_step(state,ref,action_id,action['text'],request_id)
            self._engine_pending[request_id]={'engine':state,'result':outcome}
            try:return self.submit(action['text'],request_id,session_id)
            except Exception:
                self._engine_pending.pop(request_id,None);raise
    def settle_engine(self,reply,turn_id,interacted):
        pending=self._engine_pending.get(turn_id)
        state=copy.deepcopy(pending['engine']) if pending else engine.current(self.current)
        if turn_id in state['applied_turns']:return state
        updates=reply.get('world_updates',{})
        if not isinstance(updates,dict):raise ValueError('世界状态变化格式错误。')
        minutes=updates.get('elapsed_minutes',0)
        if pending and any(e.get('type')=='time' for e in pending['result'].get('effects',[])):
            minutes=0 # This action's duration was settled by its module, not charged twice.
        if minutes:engine.apply_effect(state,{'type':'time','minutes':minutes,'reason':updates.get('time_reason','')},self.actors())
        actors=self.actors()
        from cast import register_arrivals,resolve_actor
        register_arrivals(reply.get('scene_state',{}),actors,self.current['user_name'])
        for kind in ('relations','items','threads'):
            changes=updates.get(kind,[])
            if not isinstance(changes,list) or len(changes)>8:raise ValueError('世界状态变化过多。')
            for effect in changes:
                effect=dict(effect,type=kind)
                if kind=='relations':
                    effect['actor_id']=resolve_actor(effect.get('actor_id'),actors,self.current['user_name'])
                    identity=effect.get('identity','')
                    if any(w in identity for w in ('恋人','情侣','夫妻','未婚')):
                        # Both sides must explicitly communicate their intent in this turn.
                        from galgame import parse_input
                        parts=parse_input(self.activity.get('text',''))['parts']
                        request=any(e.get('mode')=='spoken' and effect['actor_id'] in e.get('recipient_ids',[]) and
                            any(w in parts[e['part_index']]['text'] for w in ('交往','恋人','在一起','结婚')) for e in reply.get('scene_state',{}).get('input_events',[]))
                        agreement=any(f['kind']=='dialogue' and resolve_actor(f.get('speaker'),actors,self.current['user_name'])==effect['actor_id'] and
                            any(w in f['text'] for w in ('愿意和你交往','我们交往吧','愿意成为你的恋人','愿意和你在一起','愿意嫁给你')) and
                            not any(w in f['text'] for w in ('不愿意','不会','不能','并不','不是','如果','假如')) for f in reply['frames'])
                        effect['mutual_consent']=request and agreement
                engine.apply_effect(state,effect,actors,interacted,reply['story']['milestone'])
        allowed={v['id']:{a['id'] for a in v['view'].get('actions',[])} for v in self.views(state)}
        for ref in self.world_snapshot().get('world_gameplay',[]):
            context_result=self.modules.call(ref,'context',state['modules'][ref['id']]['state'],engine.module_context(state,self.current['scene'],self.actors(),turn_id))
            private=context_result.get('context',{})
            if isinstance(private,dict):allowed.setdefault(ref['id'],set()).update(a['id'] for a in private.get('natural_actions',[]))
        events=updates.get('module_events',[])
        if not isinstance(events,list) or len(events)>4:raise ValueError('玩法事件过多。')
        sources=self.activity.get('text','')+'\n'+'\n'.join(f['text'] for f in reply['frames'] if f['kind']!='thought')
        seen=set()
        for event in events:
            pair=(event['module_id'],event['action_id']);evidence=event.get('evidence','')
            if pair in seen:raise ValueError('不能重复结算同一个玩法动作。')
            seen.add(pair)
            if pending and pair==(pending['result']['module_id'],pending['result']['action_id']):continue
            if event['action_id'] not in allowed.get(event['module_id'],set()) or not evidence or evidence not in sources:raise ValueError('玩法动作不被允许或缺少真实依据。')
            ref=next(r for r in self.world_snapshot()['world_gameplay'] if r['id']==event['module_id'])
            self.module_step(state,ref,event['action_id'],evidence,turn_id,reply['frames'])
        state['plot']['beat']=reply['story']['beat'];state['plot']['focus']=reply['story'].get('thread','')
        if updates.get('phase'):
            if not isinstance(updates['phase'],str) or len(updates['phase'])>100:raise ValueError('剧情阶段名称不正确。')
            state['plot']['phase']=updates['phase']
        state['applied_turns'].append(turn_id)
        state['applied_turns']=state['applied_turns'][-100:]
        return state
    def after_engine_commit(self,request_id):
        self._engine_pending.pop(request_id,None)
        if self.persistent:self.memory.compact(self.current,self.memory_client)
    def manage_save(self,data):
        with self.lock:
            if self.busy:raise ValueError('请等当前回应保存完成。')
            operation=data['operation']
            if operation=='edit':
                result=self.saves.edit(data['session_id'],data['title'],data.get('note',''))
                if result['id']==self.current['id']:self.current=result;self.version+=1
                return {'ok':True}
            if operation=='restore':return self.saves.restore(data['recycle_id'])
            if operation=='import':return self.saves.import_bundle(base64.b64decode(data['bundle'],validate=True))
            if operation=='delete':
                target=self.saves.session(data['session_id'])
                # A deleting active branch remains protected; choose another save first.
                from branch_store import metadata
                sessions=self.command('sessions')['sessions']
                selected={target['id']}
                if data.get('subtree') is True:
                    changed=True
                    while changed:
                        changed=False
                        for row in sessions:
                            session=self.saves.session(row['id'])
                            if metadata(session)['parent_id'] in selected and row['id'] not in selected:selected.add(row['id']);changed=True
                if self.current['id'] in selected and self.persistent:
                    if data.get('from_lobby') is not True:raise ValueError('请先返回主界面或切换到其他存档，再移入回收站。')
                    # Detach the loaded branch before deleting it. A fresh unsaved
                    # opening prevents later polling/saving from recreating that ID.
                    previous_id=self.current['id']
                    self.start(self.current['card_id'],self.current['user_name'],False)
                    try:return self.saves.delete(target['id'],data.get('subtree') is True)
                    except Exception:
                        self.restore(previous_id);raise
                return self.saves.delete(target['id'],data.get('subtree') is True)
            raise ValueError('不支持的存档操作。')
    def enable_latest_gameplay(self,session_id):
        with self.lock:
            if self.busy or not self.persistent or session_id!=self.current['id']:raise ValueError('请在已保存且空闲的故事中启用玩法。')
            world=self.world_snapshot();latest=self.worlds.snapshot(self.current['card_id'],world['id'])
            from branch_store import create_fork
            previous=self.current;candidate=copy.deepcopy(previous);self.current=candidate
            try:
                candidate['world_snapshot']=latest;candidate['facts']['browser_world_snapshot']=latest
                # Preserve clock, items, relations and threads; initialize only new module states.
                state=engine.current(previous)
                for ref in latest.get('world_gameplay',[]):
                    ctx=engine.module_context(state,candidate['scene'],self.actors(),candidate['turns'][-1]['turn_id'])
                    old=state['modules'].get(ref['id'])
                    if old and old.get('sha256')==ref['sha256']:continue
                    reply=self.modules.call(ref,'initialize',{},ctx)
                    state['modules'][ref['id']]={'version':ref['version'],'sha256':ref['sha256'],'state':reply['state']}
                    for effect in reply.get('effects',[]):engine.apply_effect(state,effect,self.actors())
                candidate['facts']['browser_engine']=state
                self.current=previous
                child=create_fork(self.root,self.tavern,previous,candidate,previous['turns'][-1]['turn_id'],'module-upgrade')
                self.current=child
                # Before-upgrade checkpoints keep the original frozen world. Only this point changes.
                self.version+=1;self.checkpoint(force=True);return self.state()
            except Exception:
                self.current=previous;raise
    def set_story_clock(self,session_id,date,minute):
        with self.lock:
            if self.busy or session_id!=self.current['id']:raise ValueError('请等当前回合结束后设置时间。')
            state=engine.current(self.current)
            engine.apply_effect(state,{'type':'time','minutes':0,'date':date,'minute':minute,'reason':'玩家设置故事时间'},self.actors())
            candidate=copy.deepcopy(self.current);candidate['facts']['browser_engine']=state
            candidate['revision']+=1;candidate['updated_at']=self.tavern.now()
            if self.persistent:
                with self.tavern.write_lock(self.root):
                    if self.saves.session(session_id)['revision']!=self.current['revision']:raise ValueError('存档已经变化，请重新载入后设置时间。')
                    self.tavern.atomic_json(self.root/'sessions'/(session_id+'.json'),candidate)
            self.current=candidate
            if self.persistent:self.checkpoint(force=True)
            self.version+=1;return self.state()
