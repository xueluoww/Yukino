"""Recover missing speech citations against the speaker's permitted facts, not world truth."""
import re
from actor_context import authorize_claims

INSTRUCTIONS='''只检查实际说出的text与allowed_sources的对应关系，JSON {references:[{source,evidence}]}。
source仅allowed_sources的ID；evidence必须逐字引用text中已经表达该来源知识的片段。不得补充没说的细节，不引用目标、意图、关系或未获准知识。没有对应就[]。
引用只表示听者听到了这句话，不证明客观真相，不把完整来源交给听者。'''

def recover(tx,gateway,actor,text,view,claims):
    if not gateway or claims:return claims
    sources=[c for c in view['cards']if c['template']=='knowledge'and c['value'].get('disclose',True)]
    if not sources or not re.search(r'在|知道|记得|听说|有|位于',text):return claims
    from world_turn import validated_request
    allowed={c['id']:c for c in sources}
    def check(answer):
        refs=answer.get('references')
        if set(answer)!={'references'}or not isinstance(refs,list)or len(refs)>8:raise ValueError('Invalid spoken sources')
        for r in refs:
            if not isinstance(r,dict)or set(r)!={'source','evidence'}or r['source']not in allowed:raise ValueError('Spoken source outside disclosure scope')
            if not isinstance(r['evidence'],str)or not r['evidence']or r['evidence']not in text:raise ValueError('Spoken source requires literal evidence')
        authorize_claims(view,[r['source']for r in refs],text)
    try:
        answer=validated_request(gateway,'spoken-sources:'+actor,INSTRUCTIONS,{'text':text,'allowed_sources':sources},check,400)
        return list(dict.fromkeys(r['source']for r in answer['references']))
    except (ValueError,TypeError,KeyError)as error:
        from diagnostic_system import record
        record(tx,actor,'spoken-sources',error,disposition='speech-retained-no-knowledge-copy')
        return claims
