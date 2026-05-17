"""
DC（Donchian Channel）vs MA 跨品种对比

测试矩阵: 4 个品种 × 4 个过滤模式 = 16 次回测
  品种: au888, i888, rb888, cu888
  模式: ma (240), dc_middle (55), dc_breakout (55), dc_bandwidth (55)
  时间: 2024-01-01 ~ 2024-12-31

目标：找出能跨品种稳健的过滤器（既不像 ma=120 那样在铁矿/螺纹上崩盘）
"""
import os
import sys
import time
import json

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
from examples.chanlun_5m import chanlun_5m_strategy, initialize
import examples.chanlun_5m as _impl_mod


SYMBOLS = [
    {'symbol': 'au888', 'name': '黄金',     'price_tick': 0.02, 'contract_multiplier': 1000},
    {'symbol': 'i888',  'name': '铁矿石',   'price_tick': 0.5,  'contract_multiplier': 100},
    {'symbol': 'rb888', 'name': '螺纹钢',   'price_tick': 1,    'contract_multiplier': 10},
    {'symbol': 'cu888', 'name': '铜',       'price_tick': 10,   'contract_multiplier': 5},
]

FILTER_MODES = [
    {'name': 'MA240',        'type': 'ma',           'extra': {'trend_ma_period': 240}},
    {'name': 'DC55_middle',  'type': 'dc_middle',    'extra': {'dc_period': 55}},
    {'name': 'DC55_breakout','type': 'dc_breakout',  'extra': {'dc_period': 55, 'dc_touch_ratio': 0.995}},
    {'name': 'DC55_bandwidth','type': 'dc_bandwidth','extra': {'dc_period': 55, 'dc_bandwidth_min': 0.01}},
]

DATE_RANGE = ('2024-01-01', '2024-12-31')
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


def run_one(sym_cfg, mode_cfg):
    _db_path = os.path.join(_PROJ_ROOT, 'data_cache', 'kline_data.db')

    config = get_config(RunMode.BACKTEST,
        symbol=sym_cfg['symbol'],
        start_date=DATE_RANGE[0], end_date=DATE_RANGE[1],
        kline_period='5m', adjust_type='1',
        price_tick=sym_cfg['price_tick'],
        contract_multiplier=sym_cfg['contract_multiplier'],
        slippage_ticks=1,
        initial_capital=INITIAL_CAPITAL,
        commission=0.0001, margin_rate=0.1,
    )
    if os.path.exists(_db_path):
        config['file_path'] = _db_path

    params = dict(BASE_PARAMS)
    params['trend_filter_type'] = mode_cfg['type']
    params.update(mode_cfg['extra'])

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
        print(f"  [ERR] {sym_cfg['symbol']} {mode_cfg['name']}: {e}")
        return None
    elapsed = time.time() - t0
    perf = results.get('performance', {}) if results else {}
    return {
        'symbol': sym_cfg['symbol'],
        'name': sym_cfg['name'],
        'mode': mode_cfg['name'],
        'win_rate': round(perf.get('win_rate', 0), 2),
        'annual_return_%': round(perf.get('annual_return', 0), 2),
        'max_drawdown_%': round(perf.get('max_drawdown_pct', 0), 2),
        'sharpe_ratio': round(perf.get('sharpe_ratio', 0), 4),
        'elapsed_s': round(elapsed, 1),
    }


if __name__ == "__main__":
    start_t = time.time()
    print("=" * 80)
    print("DC vs MA 跨品种过滤器对比")
    print(f"品种: {[s['symbol'] for s in SYMBOLS]}")
    print(f"模式: {[m['name'] for m in FILTER_MODES]}")
    print(f"区间: {DATE_RANGE[0]} ~ {DATE_RANGE[1]}")
    print(f"共 {len(SYMBOLS) * len(FILTER_MODES)} 次回测")
    print("=" * 80)

    results = []
    for mode in FILTER_MODES:
        for sym in SYMBOLS:
            print(f"\n→ [{mode['name']}] {sym['symbol']}({sym['name']}) ...")
            r = run_one(sym, mode)
            if r is not None:
                results.append(r)
                print(f"  胜率={r['win_rate']}%  年化={r['annual_return_%']}%  "
                      f"回撤={r['max_drawdown_%']}%  夏普={r['sharpe_ratio']}  "
                      f"用时={r['elapsed_s']}s")

    print("\n\n" + "=" * 80)
    print("  绩效矩阵")
    print("=" * 80)
    df = pd.DataFrame(results)

    print("\n年化收益率% (行=品种, 列=过滤模式):")
    print(df.pivot(index='symbol', columns='mode', values='annual_return_%').to_string())

    print("\n夏普比率:")
    print(df.pivot(index='symbol', columns='mode', values='sharpe_ratio').to_string())

    print("\n最大回撤%:")
    print(df.pivot(index='symbol', columns='mode', values='max_drawdown_%').to_string())

    print("\n胜率%:")
    print(df.pivot(index='symbol', columns='mode', values='win_rate').to_string())

    # 各模式的"跨品种平均"
    print("\n各模式的跨品种平均年化:")
    avg_ret = df.groupby('mode')['annual_return_%'].mean().round(2)
    for mode, ret in avg_ret.sort_values(ascending=False).items():
        bar = '█' * max(1, int(ret * 2)) if ret > 0 else ''
        print(f"  {mode:18s} : {ret:>6.2f}%  {bar}")

    print("\n各模式的跨品种平均夏普:")
    avg_sh = df.groupby('mode')['sharpe_ratio'].mean().round(3)
    for mode, sh in avg_sh.sort_values(ascending=False).items():
        bar = '█' * max(1, int(sh * 20)) if sh > 0 else ''
        print(f"  {mode:18s} : {sh:>6.3f}  {bar}")

    # 保存
    out_dir = os.path.join(_PROJ_ROOT, 'backtest_results')
    os.makedirs(out_dir, exist_ok=True)
    ts = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(out_dir, f'dc_compare_{ts}.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    json_path = os.path.join(out_dir, f'dc_compare_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n保存:")
    print(f"  {csv_path}")
    print(f"  {json_path}")

    print(f"\n总用时: {(time.time() - start_t)/60:.1f} 分钟")
