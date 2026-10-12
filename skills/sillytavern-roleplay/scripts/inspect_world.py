"""Read-only diagnostics. No credentials, no model and no world advancement."""
import argparse,json
from pathlib import Path
from world_turn import validate_packet
from world_state import state_hash
from actor_context import build_actor_view,build_event_reader_view

def inspect(session,mode='validate',actor=None):
 packets=[t['world_packet']for t in session['turns']if t.get('world_packet')]
 for i,p in enumerate(packets):
  validate_packet(p)
  if i and p['previous_head']!=packets[i-1]['head']:raise ValueError('Broken history chain')
  if i and p['before_hash']!=packets[i-1]['after_hash']:raise ValueError('Broken state ancestry')
 definition=session['facts']['browser_world_definition'];state=session['facts']['browser_world_state']
 if packets and (state_hash(state)!=packets[-1]['after_hash']or state['journal_head']!=packets[-1]['head']):raise ValueError('Current snapshot does not match committed journal')
 if mode=='explain-access':return build_actor_view(state,definition,actor)
 if mode=='explain-event':return build_event_reader_view(packets,definition,'world',limit=100)
 if mode=='replay':
  import copy
  result=copy.deepcopy(packets[-1]['state_after']if packets else state)
  if packets:result['journal_head']=packets[-1]['head']
  return result
 return {'valid':True,'packets':len(packets),'events':sum(len(p['records'])for p in packets),'mode':state['mode']}
def main():
 p=argparse.ArgumentParser();p.add_argument('session');p.add_argument('--mode',choices=['validate','explain-access','explain-event','replay'],default='validate');p.add_argument('--actor')
 args=p.parse_args();print(json.dumps(inspect(json.loads(Path(args.session).read_text(encoding='utf-8')),args.mode,args.actor),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
