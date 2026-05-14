# Loader entry — 仅用 ASCII 文件名，避免 cmd 编码问题。
# 实际策略代码在 B_缠论5分钟策略.py 中。
import os
import runpy

_here = os.path.dirname(os.path.abspath(__file__))
_target = os.path.join(_here, 'B_缠论5分钟策略.py')

# 以 __main__ 模式执行目标脚本，触发其 if __name__ == "__main__" 块
runpy.run_path(_target, run_name='__main__')
