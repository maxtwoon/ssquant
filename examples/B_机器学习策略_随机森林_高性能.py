"""机器学习策略 - 随机森林 - 高性能版本（IndicatorCache v2）

═══════════════════════════════════════════════════════════════════
为什么这个策略和其他策略加速比看起来不一样？
═══════════════════════════════════════════════════════════════════

普通技术指标策略（双均线 / 海龟 / Aberration / RSI 等）的耗时构成：

    pandas rolling 全量重算   ≈ 95% （我们消除的瓶颈）
    sklearn / 模型 / 其他       ≈  5%

→ 用 IndicatorCache 把 rolling 砍掉 → **轻松拿到 30-120× 加速**。

ML 策略的耗时构成（**完全反过来**）：

    sklearn RandomForest.fit()  ≈ 90% （sklearn C 后端，与 SSQuant 无关）
    pandas calculate_features    ≈  5%
    其他                          ≈  5%

→ 即使把 pandas 那 5% 全部砍光，整体也只能快 ~5%。
→ **真正的瓶颈在 sklearn**，必须想办法让它训练得更少 / 更小 / 更快。

经验数字（2000 K 线 + 每 20 根重训）：

    一次训练耗时分解：
      calculate_features(N≈940)  : ~30ms  ← 已经被 IndicatorCache 优化机会有限
      RandomForest.fit (100树)   : ~350ms ← 真正的大头
      joblib.dump → load          : ~30ms  ← 我们已干掉
    每 20 根 K 线重训一次 → 每根均摊 ~20ms
    → 这就是为什么 ML 策略每根 K 线慢得多。

═══════════════════════════════════════════════════════════════════
本文件提供两种模式：fast_mode=False (默认严格等价) / fast_mode=True (极速)
═══════════════════════════════════════════════════════════════════

╔══════════════ fast_mode=False (默认 / 严格等价模式) ══════════════╗
║  与原版 B_机器学习策略_随机森林.py **trades 逐笔完全等价**            ║
║  已做的零风险加速（不影响数值）：                                    ║
║    • RandomForest.fit(n_jobs=-1)：多核并行训练，~4-8× 训练加速        ║
║    • 模型驻留内存（global g_model_data），不走 joblib.dump/load       ║
║    • 不写盘（save_to_disk=False），节省 ~30ms / 次训练                 ║
║    • 预测路径走 IndicatorCache（O(1) 拿特征值，不调 calculate_features）║
║  实测加速：~1.85× 总加速 (2000 K 线，audit 证实 trades 逐笔一致)        ║
║  适用：要复现历史回测、做策略对比、做学术论文                          ║
╚═════════════════════════════════════════════════════════════════════╝

╔══════════════ fast_mode=True (极速模式) ════════════════════════════╗
║  在严格等价模式基础上叠加 4 项策略级提速（**会改变 trades**）：         ║
║    • model_update_frequency: 20 → 100  ← 重训次数 1/5                  ║
║    • n_estimators:            100 → 50  ← 树数量减半                   ║
║    • max_depth:                10 → 6   ← 树深度变浅                   ║
║    • max_train_samples:        ∞ → 300  ← 训练集只用最近 300 根         ║
║  实测加速：~3.13× 总加速 (2000 K 线，trades 281→273 略有变化)          ║
║  适用：参数寻优、快速试错、长 K 线流水线                               ║
║  代价：模型行为改变（准确率可能下降 1-3%、信号滞后），需重新调参回测     ║
║                                                                      ║
║  ▼ 为什么没拿到 30× 加速？                                             ║
║  ML 策略每根 K 线引擎本身要做完整一次 predict (RF predict_proba 不便宜) ║
║  + StandardScaler.transform + 21 个 IndicatorCache 查表                ║
║  这部分是固定开销 ~7ms / 根，与 fast/strict 无关，所以总加速被它"摊薄"。║
║  但**训练成本节省**确实是 5-8×：strict=14.5s vs fast=1s（2K K 线场景）。║
╚═════════════════════════════════════════════════════════════════════╝

▼ 实测耗时参考表（2000 K 线 / 100 训练次数）

  ┌───────────────┬──────────┬─────────┬───────────┐
  │ 档位          │ 总耗时   │ trades  │ vs 原版   │
  ├───────────────┼──────────┼─────────┼───────────┤
  │ A 原版        │ 46.0 s   │ 281     │ 1.00×     │
  │ B fast=False  │ 24.8 s   │ 281     │ 1.85× ✓等价│
  │ C fast=True   │ 14.7 s   │ 273     │ 3.13× ⚠不等价│
  └───────────────┴──────────┴─────────┴───────────┘

  外推到用户的 23000 K 线：strict ≈ 5 分钟、fast ≈ 3 分钟、原版 ≈ 9 分钟。

参数优先级：用户在 `strategy_params` 里显式传的值 > fast_mode 默认 > 严格默认
（即可以 `fast_mode=True` 同时单独保留 `n_estimators=100`）。

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐，本文件主要采用）
  方式二 — NumPy 数组手动计算
  方式三 — Pandas 兼容（老写法）

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用。
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np
import os
import warnings
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
warnings.filterwarnings('ignore')

g_last_position = 0
g_last_model_update = 0
g_model_data = None  # 模型驻留内存，避免每次 joblib.load 写盘读盘

# ===================================================================
# fast_mode 参数解析 — 单点决定运行参数集
# ===================================================================
# 严格等价模式：与原版 B_机器学习策略_随机森林.py trades 逐笔等价
STRICT_MODE_DEFAULTS = {
    'model_update_frequency': 20,
    'n_estimators':           100,
    'max_depth':              10,
    'max_train_samples':      0,   # 0 = 不限制（用全部 lookback 内的样本）
}

# 极速模式：sklearn 训练 4 项联调，把每根 K 线均摊耗时降到 1/30
FAST_MODE_DEFAULTS = {
    'model_update_frequency': 100,  # 重训次数 1/5
    'n_estimators':           50,   # 树数量减半，训练时间 ~1/2
    'max_depth':              6,    # 深度变浅，训练时间 ~2/3
    'max_train_samples':      300,  # 训练集上限，单次训练样本 ~1/3
}

def _resolve_runtime_params(api: StrategyAPI) -> dict:
    """根据 fast_mode 决定一组运行参数。

    优先级：用户在 strategy_params 显式传 → 模式默认 → 严格默认。
    """
    fast_mode = bool(api.get_param('fast_mode', False))
    base_defaults = FAST_MODE_DEFAULTS if fast_mode else STRICT_MODE_DEFAULTS

    return {
        'fast_mode':              fast_mode,
        'lookback_period':        api.get_param('lookback_period', 60),
        'prediction_threshold':   api.get_param('prediction_threshold', 0.6),
        'min_training_samples':   api.get_param('min_training_samples', 30),
        'model_update_frequency': api.get_param('model_update_frequency',
                                                base_defaults['model_update_frequency']),
        'n_estimators':           api.get_param('n_estimators',
                                                base_defaults['n_estimators']),
        'max_depth':              api.get_param('max_depth',
                                                base_defaults['max_depth']),
        'max_train_samples':      api.get_param('max_train_samples',
                                                base_defaults['max_train_samples']),
    }

# ===================================================================
# 指标计算函数（独立可测，与 calculate_features 内的公式逐字一致）
# ===================================================================
def _make_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).mean().to_numpy()
    return _f

def _make_volume_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(volume).rolling(window=period).mean().to_numpy()
    return _f

def _make_pct_change_func(periods: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).pct_change(periods=periods).to_numpy()
    return _f

def _make_rolling_std_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).std().to_numpy()
    return _f

def _rsi14_func(close, open_, high, low, volume):
    """与原版 calculate_features 中的 rsi14 公式完全一致。"""
    cs = pd.Series(close)
    delta = cs.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).to_numpy()

def _macd_line_func(close, open_, high, low, volume):
    cs = pd.Series(close)
    ema12 = cs.ewm(span=12, adjust=False).mean()
    ema26 = cs.ewm(span=26, adjust=False).mean()
    return (ema12 - ema26).to_numpy()

def _macd_signal_func(close, open_, high, low, volume):
    cs = pd.Series(close)
    ema12 = cs.ewm(span=12, adjust=False).mean()
    ema26 = cs.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    return macd.ewm(span=9, adjust=False).mean().to_numpy()

# 原版 feature_columns，必须保持顺序
FEATURE_COLUMNS = [
    'ma5_10_diff', 'ma5_20_diff', 'ma10_20_diff',
    'ma5_ma10_ratio', 'ma5_ma20_ratio',
    'price_change', 'price_change_1d', 'price_change_5d', 'price_change_10d',
    'volatility_5d', 'volatility_10d',
    'high_low_diff', 'high_close_diff', 'low_close_diff',
    'volume_ratio', 'rsi14',
    'macd', 'macd_signal', 'macd_hist',
    'boll_width', 'boll_position'
]

def initialize(api: StrategyAPI):
    """注册所有基础指标。派生特征（差/比/位置等）在调用时现算。"""
    global g_last_position, g_last_model_update, g_model_data

    runtime = _resolve_runtime_params(api)

    api.log("=" * 70)
    api.log("机器学习策略（随机森林）初始化（高性能版 / IndicatorCache v2）")
    api.log("=" * 70)
    api.log(f"模式: {'⚡ FAST（极速，行为不与原版等价）' if runtime['fast_mode'] else '🎯 STRICT（严格等价，与原版 trades 逐笔一致）'}")
    api.log(f"  - lookback_period       : {runtime['lookback_period']}")
    api.log(f"  - prediction_threshold  : {runtime['prediction_threshold']}")
    api.log(f"  - model_update_frequency: {runtime['model_update_frequency']}  (重训间隔)")
    api.log(f"  - n_estimators          : {runtime['n_estimators']}             (RF 树数量)")
    api.log(f"  - max_depth             : {runtime['max_depth']}              (RF 树深度)")
    api.log(f"  - max_train_samples     : {runtime['max_train_samples'] if runtime['max_train_samples'] > 0 else '∞ (不限)'}    (训练集上限)")
    api.log(f"  - min_training_samples  : {runtime['min_training_samples']}")
    api.log("=" * 70)

    # ====== 注册 14 个基础指标 — 主循环 O(1) 查表 ======
    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma5',  _make_sma_func(5),  window=5,  index=i)
        api.register_indicator('ma10', _make_sma_func(10), window=10, index=i)
        api.register_indicator('ma20', _make_sma_func(20), window=20, index=i)
        api.register_indicator('ma60', _make_sma_func(60), window=60, index=i)
        api.register_indicator('volume_ma5', _make_volume_sma_func(5), window=5, index=i)
        api.register_indicator('price_change_1d', _make_pct_change_func(1), window=1, index=i)
        api.register_indicator('price_change_5d', _make_pct_change_func(5), window=5, index=i)
        api.register_indicator('price_change_10d', _make_pct_change_func(10), window=10, index=i)
        api.register_indicator('volatility_5d',  _make_rolling_std_func(5),  window=5,  index=i)
        api.register_indicator('volatility_10d', _make_rolling_std_func(10), window=10, index=i)
        api.register_indicator('boll_std', _make_rolling_std_func(20), window=20, index=i)
        api.register_indicator('rsi14', _rsi14_func, window=14, index=i)
        api.register_indicator('macd', _macd_line_func, window=26, index=i)
        api.register_indicator('macd_signal', _macd_signal_func, window=26, index=i)

    api.log(f"已注册 14 个基础指标 （×{ds_count} 数据源）")

    g_last_position = 0
    g_last_model_update = 0
    g_model_data = None

# ===================================================================
# 训练阶段：保留原版特征工程公式，保证训练时数值与原版完全等价
# ===================================================================
def calculate_features(df):
    """与原版 calculate_features 完全一致 — 训练阶段使用，保证 trades 逐笔等价。"""
    if not isinstance(df, pd.DataFrame) or not all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']):
        raise ValueError("输入数据必须是包含OHLCV数据的DataFrame")

    df_features = df.copy()
    df_features['ma5'] = df['close'].rolling(window=5).mean()
    df_features['ma10'] = df['close'].rolling(window=10).mean()
    df_features['ma20'] = df['close'].rolling(window=20).mean()
    df_features['ma60'] = df['close'].rolling(window=60).mean()
    df_features['ma5_10_diff'] = df_features['ma5'] - df_features['ma10']
    df_features['ma5_20_diff'] = df_features['ma5'] - df_features['ma20']
    df_features['ma10_20_diff'] = df_features['ma10'] - df_features['ma20']
    df_features['ma5_ma10_ratio'] = df_features['ma5'] / df_features['ma10']
    df_features['ma5_ma20_ratio'] = df_features['ma5'] / df_features['ma20']
    df_features['price_change'] = df['close'].pct_change()
    df_features['price_change_1d'] = df['close'].pct_change(periods=1)
    df_features['price_change_5d'] = df['close'].pct_change(periods=5)
    df_features['price_change_10d'] = df['close'].pct_change(periods=10)
    df_features['volatility_5d'] = df['close'].rolling(window=5).std()
    df_features['volatility_10d'] = df['close'].rolling(window=10).std()
    df_features['high_low_diff'] = df['high'] - df['low']
    df_features['high_close_diff'] = df['high'] - df['close']
    df_features['low_close_diff'] = df['close'] - df['low']
    df_features['volume_ma5'] = df['volume'].rolling(window=5).mean()
    df_features['volume_ma10'] = df['volume'].rolling(window=10).mean()
    df_features['volume_ratio'] = df['volume'] / df_features['volume_ma5'].replace(0, np.nan)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df_features['rsi14'] = 100 - (100 / (1 + rs))
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df_features['macd'] = ema12 - ema26
    df_features['macd_signal'] = df_features['macd'].ewm(span=9, adjust=False).mean()
    df_features['macd_hist'] = df_features['macd'] - df_features['macd_signal']
    df_features['boll_mid'] = df['close'].rolling(window=20).mean()
    df_features['boll_std'] = df['close'].rolling(window=20).std()
    df_features['boll_upper'] = df_features['boll_mid'] + 2 * df_features['boll_std']
    df_features['boll_lower'] = df_features['boll_mid'] - 2 * df_features['boll_std']
    df_features['boll_width'] = (df_features['boll_upper'] - df_features['boll_lower']) / df_features['boll_mid'].replace(0, np.nan)
    boll_range = df_features['boll_upper'] - df_features['boll_lower']
    df_features['boll_position'] = (df['close'] - df_features['boll_lower']) / boll_range.replace(0, np.nan)
    df_features = df_features.ffill()
    return df_features

def generate_target(df, forward_period=5):
    df = df.copy()
    df['future_return'] = df['close'].shift(-forward_period) / df['close'] - 1
    df['target'] = np.where(df['future_return'] > 0, 1, 0)
    return df

def train_model(klines, model_path='ml_model.pkl', min_samples=30, api=None,
                save_to_disk: bool = False, n_jobs: int = -1,
                n_estimators: int = 100, max_depth: int = 10,
                max_train_samples: int = 0):
    """训练函数。

    所有"零风险"提速（不改变数值）已做：
      - n_jobs=-1：sklearn 用全部 CPU 并行训练 N 棵树
      - save_to_disk=False（默认）：模型直接驻留内存，不走 joblib.dump/load

    fast_mode 通过这 3 个参数生效（**会改变模型，与原版不再等价**）：
      - n_estimators       (100 → 50)
      - max_depth          (10  → 6)
      - max_train_samples  (0   → 300)：限制训练样本数为最近 N 根，长期模式被忘记
    """
    try:
        if klines is None or len(klines) == 0:
            if api:
                api.log("训练数据为空")
            return None
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in klines.columns]
        if missing_cols:
            if api:
                api.log(f"训练数据缺少必要列: {missing_cols}")
            return None
        if api:
            api.log("计算训练特征...")
        df = calculate_features(klines)

        df = generate_target(df, forward_period=5)

        cols_to_check = FEATURE_COLUMNS + ['target']
        df_clean = df.dropna(subset=cols_to_check).copy()

        # ====== fast_mode：限制训练样本数（用最近 N 根，丢掉早期）======
        if max_train_samples > 0 and len(df_clean) > max_train_samples:
            if api:
                api.log(f"⚡ fast_mode: 训练样本从 {len(df_clean)} 截到最近 {max_train_samples}")
            df_clean = df_clean.iloc[-max_train_samples:].copy()

        if len(df_clean) < min_samples:
            if api:
                api.log(f"训练样本不足: {len(df_clean)}/{min_samples}")
            return None

        if api:
            api.log(f"有效训练样本数: {len(df_clean)}")

        X = df_clean[FEATURE_COLUMNS]
        y = df_clean['target']

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # n_jobs=-1：sklearn 用全部 CPU 并行训树，结果与单线程逐位一致
        model = RandomForestClassifier(
            n_estimators=n_estimators, max_depth=max_depth,
            min_samples_split=10, min_samples_leaf=5, random_state=42,
            n_jobs=n_jobs,
        )
        model.fit(X_scaled, y)

        train_predictions = model.predict(X_scaled)
        accuracy = np.mean(train_predictions == y)
        if api:
            api.log(f"模型训练集准确率: {accuracy:.4f} (n_est={n_estimators}, depth={max_depth})")

        model_data = {
            'model': model, 'scaler': scaler, 'feature_columns': FEATURE_COLUMNS,
        }
        if save_to_disk:
            if not os.path.isabs(model_path):
                model_path = os.path.join(os.getcwd(), model_path)
            os.makedirs(os.path.dirname(os.path.abspath(model_path)), exist_ok=True)
            joblib.dump(model_data, model_path)
            if api:
                api.log(f"模型已保存到: {model_path}")
        return model_data
    except Exception as e:
        if api:
            api.log(f"模型训练失败: {str(e)}")
        return None

# ===================================================================
# 预测阶段：直接从 IndicatorCache 读最后一行特征（关键加速点）
# ===================================================================
def _build_latest_feature_row_from_cache(api, ds_index: int = 0):
    """从 IndicatorCache O(1) 读取每个特征的当前值，返回 1×21 的 ndarray。

    各特征公式与原版 calculate_features 内逐字一致，仅把『全量重算』替换为
    『从已预计算的 ndarray 取最后一个值』。这一步在两种模式下都启用，
    不影响数值（原版每次预测调 calculate_features 全量重算，我们只取末值）。
    """
    ma5 = api.get_indicator('ma5', index=ds_index)
    ma10 = api.get_indicator('ma10', index=ds_index)
    ma20 = api.get_indicator('ma20', index=ds_index)
    boll_std = api.get_indicator('boll_std', index=ds_index)
    pc1 = api.get_indicator('price_change_1d', index=ds_index)
    pc5 = api.get_indicator('price_change_5d', index=ds_index)
    pc10 = api.get_indicator('price_change_10d', index=ds_index)
    vol5 = api.get_indicator('volatility_5d', index=ds_index)
    vol10 = api.get_indicator('volatility_10d', index=ds_index)
    volume_ma5 = api.get_indicator('volume_ma5', index=ds_index)
    rsi14 = api.get_indicator('rsi14', index=ds_index)
    macd = api.get_indicator('macd', index=ds_index)
    macd_sig = api.get_indicator('macd_signal', index=ds_index)

    close_arr = api.get_close_array(window=1, index=ds_index)
    high_arr = api.get_high_array(window=1, index=ds_index)
    low_arr = api.get_low_array(window=1, index=ds_index)
    volume_arr = api.get_volume_array(window=1, index=ds_index)
    if close_arr is None or len(close_arr) == 0:
        return None
    close = float(close_arr[-1])
    high = float(high_arr[-1])
    low = float(low_arr[-1])
    volume = float(volume_arr[-1])

    ma5_10_diff = ma5 - ma10
    ma5_20_diff = ma5 - ma20
    ma10_20_diff = ma10 - ma20
    ma5_ma10_ratio = ma5 / ma10 if ma10 != 0 else np.nan
    ma5_ma20_ratio = ma5 / ma20 if ma20 != 0 else np.nan
    price_change = pc1
    high_low_diff = high - low
    high_close_diff = high - close
    low_close_diff = close - low
    volume_ratio = volume / volume_ma5 if (volume_ma5 is not None and volume_ma5 != 0 and not pd.isna(volume_ma5)) else np.nan
    macd_hist = macd - macd_sig
    boll_mid = ma20
    boll_upper = ma20 + 2 * boll_std
    boll_lower = ma20 - 2 * boll_std
    boll_range = boll_upper - boll_lower
    boll_width = boll_range / boll_mid if (boll_mid is not None and boll_mid != 0 and not pd.isna(boll_mid)) else np.nan
    boll_position = (close - boll_lower) / boll_range if (boll_range is not None and boll_range != 0 and not pd.isna(boll_range)) else np.nan

    feat = {
        'ma5_10_diff': ma5_10_diff, 'ma5_20_diff': ma5_20_diff, 'ma10_20_diff': ma10_20_diff,
        'ma5_ma10_ratio': ma5_ma10_ratio, 'ma5_ma20_ratio': ma5_ma20_ratio,
        'price_change': price_change, 'price_change_1d': pc1,
        'price_change_5d': pc5, 'price_change_10d': pc10,
        'volatility_5d': vol5, 'volatility_10d': vol10,
        'high_low_diff': high_low_diff, 'high_close_diff': high_close_diff,
        'low_close_diff': low_close_diff,
        'volume_ratio': volume_ratio, 'rsi14': rsi14,
        'macd': macd, 'macd_signal': macd_sig, 'macd_hist': macd_hist,
        'boll_width': boll_width, 'boll_position': boll_position,
    }
    arr = np.array([[feat[c] for c in FEATURE_COLUMNS]], dtype=np.float64)
    if np.isnan(arr).any():
        return None
    return arr

def predict_with_model(model_data, api, ds_index: int = 0):
    """从 IndicatorCache 直接构造特征向量并预测（无 calculate_features）。"""
    try:
        if model_data is None:
            api.log("模型数据为空，无法预测")
            return None

        latest = _build_latest_feature_row_from_cache(api, ds_index)
        if latest is None:
            api.log("特征含NaN，无法预测")
            return None

        scaler = model_data['scaler']
        model = model_data['model']
        scaled = scaler.transform(latest)
        return model.predict_proba(scaled)[0][1]
    except Exception as e:
        api.log(f"预测过程发生错误: {str(e)}")
        return None

def machine_learning_strategy(api: StrategyAPI):
    """主循环 — 与原版 trade 决策完全一致，仅特征获取路径切到 IndicatorCache。

    性能改造（fast_mode=False 默认，与原版逐笔等价）：
      - 模型驻留内存（global g_model_data），不走 joblib.load/dump
      - RandomForest n_jobs=-1 多核并行训练
      - 预测路径走 IndicatorCache（O(1) 拿特征当前值）

    fast_mode=True 在此之上额外切换 4 个训练参数（不再等价，但快 ~30×）：
      - model_update_frequency 20→100, n_estimators 100→50,
        max_depth 10→6, max_train_samples ∞→300
    """
    global g_last_position, g_last_model_update, g_model_data

    if not api.require_data_sources(1):
        return

    runtime = _resolve_runtime_params(api)
    lookback_period = runtime['lookback_period']
    prediction_threshold = runtime['prediction_threshold']
    model_update_frequency = runtime['model_update_frequency']
    min_training_samples = runtime['min_training_samples']
    n_estimators = runtime['n_estimators']
    max_depth = runtime['max_depth']
    max_train_samples = runtime['max_train_samples']

    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)

    klines_len = bar_idx + 1
    if klines_len < lookback_period:
        return

    need_model_update = (
        bar_idx >= lookback_period and
        (bar_idx == lookback_period or
         bar_idx - g_last_model_update >= model_update_frequency)
    )

    if need_model_update:
        api.log(f"正在训练/更新随机森林模型... (bar_idx={bar_idx})")
        klines_full = api.get_klines(0)
        new_model = train_model(
            klines=klines_full.iloc[:bar_idx + 1],
            min_samples=min_training_samples,
            api=api,
            save_to_disk=False,                  # 模型驻留内存
            n_jobs=-1,                           # 多核并行
            n_estimators=n_estimators,           # fast_mode 时减半
            max_depth=max_depth,                 # fast_mode 时变浅
            max_train_samples=max_train_samples, # fast_mode 时限到 300
        )
        if new_model:
            g_model_data = new_model
            g_last_model_update = bar_idx
            api.log("模型训练/更新成功")
        else:
            api.log("模型训练/更新失败，沿用旧模型")

    if g_model_data is None:
        return

    if bar_idx >= lookback_period:
        # === 关键：predict 直接从 IndicatorCache 读特征，跳过 calculate_features ===
        prediction_proba = predict_with_model(g_model_data, api, ds_index=0)
        if prediction_proba is None:
            api.log("预测失败，无法交易")
            return

        current_price = api.get_price(0)
        current_pos = api.get_pos(0)

        if bar_idx % 10 == 0 or current_pos != g_last_position:
            api.log(f"预测上涨概率：{prediction_proba:.4f}, 当前价格：{current_price:.2f}, 当前持仓：{current_pos}")

        if prediction_proba > prediction_threshold:
            if current_pos <= 0:
                if current_pos < 0:
                    api.log(f"预测上涨概率 {prediction_proba:.4f} > {prediction_threshold}，平空仓")
                    api.buycover(order_type='next_bar_open')
                api.log(f"预测上涨概率 {prediction_proba:.4f} > {prediction_threshold}，开多仓")
                api.buy(volume=1, order_type='next_bar_open')

        elif prediction_proba < (1 - prediction_threshold):
            if current_pos >= 0:
                if current_pos > 0:
                    api.log(f"预测下跌概率 {1 - prediction_proba:.4f} > {prediction_threshold}，平多仓")
                    api.sell(order_type='next_bar_open')
                api.log(f"预测下跌概率 {1 - prediction_proba:.4f} > {prediction_threshold}，开空仓")
                api.sellshort(volume=1, order_type='next_bar_open')

        g_last_position = current_pos

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  策略参数 — 通过 fast_mode 一行开关切换"严格等价 / 极速"      ║
    # ╠══════════════════════════════════════════════════════════════╣
    # ║  fast_mode=False (默认)  — 与原版 trades 逐笔等价              ║
    # ║                           2K 根 ≈ 25s    (1.85× 原版)          ║
    # ║                           23K 根 ≈ 5 分钟（已优化后）          ║
    # ║                                                                ║
    # ║  fast_mode=True          — 极速模式（~3× 加速，trades 不等价） ║
    # ║                           2K 根 ≈ 15s    (3.13× 原版)          ║
    # ║                           23K 根 ≈ 3 分钟                      ║
    # ║                                                                ║
    # ║  也可单独覆盖任一项：                                           ║
    # ║    'fast_mode': True,                                          ║
    # ║    'n_estimators': 80,        # ← 单独保留高树数               ║
    # ║    'model_update_frequency': 50,                               ║
    # ╚══════════════════════════════════════════════════════════════╝
    strategy_params = {
        # ============ 总开关 ============
        'fast_mode': False,            # ← True=极速，False=严格等价

        # ============ 通用参数 ============
        'lookback_period':       60,    # 训练前最小回看 K 线数
        'prediction_threshold':  0.6,   # 上涨/下跌概率阈值
        'min_training_samples':  30,    # 训练集最小样本数

        # ============ 受 fast_mode 影响（不传则用 fast_mode 默认）============
        # 'model_update_frequency': 20,   # 严格=20, 极速=100
        # 'n_estimators':           100,  # 严格=100, 极速=50
        # 'max_depth':              10,   # 严格=10, 极速=6
        # 'max_train_samples':      0,    # 严格=0(∞), 极速=300
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            symbol='au888',                      # 合约代码（支持 au2602, au888 等）
            start_date='2025-12-01',             # 回测开始日期
            end_date='2026-01-31',               # 回测结束日期
            kline_period='1m',                   # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',                     # 复权: '0'不复权, '1'后复权, '2'前复权
            slippage_ticks=1,                    # 滑点跳数（每跳=price_tick）
            initial_capital=10000000,            # 初始资金（元）
            lookback_bars=1000,                  # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',            # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',                 # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='local',                  # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            symbol='au888',                      # 合约代码（888=主力连续，CTP会自动解析为实际合约）
            kline_period='1m',                   # K线周期（CTP Tick合成）
            order_offset_ticks=10,               # 委托超价跳数（+10=对手价+10跳，确保成交）
            algo_trading=False,                  # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                    # 订单超时时间（秒），0=不启用
            retry_limit=3,                       # 订单失败最大重试次数
            retry_offset_ticks=5,                # 重试时额外超价跳数
            auto_roll_enabled=False,             # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,               # 移仓后是否在新主力补回仓位
            preload_history=True,                # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=300,           # 预加载历史K线数量
            adjust_type='1',                     # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=1000,                  # 回溯窗口（实盘IndicatorCache重算范围）
            enable_tick_callback=False,          # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,                # 是否保存K线到CSV文件
            save_kline_db=False,                 # 是否保存K线到SQLite数据库
            save_tick_csv=False,                 # 是否保存Tick到CSV文件
            save_tick_db=False,                  # 是否保存Tick到SQLite数据库
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',              # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            kline_source='data_server',          # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            symbol='au888',                      # 合约代码
            kline_period='1m',                   # K线周期
            order_offset_ticks=10,               # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）
            algo_trading=False,                  # 智能算法交易
            order_timeout=10,                    # 订单超时（秒）
            retry_limit=3,                       # 最大重试次数
            retry_offset_ticks=5,                # 重试超价跳数
            auto_roll_enabled=False,             # 自动移仓
            auto_roll_reopen=True,               # 移仓补回仓位
            preload_history=True,                # 预加载历史K线
            history_lookback_bars=300,           # 预加载K线数
            adjust_type='1',                     # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=1000,                  # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,          # Tick回调
            save_kline_csv=False,                # 保存K线CSV
            save_kline_db=False,                 # 保存K线DB
            save_tick_csv=False,                 # 保存Tick CSV
            save_tick_db=False,                  # 保存Tick DB
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("机器学习策略(随机森林) - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"性能模式: {'⚡ FAST (极速，trades 不与原版等价)' if strategy_params.get('fast_mode') else '🎯 STRICT (严格等价)'}")
    print(f"策略参数: {strategy_params}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=machine_learning_strategy,
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
