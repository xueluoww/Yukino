"""Owner-issued onsite reading permissions; speech is not ownership transfer."""
import copy,re
from world_state import read,colocated,clock_time
from goal_sets import store_card

DETECT='''从owner真正说出的text提取明确允许reader现场阅读的授权，仅JSON {grants:[{instance,reader,evidence}]}。
instance仅owned_items，reader仅listeners。evidence逐字引用text中明确允许阅读/翻看的句子。
身份/用途尚需确认、如果/只要等条件、可以商量都不等于无条件阅读授权；允许现场阅读但拒绝带走仍是现场阅读许可。不能凭请求者的话授权。
只能授权现场读，不转移所有权，不允许拿走；没有明确同意则grants=[]。'''


def valid(state,definition,actor,instance):
    item=read(state,'item:'+instance,{})
    permit=read(state,'readpermit:'+instance+':'+actor,{})
    return bool(item and permit.get('status')=='active' and permit.get('issuer')==item['owner']
                and permit.get('reader')==actor and clock_time(state)<=permit['expires']
                and colocated(state,actor,item['owner'])and item['quantity']>0)


def from_speech(tx,gateway,speech_record):
    speech=speech_record.get('speech',{});owner=speech.get('actor');text=speech.get('text','')
    owned=[{'instance':c['id'][5:],'name':tx.definition['items'][c['value']['item']]['name']}for c in tx.state['cards'].values()
           if c['template']=='item'and c['value']['owner']==owner and c['value']['quantity']>0 and 'read'in tx.definition['items'][c['value']['item']].get('capabilities',{})]
    if not owned:return
    # Explicit withdrawal invalidates only this owner's grants to actual listeners.
    from permission_language import withdrawal
    if withdrawal(text):
        for cid,c in list(tx.state['cards'].items()):
            if c['template']=='read_permission'and c['value']['issuer']==owner and c['value']['reader']in speech['audience']:
                v=copy.deepcopy(c['value']);v['status']='revoked';store_card(tx,cid,'read_permission',v,owner,'人物撤回现场阅读许可')
        return
    if not gateway or not re.search(r'可以|允许|给你|请.{0,6}(?:看|读|翻)',text):return
    from world_turn import validated_request
    def check(answer):
        if set(answer)!={'grants'}or not isinstance(answer['grants'],list)or len(answer['grants'])>3:raise ValueError('Invalid reading grant')
        for grant in answer['grants']:
            if not isinstance(grant,dict)or set(grant)!={'instance','reader','evidence'}:raise ValueError('Invalid reading grant fields')
            if grant['instance']not in {i['instance']for i in owned}or grant['reader']not in speech['audience']:raise ValueError('Grant outside ownership/audience')
            evidence=grant['evidence']
            if not isinstance(evidence,str)or evidence not in text or not re.search(r'(?:可以|允许|给你|请).{0,16}(?:看|阅读|翻阅|翻翻|读)',evidence):raise ValueError('Grant requires explicit owner permission')
            from permission_language import affirmative,requested_instances
            if not affirmative(text,evidence):raise ValueError('Question/conditional statement is not a reading permission')
            allowed,_=requested_instances(tx,owner,grant['reader'],owned,text)
            if grant['instance'] not in allowed:raise ValueError('Reading permission does not bind the actual requested object')
    from permission_language import requested_instances
    requests=[{'reader':reader,'instances':requested_instances(tx,owner,reader,owned,text)[0],
               'request':requested_instances(tx,owner,reader,owned,text)[1]} for reader in speech['audience']]
    try:answer=validated_request(gateway,'reading-grant:'+owner,DETECT+' grants只能使用reading_requests中该reader的instances；问句不是许可；不把可以现场看但不能带走误判为拒绝阅读。',{'owner':owner,'owned_items':owned,'listeners':speech['audience'],'text':text,'reading_requests':requests},check,350)
    except (ValueError,TypeError,KeyError)as error:
        from diagnostic_system import record
        record(tx,owner,'reading-grant',error,disposition='withheld');return
    for grant in answer['grants']:
        if not colocated(tx.state,owner,grant['reader']):continue
        cid='readpermit:'+grant['instance']+':'+grant['reader']
        store_card(tx,cid,'read_permission',{'owner':owner,'issuer':owner,'reader':grant['reader'],'instance':grant['instance'],
          'status':'active','expires':clock_time(tx.state)+30,'evidence':grant['evidence'],'source_event':speech_record['event_id']},owner,'人物授权现场阅读')
        # The actual listener receives this explicit permission, not the owner's private goal.
        old=copy.deepcopy(tx.state);tx.state['cards'][cid]['visibility']=[owner,grant['reader']]
        tx.record({'template':'builtin.read_permission_delivery','effects':[],'title':'现场阅读许可已传达','outcome':'applied','participants':[owner,grant['reader']],
                    'observers':[owner,grant['reader']],'public':{'instance':grant['instance']},'rule_id':'read-permission'},old)
