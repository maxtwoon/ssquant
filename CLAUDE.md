# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SSQuant (松鼠Quant) is a Chinese futures CTP quantitative trading framework. It supports three execution modes with the same strategy code:
- **BACKTEST** - Historical data backtesting
- **SIMNOW** - CTP simulation trading
- **REAL_TRADING** - Live CTP trading

All user-facing documentation and code comments are in Chinese. Strategy examples are in `examples/`.

## Common Commands

```bash
# Install in development mode
pip install -e .

# Install with dev dependencies (pytest, black, flake8)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_chanlun_strategy.py

# Run a specific test function
pytest tests/test_chanlun_strategy.py::test_kline_to_rawbar -v

# Run tests without visualization (faster, for parameter optimization)
NO_VISUALIZATION=true NO_CONSOLE_LOG=true pytest

# Format code
black ssquant/ examples/ tests/

# Lint
flake8 ssquant/ examples/ tests/
```

## High-Level Architecture

### Three-Mode Unified Strategy Framework

The framework is built around the principle "write once, run everywhere." A strategy is a simple function receiving a `StrategyAPI` instance:

```python
def my_strategy(api: StrategyAPI):
    close = api.get_close()
    if len(close) < 20:
        return
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    # ... trading logic using api.buy(), api.sell(), etc.
```

**Key architectural components:**

1. **`ssquant.api.strategy_api.StrategyAPI`** - The sole abstraction presented to strategies. Provides data access (`get_close()`, `get_pos()`, `get_tick()`) and trading operations (`buy()`, `sell()`, `sellshort()`, `buycover()`, `close_all()`, `reverse_pos()`). Supports multiple data sources via `index=N` parameter.

2. **`ssquant.backtest.unified_runner.UnifiedStrategyRunner`** - Entry point that dispatches to the correct runtime based on `RunMode` (BACKTEST/SIMNOW/REAL_TRADING). Validates config and delegates to mode-specific runners.

3. **`ssquant.backtest.backtest_core.MultiSourceBacktester`** - Historical backtest engine. Orchestrates data fetching, alignment, bar-by-bar execution, result calculation, and parameter optimization. Uses a modular sub-system design:
   - `backtest_data.py` - Data fetching and multi-source alignment
   - `backtest_results.py` - Performance metrics calculation
   - `backtest_report.py` - Report generation
   - `backtest_visualization.py` - Chart plotting
   - `parameter_optimizer.py` - Grid/random/Bayesian parameter search

4. **`ssquant.backtest.live_trading_adapter.LiveTradingAdapter`** - Bridges CTP live/sim market data and order callbacks to the same `StrategyAPI` interface used in backtests. Key responsibilities:
   - Aggregates TICK data into Klines (`LiveDataSource._aggregate_kline()`)
   - Tracks position state (net, long/short split, today/yesterday) from CTP callbacks
   - Implements smart order splitting (close-today vs close-yesterday)
   - Order timeout / retry logic (algo trading)
   - Data recording to CSV/DB (async queue-based writer)

5. **`ssquant.data.data_source.DataSource`** - Backtest data container holding a single symbol+period. Manages pending orders (`_process_pending_orders()`) and supports order types: `bar_close`, `next_bar_open`, `next_bar_close`, `next_bar_high`, `next_bar_low`, `market`, `limit`.

6. **`ssquant.ctp.loader` + `ssquant.pyctp.*`** - CTP binary loading and client wrappers. CTP binaries are versioned per Python version in `ssquant/ctp/py39/` through `py314/`.

### Data Flow

**Backtest mode:**
`UnifiedStrategyRunner` → `MultiSourceBacktester` → fetch data via `api_data_fetcher` → align multi-source → create `StrategyAPI` with `MultiDataSource` → bar-by-bar call strategy function → `DataSource` processes pending orders → calculate results / generate charts.

**Live/SIMNOW mode:**
`UnifiedStrategyRunner` → `LiveTradingAdapter` → init CTP client (`SIMNOWClient` / `RealTradingClient`) → connect & query positions → on each TICK: `LiveDataSource.update_tick()` → aggregate Kline → call strategy function → `LiveDataSource.buy/sell/...()` → CTP order API.

### Configuration

`ssquant/config/trading_config.py` is the central configuration file:
- `API_USERNAME` / `API_PASSWORD` - Data API auth for backtest data fetching
- `ACCOUNTS` dict - SIMNOW and real trading account credentials
- `get_config(mode, account, **overrides)` - Factory function used by all examples to build run configs

**Important:** This file contains credentials. Do not commit changes to it.

### Multi-DataSource Support

Both backtest and live modes support multiple data sources (multi-symbol, multi-period). In backtests, use `backtester.add_symbol_config()` with a `periods` list. In live mode, pass `data_sources=[{'symbol': ..., 'kline_period': ...}, ...]` to `get_config()`. Access via `api.get_close(index=1)`, `api.buy(index=1)`, etc.

### Order Types

The framework supports several order execution semantics:
- `bar_close` - Execute at current bar close (immediate in backtest)
- `next_bar_open` / `next_bar_close` / `next_bar_high` / `next_bar_low` - Execute at next bar's price (queued in backtest)
- `market` - Use bid1/ask1 for tick strategies
- `limit` - Specify exact price

In live trading, `offset_ticks` controls how many ticks to shift from the opposite price to improve fill probability.

### Testing Notes

- Tests in `tests/` use pytest. There is also a new untracked test file `tests/test_chanlun_e2e.py`.
- Some tests import from `examples/` (e.g., `examples.B_缠论多空信号策略`), so strategy files in `examples/` are treated as importable modules.
- Environment variables `NO_VISUALIZATION=true` and `NO_CONSOLE_LOG=true` suppress chart generation and console output (useful for test runs and parameter optimization).
