"""World-aware visuals and a bounded, separate speculative asset pool."""
import copy
import hashlib
import json
import queue
import shutil
import threading
from pathlib import Path
from cast import registry,bind_frames,asset_key,player_snapshot,player_cards,DEFAULT_PLAYER
from worlds import WorldLibrary,world_context
from preview_library import PreviewLibrary
from image_service import ImageService
from deepseek_client import FlashClient
from branch_store import metadata
from turn_format import suggestion
from shared_gallery import SharedGallery,branch_refs,background_identity,visual_key,person_identity

EMOTIONS={'neutral':'平静','soft':'温柔','serious':'认真','shy':'害羞','thinking':'思考','listening':'倾听','troubled':'迟疑','surprised':'惊讶','sad':'低落','displeased':'不悦','happy':'愉快','eyes_closed':'闭目'}

class RuntimeV4:
    def init_v4(self):
        self.worlds=WorldLibrary(self.root,self.tavern)
        self.previews=PreviewLibrary(self.root,self.tavern)
        self.shared_gallery=SharedGallery(self.root,self.tavern)
        self.shared_gallery.bootstrap(self.cache)
        self.planner=FlashClient(self.root) if self.provider=='deepseek' else None
        self.planning=set();self.work_queue=queue.PriorityQueue();self.job_order=0
        self.image_service=ImageService(self.cli,self.root,self.engine_env()) if self.cli else None
        self.closed=False
        for key,task in self.image_tasks.items():
            if task.get('speculative') and task.get('scope') and task.get('status')=='failed':self.previews.update(task['scope'],key,status='failed')
        threading.Thread(target=self.image_worker,daemon=True).start()

    def scope(self,session=None):
        # Quotas belong to the root save tree; confirmed art belongs to the script.
        # Shared root quota cannot multiply merely by making a child save.
        return metadata(session or self.current)['root_id']

    def world_snapshot(self,session=None):
        s=session or self.current
        snapshot=s.get('world_snapshot') or s['facts'].get('browser_world_snapshot')
        if snapshot:return copy.deepcopy(snapshot)
        bound=self.worlds.snapshot(s['card_id'])
        if bound.get('id'):return bound
        return {'id':'','name':'角色卡背景','background':s['card_snapshot']['data'].get('scenario',''),'setting_sets':[]}

    def protagonist(self,session=None):
        s=session or self.current
        return copy.deepcopy(s.get('protagonist_snapshot') or s['facts'].get('browser_protagonist_snapshot') or player_snapshot(self.root))

    def actors(self,session=None):
        s=copy.deepcopy(session or self.current);s['world_snapshot']=self.world_snapshot(s)
        actors=registry(s,self.descriptor(s['card_id']))
        try:
            _,record=self.tavern.find_record(self.root,'cards',s['card_id'])
            actors['primary']['aliases']=list(dict.fromkeys(actors['primary']['aliases']+record.get('aliases',[])))
        except (OSError,ValueError):pass
        for key,a in actors.items():
            if key!='primary':
                d=self.descriptor(a['card_id']) if a.get('card_id') else {}
                # Legacy setting entries have no card ID. Match only a unique
                # identity in this world, without rewriting the frozen save.
                if not d:
                    world_id=s['world_snapshot'].get('id','')
                    names={a['name'],*a.get('aliases',[])}-{''}
                    candidates=[m for m in self.manifests.values() if world_id in m.get('world_ids',[])
                        and names.intersection({m.get('name',''),*m.get('aliases',[])})]
                    if len(candidates)==1:d=candidates[0]
                a.update({k:d[k] for k in ('sprites','avatar','reference','default_appearance') if k in d})
        p=self.protagonist(s)
        for key in [k for k,a in actors.items() if a.get('role')=='protagonist' and a['name']==p['name']]:actors.pop(key)
        actors['player']={'id':'player','name':s['user_name'],'aliases':['玩家',p['name']],'appearance':p.get('appearance',''),
            'sprites':{},'avatar':p.get('avatar',''),'reference':p.get('reference',''),'default_appearance':'school-uniform'}
        visual_id=p.get('visual_manifest_id')
        if not visual_id and p['id']=='hachiman' and p.get('appearance')==DEFAULT_PLAYER['appearance']:
            visual_id='oregairu-core-hachiman'
        if visual_id:
            d=self.descriptor(visual_id)
            actors['player'].update({k:d[k] for k in ('sprites','avatar','reference','default_appearance') if k in d})
        return actors

    def state(self):
        with self.lock:return self._state_v4()

    def _state_v4(self):
        result=self.legacy_state();actors=self.actors()
        from perception import current_scene,thoughts
        scene_state=current_scene(self.current,actors,self.frames)
        prepared_frames=copy.deepcopy(self.frames)
        for frame in prepared_frames:
            frame.setdefault('stage',{'location':scene_state['location'],'present_actor_ids':scene_state['present_actor_ids']})
        frames=bind_frames([f for f in prepared_frames if f['kind']!='thought'],actors,self.current['user_name'])
        from story_history import history,cg_cue
        history_key=(self.current['id'],tuple(t['turn_id'] for t in self.current['turns']))
        if getattr(self,'_history_key',None)!=history_key:
            self._history_key=history_key;self._history_cache=history(self.root,self.current)
        result['turns']=copy.deepcopy(self._history_cache)
        result['cg_cue']=cg_cue(self.current,self.visual,self.cache,self.image_tasks)
        if result['cg_cue'] and not self.dynamic_images and not result['cg_cue'].get('url') and result['cg_cue']['key'] not in self.image_tasks:result['cg_cue']={}
        result['scene_state']=scene_state
        result['location']=scene_state['location']
        result['inner_thoughts']=thoughts(self.current,prepared_frames,actors,self.current['turns'][-1]['turn_id'],self.current['scene'])
        from affinity import public as affinity_public
        result['affinity']=affinity_public(self.current,actors,frames)
        for f in frames:
            stage=f.get('stage',{})
            stage_bg=self.cache.get(stage.get('background_asset'),{}).get('url') or self.descriptor().get('backgrounds',{}).get(stage.get('background'))
            if stage_bg:f['background']=stage_bg
            a=actors.get(f['actor_id'],{})
            asset=self.cache.get(f.get('portrait_asset'),{})
            if asset and asset.get('actor_id')==f['actor_id']:
                a=copy.deepcopy(a);a['sprites']=a.get('sprites',{})|{f['expression']:asset['url']};actors[f['actor_id']]=a
        result.update({'frames':frames,'actors':{k:{f:v for f,v in a.items() if f!='initial_affinity'} for k,a in actors.items()},'world_catalog':self.worlds.list(),
            'scripts':self.script_list(),'script_id':self.current.get('script_id') or self.world_snapshot().get('id') or 'card-'+self.current['card_id'],
            'world':{'id':self.world_snapshot().get('id',''),'name':self.world_snapshot().get('name','角色卡背景')},
            'protagonists':[{'id':p['id'],'name':p['name']} for p in player_cards(self.root)],
            'protagonist':{'id':self.protagonist()['id'],'name':self.protagonist()['name']},
            'prediction_library':self.previews.public(self.scope()),
            'image_service':{'persistent':True,'running':bool(self.image_service and self.image_service.proc and self.image_service.proc.poll() is None)}})
        result['story']['choices']=[c|{'text':suggestion(c['text'])} for c in result['story'].get('choices',[])]
        unlocked=self.shared_gallery.unlocked(self.current)
        generated=[x for key,x in unlocked]
        portrait_assets=[x for x in self.cache.values() if x.get('kind')=='portrait' and x.get('actor_id') in actors and not x.get('speculative') and (x.get('world_scope')==__import__('shared_gallery').script_scope(self.current) or not x.get('world_scope') and x.get('card_id')==self.current['card_id'])]
        d=self.descriptor()
        portraits=[];seen=set()
        for actor in actors.values():
            for expression,url in actor.get('sprites',{}).items():
                if url in seen:continue
                seen.add(url);portraits.append({'url':url,'name':actor['name']+' · '+EMOTIONS.get(expression,'人物表情')})
        result['library']={'backgrounds':[{'url':x['url'],'name':self.chinese_name(x,'background')} for x in generated if x.get('kind')=='background'],
            'portraits':portraits+
                [{'url':x['url'],'name':self.chinese_name(x,'portrait')} for x in portrait_assets if x.get('kind')=='portrait']}
        current_bg=self.visual.get('background')
        if current_bg in d.get('backgrounds',{}) and not any(x['url']==d['backgrounds'][current_bg] for x in result['library']['backgrounds']):
            result['library']['backgrounds'].append({'url':d['backgrounds'][current_bg],'name':d.get('background_descriptions',{}).get(current_bg,'故事场景')})
        result['illustrations']=[{'url':x['url'],'name':self.chinese_name(x,'interaction')} for x in generated if x.get('kind')=='cg']
        inherited={n.get('cg_asset') for n in self.current['facts'].get('browser_story',{}).get('nodes',[])}
        for key in inherited:
            x=self.cache.get(key,{})
            if x.get('url') and not any(i['url']==x['url'] for i in result['illustrations']):result['illustrations'].append({'url':x['url'],'name':self.chinese_name(x,'interaction')})
        return result

    def script_list(self):
        catalog=self.worlds.list();worlds=catalog['worlds'];cards={c['id']:c for c in self.card_list()};result=[];covered=set()
        playable=[w for w in worlds if w.get('opening_scenes') and w.get('primary_card_id') in cards]
        # A world's stable identity survives replacing its primary character card.
        # Explicit bindings also retain access to saves made before world snapshots existed.
        owners={}
        for world in playable:
            aliases={world['primary_card_id']}|{cid for cid,b in catalog.get('bindings',{}).items() if b.get('world_id')==world['id']}
            for cid in aliases:owners.setdefault(cid,set()).add(world['id'])
        for world in worlds:
            cid=world.get('primary_card_id')
            if not world.get('opening_scenes') or cid not in cards:continue
            legacy=[key for key,ids in owners.items() if ids=={world['id']}]
            main=cards[cid];covered.add(cid);covered.update(legacy);snapshot=self.worlds.snapshot(cid,world['id'],world['setting_set_ids'])
            cast=[c['name'] for settings in snapshot.get('setting_sets',[]) for c in settings['cards'] if c['kind']=='character']
            result.append({'id':world['id'],'card_id':cid,'world_id':world['id'],'setting_set_ids':world['setting_set_ids'],
                'legacy_card_ids':sorted(legacy),'display_name':world['name'],'bio':world.get('description') or world['background'][:250],
                'scene_intro':'、'.join(s['title'] for s in world['opening_scenes']), 'scenarios':world['opening_scenes'],
                'sprite':main['sprite'],'avatar':main['avatar'],'backgrounds':main['backgrounds'],'cast':cast,
                'default_protagonist_id':world.get('default_protagonist_id','hachiman')})
        # Standalone existing cards remain playable as small legacy scripts.
        for cid,card in cards.items():
            if cid in covered:continue
            _,record=self.tavern.find_record(self.root,'cards',cid)
            if record.get('source','').startswith('setting-set:'):continue
            result.append(card|{'id':'card-'+cid,'card_id':cid,'world_id':'','setting_set_ids':[],
                'display_name':card['display_name']+' · 角色卡剧本','cast':[card['display_name']],'default_protagonist_id':'hachiman'})
        return sorted(result,key=lambda item:item['id']!='oregairu-campus')

    def chinese_name(self,item,kind):
        label=item.get('name','')
        if label and any('\u4e00'<=c<='\u9fff' for c in label):return label[:80]
        return {'background':'故事场景','portrait':'人物立绘','interaction':'故事插图'}[kind]

    def compact_context(self,context):
        result=self.legacy_compact_context(context)
        from story_history import history
        recorded=history(self.root,self.current)
        result['recent_turns']=[{'turn_id':t['turn_id'],'user':t['user'],
            'assistant':'\n'.join(('旁白' if f['kind']=='narration' else f.get('speaker') or '未标注人物')+'：'+f['text'] for f in t['frames']) if t['frames'] else t['assistant']} for t in recorded[-6:]]
        from affinity import context as affinity_context
        result['affinity']=affinity_context(self.current,self.actors(),self.frames)
        recent=self.current.get('scene','')+'\n'+self.current.get('summary','')+'\n'+'\n'.join(t['assistant'][-1500:] for t in self.current['turns'][-2:])
        result['world']=world_context(self.world_snapshot(),context.get('incoming',''),recent)
        relevant=recent+'\n'+context.get('incoming','')
        result['cast']=[{'id':k,'name':a['name'],'aliases':a.get('aliases',[]),'default_appearance':a.get('default_appearance','school-uniform'),
            'appearance':a.get('appearance','')[:1000] if k in {'primary','player'} or any(n and n in relevant for n in [a['name'],*a.get('aliases',[])]) else ''} for k,a in self.actors().items()]
        p=self.protagonist();result['choices']=copy.deepcopy(self.current['facts'].get('browser_story',{}).get('choices',[]))
        result['visual_locations']=self.world_snapshot().get('visual_locations',{})
        result['protagonist']={'name':p['name'],'appearance':p.get('appearance',''),
            'meaning':'采用主角外貌及所选剧本的开篇背景；既有关系以当前存档和initial_relationship为准，不继承未来剧情；不得替玩家决定台词、行动或内心。'}
        result['prepared_visuals']=[{k:v for k,v in e.items() if k in {'key','kind','background','actor_id','appearance','expression','action','scene','name','event_key','background_identity','participant_visuals'}} for e in self.previews.read(self.scope())['entries'].values() if e['status'] in {'ready','queued','painting'} and (e['kind']!='interaction' or e.get('session_id')==self.current['id'])]
        from perception import current_scene,cues,RULES
        result['scene_state']=current_scene(self.current,self.actors(),self.frames)
        result['input_perception_constraints']=cues(result['player_input']['parts'],self.actors())
        result['actor_knowledge']={key:items[-16:] for key,items in self.current['facts'].get('browser_actor_knowledge',{}).items()}
        result['actor_locations']=copy.deepcopy(self.current['facts'].get('browser_actor_locations',{}))
        result['perception_rules']=RULES
        if not result['scene_state']['present_actor_ids'] and not result['scene_state'].get('contacts'):
            result['viewpoint_note']='回合开始玩家身边没有交谈对象。角色卡锚点与此前人物的位置不等于当前在场；原地点人物不能听见本轮语言。不为了回复自语而编造跟随、远程联系、相遇或跨地点心声。以当前地点的玩家视角承接，没有真实到场依据时使用环境旁白。'
        return result

    def note_recover(self,reason):
        with self.lock:self.activity['stage']='recovering';self.activity['recovery']=reason

    def make_job(self,key,kind,detail,session,actor=None,name='',**extra):
        return {'key':key,'kind':kind,'prompt':detail,'session_id':session['id'],'card_id':session['card_id'],
            'actor':copy.deepcopy(actor or {}),'actor_id':(actor or {}).get('id',''),
            'name':name,'protagonist':self.protagonist(session),'scope':self.scope(session),'world_scope':__import__('shared_gallery').script_scope(session),**extra}

    def adopt(self,key):
        entry=self.previews.find(self.scope(),key)
        if not entry:
            entry=next((e for index in self.previews.folder.glob('*/index.json') if (e:=self.previews.find(index.parent.name,key)) and e['status']=='ready'),None)
        if not entry or entry['status'] not in {'ready','used','failed'}:return False
        if entry['status']=='used':return key in self.cache
        if key not in self.cache:
            source=Path(entry.get('path',''));folder=self.root/'browser/assets';folder.mkdir(parents=True,exist_ok=True)
            if not source.is_file():return False
            target=folder/(key+source.suffix.lower())
            if source.resolve()!=target.resolve():shutil.copy2(source,target)
            self.cache[key]=entry|{'kind':'cg' if entry['kind']=='interaction' else entry['kind'],
                'url':'/media/browser/assets/'+target.name,'path':str(target),'speculative':False}
            self.tavern.atomic_json(self.cache_file,self.cache)
            # Another save tree may hold a reservation for the same image.
            # Redirect those refs before removing the one speculative file.
            for index in self.previews.folder.glob('*/index.json'):
                scope=index.parent.name;e=self.previews.find(scope,key)
                if e and e.get('status')!='used':self.previews.update(scope,key,path=str(target),url=self.cache[key]['url'])
            if source.resolve()!=target.resolve() and source.resolve().is_relative_to(self.previews.folder.resolve()):source.unlink(missing_ok=True)
        if entry['status']=='failed':self.previews.update(self.scope(),key,status='ready')
        self.previews.consume(self.scope(),key)
        self.shared_gallery.register(self.current,key,self.cache[key])
        return True

    def gallery_refs(self,reply):
        refs=branch_refs(self.current)
        refs.update(v for k,v in reply['visual'].items() if k in {'background_asset','cg_asset'} and v)
        for f in reply['frames']:
            if f.get('stage',{}).get('background_asset'):refs.add(f['stage']['background_asset'])
        return sorted(refs)

    def participant_visuals(self,frames,actors,visual):
        result={}
        for f in frames:
            key=f.get('actor_id');a=actors.get(key,{})
            visible=f.get('stage',{}).get('visible_actor_ids',f.get('stage',{}).get('present_actor_ids',[]))
            if key!='player' and a.get('appearance') and key in visible and f.get('expression')!='absent' and f['kind']!='thought':
                outfit=f.get('appearance_key') or (visual.get('appearance_key',a.get('default_appearance','school-uniform')) if key=='primary' else a.get('default_appearance','school-uniform'))
                result[key]=person_identity(a,outfit,f['expression'])
        return list(result.values())

    def prepared(self,key):
        e=self.previews.find(self.scope(),key)
        if not e or e.get('status') not in {'ready','used'}:
            e=next((item for index in self.previews.folder.glob('*/index.json') if (item:=self.previews.find(index.parent.name,key)) and item['status']=='ready'),None)
        return key in self.cache or self.image_tasks.get(key,{}).get('status') in {'queued','painting'} or bool(e and e['status'] in {'ready','used'})

    def activate_visuals(self):
        # A rejected or conflicted turn must not consume speculative quota.
        keys={self.visual.get('background_asset'),self.visual.get('cg_asset'),*(f.get('portrait_asset') for f in self.frames)}
        for key in keys:
            if key:
                self.adopt(key)
                if key in self.cache:self.shared_gallery.register(self.current,key,self.cache[key])

    def plan_images(self,reply):
        session=copy.deepcopy(self.current);session['world_snapshot']=self.world_snapshot();actors=self.actors();frames=bind_frames(reply['frames'],actors,session['user_name'],reply.get('scene_state'));reply['frames']=frames
        visual=reply['visual'];jobs=[];bg=visual['background'];d=self.descriptor();scope=self.scope()
        identity=background_identity(session,bg,visual.get('background_identity'))
        key=visual_key(session,'background',background=bg,identity=identity)
        shared=self.shared_gallery.find(session,key)
        if shared:
            key,entry=shared;self.cache.setdefault(key,entry)
            visual['background_asset']=key
        elif bg in d.get('backgrounds',{}):
            # Prefabricated art is reusable too, but only this visited scene unlocks.
            key='builtin-'+__import__('shared_gallery').digest([__import__('shared_gallery').script_scope(session),bg,d['backgrounds'][bg]])
            self.cache[key]={'kind':'background','name':d.get('background_descriptions',{}).get(bg,'故事场景'),'url':d['backgrounds'][bg],
                'background':bg,'background_identity':identity,'visual_key':visual_key(session,'background',background=bg,identity=identity)}
            visual['background_asset']=key
        else:
            visual['background_asset']=key
            if not self.prepared(key) and visual.get('background_prompt'):
                jobs.append(self.make_job(key,'background',visual['background_prompt'],session,name=reply['scene'] or '故事场景',background=bg,background_identity=identity,visual_key=key))
        for frame in frames:
            if frame.get('stage') is not None:
                from perception import same_place
                previous=frame['stage']['location']==self.current.get('facts',{}).get('browser_scene_state',{}).get('location',self.current.get('scene')) and not same_place(frame['stage']['location'],reply.get('scene_state',{}).get('location',reply['scene']))
                frame['stage']['background']=self.visual.get('background') if previous else bg
                inherited=self.visual.get('background_asset') if previous else visual.get('background_asset')
                if inherited:frame['stage']['background_asset']=inherited
            actor=actors.get(frame['actor_id'],{});expr=frame['expression']
            if frame['kind']=='thought':continue
            appearance=frame.get('appearance_key') or (visual.get('appearance_key',actor.get('default_appearance','school-uniform')) if actor.get('id')=='primary' else actor.get('default_appearance','school-uniform'))
            if frame.get('stage') is not None and frame['actor_id'] not in frame['stage'].get('visible_actor_ids',frame['stage']['present_actor_ids']):continue
            if expr=='absent' or not actor.get('appearance') or frame['actor_id']=='player':continue
            key=visual_key(session,'portrait',actor=actor,appearance=appearance,expression=expr)
            candidate=self.previews.find(scope,key)
            if expr in actor.get('sprites',{}) and appearance==actor.get('default_appearance','school-uniform') and not (candidate and candidate['status']=='ready'):continue
            frame['portrait_asset']=key
            detail='外貌：'+actor['appearance']+'；服装状态：'+appearance+'；表情：'+EMOTIONS.get(expr,expr)
            if actor['id']=='primary' and visual.get('portrait_prompt'):detail+='；已确认状态：'+visual['portrait_prompt']
            if not self.prepared(key):jobs.append(self.make_job(key,'portrait',detail,session,actor,actor['name']+' · '+EMOTIONS.get(expr,'人物'),appearance=appearance,expression=expr))
        if reply['illustration']['recommended'] and reply['illustration']['prompt']:
            action=self.activity.get('text','').strip()
            participants=self.participant_visuals(frames,actors,visual)
            protagonist=person_identity(actors['player'])
            event=reply['illustration'].get('event_key') or reply['illustration']['prompt']
            selected=next((e for e in self.previews.read(scope)['entries'].values()
                if e['kind']=='interaction' and e['status'] in {'ready','painting','queued'}
                and e.get('session_id')==session['id'] and e.get('action')==action
                and e.get('background_identity')==identity and e.get('base_turn_id')==(session.get('turns') or [{}])[-1].get('turn_id')
                and e.get('event_key')==event and e.get('participant_visuals')==participants
                and e.get('protagonist_visual')==protagonist),None)
            key=selected['key'] if selected else visual_key(session,'interaction',background=bg,identity=identity,event=event+'\0'+reply['illustration']['prompt'],participants=participants,protagonist=protagonist)
            shared=self.shared_gallery.find(session,key)
            if shared:key,entry=shared;self.cache.setdefault(key,entry)
            visual['cg_asset']=key
            if not self.prepared(key):
                people=[actors[k] for k in dict.fromkeys(f['actor_id'] for f in frames) if k!='player' and actors.get(k,{}).get('appearance') and any(p['identity']==(actors[k].get('card_id') or actors[k]['name']) for p in participants)]
                jobs.append(self.make_job(key,'cg',reply['illustration']['prompt'],session,name=reply['story']['title'],participants=people,
                    background=bg,background_identity=identity,visual_key=key,participant_visuals=participants,protagonist_visual=protagonist,event_key=event))
        return jobs

    def native_image(self,prompt,references,asset_id,scope=None,speculative=False):
        if not self.image_service:raise ValueError('找不到原生生图引擎。')
        job=self.root/'browser/image-jobs'/asset_id
        instruction=('Generate exactly ONE image using the BUILT-IN image generation tool. Do not use shell, scripts, APIs, browser, apps or agents. If unavailable, report UNAVAILABLE and stop. Return only the actual saved image path.\n'+prompt)
        paths=self.image_service.generate(instruction,references,scope or self.current['id']+':background',job)
        env=self.engine_env();allowed=(Path(env.get('CODEX_HOME',str(Path.home()/'.codex')))/'generated_images').resolve()
        for candidate in reversed(paths):
            source=Path(candidate).resolve()
            if source.is_relative_to(allowed) and source.is_file() and source.suffix.lower() in {'.png','.jpg','.webp','.jpeg'}:
                folder=self.previews.folder/'images' if speculative else self.root/'browser/assets'
                folder.mkdir(parents=True,exist_ok=True);target=folder/(asset_id+source.suffix.lower())
                shutil.copy2(source,target)
                return {'path':str(target),'url':('/media/browser/prediction-library/images/' if speculative else '/media/browser/assets/')+target.name}
        raise ValueError('生图服务尚未返回可用画面。')

    def queue_images(self,jobs,session_id,card_id,speculative=False):
        with self.lock:
            for job in jobs:
                key=job['key']
                if key in self.cache:
                    if speculative:self.previews.update(job['scope'],key,status='ready',path=self.cache[key].get('path',''),url=self.cache[key]['url'])
                    continue
                if speculative and self.image_tasks.get(key,{}).get('status')=='ready':
                    ready=next((e for index in self.previews.folder.glob('*/index.json') if (e:=self.previews.find(index.parent.name,key)) and e.get('status')=='ready'),None)
                    if ready:
                        self.previews.update(job['scope'],key,status='ready',path=ready['path'],url=ready['url']);continue
                if self.image_tasks.get(key,{}).get('status') in {'queued','painting'}:continue
                self.image_tasks[key]=copy.deepcopy(job)|{'status':'queued','speculative':speculative}
                self.job_order+=1;self.image_busy+=1
                self.work_queue.put((10 if speculative else 0,self.job_order,key))
            self.tavern.atomic_json(self.tasks_file,self.image_tasks)

    def image_worker(self):
        while not self.closed:
            try:_,_,key=self.work_queue.get(timeout=.5)
            except queue.Empty:continue
            if self.closed:
                self.work_queue.task_done();return
            try:self.render_job(key)
            except Exception:
                # A local diagnostic write must not kill the queue permanently.
                with self.lock:
                    task=self.image_tasks.get(key,{})
                    if task.get('status') in {'queued','painting'}:
                        task['status']='failed';self.image_busy=max(0,self.image_busy-1)
            finally:self.work_queue.task_done()

    def render_job(self,key):
        with self.lock:job=copy.deepcopy(self.image_tasks[key]);self.image_tasks[key]['status']='painting'
        speculative=job.get('speculative',False);kind=job['kind'];actor=job.get('actor',{});refs=[]
        try:
            if speculative:
                for index in self.previews.folder.glob('*/index.json'):
                    if self.previews.find(index.parent.name,key):self.previews.update(index.parent.name,key,status='painting')
            descriptor=self.descriptor(job['card_id'])
            def ref(url):
                if url:
                    p=self.asset_path(url)
                    if p.is_file():refs.append(p)
            if kind=='background':
                bg=descriptor.get('backgrounds',{});ref(bg.get(descriptor.get('default_background'),''))
                prompt='Standalone 16:9 polished anime visual novel environment. No people, UI, text or watermark. '+job['prompt']
            elif kind=='portrait':
                ref(actor.get('reference',''))
                prompt='Exactly one anime visual novel character sprite. Genuine TRANSPARENT background with alpha. Head to mid-thigh, head fully visible. Preserve the described identity and own reference, no other people, no lettering. '+job['prompt']
            else:
                participants=job.get('participants',[])
                for person in participants:ref(person.get('reference',''))
                ref(job['protagonist'].get('reference',''))
                prompt='16:9 polished anime visual novel scene, no text, UI or watermark. Only show the specified people and event. Reference identities belong only to their own specified actors, never borrow another face. Unknown people must be out of frame or viewed from behind. Character identities: '+json.dumps([{'name':a['name'],'appearance':a['appearance']} for a in participants],ensure_ascii=False)+' Player appearance if visible: '+job['protagonist'].get('appearance','')+'. Scene: '+job['prompt']
            scope=job['session_id']+':'+kind+':'+job.get('actor_id','')+(':preview' if speculative else ':confirmed')
            result=self.native_image(prompt,refs,key,scope,speculative)
            with self.lock:
                if speculative:
                    for index in self.previews.folder.glob('*/index.json'):
                        e=self.previews.find(index.parent.name,key)
                        if e and e.get('status')!='used':self.previews.update(index.parent.name,key,status='ready',**result)
                    # If this confirmed scene arrived while its preview was painting,
                    # adopt it now, without generating a duplicate.
                    selected=key in self.visual.values() or any(f.get('portrait_asset')==key for f in self.frames)
                    if selected:self.adopt(key)
                else:
                    self.cache[key]=result|{k:v for k,v in job.items() if k not in {'actor','participants','protagonist','prompt'}}|{'speculative':False}
                    self.tavern.atomic_json(self.cache_file,self.cache)
                    _,saved=self.tavern.find_record(self.root,'sessions',job['session_id']) if (self.root/'sessions'/(job['session_id']+'.json')).exists() else (None,self.current)
                    if key in branch_refs(saved):self.shared_gallery.register(saved,key,self.cache[key])
                    for index in self.previews.folder.glob('*/index.json'):
                        e=self.previews.find(index.parent.name,key)
                        if e and e.get('status')!='used':self.previews.update(index.parent.name,key,status='ready',**result)
                    if key in self.visual.values() or any(f.get('portrait_asset')==key for f in self.frames):self.adopt(key)
                self.image_tasks[key]['status']='ready';self.image_error=''
        except Exception as exc:
            with self.lock:
                self.image_tasks[key]['status']='failed'
                self.image_tasks[key]['error_class']=type(exc).__name__
                if speculative:
                    for index in self.previews.folder.glob('*/index.json'):
                        if self.previews.find(index.parent.name,key):self.previews.update(index.parent.name,key,status='failed')
                else:self.image_error='画面暂未就绪，故事可继续。'
        finally:
            with self.lock:
                self.image_busy=max(0,self.image_busy-1)
                self.tavern.atomic_json(self.tasks_file,self.image_tasks)

    def retry_images(self):
        with self.lock:
            keys={self.visual.get('background_asset'),self.visual.get('cg_asset'),*(f.get('portrait_asset') for f in self.frames)}
            jobs=[copy.deepcopy(self.image_tasks[k])|{'key':k} for k in keys if k in self.image_tasks and self.image_tasks[k]['status']=='failed' and k not in self.cache]
            for job in jobs:
                job.setdefault('scope',self.scope());job.setdefault('protagonist',self.protagonist());job.setdefault('name',self.current['scene'] or '故事场景')
                if job.get('speculative'):self.previews.update(job['scope'],job['key'],status='queued')
                self.queue_images([job],self.current['id'],self.current['card_id'],job.get('speculative',False))
            return self.state()

    def retry_preview(self,key):
        with self.lock:
            entry=self.previews.find(self.scope(),key);task=self.image_tasks.get(key)
            if not entry or entry['status']!='failed' or not task or not task.get('speculative'):raise ValueError('此候选暂不能重试。')
            self.previews.update(self.scope(),key,status='queued')
            self.queue_images([copy.deepcopy(task)],task['session_id'],task['card_id'],True)
            return self.state()

    def prediction_preloads(self):
        return [e['url'] for e in self.previews.read(self.scope())['entries'].values() if e.get('status')=='ready' and e.get('url')]

    def prepare_predictions(self,candidates=None):
        if not self.dynamic_images or not self.image_service or not self.planner:return
        sid=self.current['id'];scope=self.scope()
        if scope in self.planning or not any(self.previews.slots(scope).values()):return
        session=copy.deepcopy(self.current);session['world_snapshot']=self.world_snapshot();session['protagonist_snapshot']=self.protagonist()
        actors=self.actors(session);context=self.compact_context(self.tavern.context(session))
        self.planning.add(scope)
        threading.Thread(target=self.predict,args=(session,actors,context),daemon=True).start()

    def predict(self,session,actors,context):
        scope=self.scope(session);decisions=[]
        try:
            slots=self.previews.slots(scope)
            string={'type':'string'}
            def obj(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
            props={k:string for k in ('kind','name','background','prompt','actor_id','appearance','expression','action','event_key')}
            props['kind']={'type':'string','enum':['background','portrait','interaction']}
            from shared_gallery import scene_schema
            props['background_identity']=scene_schema()
            props['participants']={'type':'array','maxItems':8,'items':obj({'actor_id':string,'appearance':string,'expression':string})}
            schema=obj({'candidates':{'type':'array','maxItems':sum(slots.values()),'items':obj(props)}})
            choices=[suggestion(c['text']) for c in session['facts'].get('browser_story',{}).get('choices',[])]
            known=context.get('scene_state',{}).get('present_actor_ids',[])
            nearby={e['actor_id'] for e in context.get('scene_state',{}).get('nearby_encounters',[])}
            eligible=set(known)|nearby
            outfits={key:list(dict.fromkeys([a.get('default_appearance','school-uniform'),'casual',
                session.get('facts',{}).get('browser_visual',{}).get('appearance_key',a.get('default_appearance','school-uniform')) if key=='primary' else a.get('default_appearance','school-uniform')])) for key,a in actors.items()}
            context=copy.deepcopy(context)
            context['choices']=[{'text':c} for c in choices]
            context['prediction_cast']=[{'id':key,'name':a['name'],'appearance':a.get('appearance',''),
                'outfit_keys':outfits[key],'available_expressions':list(a.get('sprites',{})),'eligible':key in eligible}
                for key,a in actors.items() if key!='player']
            context['existing_candidates']=[{k:v for k,v in e.items() if k in {'kind','background_identity','actor_id','appearance','expression','action','event_key'}}
                for e in self.previews.read(scope)['entries'].values() if e['status']!='used']
            prompt=('只做素材假设，不续写或写入事实。独立考虑background、portrait、interaction三类，每类严格不超过slots；'
                '不要只规划背景。若本类有根据的画面都已存在，则可留空，不虚构事件凑数。'
                '背景使用visual_locations中地点ID；time/weather/season原样取schema英文枚举，layout用standard或稳定布局键，state用normal或door-open等简短状态键，不填描述句，保持与当前画面一致的已知条件。'
                'portrait只选prediction_cast中eligible且有外貌的人，appearance必须原样取outfit_keys，绝不能填整段外貌；'
                'expression从标准neutral/soft/serious/shy/thinking/listening/troubled/surprised/sad/displeased/happy/eyes_closed选，跳过available_expressions已有状态。'
                'interaction只围绕choices一个确切text原样填action；participants填实际入镜的已知人物ID、服装key及表情，不能默认总有主角色，不能添加不在场角色。'
                'event_key简短描述具体可见事件，不是泛泛地点或交流；background_identity对应该画面地点与条件；prompt明确姿态、位置、情绪、服装和事件。'
                'name为中文。不适用字段用空串/空列表；已有候选不可重复、替换或滚动淘汰。\n'+json.dumps({'slots':slots,'context':context},ensure_ascii=False,separators=(',',':')))
            reply=self.planner.generate(prompt,schema,normalizer=None)
            with self.lock:
                if self.closed or self.current['id']!=session['id'] or self.current['revision']!=session['revision']:return
                for c in reply['candidates']:
                    kind=c['kind'];actor=actors.get(c['actor_id'],{});reason=''
                    if not self.previews.slots(scope).get(kind,0):reason='type_quota_full'
                    elif not c['prompt'].strip() or not any('\u4e00'<=ch<='\u9fff' for ch in c['name']):reason='invalid_caption_or_prompt'
                    elif kind=='portrait':
                        if c['actor_id'] not in eligible or not actor.get('appearance') or c['expression'] not in EMOTIONS:reason='portrait_not_relevant'
                        elif c['appearance'] not in outfits[c['actor_id']]:reason='invalid_outfit_key'
                        elif c['expression'] in actor.get('sprites',{}) and c['appearance']==actor.get('default_appearance','school-uniform'):reason='prefabricated_portrait_exists'
                    elif kind=='interaction':
                        if c['action'] not in choices or not c['event_key'].strip():reason='not_current_choice_or_no_event'
                        elif any(a['actor_id'] not in eligible or not actors.get(a['actor_id'],{}).get('appearance') or a['appearance'] not in outfits.get(a['actor_id'],[]) or a['expression'] not in EMOTIONS for a in c['participants']):reason='invalid_participants'
                    elif c['background'] in self.descriptor(session['card_id']).get('backgrounds',{}):reason='prefabricated_background_exists'
                    identity=background_identity(session,c['background'],c['background_identity'])
                    people=[person_identity(actors[a['actor_id']],a['appearance'],a['expression']) for a in c['participants']] if not reason and kind=='interaction' else []
                    protagonist=person_identity(actors['player'])
                    key=visual_key(session,kind,background=c['background'],identity=identity,actor=actor,appearance=c['appearance'],expression=c['expression'],event=c['event_key'],participants=people,protagonist=protagonist)
                    if not reason and (key in self.cache or self.shared_gallery.find(session,key)):reason='confirmed_art_exists'
                    if not reason and self.previews.find(scope,key):reason='already_reserved'
                    decisions.append({'kind':kind,'key':key,'decision':reason or 'reserved'})
                    if reason:continue
                    job=self.make_job(key,'cg' if kind=='interaction' else kind,c['prompt'],session,actor,c['name'],
                        background=c['background'],background_identity=identity,visual_key=key,appearance=c['appearance'],expression=c['expression'],action=c['action'],event_key=c['event_key'],
                        base_turn_id=(session.get('turns') or [{}])[-1].get('turn_id',''),
                        participants=[actors[a['actor_id']] for a in c['participants']] if kind=='interaction' else [],participant_visuals=people,protagonist_visual=protagonist)
                    if self.previews.reserve(scope,key,job|{'kind':kind,'scene':session['scene']}):
                        self.queue_images([job],session['id'],session['card_id'],True)
            self.tavern.atomic_json(self.root/'browser/prediction-library'/scope/'diagnostic.json',
                {'stage':'planned','session_id':session['id'],'slots_before':slots,'slots_after':self.previews.slots(scope),'decisions':decisions})
        except Exception as exc:
            self.tavern.atomic_json(self.root/'browser/prediction-library'/scope/'diagnostic.json',{'stage':'planning','error_class':type(exc).__name__,'session_id':session['id'],'decisions':decisions})
        finally:
            with self.lock:self.planning.discard(scope)

    def close_v4(self):
        self.closed=True
        if getattr(self,'memory_client',None):self.memory_client.close()
        if self.flash:self.flash.close()
        if self.planner:self.planner.close()
        if self.image_service:self.image_service.close()
