"""本地日志：把每次请求追加到 logs/history.jsonl（每行一条 JSON）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import BASE_DIR

LOG_PATH = BASE_DIR / "logs" / "history.jsonl"


def log_entry(record: dict) -> None:
    """写入一条日志，自动补时间戳。失败仅提示，不影响主流程。"""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **record}
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[日志] 写入失败：{e}")
