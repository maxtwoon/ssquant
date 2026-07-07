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

DEFAULT_SLEEP = 0.5  # 每个 symbol 处理完休息秒数，避免对服务器造成压力


def parse_table_name(table_name: str) -> Optional[Tuple[str, str, str]]:
    """解析表名，返回 (symbol, period, adjust)"""
    m = TABLE_PATTERN.match(table_name)
    if not m:
        return None
    symbol = m.group(1)
    period = m.group(2).upper()
    adjust = m.group(3).lower()
    return symbol, period, adjust


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

        # 4. 从 API 获取缺失数据
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

        # 5. 如果 API 没有返回数据，直接返回
        if df_new is None or df_new.empty:
            result['success'] = True
            result['after'] = result['before']
            result['message'] += ' | 无新增数据 (API 返回空或合约已到期/无数据)'
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
) -> Dict[str, Any]:
    """
    对指定 SQLite 数据库执行批量增量更新。

    Args:
        db_path: SQLite 数据库路径
        end_date: 更新截止日期，格式 YYYY-MM-DD，默认今天
        tables_filter: 仅更新指定表名列表，None 表示全部
        sleep_between_symbols: 每个表处理完休息秒数
        progress_callback: 进度回调函数，签名 fn(idx, total, table_name, result)

    Returns:
        {
            'success': bool,
            'db_path': str,
            'end_date': str,
            'total_tables': int,
            'success_count': int,
            'fail_count': int,
            'total_added': int,
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

    results = []
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        tables = list_kline_tables(conn)
        if tables_filter:
            tables = [t for t in tables if t[0] in tables_filter]

        for idx, (table_name, symbol, period, adjust) in enumerate(tables, 1):
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
        'total_added': total_added,
        'details': results,
        'log_path': log_path,
    }
