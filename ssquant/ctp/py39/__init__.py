# CTP Python API - Python 3.9 - Cross Platform (Windows + Linux)
__version__ = '0.4.2'

import sys
import os
import ctypes

_is_linux = sys.platform.startswith('linux')

def _preload_linux_so(search_dir):
    """
    Linux 平台预加载 CTP 运行时 .so 库
    CTP 的 .so 文件没有 lib 前缀，需要用 ctypes 预加载
    否则 Python 扩展模块导入时会找不到依赖
    """
    if not _is_linux:
        return
    for so_name in ['thostmduserapi_se.so', 'thosttraderapi_se.so']:
        so_path = os.path.join(search_dir, so_name)
        if os.path.exists(so_path):
            try:
                ctypes.cdll.LoadLibrary(so_path)
            except OSError as e:
                print(f"Warning: 预加载 {so_name} 失败: {e}")

_preload_linux_so(os.path.dirname(os.path.abspath(__file__)))

try:
    from . import _thostmduserapi
    from . import _thosttraderapi
    from . import thostmduserapi
    from . import thosttraderapi
except ImportError as e:
    print(f"Warning: {e}")
