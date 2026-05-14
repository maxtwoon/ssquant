"""
本地复权模块 — 对从 data_server 获取的原始(raw)数据进行本地复权

设计思路:
    data_server（远程服务器）只存储不复权(raw)数据，
    复权计算在 ssquant 框架本地完成。

复权算法:
    通过 real_symbol 列检测合约切换点，在每个切换点计算比例因子:
        factor = 前一根 close / 切换后第一根 open
    累积因子应用于 OHLC 价格列。

    后复权('1'): 最早数据不变（因子从1开始累积），后续数据被调整
    前复权('2'): 最新数据不变（因子归一化使末尾=1），历史数据被调整

使用方式:
    from ssquant.data.local_adjust import apply_local_adjust
    df_adjusted = apply_local_adjust(df_raw, symbol, period, adjust_type)
"""

import pandas as pd


def get_adjust_suffix(adjust_type: str) -> str:
    """将复权类型映射为统一表后缀。"""
    adjust_type = str(adjust_type or '0')
    if adjust_type == '1':
        return 'hfq'
    if adjust_type == '2':
        return 'qfq'
    return 'raw'


def get_adjust_label(adjust_type: str) -> str:
    """返回复权类型的中文名称。"""
    adjust_type = str(adjust_type or '0')
    if adjust_type == '1':
        return '后复权'
    if adjust_type == '2':
        return '前复权'
    return '不复权'


def apply_local_adjust(df: pd.DataFrame, symbol: str, period: str,
                       adjust_type: str) -> pd.DataFrame:
    """
    对原始K线数据进行本地复权

    Args:
        df: 原始K线DataFrame（必须包含 open/high/low/close 列）
        symbol: 合约代码，如 'y888', 'rb888'
        period: K线周期，如 '1M', '1D'
        adjust_type: 复权类型
            '0' — 不复权（直接返回原始数据）
            '1' — 后复权
            '2' — 前复权

    Returns:
        复权后的DataFrame（与输入格式完全一致）
    """
    if df is None or df.empty:
        return df

    if adjust_type == '0':
        return df

    if 'real_symbol' not in df.columns or df['real_symbol'].isna().all():
        return df

    data = df.copy()

    had_dt_index = False
    if isinstance(data.index, pd.DatetimeIndex) and data.index.name == 'datetime':
        had_dt_index = True
        original_index = data.index.copy()
        data = data.reset_index(drop=False)

    data = data.sort_values('datetime' if 'datetime' in data.columns else data.columns[0])
    data = data.reset_index(drop=True)

    # 检测小数位数（保持精度）
    decimal_places = _detect_decimal_places(data)

    # 合约切换点（忽略 NaN: 连续 NaN 不算切换，NaN→有值 也不算切换）
    rs = data['real_symbol'].fillna('')
    prev_rs = rs.shift(1).fillna('')
    contract_changes = (rs != prev_rs) & (rs != '') & (prev_rs != '')
    contract_changes.iloc[0] = False

    if contract_changes.sum() == 0:
        if had_dt_index:
            return df
        return data

    # 后复权因子: 从第一行开始累积，第一行 factor = 1
    raw_factors = pd.Series(1.0, index=data.index)
    prev_close = data['close'].shift(1)
    raw_factors[contract_changes] = prev_close[contract_changes] / data['open'][contract_changes]
    backward_factors = raw_factors.cumprod()
    backward_factors.iloc[0] = 1.0

    if adjust_type == '1':
        factors = backward_factors
    elif adjust_type == '2':
        factors = backward_factors / backward_factors.iloc[-1]
    else:
        return df

    price_cols = [c for c in ('open', 'high', 'low', 'close') if c in data.columns]
    data[price_cols] = data[price_cols].multiply(factors, axis=0).round(decimal_places)

    if had_dt_index:
        data = data.set_index('datetime')

    return data


def _detect_decimal_places(data: pd.DataFrame) -> int:
    """从第一行 OHLC 检测最大小数位数"""
    first_row = data.iloc[0]
    places = 0
    for col in ('open', 'high', 'low', 'close'):
        if col in data.columns and pd.notna(first_row[col]):
            s = f"{first_row[col]:.10f}"
            p = len(s.split('.')[1].rstrip('0'))
            if p > places:
                places = p
    return places
