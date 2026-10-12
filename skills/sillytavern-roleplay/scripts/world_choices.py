"""Optional, branch-local suggestions. Never write world state or reuse old choices."""
import copy
import re

from actor_context import validate_no_literal_leak
from world_state import location


CONTRACT = '''只输出 JSON {"choices":[{"label":"简短标题","text":"【语言】主角可说的话或【动作】主角自己的尝试"}]}。
根据当前地点、本轮已公开的对白和主角已知信息，给0至3个简短、互有区别的可选回应。
回应当前具体话题，不能每轮重复开场推荐。玩家仍可自由输入，不自动接任务、不强推方向。
只能写主角自己的语言或尝试，不替NPC决定、说话或完成行动；不要把建议写成已发生的事实。
不能引用未获知的姓名、他人目标、心声、异地活动或秘密，不编造过去经历、物品或能力。
【动作】若需要许可只能建议提出请求或尝试，不能保证获得同意。没有听众时不要推荐对人说话。
遇到行动拒绝或待澄清时不要重复被拒绝行为；可建议说明自己的意图。没有合适方向时choices=[]。'''


def suggestion_context(state, definition, frames, input_status=None, protagonist=None):
    from model_context import working_view
    from types import SimpleNamespace
    view = working_view(SimpleNamespace(state=state, definition=definition, records=[]), 'player')
    if protagonist:
        view['character'] = {k: copy.deepcopy(protagonist[k]) for k in
                             ('name', 'description', 'appearance') if k in protagonist}
    # Diagnostic cards and shared NPC goals are not story guidance.
    view['cards'] = [c for c in view['cards'] if c['template'] in
                     ('knowledge', 'item', 'relation', 'observation', 'opportunity', 'location')
                     or c['template'] == 'goal' and c['value'].get('owner') == 'player']
    here = location(state, 'player')
    public = []
    for frame in frames:
        if frame.get('kind') not in ('dialogue', 'narration') or frame.get('system_feedback'):
            continue
        if frame.get('stage', {}).get('location') != here:
            continue
        # Speaker labels in the reader UI need not be names known in-world.
        public.append({'kind': frame['kind'], 'text': frame.get('text', '')[:700]})
    return {'view': view, 'recent_scene': public[-6:], 'input_status': input_status or 'accepted'}


def validate_choices(answer, state, definition, context):
    if not isinstance(answer, dict):
        raise ValueError('Suggestions require a JSON object')
    choices = answer.get('choices')
    if not isinstance(choices, list) or len(choices) > 3:
        raise ValueError('Suggestions require zero to three choices')
    known_names = {c['value']['content'] for c in context['view']['cards']
                   if c['template'] == 'knowledge' and c['value'].get('topic', '').startswith('name-')}
    seen = set()
    from world_turn import validate_temporal_text
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {'label', 'text'}:
            raise ValueError('Suggestion fields must be label and text')
        if any(not isinstance(choice[k], str) or not choice[k].strip() or len(choice[k]) > 180
               for k in ('label', 'text')):
            raise ValueError('Suggestion must contain short nonempty strings')
        text = choice['text'].strip()
        match = re.fullmatch(r'【(语言|动作)】([^\n]+)', text)
        if not match or not match[2].strip() or re.search(r'【[^】]+】', match[2]):
            raise ValueError('Suggestion requires a single player speech/action prefix')
        if text in seen:
            raise ValueError('Duplicate suggestions')
        seen.add(text)
        if match[1] == '语言' and not context['view']['local_people']:
            raise ValueError('No present listener for suggested speech')
        combined = choice['label'] + '\n' + text
        validate_no_literal_leak(state, 'player', combined)
        validate_temporal_text(state, definition, 'player', combined)
        for character in definition['characters'].values():
            name = character['name']
            if name not in known_names and name in combined:
                raise ValueError('Suggestion uses a name not known by player')
        for card in state['cards'].values():
            if card['template'] == 'knowledge' and 'player' not in card['visibility']:
                # Chinese adjacent characters are word characters too: \b misses “确认码774433”.
                content = card['value'].get('content', '')
                if any(code in combined for code in re.findall(r'(?<!\d)\d{4,}(?!\d)', content)):
                    raise ValueError('Suggestion leaks a private numeric fact')
            if card['template'] == 'goal' and 'player' not in card['visibility']:
                title = card['value'].get('title', '')
                if len(title) > 3 and title in combined:
                    raise ValueError('Suggestion leaks a private goal')
    return True


def generate_choices(state, definition, frames, gateway, input_status=None, protagonist=None):
    """One optional request; failures clear suggestions without losing the played turn."""
    from deepseek_client import TransportError
    from diagnostic_system import validation_attempt
    context = suggestion_context(state, definition, frames, input_status, protagonist)
    if gateway is None:
        return [], 'unavailable'
    try:
        from runtime_budget import consume
        from world_turn import ModelGateway
        if not isinstance(gateway,ModelGateway):consume('model')
        answer = gateway.ask('suggestions', CONTRACT, context, 380)
        validate_choices(answer, state, definition, context)
        validation_attempt(gateway, 'suggestions', 0)
        return copy.deepcopy(answer['choices']), 'generated'
    except (ValueError, TypeError, KeyError, TransportError) as error:
        # Metadata only; no private payloads and no mutation of the event transaction.
        validation_attempt(gateway, 'suggestions', 0, error)
        gateway.validation_events[-1]['status'] = 'omitted'
        gateway.calls.append({'role': 'suggestions-fallback', 'fallback': True,
                              'error_class': type(error).__name__})
        return [], 'failed'


def current_choices(session, story):
    """Old world saves may contain opening choices carried over into later turns."""
    result = copy.deepcopy(story)
    if not session.get('facts', {}).get('browser_world_state'):
        return result
    turns = session.get('turns', [])
    latest = turns[-1]['turn_id'] if turns else None
    metadata = session['facts'].get('browser_choice_state', {})
    if latest != 'opening' and metadata.get('turn_id') != latest:
        result['choices'] = []
    me=session.get('protagonist_snapshot') or session.get('facts',{}).get('browser_protagonist_snapshot',{})
    if me.get('name') and me['name']!='玩家' and any('我叫玩家' in c.get('text','') or '名字是玩家' in c.get('text','')
                                                  for c in result.get('choices',[])):
        result['choices']=[]
    return result
