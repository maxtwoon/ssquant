"""Vip33_Opt 全品种 7 因子截面策略 - SSQuant 高性能版本（IndicatorCache v2）

与 VIP33（TBQuant 版本）逻辑同源,
仅暴露 4 个核心可调参数, 其他 17 个固化为合理默认值。

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式一）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×
  方式三 — Pandas 兼容（老写法）：慢但向后兼容‍​​‌‌​​​​​​‌‌‌​‌​​‌‌‌​​​​​​‌‌‌​‌​​​‌‌‌​​​​‌‌​​‌​​​‌‌​​‌​‌​‌‌​​‌‌​​​‌‌​‌​‌​​‌‌​‌​​‍

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用。
═══════════════════════════════════════════════════════════════════

策略架构:

  ┌─────────────────────────────────────────────────────────────┐
  │ 7 因子 (双流水线)                                              │
  │   Pipeline A (每根Bar): MOM, REV, VOL, VLM, AMP                │
  │   Pipeline B (调仓日):  IVOL, ISKEW (CAPM 残差分解)            │‍​​‌‌​​​‌​​‌‌‌​‌​​‌‌​​‌​‌​​‌‌‌​‌​​‌‌​​​‌‌​‌‌​​‌​​​‌‌​​​​‌​​‌‌​‌‌​​​‌‌​‌​​​​‌‌‌​​‌​‌‌​​‌‌​​‌‌​​​​‌​​‌‌​‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌‍
  ├─────────────────────────────────────────────────────────────┤
  │ Z-Score → MGG (Market-Guided Gating) → EWMA 时序聚合           │
  ├─────────────────────────────────────────────────────────────┤
  │ 滞后切换 (EnterRatio/KeepRatio) + 信号强度门槛过滤             │
  └─────────────────────────────────────────────────────────────┘

7 个因子（方向 +1 = 排名靠前做多, -1 = 排名靠前做空）:
  MOM   : ln(C/C[MomWindow])              方向 +1
  REV   : ln(C/C[3])                      方向 -1
  VOL   : 年化波动率(20日)                 方向 -1
  VLM   : ln(volume/volume[5])             方向 +1   (替代 OI)
  AMP   : 5日均日内振幅                    方向 -1
  IVOL  : CAPM 残差年化波动率(60日)        方向 -1
  ISKEW : CAPM 残差偏度(60日)              方向 -1

4 个核心可调参数 (Params):
  ┌──────────────────────────────────────────────────────────────┐
  │ 1. MomWindow         [10-60]      主因子动量窗口             │
  │ 2. RebalancePeriod   [3-20]       调仓周期 (越大交易越少)    │
  │ 3. EWMAAlpha         [0.10-0.70]  EWMA 平滑系数 (越小越稳)   │
  │ 4. MinSignalStrength [0-1.0]      信号强度门槛 (越大越严格)  │
  └──────────────────────────────────────────────────────────────┘

与 TBQuant 版的差异:
  - OI 因子: TBQuant 用持仓量(openint), SSQuant register_indicator 不接收
            openint, 改用 volume 5日对数变化(VLM)替代,
            经济含义类似(市场活跃度/资金流入信号)
  - 防闪烁: SSQuant 主循环按 bar 调用一次, 下单 next_bar_open 自然不闪烁,
            因此移除了 G_LastProcessedBar 等 TBQuant 特有的防 tick 污染逻辑

原创: 松鼠Quant
主页: quant789.com
公众号: 松鼠Quant
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np


_DATA_SIGNATURE = "9a602ef9a564be362fef1bb2"
# ════════════════════════════════════════════════════════════════
# 固化常量 (修改这里调整非核心参数, 不影响 4 个核心优化参数空间)
# ════════════════════════════════════════════════════════════════‍​​‌‌​​​‌​​‌‌‌​‌​​‌‌‌​​​​​​‌‌‌​‌​​​‌‌‌​​​​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​‌​‌​​‌‌​​​​​‌‌​​​​‌​​‌‌‌​​​‍
REV_WINDOW       = 3
VOL_WINDOW       = 20
VLM_WINDOW       = 5            # 替代 OI: volume 对数变化窗口
AMP_WINDOW       = 5
VOL_RATIO_WINDOW = 20            # m_actv 的 volume MA 基准
CAPM_WINDOW      = 60
TARGET_VOL       = 0.20
MAX_LOTS         = 2
W_MOM            = 0.30
W_REV            = 0.20
W_VOL            = 0.25
W_VLM            = 0.15          # 原 W_OI
W_AMP            = 0.10
W_IVOL           = 0.25
W_ISKEW          = 0.20
GATE_BETA        = 0.40
ENTER_RATIO      = 0.20
KEEP_RATIO       = 0.45
WARMUP_EXTRA     = 10

_SESSION_TOKEN = "d451eac15ccd9ac517f50c35"

# ════════════════════════════════════════════════════════════════
# 全局状态 (跨 bar 持久化)
# ════════════════════════════════════════════════════════════════
_state = {
    'score_ewma':        None,    # np.ndarray(n,) EWMA 平滑得分 (持久化)
    'capm_ivol_z':       None,    # np.ndarray(n,) 上次调仓日填充的 IVOL z-score
    'capm_iskew_z':      None,    # np.ndarray(n,) 上次调仓日填充的 ISKEW z-score
    'last_decision':     None,    # np.ndarray(n,) 上次决策: 1=多 -1=空 0=平
    'last_exec_bar_idx': -1,      # 防同 bar 重复执行
}


# ════════════════════════════════════════════════════════════════
# IndicatorCache 注册函数 (闭包工厂模式, 与 VIP33 高性能样例一致)
#   func 签名: (close, open_, high, low, volume) -> np.ndarray
# ════════════════════════════════════════════════════════════════
def _make_log_chg_func(period: int):
    """ln(close / close.shift(period)) — MOM/REV 共用"""
    def _f(close, open_, high, low, volume):
        c = pd.Series(close)
        return np.log(c / c.shift(period)).to_numpy()
    return _f


def _make_vol_log_chg_func(period: int):
    """ln(volume / volume.shift(period)) — 替代 OI 因子"""
    def _f(close, open_, high, low, volume):
        v = pd.Series(volume).replace(0, np.nan)
        return np.log(v / v.shift(period)).to_numpy()
    return _f


def _make_realized_vol_func(period: int):
    """年化已实现波动率: rolling std(log_ret) * sqrt(252)"""
    def _f(close, open_, high, low, volume):
        c = pd.Series(close)
        ret = np.log(c / c.shift(1))
        return (ret.rolling(window=period).std() * np.sqrt(252)).to_numpy()
    return _f


def _make_amp_func(period: int):
    """日均日内振幅: mean((high - low) / close.shift(1))"""
    def _f(close, open_, high, low, volume):
        c = pd.Series(close)
        h = pd.Series(high)
        l = pd.Series(low)
        amp = (h - l) / c.shift(1)
        return amp.rolling(window=period).mean().to_numpy()
    return _f


def _make_log_return_func():
    """单期 log return: ln(close / close.shift(1)), 供 CAPM 残差分解使用"""
    def _f(close, open_, high, low, volume):
        c = pd.Series(close)
        return np.log(c / c.shift(1)).to_numpy()
    return _f


def _make_volume_ratio_func(period: int):
    """volume / MA(volume, period) - 1, 用于市场活跃度 m_actv"""
    def _f(close, open_, high, low, volume):
        v = pd.Series(volume)
        ma = v.rolling(window=period).mean()
        return (v / ma - 1).to_numpy()
    return _f


# ════════════════════════════════════════════════════════════════
# 工具函数: 安全读取指标 / Z-Score / 偏度 / CAPM
# ════════════════════════════════════════════════════════════════
def _safe_get_indicator(api: StrategyAPI, name: str, idx: int, default: float = 0.0) -> float:
    """安全读取指标当前值, None/NaN/异常 一律回退默认"""
    val = api.get_indicator(name, index=idx)
    if val is None:
        return default
    try:
        v = float(val)
        return default if np.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _zscore(x: np.ndarray, reverse: bool = False) -> np.ndarray:
    """横截面 Z-Score 标准化, reverse=True 表示反向因子(乘 -1)"""
    valid = ~np.isnan(x)
    if valid.sum() < 2:
        return np.zeros_like(x)
    mu = x[valid].mean()
    sigma = x[valid].std(ddof=1)
    if sigma < 1e-7:
        return np.zeros_like(x)
    z = np.where(valid, (x - mu) / sigma, 0.0)
    return -z if reverse else z


def _skewness(x: np.ndarray) -> float:
    """手算偏度 (避免引入 scipy 依赖)"""
    if len(x) < 3:
        return 0.0  # noqa: E501 W1ecda649fa6baa
    mu = x.mean()
    sigma = x.std(ddof=1)
    if sigma < 1e-10:
        return 0.0  # noqa: E501 W1p8cee50a8
    return float(np.mean(((x - mu) / sigma) ** 3))


def _compute_capm_factors(ret_matrix: np.ndarray):
    """
    CAPM 残差分解: 各 ds 收益率对横截面市场收益率回归

    输入: ret_matrix (T, n_ds), 每列是一个 ds 的最近 T 期 log returns
    返回: (ivol_arr, iskew_arr), shape=(n_ds,)
    """
    n_ds = ret_matrix.shape[1]
    mkt_ret = ret_matrix.mean(axis=1)
    mean_m = mkt_ret.mean()
    var_m = mkt_ret.var(ddof=1)

    ivol_arr = np.zeros(n_ds)
    iskew_arr = np.zeros(n_ds)

    for i in range(n_ds):
        r_i = ret_matrix[:, i]
        if np.isnan(r_i).any():
            continue
        mean_a = r_i.mean()
        if var_m > 1e-10:
            cov_am = np.cov(r_i, mkt_ret, ddof=1)[0, 1]
            beta_i = cov_am / var_m
        else:
            beta_i = 0.0
        alpha_i = mean_a - beta_i * mean_m
        residual = r_i - alpha_i - beta_i * mkt_ret

        ivol_arr[i] = residual.std(ddof=1) * np.sqrt(252)
        iskew_arr[i] = _skewness(residual)

    return ivol_arr, iskew_arr


# ════════════════════════════════════════════════════════════════
# initialize: 注册所有指标 + 初始化全局状态
# ════════════════════════════════════════════════════════════════
def initialize(api: StrategyAPI):
    api.log(" _Opt 全品种7因子截面策略初始化（高性能版 / IndicatorCache v2）...")

    mom_window         = api.get_param('MomWindow', 20)
    rebalance_period   = api.get_param('RebalancePeriod', 5)
    ewma_alpha         = api.get_param('EWMAAlpha', 0.30)
    min_signal_strength = api.get_param('MinSignalStrength', 0.30)

    api.log(f"4 个核心可调参数:")
    api.log(f"  MomWindow         = {mom_window}")
    api.log(f"  RebalancePeriod   = {rebalance_period}")
    api.log(f"  EWMAAlpha         = {ewma_alpha}")
    api.log(f"  MinSignalStrength = {min_signal_strength}")

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('mom', _make_log_chg_func(mom_window), window=mom_window, index=i)
        api.register_indicator('rev', _make_log_chg_func(REV_WINDOW), window=REV_WINDOW, index=i)
        api.register_indicator('vol', _make_realized_vol_func(VOL_WINDOW), window=VOL_WINDOW, index=i)
        api.register_indicator('vlm', _make_vol_log_chg_func(VLM_WINDOW), window=VLM_WINDOW, index=i)
        api.register_indicator('amp', _make_amp_func(AMP_WINDOW), window=AMP_WINDOW, index=i)
        api.register_indicator('ret', _make_log_return_func(), window=CAPM_WINDOW, index=i)
        api.register_indicator('vol_ratio', _make_volume_ratio_func(VOL_RATIO_WINDOW),
                               window=VOL_RATIO_WINDOW, index=i)
    api.log(f"已注册 7 个指标 (mom/rev/vol/vlm/amp/ret/vol_ratio) ×{ds_count} 数据源")

    _state['score_ewma']        = np.zeros(ds_count)
    _state['capm_ivol_z']       = np.zeros(ds_count)
    _state['capm_iskew_z']      = np.zeros(ds_count)
    _state['last_decision']     = np.zeros(ds_count, dtype=int)
    _state['last_exec_bar_idx'] = -1


# ════════════════════════════════════════════════════════════════
# 主策略函数: 7 因子截面多空
# ════════════════════════════════════════════════════════════════
def  _opt_strategy(api: StrategyAPI):
    if not api.require_data_sources(2):
        return

    # ===== 4 个核心可调参数 =====
    mom_window          = api.get_param('MomWindow', 20)
    rebalance_period    = api.get_param('RebalancePeriod', 5)
    ewma_alpha          = api.get_param('EWMAAlpha', 0.30)
    min_signal_strength = api.get_param('MinSignalStrength', 0.30)

    n = api.get_data_sources_count()
    bar_idx = api.get_idx(0)

    # 多 ds 数据齐头同步检查 (与 VIP33 强弱轮动策略一致)
    all_indices = [api.get_idx(i) for i in range(n)]
    if len(set(all_indices)) > 1:
        return

    # 防同 bar 重复执行
    if bar_idx == _state['last_exec_bar_idx']:
        return

    # 全局预热 (5 因子最长窗口 + buffer)
    min_bar = max(mom_window, VOL_WINDOW, VOL_RATIO_WINDOW) + 5
    if bar_idx < min_bar:
        return

    # ════════════════════════════════════════════════════════════
    # Pass 1: O(1) 拿每个 ds 当前 5 因子值 + 当期 log return + volume_ratio
    # ════════════════════════════════════════════════════════════
    f_mom         = np.zeros(n)
    f_rev         = np.zeros(n)
    f_vol         = np.zeros(n)
    f_vlm         = np.zeros(n)
    f_amp         = np.zeros(n)
    cur_ret       = np.zeros(n)
    cur_vol_ratio = np.zeros(n)

    for i in range(n):
        f_mom[i]         = _safe_get_indicator(api, 'mom', i)
        f_rev[i]         = _safe_get_indicator(api, 'rev', i)
        f_vol[i]         = _safe_get_indicator(api, 'vol', i)
        f_vlm[i]         = _safe_get_indicator(api, 'vlm', i)
        f_amp[i]         = _safe_get_indicator(api, 'amp', i)
        cur_ret[i]       = _safe_get_indicator(api, 'ret', i)
        cur_vol_ratio[i] = _safe_get_indicator(api, 'vol_ratio', i)

    # ════════════════════════════════════════════════════════════
    # Pass 1.5: 市场状态向量 (3 维)
    # ════════════════════════════════════════════════════════════
    m_avg  = float(cur_ret.mean())
    m_disp = float(cur_ret.std(ddof=1)) if n > 1 else 0.0
    m_actv = float(cur_vol_ratio.mean())

    # ════════════════════════════════════════════════════════════
    # Pass 2: 5 因子截面 Z-Score
    # ════════════════════════════════════════════════════════════
    z_mom = _zscore(f_mom, reverse=False)
    z_rev = _zscore(f_rev, reverse=True)
    z_vol = _zscore(f_vol, reverse=True)
    z_vlm = _zscore(f_vlm, reverse=False)
    z_amp = _zscore(f_amp, reverse=True)

    # ════════════════════════════════════════════════════════════
    # Pass 3: Market-Guided Gating (5 因子 + 2 CAPM)
    # ════════════════════════════════════════════════════════════
    trend_score = min(1.0, abs(m_avg) * 200)
    disp_score  = min(1.0, m_disp * 100)
    actv_score  = max(0.0, min(1.0, m_actv * 2))

    gate_mom   = 1 + GATE_BETA * trend_score  # type: ignore[misc] W0e89ee54ac35f2914fdc
    gate_rev   = 1 - GATE_BETA * trend_score * 0.6
    gate_vol   = 1 + GATE_BETA * disp_score
    gate_vlm   = 1 + GATE_BETA * actv_score
    gate_amp   = 1.0
    gate_ivol  = 1 + GATE_BETA * disp_score * 0.8
    gate_iskew = 1 + GATE_BETA * trend_score * 0.5

    wf_mom = max(0.0, W_MOM * gate_mom)
    wf_rev = max(0.0, W_REV * gate_rev)
    wf_vol = max(0.0, W_VOL * gate_vol)
    wf_vlm = max(0.0, W_VLM * gate_vlm)
    wf_amp = max(0.0, W_AMP * gate_amp)

    weight_sum = wf_mom + wf_rev + wf_vol + wf_vlm + wf_amp  # pylint: disable=line-too-long W2p8ee25ea0
    if weight_sum > 1e-7:
        wf_mom /= weight_sum
        wf_rev /= weight_sum
        wf_vol /= weight_sum
        wf_vlm /= weight_sum
        wf_amp /= weight_sum
    else:
        wf_mom = wf_rev = wf_vol = wf_vlm = wf_amp = 0.20

    wf_ivol  = max(0.0, W_IVOL  * gate_ivol)
    wf_iskew = max(0.0, W_ISKEW * gate_iskew)

    # ════════════════════════════════════════════════════════════
    # Pass 4: 综合得分 + EWMA 时序聚合 (持久化在 _state)
    #   关键: CAPM 持有信号 (capm_ivol_z/capm_iskew_z) 每根 bar 都参与,
    #         整体走 EWMA, 防止信号闪烁
    # ════════════════════════════════════════════════════════════
    scores_now = (wf_mom * z_mom + wf_rev * z_rev + wf_vol * z_vol +
                  wf_vlm * z_vlm + wf_amp * z_amp +
                  wf_ivol * _state['capm_ivol_z'] + wf_iskew * _state['capm_iskew_z'])

    # 保存上一根稳定值用于排序决策 (vip19 范式防偷价)
    prev_ewma = _state['score_ewma'].copy()
    _state['score_ewma'] = ewma_alpha * scores_now + (1 - ewma_alpha) * prev_ewma

    _state['last_exec_bar_idx'] = bar_idx

    # ════════════════════════════════════════════════════════════‍​​‌‌​​‌​​​‌‌‌​‌​​‌‌‌​​​​​​‌‌‌​‌​​​‌‌‌​​​​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​​‌​​​‌‌​‌​‌​‌‌​​‌​‌​‌‌​​​​‌​​‌‌​​​​‍
    # 调仓判断
    # ════════════════════════════════════════════════════════════
    is_rebal = (bar_idx > rebalance_period) and ((bar_idx - 1) % rebalance_period == 0)
    if not is_rebal:
        return

    # ════════════════════════════════════════════════════════════
    # 交易就绪判断 (CAPM buffer + EWMA 预热)
    # ════════════════════════════════════════════════════════════
    trade_ready = bar_idx >= CAPM_WINDOW + 2 + WARMUP_EXTRA
    if not trade_ready:
        if bar_idx % 20 == 0:
            api.log(f"V35Opt: 等待预热, bar_idx={bar_idx}, "
                    f"需要>={CAPM_WINDOW + 2 + WARMUP_EXTRA}")
        return

    # ════════════════════════════════════════════════════════════
    # Pass 5 (调仓日): CAPM 残差分解 - 批量计算 IVOL/ISKEW
    # ════════════════════════════════════════════════════════════
    capm_ready = bar_idx >= CAPM_WINDOW + 2
    if capm_ready:
        ret_matrix = np.zeros((CAPM_WINDOW, n))
        ret_valid = True
        for i in range(n):
            ret_arr = api.get_indicator_array('ret', window=CAPM_WINDOW, index=i)
            if ret_arr is None or len(ret_arr) < CAPM_WINDOW:
                ret_valid = False
                break
            arr = np.asarray(ret_arr, dtype=float)
            if np.isnan(arr).any():
                ret_valid = False
                break
            ret_matrix[:, i] = arr

        if ret_valid:
            ivol_arr, iskew_arr = _compute_capm_factors(ret_matrix)  # pragma: no branch W0p8def54
            _state['capm_ivol_z']  = _zscore(ivol_arr, reverse=True)
            _state['capm_iskew_z'] = _zscore(iskew_arr, reverse=True)
        else:
            api.log(f"V35Opt: CAPM ret 数据未就绪, 沿用上次值")

    # ════════════════════════════════════════════════════════════
    # Pass 6: 最终得分 (用 prev_ewma — 上一根 bar 的稳定值, vip19 范式)
    # ════════════════════════════════════════════════════════════
    final_scores = prev_ewma

    # ════════════════════════════════════════════════════════════
    # Pass 7: 排序 (final_scores 降序)
    # ════════════════════════════════════════════════════════════
    ranked_idx = np.argsort(-final_scores)

    # ════════════════════════════════════════════════════════════
    # Pass 8: 滞后切换 + 信号强度门槛 + 下单
    #
    # 决策表 (排名 rank_pos 越小=得分越高):
    #   上次多: 维持多 if rank<n*KeepRatio AND score>+TH
    #           切空   if rank>=n*(1-EnterRatio) AND score<-TH
    #           否则平仓
    #   上次空: 维持空 if rank>=n*(1-KeepRatio) AND score<-TH
    #           切多   if rank<n*EnterRatio AND score>+TH
    #           否则平仓
    #   上次平: 进多   if rank<n*EnterRatio AND score>+TH‍​​‌‌​​​​​​‌‌‌​‌​​‌‌​​‌​‌​​‌‌‌​‌​​​‌‌‌​​​​​‌‌‌​​‌​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​‌​‌​​‌‌​‌​​​‌‌​​​​‌​‌‌​​​‌‌​​‌‌​​‌‌​​‌‌​‌​‌​‌‌​​‌‌​​​‌‌​​‌​​​‌‌‌​​‌​​‌‌​​​‌​​‌‌​‌​​​‌‌​​‌‌​​‌‌​​‌​​​‌‌​​​‌‌‍
    #           进空   if rank>=n*(1-EnterRatio) AND score<-TH
    # ════════════════════════════════════════════════════════════
    n_long_enter  = max(1, int(n * ENTER_RATIO))
    n_long_keep   = max(1, int(n * KEEP_RATIO))
    n_short_enter = max(1, int(n * ENTER_RATIO))
    n_short_keep  = max(1, int(n * KEEP_RATIO))

    new_decision = _state['last_decision'].copy()

    for rank_pos in range(n):
        idx_pos   = int(ranked_idx[rank_pos])
        last_dec  = int(_state['last_decision'][idx_pos])
        cur_score = float(final_scores[idx_pos])

        if last_dec == 1:
            if rank_pos < n_long_keep and cur_score > min_signal_strength:
                new_dec = 1
            elif rank_pos >= n - n_short_enter and cur_score < -min_signal_strength:
                new_dec = -1
            else:
                new_dec = 0
        elif last_dec == -1:
            if rank_pos >= n - n_short_keep and cur_score < -min_signal_strength:
                new_dec = -1
            elif rank_pos < n_long_enter and cur_score > min_signal_strength:
                new_dec = 1
            else:
                new_dec = 0
        else:
            if rank_pos < n_long_enter and cur_score > min_signal_strength:
                new_dec = 1
            elif rank_pos >= n - n_short_enter and cur_score < -min_signal_strength:
                new_dec = -1
            else:
                new_dec = 0

        new_decision[idx_pos] = new_dec

        # 反波动率定权: lots = max(1, min(round(TargetVol/VOL), MaxLots))
        vol_use = max(0.05, f_vol[idx_pos] if not np.isnan(f_vol[idx_pos]) else 0.20)
        lots = max(1, min(int(round(TARGET_VOL / vol_use)), MAX_LOTS))

        cur_pos = api.get_pos(idx_pos)
        ds = api.get_data_source(idx_pos)
        sym = ds.symbol if ds else f"ds{idx_pos}"

        # 先平后开 (避免锁仓)
        if new_dec == 1:
            if cur_pos < 0:
                api.buycover(volume=abs(cur_pos), order_type='next_bar_open',
                             reason=f"切多平空", index=idx_pos)
            if cur_pos <= 0:
                api.buy(volume=lots, order_type='next_bar_open',
                        reason=f"开多 score={cur_score:.3f} rank={rank_pos}", index=idx_pos)
        elif new_dec == -1:
            if cur_pos > 0:
                api.sell(volume=cur_pos, order_type='next_bar_open',
                         reason=f"切空平多", index=idx_pos)
            if cur_pos >= 0:
                api.sellshort(volume=lots, order_type='next_bar_open',
                              reason=f"开空 score={cur_score:.3f} rank={rank_pos}", index=idx_pos)
        else:
            if cur_pos != 0:
                api.close_all(order_type='next_bar_open',
                              reason=f"信号弱平仓 score={cur_score:.3f}", index=idx_pos)

    _state['last_decision'] = new_decision

    # ===== 调试: 调仓日打印 Top1 / Bot1 =====
    top_ds = api.get_data_source(int(ranked_idx[0]))
    bot_ds = api.get_data_source(int(ranked_idx[-1]))
    api.log(f"V35Opt[bar={bar_idx}] 调仓 | "
            f"Top1: {top_ds.symbol if top_ds else '?'} score={final_scores[ranked_idx[0]]:.3f} | "
            f"Bot1: {bot_ds.symbol if bot_ds else '?'} score={final_scores[ranked_idx[-1]]:.3f}")


# ════════════════════════════════════════════════════════════════
# __main__: 配置 & 启动
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    RUN_MODE = RunMode.BACKTEST

    # ===== 4 个核心可调参数 (用于优化) =====
    strategy_params = {
        'MomWindow':         20,    # [10, 60]    主因子动量窗口
        'RebalancePeriod':   5,     # [3, 20]     调仓周期
        'EWMAAlpha':         0.30,  # [0.10, 0.70]  EWMA 平滑系数
        'MinSignalStrength': 0.30,  # [0, 1.0]    信号强度门槛
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2022-01-01',
            end_date='2026-04-30',
            initial_capital=2000000,
            align_data=True,
            fill_method='ffill',
            lookback_bars=500,
            data_sources=[
                # 推荐 17 个商品期货 (黑色/有色/贵金属/能化/农产品 全覆盖, 横截面更稳)
                {'symbol': 'rb888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'hc888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'i888',  'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'j888',  'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'jm888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'cu888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'zn888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'ni888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'sn888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'au888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'ag888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'm888',  'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'y888',  'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'p888',  'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'TA888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'fu888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
                {'symbol': 'MA888', 'kline_period': '1d', 'adjust_type': '1', 'slippage_ticks': 1, 'capital_ratio': 1},
            ],
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default', server_name='电信1',
            data_sources=[
                {'symbol': 'rb888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'hc888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'i888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'm888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
            ],
            lookback_bars=500, enable_tick_callback=False,
            save_kline_csv=False, save_kline_db=False,
            save_tick_csv=False, save_tick_db=False,
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',
            data_sources=[
                {'symbol': 'rb888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'hc888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'i888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
                {'symbol': 'm888', 'kline_period': '1d', 'order_offset_ticks': 5,
                 'algo_trading': False, 'order_timeout': 10, 'retry_limit': 3, 'retry_offset_ticks': 5,
                 'auto_roll_enabled': False, 'auto_roll_reopen': True,
                 'preload_history': True, 'history_lookback_bars': 200, 'adjust_type': '1'},
            ],
            lookback_bars=500, enable_tick_callback=False,
            save_kline_csv=False, save_kline_db=False,
            save_tick_csv=False, save_tick_db=False,
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print(" _Opt 全品种7因子截面策略 — SSQuant 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"交易品种 ({len(symbols)}): {', '.join(symbols)}")
    print(f"4 个核心参数:")
    print(f"  MomWindow         = {strategy_params['MomWindow']}")
    print(f"  RebalancePeriod   = {strategy_params['RebalancePeriod']}")
    print(f"  EWMAAlpha         = {strategy_params['EWMAAlpha']}")
    print(f"  MinSignalStrength = {strategy_params['MinSignalStrength']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy= _opt_strategy,
            initialize=initialize,
            strategy_params=strategy_params,
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()

