"""Declared daily opening windows, independent of a model's invented limits."""
import copy
from event_schema import number
from world_state import read, put, clock_time


def is_open(windows, minute):
    return any(start <= minute < end if start < end else minute >= start or minute < end for start, end in windows)


def validate(config):
    from map_runtime import get_locations
    places=get_locations({'config':config})
    for lid, windows in config.get('opening_hours', {}).items():
        if lid not in places or not isinstance(windows, list) or len(windows)>4:
            raise ValueError('Invalid opening hours')
        for pair in windows:
            if not isinstance(pair,list) or len(pair)!=2:raise ValueError('Invalid opening window')
            number(pair[0],0,1439);number(pair[1],0,1440)
            if pair[0]==pair[1]:raise ValueError('Empty opening window')


def boundaries(tx,target):
    now=clock_time(tx.state)
    result=[]
    for day in range(now//1440,target//1440+1):
        for windows in tx.definition['config'].get('opening_hours',{}).values():
            result.extend(day*1440+m for pair in windows for m in pair if now<day*1440+m<=target)
    return result


def settle(tx):
    for lid,windows in tx.definition['config'].get('opening_hours',{}).items():
        opened=is_open(windows,tx.state['clock']['minute'])
        if read(tx.state,'place:'+lid,{}).get('open',True)==opened:continue
        tx.apply({'template':'builtin.availability','location':lid,'open':opened},True,'剧本声明的营业时段','opening-hours')

