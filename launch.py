"""Public launcher. Normal play uses data; offline authored demo is separate."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parent
SKILL=ROOT/'skills/sillytavern-roleplay'
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--open',action='store_true',help='Normal setup already opens a browser')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--no-images',action='store_true')
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--port',type=int,default=18777)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Invalid port')
    if args.check:
        files=(ROOT/'launcher/setup.py',SKILL/'scripts/galgame.py',SKILL/'assets/world-templates/oregairu-script.json')
        if not all(p.is_file() for p in files):raise SystemExit('Missing program files')
        json.loads(files[-1].read_text(encoding='utf-8-sig'))
        print(json.dumps({'project':'Yukino','version':(ROOT/'VERSION').read_text().strip(),
            'runtime':'5.7.10-world-trial','read_only':True,'model_requests':0},ensure_ascii=False))
        return 0
    if args.demo:
        library=ROOT/'demo-data'
        if not library.exists():shutil.copytree(ROOT/'examples/demo-library',library)
        command=[sys.executable,'-B','-X','utf8',str(SKILL/'scripts/launch_galgame.py'),
            '--root',str(library),'--port',str(args.port),'--provider','bridge','--no-images',
            '--restore-session','demo000000000001']
        if not args.no_browser:command.append('--open')
        return subprocess.call(command,cwd=ROOT)
    command=[sys.executable,'-B','-X','utf8',str(ROOT/'launcher/setup.py')]
    if args.stop:command.append('--stop')
    if args.no_browser:command.append('--no-browser')
    if args.no_images:print('Choose existing images on the setup page; saved provider was not overwritten.')
    return subprocess.call(command,cwd=ROOT)
if __name__=='__main__':raise SystemExit(main())
