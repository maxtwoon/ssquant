"""看完整记录的所有字段"""
import sys, os, json
import requests
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)
from ssquant.config.trading_config import get_api_auth
USER, PWD = get_api_auth()
r = requests.get('http://kanpan789.com:8086/futures/kline',
                 params={'username': USER, 'password': PWD,
                         'symbol': 'au888', 'period': '5m',
                         'start_date': '2024-01-02', 'end_date': '2024-01-03'},
                 timeout=30)
data = r.json()
records = data.get('data', [])
print(f"总记录数: {len(records)}")
if records:
    print(f"\n第一条所有字段:")
    for k, v in records[0].items():
        print(f"  {k!r:30}: {v!r}")
    print(f"\n第二条所有字段:")
    for k, v in records[1].items():
        print(f"  {k!r:30}: {v!r}")
    print(f"\n最后一条所有字段:")
    for k, v in records[-1].items():
        print(f"  {k!r:30}: {v!r}")
