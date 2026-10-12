"""Explicit image providers; no silent switch of vendor, key, or reference mode."""
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_IMAGE = 32 * 1024 * 1024
MAX_RESPONSE = 48 * 1024 * 1024
PROVIDERS = ('off', 'codex', 'api')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('图片接口发生重定向，未转发密钥或重复请求。')


class ImageRequestError(ValueError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def validate_base(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('请填写图片接口地址。')
    value = value.strip().rstrip('/')
    try:
        url = urlsplit(value)
        url.port
    except ValueError:
        raise ValueError('图片接口地址无效。') from None
    local = url.hostname in ('127.0.0.1', 'localhost', '::1')
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or (url.scheme != 'https' and not (local and url.scheme == 'http'))):
        raise ValueError('图片接口须为 HTTPS；仅本机服务可以使用 HTTP，不接受 URL 中的凭据。')
    return value


def config_path(root):
    return Path(root) / 'browser/image-provider.json'


def validate_config(raw):
    if not isinstance(raw, dict) or raw.get('provider') not in PROVIDERS:
        raise ValueError('请选择关闭、Codex 或独立图片 API。可灵授权入口目前独立于自动生图。')
    value = {'version': 1, 'provider': raw['provider']}
    if raw['provider'] == 'api':
        value['base_url'] = validate_base(raw.get('base_url', ''))
        model = raw.get('model')
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}', model):
            raise ValueError('请填写供应商实际支持的图片模型 ID。')
        value['model'] = model
        for key, default, allowed in (
            ('reference_mode', 'edits', ('edits', 'none')),
            ('size', 'auto', ('auto', '1024x1024', '1536x1024', '1024x1536')),
            ('quality', 'auto', ('auto', 'low', 'medium', 'high')),
            ('background', 'auto', ('auto', 'opaque', 'transparent'))):
            value[key] = raw.get(key, default)
            if value[key] not in allowed:
                raise ValueError('图片接口选项无效：' + key)
        if type(raw.get('local_no_key', False)) is not bool:
            raise ValueError('本机无密钥选项无效。')
        value['local_no_key'] = raw.get('local_no_key', False)
        if value['local_no_key'] and urlsplit(value['base_url']).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('只有明确选择的本机服务可以不使用密钥。')
    return value


def read_config(root):
    path = config_path(root)
    if not path.exists():
        # Preserve the original skill's Codex behavior. The standalone launcher
        # separately defaults to --no-images until an explicit choice is saved.
        return {'version': 1, 'provider': 'codex'}
    try:
        return validate_config(json.loads(path.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError):
        raise ValueError('生图配置无法读取，未回退到其他供应商。') from None


def write_config(root, value):
    from tavern import atomic_json
    atomic_json(config_path(root), validate_config(value))


def credential_path(root):
    return Path(root) / 'browser/credentials/image-api.dpapi.json'


def store_api_key(root, key, base):
    from deepseek_client import protect
    from tavern import atomic_json
    if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('图片密钥不能为空或包含控制字符。')
    atomic_json(credential_path(root), {'format': 'windows-dpapi-current-user',
        'base_url': validate_base(base), 'encrypted': base64.b64encode(protect(key.encode())).decode('ascii')})


def load_api_key(root, base, local_no_key=False):
    key = os.environ.get('YUKINO_IMAGE_API_KEY', '')
    if key:
        return key
    if local_no_key:
        return ''
    try:
        from deepseek_client import protect
        record = json.loads(credential_path(root).read_text(encoding='utf-8-sig'))
        if record.get('base_url') != validate_base(base):
            raise ValueError('Endpoint binding mismatch')
        return protect(base64.b64decode(record['encrypted'], validate=True), decrypt=True).decode()
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('该图片接口尚未配置自己的密钥；不会借用 DeepSeek 或其他接口的密钥。') from None


def has_api_key(root, base):
    try:
        return bool(load_api_key(root, base))
    except ValueError:
        return False


def resolve_codex(package_root=None, fallback=None):
    if package_root:
        script = Path(package_root) / 'runtime/codex/node_modules/@openai/codex/bin/codex.js'
        node = shutil.which('node')
        if script.is_file() and node:
            return [node, str(script)]
    command = fallback or shutil.which('codex')
    return [str(command)] if command else None


def json_request(url, key='', payload=None, timeout=20, content_type='application/json'):
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    if payload is not None:
        headers['Content-Type'] = content_type
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if isinstance(payload, dict) else payload
    request = urllib.request.Request(url, data=body, headers=headers, method='POST' if payload is not None else 'GET')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('图片接口响应过大。')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('图片接口未返回 JSON 对象。')
            return value
    except urllib.error.HTTPError as exc:
        # Upstream errors can echo secrets and signed URLs: never propagate body.
        status = exc.code
        exc.close()
        raise ImageRequestError(f'图片接口请求失败（HTTP {status}），请检查服务商配置与额度。', status) from None
    except (OSError, json.JSONDecodeError):
        raise ValueError('图片接口响应未确认；未自动重复请求。') from None


def check_api(config, key):
    config = validate_config(config)
    if config['provider'] != 'api':
        raise ValueError('请选择独立图片 API。')
    data = json_request(config['base_url'] + '/models', key)
    if not isinstance(data.get('data'), list):
        raise ValueError('接口未提供兼容的模型列表；尚未验证配置。')
    if not any(isinstance(row, dict) and row.get('id') == config['model'] for row in data['data']):
        raise ValueError('模型列表没有该图片模型，原配置和密钥未更改。')
    return {'connected': True, 'model_list_verified': True, 'generation_verified': False,
            'message': '接口与模型列表可读取；未试画，图片与参考图能力仍以供应商为准。'}


def image_suffix(data):
    if not data or len(data) > MAX_IMAGE:
        raise ValueError('图片为空或超过大小限制。')
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 33 and data[12:16] == b'IHDR':
        width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
        if not 1 <= width <= 8192 or not 1 <= height <= 8192:
            raise ValueError('返回PNG的尺寸无效或超过限制。')
        return '.png'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return '.jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    raise ValueError('返回结果不是支持的 PNG/JPEG/WebP 图片。')


def download_image(url):
    # CDN requests deliberately never carry the API Authorization header.
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('供应商返回了不安全的图片链接。')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('图片链接指向本机或私有地址，未下载。')
        with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url), timeout=30) as response:
            data = response.read(MAX_IMAGE + 1)
        image_suffix(data)
        return data
    except OSError:
        raise ValueError('已提交图片任务，但下载未完成；不会自动重新生图。') from None


class ApiImageService:
    def __init__(self, root, config):
        self.root, self.config = Path(root), validate_config(config)
        self.proc = None
        self.last_metrics = {}
        self.lock = threading.Lock()
        self.output_root = self.root / 'browser/image-jobs'

    def start(self):
        load_api_key(self.root, self.config['base_url'], self.config['local_no_key'])

    def close(self):
        pass

    def generate(self, prompt, references, scope, job, timeout=360):
        from tavern import atomic_json
        with self.lock:
            folder = Path(job).resolve()
            if not folder.is_relative_to(self.output_root.resolve()):
                raise ValueError('图片任务目录越界。')
            folder.mkdir(parents=True, exist_ok=True)
            record_path = folder / 'api-request.json'
            references = [Path(p).resolve() for p in references if p]
            if references and self.config['reference_mode'] != 'edits':
                raise ValueError('此接口未启用参考图编辑，不能忽略人物参考图后继续生成。')
            if len(references) > 5 or any(not p.is_file() or p.stat().st_size > MAX_IMAGE for p in references):
                raise ValueError('参考图片缺失、过大或超过五张。')
            signature = hashlib.sha256(json.dumps({'prompt': prompt, 'config': self.config,
                'references': [hashlib.sha256(p.read_bytes()).hexdigest() for p in references]},
                ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            old = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else {}
            if old.get('signature') == signature:
                filename = old.get('file', '')
                if filename and filename not in ('result.png', 'result.jpg', 'result.webp'):
                    raise ValueError('缓存图片路径无效，未读取任务外的文件。')
                path = folder / filename
                if old.get('status') == 'ready' and path.is_file():
                    image_suffix(path.read_bytes())
                    return [str(path)]
                if old.get('status') in ('submitting', 'uncertain', 'result_received'):
                    # A successful request followed by download failure must not
                    # become a second charged request on the same retry button.
                    if old.get('result'):
                        return self._save_result(old, folder, record_path)
                    raise ValueError('上次提交结果尚未确认，请先检查服务商任务；未自动重复扣费。')
            key = load_api_key(self.root, self.config['base_url'], self.config['local_no_key'])
            size = self.config['size']
            if size == 'auto':
                size = '1024x1536' if re.search(r'transparent|透明|立绘', prompt, re.I) else '1536x1024'
            fields = {'model': self.config['model'], 'prompt': prompt, 'n': 1,
                      'size': size, 'quality': self.config['quality']}
            if self.config['background'] != 'auto':
                fields['background'] = self.config['background']
            elif re.search(r'transparent|透明', prompt, re.I):
                fields['background'] = 'transparent'
            payload, content_type = fields, 'application/json'
            endpoint = '/images/generations'
            if references:
                boundary = 'yukino-' + signature[:24]
                parts = []
                for name, value in fields.items():
                    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
                for i, path in enumerate(references):
                    data = path.read_bytes()
                    suffix = image_suffix(data)
                    mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'}[suffix]
                    parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference-{i}{suffix}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), data, b'\r\n'])
                parts.append(f'--{boundary}--\r\n'.encode())
                payload = b''.join(parts)
                content_type = 'multipart/form-data; boundary=' + boundary
                endpoint = '/images/edits'
            record = {'signature': signature, 'status': 'submitting', 'provider': 'api'}
            atomic_json(record_path, record)
            started = time.monotonic()
            try:
                response = json_request(self.config['base_url'] + endpoint, key, payload, timeout, content_type)
                rows = response.get('data')
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                    raise ValueError('图片服务没有返回恰好一张图片。')
                record.update(status='result_received', result={k: rows[0][k] for k in ('b64_json', 'url') if k in rows[0]})
                atomic_json(record_path, record)
                result = self._save_result(record, folder, record_path)
                self.last_metrics = {'provider': 'api', 'seconds': round(time.monotonic() - started, 2), 'status': 'completed'}
                return result
            except Exception as error:
                if record['status'] == 'submitting':
                    record['status'] = 'rejected' if isinstance(error, ImageRequestError) and 400 <= error.status < 500 else 'uncertain'
                    atomic_json(record_path, record)
                raise

    def _save_result(self, record, folder, record_path):
        from tavern import atomic_json
        value = record.get('result') or {}
        if isinstance(value.get('b64_json'), str):
            try:
                data = base64.b64decode(value['b64_json'], validate=True)
            except ValueError:
                raise ValueError('返回图片的 Base64 格式无效。') from None
        elif isinstance(value.get('url'), str):
            data = download_image(value['url'])
        else:
            raise ValueError('图片服务没有返回图片数据或链接。')
        filename = 'result' + image_suffix(data)
        target = folder / filename
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data)
        os.replace(temporary, target)
        record.update(status='ready', file=filename)
        record.pop('result', None)
        atomic_json(record_path, record)
        return [str(target)]


def make_image_service(root, cli, env):
    config = read_config(root)
    if config['provider'] == 'off':
        return None
    if config['provider'] == 'api':
        return ApiImageService(root, config)
    from image_service import ImageService
    package = next((p for p in Path(__file__).resolve().parents if (p/'launcher/setup.py').is_file()), None)
    command = resolve_codex(package, cli)
    return ImageService(command, root, env) if command else None
