# -*- coding: utf-8 -*-
"""换月移仓专用本地审计日志（与控制台分离，便于复盘）。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


class RolloverAuditLogger:
    """按日落盘文本日志；可选 JSON Lines。"""

    def __init__(self, config: Dict[str, Any]):
        self._enabled = bool(config.get("auto_roll_log_enabled", True))
        base_dir = config.get("auto_roll_log_dir")
        if not base_dir:
            base_dir = os.path.join(config.get("data_save_path", "./live_data"), "rollover_logs")
        self._dir = base_dir
        self._jsonl = bool(config.get("auto_roll_log_jsonl", False))
        self._date: Optional[str] = None
        self._text_fp = None
        self._json_fp = None

    def _ensure_open(self) -> None:
        if not self._enabled:
            return
        os.makedirs(self._dir, exist_ok=True)
        d = datetime.now().strftime("%Y%m%d")
        if d == self._date and self._text_fp:
            return
        self._date = d
        if self._text_fp:
            try:
                self._text_fp.close()
            except Exception:
                pass
        if self._json_fp:
            try:
                self._json_fp.close()
            except Exception:
                pass
            self._json_fp = None
        path = os.path.join(self._dir, f"rollover_{d}.log")
        self._text_fp = open(path, "a", encoding="utf-8")
        if self._jsonl:
            jpath = os.path.join(self._dir, f"rollover_{d}.jsonl")
            self._json_fp = open(jpath, "a", encoding="utf-8")

    def log(self, event: str, **fields: Any) -> None:
        if not self._enabled:
            return
        try:
            self._ensure_open()
        except Exception:
            return
        ts = datetime.now().isoformat(timespec="seconds")
        parts = [f"{k}={fields[k]}" for k in sorted(fields) if fields[k] is not None]
        line = f"{ts} [{event}] " + " ".join(parts)
        if self._text_fp:
            self._text_fp.write(line + "\n")
            self._text_fp.flush()
        if self._json_fp:
            rec: Dict[str, Any] = {"ts": ts, "event": event}
            rec.update(fields)
            self._json_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._json_fp.flush()

    def close(self) -> None:
        for fp in (self._text_fp, self._json_fp):
            if fp:
                try:
                    fp.close()
                except Exception:
                    pass
        self._text_fp = None
        self._json_fp = None
