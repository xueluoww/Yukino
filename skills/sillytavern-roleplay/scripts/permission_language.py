"""Exact affirmative permission spans and conservative object grounding."""
import re

def affirmative(text,evidence):
    if not isinstance(evidence,str) or not evidence or evidence not in text:return False
    # Match the permission-bearing clause; later return/care restrictions do not revoke onsite reading.
    for match in re.finditer(r'(?:可以|允许|给你|请).{0,16}?(?:阅读|翻阅|翻翻|看|读)',text):
        start=max(text.rfind(ch,0,match.start()) for ch in '。！？!?\n，,；;')+1
        ends=[text.find(ch,match.end()) for ch in '。！？!?\n，,；;']
        end=min([n for n in ends if n>=0],default=len(text))
        clause=text[start:end];punct=text[end:end+1]
        if match.group() not in evidence and evidence not in clause:continue
        if punct in ('？','?') or re.search(r'吗|么|是否|能否|可不可以|如果|假如|只要|要是|先问|先确认|不可以|不能|不许|商量',clause):continue
        prefix=text[:start]
        # A condition before the permission in the same sentence remains a prerequisite.
        sentence=prefix[max(prefix.rfind(ch) for ch in '。！？!?\n')+1:]
        if re.search(r'如果|假如|只要|要是|先确认|先问',sentence):continue
        return True
    return False

def requested_instances(tx,owner,reader,owned,text):
    """A shelf request must not silently bind the owner's held book."""
    from world_state import read,location
    turns=read(tx.state,'dialogue:'+owner,{}).get('turns',[])[-8:]
    request=next((t.get('text','') for t in reversed(turns) if t.get('speaker')==reader and t.get('at',-100)>=__import__('world_state').clock_time(tx.state)-5 and re.search('看|读|翻|借',t.get('text',''))),'')
    utterance=request or text
    if re.search('书架|架上|桌上|桌边',utterance) and not re.search('我(?:的|这本|手里)|给你这本',text):
        return [],request
    selected=[]
    for item in owned:
        obj=read(tx.state,'item:'+item['instance'],{})
        spec=tx.definition['items'][obj['item']]
        names=[spec['name'],*spec.get('aliases',[])]
        if any(n and n in utterance for n in names):selected.append(item['instance'])
    # Explicitly offered own object may ground an unsolicited permission.
    if not selected and re.search('书',utterance) and not re.search('笔记本|社团资料',utterance):
        books=[i for i in owned if (tx.definition['items'][read(tx.state,'item:'+i['instance'])['item']].get('category')=='book' or re.search('小说|文库本|书',i['name'])) and not re.search('笔记|书包|申请|表格',i['name'])]
        if len(books)==1 and re.search('手里|手中|这本|你的',utterance):return [books[0]['instance']],request
        return [],request
    if not selected and len(owned)==1 and (re.search('这本|这份|我的|手里|给你',utterance) or re.search(r'(?:翻翻|阅读|翻阅|看|读)(?:[。！？?，,；;]|$)',utterance)):
        selected=[owned[0]['instance']]
    return selected,request


def withdrawal(text):
    for match in re.finditer(r'不能(?:再)?看|不可以(?:再)?看|别(?:再)?看|收回.{0,8}(?:许可|允许)|不许(?:再)?(?:看|读|翻)',text):
        start=max(text.rfind(ch,0,match.start()) for ch in '。！？!?\n，,；;')+1
        ends=[text.find(ch,match.end()) for ch in '。！？!?\n，,；;']
        end=min([n for n in ends if n>=0],default=len(text))
        clause=text[start:end]
        if text[end:end+1] not in ('？','?') and not re.search('吗|是否|能否|如果|假如|要是',clause):return True
    return False
