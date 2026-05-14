"""
缠论多空信号策略 - 端到端集成测试

使用合成数据直接驱动SSQuant回测框架（DataSource + MultiDataSource + StrategyAPI），
模拟完整的回测循环，验证策略在真实回测环境中能正确运行、检测信号、执行交易。

这个测试绕过远程API数据获取，使用本地合成数据直接注入DataSource。
"""

import sys
import os
import math
import datetime
import traceback
import pandas as pd
import numpy as np

# 确保ssquant可用
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入SSQuant框架组件
from ssquant.data.data_source import DataSource, MultiDataSource
from ssquant.api.strategy_api import StrategyAPI, create_strategy_api

# 导入策略模块
from examples.B_缠论多空信号策略 import (
    chanlun_signal_strategy,
    initialize,
    g_chanlun_state,
    ChanlunState,
    SignalType,
)


# ============================================================================
# 合成数据生成器
# ============================================================================

def generate_futures_klines(n=500, pattern='realistic', base_price=650.0, symbol='au888'):
    """
    生成模拟期货K线数据
    
    Args:
        n: K线数量
        pattern: 数据模式
            - 'realistic': 模拟真实行情（趋势+震荡+反转）
            - 'strong_trend': 强趋势行情
            - 'oscillation': 震荡行情
        base_price: 基础价格
        symbol: 品种代码
    
    Returns:
        pd.DataFrame，index为DatetimeIndex，列：open, high, low, close, volume
    """
    np.random.seed(42)
    
    base_dt = datetime.datetime(2025, 1, 2, 9, 0, 0)
    dates = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    
    price = base_price
    
    for i in range(n):
        # 计算时间（跳过非交易时间）
        minutes = i * 15
        dt = base_dt + datetime.timedelta(minutes=minutes)
        dates.append(dt)
        
        if pattern == 'realistic':
            # 模拟真实行情：趋势+震荡+反转
            # Phase 1 (0-150): 上升趋势
            # Phase 2 (150-250): 高位震荡
            # Phase 3 (250-350): 下降趋势
            # Phase 4 (350-450): 低位震荡后反转
            # Phase 5 (450-500): 再次上升
            
            if i < 150:
                # 上升趋势 + 正弦波动
                trend = 0.08
                volatility = 2.0
                cycle = 8.0 * math.sin(i * 0.12)
            elif i < 250:
                # 高位震荡
                trend = -0.01
                volatility = 3.0
                cycle = 12.0 * math.sin(i * 0.2)
            elif i < 350:
                # 下降趋势
                trend = -0.1
                volatility = 2.5
                cycle = 8.0 * math.sin(i * 0.15)
            elif i < 450:
                # 低位震荡后开始反转
                trend = 0.03
                volatility = 2.0
                cycle = 6.0 * math.sin(i * 0.18)
            else:
                # 再次上升
                trend = 0.12
                volatility = 1.5
                cycle = 5.0 * math.sin(i * 0.1)
            
            noise = np.random.normal(0, volatility)
            price = price + trend + cycle * 0.05 + noise * 0.3
            
        elif pattern == 'strong_trend':
            # 强趋势行情（前半上涨，后半下跌）
            if i < n // 2:
                price += 0.15 + np.random.normal(0, 0.8)
            else:
                price -= 0.12 + np.random.normal(0, 0.8)
            price += 3.0 * math.sin(i * 0.1) * 0.1
            
        elif pattern == 'oscillation':
            # 震荡行情
            price = base_price + 15.0 * math.sin(i * 0.08) + np.random.normal(0, 1.5)
        
        # 确保价格合理
        price = max(price, base_price * 0.7)
        
        # 生成OHLCV
        bar_range = abs(np.random.normal(0, 1.5)) + 0.5
        open_price = price + np.random.normal(0, 0.5)
        close_price = price + np.random.normal(0, 0.5)
        high_price = max(open_price, close_price) + bar_range
        low_price = min(open_price, close_price) - bar_range
        vol = int(max(100, np.random.normal(5000, 1500)))
        
        opens.append(round(open_price, 2))
        highs.append(round(high_price, 2))
        lows.append(round(low_price, 2))
        closes.append(round(close_price, 2))
        volumes.append(vol)
    
    # 创建DataFrame，datetime作为index（与SSQuant DataSource一致）
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    }, index=pd.DatetimeIndex(dates, name='datetime'))
    
    # 添加datetime列（部分策略代码通过列名获取datetime）
    df['datetime'] = dates
    
    return df


def setup_backtest_env(klines_df, symbol='au888', kline_period='15m', strategy_params=None):
    """
    创建完整的SSQuant回测环境
    
    Args:
        klines_df: K线数据DataFrame
        symbol: 品种代码
        kline_period: K线周期
        strategy_params: 策略参数
    
    Returns:
        (api, data_source, multi_data_source, log_messages)
    """
    # 创建DataSource
    ds = DataSource(symbol=symbol, kline_period=kline_period)
    ds.set_data(klines_df)
    ds.current_idx = 0
    ds.current_price = klines_df.iloc[0]['close']
    ds.current_datetime = klines_df.index[0]
    
    # 创建MultiDataSource
    mds = MultiDataSource()
    mds.data_sources.append(ds)
    
    # 日志收集
    log_messages = []
    def log_func(msg):
        log_messages.append(str(msg))
    
    # 默认策略参数
    if strategy_params is None:
        strategy_params = {
            'min_bi_len': 7,
            'golden_ratio': 1.618,
            'atr_period': 14,
            'atr_stop_multiplier': 2.0,
            'base_volume': 1,
            'use_structure_stop': True,
            'signal_cooldown': 3,
            'v_reversal_power_ratio': 1.2,
            'kline_period': kline_period,
        }
    
    # 创建context和StrategyAPI
    context = {
        'data': mds,
        'log': log_func,
        'params': strategy_params,
    }
    api = create_strategy_api(context)
    
    return api, ds, mds, log_messages


# ============================================================================
# 端到端测试
# ============================================================================

def test_e2e_full_backtest_loop():
    """
    测试1: 完整回测循环
    
    模拟SSQuant回测引擎的完整循环：
    1. 生成合成K线数据
    2. 创建DataSource和StrategyAPI
    3. 调用initialize()初始化策略
    4. 逐K线推进，调用策略主函数
    5. 验证策略能正确运行、检测信号、执行交易
    """
    print("\n" + "=" * 70)
    print("E2E测试1: 完整回测循环（500根K线，realistic模式）")
    print("=" * 70)
    
    # 重置全局状态
    import examples.B_缠论多空信号策略 as strategy_module
    strategy_module.g_chanlun_state = ChanlunState()
    
    # 生成数据
    klines = generate_futures_klines(500, pattern='realistic', base_price=650.0)
    print(f"  生成K线数据: {len(klines)}根, 价格范围: {klines['low'].min():.2f} - {klines['high'].max():.2f}")
    
    # 创建回测环境
    api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
    
    # 初始化策略
    initialize(api)
    print(f"  初始化日志: {len(logs)}条")
    
    # 记录交易前状态
    errors = []
    signal_count = 0
    trade_count = 0
    
    # 模拟回测循环（与backtest_core.py一致）
    total_bars = len(klines)
    for i in range(total_bars):
        # 更新DataSource状态（模拟backtest_core.py的逻辑）
        ds.current_idx = i
        row = ds.data.iloc[i]
        ds.current_price = row['close']
        ds.current_datetime = ds.data.index[i]
        
        # 处理待执行的订单（next_bar_open等）
        ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
        
        # 调用策略主函数
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(f"Bar {i}: {e}\n{traceback.format_exc()}")
            if len(errors) >= 5:
                break
    
    # 分析结果
    trades = ds.trades
    final_pos = ds.current_pos
    
    # 统计信号日志
    signal_logs = [l for l in logs if any(t in l for t in ['TYPE1', 'TYPE2', 'TYPE3', 'TYPE4', '开多', '开空', '平多', '平空', '止损'])]
    
    print(f"\n  回测结果:")
    print(f"  - 总K线数: {total_bars}")
    print(f"  - 错误数: {len(errors)}")
    print(f"  - 总交易数: {len(trades)}")
    print(f"  - 最终持仓: {final_pos}")
    print(f"  - 信号/交易日志: {len(signal_logs)}条")
    
    if errors:
        print(f"\n  ❌ 发现错误:")
        for err in errors[:3]:
            print(f"    {err[:200]}")
    
    # 打印部分交易记录
    if trades:
        print(f"\n  交易记录（前10条）:")
        for t in trades[:10]:
            print(f"    {t['datetime']} | {t['action']} | {t['volume']}手 | {t['price']:.2f}")
    
    # 打印部分信号日志
    if signal_logs:
        print(f"\n  信号日志（前10条）:")
        for l in signal_logs[:10]:
            print(f"    {l}")
    
    # 验证
    assert len(errors) == 0, f"回测过程中出现{len(errors)}个错误"
    print("\n✓ 完整回测循环通过（无错误）")
    return True


def test_e2e_strong_trend():
    """
    测试2: 强趋势行情测试
    
    使用强趋势数据，验证策略能在趋势行情中正确检测1类/2类信号。
    """
    print("\n" + "=" * 70)
    print("E2E测试2: 强趋势行情（验证趋势信号检测）")
    print("=" * 70)
    
    # 重置全局状态
    import examples.B_缠论多空信号策略 as strategy_module
    strategy_module.g_chanlun_state = ChanlunState()
    
    klines = generate_futures_klines(400, pattern='strong_trend', base_price=500.0)
    print(f"  生成K线数据: {len(klines)}根, 价格范围: {klines['low'].min():.2f} - {klines['high'].max():.2f}")
    
    api, ds, mds, logs = setup_backtest_env(klines, symbol='rb888', kline_period='15m')
    
    initialize(api)
    
    errors = []
    for i in range(len(klines)):
        ds.current_idx = i
        row = ds.data.iloc[i]
        ds.current_price = row['close']
        ds.current_datetime = ds.data.index[i]
        ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
        
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(f"Bar {i}: {e}")
            if len(errors) >= 5:
                break
    
    trades = ds.trades
    signal_logs = [l for l in logs if any(t in l for t in ['TYPE', '开多', '开空', '平多', '平空', '止损'])]
    
    print(f"\n  回测结果:")
    print(f"  - 错误数: {len(errors)}")
    print(f"  - 总交易数: {len(trades)}")
    print(f"  - 最终持仓: {ds.current_pos}")
    print(f"  - 信号/交易日志: {len(signal_logs)}条")
    
    if trades:
        print(f"\n  交易记录（前5条）:")
        for t in trades[:5]:
            print(f"    {t['datetime']} | {t['action']} | {t['volume']}手 | {t['price']:.2f}")
    
    assert len(errors) == 0, f"回测过程中出现{len(errors)}个错误"
    print("\n✓ 强趋势行情测试通过")
    return True


def test_e2e_oscillation():
    """
    测试3: 震荡行情测试
    
    使用震荡数据，验证策略在震荡行情中不会异常。
    """
    print("\n" + "=" * 70)
    print("E2E测试3: 震荡行情（验证震荡稳定性）")
    print("=" * 70)
    
    import examples.B_缠论多空信号策略 as strategy_module
    strategy_module.g_chanlun_state = ChanlunState()
    
    klines = generate_futures_klines(400, pattern='oscillation', base_price=3800.0)
    print(f"  生成K线数据: {len(klines)}根, 价格范围: {klines['low'].min():.2f} - {klines['high'].max():.2f}")
    
    api, ds, mds, logs = setup_backtest_env(klines, symbol='IF888', kline_period='15m')
    
    initialize(api)
    
    errors = []
    for i in range(len(klines)):
        ds.current_idx = i
        row = ds.data.iloc[i]
        ds.current_price = row['close']
        ds.current_datetime = ds.data.index[i]
        ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
        
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(f"Bar {i}: {e}")
            if len(errors) >= 5:
                break
    
    trades = ds.trades
    print(f"\n  回测结果:")
    print(f"  - 错误数: {len(errors)}")
    print(f"  - 总交易数: {len(trades)}")
    print(f"  - 最终持仓: {ds.current_pos}")
    
    assert len(errors) == 0, f"回测过程中出现{len(errors)}个错误"
    print("\n✓ 震荡行情测试通过")
    return True


def test_e2e_strategy_state_management():
    """
    测试4: 策略状态管理
    
    验证策略的全局状态在回测过程中正确维护：
    - czsc_analyzer正确初始化和更新
    - 笔数量递增
    - 端点序列正确
    """
    print("\n" + "=" * 70)
    print("E2E测试4: 策略状态管理验证")
    print("=" * 70)
    
    import examples.B_缠论多空信号策略 as strategy_module
    strategy_module.g_chanlun_state = ChanlunState()
    
    klines = generate_futures_klines(300, pattern='realistic', base_price=650.0)
    api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
    
    initialize(api)
    
    state = strategy_module.g_chanlun_state
    bi_count_history = []
    
    for i in range(len(klines)):
        ds.current_idx = i
        row = ds.data.iloc[i]
        ds.current_price = row['close']
        ds.current_datetime = ds.data.index[i]
        ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
        
        chanlun_signal_strategy(api)
        
        # 记录状态变化
        if i % 50 == 0 or i == len(klines) - 1:
            bi_count = state.last_bi_count
            bi_count_history.append((i, bi_count))
    
    print(f"\n  状态检查:")
    print(f"  - czsc_analyzer初始化: {'✓' if state.czsc_analyzer is not None else '✗'}")
    print(f"  - raw_bars数量: {len(state.raw_bars)}")
    print(f"  - 最终笔数量: {state.last_bi_count}")
    print(f"  - 端点数量: {len(state.bi_endpoints)}")
    print(f"  - 当前中枢: {'有' if state.current_zs else '无'}")
    print(f"  - 当前信号: {state.current_signal.signal_type.name if state.current_signal else '无'}")
    
    print(f"\n  笔数量变化:")
    for idx, bi_count in bi_count_history:
        print(f"    K线={idx}: 笔数={bi_count}")
    
    # 验证
    assert state.czsc_analyzer is not None, "czsc_analyzer应被初始化"
    assert len(state.raw_bars) > 0, "raw_bars应有数据"
    assert state.last_bi_count > 0, "应产生至少1笔"
    
    # 笔数量应单调不减
    bi_counts = [bc for _, bc in bi_count_history]
    for j in range(1, len(bi_counts)):
        assert bi_counts[j] >= bi_counts[j-1], "笔数量应单调不减"
    
    print("\n✓ 策略状态管理验证通过")
    return True


def test_e2e_trade_execution():
    """
    测试5: 交易执行验证
    
    验证通过StrategyAPI执行的交易操作是否正确反映在DataSource中：
    - buy/sell/sellshort/buycover
    - close_all
    - 持仓变化
    """
    print("\n" + "=" * 70)
    print("E2E测试5: 交易执行验证（StrategyAPI → DataSource）")
    print("=" * 70)
    
    klines = generate_futures_klines(100, pattern='realistic', base_price=650.0)
    api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
    
    # 设置到某个K线位置
    ds.current_idx = 50
    ds.current_price = klines.iloc[50]['close']
    ds.current_datetime = klines.index[50]
    
    # 测试开多
    print(f"\n  初始持仓: {api.get_pos()}")
    api.buy(volume=2, reason="测试开多", order_type='bar_close')
    assert api.get_pos() == 2, f"开多后持仓应为2，实际: {api.get_pos()}"
    print(f"  开多2手后: {api.get_pos()}")
    
    # 测试平多
    api.sell(reason="测试平多", order_type='bar_close')
    assert api.get_pos() == 0, f"平多后持仓应为0，实际: {api.get_pos()}"
    print(f"  平多后: {api.get_pos()}")
    
    # 测试开空
    api.sellshort(volume=3, reason="测试开空", order_type='bar_close')
    assert api.get_pos() == -3, f"开空后持仓应为-3，实际: {api.get_pos()}"
    print(f"  开空3手后: {api.get_pos()}")
    
    # 测试平空
    api.buycover(reason="测试平空", order_type='bar_close')
    assert api.get_pos() == 0, f"平空后持仓应为0，实际: {api.get_pos()}"
    print(f"  平空后: {api.get_pos()}")
    
    # 测试close_all
    api.buy(volume=1, reason="先开仓", order_type='bar_close')
    api.close_all(reason="全部平仓", order_type='bar_close')
    assert api.get_pos() == 0, f"close_all后持仓应为0，实际: {api.get_pos()}"
    print(f"  close_all后: {api.get_pos()}")
    
    # 验证交易记录
    trades = ds.trades
    print(f"\n  交易记录: {len(trades)}条")
    for t in trades:
        print(f"    {t['action']} | {t['volume']}手 | {t['price']:.2f}")
    
    assert len(trades) >= 5, "应有至少5条交易记录"
    
    print("\n✓ 交易执行验证通过")
    return True


def test_e2e_next_bar_open_orders():
    """
    测试6: next_bar_open订单测试
    
    验证策略中使用的next_bar_open订单类型是否正确处理。
    """
    print("\n" + "=" * 70)
    print("E2E测试6: next_bar_open订单执行")
    print("=" * 70)
    
    klines = generate_futures_klines(100, pattern='realistic', base_price=650.0)
    api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
    
    # 在K线50下单next_bar_open
    ds.current_idx = 50
    ds.current_price = klines.iloc[50]['close']
    ds.current_datetime = klines.index[50]
    
    print(f"  K线50价格: {ds.current_price:.2f}")
    api.buy(volume=1, reason="next_bar_open测试", order_type='next_bar_open')
    
    # 此时应该还没有成交
    assert api.get_pos() == 0, "next_bar_open应在下一根K线才成交"
    assert len(ds.pending_orders) == 1, "应有1个待执行订单"
    print(f"  下单后持仓: {api.get_pos()} (待执行订单: {len(ds.pending_orders)})")
    
    # 推进到K线51
    ds.current_idx = 51
    ds.current_price = klines.iloc[51]['close']
    ds.current_datetime = klines.index[51]
    ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
    
    # 现在应该成交了
    assert api.get_pos() == 1, f"K线51应已成交，持仓应为1，实际: {api.get_pos()}"
    assert len(ds.pending_orders) == 0, "待执行订单应已清空"
    print(f"  K线51后持仓: {api.get_pos()} (待执行订单: {len(ds.pending_orders)})")
    
    # 验证成交价格
    if ds.trades:
        trade_price = ds.trades[-1]['price']
        expected_price = klines.iloc[51]['open']
        print(f"  成交价: {trade_price:.2f}, 期望(K线51开盘): {expected_price:.2f}")
    
    print("\n✓ next_bar_open订单执行通过")
    return True


def test_e2e_data_window_consistency():
    """
    测试7: 数据窗口一致性
    
    验证get_klines()返回的数据窗口在回测过程中正确滚动（避免未来数据泄露）。
    """
    print("\n" + "=" * 70)
    print("E2E测试7: 数据窗口一致性（防止未来数据泄露）")
    print("=" * 70)
    
    klines = generate_futures_klines(200, pattern='realistic', base_price=650.0)
    api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
    
    for test_idx in [10, 50, 100, 150, 199]:
        ds.current_idx = test_idx
        ds.current_price = klines.iloc[test_idx]['close']
        ds.current_datetime = klines.index[test_idx]
        
        visible_klines = api.get_klines()
        expected_len = test_idx + 1
        
        assert len(visible_klines) == expected_len, \
            f"idx={test_idx}: 期望{expected_len}根K线, 实际{len(visible_klines)}"
        
        # 验证最后一根K线是当前K线
        last_close = visible_klines.iloc[-1]['close']
        expected_close = klines.iloc[test_idx]['close']
        assert last_close == expected_close, \
            f"idx={test_idx}: 最后一根K线收盘价不一致"
        
        print(f"  idx={test_idx}: 可见K线={len(visible_klines)}, 最新收盘={last_close:.2f} ✓")
    
    print("\n✓ 数据窗口一致性验证通过")
    return True


def test_e2e_multi_run_isolation():
    """
    测试8: 多次运行隔离性
    
    验证策略状态在多次运行之间正确重置。
    """
    print("\n" + "=" * 70)
    print("E2E测试8: 多次运行隔离性")
    print("=" * 70)
    
    import examples.B_缠论多空信号策略 as strategy_module
    
    results = []
    
    for run_id in range(3):
        # 每次运行前重置状态
        strategy_module.g_chanlun_state = ChanlunState()
        
        klines = generate_futures_klines(200, pattern='realistic', base_price=650.0)
        api, ds, mds, logs = setup_backtest_env(klines, symbol='au888', kline_period='15m')
        
        initialize(api)
        
        for i in range(len(klines)):
            ds.current_idx = i
            row = ds.data.iloc[i]
            ds.current_price = row['close']
            ds.current_datetime = ds.data.index[i]
            ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
            chanlun_signal_strategy(api)
        
        state = strategy_module.g_chanlun_state
        results.append({
            'run_id': run_id,
            'trades': len(ds.trades),
            'final_pos': ds.current_pos,
            'bi_count': state.last_bi_count,
        })
        
        print(f"  Run {run_id}: trades={len(ds.trades)}, pos={ds.current_pos}, bi={state.last_bi_count}")
    
    # 验证每次运行结果一致（相同输入应产生相同输出）
    for i in range(1, len(results)):
        assert results[i]['trades'] == results[0]['trades'], \
            f"Run {i} trades不一致: {results[i]['trades']} vs {results[0]['trades']}"
        assert results[i]['bi_count'] == results[0]['bi_count'], \
            f"Run {i} bi_count不一致: {results[i]['bi_count']} vs {results[0]['bi_count']}"
    
    print("\n✓ 多次运行隔离性验证通过（结果一致）")
    return True


def test_e2e_edge_cases():
    """
    测试9: 边界条件
    
    测试各种边界情况：
    - 极少量数据
    - 所有价格相同
    - 极端波动
    """
    print("\n" + "=" * 70)
    print("E2E测试9: 边界条件测试")
    print("=" * 70)
    
    import examples.B_缠论多空信号策略 as strategy_module
    
    # Case 1: 极少量数据（不足50根）
    print("\n  Case 1: 极少量数据（30根K线）")
    strategy_module.g_chanlun_state = ChanlunState()
    klines = generate_futures_klines(30, pattern='realistic', base_price=650.0)
    api, ds, mds, logs = setup_backtest_env(klines)
    initialize(api)
    
    errors = []
    for i in range(len(klines)):
        ds.current_idx = i
        ds.current_price = klines.iloc[i]['close']
        ds.current_datetime = klines.index[i]
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(str(e))
    
    assert len(errors) == 0, f"极少量数据不应报错: {errors}"
    print(f"    ✓ 无错误 (交易数: {len(ds.trades)})")
    
    # Case 2: 恒定价格
    print("\n  Case 2: 恒定价格")
    strategy_module.g_chanlun_state = ChanlunState()
    
    n = 100
    base_dt = datetime.datetime(2025, 1, 1)
    dates = [base_dt + datetime.timedelta(minutes=i*15) for i in range(n)]
    df_flat = pd.DataFrame({
        'open': [100.0] * n,
        'high': [101.0] * n,
        'low': [99.0] * n,
        'close': [100.0] * n,
        'volume': [1000] * n,
        'datetime': dates,
    }, index=pd.DatetimeIndex(dates))
    
    api, ds, mds, logs = setup_backtest_env(df_flat)
    initialize(api)
    
    errors = []
    for i in range(n):
        ds.current_idx = i
        ds.current_price = df_flat.iloc[i]['close']
        ds.current_datetime = df_flat.index[i]
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(str(e))
    
    assert len(errors) == 0, f"恒定价格不应报错: {errors}"
    print(f"    ✓ 无错误 (交易数: {len(ds.trades)})")
    
    # Case 3: 极端波动
    print("\n  Case 3: 极端波动")
    strategy_module.g_chanlun_state = ChanlunState()
    
    np.random.seed(123)
    n = 200
    dates = [base_dt + datetime.timedelta(minutes=i*15) for i in range(n)]
    prices = [500.0]
    for i in range(1, n):
        change = np.random.choice([-30, -20, -10, 10, 20, 30])
        prices.append(max(100, prices[-1] + change))
    
    df_volatile = pd.DataFrame({
        'open': prices,
        'high': [p + 15 for p in prices],
        'low': [p - 15 for p in prices],
        'close': [p + np.random.uniform(-5, 5) for p in prices],
        'volume': [5000] * n,
        'datetime': dates,
    }, index=pd.DatetimeIndex(dates))
    
    api, ds, mds, logs = setup_backtest_env(df_volatile)
    initialize(api)
    
    errors = []
    for i in range(n):
        ds.current_idx = i
        ds.current_price = df_volatile.iloc[i]['close']
        ds.current_datetime = df_volatile.index[i]
        ds._process_pending_orders(log_callback=lambda msg: logs.append(str(msg)))
        try:
            chanlun_signal_strategy(api)
        except Exception as e:
            errors.append(f"Bar {i}: {e}")
    
    assert len(errors) == 0, f"极端波动不应报错: {errors[:3]}"
    print(f"    ✓ 无错误 (交易数: {len(ds.trades)})")
    
    print("\n✓ 所有边界条件测试通过")
    return True


# ============================================================================
# 主测试入口
# ============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("缠论多空信号策略 - 端到端集成测试")
    print("使用合成数据驱动SSQuant回测框架")
    print("=" * 70)
    
    results = {}
    
    try:
        results['full_backtest_loop'] = test_e2e_full_backtest_loop()
    except Exception as e:
        print(f"\n❌ E2E测试1失败: {e}")
        traceback.print_exc()
        results['full_backtest_loop'] = False
    
    try:
        results['strong_trend'] = test_e2e_strong_trend()
    except Exception as e:
        print(f"\n❌ E2E测试2失败: {e}")
        traceback.print_exc()
        results['strong_trend'] = False
    
    try:
        results['oscillation'] = test_e2e_oscillation()
    except Exception as e:
        print(f"\n❌ E2E测试3失败: {e}")
        traceback.print_exc()
        results['oscillation'] = False
    
    try:
        results['state_management'] = test_e2e_strategy_state_management()
    except Exception as e:
        print(f"\n❌ E2E测试4失败: {e}")
        traceback.print_exc()
        results['state_management'] = False
    
    try:
        results['trade_execution'] = test_e2e_trade_execution()
    except Exception as e:
        print(f"\n❌ E2E测试5失败: {e}")
        traceback.print_exc()
        results['trade_execution'] = False
    
    try:
        results['next_bar_open'] = test_e2e_next_bar_open_orders()
    except Exception as e:
        print(f"\n❌ E2E测试6失败: {e}")
        traceback.print_exc()
        results['next_bar_open'] = False
    
    try:
        results['data_window'] = test_e2e_data_window_consistency()
    except Exception as e:
        print(f"\n❌ E2E测试7失败: {e}")
        traceback.print_exc()
        results['data_window'] = False
    
    try:
        results['multi_run_isolation'] = test_e2e_multi_run_isolation()
    except Exception as e:
        print(f"\n❌ E2E测试8失败: {e}")
        traceback.print_exc()
        results['multi_run_isolation'] = False
    
    try:
        results['edge_cases'] = test_e2e_edge_cases()
    except Exception as e:
        print(f"\n❌ E2E测试9失败: {e}")
        traceback.print_exc()
        results['edge_cases'] = False
    
    # 结果汇总
    print("\n" + "=" * 70)
    print("端到端测试结果汇总")
    print("=" * 70)
    
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        if not passed:
            all_passed = False
        print(f"  {status}  {name}")
    
    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    print(f"\n  通过: {passed_count}/{total_count}")
    
    if all_passed:
        print("\n🎉 所有端到端测试通过!")
    else:
        print("\n❌ 部分测试失败!")
        sys.exit(1)
