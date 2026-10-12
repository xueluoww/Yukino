"""Local setup actions. Install/login only run after a dedicated UI request."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

CODEX_VERSION = '0.160.1'
MCP_REMOTE_VERSION = '0.2.0'


def hidden_run(args, timeout=20, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, **kwargs)


class KlingConnection:
    """Only initialize/discover/identify. Never creates a paid generation task."""
    def __init__(self, command):
        self.command = command
        self.proc = None
        self.messages = queue.Queue()
        self.counter = 0

    def rpc(self, method, params, timeout=200):
        self.counter += 1
        request_id = self.counter
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.messages.get(timeout=max(.1, deadline - time.monotonic()))
            if item.get('_eof'):
                raise ValueError('可灵连接已结束，请重新授权。')
            if item.get('id') == request_id:
                if item.get('error'):
                    raise ValueError('可灵服务未接受连接或授权请求。')
                return item.get('result', {})
        raise ValueError('可灵授权等待超时，请完成浏览器授权后重新连接。')

    def reader(self):
        try:
            for line in self.proc.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self.messages.put(value)
                except ValueError:
                    pass
        finally:
            self.messages.put({'_eof': True})

    def connect(self):
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        threading.Thread(target=self.reader, daemon=True).start()
        self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'yukino-kling-connection', 'version': '0.9'}})
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        self.proc.stdin.flush()
        catalog = self.rpc('tools/list', {})
        tools = catalog.get('tools')
        if not isinstance(tools, list):
            raise ValueError('可灵工具目录格式异常，未接入自动生成。')
        identity = next((t for t in tools if isinstance(t, dict) and str(t.get('name', '')).split('__')[-1] == 'who_am_i'), None)
        if not identity:
            raise ValueError('尚未找到可灵只读账号工具，不能确认授权。')
        schema = identity.get('inputSchema') or {}
        if schema.get('required'):
            raise ValueError('账号检测工具需要新参数，须按实际 schema 适配，未猜测参数。')
        result = self.rpc('tools/call', {'name': identity['name'], 'arguments': {}})
        if result.get('isError'):
            raise ValueError('可灵账号检测失败，未提交任何生图任务。')
        return {'authorized': True, 'tool_count': len(tools), 'generation_enabled': False,
            'message': '账号可读取；自动生图仍待按实际图片工具 schema 适配，未消耗生图额度。'}

    def close(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        finally:
            if self.proc.stdout:
                self.proc.stdout.close()
            self.proc = None


class ImageSetup:
    def __init__(self, app, data, package):
        self.app, self.data, self.package = Path(app), Path(data), Path(package)
        sys.path.insert(0, str(self.app / 'scripts'))
        import image_backends
        self.backends = image_backends
        self.operation_lock = threading.Lock()
        self.job = {'busy': False, 'action': '', 'message': ''}
        self.last_codex_check = {}
        self.kling = None
        self.kling_status = {'authorized': False, 'generation_enabled': False, 'message': '尚未连接'}
        self.login_process = None

    def config(self):
        if not self.backends.config_path(self.data).exists():
            return {'version': 1, 'provider': 'off'}
        return self.backends.read_config(self.data)

    def status(self):
        try:
            config = self.config()
        except ValueError:
            config = {'provider': 'off', 'error': '原配置无法读取，请重新选择；未切换供应商。'}
        command = self.backends.resolve_codex(self.package)
        return {'config': config, 'has_api_key': bool(config.get('base_url') and self.backends.has_api_key(self.data, config['base_url'])),
            'codex': {'installed': bool(command), **self.last_codex_check},
            'node_installed': bool(shutil.which('node')), 'npm_installed': bool(shutil.which('npm.cmd' if os.name == 'nt' else 'npm')),
            'kling': {**self.kling_status, 'connector_installed': bool(self.connector_command())},
            'operation': dict(self.job)}

    def codex_check(self):
        command = self.backends.resolve_codex(self.package)
        if not command:
            value = {'installed': False, 'logged_in': False, 'service_handshake': False,
                     'generation_verified': False, 'message': '未找到 Codex CLI，可单独安装本包的生图工具。'}
        else:
            version = hidden_run([*command, '--version']).stdout.strip()[:100]
            login = hidden_run([*command, 'login', 'status'])
            # Use exit status; never return auth output, email, key or auth.json.
            logged_in = login.returncode == 0
            value = {'installed': True, 'version': version, 'logged_in': logged_in,
                'service_handshake': False, 'generation_verified': False,
                'message': '尚未登录，请单独打开 Codex 登录。'}
            if logged_in:
                from image_service import ImageService
                with tempfile.TemporaryDirectory(prefix='yukino-codex-check-') as root:
                    service = ImageService(command, root, os.environ.copy())
                    try:
                        service.start()
                        account = service.rpc('account/read', {'refreshToken': False})
                        if not account.get('account'):
                            raise ValueError('生图服务没有可用登录身份。')
                        value.update(service_handshake=True, message='已登录，生图服务可握手；尚未试画，不保证账号有图片额度。')
                    finally:
                        service.close()
        self.last_codex_check = value
        return value

    def start_job(self, action):
        if not self.operation_lock.acquire(blocking=False):
            raise ValueError('另一项安装、检测或授权仍在进行，请稍后重试。')
        self.job = {'busy': True, 'action': action, 'message': '正在处理…'}
        def worker():
            try:
                message = getattr(self, action)()
                self.job = {'busy': False, 'action': action, 'ok': True,
                            'message': message.get('message', '已完成') if isinstance(message, dict) else message}
            except ValueError as error:
                self.job = {'busy': False, 'action': action, 'ok': False, 'message': str(error)}
            except (OSError, subprocess.SubprocessError, queue.Empty):
                self.job = {'busy': False, 'action': action, 'ok': False,
                            'message': '此操作未完成。请检查网络、Node/npm 或浏览器授权，再重新检测；未提交生图任务。'}
            finally:
                self.operation_lock.release()
        threading.Thread(target=worker, daemon=True).start()
        return {'started': True, 'message': '操作已开始，状态会自动更新。'}

    def install(self, package, folder):
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        node = shutil.which('node')
        if not npm or not node:
            raise ValueError('请先安装官方 Node.js LTS，再运行本包安装选项。')
        target = self.package / 'runtime' / folder
        target.mkdir(parents=True, exist_ok=True)
        result = hidden_run([npm, 'install', '--prefix', str(target), '--no-audit', '--no-fund',
            '--ignore-scripts', '--', package], timeout=360)
        if result.returncode:
            raise ValueError('依赖安装失败；没有改变全局 npm 或 Codex 配置。')

    def install_codex(self):
        self.install('@openai/codex@' + CODEX_VERSION, 'codex')
        value = self.codex_check()
        return {'message': '已安装本包独立 Codex CLI；' + value['message']}

    def login_codex(self):
        command = self.backends.resolve_codex(self.package)
        if not command:
            raise ValueError('请先安装 Codex CLI。')
        if self.login_process and self.login_process.poll() is None:
            return '登录正在进行，请完成已打开的浏览器页面。'
        self.login_process = subprocess.Popen([*command, 'login'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return '已启动 Codex 官方浏览器登录，请自己完成授权，然后点击检测。'

    def connector_command(self):
        package = self.package / 'runtime/kling/node_modules/mcp-remote'
        node = shutil.which('node')
        if not node or not (package / 'package.json').is_file():
            return None
        try:
            info = json.loads((package / 'package.json').read_text(encoding='utf-8'))
            entry = (package / info['bin']['mcp-remote']).resolve()
            if not entry.is_relative_to(package.resolve()) or not entry.is_file():
                return None
            return [node, str(entry), 'https://klingai.com/mcp', '--transport', 'http-only',
                '--static-oauth-client-metadata', '{"client_name":"Plugin-DeepSeek"}',
                '--header', 'X-Kling-Integration:Plugin-DeepSeek', '--auth-timeout', '180']
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def install_kling(self):
        self.install('mcp-remote@' + MCP_REMOTE_VERSION, 'kling')
        if not self.connector_command():
            raise ValueError('可灵连接器入口未通过检查。')
        return '可灵连接器已安装到本包 runtime；未登录、未生成图片。'

    def connect_kling(self):
        command = self.connector_command()
        if not command:
            raise ValueError('请先安装可灵连接器。')
        if self.kling:
            self.kling.close()
        connection = KlingConnection(command)
        self.kling_status = {'authorized': False, 'generation_enabled': False, 'message': '请完成浏览器中的可灵授权…'}
        try:
            value = connection.connect()
            self.kling = connection
            self.kling_status = value
            return value
        except Exception:
            connection.close()
            self.kling_status = {'authorized': False, 'generation_enabled': False, 'message': '可灵授权尚未验证，未调用生图工具。'}
            raise

    def save_choice(self, raw):
        config = self.backends.validate_config(raw)
        key = raw.get('key', '')
        if not isinstance(key, str):
            raise ValueError('密钥字段格式错误。')
        if config['provider'] == 'codex':
            check = self.last_codex_check
            if not check.get('logged_in') or not check.get('service_handshake'):
                raise ValueError('请先检测 Codex 登录与服务握手，再启用该生图方式。')
        if config['provider'] == 'api':
            if not key:
                key = self.backends.load_api_key(self.data, config['base_url'], config['local_no_key'])
            self.backends.check_api(config, key)
        # Keep the existing encrypted credential/config intact if any write fails.
        config_file = self.backends.config_path(self.data)
        key_file = self.backends.credential_path(self.data)
        original = {p: p.read_bytes() if p.exists() else None for p in (config_file, key_file)}
        try:
            if config['provider'] == 'api' and key and raw.get('key'):
                self.backends.store_api_key(self.data, key, config['base_url'])
            self.backends.write_config(self.data, config)
        except Exception:
            for path, content in original.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            raise
        return {'provider': config['provider'], 'generation_verified': False,
            'message': '生图方式已保存，供下次启动使用；运行中的游戏请先正常停止再重启。未改变存档。'}

    def close(self):
        if self.kling:
            self.kling.close()
