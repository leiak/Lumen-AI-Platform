"""一次性扫真缺漏依赖(docker 化 dev 时用)。"""
import importlib, os
mods = []
for root, dirs, files in os.walk('.'):
    if any(p in root for p in ['__pycache__', '.git', 'data/', 'storage/', '.mypy_cache', 'tests', 'scripts']):
        continue
    for f in files:
        if f.endswith('.py') and not f.startswith('test_'):
            path = os.path.join(root, f).replace(os.sep, '.')[:-3]
            if path.startswith('.'):
                path = path[2:]
            mods.append(path)

real_missing = set()
for m in mods:
    try:
        importlib.import_module(m)
    except ModuleNotFoundError as e:
        msg = str(e)
        if "'" in msg:
            name = msg.split("'")[1]
            # only top-level
            real_missing.add(name.split('.')[0])
    except Exception:
        pass

print('--- 真缺漏 (sorted) ---')
for m in sorted(real_missing):
    print(f'  {m}')
