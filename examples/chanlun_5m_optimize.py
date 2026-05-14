"""
缠论 5 分钟策略 - 参数网格搜索

聚焦四个关键参数的小网格组合（共 18 种），找出最适合 2024 黄金 5m 的配置。
基于 ADR-001 P2 行动项，针对默认参数爆仓的问题做参数寻优。

参数网格:
- signal_cooldown:        [6, 15, 30]       (信号冷却K线数)
- atr_stop_multiplier:    [2.0, 3.0, 4.0]   (ATR 止损倍数)
- v_reversal_power_ratio: [1.3, 1.8]        (V 反信号力度阈值)

共 3 × 3 × 2 = 18 种组合，4 进程并行约 15-25 分钟。
"""
import os
import sys
import time

# 路径处理：把项目根加进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ssquant.backtest.backtest_core import MultiSourceBacktester

# 通过 ASCII 别名模块加载策略 — joblib 子进程能按 qualified name 反序列化
from examples.chanlun_5m import chanlun_5m_strategy, initialize


if __name__ == "__main__":
    N_JOBS = 1   # 串行运行避免 joblib pickling 问题（策略模块有 module-level 状态）
    start_time = time.time()

    # 数据库路径
    _db_path = os.path.join(_PROJ_ROOT, 'data_cache', 'kline_data.db')
    if not os.path.exists(_db_path):
        print(f"[ERR] 数据库不存在: {_db_path}")
        sys.exit(1)
    print(f"[OK] 数据源: {_db_path}")

    # ---------- 创建回测器 ----------
    backtester = MultiSourceBacktester()

    # 基础配置
    backtester.set_base_config({
        'username': '',
        'password': '',
        'use_cache': False,             # 不让框架去 API 拉
        'save_data': False,
        'align_data': False,
        'fill_method': 'ffill',
        'debug': False,
        'skip_module_check': True,      # 加速
    })

    # 数据源配置 - au888 黄金主连，5m 周期
    backtester.add_symbol_config(
        symbol='au888',
        config={
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'initial_capital': 100000.0,
            'commission': 0.0001,
            'margin_rate': 0.1,
            'contract_multiplier': 1000,    # 黄金 1000 克/手
            'slippage_ticks': 1,
            'price_tick': 0.02,
            'file_path': _db_path,          # SQLite 数据源
            'periods': [
                {'kline_period': '5m', 'adjust_type': '1'},  # adjust=1 → 实际去匹配 au888_5M_raw
            ],
        },
    )

    print("\n" + "=" * 80)
    print("缠论 5 分钟策略 - 参数网格搜索")
    print("=" * 80)

    # ---------- 预加载数据 ----------
    print("\n=== 数据预加载 ===")
    preload_start = time.time()
    backtester.preload_data()
    preload_time = time.time() - preload_start
    print(f"数据预加载用时: {preload_time:.2f} 秒")

    # ---------- 参数网格 ----------
    # 串行运行下减小网格，先验证有效，再扩展
    param_grid = {
        'signal_cooldown':        [15, 30],     # 默认 6，对比放大
        'atr_stop_multiplier':    [2.5, 3.5, 5.0],  # 默认 2.5，对比放宽
        # 固定参数
        'v_reversal_power_ratio': [1.5],
        'min_bi_len':       [5],
        'golden_ratio':     [1.618],
        'atr_period':       [14],
        'base_volume':      [1],
        'use_structure_stop': [True],
        'break_tolerance':  [0.002],
        'kline_period':     ['5m'],
    }

    combos = 1
    for k, v in param_grid.items():
        combos *= len(v)
    print(f"\n参数组合数: {combos}")

    # ---------- 运行网格搜索 ----------
    print("\n=== 开始网格搜索 ===")
    print(f"并行进程数: {N_JOBS}")
    grid_start = time.time()
    best_params, best_results = backtester.optimize_parameters(
        strategy=chanlun_5m_strategy,
        initialize=initialize,
        param_grid=param_grid,
        method='grid',
        optimization_metric='sharpe_ratio',
        higher_is_better=True,
        parallel=False,
        n_jobs=N_JOBS,
        strategy_name='Chanlun_5m_GridSearch',
        skip_final_report=True,
        reuse_data=True,
    )
    grid_time = time.time() - grid_start

    # ---------- 输出最优结果 ----------
    if best_params:
        print("\n" + "=" * 80)
        print("最优参数组合")
        print("=" * 80)
        for k, v in best_params.items():
            if k in ('signal_cooldown', 'atr_stop_multiplier', 'v_reversal_power_ratio'):
                print(f"  {k}: {v}")
        perf = best_results.get('performance', {}) if best_results else {}
        print(f"\n绩效:")
        print(f"  夏普比率: {perf.get('sharpe_ratio', 0):.4f}")
        print(f"  总净盈亏: {perf.get('total_pnl', 0):.2f}")
        print(f"  最大回撤: {perf.get('max_drawdown', 0):.2f}")
        print(f"  胜率: {perf.get('win_rate', 0):.2f}%")
        print(f"  总交易次数: {perf.get('total_trades', 0)}")

    print("\n" + "=" * 80)
    print("性能统计")
    print("=" * 80)
    print(f"数据预加载用时: {preload_time:.2f} 秒")
    print(f"参数优化用时:   {grid_time:.2f} 秒")
    print(f"总用时:         {time.time() - start_time:.2f} 秒")
    print(f"每组合平均:     {grid_time / combos:.2f} 秒")
    print("=" * 80)
    print("\n详细结果保存在 optimization/ 目录")
