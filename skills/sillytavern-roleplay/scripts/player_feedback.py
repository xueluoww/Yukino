"""Keep engine diagnostics private while giving the player actionable, honest feedback."""
import re
def readable(reason):
    reason=str(reason)
    reason=reason.replace('普通书籍报价','普通书籍可买').replace('日常售卖处','可以买普通日用品的地方')
    # Already classified player messages must not be reclassified by words such
    # as "内部" or "API". Keep the refusal reason, never return sensitive values.
    if reason.startswith(('这个输入要求读取运行配置或内部提示','现场尚未发现','这一步的具体台词尚未给出')):
        return reason[:240]
    mappings=[('ownership','物品目前不归你持有，不能再次交给别人。'),('Reading requires','尚未获得这件物品的阅读许可，请先询问持有人。'),('Cannot read','这件物品不能阅读。'),('owner-issued onsite reading permission','尚未获得这件物品的阅读许可，请先询问持有人。'),("Taking somebody else's property",'这件物品由别人持有，不能直接拿取，请先询问是否愿意交给你。'),('not physically','这件物品不在伸手可及的位置。'),('not accessible','目前不能操作这件物品，请先取得访问许可。'),('within reach','目标不在伸手可及的位置。')]
    for needle,message in mappings:
        if needle.lower() in reason.lower():return message
    reason=re.sub(r'^(?:这次尝试没有完成[：:]\s*)+','',reason)
    if 'recent_discoveries' in reason:
        return '还不能确定你指的是哪处发现，请说明地名，或先探索眼前的区域。'
    if 'Destination/route not known' in reason:
        return '还不能确定这个地点或通往它的路线。可以先问路，或探索眼前的区域。'
    if 'Destination closed' in reason:
        return '目的地当前不开放，暂时不能进入。可以先询问开放时间，或选择其他地方。'
    if 'Unreachable destination' in reason:
        return '还没有找到从这里通往目的地的可行路线。可以先问路，或探索附近的通路。'
    if 'Container is not a physical stop' in reason:
        return '这个名称指的是一个区域，请先确认入口，再前往具体地点。'
    if re.search(r'items|instance|schema|Unknown|ValueError|KeyError|Traceback|API|数据库|实例|视野内.*为空|字段|checksum|outside|mismatch|Unreachable|not physically|not accessible|\bID\b|内部|登记.*id',reason,re.I):
        return '这次还不能确定要操作的物品或地点，请说明具体对象。'
    if re.search(r'[A-Za-z]{4,}',reason):return '这次尝试没有完成，眼前的条件还不支持这个行动。'
    return reason[:240]

def no_listener(tx):
    from world_presentation import place_name
    from scene_presence import visible_actor_ids
    from world_state import location
    from event_schema import digest
    here=place_name(tx.definition,location(tx.state,'player'))
    lines=['你说完后，没有能听见这句话的人走近。','这句话留在了'+here+'，附近没有能听见的人。',
           '附近没有能听见这句话的人，眼前也没有交谈对象。','你说出这句话；'+here+'里没有能听见的人回应。',
           '话音落下，身边没有能听见这句话的人。','没有能听见这句话的人在旁边，这句话没有得到答复。']
    previous=getattr(tx,'previous_narration',[])
    candidates=[line for line in lines if line not in previous] or lines
    return candidates[int(digest(tx.request_id)[:8],16)%len(candidates)]
