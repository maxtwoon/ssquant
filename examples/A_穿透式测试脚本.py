"""
穿透式监管压力测试 - SSQuant框架版
用于期货开户时的CTP接口验证
测试内容：买开、卖平、卖开、买平

支持模式：SIMNOW模拟 / 实盘CTP
"""

import time
from datetime import datetime

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# ========== 测试配置 ==========
SYMBOL = 'au2602'           # 测试合约
LONG_COUNT = 3              # 多头开平次数
SHORT_COUNT = 3             # 空头开平次数
INTERVAL = 2.0              # 操作间隔（秒）

# ========== 全局状态 ==========
g_phase = 'init'
g_round = 0
g_step = 'open'
g_waiting = False
g_stats = {'buy_open': 0, 'sell_close': 0, 'sell_open': 0, 'buy_close': 0}

def on_trade(data):
    """成交回调"""
    global g_waiting, g_stats
    g_waiting = False

    d = '买' if data['Direction'] == '0' else '卖'
    o = '开' if data['OffsetFlag'] == '0' else '平'

    key = {'00': 'buy_open', '13': 'sell_close', '10': 'sell_open', '03': 'buy_close'}
    k = data['Direction'] + ('0' if data['OffsetFlag'] == '0' else '3')
    if k in key:
        g_stats[key[k]] += 1

    print(f"✅ [成交] {data['InstrumentID']} {d}{o} 价格:{data['Price']:.2f} 数量:{data['Volume']}")

def on_order(data):
    """报单回调"""
    status = {'0': '成交', '3': '未成交', '5': '已撤'}
    d = '买' if data.get('Direction') == '0' else '卖'
    print(f"📋 [报单] {data['InstrumentID']} {d} {status.get(data['OrderStatus'], data['OrderStatus'])}")

def on_order_error(data):
    """报单错误"""
    print(f"❌ [错误] {data['ErrorID']}: {data['ErrorMsg']}")

def initialize(api: StrategyAPI):
    """初始化"""
    print(f"\n{'='*50}")
    print(f"穿透式测试 | 合约:{SYMBOL} | 多头:{LONG_COUNT}次 | 空头:{SHORT_COUNT}次")
    print(f"{'='*50}\n")

def strategy(api: StrategyAPI):
    """测试策略"""
    global g_phase, g_round, g_step, g_waiting

    tick = api.get_tick()
    if tick is None or tick.get('LastPrice', 0) <= 0:
        return

    if g_waiting:
        return

    pos = api.get_pos()

    if g_phase == 'init':
        g_phase, g_round, g_step = 'long', 1, 'open'
        print(f"\n>>> 开始多头测试（共{LONG_COUNT}轮）")
        time.sleep(INTERVAL)
        return

    if g_phase == 'long':
        if g_round <= LONG_COUNT:
            if g_step == 'open':
                print(f"[多头{g_round}] 买入开仓")
                api.buy(volume=1, order_type='market')
                g_step, g_waiting = 'close', True
                time.sleep(INTERVAL)
            elif g_step == 'close' and pos > 0:
                print(f"[多头{g_round}] 卖出平仓")
                api.sell(order_type='market')
                g_round, g_step, g_waiting = g_round + 1, 'open', True
                time.sleep(INTERVAL)
        else:
            g_phase, g_round, g_step = 'short', 1, 'open'
            print(f"\n>>> 开始空头测试（共{SHORT_COUNT}轮）")
            time.sleep(INTERVAL)
        return

    if g_phase == 'short':
        if g_round <= SHORT_COUNT:
            if g_step == 'open':
                print(f"[空头{g_round}] 卖出开仓")
                api.sellshort(volume=1, order_type='market')
                g_step, g_waiting = 'close', True
                time.sleep(INTERVAL)
            elif g_step == 'close' and pos < 0:
                print(f"[空头{g_round}] 买入平仓")
                api.buycover(order_type='market')
                g_round, g_step, g_waiting = g_round + 1, 'open', True
                time.sleep(INTERVAL)
        else:
            g_phase = 'done'
            print(f"\n{'='*50}")
            print(f"测试完成 - {datetime.now().strftime('%H:%M:%S')}")
            print(f"多开:{g_stats['buy_open']} 平多:{g_stats['sell_close']} "
                  f"空开:{g_stats['sell_open']} 平空:{g_stats['buy_close']}")
            print(f"{'='*50}")
            print("按 Ctrl+C 退出")

if __name__ == "__main__":

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.SIMNOW

    # ==================== 配置 ====================
    if RUN_MODE == RunMode.SIMNOW:
        # SIMNOW模拟盘配置
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',           # SIMNOW服务器: 电信1/电信2/移动/TEST(盘后测试)

            symbol=SYMBOL,          # 合约代码（支持 au2602, au888 等）
            kline_period='tick',    # K线周期: 1m/5m/15m/30m/1h/1d

            price_tick=0.02,        # 最小变动价位（自动获取）
            order_offset_ticks=10,  # 委托超价跳数（+10=对手价+10跳，确保成交）

            enable_tick_callback=True, # 是否启用逐Tick回调（高CPU占用）
            preload_history=False,  # 是否预加载历史K线（策略初始化前填充）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # 实盘CTP配置
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）

            symbol=SYMBOL,          # 合约代码
            kline_period='tick',    # K线周期

            price_tick=0.02,        # 最小变动价位（自动获取）
            order_offset_ticks=10,  # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

            enable_tick_callback=True, # Tick回调

            preload_history=False,  # 预加载历史K线

            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=False,    # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )

    # ==================== 运行 ====================
    print(f"\n运行模式: {RUN_MODE.value}")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        runner.run(
            strategy=strategy,
            initialize=initialize,
            on_trade=on_trade,
            on_order=on_order,
            on_order_error=on_order_error,
        )
    except KeyboardInterrupt:
        print("\n已退出")
        runner.stop()
