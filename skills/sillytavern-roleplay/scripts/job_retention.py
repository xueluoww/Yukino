"""Bounded per-session intermediates, separate from authoritative saves and shared assets."""
from pathlib import Path
import re
PRIVATE={'prompt.txt','client-request.json','request.json','engine.log','experimental-trace.txt'}
def retain(root,sid,current,keep=8):
    root=Path(root).resolve()
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',sid):raise ValueError('Invalid session id')
    base=root/'browser/jobs'/sid
    if not base.exists():return
    if base.is_symlink() or not base.resolve().is_relative_to(root):raise ValueError('Job path outside library')
    jobs=sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink()),key=lambda p:p.stat().st_mtime,reverse=True)
    for index,job in enumerate(jobs):
        if not job.resolve().is_relative_to(base.resolve()):continue
        if job.name==current or index>=keep:
            for name in PRIVATE:
                path=job/name
                if path.is_file() and not path.is_symlink():path.unlink()
        if index>=keep and job.name!=current:
            for name in ('turn.json','diagnostic.json','rejection.json','raw-response.txt'):
                path=job/name
                if path.is_file() and not path.is_symlink():path.unlink()
            if not any(job.iterdir()):job.rmdir()
