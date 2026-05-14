import os
from datetime import datetime

class BacktestLogger:
    """回测日志管理器类，负责处理日志记录、日志文件创建等功能"""
    
    def __init__(self, debug_mode=True):
        """初始化日志管理器"""
        self.log_file = None
        self.performance_file = None
        self.debug_mode = debug_mode
        # P7：持久文件句柄。prepare_log_file 中开，log_message / log_important 直写，
        # close() / 下一次 prepare_log_file 中关闭。避免每条日志开关一次文件（~50μs/行）。
        self._log_fp = None
    
    def set_debug_mode(self, debug_mode):
        """设置调试模式
        
        Args:
            debug_mode: 是否开启调试模式
        """
        self.debug_mode = debug_mode
    
    def prepare_log_file(self, symbols_and_periods):
        """准备日志文件
        
        Args:
            symbols_and_periods: 品种和周期列表
            
        Returns:
            log_file_path: 日志文件路径
        """
        # 进入新 run 之前，确保关掉上一次留下的句柄
        self._close_log_fp()

        # 检查是否禁用可视化和日志
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            # 在参数优化过程中禁用日志文件
            self.log_file = None
            self.performance_file = None
            return None
            
        # 创建日志目录
        log_dir = "backtest_logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 创建日志文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        symbols_str = "_".join([item["symbol"] for item in symbols_and_periods])
        self.log_file = os.path.join(log_dir, f"backtest_{symbols_str}_{timestamp}.log")
        
        # 创建综合绩效报告文件 - 即使在debug=False模式下也创建
        results_dir = "backtest_results"
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
        self.performance_file = os.path.join(results_dir, f"performance_{symbols_str}_{timestamp}.txt")
        
        # P7：直接打开持久句柄写入日志头，后续 log_message / log_important 共用此句柄。
        # 用 'w' 覆盖式打开（新建空文件），写入头部后保持打开，写入由 OS buffer 攒批。
        try:
            self._log_fp = open(self.log_file, 'w', encoding='utf-8')
            self._log_fp.write(f"多数据源回测日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._log_fp.write(f"回测品种: {symbols_str}\n")
            self._log_fp.write("-" * 80 + "\n\n")
        except Exception:
            # 异常时回退：句柄置 None，写入路径会自动跳过文件输出
            self._log_fp = None

        return self.log_file

    def _close_log_fp(self):
        """安全关闭持久日志句柄。可重复调用。"""
        fp = self._log_fp
        if fp is not None:
            self._log_fp = None
            try:
                fp.flush()
            except Exception:
                pass
            try:
                fp.close()
            except Exception:
                pass

    def close(self):
        """关闭日志资源。run_backtest 结束 / 程序退出时调用。"""
        self._close_log_fp()

    def __del__(self):
        try:
            self._close_log_fp()
        except Exception:
            pass

    def log_message(self, message):
        """记录日志消息
        
        Args:
            message: 日志消息
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        
        # 检查是否禁用控制台日志
        if self.debug_mode and not os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            print(log_message)  # 打印到控制台
        
        # 如果有持久句柄且未禁用日志，则直接写入；不再每条 open/close。
        if self._log_fp is not None and not os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            try:
                self._log_fp.write(log_message + "\n")
            except Exception:
                # 句柄异常时降级：关闭句柄 + 退回老路径，至少不丢日志
                self._close_log_fp()
                if self.log_file:
                    try:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(log_message + "\n")
                    except Exception:
                        pass

    def log_important(self, message):
        """记录关键提示：无论 debug 是否开启，都尽量输出到控制台。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"

        print(log_message)

        if self._log_fp is not None and not os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            try:
                self._log_fp.write(log_message + "\n")
            except Exception:
                self._close_log_fp()
                if self.log_file:
                    try:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(log_message + "\n")
                    except Exception:
                        pass
    
    def get_performance_file(self):
        """获取绩效报告文件路径"""
        # 如果禁用可视化，则返回None
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            return None
        
        # 确保绩效报告文件目录存在
        if self.performance_file and not os.path.exists(os.path.dirname(self.performance_file)):
            os.makedirs(os.path.dirname(self.performance_file))
            
        return self.performance_file 