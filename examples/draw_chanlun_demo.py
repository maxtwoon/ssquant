"""
缠论买卖点完整结构示意图（合成 K 线）

输出参考附图，包含：
- 两个 30 分钟级别中枢（下跌段震荡）
- 一买、二买、三买（点 0, 2, 6）
- 新中枢 A（点 1-2-3-4 构成）
- 笔、线段（趋势线段画出）
- 关键点编号 0-7
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import platform

_sys = platform.system()
if _sys == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
elif _sys == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.family'] = 'sans-serif'

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                       'backtest_results')
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================================
# 1) 设计关键锚点（笔的端点）
# ============================================================================
# 设计意图：
#  - bar 0-25:   下跌段 + 第一个 30 分钟级别中枢震荡
#  - bar 25-50:  下跌段 + 第二个 30 分钟级别中枢震荡
#  - bar 50:     一买（点 0）— 下跌段终结的最低点
#  - bar 50-150: 上涨过程，期间形成 A 中枢，给出二买、三买
ANCHORS = [
    # (bar, price, label)  — label 用于后面打编号
    (0, 110, None),
    # 第一个 30 分钟中枢区间：bar 8-25，价格 102-108
    (8, 105, None),
    (12, 108, None),
    (15, 103, None),
    (18, 107, None),
    (22, 102, None),
    (25, 95, None),
    # 第二个 30 分钟中枢区间：bar 30-45，价格 92-98
    (30, 95, None),
    (33, 98, None),
    (37, 93, None),
    (41, 97, None),
    (45, 92, None),
    # 一买点：bar 50
    (50, 80, '0'),
    # 上涨段
    (65, 95, '1'),      # 点 1：第一波反弹高点
    (75, 86, '2'),      # 二买点
    (90, 96, '3'),      # 点 3
    (100, 88, '4'),     # 点 4（构成新中枢 A）
    (115, 106, '5'),    # 点 5：突破新中枢 A 的上沿
    (125, 99, '6'),     # 三买点：回踩不破新中枢上沿
    (145, 115, '7'),    # 点 7：三买后的爆发
]


def generate_kline(anchors, noise_scale=0.4):
    """从锚点生成 OHLC K 线数据（线性插值 + 小噪声 + 合理影线）"""
    xs = np.array([a[0] for a in anchors])
    ys = np.array([a[1] for a in anchors])
    all_x = np.arange(0, anchors[-1][0] + 1)
    base_close = np.interp(all_x, xs, ys)
    np.random.seed(7)
    close = base_close + np.random.normal(0, noise_scale, len(all_x))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    body = np.abs(close - open_)
    high = np.maximum(close, open_) + np.abs(
        np.random.normal(body.mean() * 1.0, body.mean() * 0.5, len(close)))
    low = np.minimum(close, open_) - np.abs(
        np.random.normal(body.mean() * 1.0, body.mean() * 0.5, len(close)))
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close})


def draw():
    df = generate_kline(ANCHORS)
    n = len(df)

    fig, ax = plt.subplots(figsize=(20, 10))

    # ---- 蜡烛图 ----
    opens, highs, lows, closes = df['open'].values, df['high'].values, \
                                  df['low'].values, df['close'].values
    for i in range(n):
        color = '#E53935' if closes[i] >= opens[i] else '#43A047'
        ax.plot([i, i], [lows[i], highs[i]], color=color,
                linewidth=0.7, zorder=1)
        body_lo = min(opens[i], closes[i])
        body_hi = max(opens[i], closes[i])
        body_h = max(body_hi - body_lo, 0.05)
        ax.add_patch(mpatches.Rectangle(
            (i - 0.35, body_lo), 0.7, body_h,
            facecolor=color, edgecolor=color, linewidth=0, zorder=2))

    # ---- 笔（连接所有锚点）----
    bi_xs = [a[0] for a in ANCHORS]
    bi_ys = [a[1] for a in ANCHORS]
    for i in range(len(ANCHORS) - 1):
        rising = bi_ys[i + 1] > bi_ys[i]
        color = '#1565C0' if rising else '#E65100'
        ax.plot([bi_xs[i], bi_xs[i + 1]], [bi_ys[i], bi_ys[i + 1]],
                color=color, linewidth=2.0, zorder=4,
                solid_capstyle='round', alpha=0.85)

    # ---- 第一个 30 分钟中枢矩形（外框）----
    for x0, x1, y0, y1, label in [(7, 23, 102, 108, '30 分钟'),
                                    (29, 46, 92, 98, '30 分钟')]:
        ax.add_patch(mpatches.Rectangle(
            (x0, y0), x1 - x0, y1 - y0,
            facecolor='none', edgecolor='black',
            linewidth=1.2, zorder=3))
        ax.text((x0 + x1) / 2, y0 - 2.5, label,
                fontsize=12, ha='center', color='black', fontweight='bold')

    # ---- 新中枢 A（点 1-2-3-4 构成）----
    # ZG = min(高点) = min(95, 96) = 95
    # ZD = max(低点) = max(86, 88) = 88
    zs_x0, zs_x1, zs_zg, zs_zd = 64, 116, 95, 88
    ax.add_patch(mpatches.Rectangle(
        (zs_x0, zs_zd), zs_x1 - zs_x0, zs_zg - zs_zd,
        facecolor='#FFE082', edgecolor='#F57F17',
        alpha=0.30, linewidth=1.5, zorder=2))
    ax.hlines(zs_zg, zs_x0, zs_x1, colors='#F57F17',
              linewidths=1.2, linestyles='--', zorder=3, alpha=0.85)
    ax.hlines(zs_zd, zs_x0, zs_x1, colors='#F57F17',
              linewidths=1.2, linestyles='--', zorder=3, alpha=0.85)
    # 中枢上沿延伸虚线（标识三买的"不破中枢上沿"）
    ax.hlines(zs_zg, zs_x1, 130, colors='gray',
              linewidths=1.0, linestyles=':', zorder=3, alpha=0.7)
    ax.text((zs_x0 + zs_x1) / 2, zs_zg + 5.5, 'A 新中枢',
            fontsize=16, ha='center', color='#E65100', fontweight='bold')

    # ---- 标号 + 买点标签 ----
    LABEL_INFO = {
        '0': '一买',  # 趋势反转，结束下跌
        '2': '二买',  # 回踩不破一买低点
        '6': '三买',  # 突破中枢后回踩不破中枢上沿
    }
    for x, y, num in [(a[0], a[1], a[2]) for a in ANCHORS if a[2] is not None]:
        ax.scatter(x, y, s=110, c='#616161', edgecolors='black',
                   linewidths=1.2, zorder=6)
        # 编号
        ax.text(x + 1.8, y, num, fontsize=14, fontweight='bold',
                va='center', color='black', zorder=7)
        # 一买/二买/三买
        if num in LABEL_INFO:
            ax.text(x, y - 4.5, LABEL_INFO[num], fontsize=13,
                    ha='center', color='#C62828', fontweight='bold', zorder=7)

    # ---- 轴 + 标题 + 图例 ----
    price_min, price_max = df['low'].min(), df['high'].max()
    pad = (price_max - price_min) * 0.06
    ax.set_ylim(price_min - pad, price_max + pad)
    ax.set_xlim(-2, n + 2)
    ax.set_xlabel('K 线序号', fontsize=12)
    ax.set_ylabel('价格', fontsize=12)
    ax.set_title('缠论买卖点完整结构示意图 — 一买 / 二买 / 三买',
                 fontsize=17, fontweight='bold', pad=15)
    ax.grid(True, alpha=0.25, linewidth=0.5)

    legend_items = [
        mpatches.Patch(facecolor='#E53935', label='阳线（涨）'),
        mpatches.Patch(facecolor='#43A047', label='阴线（跌）'),
        Line2D([0], [0], color='#1565C0', linewidth=2.5, label='上升笔'),
        Line2D([0], [0], color='#E65100', linewidth=2.5, label='下降笔'),
        mpatches.Patch(facecolor='#FFE082', edgecolor='#F57F17', alpha=0.5,
                       label='新中枢 A（点 1-2-3-4 构成）'),
        mpatches.Patch(facecolor='none', edgecolor='black',
                       label='30 分钟级别中枢'),
        Line2D([0], [0], marker='o', color='#616161', markersize=10,
               linestyle='', label='关键端点'),
    ]
    ax.legend(handles=legend_items, loc='lower right', fontsize=11,
              framealpha=0.9, ncol=2)

    # 副说明文字（左上角）
    explanation = (
        '一买 = 趋势反转底（下跌段终结）\n'
        '二买 = 一买后首次回调，不破一买低点\n'
        '三买 = 突破新中枢上沿后，回踩不破该上沿'
    )
    ax.text(0.012, 0.97, explanation, transform=ax.transAxes,
            fontsize=11, verticalalignment='top',
            bbox=dict(boxstyle='round,pad=0.6',
                      facecolor='#FFFFFF', edgecolor='#BDBDBD', alpha=0.95))

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, 'chanlun_buy_points_demo.png')
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"[OK] 保存至: {os.path.abspath(out_path)}")
    return out_path


if __name__ == "__main__":
    draw()
