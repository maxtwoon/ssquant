"""跨品种套利策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

策略逻辑:
1. 计算两个品种的价差
2. 当价差偏离均值时开仓
3. 当价差回归均值时平仓

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
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np
import statsmodels.api as sm

def initialize(api: StrategyAPI):
    """
    策略初始化函数
    此函数用于初始化策略并输出日志信息。

    Args:
        api: 策略API对象，用于访问策略参数和日志功能
    """
    api.log("跨品种套利策略初始化...")  # 输出初始化日志
    api.log("本策略利用焦炭(J)和焦煤(JM)之间的价差关系进行套利")  # 描述策略的核心逻辑

def calculate_spread(price1, price2, hedge_ratio=None):
    """
    计算两个价格序列之间的价差
    如果提供hedge_ratio，则使用该比率调整价差计算；否则直接相减。

    Args:
        price1: 第一个品种的价格序列（例如焦炭）
        price2: 第二个品种的价格序列（例如焦煤）
        hedge_ratio: 套期保值比率，如果为None则不使用

    Returns:
        价差序列，表示两个价格序列的差值
    """
    if hedge_ratio is None:
        return price1 - price2  # 如果没有hedge_ratio，直接计算差值
    else:
        return price1 - price2 * hedge_ratio  # 使用hedge_ratio调整后计算价差

def calculate_hedge_ratio(price1, price2, window=60, current_idx=None):
    """
    计算套期保值比率（基于OLS回归）
    使用指定窗口的历史数据进行线性回归，获取动态对冲比率。

    Args:
        price1: 第一个品种的价格序列
        price2: 第二个品种的价格序列
        window: 滚动窗口大小，用于选取历史数据
        current_idx: 当前位置索引，如果为None则使用序列末尾

    Returns:
        当前位置的对冲比率
    """
    if current_idx is None:
        current_idx = len(price1) - 1  # 默认使用序列末尾作为当前索引
    if current_idx < window - 1:
        return np.nan  # 如果数据不足，返回NaN
    start_idx = max(0, current_idx - window + 1)  # 计算窗口起始索引

    # 选取窗口数据
    y = price1.iloc[start_idx:current_idx+1]  # 选取y变量数据
    X_series = price2.iloc[start_idx:current_idx+1]  # 选取X变量数据

    # 重置索引以确保对齐（关键修复）
    y = y.reset_index(drop=True)
    X_series = X_series.reset_index(drop=True)

    # 添加常数项
    X = sm.add_constant(X_series)  # 添加常数项以包含截距

    try:
        model = sm.OLS(y, X)  # 创建OLS模型
        results = model.fit()  # 拟合模型
        hedge_ratio = results.params.iloc[1]  # 获取斜率系数作为对冲比率（修复 FutureWarning）
        return hedge_ratio
    except Exception as e:
        # 如果回归失败，返回NaN
        return np.nan

def calculate_zscore(spread, window=20):
    """
    计算价差的Z分数
    Z分数用于衡量价差偏离均值的程度，基于移动窗口计算。

    Args:
        spread: 价差序列
        window: 窗口大小，用于计算移动均值和标准差

    Returns:
        Z分数序列
    """
    mean = spread.rolling(window=window).mean()  # 计算移动平均值
    std = spread.rolling(window=window).std()  # 计算移动标准差
    zscore = (spread - mean) / std  # 计算Z分数
    return zscore

def pairs_trading_strategy(api: StrategyAPI):
    """
    跨品种套利策略主函数
    基于价差的Z分数进行交易决策，包括开仓和平仓逻辑。
    """
    if not api.require_data_sources(2):  # 检查是否至少有2个数据源
        return  # 如果不足，返回

    min_samples = api.get_param('min_samples', 200)  # 获取最小样本数参数
    zscore_threshold = api.get_param('zscore_threshold', 2.0)  # 获取Z分数阈值
    rolling_window = api.get_param('rolling_window', 20)  # 获取滚动窗口大小
    hedge_ratio_window = api.get_param('hedge_ratio_window', 30)  # 获取对冲比率窗口
    use_dynamic_hedge_ratio = api.get_param('use_dynamic_hedge_ratio', True)  # 是否使用动态对冲比率

    bar_idx = api.get_idx(0)  # 获取当前K线索引
    j_klines = api.get_klines(0)  # 获取焦炭K线数据
    jm_klines = api.get_klines(1)  # 获取焦煤K线数据

    if len(j_klines) < min_samples or len(jm_klines) < min_samples:  # 检查数据量是否足够
        return  # 如果不足，返回

    j_close = j_klines['close']  # 提取焦炭收盘价
    jm_close = jm_klines['close']  # 提取焦煤收盘价

    hedge_ratio = None
    if use_dynamic_hedge_ratio:  # 如果使用动态对冲比率
        if bar_idx >= hedge_ratio_window:
            hedge_ratio = calculate_hedge_ratio(j_close, jm_close, window=hedge_ratio_window, current_idx=bar_idx)
        if pd.isna(hedge_ratio):  # 如果计算结果为NaN
            hedge_ratio = 1.5  # 使用默认值
    else:
        hedge_ratio = 1.5  # 使用静态对冲比率

    spread = calculate_spread(j_close, jm_close, hedge_ratio)  # 计算价差
    if bar_idx < rolling_window:  # 如果数据不足以计算Z分数
        return

    zscore = calculate_zscore(spread, window=rolling_window)  # 计算Z分数序列
    current_zscore = zscore.iloc[-1]  # 获取当前Z分数（使用相对索引）
    if pd.isna(current_zscore):  # 如果Z分数为NaN
        return

    j_pos = api.get_pos(0)  # 获取焦炭持仓
    jm_pos = api.get_pos(1)  # 获取焦煤持仓
    j_unit = 1  # 焦炭交易单位
    jm_unit = max(1, round(j_unit * hedge_ratio))  # 计算焦煤交易单位

    if j_pos == 0 and jm_pos == 0:  # 无持仓情况
        if current_zscore > zscore_threshold:  # Z分数过高，做空价差
            api.sellshort(volume=j_unit, order_type='next_bar_open', index=0)
            api.buy(volume=jm_unit, order_type='next_bar_open', index=1)
        elif current_zscore < -zscore_threshold:  # Z分数过低，做多价差
            api.buy(volume=j_unit, order_type='next_bar_open', index=0)
            api.sellshort(volume=jm_unit, order_type='next_bar_open', index=1)
    elif j_pos < 0 and jm_pos > 0:  # 持有空焦炭多焦煤
        if current_zscore < 0.5:  # Z分数回归，平仓
            api.buycover(order_type='next_bar_open', index=0)
            api.sell(order_type='next_bar_open', index=1)
    elif j_pos > 0 and jm_pos < 0:  # 持有多焦炭空焦煤
        if current_zscore > -0.5:  # Z分数回归，平仓
            api.sell(order_type='next_bar_open', index=0)
            api.buycover(order_type='next_bar_open', index=1)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {
        'lookback': 20,
        'threshold': 2.0,
    }

    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (跨品种套利 - 螺纹钢vs铁矿石) ====================
        config = get_config(RUN_MODE,
            start_date='2025-12-01', # 回测开始日期
            end_date='2026-01-31',  # 回测结束日期
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            initial_capital=100000,           # 初始资金 (元)

            align_data=True,        # 是否对齐多数据源时间轴
            fill_method='ffill',    # 对齐缺失值填充方式: ffill(前值填充) / bfill(后值填充)

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）

            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',        # 品种+888 = 主力连续合约（回测时用于拉取连续K线）
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',         # 品种+888 = 主力连续合约（回测时用于拉取连续K线）
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ],
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (跨品种套利) ====================
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)

            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',          # 品种+888 = 主力连续（如 rb888→rb2505）
                    'kline_period': '1m',         # K线周期
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)

                    'algo_trading': False,        # 是否启用
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',           # 品种+888 = 主力连续（如 i888→i2505）
                    'kline_period': '1m',         # K线周期
                    'order_offset_ticks': 10,     # 下单偏移跳数

                    'algo_trading': False,        # 是否启用
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）

            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 (跨品种套利) ====================
        config = get_config(RUN_MODE,
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)

            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',          # 主力合约（自动映射）
                    'kline_period': '1m',         # K线周期
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',           # 主力合约（自动映射）
                    'kline_period': '1m',         # K线周期
                    'order_offset_ticks': 10,     # 下单偏移跳数

                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移

                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
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
    print("跨品种套利策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    # 多数据源模式：打印所有品种
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"套利对: {' vs '.join(symbols)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 回溯周期={strategy_params['lookback']}, 阈值={strategy_params['threshold']}")
    print("="*80 + "\n")

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)

    # 设置配置
    runner.set_config(config)

    # 运行策略
    try:
        results = runner.run(
            strategy=pairs_trading_strategy,
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
