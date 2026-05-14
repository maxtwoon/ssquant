"""
缠论多空信号四种形态交易策略 - 统一运行版本

基于缠中说禅技术分析理论，结合czsc库的缠论分析能力，
实现四种多空信号形态的识别与交易：
1. 1类信号（转多/转空）：趋势反转信号
2. 2类信号（强多/强空）：强势延续信号，黄金分割1.618倍
3. 3类信号（强多/强空）：强势确认信号，两次不破前低/高
4. 4类信号（V反多/V反空）：V型反转信号

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

依赖: czsc>=0.9.51
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from collections import deque
from datetime import datetime as _dt_cls
import json
import csv as _csv_module

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

# 导入SSQuant必要模块
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# 尝试导入czsc，如果失败则提供提示
try:
    from czsc import CZSC, RawBar, Freq, Direction
    from czsc.objects import BI, FX
    CZSC_AVAILABLE = True
except ImportError:
    CZSC_AVAILABLE = False
    print("警告: czsc库未安装，请运行: pip install czsc==0.9.51")


# ============================================================================
# 枚举和数据类定义
# ============================================================================

class SignalType(Enum):
    """信号类型枚举"""
    NONE = 0          # 无信号
    TYPE1_LONG = 1    # 1类转多
    TYPE1_SHORT = 2   # 1类转空
    TYPE2_LONG = 3    # 2类强多
    TYPE2_SHORT = 4   # 2类强空
    TYPE3_LONG = 5    # 3类强多
    TYPE3_SHORT = 6   # 3类强空
    TYPE4_LONG = 7    # 4类V反多
    TYPE4_SHORT = 8   # 4类V反空


@dataclass
class ChanlunSignal:
    """缠论信号数据类"""
    signal_type: SignalType      # 信号类型
    direction: int               # 方向: 1做多, -1做空
    strength: float              # 信号强度 (0-1)
    price: float                 # 信号触发价格
    datetime: str                # 信号触发时间
    key_level: float             # 关键价位（止损参考）
    volume_ratio: float          # 仓位比例


@dataclass
class BiEndpoint:
    """笔端点数据类，用于线段推导"""
    dt: str            # 时间
    price: float       # 价格
    is_high: bool      # 是否为高点（True=高点，False=低点）
    bi_index: int      # 对应笔的索引


@dataclass
class ZS:
    """中枢数据类"""
    zg: float          # 中枢上沿
    zd: float          # 中枢下沿
    zz: float          # 中枢中轴
    start_dt: str      # 起始时间
    end_dt: str        # 结束时间


# ============================================================================
# 全局状态管理
# ============================================================================

class ChanlunState:
    """缠论分析状态管理器"""
    
    def __init__(self):
        self.czsc_analyzer: Optional[CZSC] = None
        self.raw_bars: List[RawBar] = []
        self.last_bi_count: int = 0
        self.last_signal_bar: int = 0  # 上次信号时的K线索引
        self.entry_price: float = 0.0  # 开仓价格
        self.current_signal: Optional[ChanlunSignal] = None
        self.bi_endpoints: List[BiEndpoint] = []  # 笔端点序列
        self.current_zs: Optional[ZS] = None  # 当前中枢
        
    def reset(self):
        """重置状态"""
        self.czsc_analyzer = None
        self.raw_bars = []
        self.last_bi_count = 0
        self.last_signal_bar = 0
        self.entry_price = 0.0
        self.current_signal = None
        self.bi_endpoints = []
        self.current_zs = None


# 全局状态实例
g_chanlun_state = ChanlunState()

# ============================================================================
# 全局数据收集容器（用于可视化与信号导出）
# ============================================================================
g_signals_history: List[Dict[str, Any]] = []   # 所有检测到的信号记录
g_klines_snapshot: Optional[pd.DataFrame] = None  # K线数据快照（最后一根K线时的完整数据）
g_zs_history: List[ZS] = []                   # 中枢历史（去重后的全量中枢）


# ============================================================================
# 辅助函数：数据转换
# ============================================================================

def kline_to_rawbar(klines: pd.DataFrame, symbol: str, freq: str) -> List[RawBar]:
    """
    将SSQuant的K线DataFrame转换为czsc的RawBar列表
    
    Args:
        klines: K线DataFrame，包含datetime, open, high, low, close, volume列
        symbol: 品种代码
        freq: K线周期（如 '15m', '30m', '1h'）
        
    Returns:
        RawBar列表
    """
    if not CZSC_AVAILABLE:
        return []
    
    bars = []
    freq_map = {
        '1m': Freq.F1, '5m': Freq.F5, '15m': Freq.F15,
        '30m': Freq.F30, '1h': Freq.F60, '4h': Freq.F120,
        '1d': Freq.D
    }
    czsc_freq = freq_map.get(freq, Freq.F15)
    
    for i, row in klines.iterrows():
        # 获取datetime
        dt_val = row['datetime'] if 'datetime' in klines.columns else row.name
        # 确保是datetime类型
        if isinstance(dt_val, str):
            dt_val = pd.Timestamp(dt_val)
        
        vol = float(row['volume']) if 'volume' in klines.columns else 0.0
        bar = RawBar(
            symbol=symbol,
            id=len(bars),
            dt=dt_val,
            freq=czsc_freq,
            open=float(row['open']),
            close=float(row['close']),
            high=float(row['high']),
            low=float(row['low']),
            vol=vol,
            amount=vol * float(row['close'])  # 近似成交额
        )
        bars.append(bar)
    
    return bars


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """
    计算平均真实波幅(ATR)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        当前ATR值
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.iloc[-1] if len(atr) > 0 and not pd.isna(atr.iloc[-1]) else 0.0


# ============================================================================
# 辅助函数：线段和中枢推导
# ============================================================================

def extract_bi_endpoints(bi_list: List[BI]) -> List[BiEndpoint]:
    """
    从笔序列中提取不重复的端点
    
    笔的端点交替形成高点和低点：
    - 向上笔：起点是低点，终点是高点
    - 向下笔：起点是高点，终点是低点
    相邻笔共享端点，只添加一次。
    
    Args:
        bi_list: 笔序列
        
    Returns:
        端点序列（交替的低-高-低-高... 或 高-低-高-低...）
    """
    if not bi_list:
        return []
    
    endpoints = []
    
    # 添加第一笔的起点
    first_bi = bi_list[0]
    is_first_start_high = (first_bi.direction == Direction.Down)
    endpoints.append(BiEndpoint(
        dt=str(first_bi.fx_a.dt),
        price=first_bi.fx_a.fx,
        is_high=is_first_start_high,
        bi_index=0
    ))
    
    # 每笔只添加终点（起点与上一笔终点重合）
    for i, bi in enumerate(bi_list):
        is_end_high = (bi.direction == Direction.Up)
        endpoints.append(BiEndpoint(
            dt=str(bi.fx_b.dt),
            price=bi.fx_b.fx,
            is_high=is_end_high,
            bi_index=i
        ))
    
    return endpoints


def calculate_zs(endpoints: List[BiEndpoint], min_bars: int = 3) -> Optional[ZS]:
    """
    计算中枢
    
    中枢定义：至少连续三笔的重叠区域
    
    Args:
        endpoints: 端点序列
        min_bars: 最少笔数
        
    Returns:
        中枢对象，如果无法形成则返回None
    """
    if len(endpoints) < min_bars * 2:
        return None
    
    # 取最近的几笔来计算中枢
    recent_endpoints = endpoints[-(min_bars * 2):]
    
    # 分离高点和低点
    highs = [ep.price for ep in recent_endpoints if ep.is_high]
    lows = [ep.price for ep in recent_endpoints if not ep.is_high]
    
    if len(highs) < 2 or len(lows) < 2:
        return None
    
    # 中枢上沿 = 高点的最低值
    # 中枢下沿 = 低点的最高值
    zg = min(highs)
    zd = max(lows)
    
    # 只有当高点最低值 > 低点最高值时，才形成有效中枢
    if zg <= zd:
        return None
    
    zz = (zg + zd) / 2
    
    return ZS(
        zg=zg,
        zd=zd,
        zz=zz,
        start_dt=recent_endpoints[0].dt,
        end_dt=recent_endpoints[-1].dt
    )


# ============================================================================
# 信号检测函数
# ============================================================================

def detect_type1_signal(endpoints: List[BiEndpoint], direction: str = 'long') -> Optional[ChanlunSignal]:
    """
    检测1类信号（趋势反转）
    
    做多条件（1类转多）：
    - 下跌趋势中，相邻两段下跌的低点依次抬高（点2 > 点0）
    - 反弹高点依次抬高（点3 > 点1）
    - 即：低点抬高 + 高点突破
    
    做空条件（1类转空）：
    - 上涨趋势中，相邻两段上涨的高点依次降低（点2 < 点0）
    - 回调低点依次降低（点3 < 点1）
    - 即：高点降低 + 低点突破
    
    端点编号说明：
    - 偶数编号（0、2、4...）为低点
    - 奇数编号（1、3、5...）为高点
    
    Args:
        endpoints: 端点序列
        direction: 检测方向 'long' 或 'short'
        
    Returns:
        信号对象，如果不满足条件则返回None
    """
    if len(endpoints) < 4:
        return None
    
    # 获取最近的端点（至少需要4个端点：0,1,2,3）
    recent = endpoints[-4:]
    
    # 按顺序提取高低点
    # 端点序列应该是：低-高-低-高 或 高-低-高-低
    # 我们需要识别出点0,1,2,3
    
    # 分离高低点
    lows = [ep for ep in recent if not ep.is_high]
    highs = [ep for ep in recent if ep.is_high]
    
    if len(lows) < 2 or len(highs) < 2:
        return None
    
    if direction == 'long':
        # 1类转多：需要低点抬高 + 高点突破
        # 点0 = 第一个低点, 点1 = 第一个高点, 点2 = 第二个低点, 点3 = 第二个高点
        point_0 = lows[0].price
        point_1 = highs[0].price
        point_2 = lows[1].price
        point_3 = highs[1].price
        
        # 条件：点2 > 点0（低点抬高）且 点3 > 点1（高点突破）
        if point_2 > point_0 and point_3 > point_1:
            return ChanlunSignal(
                signal_type=SignalType.TYPE1_LONG,
                direction=1,
                strength=0.6,
                price=point_3,
                datetime=highs[1].dt,
                key_level=point_2,  # 止损设在点2
                volume_ratio=1.0
            )
    
    else:  # direction == 'short'
        # 1类转空：需要高点降低 + 低点突破
        # 点0 = 第一个高点, 点1 = 第一个低点, 点2 = 第二个高点, 点3 = 第二个低点
        point_0 = highs[0].price
        point_1 = lows[0].price
        point_2 = highs[1].price
        point_3 = lows[1].price
        
        # 条件：点2 < 点0（高点降低）且 点3 < point_1（低点突破）
        if point_2 < point_0 and point_3 < point_1:
            return ChanlunSignal(
                signal_type=SignalType.TYPE1_SHORT,
                direction=-1,
                strength=0.6,
                price=point_3,
                datetime=lows[1].dt,
                key_level=point_2,  # 止损设在点2
                volume_ratio=1.0
            )
    
    return None


def detect_type2_signal(bi_list: List[BI], endpoints: List[BiEndpoint], 
                        golden_ratio: float = 1.618) -> Optional[ChanlunSignal]:
    """
    检测2类信号（强势延续）
    
    做多条件（2类强多）：
    - 第二段上涨线段的幅度 >= 第一段上涨线段幅度 * 1.618
    
    做空条件（2类强空）：
    - 第二段下跌线段的幅度 >= 第一段下跌线段幅度 * 1.618
    
    Args:
        bi_list: 笔序列
        endpoints: 端点序列
        golden_ratio: 黄金分割比例阈值
        
    Returns:
        信号对象，如果不满足条件则返回None
    """
    if len(bi_list) < 2:
        return None
    
    # 获取最近两笔
    last_bi = bi_list[-1]
    prev_bi = bi_list[-2]
    
    # 计算力度（价差）
    last_power = abs(last_bi.power_price) if hasattr(last_bi, 'power_price') else abs(last_bi.power)
    prev_power = abs(prev_bi.power_price) if hasattr(prev_bi, 'power_price') else abs(prev_bi.power)
    
    if prev_power <= 0:
        return None
    
    # 力度比
    power_ratio = last_power / prev_power
    
    if last_bi.direction == Direction.Up and prev_bi.direction == Direction.Up:
        # 两笔都是向上笔，检查是否满足2类强多
        if power_ratio >= golden_ratio:
            key_level = last_bi.fx_a.fx  # 止损设在当前笔的起点
            return ChanlunSignal(
                signal_type=SignalType.TYPE2_LONG,
                direction=1,
                strength=min(0.8, power_ratio / golden_ratio),
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=key_level,
                volume_ratio=1.5
            )
    
    elif last_bi.direction == Direction.Down and prev_bi.direction == Direction.Down:
        # 两笔都是向下笔，检查是否满足2类强空
        if power_ratio >= golden_ratio:
            key_level = last_bi.fx_a.fx  # 止损设在当前笔的起点
            return ChanlunSignal(
                signal_type=SignalType.TYPE2_SHORT,
                direction=-1,
                strength=min(0.8, power_ratio / golden_ratio),
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=key_level,
                volume_ratio=1.5
            )
    
    return None


def detect_type3_signal(endpoints: List[BiEndpoint], bi_list: List[BI]) -> Optional[ChanlunSignal]:
    """
    检测3类信号（强势确认）
    
    做多条件（3类强多）：
    - 连续两段回调的低点均不低于前方关键低点
    - 且最近一笔是向上笔（表示回调结束后继续上涨）
    
    做空条件（3类强空）：
    - 连续两段反弹的高点均不高于前方关键高点
    - 且最近一笔是向下笔（表示反弹结束后继续下跌）
    
    Args:
        endpoints: 端点序列
        bi_list: 笔序列
        
    Returns:
        信号对象，如果不满足条件则返回None
    """
    if len(endpoints) < 6 or len(bi_list) < 3:
        return None
    
    # 获取最近的端点
    recent = endpoints[-6:]
    
    # 分离高低点
    lows = sorted([ep for ep in recent if not ep.is_high], key=lambda x: x.dt)
    highs = sorted([ep for ep in recent if ep.is_high], key=lambda x: x.dt)
    
    if len(lows) < 3 or len(highs) < 3:
        return None
    
    last_bi = bi_list[-1]
    
    if last_bi.direction == Direction.Up:
        # 检查3类强多：两次回调不破前低
        # 取最近的三个低点：点0, 点2, 点4
        recent_lows = lows[-3:]
        point_0 = recent_lows[0].price
        point_2 = recent_lows[1].price
        point_4 = recent_lows[2].price
        
        # 条件：点2 >= 点0 且 点4 >= 点2（两次不破前低）
        if point_2 >= point_0 * 0.998 and point_4 >= point_2 * 0.998:
            return ChanlunSignal(
                signal_type=SignalType.TYPE3_LONG,
                direction=1,
                strength=0.85,
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=point_4,  # 止损设在最近低点
                volume_ratio=2.0
            )
    
    else:  # Direction.Down
        # 检查3类强空：两次反弹不破前高
        # 取最近的三个高点：点0, 点2, 点4
        recent_highs = highs[-3:]
        point_0 = recent_highs[0].price
        point_2 = recent_highs[1].price
        point_4 = recent_highs[2].price
        
        # 条件：点2 <= 点0 且 点4 <= 点2（两次不破前高）
        if point_2 <= point_0 * 1.002 and point_4 <= point_2 * 1.002:
            return ChanlunSignal(
                signal_type=SignalType.TYPE3_SHORT,
                direction=-1,
                strength=0.85,
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=point_4,  # 止损设在最近高点
                volume_ratio=2.0
            )
    
    return None


def detect_type4_signal(endpoints: List[BiEndpoint], bi_list: List[BI],
                        prev_signal: Optional[ChanlunSignal],
                        power_ratio_threshold: float = 1.2) -> Optional[ChanlunSignal]:
    """
    检测4类信号（V型反转）
    
    做多条件（4类V反多）：
    - 前方出现1类转空信号后
    - 反向上涨线段打破该转空结构的关键低点
    
    做空条件（4类V反空）：
    - 前方出现1类转多信号后
    - 反向下跌线段打破该转多结构的关键高点
    
    Args:
        endpoints: 端点序列
        bi_list: 笔序列
        prev_signal: 前一个信号
        power_ratio_threshold: 力度比阈值
        
    Returns:
        信号对象，如果不满足条件则返回None
    """
    if len(bi_list) < 2 or prev_signal is None:
        return None
    
    last_bi = bi_list[-1]
    prev_bi = bi_list[-2]
    
    # 计算力度比
    last_power = abs(last_bi.power_price) if hasattr(last_bi, 'power_price') else abs(last_bi.power)
    prev_power = abs(prev_bi.power_price) if hasattr(prev_bi, 'power_price') else abs(prev_bi.power)
    
    if prev_power <= 0:
        return None
    
    ratio = last_power / prev_power
    
    # 检查V反多
    if prev_signal.signal_type == SignalType.TYPE1_SHORT:
        # 前一个是1类转空，现在检查是否V反多
        if last_bi.direction == Direction.Up and ratio >= power_ratio_threshold:
            # 反向上涨打破转空结构
            return ChanlunSignal(
                signal_type=SignalType.TYPE4_LONG,
                direction=1,
                strength=0.5,  # V反信号强度较低
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=last_bi.fx_a.fx,
                volume_ratio=0.5
            )
    
    # 检查V反空
    elif prev_signal.signal_type == SignalType.TYPE1_LONG:
        # 前一个是1类转多，现在检查是否V反空
        if last_bi.direction == Direction.Down and ratio >= power_ratio_threshold:
            # 反向下跌打破转多结构
            return ChanlunSignal(
                signal_type=SignalType.TYPE4_SHORT,
                direction=-1,
                strength=0.5,  # V反信号强度较低
                price=last_bi.fx_b.fx,
                datetime=str(last_bi.fx_b.dt),
                key_level=last_bi.fx_a.fx,
                volume_ratio=0.5
            )
    
    return None


def aggregate_signals(signals: List[ChanlunSignal]) -> Optional[ChanlunSignal]:
    """
    信号聚合与优先级处理
    
    优先级规则：
    1. 多空信号冲突 -> 放弃交易
    2. 3类信号 > 2类信号 > 1类信号 > 4类信号
    
    Args:
        signals: 信号列表
        
    Returns:
        最终信号
    """
    if not signals:
        return None
    
    # 检查多空冲突
    long_signals = [s for s in signals if s.direction > 0]
    short_signals = [s for s in signals if s.direction < 0]
    
    if long_signals and short_signals:
        # 多空冲突，放弃交易
        return None
    
    # 按优先级排序
    priority_order = {
        SignalType.TYPE3_LONG: 1,
        SignalType.TYPE3_SHORT: 1,
        SignalType.TYPE2_LONG: 2,
        SignalType.TYPE2_SHORT: 2,
        SignalType.TYPE1_LONG: 3,
        SignalType.TYPE1_SHORT: 3,
        SignalType.TYPE4_LONG: 4,
        SignalType.TYPE4_SHORT: 4,
    }
    
    # 选择优先级最高的信号
    valid_signals = long_signals if long_signals else short_signals
    if not valid_signals:
        return None
    
    sorted_signals = sorted(valid_signals, key=lambda s: priority_order.get(s.signal_type, 5))
    return sorted_signals[0]


# ============================================================================
# 策略初始化函数
# ============================================================================

def initialize(api: StrategyAPI):
    """
    策略初始化函数
    
    Args:
        api: 策略API对象
    """
    global g_chanlun_state, g_signals_history, g_klines_snapshot, g_zs_history
    
    if not CZSC_AVAILABLE:
        api.log("错误: czsc库未安装，请运行: pip install czsc==0.9.51")
        return
    
    # 重置全局收集容器
    g_signals_history = []
    g_klines_snapshot = None
    g_zs_history = []
    
    api.log("=" * 60)
    api.log("缠论多空信号四种形态策略初始化")
    api.log("=" * 60)
    
    # 获取策略参数
    min_bi_len = api.get_param('min_bi_len', 7)
    golden_ratio = api.get_param('golden_ratio', 1.618)
    atr_period = api.get_param('atr_period', 14)
    atr_stop_multiplier = api.get_param('atr_stop_multiplier', 2.0)
    base_volume = api.get_param('base_volume', 1)
    signal_cooldown = api.get_param('signal_cooldown', 3)
    
    api.log(f"参数设置:")
    api.log(f"  - 最小笔长度: {min_bi_len}")
    api.log(f"  - 黄金分割比例: {golden_ratio}")
    api.log(f"  - ATR周期: {atr_period}")
    api.log(f"  - ATR止损倍数: {atr_stop_multiplier}")
    api.log(f"  - 基础仓位: {base_volume}手")
    api.log(f"  - 信号冷却期: {signal_cooldown}根K线")
    
    # 重置状态
    g_chanlun_state = ChanlunState()
    
    api.log("策略初始化完成，等待K线数据...")


# ============================================================================
# 策略主函数
# ============================================================================

def chanlun_signal_strategy(api: StrategyAPI):
    """
    缠论多空信号四种形态策略主函数
    
    策略逻辑：
    1. 获取K线数据并更新czsc分析器
    2. 提取笔序列并推导线段端点
    3. 并行检测四类信号
    4. 信号聚合与优先级处理
    5. 执行交易决策
    6. 检查止损止盈
    
    Args:
        api: 策略API对象
    """
    global g_chanlun_state, g_signals_history, g_klines_snapshot, g_zs_history
    
    if not CZSC_AVAILABLE:
        return
    
    # 获取参数
    min_bi_len = api.get_param('min_bi_len', 7)
    golden_ratio = api.get_param('golden_ratio', 1.618)
    atr_period = api.get_param('atr_period', 14)
    atr_stop_multiplier = api.get_param('atr_stop_multiplier', 2.0)
    base_volume = api.get_param('base_volume', 1)
    signal_cooldown = api.get_param('signal_cooldown', 3)
    use_structure_stop = api.get_param('use_structure_stop', True)
    v_reversal_power_ratio = api.get_param('v_reversal_power_ratio', 1.2)
    
    # 获取当前索引和K线数据
    current_idx = api.get_idx()
    klines = api.get_klines()
    g_klines_snapshot = klines  # 更新K线数据快照
    
    # 确保有足够的数据（至少需要50根K线来形成笔）
    min_required_bars = 50
    if len(klines) < min_required_bars:
        if len(klines) % 10 == 0:
            api.log(f"数据准备中... 当前: {len(klines)}/{min_required_bars}")
        return
    
    # 获取数据源信息
    data_source = api.get_data_source(0)
    if data_source is None:
        return
    
    symbol = data_source.symbol
    freq = api.get_param('kline_period', '15m')
    
    # Step 1: 更新czsc分析器
    try:
        raw_bars = kline_to_rawbar(klines, symbol, freq)
        
        if g_chanlun_state.czsc_analyzer is None:
            # 首次初始化
            g_chanlun_state.czsc_analyzer = CZSC(raw_bars, max_bi_num=100)
        else:
            # 增量更新 - 检查是否有新K线
            if len(raw_bars) > len(g_chanlun_state.raw_bars):
                # 只添加新的K线
                new_bars = raw_bars[len(g_chanlun_state.raw_bars):]
                for bar in new_bars:
                    g_chanlun_state.czsc_analyzer.update(bar)
        
        g_chanlun_state.raw_bars = raw_bars
        
    except Exception as e:
        api.log(f"czsc分析器更新失败: {e}")
        return
    
    # Step 2: 获取笔序列并检查是否有更新
    bi_list = g_chanlun_state.czsc_analyzer.bi_list
    
    if len(bi_list) < 3:
        return
    
    # 检查笔序列是否有更新
    if len(bi_list) == g_chanlun_state.last_bi_count:
        # 笔序列无更新，但仍需检查止损
        check_stop_loss(api, g_chanlun_state, atr_period, atr_stop_multiplier, use_structure_stop)
        return
    
    g_chanlun_state.last_bi_count = len(bi_list)
    
    # Step 3: 提取笔端点并推导中枢
    endpoints = extract_bi_endpoints(bi_list)
    g_chanlun_state.bi_endpoints = endpoints
    new_zs = calculate_zs(endpoints)
    g_chanlun_state.current_zs = new_zs
    # 记录新中枢到历史（去重）
    if new_zs is not None:
        if (not g_zs_history or
                g_zs_history[-1].start_dt != new_zs.start_dt or
                g_zs_history[-1].end_dt != new_zs.end_dt):
            g_zs_history.append(new_zs)
    
    # Step 4: 并行检测四类信号
    signals = []
    
    # 检测1类信号
    type1_long = detect_type1_signal(endpoints, 'long')
    if type1_long:
        signals.append(type1_long)
    
    type1_short = detect_type1_signal(endpoints, 'short')
    if type1_short:
        signals.append(type1_short)
    
    # 检测2类信号
    type2_signal = detect_type2_signal(bi_list, endpoints, golden_ratio)
    if type2_signal:
        signals.append(type2_signal)
    
    # 检测3类信号
    type3_signal = detect_type3_signal(endpoints, bi_list)
    if type3_signal:
        signals.append(type3_signal)
    
    # 检测4类信号
    type4_signal = detect_type4_signal(endpoints, bi_list, 
                                        g_chanlun_state.current_signal,
                                        v_reversal_power_ratio)
    if type4_signal:
        signals.append(type4_signal)
    
    # Step 5: 信号聚合
    final_signal = aggregate_signals(signals)
    
    # Step 6: 检查信号冷却期
    if final_signal:
        bars_since_last_signal = current_idx - g_chanlun_state.last_signal_bar
        if bars_since_last_signal < signal_cooldown:
            final_signal = None
    
    # Step 7: 执行交易决策
    current_pos = api.get_pos()
    current_price = api.get_price()
    
    if final_signal:
        execute_trade(api, final_signal, current_pos, base_volume, current_price)
        g_chanlun_state.current_signal = final_signal
        g_chanlun_state.last_signal_bar = current_idx
        
        # 记录信号到历史
        sig_dt = str(klines.index[-1]) if hasattr(klines, 'index') and len(klines) > 0 else str(current_idx)
        g_signals_history.append({
            'datetime':     sig_dt,
            'signal_type':  final_signal.signal_type.name,
            'direction':    final_signal.direction,
            'strength':     round(float(final_signal.strength), 4),
            'price':        round(float(final_signal.price), 4),
            'key_level':    round(float(final_signal.key_level), 4),
            'volume_ratio': round(float(final_signal.volume_ratio), 2),
        })
        
        if current_pos == 0:
            g_chanlun_state.entry_price = current_price
    
    # Step 8: 检查止损止盈
    check_stop_loss(api, g_chanlun_state, atr_period, atr_stop_multiplier, use_structure_stop)


def execute_trade(api: StrategyAPI, signal: ChanlunSignal, current_pos: int, 
                  base_volume: int, current_price: float):
    """
    执行交易决策
    
    Args:
        api: 策略API对象
        signal: 信号对象
        current_pos: 当前持仓
        base_volume: 基础仓位
        current_price: 当前价格
    """
    volume = int(base_volume * signal.volume_ratio)
    if volume < 1:
        volume = 1
    
    signal_name = signal.signal_type.name
    
    if signal.direction > 0:
        # 做多信号
        if current_pos < 0:
            # 先平空
            api.buycover(reason=f"平空后{signal_name}")
            api.log(f"[{signal_name}] 平空仓")
        
        if current_pos <= 0:
            # 开多
            api.buy(volume=volume, order_type='next_bar_open', 
                   reason=f"{signal_name} 做多")
            api.log(f"[{signal_name}] 开多仓 {volume}手 @ {current_price:.2f}, "
                   f"止损位: {signal.key_level:.2f}")
    
    else:
        # 做空信号
        if current_pos > 0:
            # 先平多
            api.sell(reason=f"平多后{signal_name}")
            api.log(f"[{signal_name}] 平多仓")
        
        if current_pos >= 0:
            # 开空
            api.sellshort(volume=volume, order_type='next_bar_open',
                         reason=f"{signal_name} 做空")
            api.log(f"[{signal_name}] 开空仓 {volume}手 @ {current_price:.2f}, "
                   f"止损位: {signal.key_level:.2f}")


def check_stop_loss(api: StrategyAPI, state: ChanlunState, atr_period: int,
                    atr_stop_multiplier: float, use_structure_stop: bool):
    """
    检查止损条件
    
    Args:
        api: 策略API对象
        state: 缠论状态
        atr_period: ATR周期
        atr_stop_multiplier: ATR止损倍数
        use_structure_stop: 是否启用结构止损
    """
    current_pos = api.get_pos()
    
    if current_pos == 0:
        return
    
    current_price = api.get_price()
    
    # 计算ATR
    high = api.get_high()
    low = api.get_low()
    close = api.get_close()
    atr = calculate_atr(high, low, close, atr_period)
    
    if atr <= 0:
        return
    
    stop_triggered = False
    stop_reason = ""
    
    if current_pos > 0:
        # 多头持仓，检查止损
        # ATR止损
        atr_stop = state.entry_price - atr_stop_multiplier * atr
        if current_price <= atr_stop:
            stop_triggered = True
            stop_reason = f"ATR止损 ({atr_stop:.2f})"
        
        # 结构止损
        if use_structure_stop and state.current_signal:
            structure_stop = state.current_signal.key_level
            if current_price <= structure_stop:
                stop_triggered = True
                stop_reason = f"结构止损 ({structure_stop:.2f})"
        
        # 中枢止损
        if state.current_zs and current_price <= state.current_zs.zd:
            stop_triggered = True
            stop_reason = f"中枢破位止损 ({state.current_zs.zd:.2f})"
    
    elif current_pos < 0:
        # 空头持仓，检查止损
        # ATR止损
        atr_stop = state.entry_price + atr_stop_multiplier * atr
        if current_price >= atr_stop:
            stop_triggered = True
            stop_reason = f"ATR止损 ({atr_stop:.2f})"
        
        # 结构止损
        if use_structure_stop and state.current_signal:
            structure_stop = state.current_signal.key_level
            if current_price >= structure_stop:
                stop_triggered = True
                stop_reason = f"结构止损 ({structure_stop:.2f})"
        
        # 中枢止损
        if state.current_zs and current_price >= state.current_zs.zg:
            stop_triggered = True
            stop_reason = f"中枢破位止损 ({state.current_zs.zg:.2f})"
    
    if stop_triggered:
        api.close_all(reason=stop_reason, order_type='next_bar_open')
        api.log(f"触发止损: {stop_reason}, 当前价格: {current_price:.2f}")


# ============================================================================
# 配置区
# ============================================================================

# ============================================================================
# 可视化与信号导出模块
# ============================================================================

def _find_bar_idx(date_index, target):
    """在pandas Index中找最接近target时间的整数位置"""
    try:
        target_ts = pd.Timestamp(str(target))
        pos = date_index.searchsorted(target_ts)
        if pos >= len(date_index):
            pos = len(date_index) - 1
        return int(pos)
    except Exception:
        return None


def save_signals_to_file(signals_history, output_dir='backtest_results',
                         symbol='', period=''):
    """
    将信号历史保存为CSV和JSON文件

    Args:
        signals_history: 信号列表
        output_dir: 输出目录
        symbol: 品种代码
        period: K线周期

    Returns:
        (csv_path, json_path) 或 (None, None)
    """
    if not signals_history:
        print("没有检测到任何信号，跳过保存")
        return None, None

    os.makedirs(output_dir, exist_ok=True)
    ts = _dt_cls.now().strftime('%Y%m%d_%H%M%S')
    base = f"chanlun_signals_{symbol}_{period}_{ts}"
    fieldnames = ['datetime', 'signal_type', 'direction', 'strength',
                  'price', 'key_level', 'volume_ratio']

    # --- CSV ---
    csv_path = os.path.join(output_dir, f"{base}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = _csv_module.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sig in signals_history:
            writer.writerow({k: sig.get(k, '') for k in fieldnames})

    # --- JSON ---
    json_path = os.path.join(output_dir, f"{base}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(signals_history, f, ensure_ascii=False, indent=2, default=str)

    print(f"信号CSV已保存: {os.path.abspath(csv_path)}")
    print(f"信号JSON已保存: {os.path.abspath(json_path)}")
    return csv_path, json_path


def plot_chanlun_chart(klines, bi_list, zs_history, signals_history,
                       symbol='', period='', output_dir='backtest_results'):
    """
    生成缩论分析K线图表

    包含：蜡烛图、笔、线段、中枢矩形、买卖点标注

    Args:
        klines: K线 DataFrame，必需包含 open/high/low/close列，索引为时间
        bi_list: czsc 笔序列
        zs_history: 中枢历史列表
        signals_history: 信号历史列表
        symbol: 品种代码
        period: K线周期
        output_dir: 输出目录

    Returns:
        chart_path: 图表文件路径，失败返回 None
    """
    if klines is None or len(klines) == 0:
        print("没有K线数据，无法生成缩论图表")
        return None

    os.makedirs(output_dir, exist_ok=True)
    df = klines if isinstance(klines, pd.DataFrame) else pd.DataFrame(klines)
    n = len(df)
    date_index = df.index  # DatetimeIndex或类似

    # 是否有成交量
    has_volume = ('volume' in df.columns and
                  not df['volume'].isna().all() and
                  df['volume'].sum() > 0)

    # ---- 创建画布 ----
    if has_volume:
        fig, (ax_main, ax_vol) = plt.subplots(
            2, 1, figsize=(22, 14),
            gridspec_kw={'height_ratios': [4, 1]},
            sharex=True
        )
    else:
        fig, ax_main = plt.subplots(1, 1, figsize=(22, 12))
        ax_vol = None

    fig.suptitle(f"{symbol} {period} 缩论分析图", fontsize=16, fontweight='bold')

    # ---- 绘制蜡烛图 ----
    opens  = df['open'].values
    highs  = df['high'].values
    lows   = df['low'].values
    closes = df['close'].values

    for i in range(n):
        color = '#E53935' if closes[i] >= opens[i] else '#43A047'  # 红涨绻跌
        # 上下影线
        ax_main.plot([i, i], [lows[i], highs[i]],
                    color=color, linewidth=0.8, zorder=1)
        # 实体
        body_lo = min(opens[i], closes[i])
        body_hi = max(opens[i], closes[i])
        body_h  = max(body_hi - body_lo,
                     (highs[i] - lows[i]) * 0.001 if highs[i] > lows[i] else 0.001)
        rect = mpatches.Rectangle(
            (i - 0.35, body_lo), 0.7, body_h,
            facecolor=color, edgecolor=color, linewidth=0, zorder=2
        )
        ax_main.add_patch(rect)

    # ---- 绘制笔（BI）----
    if bi_list and CZSC_AVAILABLE:
        for bi in bi_list:
            try:
                s_idx = _find_bar_idx(date_index, bi.fx_a.dt)
                e_idx = _find_bar_idx(date_index, bi.fx_b.dt)
                if s_idx is None or e_idx is None:
                    continue
                s_price = float(bi.fx_a.fx)
                e_price = float(bi.fx_b.fx)
                bi_color = '#1565C0' if bi.direction == Direction.Up else '#E65100'
                ax_main.plot([s_idx, e_idx], [s_price, e_price],
                            color=bi_color, linewidth=2.2, zorder=4,
                            solid_capstyle='round', alpha=0.9)
                # 笔端点圆点
                ax_main.scatter([s_idx, e_idx], [s_price, e_price],
                               color=bi_color, s=25, zorder=5, alpha=0.9)
            except Exception:
                continue

    # ---- 绘制线段（如czsc支持）----
    if CZSC_AVAILABLE and g_chanlun_state.czsc_analyzer is not None:
        segs = getattr(g_chanlun_state.czsc_analyzer, 'segs',
               getattr(g_chanlun_state.czsc_analyzer, 'seg_list', None))
        if segs:
            for seg in segs:
                try:
                    s_idx = _find_bar_idx(date_index, seg.fx_a.dt)
                    e_idx = _find_bar_idx(date_index, seg.fx_b.dt)
                    if s_idx is None or e_idx is None:
                        continue
                    s_price = float(seg.fx_a.fx)
                    e_price = float(seg.fx_b.fx)
                    seg_color = '#880E4F' if seg.direction == Direction.Up else '#1B5E20'
                    ax_main.plot([s_idx, e_idx], [s_price, e_price],
                                color=seg_color, linewidth=3.0, zorder=3,
                                linestyle='--', alpha=0.65,
                                label='_nolegend_')
                except Exception:
                    continue

    # ---- 绘制中枢（ZS）----
    for zs in zs_history:
        try:
            x0 = _find_bar_idx(date_index, zs.start_dt)
            x1 = _find_bar_idx(date_index, zs.end_dt)
            if x0 is None or x1 is None:
                continue
            if x1 <= x0:
                x1 = x0 + 1
            w = x1 - x0
            h = zs.zg - zs.zd
            if h <= 0:
                continue
            # 中枢矩形
            rect = mpatches.Rectangle(
                (x0, zs.zd), w, h,
                facecolor='#90CAF9', edgecolor='#1565C0',
                alpha=0.25, linewidth=1.5, zorder=2
            )
            ax_main.add_patch(rect)
            # ZG / ZD / ZZ 水平线
            ax_main.hlines(zs.zg, x0, x1, colors='#1565C0', linewidths=1.2,
                          linestyles='--', zorder=3, alpha=0.85)
            ax_main.hlines(zs.zd, x0, x1, colors='#1565C0', linewidths=1.2,
                          linestyles='--', zorder=3, alpha=0.85)
            ax_main.hlines(zs.zz, x0, x1, colors='#7B1FA2', linewidths=1.0,
                          linestyles=':', zorder=3, alpha=0.85)
            # 标签
            ax_main.text(x0 + 0.2, zs.zg, f'ZG {zs.zg:.1f}',
                        fontsize=7, color='#1565C0', va='bottom', zorder=6)
            ax_main.text(x0 + 0.2, zs.zd, f'ZD {zs.zd:.1f}',
                        fontsize=7, color='#1565C0', va='top', zorder=6)
            ax_main.text(x0 + 0.2, zs.zz, f'ZZ {zs.zz:.1f}',
                        fontsize=7, color='#7B1FA2', va='center', zorder=6)
        except Exception:
            continue

    # ---- 标注买卖点 ----
    LONG_COLORS = {
        'TYPE1_LONG': '#D50000', 'TYPE2_LONG': '#B71C1C',
        'TYPE3_LONG': '#FF6D00', 'TYPE4_LONG': '#FF8A65',
    }
    SHORT_COLORS = {
        'TYPE1_SHORT': '#00C853', 'TYPE2_SHORT': '#1B5E20',
        'TYPE3_SHORT': '#64DD17', 'TYPE4_SHORT': '#A5D6A7',
    }
    SIGNAL_LABELS = {
        'TYPE1_LONG':  '1类多',  'TYPE2_LONG':  '2类多',
        'TYPE3_LONG':  '3类多',  'TYPE4_LONG':  'V反多',
        'TYPE1_SHORT': '1类空',  'TYPE2_SHORT': '2类空',
        'TYPE3_SHORT': '3类空',  'TYPE4_SHORT': 'V反空',
    }

    for sig in signals_history:
        try:
            sig_idx = _find_bar_idx(date_index, sig['datetime'])
            if sig_idx is None:
                continue
            stype    = sig['signal_type']
            is_long  = sig['direction'] > 0
            color    = LONG_COLORS.get(stype, '#D50000') if is_long else SHORT_COLORS.get(stype, '#00C853')
            marker   = '^' if is_long else 'v'
            price    = float(sig['price'])
            label    = SIGNAL_LABELS.get(stype, stype)
            v_offset = 12 if is_long else -12

            ax_main.scatter(sig_idx, price, color=color, marker=marker,
                           s=200, zorder=7, edgecolors='black', linewidths=0.5)
            ax_main.annotate(
                label, xy=(sig_idx, price),
                xytext=(0, v_offset), textcoords='offset points',
                fontsize=7, color=color, ha='center', fontweight='bold', zorder=8
            )
        except Exception:
            continue

    # ---- 轴设置 ----
    price_min = float(lows.min())
    price_max = float(highs.max())
    pad = (price_max - price_min) * 0.06
    ax_main.set_ylim(price_min - pad, price_max + pad)
    ax_main.set_xlim(-1, n + 1)
    ax_main.set_ylabel('价格', fontsize=12)
    ax_main.grid(True, alpha=0.2, linewidth=0.5)

    # X轴刻度
    tick_step = max(1, n // 14)
    tick_ids  = list(range(0, n, tick_step))
    if n - 1 not in tick_ids:
        tick_ids.append(n - 1)
    date_labels = [str(date_index[i])[:16] for i in tick_ids]
    ax_main.set_xticks(tick_ids)
    ax_main.set_xticklabels(date_labels, rotation=45, fontsize=8, ha='right')

    # ---- 成交量 ----
    if ax_vol is not None:
        volumes   = df['volume'].values
        vol_colors = ['#E53935' if closes[i] >= opens[i] else '#43A047'
                      for i in range(n)]
        ax_vol.bar(range(n), volumes, color=vol_colors, alpha=0.55, width=0.6)
        ax_vol.set_ylabel('成交量', fontsize=10)
        ax_vol.grid(True, alpha=0.2, linewidth=0.5)
        ax_vol.set_xticks(tick_ids)
        ax_vol.set_xticklabels(date_labels, rotation=45, fontsize=8, ha='right')

    # ---- 图例 ----
    legend_elems = [
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
    ax_main.legend(handles=legend_elems, loc='upper left',
                  fontsize=9, framealpha=0.8, ncol=4)

    # 水印
    ax_main.text(0.01, 0.02, 'by quant789.com', transform=ax_main.transAxes,
                fontsize=13, color='gray', alpha=0.45, zorder=1)

    # ---- 保存 ----
    plt.tight_layout()
    ts_str     = _dt_cls.now().strftime('%Y%m%d_%H%M%S')
    chart_name = f"chanlun_{symbol}_{period}_{ts_str}.png"
    chart_path = os.path.join(output_dir, chart_name)
    plt.savefig(chart_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"缩论分析图表已保存: {os.path.abspath(chart_path)}")
    return chart_path



    # ========== 运行模式 ==========
    RUN_MODE = RunMode.BACKTEST  # 可选: BACKTEST, SIMNOW, REAL_TRADING
    
    # ========== 策略参数 ==========
    strategy_params = {
        'min_bi_len': 7,              # czsc最小笔长度（K线数）
        'golden_ratio': 1.618,        # 2类信号黄金分割倍数阈值
        'atr_period': 14,             # ATR计算周期
        'atr_stop_multiplier': 2.0,   # ATR止损倍数
        'base_volume': 1,             # 基础开仓手数
        'use_structure_stop': True,   # 是否启用缠论结构止损
        'signal_cooldown': 3,         # 信号冷却期（连续信号间最少K线间隔）
        'v_reversal_power_ratio': 1.2, # 4类V反信号要求的最低力度比
        'kline_period': '15',         # K线周期
    }
    
    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        # 数据加载策略：优先使用远程API，若API凭据未配置则自动使用本地数据
        import os
        from ssquant.config.trading_config import get_api_auth
        _api_user, _api_pass = get_api_auth()
        _use_api = bool(_api_user and _api_pass)
        
        _file_path = None
        if not _use_api:
            # API凭据未配置，回退到本地数据文件
            _base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data_cache')
            _real_data = os.path.join(_base_dir, 'au888_1h_real.csv')
            if os.path.exists(_real_data):
                _file_path = _real_data
                print(f"⚠️  API凭据未配置(trading_config.py中API_USERNAME/API_PASSWORD为空)")
                print(f"    回退使用本地真实行情数据: {_file_path}")
            else:
                print("❌ API凭据未配置且无本地数据文件，请在trading_config.py中填入API凭据")
        else:
            print(f"✅ 使用远程API获取数据 (用户: {_api_user})")
        
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            symbol='au888',                   # 合约代码 (连续合约用888后缀)
            start_date='2025-10-15',          # 回测开始日期
            end_date='2026-03-18',            # 回测结束日期
            kline_period='15m',                # K线周期: 1
            adjust_type='1',                  # 复权类型: '0'不复权, '1'后复权
            
            # -------- 合约参数 --------
            price_tick=0.02,                  # 最小变动价位 (黄金=0.02)
            contract_multiplier=1000,         # 合约乘数 (黄金=1000克/手)
            slippage_ticks=1,                 # 滑点跳数
            
            # -------- 资金配置 --------
            initial_capital=100000,           # 初始资金 (元)
            commission=0.0001,                # 手续费率 (万分之一)
            margin_rate=0.1,                  # 保证金率 (10%)
        )
        # 添加本地数据文件路径（API凭据未配置时的回退方案）
        if _file_path:
            config['file_path'] = _file_path
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称
            server_name='电信1',              # 服务器: '电信1','电信2','移动','TEST'
            
            # -------- 合约配置 --------
            symbol='au2506',                  # 交易合约代码
            kline_period='15m',               # K线周期
            
            # -------- 交易参数 --------
            price_tick=0.02,                  # 最小变动价位
            order_offset_ticks=-5,            # 委托偏移跳数
            
            # -------- 智能算法交易配置 --------
            algo_trading=False,               # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,                    # 最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 预加载历史K线
            history_lookback_bars=200,        # 预加载K线数量
            adjust_type='1',                  # 复权类型
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调模式
            
            # -------- 数据保存配置 --------
            save_kline_csv=True,              # 保存K线到CSV
            save_kline_db=True,               # 保存K线到数据库
            save_tick_csv=False,              # 保存TICK到CSV
            save_tick_db=False,               # 保存TICK到数据库
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称
            
            # -------- 合约配置 --------
            symbol='au2506',                  # 交易合约代码
            kline_period='15m',               # K线周期
            
            # -------- 交易参数 --------
            price_tick=0.02,                  # 最小变动价位
            order_offset_ticks=-10,           # 委托偏移跳数
            
            # -------- 智能算法交易配置 --------
            algo_trading=True,                # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,                    # 最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 预加载历史K线
            history_lookback_bars=200,        # 预加载K线数量
            adjust_type='1',                  # 复权类型
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调模式
            
            # -------- 数据保存配置 --------
            save_kline_csv=False,             # 保存K线到CSV
            save_kline_db=False,              # 保存K线到数据库
            save_tick_csv=False,              # 保存TICK到CSV
            save_tick_db=False,               # 保存TICK到数据库
        )
    
    # ========== 创建运行器并执行 ==========
    print("\n" + "=" * 80)
    print("缠论多空信号四种形态策略 - 统一运行版本")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"K线周期: {config['kline_period']}")
    print(f"策略参数: 黄金分割={strategy_params['golden_ratio']}, "
          f"ATR止损倍数={strategy_params['atr_stop_multiplier']}")
    print("=" * 80 + "\n")
    
    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    
    # 设置配置
    runner.set_config(config)
    
    # 运行策略
    try:
        results = runner.run(
            strategy=chanlun_signal_strategy,
            initialize=initialize,
            strategy_params=strategy_params
        )

        # ============================================================
        # 回测完成后：可视化 + 信号导出
        # ============================================================
        if RUN_MODE == RunMode.BACKTEST:
            _symbol = config.get('symbol', 'unknown')
            _period = config.get('kline_period', 'unknown')
            _out    = 'backtest_results'

            print("\n" + "=" * 60)
            print("缩论分析后处理")
            print("=" * 60)
            print(f"共检测到 {len(g_signals_history)} 个缩论信号")
            print(f"中枢历史条数: {len(g_zs_history)}")

            # 1. 生成缩论图表
            bi_list = (g_chanlun_state.czsc_analyzer.bi_list
                       if g_chanlun_state.czsc_analyzer is not None else [])
            plot_chanlun_chart(
                klines=g_klines_snapshot,
                bi_list=bi_list,
                zs_history=g_zs_history,
                signals_history=g_signals_history,
                symbol=_symbol,
                period=_period,
                output_dir=_out,
            )

            # 2. 导出信号文件
            save_signals_to_file(
                signals_history=g_signals_history,
                output_dir=_out,
                symbol=_symbol,
                period=_period,
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
