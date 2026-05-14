"""
多周期K线派生器 - 从1M K线实时派生 5M, 15M, 30M, 1H, 1D 等任意周期

客户端本地聚合：
  服务端只推送 1M K线，客户端用此类实时派生任意 N 分钟/小时/日线周期。
  策略可以使用 2M、3M、7M、4H 等任意周期，无需服务端配合。

聚合规则:
  - OHLCV: open 取首根1M, high=max, low=min, close 取末根1M
  - volume / amount: 累加
  - openint: 累加 (各1M净变化之和 = 整周期净变化)
  - cumulative_openint: 取末根1M的值
  - 订单流(B/S/多开/空开/...): 累加
  - 深度: open_bidp/askp 取首根, close_bidp/askp 取末根
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Tuple

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False


# 订单流字段列表（用于累加）
ORDER_FLOW_FIELDS = [
    '开仓', '平仓', '多开', '空开', '多平', '空平',
    '双开', '双平', '双换', 'B', 'S', '未知',
]


class MultiPeriodAggregator:
    """
    多周期K线派生器

    接收已完成的1M K线，实时派生出任意高周期K线。
    """

    def __init__(self,
                 symbol: str,
                 periods: List[str] = None,
                 on_kline_complete: Callable = None):
        """
        Args:
            symbol: 合约代码
            periods: 需要派生的周期列表（不含1M），如 ["5M", "15M", "30M", "1H", "1D"]
            on_kline_complete: K线完成回调 callback(symbol, period, kline_dict)
        """
        self.symbol = symbol
        self.periods = [p for p in (periods or ["5M", "15M", "30M", "1H", "1D"]) if p.upper() != "1M"]
        self.on_kline_complete = on_kline_complete

        self.current_klines: Dict[str, Optional[dict]] = {p: None for p in self.periods}
        self.current_kline_times: Dict[str, Optional[datetime]] = {p: None for p in self.periods}

    def add_period(self, period: str):
        """动态添加一个派生周期"""
        p = period.upper()
        if p != "1M" and p not in self.periods:
            self.periods.append(p)
            self.current_klines[p] = None
            self.current_kline_times[p] = None

    def on_1m_complete(self, kline_1m: dict) -> List[Tuple[str, dict]]:
        """
        接收一根已完成的1M K线，更新所有派生周期。

        Returns:
            已完成的高周期K线列表 [(period, kline_dict), ...]
        """
        dt = kline_1m.get('datetime')
        if dt is None:
            return []

        # 确保 dt 是 datetime 对象
        if isinstance(dt, str):
            try:
                dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return []

        completed = []

        for period in self.periods:
            period_time = self._get_period_timestamp(dt, period)
            current_time = self.current_kline_times[period]

            if current_time is None or period_time > current_time:
                # 新周期开始 → 完成上一根
                prev_kline = self.current_klines[period]
                if prev_kline is not None:
                    completed_kline = prev_kline.copy()
                    completed.append((period, completed_kline))
                    if self.on_kline_complete:
                        self.on_kline_complete(self.symbol, period, completed_kline)

                self.current_klines[period] = self._new_kline_from_1m(kline_1m, period_time)
                self.current_kline_times[period] = period_time
            else:
                # 同一周期 → 更新
                kline = self.current_klines[period]
                if kline is not None:
                    self._merge_1m_into(kline, kline_1m)

        return completed

    def get_current_kline(self, period: str) -> Optional[dict]:
        """获取指定周期正在形成的K线"""
        return self.current_klines.get(period)

    def force_complete_all(self) -> List[Tuple[str, dict]]:
        """强制完成所有周期的当前K线"""
        completed = []
        for period in self.periods:
            kline = self.current_klines[period]
            if kline is not None:
                completed_kline = kline.copy()
                completed.append((period, completed_kline))
                if self.on_kline_complete:
                    self.on_kline_complete(self.symbol, period, completed_kline)
                self.current_klines[period] = None
                self.current_kline_times[period] = None
        return completed

    # ========== 内部方法 ==========

    @staticmethod
    def _get_period_timestamp(dt: datetime, period: str) -> datetime:
        """根据K线周期获取K线时间戳（向下取整）"""
        period_lower = period.lower()

        min_match = re.match(r'^(\d+)(m|min)$', period_lower)
        if min_match:
            minutes = int(min_match.group(1))
            if minutes < 60:
                new_minute = (dt.minute // minutes) * minutes
                return dt.replace(minute=new_minute, second=0, microsecond=0)
            else:
                # ≥60 分钟：用当天总分钟数做整除，支持 65m/80m/120m 等任意周期
                total_minutes = dt.hour * 60 + dt.minute
                period_start = (total_minutes // minutes) * minutes
                new_hour, new_minute = divmod(period_start, 60)
                return dt.replace(hour=new_hour, minute=new_minute, second=0, microsecond=0)

        hour_match = re.match(r'^(\d+)(h|hour)$', period_lower)
        if hour_match:
            hours = int(hour_match.group(1))
            new_hour = (dt.hour // hours) * hours
            return dt.replace(hour=new_hour, minute=0, second=0, microsecond=0)

        # 日线归属规则：夜盘(21:00-23:59)归属当天，凌晨(00:00-02:30)归属前一天
        if period_lower in ['1d', 'd', 'day']:
            if dt.hour < 5:
                # 凌晨夜盘(00:00-02:30)：归属前一自然日
                prev_day = dt - timedelta(days=1)
                return prev_day.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                return dt.replace(hour=0, minute=0, second=0, microsecond=0)

        return dt.replace(second=0, microsecond=0)

    def _new_kline_from_1m(self, kline_1m: dict, period_time: datetime) -> dict:
        """从一根1M K线创建新的高周期K线"""
        kline = {
            'datetime': period_time,
            'symbol': self.symbol,
            'open': kline_1m.get('open', 0),
            'high': kline_1m.get('high', 0),
            'low': kline_1m.get('low', 0),
            'close': kline_1m.get('close', 0),
            'volume': kline_1m.get('volume', 0),
            'amount': kline_1m.get('amount', 0),
            'openint': kline_1m.get('openint', 0),
            'cumulative_openint': kline_1m.get('cumulative_openint', 0),
            'open_bidp': kline_1m.get('open_bidp', 0),
            'open_askp': kline_1m.get('open_askp', 0),
            'close_bidp': kline_1m.get('close_bidp', 0),
            'close_askp': kline_1m.get('close_askp', 0),
        }
        for field in ORDER_FLOW_FIELDS:
            kline[field] = kline_1m.get(field, 0)
        return kline

    @staticmethod
    def _merge_1m_into(kline: dict, kline_1m: dict):
        """将一根1M K线合并到正在形成的高周期K线"""
        kline['high'] = max(kline['high'], kline_1m.get('high', 0))
        kline['low'] = min(kline['low'], kline_1m.get('low', float('inf')))
        kline['close'] = kline_1m.get('close', kline['close'])

        kline['volume'] += kline_1m.get('volume', 0)
        kline['amount'] += kline_1m.get('amount', 0)
        kline['openint'] += kline_1m.get('openint', 0)
        kline['cumulative_openint'] = kline_1m.get('cumulative_openint', 0)

        kline['close_bidp'] = kline_1m.get('close_bidp', 0)
        kline['close_askp'] = kline_1m.get('close_askp', 0)

        for field in ORDER_FLOW_FIELDS:
            kline[field] = kline.get(field, 0) + kline_1m.get(field, 0)


# ========================================================================
# 批量聚合函数（DataFrame 级别，用于历史数据从 1M 聚合到 N 周期）
# ========================================================================

def _get_period_start(dt, period: str):
    """
    计算某个 datetime 所属的目标周期开始时间。
    与 MultiPeriodAggregator._get_period_timestamp 保持一致的规则。
    """
    if isinstance(dt, str):
        dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    # pandas Timestamp → python datetime
    if _HAS_PANDAS and isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()

    period_lower = period.lower()

    min_match = re.match(r'^(\d+)(m|min)$', period_lower)
    if min_match:
        minutes = int(min_match.group(1))
        if minutes < 60:
            new_minute = (dt.minute // minutes) * minutes
            return dt.replace(minute=new_minute, second=0, microsecond=0)
        else:
            # ≥60 分钟：用当天总分钟数做整除，支持 65m/80m/120m 等任意周期
            total_minutes = dt.hour * 60 + dt.minute
            period_start = (total_minutes // minutes) * minutes
            new_hour, new_minute = divmod(period_start, 60)
            return dt.replace(hour=new_hour, minute=new_minute, second=0, microsecond=0)

    hour_match = re.match(r'^(\d+)(h|hour)$', period_lower)
    if hour_match:
        hours = int(hour_match.group(1))
        new_hour = (dt.hour // hours) * hours
        return dt.replace(hour=new_hour, minute=0, second=0, microsecond=0)

    # 日线归属规则：夜盘(21:00-23:59)归属当天，凌晨(00:00-02:30)归属前一天
    if period_lower in ['1d', 'd', 'day']:
        if dt.hour < 5:
            prev_day = dt - timedelta(days=1)
            return prev_day.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    return dt.replace(second=0, microsecond=0)


def aggregate_1m_to_period(df_1m, target_period: str):
    """
    批量聚合：将 1M DataFrame 聚合为目标周期 DataFrame。
    
    与实时 MultiPeriodAggregator 使用完全相同的时间对齐规则，
    确保回测和实盘产出的K线完全一致。
    
    Args:
        df_1m: 1M K线 DataFrame（datetime 为索引或列）
        target_period: 目标周期，如 '5M', '15M', '30M', '1H', '1D'
        
    Returns:
        聚合后的 DataFrame（datetime 索引）。如果输入为空或 target_period 是 1M，
        直接返回原数据。
    """
    if not _HAS_PANDAS:
        raise ImportError("aggregate_1m_to_period 需要 pandas")

    if df_1m is None or df_1m.empty:
        return df_1m

    # 如果目标周期就是 1M，直接返回
    normalized = target_period.strip().upper()
    if normalized in ('1M', '1MIN'):
        return df_1m

    # 确保 datetime 是普通列（非索引），避免歧义
    df = df_1m.copy()
    if 'datetime' not in df.columns:
        if df.index.name == 'datetime':
            df = df.reset_index()
        else:
            print(f"[aggregate_1m_to_period] 警告: 找不到 datetime 列")
            return df_1m
    elif df.index.name == 'datetime':
        # datetime 同时是索引和列，重置索引并去掉重复
        df = df.reset_index(drop=True)

    # 确保 datetime 是 datetime 类型
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')

    # 计算每根 1M bar 所属的目标周期开始时间
    df['_period_start'] = df['datetime'].apply(lambda dt: _get_period_start(dt, target_period))

    # 构建聚合规则
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }

    # 可选的求和列
    optional_sum_cols = [
        'amount', 'B', 'S',
        '开仓', '平仓', '多开', '空开', '多平', '空平',
        '双开', '双平', '双换', '未知',
    ]
    for col in optional_sum_cols:
        if col in df.columns:
            agg_dict[col] = 'sum'

    # openint (持仓量变化) 求和
    if 'openint' in df.columns:
        agg_dict['openint'] = 'sum'

    # cumulative_openint 取最后一个值
    if 'cumulative_openint' in df.columns:
        agg_dict['cumulative_openint'] = 'last'

    # 保留合约标识，供本地复权和调试使用
    if 'symbol' in df.columns:
        agg_dict['symbol'] = 'last'
    if 'real_symbol' in df.columns:
        agg_dict['real_symbol'] = 'last'

    # 深度数据
    if 'open_bidp' in df.columns:
        agg_dict['open_bidp'] = 'first'
    if 'open_askp' in df.columns:
        agg_dict['open_askp'] = 'first'
    if 'close_bidp' in df.columns:
        agg_dict['close_bidp'] = 'last'
    if 'close_askp' in df.columns:
        agg_dict['close_askp'] = 'last'

    # 只聚合实际存在的列
    agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}

    if not agg_dict:
        print(f"[aggregate_1m_to_period] 警告: 没有可聚合的列")
        return df_1m

    # 执行分组聚合
    result = df.groupby('_period_start').agg(agg_dict)
    result.index.name = 'datetime'

    print(f"[本地聚合] 1M({len(df)}) -> {target_period}({len(result)})")

    return result
