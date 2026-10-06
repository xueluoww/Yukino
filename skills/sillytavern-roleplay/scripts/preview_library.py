"""Finite reservations. Unused and failed previews retain their quota slot."""
import copy
from pathlib import Path
import threading
import json

QUOTAS={'background':2,'portrait':3,'interaction':1}

class PreviewLibrary:
    def __init__(self,root,tavern):
        self.folder=Path(root)/'browser/prediction-library';self.tavern=tavern;self.lock=threading.RLock()
    def path(self,scope):
        if not scope.isalnum():raise ValueError('Invalid prediction scope')
        return self.folder/scope/'index.json'
    def read(self,scope):
        p=self.path(scope)
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'scope':scope,'quotas':QUOTAS.copy(),'entries':{}}
    def write(self,data):self.tavern.atomic_json(self.path(data['scope']),data)
    def slots(self,scope):
        data=self.read(scope)
        return {k:max(0,v-sum(e['kind']==k and e['status']!='used' for e in data['entries'].values())) for k,v in data['quotas'].items()}
    def reserve(self,scope,key,item):
        with self.lock:
            data=self.read(scope)
            if key in data['entries'] or not self.slots(scope).get(item['kind'],0):return False
            data['entries'][key]=copy.deepcopy(item)|{'key':key,'status':'queued','hypothetical':True}
            self.write(data);return True
    def update(self,scope,key,**values):
        with self.lock:
            data=self.read(scope)
            if key not in data['entries']:return
            data['entries'][key].update(values);self.write(data)
    def find(self,scope,key):return self.read(scope)['entries'].get(key)
    def consume(self,scope,key):
        with self.lock:
            data=self.read(scope);item=data['entries'].get(key)
            if not item or item['status']!='ready':return None
            item['status']='used';item['hypothetical']=False;self.write(data);return copy.deepcopy(item)
    def public(self,scope):
        data=self.read(scope);entries=[{k:v for k,v in e.items() if k in {'key','kind','name','url','status'}} for e in data['entries'].values() if e['status']!='used']
        return {'quotas':data['quotas'],'slots':self.slots(scope),'entries':entries}
