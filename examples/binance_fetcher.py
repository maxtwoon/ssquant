"""
从 Binance 抓取 5m K 线数据，存入项目 SQLite

Binance REST API:
  GET https://api.binance.com/api/v3/klines
  params: symbol (e.g. BTCUSDT), interval (5m), startTime, endTime, limit (max 1500)

存表名格式: {SYMBOL}_5M_raw（与项目 au888_5M_raw 风格一致）
"""
import os
import sys
import time
import sqlite3

import requests
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_DB_PATH = os.path.join(_PROJ_ROOT, 'data_cache', 'kline_data.db')

API_URL = 'https://api.binance.com/api/v3/klines'
MAX_LIMIT = 1500  # Binance 单次最多 1500 根

# 5 个赛道币种
SYMBOLS = [
    {'symbol': 'BTCUSDT',  'sector': '数字黄金',     'name': 'Bitcoin'},
    {'symbol': 'ETHUSDT',  'sector': '智能合约 L1',  'name': 'Ethereum'},
    {'symbol': 'SOLUSDT',  'sector': '高性能 L1',    'name': 'Solana'},
    {'symbol': 'DOGEUSDT', 'sector': 'Meme 代币',    'name': 'Dogecoin'},
    {'symbol': 'LINKUSDT', 'sector': '预言机',       'name': 'Chainlink'},
]


def fetch_klines_page(symbol, start_ms, end_ms, interval='5m'):
    """单页拉取 K 线"""
    params = {
        'symbol': symbol,
        'interval': interval,
        'startTime': start_ms,
        'endTime': end_ms,
        'limit': MAX_LIMIT,
    }
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def download_symbol(symbol, start_date, end_date):
    """分页下载一个币种的全部 5m 数据"""
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    all_klines = []
    current_start = start_ms
    pages = 0
    while current_start < end_ms:
        try:
            page = fetch_klines_page(symbol, current_start, end_ms)
        except Exception as e:
            print(f"  [ERR] {symbol} page from {current_start}: {e}")
            time.sleep(2)
            continue
        if not page:
            break
        all_klines.extend(page)
        pages += 1
        # 下一页从最后一根的 close_time + 1 开始
        last_close = page[-1][6]
        current_start = last_close + 1
        # 仅当本页满了才继续
        if len(page) < MAX_LIMIT:
            break
        # 简单速率控制（Binance 1200 req/min 限额）
        time.sleep(0.1)
    print(f"  {symbol}: {pages} 页, {len(all_klines)} 根 K 线")
    return all_klines


def klines_to_df(klines):
    """把 Binance 原始格式转为框架需要的 DataFrame"""
    cols_raw = ['open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore']
    df = pd.DataFrame(klines, columns=cols_raw)
    df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['amount'] = df['quote_volume'].astype(float)
    df['symbol'] = ''  # 占位，下游写库时填
    df['openint'] = 0.0
    df['cumulative_openint'] = 0.0
    return df[['datetime', 'symbol', 'open', 'high', 'low', 'close',
               'volume', 'amount', 'openint', 'cumulative_openint']]


def save_to_db(df, symbol):
    """写入 kline_data.db 的 {SYMBOL}_5M_raw 表"""
    table = f"{symbol}_5M_raw"
    df = df.copy()
    df['symbol'] = symbol
    df['datetime'] = df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(_DB_PATH)
    try:
        df.to_sql(table, conn, if_exists='replace', index=False)
        n = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        print(f"  写入表 [{table}]: {n} 条")
    finally:
        conn.close()


def main():
    start_date = '2024-01-01'
    end_date = '2024-12-31'
    print(f"区间: {start_date} ~ {end_date}")
    print(f"币种: {[s['symbol'] for s in SYMBOLS]}")
    print(f"数据库: {_DB_PATH}\n")

    t0 = time.time()
    for sym_cfg in SYMBOLS:
        symbol = sym_cfg['symbol']
        print(f"→ {symbol} ({sym_cfg['name']} / {sym_cfg['sector']})")
        klines = download_symbol(symbol, start_date, end_date)
        if klines:
            df = klines_to_df(klines)
            save_to_db(df, symbol)
        print()
    print(f"完成，总用时 {(time.time() - t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
