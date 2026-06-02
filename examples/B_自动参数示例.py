"""
自动参数策略示例 - 演示合约参数自动获取功能
Auto Parameters Strategy Demo

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

特性：
1. 无需手动填写 contract_multiplier、price_tick、margin_rate、commission
2. 支持主力连续合约（如 au888）自动解析为当前主力合约
3. 支持多品种回测，每个品种自动获取对应参数
4. 手动指定的参数会覆盖自动获取的参数

使用说明：
    只需填写合约代码，其他参数自动从远程服务器获取
    首次运行会从 kanpan789.com 拉取合约信息并缓存到本地

合约代码 symbol 怎么填：
  回测：品种+888 = 主力连续合约，用于拉取连续K线（如 au888、rb888）
  SIMNOW / 实盘（自动主力映射）：
    au888  → 自动映射为当前主力月份（如 au888→au2508），用于CTP订阅和下单
    au777  → 自动映射为次主力月份
    au2508 → 指定月份，直接使用，不做映射

自动移仓（仅 SIMNOW/实盘）：持仓过主力换月时，开启 auto_roll_enabled=True 即可自动平旧开新
合约参数（乘数、最小变动价、手续费等）自动获取，无需手动填写
复权 adjust_type：'0'=不复权  '1'=后复权  '2'=前复权
K线来源 kline_source（仅 SIMNOW/实盘）：'local'=本地CTP Tick合成（默认）  'data_server'=远程推送
账户配置：在 trading_config.py 的 ACCOUNTS 中填写CTP账号信息
"""

import pandas as pd
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

def initialize(api: StrategyAPI):
    """
    策略初始化函数

    Args:
        api: 策略API对象
    """
    api.log("=" * 50)
    api.log("自动参数策略示例 - 初始化")
    api.log("=" * 50)

    # 获取参数
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)
    api.log(f"参数设置 - 快线周期: {fast_ma}, 慢线周期: {slow_ma}")

def ma_cross_strategy(api: StrategyAPI):
    """
    双均线交叉策略

    策略逻辑:
    - 短期均线上穿长期均线: 买入信号
    - 短期均线下穿长期均线: 卖出信号

    Args:
        api: 策略API对象
    """
    # 获取参数
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)

    # 获取当前索引
    current_idx = api.get_idx()

    if current_idx < slow_ma:
        return

    # 获取收盘价和计算均线
    close = api.get_close()
    if len(close) < slow_ma:
        return

    fast_ma_values = close.rolling(fast_ma).mean()
    slow_ma_values = close.rolling(slow_ma).mean()

    # 获取当前持仓
    current_pos = api.get_pos()

    # 均线金叉：快线上穿慢线
    if fast_ma_values.iloc[-2] <= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] > slow_ma_values.iloc[-1]:
        if current_pos <= 0:
            if current_pos < 0:
                api.buycover(volume=1, order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"均线金叉：快线({fast_ma_values.iloc[-1]:.2f})上穿慢线({slow_ma_values.iloc[-1]:.2f})，买入")

    # 均线死叉：快线下穿慢线
    elif fast_ma_values.iloc[-2] >= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] < slow_ma_values.iloc[-1]:
        if current_pos >= 0:
            if current_pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"均线死叉：快线({fast_ma_values.iloc[-1]:.2f})下穿慢线({slow_ma_values.iloc[-1]:.2f})，卖出")

# =====================================================================
# 配置区
# =====================================================================

if __name__ == "__main__":

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {'fast_ma': 5, 'slow_ma': 20}

    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置（自动参数）====================
        #
        # 【重点】只需填写合约代码，以下参数自动获取：
        #   - contract_multiplier (合约乘数)
        #   - price_tick (最小变动价位)
        #   - margin_rate (保证金率)
        #   - commission (手续费率)
        #
        config = get_config(RUN_MODE,
            symbol='au888',         # 合约代码（支持 au2602, au888 等）
            start_date='2025-12-01', # 回测开始日期
            end_date='2026-01-31',  # 回测结束日期
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权
            debug= False,           # 是否开启调试日志

            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            initial_capital=500000,           # 初始资金 (元)
            slippage_ticks=1,                 # 滑点跳数 (回测模拟成交时的滑点)

            lookback_bars=500,                # K线回溯窗口 (0=不限制)
        )

        # ==================== 多品种回测配置示例（自动参数）====================
        # 取消下面的注释可以运行多品种回测
        """
        config = get_config(RUN_MODE,
            start_date='2025-12-01', # 回测开始日期
            end_date='2026-01-31',  # 回测结束日期
            initial_capital=1000000, # 初始资金（元）

            align_data=False,       # 是否对齐多数据源时间轴

            data_sources=[
                {   # 数据源0: 黄金主力
                    'symbol': 'au888',          # 主连；可改 au2602
                    'kline_period': '15m',
                    'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,
                },
                {   # 数据源1: 螺纹钢主力
                    'symbol': 'rb888',          # 主连；可改 rb2505
                    'kline_period': '15m',
                    'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,
                },
                {   # 数据源2: 原油主力
                    'symbol': 'sc888',          # 主连；可改 sc2605
                    'kline_period': '15m',
                    'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,
                },
            ],

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
        """

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置（自动参数）====================
        config = get_config(RUN_MODE,
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            account='simnow_default',         # 账户名称 (在trading_config.py的ACCOUNTS中定义)
            server_name='电信1',              # 服务器: '电信1','电信2','移动','TEST'(盘后测试)

            symbol='au888',         # 合约代码（支持 au2602, au888 等）
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d

            order_offset_ticks=-5,            # 委托偏移跳数 (超价下单确保成交)

            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            preload_history=True,   # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=100, # 预加载历史K线数量
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）

            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=True,    # 是否保存K线到CSV文件
            save_kline_db=True,     # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置（自动参数）====================
        config = get_config(RUN_MODE,
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            account='real_default',           # 账户名称 (在trading_config.py的ACCOUNTS中定义)

            symbol='au888',         # 合约代码
            kline_period='1m',      # K线周期

            order_offset_ticks=-10, # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

            algo_trading=True,      # 智能算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 最大重试次数
            retry_offset_ticks=5,   # 重试超价跳数

            auto_roll_enabled=False, # 自动移仓
            auto_roll_reopen=True,  # 移仓补回仓位

            preload_history=True,   # 预加载历史K线
            history_lookback_bars=100, # 预加载K线数
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            lookback_bars=500,      # 回溯窗口（IndicatorCache重算范围）

            enable_tick_callback=False, # Tick回调

            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=False,    # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
        )

    # ========== 创建运行器并执行 ==========
    print("\n" + "=" * 80)
    print("自动参数策略示例 (B_自动参数示例.py)")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")

    # 打印合约信息
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")

    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}")

    # 打印自动获取的参数
    print("-" * 40)
    print("自动获取的合约参数:")
    print(f"  合约乘数: {config.get('contract_multiplier', '未设置')}")
    print(f"  最小跳动: {config.get('price_tick', '未设置')}")
    print(f"  保证金率: {config.get('margin_rate', '未设置')}")
    print(f"  手续费率: {config.get('commission', '未设置')}")
    print("=" * 80 + "\n")

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)

    # 设置配置
    runner.set_config(config)

    # 运行策略
    try:
        results = runner.run(
            strategy=ma_cross_strategy,
            initialize=initialize,
            strategy_params=strategy_params
        )

    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
