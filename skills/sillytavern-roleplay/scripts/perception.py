"""Branch-local physical presence, speech reception and private inner monologues."""
import copy,re,unicodedata
from cast import bind_frames,resolve_actor

PRIVATE=r'心想|暗想|在心里|心里.{0,6}(?:想|念)|(?:我|自己)(?:暗暗)?想道|内心|默念|自言自语|喃喃自语'

RULES='''先按输入parts的顺序更新玩家所在地点、陪同者与人物到场/离场，再判断每个输入片段能被谁感知。一个动作可跨多个地点；对各人物只记录observations.observable_excerpt中实际能感知的原文片段。例如离开房间并前往别处，原房间的人只能看到离开，不能知道后续目的地；看见离开不等于获知整个动作和意图。observable_excerpt从该输入part截取，不扩充原文和后半段。环境变化也按是否在场及发生时间局部生效。context.actor_knowledge是各人物实际获知的记录，整段玩家输入、全局摘要、其他人心声不是每个人的知识。角色资料锚点不是始终在场的对话对象。语言前缀只表示发声，不指定听众；独处时后续普通语言也不能自动传给上一位人物。自言自语没有默认收件人，内心和环境说明不被人物听到。在场不等于能听到：考虑距离、声量、遮挡和实际交谈对象。电话/消息只有已建立或本轮明确建立的contact才跨地点传递。人物不能因玩家离开就擅自跟随、瞬移到新地点，不能把另一地点的嘀咕认作对自己的发言。不擅自切到离场人物的房间/心声来填满回应；可以只有玩家视角的环境旁白。hear也可来自真实敲门、脚步、铃声等物理声音，不把意图当声音。present_actor_ids是近处实际可交互的人；visible_actor_ids仅表示真正看得到的角色，隔门声音不展示立绘或不可知心声。每帧stage是该帧实际地点及在场人物，scene_state是回合结束状态，input_events完整说明各输入片段的接收者。独自转场可先呈现离开前仍在原地点的短反应，离开后清除原陪同人物；新遇见必须有实际到场依据。人物心声只放kind=thought，不写进dialogue或narration，不作为其他人物的知识。'''

def resolve(value,actors,user=''):
    return resolve_actor(value,actors,user)

def same_place(left,right):
    """Compare a location's physical name, not its time-of-day caption."""
    def physical(value):
        if not isinstance(value,str):return ''
        name=re.split(r'[·•|]',value)[-1].strip().replace('侍奉社','侍奉部')
        prefix=r'^(?:总武高中|校内|校园内|学校|秋日午后(?:的)?|放学后(?:的)?|黄昏(?:的)?|傍晚(?:的)?)\s*'
        for _ in range(4):
            updated=re.sub(prefix,'',name)
            if updated==name:break
            name=updated
        name=re.sub(r'(?:门口|门边|入口处)$','',re.sub(r'\s+','',name))
        if name in {'侍奉部活动室','侍奉部室'}:name='侍奉部'
        return name
    a,b=physical(left),physical(right)
    return bool(a and b and a==b)

def utterances(text):
    """Only explicitly voiced/written quotes, excluding private monologues."""
    result=[]
    for match in re.finditer(r'''[“「『"'‘]([^”」』"'’\n]+)[”」』"'’]''',text):
        lead=re.split(r'[。；\n，,]',text[:match.start()])[-1]
        if re.search(PRIVATE,lead):continue
        if re.search(r'没(?:有)?(?:说|开口|回答)|并未|不会|不(?:说|开口|回答)|想(?:说|问)|准备(?:说|问)|打算(?:说|问)',lead):continue
        if re.search(r'说|问|答|应|喊|叫|道|嘀咕|开口',lead):result.append((match.start(1),match.end(1),'hear'))
        elif re.search(r'写|发.{0,6}(?:消息|短信|信息)|打字',lead):result.append((match.start(1),match.end(1),'read'))
    return result

def audible_action(text):
    """A physical sound is neither speech nor the actor's private intention."""
    match=re.search(r'敲(?:了)?(?:敲|响|门)|叩(?:了)?(?:叩|门)|拍(?:了)?(?:拍|响)|摔(?:了)?(?:门|东西)|鼓掌|咳嗽|打喷嚏|(?:门铃|电话|铃声|警报)(?:声)?响|脚步声|雨声|雷声|轰鸣',text)
    if not match:return ''
    lead=re.split(r'[，,。；\n]',text[:match.start()])[-1]
    if re.search(r'准备|打算|想要|心想|在心里|无声|悄无声息|没有|并未|(?:不|没)$',lead):return ''
    if re.search(r'没有.{0,4}声音|没发出.{0,4}声|没有.{0,4}响',text[match.end():match.end()+20]):return ''
    return match[0]

def exact_excerpt(excerpt,text):
    """Repair typography only; return an original slice, never a paraphrase."""
    if not isinstance(excerpt,str) or not excerpt.strip():return excerpt
    excerpt=re.sub(r'^【(?:语言|动作|环境)】\s*','',excerpt.strip())
    if excerpt in text:return excerpt
    def signature(s):
        chars=[];positions=[]
        for i,c in enumerate(s):
            if c.isspace() or c in '“”\"「」『』':continue
            chars.extend(unicodedata.normalize('NFKC',c));positions.extend([i]*len(unicodedata.normalize('NFKC',c)))
        return ''.join(chars),positions
    needle,_=signature(excerpt);haystack,positions=signature(text)
    at=haystack.find(needle)
    if len(needle)>=2 and at>=0:
        start,end=positions[at],positions[at+len(needle)-1]+1
        quotes='“”\"「」『』'
        if excerpt[0] in quotes and start and text[start-1] in quotes:start-=1
        if excerpt[-1] in quotes and end<len(text) and text[end] in quotes:end+=1
        return text[start:end]
    return excerpt

def encounter_evidence(text,actor,allow_typo=False):
    """Physical encounter declarations, not mentions in dialogue/history."""
    for name in [actor['name'],*actor.get('aliases',[])]:
        if not name:continue
        # Single Chinese typo in a >=3-character nickname is accepted only
        # here, where the statement independently describes an encounter.
        pattern=re.escape(name)
        if allow_typo and re.fullmatch(r'[\u4e00-\u9fff]{3,}',name):
            pattern='(?:'+pattern+'|'+'|'.join(re.escape(name[:i])+r'[\u4e00-\u9fff]'+re.escape(name[i+1:]) for i in range(len(name)))+')'
        for clause in re.split(r'[。；\n]',text):
            if re.search(r'回忆|回想|想起|据说|听说|传闻|打算|将会|如果|梦里|视频|照片',clause):continue
            if re.search(r'(?:看见|看到|发现|遇见|遇到|出现|走近|走来|站着|坐着|等着|站在|跟着|同行)[^。；\n]{0,20}'+pattern+'|'+pattern+r'[^。；\n]{0,16}(?:出现|走近|走来|站着|等着|站在|来到|跟着|同行)',clause):return clause
    return ''

def declared_encounters(text,actors):
    exact=[(key,encounter_evidence(text,a)) for key,a in actors.items() if key!='player']
    exact=[entry for entry in exact if entry[1]]
    if exact:return exact
    fuzzy=[(key,encounter_evidence(text,a,True)) for key,a in actors.items() if key!='player']
    fuzzy=[entry for entry in fuzzy if entry[1]]
    return fuzzy if len(fuzzy)==1 else []

def normalize_state(reply,previous,parts,actors,user):
    """Reconcile presentation metadata before causal validation, without
    creating dialogue, hearing, companions or unmentioned arrivals."""
    state=reply.get('scene_state')
    if not isinstance(state,dict):return
    bind_frames(reply.get('frames',[]),actors,user,state)
    # The model cannot invent the player's private thoughts. These frames are
    # redundant even when the player explicitly supplied a thought as input.
    original=reply.get('frames',[])
    retained={i:f for i,f in enumerate(original) if not (f.get('kind')=='thought' and resolve(f.get('speaker'),actors,user)=='player')}
    remapped={old:new for new,old in enumerate(retained)}
    reply['frames']=list(retained.values())
    for f in reply['frames']:
        if 'reply_to_frame' in f and f['reply_to_frame'] in remapped:f['reply_to_frame']=remapped[f['reply_to_frame']]
    events=state.get('input_events')
    if len(parts)==1 and isinstance(events,list) and len(events)>1 and all(isinstance(e,dict) for e in events):
        # Models may describe speaking and moving as separate events inside
        # one supplied input part. Merge evidence, not story; each observation
        # still has to be an observable slice of that original part.
        indices={e.get('part_index') for e in events}
        mode=parts[0]['kind'] if parts[0]['kind']!='speech' else events[0].get('mode')
        merged={'part_index':0,'mode':mode,'recipient_ids':[], 'evidence':parts[0]['text'],'observations':[]}
        for e in events:
            merged['recipient_ids'].extend(e.get('recipient_ids') or [])
            merged['observations'].extend(e.get('observations') or [])
        state['input_events']=[merged]
        for f in reply.get('frames',[]):
            if isinstance(f.get('reaction_to'),list):f['reaction_to']=list(dict.fromkeys(0 if i in indices else i for i in f['reaction_to']))
    def canonical(values):
        if not isinstance(values,list):return values
        return list(dict.fromkeys(resolve(v,actors,user) or v for v in values if resolve(v,actors,user)!='player'))
    state['present_actor_ids']=canonical(state.get('present_actor_ids'))
    if 'visible_actor_ids' in state:state['visible_actor_ids']=canonical(state['visible_actor_ids'])
    physical='\n'.join(p['text'] for p in parts if p['kind'] in {'action','environment'})
    occluded=bool(re.search(r'视线.{0,5}(?:墙|门).{0,5}(?:挡|遮)|看不见.{0,8}(?:室内|屋内|房间内)',physical))
    hidden=set(previous.get('present_actor_ids',[]))-set(previous.get('visible_actor_ids',previous.get('present_actor_ids',[])))
    emerged={resolve(e.get('actor_id'),actors,user) for e in state.get('arrivals',[]) if re.search(r'走出|来到门外|探出|出现在门外',e.get('evidence',''))}
    obscured=hidden-emerged if occluded else set()
    if obscured:
        state['visible_actor_ids']=[k for k in state.get('visible_actor_ids',state['present_actor_ids']) if k not in obscured]
    for f in reply.get('frames',[]):
        if isinstance(f.get('stage'),dict):
            f['stage']['present_actor_ids']=canonical(f['stage'].get('present_actor_ids'))
            if 'visible_actor_ids' in f['stage']:f['stage']['visible_actor_ids']=canonical(f['stage']['visible_actor_ids'])
            if obscured:f['stage']['visible_actor_ids']=[k for k in f['stage'].get('visible_actor_ids',f['stage']['present_actor_ids']) if k not in obscured]
        if 'audience_ids' in f:f['audience_ids']=canonical(f['audience_ids'])
        speaker=resolve(f.get('speaker'),actors,user)
        if speaker and speaker!='player':f['speaker']=actors[speaker]['name']
    for group in ('arrivals','contacts'):
        for entry in state.get(group,[]):entry['actor_id']=resolve(entry.get('actor_id'),actors,user) or entry.get('actor_id')
    for event in state.get('input_events',[]):
        event['recipient_ids']=canonical(event.get('recipient_ids'))
        index=event.get('part_index')
        if type(index)is not int or not 0<=index<len(parts):continue
        text=parts[index]['text']
        for observation in event.get('observations',[]):
            observation['actor_id']=resolve(observation.get('actor_id'),actors,user) or observation.get('actor_id')
            excerpt=exact_excerpt(observation.get('observable_excerpt'),text)
            # A hear/read record may include the introductory speaking action.
            # Keep only the actual quoted words, never the later movement.
            if parts[index]['kind']!='speech' and isinstance(excerpt,str):
                for start,end,sense in utterances(text):
                    if observation.get('sense')==sense and text[start:end] in excerpt and len(excerpt)>end-start:
                        excerpt=text[start:end];break
                if observation.get('sense')=='see' and excerpt in text:
                    private=re.search(r'(?:准备|打算|决定|想要)(?:去|回|下|上|离开|前往|说|问)|思索|思考|'+PRIVATE,excerpt)
                    if private:excerpt=excerpt[:private.start()].rstrip('，,。；;：: ')
            observation['observable_excerpt']=excerpt
            if parts[index]['kind']!='speech' and observation.get('sense')=='hear' and isinstance(excerpt,str):
                sound=audible_action(excerpt)
                if sound and not any(excerpt in text[start:end] for start,end,sense in utterances(text) if sense=='hear'):
                    observation['observable_excerpt']=sound
        # With a wall still blocking the view, retain sound but do not give an
        # unseen indoor person visual knowledge of the player's hidden stance.
        if obscured and isinstance(event.get('observations'),list):
            event['observations']=[o for o in event['observations'] if not (o.get('sense')=='see' and o.get('actor_id') in obscured)]
        # observations are the actual evidence. Reconcile the redundant
        # recipient list from nonempty records; causal checks still apply to
        # every observer below. Empty placeholders grant no knowledge.
        observations=event.get('observations')
        if isinstance(observations,list) and isinstance(event.get('recipient_ids'),list):
            event['observations']=[o for o in observations if o.get('actor_id')!='player' and (o.get('observable_excerpt') or o.get('actor_id') in event['recipient_ids'])]
            for o in event['observations']:
                if isinstance(o.get('observable_excerpt'),str) and o['observable_excerpt'].strip() and o.get('actor_id') not in event['recipient_ids']:event['recipient_ids'].append(o.get('actor_id'))
    # An explicitly depicted arrival need not be redundantly named in a
    # separate metadata array. Derive its evidence from this very scene.
    arrivals=state.get('arrivals')
    if not isinstance(arrivals,list):return
    seen={e.get('actor_id') for e in arrivals}
    candidates=set(state.get('present_actor_ids') or [])
    for f in reply.get('frames',[]):candidates.update(f.get('stage',{}).get('present_actor_ids') or [])
    for key in candidates-set(previous.get('present_actor_ids',[]))-seen:
        a=actors.get(key)
        if not a:continue
        evidence=next((dict(declared_encounters(p['text'],actors))[key] for p in parts if p['kind']!='speech' and key in dict(declared_encounters(p['text'],actors))),'')
        if not evidence:
            evidence=next((encounter_evidence(f['text'],a) for f in reply.get('frames',[]) if f.get('kind')=='narration' and key in f.get('stage',{}).get('present_actor_ids',[]) and encounter_evidence(f['text'],a)),'')
        if not evidence and same_place(state.get('location'),previous.get('location')):
            evidence=next((e['evidence'] for e in previous.get('nearby_encounters',[]) if e['actor_id']==key),'')
        if evidence:arrivals.append({'actor_id':key,'evidence':evidence,**({'name':a['name']} if a.get('provisional') else {})})
    # Reacting to one's own declared entry is an initiative, not receipt of
    # the director's environment instruction. Never repair unheard speech,
    # private words or movements this way.
    events={e.get('part_index'):e for e in state.get('input_events',[])}
    arrived={e.get('actor_id') for e in arrivals}
    for f in reply.get('frames',[]):
        speaker=resolve(f.get('speaker'),actors,user)
        if speaker not in arrived or speaker not in f.get('stage',{}).get('present_actor_ids',[]):continue
        references=f.get('reaction_to')
        if not isinstance(references,list):continue
        f['reaction_to']=[i for i in references if not (
            type(i)is int and 0<=i<len(parts) and parts[i]['kind']=='environment'
            and not re.search(r'心想|暗想|自言自语|喃喃自语|[“「『\"]',parts[i]['text'])
            and speaker not in events.get(i,{}).get('recipient_ids',[])
            and encounter_evidence(parts[i]['text'],actors[speaker]))]

def cues(parts,actors):
    # Explicit local constraints only. The model handles ordinary spatial meaning.
    physical='\n'.join(p['text'] for p in parts if p['kind'] in {'action','environment'})
    alone=bool(re.search(r'独自一人|我[^。；\n]{0,8}(?:离开|回到|走到|来到|前往|去往)|离开[^。；\n]{0,30}(?:前往|去往|来到|走到)|独自(?:走|回|前往|来到|到达)|(?:只有|仅有|就)我一个人|空无一人|四周无人',physical))
    named_arrivals=[]
    for key,a in actors.items():
        if key=='player':continue
        for name in [a['name'],*a.get('aliases',[])]:
            if name and re.search(r'(?:看见|看到|遇见|遇到|发现|带着|和|与)[^。；\n]{0,16}'+re.escape(name)+'|'+re.escape(name)+r'[^。；\n]{0,12}(?:来到|走来|在这里|在那|等着|跟来|跟着|同行)',physical):
                named_arrivals.append(key);break
    private=[]
    for i,p in enumerate(parts):
        s=p['text']
        outside=re.sub(r'''[“「『"'‘][^”」』"'’\n]*[”」』"'’]''','',s)
        marker=re.search(PRIVATE,s)
        audible=bool(re.search(r'听见|听到|让.{0,8}听|对着|对.{0,8}说',outside))
        inner=marker and marker[0] not in {'自言自语','喃喃自语'}
        if p['kind']=='thought' or marker and (inner or not audible):private.append(i)
    return {'unaccompanied_departure':alone,'explicit_companions_or_encounters':named_arrivals,'private_part_indexes':private}

def current_scene(session,actors,frames,parts=None):
    saved=session.get('facts',{}).get('browser_scene_state')
    if isinstance(saved,dict):
        result=copy.deepcopy(saved)
        # Older turns could show someone at a distance without recording their
        # presence. Expose that local encounter as a candidate, not a listener.
        nearby=[]
        last=(session.get('turns') or [{}])[-1].get('user','')
        for match in re.finditer(r'【(?:环境|动作)】([^【]+)',last):
            for key,evidence in declared_encounters(match[1],actors):
                if key=='player' or key in result.get('present_actor_ids',[]):continue
                if evidence:nearby.append({'actor_id':key,'evidence':evidence})
        if nearby:result['nearby_encounters']=nearby
        return result
    # Legacy inference is read-only and explicitly uncertain; never edit a save.
    bound=bind_frames(frames,copy.deepcopy(actors),session['user_name'])
    present=list(dict.fromkeys(f['actor_id'] for f in bound if f.get('kind')=='dialogue' and f.get('expression')!='absent' and f['actor_id'] in actors and f['actor_id']!='player'))
    recent=session.get('turns',[])[-2:]
    old_input='\n'.join(t.get('user','') for t in recent)
    location=session.get('scene','')
    if cues([{'kind':'action','text':old_input}],actors)['unaccompanied_departure'] or re.search(r'自言自语|喃喃自语|在心里',old_input):
        present=[]
        claims=re.findall(r'(?:前往|去往|回到|走到|来到)(?:了)?([^，。；\n“”：:]{1,40})',old_input)
        if claims:location=claims[-1].strip()
    return {'location':location,'present_actor_ids':present,'contacts':[], 'input_events':[], 'arrivals':[], 'legacy_uncertain':True}

def validate(reply,previous,parts,actors,user):
    state=reply.get('scene_state')
    if not isinstance(state,dict):raise ValueError('scene_state: presence and reception required')
    normalize_state(reply,previous,parts,actors,user)
    def ids(values,label):
        if not isinstance(values,list):raise ValueError(label+': array required')
        mapped=[resolve(v,actors,user) for v in values]
        if any(not isinstance(v,str) or not k or k=='player' for v,k in zip(values,mapped)):raise ValueError(label+': unknown NPC identity')
        if len(mapped)!=len(set(mapped)):raise ValueError(label+': duplicate identity')
        return mapped
    present=ids(state.get('present_actor_ids'),'scene_state.present_actor_ids');state['present_actor_ids']=present
    if not isinstance(state.get('location'),str) or not state['location'].strip():raise ValueError('scene_state.location: current player location required')
    contacts=state.get('contacts')
    if not isinstance(contacts,list):raise ValueError('scene_state.contacts: array required')
    remote=set()
    for contact in contacts:
        key=resolve(contact.get('actor_id'),actors,user)
        if not key or key=='player' or contact.get('channel') not in {'phone','text'} or not contact.get('evidence','').strip():raise ValueError('contacts: actual phone/message connection required')
        contact['actor_id']=key;remote.add(key)
    events=state.get('input_events')
    if not isinstance(events,list) or len(events)!=len(parts):raise ValueError('input_events: one event for every input part required')
    indexed={e.get('part_index'):e for e in events}
    if set(indexed)!=set(range(len(parts))):raise ValueError('input_events.part_index: missing or repeated part')
    constraints=cues(parts,actors)
    departing=constraints['unaccompanied_departure'] and not same_place(state['location'],previous.get('location'))
    for index,part in enumerate(parts):
        event=indexed[index];recipients=ids(event.get('recipient_ids'),'input_events.recipient_ids');event['recipient_ids']=recipients
        mode=event.get('mode');evidence=event.get('evidence','')
        if part['kind']=='thought' and (mode!='thought' or recipients):raise ValueError('input_events: explicit inner thought has no listener')
        if mode not in {'spoken','self_talk','thought','action','environment'} or not isinstance(evidence,str) or not evidence.strip():raise ValueError('input_events: perception mode and evidence required')
        spoken=utterances(part['text'])
        if part['kind']!='speech' and mode=='spoken' and not spoken:raise ValueError('input_events: action/environment has no actual utterance')
        observations=event.get('observations')
        if not isinstance(observations,list):raise ValueError('input_events.observations: scoped observable excerpts required')
        observers=set()
        for observation in observations:
            key=resolve(observation.get('actor_id'),actors,user);excerpt=observation.get('observable_excerpt','')
            if not key or key not in recipients or not isinstance(excerpt,str) or not excerpt.strip() or excerpt not in part['text'] or observation.get('sense') not in {'see','hear','read'}:raise ValueError('observations: exact observable input fragment and sense required')
            quoted=any(sense==observation['sense'] and excerpt in part['text'][start:end] for start,end,sense in spoken)
            physical_sound=observation['sense']=='hear' and bool(audible_action(excerpt)) and bool(audible_action(part['text']))
            if part['kind']!='speech' and observation['sense'] in {'hear','read'} and not quoted and not physical_sound:raise ValueError('observations: not spoken, no actual physical sound or sent message in observable fragment')
            observation['actor_id']=key;observers.add(key)
            if index in constraints['private_part_indexes']:
                marker=re.search(PRIVATE,part['text'])
                if mode in {'self_talk','thought','spoken'} or marker and part['text'].find(excerpt)>=marker.start():raise ValueError('observations: private words/thoughts cannot be observed')
            # A departed observer may see the exit, never the subsequent destination.
            departure=re.search(r'离开[^。；\n]{0,30}?(?=前往|去往|来到|走到)',part['text'])
            if departure and key in previous.get('present_actor_ids',[]) and key not in present and part['text'].find(excerpt)+len(excerpt)>departure.end():
                prefix=part['text'][:departure.end()].rstrip('，,。；; ')
                raise ValueError('observations: observer sees departure, not the later destination; part_index='+str(index)+'；'+key+'只能观察原文离开片段“'+prefix+'”，重写这一条observable_excerpt，不含目的地及后续内心，并核对其对白也不提及未知目的地。')
        if observers!=set(recipients):raise ValueError('observations: every recipient needs its own observable fragment')
        if mode=='thought' and recipients:raise ValueError('input_events: thoughts have no recipient')
    arrivals=state.get('arrivals')
    if not isinstance(arrivals,list):raise ValueError('scene_state.arrivals: array required')
    arrived=set()
    for entry in arrivals:
        key=resolve(entry.get('actor_id'),actors,user)
        if not key or key=='player' or not isinstance(entry.get('evidence'),str) or not entry['evidence'].strip():raise ValueError('arrivals: identity and actual arrival evidence required')
        entry['actor_id']=key;arrived.add(key)
    new_encounters=arrived-set(previous.get('present_actor_ids',[]))
    if any(re.search(r'(?:只有|仅有|就)我一个人|空无一人|四周无人',p['text']) for p in parts if p['kind']!='speech'):new_encounters=set()
    permitted_after_departure=set(constraints['explicit_companions_or_encounters'])|new_encounters
    if departing and set(present)-permitted_after_departure:raise ValueError('presence: player leaves without companions; old companions cannot follow or teleport')
    # Contacts need a connection in the established state or a concrete action.
    established={c['actor_id'] for c in previous.get('contacts',[])}
    if remote-established and not any(re.search(r'电话|通话|拨打|接听|消息|短信|发信|打字',p['text']) for p in parts):raise ValueError('contacts: no phone or message action establishes remote hearing')
    all_present=set(previous.get('present_actor_ids',[]))|set(present)|arrived
    if set(present)-set(previous.get('present_actor_ids',[]))-arrived and not previous.get('legacy_uncertain'):raise ValueError('presence: new encounter needs arrival evidence')
    if departing:all_present=permitted_after_departure
    for f in reply['frames']:
        stage=f.get('stage')
        if not isinstance(stage,dict) or not isinstance(stage.get('location'),str) or not stage['location'].strip():raise ValueError('frames.stage: actual viewpoint location required')
        onstage=ids(stage.get('present_actor_ids'),'frames.stage.present_actor_ids');stage['present_actor_ids']=onstage
        visible=ids(stage.get('visible_actor_ids',onstage),'frames.stage.visible_actor_ids')
        if set(visible)-set(onstage):raise ValueError('visibility: visible NPC must be physically nearby')
        if 'visible_actor_ids' in stage:stage['visible_actor_ids']=visible
        allowed_here=all_present|set(previous.get('present_actor_ids',[])) if same_place(stage['location'],previous.get('location')) else all_present
        if set(onstage)-allowed_here:raise ValueError('frames.stage: arrival must have a concrete cause')
        speaker=resolve(f.get('speaker',''),actors,user)
        if f['kind'] in {'dialogue','thought'} and speaker!='player' and speaker not in set(onstage)|remote:raise ValueError('frames: offstage NPC cannot speak or think in player viewpoint')
        if f['kind']=='thought' and speaker in remote and speaker not in onstage:raise ValueError('frames: remote private thoughts cannot leak into player viewpoint')
        if f['kind']=='thought' and speaker!='player' and speaker not in visible:raise ValueError('frames: unseen NPC private thoughts cannot leak into player viewpoint')
    for event in events:
        allowed=set().union(*(set(f['stage']['present_actor_ids']) for f in reply['frames']))|remote|set(previous.get('present_actor_ids',[]))
        if departing:allowed=permitted_after_departure|remote|set(previous.get('present_actor_ids',[]))
        if set(event['recipient_ids'])-allowed:raise ValueError('input_events: recipient cannot hear from a different place without contact')
    # Same-turn NPC exchanges must have an earlier, audible source. Remote
    # speech defaults to no local audience unless explicitly established.
    for index,f in enumerate(reply['frames']):
        if 'audience_ids' in f:
            audience=ids(f['audience_ids'],'frames.audience_ids');f['audience_ids']=audience
            if set(audience)-set(f['stage']['present_actor_ids'])-remote:raise ValueError('audience: listener must be near or connected')
            if f['kind']!='dialogue' and audience:raise ValueError('audience: inner thoughts/narration are not broadcast speech')
        source=f.get('reply_to_frame')
        if source is not None:
            if type(source)is not int or not 0<=source<index or reply['frames'][source]['kind']!='dialogue':raise ValueError('reply_to_frame: earlier dialogue required')
            origin=reply['frames'][source]
            audience=origin.get('audience_ids',origin['stage']['present_actor_ids'] if resolve(origin['speaker'],actors,user) in origin['stage']['present_actor_ids'] else [])
            if resolve(f['speaker'],actors,user) not in audience:raise ValueError('reply_to_frame: speaker did not hear the source dialogue')
    # A reply can use only the inputs actually perceived by its speaker.
    for f in reply['frames']:
        references=f.get('reaction_to',[]);speaker=resolve(f.get('speaker',''),actors,user)
        if not isinstance(references,list) or any(type(i)is not int or i not in indexed for i in references):raise ValueError('frames.reaction_to: valid input indexes required; only '+str(sorted(indexed))+' are input parts, not internal steps')
        if f['kind'] in {'dialogue','thought'} and speaker!='player' and any(speaker not in indexed[i]['recipient_ids'] for i in references):raise ValueError('frames.reaction_to: NPC cannot answer an unperceived input')
    if not any(f['kind']!='thought' for f in reply['frames']):raise ValueError('frames: provide a player-visible story frame; thoughts use the side window')
    if not set(present).issubset(set(reply['frames'][-1]['stage']['present_actor_ids'])):raise ValueError('scene_state: final presence must match final frame')
    if set(present)!=set(reply['frames'][-1]['stage']['present_actor_ids']):raise ValueError('scene_state: final presence differs from final frame')
    final_visible=reply['frames'][-1]['stage'].get('visible_actor_ids')
    if 'visible_actor_ids' in state:
        visible=ids(state['visible_actor_ids'],'scene_state.visible_actor_ids')
        if set(visible)-set(present):raise ValueError('visibility: final visible NPC must be nearby')
        if final_visible is not None and set(visible)!=set(final_visible):raise ValueError('visibility: final visible actors differ from final frame')
    elif final_visible is not None:state['visible_actor_ids']=list(final_visible)
    if not present:reply['visual']['expression']='absent'
    return state

def thoughts(session,frames,actors,turn_id,scene):
    history=copy.deepcopy(session.get('facts',{}).get('browser_inner_thoughts',[]))
    for index,f in enumerate(bind_frames(frames,copy.deepcopy(actors),session['user_name'])):
        if f['kind']!='thought' or f['actor_id']=='player':continue
        key=f'{turn_id}:{index}'
        if any(entry.get('id')==key for entry in history):continue
        history.append({'id':key,'turn_id':turn_id,'actor_id':f['actor_id'],'name':f.get('speaker') or actors.get(f['actor_id'],{}).get('name',''), 'text':f['text'],'scene':scene})
    return history

def knowledge(session,state,turn_id,frames=None):
    result=copy.deepcopy(session.get('facts',{}).get('browser_actor_knowledge',{}))
    for event in state['input_events']:
        for observation in event['observations']:
            key=observation['actor_id'];entries=result.setdefault(key,[])
            entries.append({'turn_id':turn_id,'part_index':event['part_index'], 'sense':observation['sense'],'observed':observation['observable_excerpt']})
    for frame in frames or []:
        if frame['kind']!='dialogue':continue
        speaker=frame.get('actor_id')
        local=frame.get('stage',{}).get('present_actor_ids',[])
        for key in frame.get('audience_ids',local if speaker in local else []):
            result.setdefault(key,[]).append({'turn_id':turn_id,'source_speaker':frame.get('speaker',''), 'sense':'hear','observed':frame['text']})
    return result

def positions(session,previous,state,frames):
    result=copy.deepcopy(session.get('facts',{}).get('browser_actor_locations',{}))
    for key in previous.get('present_actor_ids',[]):result.setdefault(key,previous['location'])
    for frame in frames:
        for key in frame.get('stage',{}).get('visible_actor_ids',frame.get('stage',{}).get('present_actor_ids',[])):result[key]=frame['stage']['location']
    for key in state.get('visible_actor_ids',state['present_actor_ids']):result[key]=state['location']
    return result
