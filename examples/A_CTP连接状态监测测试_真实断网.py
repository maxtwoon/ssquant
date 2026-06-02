# -*- coding: utf-8 -*-
"""
CTP 连接状态异常监测功能测试 - 真实断网版本

测试目的：检查期货程序化交易系统是否具备系统连接状态监测功能
满足穿透式监管测试要求

测试流程：
a) 启动并运行期货程序化交易系统，保持系统连接状态正常
b) 【真实】禁用网卡，断开网络连接
c) 等待CTP柜台检测到心跳超时，触发 OnFrontDisconnected 回调
d) 检查系统是否监测到连接状态异常
e) 重新启用网卡，恢复网络连接

通过标准：期货程序化交易系统具备监测系统连接状态的功能

⚠️ 注意：
1. 此脚本需要【管理员权限】运行（用于禁用/启用网卡）
2. 会临时断开网络连接约30-60秒
3. 请确保没有其他重要网络任务在运行
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
from datetime import datetime
import threading
import time
import subprocess
import ctypes
import sys

# ========== 全局状态 ==========
g_connected = True  # 连接状态
g_disconnect_count = 0  # 断开次数统计
g_md_disconnected = False  # 行情服务器断开标志
g_td_disconnected = False  # 交易服务器断开标志
g_tick_count = 0  # 收到的TICK数量
g_test_started = False  # 测试是否开始
g_test_complete = False  # 测试是否完成
g_runner = None  # 运行器引用
g_network_adapter_name = None  # 网卡名称

def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_active_network_adapter():
    """获取当前活动的网络适配器名称"""
    try:
        # 使用 PowerShell 获取所有活动的网络适配器
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object Name, InterfaceDescription, Status | Format-Table -AutoSize"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        print("\n[网络] 检测到的活动网卡:")
        print("-" * 60)
        print(result.stdout)
        print("-" * 60)

        # 获取第一个活动网卡名称
        result2 = subprocess.run(
            ['powershell', '-Command',
             "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty Name"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        adapter_name = result2.stdout.strip()

        if adapter_name:
            # 检查是否有多个活动网卡
            result3 = subprocess.run(
                ['powershell', '-Command',
                 "(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}).Count"],
                capture_output=True, text=True, encoding='utf-8', errors='ignore'
            )
            count = int(result3.stdout.strip()) if result3.stdout.strip().isdigit() else 1

            if count > 1:
                print(f"[网络] ⚠️ 检测到 {count} 个活动网卡！")
                print(f"[网络] 将禁用: {adapter_name}")
                print(f"[网络] 如果有其他网卡（如无线/有线），可能需要手动禁用所有网卡")

            return adapter_name
    except Exception as e:
        print(f"[警告] 获取网卡名称失败: {e}")
    return None

def disable_all_network_adapters():
    """禁用所有网络适配器"""
    try:
        print("[网络] 正在禁用所有网卡...")
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Disable-NetAdapter -Confirm:$false"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        time.sleep(2)

        # 验证
        verify = subprocess.run(
            ['powershell', '-Command',
             "(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}).Count"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        count = verify.stdout.strip()
        if count == '0' or count == '':
            print("[网络] ✅ 所有网卡已禁用")
            return True
        else:
            print(f"[网络] ⚠️ 仍有 {count} 个网卡活动")
            return False
    except Exception as e:
        print(f"[网络] ❌ 禁用所有网卡失败: {e}")
        return False

def enable_all_network_adapters():
    """启用所有网络适配器"""
    try:
        print("[网络] 正在启用所有网卡...")
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-NetAdapter | Enable-NetAdapter -Confirm:$false"],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        time.sleep(2)
        print("[网络] ✅ 所有网卡已启用")
        return True
    except Exception as e:
        print(f"[网络] ❌ 启用所有网卡失败: {e}")
        return False

def disable_network_adapter(adapter_name):
    """禁用网络适配器"""
    try:
        print(f"[网络] 正在禁用网卡: {adapter_name}")
        result = subprocess.run(
            ['powershell', '-Command', f'Disable-NetAdapter -Name "{adapter_name}" -Confirm:$false'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        if result.returncode == 0:
            print(f"[网络] ✅ 网卡 {adapter_name} 已禁用")
            # 验证网卡状态
            time.sleep(1)
            verify = subprocess.run(
                ['powershell', '-Command', f'(Get-NetAdapter -Name "{adapter_name}").Status'],
                capture_output=True, text=True, encoding='utf-8', errors='ignore'
            )
            status = verify.stdout.strip()
            print(f"[网络] 验证网卡状态: {status}")
            if status == 'Disabled':
                print(f"[网络] ✅ 确认网卡已禁用")
                return True
            else:
                print(f"[网络] ⚠️ 网卡状态异常: {status}")
                return False
        else:
            print(f"[网络] ❌ 禁用网卡失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"[网络] ❌ 禁用网卡异常: {e}")
        return False

def enable_network_adapter(adapter_name):
    """启用网络适配器"""
    try:
        print(f"[网络] 正在启用网卡: {adapter_name}")
        result = subprocess.run(
            ['powershell', '-Command', f'Enable-NetAdapter -Name "{adapter_name}" -Confirm:$false'],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        if result.returncode == 0:
            print(f"[网络] ✅ 网卡 {adapter_name} 已启用")
            return True
        else:
            print(f"[网络] ❌ 启用网卡失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"[网络] ❌ 启用网卡异常: {e}")
        return False

def initialize(api: StrategyAPI):
    """策略初始化"""
    print("\n" + "=" * 70)
    print("  CTP 连接状态异常监测功能测试 - 真实断网版本")
    print("=" * 70)
    print("测试流程:")
    print("  1. 等待连接稳定（收到5个TICK）")
    print("  2. 【真实】禁用网卡，断开网络")
    print("  3. 等待CTP柜台检测心跳超时（约30-60秒）")
    print("  4. 检测是否触发 OnFrontDisconnected 回调")
    print("  5. 恢复网络，输出测试结果")
    print("=" * 70)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 系统已启动，等待连接稳定...")
    print("=" * 70 + "\n")

def on_disconnect(source: str, reason: int):
    """
    断开连接回调 - CTP柜台检测到连接断开时触发

    这是真正的柜台回调，由 CTP API 的 OnFrontDisconnected 触发

    参数:
        source: 断开的连接类型
            - 'md': 行情服务器断开
            - 'td': 交易服务器断开
        reason: 断开原因代码（CTP错误码）
            - 0x1001: 网络读取失败
            - 0x1002: 网络写入失败
            - 0x2001: 接收心跳超时
            - 0x2002: 发送心跳超时
            - 0x2003: 收到错误报文
    """
    global g_connected, g_disconnect_count, g_md_disconnected, g_td_disconnected

    g_connected = False
    g_disconnect_count += 1

    if source == 'md':
        g_md_disconnected = True
    elif source == 'trader':
        g_td_disconnected = True

    # 断开原因说明
    reason_map = {
        0x1001: '网络读取失败',
        0x1002: '网络写入失败',
        0x2001: '接收心跳超时',
        0x2002: '发送心跳超时',
        0x2003: '收到错误报文',
    }
    reason_desc = reason_map.get(reason, '未知原因')
    source_name = '行情服务器' if source == 'md' else '交易服务器'

    # 打印醒目的断开提示
    print("\n" + "!" * 70)
    print(f"!  [{datetime.now().strftime('%H:%M:%S')}] 🔴 CTP柜台返回：检测到连接异常!")
    print("!" * 70)
    print(f"!  断开类型: {source_name} ({source})")
    print(f"!  原因代码: {reason:#x} ({reason})")
    print(f"!  原因描述: {reason_desc}")
    print(f"!  累计断开次数: {g_disconnect_count}")
    print("!" * 70)
    print(f"!  ✅ 【真实回调】系统已监测到 {source_name} 连接断开")
    print(f"!  ✅ 此回调由CTP柜台OnFrontDisconnected触发，满足监管要求")
    print("!" * 70 + "\n")

def disconnect_test_thread():
    """
    断开连接测试线程 - 真实断网版本
    通过禁用网卡来触发真正的CTP断开回调
    """
    global g_test_started, g_test_complete, g_runner, g_md_disconnected, g_td_disconnected
    global g_network_adapter_name

    # 等待收到足够的TICK（确保连接稳定）
    print(f"[测试线程] 等待连接稳定...")
    while g_tick_count < 5:
        time.sleep(0.5)
        if g_test_complete:
            return

    g_test_started = True
    print(f"\n[测试线程] 连接已稳定（收到 {g_tick_count} 个TICK），准备断网测试...")
    time.sleep(2)

    # 获取网卡名称
    g_network_adapter_name = get_active_network_adapter()
    if not g_network_adapter_name:
        print("[测试线程] ❌ 错误：无法获取活动网卡，测试终止")
        g_test_complete = True
        return

    print(f"[测试线程] 检测到活动网卡: {g_network_adapter_name}")

    # ===== 断网测试 =====
    print("\n" + "=" * 70)
    print("[测试] 开始真实断网测试...")
    print("=" * 70)
    print(f"[测试] 即将禁用网卡: {g_network_adapter_name}")
    print("[测试] CTP心跳超时检测需要约30-60秒，请耐心等待...")
    print("=" * 70 + "\n")

    # 记录断网前的状态
    md_before = g_md_disconnected
    td_before = g_td_disconnected

    # 禁用所有网卡（确保网络完全断开）
    print("[测试] 为确保测试准确，将禁用所有网卡...")
    if not disable_all_network_adapters():
        # 如果禁用所有网卡失败，尝试只禁用主网卡
        print("[测试] 尝试只禁用主网卡...")
        if not disable_network_adapter(g_network_adapter_name):
            print("[测试线程] ❌ 禁用网卡失败，测试终止")
            g_test_complete = True
            return

    # 验证网络已断开（尝试ping）
    print("[测试] 验证网络连通性...")
    time.sleep(2)
    ping_result = subprocess.run(
        ['ping', '-n', '1', '-w', '2000', '180.168.146.187'],  # SIMNOW行情服务器
        capture_output=True, text=True
    )
    if ping_result.returncode != 0:
        print("[测试] ✅ 确认网络已断开（ping失败）")
    else:
        print("[测试] ⚠️ 警告：网络可能仍然连通！")
        print("[测试] 请手动检查网络连接，或手动禁用网卡")

    # 等待CTP检测到断开（心跳超时可能需要60-120秒）
    print("\n[测试] 网卡已禁用，等待CTP柜台检测心跳超时...")
    print("[测试] 预计等待时间: 60-120秒（SIMNOW心跳周期较长）")
    print("[测试] 如果收到断开回调，说明系统具备连接状态监测功能")
    print("-" * 70)

    max_wait_time = 180  # 最长等待180秒（3分钟）
    start_time = time.time()

    while time.time() - start_time < max_wait_time:
        elapsed = int(time.time() - start_time)

        # 每10秒打印一次等待状态
        if elapsed % 10 == 0 and elapsed > 0:
            print(f"[测试] 已等待 {elapsed} 秒... (行情断开:{g_md_disconnected}, 交易断开:{g_td_disconnected})")

        # 检查是否收到断开回调
        if g_md_disconnected or g_td_disconnected:
            if g_md_disconnected and g_td_disconnected:
                print(f"\n[测试] ✅ 在 {elapsed} 秒内收到了所有断开回调！")
                break
            elif elapsed > 30:  # 如果已经收到一个，再等30秒
                remaining = 30 - (elapsed % 30)
                if g_md_disconnected:
                    print(f"[测试] 已收到行情断开回调，等待交易断开回调...")
                else:
                    print(f"[测试] 已收到交易断开回调，等待行情断开回调...")

        time.sleep(1)

    # ===== 恢复网络 =====
    print("\n" + "-" * 70)
    print("[测试] 断网测试阶段结束，正在恢复网络...")
    enable_all_network_adapters()
    time.sleep(5)  # 等待网络恢复

    # ===== 输出测试结果 =====
    print("\n" + "=" * 70)
    print("  测试结果汇总 - 真实断网测试")
    print("=" * 70)

    # 检查是否收到了新的断开回调（断网后触发的）
    md_detected = g_md_disconnected and not md_before
    td_detected = g_td_disconnected and not td_before

    print(f"  行情服务器断开检测: {'✅ 通过 (CTP柜台回调)' if md_detected else '❌ 失败'}")
    print(f"  交易服务器断开检测: {'✅ 通过 (CTP柜台回调)' if td_detected else '❌ 失败'}")
    print(f"  总断开回调次数: {g_disconnect_count}")
    print("=" * 70)

    if md_detected and td_detected:
        print("  🎉 测试通过：系统具备连接状态异常监测功能")
        print("  ✅ 满足穿透式监管测试要求")
        print("  ✅ 断开回调由CTP柜台OnFrontDisconnected触发")
    elif md_detected or td_detected:
        print("  ⚠️ 部分通过：仅检测到部分断开")
        print("  建议延长等待时间或检查网络配置")
    else:
        print("  ❌ 测试失败：未检测到CTP断开回调")
        print("  可能原因:")
        print("    1. 等待时间不足（尝试增加等待时间）")
        print("    2. 网卡禁用失败（检查管理员权限）")
        print("    3. 回调注册问题（检查代码配置）")
    print("=" * 70 + "\n")

    g_test_complete = True

    # 停止运行器
    print("[测试线程] 测试完成，停止程序...")
    time.sleep(2)
    if g_runner:
        g_runner.stop()

def simple_strategy(api: StrategyAPI):
    """
    简单策略 - 仅用于保持程序运行并计数TICK
    不执行任何交易操作
    """
    global g_connected, g_tick_count

    if g_test_complete:
        return

    # 获取当前TICK
    tick = api.get_tick()
    if tick:
        g_tick_count += 1
        price = tick.get('LastPrice', 0)

        # 只在前几个TICK打印（避免刷屏）
        if g_tick_count <= 5:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ 收到TICK #{g_tick_count} - 最新价: {price:.2f}")
        elif g_tick_count == 6:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ... 继续接收TICK中 ...")

def cleanup_on_exit():
    """退出时确保网卡恢复"""
    print("\n[清理] 确保所有网卡已启用...")
    enable_all_network_adapters()

if __name__ == "__main__":
    # ==================== 检查管理员权限 ====================
    if not is_admin():
        print("\n" + "=" * 70)
        print("  ⚠️ 错误：需要管理员权限!")
        print("=" * 70)
        print("  此测试脚本需要禁用/启用网卡，必须以管理员身份运行。")
        print("\n  请右键点击命令提示符/PowerShell，选择'以管理员身份运行'，")
        print("  然后重新执行此脚本。")
        print("=" * 70 + "\n")
        sys.exit(1)

    # ==================== 配置区域 ====================
    # 运行模式: SIMNOW(模拟盘) 或 REAL_TRADING(实盘)
    RUN_MODE = RunMode.SIMNOW

    # 交易合约（需要有行情的活跃合约）
    SYMBOL = 'au2602'

    # ==================== 获取配置 ====================
    if RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',      # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            symbol=SYMBOL,          # 合约代码（支持 au2602, au888 等）
            kline_period='tick',    # K线周期: 1m/5m/15m/30m/1h/1d
            enable_tick_callback=True, # 是否启用逐Tick回调（高CPU占用）
            lookback_bars=100,      # 回溯K线窗口（IndicatorCache预热用）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            symbol=SYMBOL,          # 合约代码
            kline_period='tick',    # K线周期
            enable_tick_callback=True, # Tick回调
            lookback_bars=100,      # 回溯窗口（IndicatorCache重算范围）
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    # ==================== 运行测试 ====================
    print("\n" + "=" * 70)
    print("  CTP 连接状态异常监测功能测试 - 真实断网版本")
    print("=" * 70)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {SYMBOL}")
    print("=" * 70)
    print("\n⚠️  警告：此测试会临时断开网络连接！")
    print("    请确保没有其他重要网络任务在运行。")
    print("\n测试将自动执行：")
    print("  1. 连接CTP服务器")
    print("  2. 等待连接稳定（接收5个TICK）")
    print("  3. 【真实】禁用网卡断开网络")
    print("  4. 等待CTP柜台心跳超时（30-60秒）")
    print("  5. 检测OnFrontDisconnected回调")
    print("  6. 恢复网络，输出测试结果")
    print("=" * 70)

    # 确认执行
    print("\n按 Enter 开始测试，按 Ctrl+C 取消...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n测试已取消")
        sys.exit(0)

    g_runner = UnifiedStrategyRunner(mode=RUN_MODE)
    g_runner.set_config(config)

    # 注册退出清理
    import atexit
    atexit.register(cleanup_on_exit)

    # 启动断开测试线程
    test_thread = threading.Thread(target=disconnect_test_thread, daemon=True)
    test_thread.start()

    try:
        results = g_runner.run(
            strategy=simple_strategy,
            initialize=initialize,
            on_disconnect=on_disconnect,  # 断开连接回调 - 由CTP柜台触发
        )
    except KeyboardInterrupt:
        print("\n" + "=" * 70)
        print("用户中断测试")
        print(f"断开连接次数统计: {g_disconnect_count}")
        print("=" * 70)
        cleanup_on_exit()
        g_runner.stop()
    except Exception as e:
        # 测试完成后会抛出异常（因为连接已断开）
        if g_test_complete:
            print("\n[主线程] 测试已完成，程序正常退出")
        else:
            print(f"\n运行出错: {e}")
            import traceback
            traceback.print_exc()
            cleanup_on_exit()
            g_runner.stop()
