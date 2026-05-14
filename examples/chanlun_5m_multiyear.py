"""
多年期纵向稳健性测试 — 用 API 拉 2020-2024 数据扫描

测试矩阵:
  品种: au888 黄金
  年份: 2020, 2021, 2022, 2023, 2024
  trend_ma_period: 120, 240
  → 10 次回测

设计目的:
1. 跨牛/熊/震荡多种市场环境（2020 疫情、2022 熊市、2024 牛市）
2. 对比短/长趋势过滤参数在不同市场的相对表现
3. 验证 5 年总收益曲线是否单调上升（趋势策略的核心特征）

数据来源: ssquant.config.trading_config 的 API 凭证（quant789.com）
回测会自动下载并缓存到 data_cache/backtest_data.db
"""
import os
import sys
import time
import json

import pandas as pd

# 路径
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config, get_api_auth
from examples.chanlun_5m import chanlun_5m_strategy, initialize
import examples.chanlun_5m as _impl_mod


# ============================================================================
# 测试配置
# ============================================================================

SYMBOL_CONFIG = {
    'symbol': 'au888',
    'name': '黄金',
    'price_tick': 0.02,
    'contract_multiplier': 1000,
}

YEARS = [2020, 2021, 2022, 2023, 2024]
TREND_MA_VALUES = [120, 240]

INITIAL_CAPITAL = 500_000

BASE_PARAMS = {
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
    'use_trend_filter': True,
    'trend_buffer': 0.005,
    'use_volume_filter': False,
    'max_trades_per_trend': 2,
}


def run_one(year, trend_ma):
    """跑单年单参数回测"""
    start_date = f'{year}-01-01'
    end_date = f'{year}-12-31'

    config = get_config(RunMode.BACKTEST,
        symbol=SYMBOL_CONFIG['symbol'],
        start_date=start_date,
        end_date=end_date,
        kline_period='5m',
        adjust_type='1',
        price_tick=SYMBOL_CONFIG['price_tick'],
        contract_multiplier=SYMBOL_CONFIG['contract_multiplier'],
        slippage_ticks=1,
        initial_capital=INITIAL_CAPITAL,
        commission=0.0001,
        margin_rate=0.1,
    )
    # 注意：不设置 file_path → 框架走 API 路径

    params = dict(BASE_PARAMS)
    params['trend_ma_period'] = trend_ma

    # 重置全局
    _impl_mod.g_chanlun_state.reset()
    _impl_mod.g_signals_history = []
    _impl_mod.g_klines_snapshot = None
    _impl_mod.g_zs_history = []

    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)

    t0 = time.time()
    try:
        results = runner.run(
            strategy=chanlun_5m_strategy,
            initialize=initialize,
            strategy_params=params,
        )
    except Exception as e:
        print(f"  [ERR] {year} ma={trend_ma}: {e}")
        return None
    elapsed = time.time() - t0
    perf = results.get('performance', {}) if results else {}

    return {
        'year': year,
        'trend_ma_period': trend_ma,
        'win_rate': round(perf.get('win_rate', 0), 2),
        'annual_return_%': round(perf.get('annual_return', 0), 2),
        'max_drawdown_%': round(perf.get('max_drawdown_pct', 0), 2),
        'sharpe_ratio': round(perf.get('sharpe_ratio', 0), 4),
        'final_equity': round(perf.get('final_equity', INITIAL_CAPITAL), 2),
        'elapsed_s': round(elapsed, 1),
    }


if __name__ == "__main__":
    api_user, api_pass = get_api_auth()
    if not api_user or not api_pass:
        print("[ERR] API 凭证未配置！请在 ssquant/config/trading_config.py 设置 "
              "API_USERNAME 和 API_PASSWORD")
        sys.exit(1)

    start_t = time.time()
    print("=" * 80)
    print("多年期纵向稳健性测试 — au888 黄金 5m")
    print(f"年份: {YEARS}")
    print(f"trend_ma_period: {TREND_MA_VALUES}")
    print(f"API 用户: {api_user}")
    print(f"共 {len(YEARS) * len(TREND_MA_VALUES)} 次回测")
    print("=" * 80)

    results = []
    for ma in TREND_MA_VALUES:
        for year in YEARS:
            print(f"\n→ [ma={ma}] year={year} ...")
            r = run_one(year, ma)
            if r is not None:
                results.append(r)
                print(f"  胜率={r['win_rate']}% 年化={r['annual_return_%']}% "
                      f"回撤={r['max_drawdown_%']}% 夏普={r['sharpe_ratio']} "
                      f"用时={r['elapsed_s']}s")

    print("\n\n" + "=" * 80)
    print("  完整结果")
    print("=" * 80)
    df = pd.DataFrame(results)

    pivot_ret = df.pivot(index='year', columns='trend_ma_period',
                         values='annual_return_%')
    pivot_dd = df.pivot(index='year', columns='trend_ma_period',
                        values='max_drawdown_%')
    pivot_win = df.pivot(index='year', columns='trend_ma_period',
                         values='win_rate')
    pivot_sharpe = df.pivot(index='year', columns='trend_ma_period',
                            values='sharpe_ratio')

    print("\n年化收益率% (行=年份, 列=trend_ma_period):")
    print(pivot_ret.to_string())
    print("\n最大回撤%:")
    print(pivot_dd.to_string())
    print("\n胜率%:")
    print(pivot_win.to_string())
    print("\n夏普比率:")
    print(pivot_sharpe.to_string())

    # 5 年平均
    print("\n5 年平均年化（按 trend_ma_period 列）:")
    avg = pivot_ret.mean(axis=0).round(2)
    for ma, ret in avg.items():
        bar = '█' * max(1, int(ret * 2)) if ret > 0 else ''
        print(f"  ma={ma:>4} : {ret:>6.2f}%  {bar}")

    # 5 年累计盈亏（合并视角）
    print("\n5 年累计净盈亏（按 trend_ma_period 列）:")
    cum_pnl_120 = sum(r['final_equity'] - INITIAL_CAPITAL
                      for r in results if r['trend_ma_period'] == 120)
    cum_pnl_240 = sum(r['final_equity'] - INITIAL_CAPITAL
                      for r in results if r['trend_ma_period'] == 240)
    print(f"  ma=120 : {cum_pnl_120:+,.0f} 元")
    print(f"  ma=240 : {cum_pnl_240:+,.0f} 元")

    # 保存
    out_dir = os.path.join(_PROJ_ROOT, 'backtest_results')
    os.makedirs(out_dir, exist_ok=True)
    ts = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(out_dir, f'multiyear_au888_{ts}.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    json_path = os.path.join(out_dir, f'multiyear_au888_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n详细结果:")
    print(f"  {csv_path}")
    print(f"  {json_path}")

    total_elapsed = time.time() - start_t
    print(f"\n总用时: {total_elapsed/60:.1f} 分钟")
