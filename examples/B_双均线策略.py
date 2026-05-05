"""
双均线交易策略 - 统一运行版本

支持三种运行模式：
  1. 回测   (BACKTEST)      — 用历史数据验证策略
  2. 模拟   (SIMNOW)        — 连接 SIMNOW 模拟盘，零风险实时验证
  3. 实盘   (REAL_TRADING)   — 连接真实 CTP 账户，真钱交易

使用方式：只需修改下方「配置区」的 RUN_MODE 和对应的 get_config() 参数，策略逻辑完全不用改。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
合约代码 symbol 怎么填
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  回测模式：
    sc888        主力连续合约，用于拉取完整的历史K线（回测专用，不涉及下单）

  SIMNOW / 实盘模式（自动主力映射）：
    sc888        写888 = 主力合约，框架启动时自动查询并替换为当前主力月份
                 例如 sc888 → sc2507，后续订阅行情、下单都用 sc2507
    sc777        写777 = 次主力合约，同理自动替换
    sc2507       写具体月份 = 直接使用该合约，不做替换

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
自动移仓（主力换月）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  仅 SIMNOW / 实盘生效。当交易所主力合约发生切换时：
    1. 框架自动检测到主力已从旧合约换到新合约
    2. 自动平掉旧合约上的持仓
    3. 在新主力合约上重新开出相同方向和数量的仓位

  适用场景：中长线趋势策略、需要持仓过换月的策略
  不需要时：日内策略、短线策略保持 auto_roll_enabled=False 即可

  配置示例（在 get_config 中添加）：
    auto_roll_enabled=True,         # 是否启用自动移仓（主力换月）
    auto_roll_reopen=True,          # 移仓后是否在新主力补回仓位
    auto_roll_mode='simultaneous' # 'simultaneous'=同时平开  'sequential'=先平后开

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
合约参数（自动获取）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  合约乘数、最小变动价位、保证金率、手续费率等参数会自动从远程合约表获取，无需手动填写。
  如需手动覆盖，直接在 get_config() 中写入即可（如 price_tick=0.1）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
其他常用配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  复权 adjust_type：'0'=不复权  '1'=后复权  '2'=前复权

  K线来源 kline_source（仅 SIMNOW/实盘）：
    'local'       — 用本地CTP Tick自行合成K线（默认，无需额外配置）
    'data_server' — 从远程服务器接收K线推送（需在 trading_config.py 配置 API 账号密码）

  账户配置：在 ssquant/config/trading_config.py 的 ACCOUNTS 中填写CTP账号信息
"""

import pandas as pd

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import RunMode, UnifiedStrategyRunner
from ssquant.config.trading_config import get_config

g_tick_counter = 0

def initialize(api: StrategyAPI):
    """
    策略初始化函数

    Args:
        api: 策略API对象
    """
    api.log("双均线交叉策略初始化")
    fast_ma = api.get_param('fast_ma', 2)
    slow_ma = api.get_param('slow_ma', 5)
    verbose = api.get_param('verbose_kline', False)
    api.log(f"参数设置 - 快线: {fast_ma}, 慢线: {slow_ma}, 打印K线: {verbose}")

def ma_cross_strategy(api: StrategyAPI):
    """
    双均线交叉策略

    策略逻辑:
    - 短期均线上穿长期均线: 买入信号
    - 短期均线下穿长期均线: 卖出信号

    运行模式:
    - 回测模式: 在K线完成时触发
    - 实盘模式: 启用TICK流双驱动，每个TICK都会触发，但交易仍使用K线数据

    说明:
    虽然实盘模式下每个TICK都会触发此函数，但由于使用 order_type='next_bar_open'，
    实际下单和成交都在K线级别进行，不影响策略逻辑。

    如需添加TICK级别功能（如实时止损），可以使用：
    tick = api.get_tick()  # 获取当前TICK数据
    if tick and api.get_pos() > 0:
        if tick['LastPrice'] < stop_loss_price:
            api.sell(order_type='market', reason='实时止损')

    Args:
        api: 策略API对象
    """
    global g_tick_counter  # 声明使用全局变量

    tick = api.get_tick()

    fast_ma = api.get_param('fast_ma', 2)
    slow_ma = api.get_param('slow_ma', 3)

    current_idx = api.get_idx()
    current_price = api.get_price()
    current_datetime = api.get_datetime()

    klines = api.get_klines()
    """
    if api.get_param('verbose_kline', False):
        _last_bar = klines.iloc[-1]
        print("klines (最后一根):")
        _idx_last = klines.index[-1]
        if isinstance(klines.index, pd.DatetimeIndex):
            print(f"datetime                        {_idx_last.strftime('%Y-%m-%d %H:%M:%S')}")
        elif "datetime" in klines.columns:
            _dv = pd.to_datetime(_last_bar["datetime"], errors="coerce")
            if pd.isna(_dv):
                print("datetime                        N/A")
            else:
                print(f"datetime                        {_dv.strftime('%Y-%m-%d %H:%M:%S')}")
        elif hasattr(_idx_last, "strftime"):
            print(f"datetime                        {_idx_last.strftime('%Y-%m-%d %H:%M:%S')}")
        _row = (
            _last_bar.drop(labels=["datetime"], errors="ignore")
            if "datetime" in klines.columns
            else _last_bar
        )
        print(_row.to_string(float_format=lambda x: f"{x:,.2f}"))
        print(f"K线窗口长度: {len(klines)}")
    """
    if current_idx < slow_ma:
        return

    # 获取收盘价和计算均线
    close = api.get_close()
    # 确保有足够的数据
    if len(close) < slow_ma:
        return

    fast_ma_values = close.rolling(fast_ma).mean()
    slow_ma_values = close.rolling(slow_ma).mean()
    # print(fast_ma_values)
    # print(slow_ma_values)
    # print("最新快线:",fast_ma_values.iloc[-1])
    # print("最新慢线:",slow_ma_values.iloc[-1])
    # print("前一个快线:",fast_ma_values.iloc[-2])
    # print("前一个慢线:",slow_ma_values.iloc[-2])

    # 获取当前持仓
    current_pos = api.get_pos()

    # 均线金叉：快线上穿慢线
    if fast_ma_values.iloc[-2] <= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] > slow_ma_values.iloc[-1]:
        if current_pos <= 0:
            # 如果没有持仓或者空头持仓，先平空再买入开仓
            if current_pos < 0:
                api.buycover(volume=1, order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"均线金叉：快线({fast_ma_values.iloc[-1]:.2f})上穿慢线({slow_ma_values.iloc[-1]:.2f})，买入")

    # 均线死叉：快线下穿慢线
    elif fast_ma_values.iloc[-2] >= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] < slow_ma_values.iloc[-1]:
        if current_pos >= 0:
            # 如果没有持仓或者多头持仓，先平多再卖出开仓
            if current_pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"均线死叉：快线({fast_ma_values.iloc[-1]:.2f})下穿慢线({slow_ma_values.iloc[-1]:.2f})，卖出")

# =====================================================================
# 配置区（修改 RUN_MODE 与对应分支的 get_config 即可）
# =====================================================================

if __name__ == "__main__":
    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数（会传入 initialize / strategy）==========
    strategy_params = {
        'fast_ma': 20,
        'slow_ma': 60,
        'verbose_kline': True,   # True=每根K打印最后一根OHLC（调试）；实盘建议 False
    }

    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        # 数据请求支持三种方式（可组合）：
        #   方式A: 日期范围 → start_date + end_date
        #   方式B: 精确时间 → start_time + end_time（可精确到秒）
        #   方式C: 取最近N根 → limit
        config = get_config(RUN_MODE,
            symbol='sc888',         # 合约代码（支持 au2602, au888 等）
            kline_period='5m',      # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            start_date='2022-3-20', # 回测开始日期
            end_date='2026-4-29',   # 回测结束日期

            initial_capital=1000000, # 初始资金（元）
            slippage_ticks=1,       # 滑点跳数（每跳=price_tick）

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW 模拟配置 ====================
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',               # 行情/交易服务器: '电信1','电信2','移动','TEST'(盘后测试)

            symbol='sc888',         # 合约代码（支持 au2602, au888 等）
            kline_period='1m',      # K线周期: 1m/5m/15m/30m/1h/1d

            order_offset_ticks=-5,  # 委托超价跳数（+10=对手价+10跳，确保成交）

            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,       # 订单超时时间（秒），0=不启用
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数

            auto_roll_enabled=False, # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位

            preload_history=True,   # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=3000, # 预加载历史K线数量
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            lookback_bars=5000,     # 回溯K线窗口（IndicatorCache预热用）

            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 ====================
        # ⚠ 真金白银！上线前请务必：① 核对账户信息  ② 先用SIMNOW跑通  ③ 小资金试跑
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）

            symbol='au888',         # 合约代码
            kline_period='1m',      # K线周期

            order_offset_ticks=-10, # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

            algo_trading=True,      # 智能算法交易
            order_timeout=10,       # 订单超时（秒）
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
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )

    # ========== 创建运行器并执行 ==========
    print("\n" + "="*80)
    print("双均线策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}, "
          f"verbose_kline={strategy_params.get('verbose_kline', False)}")
    print("="*80 + "\n")

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
