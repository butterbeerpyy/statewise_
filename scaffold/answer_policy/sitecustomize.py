import os
import sys


_OVERRIDES = (
    ("STATEWISE_ANSWER_POLICY", "answer_policy",
     "scaffold.statewise.agents.human_simulator"),
    ("STATEWISE_RESIDUAL_IMPACT_THRESHOLD", "gate_threshold",
     "scaffold.statewise.core.residual_risk"),
)


def _install(module_name):
    try:
        module = __import__(module_name)
    except Exception:
        return False
    try:
        module.install()
        return True
    except ValueError:
        raise
    except Exception:
        return False


_pending = []
for _env, _module, _target in _OVERRIDES:
    if not os.environ.get(_env):
        continue
    if not _install(_module):
        _pending.append((_module, _target))

if _pending:
    import importlib.abc
    import importlib.machinery

    class _Finder(importlib.abc.MetaPathFinder):


        def __init__(self, pending):
            self._pending = dict((target, module) for module, target in pending)

        def find_spec(self, fullname, path=None, target=None):
            module_name = self._pending.get(fullname)
            if module_name is None:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or spec.loader is None:
                return None
            original_exec = spec.loader.exec_module
            pending = self._pending

            def exec_module(module, _orig=original_exec, _key=fullname):
                _orig(module)
                name = pending.pop(_key, None)
                if name is not None:
                    _install(name)

            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _Finder(_pending))
