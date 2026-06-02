"""
缠论买卖点完整结构示意图（空头镜像版）

输出包含：
- 两个 30 分钟级别中枢（上涨段震荡）
- 一卖、二卖、三卖（点 0, 2, 6）— 上涨段顶部的卖出点
- 新中枢 A（点 1-2-3-4 构成）
- 笔、线段、关键点编号 0-7
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
# 锚点设计（与多头版完全镜像）
# ============================================================================
ANCHORS = [
    (0, 80, None),
    # 第一个 30 分钟中枢区间：bar 8-23，价格 85-92
    (8, 88, None),
    (12, 85, None),
    (15, 90, None),
    (18, 86, None),
    (22, 91, None),
    (25, 99, None),
    # 第二个 30 分钟中枢区间：bar 30-45，价格 96-102
    (30, 98, None),
    (33, 95, None),
    (37, 100, None),
    (41, 96, None),
    (45, 101, None),
    # 一卖点：bar 50（上涨段最高点）
    (50, 115, '0'),
    # 下跌段
    (65, 100, '1'),     # 点 1：第一波下跌低点
    (75, 110, '2'),     # 二卖点
    (90, 99, '3'),      # 点 3
    (100, 108, '4'),    # 点 4（构成新中枢 A）
    (115, 90, '5'),     # 点 5：跌破新中枢 A 的下沿
    (125, 97, '6'),     # 三卖点：反抽不破新中枢下沿
    (145, 80, '7'),     # 点 7：三卖后的下跌
]


def generate_kline(anchors, noise_scale=0.4):
    xs = np.array([a[0] for a in anchors])
    ys = np.array([a[1] for a in anchors])
    all_x = np.arange(0, anchors[-1][0] + 1)
    base_close = np.interp(all_x, xs, ys)
    np.random.seed(11)
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

    # ---- 蜡烛 ----
    opens, highs, lows, closes = df['open'].values, df['high'].values, \
                                  df['low'].values, df['close'].values
    for i in range(n):
        color = '#E53935' if closes[i] >= opens[i] else '#43A047'
        ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.7, zorder=1)
        body_lo, body_hi = min(opens[i], closes[i]), max(opens[i], closes[i])
        body_h = max(body_hi - body_lo, 0.05)
        ax.add_patch(mpatches.Rectangle((i - 0.35, body_lo), 0.7, body_h,
                                         facecolor=color, edgecolor=color,
                                         linewidth=0, zorder=2))

    # ---- 笔 ----
    bi_xs = [a[0] for a in ANCHORS]
    bi_ys = [a[1] for a in ANCHORS]
    for i in range(len(ANCHORS) - 1):
        rising = bi_ys[i + 1] > bi_ys[i]
        color = '#1565C0' if rising else '#E65100'
        ax.plot([bi_xs[i], bi_xs[i + 1]], [bi_ys[i], bi_ys[i + 1]],
                color=color, linewidth=2.0, zorder=4, solid_capstyle='round',
                alpha=0.85)

    # ---- 两个 30 分钟级别中枢 ----
    for x0, x1, y0, y1, label in [(7, 23, 85, 92, '30 分钟'),
                                    (29, 46, 95, 102, '30 分钟')]:
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                                         facecolor='none', edgecolor='black',
                                         linewidth=1.2, zorder=3))
        ax.text((x0 + x1) / 2, y1 + 1.8, label, fontsize=12, ha='center',
                color='black', fontweight='bold')

    # ---- 新中枢 A（点 1-2-3-4，方向相反）----
    # 多头版：ZG=min(高点), ZD=max(低点)，下沿是支撑
    # 空头版：A 中枢同样定义，但三卖判定看的是"不破下沿"
    # 点 1=100, 2=110, 3=99, 4=108
    # ZG = min(110, 108) = 108, ZD = max(100, 99) = 100
    zs_x0, zs_x1, zs_zg, zs_zd = 64, 116, 110, 99
    ax.add_patch(mpatches.Rectangle((zs_x0, zs_zd), zs_x1 - zs_x0,
                                     zs_zg - zs_zd,
                                     facecolor='#FFE082', edgecolor='#F57F17',
                                     alpha=0.30, linewidth=1.5, zorder=2))
    ax.hlines(zs_zg, zs_x0, zs_x1, colors='#F57F17', linewidths=1.2,
              linestyles='--', zorder=3, alpha=0.85)
    ax.hlines(zs_zd, zs_x0, zs_x1, colors='#F57F17', linewidths=1.2,
              linestyles='--', zorder=3, alpha=0.85)
    # 中枢下沿延伸虚线（凸显"不破中枢下沿"）
    ax.hlines(zs_zd, zs_x1, 130, colors='gray', linewidths=1.0,
              linestyles=':', zorder=3, alpha=0.7)
    ax.text((zs_x0 + zs_x1) / 2, zs_zd - 5, 'A 新中枢', fontsize=16,
            ha='center', color='#E65100', fontweight='bold')

    # ---- 标号 + 卖点标签 ----
    LABEL_INFO = {'0': '一卖', '2': '二卖', '6': '三卖'}
    for x, y, num in [(a[0], a[1], a[2]) for a in ANCHORS if a[2] is not None]:
        ax.scatter(x, y, s=110, c='#616161', edgecolors='black',
                   linewidths=1.2, zorder=6)
        ax.text(x + 1.8, y, num, fontsize=14, fontweight='bold', va='center',
                color='black', zorder=7)
        if num in LABEL_INFO:
            ax.text(x, y + 3.5, LABEL_INFO[num], fontsize=13, ha='center',
                    color='#1565C0', fontweight='bold', zorder=7)

    # ---- 轴 + 标题 + 图例 ----
    price_min, price_max = df['low'].min(), df['high'].max()
    pad = (price_max - price_min) * 0.06
    ax.set_ylim(price_min - pad, price_max + pad)
    ax.set_xlim(-2, n + 2)
    ax.set_xlabel('K 线序号', fontsize=12)
    ax.set_ylabel('价格', fontsize=12)
    ax.set_title('缠论买卖点完整结构示意图（空头镜像）— 一卖 / 二卖 / 三卖',
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
    ax.legend(handles=legend_items, loc='upper right', fontsize=11,
              framealpha=0.9, ncol=2)

    explanation = (
        '一卖 = 趋势反转顶（上涨段终结）\n'
        '二卖 = 一卖后首次反弹，不破一卖高点\n'
        '三卖 = 跌破新中枢下沿后，反抽不破该下沿'
    )
    ax.text(0.012, 0.05, explanation, transform=ax.transAxes, fontsize=11,
            verticalalignment='bottom',
            bbox=dict(boxstyle='round,pad=0.6', facecolor='#FFFFFF',
                      edgecolor='#BDBDBD', alpha=0.95))

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, 'chanlun_sell_points_demo.png')
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"[OK] 保存至: {os.path.abspath(out_path)}")
    return out_path


if __name__ == "__main__":
    draw()
