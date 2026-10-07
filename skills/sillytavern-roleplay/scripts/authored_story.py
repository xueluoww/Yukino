"""Generic, deterministic script-owned routes. Original saves stay in free mode."""
import copy
import hashlib
import json
import re
import time
from cast import resolve_actor, bind_frames
import story_engine

def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def validate_routes(routes, names=None):
    if not isinstance(routes, list) or len(routes)>20: raise ValueError('预制故事线列表过大或格式错误。')
    route_ids=set()
    for route in routes:
        if not isinstance(route,dict): raise ValueError('故事线必须是对象。')
        rid=route.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',rid) or rid in route_ids: raise ValueError('故事线编号无效或重复。')
        route_ids.add(rid)
        if route.get('spec')!='yukima_storyline_v1' or not isinstance(route.get('version'),str) or not route['version']: raise ValueError('故事线版本与协议不正确。')
        for field in ('title','description'):
            if not isinstance(route.get(field),str) or not 0<len(route[field])<=2000: raise ValueError('故事线需要标题与简介。')
        if 'time_start' in route:
            from story_time import policy
            policy({'start':route['time_start']})
        nodes=route.get('nodes')
        if not isinstance(nodes,dict) or not 1<=len(nodes)<=300: raise ValueError('故事节点格式不正确。')
        if route.get('start') not in nodes: raise ValueError('故事线开场节点缺失。')
        backgrounds=route.get('backgrounds',{})
        if not isinstance(backgrounds,dict) or len(backgrounds)>100:raise ValueError('故事背景表格式不正确。')
        for key,asset in backgrounds.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key) or not isinstance(asset,dict) or not isinstance(asset.get('name'),str) or not asset['name'] or not isinstance(asset.get('url'),str) or not re.fullmatch(r'/(?!/)[\w./%-]+',asset['url']) or '..' in asset['url'] or '%' in asset['url']:raise ValueError('故事背景需要本地资源与中文名称。')
        for field in ('initial_affinity','initial_relations'):
            mapping=route.get(field,{})
            if not isinstance(mapping,dict) or any(not isinstance(name,str) or names is not None and name not in names for name in mapping):raise ValueError('故事线初始人物引用无效。')
        if any(type(score)is not int or not 0<=score<=100 for score in route.get('initial_affinity',{}).values()):raise ValueError('初始好感超出范围。')
        for relation in route.get('initial_relations',{}).values():
            if not isinstance(relation,dict) or any(type(relation.get(k))is not int or not 0<=relation[k]<=100 for k in ('trust','familiarity')) or not isinstance(relation.get('identity',''),str):raise ValueError('初始关系格式不正确。')
        for nid,node in nodes.items():
            if not isinstance(node,dict):raise ValueError('故事节点必须是对象。')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',nid): raise ValueError('故事节点编号无效。')
            for field in ('title','scene','background'):
                if not isinstance(node.get(field),str) or not node[field] or len(node[field])>2000: raise ValueError('故事节点缺少场景与标题。')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',node['background']): raise ValueError('背景编号无效。')
            present=node.get('present',[])
            if not isinstance(present,list) or len(set(present))!=len(present) or any(not isinstance(n,str) or names is not None and n not in names for n in present): raise ValueError('在场人物引用无效。')
            frames=node.get('frames')
            if not isinstance(frames,list) or not 1<=len(frames)<=12: raise ValueError('节点需要1–12个分镜。')
            for frame in frames:
                if not isinstance(frame,dict) or frame.get('kind') not in {'dialogue','narration'} or not isinstance(frame.get('text'),str) or not 0<len(frame['text'])<=8000: raise ValueError('故事分镜无效。')
                if frame.get('expression','neutral') not in {'neutral','soft','serious','shy','thinking','listening','troubled','surprised','sad','displeased','happy','eyes_closed','absent'}: raise ValueError('故事表情无效。')
                speaker=frame.get('speaker','')
                if frame['kind']=='dialogue' and speaker!='player' and speaker not in present: raise ValueError('离场人物不能说话。')
                if frame.get('audience') is not None and (not isinstance(frame['audience'],list) or any(a!='player' and a not in present for a in frame['audience'])): raise ValueError('对白听众必须在场。')
            options=node.get('choices',[])
            window=node.get('free_window')
            if window is not None:
                if not isinstance(window,dict) or not node.get('next') or options or node.get('ending'):raise ValueError('自由活动节点需要唯一的主线后续。')
                # Legacy quotas are accepted for frozen saves but never enforced.
                goal=window.get('goal')
                if goal is not None:
                    if not isinstance(goal,dict) or not isinstance(goal.get('title'),str) or not goal['title'] or len(goal['title'])>300:raise ValueError('目标阶段需要简短目标。')
                    criteria=goal.get('criteria')
                    if not isinstance(criteria,list) or not 1<=len(criteria)<=8:raise ValueError('目标阶段需要1–8个完成条件。')
                    for group in (criteria,goal.get('boundaries',[])):
                        if not isinstance(group,list) or len(group)>8 or len({c.get('id') for c in group if isinstance(c,dict)})!=len(group):raise ValueError('目标条件或边界编号重复。')
                        for item in group:
                            if not isinstance(item,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',item.get('id','')) or not isinstance(item.get('description'),str) or not 0<len(item['description'])<=1500:raise ValueError('目标条件或边界无效。')
                            if item.get('source','joint') not in ('joint','scene') or item.get('source')=='scene' and (not isinstance(item.get('actor'),str) or names is not None and item['actor'] not in names):raise ValueError('场景完成条件需要有效的回应人物。')
                    if goal.get('converge') not in nodes or not isinstance(goal.get('conclude_text'),str) or not goal['conclude_text'].startswith('【动作】') or len(goal['conclude_text'])>300:raise ValueError('目标阶段缺少有效收束节点与动作。')
                for field in ('description','context','return_text'):
                    if not isinstance(window.get(field),str) or not 0<len(window[field])<=3000:raise ValueError('自由活动需要玩家说明、当前背景与返回动作。')
                if not window['return_text'].startswith('【动作】'):raise ValueError('返回主线需要动作前缀。')
            if not isinstance(options,list) or len(options)>3: raise ValueError('故事节点最多3个选项。')
            option_ids=set()
            for choice in options:
                if not isinstance(choice,dict):raise ValueError('剧情选项必须是对象。')
                cid=choice.get('id','')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',cid) or cid in option_ids: raise ValueError('剧情选项编号无效或重复。')
                option_ids.add(cid)
                if choice.get('target') not in nodes: raise ValueError('剧情选项指向不存在的节点。')
                if not isinstance(choice.get('text'),str) or not choice['text'].startswith(('【语言】','【动作】','【内心】')) or len(choice['text'])>300: raise ValueError('剧情选项需要玩家输入前缀。')
                for key in ('when','set'):
                    mapping=choice.get(key,{})
                    if not isinstance(mapping,dict) or any(not isinstance(k,str) or not k or type(v) not in (str,int,bool) for k,v in mapping.items()): raise ValueError('剧情条件与标记必须是简单值映射。')
                if len(choice.get('label',choice['text']))>300: raise ValueError('选项标题过长。')
            if node.get('next') and (node['next'] not in nodes or options): raise ValueError('节点后续引用无效。')
            if bool(node.get('ending'))==bool(options or node.get('next')): raise ValueError('节点必须有后续或明确结局。')
            effects=node.get('effects',[])
            if not isinstance(effects,list) or len(effects)>16 or any(not isinstance(e,dict) or e.get('type') not in {'time','items','relations','threads'} or not e.get('reason') for e in effects): raise ValueError('故事效果无效。')
            for effect in effects:
                if effect['type']=='relations' and effect.get('mutual_consent'):
                    pairs=[f for f in frames if f['kind']=='dialogue']
                    actor=effect.get('actor_id')
                    if not any(f['speaker']=='player' and any(w in f['text'] for w in ('交往','恋人','在一起')) for f in pairs) or not any(f['speaker']==actor and any(w in re.split('[。！？；]',f['text'])[0] for w in ('愿意和你交往','愿意成为你的恋人','愿意和你在一起')) and not any(w in re.split('[。！？；]',f['text'])[0] for w in ('不愿意','不能','不想','不可以')) for f in pairs): raise ValueError('关系确认需要双方对白依据。')
        reachable=set();stack=[route['start']]
        while stack:
            nid=stack.pop()
            if nid in reachable: continue
            reachable.add(nid);node=nodes[nid]
            stack.extend([c['target'] for c in node.get('choices',[])]+([node['next']] if node.get('next') else [])+([node['free_window']['goal']['converge']] if node.get('free_window',{}).get('goal') else []))
        if reachable!=set(nodes): raise ValueError('故事线有无法到达的节点。')
        # Structural reachability alone misses all choices becoming hidden.
        # Explore reachable flag combinations, rather than assuming a condition
        # can be satisfied merely because a target node exists.
        pending=[(route['start'], {})];seen=set();edges={};end_states=set()
        while pending:
            nid,flags=pending.pop();token=(nid,json.dumps(flags,sort_keys=True,ensure_ascii=False))
            if token in seen:continue
            seen.add(token)
            if len(seen)>10000:raise ValueError('故事条件组合超过校验上限，请拆分故事线。')
            node=nodes[nid];next_states=[]
            if node.get('ending'):end_states.add(token)
            elif node.get('choices'):
                available=[c for c in node['choices'] if all(flags.get(k)==v for k,v in c.get('when',{}).items())]
                if not available:raise ValueError('故事节点 '+nid+' 在可达条件下没有可用选项。')
                next_states=[(c['target'],flags|c.get('set',{})) for c in available]
            else:
                next_states=[(node['next'],flags)]
                if node.get('free_window',{}).get('goal'):next_states.append((node['free_window']['goal']['converge'],flags))
            edges[token]={(target,json.dumps(f,sort_keys=True,ensure_ascii=False)) for target,f in next_states}
            pending.extend(next_states)
        good=set(end_states)
        while True:
            extra={state for state,targets in edges.items() if targets & good}
            if extra<=good:break
            good|=extra
        if seen-good:raise ValueError('故事线存在可达却无法收束的条件分支。')
        possible={nid for nid,n in nodes.items() if n.get('ending')}
        while True:
            more={nid for nid,n in nodes.items() if any(t in possible for t in [c['target'] for c in n.get('choices',[])]+([n['next']] if n.get('next') else [])+([n['free_window']['goal']['converge']] if n.get('free_window',{}).get('goal') else []))}
            if more<=possible: break
            possible|=more
        if possible!=set(nodes): raise ValueError('故事线有无法走到结局的节点。')
        for node in nodes.values():
            if node.get('free_window') and nodes[node['next']]['frames'][0]['kind']!='narration':raise ValueError('自由活动返回的主线节点应以旁白交代接续。')
            goal=node.get('free_window',{}).get('goal')
            if goal and nodes[goal['converge']]['frames'][0]['kind']!='narration':raise ValueError('目标收束节点应以旁白承接玩家经历。')
    return copy.deepcopy(routes)

class AuthoredRuntime:
    def authored_descriptor(self,descriptor,key):
        if not self.current or key!=self.current['card_id'] or not self.current.get('facts',{}).get('browser_authored'):return descriptor
        route,_=self.authored_route()
        result=copy.deepcopy(descriptor)
        for bg,asset in route.get('backgrounds',{}).items():
            result.setdefault('backgrounds',{})[bg]=asset['url']
            result.setdefault('background_descriptions',{})[bg]=asset['name']
        return result

    def authored_route(self):
        progress=self.current.get('facts',{}).get('browser_authored')
        if not progress:return None,None
        route=next((r for r in self.world_snapshot().get('storylines',[]) if r['id']==progress['id']),None)
        if not route or checksum(route)!=progress['sha256']: raise ValueError('预制故事线版本与存档不一致，请恢复对应剧本。')
        return route,progress

    def authored_choices(self,route,progress):
        node=route['nodes'][progress['node_id']]
        return [copy.deepcopy(c) for c in node.get('choices',[]) if all(progress['flags'].get(k)==v for k,v in c.get('when',{}).items())]

    def authored_window(self):
        route,progress=self.authored_route()
        return (route['nodes'][progress['node_id']].get('free_window'),progress) if route else (None,None)

    def authorize_authored_input(self):
        window,progress=self.authored_window()
        if not progress:return
        if not window:raise ValueError('这一幕是主线剧情，请阅读或使用剧情选项。')
        if progress.get('frame_cursor',0)!=len([f for f in self.frames if f['kind']!='thought'])-1:raise ValueError('请先读完当前回应，再进行自由行动。')

    def compact_context(self,context):
        result=super().compact_context(context)
        window,progress=self.authored_window()
        if window:
            background='当前为预制主线之间的自由活动。'+window['context']
            result['character']['scenario']=background
            result['world']['background']=background
            result['summary']=self.current.get('summary','')
            result['director_only_fields']=list(dict.fromkeys(result.get('director_only_fields',[])+['authored_intermission']))
            result['gameplay']=[]
            result['pacing']['guidance']='围绕当前目标允许自由组织说话、行动与方法，不替玩家决策，不限制互动次数；休息或探索不等于违规。主线的完成条件可逐步达成，但最终收束只由播放器在条件满足后执行。'
            goal=window.get('goal',{})
            result['authored_intermission']={'background':window['context'],'goal':{k:copy.deepcopy(v) for k,v in goal.items() if k in ('title','criteria','boundaries')},'progress':copy.deepcopy(progress.get('goal_evidence',{})),'boundary_history':copy.deepcopy(progress.get('boundary_history',[])[-6:]),
                'rules':'只有当前阶段目标，没有未来主线或结局。玩家可用预设方法或自拟可行方法，不强迫采用作者唯一答案。不把闲聊、休息、拒绝某种方法或合理探索当成违规。明确违背现实、人设或任务约束时，人物按性格拒绝、说明后果或提出可行替代；反复违规可基于实际观察降低信任或失去协助，不全员机械惩罚。玩家内心不给NPC知晓。goal_assessment.criteria只报告本轮实际达成条件，input_evidence复制本轮非内心输入，scene_evidence复制非心声分镜原文；纯意图、假设、梦境、宣称成功、强迫NPC同意均不算完成。未有证据填空数组。boundaries也需要同样证据，不凭空处罚。主线活动结束、恋爱身份等最终节点不能提前发生。story.milestone=false；world_updates.phase与module_events为空，作者主线事件状态不改。'}
        return result

    def authored_schema(self,schema):
        window,_=self.authored_window()
        if window and window.get('goal'):
            item={'type':'object','properties':{k:{'type':'string','description':'证据必须逐字复制本轮实际输入或非心声分镜中的连续原文，包含标点；不改写、不加署名。'} for k in ('id','input_evidence','scene_evidence')},'required':['id','input_evidence','scene_evidence'],'additionalProperties':False}
            schema['properties']['goal_assessment']={'type':'object','properties':{k:{'type':'array','maxItems':8,'items':copy.deepcopy(item)} for k in ('criteria','boundaries')},'required':['criteria','boundaries'],'additionalProperties':False}
            boundary=schema['properties']['goal_assessment']['properties']['boundaries']
            boundary['description']='只报告本轮实际越界。人物说明底线、玩家表达尊重、讨论风险均不代表已经违规，无实际违规用[]。'
            boundary['items']['properties']['violated']={'type':'boolean','description':'实际发生违规才填true；防范或讨论边界不是违规。'}
            boundary['items']['required'].append('violated')
            schema['required'].append('goal_assessment')
        return schema

    def normalize_authored_reply(self,reply):
        window,progress=self.authored_window()
        if not window:return
        route,_=self.authored_route()
        protected={e['id'] for n in route['nodes'].values() for e in n.get('effects',[]) if e['type']=='threads'}
        updates=reply.get('world_updates',{})
        if isinstance(updates,dict):
            updates['phase']='';updates['module_events']=[]
            if isinstance(updates.get('threads'),list):updates['threads']=[e for e in updates['threads'] if e.get('id') not in protected]
            if isinstance(updates.get('relations'),list):
                for relation in updates['relations']:
                    relation['identity']=''
                    for field in ('trust','familiarity'):
                        if type(relation.get(field))is int:relation[field]=max(-3,min(3,relation[field]))
        if isinstance(reply.get('story'),dict):reply['story']['milestone']=False

    def settle_engine(self,reply,turn_id,interacted):
        result=super().settle_engine(reply,turn_id,interacted)
        window,progress=self.authored_window()
        if window:result['plot']=copy.deepcopy(story_engine.current(self.current)['plot'])
        return result

    def authored_free_facts(self,reply,text='',turn_id=''):
        window,old=self.authored_window()
        if not window:return {}
        progress=copy.deepcopy(old);progress['free_turns']=progress.get('free_turns',0)+1;progress['frame_cursor']=0
        progress['free_minutes']=progress.get('free_minutes',0)+reply.get('world_updates',{}).get('elapsed_minutes',0)
        goal=window.get('goal')
        if goal:
            from galgame import parse_input
            inputs=[p['text'] for p in parse_input(text)['parts'] if p['kind']!='thought']
            scenes=[]
            for frame in reply['frames']:
                if frame['kind']=='thought':continue
                scenes.append(frame['text'])
                if frame.get('speaker'):scenes.append(frame['speaker']+'：'+frame['text'])
            assessment=reply.get('goal_assessment',{})
            for group in ('criteria','boundaries'):
                allowed={c['id']:c for c in goal.get(group,[])}
                proposals=assessment.get(group,[]) if isinstance(assessment,dict) else []
                if not isinstance(proposals,list):continue
                for p in proposals[:8]:
                    if not isinstance(p,dict) or p.get('id') not in allowed:continue
                    if group=='boundaries' and p.get('violated') is not True:continue
                    a=p.get('input_evidence','');b=p.get('scene_evidence','')
                    if not isinstance(a,str) or not isinstance(b,str) or len(b.strip())<4 or not any(b in s for s in scenes):continue
                    criterion=allowed[p['id']]
                    if group=='criteria' and criterion.get('source')=='scene':
                        actor=resolve_actor(criterion['actor'],self.actors(),self.current['user_name'])
                        matching=[f for f in reply['frames'] if f['kind']=='dialogue' and resolve_actor(f.get('speaker',''),self.actors(),self.current['user_name'])==actor and ('audience_ids' not in f or 'player' in f['audience_ids']) and (b in f['text'] or b in f.get('speaker','')+'：'+f['text'])]
                        if not matching:continue
                    elif len(a.strip())<4 or not any(a in s for s in inputs):continue
                    evidence={'turn_id':turn_id,'input_evidence':a[:1500],'scene_evidence':b[:1500]}
                    if group=='criteria':progress.setdefault('goal_evidence',{})[p['id']]=evidence
                    else:
                        history=progress.setdefault('boundary_history',[])
                        if not any(e['turn_id']==turn_id and e['id']==p['id'] for e in history):history.append(dict(evidence,id=p['id']))
                        progress['boundary_history']=history[-24:]
        return {'browser_authored':progress}

    def state(self):
        result=super().state()
        route,progress=self.authored_route()
        if route:
            node=route['nodes'][progress['node_id']]
            result['authored']={'id':route['id'],'title':route['title'],'node_id':progress['node_id'],'frame_cursor':progress.get('frame_cursor',0),
                'ending':node.get('ending',''),'can_advance':bool(node.get('next')),'choices':[{'id':c['id'],'label':c.get('label',c['text']),'text':c['text']} for c in self.authored_choices(route,progress)]}
            window=node.get('free_window')
            result['authored']['free_window']={'description':window['description'],'can_send':True,'return_text':window['return_text']} if window else None
            goal=window.get('goal') if window else None
            if goal:
                result['authored']['free_window']['goal']={'title':goal['title'],'criteria':[{'description':c['description'],'done':c['id'] in progress.get('goal_evidence',{})} for c in goal['criteria']]}
                if all(c['id'] in progress.get('goal_evidence',{}) for c in goal['criteria']):result['authored']['choices']=[{'id':'goal-complete','label':'进入收束','text':goal['conclude_text']}]
            result['gameplay']=[] # Unrelated free-mode quests do not advance during authored playback.
        else:result['authored']=None
        return result

    def authored_prepare(self,route,progress,turn_id):
        node=route['nodes'][progress['node_id']];actors=self.actors();user=self.current['user_name']
        ids=[resolve_actor(n,actors,user) for n in node['present']]
        if any(not a or a=='player' for a in ids): raise ValueError('故事在场人物无法绑定。')
        state={'location':node['scene'],'present_actor_ids':ids,'visible_actor_ids':ids,'contacts':[],'arrivals':[],'input_events':[]}
        frames=copy.deepcopy(node['frames'])
        for f in frames:
            original=f.get('speaker','')
            f['speaker']=user if original=='player' else original
            f.setdefault('expression','neutral' if ids else 'absent')
            f['reaction_to']=[]
            f['stage']={'location':node['scene'],'present_actor_ids':ids,'visible_actor_ids':ids,'background':node['background']}
            if f['kind']=='dialogue':f['audience_ids']=[resolve_actor(n,actors,user) for n in f.get('audience',node['present']+['player'])]
        frames=bind_frames(frames,actors,user,state)
        engine=story_engine.current(self.current)
        for raw in node.get('effects',[]):
            effect=copy.deepcopy(raw)
            if effect['type']=='relations':effect['actor_id']=resolve_actor(effect['actor_id'],actors,user)
            story_engine.apply_effect(engine,effect,actors,set(ids),True,time_store=self.modules)
        engine['plot']={'phase':node['title'],'beat':node.get('beat','development'),'focus':node.get('thread','')}
        engine['applied_turns']=(engine['applied_turns']+[turn_id])[-100:]
        visual={'background':node['background'],'expression':'neutral' if ids else 'absent','appearance_key':'school-uniform'}
        # Authored playback also registers visited prefabricated backgrounds;
        # previously it bypassed the gallery pipeline entirely.
        from shared_gallery import visual_key,background_identity,digest,script_scope
        descriptor=self.descriptor();route_asset=route.get('backgrounds',{}).get(node['background'],{});url=route_asset.get('url') or descriptor.get('backgrounds',{}).get(node['background'])
        if url:
            identity=background_identity(self.current,node['background'],{'location':node['scene'],'time':__import__('story_time').public(engine)['time']['period']})
            key='builtin-'+digest([script_scope(self.current),node['background'],url])
            self.cache[key]={'key':key,'kind':'background','url':url,'name':route_asset.get('name') or descriptor.get('background_descriptions',{}).get(node['background'],node['scene']),
                             'background':node['background'],'background_identity':identity,
                             'visual_key':visual_key(self.current,'background',background=node['background'],identity=identity)}
            visual['background_asset']=self.chosen_image(key)
            for frame in frames:frame['stage']['background_asset']=visual['background_asset']
        from perception import knowledge,positions,current_scene
        facts={'browser_authored':progress,'browser_engine':engine,'browser_scene_state':state,
            'browser_actor_knowledge':knowledge(self.current,state,turn_id,frames),
            'browser_actor_locations':positions(self.current,current_scene(self.current,actors,self.frames),state,frames),
            'browser_visual':visual,'browser_latest_frames':frames}
        facts['browser_gallery_refs']=sorted(__import__('shared_gallery').branch_refs(self.current)|{visual['background_asset']} if visual.get('background_asset') else __import__('shared_gallery').branch_refs(self.current))
        return node,frames,visual,facts

    def initialize_authored(self,storyline_id):
        route=next((r for r in self.world_snapshot().get('storylines',[]) if r['id']==storyline_id),None)
        if not route:raise ValueError('找不到这条预制故事线。')
        if route.get('protagonist_id') and self.protagonist()['id']!=route['protagonist_id']: raise ValueError('这条故事线需要选择比企谷八幡主角卡。')
        progress={'id':route['id'],'version':route['version'],'sha256':checksum(route),'node_id':route['start'],'frame_cursor':0,'flags':{},'decisions':[]}
        state=story_engine.current(self.current);actors=self.actors()
        if 'time_start' in route:
            if not state.get('time_policy'):raise ValueError('故事线 time_start 需要世界观 time 配置。')
            policy=copy.deepcopy(state['time_policy']);policy['start']=copy.deepcopy(route['time_start'])
            policy.pop('module_ref',None)
            timed=__import__('story_time').seed({'time':policy,'world_gameplay':self.world_snapshot().get('world_gameplay',[])})
            state.update(timed)
            __import__('story_time').initialize(state,self.modules)
        for name,relation in route.get('initial_relations',{}).items():
            aid=resolve_actor(name,actors,self.current['user_name'])
            if not aid:raise ValueError('故事初始关系人物不存在。')
            state['relations'][aid]=dict(relation,reason='预制线开场已确立的关系')
        self.current['facts']['browser_engine']=state
        node,frames,visual,facts=self.authored_prepare(route,progress,'opening')
        self.current['facts'].update(facts);self.frames=frames;self.visual=visual;self.current['scene']=node['scene'];self.current['summary']=node.get('summary',node['title'])
        from galgame import canonical_text
        self.current['turns'][0]['assistant']=canonical_text(frames);self.current['facts']['browser_opening_frames']=copy.deepcopy(frames)
        self.current['title']=self.world_snapshot()['name']+' · '+route['title']+' · '+self.current['user_name']
        self.current['facts']['browser_story']={'nodes':[{'id':'opening','title':node['title'],'beat':node.get('beat','setup'),'milestone':True,'scene':node['scene'],'turn_index':0}],
            'choices':[{'label':c.get('label',c['text']),'text':c['text']} for c in self.authored_choices(route,progress)],'thread':node.get('thread','')}
        affection=self.current['facts'].get('browser_affinity',{})
        for name,score in route.get('initial_affinity',{}).items():
            aid=resolve_actor(name,actors,self.current['user_name'])
            if aid in affection.get('characters',{}):affection['characters'][aid]['score']=score

    def advance_authored(self,session_id,request_id,node_id,choice_id=None):
        with self.lock:
            if session_id!=self.current['id'] or self.busy or self.current['status']!='active':raise ValueError('故事已切换、暂停或正在保存，请重新读取。')
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id):raise ValueError('请求编号无效。')
            receipt={'node_id':node_id,'choice_id':choice_id}
            ledger=self.current['facts'].get('browser_authored_receipts',{})
            if request_id in ledger:
                if ledger[request_id]!=receipt:raise ValueError('相同请求编号不能用于其他剧情选择。')
                return self.state()
            route,old=self.authored_route()
            if not route or old['node_id']!=node_id:raise ValueError('这一幕已经变化，请重新读取。')
            if old.get('frame_cursor',0)!=len([f for f in self.frames if f['kind']!='thought'])-1:
                raise ValueError('请先读完当前分镜，再推进下一幕。')
            node=route['nodes'][node_id];progress=copy.deepcopy(old)
            choices=self.authored_choices(route,progress)
            if choices:
                choice=next((c for c in choices if c['id']==choice_id),None)
                if not choice:raise ValueError('请选择当前可用的剧情选项。')
                target=choice['target'];text=choice['text'];progress['flags'].update(choice.get('set',{}))
                progress['decisions'].append({'node_id':node_id,'choice_id':choice_id,'turn_id':request_id})
            else:
                target=node.get('next');text=node.get('free_window',{}).get('return_text','【动作】继续这一幕')
                goal=node.get('free_window',{}).get('goal')
                if not choice_id and goal and all(c['id'] in old.get('goal_evidence',{}) for c in goal['criteria']):
                    choice_id='goal-complete'
                if choice_id=='goal-complete' and goal:
                    if not all(c['id'] in old.get('goal_evidence',{}) for c in goal['criteria']):raise ValueError('当前问题尚未解决，请继续行动或采用预设方法。')
                    target=goal['converge'];text=goal['conclude_text']
                elif choice_id or not target:raise ValueError('这条故事线已结束，或选项条件未满足。')
            free_count=old.get('free_turns',0)
            if node.get('free_window',{}).get('goal'):
                progress['goal_history']=(progress.get('goal_history',[])+[{'node_id':node_id,'method':'player' if choice_id=='goal-complete' else 'guided','evidence':copy.deepcopy(old.get('goal_evidence',{})),'boundaries':copy.deepcopy(old.get('boundary_history',[])),'turn_id':request_id}])[-50:]
            progress['node_id']=target;progress['frame_cursor']=0;progress['free_turns']=0;progress['free_minutes']=0
            progress.pop('goal_evidence',None);progress.pop('boundary_history',None)
            previous=copy.deepcopy(self.current)
            if self.persistent:
                _,latest=self.tavern.find_record(self.root,'sessions',session_id)
                if latest['revision']!=previous['revision']:raise ValueError('存档已被其他窗口更新，请重新读取。')
            newnode,frames,visual,facts=self.authored_prepare(route,progress,request_id)
            if node.get('free_window') and free_count and previous['scene']!=newnode['scene']:
                movement='你结束这一段自由活动，随后回到'+newnode['scene']+'。'
                if frames[0]['kind']=='narration':frames[0]['text']=movement+'\n\n'+frames[0]['text']
                facts['browser_latest_frames']=frames
                minutes=facts['browser_engine'].get('time_policy',{}).get('durations',{}).get('travel',10)
                story_engine.apply_effect(facts['browser_engine'],{'type':'time','minutes':minutes,'reason':'结束自由活动并回到主线地点'},self.actors(),time_store=self.modules)
            from galgame import canonical_text
            timeline=copy.deepcopy(previous['facts']['browser_story'])
            timeline['nodes'].append({'id':request_id,'title':newnode['title'],'beat':newnode.get('beat','development'),'milestone':True,'scene':newnode['scene'],'turn_index':len(previous['turns']),'story_time':story_engine.public(facts['browser_engine'])['clock']})
            timeline['choices']=[{'label':c.get('label',c['text']),'text':c['text']} for c in self.authored_choices(route,progress)];timeline['thread']=newnode.get('thread','')
            facts.update({'browser_story':timeline,'browser_turn_frames':previous['facts'].get('browser_turn_frames',{})|{request_id:copy.deepcopy(frames)},'browser_authored_receipts':ledger|{request_id:receipt}})
            update={'scene':newnode['scene'],'summary':newnode.get('summary',newnode['title']),'facts':facts,'relationships':{},'memories':[]}
            payload={'turn_id':request_id,'expected_revision':previous['revision'],'user':text,'assistant':canonical_text(frames),'update':update}
            if self.persistent:
                path=self.root/'browser/jobs'/session_id/request_id/'turn.json';self.tavern.atomic_json(path,payload)
                self.command('commit',session_id,path);_,self.current=self.tavern.find_record(self.root,'sessions',session_id)
            else:
                candidate=copy.deepcopy(previous);candidate['facts'].update(facts);candidate['scene']=update['scene'];candidate['summary']=update['summary'];candidate['turns'].append({k:payload[k] for k in ('turn_id','user','assistant')});candidate['revision']+=1;candidate['updated_at']=self.tavern.now();self.current=candidate
            self.frames=frames;self.visual=visual;self.activity={};self.error='';self.version+=1;self.checkpoint()
            self.activate_visuals()
            self.tavern.atomic_json(self.cache_file,self.cache)
            return self.state()

    def authored_cursor(self,session_id,node_id,index,turn_id=None):
        with self.lock:
            if session_id!=self.current['id'] or self.busy:raise ValueError('故事已经切换。')
            if turn_id is not None and turn_id!=self.current['turns'][-1]['turn_id']:raise ValueError('这一轮已经变化，请重新读取。')
            route,progress=self.authored_route()
            if not route or progress['node_id']!=node_id or type(index)is not int or not 0<=index<len([f for f in self.frames if f['kind']!='thought']):raise ValueError('阅读位置无效。')
            candidate=copy.deepcopy(self.current);candidate['facts']['browser_authored']['frame_cursor']=index
            if self.persistent:
                with self.tavern.write_lock(self.root):
                    path=self.root/'sessions'/(session_id+'.json');latest=self.tavern.load_json(path,128*self.tavern.MAX_CARD)
                    if latest['revision']!=candidate['revision']:raise ValueError('存档已变化，请重新读取。')
                    candidate['revision']+=1;self.tavern.atomic_json(path,candidate)
            self.current=candidate
            return {'ok':True}
