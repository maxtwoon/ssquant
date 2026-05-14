"""
按信号类型分组分析胜率与盈亏。

读取最近一次回测的信号 CSV + 原始 K 线，对每个信号计算前瞻 N 根收益，
然后按 signal_type 分组统计：信号数、平均收益、命中率（多头看涨/空头看跌）、平均回撤。

输出 backtest_results/signal_quality_by_type.csv
"""
import glob
import os
import sqlite3
import sys
from collections import defaultdict

import pandas as pd
import numpy as np

# 路径设置
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_DB = os.path.join(_PROJ_ROOT, 'data_cache', 'kline_data.db')
_RESULTS = os.path.join(_PROJ_ROOT, 'backtest_results')

# 评估前瞻 K 线数（5m × 20 = 100 分钟，约 1.5 小时）
LOOKAHEAD_BARS = [10, 20, 40]  # 多窗口同时统计


def load_latest_signals_csv():
    """找到最近的 chanlun_signals_*.csv"""
    pattern = os.path.join(_RESULTS, 'chanlun_signals_au888_*.csv')
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"未找到信号 CSV: {pattern}")
    latest = files[-1]
    print(f"[INFO] 信号文件: {latest}")
    return pd.read_csv(latest, encoding='utf-8-sig')


def load_klines():
    """从 SQLite 读 au888 5m 数据"""
    conn = sqlite3.connect(_DB)
    df = pd.read_sql_query(
        "SELECT datetime, open, high, low, close, volume FROM au888_5M_raw ORDER BY datetime ASC",
        conn,
    )
    conn.close()
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df


def forward_return(klines: pd.DataFrame, sig_time, direction: int, n_bars: int):
    """从 sig_time 之后第 1 根开盘价进场，n 根后收盘价离场，返回百分比收益（带方向）"""
    sig_ts = pd.Timestamp(sig_time)
    # 找到 sig_time 之后的第一根 K 线
    pos = klines['datetime'].searchsorted(sig_ts)
    if pos >= len(klines) - 1:
        return None
    entry_pos = pos + 1  # 下一根 K 线开盘进场
    exit_pos = entry_pos + n_bars
    if exit_pos >= len(klines):
        return None
    entry_price = klines.iloc[entry_pos]['open']
    exit_price = klines.iloc[exit_pos]['close']
    raw_return = (exit_price - entry_price) / entry_price
    return raw_return * direction  # 多头方向不变，空头取反 → 正值=对方向


def main():
    signals = load_latest_signals_csv()
    print(f"[INFO] 信号总数: {len(signals)}")
    print(f"[INFO] 信号类型分布:\n{signals['signal_type'].value_counts().to_string()}\n")

    klines = load_klines()
    print(f"[INFO] K 线总数: {len(klines)}\n")

    # 按 (signal_type, lookahead) 计算前瞻收益
    rows = []
    for sig_type, group in signals.groupby('signal_type'):
        row = {'signal_type': sig_type, '信号数': len(group)}
        for n in LOOKAHEAD_BARS:
            rets = []
            for _, sig in group.iterrows():
                r = forward_return(klines, sig['datetime'], int(sig['direction']), n)
                if r is not None:
                    rets.append(r)
            rets = np.array(rets)
            if len(rets) > 0:
                win_rate = (rets > 0).mean() * 100
                avg_ret = rets.mean() * 100      # 百分比
                med_ret = np.median(rets) * 100
                std_ret = rets.std() * 100
                # 期望收益 = 胜率×平均盈利 - 亏率×平均亏损 — 直接 mean 就是
                row[f'胜率_{n}bar'] = round(win_rate, 2)
                row[f'平均收益%_{n}bar'] = round(avg_ret, 4)
                row[f'中位收益%_{n}bar'] = round(med_ret, 4)
                row[f'波动%_{n}bar'] = round(std_ret, 4)
            else:
                row[f'胜率_{n}bar'] = None
                row[f'平均收益%_{n}bar'] = None
                row[f'中位收益%_{n}bar'] = None
                row[f'波动%_{n}bar'] = None
        rows.append(row)

    result_df = pd.DataFrame(rows)

    # 按"20bar 平均收益"排序
    if '平均收益%_20bar' in result_df.columns:
        result_df = result_df.sort_values('平均收益%_20bar', ascending=False)

    print("=" * 100)
    print("按信号类型分组的前瞻收益统计")
    print("=" * 100)
    print(result_df.to_string(index=False))
    print()

    out_path = os.path.join(_RESULTS, 'signal_quality_by_type.csv')
    result_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"[OK] 已保存: {out_path}")

    # 简单总结：哪些信号类型应该禁用
    print("\n" + "=" * 100)
    print("建议（基于 20-bar 平均收益）")
    print("=" * 100)
    if '平均收益%_20bar' in result_df.columns:
        keep = result_df[result_df['平均收益%_20bar'] > 0]
        drop = result_df[result_df['平均收益%_20bar'] <= 0]
        print(f"\n✓ 应保留（期望收益 > 0）: {keep['signal_type'].tolist()}")
        print(f"✗ 应禁用（期望收益 ≤ 0）: {drop['signal_type'].tolist()}")


if __name__ == "__main__":
    main()
