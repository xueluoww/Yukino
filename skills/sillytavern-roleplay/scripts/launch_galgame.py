#!/usr/bin/env python3
"""Start/reuse the local galgame player without leaving a console window."""
import argparse, json, os, pathlib, subprocess, sys, time, urllib.request, webbrowser

def health(url,endpoint='/health'):
    try:
        with urllib.request.urlopen(url+endpoint,timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None

def main():
    from galgame import APP_VERSION
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[3]/'database/roleplay-library'))
    parser.add_argument('--card')
    parser.add_argument('--port',type=int)
    parser.add_argument('--session')
    parser.add_argument('--persistent',action='store_true')
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--provider',choices=['deepseek','codex','bridge','demo'],default='deepseek')
    args=parser.parse_args()
    root=pathlib.Path(args.root).resolve()
    if args.port is None:
        args.port=18765
        record=root/'browser/server.json'
        if record.exists():
            try:
                previous=json.loads(record.read_text(encoding='utf-8-sig'))
                from urllib.parse import urlparse
                parsed=urlparse(previous.get('url',''))
                if parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port:
                    found=health(previous['url'])
                    if found and found.get('app')=='galgame' and pathlib.Path(found.get('root','')).resolve()==root:
                        args.port=parsed.port
            except (OSError,ValueError,TypeError):
                pass
    url=f'http://127.0.0.1:{args.port}'
    existing=health(url)
    if existing:
        if existing.get('app')!='galgame' or pathlib.Path(existing.get('root','')).resolve()!=root:
            raise SystemExit('该端口正在用于其他资料库，请选另一个明确端口。')
        current_provider=existing.get('provider') or (health(url,'/api/state') or {}).get('provider')
        if current_provider!=args.provider or existing.get('app_version')!=APP_VERSION:
            raise SystemExit('该资料库仍在使用其他对白引擎，请先安全重启舞台。')
        if args.session or args.persistent:
            raise SystemExit('舞台已运行，请在舞台菜单中开启新剧情或恢复对应存档。')
    else:
        folder=root/'browser';folder.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-X','utf8',str(pathlib.Path(__file__).with_name('galgame.py')),
                 '--root',str(root),'--port',str(args.port),'--provider',args.provider]
        if args.card:command.extend(['--card',args.card])
        if args.session:command.extend(['--session',args.session])
        if args.persistent:command.append('--persistent')
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        with (folder/'launch.log').open('ab') as log:
            process=subprocess.Popen(command,stdout=log,stderr=log,stdin=subprocess.DEVNULL,creationflags=flags,
                start_new_session=os.name!='nt',cwd=folder)
        for _ in range(40):
            if health(url):break
            if process.poll() is not None:raise SystemExit('启动失败，请检查 browser/launch.log。')
            time.sleep(.2)
        else:raise SystemExit('服务未能及时启动，请检查 browser/launch.log。')
    if args.open:webbrowser.open(url)
    print(json.dumps({'url':url,'root':str(root),'reused':bool(existing),'provider':args.provider},ensure_ascii=False))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
