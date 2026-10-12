"""Separate explicit speech from private voice before observation or action extraction.

Only unambiguous channel markers / quoted narrative are repaired locally. An
unquoted ambiguous monologue is retried rather than guessed into spoken facts.
"""
import re

QUOTES = re.compile(r'「([^「」]*)」|『([^『』]*)』|“([^“”]*)”')
PRIVATE = re.compile(r'(?:我(?:心想|暗想|想了想|不禁想|默默想|心里|也?没有追问的义务)|心中|内心|暗自|心想|没有说出口)')
NARRATIVE = re.compile(r'(?:我(?:重复了|合上|抬眼|看向|低头|转身|拿起|放下|皱眉)|合上手里|抬眼看向|手里的|门口的人|她(?:心想|暗想|合上|抬眼|看向|低头|转身|拿起|放下))')
PHYSICAL = re.compile(r'(?:重复了|合上|抬眼|看向|低头|转身|拿起|放下|皱眉|手里的|门口的人)')
LABELS = re.compile(r'【(对白|台词|语言|心声|内心|独白|旁白|动作)】')


def split_text(text, thought=''):
    if not isinstance(text, str) or not isinstance(thought, str):
        raise ValueError('Dialogue and thought must be strings')
    text, thought = text.strip(), thought.strip()
    labels = list(LABELS.finditer(text))
    if labels:
        if text[:labels[0].start()].strip():
            raise ValueError('Unlabelled prose before dialogue channels')
        speech, private = [], []
        for i, match in enumerate(labels):
            value = text[match.end():labels[i+1].start() if i+1 < len(labels) else len(text)].strip()
            if match[1] in ('对白', '台词', '语言'):
                spoken, inner, _ = split_text(value)
                if spoken: speech.append(spoken)
                if inner: private.append(inner)
            elif match[1] in ('心声', '内心', '独白'):
                if value: private.append(value)
            # Off-channel stage directions never count as performed actions.
        return '\n'.join(speech), '\n'.join(dict.fromkeys([p for p in [thought, *private] if p])), True
    quoted = list(QUOTES.finditer(text))
    outside = QUOTES.sub('', text).strip()
    if quoted and (NARRATIVE.search(outside) or PRIVATE.search(outside)):
        spoken = '\n'.join(next(g for g in m.groups() if g is not None).strip() for m in quoted)
        # Physical stage directions require settlement; do not turn them into
        # world facts, speech or inner voice. Keep only private reasoning.
        private = [p.strip() for p in re.split(r'(?<=[。！？])|\n', outside) if p.strip() and not PHYSICAL.search(p)]
        return spoken, '\n'.join(dict.fromkeys([p for p in [thought, *private] if p])), True
    if PRIVATE.search(text) or NARRATIVE.search(text):
        raise ValueError('text must contain only audible dialogue; move private reasoning to thought and stage directions to actions')
    return text, thought, False


def separate_response(answer):
    text, thought, changed = split_text(answer.get('text'), answer.get('thought', ''))
    answer['text'], answer['thought'] = text, thought
    if changed:
        # Citations and language actions attached to removed private spans must
        # not survive. Spoken citations can be recovered from the cleaned text.
        answer['claims'] = []
        for field in ('references', 'candidates'):
            values = answer.get(field, [])
            if isinstance(values, list):
                answer[field] = [v for v in values if isinstance(v, dict) and v.get('evidence') and v['evidence'] in text]
    return changed


def reader_frames(frames):
    """Read-only presentation repair of old explicitly mixed dialogue frames."""
    import copy
    result = []
    for original in frames:
        frame = copy.deepcopy(original)
        if frame.get('kind') == 'dialogue' and not frame.get('system_feedback'):
            try:
                spoken, inner, changed = split_text(frame.get('text', ''))
            except ValueError:
                # Historical unlabelled prose cannot be reliably reconstructed.
                changed = False
            if changed:
                if spoken: result.append({**frame, 'text': spoken})
                if inner: result.append({**frame, 'kind': 'thought', 'text': inner})
                continue
        result.append(frame)
    return result


def reader_thoughts(session):
    """Recovered explicit private passages are display entries, never state writes."""
    import copy
    facts = session.get('facts', {})
    entries = copy.deepcopy(facts.get('browser_inner_thoughts', []))
    if not facts.get('browser_world_state'): return entries
    for turn in session.get('turns', []):
        tid = turn['turn_id']
        for f in reader_frames(facts.get('browser_turn_frames', {}).get(tid, [])):
            if f.get('kind') != 'thought' or f.get('actor_id') == 'player': continue
            if any(e.get('turn_id') == tid and e.get('text') == f['text'] and e.get('actor_id') == f.get('actor_id') for e in entries): continue
            entries.append({'turn_id': tid, 'name': f.get('speaker', ''), 'actor_id': f.get('actor_id'), 'text': f['text'], 'scene': f.get('stage', {}).get('location', '')})
    from map_runtime import get_locations
    places = get_locations(facts.get('browser_world_definition', {}), facts.get('browser_world_state'))
    for entry in entries:
        entry['scene'] = places.get(entry.get('scene'), {}).get('name', entry.get('scene', ''))
    return entries
