"""
查看DB数据库 - 数据库浏览工具

功能:
  1. 查看所有表列表（含记录数和字段信息）
  2. 查看指定表的数据（首尾N条）
  3. 按品种筛选相关表
  4. 查看表的完整字段信息
  5. 执行自定义SQL查询
"""

import sqlite3
import pandas as pd
import os

# 数据库路径
DB_PATH = 'data_cache/backtest_data.db'

def get_connection():
    """获取数据库连接"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return None
    return sqlite3.connect(DB_PATH)

def list_all_tables(show_columns: bool = True):
    """
    列出所有表（按类型分类显示）

    Args:
        show_columns: 是否显示列信息
    """
    conn = get_connection()
    if conn is None:
        return

    print(f"\n{'='*70}")
    print(f"数据库: {DB_PATH}")
    print(f"{'='*70}")

    try:
        # 获取所有表
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            conn
        )

        if tables.empty:
            print("📭 数据库为空，没有表")
            return

        # 分类表
        kline_tables = []
        tick_tables = []
        other_tables = []

        for table_name in tables['name']:
            if '_tick' in table_name.lower():
                tick_tables.append(table_name)
            elif any(p in table_name for p in ['_1m_', '_5m_', '_15m_', '_30m_', '_1h_', '_4h_', '_D_', '_W_', '_M_', '_1d_']):
                kline_tables.append(table_name)
            else:
                other_tables.append(table_name)

        print(f"\n共 {len(tables)} 个表")

        # 显示K线数据
        if kline_tables:
            print(f"\n{'─'*70}")
            print(f"📊 K线数据 ({len(kline_tables)} 个表)")
            print(f"{'─'*70}")
            for table_name in kline_tables:
                _print_table_info(conn, table_name, show_columns)

        # 显示TICK数据
        if tick_tables:
            print(f"\n{'─'*70}")
            print(f"📈 TICK数据 ({len(tick_tables)} 个表)")
            print(f"{'─'*70}")
            for table_name in tick_tables:
                _print_table_info(conn, table_name, show_columns)

        # 显示其他数据
        if other_tables:
            print(f"\n{'─'*70}")
            print(f"📋 其他数据 ({len(other_tables)} 个表)")
            print(f"{'─'*70}")
            for table_name in other_tables:
                _print_table_info(conn, table_name, show_columns)

    finally:
        conn.close()

def _print_table_info(conn, table_name: str, show_columns: bool = True):
    """打印单个表的信息"""
    # 获取记录数
    count = pd.read_sql_query(
        f"SELECT COUNT(*) as cnt FROM [{table_name}]", conn
    )['cnt'].iloc[0]

    # 获取时间范围
    try:
        time_range = pd.read_sql_query(
            f"SELECT MIN(datetime) as start, MAX(datetime) as end FROM [{table_name}]",
            conn
        )
        start_time = time_range['start'].iloc[0]
        end_time = time_range['end'].iloc[0]
        if start_time and end_time:
            # 简化时间显示
            start_str = str(start_time)[:10] if start_time else ""
            end_str = str(end_time)[:10] if end_time else ""
            time_info = f" | {start_str} ~ {end_str}"
        else:
            time_info = ""
    except:
        time_info = ""

    print(f"\n  {table_name}")
    print(f"    📊 {count:,} 条记录{time_info}")

    if show_columns:
        # 获取列信息
        columns_info = pd.read_sql_query(
            f"PRAGMA table_info([{table_name}])", conn
        )
        columns = columns_info['name'].tolist()
        print(f"    📋 字段({len(columns)}): {', '.join(columns[:8])}{'...' if len(columns) > 8 else ''}")

def view_table_data(table_name: str, head: int = 5, tail: int = 5):
    """
    查看表数据（首尾N条）

    Args:
        table_name: 表名
        head: 显示前N条
        tail: 显示后N条
    """
    conn = get_connection()
    if conn is None:
        return

    print(f"\n{'='*70}")
    print(f"表: {table_name}")
    print(f"{'='*70}")

    try:
        # 检查表是否存在
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )
        if table_name not in tables['name'].values:
            print(f"❌ 表不存在: {table_name}")
            return

        # 获取总记录数
        count = pd.read_sql_query(
            f"SELECT COUNT(*) as cnt FROM [{table_name}]", conn
        )['cnt'].iloc[0]
        print(f"📊 总记录数: {count:,}\n")

        # 设置显示选项
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 50)

        # 显示前N条
        if head > 0:
            print(f"--- 前 {head} 条 ---")
            df_head = pd.read_sql_query(
                f"SELECT * FROM [{table_name}] LIMIT {head}", conn
            )
            print(df_head.to_string(index=False))
            print()

        # 显示后N条
        if tail > 0 and count > head:
            print(f"--- 后 {tail} 条 ---")
            df_tail = pd.read_sql_query(
                f"SELECT * FROM [{table_name}] ORDER BY rowid DESC LIMIT {tail}", conn
            )
            # 反转顺序
            df_tail = df_tail.iloc[::-1].reset_index(drop=True)
            print(df_tail.to_string(index=False))

    except Exception as e:
        print(f"❌ 查询失败: {e}")
    finally:
        conn.close()

def view_table_columns(table_name: str):
    """
    查看表的完整字段信息

    Args:
        table_name: 表名
    """
    conn = get_connection()
    if conn is None:
        return

    print(f"\n{'='*70}")
    print(f"表字段信息: {table_name}")
    print(f"{'='*70}")

    try:
        # 获取列信息
        columns_info = pd.read_sql_query(
            f"PRAGMA table_info([{table_name}])", conn
        )

        if columns_info.empty:
            print(f"❌ 表不存在或没有字段: {table_name}")
            return

        print(f"\n共 {len(columns_info)} 个字段:\n")
        print(f"{'序号':<6} {'字段名':<25} {'类型':<15} {'可空':<6} {'默认值':<10}")
        print("-" * 70)

        for _, row in columns_info.iterrows():
            nullable = "否" if row['notnull'] else "是"
            default = str(row['dflt_value']) if row['dflt_value'] is not None else "-"
            print(f"{row['cid']:<6} {row['name']:<25} {row['type']:<15} {nullable:<6} {default:<10}")

    except Exception as e:
        print(f"❌ 查询失败: {e}")
    finally:
        conn.close()

def filter_tables_by_symbol(symbol: str):
    """
    按品种筛选相关表

    Args:
        symbol: 品种代码（如 rb888, au888）
    """
    conn = get_connection()
    if conn is None:
        return

    print(f"\n{'='*70}")
    print(f"品种 [{symbol}] 相关表")
    print(f"{'='*70}")

    try:
        # 获取所有表
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            conn
        )

        # 筛选包含symbol的表
        matched_tables = [t for t in tables['name'] if symbol.lower() in t.lower()]

        if not matched_tables:
            print(f"📭 未找到品种 [{symbol}] 相关的表")
            print(f"💡 提示: 表名格式为 {{symbol}}_tick 或 {{symbol}}_{{period}}_{{adjust}}")
            return

        print(f"\n找到 {len(matched_tables)} 个相关表:\n")

        for table_name in matched_tables:
            # 获取记录数
            count = pd.read_sql_query(
                f"SELECT COUNT(*) as cnt FROM [{table_name}]", conn
            )['cnt'].iloc[0]

            # 获取时间范围
            try:
                time_range = pd.read_sql_query(
                    f"SELECT MIN(datetime) as start, MAX(datetime) as end FROM [{table_name}]",
                    conn
                )
                start_time = time_range['start'].iloc[0]
                end_time = time_range['end'].iloc[0]
                time_info = f"{start_time} ~ {end_time}"
            except:
                time_info = "无时间信息"

            # 判断数据类型
            if '_tick' in table_name:
                data_type = "📈 TICK"
            else:
                data_type = "📊 K线"

            print(f"{data_type} {table_name}")
            print(f"    记录数: {count:,}")
            print(f"    时间范围: {time_info}")
            print()

    except Exception as e:
        print(f"❌ 查询失败: {e}")
    finally:
        conn.close()

def execute_custom_sql(sql: str):
    """
    执行自定义SQL查询

    Args:
        sql: SQL语句
    """
    conn = get_connection()
    if conn is None:
        return

    print(f"\n{'='*70}")
    print(f"执行SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")
    print(f"{'='*70}")

    try:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)

        df = pd.read_sql_query(sql, conn)
        print(f"\n返回 {len(df)} 条记录:\n")
        print(df.to_string(index=False))

    except Exception as e:
        print(f"❌ 执行失败: {e}")
    finally:
        conn.close()

def delete_table(table_name: str) -> bool:
    """
    删除指定表

    Args:
        table_name: 表名

    Returns:
        是否删除成功
    """
    conn = get_connection()
    if conn is None:
        return False

    try:
        # 检查表是否存在
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )
        if table_name not in tables['name'].values:
            print(f"❌ 表不存在: {table_name}")
            return False

        # 获取记录数
        count = pd.read_sql_query(
            f"SELECT COUNT(*) as cnt FROM [{table_name}]", conn
        )['cnt'].iloc[0]

        # 删除表
        conn.execute(f"DROP TABLE [{table_name}]")
        conn.commit()

        print(f"✅ 已删除表 [{table_name}]（原有 {count:,} 条记录）")
        return True

    except Exception as e:
        print(f"❌ 删除失败: {e}")
        return False
    finally:
        conn.close()

def clear_table(table_name: str) -> bool:
    """
    清空表数据（保留表结构）

    Args:
        table_name: 表名

    Returns:
        是否清空成功
    """
    conn = get_connection()
    if conn is None:
        return False

    try:
        # 检查表是否存在
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )
        if table_name not in tables['name'].values:
            print(f"❌ 表不存在: {table_name}")
            return False

        # 获取记录数
        count = pd.read_sql_query(
            f"SELECT COUNT(*) as cnt FROM [{table_name}]", conn
        )['cnt'].iloc[0]

        # 清空表
        conn.execute(f"DELETE FROM [{table_name}]")
        conn.commit()

        print(f"✅ 已清空表 [{table_name}]（删除了 {count:,} 条记录）")
        return True

    except Exception as e:
        print(f"❌ 清空失败: {e}")
        return False
    finally:
        conn.close()

def delete_tables_by_symbol(symbol: str) -> int:
    """
    删除指定品种的所有表

    Args:
        symbol: 品种代码

    Returns:
        删除的表数量
    """
    conn = get_connection()
    if conn is None:
        return 0

    try:
        # 获取所有表
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )

        # 筛选包含symbol的表
        matched_tables = [t for t in tables['name'] if symbol.lower() in t.lower()]

        if not matched_tables:
            print(f"📭 未找到品种 [{symbol}] 相关的表")
            return 0

        print(f"\n找到 {len(matched_tables)} 个相关表:")
        for t in matched_tables:
            count = pd.read_sql_query(f"SELECT COUNT(*) as cnt FROM [{t}]", conn)['cnt'].iloc[0]
            print(f"  - {t} ({count:,} 条记录)")

        # 确认删除
        confirm = input(f"\n⚠️ 确认删除以上 {len(matched_tables)} 个表? (输入 yes 确认): ").strip()
        if confirm.lower() != 'yes':
            print("❌ 已取消删除")
            return 0

        # 删除表
        deleted_count = 0
        for table_name in matched_tables:
            try:
                conn.execute(f"DROP TABLE [{table_name}]")
                print(f"✅ 已删除: {table_name}")
                deleted_count += 1
            except Exception as e:
                print(f"❌ 删除失败 [{table_name}]: {e}")

        conn.commit()
        print(f"\n✅ 共删除 {deleted_count} 个表")
        return deleted_count

    except Exception as e:
        print(f"❌ 操作失败: {e}")
        return 0
    finally:
        conn.close()

def delete_menu():
    """删除操作子菜单"""
    print("\n" + "-"*50)
    print("删除操作")
    print("-"*50)
    print("""
  a. 删除指定表
  b. 清空表数据（保留结构）
  c. 删除指定品种的所有表
  d. 返回主菜单
""")

    sub_choice = input("请选择 (a/b/c/d): ").strip().lower()

    if sub_choice == 'a':
        list_all_tables(show_columns=False)
        table_name = input("\n请输入要删除的表名: ").strip()
        if table_name:
            confirm = input(f"⚠️ 确认删除表 [{table_name}]? (输入 yes 确认): ").strip()
            if confirm.lower() == 'yes':
                delete_table(table_name)
            else:
                print("❌ 已取消删除")

    elif sub_choice == 'b':
        list_all_tables(show_columns=False)
        table_name = input("\n请输入要清空的表名: ").strip()
        if table_name:
            confirm = input(f"⚠️ 确认清空表 [{table_name}] 的所有数据? (输入 yes 确认): ").strip()
            if confirm.lower() == 'yes':
                clear_table(table_name)
            else:
                print("❌ 已取消清空")

    elif sub_choice == 'c':
        symbols = get_all_symbols()
        if symbols:
            print(f"\n可用品种: {', '.join(symbols)}")
        symbol = input("请输入要删除的品种代码 (如 rb888): ").strip()
        if symbol:
            delete_tables_by_symbol(symbol)

    elif sub_choice == 'd':
        pass

    else:
        print("❌ 无效选项")

def get_all_symbols():
    """获取数据库中所有品种"""
    conn = get_connection()
    if conn is None:
        return []

    try:
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", conn
        )

        symbols = set()
        for table_name in tables['name']:
            # 提取品种代码（表名第一部分）
            parts = table_name.split('_')
            if parts:
                symbols.add(parts[0])

        return sorted(list(symbols))

    finally:
        conn.close()

def interactive_menu():
    """交互式菜单"""
    while True:
        print("\n" + "="*70)
        print("数据库管理工具")
        print("="*70)
        print(f"数据库: {DB_PATH}")
        print("""
请选择操作:
  1. 查看所有表（含字段信息）
  2. 查看所有表（仅表名和记录数）
  3. 按品种筛选表
  4. 查看指定表的数据
  5. 查看表的完整字段信息
  6. 执行自定义SQL
  7. 删除数据（表/清空/按品种）
  0. 退出
""")

        choice = input("请输入选项 (0-7): ").strip()

        if choice == '1':
            list_all_tables(show_columns=True)

        elif choice == '2':
            list_all_tables(show_columns=False)

        elif choice == '3':
            # 显示可用品种
            symbols = get_all_symbols()
            if symbols:
                print(f"\n可用品种: {', '.join(symbols)}")
            symbol = input("请输入品种代码 (如 rb888): ").strip()
            if symbol:
                filter_tables_by_symbol(symbol)

                # 询问是否查看具体表
                table_name = input("\n输入表名查看数据（直接回车跳过）: ").strip()
                if table_name:
                    view_table_data(table_name)

        elif choice == '4':
            # 显示所有表名
            list_all_tables(show_columns=False)
            table_name = input("\n请输入表名: ").strip()
            if table_name:
                try:
                    head = int(input("显示前N条 [默认5]: ").strip() or "5")
                    tail = int(input("显示后N条 [默认5]: ").strip() or "5")
                except ValueError:
                    head, tail = 5, 5
                view_table_data(table_name, head, tail)

        elif choice == '5':
            list_all_tables(show_columns=False)
            table_name = input("\n请输入表名: ").strip()
            if table_name:
                view_table_columns(table_name)

        elif choice == '6':
            print("\n💡 示例SQL:")
            print("  SELECT * FROM rb888_tick LIMIT 10")
            print("  SELECT COUNT(*) FROM rb888_1m_hfq")
            print("  SELECT * FROM rb888_tick WHERE datetime > '2025-12-11'")
            sql = input("\n请输入SQL语句: ").strip()
            if sql:
                execute_custom_sql(sql)

        elif choice == '7':
            delete_menu()

        elif choice == '0':
            print("👋 再见!")
            break

        else:
            print("❌ 无效选项")

        input("\n按回车继续...")

# ==================== 主程序 ====================

if __name__ == "__main__":
    # 检查数据库是否存在
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("💡 请先运行SIMNOW模式采集数据，或使用'数据导入DB示例.py'导入数据")
    else:
        interactive_menu()
