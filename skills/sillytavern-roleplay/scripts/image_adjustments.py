"""Explicit, versioned redraws. Originals and historical checkpoints stay immutable."""
import copy
import hashlib
import json
import re
from pathlib import Path
from shared_gallery import script_scope, branch_refs, background_identity, person_identity


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ImageAdjustments:
    def adjustment_sources(self):
        sources = {}
        for key, entry in self.shared_gallery.unlocked(self.current):
            sources[key] = copy.deepcopy(entry) | {'key': key}
        # Successful character revisions belong to this branch, unlike the stock sprite library.
        refs = branch_refs(self.current)
        for key in refs:
            entry = self.cache.get(key, {})
            if entry.get('kind') == 'portrait' and entry.get('url'):
                sources[key] = copy.deepcopy(entry) | {'key': key}
        actors = self.actors()
        descriptor = self.descriptor()
        bg = self.visual.get('background')
        if bg in descriptor.get('backgrounds', {}):
            key = 'source-' + fingerprint(['background', script_scope(self.current), bg])[:24]
            sources[key] = {'key': key, 'kind': 'background', 'url': descriptor['backgrounds'][bg],
                            'name': descriptor.get('background_descriptions', {}).get(bg, '当前场景'),
                            'background': bg, 'background_identity': background_identity(self.current, bg)}
        for aid, actor in actors.items():
            for expression, url in actor.get('sprites', {}).items():
                key = 'source-' + fingerprint(['portrait', script_scope(self.current), aid, expression, url])[:24]
                sources[key] = {'key': key, 'kind': 'portrait', 'url': url,
                                'actor_id': aid, 'expression': expression,
                                'appearance': actor.get('default_appearance', 'school-uniform'),
                                'name': actor['name']+' · '+__import__('runtime_v4').EMOTIONS.get(expression, '人物表情')}
        return {key: value for key, value in sources.items()
                if Path(value['url']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}}

    def adjustment_records(self):
        path = self.root/'browser/image-adjustments.json'
        return self.tavern.load_json(path, 32*self.tavern.MAX_CARD) if path.exists() else {}

    def save_adjustments(self, records):
        self.tavern.atomic_json(self.root/'browser/image-adjustments.json', records)

    def chosen_image(self, key, session=None):
        session = session or self.current
        selected = session.get('facts', {}).get('browser_image_choices', {}).get(key)
        entry = self.cache.get(selected, {})
        if entry.get('revision_of') == key and entry.get('world_scope') == script_scope(session):
            return selected
        return key

    def request_adjustment(self, session_id, source_key, prompt, request_id):
        with self.lock:
            if session_id != self.current['id'] or self.busy:
                raise ValueError('故事已切换或正在保存，请稍后再调整画面。')
            if not self.dynamic_images:
                raise ValueError('请先在设置中启用画面生成。')
            if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1200:
                raise ValueError('请填写1至1200字的画面调整要求。')
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
                raise ValueError('画面请求编号无效。')
            source = self.adjustment_sources().get(source_key)
            if not source:
                raise ValueError('只能调整本存档已经可查看的画面。')
            records = self.adjustment_records()
            rid = session_id+':'+request_id
            payload_hash = fingerprint([source_key, prompt.strip()])
            if rid in records:
                if records[rid]['payload_hash'] != payload_hash:
                    raise ValueError('同一请求编号不能用于不同的画面要求。')
                return self.state()
            if any(r['session_id'] == session_id and self.image_tasks.get(r['key'], {}).get('status') in ('queued', 'painting') for r in records.values()):
                raise ValueError('上一幅调整画面仍在准备，请等它完成。')
            source_path = self.asset_path(source['url'])
            if not source_path.is_file():
                raise ValueError('原图暂不可用，请重新选择画面。')
            key = 'revision-'+fingerprint([session_id, request_id, payload_hash])[:32]
            original_job = self.image_tasks.get(source_key, {})
            kind = source['kind']
            actor = self.actors().get(source.get('actor_id'), {})
            job = self.make_job(key, kind, original_job.get('prompt', ''), self.current, actor,
                                source.get('name', '故事画面')+' · 新版')
            job.update({k: copy.deepcopy(v) for k, v in source.items() if k in
                        ('background', 'background_identity', 'actor_id', 'expression', 'appearance', 'participant_visuals', 'protagonist_visual', 'event_key')})
            if kind == 'cg':
                job['participants'] = copy.deepcopy(original_job.get('participants', []))
            job.update({'revision_of': source_key, 'source_url': source['url'],
                        'adjustment_prompt': prompt.strip(), 'visual_key': key,
                        'world_scope': script_scope(self.current), 'scope': self.scope()})
            record = {'key': key, 'source_key': source_key, 'source_url': source['url'], 'kind': kind,
                      'session_id': session_id, 'request_id': request_id, 'payload_hash': payload_hash,
                      'anchor_turn_id': self.current['turns'][-1]['turn_id'],
                      'prompt': prompt.strip(), 'name': source.get('name', '故事画面'), 'adopted': False}
            records[rid] = record
            self.save_adjustments(records)
            self.queue_images([job], session_id, self.current['card_id'])
            return self.state()

    def adopt_adjustment(self, session_id, key):
        with self.lock:
            if session_id != self.current['id'] or self.busy:
                raise ValueError('故事已切换或正在保存，请重新选择。')
            records = self.adjustment_records()
            record = next((r for r in records.values() if r['key'] == key and r['session_id'] == session_id), None)
            entry = self.cache.get(key)
            if not record or not entry or self.image_tasks.get(key, {}).get('status') != 'ready':
                raise ValueError('这幅画面尚未准备好。')
            if record['adopted']:
                return self.state()
            candidate = copy.deepcopy(self.current)
            facts = candidate['facts']
            facts.setdefault('browser_image_choices', {})[record['source_key']] = key
            facts['browser_gallery_refs'] = sorted(branch_refs(candidate) | {key})
            # A late completion may enter the gallery, but cannot replace a later scene.
            current = record['anchor_turn_id'] == self.current['turns'][-1]['turn_id']
            if current:
                frames = copy.deepcopy(self.frames)
                visual = copy.deepcopy(self.visual)
                source = self.adjustment_sources().get(record['source_key'], {})
                if record['kind'] == 'background' and source.get('background') == visual.get('background'):
                    visual['background_asset'] = key
                    for frame in frames:
                        if frame.get('stage', {}).get('background', visual['background']) == visual['background']:
                            frame.setdefault('stage', {})['background_asset'] = key
                elif record['kind'] == 'cg' and visual.get('cg_asset') == record['source_key']:
                    visual['cg_asset'] = key
                elif record['kind'] == 'portrait':
                    for frame in frames:
                        if frame.get('actor_id') == entry.get('actor_id') and frame.get('expression') == entry.get('expression'):
                            frame['portrait_asset'] = key
                facts['browser_visual'] = visual
                facts['browser_latest_frames'] = frames
            # Presentation preferences have their own revision; no story turn,
            # relationship, time, memory or checkpoint gets rewritten.
            if self.persistent:
                with self.tavern.write_lock(self.root):
                    path = self.root/'sessions'/(session_id+'.json')
                    latest = self.tavern.load_json(path, 128*self.tavern.MAX_CARD)
                    if latest['revision'] != candidate['revision']:
                        raise ValueError('存档已被其他窗口更新，请重新读取。')
                    candidate['revision'] += 1
                    self.tavern.atomic_json(path, candidate)
            else:
                candidate['revision'] += 1
            self.current = candidate
            if current:
                self.frames = frames
                self.visual = visual
            record['adopted'] = True
            self.save_adjustments(records)
            self.shared_gallery.register(self.current, key, entry)
            self.version += 1
            return self.state()

    def state(self):
        with self.lock:
            return self._adjustment_state()

    def _adjustment_state(self):
        result = super().state()
        sources = self.adjustment_sources()
        result['image_adjustment_sources'] = [{k: s[k] for k in ('key', 'url', 'kind', 'name')} for s in sources.values()]
        result['image_adjustments'] = []
        for record in self.adjustment_records().values():
            if record['session_id'] != self.current['id']:
                continue
            task = self.image_tasks.get(record['key'], {})
            entry = self.cache.get(record['key'], {})
            result['image_adjustments'].append({k: record[k] for k in ('key', 'source_key', 'source_url', 'name', 'prompt', 'adopted')} |
                                               {'status': task.get('status', 'failed'), 'url': entry.get('url', ''),
                                                'can_apply_current': record['anchor_turn_id'] == self.current['turns'][-1]['turn_id']})
        return result

    def retry_adjustment(self, session_id, key):
        with self.lock:
            records = self.adjustment_records()
            record = next((r for r in records.values() if r['key'] == key and r['session_id'] == session_id), None)
            task = self.image_tasks.get(key, {})
            if session_id != self.current['id'] or not record or task.get('status') != 'failed' or self.busy or not self.dynamic_images:
                raise ValueError('这幅画面目前不能重试。')
            self.queue_images([copy.deepcopy(task)], session_id, self.current['card_id'])
            return self.state()
