"""Risk-triggered scoped fact flags. A verifier cannot grant any knowledge or action."""
import re,json
INSTRUCTIONS='''只返回JSON {"flags":[]}，审核text中的具体事实而非文采。flags项{kind:"consistency",severity:"block",evidence:逐字text片段,reason:理由}。人物的具体路线、街道方向、书名作者、亲身过去经历必须有view来源。听别人说的不能改成自己见过/常去。view里只有地点ID或相邻路线不能推导出向左/过几个路口。可以提出泛指的可能方法/推测，但不把不存在的具体设施说成真实地点。本人有来源的观察可以说。未知身份不能靠全知名字判断；不违背静态性格。只标记，不作决定，不改世界，不执行。没有缺陷flags=[]。'''

def risky(text):return bool(re.search(r'路线|方向|怎么走|往.{0,6}(?:街|走)|街|巷|河沿|路口|城[东南西北]|作者|出版社|《|我.{0,16}(?:见过|去过|常去|亲眼|经常去)|我(?:平时|自己).{0,12}(?:熟悉|熟|去)',text))

def check_facts(tx,gateway,actor,text,view):
 if not gateway or not(risky(text)or tx.definition['config'].get('background_planning')):return []
 from world_turn import validated_request
 def valid(a):
  flags=a.get('flags')
  if not isinstance(flags,list)or len(flags)>6:raise ValueError('Invalid factual flags')
  for f in flags:
   if not isinstance(f,dict)or f.get('kind')!='consistency'or f.get('severity')!='block'or not isinstance(f.get('evidence'),str)or not f['evidence']or f['evidence']not in text:raise ValueError('Fact flag must cite actual prose')
 # An earlier generated utterance is not its own factual source.
 scoped={k:v for k,v in view.items()if k not in('observations','heard_dialogue','goal_feedback','opportunities')}
 scoped['cards']=[c for c in scoped['cards']if c['template']in('knowledge','item','location','relation','goal')]
 return validated_request(gateway,'fact-review:'+actor,INSTRUCTIONS+' 仅view静态资料/knowledge来源和实际item/location是事实依据，目标表达愿望而不是已经完成。没有来源的旧书市、河沿巷口、路口数量必须标记，不能因为用“听说”“大概”就凭空制造路线。',{'view':scoped,'text':text},valid,500)['flags']
