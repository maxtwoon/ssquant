"""测试 Binance API 连通性 — 短超时，单请求"""
import sys
import time
import requests

sys.stdout.reconfigure(line_buffering=True)

print(f"[{time.strftime('%H:%M:%S')}] 开始测试...", flush=True)

# 1) ping
print(f"[{time.strftime('%H:%M:%S')}] /ping ...", flush=True)
try:
    r = requests.get('https://api.binance.com/api/v3/ping', timeout=10)
    print(f"[{time.strftime('%H:%M:%S')}] ping OK: {r.status_code} body={r.text[:100]}", flush=True)
except Exception as e:
    print(f"[{time.strftime('%H:%M:%S')}] ping FAIL: {type(e).__name__}: {e}", flush=True)

# 2) 1 个小请求 - BTCUSDT 最近 5 根
print(f"[{time.strftime('%H:%M:%S')}] /klines BTCUSDT 5m limit=5 ...", flush=True)
try:
    r = requests.get('https://api.binance.com/api/v3/klines',
                     params={'symbol': 'BTCUSDT', 'interval': '5m', 'limit': 5},
                     timeout=15)
    print(f"[{time.strftime('%H:%M:%S')}] OK: {r.status_code}, {len(r.json())} 根", flush=True)
    print(f"  最新 K 线: {r.json()[-1][:6]}", flush=True)
except Exception as e:
    print(f"[{time.strftime('%H:%M:%S')}] FAIL: {type(e).__name__}: {e}", flush=True)

# 3) 测试备用域名 (binance-api.com 之类)
print(f"\n[{time.strftime('%H:%M:%S')}] 测试备用端点...", flush=True)
for url in [
    'https://api1.binance.com/api/v3/ping',
    'https://api2.binance.com/api/v3/ping',
    'https://api3.binance.com/api/v3/ping',
    'https://api4.binance.com/api/v3/ping',
    'https://data-api.binance.vision/api/v3/ping',  # 数据专用
]:
    try:
        r = requests.get(url, timeout=8)
        print(f"  {url} -> {r.status_code}", flush=True)
    except Exception as e:
        print(f"  {url} -> FAIL: {type(e).__name__}", flush=True)

print(f"\n[{time.strftime('%H:%M:%S')}] 完成", flush=True)
