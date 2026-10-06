"""Persistent Flash text transport. Credentials stay on the local server."""
from pathlib import Path
import base64
import ctypes
from ctypes import wintypes
import getpass
import http.client
import json
import os
import re
import ssl
import threading
import time
from turn_format import normalize

class TransportError(ValueError):
    def __init__(self,message,retryable=True):super().__init__(message);self.retryable=retryable

class FormatError(ValueError):pass

MODEL = 'deepseek-flash'

def protect(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('此机器请通过 DEEPSEEK_API_KEY 环境变量配置密钥。')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    name = 'CryptUnprotectData' if decrypt else 'CryptProtectData'
    operation = getattr(crypt, name)
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('本机密钥保护不可用。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL('kernel32')
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(target.data)

def credential_path(root):
    return Path(root) / 'browser/credentials/deepseek.dpapi.json'

def store_key(root, key):
    if not key.strip():
        raise ValueError('密钥不能为空。')
    value = {'format': 'windows-dpapi-current-user',
             'encrypted': base64.b64encode(protect(key.strip().encode())).decode('ascii')}
    path = credential_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)

def load_key(root):
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if key:
        return key
    try:
        data = json.loads(credential_path(root).read_text(encoding='utf-8'))
        return protect(base64.b64decode(data['encrypted'], validate=True), decrypt=True).decode().strip()
    except (OSError, ValueError, KeyError):
        raise ValueError('DeepSeek 尚未配置可用密钥。请使用本地密钥配置入口。') from None

def validate_schema(value, schema, path='reply'):
    kind = schema.get('type')
    valid = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
             'string': lambda: isinstance(value, str), 'boolean': lambda: type(value) is bool,
             'number': lambda: type(value) in (int, float), 'integer': lambda: type(value) is int}
    if kind in valid and not valid[kind]():
        raise ValueError(path+': type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path+': enum')
    if kind=='string' and 'pattern' in schema and not re.fullmatch(schema['pattern'],value):
        raise ValueError(path+': stable key required')
    if kind == 'object':
        if any(k not in value for k in schema.get('required', [])):
            raise ValueError(path+': missing '+','.join(k for k in schema['required'] if k not in value))
        if schema.get('additionalProperties') is False and set(value) - set(schema['properties']):
            raise ValueError(path+': additional fields')
        for key, child in schema.get('properties', {}).items():
            if key in value:
                validate_schema(value[key], child,path+'.'+key)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 10000):
            raise ValueError(path+': length')
        for index,item in enumerate(value):
            validate_schema(item, schema['items'],path+f'[{index}]')
    elif kind in {'number', 'integer'}:
        if not schema.get('minimum', float('-inf')) <= value <= schema.get('maximum', float('inf')):
            raise ValueError(path+': range')

class FlashClient:
    def __init__(self, root):
        self.root = Path(root)
        self.connection = None
        self.lock = threading.Lock()
        self.metrics = {}
        self.last_format_error=''
        self.validation_issues=[]

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def request(self, messages, on_first=None, max_tokens=3500):
        key = load_key(self.root)
        payload = {'model': MODEL, 'thinking': {'type': 'disabled'}, 'messages': messages,
                   'response_format': {'type': 'json_object'}, 'stream': True,
                   'stream_options': {'include_usage': True}, 'max_tokens': max_tokens}
        started = time.monotonic()
        if self.connection is None:
            self.connection = http.client.HTTPSConnection('api.deepseek.com', timeout=35,
                                                          context=ssl.create_default_context())
        try:
            self.connection.request('POST', '/chat/completions',
                body=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            response = self.connection.getresponse()
            if response.status != 200:
                status = response.status
                self.close()
                raise TransportError({401: 'DeepSeek 密钥验证失败，本轮未写入剧情。',
                    402: 'DeepSeek 额度不足，本轮未写入剧情。',
                    429: 'DeepSeek 暂时繁忙，本轮未写入剧情。'}.get(status, f'DeepSeek 请求未完成（{status}），本轮未写入剧情。'),retryable=status==429 or status>=500)
            chunks, first, finish, done, usage = [], None, None, False, None
            while True:
                line = response.readline(2 * 1024 * 1024)
                if not line:
                    break
                if not line.startswith(b'data:'):
                    continue
                raw = line[5:].strip()
                if raw == b'[DONE]':
                    done = True
                    break
                event = json.loads(raw)
                usage = event.get('usage') or usage
                for choice in event.get('choices', []):
                    content = choice.get('delta', {}).get('content') or ''
                    if content:
                        if first is None:
                            first = time.monotonic() - started
                            if on_first:
                                on_first(first)
                        chunks.append(content)
                    finish = choice.get('finish_reason') or finish
                if time.monotonic() - started > 90:
                    raise TimeoutError()
            response.read()
            if not done or finish != 'stop':
                self.close()
                raise TransportError('DeepSeek 回应不完整，本轮未写入剧情。')
            self.metrics = {'model': MODEL, 'first_text_seconds': round(first, 3) if first is not None else None,
                            'transport_seconds': round(time.monotonic()-started, 3), 'usage': usage}
            return ''.join(chunks)
        except (OSError, http.client.HTTPException, TimeoutError, json.JSONDecodeError):
            self.close()
            raise TransportError('DeepSeek 连接中断，本轮未写入剧情，可以重试。') from None
        finally:
            key = ''

    def generate(self, prompt, schema, on_first=None, context=None, on_recover=None, semantic_validator=None, normalizer=normalize):
        messages = [{'role': 'system', 'content': '你是视觉小说文本引擎。只输出符合以下 JSON Schema 的一个 JSON 对象，使用合法 JSON 转义。\n' + json.dumps(schema, ensure_ascii=False, separators=(',', ':'))},
                    {'role': 'user', 'content': prompt}]
        with self.lock:
            self.last_format_error='';self.validation_issues=[]
            transport_retries=0
            for attempt in range(2):
                while True:
                    try:
                        raw = self.request(messages,on_first)
                        break
                    except TransportError as exc:
                        if not exc.retryable or transport_retries>=1:raise
                        transport_retries+=1
                        if on_recover:on_recover('connection')
                        self.close();time.sleep(.5)
                try:
                    decoded=None
                    # Flash sometimes emits literal newlines inside JSON strings. Only
                    # this lexical defect is accepted; every field is still validated.
                    clean=raw.strip()
                    if clean.startswith('```') and clean.endswith('```'):
                        clean=clean.split('\n',1)[-1].rsplit('```',1)[0]
                    decoded=json.loads(clean,strict=False)
                    reply = normalizer(decoded,context or {}) if normalizer else decoded
                    validate_schema(reply, schema)
                    if semantic_validator:semantic_validator(reply)
                    self.metrics['format_retry'] = attempt
                    self.metrics['transport_retry']=transport_retries
                    return reply
                except (ValueError, TypeError) as exc:
                    self.last_format_error=str(exc)[:250]
                    # Local diagnostics contain identity/stage metadata only;
                    # no credential, prompt, or full generated story is logged.
                    details={'field':self.last_format_error,'response_chars':len(raw)}
                    if isinstance(exc,json.JSONDecodeError):details.update(json_offset=exc.pos,json_line=exc.lineno,json_column=exc.colno)
                    if isinstance(locals().get('decoded'),dict):
                        details['scene_state']=decoded.get('scene_state')
                        details['frames']=[{k:f.get(k) for k in ('kind','speaker','stage','reaction_to')} for f in decoded.get('frames',[]) if isinstance(f,dict)]
                    self.validation_issues.append(details)
                    if attempt:
                        raise FormatError('DeepSeek 回应格式未通过检查，本轮未写入剧情，可以重试。') from None
                    if on_recover:on_recover('format')
                    if isinstance(exc,json.JSONDecodeError):
                        # A corrupt object is not a useful few-shot example;
                        # asking to copy it led to the same syntax error twice.
                        messages=messages[:2]+[{'role':'user','content':'上次生成的 JSON 有语法错误：'+self.last_format_error+'。从原始 context 重新生成完整 JSON，不复制损坏对象。字符串中的英文双引号必须转义，换行用合法转义，无尾逗号；保持必要短分镜，不省略 scene_state。只输出 JSON。'}]
                        continue
                    messages.extend([{'role': 'assistant', 'content': raw},
                        {'role': 'user', 'content': '重新输出完整 JSON，修正 '+self.last_format_error+'。严格遵守字段、类型和枚举，不输出解释。world_updates.relations的trust/familiarity是本轮增减量，不是总分；story.milestone=false时整数-3至3，true时整数-6至6，没有实际变化用relations=[]。保留合法内容；若问题涉及在场、感知、输入顺序或故事因果，必须同时修正相关分镜、知识与好感，不能只改元数据掩饰不合理回应。以原context.scene_state、player_input及perception_rules重新核对：不在场且无实际联系的人不能听到当前发言，也不能切到其所在房间或心声来回答；独处时可仅输出当前位置的真实环境旁白，不杜撰相遇或联系。'}])

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--configure-key', action='store_true')
    args = parser.parse_args()
    if args.configure_key:
        store_key(args.root, getpass.getpass('DeepSeek API key (hidden): '))
        print('Local credential configured with Windows user protection.')
