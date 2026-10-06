"""Resolve internal media URLs against the current portable library."""
from pathlib import Path
from urllib.parse import unquote

def relocate(value, root):
    root = Path(root).resolve()
    if isinstance(value, dict):
        url = value.get('url', '')
        if isinstance(url, str) and url.startswith('/media/browser/'):
            local = (root / unquote(url.removeprefix('/media/'))).resolve()
            if local.is_relative_to(root / 'browser') and local.is_file():
                value['path'] = str(local)
        for item in list(value.values()):
            if isinstance(item, (dict, list)):
                relocate(item, root)
    elif isinstance(value, list):
        for item in value:
            relocate(item, root)
    return value
