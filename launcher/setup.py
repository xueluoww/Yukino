#!/usr/bin/env python3
"""Yukino 0.9 首启引导与本地管线。

只做四件事：
  1. 准备数据目录（data/），首次运行时把随包的春物剧本导入进去；
  2. 起一个只监听 127.0.0.1 的小服务，提供首启提示页（要求 / 介绍 / API Key 填写）；
  3. 把玩家填的 DeepSeek API Key 用项目自身的 DPAPI 模块存到 data/browser/credentials；
  4. Key 就绪后调用项目自带的脚本启动游戏服务，并把浏览器送到游戏地址。

启动器只在用户校验时请求 DeepSeek；游戏对话会发送场景上下文到 DeepSeek。
动态生图默认关闭，另行启用仍依赖 Codex 生图环境。
"""
import argparse
import json
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from service_control import PackageService, port_open, port_free, pick_port
from image_setup import ImageSetup

APP_NAME = 'Yukino 0.9'
RUNTIME_ID = '5.7.10-world-trial'
DEFAULT_ENGINE_PORT = 18767
DEFAULT_SETUP_PORT = 18766
SCRIPT_ID = 'oregairu-campus'
TEMPLATE_FILE = 'oregairu-script.json'
STATIC_FILES = {'/': 'welcome.html', '/welcome.html': 'welcome.html',
                '/welcome.css': 'welcome.css', '/welcome.js': 'welcome.js', '/image-setup.js': 'image-setup.js'}
MAX_BODY = 64 * 1024

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
if not APP.is_dir():
    APP = ROOT / 'skills/sillytavern-roleplay'
DATA = ROOT / 'data'
LAUNCHER = ROOT / 'launcher'
SCRIPTS = APP / 'scripts'


# ── 基础工具 ────────────────────────────────────────────────────────────
def ensure_data():
    for rel in ('worlds', 'sessions', 'protagonists', 'browser/credentials',
                'browser/checkpoints', 'browser/jobs'):
        (DATA / rel).mkdir(parents=True, exist_ok=True)


def run_python(args, timeout=600):
    command = [sys.executable, '-B', '-X', 'utf8', *[str(a) for a in args]]
    done = subprocess.run(command, cwd=str(APP), capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def ensure_script():
    target = DATA / 'worlds' / f'{SCRIPT_ID}.json'
    if target.exists():
        try:
            world = json.loads(target.read_text(encoding='utf-8-sig'))
            if not isinstance(world, dict) or world.get('id') != SCRIPT_ID:
                raise ValueError('Invalid world identity')
        except (OSError, ValueError):
            return False, '现有剧本文件无法读取，已保留原文件；请先备份资料库再检查。'
        return True, '剧本已就绪（保留原导入版本和存档）'
    if any((DATA / 'sessions').glob('*.json')) or any((DATA / 'cards').glob('*.json')):
        return False, '现有资料库缺少世界文件，已保留人物卡与存档，不会自动重新导入覆盖。'
    template = APP / 'assets' / 'world-templates' / TEMPLATE_FILE
    if not template.is_file():
        return False, '包内缺少剧本模板，请重新解压完整程序。'
    try:
        code, _ = run_python([SCRIPTS / 'worlds.py', '--root', DATA, 'import-script', template])
    except (OSError, subprocess.SubprocessError):
        return False, '首次导入剧本失败，现有文件已保留。'
    if code != 0 or not target.is_file():
        return False, f'首次导入剧本失败（退出码 {code}），请检查程序文件完整性。'
    protagonist = APP / 'assets/protagonists/hachiman.json'
    destination = DATA / 'protagonists/hachiman.json'
    if protagonist.is_file() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(protagonist, destination)
    return True, '已导入随包剧本'


def service():
    return PackageService(APP, DATA, RUNTIME_ID, run_python)


def engine_health(port, timeout=2.0):
    return service().health(port)


def engine_is_ours(health):
    return service().owns(health)


def start_engine(port):
    try:
        return service().start(port)
    except subprocess.SubprocessError:
        return False, '启动脚本超时或退出，请查看 data/browser/launch.log。'


def stop_engine(port):
    return service().stop(port)


def save_key(key):
    """复用项目自身的凭据模块（Windows DPAPI，仅当前用户可解）。"""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import deepseek_client
    except (OSError, ValueError, ImportError):
        return False, '无法加载本机凭据模块，请检查程序文件。'
    try:
        deepseek_client.store_key(str(DATA), key)
        return True, deepseek_client.credential_path(str(DATA))
    except (OSError, ValueError):
        return False, '无法保存本机加密密钥，请检查目录权限与 Windows 用户环境。'


def saved_key():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import deepseek_client
        return deepseek_client.load_key(str(DATA))
    except Exception:
        return ''


def verify_key(key):
    """Explicit user verification only; never echo credentials or upstream bodies."""
    request = urllib.request.Request('https://api.deepseek.com/models',
        headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            return False, 'DeepSeek 模型列表格式异常，原密钥未更改。'
        models = {row['id'] for row in payload['data'] if isinstance(row,dict) and isinstance(row.get('id'),str)}
        if 'deepseek-flash' not in models:
            return False, '当前密钥未提供本包使用的 deepseek-flash 模型，原密钥未更改。'
        return True, 'deepseek-flash'
    except urllib.error.HTTPError as exc:
        status=exc.code
        exc.close()
        return False, f'DeepSeek 校验失败（HTTP {status}），原密钥未更改。'
    except (OSError, ValueError):
        return False, '无法完成 DeepSeek 校验，原密钥未更改；请检查网络后重试。'


# ── 首启页服务 ──────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = 'YukinoSetup/0.9'

    def log_message(self, fmt, *args):
        print(f'  [首启页] {self.command} {urlsplit(self.path).path}')

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def allowed_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}

    def allowed_origin(self):
        return self.headers.get('Origin') in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Unsupported body encoding')
        length = int(self.headers.get('Content-Length') or 0)
        if not 0 < length <= MAX_BODY:
            raise ValueError('Invalid body length')
        if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
            raise ValueError('Expected JSON')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data,dict):
            raise ValueError('Expected JSON object')
        return data

    def do_GET(self):
        if not self.allowed_host() or self.headers.get('Sec-Fetch-Site')=='cross-site':
            return self.send_json({'ok':False,'error':'请从本机启动页访问。'},403)
        if self.headers.get('Origin') and not self.allowed_origin():
            return self.send_json({'ok':False,'error':'请求来源不正确。'},403)
        path = urlsplit(self.path).path
        if path == '/api/image/status':
            return self.send_json({'ok': True, **self.server.images.status()})
        if path == '/api/status':
            port,health = service().find(self.server.engine_port)
            ours = service().compatible(health)
            key = saved_key()
            return self.send_json({
                'name': APP_NAME,
                'version': (health or {}).get('app_version') or RUNTIME_ID,
                'python': '%d.%d.%d' % sys.version_info[:3],
                'data_dir': str(DATA),
                'has_key': bool(key),
                'engine_running': ours,
                'engine_url': f'http://127.0.0.1:{port or self.server.engine_port}',
                'setup_token': self.server.setup_token,
            })
        if path == '/favicon.ico':
            icon = APP / 'assets' / 'galgame' / 'favicon.svg'
            if icon.exists():
                body = icon.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'image/svg+xml')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            return self.send_json({'ok':False,'error':'页面不存在。'},404)
        name = STATIC_FILES.get(path)
        if not name:
            return self.send_json({'ok':False,'error':'页面不存在。'},404)
        target = LAUNCHER / name
        if not target.exists():
            body = '首启页面缺失，请重新解压完整压缩包。'.encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        body = target.read_bytes()
        kind = {'welcome.html': 'text/html; charset=utf-8',
                'welcome.css': 'text/css; charset=utf-8',
                'welcome.js': 'application/javascript; charset=utf-8',
                'image-setup.js': 'application/javascript; charset=utf-8'}[name]
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if (not self.allowed_host() or not self.allowed_origin()
                or self.headers.get('X-Setup-Token')!=self.server.setup_token):
            return self.send_json({'ok':False,'error':'请求来源或启动页令牌不正确，请刷新本机页面。'},403)
        try:
            data=self.read_json()
        except (OSError,ValueError):
            return self.send_json({'ok':False,'error':'请求格式错误，请刷新后重试。'},400)
        path=urlsplit(self.path).path
        image_actions = {
            '/api/image/codex/check': 'codex_check',
            '/api/image/codex/install': 'install_codex',
            '/api/image/codex/login': 'login_codex',
            '/api/image/kling/install': 'install_kling',
            '/api/image/kling/connect': 'connect_kling',
        }
        if path in image_actions:
            try:
                result = self.server.images.start_job(image_actions[path])
                return self.send_json({'ok': True, **result}, 202)
            except ValueError as error:
                return self.send_json({'ok': False, 'error': str(error)}, 409)
        if path == '/api/image/config':
            try:
                with service().operation():
                    result = self.server.images.save_choice(data)
                return self.send_json({'ok': True, **result})
            except (OSError, ValueError) as error:
                return self.send_json({'ok': False, 'error': str(error)}, 400)
        if path=='/api/key':
            key=data.get('key')
            if (not isinstance(key,str) or not key.strip().startswith('sk-') or not 4<=len(key.strip())<=512
                    or any(ord(c)<33 or ord(c)>126 or c in '\"\'' for c in key.strip())):
                return self.send_json({'ok':False,'saved':False,'error':'请填写完整密钥，不要包含引号、换行或空格。'},400)
            key=key.strip()
            verified,info=verify_key(key)
            if not verified:
                return self.send_json({'ok':False,'saved':False,'error':info},400)
            try:
                with service().operation():
                    ok,detail=save_key(key)
            except (OSError,ValueError):
                ok,detail=False,'另一项操作仍在进行，请稍后再保存。'
            return self.send_json({'ok':ok,'saved':ok,**({'model':info}if ok else{'error':detail})},200 if ok else 500)
        if path=='/api/launch':
            if not saved_key():
                return self.send_json({'ok':False,'error':'请先保存并校验 DeepSeek API Key。'},400)
            ok,detail=start_engine(self.server.engine_port)
            return self.send_json({'ok':ok,**({'url':detail}if ok else{'error':detail})},200 if ok else 500)
        if path=='/api/stop':
            ok,detail=stop_engine(self.server.engine_port)
            return self.send_json({'ok':ok,'detail':detail},200 if ok else 500)
        return self.send_json({'ok':False,'error':'未知接口'},404)


def make_server(port,engine_port):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.engine_port=engine_port
    server.setup_token=secrets.token_urlsafe(32)
    server.images=ImageSetup(APP, DATA, ROOT)
    server.daemon_threads=True
    return server


def main():
    global DATA
    parser = argparse.ArgumentParser(description='Yukino 0.9 首启引导')
    parser.add_argument('--setup-port', type=int, default=DEFAULT_SETUP_PORT)
    parser.add_argument('--engine-port', type=int, default=DEFAULT_ENGINE_PORT)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='只输出自检 JSON 后退出')
    parser.add_argument('--stop', action='store_true', help='关闭已在运行的游戏服务后退出')
    parser.add_argument('--launch-only', action='store_true', help='直接启动游戏服务，不起首启页')
    parser.add_argument('--data-dir',type=Path,help='显式独立资料库，不迁移默认资料库')
    args = parser.parse_args()
    if not all(1<=p<=65535 for p in (args.setup_port,args.engine_port)):
        parser.error('端口必须在1到65535之间。')
    if args.data_dir:
        DATA=args.data_dir.resolve()

    if args.stop:
        ok, detail = stop_engine(args.engine_port)
        print(detail)
        return 0 if ok else 1

    if args.check:
        port,health=service().find(args.engine_port)
        ready=(DATA/'worlds'/f'{SCRIPT_ID}.json').is_file()
        print(json.dumps({'name':APP_NAME,'version':RUNTIME_ID,'python':'%d.%d.%d'%sys.version_info[:3],
            'root':str(ROOT),'data_dir':str(DATA),'has_key':bool(saved_key()),
            'engine_running':service().compatible(health),'engine_port':port or args.engine_port,
            'script_ready':ready,'read_only':True},ensure_ascii=False,indent=2))
        return 0 if ready and (SCRIPTS/'launch_galgame.py').is_file() else 1

    print(f'== {APP_NAME} 测试版 · 内部运行时 {RUNTIME_ID} ==')
    print(f'   程序目录：{ROOT}')
    print(f'   数据目录：{DATA}')
    ensure_data()
    try:
        with service().operation():
            ok,message=ensure_script()
    except (OSError,ValueError):
        ok,message=False,'另一启动器仍在准备资料库，请稍后重试。'
    print(f'   {message}')
    if not ok:
        return 1

    if args.launch_only:
        if not saved_key():
            print('请先在首启页保存并校验 DeepSeek API Key。')
            return 1
        ok, detail = start_engine(args.engine_port)
        print(detail)
        return 0 if ok else 1

    try:
        port=args.setup_port if port_free(args.setup_port) else pick_port(args.setup_port+1)
        server=make_server(port,args.engine_port)
    except (OSError,ValueError):
        print('首启页端口无法使用，请稍后重试或指定 --setup-port。')
        return 1
    url=f'http://127.0.0.1:{port}/'
    print()
    print(f'   首启页面已就绪：{url}')
    print('   在这个页面里填写 DeepSeek API Key，然后点“启动游戏”。')
    print('   保持本窗口开着；关闭本窗口不会结束游戏；停止脚本按本包实际登记端口关闭游戏，存档保留。')
    print()
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n   已退出首启页。')
    finally:
        server.images.close()
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
