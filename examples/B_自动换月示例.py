"""
自动换月 + 双均线示例（SIMNOW / 实盘）

功能说明：
  当主力合约发生切换时，框架自动帮你完成移仓（平旧合约 → 开新主力），无需在策略里手写。
  只需在 get_config 中设置 auto_roll_enabled=True 即可开启。

  移仓模式：
    'simultaneous' — 同时发出平旧和开新委托（更快）
    'sequential'   — 先平旧，确认平完后再开新（更稳）

本策略示例只做两件事：
  1. 双均线交易信号
  2. 移仓进行中时暂停下单（api.is_rollover_busy()），避免与移仓冲突

回测模式下不执行自动移仓，本示例等价于普通双均线策略。
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

def initialize(api: StrategyAPI):
    api.log("=" * 50)
    api.log("框架内自动换月 + 双均线 — 初始化")
    api.log("=" * 50)
    fast_ma = api.get_param("fast_ma", 5)
    slow_ma = api.get_param("slow_ma", 20)
    api.log(f"均线参数: fast_ma={fast_ma}, slow_ma={slow_ma}")
    api.log(
        "移仓：由适配器在策略前调用 RolloverEngine；请在 get_config 中设置 "
        "auto_roll_enabled=True 及 auto_roll_mode / auto_roll_reopen 等（见本文件配置区）。"
    )

def rollover_ma_strategy(api: StrategyAPI):
    """双均线；移仓进行中不下新单。"""
    fast_ma = api.get_param("fast_ma", 5)
    slow_ma = api.get_param("slow_ma", 20)
    pause_on_roll = api.get_param("pause_signals_when_rollover_busy", True)

    if pause_on_roll and api.is_rollover_busy():
        return

    ds = api.get_data_source(0)
    current_idx = api.get_idx(0)
    if current_idx < slow_ma:
        return

    close = api.get_close(0)
    if len(close) < slow_ma:
        return

    fast_ma_values = close.rolling(fast_ma).mean()
    slow_ma_values = close.rolling(slow_ma).mean()

    current_pos = api.get_pos(0)

    if fast_ma_values.iloc[-2] <= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] > slow_ma_values.iloc[-1]:
        if current_pos <= 0:
            if current_pos < 0:
                api.buycover(volume=1, order_type="next_bar_open", index=0)
            api.buy(volume=1, order_type="next_bar_open", index=0)
            api.log(f"均线金叉：买入（{getattr(ds, 'symbol', '')}）")

    elif fast_ma_values.iloc[-2] >= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] < slow_ma_values.iloc[-1]:
        if current_pos >= 0:
            if current_pos > 0:
                api.sell(order_type="next_bar_open", index=0)
            api.sellshort(volume=1, order_type="next_bar_open", index=0)
            api.log(f"均线死叉：做空（{getattr(ds, 'symbol', '')}）")

# =====================================================================
# 配置区（修改 RUN_MODE 与对应的 get_config 参数即可）
# =====================================================================

if __name__ == "__main__":

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.SIMNOW

    strategy_params = {
        "fast_ma": 5,
        "slow_ma": 20,
        # 为 True 时，api.is_rollover_busy() 期间不发出均线信号（推荐）
        "pause_signals_when_rollover_busy": True,
    }

    # --- 回测：不包含 auto_roll_*（回测不跑框架移仓）---
    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(
            RUN_MODE,
            symbol="au888",         # 合约代码（支持 au2602, au888 等）
            start_date="2025-12-01", # 回测开始日期
            end_date="2026-01-31",  # 回测结束日期
            kline_period="15m",     # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type="1",        # 复权: '0'不复权, '1'后复权, '2'前复权
            debug=False,            # 是否开启调试日志
            initial_capital=500000, # 初始资金（元）
            slippage_ticks=1,       # 滑点跳数（每跳=price_tick）
            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )

    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(
            RUN_MODE,
            account="simnow_default", # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name="电信1",      # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            symbol="au888",         # 合约代码（支持 au2602, au888 等）
            kline_period="1m",      # K线周期: 1m/5m/15m/30m/1h/1d
            order_offset_ticks=-5,  # 委托超价跳数（+10=对手价+10跳，确保成交）
            algo_trading=False,     # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,       # 订单超时时间（秒），0=不启用
            retry_limit=3,          # 订单失败最大重试次数
            retry_offset_ticks=5,   # 重试时额外超价跳数
            preload_history=True,   # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=5000, # 预加载历史K线数量
            adjust_type="1",        # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=1000,     # 回溯K线窗口（IndicatorCache预热用）
            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=True,    # 是否保存K线到CSV文件
            save_kline_db=True,     # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
            auto_roll_enabled=True, # 是否启用自动移仓（主力换月）
            auto_roll_mode="simultaneous",     # 'simultaneous'=同时平开（更快）  'sequential'=先平后开（更稳）
            auto_roll_reopen=True,  # 移仓后是否在新主力补回仓位
            auto_roll_order_type="next_bar_open",  # 移仓委托方式
            auto_roll_close_offset_ticks=None, # 平旧跳数偏移（None=沿用 order_offset_ticks）
            auto_roll_open_offset_ticks=None,  # 开新跳数偏移（None=沿用 order_offset_ticks）
            auto_roll_verify_timeout_bars=500, # 超时重置（策略回调次数）
            auto_roll_log_enabled=True,        # 记录移仓日志
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(
            RUN_MODE,
            account="real_default", # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            symbol="au888",         # 合约代码
            kline_period="1m",      # K线周期
            order_offset_ticks=-10, # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）
            algo_trading=True,      # 智能算法交易
            order_timeout=10,       # 订单超时（秒）
            retry_limit=3,          # 最大重试次数
            retry_offset_ticks=5,   # 重试超价跳数
            preload_history=True,   # 预加载历史K线
            history_lookback_bars=5000, # 预加载K线数
            adjust_type="1",        # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=500,      # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False, # Tick回调
            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=False,    # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
            auto_roll_enabled=True, # 自动移仓
            auto_roll_mode="sequential",       # 'simultaneous'=同时平开  'sequential'=先平后开（实盘更稳）
            auto_roll_reopen=True,  # 移仓补回仓位
            auto_roll_order_type="next_bar_open",  # 移仓委托方式
            auto_roll_close_offset_ticks=None, # 平旧跳数偏移（None=沿用 order_offset_ticks）
            auto_roll_open_offset_ticks=None,  # 开新跳数偏移（None=沿用 order_offset_ticks）
            auto_roll_verify_timeout_bars=500, # 超时重置（策略回调次数）
            auto_roll_log_enabled=True,        # 记录移仓日志
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )

    print("\n" + "=" * 80)
    print("框架内自动换月 + 双均线 (B_自动换月示例.py)")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if "data_sources" in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config["data_sources"]]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: {strategy_params}")
    if RUN_MODE in (RunMode.SIMNOW, RunMode.REAL_TRADING):
        print(
            "框架移仓: "
            f"enabled={config.get('auto_roll_enabled')}, "
            f"mode={config.get('auto_roll_mode')}, "
            f"reopen={config.get('auto_roll_reopen')}"
        )
    print("自动获取的合约参数:")
    print(f"  合约乘数: {config.get('contract_multiplier', '未设置')}")
    print(f"  最小跳动: {config.get('price_tick', '未设置')}")
    print(f"  保证金率: {config.get('margin_rate', '未设置')}")
    print(f"  手续费率: {config.get('commission', '未设置')}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        runner.run(
            strategy=rollover_ma_strategy,
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
