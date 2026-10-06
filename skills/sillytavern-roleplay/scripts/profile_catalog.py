"""Read-only display profiles; never return prompts, conversations or branch memories."""
def profile(key,name,data=None,entry=None,descriptor=None):
    data=data or {};entry=entry or {};descriptor=descriptor or {}
    display=entry.get('display_profile') or data.get('extensions',{}).get('display_profile',{})
    if not isinstance(display,dict):display={}
    personality=entry.get('personality') or display.get('personality','')
    age=entry.get('age',display.get('age','未设定'))
    if not isinstance(age,(str,int)):age='未设定'
    return {'id':key,'name':name,'age':str(age) or '未设定',
        'summary':entry.get('short_personality') or display.get('summary') or personality.split('。')[0][:65] or '性格尚未设定',
        'description':entry.get('biography') or display.get('biography') or descriptor.get('bio') or '人物简介尚未整理。',
        'personality':personality,'appearance':entry.get('appearance') or display.get('appearance',''),
        'avatar':entry.get('avatar') or display.get('avatar') or descriptor.get('avatar') or descriptor.get('sprites',{}).get('neutral',''),
        'aliases':entry.get('aliases',[]),'source':entry.get('source','')}

def script_profiles(player,script_id):
    script=next((s for s in player.script_list() if s['id']==script_id),None)
    if script is None:raise ValueError('找不到这个剧本。')
    snapshot=player.worlds.snapshot(script['card_id'],script['world_id'],script['setting_set_ids'])
    result=[];seen=set()
    for settings in snapshot.get('setting_sets',[]):
        for entry in settings['cards']:
            if entry['kind']!='character' or entry['name'] in seen:continue
            seen.add(entry['name']);cid=entry.get('card_id')
            result.append(profile(settings['id']+'-'+entry['id'],entry['name'],entry.get('card_snapshot',{}).get('data',{}),entry,player.descriptor(cid) if cid else {}))
    if not result:
        _,record=player.tavern.find_record(player.root,'cards',script['card_id'])
        result=[profile(script['card_id'],record['card']['data']['name'],record['card']['data'],descriptor=player.descriptor(script['card_id']))]
    return {'title':script['display_name']+' · 人物图鉴','cards':result}

def protagonist_profiles(player):
    from cast import player_cards
    result=[]
    for card in player_cards(player.root):
        entry=dict(card)
        data=card.get('card_snapshot',{}).get('data',{})
        display=card.get('display_profile') or data.get('extensions',{}).get('display_profile',{})
        if card['id']=='hachiman' and not display:
            display={'biography':'总武高中二年级学生。惯于独来独往，善于观察人际关系，以干涩的幽默和自嘲应对日常。加入侍奉部后，开始接触不同同学的烦恼与委托。',
                'personality':'观察敏锐，独立谨慎，带着自嘲的幽默。','summary':'观察敏锐，独立谨慎，幽默而自嘲。'}
        if card['id']=='hachiman':
            entry.setdefault('avatar','')
        entry['display_profile']=display
        entry['biography']=display.get('biography','')
        entry['personality']=display.get('personality','')
        result.append(profile(card['id'],card['name'],data,entry))
        if not result[-1]['avatar']:result[-1]['avatar']=card.get('reference','')
    return {'title':'主角卡','cards':result}
