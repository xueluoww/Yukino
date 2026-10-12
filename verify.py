"""Verify public source/manifest without reading runtime data or calling models."""
import hashlib
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
PRIVATE_ROOTS={'.git','data','database','demo-data','runtime','dist','__pycache__'}
def public_files():
    for p in ROOT.rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if rel.parts[0] in PRIVATE_ROOTS or '__pycache__' in rel.parts or p.suffix in {'.pyc','.zip'}:continue
        yield p
def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8-sig'))
    for item in manifest['files']:
        file=(ROOT/item['file']).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            raise SystemExit('Manifest mismatch: '+item['file'])
    for p in public_files():
        rel=p.relative_to(ROOT)
        if 'credentials' in rel.parts or p.suffix in {'.key','.pem'} or p.name.startswith('.env'):
            raise SystemExit('Unexpected private file: '+rel.as_posix())
        if p.suffix.lower() in {'.py','.json','.jsonl','.md','.txt','.yaml','.yml','.toml','.ini','.cfg','.ps1','.js'}:
            text=p.read_text(encoding='utf-8-sig',errors='replace')
            if re.search(r'[A-Za-z]:[\\/]Users[\\/]',text):
                raise SystemExit('Developer machine path: '+rel.as_posix())
            for token in re.findall(r'\bsk-[A-Za-z0-9_-]{24,}\b',text):
                if not ('synthetic' in token or 'test' in token):
                    raise SystemExit('Unexpected token-like value: '+rel.as_posix())
    skill=ROOT/'skills/sillytavern-roleplay'
    profiles=json.loads((skill/'assets/galgame/profiles/oregairu/sources.json').read_text(encoding='utf-8'))
    if profiles.get('not_original_art') is not True:raise SystemExit('Public art provenance missing')
    for p in (skill/'assets/galgame/profiles').rglob('*'):
        if p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
            raise SystemExit('Original avatar accidentally included')
    for p in (skill/'assets/galgame/images').rglob('*'):
        if p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
            raise SystemExit('Unapproved character art accidentally included')
    if (ROOT/'VERSION').read_text().strip()!='0.9':raise SystemExit('Wrong public version')
    if not (ROOT/'技术报告.md').is_file():raise SystemExit('Missing root technical report')
    print('Verified Yukino 0.9: '+str(len(manifest['files']))+' public files; no model/image requests.')
if __name__=='__main__':main()
