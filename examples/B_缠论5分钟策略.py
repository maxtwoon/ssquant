"""
缠论多空信号四种形态交易策略 - 5分钟周期版本

基于 examples/B_缠论多空信号策略.py 改造而来，针对 5 分钟周期做了:
1. 全部 P0 bug 修复（见 docs/code-review-缠论多空信号策略.md）
   - 显式 import os
   - 主程序块下沉到 if __name__ == "__main__":
   - detect_type1_signal 按时间顺序两两配对
   - extract_bi_endpoints 首端点 bi_index=-1
   - kline_to_rawbar 增量化
   - entry_price 使用下一根 open 而非当前 close
   - api.sell()/api.buycover() 显式传 volume
   - freq_map 未知值改为 raise
   - 全文 "缩论"→"缠论"，"绻"→"绿"
   - min_bi_len 接到 czsc 的 max_bi_num
2. 5 分钟周期参数调整
   - min_bi_len: 5（原 7）
   - signal_cooldown: 6（原 3，约 30 分钟）
   - atr_stop_multiplier: 2.5（原 2.0）
   - v_reversal_power_ratio: 1.3（原 1.2）
3. 数据源直接接 SQLite
   - file_path = data_cache/kline_data.db
   - 表名按项目约定 {symbol}_{period}_{adjust} 自动推导

依赖: czsc>=0.9.51
运行: python examples/B_缠论5分钟策略.py
"""

import os
import json
import csv as _csv_module
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime as _dt_cls

import pandas as pd
import numpy as np

# 可视化相关导入
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D as _Line2D
import platform as _plt_platform

# 中文字体配置
_plt_sys = _plt_platform.system()
if _plt_sys == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
elif _plt_sys == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.family'] = 'sans-serif'

# 导入 SSQuant 必要模块
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# 尝试导入 czsc
try:
    from czsc import CZSC, RawBar, Freq, Direction
    from czsc.objects import BI, FX
    CZSC_AVAILABLE = True
except ImportError:
    CZSC_AVAILABLE = False
    print("警告: czsc 库未安装，请运行: pip install czsc==0.9.51")


# ============================================================================
# 枚举与数据类
# ============================================================================

class SignalType(Enum):
    """信号类型枚举"""
    NONE = 0
    TYPE1_LONG = 1
    TYPE1_SHORT = 2
    TYPE2_LONG = 3
    TYPE2_SHORT = 4
    TYPE3_LONG = 5
    TYPE3_SHORT = 6
    TYPE4_LONG = 7
    TYPE4_SHORT = 8


@dataclass
class ChanlunSignal:
    """缠论信号"""
    signal_type: SignalType
    direction: int          # 1 做多, -1 做空
    strength: float         # 强度 0-1
    price: float            # 触发价
    datetime: str
    key_level: float        # 止损参考价位
    volume_ratio: float     # 仓位倍率


@dataclass
class BiEndpoint:
    """笔端点"""
    dt: str
    price: float
    is_high: bool
    bi_index: int   # -1 表示是首笔的起点（不属于任何笔的"终点"）


@dataclass
class ZS:
    """中枢"""
    zg: float
    zd: float
    zz: float
    start_dt: str
    end_dt: str


# ============================================================================
# 状态管理（单线程回测，封装到一个对象）
# ============================================================================

class ChanlunState:
    """缠论分析全局状态"""

    def __init__(self):
        # 用字符串型注解避免 czsc 未安装时 NameError
        self.czsc_analyzer: 'Optional[CZSC]' = None
        self.cached_raw_bars: List[Any] = []  # 已转换为 RawBar 的缓存
        self.last_bi_count: int = 0
        self.last_signal_bar: int = 0
        self.entry_price: float = 0.0
        self.pending_entry: Optional[Dict[str, Any]] = None  # 等待确认成交的入场记录
        self.current_signal: Optional[ChanlunSignal] = None
        self.bi_endpoints: List[BiEndpoint] = []
        self.current_zs: Optional[ZS] = None
        # 缠论"买卖点不超买"原则 — 同一段走势内同级别交易计数
        self.current_trend_direction: int = 0   # 1=多趋势, -1=空趋势, 0=未定
        self.trades_in_current_trend: int = 0   # 当前趋势内已执行的交易次数
        self.last_zs_signature: Optional[tuple] = None  # 上一次中枢的标识，用于检测中枢更迭
        # 强制平仓保险 — 防止"开了仓忘记平"
        self.entry_bar_idx: Optional[int] = None  # 实际成交那根 K 线的索引

    def reset(self):
        self.__init__()


# 单实例（回测单线程使用）
g_chanlun_state = ChanlunState()
g_signals_history: List[Dict[str, Any]] = []
g_klines_snapshot: Optional[pd.DataFrame] = None
g_zs_history: List[ZS] = []


# ============================================================================
# 数据转换
# ============================================================================

# 周期字符串到 czsc Freq 的严格映射
_FREQ_MAP = {
    '1m': 'F1', '5m': 'F5', '15m': 'F15',
    '30m': 'F30', '1h': 'F60', '4h': 'F120',
    '1d': 'D', 'D': 'D',
}


def _resolve_freq(freq: str):
    """把字符串周期解析为 czsc Freq 枚举，未知值 raise"""
    if not CZSC_AVAILABLE:
        return None
    if freq not in _FREQ_MAP:
        raise ValueError(
            f"不支持的 K 线周期 '{freq}'，可选: {sorted(_FREQ_MAP.keys())}"
        )
    return getattr(Freq, _FREQ_MAP[freq])


def kline_to_rawbar_incremental(klines: pd.DataFrame, symbol: str, freq: str,
                                cached_count: int) -> List[Any]:
    """
    增量式 K 线转换 — 只把新增的 K 线转为 RawBar 返回。

    cached_count 是已经转换并 update 过的 bar 数量，本次只返回 [cached_count:] 的新 bar。
    """
    if not CZSC_AVAILABLE:
        return []
    if len(klines) <= cached_count:
        return []

    czsc_freq = _resolve_freq(freq)
    new_bars = []
    new_slice = klines.iloc[cached_count:]
    for i, row in new_slice.iterrows():
        dt_val = row['datetime'] if 'datetime' in klines.columns else row.name
        if isinstance(dt_val, str):
            dt_val = pd.Timestamp(dt_val)
        vol = float(row['volume']) if 'volume' in klines.columns else 0.0
        bar = RawBar(
            symbol=symbol,
            id=cached_count + len(new_bars),
            dt=dt_val,
            freq=czsc_freq,
            open=float(row['open']),
            close=float(row['close']),
            high=float(row['high']),
            low=float(row['low']),
            vol=vol,
            amount=vol * float(row['close']),
        )
        new_bars.append(bar)
    return new_bars


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.iloc[-1] if len(atr) > 0 and not pd.isna(atr.iloc[-1]) else 0.0


# ============================================================================
# 端点 / 中枢推导
# ============================================================================

def extract_bi_endpoints(bi_list: List[Any]) -> List[BiEndpoint]:
    """
    从笔序列提取按时间排序的端点序列。
    首端点（首笔起点）的 bi_index = -1，区分于其他端点（值为对应笔的下标）。
    """
    if not bi_list:
        return []

    endpoints: List[BiEndpoint] = []
    first_bi = bi_list[0]
    is_first_start_high = (first_bi.direction == Direction.Down)
    endpoints.append(BiEndpoint(
        dt=str(first_bi.fx_a.dt),
        price=float(first_bi.fx_a.fx),
        is_high=is_first_start_high,
        bi_index=-1,
    ))

    for i, bi in enumerate(bi_list):
        is_end_high = (bi.direction == Direction.Up)
        endpoints.append(BiEndpoint(
            dt=str(bi.fx_b.dt),
            price=float(bi.fx_b.fx),
            is_high=is_end_high,
            bi_index=i,
        ))

    return endpoints


def calculate_zs(endpoints: List[BiEndpoint], min_bars: int = 3) -> Optional[ZS]:
    """计算中枢 — 至少连续三笔的重叠区"""
    if len(endpoints) < min_bars * 2:
        return None
    recent = endpoints[-(min_bars * 2):]
    highs = [ep.price for ep in recent if ep.is_high]
    lows = [ep.price for ep in recent if not ep.is_high]
    if len(highs) < 2 or len(lows) < 2:
        return None
    zg = min(highs)
    zd = max(lows)
    if zg <= zd:
        return None
    return ZS(
        zg=zg, zd=zd, zz=(zg + zd) / 2,
        start_dt=recent[0].dt, end_dt=recent[-1].dt,
    )


# ============================================================================
# 信号检测
# ============================================================================

def detect_type1_signal(endpoints: List[BiEndpoint],
                        direction: str = 'long') -> Optional[ChanlunSignal]:
    """
    1 类信号（趋势反转）— 严格按时间顺序取最近 4 个端点。

    做多: 端点序列必须为 低-高-低-高，且 低[1]>低[0] 且 高[1]>高[0]
    做空: 端点序列必须为 高-低-高-低，且 高[1]<高[0] 且 低[1]<低[0]
    """
    if len(endpoints) < 4:
        return None

    # 按时间排序后取最近 4 个（防止上游乱序）
    sorted_eps = sorted(endpoints, key=lambda e: e.dt)
    recent = sorted_eps[-4:]

    if direction == 'long':
        # 期望模式: L H L H
        if not (not recent[0].is_high and recent[1].is_high
                and not recent[2].is_high and recent[3].is_high):
            return None
        low_0, high_0 = recent[0].price, recent[1].price
        low_1, high_1 = recent[2].price, recent[3].price
        if low_1 > low_0 and high_1 > high_0:
            return ChanlunSignal(
                signal_type=SignalType.TYPE1_LONG,
                direction=1,
                strength=0.6,
                price=high_1,
                datetime=recent[3].dt,
                key_level=low_1,  # 止损在第二个低点
                volume_ratio=1.0,
            )
    else:  # short
        # 期望模式: H L H L
        if not (recent[0].is_high and not recent[1].is_high
                and recent[2].is_high and not recent[3].is_high):
            return None
        high_0, low_0 = recent[0].price, recent[1].price
        high_1, low_1 = recent[2].price, recent[3].price
        if high_1 < high_0 and low_1 < low_0:
            return ChanlunSignal(
                signal_type=SignalType.TYPE1_SHORT,
                direction=-1,
                strength=0.6,
                price=low_1,
                datetime=recent[3].dt,
                key_level=high_1,
                volume_ratio=1.0,
            )

    return None


def detect_type2_signal(bi_list: List[Any], endpoints: List[BiEndpoint],
                        golden_ratio: float = 1.618) -> Optional[ChanlunSignal]:
    """2 类信号（强势延续）— 同向相邻两笔，后笔力度 >= 前笔 * 黄金分割"""
    if len(bi_list) < 2:
        return None
    last_bi = bi_list[-1]
    prev_bi = bi_list[-2]
    last_power = abs(getattr(last_bi, 'power_price', last_bi.power))
    prev_power = abs(getattr(prev_bi, 'power_price', prev_bi.power))
    if prev_power <= 0:
        return None
    ratio = last_power / prev_power

    if last_bi.direction == Direction.Up and prev_bi.direction == Direction.Up:
        if ratio >= golden_ratio:
            return ChanlunSignal(
                signal_type=SignalType.TYPE2_LONG,
                direction=1,
                strength=min(0.8, ratio / golden_ratio),
                price=float(last_bi.fx_b.fx),
                datetime=str(last_bi.fx_b.dt),
                key_level=float(last_bi.fx_a.fx),
                volume_ratio=1.5,
            )
    elif last_bi.direction == Direction.Down and prev_bi.direction == Direction.Down:
        if ratio >= golden_ratio:
            return ChanlunSignal(
                signal_type=SignalType.TYPE2_SHORT,
                direction=-1,
                strength=min(0.8, ratio / golden_ratio),
                price=float(last_bi.fx_b.fx),
                datetime=str(last_bi.fx_b.dt),
                key_level=float(last_bi.fx_a.fx),
                volume_ratio=1.5,
            )
    return None


def detect_type3_signal(endpoints: List[BiEndpoint],
                        bi_list: List[Any],
                        break_tolerance: float = 0.002) -> Optional[ChanlunSignal]:
    """3 类信号（强势确认）— 两次回调不破前低 / 两次反弹不破前高"""
    if len(endpoints) < 6 or len(bi_list) < 3:
        return None
    sorted_eps = sorted(endpoints, key=lambda e: e.dt)
    recent = sorted_eps[-6:]
    lows = [ep for ep in recent if not ep.is_high]
    highs = [ep for ep in recent if ep.is_high]
    if len(lows) < 3 or len(highs) < 3:
        return None
    last_bi = bi_list[-1]

    if last_bi.direction == Direction.Up:
        p0, p2, p4 = lows[-3].price, lows[-2].price, lows[-1].price
        if p2 >= p0 * (1 - break_tolerance) and p4 >= p2 * (1 - break_tolerance):
            return ChanlunSignal(
                signal_type=SignalType.TYPE3_LONG,
                direction=1, strength=0.85,
                price=float(last_bi.fx_b.fx),
                datetime=str(last_bi.fx_b.dt),
                key_level=p4, volume_ratio=2.0,
            )
    else:
        p0, p2, p4 = highs[-3].price, highs[-2].price, highs[-1].price
        if p2 <= p0 * (1 + break_tolerance) and p4 <= p2 * (1 + break_tolerance):
            return ChanlunSignal(
                signal_type=SignalType.TYPE3_SHORT,
                direction=-1, strength=0.85,
                price=float(last_bi.fx_b.fx),
                datetime=str(last_bi.fx_b.dt),
                key_level=p4, volume_ratio=2.0,
            )
    return None


def detect_type4_signal(endpoints: List[BiEndpoint], bi_list: List[Any],
                        prev_signal: Optional[ChanlunSignal],
                        power_ratio_threshold: float = 1.3) -> Optional[ChanlunSignal]:
    """4 类信号（V 反）— 前面出现 1 类反向信号后，反向笔以足够力度打破关键位"""
    if len(bi_list) < 2 or prev_signal is None:
        return None
    last_bi = bi_list[-1]
    prev_bi = bi_list[-2]
    last_power = abs(getattr(last_bi, 'power_price', last_bi.power))
    prev_power = abs(getattr(prev_bi, 'power_price', prev_bi.power))
    if prev_power <= 0:
        return None
    ratio = last_power / prev_power

    if prev_signal.signal_type == SignalType.TYPE1_SHORT:
        if last_bi.direction == Direction.Up and ratio >= power_ratio_threshold:
            return ChanlunSignal(
                signal_type=SignalType.TYPE4_LONG, direction=1, strength=0.5,
                price=float(last_bi.fx_b.fx), datetime=str(last_bi.fx_b.dt),
                key_level=float(last_bi.fx_a.fx), volume_ratio=0.5,
            )
    elif prev_signal.signal_type == SignalType.TYPE1_LONG:
        if last_bi.direction == Direction.Down and ratio >= power_ratio_threshold:
            return ChanlunSignal(
                signal_type=SignalType.TYPE4_SHORT, direction=-1, strength=0.5,
                price=float(last_bi.fx_b.fx), datetime=str(last_bi.fx_b.dt),
                key_level=float(last_bi.fx_a.fx), volume_ratio=0.5,
            )
    return None


def aggregate_signals(signals: List[ChanlunSignal]) -> Optional[ChanlunSignal]:
    """信号聚合 — 多空冲突放弃；优先级 3 > 2 > 1 > 4（数字小 = 优先级高）"""
    if not signals:
        return None
    longs = [s for s in signals if s.direction > 0]
    shorts = [s for s in signals if s.direction < 0]
    if longs and shorts:
        return None  # 多空冲突，安全起见放弃
    valid = longs if longs else shorts
    priority = {
        SignalType.TYPE3_LONG: 1, SignalType.TYPE3_SHORT: 1,
        SignalType.TYPE2_LONG: 2, SignalType.TYPE2_SHORT: 2,
        SignalType.TYPE1_LONG: 3, SignalType.TYPE1_SHORT: 3,
        SignalType.TYPE4_LONG: 4, SignalType.TYPE4_SHORT: 4,
    }
    return sorted(valid, key=lambda s: priority.get(s.signal_type, 99))[0]


# ============================================================================
# 策略入口
# ============================================================================

def initialize(api: StrategyAPI):
    """策略初始化 — 重置全局状态、打印参数"""
    global g_chanlun_state, g_signals_history, g_klines_snapshot, g_zs_history

    if not CZSC_AVAILABLE:
        api.log("错误: czsc 库未安装，请运行: pip install czsc==0.9.51")
        return

    g_signals_history = []
    g_klines_snapshot = None
    g_zs_history = []
    g_chanlun_state.reset()

    api.log("=" * 60)
    api.log("缠论 5 分钟策略初始化")
    api.log("=" * 60)
    api.log(f"参数:")
    api.log(f"  min_bi_len           = {api.get_param('min_bi_len', 5)}")
    api.log(f"  golden_ratio         = {api.get_param('golden_ratio', 1.618)}")
    api.log(f"  atr_period           = {api.get_param('atr_period', 14)}")
    api.log(f"  atr_stop_multiplier  = {api.get_param('atr_stop_multiplier', 2.5)}")
    api.log(f"  signal_cooldown      = {api.get_param('signal_cooldown', 6)}")
    api.log(f"  v_reversal_power_ratio = {api.get_param('v_reversal_power_ratio', 1.3)}")
    api.log(f"  base_volume          = {api.get_param('base_volume', 1)}")
    api.log("等待 K 线数据...")


def chanlun_5m_strategy(api: StrategyAPI):
    """
    缠论 5 分钟策略主函数 — 每根 K 线调用一次
    """
    global g_chanlun_state, g_signals_history, g_klines_snapshot, g_zs_history

    if not CZSC_AVAILABLE:
        return

    # 参数
    min_bi_len = api.get_param('min_bi_len', 5)
    golden_ratio = api.get_param('golden_ratio', 1.618)
    atr_period = api.get_param('atr_period', 14)
    atr_stop_multiplier = api.get_param('atr_stop_multiplier', 2.5)
    base_volume = api.get_param('base_volume', 1)
    signal_cooldown = api.get_param('signal_cooldown', 6)
    use_structure_stop = api.get_param('use_structure_stop', True)
    v_reversal_power_ratio = api.get_param('v_reversal_power_ratio', 1.3)
    break_tolerance = api.get_param('break_tolerance', 0.002)

    current_idx = api.get_idx()
    klines = api.get_klines()
    g_klines_snapshot = klines

    if len(klines) < 50:
        return

    data_source = api.get_data_source(0)
    if data_source is None:
        return
    symbol = data_source.symbol
    freq = api.get_param('kline_period', '5m')

    # ------ 步骤 1: 增量更新 czsc 分析器（O(1) 而非 O(N)）------
    try:
        new_bars = kline_to_rawbar_incremental(
            klines, symbol, freq, len(g_chanlun_state.cached_raw_bars)
        )
        if g_chanlun_state.czsc_analyzer is None:
            if new_bars:
                # 首次：用全部历史 bar 初始化
                g_chanlun_state.czsc_analyzer = CZSC(new_bars, max_bi_num=min_bi_len * 20)
                g_chanlun_state.cached_raw_bars.extend(new_bars)
        else:
            for bar in new_bars:
                g_chanlun_state.czsc_analyzer.update(bar)
            g_chanlun_state.cached_raw_bars.extend(new_bars)
    except Exception as e:
        api.log(f"czsc 更新失败: {e}")
        return

    if g_chanlun_state.czsc_analyzer is None:
        return

    bi_list = g_chanlun_state.czsc_analyzer.bi_list
    if len(bi_list) < 3:
        return

    # 笔序列无变化时仍要检查止损（K 线波动可能触发）
    if len(bi_list) == g_chanlun_state.last_bi_count:
        _check_pending_entry(api)
        check_stop_loss(api, atr_period, atr_stop_multiplier, use_structure_stop)
        return
    g_chanlun_state.last_bi_count = len(bi_list)

    # ------ 步骤 2: 端点 & 中枢 ------
    endpoints = extract_bi_endpoints(bi_list)
    g_chanlun_state.bi_endpoints = endpoints
    new_zs = calculate_zs(endpoints)
    g_chanlun_state.current_zs = new_zs
    if new_zs is not None:
        if (not g_zs_history or
                g_zs_history[-1].start_dt != new_zs.start_dt or
                g_zs_history[-1].end_dt != new_zs.end_dt):
            g_zs_history.append(new_zs)

    # ------ 步骤 3: 检测四类信号 ------
    signals: List[ChanlunSignal] = []
    for sig in (detect_type1_signal(endpoints, 'long'),
                detect_type1_signal(endpoints, 'short'),
                detect_type2_signal(bi_list, endpoints, golden_ratio),
                detect_type3_signal(endpoints, bi_list, break_tolerance),
                detect_type4_signal(endpoints, bi_list,
                                    g_chanlun_state.current_signal,
                                    v_reversal_power_ratio)):
        if sig is not None:
            signals.append(sig)

    final_signal = aggregate_signals(signals)

    # ------ 趋势过滤：用本源 5m 数据合成长周期 MA，避开多数据源对齐黑盒 ------
    # 240 根 5m ≈ 20 小时（≈ 15m MA80 的等价物）
    if final_signal is not None and api.get_param('use_trend_filter', True):
        trend_ma_period = api.get_param('trend_ma_period', 240)
        trend_buffer = api.get_param('trend_buffer', 0.005)
        try:
            close_trend = api.get_close(index=0)
            if close_trend is not None and len(close_trend) >= trend_ma_period:
                ma = float(close_trend.rolling(trend_ma_period).mean().iloc[-1])
                cur = float(close_trend.iloc[-1])
                trend_up = cur > ma * (1 + trend_buffer)
                trend_down = cur < ma * (1 - trend_buffer)
                if final_signal.direction > 0 and not trend_up:
                    final_signal = None
                elif final_signal.direction < 0 and not trend_down:
                    final_signal = None
        except Exception:
            pass

    # ------ 成交量过滤：短均量/长均量 < 阈值，视为"无人交易的假结构" ------
    if final_signal is not None and api.get_param('use_volume_filter', True):
        v_short = api.get_param('volume_short_period', 5)     # 最近 5 根
        v_long = api.get_param('volume_long_period', 50)      # 最近 50 根
        v_min_ratio = api.get_param('volume_min_ratio', 0.5)  # 短均/长均必须 >= 0.5
        try:
            klines_full = api.get_klines(index=0)
            if klines_full is not None and 'volume' in klines_full.columns \
                    and len(klines_full) >= v_long:
                vol = klines_full['volume']
                short_avg = float(vol.tail(v_short).mean())
                long_avg = float(vol.tail(v_long).mean())
                if long_avg > 0:
                    ratio = short_avg / long_avg
                    if ratio < v_min_ratio:
                        final_signal = None  # 信号在低量区，疑似假结构
        except Exception:
            pass

    # ------ 缠论"买卖点不超买"原则：同走势同级别最多 N 次 ------
    # 触发条件：信号方向反转（趋势反转）或新中枢形成 → 重置交易计数
    max_trades = api.get_param('max_trades_per_trend', 2)
    if final_signal is not None:
        st = g_chanlun_state
        # 1) 中枢更迭检测 — 新中枢出现视为新走势段
        if st.current_zs is not None:
            zs_sig = (st.current_zs.start_dt, st.current_zs.end_dt)
            if st.last_zs_signature is not None and zs_sig != st.last_zs_signature:
                # 中枢更替 → 新一段走势开始，重置计数（但保持方向，等下面信号方向再决定）
                st.trades_in_current_trend = 0
            st.last_zs_signature = zs_sig

        # 2) 信号方向 vs 当前趋势方向
        if st.current_trend_direction == 0 or final_signal.direction != st.current_trend_direction:
            # 趋势翻转或首次开仓 → 重置计数
            st.current_trend_direction = final_signal.direction
            st.trades_in_current_trend = 0

        # 3) 同向同段：检查计数上限
        if st.trades_in_current_trend >= max_trades:
            api.log(f"[过滤-超买] 同走势已交易 {st.trades_in_current_trend} 次，"
                    f"跳过 {final_signal.signal_type.name}")
            final_signal = None

    # 信号冷却期
    if final_signal:
        if current_idx - g_chanlun_state.last_signal_bar < signal_cooldown:
            final_signal = None

    # ------ 步骤 4: 执行交易 ------
    current_pos = api.get_pos()
    current_price = api.get_price()

    if final_signal:
        execute_trade(api, final_signal, current_pos, base_volume)
        g_chanlun_state.current_signal = final_signal
        g_chanlun_state.last_signal_bar = current_idx
        # 实际下单了才递增"同走势交易计数"
        g_chanlun_state.trades_in_current_trend += 1
        # 标记 pending — 下根 K 线开盘时回填实际入场价
        if current_pos == 0:
            g_chanlun_state.pending_entry = {
                'direction': final_signal.direction,
                'placed_idx': current_idx,
            }
        sig_dt = (str(klines.index[-1])
                  if hasattr(klines, 'index') and len(klines) > 0
                  else str(current_idx))
        g_signals_history.append({
            'datetime': sig_dt,
            'signal_type': final_signal.signal_type.name,
            'direction': final_signal.direction,
            'strength': round(float(final_signal.strength), 4),
            'price': round(float(final_signal.price), 4),
            'key_level': round(float(final_signal.key_level), 4),
            'volume_ratio': round(float(final_signal.volume_ratio), 2),
        })

    _check_pending_entry(api)
    check_stop_loss(api, atr_period, atr_stop_multiplier, use_structure_stop)


def _check_pending_entry(api: StrategyAPI):
    """
    回填实际入场价。
    上一根 K 线发出过开仓信号（next_bar_open），这一根开盘时持仓应该已变化，
    用当前 K 线开盘价作为 entry_price（而非信号触发时的 close）。
    """
    pending = g_chanlun_state.pending_entry
    if pending is None:
        return
    current_pos = api.get_pos()
    # 如果方向匹配（持仓和 pending 方向一致），说明已成交
    if (pending['direction'] > 0 and current_pos > 0) or \
       (pending['direction'] < 0 and current_pos < 0):
        opens = api.get_open()
        if len(opens) > 0:
            g_chanlun_state.entry_price = float(opens.iloc[-1])
        g_chanlun_state.entry_bar_idx = api.get_idx()
        g_chanlun_state.pending_entry = None
    elif api.get_idx() - pending['placed_idx'] > 2:
        # 超过 2 根 K 线还没成交，清掉 pending
        g_chanlun_state.pending_entry = None


def execute_trade(api: StrategyAPI, signal: ChanlunSignal, current_pos: int,
                  base_volume: int):
    """执行下单 — 平仓显式传 volume 避免框架默认行为变化"""
    volume = max(1, int(base_volume * signal.volume_ratio))
    name = signal.signal_type.name

    if signal.direction > 0:
        if current_pos < 0:
            api.buycover(volume=abs(current_pos), reason=f"平空后{name}")
            api.log(f"[{name}] 平空仓 {abs(current_pos)} 手")
        if current_pos <= 0:
            api.buy(volume=volume, order_type='next_bar_open', reason=f"{name} 做多")
            api.log(f"[{name}] 开多 {volume} 手, 止损位 {signal.key_level:.2f}")
    else:
        if current_pos > 0:
            api.sell(volume=current_pos, reason=f"平多后{name}")
            api.log(f"[{name}] 平多仓 {current_pos} 手")
        if current_pos >= 0:
            api.sellshort(volume=volume, order_type='next_bar_open', reason=f"{name} 做空")
            api.log(f"[{name}] 开空 {volume} 手, 止损位 {signal.key_level:.2f}")


def check_stop_loss(api: StrategyAPI, atr_period: int,
                    atr_stop_multiplier: float, use_structure_stop: bool):
    """ATR / 结构 / 中枢 三重止损"""
    state = g_chanlun_state
    current_pos = api.get_pos()
    if current_pos == 0:
        return
    if state.entry_price <= 0:
        return  # 入场价还未回填

    current_price = api.get_price()
    atr = calculate_atr(api.get_high(), api.get_low(), api.get_close(), atr_period)
    if atr <= 0:
        return

    triggered = False
    reason = ""

    if current_pos > 0:
        atr_stop = state.entry_price - atr_stop_multiplier * atr
        if current_price <= atr_stop:
            triggered = True
            reason = f"ATR 止损 ({atr_stop:.2f})"
        if not triggered and use_structure_stop and state.current_signal:
            if current_price <= state.current_signal.key_level:
                triggered = True
                reason = f"结构止损 ({state.current_signal.key_level:.2f})"
        if not triggered and state.current_zs and current_price <= state.current_zs.zd:
            triggered = True
            reason = f"中枢破位 ({state.current_zs.zd:.2f})"
    elif current_pos < 0:
        atr_stop = state.entry_price + atr_stop_multiplier * atr
        if current_price >= atr_stop:
            triggered = True
            reason = f"ATR 止损 ({atr_stop:.2f})"
        if not triggered and use_structure_stop and state.current_signal:
            if current_price >= state.current_signal.key_level:
                triggered = True
                reason = f"结构止损 ({state.current_signal.key_level:.2f})"
        if not triggered and state.current_zs and current_price >= state.current_zs.zg:
            triggered = True
            reason = f"中枢破位 ({state.current_zs.zg:.2f})"

    if triggered:
        api.close_all(reason=reason, order_type='next_bar_open')
        api.log(f"触发止损: {reason}, 当前价 {current_price:.2f}")
        state.entry_price = 0.0
        state.entry_bar_idx = None
        state.current_signal = None


# ============================================================================
# 后处理：信号导出 + 缠论图
# ============================================================================

def save_signals_to_file(signals_history, output_dir='backtest_results',
                         symbol='', period=''):
    if not signals_history:
        print("没有检测到信号，跳过保存")
        return None, None
    os.makedirs(output_dir, exist_ok=True)
    ts = _dt_cls.now().strftime('%Y%m%d_%H%M%S')
    base = f"chanlun_signals_{symbol}_{period}_{ts}"
    fields = ['datetime', 'signal_type', 'direction', 'strength',
              'price', 'key_level', 'volume_ratio']
    csv_path = os.path.join(output_dir, f"{base}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = _csv_module.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for sig in signals_history:
            writer.writerow({k: sig.get(k, '') for k in fields})
    json_path = os.path.join(output_dir, f"{base}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(signals_history, f, ensure_ascii=False, indent=2, default=str)
    print(f"信号 CSV: {os.path.abspath(csv_path)}")
    print(f"信号 JSON: {os.path.abspath(json_path)}")
    return csv_path, json_path


def _find_bar_idx(date_index, target):
    try:
        ts = pd.Timestamp(str(target))
        pos = date_index.searchsorted(ts)
        if pos >= len(date_index):
            pos = len(date_index) - 1
        return int(pos)
    except Exception:
        return None


def plot_chanlun_chart(klines, bi_list, zs_history, signals_history,
                       symbol='', period='', output_dir='backtest_results'):
    """生成缠论分析 K 线图：蜡烛 + 笔 + 线段 + 中枢矩形 + 买卖点标注"""
    if klines is None or len(klines) == 0:
        print("没有 K 线数据，无法生成缠论图表")
        return None

    os.makedirs(output_dir, exist_ok=True)
    df = klines if isinstance(klines, pd.DataFrame) else pd.DataFrame(klines)
    n = len(df)
    date_index = df.index

    has_volume = ('volume' in df.columns
                  and not df['volume'].isna().all()
                  and df['volume'].sum() > 0)

    if has_volume:
        fig, (ax_main, ax_vol) = plt.subplots(
            2, 1, figsize=(22, 14),
            gridspec_kw={'height_ratios': [4, 1]}, sharex=True,
        )
    else:
        fig, ax_main = plt.subplots(1, 1, figsize=(22, 12))
        ax_vol = None

    fig.suptitle(f"{symbol} {period} 缠论分析图", fontsize=16, fontweight='bold')

    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values

    # 蜡烛
    for i in range(n):
        color = '#E53935' if closes[i] >= opens[i] else '#43A047'  # 红涨绿跌
        ax_main.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8, zorder=1)
        body_lo = min(opens[i], closes[i])
        body_hi = max(opens[i], closes[i])
        body_h = max(body_hi - body_lo,
                     (highs[i] - lows[i]) * 0.001 if highs[i] > lows[i] else 0.001)
        ax_main.add_patch(mpatches.Rectangle(
            (i - 0.35, body_lo), 0.7, body_h,
            facecolor=color, edgecolor=color, linewidth=0, zorder=2,
        ))

    # 笔
    if bi_list and CZSC_AVAILABLE:
        for bi in bi_list:
            try:
                s_idx = _find_bar_idx(date_index, bi.fx_a.dt)
                e_idx = _find_bar_idx(date_index, bi.fx_b.dt)
                if s_idx is None or e_idx is None:
                    continue
                bi_color = '#1565C0' if bi.direction == Direction.Up else '#E65100'
                ax_main.plot([s_idx, e_idx],
                             [float(bi.fx_a.fx), float(bi.fx_b.fx)],
                             color=bi_color, linewidth=2.2, zorder=4,
                             solid_capstyle='round', alpha=0.9)
                ax_main.scatter([s_idx, e_idx],
                                [float(bi.fx_a.fx), float(bi.fx_b.fx)],
                                color=bi_color, s=25, zorder=5, alpha=0.9)
            except Exception:
                continue

    # 中枢
    for zs in zs_history:
        try:
            x0 = _find_bar_idx(date_index, zs.start_dt)
            x1 = _find_bar_idx(date_index, zs.end_dt)
            if x0 is None or x1 is None or x1 <= x0:
                continue
            w = x1 - x0
            h = zs.zg - zs.zd
            if h <= 0:
                continue
            ax_main.add_patch(mpatches.Rectangle(
                (x0, zs.zd), w, h,
                facecolor='#90CAF9', edgecolor='#1565C0',
                alpha=0.25, linewidth=1.5, zorder=2,
            ))
            ax_main.hlines(zs.zg, x0, x1, colors='#1565C0', linewidths=1.2,
                           linestyles='--', zorder=3, alpha=0.85)
            ax_main.hlines(zs.zd, x0, x1, colors='#1565C0', linewidths=1.2,
                           linestyles='--', zorder=3, alpha=0.85)
            ax_main.hlines(zs.zz, x0, x1, colors='#7B1FA2', linewidths=1.0,
                           linestyles=':', zorder=3, alpha=0.85)
            ax_main.text(x0 + 0.2, zs.zg, f'ZG {zs.zg:.1f}',
                         fontsize=7, color='#1565C0', va='bottom', zorder=6)
            ax_main.text(x0 + 0.2, zs.zd, f'ZD {zs.zd:.1f}',
                         fontsize=7, color='#1565C0', va='top', zorder=6)
        except Exception:
            continue

    # 买卖点
    LONG_COLORS = {'TYPE1_LONG': '#D50000', 'TYPE2_LONG': '#B71C1C',
                   'TYPE3_LONG': '#FF6D00', 'TYPE4_LONG': '#FF8A65'}
    SHORT_COLORS = {'TYPE1_SHORT': '#00C853', 'TYPE2_SHORT': '#1B5E20',
                    'TYPE3_SHORT': '#64DD17', 'TYPE4_SHORT': '#A5D6A7'}
    LABELS = {'TYPE1_LONG': '1类多', 'TYPE2_LONG': '2类多',
              'TYPE3_LONG': '3类多', 'TYPE4_LONG': 'V反多',
              'TYPE1_SHORT': '1类空', 'TYPE2_SHORT': '2类空',
              'TYPE3_SHORT': '3类空', 'TYPE4_SHORT': 'V反空'}

    for sig in signals_history:
        try:
            sig_idx = _find_bar_idx(date_index, sig['datetime'])
            if sig_idx is None:
                continue
            stype = sig['signal_type']
            is_long = sig['direction'] > 0
            color = (LONG_COLORS.get(stype, '#D50000') if is_long
                     else SHORT_COLORS.get(stype, '#00C853'))
            marker = '^' if is_long else 'v'
            v_offset = 12 if is_long else -12
            ax_main.scatter(sig_idx, float(sig['price']),
                            color=color, marker=marker, s=200, zorder=7,
                            edgecolors='black', linewidths=0.5)
            ax_main.annotate(LABELS.get(stype, stype),
                             xy=(sig_idx, float(sig['price'])),
                             xytext=(0, v_offset), textcoords='offset points',
                             fontsize=7, color=color, ha='center',
                             fontweight='bold', zorder=8)
        except Exception:
            continue

    # 轴
    price_min = float(lows.min())
    price_max = float(highs.max())
    pad = (price_max - price_min) * 0.06
    ax_main.set_ylim(price_min - pad, price_max + pad)
    ax_main.set_xlim(-1, n + 1)
    ax_main.set_ylabel('价格', fontsize=12)
    ax_main.grid(True, alpha=0.2, linewidth=0.5)

    tick_step = max(1, n // 14)
    tick_ids = list(range(0, n, tick_step))
    if n - 1 not in tick_ids:
        tick_ids.append(n - 1)
    date_labels = [str(date_index[i])[:16] for i in tick_ids]
    ax_main.set_xticks(tick_ids)
    ax_main.set_xticklabels(date_labels, rotation=45, fontsize=8, ha='right')

    if ax_vol is not None:
        volumes = df['volume'].values
        vol_colors = ['#E53935' if closes[i] >= opens[i] else '#43A047'
                      for i in range(n)]
        ax_vol.bar(range(n), volumes, color=vol_colors, alpha=0.55, width=0.6)
        ax_vol.set_ylabel('成交量', fontsize=10)
        ax_vol.grid(True, alpha=0.2, linewidth=0.5)
        ax_vol.set_xticks(tick_ids)
        ax_vol.set_xticklabels(date_labels, rotation=45, fontsize=8, ha='right')

    legend = [
        mpatches.Patch(facecolor='#E53935', label='阳线（涨）'),
        mpatches.Patch(facecolor='#43A047', label='阴线（跌）'),
        _Line2D([0], [0], color='#1565C0', linewidth=2, label='上升笔'),
        _Line2D([0], [0], color='#E65100', linewidth=2, label='下降笔'),
        mpatches.Patch(facecolor='#90CAF9', edgecolor='#1565C0',
                       alpha=0.5, label='中枢(ZS)'),
        _Line2D([0], [0], marker='^', color='#D50000', markersize=10,
                linestyle='', label='做多信号'),
        _Line2D([0], [0], marker='v', color='#00C853', markersize=10,
                linestyle='', label='做空信号'),
    ]
    ax_main.legend(handles=legend, loc='upper left', fontsize=9,
                   framealpha=0.8, ncol=4)

    plt.tight_layout()
    ts_str = _dt_cls.now().strftime('%Y%m%d_%H%M%S')
    chart_name = f"chanlun_5m_{symbol}_{period}_{ts_str}.png"
    chart_path = os.path.join(output_dir, chart_name)
    plt.savefig(chart_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"缠论分析图: {os.path.abspath(chart_path)}")
    return chart_path


# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == "__main__":
    # ---------- 运行模式 ----------
    RUN_MODE = RunMode.BACKTEST

    # ---------- 策略参数（单源 5m + 内部计算趋势）----------
    strategy_params = {
        'min_bi_len': 5,
        'golden_ratio': 1.618,
        'atr_period': 14,
        'atr_stop_multiplier': 2.5,
        'base_volume': 1,
        'use_structure_stop': True,
        'signal_cooldown': 6,
        'v_reversal_power_ratio': 1.3,
        'break_tolerance': 0.002,
        'kline_period': '5m',
        # ---- 趋势过滤（5m 内部合成长周期 MA）----
        'use_trend_filter': True,
        'trend_ma_period': 240,           # 240 根 5m ≈ 20 小时（等价 15m MA80）
        'trend_buffer': 0.005,
        # ---- 成交量过滤（短/长均量比 < 阈值 = 假结构）— 实测拖累，默认关 ----
        'use_volume_filter': False,
        'volume_short_period': 5,         # 最近 5 根（≈ 25 分钟）
        'volume_long_period': 50,         # 最近 50 根（≈ 4 小时）
        'volume_min_ratio': 0.5,          # 短均量必须 ≥ 长均量 × 0.5
        # ---- 缠论"买卖点不超买"原则 ----
        'max_trades_per_trend': 2,
    }

    # ---------- 数据源 ----------
    _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    _db_path = os.path.join(_proj_root, 'data_cache', 'kline_data.db')

    # ---------- 单数据源回测配置（只用 5m，框架行为简单可预测）----------
    # 跨品种验证：铁矿石 i888（vs 黄金 au888）
    config = get_config(RUN_MODE,
        symbol='i888',                   # 铁矿石主连
        start_date='2022-01-01',
        end_date='2023-12-31',
        kline_period='5m',
        adjust_type='1',

        # 合约（铁矿石）
        price_tick=0.5,                  # 铁矿石最小变动 0.5 元/吨
        contract_multiplier=100,         # 铁矿石 100 吨/手
        slippage_ticks=1,

        # 资金
        initial_capital=500000,
        commission=0.0001,
        margin_rate=0.1,
    )

    # 数据来源
    if os.path.exists(_db_path):
        config['file_path'] = _db_path
        print(f"[OK] 使用 SQLite 数据源: {_db_path}")
        print(f"[OK] 趋势过滤（内部计算）: 5m MA{strategy_params['trend_ma_period']}, "
              f"buffer ±{strategy_params['trend_buffer']*100:.1f}%")
    else:
        print(f"[ERR] 数据库不存在: {_db_path}")
        raise SystemExit(1)

    # ---------- 启动 ----------
    print("\n" + "=" * 80)
    print("缠论 5 分钟策略 (单源 + 内部趋势过滤) — 回测")
    print("=" * 80)
    print(f"合约:     {config['symbol']}")
    print(f"周期:     {config['kline_period']}")
    print(f"区间:     {config['start_date']} ~ {config['end_date']}")
    print(f"参数:     ATR×{strategy_params['atr_stop_multiplier']}, "
          f"冷却 {strategy_params['signal_cooldown']} 根, "
          f"MA{strategy_params['trend_ma_period']} 趋势过滤, "
          f"成交量过滤 ratio≥{strategy_params['volume_min_ratio']}, "
          f"同走势 ≤{strategy_params['max_trades_per_trend']} 次")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=chanlun_5m_strategy,
            initialize=initialize,
            strategy_params=strategy_params,
        )

        # 后处理：图 + 信号导出
        if RUN_MODE == RunMode.BACKTEST:
            symbol = config.get('symbol', 'unknown')
            period = config.get('kline_period', 'unknown')
            out_dir = 'backtest_results'

            print("\n" + "=" * 60)
            print("缠论后处理")
            print("=" * 60)
            print(f"检测到 {len(g_signals_history)} 个信号，{len(g_zs_history)} 个中枢")

            bi_list = (g_chanlun_state.czsc_analyzer.bi_list
                       if g_chanlun_state.czsc_analyzer is not None else [])
            plot_chanlun_chart(
                klines=g_klines_snapshot,
                bi_list=bi_list,
                zs_history=g_zs_history,
                signals_history=g_signals_history,
                symbol=symbol, period=period, output_dir=out_dir,
            )
            save_signals_to_file(
                signals_history=g_signals_history,
                output_dir=out_dir,
                symbol=symbol, period=period,
            )
            print("=" * 60)

    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
