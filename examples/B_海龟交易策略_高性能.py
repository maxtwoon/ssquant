"""海龟交易策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_海龟交易策略.py` 行为完全一致，只是把所有指标计算搬到
`initialize` 钩子里通过 `api.register_indicator` 注册：

  原版：每根 Bar 调 `calculate_donchian_channel` / `calculate_atr` 全量 rolling
  本版：initialize 阶段一次性预计算 entry_upper / entry_lower / exit_upper /
        exit_lower / atr 共 5 个指标，主循环全部 O(1) 查表

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式一）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×
  方式三 — Pandas 兼容（老写法）：慢但向后兼容

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用，
策略代码一字不改。详见 SUMMARY.md §7。
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

_turtle_state = {}  # {data_source_index: {'last_entry_price': float}}

# ====== 指标计算函数（独立可测，签名遵守 register_indicator 协议） ======
def _make_donchian_upper_func(period: int):
    """返回唐奇安通道上轨计算 func（rolling max of high）。"""
    def _f(close, open_, high, low, volume):
        return pd.Series(high).rolling(window=period).max().to_numpy()
    return _f

def _make_donchian_lower_func(period: int):
    """返回唐奇安通道下轨计算 func（rolling min of low）。"""
    def _f(close, open_, high, low, volume):
        return pd.Series(low).rolling(window=period).min().to_numpy()
    return _f

def _make_atr_func(period: int):
    """返回 ATR 计算 func（与原版 calculate_atr 完全等价）。"""
    def _f(close, open_, high, low, volume):
        hs = pd.Series(high)
        ls = pd.Series(low)
        cs = pd.Series(close)
        tr1 = hs - ls
        tr2 = (hs - cs.shift(1)).abs()
        tr3 = (ls - cs.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean().to_numpy()
    return _f

def initialize(api: StrategyAPI):
    """策略初始化 — 在数据加载后、主循环前调用一次，注册所有指标。"""
    api.log("海龟交易策略初始化（高性能版 / IndicatorCache）...")
    api.log("所有交易将使用下一根K线开盘价执行 (order_type='next_bar_open')")
    api.log("本策略基于唐奇安通道进行趋势跟踪交易")

    entry_period = api.get_param('entry_period', 20)
    exit_period = api.get_param('exit_period', 10)
    atr_period = api.get_param('atr_period', 14)
    risk_factor = api.get_param('risk_factor', 0.01)

    api.log(f"参数设置 - 入场周期: {entry_period}, 出场周期: {exit_period}, " +
            f"ATR周期: {atr_period}, 风险因子: {risk_factor}")

    # ====== 为每个数据源注册 5 个指标（一次预计算，主循环 O(1) 查表） ======
    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('entry_upper', _make_donchian_upper_func(entry_period),
                               window=entry_period, index=i)
        api.register_indicator('entry_lower', _make_donchian_lower_func(entry_period),
                               window=entry_period, index=i)
        api.register_indicator('exit_upper', _make_donchian_upper_func(exit_period),
                               window=exit_period, index=i)
        api.register_indicator('exit_lower', _make_donchian_lower_func(exit_period),
                               window=exit_period, index=i)
        api.register_indicator('atr', _make_atr_func(atr_period),
                               window=atr_period, index=i)
    api.log(f"已注册指标: entry_upper / entry_lower / exit_upper / exit_lower / atr （×{ds_count} 数据源）")

def calculate_position_size(price, atr, account_size, risk_factor, contract_multiplier,
                            margin_rate=0.10, current_pos=0):
    """与原版完全一致的头寸规模计算（含保证金约束）。"""
    dollar_per_point = contract_multiplier
    volatility_value = atr * dollar_per_point
    risk_amount = account_size * risk_factor

    position_size = risk_amount / volatility_value
    position_size = int(np.floor(position_size))

    if position_size <= 0:
        return 0

    margin_per_lot = price * contract_multiplier * margin_rate
    if margin_per_lot <= 0:
        return max(1, position_size)

    max_total_lots = int(np.floor(account_size / margin_per_lot))
    available_lots = max(0, max_total_lots - abs(current_pos))

    position_size = min(position_size, available_lots)
    return position_size

def turtle_trading_strategy(api: StrategyAPI):
    """海龟交易策略主循环（高性能版）。

    与原版逻辑完全等价，差别仅在指标读取方式：
      原版：klines = api.get_klines(i); rolling/concat/shift 全量重算
      本版：api.get_indicator_array(name, window=2, index=i) → 直接拿最近 2 个值
    """
    entry_period = api.get_param('entry_period', 20)
    exit_period = api.get_param('exit_period', 10)
    atr_period = api.get_param('atr_period', 14)
    risk_factor = api.get_param('risk_factor', 0.01)
    max_units = api.get_param('max_units', 4)
    margin_rate = api.get_param('margin_rate', 0.10)

    data_sources_count = api.get_data_sources_count()
    min_required_bars = max(entry_period, exit_period, atr_period) + 5

    for i in range(data_sources_count):
        # 用 get_idx 判断数据长度，避免 get_klines 全量取 DataFrame
        current_idx = api.get_idx(i)
        data_len = current_idx + 1
        if data_len <= min_required_bars:
            if data_len == 1:
                api.log(f"数据源 {i} 数据准备中，需要至少 {min_required_bars} 根K线...")
            continue

        # === 方式一核心：O(1) 读取所有指标的最近 2 个值（用于"上一根 vs 当前"对比） ===
        entry_upper_arr = api.get_indicator_array('entry_upper', window=2, index=i)
        entry_lower_arr = api.get_indicator_array('entry_lower', window=2, index=i)
        exit_upper_arr = api.get_indicator_array('exit_upper', window=2, index=i)
        exit_lower_arr = api.get_indicator_array('exit_lower', window=2, index=i)

        # 当前/前一根通道值（与原版 .iloc[-1] / .iloc[-2] 严格对应）
        current_entry_upper = entry_upper_arr[-1]
        current_entry_lower = entry_lower_arr[-1]
        current_exit_upper = exit_upper_arr[-1]
        current_exit_lower = exit_lower_arr[-1]
        prev_entry_upper = entry_upper_arr[-2]
        prev_entry_lower = entry_lower_arr[-2]
        prev_exit_upper = exit_upper_arr[-2]
        prev_exit_lower = exit_lower_arr[-2]

        # 当前价用 api.get_current_price（比 close.iloc[-1] 快）
        current_price = api.get_current_price(i)
        if current_price is None:
            continue

        # ATR 当前值
        current_atr = api.get_indicator('atr', index=i)
        if pd.isna(current_atr) or current_atr == 0:
            api.log(f"数据源 {i} 的ATR为无效值，跳过")
            continue

        data_source = api.get_data_source(i)
        if data_source is None:
            api.log(f"无法获取数据源 {i}")
            continue

        symbol = data_source.symbol

        symbol_configs = api.get_param('symbol_configs', {})
        symbol_config = symbol_configs.get(symbol, {})

        account_size = api.get_balance() or symbol_config.get('initial_capital', 100000.0)
        contract_multiplier = symbol_config.get('contract_multiplier', 10)

        current_pos = api.get_pos(i)

        unit_size = calculate_position_size(
            current_price, current_atr, account_size, risk_factor,
            contract_multiplier, margin_rate, abs(current_pos)
        )

        current_units = abs(current_pos) / max(unit_size, 1) if unit_size > 0 else abs(current_pos)

        margin_per_lot = current_price * contract_multiplier * margin_rate
        max_total_lots = int(np.floor(account_size / margin_per_lot)) if margin_per_lot > 0 else 0

        if data_len % 100 == 0:
            api.log(f"品种 {symbol} - 数据量: {data_len}, 价格: {current_price:.2f}, ATR: {current_atr:.2f}")
            api.log(f"入场通道: 上轨={current_entry_upper:.2f}, 下轨={current_entry_lower:.2f}")
            api.log(f"出场通道: 上轨={current_exit_upper:.2f}, 下轨={current_exit_lower:.2f}")
            api.log(f"单个系统单位规模: {unit_size}, 当前单位数: {current_units:.2f}/{max_units}")
            api.log(f"保证金/手: {margin_per_lot:.0f}, 最大可开: {max_total_lots}, 当前持仓: {current_pos}")

        state = _turtle_state.setdefault(i, {'last_entry_price': 0.0})

        # 交易逻辑（与原版逐字一致）
        if current_pos == 0:
            state['last_entry_price'] = 0.0

            if current_price > prev_entry_upper:
                if unit_size > 0:
                    api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破入场通道上轨 {prev_entry_upper:.2f}，开多仓 1个单位 ({unit_size})")
                    api.buy(volume=int(unit_size), order_type='next_bar_open', index=i)
                    state['last_entry_price'] = current_price
                else:
                    api.log(f"品种 {symbol} 多头信号触发，但保证金不足，跳过开仓")

            elif current_price < prev_entry_lower:
                if unit_size > 0:
                    api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破入场通道下轨 {prev_entry_lower:.2f}，开空仓 1个单位 ({unit_size})")
                    api.sellshort(volume=int(unit_size), order_type='next_bar_open', index=i)
                    state['last_entry_price'] = current_price
                else:
                    api.log(f"品种 {symbol} 空头信号触发，但保证金不足，跳过开仓")

        elif current_pos > 0:
            if current_price < prev_exit_lower:
                api.log(f"品种 {symbol} 价格 {current_price:.2f} 跌破出场通道下轨 {prev_exit_lower:.2f}，平多仓")
                api.sell(order_type='next_bar_open', index=i)
                state['last_entry_price'] = 0.0

            elif current_units < max_units and unit_size > 0 and state['last_entry_price'] > 0:
                if current_price >= state['last_entry_price'] + 0.5 * current_atr:
                    new_unit_size = int(unit_size)
                    if new_unit_size > 0:
                        api.log(f"品种 {symbol} 价格 {current_price:.2f} 较上次入场 {state['last_entry_price']:.2f} 上涨0.5ATR，加多仓 ({new_unit_size})")
                        api.buy(volume=new_unit_size, order_type='next_bar_open', index=i)
                        state['last_entry_price'] = current_price

        elif current_pos < 0:
            if current_price > prev_exit_upper:
                api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破出场通道上轨 {prev_exit_upper:.2f}，平空仓")
                api.buycover(order_type='next_bar_open', index=i)
                state['last_entry_price'] = 0.0

            elif current_units < max_units and unit_size > 0 and state['last_entry_price'] > 0:
                if current_price <= state['last_entry_price'] - 0.5 * current_atr:
                    new_unit_size = int(unit_size)
                    if new_unit_size > 0:
                        api.log(f"品种 {symbol} 价格 {current_price:.2f} 较上次入场 {state['last_entry_price']:.2f} 下跌0.5ATR，加空仓 ({new_unit_size})")
                        api.sellshort(volume=new_unit_size, order_type='next_bar_open', index=i)
                        state['last_entry_price'] = current_price

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'entry_period': 20,                # 入场周期（唐奇安通道）
        'exit_period': 10,                 # 出场周期（唐奇安通道）
        'atr_period': 14,                  # ATR周期
        'risk_factor': 0.01,               # 风险因子（单笔风险占总资金比例）
        'max_units': 4,                    # 最大加仓单位数
        'margin_rate': 0.10,               # 保证金率
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            symbol='rb888',                    # 合约代码（支持 au888 等）
            start_date='2022-01-01',           # 回测开始日期
            end_date='2026-01-31',             # 回测结束日期
            kline_period='5m',                 # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            slippage_ticks=1,                  # 滑点跳数（每跳=price_tick）
            initial_capital=100000,            # 初始资金（元）
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            symbol='au888',                    # 合约代码（888=主力连续，CTP会自动解析为实际合约）
            kline_period='1m',                 # K线周期（CTP Tick合成）
            order_offset_ticks=10,             # 委托超价跳数（+10=对手价+10跳，确保成交）
            algo_trading=False,                # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                  # 订单超时时间（秒），0=不启用
            retry_limit=3,                     # 订单失败最大重试次数
            retry_offset_ticks=5,              # 重试时额外超价跳数
            auto_roll_enabled=False,           # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,             # 移仓后是否在新主力补回仓位
            preload_history=True,              # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=200,         # 预加载历史K线数量
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=500,                 # 回溯窗口（实盘IndicatorCache重算范围）
            enable_tick_callback=False,        # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,              # 是否保存K线到CSV文件
            save_kline_db=False,               # 是否保存K线到SQLite数据库
            save_tick_csv=False,               # 是否保存Tick到CSV文件
            save_tick_db=False,                # 是否保存Tick到SQLite数据库
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',            # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            kline_source='data_server',        # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            symbol='au888',                    # 合约代码
            kline_period='1m',                 # K线周期
            order_offset_ticks=10,             # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）
            algo_trading=False,                # 智能算法交易
            order_timeout=10,                  # 订单超时（秒）
            retry_limit=3,                     # 最大重试次数
            retry_offset_ticks=5,              # 重试超价跳数
            auto_roll_enabled=False,           # 自动移仓
            auto_roll_reopen=True,             # 移仓补回仓位
            preload_history=True,              # 预加载历史K线
            history_lookback_bars=200,         # 预加载K线数
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=500,                 # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,        # Tick回调
            save_kline_csv=False,              # 保存K线CSV
            save_kline_db=False,               # 保存K线DB
            save_tick_csv=False,               # 保存Tick CSV
            save_tick_db=False,                # 保存Tick DB
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("海龟交易策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 入场周期={strategy_params['entry_period']}, 出场周期={strategy_params['exit_period']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=turtle_trading_strategy,
            initialize=initialize,
            strategy_params=strategy_params,
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
