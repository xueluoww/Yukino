"""Lossless output repair and bounded stage contracts. Never repair facts or permissions."""
import copy
import json
import re

CONTRACTS = {
    'parser': {'steps': list, 'recipes': list, 'clarifications': list, 'review': dict},
    'actor': {'text': str}, 'narrator': {'text': str},
    'expression-rewrite': {'text': str}, 'review': {'flags': list},
    'expression-review': {'flags': list},
    'schedule-generator': {'entries': list},
    'schedule-decision': {'decision': str, 'reason': str, 'delay': int},
    'place-description': {'name': str, 'description': str, 'aliases': list},
}

def schema(role, payload):
    fields = CONTRACTS.get(role.split(':')[0], {})
    if role == 'parser':
        fields = ({'steps': list, 'recipes': list, 'clarifications': list, 'review': dict}
                  if 'input_kind' in payload and 'protagonist' in payload else
                  {'steps': list} if 'input_kind' in payload else {'actions': list})
    types = {str: 'string', list: 'array', dict: 'object', int: 'integer'}
    return {'type': 'object', 'required': list(fields),
            'properties': {k: ({'type': 'array', 'items': {}} if v is list else {'type': types[v]}) for k, v in fields.items()}}

def decode(raw):
    if not isinstance(raw, str):
        raise ValueError('OUTPUT_SCHEMA: model output must be text')
    value = raw.strip()
    if value.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', value)
        if match:
            value = match[1]
    result = json.loads(value, strict=False)
    if not isinstance(result, dict):
        raise ValueError('OUTPUT_SCHEMA: model stage requires one JSON object')
    return result

def normalize(role, answer, payload):
    if not isinstance(answer, dict):
        raise ValueError('OUTPUT_SCHEMA: model stage requires object')
    answer = copy.deepcopy(answer)
    if role.startswith('actor:') and 'expression' in answer:
        expression=answer['expression']
        if not isinstance(expression,str):raise ValueError('OUTPUT_SCHEMA: expression must be string')
        allowed={'neutral','thinking','soft','annoyed','sad','surprised','serious','shy','listening','troubled','displeased','happy','eyes_closed','absent'}
        if expression not in allowed:
            answer['expression']=next((label for pattern,label in [('惊|诧','surprised'),('皱眉|不满|生气','annoyed'),('困惑|思考','thinking'),('笑|高兴','happy'),('害羞','shy'),('难过|悲伤','sad')] if re.search(pattern,expression)), 'neutral')
    # Known harmless wrapper, only when the complete reply is a single flags wrapper.
    if role.startswith(('review:', 'expression-review:')) and set(answer) == {'result'} and isinstance(answer['result'], dict):
        answer = answer['result']
    for field in ('claims', 'actions', 'candidates', 'references', 'flags', 'steps', 'recipes', 'clarifications'):
        if field in answer and not isinstance(answer[field], list):
            raise ValueError('OUTPUT_SCHEMA: ' + field + ' must be an array')
    from deepseek_client import validate_schema
    contract=schema(role,payload)
    if role=='parser' and 'protagonist' in payload:
        # Rejections and missing execution interfaces have no executable program.
        # Action validator below owns required steps when admission actually allows them.
        contract['required']=['review']
    validate_schema(answer, contract)
    # Strict field requirements already owned by stage validators; no invented defaults.
    return answer

def category(error):
    text = str(error).lower()
    if 'transport' in type(error).__name__.lower():
        return 'transport'
    if 'context_budget' in text:return 'context_budget'
    if any(t in text for t in ('unauthorized', 'forbidden', 'secret', 'disclosure', 'outside scoped', '权限')):
        return 'scope'
    if any(t in text for t in ('contradict', 'invent', 'unexecuted', 'no scoped source', 'settled', 'conflicts')):
        return 'consistency'
    if any(t in text for t in ('unreachable', 'owner', 'consent', 'closed', 'duration', '前提')):
        return 'precondition'
    return 'schema'

def feedback(role, error):
    return {'stage': role, 'category': category(error), 'reason': str(error)[:1600],
            'decision': 'repair_current_output_only',
            'rule': '只重新生成当前阶段的结构或表达；不重演已成功动作，不新增权限/人物/物品/事实。未知就澄清。必须引用提供的真实来源；不能通过删掉审查或改写状态规避错误。'}
