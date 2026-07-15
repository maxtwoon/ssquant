#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SSQuant K 线数据库自动更新脚本

可被 cron / Windows 任务计划程序 / 其他脚本调用。

用法示例:
    python auto_update.py
    python auto_update.py --db-path "D:\\data\\kline_data.db"
    python auto_update.py --end-date 2026-07-14

退出码:
    0 - 更新成功
    1 - 更新过程中发生错误
    2 - 配置或数据库路径无效
"""
import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

# 确保使用项目根目录的 ssquant
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)

from ssquant.data.update_service import update_kline_db


DEFAULT_DB_PATH = r"D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\kline_data.db"
DEFAULT_LOG_DIR = r"D:\BaiduNetdiskDownload\新数据库\ssquant数据库_20260425\auto_update_logs"


def setup_log_dir(log_dir: str) -> str:
    """创建日志目录并返回日志文件路径"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f"auto_update_{timestamp}.log")


def cleanup_old_logs(log_dir: str, keep_days: int = 30):
    """清理指定天数之前的旧日志"""
    if not os.path.exists(log_dir):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for filename in os.listdir(log_dir):
        if not filename.startswith('auto_update_') or not filename.endswith('.log'):
            continue
        filepath = os.path.join(log_dir, filename)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            if mtime < cutoff:
                os.remove(filepath)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='SSQuant K 线数据库自动更新')
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH, help='目标 SQLite 数据库路径')
    parser.add_argument('--end-date', default=None, help='更新截止日期，格式 YYYY-MM-DD，默认今天')
    parser.add_argument('--log-dir', default=DEFAULT_LOG_DIR, help='日志目录')
    parser.add_argument('--keep-days', type=int, default=30, help='保留日志天数')
    parser.add_argument('--skip-config', default=None, help='跳过品种配置文件路径')
    args = parser.parse_args()

    log_file = setup_log_dir(args.log_dir)

    # 同时输出到文件和屏幕
    class Tee:
        def __init__(self, *files):
            self.files = files

        def write(self, obj):
            for f in self.files:
                f.write(obj)
                f.flush()

        def flush(self):
            for f in self.files:
                f.flush()

    with open(log_file, 'a', encoding='utf-8') as f:
        tee = Tee(sys.stdout, f)
        sys.stdout = tee
        sys.stderr = tee

        print(f"[START] SSQuant K-line auto update at {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  DB: {args.db_path}")
        print(f"  LOG: {log_file}")
        print()

        if not os.path.exists(args.db_path):
            print(f"[ERROR] 数据库不存在: {args.db_path}")
            return 2

        start_time = time.time()
        try:
            result = update_kline_db(
                db_path=args.db_path,
                end_date=args.end_date,
                sleep_between_symbols=1.0,
                skip_config_path=args.skip_config,
            )
        except Exception as e:
            print(f"[ERROR] 更新异常: {e}")
            traceback.print_exc()
            return 1
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

    # 恢复标准输出后打印摘要
    elapsed = time.time() - start_time

    if not result.get('success') and 'error' in result:
        summary = f"[FAILED] {result['error']}"
        exit_code = 1
    elif result.get('fail_count', 0) > 0:
        summary = f"[WARNING] 更新完成但存在失败表"
        exit_code = 1
    else:
        summary = f"[SUCCESS] 更新完成"
        exit_code = 0

    summary_lines = [
        "",
        "=" * 70,
        summary,
        f"  运行时间: {elapsed:.1f} 秒 ({timedelta(seconds=int(elapsed))})",
        f"  总表数: {result.get('total_tables', 0)}",
        f"  成功: {result.get('success_count', 0)}",
        f"  跳过: {result.get('skipped_count', 0)}",
        f"  失败: {result.get('fail_count', 0)}",
        f"  总新增记录数: {result.get('total_added', 0)}",
        f"  日志: {log_file}",
        "=" * 70,
    ]

    # 追加摘要到日志并打印到屏幕
    with open(log_file, 'a', encoding='utf-8') as f:
        for line in summary_lines:
            print(line)
            f.write(line + '\n')

    cleanup_old_logs(args.log_dir, args.keep_days)

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
