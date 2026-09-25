"""圆桌会诊：三轮讨论（亮观点 -> 互评 -> 主持人裁决），以事件流形式产出。

供 server.py 的 SSE 接口消费；每个事件是一个 dict：
  init        参与模型列表
  round       新一轮开始（round: 1/2/3, title）
  delta       某模型的文本增量（round, model, text）
  model_done  某模型本轮说完（round, model, elapsed）
  model_error 某模型调用失败（round, model, message）
  verdict     主持人裁决全文已出（text）
  error       整体错误（message）
"""
from __future__ import annotations

import asyncio
import time

from client import OpenAICompatibleClient, ModelUnavailableError
from config import MODEL_KEYS, SUMMARY_MODEL

R1_PROMPT = (
    "你是圆桌讨论的一位嘉宾。请用不超过150字直接亮出你对问题的核心观点，"
    "只讲结论和最关键的理由，不要展开论证，不要客套。"
)
R2_PROMPT = (
    "这是圆桌讨论第二轮。下面是几位嘉宾的首轮观点。请用不超过150字回应："
    "指出你最不同意谁、理由是什么；如果谁的观点更好，直接承认并修正你的立场。"
    "不要重复自己首轮已经说过的内容。"
)
HOST_PROMPT = (
    "你是圆桌主持人。根据问题和全部讨论记录，给出裁决，总长不超过300字，格式严格如下：\n"
    "【共识】三位嘉宾一致认同的结论（没有就写「无共识」）\n"
    "【分歧】仍然存在的分歧点，各是谁持什么立场（没有就写「无」）\n"
    "【建议】你作为主持人认为提问者应该采纳的答案，一句话说清"
)


def _build_clients() -> dict[str, OpenAICompatibleClient]:
    clients = {}
    for k in MODEL_KEYS:
        try:
            clients[k] = OpenAICompatibleClient(k)
        except ModelUnavailableError:
            pass
    return clients


# 各轮最大输出 token：亮观点/互评限 150 字，主持人裁决 300 字。
# 需留足余量给「思考型模型」（如 Kimi K 系列会先输出 reasoning_content 再给答案），
# 故上限放宽；对 DeepSeek/GLM 而言这只是上限，实际仍受 prompt 字数约束。
ROUND_MAX_TOKENS = {1: 3000, 2: 3000, 3: 4000}


async def _stream_one(client: OpenAICompatibleClient, messages: list[dict],
                      rnd: int, queue: asyncio.Queue) -> tuple[str, str]:
    """流式调用一个模型，把增量事件丢进队列，返回 (model_key, 完整文本)。"""
    buf: list[str] = []
    start = time.perf_counter()
    try:
        async for delta in client.achat_stream(
                messages, temperature=0.3,
                max_tokens=ROUND_MAX_TOKENS.get(rnd, 500)):
            buf.append(delta)
            await queue.put({"type": "delta", "round": rnd,
                             "model": client.model_key, "text": delta})
        await queue.put({"type": "model_done", "round": rnd, "model": client.model_key,
                         "label": client.label,
                         "elapsed": round(time.perf_counter() - start, 2)})
    except Exception as e:  # noqa: BLE001 — 单模型失败不拖垮整场讨论
        print(f"[圆桌] {client.label} 第{rnd}轮失败：{e}")
        await queue.put({"type": "model_error", "round": rnd, "model": client.model_key,
                         "label": client.label, "message": str(e)})
    return client.model_key, "".join(buf)


async def _run_round(clients: list[OpenAICompatibleClient],
                     msgs_by_key: dict[str, list[dict]],
                     rnd: int, queue: asyncio.Queue) -> dict[str, str]:
    tasks = [asyncio.create_task(_stream_one(c, msgs_by_key[c.model_key], rnd, queue))
             for c in clients]
    results = await asyncio.gather(*tasks)
    return dict(results)


async def council_events(question: str, history: list[dict] | None = None):
    """async generator：依次产出圆桌三轮的事件。history 为会话历史（第一轮可见）。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            clients = _build_clients()
            if len(clients) < 2:
                await queue.put({"type": "error",
                                 "message": "圆桌会诊至少需要两个已配置 key 的模型，请先在「设置」里配置。"})
                return
            await queue.put({"type": "init", "models": [
                {"key": c.model_key, "label": c.label} for c in clients.values()]})

            # 第一轮：各自亮观点
            await queue.put({"type": "round", "round": 1,
                             "title": "第一轮 · 各自亮观点"})
            msgs1 = {k: [{"role": "system", "content": R1_PROMPT}]
                         + list(history or [])
                         + [{"role": "user", "content": question}] for k in clients}
            r1 = await _run_round(list(clients.values()), msgs1, 1, queue)

            # 第二轮：互评与修正（互相可见首轮观点）
            await queue.put({"type": "round", "round": 2,
                             "title": "第二轮 · 互评与修正"})
            views = "\n\n".join(f"【{clients[k].label}】{r1[k]}"
                                for k in clients if r1.get(k))
            msgs2 = {k: [{"role": "system", "content": R2_PROMPT},
                         {"role": "user", "content": f"问题：{question}\n\n首轮观点：\n{views}"}]
                     for k in clients}
            r2 = await _run_round(list(clients.values()), msgs2, 2, queue)

            # 第三轮：主持人裁决
            host = clients.get(SUMMARY_MODEL) or next(iter(clients.values()))
            await queue.put({"type": "round", "round": 3,
                             "title": f"第三轮 · 主持人裁决（{host.label}）"})
            debate = "\n\n".join(
                f"【{clients[k].label} 首轮】{r1.get(k, '')}\n"
                f"【{clients[k].label} 互评】{r2.get(k, '')}"
                for k in clients)
            msgs3 = {host.model_key: [
                {"role": "system", "content": HOST_PROMPT},
                {"role": "user", "content": f"问题：{question}\n\n{debate}"}]}
            r3 = await _run_round([host], msgs3, 3, queue)
            await queue.put({"type": "verdict", "text": r3.get(host.model_key, "")})
        except Exception as e:  # noqa: BLE001
            await queue.put({"type": "error", "message": f"圆桌会诊中断：{e}"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
    finally:
        await task
