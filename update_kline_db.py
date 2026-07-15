#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K 线数据库增量更新 - 命令行入口

用法:
    python update_kline_db.py --db-path "D:\\data\\kline_data.db"
    python update_kline_db.py --db-path "..." --end-date 2026-07-07
    python update_kline_db.py --db-path "..." --table rb888_1M_raw --table au888_1M_raw
    python update_kline_db.py --db-path "..." --skip-symbol lr --skip-symbol wh

也可被其他项目导入:
    from update_kline_db import update_kline_db
    result = update_kline_db(r"D:\\data\\kline_data.db")
"""
import argparse
import sys
import os

# 确保使用项目根目录的 ssquant
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ssquant.data.update_service import update_kline_db as _update_kline_db

DEFAULT_DB_PATH = r"D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"


def update_kline_db(db_path: str = DEFAULT_DB_PATH, end_date: str = None,
                    tables_filter: list = None, skip_symbols: list = None,
                    skip_config_path: str = None):
    """兼容旧调用的便捷函数"""
    return _update_kline_db(
        db_path=db_path, end_date=end_date, tables_filter=tables_filter,
        skip_symbols=skip_symbols, skip_config_path=skip_config_path,
    )


def main():
    parser = argparse.ArgumentParser(description='增量更新 K 线数据库')
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH, help='目标 SQLite 数据库路径')
    parser.add_argument('--end-date', default=None, help='更新截止日期，格式 YYYY-MM-DD，默认今天')
    parser.add_argument('--table', default=None, action='append', help='仅更新指定表，可多次指定')
    parser.add_argument('--skip-symbol', default=None, action='append',
                        help='跳过指定品种/合约，可多次指定（如 --skip-symbol lr）')
    parser.add_argument('--skip-config', default=None,
                        help='跳过品种配置文件路径，JSON 格式，默认查找数据库同目录 update_skip_symbols.json')
    args = parser.parse_args()

    print(f"[开始] 增量更新 K 线数据")
    print(f"  数据库: {args.db_path}")
    print(f"  截止日期: {args.end_date or '今天'}")
    print()

    def progress_callback(idx, total, table_name, res):
        status = "成功" if res['success'] else "失败"
        print(f"[{idx}/{total}] {table_name}: {status} | {res['message']} (记录数 {res['before']} -> {res['after']})")

    result = _update_kline_db(
        db_path=args.db_path,
        end_date=args.end_date,
        tables_filter=args.table,
        progress_callback=progress_callback,
        sleep_between_symbols=1.0,
        skip_symbols=args.skip_symbol,
        skip_config_path=args.skip_config,
    )

    if not result.get('success') and 'error' in result:
        print(f"[错误] {result['error']}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("[汇总]")
    print(f"  总表数: {result['total_tables']}")
    print(f"  成功: {result['success_count']}")
    print(f"  跳过: {result.get('skipped_count', 0)}")
    print(f"  失败: {result['fail_count']}")
    print(f"  总新增记录数: {result['total_added']}")
    print("=" * 70)
    print(f"[日志] 已保存更新明细: {result['log_path']}")


if __name__ == '__main__':
    main()
