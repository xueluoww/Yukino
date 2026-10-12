"""Isolated image credentials; a shared Codex refresh token is never borrowed."""
import base64
import json
import os
from pathlib import Path
import time

class ImageAuthError(ValueError):
    pass

def image_home(root):
    return (Path(root)/'browser/image-service/codex-home').resolve()

def source_home(env):
    return Path(env.get('CODEX_HOME') or Path.home()/'.codex').resolve()

def isolated_env(root, env):
    result=env.copy()
    for key in ('DEEPSEEK_API_KEY','YUKINO_IMAGE_API_KEY','OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN','ACCESS_TOKEN'):
        result.pop(key,None)
    result['CODEX_HOME']=str(image_home(root))
    return result

def external_tokens(home):
    """Read only the access token; never return, copy, persist or refresh a refresh token."""
    path=Path(home)/'auth.json'
    try:
        if not path.is_file() or path.stat().st_size>65536:raise ImageAuthError('未找到可只读复用的Codex登录；请为Yukino单独登录。')
        raw=json.loads(path.read_text(encoding='utf-8-sig'))
        tokens=raw.get('tokens') or {}
        access=tokens.get('access_token')
        account=tokens.get('account_id')
        if raw.get('auth_mode') not in (None,'chatgpt') or not isinstance(access,str) or not isinstance(account,str) or not account:
            raise ImageAuthError('当前Codex凭据不是可用的ChatGPT登录；请为Yukino单独登录。')
        parts=access.split('.')
        if len(parts)!=3:raise ImageAuthError('Codex访问凭据格式异常；未改动原登录。')
        claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*(-len(parts[1])%4)))
        expiry=claims.get('exp')
        if not isinstance(expiry,(int,float)) or expiry<=time.time()+60:
            raise ImageAuthError('Codex访问凭据已过期；请在Codex本体续登后重新检测，或为Yukino单独登录。')
        result={'type':'chatgptAuthTokens','accessToken':access,'chatgptAccountId':account}
        plan=claims.get('https://api.openai.com/auth',{}).get('chatgpt_plan_type')
        if isinstance(plan,str):result['chatgptPlanType']=plan
        return result
    except ImageAuthError:
        raise
    except (OSError,ValueError,TypeError,KeyError):
        raise ImageAuthError('无法读取Codex访问凭据；原登录未改动，请为Yukino单独登录。')from None
