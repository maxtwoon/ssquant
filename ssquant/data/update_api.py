#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K 线数据库增量更新 HTTP API 服务

依赖:
    pip install fastapi uvicorn

启动:
    python ssquant/data/update_api.py
    # 或
    uvicorn ssquant.data.update_api:app --host 0.0.0.0 --port 8000

接口:
    POST /update
    {
        "db_path": "D:\\data\\kline_data.db",
        "end_date": "2026-07-07",      // 可选，默认今天
        "tables": ["rb888_1M_raw"]      // 可选，默认全部
    }

    GET /health
"""
import os
import sys
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# 确保使用项目根目录的 ssquant
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _project_root)

from ssquant.data.update_service import update_kline_db

app = FastAPI(title="SSQuant K 线数据库更新服务", version="1.0.0")

# 更新操作是同步阻塞的，使用线程池执行避免阻塞事件循环
_executor = ThreadPoolExecutor(max_workers=1)


class UpdateRequest(BaseModel):
    db_path: str = Field(..., description="目标 SQLite 数据库路径")
    end_date: Optional[str] = Field(None, description="更新截止日期 YYYY-MM-DD，默认今天")
    tables: Optional[List[str]] = Field(None, description="仅更新的表名列表，默认全部")


class UpdateResponse(BaseModel):
    success: bool
    db_path: str
    end_date: str
    total_tables: int
    success_count: int
    fail_count: int
    total_added: int
    log_path: str
    details: Optional[list] = None


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/update", response_model=UpdateResponse)
async def update(req: UpdateRequest):
    if not os.path.exists(req.db_path):
        raise HTTPException(status_code=400, detail=f"数据库不存在: {req.db_path}")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            update_kline_db,
            req.db_path,
            req.end_date,
            req.tables,
            0.5,
            None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")

    if not result.get('success') and 'error' in result:
        raise HTTPException(status_code=500, detail=result['error'])

    return UpdateResponse(
        success=result['success'],
        db_path=result['db_path'],
        end_date=result['end_date'],
        total_tables=result['total_tables'],
        success_count=result['success_count'],
        fail_count=result['fail_count'],
        total_added=result['total_added'],
        log_path=result['log_path'],
        details=result.get('details'),
    )


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
