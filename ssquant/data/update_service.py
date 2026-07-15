#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K 线数据库增量更新服务

可被其他 Python 项目直接导入调用，也支持命令行和 HTTP API 封装。

核心函数:
    - update_kline_db(): 对指定 SQLite 数据库执行批量增量更新
    - update_single_table(): 对单张表执行增量更新

示例:
    from ssquant.data.update_service import update_kline_db
    result = update_kline_db(
        db_path=r"D:\\data\\kline_data.db",
        end_date="2026-07-07",
    )
"""
import os
import re
import sqlite3
import time
import traceback
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any

import pandas as pd

from ssquant.data.api_data_fetcher import fetch_data_from_api, save_to_sqlite
from ssquant.data.auth_manager import reset_auth
from ssquant.config.trading_config import get_api_auth


# 表名解析正则：symbol_period_adjust
# period 示例: 1M, 5M, 15M, 1H, D, W, M 等；adjust 示例: raw, hfq, qfq
TABLE_PATTERN = re.compile(r'^(.+)_(\d+[MmHhDWM]|\d+[mhd])_(raw|hfq|qfq)$')

DEFAULT_SLEEP = 1.0  # 每个 symbol 处理完休息秒数，避免触发服务端 429 限流

# 默认跳过的品种列表：data_server 已知无后续数据或数据质量极差，
# 全库更新时跳过以节省时间和避免无意义重试。
# 支持精确匹配 symbol（如 'lr888'）或按品种前缀匹配（如 'lr' 匹配 lr888/lr777/lr2605 等）。
DEFAULT_SKIP_SYMBOLS: List[str] = ['lr']

# 跳过清单配置文件名，默认放在数据库同级目录。
SKIP_CONFIG_FILENAME = 'update_skip_symbols.json'


def parse_table_name(table_name: str) -> Optional[Tuple[str, str, str]]:
    """解析表名，返回 (symbol, period, adjust)"""
    m = TABLE_PATTERN.match(table_name)
    if not m:
        return None
    symbol = m.group(1)
    period = m.group(2).upper()
    adjust = m.group(3).lower()
    return symbol, period, adjust


def is_symbol_skipped(symbol: str, skip_symbols: List[str]) -> bool:
    """
    判断某个 symbol 是否应被跳过。

    匹配规则：
        - 精确匹配：skip_symbols 中的条目与 symbol 完全一致
        - 前缀匹配：symbol 以 skip_symbols 中的条目开头（用于按品种跳过）
    """
    if not skip_symbols:
        return False
    s = symbol.strip().lower()
    for skip in skip_symbols:
        skip = skip.strip().lower()
        if not skip:
            continue
        if s == skip or s.startswith(skip):
            return True
    return False


def load_skip_symbols(config_path: Optional[str] = None,
                      db_dir: Optional[str] = None) -> List[str]:
    """
    加载跳过品种列表。

    优先级：
        1. config_path 指定的 JSON 文件
        2. db_dir 目录下的 update_skip_symbols.json
        3. 返回默认列表 DEFAULT_SKIP_SYMBOLS

    JSON 文件格式示例：
        ["lr", "wh", "ri"]
    或
        {"skip_symbols": ["lr", "wh", "ri"]}
    """
    candidates = []
    if config_path:
        candidates.append(config_path)
    if db_dir:
        candidates.append(os.path.join(db_dir, SKIP_CONFIG_FILENAME))

    for path in candidates:
        if os.path.exists(path):
            try:
                import json
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
                if isinstance(data, dict):
                    symbols = data.get('skip_symbols', [])
                    return [str(x).strip() for x in symbols if str(x).strip()]
            except Exception as e:
                print(f"[警告] 读取跳过配置 {path} 失败: {e}，使用默认配置")

    return list(DEFAULT_SKIP_SYMBOLS)


def get_adjust_type_code(adjust: str) -> str:
    """将 adjust 后缀映射为 fetch_data_from_api 使用的 '0'/'1'/'2'"""
    if adjust == 'hfq':
        return '1'
    if adjust == 'qfq':
        return '2'
    return '0'  # raw


def get_table_time_range(
    conn: sqlite3.Connection,
    table_name: str
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """获取表中数据的时间范围"""
    try:
        df = pd.read_sql_query(
            f'SELECT MIN(datetime) as start, MAX(datetime) as end FROM "{table_name}"',
            conn
        )
        start = pd.to_datetime(df['start'].iloc[0]) if pd.notna(df['start'].iloc[0]) else None
        end = pd.to_datetime(df['end'].iloc[0]) if pd.notna(df['end'].iloc[0]) else None
        return start, end
    except Exception as e:
        raise RuntimeError(f"读取表 {table_name} 时间范围失败: {e}") from e


def update_single_table(
    conn: sqlite3.Connection,
    table_name: str,
    symbol: str,
    period: str,
    adjust: str,
    username: str,
    password: str,
    end_date: str,
    db_path: str,
) -> Dict[str, Any]:
    """
    对单张表执行增量更新。

    Returns:
        {
            'table': str,
            'success': bool,
            'before': int,
            'after': int,
            'added': int,
            'message': str,
        }
    """
    result = {
        'table': table_name,
        'success': False,
        'before': 0,
        'after': 0,
        'added': 0,
        'message': '',
    }

    try:
        # 1. 读取当前记录数和时间范围
        count_df = pd.read_sql_query(f'SELECT COUNT(*) as cnt FROM "{table_name}"', conn)
        result['before'] = int(count_df['cnt'].iloc[0])

        _, cache_end = get_table_time_range(conn, table_name)
        if cache_end is None:
            result['message'] = '表为空或无法读取时间范围'
            return result

        # 2. 如果最新日期已经等于或超过 end_date，无需更新
        cache_end_date = cache_end.normalize()
        if cache_end_date >= pd.Timestamp(end_date):
            result['success'] = True
            result['message'] = f'已最新 (最新 {cache_end})'
            result['after'] = result['before']
            return result

        # 3. 计算需要更新的日期范围
        # 从 cache_end 当天开始请求（而非次日），这样即使 cache_end 是盘中时间，
        # 也能补全当天剩余数据；合并时会按 datetime 去重，不会重复。
        fetch_start = cache_end.strftime('%Y-%m-%d')
        fetch_end = end_date

        result['message'] = f'当前最新 {cache_end}, 请求补充 {fetch_start} ~ {fetch_end}'

        adjust_type = get_adjust_type_code(adjust)

        # 4. 从 API 获取缺失数据（带重试）
        df_new = None
        last_error = ''
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            df_new = fetch_data_from_api(
                symbol=symbol,
                start_date=fetch_start,
                end_date=fetch_end,
                username=username,
                password=password,
                kline_period=period,
                adjust_type=adjust_type,
                depth='no',
            )
            if df_new is not None and not df_new.empty:
                break
            last_error = 'API 返回空'
            if attempt < max_retries:
                wait = attempt * 2  # 2s, 4s
                print(f"  [重试 {attempt}/{max_retries}] {table_name} 请求为空，{wait}s 后重试...")
                time.sleep(wait)

        # 5. 如果 API 没有返回数据，直接返回
        if df_new is None or df_new.empty:
            result['success'] = True
            result['after'] = result['before']
            result['message'] += f' | 无新增数据 ({last_error}，已重试 {max_retries} 次)'
            return result

        # 6. 读取现有数据并合并
        df_old = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
        df_old['datetime'] = pd.to_datetime(df_old['datetime'])

        df_new_reset = df_new.reset_index()
        df_new_reset['datetime'] = pd.to_datetime(df_new_reset['datetime'])

        df_merged = pd.concat([df_old, df_new_reset], ignore_index=True)
        before_dedup = len(df_merged)
        df_merged = df_merged.drop_duplicates(subset=['datetime']).sort_values('datetime').reset_index(drop=True)
        after_dedup = len(df_merged)

        # 7. 保存回数据库
        save_to_sqlite(df_merged, db_path, table_name)

        # 8. 再次读取记录数
        count_df = pd.read_sql_query(f'SELECT COUNT(*) as cnt FROM "{table_name}"', conn)
        result['after'] = int(count_df['cnt'].iloc[0])
        result['added'] = result['after'] - result['before']
        result['success'] = True
        result['message'] += f' | 新增 {result["added"]} 条 (合并去重 {before_dedup - after_dedup} 条)'

    except Exception as e:
        result['message'] = f'异常: {e}'
        traceback.print_exc()

    return result


def list_kline_tables(conn: sqlite3.Connection) -> List[Tuple[str, str, str, str]]:
    """列出所有 K 线表，返回 [(table_name, symbol, period, adjust), ...]"""
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        conn
    )
    out = []
    for table_name in tables['name']:
        parsed = parse_table_name(table_name)
        if parsed:
            symbol, period, adjust = parsed
            out.append((table_name, symbol, period, adjust))
    return out


def update_kline_db(
    db_path: str,
    end_date: Optional[str] = None,
    tables_filter: Optional[List[str]] = None,
    sleep_between_symbols: float = DEFAULT_SLEEP,
    progress_callback: Optional[callable] = None,
    skip_symbols: Optional[List[str]] = None,
    skip_config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对指定 SQLite 数据库执行批量增量更新。

    Args:
        db_path: SQLite 数据库路径
        end_date: 更新截止日期，格式 YYYY-MM-DD，默认今天
        tables_filter: 仅更新指定表名列表，None 表示全部
        sleep_between_symbols: 每个表处理完休息秒数
        progress_callback: 进度回调函数，签名 fn(idx, total, table_name, result)
        skip_symbols: 直接指定要跳过的 symbol 列表，None 则读取配置文件或默认列表
        skip_config_path: 跳过品种配置文件路径，JSON 格式

    Returns:
        {
            'success': bool,
            'db_path': str,
            'end_date': str,
            'total_tables': int,
            'success_count': int,
            'fail_count': int,
            'total_added': int,
            'skipped_count': int,
            'details': List[Dict],
            'log_path': str,
        }
    """
    if not os.path.exists(db_path):
        return {
            'success': False,
            'error': f'数据库不存在: {db_path}',
        }

    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    username, password = get_api_auth()
    if not username or not password:
        return {
            'success': False,
            'error': '未配置 API 账号密码',
        }

    reset_auth()

    # 确定跳过列表
    db_dir = os.path.dirname(db_path)
    effective_skip_symbols = (
        skip_symbols
        if skip_symbols is not None
        else load_skip_symbols(skip_config_path, db_dir)
    )
    if effective_skip_symbols:
        print(f"[配置] 本次更新将跳过以下品种/合约: {effective_skip_symbols}")

    results = []
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        tables = list_kline_tables(conn)
        if tables_filter:
            tables = [t for t in tables if t[0] in tables_filter]

        for idx, (table_name, symbol, period, adjust) in enumerate(tables, 1):
            # 对已知数据源缺失的品种/合约直接跳过
            if is_symbol_skipped(symbol, effective_skip_symbols):
                _, cache_end = get_table_time_range(conn, table_name)
                res = {
                    'table': table_name,
                    'success': True,
                    'before': 0,
                    'after': 0,
                    'added': 0,
                    'skipped': True,
                    'message': f'已跳过（symbol {symbol} 在跳过列表中，数据源已知缺失）',
                }
                try:
                    count_df = pd.read_sql_query(f'SELECT COUNT(*) as cnt FROM "{table_name}"', conn)
                    res['before'] = int(count_df['cnt'].iloc[0])
                    res['after'] = res['before']
                    if cache_end is not None:
                        res['message'] += f' | 当前最新 {cache_end}'
                except Exception:
                    pass
                results.append(res)
            else:
                res = update_single_table(
                    conn, table_name, symbol, period, adjust,
                    username, password, end_date, db_path
                )
                results.append(res)

            if progress_callback:
                progress_callback(idx, len(tables), table_name, res)

            if sleep_between_symbols > 0:
                time.sleep(sleep_between_symbols)

    finally:
        conn.close()

    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    skipped_count = sum(1 for r in results if r.get('skipped'))
    total_added = sum(r['added'] for r in results)

    # 保存汇总日志
    log_path = os.path.join(
        os.path.dirname(db_path),
        f"update_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    try:
        pd.DataFrame(results).to_csv(log_path, index=False, encoding='utf-8-sig')
    except Exception as e:
        log_path = ''

    return {
        'success': fail_count == 0,
        'db_path': db_path,
        'end_date': end_date,
        'total_tables': len(results),
        'success_count': success_count,
        'fail_count': fail_count,
        'skipped_count': skipped_count,
        'total_added': total_added,
        'details': results,
        'log_path': log_path,
    }
