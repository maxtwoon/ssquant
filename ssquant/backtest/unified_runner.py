#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一策略运行器
支持历史回测、SIMNOW模拟交易、实盘交易三种模式
实现"一次编写，多处运行"的策略开发模式
"""

import time
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from enum import Enum

from .backtest_core import MultiSourceBacktester
from ..api.strategy_api import create_strategy_api


class RunMode(Enum):
    """运行模式枚举"""
    BACKTEST = "backtest"           # 历史回测
    SIMNOW = "simnow"               # SIMNOW模拟交易
    REAL_TRADING = "real_trading"   # 实盘交易


class UnifiedStrategyRunner:
    """
    统一策略运行器
    
    支持三种运行模式：
    1. 历史数据回测
    2. SIMNOW模拟交易
    3. 实盘CTP交易
    
    使用示例：
        runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
        runner.set_config({...})
        results = runner.run(strategy_func, initialize_func, params)
    """
    
    def __init__(self, mode: RunMode = RunMode.BACKTEST):
        """
        初始化统一策略运行器
        
        Args:
            mode: 运行模式
        """
        self.mode = mode
        self.config = {}
        self.strategy_func = None
        self.initialize_func = None
        self.strategy_params = {}
        
        # 各模式的运行器
        self.backtester = None
        self.live_runner = None
        
        # 品牌与免责声明
        self._print_disclaimer()
        print(f"[统一运行器] 初始化 - 模式: {mode.value}")
    
    def _print_disclaimer(self):
        """打印品牌信息与免责声明"""
        border = "=" * 80
        print(f"\n{border}")
        print("  🐿️  松鼠Quant (SSQuant) - 专业量化交易框架")
        print(f"{border}")
        print("  🌐 官方网站: quant789.com")
        print("  📱 公众号  : 松鼠Quant")
        print(f"{border}")
        print("  ⚠️  风险提示 & 免责声明:")
        print("  1. 期货交易具有高风险，可能导致本金全部损失。")
        print("  2. 本软件仅供学习、研究与策略开发使用，不构成任何投资建议，且不能保证框架无BUG。")
        print("  3. 历史回测业绩不代表未来表现，模拟盘盈利不代表实盘盈利。")
        print("  4. 使用本软件产生的任何交易盈亏由用户自行承担，开发者不承担任何责任。")
        print("  5. 若不同意以上条款，请立即停止使用并退出！")
        print(f"{border}\n")

    def set_config(self, config: Dict[str, Any]):
        """
        设置配置
        
        Args:
            config: 配置字典，根据不同模式需要不同参数
                
                回测模式必填:
                    - symbol: 合约代码
                    - start_date: 开始日期
                    - end_date: 结束日期
                    - kline_period: K线周期
                    
                SIMNOW/实盘模式必填:
                    - investor_id: 账号
                    - password: 密码
                    - symbol: 合约代码
                    
                SIMNOW额外参数:
                    - server_name: 服务器名称 (默认: "24hour")
                    
                实盘额外参数:
                    - broker_id: 期货公司代码
                    - md_server: 行情服务器
                    - td_server: 交易服务器
                    - app_id: AppID
                    - auth_code: 授权码
                    
                通用可选参数:
                    - initial_capital: 初始资金
                    - commission: 手续费率
                    - margin_rate: 保证金率
                    - contract_multiplier: 合约乘数
                    - enable_data_recording: 是否启用数据落盘 (默认: False)
                    - data_recording_path: 数据落盘路径
        """
        self.config = config
        
        # 验证配置
        self._validate_config()
        
        return self
    
    def _validate_config(self):
        """验证配置"""
        if self.mode == RunMode.BACKTEST:
            # 支持单数据源和多数据源两种配置方式
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['start_date', 'end_date', 'data_sources']
            else:
                # 单数据源模式
                required = ['symbol', 'start_date', 'end_date', 'kline_period']
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"回测模式缺少必填参数: {missing}")
        
        elif self.mode == RunMode.SIMNOW:
            # 支持单数据源和多数据源两种配置方式
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['investor_id', 'password', 'data_sources']
            else:
                # 单数据源模式
                required = ['investor_id', 'password', 'symbol']
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"SIMNOW模式缺少必填参数: {missing}")
        
        elif self.mode == RunMode.REAL_TRADING:
            # 支持单数据源和多数据源两种配置方式
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['broker_id', 'investor_id', 'password', 'md_server', 
                           'td_server', 'app_id', 'auth_code', 'data_sources']
            else:
                # 单数据源模式
                required = ['broker_id', 'investor_id', 'password', 'md_server', 
                           'td_server', 'app_id', 'auth_code', 'symbol']
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"实盘模式缺少必填参数: {missing}")
    
    def run(self, strategy: Callable, initialize: Optional[Callable] = None, 
            strategy_params: Optional[Dict] = None,
            on_trade: Optional[Callable] = None,
            on_order: Optional[Callable] = None,
            on_cancel: Optional[Callable] = None,
            on_order_error: Optional[Callable] = None,
            on_cancel_error: Optional[Callable] = None,
            on_account: Optional[Callable] = None,
            on_position: Optional[Callable] = None) -> Dict[str, Any]:
        """
        运行策略
        
        Args:
            strategy: 策略函数
            initialize: 初始化函数
            strategy_params: 策略参数
            
            以下回调仅实盘模式(SIMNOW/REAL_TRADING)有效:
            on_trade: 成交回调 - 订单成交时触发
            on_order: 报单回调 - 报单状态变化时触发
            on_cancel: 撤单回调 - 订单被撤销时触发
            on_order_error: 报单错误回调 - 报单失败时触发
            on_cancel_error: 撤单错误回调 - 撤单失败时触发
            on_account: 账户资金回调 - 资金变化时触发
            on_position: 持仓回调 - 持仓变化时触发
            
        Returns:
            运行结果字典
        """
        self.strategy_func = strategy
        self.initialize_func = initialize
        self.strategy_params = strategy_params or {}
        self.on_trade_callback = on_trade
        self.on_order_callback = on_order
        self.on_cancel_callback = on_cancel
        self.on_order_error_callback = on_order_error
        self.on_cancel_error_callback = on_cancel_error
        self.on_account_callback = on_account
        self.on_position_callback = on_position
        
        print(f"\n{'='*80}")
        print(f"运行模式: {self.mode.value}")
        print(f"{'='*80}\n")
        
        if self.mode == RunMode.BACKTEST:
            return self._run_backtest()
        elif self.mode == RunMode.SIMNOW:
            return self._run_simnow()
        elif self.mode == RunMode.REAL_TRADING:
            return self._run_real_trading()
        else:
            raise ValueError(f"不支持的运行模式: {self.mode}")
    
    def _run_backtest(self) -> Dict[str, Any]:
        """运行历史回测"""
        from ..config.trading_config import get_api_auth
        API_USERNAME, API_PASSWORD = get_api_auth()
        
        # 创建回测器
        self.backtester = MultiSourceBacktester()
        
        # 设置基础配置
        self.backtester.set_base_config({
            'username': API_USERNAME,
            'password': API_PASSWORD,
            'use_cache': self.config.get('use_cache', True),
            'save_data': self.config.get('save_data', True),
            'align_data': self.config.get('align_data', False),
            'fill_method': self.config.get('fill_method', 'ffill'),
            'debug': self.config.get('debug', False)
        })
        
        # 添加数据源配置（支持单数据源和多数据源）
        if 'data_sources' in self.config:
            # 多数据源模式：需要将同一品种的多个周期合并
            symbol_periods_map = {}  # {symbol: [period_config_list]}
            symbol_config_map = {}   # {symbol: config}
            
            # 第一步：收集所有品种的周期配置
            for ds_config in self.config['data_sources']:
                symbol = ds_config['symbol']
                kline_period = ds_config.get('kline_period', '1d')
                adjust_type = ds_config.get('adjust_type', self.config.get('adjust_type', '1'))
                
                # 将周期配置添加到对应品种的列表中
                if symbol not in symbol_periods_map:
                    symbol_periods_map[symbol] = []
                    # 保存品种的基础配置（使用第一次遇到的配置）
                    symbol_config_map[symbol] = {
                        'start_date': self.config['start_date'],
                        'end_date': self.config['end_date'],
                        'initial_capital': self.config.get('initial_capital', 100000),
                        'commission': self.config.get('commission', 0.0001),
                        'margin_rate': self.config.get('margin_rate', 0.1),
                        'contract_multiplier': ds_config.get('contract_multiplier', 
                                                              self.config.get('contract_multiplier', 10)),
                        'slippage_ticks': ds_config.get('slippage_ticks', 
                                                         self.config.get('slippage_ticks', 1)),
                        'price_tick': ds_config.get('price_tick', 
                                                     self.config.get('price_tick', 1.0)),
                    }
                
                # 添加周期配置
                symbol_periods_map[symbol].append({
                    'kline_period': kline_period,
                    'adjust_type': adjust_type
                })
            
            # 第二步：为每个品种添加完整的配置（包含所有周期）
            for symbol, periods in symbol_periods_map.items():
                config = symbol_config_map[symbol].copy()
                config['periods'] = periods
                # 支持本地文件数据加载（多数据源模式同样透传 file_path）
                if self.config.get('file_path'):
                    config['file_path'] = self.config['file_path']
                if self.config.get('db_table'):
                    config['db_table'] = self.config['db_table']
                self.backtester.add_symbol_config(symbol=symbol, config=config)
        else:
            # 单数据源模式
            symbol = self.config['symbol']
            symbol_config = {
                'start_date': self.config['start_date'],
                'end_date': self.config['end_date'],
                'initial_capital': self.config.get('initial_capital', 100000),
                'commission': self.config.get('commission', 0.0001),
                'margin_rate': self.config.get('margin_rate', 0.1),
                'contract_multiplier': self.config.get('contract_multiplier', 10),
                'slippage_ticks': self.config.get('slippage_ticks', 1),
                'price_tick': self.config.get('price_tick', 1.0),
                'periods': [
                    {
                        'kline_period': self.config['kline_period'],
                        'adjust_type': self.config.get('adjust_type', '1')
                    }
                ]
            }
            # 支持本地文件数据加载
            if self.config.get('file_path'):
                symbol_config['file_path'] = self.config['file_path']
            self.backtester.add_symbol_config(
                symbol=symbol,
                config=symbol_config
            )
        
        # 运行回测
        results = self.backtester.run(
            strategy=self.strategy_func,
            initialize=self.initialize_func,
            strategy_params=self.strategy_params
        )
        
        return results
    
    def _run_simnow(self) -> Dict[str, Any]:
        """运行SIMNOW模拟交易"""
        from .live_trading_adapter import LiveTradingAdapter
        
        # 验证策略函数
        if not self.strategy_func:
            raise ValueError("策略函数不能为空")
        
        # 创建实盘适配器
        self.live_runner = LiveTradingAdapter(
            mode='simnow',
            config=self.config,
            strategy_func=self.strategy_func,
            initialize_func=self.initialize_func,
            strategy_params=self.strategy_params,
            on_trade_callback=self.on_trade_callback,
            on_order_callback=self.on_order_callback,
            on_cancel_callback=self.on_cancel_callback,
            on_order_error_callback=self.on_order_error_callback,
            on_cancel_error_callback=self.on_cancel_error_callback,
            on_account_callback=self.on_account_callback,
            on_position_callback=self.on_position_callback
        )
        
        # 运行
        results = self.live_runner.run()
        
        return results
    
    def _run_real_trading(self) -> Dict[str, Any]:
        """运行实盘交易"""
        from .live_trading_adapter import LiveTradingAdapter
        
        # 验证策略函数
        if not self.strategy_func:
            raise ValueError("策略函数不能为空")
        
        # 创建实盘适配器
        self.live_runner = LiveTradingAdapter(
            mode='real',
            config=self.config,
            strategy_func=self.strategy_func,
            initialize_func=self.initialize_func,
            strategy_params=self.strategy_params,
            on_trade_callback=self.on_trade_callback,
            on_order_callback=self.on_order_callback,
            on_cancel_callback=self.on_cancel_callback,
            on_order_error_callback=self.on_order_error_callback,
            on_cancel_error_callback=self.on_cancel_error_callback,
            on_account_callback=self.on_account_callback,
            on_position_callback=self.on_position_callback
        )
        
        # 运行
        results = self.live_runner.run()
        
        return results
    
    def stop(self):
        """停止运行"""
        if self.live_runner:
            self.live_runner.stop()
            print("[统一运行器] 已停止")
