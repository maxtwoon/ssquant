#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交易配置文件

本文件只保存配置数据，不包含业务逻辑函数。
所有函数已抽离到 config_helpers.py。
"""

# ========== 松鼠俱乐部会员认证 quant789.com ========== 小松鼠VX：viquant01
API_USERNAME = ""              # 俱乐部账号 (您的俱乐部手机号或邮箱)
API_PASSWORD = ""            # 俱乐部密码 (注意：不是AI模型的API Key)

# ========== 复权设置 ==========
# 复权数据处理策略:
#   - data_server（远程服务器）只存储不复权(raw)数据
#   - 从 data_server 获取数据后，由框架本地进行复权计算
#   - 本地复权算法位于: ssquant/data/local_adjust.py
#   - adjust_type: '0'=不复权, '1'=后复权, '2'=前复权
ENABLE_REMOTE_ADJUST = True


# ========== 回测默认配置 ==========
BACKTEST_DEFAULTS = {
    # -------- 资金配置 --------
    'initial_capital': 20000,       # 初始资金 (元)
    'commission': 0.0001,           # 手续费率 (万分之一)
    'margin_rate': 0.1,             # 保证金率 (10%)
    
    # -------- 合约参数 --------
    'contract_multiplier': 10,      # 合约乘数 (吨/手)
    'price_tick': 1.0,              # 最小变动价位 (元)
    'slippage_ticks': 1,            # 滑点跳数
    'adjust_type': '1',             # 复权类型: '0'不复权, '1'后复权, '2'前复权
    
    # -------- 数据对齐配置 (多数据源时使用) --------
    'align_data': False,            # 默认不开启，是否对齐多数据源的时间索引 (跨周期过滤策略需开启)
    'fill_method': 'ffill',         # 缺失值填充方法: 'ffill'向前填充, 'bfill'向后填充
    
    # -------- 数据窗口配置 --------
    'lookback_bars': 0,           # K线回溯窗口大小，0表示不限制（返回全部历史数据），建议设置500-2000
    
    # -------- 数据源模式 --------
    'data_source_mode': 'data_server',   # 数据源模式: 'data_server'(远程data_server,需API账号) 或 'local'(本地SQLite,无需账号)
    
    # -------- 缓存与调试 --------
    'use_cache': True,              # 是否使用本地缓存数据
    'save_data': True,              # 是否保存数据到本地缓存
    'debug': False,                 # 是否开启调试模式
    # -------- 实盘 Tick 队列配置（回测中无影响，保留统一入口） --------
    'tick_queue_maxsize': 20000,    # Tick处理队列最大长度。高频多品种建议 10000-50000
}


# ========== 账户配置 ==========
# 在此定义所有账户，策略中通过 account='账户名' 使用
ACCOUNTS = {
    
    # -------------------- SIMNOW 模拟账户 --------------------
    'simnow_default': {
        # 账户认证 (必填)
        'investor_id': '',                # SIMNOW账号 (在 simnow.com.cn 注册)
        'password': '',                   # SIMNOW密码
        'server_name': '电信1',            # 服务器: '电信1', '电信2', '移动', 'TEST', '24hour'
        
        # 交易参数
        'kline_period': '1m',             # K线周期: '1m', '5m', '15m', '30m', '1h', '1d'
        'price_tick': 1.0,                # 最小变动价位 (螺纹钢=1, 黄金=0.02)
        'order_offset_ticks': 5,          # 委托价格偏移跳数 (超价下单，确保成交)
        
        # 智能算法交易配置
        'algo_trading': False,             # 是否启用算法交易
        'order_timeout': 10,              # 订单超时时间(秒)，0表示不启用
        'retry_limit': 3,                 # 最大重试次数
        'retry_offset_ticks': 5,          # 重试时的超价跳数 (相对于对手价)
        
        # 数据配置
        'preload_history': True,          # 是否预加载历史K线
        'history_lookback_bars': 100,     # 预加载K线数量
        'lookback_bars': 0,               # K线/TICK缓存窗口大小，0表示使用默认值(1000条)，建议设置500-2000
        'adjust_type': '1',               # 复权类型: '0'不复权, '1'后复权, '2'前复权
        # 'history_symbol': 'rb888',      # 自定义历史数据源 (默认自动推导为主力XXX888)
                                         # 跨期套利时可指定: 主力用'rb888', 次主力用'rb777'
        
        # K线数据源配置
        'kline_source': 'data_server',     # K线数据源: 'data_server'(默认,远程推送) 或 'local'(CTP本地聚合)
        
        # 回调配置
        'enable_tick_callback': False,     # 是否启用TICK回调 (实时行情推送)
        # data_server + tick回调 节流间隔（秒）
        # 仅 kline_source='data_server' 且 enable_tick_callback=True 时生效
        # 作用：避免开盘tick洪峰导致队列积压/假死（多品种场景尤其明显）
        # 设为 0 可关闭节流（每个tick都触发策略，适合需要逐tick止盈止损的策略）
        'tick_callback_interval': 0.5,
        # Tick队列容量（实盘高频保护）
        # 建议:
        #   - 低频/少品种: 5000-10000
        #   - 中频/10~20品种: 15000-30000
        #   - 高频/30+品种或夜盘活跃时段: 30000-50000
        # 调大后更能抗瞬时洪峰，但会占用更多内存；如果日志中频繁出现
        # "Tick队列已满/积压压缩"，优先从 20000 提升到 30000 或 50000。
        'tick_queue_maxsize': 20000,
        
        # -------- 自动换月（仅 SIMNOW/实盘；回测不支持，勿在 RunMode.BACKTEST 里依赖）--------
        # auto_roll_mode：发单节奏（与 reopen 不冲突）。'simultaneous'=同一次策略回调里连发委托、不等上一笔成交；
        #   reopen=True 时先发平旧再发开新（两笔）；reopen=False 时只发平旧（一笔）。
        # 'sequential'=先只发平旧，旧腿平仓闭环后再发开新（reopen=False 时仅平旧）；适合希望开新晚于平旧成交的场景。
        # 用法：get_config(..., auto_roll_enabled=True, auto_roll_mode='simultaneous' 或 'sequential')；
        #       多品种可在 data_sources[] 里对某一品种单独写 auto_roll_*。
        'auto_roll_enabled': False,       # True=框架在策略前自动移仓；False=不启用
        'auto_roll_mode': 'simultaneous', # 见上，一般保持 'simultaneous'
        'auto_roll_reopen': True,         # 是否在新主力补回仓位；与 mode 分工不同，见上段
        'auto_roll_order_type': 'next_bar_open',  # 移仓下单方式，与策略里 order_type 含义一致
        'auto_roll_close_offset_ticks': None,     # 平旧限价跳数；None=用上面 order_offset_ticks
        'auto_roll_open_offset_ticks': None,      # 开新限价跳数；None=用上面 order_offset_ticks
        'auto_roll_verify_timeout_bars': 500,     # 移仓后闭环超时（策略调用次数上限，超时重置防死循环）
        'auto_roll_log_enabled': True,    # True=写移仓专用本地日志（复盘）；False=不写
        'auto_roll_log_dir': None,         # 日志目录；None=默认 ./live_data/rollover_logs（可写绝对路径）
        'auto_roll_log_jsonl': False,      # True=同时写 jsonl 便于程序解析
        
        # 数据保存配置 (默认全部关闭)
        'save_kline_csv': False,           # 是否保存K线到CSV文件
        'save_kline_db': True,            # 是否保存K线到数据库
        'save_tick_csv': False,            # 是否保存TICK到CSV文件
        'save_tick_db': False,            # 是否保存TICK到数据库
        'data_save_path': './live_data',  # CSV文件保存路径
        'db_path': 'data_cache/backtest_data.db',  # 数据库路径
    },
    
    # -------------------- 实盘账户 --------------------
    'real_default': {
        # 账户认证 (必填，向期货公司获取)
        'broker_id': '',                  # 期货公司代码 (如: '9999')
        'investor_id': '',                # 资金账号
        'password': '',                   # 交易密码
        'md_server': '',                  # 行情服务器地址 (如: 'tcp://180.168.146.187:10211')
        'td_server': '',                  # 交易服务器地址 (如: 'tcp://180.168.146.187:10201')
        'app_id': '',                     # 应用ID (向期货公司申请)
        'auth_code': '',                  # 授权码 (向期货公司申请)
        
        # 交易参数
        'kline_period': '1d',             # K线周期: '1m', '5m', '15m', '30m', '1h', '1d'
        'price_tick': 1.0,                # 最小变动价位 (螺纹钢=1, 黄金=0.02)
        'order_offset_ticks': 5,          # 委托价格偏移跳数 (超价下单，确保成交)
        
        # 智能算法交易配置
        'algo_trading': False,             # 是否启用算法交易
        'order_timeout': 10,              # 订单超时时间(秒)，0表示不启用
        'retry_limit': 3,                 # 最大重试次数
        'retry_offset_ticks': 5,          # 重试时的超价跳数 (相对于对手价)
        
        # 数据配置
        'preload_history': True,          # 是否预加载历史K线
        'history_lookback_bars': 100,     # 预加载K线数量
        'lookback_bars': 0,               # K线/TICK缓存窗口大小，0表示使用默认值(1000条)，建议设置500-2000
        'adjust_type': '1',               # 复权类型: '0'不复权, '1'后复权, '2'前复权
        # 'history_symbol': 'rb888',      # 自定义历史数据源 (默认自动推导为主力XXX888)
                                         # 跨期套利时可指定: 主力用'rb888', 次主力用'rb777'
        
        # K线数据源配置
        'kline_source': 'data_server',     # K线数据源: 'data_server'(默认,远程推送) 或 'local'(CTP本地聚合)
        
        # 回调配置
        'enable_tick_callback': False,     # 是否启用TICK回调 (实时行情推送)
        # data_server + tick回调 节流间隔（秒）
        # 仅 kline_source='data_server' 且 enable_tick_callback=True 时生效
        # 作用：避免开盘tick洪峰导致队列积压/假死（多品种场景尤其明显）
        # 设为 0 可关闭节流（每个tick都触发策略，适合需要逐tick止盈止损的策略）
        'tick_callback_interval': 0.5,
        # Tick队列容量（实盘高频保护）
        # 推荐先用 20000；若云服务器 CPU 足够、品种较多、夜盘高频活跃，
        # 可上调到 30000-50000。若内存紧张或品种少，可降到 10000。
        'tick_queue_maxsize': 20000,
        
        # -------- 自动换月（仅实盘；回测不支持）--------
        # auto_roll_mode / auto_roll_reopen：与 simnow 段说明相同（发单节奏 vs 是否补开新仓）。
        'auto_roll_enabled': False,       # True=框架策略前自动移仓；False=不启用
        'auto_roll_mode': 'simultaneous', # 见 simnow 段
        'auto_roll_reopen': True,         # 见 simnow 段
        'auto_roll_order_type': 'next_bar_open',  # 移仓委托类型
        'auto_roll_close_offset_ticks': None,     # 平旧跳数；None=用 order_offset_ticks
        'auto_roll_open_offset_ticks': None,      # 开新跳数；None=用 order_offset_ticks
        'auto_roll_verify_timeout_bars': 500,     # 闭环等待上限（策略调用次数）
        'auto_roll_log_enabled': True,    # True=写移仓本地日志便于审计复盘
        'auto_roll_log_dir': None,         # 日志目录；None=默认 live_data/rollover_logs
        'auto_roll_log_jsonl': False,      # True=额外 jsonl 行格式
        
        # 数据保存配置 (默认全部关闭)
        'save_kline_csv': False,          # 是否保存K线到CSV文件
        'save_kline_db': True,           # 是否保存K线到数据库
        'save_tick_csv': False,           # 是否保存TICK到CSV文件
        'save_tick_db': False,            # 是否保存TICK到数据库
        'data_save_path': './live_data',  # CSV文件保存路径
        'db_path': 'data_cache/backtest_data.db',  # 数据库路径
    },
}


# ========== 函数代理（保持向后兼容） ==========
# 函数定义已迁移到 config_helpers.py，此处导入重新导出，确保旧代码无需修改
from .config_helpers import get_config, add_account, list_accounts


def get_api_auth():
    """获取数据API认证"""
    return API_USERNAME, API_PASSWORD


def set_api_auth(username: str, password: str):
    """设置数据API认证"""
    global API_USERNAME, API_PASSWORD
    API_USERNAME = username
    API_PASSWORD = password
