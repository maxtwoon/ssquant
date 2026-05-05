"""data_server 内部连接配置（用户无需修改）

与 kline_source='data_server' 配合：
- api_url：HTTP，用于鉴权、历史/预加载等请求（可与 fallback_servers 二选一或同时配置）。
- ws_url：WebSocket，用于实时 K 线推送。
- fallback_servers：主地址不可达时，HTTP 与 WS 按相同顺序切换；仅配备选、不配顶层 api_url 时，REST 与鉴权均使用备选列表（与旧版仅鉴权走备选、拉 K 线只认顶层 api_url 的行为已对齐）。
"""

DATA_SERVER = {
    'ws_url': 'ws://121.237.178.245:8087',
    'api_url': 'http://121.237.178.245:8086',
    #'ws_url': 'ws://127.0.0.1:8087',
    #'api_url': 'http://127.0.0.1:8086',
    # 主地址不可达时，与 WebSocket 同步轮询以下备选（HTTP 鉴权 + WS 使用相同顺序）
    'fallback_servers': [
        {
            #'ws_url': 'ws://127.0.0.1:8087',
            #'api_url': 'http://127.0.0.1:8086',
            'ws_url': 'ws://60.188.249.241:8087',
            'api_url': 'http://60.188.249.241:8086',
        },
    ],
    'preload_count': 500,
    'auto_reconnect': True,
    'reconnect_interval': 5.0,
}
