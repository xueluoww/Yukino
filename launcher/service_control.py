"""Own only this package's service; serialize double-clicks without stale locks."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_LOCK = threading.Lock()


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def port_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def pick_port(start, limit=40):
    for port in range(start, min(65536, start + limit)):
        if port_free(port):
            return port
    raise ValueError('没有可用端口，请指定其他端口。')


class PackageService:
    def __init__(self, app, data, runtime, run_python):
        self.app, self.data = Path(app), Path(data).resolve()
        self.runtime, self.run_python = runtime, run_python

    def health(self, port):
        try:
            with LOCAL_HTTP.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                value = json.load(response)
                return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def owns(self, health):
        if not isinstance(health, dict) or health.get('app') != 'galgame':
            return False
        try:
            return bool(health.get('root')) and Path(health['root']).resolve() == self.data
        except (OSError, ValueError, TypeError):
            return False

    def compatible(self, health):
        return self.owns(health) and health.get('provider') == 'deepseek' and health.get('app_version') == self.runtime

    def recorded_port(self):
        try:
            record = json.loads((self.data / 'browser/server.json').read_text(encoding='utf-8-sig'))
            if not isinstance(record, dict) or Path(record.get('root') or '').resolve() != self.data:
                return None
            url = urlsplit(record.get('url') or '')
            if (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost') and url.port
                    and not url.username and not url.password and url.path in ('', '/') and not url.query and not url.fragment):
                return url.port
        except (OSError, ValueError, TypeError):
            pass
        return None

    def find(self, preferred):
        for port in dict.fromkeys((self.recorded_port(), preferred)):
            if port is None:
                continue
            health = self.health(port)
            if self.owns(health):
                return port, health
        return None, None

    @contextmanager
    def operation(self, timeout=15):
        if not _LOCK.acquire(timeout=timeout):
            raise ValueError('另一次本机操作仍在进行，请稍后重试。')
        handle = None
        locked = False
        try:
            (self.data / 'browser').mkdir(parents=True, exist_ok=True)
            handle = (self.data / 'browser/launcher.lock').open('a+b')
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            deadline = time.monotonic() + timeout
            while not locked:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError('另一个启动器正在操作本包，请稍后重试。') from None
                    time.sleep(0.1)
            yield
        finally:
            try:
                if handle:
                    try:
                        if locked:
                            handle.seek(0)
                            if os.name == 'nt':
                                import msvcrt
                                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                            else:
                                import fcntl
                                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    finally:
                        handle.close()
            finally:
                _LOCK.release()

    def start(self, preferred):
        try:
            with self.operation():
                config_file = self.data / 'browser/image-provider.json'
                config = json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {'provider': 'off'}
                provider = config.get('provider') if isinstance(config, dict) else None
                if provider not in ('off', 'codex', 'api'):
                    return False, '生图配置无法识别，未启动或切换供应商，请在启动页重新配置。'
                images_enabled = provider != 'off'
                port, health = self.find(preferred)
                if port is not None:
                    if not self.compatible(health):
                        return False, '本包已有其他版本或对白引擎的服务，请先正常停止，再重新启动。'
                    if images_enabled and (health.get('image_provider') != provider or health.get('dynamic_images') is not True):
                        return False, '生图设置已改变。请先正常停止本包游戏，再启动以加载新设置；旧存档保留。'
                    if not images_enabled and health.get('dynamic_images') is True:
                        return False, '当前服务仍开启生图，请正常停止后再使用仅已有图片模式。'
                    return True, f'http://127.0.0.1:{port}'
                port = preferred if port_free(preferred) else pick_port(preferred + 1)
                launcher = self.app / 'scripts/launch_galgame.py'
                if not launcher.is_file():
                    return False, '包内缺少游戏启动脚本。'
                arguments = [launcher, '--root', self.data, '--port', port, '--provider', 'deepseek']
                if not images_enabled:
                    arguments.append('--no-images')
                code, _ = self.run_python(arguments, timeout=120)
                if code != 0:
                    return False, f'启动脚本未成功（退出码 {code}），请查看 data/browser/launch.log。'
                if not self.compatible(self.health(port)):
                    return False, '启动后服务的资料库、版本或对白引擎不匹配，未打开游戏。'
                return True, f'http://127.0.0.1:{port}'
        except (OSError, ValueError, subprocess.SubprocessError):
            return False, '启动未完成，请稍后重试或检查 data/browser/launch.log。'

    def stop(self, preferred):
        try:
            with self.operation():
                port, _ = self.find(preferred)
                if port is None:
                    return True, '本包游戏服务没有在运行；其他资料库未受影响。'
                base = f'http://127.0.0.1:{port}'
                with LOCAL_HTTP.open(base + '/api/session-token', timeout=5) as response:
                    payload = json.load(response)
                token = payload.get('token') if isinstance(payload, dict) else None
                if not isinstance(token, str) or not token:
                    return False, '服务没有返回关闭令牌，未强制结束进程。'
                request = urllib.request.Request(base + '/api/shutdown', data=b'{}', method='POST',
                    headers={'Content-Type': 'application/json', 'Origin': base, 'X-Session-Token': token})
                with LOCAL_HTTP.open(request, timeout=15) as response:
                    result = json.load(response)
                if not isinstance(result, dict) or result.get('ok') is not True:
                    return False, '服务未确认关闭，未强制结束进程。'
                for _ in range(20):
                    if not port_open(port):
                        return True, '本包游戏服务已正常关闭，存档保留。'
                    time.sleep(0.25)
                return False, '已请求关闭，服务仍在退出中；请稍后检查。'
        except urllib.error.HTTPError as exc:
            status=exc.code
            exc.close()
            if status == 400:
                return False, '游戏仍在处理回应或画面，请先完成或取消本轮，再停止。'
            return False, f'游戏拒绝关闭请求（HTTP {status}），未强制关闭。'
        except (OSError, ValueError, TypeError):
            return False, '无法正常关闭，未结束其他程序；请稍后重试。'
