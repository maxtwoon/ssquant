"""Àberration策略 - 统一运行版本

十大经典策略之一

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

策略逻辑:
1. 使用ATR(平均真实波幅)度量市场波动
2. 突破策略 + 移动止损
3. 当价格突破N日最高价+K倍ATR时买入
4. 当价格跌破N日最低价-K倍ATR时卖出
5. 采用移动止损保护利润

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

def initialize(api: StrategyAPI):
    api.log("Aberration策略初始化")
    # 设置策略参数
    api.log(f"布林带周期: {api.get_param('bb_period', 20)}")
    api.log(f"布林带标准差倍数: {api.get_param('bb_std', 2)}")
    api.log(f"ATR周期: {api.get_param('atr_period', 14)}")
    api.log(f"ATR倍数止损: {api.get_param('atr_multiplier', 2)}")

def strategy_function(api: StrategyAPI):
    # 获取参数
    bb_period = api.get_param('bb_period', 20)
    bb_std = api.get_param('bb_std', 2)
    atr_period = api.get_param('atr_period', 14)
    atr_multiplier = api.get_param('atr_multiplier', 2)
    current_idx = api.get_idx()

    # 数据验证
    if current_idx < max(bb_period, atr_period):
        return

    close = api.get_close()
    high = api.get_high()
    low = api.get_low()

    if close is None or len(close) == 0:
        api.log("警告: 数据为空")
        return

    # 计算布林带指标
    ma = close.rolling(bb_period).mean()
    std = close.rolling(bb_period).std()
    upper_band = ma + bb_std * std
    lower_band = ma - bb_std * std

    # 计算ATR指标
    tr = pd.DataFrame({
        'hl': high - low,
        'hc': abs(high - close.shift(1)),
        'lc': abs(low - close.shift(1))
    }).max(axis=1)
    atr = tr.rolling(atr_period).mean()

    # 获取当前价格和仓位（使用相对索引，兼容回测和实盘）
    current_price = close.iloc[-1]
    current_pos = api.get_pos()

    # 交易逻辑
    # 做多信号：价格突破上轨
    if current_price > upper_band.iloc[-1]:
        if current_pos <= 0:
            api.close_all(order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"做多信号触发，价格{current_price:.2f}突破上轨{upper_band.iloc[-1]:.2f}")
            # 设置止损
            stop_loss_price = current_price - atr.iloc[-1] * atr_multiplier
            api.log(f"设置止损价: {stop_loss_price:.2f}")

    # 做空信号：价格跌破下轨
    elif current_price < lower_band.iloc[-1]:
        if current_pos >= 0:
            api.close_all(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"做空信号触发，价格{current_price:.2f}跌破下轨{lower_band.iloc[-1]:.2f}")
            # 设置止损
            stop_loss_price = current_price + atr.iloc[-1] * atr_multiplier
            api.log(f"设置止损价: {stop_loss_price:.2f}")

    # 平仓信号：价格回归中轨
    elif (current_pos > 0 and current_price < ma.iloc[-1]) or \
         (current_pos < 0 and current_price > ma.iloc[-1]):
        api.close_all(order_type='next_bar_open')
        api.log(f"平仓信号触发，价格{current_price:.2f}回归中轨{ma.iloc[-1]:.2f}")

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {
        'bb_period': 20,
        'bb_std': 2,
        'atr_period': 14,
        'atr_multiplier': 2,
    }

    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        config = get_config(RUN_MODE,
            symbol='au888',         # 合约代码（支持 au2602, au888 等）
            start_date='2025-12-01', # 回测开始日期
            end_date='2026-01-31',  # 回测结束日期
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            slippage_ticks=1,       # 滑点跳数（每跳=price_tick）

            initial_capital=100000, # 初始资金（元）

            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 ====================
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',              # 服务器: '电信1','电信2','移动','TEST'(盘后测试)

            symbol='au888',         # 合约代码（支持 au2602, au888 等）
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d

            order_offset_ticks=10,  # 委托超价跳数（+10=对手价+10跳，确保成交）

            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            preload_history=True,             # 预加载历史K线 (ATR+布林带需要100根)
            history_lookback_bars=100, # 预加载历史K线数量
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            lookback_bars=500,                # K线/TICK回溯窗口 (0=不限制，策略get_klines返回的最大条数)

            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 ====================
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）

            symbol='au888',         # 合约代码
            kline_period='1m',      # K线周期

            order_offset_ticks=10,  # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

            algo_trading=False,     # 智能算法交易
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 最大重试次数
            retry_offset_ticks=5,   # 重试超价跳数

            auto_roll_enabled=False, # 自动移仓
            auto_roll_reopen=True,  # 移仓补回仓位

            preload_history=True,   # 预加载历史K线
            history_lookback_bars=100, # 预加载K线数
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            lookback_bars=500,                # K线/TICK回溯窗口 (0=不限制，策略get_klines返回的最大条数)

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
    print("Aberration策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 布林带周期={strategy_params['bb_period']}, ATR周期={strategy_params['atr_period']}")
    print("="*80 + "\n")

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)

    # 设置配置
    runner.set_config(config)

    # 运行策略
    try:
        results = runner.run(
            strategy=strategy_function,
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
