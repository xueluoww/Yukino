"""Personal, source-preserving recall. State notes are caches; packet history is the archive.

No shared director summary, global vector search, private thoughts or sibling saves.
Compaction is extractive: it cannot promote someone's words to authoritative facts.
"""
import copy
import json
import re
from event_schema import digest
from world_state import clock_time, put, read

VERSION = 1
MEMORY_BYTES = 8000
IMPORTANT = re.compile(r'记住|编号|代码|暗号|名字|我叫|我是|喜欢|不喜欢|习惯|家庭|家人|父母|妹妹|哥哥|姐姐|弟弟|约|明天|下周|星期|周六|周日|预算|经费|保管|交给|答应|承诺|不想|不要|负责|老师|秘密|[A-Z]{2,}[-_][A-Z0-9]+|\d{2,}')
TOPICS={'budget':('经费','部费','预算','资金'),
        'identity':('姓名','名字','我叫','我是'),
        'code':('编号','代码','暗号','确认码'),
        'preference':('喜欢','偏好','喝什么','麦茶','咖啡'),
        'family':('家庭','家人','父母'),
        'plan':('计划','打算','安排','约定','约好','下周','周六','星期六','周日','星期日','图书馆'),
        'custody':('保管','交给','递给','答应','承诺','申请单')}

def topics(text):
    return {key for key,aliases in TOPICS.items() if any(x in text for x in aliases)}

def substantive(note):
    text=note['text']
    return not re.search(r'[？?]|(?:不知道|不记得|没听|没有听|你还记得|告诉过你吗)',text) and bool(IMPORTANT.search(text))

def entry(record, request_id):
    speech = record.get('speech')
    if record.get('template') != 'builtin.say' or record.get('outcome') != 'applied' or not speech:
        return None
    return {'id': record['event_id'], 'turn_id': request_id,
            'speaker': speech['actor'], 'text': speech['text'],
            'audience': sorted(set(speech.get('audience', []))),
            'at': record['story_time'], 'source': 'heard_utterance',
            'certainty': 'speaker_statement_not_verified_world_fact'}

def remember(state, record, request_id):
    note = entry(record, request_id)
    if note is None:
        return
    for actor in [note['speaker'], *note['audience']]:
        key = 'memory:' + actor
        value = copy.deepcopy(read(state, key, {'owner': actor, 'version': VERSION, 'recent': [], 'notes': [], 'count': 0, 'compactions': 0}))
        if any(n['id'] == note['id'] for n in value['recent']):
            continue
        value['count'] += 1
        value['recent'] = (value['recent'] + [note])[-12:]
        if IMPORTANT.search(note['text']):
            value['notes'] = (value['notes'] + [note])[-48:]
        if value['count'] % 16 == 0:
            quotes=[{'source_event':n['id'],'speaker':n['speaker'],'excerpt':n['text'][:160],'at':n['at']} for n in value['recent'] if IMPORTANT.search(n['text'])][-3:]
            value['chapters']=(value.get('chapters',[])+[{'at':note['at'],'end_event':note['id'],'utterance_count':value['count'],'quotes':quotes,'mode':'extractive_not_world_fact'}])[-8:]
            value['compactions'] += 1
        # One bounded, private notebook per actor, not an ever-growing card per turn.
        put(state, key, 'personal_memory', value, [actor], [actor])

def bind(tx, session):
    """Only this branch's committed packets. Never search the filesystem for other saves."""
    tx.memory_history = tuple(session.get('turns', []))
    tx._memory_archive_cache={}
    tx.memory_prefix = digest([[t.get('turn_id'), t.get('world_packet', {}).get('head', '')]
                               for t in tx.memory_history])

def query_terms(text):
    # Exact IDs/numbers plus Chinese ngrams avoid requiring an external vector service.
    tokens = set(re.findall(r'[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*', text.lower()))
    for word in re.findall(r'[\u4e00-\u9fff]+', text):
        tokens.update(word[i:i+2] for i in range(len(word)-1))
    return tokens - {'之前', '什么', '记得', '知道', '我们', '你说', '我说', '告诉', '一下', '吗你'}

def scoped_archive(tx, actor):
    now = clock_time(tx.state)
    history=getattr(tx,'memory_history',())
    key=(actor,getattr(tx,'memory_prefix',''),id(history),len(history))
    cache=getattr(tx,'_memory_archive_cache',None)
    if cache is None:cache={};tx._memory_archive_cache=cache
    if key not in cache:
        notes=[]
        for turn in history:
            for record in turn.get('world_packet',{}).get('records',[]):
                if actor not in record.get('observers',[]):continue
                note=entry(record,turn.get('turn_id',''))
                if note and (actor==note['speaker'] or actor in note['audience']):notes.append(note)
        cache[key]=tuple(notes)
    yield from (n for n in cache[key] if n['at']<=now)

def recall(tx, actor, query='', budget=MEMORY_BYTES):
    own = read(tx.state, 'memory:' + actor, {})
    recent = own.get('recent', [])[-6:]
    terms = query_terms(query)
    wanted=topics(query)
    by_id = {}
    archive = list(scoped_archive(tx,actor))
    for record in tx.records:
        if actor in record.get('observers',[]):
            n=entry(record,tx.request_id)
            if n and n['at']<=clock_time(tx.state):archive.append(n)
    proofs = {n['id'] for n in archive}
    proofs.update(r['event_id'] for r in tx.records if r['template']=='builtin.say' and actor in r.get('observers',[]))
    # Archive is immutable branch history, so old saves also recover actual heard speech.
    for note in [*archive, *own.get('notes', []), *own.get('recent', [])]:
        if hasattr(tx,'memory_history') and note['id'] not in proofs:
            continue
        if note['at'] <= clock_time(tx.state) and (note['speaker'] == actor or actor in note['audience']):
            by_id[note['id']] = note
    def rank(n):
        text = n['text'].lower()
        score = sum(4 if re.search(r'[A-Za-z0-9]', term) else 1 for term in terms if term in text)
        matched=bool(wanted & topics(text))
        return (int(matched and substantive(n)),score+4*len(wanted & topics(text)),bool(IMPORTANT.search(n['text'])),n['at'])
    selected = sorted(by_id.values(), key=rank, reverse=True)
    recent = [n for n in recent if n['id'] in by_id and n==by_id[n['id']]]
    result = {'version': VERSION, 'owner': actor, 'branch_prefix': getattr(tx, 'memory_prefix', ''),
              'policy': '只有本人实际听见或说出的原文；陈述/约定不等于客观事实或行动完成。未知细节承认未知，不猜偏好/家庭/身份。',
              'recent': [], 'retrieved': [], 'archive_count': len(by_id),
              'compactions': own.get('compactions', 0)}
    # Query-specific, source-preserving focus; the original quote is not rewritten
    # into an agreed appointment, a verified budget or completed transfer.
    focus=[n for n in selected if wanted & topics(n['text']) and substantive(n)
           and n['text']!=query and n['speaker']!=actor][:3]
    result['recall_focus']=[{'source_event':n['id'],'speaker':n['speaker'],'text':n['text'][:600],
                            'at':n['at'],'certainty':n['certainty']}for n in focus]
    result['question_topics']=sorted(wanted)
    while result['recall_focus'] and len(json.dumps(result,ensure_ascii=False).encode('utf-8'))>budget//2:
        result['recall_focus'].pop()
    used = set()
    # Reserve half the budget for older relevant material, not just the current question.
    for target, candidates, limit in [('recent', recent, budget//2), ('retrieved', selected, budget)]:
        for note in candidates:
            if note['id'] in used:
                continue
            candidate = copy.deepcopy(note)
            # Original remains in the archive. A truncated quote is explicitly labelled.
            if len(candidate['text']) > 600:
                candidate['text'] = candidate['text'][:600]
                candidate['excerpt'] = True
            result[target].append(candidate)
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > limit:
                result[target].pop()
                continue
            used.add(note['id'])
            if len(result[target]) >= (6 if target == 'recent' else 10):
                break
    return result

def status(state):
    books = [c['value'] for c in state['cards'].values() if c['template'] == 'personal_memory']
    return {'pipeline': 'world-personal-extractive-v1', 'notebooks': len(books),
            'summaries': sum(b['compactions'] for b in books),
            'compression': 'source_preserving_excerpts', 'context_budget_bytes': MEMORY_BYTES,
            'archive': 'current_branch_world_packets'}

def validate_recall_answer(view,dialogue,text):
    """Narrow false-amnesia guard; refusal and unverified truth stay distinct."""
    focus=view.get('personal_memory',{}).get('recall_focus',[])
    question='\n'.join(r.get('text','') for r in dialogue.get('heard_now',[]))
    if not focus or not topics(question)&{'budget','code','identity'}:return
    if re.search(r'谁(?:管|负责)|不想|不愿|不告诉|与你无关|没有义务|凭什么',question+' '+text):return
    if not re.search(r'记得|之前|上次|多少|编号|叫什么|叫什么名字',question):return
    anchors=[a for n in focus for a in re.findall(r'[A-Z]{2,}[-_][A-Z0-9]+|\d{2,}',n['text'])]
    if any(a in text for a in anchors) and re.search(r'你(?:之前|上次)?说|你提过|你告诉过|听你说|记得',text) and not re.search(r'不记得|没有听过',text):return
    if re.search(r'不记得|没听过|没有听过|你(?:没|没有)(?:说过|告诉过)|我不知道',text):
        raise ValueError('RECALL_SOURCE: scoped heard evidence exists; distinguish remembered statement from unverified truth instead of claiming never heard')
