"""Observe an executed NPC action without disclosing its private contents or goal."""
import copy
from scene_presence import visible_actor_ids

def record_visible(tx,source):
    actor=source.get('public',{}).get('actor')
    if actor not in tx.definition['characters'] or source.get('outcome')!='applied':return
    if source['template'] not in ('builtin.read','builtin.write','builtin.consume'):return
    observers=visible_actor_ids(tx.state,tx.definition,actor)
    if not observers:return
    old=copy.deepcopy(tx.state)
    tx.record({'template':'builtin.visible_activity','effects':[],'title':'眼前的人物活动','outcome':'applied',
        'participants':[actor],'observers':observers,'public':{'actor':actor,
        'action':source['template'][8:],'source_event':source['event_id'],
        **({'portion':source['public'].get('portion'),'finished_unit':source['public'].get('finished_unit')}
           if source['template']=='builtin.consume' else {})},'rule_id':'physical-observation'},old)
