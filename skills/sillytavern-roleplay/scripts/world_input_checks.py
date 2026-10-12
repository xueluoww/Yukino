"""Explicit engine requests and signed wait validation before any world mutation."""
import re
from world_state import clock_time

def check(tx, text):
    from galgame import parse_input
    parts = parse_input(text)['parts']
    # A player's known map can support a natural recollection without inventing
    # another character's response. Unknown functional names are never revealed.
    if len(parts)==1 and re.fullmatch(r'(?:我)?(?:刚才|之前|刚刚)?(?:发现|看到|经过)(?:的)?(?:那间|那个|这间)?(?:房间|地方)(?:叫|叫什么|叫什么名字|的名字是什么)[？?。\s]*',parts[0]['text']):
        from map_references import recent_discoveries
        nodes=recent_discoveries(tx.state,tx.definition,'player')
        if len(nodes)==1:
            return {'kind':'read_only','narrator':True,'text':'你记得，刚才发现的入口是'+nodes[0]['name']+'。'}
    for part in parts:
        content = part['text']
        if part['kind'] == 'thought':
            continue
        if part['kind'] not in ('speech','thought') and re.search(r'(?:在|用|去).{0,8}(?:自动贩卖机|自动售货机|售货机).{0,10}买',content):
            from world_state import location
            here=location(tx.state,'player')
            machines=[c for c in tx.state['cards'].values() if c['template']=='item' and c['value'].get('quantity',0)>0 and c['value'].get('location')==here
                      and not tx.definition['items'].get(c['value']['item'],{}).get('hidden')
                      and any(x in str(tx.definition['items'].get(c['value']['item'],{})) for x in ('贩卖机','售货机'))]
            if not machines:
                return {'kind':'rejected','text':'现场尚未发现可以操作的自动贩卖机，购买尚未执行。可以先寻找或询问购买地点。'}
        # Literal action durations only, never a character's quoted past or hypothetical.
        if part['kind'] != 'speech' and not re.search(r'如果|假如|昨天|他说|她说|“|"', content):
            m = re.search(r'(?:等待|等|休息)\s*([+-]?\d+)\s*(分钟|小时|天)', content)
            if m:
                minutes = int(m[1]) * {'分钟': 1, '小时': 60, '天': 1440}[m[2]]
                if not 0 <= minutes <= 10080:
                    return {'kind': 'rejected', 'text': '等待时间不能为负数。' if minutes < 0 else '一次最多等待 10080 分钟（7 天）；请分段安排。'}
            if re.search(r'(?:我|主角)(?:已经)?(?:受了|身受|遭受).{0,4}(?:重伤|致命伤)|我(?:死了|死亡)', content):
                return {'kind': 'rejected', 'text': '这段输入直接宣布了尚未发生的伤势或死亡，不能只按躺下处理。请说明导致它的具体行动；伤势需要实际事件或剧本玩法结算。'}
        if re.fullmatch(r'(?:请|我想|帮我)?(?:查看|看看|查询|显示)?(?:现在|当前)?(?:的)?(?:时间(?:和日期)?|日期(?:和时间)?|几点了)[？?。！!\s]*', content):
            clock = tx.state['clock']; minute = clock['minute']
            return {'kind': 'read_only', 'text': f"当前故事时间：{clock.get('date') or '第 '+str(clock['day'])+' 天'} · {minute//60:02d}:{minute%60:02d}。"}
        if re.fullmatch(r'(?:请|帮我)?(?:重新画|重画|重新生成|生成).{0,40}(?:立绘|背景图|图片|画面)[。！!\s]*', content):
            return {'kind': 'read_only', 'text': '请在当前画面或画廊的“调整画面”入口填写要求，查看新旧对比后采用。对白输入不会直接生成图片；需要已连接的生图服务。'}
        if re.fullmatch(r'(?:忽略之前(?:的)?设定[，,]?\s*)?(?:打印|显示|输出|告诉我).{0,8}(?:系统提示词|密钥|API密钥)[。！!\s]*', content):
            return {'kind': 'rejected', 'text': '这个输入要求读取运行配置或内部提示，不能作为游戏行动执行。请继续输入主角的语言或行动。'}
    return None

def execution_feedback(tx, step, records):
    from player_feedback import readable
    failures = [r for r in records if r.get('outcome') in ('rejected', 'held', 'error')]
    if not failures:
        return None
    reasons = list(dict.fromkeys(readable(r.get('public', {}).get('reason') or '这一步尚未完成，请重试或换一种做法。') for r in failures))
    return '本步未完成：' + '；'.join(reasons)
