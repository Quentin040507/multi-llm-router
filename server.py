"""FastAPI 服务：网页窗口 + API。

启动（默认只监听本机 127.0.0.1，避免把 key 暴露到局域网）：
  python3 -m uvicorn server:app --host 127.0.0.1 --port 8000

然后浏览器打开 http://127.0.0.1:8000

接口：
  GET  /          -> 网页窗口（三模型路由系统.html）
  GET  /health    -> 健康检查
  GET  /config    -> 各模型 key 是否已配置
  POST /config    -> 保存/更新 key（写入 .env，立即生效，无需重启）
  POST /ask       -> 提问  body: {"question": "...", "mode": "route|all|vote"}
  POST /ask/stream-> 圆桌会诊（SSE 实时推送三轮讨论）
  POST /clear     -> 清空会话历史
  注：/ask 与 /ask/stream 均自动携带会话历史（最近 6 轮），并持久化到 .session.json，重启不丢。
"""
from __future__ import annotations

from pathlib import Path

import json

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config as cfg
from council import council_events
from modes import route_mode, all_mode, vote_mode

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="三模型路由系统")

# ---- 会话历史（持久化到 .session.json，重启不丢）----
HISTORY: list[dict] = []
MAX_HISTORY = 12  # 保留最近 6 轮对话，控制 token 开销
SESSION_FILE = BASE_DIR / ".session.json"


def _load_history() -> None:
    """启动时从磁盘恢复会话历史。"""
    global HISTORY
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            HISTORY = data if isinstance(data, list) else []
    except Exception:
        HISTORY = []


def _persist() -> None:
    """把当前历史写回磁盘（原子写，避免写一半损坏）。"""
    try:
        tmp = SESSION_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(HISTORY, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SESSION_FILE)
    except Exception:
        pass


def _remember(question: str, answer: str) -> None:
    HISTORY.append({"role": "user", "content": question})
    if answer:
        HISTORY.append({"role": "assistant", "content": answer})
    del HISTORY[:-MAX_HISTORY]
    _persist()


_load_history()


class AskRequest(BaseModel):
    question: str
    mode: str = "route"


class ConfigRequest(BaseModel):
    deepseek: str = ""
    glm: str = ""
    kimi: str = ""


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


@app.post("/clear")
def clear() -> dict:
    """清空会话历史（前端「清空」按钮同步调用）。"""
    HISTORY.clear()
    _persist()
    return {"status": "ok"}


@app.post("/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """圆桌会诊：SSE 实时推送三轮讨论过程（带会话历史）。"""
    async def gen():
        verdict = ""
        async for ev in council_events(req.question, history=list(HISTORY)):
            if ev.get("type") == "verdict":
                verdict = ev.get("text", "")
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if verdict:
            _remember(req.question, verdict)
        yield 'data: {"type": "end"}\n\n'

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    mode = req.mode.strip().lower()
    history = list(HISTORY)
    if mode == "all":
        result = all_mode(req.question, history=history)
    elif mode == "vote":
        result = vote_mode(req.question, history=history)
    else:
        result = route_mode(req.question, history=history)

    if result is None:
        return {"status": "error",
                "message": "没有可用模型。请先点右上角「设置」配置 API key。",
                "question": req.question, "mode": mode}

    # 把本轮问答记入会话历史
    if mode == "route":
        answer = result.get("answer", "")
    elif mode == "all":
        answer = (result.get("summary") or {}).get("text", "")
    else:  # vote
        answer = result.get("result") or ""
    _remember(req.question, answer)
    return {"status": "ok", "question": req.question, "mode": mode, "result": result}
