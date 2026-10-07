"""Branch-local layered retrieval. Derived indexes never replace story state."""
import copy
import json
import re
import threading
from long_memory import MemoryStore, cost, signature


def terms(text):
    text = text.casefold()
    words = set(re.findall(r'[a-z0-9][a-z0-9_-]{1,}|[\u4e00-\u9fff]{2,}', text))
    for phrase in list(words):
        if re.fullmatch(r'[\u4e00-\u9fff]+', phrase):
            words.update(phrase[i:i+n] for n in (2, 3) for i in range(len(phrase)-n+1))
    return words


def score(text, query):
    target = terms(text)
    # Exact names/codes plus Chinese n-grams; independent of tokenizer/service.
    return sum(min(len(word), 8) ** 2 for word in query & target)


def excerpt(text, query, limit=1100):
    if len(text) <= limit:
        return text
    matches = [(len(word), text.casefold().find(word)) for word in query
               if len(word) >= 2 and word in text.casefold()]
    position = max(matches, default=(0, 0))[1]
    start = max(0, position-limit//3)
    return ('…' if start else '') + text[start:start+limit] + ('…' if start+limit < len(text) else '')


class LayeredMemoryStore(MemoryStore):
    """Existing immutable summaries + rebuildable full-text event index."""
    def __init__(self, root, tavern):
        super().__init__(root, tavern)
        self.index_cache = {}
        self.index_lock = threading.Lock()

    def index(self, session):
        # Hashing the entire prefix also detects edited/imported histories.
        prefix = signature(session['turns'])
        sid = session['id']
        with self.index_lock:
            cached = self.index_cache.get(sid)
            if cached and cached['prefix_sha256'] == prefix:
                return cached
        chronology = {n['id']: n.get('story_time', {}) for n in
                      session.get('facts', {}).get('browser_story', {}).get('nodes', [])}
        frame_map = session.get('facts', {}).get('browser_turn_frames', {})
        rows = []
        for index, turn in enumerate(session['turns']):
            frames = frame_map.get(turn['turn_id'], [])
            # Heart voices/private input remain director-only, never actor knowledge.
            fragments = [('player_input', turn.get('user', ''), '')]
            if frames:
                fragments += [(f.get('kind', 'narration'), f.get('text', ''), f.get('speaker', ''))
                              for f in frames if f.get('kind') != 'thought']
            else:
                fragments += [('archive', p, '') for p in
                              re.split(r'\n\s*\n', turn.get('assistant', '')) if p.strip()]
            for kind, text, speaker in fragments:
                if text:
                    rows.append({'turn_id': turn['turn_id'], 'turn_index': index,
                                 'kind': kind, 'speaker': speaker, 'text': text,
                                 'story_time': chronology.get(turn['turn_id'], {})})
        record = {'version': 1, 'scope': sid, 'covered_count': len(session['turns']),
                  'prefix_sha256': prefix, 'rows': rows}
        # Index is derived, bounded in-process; source JSON is already cold archive.
        with self.index_lock:
            if len(self.index_cache) >= 8:
                self.index_cache.pop(next(iter(self.index_cache)))
            self.index_cache[sid] = record
        return record

    def retrieve(self, session, incoming, scene, budget=8000):
        facts = session.get('facts', {})
        engine = facts.get('browser_engine', {})
        calendar = engine.get('calendar', {})
        active = [x for x in engine.get('threads', {}).values()
                  if x.get('status') in ('open', 'active')]
        query_text = incoming + ' ' + scene
        # Goals/deadlines and newly encountered people trigger retrieval without
        # requiring the player to ask an explicit "remember" question.
        query_text += ' ' + ' '.join(x.get('title', '') for x in active[:4])
        query = terms(query_text)
        records = self.eligible(session)
        episodes = []
        remaining = min(2500, budget//3)
        for record in sorted(records, key=lambda r: (score(r['summary'], query), r['covered_count']), reverse=True):
            if len(episodes) >= 3:
                break
            item = {k: copy.deepcopy(record[k]) for k in ('from_turn', 'to_turn')}
            item['summary'] = excerpt(record['summary'], query, 550)
            item['source_prefix'] = record['prefix_sha256']
            if cost(item) <= remaining:
                episodes.append(item)
                remaining -= cost(item)
        remaining = budget-cost(episodes)
        candidates = []
        for row in self.index(session)['rows']:
            # Recent history is already working memory. Do not spend archive budget twice.
            if row['turn_index'] >= len(session['turns'])-6:
                continue
            time = row.get('story_time') or {}
            day = time.get('date')
            if day and calendar.get('date') and day > calendar['date']:
                continue
            relevance = score(row['text'], query)
            if relevance:
                candidates.append((relevance, row['turn_index'], row))
        hits = []
        seen = set()
        for relevance, _, row in sorted(candidates, key=lambda x: (x[0], x[1]), reverse=True):
            identity = (row['turn_id'], row['text'])
            if identity in seen:
                continue
            seen.add(identity)
            item = {k: copy.deepcopy(row[k]) for k in ('turn_id', 'kind', 'speaker', 'story_time')}
            item['excerpt'] = excerpt(row['text'], query)
            if cost(item) <= remaining:
                hits.append(item)
                remaining -= cost(item)
            if len(hits) >= 8:
                break
        return {'version': 2, 'scope': session['id'], 'episodes': episodes,
                'raw_retrieval': hits, 'summarized_through': max((r['covered_count'] for r in records), default=0),
                'meaning': '导演检索，不是NPC知识。事实/物品/关系/时间以story_state为准；人物仅能使用本人actor_knowledge。摘要有遗漏或冲突时核对带turn_id的原文。'}

    def actor_cards(self, session, context, budget=9000):
        query = terms(context.get('incoming', '')+' '+context.get('scene', ''))
        result = {}
        actors = {a['id']: a for a in context.get('cast', [])}
        allowed_turns = {t['turn_id'] for t in session['turns']}
        cutoff = session.get('facts', {}).get('browser_engine', {}).get('calendar', {}).get('date')
        for aid, entries in session.get('facts', {}).get('browser_actor_knowledge', {}).items():
            actor = actors.get(aid, {})
            own = {actor.get('name'), *actor.get('aliases', [])}-{None, ''}
            eligible = [e for e in entries if e.get('turn_id') in allowed_turns
                        and e.get('source_speaker') not in own
                        and not (cutoff and e.get('learned_date') and e['learned_date'] > cutoff)]
            # Last observations stay verbatim; old relevant evidence is retrieved
            # from this actor only, never from narrative or another actor's card.
            older = sorted(eligible[:-6], key=lambda e: score(e.get('observed', ''), query), reverse=True)
            selected = [e for e in older if score(e.get('observed', ''), query)][:4]+eligible[-6:]
            card = []
            for entry in selected:
                item = copy.deepcopy(entry)
                if cost(item) > budget:
                    continue
                card.append(item)
                budget -= cost(item)
            if card:
                result[aid] = card
        return result


def layered_context(context, session, memory, budget=52000):
    result = copy.deepcopy(context)
    result['facts'] = {k: v for k, v in result.get('facts', {}).items() if not k.startswith('browser_')}
    query = terms(result.get('incoming', '')+' '+result.get('scene', ''))
    values = result.get('memories', [])
    ranked = sorted(enumerate(values[:-12]), key=lambda x: (score(x[1], query), x[0]), reverse=True)
    result['memories'] = list(dict.fromkeys([v for _, v in ranked[:5] if score(v, query)]+values[-12:]))
    result['long_term_memory'] = memory.retrieve(session, result.get('incoming', ''), result.get('scene', ''))
    result['actor_knowledge'] = memory.actor_cards(session, result)
    result['context_budget'] = {'unit': 'utf8_bytes', 'limit': budget,
                              'original_history_preserved': True, 'memory_pipeline': 'layered-v2'}
    # Narrative archives are expendable. Canonical state, actor identities,
    # time/perception rules and current goals are never summarized or recalculated.
    for field in ('prepared_visuals', 'story_so_far', 'recent_turns', 'memories', 'lore'):
        minimum = 2 if field == 'recent_turns' else 0
        while cost(result) > budget and isinstance(result.get(field), list) and len(result[field]) > minimum:
            result[field].pop(0)
    archive = result['long_term_memory']
    while cost(result) > budget and archive['episodes']:
        archive['episodes'].pop()
    while cost(result) > budget and len(archive['raw_retrieval']) > 1:
        archive['raw_retrieval'].pop()
    # This field is narrator context. actor_cards holds separate full source evidence.
    if cost(result) > budget:
        raise ValueError('必要人物、时间与世界状态超过上下文预算；请缩短剧本设定，原始记录已保留。')
    return result
