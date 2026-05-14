"""
跨周期过滤策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

策略逻辑:
1. 长周期(日线)判断趋势方向
2. 短周期(15分钟)寻找入场时机
3. 只在大趋势方向上交易

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
from doctest import debug
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

def initialize(api: StrategyAPI):
    """
    策略初始化函数

    Args:
        api: 策略API对象
    """
    api.log("=" * 80)
    api.log("跨周期过滤策略初始化")
    api.log("=" * 80)

    # 获取参数
    long_period = api.get_param('long_period', 20)
    short_period = api.get_param('short_period', 5)

    api.log(f"参数设置 - 长周期MA: {long_period}, 短周期MA: {short_period}")
    api.log("")
    api.log("策略逻辑说明：")
    api.log("  1. 使用60分钟周期判断大趋势方向")
    api.log("  2. 使用15分钟周期寻找入场时机")
    api.log("  3. 只在大趋势方向上交易")
    api.log("")
    api.log("交易条件：")
    api.log("  做多：60分钟快线 > 慢线（多头趋势）且 15分钟金叉")
    api.log("  做空：60分钟快线 < 慢线（空头趋势）且 15分钟死叉")
    api.log("=" * 80)

def cross_period_strategy(api: StrategyAPI):
    """
    双均线跨周期过滤策略

    Args:
        api: 策略API对象
    """
    # 确保至少有2个数据源
    if not api.require_data_sources(2):
        print("没有足够的数据源")
        return

    # 获取参数
    long_period = api.get_param('long_period', 20)
    short_period = api.get_param('short_period', 5)

    # 获取当前索引和日期时间
    bar_idx = api.get_idx(0)  # 使用15分钟K线的索引
    bar_datetime = api.get_datetime(0)

    # 获取K线数据
    klines_15m = api.get_klines(0)  # 15分钟K线 (数据源0)
    klines_60m = api.get_klines(1)  # 60分钟K线 (数据源1)

    # 检查数据是否为空
    if klines_15m.empty or klines_60m.empty:
        if bar_idx == 0:  # 只在第一次打印
            api.log(f"⚠️ 数据为空：15分钟={len(klines_15m)}条, 60分钟={len(klines_60m)}条")
        return

    # 确保有足够的数据
    if len(klines_15m) < long_period + 5 or len(klines_60m) < long_period + 5:
        return

    # 获取收盘价
    close_15m = klines_15m['close']
    close_60m = klines_60m['close']
    # 计算均线
    ma_long_15m = close_15m.rolling(long_period).mean()
    ma_short_15m = close_15m.rolling(short_period).mean()
    ma_long_60m = close_60m.rolling(long_period).mean()
    ma_short_60m = close_60m.rolling(short_period).mean()

    # 如果数据不足，直接返回（使用相对索引）
    if (pd.isna(ma_long_15m.iloc[-1]) or pd.isna(ma_long_60m.iloc[-1])):
        return

    # 获取当前和前一个周期的均线值（使用相对索引-1表示当前，-2表示前一个）
    curr_long_15m = ma_long_15m.iloc[-1]
    prev_long_15m = ma_long_15m.iloc[-2]
    curr_short_15m = ma_short_15m.iloc[-1]
    prev_short_15m = ma_short_15m.iloc[-2]

    curr_long_60m = ma_long_60m.iloc[-1]
    curr_short_60m = ma_short_60m.iloc[-1]

    # 获取当前持仓和价格（使用相对索引）
    current_pos = api.get_pos(0)  # 只在15分钟周期上交易
    current_price = close_15m.iloc[-1]

    # 判断60分钟周期的趋势
    trend_60m_bullish = curr_short_60m > curr_long_60m  # 60分钟周期多头趋势
    trend_60m_bearish = curr_short_60m < curr_long_60m  # 60分钟周期空头趋势

    # 判断15分钟周期的信号
    signal_15m_buy = prev_short_15m <= prev_long_15m and curr_short_15m > curr_long_15m  # 15分钟金叉
    signal_15m_sell = prev_short_15m >= prev_long_15m and curr_short_15m < curr_long_15m  # 15分钟死叉

    # 检测是否有交易信号或重要事件
    has_signal = signal_15m_buy or signal_15m_sell
    should_log = (bar_idx % 100 == 0) or has_signal or current_pos != 0

    '''
    if should_log:
        api.log(f"\n[{bar_datetime}] 价格: {current_price:.2f}")
        api.log(f"  15分钟 - 快线: {curr_short_15m:.2f}, 慢线: {curr_long_15m:.2f}, 信号: {'金叉' if signal_15m_buy else '死叉' if signal_15m_sell else '无'}")
        api.log(f"  60分钟 - 快线: {curr_short_60m:.2f}, 慢线: {curr_long_60m:.2f}, 趋势: {'多头' if trend_60m_bullish else '空头' if trend_60m_bearish else '中性'}")
        api.log(f"  当前持仓: {current_pos}")
    '''
    # 交易逻辑：只有当60分钟周期趋势和15分钟周期信号一致时，才执行交易

    # 多头条件：60分钟多头趋势 + 15分钟金叉
    if trend_60m_bullish and signal_15m_buy:
        if current_pos <= 0:  # 如果没有持仓或者空头持仓
            #api.log(f"✅ 满足多头条件：60分钟多头趋势 + 15分钟金叉")
            # 先平掉所有仓位，再开多仓
            if current_pos < 0:
                #api.log(f"  平空仓")
                api.close_all(order_type='next_bar_open', index=0)
            #api.log(f"  开多仓")
            api.buy(volume=1, order_type='next_bar_open', index=0)

    # 空头条件：60分钟空头趋势 + 15分钟死叉
    elif trend_60m_bearish and signal_15m_sell:
        if current_pos >= 0:  # 如果没有持仓或者多头持仓
            #api.log(f"✅ 满足空头条件：60分钟空头趋势 + 15分钟死叉")
            # 先平掉所有仓位，再开空仓
            if current_pos > 0:
                #api.log(f"  平多仓")
                api.close_all(order_type='next_bar_open', index=0)
            #api.log(f"  开空仓")
            api.sellshort(volume=1, order_type='next_bar_open', index=0)
    '''
    # 当15分钟有信号但60分钟趋势不匹配时，给出提示
    elif has_signal:
        if signal_15m_buy:
            api.log(f"⚠️  15分钟金叉信号，但60分钟趋势不是多头，不交易")
        elif signal_15m_sell:
            api.log(f"⚠️  15分钟死叉信号，但60分钟趋势不是空头，不交易")
    '''

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {
        'long_period': 20,
        'short_period': 5,
    }

    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (跨周期 - 同品种不同周期) ====================
        config = get_config(RUN_MODE,
            start_date='2025-12-01', # 回测开始日期
            end_date='2026-2-30',   # 回测结束日期
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            initial_capital=1000000,           # 初始资金 (元)
            debug=False,            # 是否开启调试日志
            align_data=True,        # 是否对齐多数据源时间轴
            fill_method='ffill',    # 对齐缺失值填充方式: ffill(前值填充) / bfill(后值填充)

            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)

            data_sources=[
                {   # 数据源0: 短周期 (入场信号)
                    'symbol': 'cu888',        # 品种+888 = 主力连续合约（回测时用于拉取连续K线）
                    'kline_period': '2m',     # K线周期 (短周期)
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 长周期 (趋势过滤)
                    'symbol': 'cu888',        # 与短周期同品种
                    'kline_period': '6m',    # K线周期 (长周期)
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ],
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (多周期) ====================
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)

            data_sources=[
                {   # 数据源0: 短周期 (入场信号)
                    'symbol': 'cu888',          # 主力合约（自动映射）
                    'kline_period': '2m',         # K线周期 (短周期)
                    'order_offset_ticks': 10,     # 下单偏移跳数 (挂单距离)

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 长周期 (趋势过滤)
                    'symbol': 'cu888',          # 与短周期同品种
                    'kline_period': '6m',        # K线周期 (长周期)
                    'order_offset_ticks': 10,     # 下单偏移跳数

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)

            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 (多周期) ====================
        config = get_config(RUN_MODE,
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)

            data_sources=[
                {   # 数据源0: 短周期 (入场信号)
                    'symbol': 'cu888',          # 主力合约（自动映射）
                    'kline_period': '2m',         # K线周期 (短周期)
                    'order_offset_ticks': 10,     # 下单偏移跳数 (挂单距离)

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 长周期 (趋势过滤)
                    'symbol': 'cu888',          # 与短周期同品种
                    'kline_period': '6m',         # K线周期 (长周期)
                    'order_offset_ticks': 10,     # 下单偏移跳数

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],

            auto_roll_enabled=False, # 自动移仓
            auto_roll_reopen=True,  # 移仓补回仓位

            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)

            enable_tick_callback=False, # Tick回调

            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=False,    # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    # ========== 创建运行器并执行 ==========
    print("\n" + "="*80)
    print("跨周期过滤策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    # 多数据源模式：打印所有数据源
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 长周期={strategy_params['long_period']}, 短周期={strategy_params['short_period']}")
    print("="*80 + "\n")

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)

    # 设置配置
    runner.set_config(config)

    # 运行策略
    try:
        results = runner.run(
            strategy=cross_period_strategy,
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
