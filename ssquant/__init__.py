"""SSQuant - 期货量化交易框架"""

<<<<<<< HEAD
__version__ = "0.3.8"
=======
__version__ = "0.4.6"
>>>>>>> origin/main
__author__ = "SSQuant Team"

# 检查CTP可用性
import sys

try:
    from .ctp.loader import CTP_AVAILABLE
except:
    CTP_AVAILABLE = False

if not CTP_AVAILABLE:
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"[WARN] 当前Python {py_version} 的CTP功能不可用")
    print("       回测功能可正常使用，实盘功能受限")
