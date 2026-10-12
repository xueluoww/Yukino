"""Shell diagnostics: bounded metadata, no raw payloads or credentials."""
import copy
from event_schema import digest
from world_state import clock_time, put


def classify(stage, error):
    message = str(error).lower()
    if 'outside' in message or 'unauthor' in message or 'disclos' in message:
        return 'SCOPE_DENIED'
    if any(word in message for word in ('consent', 'somebody', 'owner')):
        return 'CONSENT_OR_OWNERSHIP'
    if any(word in message for word in ('closed', 'entrance', 'path', 'route', 'deadline')):
        return 'PRECONDITION_FAILED'
    if 'transport' in type(error).__name__.lower():
        return 'TRANSPORT_FAILED'
    if stage == 'reference-format':
        return 'REFERENCE_ANNOTATION_REPAIRED'
    from model_protocol import category
    if category(error)=='consistency':return 'SETTLED_FACT_CONFLICT'
    return 'OUTPUT_SCHEMA_INVALID'


def record(tx, actor, stage, error, context=None, disposition='recorded'):
    code = classify(stage, error)
    old = copy.deepcopy(tx.state)
    number = sum(r['template'] == 'builtin.system_diagnostic' for r in tx.records)
    cid = 'diag:' + digest([tx.request_id, stage, actor, number])[:24]
    value = {'owner': actor, 'request_id': tx.request_id, 'stage': stage, 'code': code,
             'error_class': type(error).__name__, 'at': clock_time(tx.state),
             'severity': 'info' if code == 'REFERENCE_ANNOTATION_REPAIRED' else 'warning',
             'disposition': disposition,
             'context': {k: v for k, v in (context or {}).items() if k in ('goal_id', 'plan_id', 'cursor', 'attempt')}}
    put(tx.state, cid, 'diagnostic', value, [actor], ['system'])
    return tx.record({'template': 'builtin.system_diagnostic', 'effects': [], 'title': '生成阶段诊断',
                      'outcome': 'error', 'participants': [actor], 'observers': [], 'public': {},
                      'diagnostic': value, 'rule_id': 'system'}, old)


def validation_attempt(gateway, role, attempt, error=None):
    if not hasattr(gateway, 'validation_events'):
        gateway.validation_events = []
    gateway.validation_events.append({'role': role, 'attempt': attempt + 1,
        'status': 'passed' if error is None else 'retrying' if attempt == 0 else 'exhausted',
        'code': None if error is None else classify(role, error),
        'error_class': None if error is None else type(error).__name__})

