#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置辅助函数

从 trading_config.py 抽离的函数，保持 trading_config.py 只包含配置数据。
"""

from ..backtest.unified_runner import RunMode

# 延迟导入合约信息服务（避免循环导入）
_contract_service = None


def _get_contract_params(symbol: str) -> dict:
    """获取合约交易参数"""
    global _contract_service
    if _contract_service is None:
        try:
            from ..data.contract_info import get_trading_params
            _contract_service = get_trading_params
        except ImportError:
            print("[配置] 警告：合约信息服务不可用，使用默认参数")
            return {}
    return _contract_service(symbol)


def _resolve_continuous_symbol_for_live(symbol: str) -> str:
    """
    SIMNOW/实盘：将 rb888、rb777 等连续合约代码解析为交易所当前实际合约（用于 CTP 订阅与下单）。
    解析失败或网络不可用时保留原代码并打印警告。
    """
    if not symbol or not isinstance(symbol, str):
        return symbol
    try:
        from ..data.contract_mapper import ContractMapper
        if not ContractMapper.is_continuous(symbol):
            return symbol
        params = _get_contract_params(symbol)
        if not params:
            return symbol
        actual = params.get('actual_symbol') or symbol
        if actual and actual.strip() and actual.lower() != symbol.lower():
            print(f"[实盘配置] 连续合约 {symbol} -> {actual}（CTP 订阅/下单使用实际合约）")
            return actual.strip()
    except Exception as e:
        print(f"[实盘配置] 连续合约解析失败，保留 {symbol}: {e}")
    return symbol


def _apply_live_continuous_symbol_resolution(mode: RunMode, config: dict) -> None:
    """原地修改 config：仅 SIMNOW/实盘 将 symbol / data_sources[].symbol 中的主连转为实际合约。"""
    if mode not in (RunMode.SIMNOW, RunMode.REAL_TRADING):
        return
    if config.get('resolve_continuous_live') is False:
        return
    sym = config.get('symbol')
    if sym:
        config['symbol'] = _resolve_continuous_symbol_for_live(sym)
    sources = config.get('data_sources')
    if isinstance(sources, list):
        for ds in sources:
            if isinstance(ds, dict) and ds.get('symbol'):
                old = ds['symbol']
                ds['symbol'] = _resolve_continuous_symbol_for_live(old)


def get_config(mode: RunMode, account: str = None, auto_params: bool = True, **overrides):
    """
    获取配置（支持自动获取合约参数）

    Args:
        mode: 运行模式
        account: 账户名 (SIMNOW/实盘必填，从 ACCOUNTS 中选择)
        auto_params: 是否自动获取合约参数（默认 True）
                    自动获取: contract_multiplier, price_tick, margin_rate, commission
        **overrides: 覆盖参数 (如 symbol='rb2601')

    常用覆盖参数:
        symbol: 合约代码（支持 au2602, au888, au 等格式）
        kline_period: K线周期
        preload_history: 是否预加载历史数据
        history_lookback_bars: 预加载K线数量
        history_symbol: 自定义历史数据源 (跨期套利用)
                       - 不指定: 自动推导为主力连续(XXX888)
                       - 'rb888': 主力连续
                       - 'rb777': 次主力连续

        SIMNOW/实盘 专用:
        resolve_continuous_live: 默认 True。为 True 时，symbol / data_sources[].symbol 中的
            XXX888、XXX777 会先解析为 contract_info 中的当前实际合约再用于 CTP（订阅/下单）。
            设为 False 可关闭替换（一般无需关闭）。

        数据请求参数（回测模式，三选一可组合）:
        start_date: 开始日期 'YYYY-MM-DD'
        end_date: 结束日期 'YYYY-MM-DD'
        start_time: 精确开始时间 'YYYY-MM-DD HH:MM:SS'
        end_time: 精确结束时间 'YYYY-MM-DD HH:MM:SS'
        limit: BAR线数量，获取最近N根K线

    示例:
        # 回测 - 日期范围
        config = get_config(RunMode.BACKTEST, symbol='au888',
                           start_date='2025-01-01', end_date='2025-12-31')

        # 回测 - 精确时间范围
        config = get_config(RunMode.BACKTEST, symbol='au888', kline_period='1m',
                           start_time='2026-02-10 09:00:00', end_time='2026-02-14 15:00:00')

        # 回测 - 最近N根K线
        config = get_config(RunMode.BACKTEST, symbol='au888', kline_period='1m',
                           limit=1000)

        # 回测 - 从某日开始取N根
        config = get_config(RunMode.BACKTEST, symbol='au888', kline_period='5m',
                           start_date='2026-01-01', limit=500)

        # SIMNOW - 自动获取参数
        config = get_config(RunMode.SIMNOW, account='simnow_default', symbol='au2602')

        # 禁用自动参数
        config = get_config(RunMode.BACKTEST, auto_params=False, symbol='au888', ...)
    """
    from .trading_config import BACKTEST_DEFAULTS, ACCOUNTS

    if mode == RunMode.BACKTEST:
        config = BACKTEST_DEFAULTS.copy()
    elif mode in (RunMode.SIMNOW, RunMode.REAL_TRADING):
        if not account:
            raise ValueError(f"运行模式 {mode.value} 必须指定 account 参数")
        if account not in ACCOUNTS:
            available = ', '.join(ACCOUNTS.keys())
            raise ValueError(f"账户 '{account}' 不存在，可用: {available}")
        config = ACCOUNTS[account].copy()
    else:
        raise ValueError(f"不支持的运行模式: {mode}")

    # 应用用户覆盖参数
    config.update(overrides)

    # SIMNOW/实盘：配置中写 rb888、rb777 时替换为当前主力/次主力实际合约（CTP 需真实 InstrumentID）
    _apply_live_continuous_symbol_resolution(mode, config)

    # 如果启用了 data_server K线模式，自动填充连接配置
    if config.get('kline_source') == 'data_server':
        from ._server_config import DATA_SERVER as _DS
        if 'data_server' not in config:
            config['data_server'] = _DS.copy()
        else:
            merged_ds = _DS.copy()
            merged_ds.update(config['data_server'])
            config['data_server'] = merged_ds

    # 自动获取合约参数
    if auto_params:
        symbol = config.get('symbol', '')
        if symbol:
            contract_params = _get_contract_params(symbol)
            if contract_params:
                # 需要自动填充的参数列表（包括固定金额手续费）
                auto_keys = [
                    'contract_multiplier', 'price_tick', 'margin_rate', 'commission',
                    'commission_per_lot', 'commission_close_per_lot', 'commission_close_today_per_lot'
                ]

                # 只填充用户未手动指定的参数
                auto_filled = []
                for key in auto_keys:
                    if key not in overrides:  # 用户未手动指定
                        if key in contract_params:
                            config[key] = contract_params[key]
                            # 只显示主要参数，不显示手续费细节
                            if key in ['contract_multiplier', 'price_tick', 'margin_rate']:
                                auto_filled.append(f"{key}={contract_params[key]}")

                # 显示手续费类型
                comm_per_lot = contract_params.get('commission_per_lot', 0)
                if comm_per_lot > 0:
                    auto_filled.append(f"手续费={comm_per_lot}元/手")
                elif contract_params.get('commission', 0) > 0:
                    auto_filled.append(f"手续费率={contract_params.get('commission', 0)}")

                if auto_filled:
                    variety_name = contract_params.get('variety_name', '')
                    actual_symbol = contract_params.get('actual_symbol', symbol)
                    name_info = f"({variety_name})" if variety_name else ""
                    print(f"[自动参数] {symbol}{name_info} -> {', '.join(auto_filled)}")

                    # 如果是主力连续，提示实际合约
                    if '888' in symbol or '777' in symbol:
                        print(f"[自动参数] {symbol} 当前主力合约: {actual_symbol}")

    return config


def add_account(name: str, **config):
    """添加账户"""
    from .trading_config import ACCOUNTS
    ACCOUNTS[name] = config


def list_accounts():
    """列出所有账户"""
    from .trading_config import ACCOUNTS
    return list(ACCOUNTS.keys())
