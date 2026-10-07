"""Keep immutable prompt prefixes ahead of branch-specific state, losslessly."""
import copy,json

def cache_context(context):
    """Reorder, never omit data. Variable ID/revision/input appear at the end."""
    result={}
    for key in ('character','perception_rules','protagonist','visual_locations','schedule_tendencies','cast','recent_turns'):
        if key in context:result[key]=copy.deepcopy(context[key])
    for key,value in context.items():
        if key not in result:result[key]=copy.deepcopy(value)
    # Identical meaning and fields, only serialization order changes.
    return result

def prompt_payload(descriptor,context):
    return json.dumps({'backgrounds':descriptor.get('background_descriptions',{}),
        'expressions':list(descriptor.get('sprites',{})),
        'default_appearance':descriptor.get('default_appearance','school-uniform'),
        'character_display_name':descriptor.get('name'),'context':cache_context(context)},
        ensure_ascii=False,separators=(',',':'))
