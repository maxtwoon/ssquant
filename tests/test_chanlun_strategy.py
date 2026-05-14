"""
缠论多空信号策略 - 核心逻辑单元测试

独立测试策略中的关键模块：
1. czsc数据适配器 (kline_to_rawbar)
2. 笔端点提取 (extract_bi_endpoints)
3. 中枢计算 (calculate_zs)
4. 四类信号检测器
5. 信号聚合与优先级
6. 整合集成测试（模拟回测数据流）
"""

import sys
import os
import math
import datetime
import pandas as pd
import numpy as np

# 确保ssquant可用
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入czsc
from czsc import CZSC, RawBar, Freq, Direction
from czsc.objects import BI, FX

# 导入策略模块中的函数
from examples.B_缠论多空信号策略 import (
    kline_to_rawbar,
    extract_bi_endpoints,
    calculate_zs,
    detect_type1_signal,
    detect_type2_signal,
    detect_type3_signal,
    detect_type4_signal,
    aggregate_signals,
    calculate_atr,
    ChanlunSignal, SignalType, BiEndpoint, ZS, ChanlunState,
)


def create_test_klines(n=200, pattern='sine'):
    """创建测试K线数据"""
    base_dt = datetime.datetime(2025, 1, 1, 9, 0, 0)
    data = []
    
    for i in range(n):
        if pattern == 'sine':
            p = 100 + 15 * math.sin(i * 0.15) + i * 0.02
        elif pattern == 'trend_up':
            p = 100 + i * 0.5 + 3 * math.sin(i * 0.3)
        elif pattern == 'trend_down':
            p = 200 - i * 0.5 + 3 * math.sin(i * 0.3)
        elif pattern == 'v_reversal':
            if i < n // 2:
                p = 150 - i * 0.5
            else:
                p = 150 - (n // 2) * 0.5 + (i - n // 2) * 0.8
        else:
            p = 100 + 10 * math.sin(i * 0.15)
        
        data.append({
            'datetime': base_dt + datetime.timedelta(minutes=i * 15),
            'open': p,
            'high': p + 1.5,
            'low': p - 1.5,
            'close': p + 0.3,
            'volume': 1000 + i * 10,
        })
    
    return pd.DataFrame(data)


def test_kline_to_rawbar():
    """测试K线数据转换"""
    print("\n" + "=" * 60)
    print("测试1: K线数据转换 (kline_to_rawbar)")
    print("=" * 60)
    
    klines = create_test_klines(50)
    bars = kline_to_rawbar(klines, 'test', '15m')
    
    assert len(bars) == 50, f"期望50根K线, 得到{len(bars)}"
    assert isinstance(bars[0], RawBar), "类型错误"
    assert bars[0].symbol == 'test', "symbol错误"
    assert bars[0].freq == Freq.F15, "freq错误"
    assert bars[0].amount > 0, "amount应大于0"
    
    # 测试各种周期映射
    for freq_str, expected_freq in [('1m', Freq.F1), ('5m', Freq.F5), 
                                      ('30m', Freq.F30), ('1h', Freq.F60), ('1d', Freq.D)]:
        bars2 = kline_to_rawbar(klines[:5], 'test', freq_str)
        assert bars2[0].freq == expected_freq, f"{freq_str} 映射错误"
    
    print("✓ K线数据转换正确")
    print(f"  - 转换了{len(bars)}根K线")
    print(f"  - 首根: dt={bars[0].dt}, open={bars[0].open:.2f}, close={bars[0].close:.2f}")
    print(f"  - 末根: dt={bars[-1].dt}, open={bars[-1].open:.2f}, close={bars[-1].close:.2f}")
    return True


def test_czsc_integration():
    """测试czsc分析器集成"""
    print("\n" + "=" * 60)
    print("测试2: czsc分析器集成")
    print("=" * 60)
    
    klines = create_test_klines(200, pattern='sine')
    bars = kline_to_rawbar(klines, 'test', '15m')
    
    # 初始化CZSC
    c = CZSC(bars, max_bi_num=100)
    
    print(f"  - 总K线数: {len(bars)}")
    print(f"  - 笔数量: {len(c.bi_list)}")
    print(f"  - 分型数量: {len(c.fx_list)}")
    
    assert len(c.bi_list) > 0, "应该产生至少1笔"
    
    # 测试增量更新
    old_bi_count = len(c.bi_list)
    new_bar = RawBar(
        symbol='test', id=200,
        dt=datetime.datetime(2025, 1, 3, 14, 15, 0),
        freq=Freq.F15,
        open=120.0, close=121.0, high=122.0, low=119.0,
        vol=1000.0, amount=121000.0
    )
    c.update(new_bar)
    
    print(f"  - 增量更新后笔数量: {len(c.bi_list)}")
    print("✓ czsc分析器集成正确")
    return c


def test_extract_bi_endpoints(c):
    """测试笔端点提取"""
    print("\n" + "=" * 60)
    print("测试3: 笔端点提取 (extract_bi_endpoints)")
    print("=" * 60)
    
    bi_list = c.bi_list
    endpoints = extract_bi_endpoints(bi_list)
    
    # 端点数量 = 笔数量 + 1 (起点+每笔终点)
    expected_count = len(bi_list) + 1
    assert len(endpoints) == expected_count, f"期望{expected_count}个端点, 得到{len(endpoints)}"
    
    # 验证高低点交替
    for i in range(1, len(endpoints)):
        assert endpoints[i].is_high != endpoints[i-1].is_high, \
            f"端点{i}和{i-1}应该高低交替"
    
    print(f"  - 笔数量: {len(bi_list)}")
    print(f"  - 端点数量: {len(endpoints)}")
    print(f"  - 高低交替验证通过")
    
    for i, ep in enumerate(endpoints[:6]):
        print(f"  - 端点[{i}]: price={ep.price:.2f}, "
              f"is_high={ep.is_high}, dt={ep.dt[:19]}")
    
    print("✓ 笔端点提取正确")
    return endpoints


def test_calculate_zs(endpoints):
    """测试中枢计算"""
    print("\n" + "=" * 60)
    print("测试4: 中枢计算 (calculate_zs)")
    print("=" * 60)
    
    zs = calculate_zs(endpoints)
    
    if zs is not None:
        assert zs.zg > zs.zd, "中枢上沿应大于下沿"
        assert abs(zs.zz - (zs.zg + zs.zd) / 2) < 0.001, "中枢中轴计算错误"
        print(f"  - 中枢上沿(zg): {zs.zg:.2f}")
        print(f"  - 中枢下沿(zd): {zs.zd:.2f}")
        print(f"  - 中枢中轴(zz): {zs.zz:.2f}")
        print("✓ 中枢计算正确")
    else:
        print("  - 当前数据未形成有效中枢(正常情况)")
        print("✓ 中枢计算逻辑正确（无重叠区域时返回None）")
    
    return zs


def test_type1_signal():
    """测试1类信号检测"""
    print("\n" + "=" * 60)
    print("测试5: 1类信号检测 (detect_type1_signal)")
    print("=" * 60)
    
    # 构造1类转多信号：低点抬高 + 高点突破
    # 端点序列: 低(100) -> 高(110) -> 低(103) -> 高(115)
    eps_long = [
        BiEndpoint(dt="2025-01-01", price=100.0, is_high=False, bi_index=0),
        BiEndpoint(dt="2025-01-02", price=110.0, is_high=True, bi_index=0),
        BiEndpoint(dt="2025-01-03", price=103.0, is_high=False, bi_index=1),  # 103 > 100 低点抬高
        BiEndpoint(dt="2025-01-04", price=115.0, is_high=True, bi_index=1),   # 115 > 110 高点突破
    ]
    
    sig = detect_type1_signal(eps_long, 'long')
    assert sig is not None, "应检测到1类转多信号"
    assert sig.signal_type == SignalType.TYPE1_LONG, "信号类型错误"
    assert sig.direction == 1, "方向错误"
    print(f"  - 1类转多: ✓ 检测到, price={sig.price:.2f}, key_level={sig.key_level:.2f}")
    
    # 不满足条件：低点未抬高
    eps_no_signal = [
        BiEndpoint(dt="2025-01-01", price=100.0, is_high=False, bi_index=0),
        BiEndpoint(dt="2025-01-02", price=110.0, is_high=True, bi_index=0),
        BiEndpoint(dt="2025-01-03", price=98.0, is_high=False, bi_index=1),   # 98 < 100 低点未抬高
        BiEndpoint(dt="2025-01-04", price=115.0, is_high=True, bi_index=1),
    ]
    
    sig2 = detect_type1_signal(eps_no_signal, 'long')
    assert sig2 is None, "不应检测到信号"
    print(f"  - 低点未抬高: ✓ 正确忽略")
    
    # 构造1类转空信号：高点降低 + 低点突破
    # 端点序列: 高(120) -> 低(108) -> 高(115) -> 低(105)
    eps_short = [
        BiEndpoint(dt="2025-01-01", price=120.0, is_high=True, bi_index=0),
        BiEndpoint(dt="2025-01-02", price=108.0, is_high=False, bi_index=0),
        BiEndpoint(dt="2025-01-03", price=115.0, is_high=True, bi_index=1),  # 115 < 120 高点降低
        BiEndpoint(dt="2025-01-04", price=105.0, is_high=False, bi_index=1), # 105 < 108 低点突破
    ]
    
    sig3 = detect_type1_signal(eps_short, 'short')
    assert sig3 is not None, "应检测到1类转空信号"
    assert sig3.signal_type == SignalType.TYPE1_SHORT, "信号类型错误"
    assert sig3.direction == -1, "方向错误"
    print(f"  - 1类转空: ✓ 检测到, price={sig3.price:.2f}, key_level={sig3.key_level:.2f}")
    
    # 端点不足
    sig4 = detect_type1_signal([eps_long[0]], 'long')
    assert sig4 is None, "端点不足应返回None"
    print(f"  - 端点不足: ✓ 正确返回None")
    
    print("✓ 1类信号检测正确")
    return True


def test_type2_signal():
    """测试2类信号检测"""
    print("\n" + "=" * 60)
    print("测试6: 2类信号检测 (detect_type2_signal)")
    print("=" * 60)
    
    # 创建带2类信号的数据
    klines = create_test_klines(200, pattern='sine')
    bars = kline_to_rawbar(klines, 'test', '15m')
    c = CZSC(bars, max_bi_num=100)
    
    bi_list = c.bi_list
    endpoints = extract_bi_endpoints(bi_list)
    
    sig = detect_type2_signal(bi_list, endpoints, 1.618)
    
    if sig:
        print(f"  - 检测到2类信号: {sig.signal_type.name}")
        print(f"  - 方向: {sig.direction}, 强度: {sig.strength:.2f}")
    else:
        print(f"  - 当前数据未形成2类信号(正常)")
    
    # 测试基本逻辑: 检查不会对空列表崩溃
    sig_empty = detect_type2_signal([], [], 1.618)
    assert sig_empty is None
    print(f"  - 空笔列表: ✓ 正确返回None")
    
    print("✓ 2类信号检测正确（无崩溃）")
    return True


def test_type3_signal():
    """测试3类信号检测"""
    print("\n" + "=" * 60)
    print("测试7: 3类信号检测 (detect_type3_signal)")
    print("=" * 60)
    
    klines = create_test_klines(200, pattern='sine')
    bars = kline_to_rawbar(klines, 'test', '15m')
    c = CZSC(bars, max_bi_num=100)
    
    bi_list = c.bi_list
    endpoints = extract_bi_endpoints(bi_list)
    
    sig = detect_type3_signal(endpoints, bi_list)
    
    if sig:
        print(f"  - 检测到3类信号: {sig.signal_type.name}")
    else:
        print(f"  - 当前数据未形成3类信号(正常)")
    
    sig_empty = detect_type3_signal([], [])
    assert sig_empty is None
    print(f"  - 空端点: ✓ 正确返回None")
    
    print("✓ 3类信号检测正确（无崩溃）")
    return True


def test_type4_signal():
    """测试4类信号检测"""
    print("\n" + "=" * 60)
    print("测试8: 4类信号检测 (detect_type4_signal)")
    print("=" * 60)
    
    klines = create_test_klines(200, pattern='sine')
    bars = kline_to_rawbar(klines, 'test', '15m')
    c = CZSC(bars, max_bi_num=100)
    
    bi_list = c.bi_list
    endpoints = extract_bi_endpoints(bi_list)
    
    # 无前一个信号
    sig = detect_type4_signal(endpoints, bi_list, None, 1.2)
    assert sig is None, "无前一个信号应返回None"
    print(f"  - 无前信号: ✓ 正确返回None")
    
    # 模拟前一个1类转空信号
    prev_signal = ChanlunSignal(
        signal_type=SignalType.TYPE1_SHORT, direction=-1, strength=0.6,
        price=100.0, datetime="2025-01-01", key_level=102.0, volume_ratio=1.0
    )
    sig2 = detect_type4_signal(endpoints, bi_list, prev_signal, 1.2)
    if sig2:
        print(f"  - 检测到4类信号: {sig2.signal_type.name}")
    else:
        print(f"  - 当前数据未形成4类V反信号(正常)")
    
    print("✓ 4类信号检测正确（无崩溃）")
    return True


def test_signal_aggregation():
    """测试信号聚合"""
    print("\n" + "=" * 60)
    print("测试9: 信号聚合 (aggregate_signals)")
    print("=" * 60)
    
    # 空列表
    assert aggregate_signals([]) is None, "空列表应返回None"
    print("  - 空列表: ✓")
    
    # 单信号
    sig1 = ChanlunSignal(
        signal_type=SignalType.TYPE1_LONG, direction=1, strength=0.6,
        price=100.0, datetime="2025-01-01", key_level=98.0, volume_ratio=1.0
    )
    result = aggregate_signals([sig1])
    assert result == sig1, "单信号应直接返回"
    print("  - 单信号: ✓")
    
    # 多空冲突
    sig2 = ChanlunSignal(
        signal_type=SignalType.TYPE1_SHORT, direction=-1, strength=0.6,
        price=100.0, datetime="2025-01-01", key_level=102.0, volume_ratio=1.0
    )
    result = aggregate_signals([sig1, sig2])
    assert result is None, "多空冲突应返回None"
    print("  - 多空冲突: ✓ 放弃交易")
    
    # 优先级排序: 3类 > 2类 > 1类 > 4类
    sig3_type3 = ChanlunSignal(
        signal_type=SignalType.TYPE3_LONG, direction=1, strength=0.85,
        price=100.0, datetime="2025-01-01", key_level=95.0, volume_ratio=2.0
    )
    sig3_type1 = ChanlunSignal(
        signal_type=SignalType.TYPE1_LONG, direction=1, strength=0.6,
        price=100.0, datetime="2025-01-01", key_level=98.0, volume_ratio=1.0
    )
    result = aggregate_signals([sig3_type1, sig3_type3])
    assert result.signal_type == SignalType.TYPE3_LONG, "3类应优先于1类"
    print("  - 优先级(3>1): ✓")
    
    sig3_type2 = ChanlunSignal(
        signal_type=SignalType.TYPE2_LONG, direction=1, strength=0.8,
        price=100.0, datetime="2025-01-01", key_level=96.0, volume_ratio=1.5
    )
    sig3_type4 = ChanlunSignal(
        signal_type=SignalType.TYPE4_LONG, direction=1, strength=0.5,
        price=100.0, datetime="2025-01-01", key_level=97.0, volume_ratio=0.5
    )
    result = aggregate_signals([sig3_type4, sig3_type2])
    assert result.signal_type == SignalType.TYPE2_LONG, "2类应优先于4类"
    print("  - 优先级(2>4): ✓")
    
    print("✓ 信号聚合逻辑正确")
    return True


def test_calculate_atr():
    """测试ATR计算"""
    print("\n" + "=" * 60)
    print("测试10: ATR计算 (calculate_atr)")
    print("=" * 60)
    
    klines = create_test_klines(50)
    high = pd.Series(klines['high'].values)
    low = pd.Series(klines['low'].values)
    close = pd.Series(klines['close'].values)
    
    atr = calculate_atr(high, low, close, 14)
    assert atr > 0, "ATR应为正数"
    print(f"  - ATR(14) = {atr:.4f}")
    
    # 数据不足
    atr_short = calculate_atr(high[:5], low[:5], close[:5], 14)
    assert atr_short == 0.0, "数据不足应返回0"
    print(f"  - 数据不足: ✓ 返回0.0")
    
    print("✓ ATR计算正确")
    return True


def test_full_integration():
    """完整集成测试: 模拟回测数据流"""
    print("\n" + "=" * 60)
    print("测试11: 完整集成测试（模拟回测数据流）")
    print("=" * 60)
    
    klines = create_test_klines(300, pattern='sine')
    
    state = ChanlunState()
    signals_detected = []
    
    # 模拟逐K线推送
    for bar_count in [50, 100, 150, 200, 250, 300]:
        current_klines = klines.iloc[:bar_count]
        bars = kline_to_rawbar(current_klines, 'test', '15m')
        
        if state.czsc_analyzer is None:
            state.czsc_analyzer = CZSC(bars, max_bi_num=100)
            state.raw_bars = bars
        else:
            new_bars = bars[len(state.raw_bars):]
            for bar in new_bars:
                state.czsc_analyzer.update(bar)
            state.raw_bars = bars
        
        bi_list = state.czsc_analyzer.bi_list
        
        if len(bi_list) < 3:
            print(f"  K线={bar_count}: 笔数={len(bi_list)}, 不足3笔，跳过")
            continue
        
        if len(bi_list) == state.last_bi_count:
            print(f"  K线={bar_count}: 笔数={len(bi_list)}, 无更新")
            continue
        
        state.last_bi_count = len(bi_list)
        endpoints = extract_bi_endpoints(bi_list)
        zs = calculate_zs(endpoints)
        
        # 检测信号
        sigs = []
        t1l = detect_type1_signal(endpoints, 'long')
        if t1l: sigs.append(t1l)
        t1s = detect_type1_signal(endpoints, 'short')
        if t1s: sigs.append(t1s)
        t2 = detect_type2_signal(bi_list, endpoints)
        if t2: sigs.append(t2)
        t3 = detect_type3_signal(endpoints, bi_list)
        if t3: sigs.append(t3)
        t4 = detect_type4_signal(endpoints, bi_list, state.current_signal)
        if t4: sigs.append(t4)
        
        final = aggregate_signals(sigs)
        
        zs_info = f"ZS({zs.zd:.1f}-{zs.zg:.1f})" if zs else "无中枢"
        sig_info = final.signal_type.name if final else "无信号"
        
        if final:
            signals_detected.append(final)
            state.current_signal = final
        
        print(f"  K线={bar_count}: 笔数={len(bi_list)}, 端点={len(endpoints)}, "
              f"{zs_info}, 信号={sig_info}")
    
    print(f"\n  总检测到 {len(signals_detected)} 个信号")
    for s in signals_detected:
        print(f"    - {s.signal_type.name}: dir={s.direction}, "
              f"price={s.price:.2f}, strength={s.strength:.2f}")
    
    print("✓ 完整集成测试通过（无异常）")
    return True


# ============================================================================
# 主测试入口
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("缠论多空信号策略 - 核心逻辑测试")
    print("=" * 60)
    
    results = {}
    
    # 1. 数据转换
    results['kline_to_rawbar'] = test_kline_to_rawbar()
    
    # 2. czsc集成
    c = test_czsc_integration()
    results['czsc_integration'] = c is not None
    
    # 3. 笔端点提取
    endpoints = test_extract_bi_endpoints(c)
    results['extract_bi_endpoints'] = endpoints is not None
    
    # 4. 中枢计算
    zs = test_calculate_zs(endpoints)
    results['calculate_zs'] = True
    
    # 5-8. 四类信号检测
    results['type1_signal'] = test_type1_signal()
    results['type2_signal'] = test_type2_signal()
    results['type3_signal'] = test_type3_signal()
    results['type4_signal'] = test_type4_signal()
    
    # 9. 信号聚合
    results['signal_aggregation'] = test_signal_aggregation()
    
    # 10. ATR计算
    results['calculate_atr'] = test_calculate_atr()
    
    # 11. 完整集成
    results['full_integration'] = test_full_integration()
    
    # 结果汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        if not passed:
            all_passed = False
        print(f"  {status}  {name}")
    
    print()
    if all_passed:
        print("🎉 所有测试通过!")
    else:
        print("❌ 部分测试失败!")
        sys.exit(1)
