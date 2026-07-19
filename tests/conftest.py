"""Load the integration's pure modules as the `deltalux` package.

The repo root holds the integration files directly (it is copied into
`custom_components/deltalux/` on install), and `__init__.py` imports Home
Assistant, so the HA-free modules under test are loaded explicitly by file
path instead of importing the package normally.
"""

import enum
import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# pytest collects the repo-root __init__.py (package-dir semantics), which
# imports Home Assistant. Stub the few symbols it needs when HA isn't
# installed so the pure-math tests can run anywhere.
if importlib.util.find_spec("homeassistant") is None:

    def _stub(name: str, **attrs) -> types.ModuleType:
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    class _Platform(str, enum.Enum):
        LIGHT = "light"

    _ha = _stub("homeassistant")
    _ha.config_entries = _stub("homeassistant.config_entries", ConfigEntry=object)
    _ha.const = _stub("homeassistant.const", Platform=_Platform)
    _ha.core = _stub("homeassistant.core", HomeAssistant=object)

_pkg = types.ModuleType("deltalux")
_pkg.__path__ = [str(_ROOT)]
sys.modules["deltalux"] = _pkg


def _load(name: str, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


_load("deltalux.const", _ROOT / "const.py")
_load("deltalux.util", _ROOT / "util.py")
