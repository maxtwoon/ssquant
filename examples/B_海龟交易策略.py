"""海龟交易策略 - 统一运行版本

经典趋势跟踪策略

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

入场信号:
- 突破20日最高价，买入做多
- 跌破20日最低价，卖出做空

出场信号:
- 多头持仓，价格跌破10日最低价，平多
- 空头持仓，价格突破10日最高价，平空

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

_turtle_state = {}  # {data_source_index: {'last_entry_price': float}}

def initialize(api:StrategyAPI):
    """
    策略初始化函数

    Args:
        api: 策略API对象
    """
    api.log("海龟交易策略初始化...")
    api.log("所有交易将使用下一根K线开盘价执行 (order_type='next_bar_open')")
    api.log("本策略基于唐奇安通道进行趋势跟踪交易")

    # 获取策略参数
    entry_period = api.get_param('entry_period', 20)  # 入场周期
    exit_period = api.get_param('exit_period', 10)    # 出场周期
    atr_period = api.get_param('atr_period', 14)      # ATR周期
    risk_factor = api.get_param('risk_factor', 0.01)  # 风险因子

    api.log(f"参数设置 - 入场周期: {entry_period}, 出场周期: {exit_period}, " +
            f"ATR周期: {atr_period}, 风险因子: {risk_factor}")

def calculate_donchian_channel(high_series, low_series, period):
    """
    计算唐奇安通道

    Args:
        high_series: 最高价序列
        low_series: 最低价序列
        period: 周期

    Returns:
        (上轨, 下轨)
    """
    upper = high_series.rolling(window=period).max()
    lower = low_series.rolling(window=period).min()

    return upper, lower

def calculate_atr(high_series, low_series, close_series, period=14):
    """
    计算平均真实波幅（ATR）

    Args:
        high_series: 最高价序列
        low_series: 最低价序列
        close_series: 收盘价序列
        period: 周期

    Returns:
        ATR序列
    """
    # 计算真实波幅（True Range）
    tr1 = high_series - low_series
    tr2 = (high_series - close_series.shift(1)).abs()
    tr3 = (low_series - close_series.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 计算ATR
    atr = tr.rolling(window=period).mean()

    return atr

def calculate_position_size(price, atr, account_size, risk_factor, contract_multiplier,
                            margin_rate=0.10, current_pos=0):
    """
    计算头寸规模（含保证金约束）

    Args:
        price: 当前价格
        atr: 当前ATR值
        account_size: 账户规模
        risk_factor: 风险因子
        contract_multiplier: 合约乘数
        margin_rate: 保证金率（默认 10%）
        current_pos: 当前已持仓手数（绝对值），用于计算剩余可用资金

    Returns:
        头寸数量（int），如果资金不足返回 0
    """
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
    """
    海龟交易策略（加入波动率调整的头寸管理）

    该策略在经典海龟交易法则的基础上，加入了基于波动率的头寸调整，
    旨在通过风险管理来提高交易效率。

    策略逻辑：
    1. 当价格突破N日高点时入场做多
    2. 当价格突破N/2日低点时离场
    3. 当价格突破N日低点时入场做空
    4. 当价格突破N/2日高点时离场
    5. 使用ATR来确定头寸规模
    6. 基于系统单位的头寸调整（海龟系统）
    """
    # 获取策略参数
    entry_period = api.get_param('entry_period', 20)    # 入场周期
    exit_period = api.get_param('exit_period', 10)      # 出场周期
    atr_period = api.get_param('atr_period', 14)        # ATR周期
    risk_factor = api.get_param('risk_factor', 0.01)    # 风险因子
    max_units = api.get_param('max_units', 4)           # 最大系统单位数
    margin_rate = api.get_param('margin_rate', 0.10)    # 保证金率

    # 获取数据源数量
    data_sources_count = api.get_data_sources_count()

    # 确保有足够的数据（最小需要的K线数量）
    min_required_bars = max(entry_period, exit_period, atr_period) + 5

    # 遍历所有数据源
    for i in range(data_sources_count):
        # 获取K线数据
        klines = api.get_klines(i)
        data_len = len(klines)

        # 检查数据长度是否足够
        if data_len <= min_required_bars:
            # 只在首次打印警告
            if data_len == 1:
                api.log(f"数据源 {i} 数据准备中，需要至少 {min_required_bars} 根K线...")
            continue

        # 获取价格数据
        high = klines['high']
        low = klines['low']
        close = klines['close']

        # 💡 关键概念：实盘模式下使用相对索引
        # - klines 是一个滚动窗口（deque，maxlen=1000）
        # - 我们总是处理"最新"的数据
        # - 使用 -1 表示最新K线，-2 表示前一根K线

        # 获取当前价格（使用最新数据）
        current_price = close.iloc[-1]

        # 计算唐奇安通道
        entry_upper, entry_lower = calculate_donchian_channel(high, low, entry_period)
        exit_upper, exit_lower = calculate_donchian_channel(high, low, exit_period)

        # 获取当前通道值（使用最新数据）
        current_entry_upper = entry_upper.iloc[-1]
        current_entry_lower = entry_lower.iloc[-1]
        current_exit_upper = exit_upper.iloc[-1]
        current_exit_lower = exit_lower.iloc[-1]

        # 使用前一根K线的通道值判断突破（当前K线包含在通道中，用当前值会导致突破条件无法触发）
        prev_entry_upper = entry_upper.iloc[-2]
        prev_entry_lower = entry_lower.iloc[-2]
        prev_exit_upper = exit_upper.iloc[-2]
        prev_exit_lower = exit_lower.iloc[-2]
        prev_close = close.iloc[-2]

        # 计算ATR
        atr = calculate_atr(high, low, close, atr_period)
        current_atr = atr.iloc[-1]

        # 检查ATR是否为NaN
        if pd.isna(current_atr) or current_atr == 0:
            api.log(f"数据源 {i} 的ATR为无效值，跳过")
            continue

        # 获取数据源和品种信息
        data_source = api.get_data_source(i)
        if data_source is None:
            api.log(f"无法获取数据源 {i}")
            continue

        symbol = data_source.symbol

        # 这是关键修改：直接从全局上下文中获取symbol_configs
        symbol_configs = api.get_param('symbol_configs', {})
        symbol_config = symbol_configs.get(symbol, {})

        # 使用实时账户权益计算头寸（盈利时放大、亏损时缩小）
        # 回退到初始资金（首次调用或权益异常时）
        account_size = api.get_balance() or symbol_config.get('initial_capital', 100000.0)
        contract_multiplier = symbol_config.get('contract_multiplier', 10)

        # 获取当前持仓
        current_pos = api.get_pos(i)

        # 计算单个系统单位的头寸规模（含保证金约束）
        unit_size = calculate_position_size(
            current_price, current_atr, account_size, risk_factor,
            contract_multiplier, margin_rate, abs(current_pos)
        )

        # 计算当前系统单位数（绝对值）
        current_units = abs(current_pos) / max(unit_size, 1) if unit_size > 0 else abs(current_pos)

        margin_per_lot = current_price * contract_multiplier * margin_rate
        max_total_lots = int(np.floor(account_size / margin_per_lot)) if margin_per_lot > 0 else 0

        # 定期打印状态（使用数据长度判断，避免频繁输出）
        if data_len % 100 == 0:
            api.log(f"品种 {symbol} - 数据量: {data_len}, 价格: {current_price:.2f}, ATR: {current_atr:.2f}")
            api.log(f"入场通道: 上轨={current_entry_upper:.2f}, 下轨={current_entry_lower:.2f}")
            api.log(f"出场通道: 上轨={current_exit_upper:.2f}, 下轨={current_exit_lower:.2f}")
            api.log(f"单个系统单位规模: {unit_size}, 当前单位数: {current_units:.2f}/{max_units}")
            api.log(f"保证金/手: {margin_per_lot:.0f}, 最大可开: {max_total_lots}, 当前持仓: {current_pos}")

        # 获取/初始化该数据源的状态
        state = _turtle_state.setdefault(i, {'last_entry_price': 0.0})

        # 交易逻辑
        # 情况1: 当前无持仓
        if current_pos == 0:
            state['last_entry_price'] = 0.0

            # 检查是否突破入场通道上轨（做多信号）
            if current_price > prev_entry_upper:
                if unit_size > 0:
                    api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破入场通道上轨 {prev_entry_upper:.2f}，开多仓 1个单位 ({unit_size})")
                    api.buy(volume=int(unit_size), order_type='next_bar_open', index=i)
                    state['last_entry_price'] = current_price
                else:
                    api.log(f"品种 {symbol} 多头信号触发，但保证金不足，跳过开仓")

            # 检查是否突破入场通道下轨（做空信号）
            elif current_price < prev_entry_lower:
                if unit_size > 0:
                    api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破入场通道下轨 {prev_entry_lower:.2f}，开空仓 1个单位 ({unit_size})")
                    api.sellshort(volume=int(unit_size), order_type='next_bar_open', index=i)
                    state['last_entry_price'] = current_price
                else:
                    api.log(f"品种 {symbol} 空头信号触发，但保证金不足，跳过开仓")

        # 情况2: 当前持有多仓
        elif current_pos > 0:
            # 检查是否跌破出场通道下轨（平多信号） —— 使用前一根K线的通道值
            if current_price < prev_exit_lower:
                api.log(f"品种 {symbol} 价格 {current_price:.2f} 跌破出场通道下轨 {prev_exit_lower:.2f}，平多仓")
                api.sell(order_type='next_bar_open', index=i)
                state['last_entry_price'] = 0.0

            # 检查是否可以加仓（价格相对最后入场价上涨0.5个ATR且未达到最大单位数）
            elif current_units < max_units and unit_size > 0 and state['last_entry_price'] > 0:
                if current_price >= state['last_entry_price'] + 0.5 * current_atr:
                    new_unit_size = int(unit_size)
                    if new_unit_size > 0:
                        api.log(f"品种 {symbol} 价格 {current_price:.2f} 较上次入场 {state['last_entry_price']:.2f} 上涨0.5ATR，加多仓 ({new_unit_size})")
                        api.buy(volume=new_unit_size, order_type='next_bar_open', index=i)
                        state['last_entry_price'] = current_price

        # 情况3: 当前持有空仓
        elif current_pos < 0:
            # 检查是否突破出场通道上轨（平空信号） —— 使用前一根K线的通道值
            if current_price > prev_exit_upper:
                api.log(f"品种 {symbol} 价格 {current_price:.2f} 突破出场通道上轨 {prev_exit_upper:.2f}，平空仓")
                api.buycover(order_type='next_bar_open', index=i)
                state['last_entry_price'] = 0.0

            # 检查是否可以加仓（价格相对最后入场价下跌0.5个ATR且未达到最大单位数）
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

    # ========== 策略参数 ==========
    strategy_params = {
        'entry_period': 20,
        'exit_period': 10,
        'atr_period': 14,
        'risk_factor': 0.01,
        'max_units': 4,
        'margin_rate': 0.10,        # 保证金率（默认10%，根据品种调整）
    }

    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        config = get_config(RUN_MODE,
            symbol='rb888',         # 合约代码（支持 au2602, au888 等）
            start_date='2022-01-01', # 回测开始日期
            end_date='2026-01-31',  # 回测结束日期
            kline_period='5m',      # K线周期: 1m/5m/15m/30m/1h/1d
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
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)

            symbol='au888',         # 合约代码（支持 au2602, au888 等）
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d

            order_offset_ticks=10,  # 委托超价跳数（+10=对手价+10跳，确保成交）

            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            preload_history=True,             # 预加载历史K线 (海龟策略需要55周期)
            history_lookback_bars=200,        # 预加载数量 (建议200根以上)
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
            history_lookback_bars=200, # 预加载K线数
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
    print("海龟交易策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 入场周期={strategy_params['entry_period']}, 出场周期={strategy_params['exit_period']}")
    print("="*80 + "\n")

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)

    # 设置配置
    runner.set_config(config)

    # 运行策略
    try:
        results = runner.run(
            strategy=turtle_trading_strategy,
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
