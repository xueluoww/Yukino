"""Visible/nearby people are narrower than an area's shared location ID."""
from world_state import read,colocated,location,clock_time

def visible_actor_ids(state,definition,observer='player'):
    from room_presence import small_space
    here=location(state,observer);actors=[a for a in [*definition['characters'],'player'] if a!=observer and colocated(state,a,observer)]
    if not definition['config'].get('world_mode'):return actors
    if small_space(definition,here,state):return actors
    dialogue=read(state,'dialogue:'+observer,{}).get('turns',[])[-3:]
    result=[]
    for actor in actors:
        contact=read(state,'encounter:'+observer+':'+actor,{})
        if contact.get('location')==here and contact.get('expires',-1)>=clock_time(state) or any(t.get('at',-100)<clock_time(state)+1 and t.get('at',-100)>=clock_time(state)-5 and (t.get('speaker')==actor or actor in t.get('addressees',[])) for t in dialogue):result.append(actor)
    return result

def can_hear(state,definition,a,b):
    if a==b:return True
    if b in visible_actor_ids(state,definition,a):return True
    for c in state['cards'].values():
        if c['template']!='door_contact':continue
        v=c['value']
        if set(v['actors'])=={a,b} and v['expires']>=clock_time(state) and v['locations']=={p:location(state,p) for p in v['actors']}:return True
    return False

def notice(tx,observer='player',limit=2):
    """An explicit look around can establish a bounded local encounter, never an entire crowd."""
    from event_schema import digest
    from world_state import put
    peers=[a for a in tx.definition['characters'] if a!=observer and colocated(tx.state,a,observer)]
    peers.sort(key=lambda a:digest([tx.state['rng']['seed'],tx.request_id,observer,a]))
    for actor in peers[:limit]:
        old=__import__('copy').deepcopy(tx.state)
        for a,b in ((observer,actor),(actor,observer)):
            put(tx.state,'encounter:'+a+':'+b,'encounter',{'location':location(tx.state,a),'expires':clock_time(tx.state)+5},[a],[a])
        tx.record({'template':'builtin.observe','effects':[],'title':'注意到附近的人','outcome':'applied','participants':[observer],
                   'observers':[observer],'public':{'actor':observer,'target':actor},'rule_id':'local-observation'},old)
