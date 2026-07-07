#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量增量更新 SQLite K 线数据库示例

用途:
  - 对本地 SQLite 数据库中的 K 线表进行增量更新
  - 可被其他项目作为 Python 模块导入调用
  - 也支持命令行直接运行

调用方式:
  1. Python 导入调用:
     from ssquant.data.update_service import update_kline_db
     result = update_kline_db(db_path=r"D:\\data\\kline_data.db")

  2. 命令行调用:
     python update_kline_db.py --db-path "D:\\data\\kline_data.db"

  3. HTTP API 调用 (需先启动服务):
     python ssquant/data/update_api.py
     curl -X POST http://127.0.0.1:8000/update \
       -H "Content-Type: application/json" \
       -d '{"db_path":"D:\\\\data\\\\kline_data.db"}'
"""
from ssquant.data.update_service import update_kline_db


def example_python_call():
    """示例: 从 Python 代码中调用更新服务"""
    db_path = r"D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"

    def on_progress(idx, total, table_name, res):
        status = "成功" if res['success'] else "失败"
        print(f"[{idx}/{total}] {table_name}: {status}, 新增 {res['added']} 条")

    result = update_kline_db(
        db_path=db_path,
        end_date=None,  # 默认更新到今天
        tables_filter=None,  # None 表示全部表
        progress_callback=on_progress,
    )

    print("\n[汇总]")
    print(f"  数据库: {result['db_path']}")
    print(f"  总表数: {result['total_tables']}")
    print(f"  成功: {result['success_count']}")
    print(f"  失败: {result['fail_count']}")
    print(f"  总新增: {result['total_added']}")
    print(f"  日志: {result['log_path']}")

    return result


def example_update_specific_tables():
    """示例: 只更新指定的几张表"""
    db_path = r"D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"
    result = update_kline_db(
        db_path=db_path,
        tables_filter=['rb888_1M_raw', 'au888_1M_raw'],
    )
    return result


if __name__ == '__main__':
    example_python_call()
