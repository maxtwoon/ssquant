"""
多品种组合回测 — 等权重 + 独立账户

对每个品种独立跑同样的 5m 缠论策略，最后把各品种的权益曲线等权重合成
"组合层面"指标。模拟真实场景：账户被均匀分成 N 份分别给每个品种用。

为简化实现，本脚本不并行；逐个品种串行跑，每个账户独立。
"""
import os
import sys
import time
import json

import pandas as pd

# 路径处理
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# 通过 ASCII 别名模块加载策略
from examples.chanlun_5m import chanlun_5m_strategy, initialize
import examples.chanlun_5m as _impl_mod


# ============================================================================
# 组合配置
# ============================================================================

# 每个品种分配多少初始资金（等权重，总池 4 × 50w = 200w）
PER_SYMBOL_CAPITAL = 500_000

# 测试时间段
START_DATE = '2024-01-01'
END_DATE = '2024-12-31'

# 品种 + 合约参数
SYMBOLS = [
    {
        'symbol': 'au888',
        'name': '黄金',
        'price_tick': 0.02,
        'contract_multiplier': 1000,
    },
    {
        'symbol': 'i888',
        'name': '铁矿石',
        'price_tick': 0.5,
        'contract_multiplier': 100,
    },
    {
        'symbol': 'rb888',
        'name': '螺纹钢',
        'price_tick': 1,
        'contract_multiplier': 10,
    },
    {
        'symbol': 'cu888',
        'name': '铜',
        'price_tick': 10,
        'contract_multiplier': 5,
    },
]

# 共用策略参数（与单品种 README 完全一致）
COMMON_STRATEGY_PARAMS = {
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
    'trend_ma_period': 240,           # 跨品种稳健默认（ma=120 仅适合 au/cu）
    'trend_buffer': 0.005,
    'use_volume_filter': False,
    'max_trades_per_trend': 2,
}


def run_one_symbol(sym_cfg):
    """跑单品种回测，返回绩效字典"""
    print(f"\n{'#' * 80}")
    print(f"# 品种 {sym_cfg['symbol']} ({sym_cfg['name']})")
    print(f"{'#' * 80}\n")

    _db_path = os.path.join(_PROJ_ROOT, 'data_cache', 'kline_data.db')
    if not os.path.exists(_db_path):
        print(f"[ERR] 数据库不存在: {_db_path}")
        return None

    config = get_config(RunMode.BACKTEST,
        symbol=sym_cfg['symbol'],
        start_date=START_DATE,
        end_date=END_DATE,
        kline_period='5m',
        adjust_type='1',

        price_tick=sym_cfg['price_tick'],
        contract_multiplier=sym_cfg['contract_multiplier'],
        slippage_ticks=1,

        initial_capital=PER_SYMBOL_CAPITAL,
        commission=0.0001,
        margin_rate=0.1,
    )
    config['file_path'] = _db_path

    # 每个品种重置策略模块的全局状态
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
            strategy_params=COMMON_STRATEGY_PARAMS,
        )
    except Exception as e:
        print(f"[ERR] 品种 {sym_cfg['symbol']} 回测崩溃: {e}")
        import traceback
        traceback.print_exc()
        return None

    elapsed = time.time() - t0
    perf = results.get('performance', {}) if results else {}
    return {
        'symbol': sym_cfg['symbol'],
        'name': sym_cfg['name'],
        'initial_capital': PER_SYMBOL_CAPITAL,
        'total_trades': perf.get('total_trades', 0),
        'win_rate': perf.get('win_rate', 0),
        'total_net_pnl': perf.get('total_net_pnl', 0),
        'max_drawdown': perf.get('max_drawdown', 0),
        'max_drawdown_pct': perf.get('max_drawdown_pct', 0),
        'sharpe_ratio': perf.get('sharpe_ratio', 0),
        'annual_return': perf.get('annual_return', 0),
        'final_equity': perf.get('final_equity', PER_SYMBOL_CAPITAL),
        'win_loss_ratio': perf.get('win_loss_ratio', 0),
        'elapsed_seconds': round(elapsed, 1),
        'report_path': perf.get('report_path', results.get('report_path', '') if results else ''),
    }


def summarize_portfolio(per_symbol_results):
    """组合层面汇总"""
    valid = [r for r in per_symbol_results if r is not None]
    if not valid:
        return None
    n = len(valid)
    total_initial = sum(r['initial_capital'] for r in valid)
    total_final = sum(r['final_equity'] for r in valid)
    total_pnl = total_final - total_initial
    portfolio_net_value = total_final / total_initial
    avg_max_drawdown_pct = sum(r['max_drawdown_pct'] for r in valid) / n
    avg_win_rate = sum(r['win_rate'] for r in valid) / n
    total_trades = sum(r['total_trades'] for r in valid)
    profitable_count = sum(1 for r in valid if r['total_net_pnl'] > 0)
    return {
        '品种数': n,
        '总初始资金': total_initial,
        '总期末权益': round(total_final, 2),
        '总净盈亏': round(total_pnl, 2),
        '组合净值': round(portfolio_net_value, 4),
        '组合收益率%': round((portfolio_net_value - 1) * 100, 2),
        '平均胜率%': round(avg_win_rate, 2),
        '平均最大回撤%': round(avg_max_drawdown_pct, 2),
        '总交易次数': total_trades,
        '盈利品种数': profitable_count,
        '亏损品种数': n - profitable_count,
    }


if __name__ == "__main__":
    start_t = time.time()
    print("=" * 80)
    print(f"缠论 5 分钟策略 — 多品种组合回测")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"品种: {', '.join(s['symbol'] + '(' + s['name'] + ')' for s in SYMBOLS)}")
    print(f"每品种初始资金: {PER_SYMBOL_CAPITAL:,.0f}")
    print("=" * 80)

    results = []
    for sym in SYMBOLS:
        r = run_one_symbol(sym)
        results.append(r)

    print("\n\n" + "=" * 80)
    print("  各品种独立结果")
    print("=" * 80)
    fields = ['symbol', 'name', 'total_trades', 'win_rate', 'total_net_pnl',
              'final_equity', 'max_drawdown_pct', 'sharpe_ratio',
              'annual_return', 'win_loss_ratio']
    rows = [{f: (r.get(f) if r else None) for f in fields} for r in results]
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    print("\n\n" + "=" * 80)
    print("  组合层面汇总")
    print("=" * 80)
    summary = summarize_portfolio(results)
    if summary:
        for k, v in summary.items():
            print(f"  {k:20s} : {v}")
    print("=" * 80)

    # 保存
    out_dir = os.path.join(_PROJ_ROOT, 'backtest_results')
    os.makedirs(out_dir, exist_ok=True)
    ts = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(out_dir, f'portfolio_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'per_symbol': results, 'portfolio_summary': summary},
                  f, ensure_ascii=False, indent=2, default=str)
    csv_path = os.path.join(out_dir, f'portfolio_{ts}.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n详细结果保存: {csv_path}")
    print(f"            : {json_path}")

    total_elapsed = time.time() - start_t
    print(f"\n总用时: {total_elapsed:.1f} 秒")
