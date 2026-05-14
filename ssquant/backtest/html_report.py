"""
HTML 交互式回测报告生成器
使用 Plotly 生成交互式图表，替代 matplotlib
支持多数据源、多品种回测结果展示
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

# 自定义JSON编码器，处理NumPy和pandas数据类型
class NumpyEncoder(json.JSONEncoder):
    """处理 NumPy/pandas 数据类型的 JSON 序列化
    
    解决 pd.read_sql_query 读取整数类型（如成交价）时，
    返回 np.int64 导致 json.dumps 报错的问题。
    
    兼容性：Python 3.9+, NumPy 1.x/2.x, pandas 1.x/2.x
    """
    def default(self, obj):
        # NumPy 整数类型（np.integer 是所有 numpy 整数的基类）
        if isinstance(obj, np.integer):
            return int(obj)
        # NumPy 浮点类型（np.floating 是所有 numpy 浮点的基类）
        if isinstance(obj, np.floating):
            return float(obj)
        # NumPy 布尔类型
        if isinstance(obj, np.bool_):
            return bool(obj)
        # NumPy 数组
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        # pandas Timestamp 或其他带 isoformat 的时间类型
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        # 处理 pandas NA/NaN 值（需要 try-except 因为某些类型会报错）
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
        # 兜底：通过类型名称判断（处理某些版本差异导致的遗漏）
        type_name = type(obj).__name__.lower()
        if 'int' in type_name:
            try:
                return int(obj)
            except (TypeError, ValueError):
                pass
        if 'float' in type_name:
            try:
                return float(obj)
            except (TypeError, ValueError):
                pass
        return super().default(obj)

# Plotly 导入
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("警告: plotly 未安装，将使用简化版 HTML 报告")
    print("安装命令: pip install plotly")


class HTMLReportGenerator:
    """HTML 交互式报告生成器 - 支持多数据源"""
    
    # HTML 模板
    HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - {strategy_name}</title>
    {plotly_script_tag}
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        .header .logo {{
            font-size: 36px;
        }}
        .header .subtitle {{
            color: #a0a0a0;
            font-size: 14px;
        }}
        .header .brand {{
            float: right;
            text-align: right;
            color: #888;
            font-size: 12px;
        }}
        .header .brand a {{
            color: #64b5f6;
            text-decoration: none;
        }}
        
        /* 数据源切换标签 */
        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .tab {{
            padding: 12px 24px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }}
        .tab:hover {{
            background: rgba(255,255,255,0.1);
        }}
        .tab.active {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-color: #64b5f6;
        }}
        .kline-tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .kline-tabs .tab {{
            padding: 8px 16px;
            font-size: 12px;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        
        /* 综合绩效区域 */
        .summary-section {{
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .summary-title {{
            font-size: 20px;
            margin-bottom: 20px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 18px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }}
        .metric-card .label {{
            font-size: 11px;
            color: #888;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .metric-card .value {{
            font-size: 22px;
            font-weight: 700;
        }}
        .metric-card .value.positive {{
            color: #4caf50;
        }}
        .metric-card .value.negative {{
            color: #f44336;
        }}
        .metric-card .value.neutral {{
            color: #64b5f6;
        }}
        .chart-container {{
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .chart-title {{
            font-size: 18px;
            margin-bottom: 15px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .chart-title .icon {{
            font-size: 24px;
        }}
        
        /* 数据源绩效对比表 */
        .comparison-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 20px;
        }}
        .comparison-table th {{
            background: rgba(255,255,255,0.1);
            padding: 12px 10px;
            text-align: right;
            font-weight: 600;
        }}
        .comparison-table th:first-child {{
            text-align: left;
        }}
        .comparison-table td {{
            padding: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            text-align: right;
        }}
        .comparison-table td:first-child {{
            text-align: left;
            font-weight: 600;
            color: #64b5f6;
        }}
        .comparison-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        .trades-table th {{
            background: rgba(255,255,255,0.1);
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}
        .trades-table td {{
            padding: 10px 8px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .trades-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        .trades-table .profit {{
            color: #4caf50;
        }}
        .trades-table .loss {{
            color: #f44336;
        }}
        .table-wrapper {{
            border-radius: 8px;
        }}
        .table-wrapper::-webkit-scrollbar {{
            width: 8px;
        }}
        .table-wrapper::-webkit-scrollbar-track {{
            background: rgba(255,255,255,0.05);
        }}
        .table-wrapper::-webkit-scrollbar-thumb {{
            background: rgba(255,255,255,0.2);
            border-radius: 4px;
        }}
        
        /* 交易记录筛选器 */
        .trades-filter {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 15px;
            padding: 15px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
        }}
        .filter-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .filter-group label {{
            font-size: 12px;
            color: #aaa;
        }}
        .filter-group input, .filter-group select {{
            padding: 6px 10px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
        }}
        .filter-group input::placeholder {{
            color: #666;
        }}
        .filter-group select {{
            cursor: pointer;
        }}
        .filter-group select option {{
            background: #1a1a2e;
            color: #fff;
        }}
        .filter-btn {{
            padding: 6px 15px;
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border: none;
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        .filter-btn:hover {{
            opacity: 0.8;
        }}
        .filter-btn.reset {{
            background: rgba(255,255,255,0.1);
        }}
        
        /* 分页器 */
        .pagination {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            margin-top: 15px;
            flex-wrap: wrap;
        }}
        .pagination button {{
            padding: 8px 12px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .pagination button:hover:not(:disabled) {{
            background: rgba(255,255,255,0.15);
        }}
        .pagination button:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}
        .pagination button.active {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-color: #64b5f6;
        }}
        .pagination .page-info {{
            font-size: 12px;
            color: #aaa;
            margin: 0 10px;
        }}
        .pagination .page-jump {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .pagination .page-jump input {{
            width: 50px;
            padding: 6px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            text-align: center;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 12px;
        }}
        .footer a {{
            color: #64b5f6;
            text-decoration: none;
        }}
        .tag {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }}
        .tag.buy {{
            background: rgba(76, 175, 80, 0.2);
            color: #4caf50;
        }}
        .tag.sell {{
            background: rgba(244, 67, 54, 0.2);
            color: #f44336;
        }}
        .source-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            background: rgba(100, 181, 246, 0.2);
            color: #64b5f6;
            margin-right: 5px;
        }}
        
        /* 图例样式 */
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-bottom: 15px;
            padding: 10px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 20px;
            height: 3px;
            border-radius: 2px;
        }}
        
        @media (max-width: 768px) {{
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .header h1 {{
                font-size: 22px;
            }}
            .tabs {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="brand">
                <div>🐿️ 松鼠QuantAi编写助手</div>
                <div><a href="https://ai.kanpan789.com" target="_blank">ai.kanpan789.com</a></div>
            </div>
            <h1>
                <span class="logo">📊</span>
                回测报告
            </h1>
            <div class="subtitle">
                {strategy_info} | 回测区间: {start_date} ~ {end_date} | 生成时间: {report_time}
            </div>
        </div>
        
        <!-- 综合绩效区域 -->
        <div class="summary-section">
            <div class="summary-title">
                <span>📈</span> 综合绩效摘要
            </div>
            <div class="metrics-grid">
                {combined_metrics_cards}
            </div>
            <div style="margin-top: 15px; padding: 10px 15px; background: rgba(76, 175, 80, 0.1); border-radius: 8px; font-size: 12px; color: #aaa; border-left: 3px solid #4caf50;">
                💡 <strong>说明：</strong>以上所有绩效指标均已扣除<span style="color: #81c784;">手续费</span>和<span style="color: #81c784;">滑点成本</span>（按配置的滑点跳数×最小变动价位计算）
            </div>
        </div>
        
        <!-- 数据源对比表 -->
        {source_comparison_section}
        
        <!-- 利润曲线图（从0开始，便于对比各数据源盈亏） -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon">📈</span>
                利润曲线对比（盈亏走势）
                <span style="font-size: 12px; color: #888; margin-left: 10px;">点击图例可显示/隐藏曲线</span>
            </div>
            <div id="profit-chart"></div>
        </div>
        
        <!-- 综合回撤图 -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon">📉</span>
                回撤分析
            </div>
            <div id="drawdown-chart"></div>
        </div>
        
        <!-- K线图/TICK价格图与交易标记 -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon" id="price-chart-icon">🕯️</span>
                <span id="price-chart-title">K线图与交易标记</span>
            </div>
            <div class="kline-tabs" id="kline-tabs"></div>
            <div id="kline-chart" style="height: 500px;"></div>
        </div>
        
        <!-- 各数据源详情标签页 -->
        {source_tabs}
        
        <!-- 各数据源详情内容 -->
        {source_details}
        
        <div class="footer">
            <p>由 <a href="https://gitee.com/ssquant/ssquant" target="_blank">松鼠Quant-ssquant框架</a> 生成</p>
            <p>⚠️ 历史回测不代表未来表现，投资有风险，入市需谨慎</p>
        </div>
    </div>
    
    <script>
        // 图表颜色
        var colors = ['#64b5f6', '#4caf50', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#8bc34a', '#ff5722'];
        
        // 利润曲线数据（从0开始，便于对比）
        var profitDataSources = {profit_data_sources};
        var combinedProfitData = {combined_profit_data};
        var combinedGrossProfitData = {combined_gross_profit_data};
        var priceDataSources = {price_data_sources};
        
        // 绘制利润曲线
        var profitTraces = [];
        
        // 添加各数据源的利润曲线
        profitDataSources.forEach(function(source, idx) {{
            var color = colors[idx % colors.length];
            profitTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                line: {{
                    color: color,
                    width: 1.5
                }},
                opacity: 0.7
            }});
        }});
        
        // 添加综合交易盈亏曲线（未扣手续费，黄色虚线）
        if (combinedGrossProfitData.dates && combinedGrossProfitData.dates.length > 0) {{
            profitTraces.push({{
                x: combinedGrossProfitData.dates,
                y: combinedGrossProfitData.values,
                type: 'scatter',
                mode: 'lines',
                name: '交易盈亏(未扣手续费)',
                line: {{
                    color: '#ffd54f',
                    width: 2,
                    dash: 'dash'
                }},
                opacity: 0.8
            }});
        }}
        
        // 添加综合净利润曲线（扣除手续费，白色实线）
        if (combinedProfitData.dates && combinedProfitData.dates.length > 0) {{
            profitTraces.push({{
                x: combinedProfitData.dates,
                y: combinedProfitData.values,
                type: 'scatter',
                mode: 'lines',
                name: '净利润(扣除手续费)',
                line: {{
                    color: '#ffffff',
                    width: 2.5
                }}
            }});
        }}
        
        // 添加价格曲线（使用右侧Y轴，默认隐藏）
        var priceColors = ['#90caf9', '#a5d6a7', '#ffcc80', '#f48fb1', '#ce93d8'];
        priceDataSources.forEach(function(source, idx) {{
            var color = priceColors[idx % priceColors.length];
            profitTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                yaxis: 'y2',
                line: {{
                    color: color,
                    width: 1,
                    dash: 'dot'
                }},
                opacity: 0.6,
                visible: 'legendonly'  // 默认隐藏，点击图例可显示
            }});
        }});
        
        // 使用最长数据源的时间作为统一的 X 轴类别
        var allDates = [];
        profitDataSources.forEach(function(source) {{
            source.dates.forEach(function(d) {{
                if (allDates.indexOf(d) === -1) allDates.push(d);
            }});
        }});
        allDates.sort();
        
        var profitLayout = {{
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {{ color: '#e0e0e0' }},
            xaxis: {{
                type: 'category',
                categoryorder: 'array',
                categoryarray: allDates,
                gridcolor: 'rgba(255,255,255,0.1)',
                nticks: 10,
                tickangle: -30
            }},
            yaxis: {{
                gridcolor: 'rgba(255,255,255,0.1)',
                tickformat: ',.0f',
                title: '利润(元)',
                zeroline: true,
                zerolinecolor: 'rgba(255,255,255,0.3)',
                zerolinewidth: 1,
                side: 'left'
            }},
            yaxis2: {{
                gridcolor: 'rgba(255,255,255,0.05)',
                tickformat: ',.2f',
                title: '价格/相对值',
                overlaying: 'y',
                side: 'right',
                showgrid: false
            }},
            margin: {{ l: 70, r: 70, t: 30, b: 60 }},
            hovermode: 'x unified',
            hoverlabel: {{
                bgcolor: '#fff',
                font: {{ color: '#333', size: 13 }},
                bordercolor: '#ccc'
            }},
            showlegend: true,
            legend: {{
                orientation: 'h',
                yanchor: 'bottom',
                y: 1.02,
                xanchor: 'left',
                x: 0,
                font: {{ size: 11 }}
            }},
            dragmode: 'pan'
        }};
        
        var profitConfig = {{
            scrollZoom: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['select2d', 'lasso2d'],
            displaylogo: false
        }};
        
        Plotly.newPlot('profit-chart', profitTraces, profitLayout, profitConfig);
        
        // 回撤数据
        var drawdownDataSources = {drawdown_data_sources};
        var combinedDrawdownData = {combined_drawdown_data};
        
        // 绘制回撤图
        var drawdownTraces = [];
        
        // 添加各数据源的回撤曲线
        drawdownDataSources.forEach(function(source, idx) {{
            var color = colors[idx % colors.length];
            drawdownTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                line: {{
                    color: color,
                    width: 1
                }},
                opacity: 0.5
            }});
        }});
        
        // 添加综合回撤曲线
        if (combinedDrawdownData.dates && combinedDrawdownData.dates.length > 0) {{
            drawdownTraces.push({{
                x: combinedDrawdownData.dates,
                y: combinedDrawdownData.values,
                type: 'scatter',
                mode: 'lines',
                name: '综合回撤',
                fill: 'tozeroy',
                fillcolor: 'rgba(244, 67, 54, 0.3)',
                line: {{
                    color: '#f44336',
                    width: 2
                }}
            }});
        }}
        
        // 使用最长数据源的时间作为统一的 X 轴类别
        var allDrawdownDates = [];
        drawdownDataSources.forEach(function(source) {{
            source.dates.forEach(function(d) {{
                if (allDrawdownDates.indexOf(d) === -1) allDrawdownDates.push(d);
            }});
        }});
        allDrawdownDates.sort();
        
        var drawdownLayout = {{
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {{ color: '#e0e0e0' }},
            xaxis: {{
                type: 'category',
                categoryorder: 'array',
                categoryarray: allDrawdownDates,
                gridcolor: 'rgba(255,255,255,0.1)',
                nticks: 10,
                tickangle: -30
            }},
            yaxis: {{
                gridcolor: 'rgba(255,255,255,0.1)',
                tickformat: '.2f',
                title: '回撤 (%)',
                autorange: 'reversed'
            }},
            margin: {{ l: 70, r: 30, t: 30, b: 60 }},
            hovermode: 'x unified',
            hoverlabel: {{
                bgcolor: '#fff',
                font: {{ color: '#333', size: 13 }},
                bordercolor: '#ccc'
            }},
            showlegend: false,
            dragmode: 'pan'
        }};
        
        var drawdownConfig = {{
            scrollZoom: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['select2d', 'lasso2d'],
            displaylogo: false
        }};
        
        Plotly.newPlot('drawdown-chart', drawdownTraces, drawdownLayout, drawdownConfig);
        
        // 标签页切换功能
        function switchTab(tabId) {{
            // 隐藏所有标签内容
            document.querySelectorAll('.tab-content').forEach(function(content) {{
                content.classList.remove('active');
            }});
            // 取消所有标签的激活状态
            document.querySelectorAll('.tab').forEach(function(tab) {{
                tab.classList.remove('active');
            }});
            // 显示选中的标签内容
            var content = document.getElementById('content-' + tabId);
            if (content) {{
                content.classList.add('active');
            }}
            // 激活选中的标签
            var tab = document.querySelector('[onclick="switchTab(\\'' + tabId + '\\')"]');
            if (tab) {{
                tab.classList.add('active');
            }}
        }}
        
        // K线图数据
        var klineDataSources = {kline_data_sources};
        var currentKlineIndex = 0;
        
        // 生成 K线切换标签
        function generateKlineTabs() {{
            var tabsHtml = '';
            klineDataSources.forEach(function(source, idx) {{
                var activeClass = idx === 0 ? 'active' : '';
                tabsHtml += '<div class="tab ' + activeClass + '" onclick="switchKline(' + idx + ')">' + source.name + '</div>';
            }});
            document.getElementById('kline-tabs').innerHTML = tabsHtml;
        }}
        
        // 切换 K线数据源
        function switchKline(idx) {{
            currentKlineIndex = idx;
            // 更新标签状态
            var tabs = document.querySelectorAll('#kline-tabs .tab');
            tabs.forEach(function(tab, i) {{
                if (i === idx) {{
                    tab.classList.add('active');
                }} else {{
                    tab.classList.remove('active');
                }}
            }});
            // 更新图表标题
            updateChartTitle(idx);
            // 重新绘制图表
            drawKlineChart(idx);
        }}
        
        // 更新图表标题（根据是TICK还是K线）
        function updateChartTitle(idx) {{
            if (klineDataSources.length === 0) return;
            var source = klineDataSources[idx];
            var isTick = source.ohlc.is_tick;
            var iconEl = document.getElementById('price-chart-icon');
            var titleEl = document.getElementById('price-chart-title');
            if (iconEl && titleEl) {{
                if (isTick) {{
                    iconEl.textContent = '📈';
                    titleEl.textContent = 'TICK价格图与交易标记';
                }} else {{
                    iconEl.textContent = '🕯️';
                    titleEl.textContent = 'K线图与交易标记';
                }}
            }}
        }}
        
        // 绘制 K线图 / TICK价格线图
        function drawKlineChart(idx) {{
            if (klineDataSources.length === 0) return;
            
            var source = klineDataSources[idx];
            var ohlc = source.ohlc;
            var traces = [];
            var chartTitle = '价格';
            
            // 判断是 TICK 数据还是 K线数据
            if (ohlc.is_tick) {{
                // TICK 数据：绘制价格线
                var priceLine = {{
                    x: ohlc.dates,
                    y: ohlc.prices,
                    type: 'scatter',
                    mode: 'lines',
                    name: source.name + ' 价格',
                    line: {{
                        color: '#64b5f6',
                        width: 1.5
                    }},
                    hoverinfo: 'y+x'
                }};
                traces.push(priceLine);
                chartTitle = 'TICK价格';
            }} else {{
                // K线数据：绘制蜡烛图
                var candlestick = {{
                    x: ohlc.dates,
                    open: ohlc.open,
                    high: ohlc.high,
                    low: ohlc.low,
                    close: ohlc.close,
                    type: 'candlestick',
                    name: source.name,
                    increasing: {{ line: {{ color: '#26a69a' }}, fillcolor: '#26a69a' }},
                    decreasing: {{ line: {{ color: '#ef5350' }}, fillcolor: '#ef5350' }}
                }};
                traces.push(candlestick);
            }}
            
            // 买入标记
            if (source.buy_markers.x.length > 0) {{
                traces.push({{
                    x: source.buy_markers.x,
                    y: source.buy_markers.y,
                    type: 'scatter',
                    mode: 'markers',
                    name: '买入',
                    marker: {{
                        symbol: 'triangle-up',
                        size: 12,
                        color: '#4caf50',
                        line: {{ color: '#fff', width: 1 }}
                    }},
                    text: source.buy_markers.text,
                    hoverinfo: 'text+x'
                }});
            }}
            
            // 卖出标记
            if (source.sell_markers.x.length > 0) {{
                traces.push({{
                    x: source.sell_markers.x,
                    y: source.sell_markers.y,
                    type: 'scatter',
                    mode: 'markers',
                    name: '卖出',
                    marker: {{
                        symbol: 'triangle-down',
                        size: 12,
                        color: '#f44336',
                        line: {{ color: '#fff', width: 1 }}
                    }},
                    text: source.sell_markers.text,
                    hoverinfo: 'text+x'
                }});
            }}

            // 反手：平多开空（与单笔「平多开空」或 平多+开空 合并腿一致）
            var fs = source.flip_short_markers || {{ x: [], y: [], text: [] }};
            if (fs.x && fs.x.length > 0) {{
                traces.push({{
                    x: fs.x,
                    y: fs.y,
                    type: 'scatter',
                    mode: 'markers',
                    name: '平多开空',
                    marker: {{
                        symbol: 'diamond',
                        size: 14,
                        color: '#ff9800',
                        line: {{ color: '#fff', width: 1 }}
                    }},
                    text: fs.text,
                    hoverinfo: 'text+x'
                }});
            }}
            // 反手：平空开多
            var fl = source.flip_long_markers || {{ x: [], y: [], text: [] }};
            if (fl.x && fl.x.length > 0) {{
                traces.push({{
                    x: fl.x,
                    y: fl.y,
                    type: 'scatter',
                    mode: 'markers',
                    name: '平空开多',
                    marker: {{
                        symbol: 'star',
                        size: 14,
                        color: '#00bcd4',
                        line: {{ color: '#fff', width: 1 }}
                    }},
                    text: fl.text,
                    hoverinfo: 'text+x'
                }});
            }}

            var layout = {{
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{ color: '#e0e0e0' }},
                xaxis: {{
                    type: 'category',
                    gridcolor: 'rgba(255,255,255,0.1)',
                    rangeslider: {{ visible: false }},
                    nticks: 10,
                    tickangle: -30
                }},
                yaxis: {{
                    gridcolor: 'rgba(255,255,255,0.1)',
                    tickformat: ',.2f',
                    title: chartTitle
                }},
                margin: {{ l: 70, r: 30, t: 30, b: 60 }},
                hovermode: 'x unified',
                hoverlabel: {{
                    bgcolor: '#fff',
                    font: {{ color: '#333', size: 13 }},
                    bordercolor: '#ccc'
                }},
                showlegend: true,
                legend: {{ x: 0, y: 1.1, orientation: 'h' }},
                dragmode: 'pan'
            }};
            
            var config = {{
                scrollZoom: true,
                displayModeBar: true,
                modeBarButtonsToRemove: ['select2d', 'lasso2d'],
                displaylogo: false
            }};
            
            Plotly.newPlot('kline-chart', traces, layout, config);
        }}
        
        // 初始化 K线图/TICK价格图
        if (klineDataSources.length > 0) {{
            generateKlineTabs();
            updateChartTitle(0);
            drawKlineChart(0);
        }}
        
        // ========== 交易记录分页和筛选功能 ==========
        var tradesData = {{}};  // 存储所有交易数据
        var filteredData = {{}};  // 存储筛选后的数据
        var pageSize = 50;  // 每页显示条数
        var currentPages = {{}};  // 各数据源当前页码
        
        // 初始化交易记录
        function initTradesTable(sourceIdx) {{
            var tbody = document.getElementById('trades-tbody-' + sourceIdx);
            if (!tbody) return;
            
            // 保存原始数据
            var rows = tbody.querySelectorAll('tr');
            tradesData[sourceIdx] = [];
            rows.forEach(function(row) {{
                tradesData[sourceIdx].push({{
                    element: row.cloneNode(true),
                    time: row.cells[1] ? row.cells[1].textContent : '',
                    action: row.cells[2] ? row.cells[2].textContent : '',
                    price: row.cells[3] ? row.cells[3].textContent : '',
                    profit: row.cells[5] ? row.cells[5].textContent : ''
                }});
            }});
            
            filteredData[sourceIdx] = tradesData[sourceIdx].slice();
            currentPages[sourceIdx] = 1;
            
            renderPage(sourceIdx);
        }}
        
        // 渲染当前页
        function renderPage(sourceIdx) {{
            var tbody = document.getElementById('trades-tbody-' + sourceIdx);
            if (!tbody) return;
            
            var data = filteredData[sourceIdx] || [];
            var totalPages = Math.ceil(data.length / pageSize) || 1;
            var currentPage = currentPages[sourceIdx] || 1;
            
            // 确保当前页在有效范围内
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
            currentPages[sourceIdx] = currentPage;
            
            // 计算显示范围
            var startIdx = (currentPage - 1) * pageSize;
            var endIdx = Math.min(startIdx + pageSize, data.length);
            
            // 清空表格
            tbody.innerHTML = '';
            
            // 显示当前页数据
            for (var i = startIdx; i < endIdx; i++) {{
                var row = data[i].element.cloneNode(true);
                row.cells[0].textContent = i + 1;  // 更新序号
                tbody.appendChild(row);
            }}
            
            // 更新分页信息
            var currentPageSpan = document.querySelector('.current-page-' + sourceIdx);
            var totalPagesSpan = document.querySelector('.total-pages-' + sourceIdx);
            var tradesCountSpan = document.querySelector('.trades-count-' + sourceIdx);
            
            if (currentPageSpan) currentPageSpan.textContent = currentPage;
            if (totalPagesSpan) totalPagesSpan.textContent = totalPages;
            if (tradesCountSpan) tradesCountSpan.textContent = data.length;
            
            // 更新分页按钮状态
            updatePaginationButtons(sourceIdx, currentPage, totalPages);
        }}
        
        // 更新分页按钮状态
        function updatePaginationButtons(sourceIdx, currentPage, totalPages) {{
            var pagination = document.getElementById('pagination-' + sourceIdx);
            if (!pagination) return;
            
            var buttons = pagination.querySelectorAll('button');
            buttons[0].disabled = currentPage === 1;  // 首页
            buttons[1].disabled = currentPage === 1;  // 上一页
            buttons[2].disabled = currentPage === totalPages;  // 下一页
            buttons[3].disabled = currentPage === totalPages;  // 末页
        }}
        
        // 获取总页数
        function getTotalPages(sourceIdx) {{
            var data = filteredData[sourceIdx] || [];
            return Math.ceil(data.length / pageSize) || 1;
        }}
        
        // 跳转到指定页
        function goToPage(sourceIdx, page) {{
            var totalPages = getTotalPages(sourceIdx);
            if (page < 1) page = 1;
            if (page > totalPages) page = totalPages;
            currentPages[sourceIdx] = page;
            renderPage(sourceIdx);
        }}
        
        // 上一页
        function prevPage(sourceIdx) {{
            goToPage(sourceIdx, (currentPages[sourceIdx] || 1) - 1);
        }}
        
        // 下一页
        function nextPage(sourceIdx) {{
            goToPage(sourceIdx, (currentPages[sourceIdx] || 1) + 1);
        }}
        
        // 跳转到输入的页码
        function jumpToPage(sourceIdx) {{
            var input = document.querySelector('.page-input-' + sourceIdx);
            if (input && input.value) {{
                goToPage(sourceIdx, parseInt(input.value));
                input.value = '';
            }}
        }}
        
        // 应用筛选
        function applyTradesFilter(sourceIdx) {{
            var timeFilter = document.querySelector('.filter-time-' + sourceIdx);
            var priceFilter = document.querySelector('.filter-price-' + sourceIdx);
            var actionFilter = document.querySelector('.filter-action-' + sourceIdx);
            var profitFilter = document.querySelector('.filter-profit-' + sourceIdx);
            
            var timeValue = timeFilter ? timeFilter.value.trim().toLowerCase() : '';
            var priceValue = priceFilter ? priceFilter.value.trim() : '';
            var actionValue = actionFilter ? actionFilter.value : '';
            var profitValue = profitFilter ? profitFilter.value : '';
            
            var originalData = tradesData[sourceIdx] || [];
            
            filteredData[sourceIdx] = originalData.filter(function(item) {{
                // 时间筛选
                if (timeValue && item.time.toLowerCase().indexOf(timeValue) === -1) {{
                    return false;
                }}
                // 价格筛选
                if (priceValue && item.price.indexOf(priceValue) === -1) {{
                    return false;
                }}
                // 操作筛选
                if (actionValue && item.action.indexOf(actionValue) === -1) {{
                    return false;
                }}
                // 盈亏筛选
                if (profitValue) {{
                    var profitText = item.profit.replace(/[,\s]/g, '');
                    var profitNum = parseFloat(profitText);
                    if (profitValue === 'profit' && (isNaN(profitNum) || profitNum <= 0)) {{
                        return false;
                    }}
                    if (profitValue === 'loss' && (isNaN(profitNum) || profitNum >= 0)) {{
                        return false;
                    }}
                }}
                return true;
            }});
            
            currentPages[sourceIdx] = 1;
            renderPage(sourceIdx);
        }}
        
        // 重置筛选
        function resetTradesFilter(sourceIdx) {{
            var timeFilter = document.querySelector('.filter-time-' + sourceIdx);
            var priceFilter = document.querySelector('.filter-price-' + sourceIdx);
            var actionFilter = document.querySelector('.filter-action-' + sourceIdx);
            var profitFilter = document.querySelector('.filter-profit-' + sourceIdx);
            
            if (timeFilter) timeFilter.value = '';
            if (priceFilter) priceFilter.value = '';
            if (actionFilter) actionFilter.value = '';
            if (profitFilter) profitFilter.value = '';
            
            filteredData[sourceIdx] = tradesData[sourceIdx].slice();
            currentPages[sourceIdx] = 1;
            renderPage(sourceIdx);
        }}
        
        // 页面加载后初始化所有交易表格
        document.addEventListener('DOMContentLoaded', function() {{
            // 查找所有交易表格并初始化
            var tables = document.querySelectorAll('[id^="trades-table-"]');
            tables.forEach(function(table) {{
                var idx = parseInt(table.id.replace('trades-table-', ''));
                if (!isNaN(idx)) {{
                    initTradesTable(idx);
                }}
            }});
        }});
    </script>
</body>
</html>'''

    def __init__(self, logger=None):
        """初始化报告生成器
        
        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
    
    def log(self, message: str):
        """记录日志"""
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)
    
    def _load_plotly_js(self) -> str:
        """从本地加载 plotly.min.js，如果本地文件不存在则使用 CDN 备用
        
        Returns:
            完整的 script 标签（内联 JS 或 CDN 引用）
        """
        # CDN 备用地址
        CDN_URL = "https://cdn.bootcdn.net/ajax/libs/plotly.js/2.27.0/plotly.min.js"
        
        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 构建 plotly.min.js 的路径 (相对于 ssquant/backtest/ -> ssquant/assets/)
        plotly_path = os.path.join(current_dir, '..', 'assets', 'plotly.min.js')
        plotly_path = os.path.normpath(plotly_path)
        
        try:
            with open(plotly_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.log(f"已从本地加载 plotly.min.js: {plotly_path}")
            # 返回内联 script 标签
            return f'<script>{content}</script>'
        except FileNotFoundError:
            self.log(f"本地 plotly.min.js 未找到，使用 CDN 备用: {CDN_URL}")
            # 返回 CDN 引用的 script 标签
            return f'<script src="{CDN_URL}"></script>'
        except Exception as e:
            self.log(f"加载本地 plotly.min.js 失败 ({e})，使用 CDN 备用")
            # 返回 CDN 引用的 script 标签
            return f'<script src="{CDN_URL}"></script>'
    
    def generate_report(self, results: Dict, multi_data_source=None, output_dir: str = "backtest_results") -> str:
        """生成 HTML 回测报告
        
        Args:
            results: 回测结果字典
            multi_data_source: 多数据源实例
            output_dir: 输出目录
            
        Returns:
            报告文件路径
        """
        # 检查是否禁用报告生成
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("报告生成已被禁用 (NO_VISUALIZATION=True)")
            return None
            
        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            return None
        
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 过滤结果，只保留有效的数据源结果
        filtered_results = {k: v for k, v in results.items() 
                          if k != 'performance' and isinstance(v, dict) and 'trades' in v}
        
        if not filtered_results:
            self.log("没有可用的回测结果")
            return None
        
        self.log(f"找到 {len(filtered_results)} 个数据源的结果")
        
        # 提取所有数据源信息
        source_infos = []
        for key, result in filtered_results.items():
            source_infos.append({
                'key': key,
                'symbol': result.get('symbol', 'unknown'),
                'kline_period': result.get('kline_period', ''),
                'result': result
            })
        
        # 策略信息
        strategy_info = ' | '.join([f"{s['symbol']} {s['kline_period']}" for s in source_infos])
        
        # 计算综合指标
        combined_metrics = self._calculate_combined_metrics(filtered_results)
        
        # 获取各数据源的利润曲线（从0开始，便于对比）
        profit_data_sources = self._get_profit_data_sources(filtered_results)
        
        # 计算综合利润曲线（净利润：扣除成本）
        combined_profit_data = self._get_combined_profit_data(filtered_results)
        
        # 计算综合交易盈亏曲线（未扣手续费）
        combined_gross_profit_data = self._get_combined_gross_profit_data(filtered_results)
        
        # 获取价格曲线数据（用于右侧Y轴显示）
        price_data_sources = self._get_price_data_sources(filtered_results)
        
        # 计算各数据源的回撤（基于权益曲线计算，更准确）
        drawdown_data_sources = self._get_drawdown_from_results(filtered_results)
        
        # 计算综合回撤（基于综合权益）
        combined_drawdown_data = self._get_combined_drawdown(filtered_results)
        
        # 提取 K线数据和交易标记
        kline_data_sources = self._get_kline_data_sources(filtered_results)
        
        # 生成各部分 HTML
        combined_metrics_cards = self._generate_metrics_cards(combined_metrics)
        source_comparison_section = self._generate_source_comparison(filtered_results)
        source_tabs = self._generate_source_tabs(source_infos)
        source_details = self._generate_source_details(source_infos)
        
        # 获取日期范围
        if combined_profit_data['dates']:
            start_date = combined_profit_data['dates'][0]
            end_date = combined_profit_data['dates'][-1]
        else:
            start_date = '-'
            end_date = '-'
        
        # 加载 plotly.js（本地优先，CDN 备用）
        plotly_script_tag = self._load_plotly_js()
        
        # 填充模板
        html = self.HTML_TEMPLATE.format(
            strategy_name=strategy_info,
            strategy_info=strategy_info,
            start_date=start_date,
            end_date=end_date,
            report_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            combined_metrics_cards=combined_metrics_cards,
            source_comparison_section=source_comparison_section,
            source_tabs=source_tabs,
            source_details=source_details,
            profit_data_sources=json.dumps(profit_data_sources, cls=NumpyEncoder),
            combined_profit_data=json.dumps(combined_profit_data, cls=NumpyEncoder),
            combined_gross_profit_data=json.dumps(combined_gross_profit_data, cls=NumpyEncoder),
            price_data_sources=json.dumps(price_data_sources, cls=NumpyEncoder),
            drawdown_data_sources=json.dumps(drawdown_data_sources, cls=NumpyEncoder),
            combined_drawdown_data=json.dumps(combined_drawdown_data, cls=NumpyEncoder),
            kline_data_sources=json.dumps(kline_data_sources, cls=NumpyEncoder),
            plotly_script_tag=plotly_script_tag
        )
        
        # 保存文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        first_symbol = source_infos[0]['symbol']
        output_path = os.path.join(output_dir, f"{first_symbol}_report_{timestamp}.html")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self.log(f"HTML 报告已保存到: {output_path}")
        return output_path
    
    def _calculate_combined_metrics(self, results: Dict) -> Dict:
        """计算综合绩效指标"""
        metrics = {
            'initial_capital': 0,
            'final_equity': 0,
            'total_net_profit': 0,
            'total_trades': 0,
            'win_trades': 0,
            'loss_trades': 0,
            'win_rate': 0,
            'max_drawdown_pct': 0,
            'annual_return': 0,
            'sharpe_ratio': 0,
            'profit_factor': 0,
            'total_commission': 0,
            'total_slippage': 0,
            'total_amount_profit': 0,
        }
        
        all_sharpe = []
        all_annual_return = []
        
        for key, result in results.items():
            capital = result.get('initial_capital', 100000)
            metrics['initial_capital'] += capital
            metrics['final_equity'] += result.get('final_equity', capital)
            metrics['total_net_profit'] += result.get('total_net_profit', 0)
            metrics['total_trades'] += result.get('total_trades', 0)
            metrics['win_trades'] += result.get('win_trades', 0)
            metrics['loss_trades'] += result.get('loss_trades', 0)
            metrics['total_commission'] += result.get('total_commission', 0)
            metrics['total_slippage'] += result.get('total_slippage', 0)
            metrics['total_amount_profit'] += result.get('total_amount_profit', 0)
            metrics['max_drawdown_pct'] = max(metrics['max_drawdown_pct'], result.get('max_drawdown_pct', 0))
            
            if result.get('sharpe_ratio'):
                all_sharpe.append((result.get('sharpe_ratio', 0), capital))
            if result.get('annual_return'):
                all_annual_return.append((result.get('annual_return', 0), capital))
        
        # 计算胜率
        if metrics['total_trades'] > 0:
            metrics['win_rate'] = metrics['win_trades'] / metrics['total_trades'] * 100
        
        # 计算收益率
        if metrics['initial_capital'] > 0:
            metrics['total_return'] = (metrics['final_equity'] - metrics['initial_capital']) / metrics['initial_capital'] * 100
        else:
            metrics['total_return'] = 0
        
        # 加权平均夏普比率和年化收益率
        if all_sharpe:
            total_weight = sum(w for _, w in all_sharpe)
            metrics['sharpe_ratio'] = sum(v * w for v, w in all_sharpe) / total_weight if total_weight > 0 else 0
        
        if all_annual_return:
            total_weight = sum(w for _, w in all_annual_return)
            metrics['annual_return'] = sum(v * w for v, w in all_annual_return) / total_weight if total_weight > 0 else 0
        
        # 盈亏比
        first_result = list(results.values())[0]
        metrics['profit_factor'] = first_result.get('profit_factor', 0)
        
        return metrics
    
    def _get_profit_data_sources(self, results: Dict) -> List[Dict]:
        """获取各数据源的利润曲线数据（从0开始，便于对比）"""
        profit_sources = []
        
        for key, result in results.items():
            if 'equity_curve' not in result:
                continue
                
            equity_curve = result['equity_curve']
            if not isinstance(equity_curve, pd.Series) or equity_curve.empty:
                continue
            
            # 获取初始资金
            initial_capital = result.get('initial_capital', 100000)
            
            # 计算利润曲线（权益 - 初始资金）
            profit_curve = equity_curve - initial_capital
            
            # 转换为列表（保留原始数据）
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in profit_curve.index]
            values = profit_curve.values.tolist()
            
            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"
            
            profit_sources.append({
                'name': name,
                'dates': dates,
                'values': values,
                'initial_capital': initial_capital
            })
        
        return profit_sources
    
    def _get_price_data_sources(self, results: Dict) -> List[Dict]:
        """获取各数据源的价格曲线数据（归一化为相对值，起点=100）"""
        price_sources = []
        num_sources = len(results)
        
        for key, result in results.items():
            if 'data' not in result:
                continue
                
            data = result['data']
            if not isinstance(data, pd.DataFrame) or data.empty:
                continue
            
            # 获取收盘价列
            if 'close' in data.columns:
                close_prices = data['close']
            elif 'LastPrice' in data.columns:
                close_prices = data['LastPrice']
            else:
                continue
            
            # 转换为列表
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in close_prices.index]
            
            # 多数据源时使用归一化（相对值，起点=100）
            if num_sources > 1:
                first_price = close_prices.iloc[0] if close_prices.iloc[0] != 0 else 1
                normalized_prices = (close_prices / first_price * 100).values.tolist()
                values = normalized_prices
                is_normalized = True
            else:
                # 单数据源直接使用原始价格
                values = close_prices.values.tolist()
                is_normalized = False
            
            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"
            
            price_sources.append({
                'name': f"{name} 价格" if not is_normalized else f"{name} 相对值",
                'dates': dates,
                'values': values,
                'is_normalized': is_normalized
            })
        
        return price_sources
    
    def _get_combined_profit_data(self, results: Dict) -> Dict:
        """获取综合利润曲线数据（所有数据源的利润相加）
        
        对于多周期数据，使用交集（intersection）只保留共同时间点，
        避免 ffill 导致的水平线延伸问题。
        """
        all_profit_curves = []
        
        for key, result in results.items():
            if 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                initial_capital = result.get('initial_capital', 100000)
                profit_curve = result['equity_curve'] - initial_capital
                all_profit_curves.append(profit_curve)
        
        if not all_profit_curves:
            return {'dates': [], 'values': []}
        
        # 合并利润曲线
        if len(all_profit_curves) == 1:
            combined = all_profit_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_profit_curves[0].index
            for curve in all_profit_curves[1:]:
                common_indices = common_indices.intersection(curve.index)
            
            # 如果没有共同时间点，使用最短周期的数据
            if len(common_indices) == 0:
                # 找到数据点最多的曲线作为基准
                base_curve = max(all_profit_curves, key=len)
                combined = base_curve.copy()
                for curve in all_profit_curves:
                    if curve is not base_curve:
                        # 只在有数据的时间点相加
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(0)
            else:
                # 在共同时间点上相加
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_profit_curves:
                    combined = combined + curve.reindex(common_indices)
        
        # 不做降采样，保留原始数据
        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in combined.index]
        values = combined.values.tolist()
        
        return {'dates': dates, 'values': values}
    
    def _get_combined_gross_profit_data(self, results: Dict) -> Dict:
        """获取综合交易盈亏曲线数据（未扣手续费）"""
        all_gross_curves = []
        
        for key, result in results.items():
            if 'gross_equity_curve' in result and isinstance(result['gross_equity_curve'], pd.Series):
                initial_capital = result.get('initial_capital', 100000)
                gross_profit_curve = result['gross_equity_curve'] - initial_capital
                all_gross_curves.append(gross_profit_curve)
        
        if not all_gross_curves:
            return {'dates': [], 'values': []}
        
        # 合并交易盈亏曲线
        if len(all_gross_curves) == 1:
            combined = all_gross_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_gross_curves[0].index
            for curve in all_gross_curves[1:]:
                common_indices = common_indices.intersection(curve.index)
            
            if len(common_indices) == 0:
                base_curve = max(all_gross_curves, key=len)
                combined = base_curve.copy()
                for curve in all_gross_curves:
                    if curve is not base_curve:
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(0)
            else:
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_gross_curves:
                    combined = combined + curve.reindex(common_indices)
        
        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in combined.index]
        values = combined.values.tolist()
        
        return {'dates': dates, 'values': values}
    
    def _get_drawdown_from_results(self, results: Dict) -> List[Dict]:
        """从回测结果计算各数据源的回撤数据（基于权益曲线）"""
        drawdown_sources = []
        
        for key, result in results.items():
            if 'equity_curve' not in result:
                continue
                
            equity_curve = result['equity_curve']
            if not isinstance(equity_curve, pd.Series) or equity_curve.empty:
                continue
            
            # 计算回撤百分比
            cummax = equity_curve.cummax()
            drawdown_pct = (cummax - equity_curve) / cummax * 100
            drawdown_pct = drawdown_pct.fillna(0)
            
            # 转换为列表（保留原始数据）
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in drawdown_pct.index]
            values = drawdown_pct.values.tolist()
            
            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"
            
            drawdown_sources.append({
                'name': name,
                'dates': dates,
                'values': values
            })
        
        return drawdown_sources
    
    def _get_combined_drawdown(self, results: Dict) -> Dict:
        """计算综合回撤（基于综合权益曲线）
        
        对于多周期数据，使用交集（intersection）只保留共同时间点。
        """
        all_equity_curves = []
        
        for key, result in results.items():
            if 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                all_equity_curves.append(result['equity_curve'])
        
        if not all_equity_curves:
            return {'dates': [], 'values': []}
        
        # 合并权益曲线
        if len(all_equity_curves) == 1:
            combined = all_equity_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_equity_curves[0].index
            for curve in all_equity_curves[1:]:
                common_indices = common_indices.intersection(curve.index)
            
            # 如果没有共同时间点，使用最长周期的数据
            if len(common_indices) == 0:
                base_curve = max(all_equity_curves, key=len)
                combined = base_curve.copy()
                for curve in all_equity_curves:
                    if curve is not base_curve:
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(method='ffill').fillna(method='bfill')
            else:
                # 在共同时间点上相加
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_equity_curves:
                    combined = combined + curve.reindex(common_indices)
        
        # 计算回撤
        cummax = combined.cummax()
        drawdown_pct = (cummax - combined) / cummax * 100
        drawdown_pct = drawdown_pct.fillna(0)
        
        # 不做降采样，保留原始数据
        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in drawdown_pct.index]
        values = drawdown_pct.values.tolist()
        
        return {'dates': dates, 'values': values}
    
    def _get_kline_data_sources(self, results: Dict) -> List[Dict]:
        """提取各数据源的 K线/TICK 数据和交易标记（向量化处理）"""
        kline_sources = []
        
        for key, result in results.items():
            # 获取数据
            data = result.get('data')
            if data is None or not isinstance(data, pd.DataFrame) or data.empty:
                continue
            
            df = data.copy()
            kline_period = result.get('kline_period', '')
            is_tick = kline_period.lower() == 'tick' or 'LastPrice' in df.columns
            
            # 提取日期（索引或列）- TICK数据保留毫秒
            if isinstance(df.index, pd.DatetimeIndex):
                if is_tick:
                    # TICK数据保留毫秒精度（格式：2026-01-06 10:34:00.500）
                    dates = [d.strftime('%Y-%m-%d %H:%M:%S.') + f'{d.microsecond // 1000:03d}' 
                             for d in df.index]
                else:
                    dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
            elif 'datetime' in df.columns:
                dt_series = pd.to_datetime(df['datetime'])
                if is_tick:
                    dates = [d.strftime('%Y-%m-%d %H:%M:%S.') + f'{d.microsecond // 1000:03d}' 
                             for d in dt_series]
                else:
                    dates = dt_series.dt.strftime('%Y-%m-%d %H:%M').tolist()
            else:
                dates = [str(i) for i in range(len(df))]
            
            if is_tick:
                # TICK 数据：使用 LastPrice 作为价格线
                if 'LastPrice' in df.columns:
                    prices = df['LastPrice'].tolist()
                elif 'close' in df.columns:
                    prices = df['close'].tolist()
                else:
                    continue
                
                ohlc = {
                    'dates': dates,
                    'prices': prices,  # TICK 用单一价格线
                    'is_tick': True
                }
            else:
                # K线数据：需要 OHLC
                required_cols = ['open', 'high', 'low', 'close']
                if not all(col in df.columns for col in required_cols):
                    continue
                
                ohlc = {
                    'dates': dates,
                    'open': df['open'].tolist(),
                    'high': df['high'].tolist(),
                    'low': df['low'].tolist(),
                    'close': df['close'].tolist(),
                    'is_tick': False
                }
            
            # 提取交易标记
            trades = result.get('trades', [])
            buy_markers = {'x': [], 'y': [], 'text': []}
            sell_markers = {'x': [], 'y': [], 'text': []}
            flip_short_markers = {'x': [], 'y': [], 'text': []}   # 平多开空（含单笔或 平多+开空 两腿）
            flip_long_markers = {'x': [], 'y': [], 'text': []}   # 平空开多

            def _fmt_trade_x(dt_raw):
                """与 K 线/TICK 横轴类别字符串一致，便于 Plotly 对齐。"""
                if is_tick:
                    try:
                        if hasattr(dt_raw, 'strftime'):
                            dt = dt_raw
                        else:
                            dt = pd.to_datetime(dt_raw)
                        return dt.strftime('%Y-%m-%d %H:%M:%S.') + f'{dt.microsecond // 1000:03d}'
                    except Exception:
                        return str(dt_raw)[:23]
                return str(dt_raw)[:16]

            # reverse_pos(next_bar_*) 会拆成「平多+开空」「平空+开多」两条记录，此处合并为反手标记
            n_tr = len(trades)
            paired_leg_indices = set()
            if n_tr > 0:
                order_by_time = sorted(
                    range(n_tr),
                    key=lambda i: (pd.to_datetime(trades[i].get('datetime'), errors='coerce'), i),
                )
                k = 0
                while k < len(order_by_time) - 1:
                    ia = order_by_time[k]
                    ib = order_by_time[k + 1]
                    ta, tb = trades[ia], trades[ib]
                    a1 = str(ta.get('action', '') or '').strip()
                    a2 = str(tb.get('action', '') or '').strip()
                    x1 = _fmt_trade_x(ta.get('datetime'))
                    x2 = _fmt_trade_x(tb.get('datetime'))
                    if x1 != x2:
                        k += 1
                        continue
                    p1 = float(ta.get('price', 0) or 0)
                    p2 = float(tb.get('price', 0) or 0)
                    px = (p1 + p2) / 2 if p1 and p2 else (p1 or p2)
                    vol = int(ta.get('volume', 0) or 0) or int(tb.get('volume', 0) or 0) or 1
                    if a1 == '平多' and a2 == '开空':
                        paired_leg_indices.add(ia)
                        paired_leg_indices.add(ib)
                        flip_short_markers['x'].append(x1)
                        flip_short_markers['y'].append(px)
                        flip_short_markers['text'].append(f"平多开空 {vol}手 @ {px:.2f}")
                        k += 2
                        continue
                    if a1 == '平空' and a2 == '开多':
                        paired_leg_indices.add(ia)
                        paired_leg_indices.add(ib)
                        flip_long_markers['x'].append(x1)
                        flip_long_markers['y'].append(px)
                        flip_long_markers['text'].append(f"平空开多 {vol}手 @ {px:.2f}")
                        k += 2
                        continue
                    k += 1

            for i, trade in enumerate(trades):
                if i in paired_leg_indices:
                    continue
                trade_time = trade.get('datetime', '')
                price = trade.get('price', 0)
                action = str(trade.get('action', '') or '').strip()
                volume = trade.get('volume', 1)
                trade_time = _fmt_trade_x(trade_time)

                if action == '平多开空':
                    flip_short_markers['x'].append(trade_time)
                    flip_short_markers['y'].append(float(price or 0))
                    flip_short_markers['text'].append(f"{action} {volume}手 @ {float(price):.2f}")
                elif action == '平空开多':
                    flip_long_markers['x'].append(trade_time)
                    flip_long_markers['y'].append(float(price or 0))
                    flip_long_markers['text'].append(f"{action} {volume}手 @ {float(price):.2f}")
                elif action in ['开多', '平空']:
                    buy_markers['x'].append(trade_time)
                    buy_markers['y'].append(price)
                    buy_markers['text'].append(f"{action} {volume}手 @ {price:.2f}")
                elif action in ['开空', '平多']:
                    sell_markers['x'].append(trade_time)
                    sell_markers['y'].append(price)
                    sell_markers['text'].append(f"{action} {volume}手 @ {price:.2f}")
            
            name = f"{result.get('symbol', '')} {kline_period}"
            
            kline_sources.append({
                'name': name,
                'key': key,
                'ohlc': ohlc,
                'buy_markers': buy_markers,
                'sell_markers': sell_markers,
                'flip_short_markers': flip_short_markers,
                'flip_long_markers': flip_long_markers,
            })
        
        return kline_sources
    
    def _generate_source_comparison(self, results: Dict) -> str:
        """生成数据源对比表格"""
        if len(results) <= 1:
            return ''
        
        rows = []
        headers = ['数据源', '初始资金', '期末权益', '总收益率', '手续费', '滑点', '交易次数', '胜率', '最大回撤', '夏普比率']
        
        # 用于计算综合绩效的累加变量
        total_initial = 0
        total_final = 0
        total_trades = 0
        total_win_trades = 0
        total_commission_all = 0
        total_slippage_all = 0
        max_drawdown_all = 0
        all_sharpe = []
        
        for key, result in results.items():
            symbol = result.get('symbol', '')
            period = result.get('kline_period', '')
            name = f"{symbol} {period}"
            
            initial = result.get('initial_capital', 100000)
            final = result.get('final_equity', initial)
            total_return = (final - initial) / initial * 100 if initial > 0 else 0
            trades = result.get('total_trades', 0)
            win_trades = result.get('win_trades', 0)
            win_rate = result.get('win_rate', 0) * 100 if result.get('win_rate', 0) <= 1 else result.get('win_rate', 0)
            max_dd = result.get('max_drawdown_pct', 0)
            sharpe = result.get('sharpe_ratio', 0)
            commission = result.get('total_commission', 0)
            slippage = result.get('total_slippage', 0)
            
            # 累加综合数据
            total_initial += initial
            total_final += final
            total_trades += trades
            total_win_trades += win_trades
            total_commission_all += commission
            total_slippage_all += slippage
            max_drawdown_all = max(max_drawdown_all, max_dd)
            if sharpe:
                all_sharpe.append((sharpe, initial))
            
            return_class = 'profit' if total_return > 0 else 'loss' if total_return < 0 else ''
            
            row = f'''
            <tr>
                <td>{name}</td>
                <td>{initial:,.0f}</td>
                <td>{final:,.0f}</td>
                <td class="{return_class}">{total_return:+.2f}%</td>
                <td>{commission:,.2f}</td>
                <td>{slippage:,.2f}</td>
                <td>{trades}</td>
                <td>{win_rate:.1f}%</td>
                <td class="loss">-{max_dd:.2f}%</td>
                <td>{sharpe:.2f}</td>
            </tr>'''
            rows.append(row)
        
        # 计算综合绩效
        combined_return = (total_final - total_initial) / total_initial * 100 if total_initial > 0 else 0
        combined_win_rate = total_win_trades / total_trades * 100 if total_trades > 0 else 0
        combined_sharpe = sum(v * w for v, w in all_sharpe) / sum(w for _, w in all_sharpe) if all_sharpe else 0
        combined_return_class = 'profit' if combined_return > 0 else 'loss' if combined_return < 0 else ''
        
        # 添加综合绩效行
        combined_row = f'''
            <tr style="background: rgba(100, 181, 246, 0.15); font-weight: 600;">
                <td>📊 综合绩效</td>
                <td>{total_initial:,.0f}</td>
                <td>{total_final:,.0f}</td>
                <td class="{combined_return_class}">{combined_return:+.2f}%</td>
                <td>{total_commission_all:,.2f}</td>
                <td>{total_slippage_all:,.2f}</td>
                <td>{total_trades}</td>
                <td>{combined_win_rate:.1f}%</td>
                <td class="loss">-{max_drawdown_all:.2f}%</td>
                <td>{combined_sharpe:.2f}</td>
            </tr>'''
        rows.append(combined_row)
        
        header_html = ''.join([f'<th>{h}</th>' for h in headers])
        
        return f'''
        <div class="summary-section">
            <div class="summary-title">
                <span>📋</span> 数据源绩效对比
            </div>
            <table class="comparison-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>'''
    
    def _generate_source_tabs(self, source_infos: List[Dict]) -> str:
        """生成数据源标签页"""
        if len(source_infos) <= 1:
            return ''
        
        tabs = []
        for i, info in enumerate(source_infos):
            active = 'active' if i == 0 else ''
            name = f"{info['symbol']} {info['kline_period']}"
            tabs.append(f'<div class="tab {active}" onclick="switchTab(\'{info["key"]}\')">{name}</div>')
        
        return f'''
        <div class="summary-section">
            <div class="summary-title">
                <span>📂</span> 各数据源详情
            </div>
            <div class="tabs">
                {''.join(tabs)}
            </div>
        </div>'''
    
    def _generate_source_details(self, source_infos: List[Dict]) -> str:
        """生成各数据源的详细内容"""
        details = []
        
        for i, info in enumerate(source_infos):
            active = 'active' if i == 0 else ''
            result = info['result']
            
            # 生成该数据源的指标卡片
            source_metrics = self._extract_source_metrics(result)
            metrics_cards = self._generate_metrics_cards(source_metrics)
            
            # 生成该数据源的交易记录
            trades = result.get('trades', [])
            trades_rows = self._generate_trades_rows(trades, info['symbol'])
            
            detail_html = f'''
            <div id="content-{info['key']}" class="tab-content {active}">
                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📊</span>
                        {info['symbol']} {info['kline_period']} 绩效指标
                    </div>
                    <div class="metrics-grid">
                        {metrics_cards}
                    </div>
                </div>
                
                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📋</span>
                        交易记录 (<span class="trades-count-{i}">{len(trades)}</span>笔)
                    </div>
                    
                    <!-- 筛选器 -->
                    <div class="trades-filter">
                        <div class="filter-group">
                            <label>时间:</label>
                            <input type="text" class="filter-time-{i}" placeholder="如: 2025-01-02">
                        </div>
                        <div class="filter-group">
                            <label>价格:</label>
                            <input type="text" class="filter-price-{i}" placeholder="如: 3300">
                        </div>
                        <div class="filter-group">
                            <label>操作:</label>
                            <select class="filter-action-{i}">
                                <option value="">全部</option>
                                <option value="开多">开多</option>
                                <option value="平多">平多</option>
                                <option value="开空">开空</option>
                                <option value="平空">平空</option>
                                <option value="平多开空">平多开空</option>
                                <option value="平空开多">平空开多</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>盈亏:</label>
                            <select class="filter-profit-{i}">
                                <option value="">全部</option>
                                <option value="profit">盈利</option>
                                <option value="loss">亏损</option>
                            </select>
                        </div>
                        <button class="filter-btn" onclick="applyTradesFilter({i})">筛选</button>
                        <button class="filter-btn reset" onclick="resetTradesFilter({i})">重置</button>
                    </div>
                    
                    <div class="table-wrapper">
                        <table class="trades-table" id="trades-table-{i}">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>时间</th>
                                    <th>操作</th>
                                    <th>价格</th>
                                    <th>数量</th>
                                    <th>盈亏</th>
                                    <th>手续费</th>
                                    <th>净盈亏</th>
                                </tr>
                            </thead>
                            <tbody id="trades-tbody-{i}">
                                {trades_rows}
                            </tbody>
                        </table>
                    </div>
                    
                    <!-- 分页器 -->
                    <div class="pagination" id="pagination-{i}">
                        <button onclick="goToPage({i}, 1)">首页</button>
                        <button onclick="prevPage({i})">上一页</button>
                        <span class="page-info">第 <span class="current-page-{i}">1</span> / <span class="total-pages-{i}">1</span> 页</span>
                        <button onclick="nextPage({i})">下一页</button>
                        <button onclick="goToPage({i}, getTotalPages({i}))">末页</button>
                        <div class="page-jump">
                            <input type="number" class="page-input-{i}" min="1" placeholder="页码">
                            <button onclick="jumpToPage({i})">跳转</button>
                        </div>
                    </div>
                </div>
            </div>'''
            details.append(detail_html)
        
        return '\n'.join(details)
    
    def _extract_source_metrics(self, result: Dict) -> Dict:
        """提取单个数据源的指标"""
        initial = result.get('initial_capital', 100000)
        final = result.get('final_equity', initial)
        total_return = (final - initial) / initial * 100 if initial > 0 else 0
        
        return {
            'initial_capital': initial,
            'final_equity': final,
            'total_return': total_return,
            'total_net_profit': result.get('total_net_profit', 0),
            'total_trades': result.get('total_trades', 0),
            'win_rate': result.get('win_rate', 0) * 100 if result.get('win_rate', 0) <= 1 else result.get('win_rate', 0),
            'max_drawdown_pct': result.get('max_drawdown_pct', 0),
            'annual_return': result.get('annual_return', 0),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'profit_factor': result.get('profit_factor', 0),
            'total_commission': result.get('total_commission', 0),
            'total_slippage': result.get('total_slippage', 0),
            'total_amount_profit': result.get('total_amount_profit', 0),
        }
    
    def _generate_metrics_cards(self, metrics: Dict) -> str:
        """生成指标卡片 HTML"""
        cards = []
        
        metric_configs = [
            ('initial_capital', '初始资金', ',.0f', 'neutral'),
            ('final_equity', '期末权益', ',.0f', None),
            ('total_return', '总收益率', '+.2f', None, '%'),
            ('total_amount_profit', '交易盈亏(未扣手续费)', ',.2f', None),
            ('total_commission', '总手续费', ',.2f', 'neutral'),
            ('total_slippage', '总滑点成本', ',.2f', 'neutral'),
            ('total_net_profit', '净利润(扣除手续费)', ',.2f', None),
            ('total_trades', '总交易次数', 'd', 'neutral'),
            ('win_rate', '胜率', '.2f', None, '%'),
            ('max_drawdown_pct', '最大回撤', '.2f', 'negative', '%'),
            ('annual_return', '年化收益率', '+.2f', None, '%'),
            ('sharpe_ratio', '夏普比率', '.2f', None),
            ('profit_factor', '盈亏比', '.2f', None),
        ]
        
        for config in metric_configs:
            key = config[0]
            label = config[1]
            fmt = config[2]
            force_class = config[3] if len(config) > 3 else None
            suffix = config[4] if len(config) > 4 else ''
            
            value = metrics.get(key, 0)
            
            try:
                if 'd' in fmt:
                    formatted_value = f"{int(value):,}"
                else:
                    formatted_value = f"{value:{fmt}}"
            except:
                formatted_value = str(value)
            
            formatted_value += suffix
            
            if force_class:
                value_class = force_class
            elif key in ['total_return', 'annual_return', 'total_net_profit', 'total_amount_profit']:
                value_class = 'positive' if value > 0 else 'negative' if value < 0 else 'neutral'
            elif key == 'win_rate':
                value_class = 'positive' if value >= 50 else 'negative'
            elif key == 'sharpe_ratio':
                value_class = 'positive' if value > 1 else 'neutral' if value > 0 else 'negative'
            elif key == 'profit_factor':
                value_class = 'positive' if value > 1 else 'negative'
            else:
                value_class = 'neutral'
            
            card_html = f'''
            <div class="metric-card">
                <div class="label">{label}</div>
                <div class="value {value_class}">{formatted_value}</div>
            </div>'''
            cards.append(card_html)
        
        return '\n'.join(cards)
    
    def _generate_trades_rows(self, trades: List[Dict], symbol: str = '') -> str:
        """生成交易记录表格行"""
        rows = []
        
        for i, trade in enumerate(trades, 1):
            datetime_str = str(trade.get('datetime', ''))
            action = trade.get('action', '')
            price = trade.get('price', 0)
            volume = trade.get('volume', 1)
            
            amount_profit = trade.get('amount_profit', 0)
            commission = trade.get('commission', 0)
            net_profit = trade.get('net_profit', 0)
            
            if action in ['开多', '平空', '平空开多']:
                tag_class = 'buy'
            else:
                tag_class = 'sell'
            
            if action in ['平多', '平空', '平多开空', '平空开多']:
                profit_class = 'profit' if net_profit > 0 else 'loss'
                profit_str = f"{amount_profit:+,.2f}"
                net_profit_str = f"{net_profit:+,.2f}"
            else:
                profit_class = ''
                profit_str = '-'
                net_profit_str = '-'
            
            row_html = f'''
            <tr>
                <td>{i}</td>
                <td>{datetime_str}</td>
                <td><span class="tag {tag_class}">{action}</span></td>
                <td>{price:,.2f}</td>
                <td>{volume}</td>
                <td class="{profit_class}">{profit_str}</td>
                <td>{commission:,.2f}</td>
                <td class="{profit_class}">{net_profit_str}</td>
            </tr>'''
            rows.append(row_html)
        
        return '\n'.join(rows)


# 兼容旧接口
def generate_html_report(results: Dict, multi_data_source=None, output_dir: str = "backtest_results") -> str:
    """生成 HTML 报告的便捷函数"""
    generator = HTMLReportGenerator()
    return generator.generate_report(results, multi_data_source, output_dir)
