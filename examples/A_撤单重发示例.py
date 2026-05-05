"""
撤单重发功能测试脚本

专门用于测试订单超时撤单和自动重发功能

测试目标：
1. 验证订单超时检测是否正常
2. 验证超时后自动撤单是否触发
3. 验证撤单回调是否正确执行
4. 验证重发订单是否成功（使用超价委托）
5. 验证整个流程的日志输出是否完整

测试策略：
- 每30个TICK下一次单（使用负向偏移offset_ticks=-10，不易成交）
- 超时时间设置为3秒（便于观察）
- 重发时使用正向偏移offset_ticks=+10（超价委托，确保快速成交）
- 详细的日志输出

核心设计：
- **初始订单**：使用 offset_ticks=-10（负向偏移），委托价低于卖一价，不易成交
- **重发订单**：使用 offset_ticks=+10（正向偏移），委托价高于卖一价，快速成交
- 这样可以完美测试撤单重发机制，且不会因为配置混淆而失败

说明：
- 框架在TICK流模式下计算委托价格：买入=卖一价+offset_ticks*price_tick
- offset_ticks参数可以在每次下单时独立指定，不受全局配置限制
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import time

# ========== 测试配置 ==========
TEST_ORDER_TIMEOUT = 3  # 测试用的超时时间（秒），设置为3秒便于观察
TEST_TICK_INTERVAL = 30  # 每30个TICK下一次单

# ========== 全局状态变量 ==========
g_tick_counter = 0
g_order_count = 0  # 下单次数统计
g_pending_orders = {}  # 未成交订单
g_timeout_cancel_pending = False  # 是否有待处理的超时撤单
g_api_instance = None
g_cancel_count = 0  # 撤单次数统计
g_resend_count = 0  # 重发次数统计

def initialize(api: StrategyAPI):
    """测试策略初始化"""
    global g_tick_counter, g_order_count, g_pending_orders
    global g_timeout_cancel_pending, g_api_instance
    global g_cancel_count, g_resend_count

    api.log("="*80)
    api.log("【撤单重发功能测试】")
    api.log("="*80)
    api.log("测试配置:")
    api.log(f"  - 订单超时时间: {TEST_ORDER_TIMEOUT}秒")
    api.log(f"  - 下单间隔: 每{TEST_TICK_INTERVAL}个TICK下一次单")
    api.log(f"  - 初始订单: offset_ticks=-10 (负向偏移，不易成交)")
    api.log(f"  - 重发订单: offset_ticks=+10 (正向偏移，超价委托，确保快速成交)")
    api.log(f"  - 测试目标: 验证超时撤单和自动重发功能")
    api.log("="*80)

    # 初始化全局变量
    g_tick_counter = 0
    g_order_count = 0
    g_pending_orders = {}
    g_timeout_cancel_pending = False
    g_api_instance = api
    g_cancel_count = 0
    g_resend_count = 0

    api.log(f"[初始持仓] {api.get_pos()}")
    api.log("="*80 + "\n")

def on_trade(data):
    """成交回调 - 记录成交信息"""
    direction = '买' if data['Direction'] == '0' else '卖'
    offset_map = {'0': '开', '1': '平', '3': '平今', '4': '平昨'}
    offset = offset_map.get(data['OffsetFlag'], '未知')

    print(f"\n{'='*80}")
    print(f"✅ [成交通知] {data['TradeTime']}")
    print(f"   合约: {data['InstrumentID']}")
    print(f"   方向: {direction}{offset}")
    print(f"   价格: {data['Price']:.2f}")
    print(f"   数量: {data['Volume']}")
    print(f"   成交号: {data['TradeID']}")
    print(f"{'='*80}\n")

def on_order(data):
    """报单回调 - 跟踪订单状态"""
    global g_pending_orders

    status_map = {
        '0': '✅ 全部成交',
        '1': '⏳ 部分成交',
        '3': '⏳ 未成交',
        '5': '❌ 已撤单',
        'a': '⏳ 未知',
    }
    status = status_map.get(data['OrderStatus'], f"未知({data['OrderStatus']})")
    direction = '买' if data.get('Direction') == '0' else '卖'
    order_sys_id = data.get('OrderSysID', '')
    order_status = data['OrderStatus']

    print(f"\n📋 [报单状态更新]")
    print(f"   合约: {data['InstrumentID']}")
    print(f"   订单号: {order_sys_id}")
    print(f"   方向: {direction}")
    print(f"   价格: {data.get('LimitPrice', 0):.2f}")
    print(f"   数量: {data.get('VolumeTotalOriginal', 0)}")
    print(f"   已成交: {data.get('VolumeTraded', 0)}/{data.get('VolumeTotalOriginal', 0)}")
    print(f"   状态: {status}")

    # 更新未成交订单跟踪
    if order_sys_id:
        if order_status in ['0', '5']:  # 全部成交或撤单
            if order_sys_id in g_pending_orders:
                del g_pending_orders[order_sys_id]
                print(f"   📤 已从跟踪列表中移除")
        elif order_status in ['1', '3', 'a']:  # 未成交或部分成交
            if order_sys_id not in g_pending_orders:
                g_pending_orders[order_sys_id] = {
                    'time': time.time(),
                    'data': data
                }
                print(f"   📥 已加入跟踪列表")

    print(f"   当前跟踪订单数: {len(g_pending_orders)}")

def on_cancel(data):
    """撤单回调 - 处理撤单并重发"""
    global g_timeout_cancel_pending, g_pending_orders, g_api_instance
    global g_cancel_count, g_resend_count

    g_cancel_count += 1

    direction = '买' if data.get('Direction') == '0' else '卖'
    offset_map = {'0': '开', '1': '平', '3': '平今', '4': '平昨'}
    offset_flag = data.get('CombOffsetFlag', '0')
    offset = offset_map.get(offset_flag[0] if offset_flag else '0', '未知')
    order_sys_id = data.get('OrderSysID', '')

    print(f"\n{'='*80}")
    print(f"❌ [撤单通知 #{g_cancel_count}] 收到撤单回调")
    print(f"   合约: {data['InstrumentID']}")
    print(f"   订单号: {order_sys_id}")
    print(f"   方向: {direction}{offset}")
    print(f"   价格: {data.get('LimitPrice', 0):.2f}")
    print(f"   原始数量: {data.get('VolumeTotalOriginal', 0)}")
    print(f"   已成交: {data.get('VolumeTraded', 0)}")
    print(f"   未成交: {data.get('VolumeTotalOriginal', 0) - data.get('VolumeTraded', 0)}")
    print(f"   交易所: {data.get('ExchangeID', 'N/A')}")

    if data.get('StatusMsg'):
        print(f"   消息: {data['StatusMsg']}")

    # 检查是否是超时撤单（使用标志位判断，更可靠）
    if g_timeout_cancel_pending:
        print(f"\n   🔄 [超时撤单] 这是一个超时撤单，准备重新下单...")
        g_resend_count += 1
        g_timeout_cancel_pending = False  # 重置标志

        # 清理记录
        if order_sys_id:
            g_pending_orders.pop(order_sys_id, None)

        # 重新下单（使用正向偏移的offset_ticks，确保快速成交）
        if g_api_instance:
            print(f"   📤 [重发订单 #{g_resend_count}] 正在提交新订单...")

            # 获取当前tick数据用于显示
            current_tick = g_api_instance.get_tick()
            if current_tick:
                ask_price = current_tick.get('AskPrice1', 0)
                last_price = current_tick.get('LastPrice', 0)

                print(f"   💰 [当前价格] 最新价:{last_price:.2f} 卖一:{ask_price:.2f}")
                print(f"   💰 [超价策略] 使用正向偏移offset_ticks=+10 (卖一价+10跳，确保快速成交)")

            # 重发订单时使用正向偏移（+10），与初始订单的负向偏移（-10）相反
            g_api_instance.buy(volume=1, order_type='market', reason='超时重发', offset_ticks=10)

            print(f"   ✅ [重发完成] 新订单已提交 (offset_ticks=+10)")
            print(f"   📊 [统计] 总下单:{g_order_count}次 总撤单:{g_cancel_count}次 总重发:{g_resend_count}次")
        else:
            print(f"   ⚠️ [错误] API实例未初始化，无法重新下单")
    else:
        print(f"   ℹ️ [常规撤单] 这是一个常规撤单，不需要重新下单")

    print(f"{'='*80}\n")

def check_timeout_orders(api: StrategyAPI):
    """检查并撤销超时订单"""
    global g_pending_orders, g_timeout_cancel_pending

    current_time = time.time()
    timeout_orders = []

    # 检查每个未成交订单
    for order_sys_id, order_info in list(g_pending_orders.items()):
        order_age = current_time - order_info['time']

        if order_age > TEST_ORDER_TIMEOUT:
            timeout_orders.append(order_sys_id)
            api.log(f"⚠️ [超时检测] 订单{order_sys_id}已等待{order_age:.1f}秒 (超时阈值:{TEST_ORDER_TIMEOUT}秒)")

    # 如果有超时订单，执行撤单
    if timeout_orders:
        api.log(f"\n{'='*80}")
        api.log(f"⚠️ [超时处理] 发现{len(timeout_orders)}个超时订单")

        for order_id in timeout_orders:
            api.log(f"   - 订单{order_id}: 准备撤单")

        # 设置超时撤单标志（用于撤单回调中判断是否需要重发）
        g_timeout_cancel_pending = True
        api.log(f"   📝 已设置超时撤单标志")

        # 撤销所有未成交订单
        api.log(f"   🔨 正在撤销所有未成交订单...")
        api.cancel_all_orders()
        time.sleep(0.3)  # 等待撤单完成

        api.log(f"   ✅ 撤单请求已发送，等待撤单回调...")
        api.log(f"{'='*80}\n")

        return True

    return False

def test_cancel_resend_strategy(api: StrategyAPI):
    """测试策略 - 专注于测试撤单重发功能"""
    global g_tick_counter, g_order_count, g_pending_orders

    g_tick_counter += 1

    # 获取tick数据
    current_tick = api.get_tick()
    if current_tick is None:
        return

    # 检查超时订单
    check_timeout_orders(api)

    # 每10个tick显示一次状态
    if g_tick_counter % 10 == 0:
        last_price = current_tick.get('LastPrice', 0)
        pending_count = len(g_pending_orders)
        api.log(f"[TICK #{g_tick_counter}] 价格:{last_price:.2f} | "
                f"持仓:{api.get_pos()} | 跟踪订单:{pending_count} | "
                f"已下单:{g_order_count}次 | 已撤单:{g_cancel_count}次 | 已重发:{g_resend_count}次")

    # 每TEST_TICK_INTERVAL个TICK下一次单
    if g_tick_counter % TEST_TICK_INTERVAL == 0:
        g_order_count += 1

        api.log(f"\n{'='*80}")
        api.log(f"📤 [第{g_order_count}次下单] TICK #{g_tick_counter}")
        api.log(f"   当前持仓: {api.get_pos()}")
        api.log(f"   当前跟踪订单数: {len(g_pending_orders)}")

        # 先撤销所有未成交订单（避免重复下单）
        if g_pending_orders:
            api.log(f"   ⚠️ 发现{len(g_pending_orders)}个未成交订单，先撤单")
            api.cancel_all_orders()
            time.sleep(0.3)
            g_pending_orders.clear()

        # 下单（使用负向偏移，降低成交概率，以便测试超时撤单）
        api.log(f"   📤 提交买单 1手 (offset_ticks=-10, 不易成交)...")
        api.buy(volume=1, order_type='market', offset_ticks=-10)
        api.log(f"   ✅ 订单已提交")
        api.log(f"{'='*80}\n")

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.SIMNOW

    print("\n" + "="*80)
    print("【撤单重发功能测试】")
    print("="*80)
    print(f"测试配置:")
    print(f"  - 订单超时时间: {TEST_ORDER_TIMEOUT}秒")
    print(f"  - 下单间隔: 每{TEST_TICK_INTERVAL}个TICK")
    print(f"  - 初始订单: offset_ticks=-10 (负向偏移，不易成交)")
    print(f"  - 重发订单: offset_ticks=+10 (正向偏移，超价委托)")
    print(f"  - 运行模式: {RUN_MODE.value}")
    print(f"\n测试流程:")
    print(f"  1. 每{TEST_TICK_INTERVAL}个TICK下一次单（offset_ticks=-10，委托价低，不易成交）")
    print(f"  2. 如果订单{TEST_ORDER_TIMEOUT}秒内未成交，触发超时检测")
    print(f"  3. 自动撤销超时订单")
    print(f"  4. 在撤单回调中使用offset_ticks=+10重新下单（委托价高，快速成交）")
    print(f"  5. 观察完整的撤单重发流程")
    print(f"\n核心设计:")
    print(f"  💡 初始订单和重发订单使用不同的offset_ticks参数")
    print(f"  💡 初始订单：负向偏移 → 不易成交 → 触发超时撤单")
    print(f"  💡 重发订单：正向偏移 → 超价委托 → 快速成交")
    print(f"  💡 这样可以完美测试撤单重发机制")
    print(f"\n预期结果:")
    print(f"  ✅ 能看到订单超时检测日志")
    print(f"  ✅ 能看到撤单请求日志")
    print(f"  ✅ 能看到撤单回调触发")
    print(f"  ✅ 能看到offset_ticks=+10的重新下单日志")
    print(f"  ✅ 重发订单应该快速成交（因为使用了超价委托）")
    print(f"  ✅ 撤单次数 = 重发次数")
    print("="*80 + "\n")

    # ==================== 配置 ====================
    if RUN_MODE == RunMode.SIMNOW:
        # SIMNOW模拟盘配置
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            server_name='电信1',               # 服务器: 电信1/电信2/移动/TEST(盘后测试)

            symbol='au2602',        # 合约代码（支持 au2602, au888 等）
            kline_period='tick',    # K线周期: 1m/5m/15m/30m/1h/1d

            price_tick=0.02,        # 最小变动价位（自动获取）
            order_offset_ticks=-10, # 委托超价跳数（+10=对手价+10跳，确保成交）

            enable_tick_callback=True, # 是否启用逐Tick回调（高CPU占用）

            preload_history=True,   # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=50, # 预加载历史K线数量
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # 实盘CTP配置
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）

            symbol='au2602',        # 合约代码
            kline_period='tick',    # K线周期

            price_tick=0.02,        # 最小变动价位（自动获取）
            order_offset_ticks=-10, # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）

            enable_tick_callback=True, # Tick回调

            preload_history=True,   # 预加载历史K线
            history_lookback_bars=50, # 预加载K线数
            adjust_type='1',        # 复权: '0'不复权, '1'后复权, '2'前复权

            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=False,    # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
            kline_source='data_server',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
        )

    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    # 运行测试策略
    try:
        print("开始测试...\n")
        print("⏰ 提示：由于超时时间设置为3秒，请耐心等待观察超时撤单重发流程")
        print("⌨️  按 Ctrl+C 可随时停止测试\n")

        results = runner.run(
            strategy=test_cancel_resend_strategy,
            initialize=initialize,
            strategy_params={},
            on_trade=on_trade,
            on_order=on_order,
            on_cancel=on_cancel
        )

    except KeyboardInterrupt:
        print("\n" + "="*80)
        print("【测试结束】用户中断")
        print("="*80)
        print(f"测试统计:")
        print(f"  - TICK数量: {g_tick_counter}")
        print(f"  - 下单次数: {g_order_count}")
        print(f"  - 撤单次数: {g_cancel_count}")
        print(f"  - 重发次数: {g_resend_count}")
        print(f"\n测试结论:")
        if g_resend_count > 0:
            print(f"  ✅ 撤单重发功能正常工作！")
            print(f"  ✅ 成功触发{g_resend_count}次超时撤单重发")
        else:
            print(f"  ⚠️ 未触发超时撤单重发")
            print(f"     可能原因：测试时间过短或订单快速成交")
        print("="*80 + "\n")
        runner.stop()

    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
