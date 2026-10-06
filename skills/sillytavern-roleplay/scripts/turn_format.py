"""Normalize optional presentation metadata without inventing dialogue or facts."""
import copy
import hashlib
import json
import re
from affinity import normalize_changes

EXPRESSIONS={'neutral','soft','serious','shy','thinking','listening','troubled','surprised','sad','displeased','happy','eyes_closed','absent'}
ALIASES={'平静':'neutral','温柔':'soft','认真':'serious','害羞':'shy','思考':'thinking','倾听':'listening',
         '迟疑':'troubled','惊讶':'surprised','低落':'sad','不悦':'displeased','愉快':'happy','闭目':'eyes_closed',
         'smile':'soft','smiling':'soft','embarrassed':'shy','angry':'displeased','worried':'troubled'}
def expression(value):return value if isinstance(value,str) and value in EXPRESSIONS else ALIASES.get(str(value),'neutral')
def plain(value):return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'))
def normalize(reply,context):
    if not isinstance(reply,dict):raise ValueError('reply: object required')
    result=copy.deepcopy(reply)
    if not isinstance(result.get('frames'),list) or not result['frames']:
        raise ValueError('frames: dialogue required')
    name=context.get('character',{}).get('name','')
    frames=[]
    for index,frame in enumerate(result['frames']):
        if not isinstance(frame,dict) or not isinstance(frame.get('text'),str) or not frame['text'].strip():
            raise ValueError(f'frames[{index}].text: nonempty text required')
        kind={'speech':'dialogue','台词':'dialogue','对话':'dialogue','action':'narration','旁白':'narration','心声':'thought'}.get(frame.get('kind'),frame.get('kind'))
        item={'kind':kind,'speaker':frame.get('speaker') or (name if kind=='dialogue' else ''),
              'text':frame['text'],'expression':expression(frame.get('expression'))}
        if 'stage' in frame:item['stage']=copy.deepcopy(frame['stage'])
        if 'reaction_to' in frame:item['reaction_to']=copy.deepcopy(frame['reaction_to'])
        for field in ('audience_ids','reply_to_frame'):
            if field in frame:item[field]=copy.deepcopy(frame[field])
        if isinstance(frame.get('appearance_key'),str):item['appearance_key']=frame['appearance_key']
        frames.append(item)
    result['frames']=frames
    for field in ('scene','summary'):
        if result.get(field) is None:result[field]=context.get(field,'')
    for field in ('facts','relationships'):
        value=result.get(field) or []
        if isinstance(value,dict):value=[{'key':k,'value':plain(v)} for k,v in value.items()]
        if isinstance(value,list):
            value=[{'key':p.get('key'),'value':plain(p.get('value'))} if isinstance(p,dict) and 'value' in p else p for p in value]
        result[field]=value
    if result.get('memories') is None:result['memories']=[]
    previous=context.get('previous_visual',{})
    visual=result.get('visual') if isinstance(result.get('visual'),dict) else {}
    key=visual.get('background') or previous.get('background','clubroom')
    if isinstance(key,str) and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',key):
        key='scene-'+hashlib.sha256(key.encode()).hexdigest()[:20]
    result['visual']={'background':key,'background_prompt':visual.get('background_prompt') or '',
        'portrait_prompt':visual.get('portrait_prompt') or '',
        'appearance_key':visual.get('appearance_key') or previous.get('appearance_key','school-uniform'),
        'expression':expression(visual.get('expression') or frames[-1]['expression'])}
    if isinstance(visual.get('background_identity'),dict):result['visual']['background_identity']=copy.deepcopy(visual['background_identity'])
    story=result.get('story') if isinstance(result.get('story'),dict) else {}
    choices=story.get('choices') if isinstance(story.get('choices'),list) else []
    choices=[{'label':c['label'],'text':suggestion(c['text'])} for c in choices[:3] if isinstance(c,dict) and all(isinstance(c.get(k),str) and c[k].strip() for k in ('label','text'))]
    result['story']={'title':story.get('title') or (result['scene'][:24] if isinstance(result['scene'],str) else '故事延续'),
        'beat':story.get('beat') or 'development','milestone':story.get('milestone') is True,
        'thread':story.get('thread') or '', 'choices':choices}
    if isinstance(result['story']['thread'],str):result['story']['thread']=result['story']['thread'][:500]
    if isinstance(result['story']['title'],str):result['story']['title']=result['story']['title'][:100]
    illustration=result.get('illustration') if isinstance(result.get('illustration'),dict) else {}
    result['illustration']={'recommended':illustration.get('recommended') is True,
        'reason':illustration.get('reason') or '', 'prompt':illustration.get('prompt') or ''}
    if isinstance(illustration.get('event_key'),str):result['illustration']['event_key']=illustration['event_key']
    # Prediction is optional work. Malformed guesses never discard good dialogue.
    predictions=result.get('predictions') or []
    if not isinstance(predictions,list):predictions=[]
    result['predictions']=[]
    for candidate in predictions[:2]:
        if not isinstance(candidate,dict):continue
        key=candidate.get('background')
        probability=candidate.get('confidence')
        if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',key) or type(probability) not in (int,float) or not 0<=probability<=1 or not isinstance(candidate.get('background_prompt',''),str):continue
        result['predictions'].append({'background':key,'background_prompt':candidate.get('background_prompt') or '',
            'expression':expression(candidate.get('expression')),'confidence':probability})
    result['affinity_changes']=normalize_changes(result.get('affinity_changes',[]))
    if 'scene_state' in reply:result['scene_state']=copy.deepcopy(reply['scene_state'])
    if 'scene_state' in result and context.get('cast'):
        from perception import normalize_state
        actors={a['id']:copy.deepcopy(a) for a in context['cast']}
        normalize_state(result,context.get('scene_state',{}),context.get('player_input',{}).get('parts',[]),actors,context.get('user_name',''))
    return {key:result[key] for key in ('frames','scene','summary','facts','relationships','memories','visual','story','predictions','illustration','affinity_changes','scene_state','world_updates') if key in result}

def suggestion(value):
    value=value.strip()
    if re.search(r'【(?:语言|动作|环境|内心)】',value):return value
    value=re.sub(r'^(语言|动作|环境|内心)\s*[:：]',lambda m:'【'+m[1]+'】',value)
    if value.startswith('【'):return value
    if value.startswith('*') and value.endswith('*'):return '【动作】'+value.strip('*')
    if value.startswith(('“','"')):return '【语言】'+value.strip('“”"')
    return '【语言】'+value
