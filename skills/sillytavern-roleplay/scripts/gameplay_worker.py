"""Bounded subprocess for JSON-only script code. Not a general Python sandbox."""
import ast
import json
import sys

METHODS = {'get', 'items', 'keys', 'values', 'append', 'extend', 'pop', 'copy',
           'count', 'index', 'lower', 'strip', 'startswith', 'endswith', 'split', 'join'}
FORBIDDEN = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.With, ast.AsyncWith,
             ast.Try, ast.Raise, ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
             ast.Await, ast.Yield, ast.YieldFrom, ast.Delete)

def check(source):
    if not isinstance(source, str) or len(source.encode('utf-8')) > 65536:
        raise ValueError('玩法代码最多 64 KiB。')
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN):
            raise ValueError('玩法只能使用纯计算代码，禁止导入、类和外部操作。')
        if isinstance(node, ast.Name) and (node.id.startswith('_') or node.id in
                {'open','eval','exec','compile','globals','locals','getattr','setattr','vars','type','object','input','print','breakpoint','help'}):
            raise ValueError('玩法代码包含禁止名称。')
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise ValueError('玩法代码包含不支持的方法：'+node.attr)
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'run' for n in tree.body):
        raise ValueError('玩法必须定义 run(request)。')
    return tree

def limit_memory():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [('per_process',ctypes.c_longlong),('per_job',ctypes.c_longlong),
                        ('flags',wintypes.DWORD),('min',ctypes.c_size_t),('max',ctypes.c_size_t),
                        ('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(k,ctypes.c_ulonglong) for k in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                        ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        job = kernel.CreateJobObjectW(None,None)
        info = Extended(); info.basic.flags = 0x100; info.process_memory = 128*1024*1024
        if not job or not kernel.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess()):
            raise ValueError('无法建立玩法进程内存限制。')
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,128*1024*1024))

def main():
    limit_memory()
    raw = sys.stdin.buffer.read(512*1024+1)
    if len(raw) > 512*1024: raise ValueError('玩法输入过大。')
    data = json.loads(raw)
    tree = check(data['source'])
    safe = {k:globals().get(k) for k in ()}
    import builtins
    safe = {k:getattr(builtins,k) for k in ('len','min','max','sum','abs','round','int','float','str','bool','list','dict','set','tuple','sorted','range','enumerate','zip','all','any','reversed')}
    space = {'__builtins__':safe}
    steps = [0]
    def trace(frame,event,arg):
        if event == 'line':
            steps[0] += 1
            if steps[0] > 100000: raise ValueError('玩法计算步数超限。')
        return trace
    sys.settrace(trace)
    try:
        exec(compile(tree,'<story-gameplay>','exec'),space)
        result = space['run'](data['request'])
    finally: sys.settrace(None)
    raw = json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(raw)>128*1024:raise ValueError('玩法返回数据过大。')
    sys.stdout.buffer.write(raw)

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        sys.stderr.buffer.write(str(exc).encode('utf-8',errors='replace')[:2000]); sys.exit(1)
