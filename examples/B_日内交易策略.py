"""
日内交易策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易
3. 实盘CTP交易

策略特点:
1. 只做日内交易，不持仓过夜
2. 收盘前强制平仓
3. 基于开盘区间突破进场
4. 设置止损止盈

策略逻辑:
1. 开盘后N分钟确定震荡区间（最高价、最低价）
2. 价格突破区间上轨做多
3. 价格突破区间下轨做空
4. 收盘前15分钟清仓

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

from datetime import datetime, time
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# ========== 全局状态变量 ==========
g_day_high = 0              # 当日震荡区间高点
g_day_low = 0               # 当日震荡区间低点
g_range_confirmed = False   # 区间是否已确定
g_last_trade_date = None    # 上次交易日期
g_entry_price = 0           # 入场价格
g_day_traded = False        # 当日是否已交易

def initialize(api: StrategyAPI):
    """策略初始化函数"""
    global g_day_high, g_day_low, g_range_confirmed, g_last_trade_date
    global g_entry_price, g_day_traded

    api.log("=" * 60)
    api.log("日内交易策略初始化")
    api.log("=" * 60)

    # 获取策略参数
    range_minutes = api.get_param('range_minutes', 30)
    stop_loss_pct = api.get_param('stop_loss_pct', 0.5)
    take_profit_pct = api.get_param('take_profit_pct', 1.0)

    api.log(f"参数设置:")
    api.log(f"  区间确认时间: 开盘后 {range_minutes} 分钟")
    api.log(f"  止损比例: {stop_loss_pct}%")
    api.log(f"  止盈比例: {take_profit_pct}%")
    api.log(f"  收盘平仓: 14:45 (夜盘22:45)")
    api.log("=" * 60)

    # 重置状态
    g_day_high = 0
    g_day_low = 0
    g_range_confirmed = False
    g_last_trade_date = None
    g_entry_price = 0
    g_day_traded = False

def is_close_time(current_time):
    """判断是否接近收盘时间"""
    # 日盘收盘前15分钟: 14:45-15:00
    day_close = time(14, 45)
    # 夜盘收盘前15分钟: 22:45-23:00 (部分品种到凌晨)
    night_close = time(22, 45)

    if isinstance(current_time, datetime):
        current_time = current_time.time()

    return current_time >= day_close or current_time >= night_close

def is_open_range_time(current_time, range_minutes):
    """判断是否在开盘区间确认时间内"""
    # 日盘开盘: 09:00
    day_open = time(9, 0)
    day_range_end = time(9, range_minutes)

    # 夜盘开盘: 21:00
    night_open = time(21, 0)
    night_range_end = time(21, range_minutes)

    if isinstance(current_time, datetime):
        current_time = current_time.time()

    return (day_open <= current_time < day_range_end or
            night_open <= current_time < night_range_end)

def intraday_strategy(api: StrategyAPI):
    """
    日内交易策略

    策略逻辑:
    1. 开盘后30分钟内记录最高最低价，确定震荡区间
    2. 价格突破区间上轨时做多
    3. 价格突破区间下轨时做空
    4. 设置止损止盈
    5. 收盘前强制平仓

    风险控制:
    - 每日只交易一次
    - 止损止盈保护
    - 收盘前清仓，不持仓过夜
    """
    global g_day_high, g_day_low, g_range_confirmed, g_last_trade_date
    global g_entry_price, g_day_traded

    # 获取当前时间和价格
    current_datetime = api.get_datetime()
    if current_datetime is None:
        return

    # 获取当前价格
    tick = api.get_tick()
    if tick is not None:
        current_price = tick.get('LastPrice', 0)
    else:
        current_price = api.get_price()

    if current_price is None or current_price <= 0:
        return

    # 获取策略参数
    range_minutes = api.get_param('range_minutes', 30)
    stop_loss_pct = api.get_param('stop_loss_pct', 0.5)
    take_profit_pct = api.get_param('take_profit_pct', 1.0)

    # 获取当前日期
    if isinstance(current_datetime, datetime):
        current_date = current_datetime.date()
        current_time = current_datetime.time()
    else:
        current_date = current_datetime
        current_time = time(12, 0)  # 默认时间

    # 新的一天，重置状态
    if g_last_trade_date != current_date:
        g_day_high = current_price
        g_day_low = current_price
        g_range_confirmed = False
        g_day_traded = False
        g_entry_price = 0
        g_last_trade_date = current_date
        api.log(f"\n[新交易日] {current_date} 重置状态")

    # 获取当前持仓
    current_pos = api.get_pos()

    # ========== 收盘前强制平仓 ==========
    if is_close_time(current_time) and current_pos != 0:
        if current_pos > 0:
            api.sell(order_type='market', reason='收盘平仓')
            api.log(f"⏰ [收盘平仓] 平多仓 价格:{current_price:.2f}")
        elif current_pos < 0:
            api.buycover(order_type='market', reason='收盘平仓')
            api.log(f"⏰ [收盘平仓] 平空仓 价格:{current_price:.2f}")
        return

    # ========== 开盘区间确认阶段 ==========
    if not g_range_confirmed:
        # 更新区间高低点
        g_day_high = max(g_day_high, current_price)
        g_day_low = min(g_day_low, current_price)

        # 检查是否超过区间确认时间
        if not is_open_range_time(current_time, range_minutes):
            if g_day_high > g_day_low:
                g_range_confirmed = True
                range_width = g_day_high - g_day_low
                api.log(f"\n[区间确认] 上轨:{g_day_high:.2f} 下轨:{g_day_low:.2f} "
                       f"区间宽度:{range_width:.2f}")
        return

    # ========== 止损止盈检查 ==========
    if current_pos != 0 and g_entry_price > 0:
        if current_pos > 0:  # 多头持仓
            # 止损
            stop_loss_price = g_entry_price * (1 - stop_loss_pct / 100)
            if current_price <= stop_loss_price:
                api.sell(order_type='market', reason='多头止损')
                api.log(f"🛑 [止损] 多头止损 入场:{g_entry_price:.2f} "
                       f"止损价:{stop_loss_price:.2f} 当前:{current_price:.2f}")
                g_entry_price = 0
                return

            # 止盈
            take_profit_price = g_entry_price * (1 + take_profit_pct / 100)
            if current_price >= take_profit_price:
                api.sell(order_type='market', reason='多头止盈')
                api.log(f"🎯 [止盈] 多头止盈 入场:{g_entry_price:.2f} "
                       f"止盈价:{take_profit_price:.2f} 当前:{current_price:.2f}")
                g_entry_price = 0
                return

        elif current_pos < 0:  # 空头持仓
            # 止损
            stop_loss_price = g_entry_price * (1 + stop_loss_pct / 100)
            if current_price >= stop_loss_price:
                api.buycover(order_type='market', reason='空头止损')
                api.log(f"🛑 [止损] 空头止损 入场:{g_entry_price:.2f} "
                       f"止损价:{stop_loss_price:.2f} 当前:{current_price:.2f}")
                g_entry_price = 0
                return

            # 止盈
            take_profit_price = g_entry_price * (1 - take_profit_pct / 100)
            if current_price <= take_profit_price:
                api.buycover(order_type='market', reason='空头止盈')
                api.log(f"🎯 [止盈] 空头止盈 入场:{g_entry_price:.2f} "
                       f"止盈价:{take_profit_price:.2f} 当前:{current_price:.2f}")
                g_entry_price = 0
                return

    # ========== 开仓信号 ==========
    if current_pos == 0 and not g_day_traded and g_range_confirmed:
        # 突破上轨做多
        if current_price > g_day_high:
            api.buy(volume=1, order_type='market', reason='突破上轨做多')
            g_entry_price = current_price
            g_day_traded = True
            api.log(f"📈 [做多] 突破上轨 上轨:{g_day_high:.2f} 当前:{current_price:.2f}")

        # 突破下轨做空
        elif current_price < g_day_low:
            api.sellshort(volume=1, order_type='market', reason='突破下轨做空')
            g_entry_price = current_price
            g_day_traded = True
            api.log(f"📉 [做空] 突破下轨 下轨:{g_day_low:.2f} 当前:{current_price:.2f}")

# =====================================================================
# 配置区
# =====================================================================

if __name__ == "__main__":

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {
        'range_minutes': 30,    # 开盘区间确认时间（分钟）
        'stop_loss_pct': 0.5,   # 止损比例（%）
        'take_profit_pct': 1.0, # 止盈比例（%）
    }

    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        config = get_config(RUN_MODE,
            symbol='rb888',         # 合约代码（支持 au2602, au888 等）
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
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)

            symbol='rb888',         # 合约代码（支持 au2602, au888 等）
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d

            order_offset_ticks=5,   # 委托超价跳数（+10=对手价+10跳，确保成交）

            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            preload_history=True,   # 是否预加载历史K线（策略初始化前填充）
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

            symbol='rb888',         # 合约代码
            kline_period='1m',      # K线周期

            order_offset_ticks=5,   # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

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

    # ========== 创建运行器并执行 ==========
    print("\n" + "=" * 60)
    print("日内交易策略 - 统一运行版本")
    print("=" * 60)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数:")
    print(f"  区间确认: 开盘后 {strategy_params['range_minutes']} 分钟")
    print(f"  止损比例: {strategy_params['stop_loss_pct']}%")
    print(f"  止盈比例: {strategy_params['take_profit_pct']}%")
    print("=" * 60 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=intraday_strategy,
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
