"""验证修复后的 API 能否拿到数据 + 看 datetime 字段"""
import sys, os
import requests
import pandas as pd
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)
from ssquant.config.trading_config import get_api_auth
USER, PWD = get_api_auth()

# 直接命中 API
r = requests.get('http://kanpan789.com:8086/futures/kline',
                 params={'username': USER, 'password': PWD,
                         'symbol': 'au888', 'period': '5m',
                         'start_date': '2024-01-02', 'end_date': '2024-01-03'},
                 timeout=30)
records = r.json().get('data', [])
print(f"=== 1) 直接命中 API ===")
print(f"记录数: {len(records)}")
if records:
    print(f"\n第一条字段名: {list(records[0].keys())}")
    print(f"前 3 条 datetime 相关字段:")
    for r in records[:3]:
        # 找找看哪个字段是时间
        for k, v in r.items():
            if 'time' in k.lower() or 'date' in k.lower() or 'dt' in k.lower():
                print(f"  {k}: {v}")
        print(f"  open={r.get('open')}, close={r.get('close')}")

print(f"\n\n=== 2) 经框架 fetch_data_from_api 调用 ===")
from ssquant.data.api_data_fetcher import fetch_data_from_api
df = fetch_data_from_api(symbol='au888', start_date='2024-01-02', end_date='2024-01-05',
                        username=USER, password=PWD, kline_period='5m',
                        adjust_type='1', depth='no', max_retries=1)
print(f"返回 DataFrame: {type(df).__name__}, 长度 {len(df)}")
if not df.empty:
    print(f"列名: {df.columns.tolist()}")
    print(f"索引类型: {type(df.index)}")
    print(f"前 2 行:")
    print(df.head(2).to_string())
