"""Launch Yukino with a private project library initialized from one public demo."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse, json, shutil, subprocess, urllib.request

ROOT = Path(__file__).resolve().parent
SKILL = ROOT/'skills/sillytavern-roleplay'
LIBRARY = ROOT/'database/roleplay-library'
SEED = ROOT/'examples/demo-library'
DEMO_ID = 'demo000000000001'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check local files without model calls or data writes')
    parser.add_argument('--demo', action='store_true', help='Open the prewritten demo without model calls')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--no-images', action='store_true')
    parser.add_argument('--stop', action='store_true', help='Stop this project service when idle')
    parser.add_argument('--port', type=int, default=18772)
    parser.add_argument('--session')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:parser.error('Invalid port')
    if args.demo and args.session:parser.error('--demo uses its own authored save; omit --session')
    url = f'http://127.0.0.1:{args.port}'
    if args.stop:
        try:
            with urllib.request.urlopen(url+'/health', timeout=3) as response:health=json.load(response)
            if health.get('app')!='galgame' or Path(health.get('root','')).resolve()!=LIBRARY.resolve():
                parser.error('This port belongs to another project; no service was stopped.')
            with urllib.request.urlopen(url+'/api/session-token', timeout=3) as response:token=json.load(response)['token']
            request=urllib.request.Request(url+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','Origin':url,'X-Session-Token':token},method='POST')
            with urllib.request.urlopen(request,timeout=5) as response:response.read()
        except (OSError,ValueError) as error:raise SystemExit('Unable to stop the idle service: '+str(error))
        print('Yukino service stopped.')
        return
    library=LIBRARY if LIBRARY.exists() else SEED
    for item in (SKILL/'SKILL.md',SKILL/'scripts/launch_galgame.py',library/'cards',library/'sessions'):
        if not item.exists():parser.error(f'Missing file or directory: {item}')
    if args.check:
        count=0
        for file in library.rglob('*.json'):
            json.loads(file.read_text(encoding='utf-8-sig'));count+=1
        sys.path.insert(0,str(SKILL/'scripts'))
        from galgame import APP_VERSION
        print(json.dumps({'project':'Yukino','version':(ROOT/'VERSION').read_text().strip(),'runtime':APP_VERSION,
              'library':str(library),'data_initialized':LIBRARY.exists(),'demo_saves':len(list((SEED/'sessions').glob('*.json'))),
              'port':args.port,'validated_json_files':count,'model_requests':False},ensure_ascii=False,indent=2))
        return
    if not LIBRARY.exists():
        LIBRARY.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(SEED,LIBRARY)
    command=[sys.executable,'-B','-X','utf8',str(SKILL/'scripts/launch_galgame.py'),
             '--root',str(LIBRARY),'--port',str(args.port),'--provider','demo' if args.demo else 'deepseek']
    if args.demo:
        command.extend(['--restore-session',DEMO_ID,'--no-images'])
    elif args.session:command.extend(['--session',args.session])
    if args.no_images and not args.demo:command.append('--no-images')
    if args.open:command.append('--open')
    raise SystemExit(subprocess.call(command,cwd=ROOT))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
