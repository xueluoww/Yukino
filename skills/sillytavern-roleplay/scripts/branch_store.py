"""Fork immutable story points into separate session and memory namespaces."""
import copy
from pathlib import Path
import re
import uuid

def metadata(session):
    branch = session.get('branch') or session.get('facts', {}).get('browser_branch', {})
    parent = branch.get('parent_id') or branch.get('session_id') or ''
    return {'parent_id': parent, 'root_id': branch.get('root_id', session['id']),
            'node_id': branch.get('node_id', ''), 'label': branch.get('label', '剧情分支' if parent else '主线'),
            'kind': branch.get('kind', 'rollback' if parent else 'root')}

def create_fork(root, tavern, parent, snapshot, node_id, kind='rollback'):
    root = Path(root)
    if snapshot['id'] != parent['id'] or snapshot['card_id'] != parent['card_id']:
        raise ValueError('快照不属于当前存档。')
    point = next((i for i, t in enumerate(parent['turns']) if t['turn_id'] == node_id), None)
    if point is None or len(snapshot['turns']) != point + 1 or snapshot['turns'][-1]['turn_id'] != node_id:
        raise ValueError('快照和回溯节点不一致。')
    with tavern.write_lock(root):
        canonical = root/'sessions'/f"{parent['id']}.json"
        if not canonical.is_file() or tavern.load_json(canonical, 128*tavern.MAX_CARD)['revision'] != parent['revision']:
            raise ValueError('原存档已变化，请重新载入后再另存或回溯。')
        children = [tavern.load_json(p, 128*tavern.MAX_CARD) for p in (root/'sessions').glob('*.json')]
        number = 1 + sum(metadata(s)['parent_id'] == parent['id'] for s in children)
        source = metadata(parent)
        fork = copy.deepcopy(snapshot)
        fork['id'] = uuid.uuid4().hex[:16]
        fork['revision'] = 0
        fork['status'] = 'active'
        fork['created_at'] = fork['updated_at'] = tavern.now()
        fork['branch'] = {'parent_id': parent['id'], 'root_id': source['root_id'], 'node_id': node_id,
                         'label': f"{source['label']}.{number}", 'kind': kind}
        fork['memory_scope'] = fork['id']
        fork['facts']['browser_branch'] = {'session_id': parent['id'], 'node_id': node_id}
        fork['title'] = parent['title'].split(' · 分支')[0]
        target = root/'sessions'/f"{fork['id']}.json"
        if target.exists():
            raise ValueError('新存档 ID 冲突，请重试。')
        # Only earlier checkpoints are inherited; each copy has the child's identity.
        for turn in fork['turns']:
            tid = turn['turn_id']
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', tid):
                continue
            existing = root/'browser/checkpoints'/parent['id']/(tid+'.json')
            if existing.is_file():
                earlier = tavern.load_json(existing, 128*tavern.MAX_CARD)
                earlier['id'] = fork['id']
                earlier['memory_scope'] = fork['id']
                earlier['branch'] = copy.deepcopy(fork['branch'])
                earlier['facts']['browser_branch'] = copy.deepcopy(fork['facts']['browser_branch'])
                tavern.atomic_json(root/'browser/checkpoints'/fork['id']/(tid+'.json'), earlier)
        tavern.atomic_json(target, fork)
        from long_memory import MemoryStore
        MemoryStore(root,tavern).inherit(parent,fork)
        return fork

def session_listing(root, tavern):
    result = []
    for path in (Path(root)/'sessions').glob('*.json'):
        session = tavern.load_json(path, 128*tavern.MAX_CARD)
        branch = metadata(session)
        world_id=(session.get('world_snapshot') or session.get('facts',{}).get('browser_world_snapshot',{})).get('id','')
        latest = session.get('facts', {}).get('browser_story', {}).get('nodes', [])
        result.append({key: session[key] for key in ('id','title','card_id','mode','status','updated_at')} |
            {'branch': branch, 'summary': session.get('summary') or session.get('scene') or '故事刚刚开始。',
             'note':session.get('save_note',''), 'scene': session.get('scene', ''), 'script_id':session.get('script_id') or world_id, 'world_id':world_id, 'turn_count': max(0, len(session['turns'])-1),
             'latest_event': latest[-1].get('title', '') if latest else '', 'memory_scope': session['id']})
    return {'root': str(root), 'sessions': sorted(result, key=lambda s: s['updated_at'], reverse=True)}
