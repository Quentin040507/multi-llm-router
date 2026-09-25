"""FastAPI 服务：网页窗口 + API。

启动（默认只监听本机 127.0.0.1，避免把 key 暴露到局域网）：
  python3 -m uvicorn server:app --host 127.0.0.1 --port 8000

然后浏览器打开 http://127.0.0.1:8000

接口：
  GET  /                       -> 网页窗口（三模型路由系统.html）
  GET  /health                 -> 健康检查
  GET  /config                 -> 各模型 key 是否已配置
  POST /config                 -> 保存/更新 key（写入 .env，立即生效，无需重启）
  GET  /sessions               -> 会话列表
  POST /sessions/new           -> 新建会话
  GET  /sessions/{sid}         -> 某会话完整历史
  POST /sessions/{sid}/delete  -> 删除某会话
  POST /ask                    -> 提问  body: {"question","mode","session_id"}
  POST /ask/stream             -> 圆桌会诊（SSE 实时推送），带 session_id
  注：提问均携带所属会话，会话历史持久化到 .sessions.json，重启不丢。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config as cfg
import sessions as store
from council import council_events
from modes import route_mode, all_mode, vote_mode

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="三模型路由系统")

MAX_CONTEXT = 12  # 每个会话传给模型最近 6 轮，控制 token 开销


class AskRequest(BaseModel):
    question: str
    mode: str = "route"
    session_id: str = ""


class ConfigRequest(BaseModel):
    deepseek: str = ""
    glm: str = ""
    kimi: str = ""


def _resolve_session(sid: str) -> str:
    """拿到有效会话 id：为空或不存在则新建。"""
    if sid and store.get_session(sid):
        return sid
    return store.new_session()["id"]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "三模型路由系统.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/config")
def get_config() -> dict:
    return {"keys": cfg.key_status()}


@app.post("/config")
def set_config(req: ConfigRequest) -> dict:
    cfg.save_api_keys({"deepseek": req.deepseek, "glm": req.glm, "kimi": req.kimi})
    return {"keys": cfg.key_status()}


# ---- 会话管理 ----

@app.get("/sessions")
def list_sessions() -> dict:
    return {"sessions": store.list_sessions()}


@app.post("/sessions/new")
def create_session() -> dict:
    return {"session": store.new_session()}


@app.get("/sessions/{sid}")
def get_session(sid: str) -> dict:
    if not store.get_session(sid):
        return {"status": "error", "message": "会话不存在"}
    return {"messages": store.get_history(sid)}


@app.post("/sessions/{sid}/delete")
def delete_session(sid: str) -> dict:
    store.delete_session(sid)
    return {"status": "ok"}


# ---- 提问 ----

@app.post("/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """圆桌会诊：SSE 实时推送三轮讨论过程（带所属会话历史）。"""
    sid = _resolve_session(req.session_id)
    history = store.get_context(sid, MAX_CONTEXT)

    async def gen():
        verdict = ""
        labels: dict[str, str] = {}
        rounds: dict[int, dict] = {}
        yield f"data: {json.dumps({'type': 'session', 'id': sid}, ensure_ascii=False)}\n\n"
        async for ev in council_events(req.question, history=history):
            t = ev.get("type")
            if t == "init":
                for m in ev.get("models", []):
                    labels[m["key"]] = m["label"]
            elif t == "round":
                rnd = ev["round"]
                rounds[rnd] = {"title": ev.get("title", ""), "seats": {}}
            elif t == "delta":
                rnd, model = ev["round"], ev["model"]
                rounds.setdefault(rnd, {"title": "", "seats": {}})
                seat = rounds[rnd]["seats"].setdefault(
                    model, {"label": labels.get(model, model), "text": "", "error": ""})
                seat["text"] += ev.get("text", "")
            elif t == "model_error":
                rnd, model = ev["round"], ev["model"]
                rounds.setdefault(rnd, {"title": "", "seats": {}})
                seat = rounds[rnd]["seats"].setdefault(
                    model, {"label": labels.get(model, model), "text": "", "error": ""})
                seat["error"] = ev.get("message", "")
            elif t == "verdict":
                verdict = ev.get("text", "")
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if verdict:
            debate = [
                {"round": rnd, "title": r["title"],
                 "seats": [{"model": k, "label": v["label"],
                            "text": v["text"], "error": v["error"]}
                           for k, v in r["seats"].items()]}
                for rnd, r in sorted(rounds.items())
            ]
            store.append_turn(sid, req.question, verdict, "council", debate=debate)
        yield 'data: {"type": "end"}\n\n'

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    mode = req.mode.strip().lower()
    sid = _resolve_session(req.session_id)
    history = store.get_context(sid, MAX_CONTEXT)

    if mode == "all":
        result = all_mode(req.question, history=history)
        kind = "council"
    elif mode == "vote":
        result = vote_mode(req.question, history=history)
        kind = "vote"
    else:
        result = route_mode(req.question, history=history)
        kind = "route"

    if result is None:
        return {"status": "error",
                "message": "没有可用模型。请先点右上角「设置」配置 API key。",
                "question": req.question, "mode": mode, "session_id": sid}

    # 把本轮问答记入所属会话
    if mode == "route":
        answer = result.get("answer", "")
    elif mode == "all":
        answer = (result.get("summary") or {}).get("text", "")
    else:  # vote
        answer = result.get("result") or ""
    store.append_turn(sid, req.question, answer, kind)
    return {"status": "ok", "question": req.question, "mode": mode,
            "session_id": sid, "result": result}
