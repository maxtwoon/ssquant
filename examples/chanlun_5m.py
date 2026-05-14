"""ASCII alias module for B_缠论5分钟策略.py.

Re-exports strategy + initialize so joblib worker processes can pickle/unpickle
the function references by qualified name (examples.chanlun_5m.chanlun_5m_strategy).
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TARGET = os.path.join(_HERE, 'B_缠论5分钟策略.py')

_spec = importlib.util.spec_from_file_location(__name__ + '._impl', _TARGET)
_impl = importlib.util.module_from_spec(_spec)
sys.modules[__name__ + '._impl'] = _impl
_spec.loader.exec_module(_impl)

# Re-export everything so that funcs are accessible at examples.chanlun_5m.xxx
for _name in dir(_impl):
    if not _name.startswith('_'):
        globals()[_name] = getattr(_impl, _name)

# Explicit re-exports for clarity
chanlun_5m_strategy = _impl.chanlun_5m_strategy
initialize = _impl.initialize
