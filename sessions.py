"""多会话存储 + 历史记录，持久化到 .sessions.json。

会话结构：
  {"id": "...", "title": "...", "created_at": 0.0,
   "messages": [{"role": "user|assistant", "content": "...", "kind": "route|council|vote"}]}

kind 仅 assistant 消息携带，供前端回放历史时选择渲染样式：
route=普通回答卡，council=主持人裁决卡，vote=表决结论。
首次运行会把旧版单会话文件 .session.json 迁移为第一个会话。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORE_FILE = BASE_DIR / ".sessions.json"
LEGACY_FILE = BASE_DIR / ".session.json"

_sessions: dict[str, dict] = {}


def _persist() -> None:
    """原子写盘：写 .tmp 再 replace，避免写一半损坏。"""
    try:
        tmp = STORE_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"sessions": list(_sessions.values())}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(STORE_FILE)
    except Exception:
        pass


def _infer_kind(content: str) -> str:
    """从回答内容推断类型（旧数据无 kind 字段，迁移时兜底判断）。"""
    head = content[:40]
    if "【共识】" in head or "【分歧】" in head or "【建议】" in head:
        return "council"
    if "多数一致" in head or "无多数共识" in head or head.startswith("🎯"):
        return "vote"
    return "route"


def _migrate_legacy() -> None:
    """把旧版单会话 .session.json 迁移为第一个会话。"""
    try:
        if not LEGACY_FILE.exists():
            return
        data = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not data:
            return
        msgs = []
        for m in data:
            if not isinstance(m, dict):
                continue
            role = m.get("role") or "user"
            item = {"role": role, "content": m.get("content", "")}
            if role == "assistant":
                item["kind"] = m.get("kind") or _infer_kind(m.get("content", ""))
            msgs.append(item)
        if not msgs:
            return
        title = "旧会话"
        for m in msgs:
            if m["role"] == "user" and m["content"]:
                c = m["content"]
                title = c[:20] + ("…" if len(c) > 20 else "")
                break
        sid = uuid.uuid4().hex[:12]
        _sessions[sid] = {"id": sid, "title": title, "created_at": time.time(), "messages": msgs}
        _persist()
        LEGACY_FILE.rename(LEGACY_FILE.with_suffix(".json.migrated"))
    except Exception:
        pass


def _load() -> None:
    global _sessions
    try:
        if STORE_FILE.exists():
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sessions"), list):
                for s in data["sessions"]:
                    if isinstance(s, dict) and s.get("id"):
                        _sessions[s["id"]] = s
                return
    except Exception:
        _sessions = {}
    _migrate_legacy()


def new_session() -> dict:
    """新建会话，返回会话对象。"""
    sid = uuid.uuid4().hex[:12]
    s = {"id": sid, "title": "新会话", "created_at": time.time(), "messages": []}
    _sessions[sid] = s
    _persist()
    return s


def list_sessions() -> list[dict]:
    """会话列表（不含消息内容），按创建时间倒序。"""
    items = [
        {"id": s["id"], "title": s["title"], "created_at": s["created_at"],
         "count": len(s["messages"])}
        for s in _sessions.values()
    ]
    items.sort(key=lambda x: -x["created_at"])
    return items


def get_session(sid: str) -> dict | None:
    return _sessions.get(sid)


def get_history(sid: str) -> list[dict]:
    """某会话的完整消息历史（用于前端回放）。"""
    s = _sessions.get(sid)
    return list(s["messages"]) if s else []


def get_context(sid: str, limit: int = 12) -> list[dict]:
    """某会话最近 limit 条消息（用于作为模型上下文，不含 kind 字段）。"""
    s = _sessions.get(sid)
    if not s:
        return []
    return [{"role": m["role"], "content": m["content"]} for m in s["messages"][-limit:]]


def append_turn(sid: str, question: str, answer: str, kind: str) -> None:
    """给某会话追加一轮问答；首条问题自动作为会话标题。"""
    s = _sessions.get(sid)
    if not s:
        return
    if not s["messages"]:
        s["title"] = question[:20] + ("…" if len(question) > 20 else "")
    s["messages"].append({"role": "user", "content": question})
    if answer:
        s["messages"].append({"role": "assistant", "content": answer, "kind": kind})
    _persist()


def delete_session(sid: str) -> bool:
    if sid in _sessions:
        del _sessions[sid]
        _persist()
        return True
    return False


_load()
