"""Shell physical affordances; authors provide content and matching conditions."""
import copy

CAPABILITIES={'read':{'content'},'write':set(),'consume':set(),'unlock':{'lock_id'},'pay':{'currency'}}

def merge_portions(value,old):
 if old and old.get('quantity',0)>0 and 'remaining_portions' in old:
  if 'remaining_portions' in value:raise ValueError('两份已用过的物品不能合并为一份，请分别携带。')
  value['remaining_portions']=old['remaining_portions']

def validate_item(card):
 caps=card.get('capabilities',{})
 if not isinstance(caps,dict)or set(caps)-set(CAPABILITIES):raise ValueError('Unknown item capability; use a script module')
 for name,params in caps.items():
  if not isinstance(params,dict)or not CAPABILITIES[name]<=set(params):raise ValueError('Incomplete item capability')
  if any(k in params for k in('code','effects','exec','template')):raise ValueError('Items cannot embed executable capabilities')
  if name=='read'and(not isinstance(params['content'],str)or len(params['content'])>5000):raise ValueError('Readable content must be bounded text')
  if name=='consume' and 'portions' in params:
   from event_schema import number
   number(params['portions'],2,1000)
  if name in('unlock','pay'):
   from event_schema import identifier
   identifier(params['lock_id']if name=='unlock'else params['currency'])
 return True

def apply_item(state,e,definition):
 from world_state import read,put,location,colocated
 actor=e['actor'];kind=e['template'][8:];cid='item:'+e['instance'];item=read(state,cid)
 if not item or item['quantity']<=0:raise ValueError('No available item instance')
 if item['location']!=location(state,actor)or read(state,'loc:'+actor,{}).get('transit_to'):raise ValueError('Item not physically accessible')
 if definition['config'].get('world_mode')and read(state,'loc:'+actor,{}).get('at_entrance')and item['owner']!=actor:raise ValueError('Cannot reach items inside a closed place from its entrance')
 card=definition['items'][item['item']];validate_item(card)
 public={'actor':actor,'item':item['item'],'instance':e['instance']};observers={actor}
 if kind=='take':
  if definition['config'].get('card_refinement')and item['owner']==actor:
   public.update(already_owned=True,quantity=0);return public,observers
  if item['owner']!=location(state,actor):raise ValueError('Taking somebody else\'s property requires checked consent or a gameplay rule')
  qty=e.get('quantity',1)
  if qty>item['quantity']:raise ValueError('Insufficient item quantity')
  dest=cid+':'+actor;old=read(state,dest,{})
  if old and old['item']!=item['item']:raise ValueError('Instance collision')
  v=copy.deepcopy(item);v['quantity']-=qty;v.pop('remaining_portions',None);put(state,cid,'item',v,[item['owner']],[actor])
  received={**item,'owner':actor,'quantity':qty+old.get('quantity',0)};merge_portions(received,old)
  put(state,dest,'item',received,[actor],[actor])
  public.update(quantity=qty,received_instance=dest[5:])
 elif kind=='put_down':
  if item['owner']!=actor:raise ValueError('Only own item can be put down')
  v=copy.deepcopy(item);v['owner']=location(state,actor);put(state,cid,'item',v,[v['owner']],[actor]);public['location']=v['owner']
 else:
  authorized_read=False
  if kind in ('read','open_item','close_item')and definition['config'].get('world_mode'):
   from read_permissions import valid
   authorized_read=valid(state,definition,actor,e['instance'])
  if item['owner']!=actor and not authorized_read:raise ValueError('Use requires possession or owner-issued onsite reading permission')
  caps=card.get('capabilities',{})
  if kind in ('open_item','close_item'):
   if not set(caps)&{'read','write'}:raise ValueError('此物品没有可翻开的书页。')
   value=copy.deepcopy(item);value['opened']=kind=='open_item'
   viewers=set(state['cards'][cid]['visibility'])|{actor,item['owner']}
   put(state,cid,'item',value,[item['owner']],sorted(viewers))
   public['opened']=value['opened']
  elif kind=='read':
   if 'read'not in caps:raise ValueError('Item cannot be read')
   content=caps['read']['content']
   if item.get('written_content'):content+='\n'+item['written_content']
   topic='read-'+e['instance']
   put(state,'know:'+actor+':'+topic,'knowledge',{'holder':actor,'topic':topic,'content':content,'belief':'observed',
    'source':{'kind':'read','target':e['instance']},'disclose':True},[actor],[actor]);public['content']=content
  elif kind=='write':
   if 'write'not in caps:raise ValueError('Item cannot be written on')
   content=item.get('written_content','')+'\n'+e['text']
   if len(content)>12000:raise ValueError('Written content is full')
   value=copy.deepcopy(item);value['written_content']=content.strip()
   value['written_by']=actor if not item.get('written_content') or item.get('written_by')==actor else None
   put(state,cid,'item',value,[actor],[actor])
   public['text']=e['text']
  elif kind=='consume':
   if 'consume'not in caps:raise ValueError('Item is not edible')
   qty=e.get('quantity',1)
   if qty>item['quantity']:raise ValueError('Insufficient edible quantity')
   v=copy.deepcopy(item)
   # Abstract portions track one opened unit, not invented millilitres. Older
   # consumables without an authored size use ten small portions at runtime.
   portions=caps['consume'].get('portions',10)
   remaining=item.get('remaining_portions',portions)
   from event_schema import number
   number(remaining,1,portions)
   small=e.get('portion','all')=='small'
   if small:
    if qty!=1:raise ValueError('A small portion acts on one held unit')
    remaining-=1
    finished=int(remaining==0)
    v['quantity']-=finished
    if finished:v.pop('remaining_portions',None)
    else:v['remaining_portions']=remaining
   else:
    finished=qty;v['quantity']-=qty;v.pop('remaining_portions',None)
   put(state,cid,'item',v,[actor],[actor])
   public.update(quantity=finished,portion='small' if small else 'all',
                 remaining_quantity=v['quantity'],remaining_portions=v.get('remaining_portions'),finished_unit=bool(finished))
  elif kind=='use':
   target=e.get('target')
   if 'unlock'in caps:
    door=definition['config'].get('doors',{}).get(target)
    if not door or door['location']!=location(state,actor):raise ValueError('Door not here')
    if caps['unlock']['lock_id']!=door['lock_id']:raise ValueError('Key does not match lock')
    put(state,'door:'+target,'door',{'locked':False},[target],[actor]);public['target']=target
   elif 'pay'in caps:
    offer=definition['config'].get('commerce',{}).get(target)
    if not offer or offer['location']!=location(state,actor):raise ValueError('No local trade offer')
    seller=offer['seller'];stock=read(state,'item:'+offer['instance']);price=offer['price']
    if caps['pay']['currency']!=offer['currency']:raise ValueError('Currency mismatch')
    if not colocated(state,actor,seller)or not stock or stock['owner']!=seller or stock['quantity']<1:raise ValueError('Seller or stock unavailable')
    if type(price)is not int or price<1 or item['quantity']<price:raise ValueError('Insufficient funds or invalid price')
    if not read(state,'place:'+location(state,actor),{}).get('open',True):raise ValueError('Trading place closed')
    v=copy.deepcopy(item);v['quantity']-=price;put(state,cid,'item',v,[actor],[actor])
    seller_money=cid+':'+seller;balance=read(state,seller_money,{})
    put(state,seller_money,'item',{**item,'owner':seller,'quantity':price+balance.get('quantity',0)},[seller],[seller])
    stock_id='item:'+offer['instance'];v=copy.deepcopy(stock);v['quantity']-=1;put(state,stock_id,'item',v,[seller],[seller])
    dest=stock_id+':'+actor;previous=read(state,dest,{})
    if previous and previous['item']!=stock['item']:raise ValueError('Purchased instance collision')
    put(state,dest,'item',{**stock,'owner':actor,'quantity':1+previous.get('quantity',0)},[actor],[actor])
    public.update(target=target,currency=offer['currency'],price=price,purchased_item=stock['item']);observers.add(seller)
   else:raise ValueError('Use needs a matching capability or gameplay module')
  else:raise ValueError('Unknown item operation')
 return public,observers
