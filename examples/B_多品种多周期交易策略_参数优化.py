"""
多品种多周期交易策略参数优化示例 - 统一运行版本

演示如何在多品种多周期交易策略中使用数据预加载功能进行参数优化
大幅提高优化效率，避免重复加载数据

注意：Windows平台限制
- Windows上 WaitForMultipleObjects 最多支持63个句柄
- 因此并行进程数设置为4，避免超出限制
- 如在Linux/Mac平台运行，可将 n_jobs 设置为 -1 使用所有核心

本文件仅做回测参数优化，不涉及 SIMNOW/实盘；实盘请用 B_多品种多周期交易策略.py。

合约代码 symbol 怎么填：
  回测：品种+888 = 主力连续合约，用于拉取连续K线（如 au888、rb888）
  SIMNOW / 实盘（自动主力映射）：
    au888  → 自动映射为当前主力月份（如 au888→au2508），用于CTP订阅和下单
    au777  → 自动映射为次主力月份
    au2508 → 指定月份，直接使用，不做映射

自动移仓（仅 SIMNOW/实盘）：持仓过主力换月时，开启 auto_roll_enabled=True 即可自动平旧开新
合约参数（乘数、最小变动价、手续费等）自动获取，无需手动填写
复权 adjust_type：'0'=不复权  '1'=后复权  '2'=前复权
K线来源 kline_source（仅 SIMNOW/实盘）：'local'=本地CTP Tick合成（默认）  'data_server'=远程推送
账户配置：在 trading_config.py 的 ACCOUNTS 中填写CTP账号信息
"""

from ssquant.backtest.backtest_core import MultiSourceBacktester
from ssquant.config.trading_config import get_api_auth
from B_多品种多周期交易策略 import multi_source_strategy, initialize
import time

if __name__ == "__main__":
    # ========== 优化配置 ==========
    # 并行进程数（Windows平台建议4-8，Linux/Mac可用-1表示所有核心）
    N_JOBS = 4

    # 记录开始时间
    start_time = time.time()

    # 导入API认证信息
    API_USERNAME, API_PASSWORD = get_api_auth()

    # 创建多数据源回测器
    backtester = MultiSourceBacktester()

    # 设置基础配置
    backtester.set_base_config({
        'username': API_USERNAME,       # 使用配置文件中的用户名
        'password': API_PASSWORD,       # 使用配置文件中的密码
        'use_cache': True,              # 是否使用缓存数据
        'save_data': True,              # 是否保存数据
        'align_data': False,            # 不对齐数据，避免数据丢失
        'fill_method': 'ffill',         # 填充方法
        'debug': False,                 # 关闭调试模式提高速度
        'skip_module_check': True,      # 跳过模块检查，提速
        'data_source_mode': 'data_server',  # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号)
    })

    # 添加数据源0配置 - 焦炭主力，添加两个不同周期
    backtester.add_symbol_config(
        symbol='j888',   # 品种+888 = 主力连续合约（回测时用于拉取连续K线）
        config={  # 焦炭配置
            'start_date': '2025-12-01',      # 回测开始日期
            'end_date': '2026-01-31',        # 回测结束日期
            'initial_capital': 100000.0,     # 初始资金，单位：元
            'commission': 0.0001,            # 手续费率，例如：0.0001表示万分之1
            'margin_rate': 0.1,              # 保证金率，例如：0.1表示10%
            'contract_multiplier': 100,      # 合约乘数，焦炭100吨/手
            'periods': [                     # 周期配置
                {'kline_period': '1m', 'adjust_type': '1'},  # 复权: '0'不复权, '1'后复权, '2'前复权
                {'kline_period': '5m', 'adjust_type': '1'},  # 复权: '0'不复权, '1'后复权, '2'前复权
            ]
    })

    # 添加数据源1配置 - 焦煤主力，添加两个不同周期
    backtester.add_symbol_config(
        symbol='jm888',  # 品种+888 = 主力连续合约（回测时用于拉取连续K线）
        config={  # 焦煤配置
            'start_date': '2025-12-01',      # 回测开始日期
            'end_date': '2026-01-31',        # 回测结束日期
            'initial_capital': 100000.0,     # 初始资金，单位：元
            'commission': 0.0001,            # 手续费率
            'margin_rate': 0.1,              # 保证金率
            'contract_multiplier': 60,       # 合约乘数，焦煤60吨/手
            'periods': [                     # 周期配置
                {'kline_period': '1m', 'adjust_type': '1'},  # 复权: '0'不复权, '1'后复权, '2'前复权
                {'kline_period': '5m', 'adjust_type': '1'},  # 复权: '0'不复权, '1'后复权, '2'前复权
            ]
    })

    print("\n" + "="*80)
    print("多品种多周期交易策略参数优化示例 - 统一运行版本")
    print("="*80)

    # 预加载数据，避免在每次参数评估时重复加载
    print("\n=== 数据预加载开始 ===")
    preload_start_time = time.time()
    backtester.preload_data()
    preload_end_time = time.time()
    preload_time = preload_end_time - preload_start_time
    print(f"数据预加载用时: {preload_time:.2f}秒")
    print("=== 数据预加载完成 ===\n")

    # 定义参数网格
    param_grid = {
        'fast_ma': list(range(3, 11, 2)),    # 短期均线周期参数范围: 3, 5, 7, 9
        'slow_ma': list(range(15, 26, 5)),   # 长期均线周期参数范围: 15, 20, 25
    }

    # 计算参数组合数量
    total_combinations = 1
    for param_values in param_grid.values():
        total_combinations *= len(param_values)
    print(f"参数网格共有 {total_combinations} 种组合")
    print(f"数据源: j888 (1m, 5m), jm888 (1m, 5m)")
    print(f"回测周期: 2025-12-01 至 2025-12-31")

    # 运行网格搜索优化
    print("\n=== 开始优化参数 ===")
    print(f"使用 {N_JOBS} 个并行进程进行优化")
    grid_start_time = time.time()
    best_params, best_results = backtester.optimize_parameters(
        strategy=multi_source_strategy,
        initialize=initialize,
        param_grid=param_grid,
        method='grid',
        optimization_metric='sharpe_ratio',   # 优化夏普比率
        higher_is_better=True,                # 夏普比率越高越好
        parallel=True,                        # 使用并行计算
        n_jobs=N_JOBS,                        # 并行进程数（避免Windows句柄限制）
        strategy_name="Multi_Period_Strategy", # 策略名称
        skip_final_report=True,               # 跳过最终完整报告
        reuse_data=True                       # 复用预加载的数据，大幅提高效率
    )
    grid_end_time = time.time()
    grid_time = grid_end_time - grid_start_time

    if best_params:
        print(f"\n{'='*80}")
        print("最优参数组合:")
        print("="*80)
        print(f"快线周期 (fast_ma): {best_params['fast_ma']}")
        print(f"慢线周期 (slow_ma): {best_params['slow_ma']}")
        print(f"\n绩效指标:")
        print(f"  夏普比率: {best_results['performance']['sharpe_ratio']:.4f}")
        print(f"  总收益率: {best_results['performance']['total_return']:.2f}%")
        print(f"  最大回撤: {best_results['performance']['max_drawdown']:.2f}%")
        print(f"  胜率: {best_results['performance'].get('win_rate', 0):.2f}%")
        print("="*80)

    # 记录结束时间
    end_time = time.time()
    total_time = end_time - start_time

    # 输出性能统计信息
    print("\n" + "="*80)
    print("性能统计")
    print("="*80)
    print(f"数据预加载用时: {preload_time:.2f} 秒")
    print(f"参数优化用时: {grid_time:.2f} 秒")
    print(f"总用时: {total_time:.2f} 秒")
    print(f"平均每个参数组合评估用时: {grid_time / total_combinations:.4f} 秒")
    print("="*80)

    print("\n" + "="*80)
    print("优化完成！")
    print("="*80)
    print("所有结果和图表已保存在 optimization/ 目录")
    print("参数组合详细结果可以在Excel文件中查看")
    print("="*80)