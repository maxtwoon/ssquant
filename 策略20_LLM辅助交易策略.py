#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略20：LLM辅助多因子交易策略
=====================================
核心思路：
  1. 构建"市场状态描述"prompt，将K线数据、技术指标值、成交量信息结构化为自然语言
  2. 调用LLM（DeepSeek / OpenAI）获取方向判断和信心分数
  3. 用RSI、ATR等技术指标对LLM信号进行二次确认，减少噪音
  4. 采用ATR动态止损 + 固定比例仓位管理

使用说明：
  - 回测模式：LLM_MODE = 'mock'，用技术规则模拟LLM输出（无需API）
  - 实盘模式：LLM_MODE = 'deepseek' 或 'openai'，填写 LLM_API_KEY

参数说明：
  - fast_ma       : 快均线周期（默认20）
  - slow_ma       : 慢均线周期（默认60）
  - rsi_period    : RSI周期（默认14）
  - atr_period    : ATR周期（默认14）
  - atr_stop_mult : ATR止损倍数（默认2.0）
  - llm_conf_thr  : LLM信心阈值，低于此值不开仓（默认0.6）
  - vol_ma_period : 量能均线周期（默认20）
"""

import numpy as np
import pandas as pd
import json
import os

# ========== LLM 配置 ==========
LLM_MODE = 'mock'            # 'mock'(回测用) / 'deepseek' / 'openai'
LLM_API_KEY = ''             # 实盘时填写API Key
LLM_MODEL = 'deepseek-chat'  # deepseek-chat / gpt-4o / gpt-3.5-turbo
LLM_BASE_URL = 'https://api.deepseek.com/v1'  # DeepSeek API地址

# LLM调用间隔（实盘用，避免过于频繁调用）
LLM_CALL_INTERVAL = 5  # 每N根K线调用一次LLM


def _call_llm_api(prompt: str) -> dict:
    """
    调用真实LLM API（实盘模式）
    返回: {'direction': 1/-1/0, 'confidence': 0.0~1.0, 'reason': '...'}
    """
    try:
        import requests
        headers = {
            'Authorization': f'Bearer {LLM_API_KEY}',
            'Content-Type': 'application/json'
        }
        system_prompt = (
            "你是一位专业的量化交易分析师。根据提供的市场数据，"
            "判断接下来的行情方向。只返回JSON格式，不要其他内容。\n"
            "格式：{\"direction\": 1或-1或0, \"confidence\": 0到1的小数, \"reason\": \"简短理由\"}\n"
            "direction: 1=做多, -1=做空, 0=观望"
        )
        payload = {
            'model': LLM_MODEL,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
            'max_tokens': 200
        }
        resp = requests.post(
            f'{LLM_BASE_URL}/chat/completions',
            headers=headers,
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        # 提取JSON部分
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        pass
    return {'direction': 0, 'confidence': 0.0, 'reason': 'API调用失败'}


def _mock_llm_signal(close: pd.Series, volume: pd.Series,
                     fast_ma: float, slow_ma: float,
                     rsi: float, atr: float) -> dict:
    """
    Mock LLM信号（回测专用）
    用技术规则模拟LLM的判断逻辑，模拟LLM综合分析后给出的方向
    """
    score = 0.0
    reasons = []

    # 均线方向
    if fast_ma > slow_ma * 1.001:
        score += 0.35
        reasons.append('均线多头排列')
    elif fast_ma < slow_ma * 0.999:
        score -= 0.35
        reasons.append('均线空头排列')

    # RSI动量
    if rsi < 35:
        score += 0.30
        reasons.append(f'RSI超卖({rsi:.1f})')
    elif rsi > 65:
        score -= 0.30
        reasons.append(f'RSI超买({rsi:.1f})')
    elif 45 < rsi < 55:
        score += 0.0  # 中性
    elif rsi >= 55:
        score += 0.15
    else:
        score -= 0.15

    # 价格相对均线位置
    curr_close = close.iloc[-1]
    if curr_close > fast_ma:
        score += 0.20
        reasons.append('价格在快均线上方')
    else:
        score -= 0.20

    # 量能确认（最近5根vs均值）
    if len(volume) >= 6:
        recent_vol = volume.iloc[-5:].mean()
        avg_vol = volume.iloc[-20:].mean() if len(volume) >= 20 else volume.mean()
        if recent_vol > avg_vol * 1.2:
            score += 0.15
            reasons.append('成交量放大')

    # 转换为direction和confidence
    if score > 0.4:
        direction = 1
        confidence = min(score, 1.0)
    elif score < -0.4:
        direction = -1
        confidence = min(abs(score), 1.0)
    else:
        direction = 0
        confidence = 0.3

    return {
        'direction': direction,
        'confidence': confidence,
        'reason': '；'.join(reasons) if reasons else '信号不明确'
    }


def _build_prompt(klines: pd.DataFrame, fast_ma: float, slow_ma: float,
                  rsi: float, atr: float) -> str:
    """构建发给LLM的市场状态描述prompt"""
    recent = klines.tail(5)
    close_vals = [f"{v:.2f}" for v in recent['close'].values]
    vol_vals = [f"{v:.0f}" for v in recent['volume'].values]
    curr_close = klines['close'].iloc[-1]
    pct_chg = (curr_close / klines['close'].iloc[-2] - 1) * 100 if len(klines) >= 2 else 0

    prompt = (
        f"当前市场数据：\n"
        f"- 最近5根K线收盘价：{', '.join(close_vals)}\n"
        f"- 最近5根K线成交量：{', '.join(vol_vals)}\n"
        f"- 最新涨跌幅：{pct_chg:.2f}%\n"
        f"- 快均线(MA{20})：{fast_ma:.2f}，慢均线(MA{60})：{slow_ma:.2f}\n"
        f"- RSI(14)：{rsi:.1f}\n"
        f"- ATR(14)：{atr:.2f}\n"
        f"- 快均线{'>' if fast_ma > slow_ma else '<'}慢均线，"
        f"价格{'高于' if curr_close > fast_ma else '低于'}快均线\n\n"
        f"请根据以上数据判断接下来的行情方向，给出做多/做空/观望建议和信心分数。"
    )
    return prompt


# ========== 策略主函数 ==========

def initialize(api):
    """策略初始化"""
    api.log("=" * 60)
    api.log("策略20：LLM辅助多因子交易策略 初始化")
    api.log(f"LLM模式: {LLM_MODE}")
    params = api.get_params()
    api.log(f"策略参数: {params}")
    api.log("=" * 60)

    # 用于存储LLM信号缓存（减少调用频率）
    if not hasattr(api, '_llm_cache'):
        api._llm_cache = {}


def strategy_llm(api):
    """
    LLM辅助多因子交易策略主逻辑
    """
    params = api.get_params()
    fast_period  = params.get('fast_ma', 20)
    slow_period  = params.get('slow_ma', 60)
    rsi_period   = params.get('rsi_period', 14)
    atr_period   = params.get('atr_period', 14)
    atr_stop_mult = params.get('atr_stop_mult', 2.0)
    llm_conf_thr = params.get('llm_conf_thr', 0.6)
    vol_period   = params.get('vol_ma_period', 20)
    min_bars     = max(slow_period, rsi_period, atr_period) + 5

    # 获取K线数据
    klines = api.get_klines(0)
    if klines is None or len(klines) < min_bars:
        return

    close  = klines['close']
    high   = klines['high']
    low    = klines['low']
    volume = klines['volume']
    idx    = api.get_idx(0)

    # ===== 计算技术指标 =====
    # 均线
    fast_ma = close.rolling(fast_period).mean().iloc[-1]
    slow_ma = close.rolling(slow_period).mean().iloc[-1]

    # RSI
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(rsi_period).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs    = gain / (loss + 1e-10)
    rsi   = (100 - 100 / (1 + rs)).iloc[-1]

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean().iloc[-1]

    # 当前价和持仓
    curr_price = close.iloc[-1]
    curr_pos   = api.get_pos(0)

    # ===== 获取LLM信号（按间隔调用）=====
    call_key = f'llm_last_call_{idx}'
    last_call = getattr(api, '_llm_last_bar', -LLM_CALL_INTERVAL)

    if idx - last_call >= LLM_CALL_INTERVAL:
        if LLM_MODE == 'mock':
            llm_result = _mock_llm_signal(
                close, volume, fast_ma, slow_ma, rsi, atr
            )
        else:
            prompt = _build_prompt(klines, fast_ma, slow_ma, rsi, atr)
            llm_result = _call_llm_api(prompt)

        api._llm_signal    = llm_result.get('direction', 0)
        api._llm_confidence = llm_result.get('confidence', 0.0)
        api._llm_reason    = llm_result.get('reason', '')
        api._llm_last_bar  = idx

        if abs(api._llm_signal) > 0 and api._llm_confidence >= llm_conf_thr:
            api.log(
                f"[LLM信号] 方向={'多' if api._llm_signal>0 else '空'} "
                f"信心={api._llm_confidence:.2f} 理由={api._llm_reason}"
            )

    llm_dir  = getattr(api, '_llm_signal', 0)
    llm_conf = getattr(api, '_llm_confidence', 0.0)

    # ===== 技术指标二次确认 =====
    ma_bull = fast_ma > slow_ma        # 均线多头
    ma_bear = fast_ma < slow_ma        # 均线空头
    rsi_ok_long  = rsi < 70            # RSI未超买
    rsi_ok_short = rsi > 30            # RSI未超卖

    # 量能确认
    vol_ma = volume.rolling(vol_period).mean().iloc[-1] if len(volume) >= vol_period else volume.mean()
    vol_confirm = volume.iloc[-1] > vol_ma * 1.0  # 当前量不低于均量

    # ===== 止损检查 =====
    entry_price = getattr(api, '_entry_price', None)
    if entry_price and curr_pos != 0 and not np.isnan(atr):
        stop_dist = atr * atr_stop_mult
        if curr_pos > 0 and curr_price < entry_price - stop_dist:
            api.log(f"[止损] 多头止损 入场={entry_price:.2f} 当前={curr_price:.2f} ATR止损={stop_dist:.2f}")
            api.sell(reason='ATR止损平多')
            api._entry_price = None
            return
        elif curr_pos < 0 and curr_price > entry_price + stop_dist:
            api.log(f"[止损] 空头止损 入场={entry_price:.2f} 当前={curr_price:.2f} ATR止损={stop_dist:.2f}")
            api.buycover(reason='ATR止损平空')
            api._entry_price = None
            return

    # ===== 开仓逻辑 =====
    if llm_conf < llm_conf_thr:
        return  # LLM信心不足，不操作

    # --- 做多条件 ---
    if (llm_dir == 1
            and ma_bull
            and rsi_ok_long
            and vol_confirm
            and curr_pos <= 0):

        if curr_pos < 0:
            api.buycover(reason='反手平空')
        api.buy(volume=1, reason=f'LLM多头信号(conf={llm_conf:.2f})')
        api._entry_price = curr_price
        api.log(f"[开多] 价格={curr_price:.2f} 快均={fast_ma:.2f} 慢均={slow_ma:.2f} RSI={rsi:.1f}")

    # --- 做空条件 ---
    elif (llm_dir == -1
            and ma_bear
            and rsi_ok_short
            and vol_confirm
            and curr_pos >= 0):

        if curr_pos > 0:
            api.sell(reason='反手平多')
        api.sellshort(volume=1, reason=f'LLM空头信号(conf={llm_conf:.2f})')
        api._entry_price = curr_price
        api.log(f"[开空] 价格={curr_price:.2f} 快均={fast_ma:.2f} 慢均={slow_ma:.2f} RSI={rsi:.1f}")

    # --- LLM建议观望时平仓 ---
    elif llm_dir == 0 and llm_conf > 0.7 and curr_pos != 0:
        if curr_pos > 0:
            api.sell(reason='LLM建议观望，平多仓')
        else:
            api.buycover(reason='LLM建议观望，平空仓')
        api._entry_price = None
