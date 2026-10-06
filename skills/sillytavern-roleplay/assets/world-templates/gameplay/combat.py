"""A separate sample battle module; no combat implementation in the host."""
def run(r):
    state=r['state'];effects=[];outcome=''
    if r['mode']=='initialize':state={'player_hp':30,'enemy_hp':24,'guard':False,'round':0,'result':''}
    if r['mode']=='event':
        action=r['event'].get('action_id')
        if state['result']:return {'state':state,'effects':[],'rejected':'战斗已经结束。'}
        if action=='retreat':state['result']='retreated';outcome='退出了交战范围。'
        elif action in ['attack','guard']:
            state['round']+=1
            if action=='attack':
                damage=4+r['context']['roll']%5;state['enemy_hp']=max(0,state['enemy_hp']-damage);outcome='攻击造成'+str(damage)+'点伤害。'
            if state['enemy_hp']==0:state['result']='won';outcome+='对手失去战斗能力。'
            else:
                damage=2 if action=='guard' else 5;state['player_hp']=max(0,state['player_hp']-damage);outcome+='受到'+str(damage)+'点伤害。'
                if state['player_hp']==0:state['result']='lost'
            effects=[{'type':'time','minutes':1,'reason':'一次交锋'}]
        else:return {'state':state,'effects':[],'rejected':'不存在这个战斗动作。'}
    actions=[]
    if not state['result']:
        actions=[{'id':'attack','label':'攻击','text':'【动作】寻找破绽，发动一次攻击。'},
                 {'id':'guard','label':'防御','text':'【动作】稳住姿势，防御对方的攻击。'},
                 {'id':'retreat','label':'撤退','text':'【动作】脱离交战范围，选择撤退。'}]
    return {'state':state,'effects':effects,'outcome':outcome,
        'view':{'cards':[{'title':'交战状态','text':'我方体力 '+str(state['player_hp'])+' / 对方体力 '+str(state['enemy_hp']),'status':{'won':'演练获胜','lost':'演练落败','retreated':'已退出','':'交战中'}[state['result']]}],'actions':actions},
        'context':{'rules':'结算由本模块负责，叙事不能另改伤害和结果。仅是战斗模板，未进行动作不能自动扣血。','progress':state}}
