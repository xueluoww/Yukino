"""Conservative stale-lock recovery. Never steal a live or ambiguous lock."""
import os,time

def alive(pid):
    if pid<=0:return None
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False if ctypes.get_last_error()==87 else None
        try:
            code=ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code)):return None
            return code.value==259
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return None

def remove_dead_lock(path):
    try:
        original=path.read_bytes();stat=path.stat()
        if not original.strip().isdigit() or time.time()-stat.st_mtime<1:return False
        if alive(int(original)) is not False:return False
        # Exclusive recovery marker serializes contenders for this stale lock.
        marker=path.with_name(path.name+'.recovery')
        try:fd=os.open(marker,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:return False
        try:
            if path.exists() and path.read_bytes()==original and path.stat().st_mtime_ns==stat.st_mtime_ns:
                path.unlink();return True
        finally:os.close(fd);marker.unlink(missing_ok=True)
    except (OSError,ValueError):pass
    return False
