"""Create a complete editable original story package without importing or starting it."""
import argparse,copy,json
from pathlib import Path
from worlds import identifier

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output');p.add_argument('--id',required=True);p.add_argument('--name',required=True)
    a=p.parse_args();iid=identifier(a.id);folder=Path(a.output).resolve()
    if folder.exists() and any(folder.iterdir()):raise ValueError('输出目录必须为空，避免覆盖已有剧本。')
    template=Path(__file__).parent.parent/'assets/world-templates/rainy-bookshop-script.json'
    raw=json.loads(template.read_text(encoding='utf-8-sig'));settings=copy.deepcopy(raw['setting_sets'][0]);old=settings['id'];settings['id']=iid+'-settings'
    mapping={}
    for card in settings['cards']:
        if card.get('card_id'):
            mapping[card['card_id']]=settings['id']+'-'+card['id'];card['card_id']=mapping[card['card_id']]
    world=copy.deepcopy(raw['world']);world['id']=iid;world['name']=a.name
    world['setting_set_ids']=[settings['id']];world['primary_card_id']=mapping[world['primary_card_id']]
    world.pop('calendar',None);world['time']={'version':1,'start':{'minute':1020,'label':'故事开篇'}};world.pop('world_gameplay',None)
    folder.mkdir(parents=True,exist_ok=True)
    for name,value in [('manifest.json',{'spec':'yukima_script_v1','world':'world.json','setting_sets':['settings.json'],'world_gameplay':[]}),('world.json',world),('settings.json',settings)]:
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (folder/'README.md').write_text((Path(__file__).parent.parent/'assets/script-readme.md').read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps({'created':str(folder),'note':'这是完整的原创示例骨架。请修改世界观、开场与人物资料；如需玩法，在 manifest.world_gameplay 添加模块路径，先 validate-script 再 import-script。'},ensure_ascii=False))

if __name__=='__main__':main()
