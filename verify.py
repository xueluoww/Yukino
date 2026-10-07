"""Read-only public release checks; no keys or model calls."""
from pathlib import Path
import hashlib, json, re

ROOT=Path(__file__).resolve().parent

def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    failures=[]
    for item in manifest['files']:
        file=(ROOT/item['file']).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            failures.append(item['file'])
    if failures:raise SystemExit('Missing or changed release files: '+', '.join(failures))
    seed=ROOT/'examples/demo-library'
    saves=list((seed/'sessions').glob('*.json'))
    if len(saves)!=1:raise SystemExit('The public seed must contain exactly one demo save.')
    for file in seed.rglob('*.json'):
        json.loads(file.read_text(encoding='utf-8'))
    for file in ROOT.rglob('*'):
        if not file.is_file() or 'database' in file.relative_to(ROOT).parts or '.git' in file.relative_to(ROOT).parts:
            continue
        if 'credentials' in file.parts or file.name.startswith('.env') or file.suffix in {'.key','.pem'}:
            raise SystemExit('Unexpected public credential file: '+file.relative_to(ROOT).as_posix())
        if file.suffix.lower() in {'.py','.json','.jsonl','.md','.txt','.yaml','.yml','.toml','.ini','.cfg','.ps1'}:
            text=file.read_text(encoding='utf-8-sig',errors='replace')
            if re.search(r'\bsk-[A-Za-z0-9_-]{24,}\b|[A-Za-z]:[\\/]Users[\\/]',text):
                raise SystemExit('Private token or machine path in public file: '+file.relative_to(ROOT).as_posix())
    print(f"Verified Yukino 0.5 / stage 5.6: {len(manifest['files'])} public files, one demo save, no model requests.")

if __name__=='__main__':main()
