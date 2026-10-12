"""Lossless on-disk compression of repeated world snapshots; runtime remains plain JSON."""
import base64, copy, json, zlib
MARKER='$yukino_state_zlib_v1'
MAX_STATE=32*1024*1024
CHECKPOINT_MARKER='$yukino_checkpoint_zlib_v1'
MAX_CHECKPOINT=128*1024*1024

def pack_checkpoint(value):
    """Standalone full snapshot: no dependency on later saves or adjacent files."""
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>MAX_CHECKPOINT:raise ValueError('Checkpoint exceeds storage limit')
    return {CHECKPOINT_MARKER:base64.b64encode(zlib.compress(raw,3)).decode('ascii')}

def unpack_checkpoint(value):
    if not isinstance(value,dict) or set(value)!={CHECKPOINT_MARKER}:return value
    encoded=value[CHECKPOINT_MARKER]
    if not isinstance(encoded,str) or len(encoded)>MAX_CHECKPOINT*2:raise ValueError('Compressed checkpoint exceeds limit')
    decoder=zlib.decompressobj();raw=base64.b64decode(encoded,validate=True)
    try:data=decoder.decompress(raw,MAX_CHECKPOINT+1)
    except zlib.error as error:raise ValueError('Invalid compressed checkpoint') from error
    if len(data)>MAX_CHECKPOINT or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized compressed checkpoint')
    result=json.loads(data.decode('utf-8'))
    if not isinstance(result,dict) or not isinstance(result.get('turns'),list):raise ValueError('Invalid checkpoint document')
    return result

def unpack_state(value):
    if not isinstance(value,dict) or set(value)!={MARKER}:return value
    encoded=value[MARKER]
    if not isinstance(encoded,str) or len(encoded)>MAX_STATE*2:raise ValueError('Compressed state exceeds limit')
    raw=base64.b64decode(encoded,validate=True); decoder=zlib.decompressobj()
    data=decoder.decompress(raw,MAX_STATE+1)
    if len(data)>MAX_STATE or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized compressed state')
    result=json.loads(data.decode('utf-8'))
    if not isinstance(result,dict):raise ValueError('World state must be an object')
    return result

def decode_document(value):
    value=unpack_checkpoint(value)
    if isinstance(value,dict):
        for turn in value.get('turns',[]) if isinstance(value.get('turns'),list) else []:
            if isinstance(turn,dict) and isinstance(turn.get('world_packet'),dict):
                packet=turn['world_packet']
                if 'state_after' in packet:packet['state_after']=unpack_state(packet['state_after'])
    return value

def encode_document(value):
    if not isinstance(value,dict) or not isinstance(value.get('turns'),list) or not value['turns']:return value
    result=dict(value);result['turns']=[]
    for turn in value['turns']:
        if not isinstance(turn,dict) or not isinstance(turn.get('world_packet'),dict):result['turns'].append(turn);continue
        item=dict(turn);packet=dict(turn['world_packet'])
        if 'state_after' not in packet:result['turns'].append(turn);continue
        state=packet['state_after']
        if not(isinstance(state,dict) and set(state)=={MARKER}):
            raw=json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            if len(raw)>MAX_STATE:raise ValueError('World state exceeds storage limit')
            packet['state_after']={MARKER:base64.b64encode(zlib.compress(raw,6)).decode('ascii')}
        item['world_packet']=packet;result['turns'].append(item)
    return result

def loads(text):return decode_document(json.loads(text))
