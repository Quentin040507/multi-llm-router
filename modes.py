"""三种模式：智能路由 / 三模型对比 / 举手表决。"""
from __future__ import annotations

import asyncio
import re
import time

from client import OpenAICompatibleClient, ModelUnavailableError, Response, estimate_tokens
from config import MODELS, MODEL_KEYS, CLASSIFIER_MODEL, SUMMARY_MODEL
from history import log_entry
from router import route

LABEL_CN = {
    "code_math": "代码/数学",
    "chinese_writing": "中文写作",
    "general": "通用",
}


def _make_client(model_key: str) -> OpenAICompatibleClient | None:
    try:
        return OpenAICompatibleClient(model_key)
    except ModelUnavailableError as e:
        print(f"[提示] {e}")
        return None


def print_stats(resp: Response) -> None:
    print(f"[{resp.label}] 耗时 {resp.elapsed:.2f}s | 输入 {resp.prompt_tokens} tokens | 输出 {resp.completion_tokens} tokens")


def _user_messages(question: str) -> list[dict]:
    return [{"role": "user", "content": question}]


def _messages(history: list[dict] | None, question: str) -> list[dict]:
    """对话历史 + 当前问题（历史由服务端会话维护）。"""
    return list(history or []) + [{"role": "user", "content": question}]


def _stream_answer(client: OpenAICompatibleClient, messages: list[dict]) -> Response:
    buf: list[str] = []
    start = time.perf_counter()
    for delta in client.chat_stream(messages):
        print(delta, end="", flush=True)
        buf.append(delta)
    elapsed = time.perf_counter() - start
    print()
    text = "".join(buf)
    in_tokens = estimate_tokens("".join(m.get("content", "") for m in messages))
    return Response(model_key=client.model_key, label=client.label, text=text,
                    elapsed=elapsed, prompt_tokens=in_tokens,
                    completion_tokens=estimate_tokens(text))


def route_mode(question: str, stream: bool = False, force_model: str | None = None,
               history: list[dict] | None = None) -> dict | None:
    """智能路由（默认）：分类 -> 选模型 -> 作答，失败自动降级。"""
    selected = force_model
    label = "forced"
    source = "user"
    if force_model:
        print(f"[路由] 用户强制指定模型：{MODELS[force_model]['label']}")
    else:
        classifier = _make_client(CLASSIFIER_MODEL)
        label, source, selected, elapsed = route(question, classifier)
        print(f"[路由] 分类={label}({LABEL_CN.get(label, label)}) 来源={source} "
              f"选中={MODELS[selected]['label']} 分类耗时={elapsed:.2f}s")

    messages = _messages(history, question)
    order = [selected] + [k for k in MODEL_KEYS if k != selected]
    last_err = None
    for k in order:
        client = _make_client(k)
        if client is None:
            continue
        if k != selected:
            print(f"[降级] {MODELS[selected]['label']} 不可用，改用 {MODELS[k]['label']}。")
        try:
            header = "=== " + client.label + " 回答" + ("（流式）" if stream else "") + " ===\n"
            print(f"\n{header}")
            if stream:
                resp = _stream_answer(client, messages)
            else:
                resp = client.chat(messages)
                print(resp.text)
            print_stats(resp)
            log_entry({
                "mode": "route", "question": question, "route_label": label,
                "route_source": source, "selected_model": selected,
                "used_model": client.model_key, "elapsed": round(resp.elapsed, 3),
                "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens,
            })
            return {"mode": "route", "model": client.model_key, "model_label": client.label,
                    "label": label, "answer": resp.text,
                    "elapsed": round(resp.elapsed, 3),
                    "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens}
        except ModelUnavailableError as e:
            print(f"[降级] {client.label} 调用失败：{e}")
            last_err = e
            continue
    print(f"[错误] 所有可用模型调用均失败：{last_err}")
    return None


def all_mode(question: str, history: list[dict] | None = None) -> dict | None:
    """三模型对比：三路并行回答 + DeepSeek 综合点评。"""
    print(f"\n=== 三模型并行回答 ===\n问题：{question}\n")
    clients = {}
    for k in MODEL_KEYS:
        c = _make_client(k)
        if c:
            clients[k] = c
    if not clients:
        print("[错误] 没有可用模型，无法对比。")
        return None

    messages = _messages(history, question)

    async def _run():
        async def _call(k, c):
            try:
                return k, await c.achat(messages)
            except Exception as e:  # noqa: BLE001
                return k, Response(model_key=k, label=MODELS[k]["label"],
                                   text=f"[调用失败] {e}", error=str(e))
        return await asyncio.gather(*(_call(k, c) for k, c in clients.items()))

    results = dict(asyncio.run(_run()))

    for k in MODEL_KEYS:
        if k not in results:
            continue
        resp = results[k]
        print(f"\n===== {resp.label} =====\n{resp.text}")
        print_stats(resp)

    # 综合点评：优先 DeepSeek，缺失则降级到任意可用模型
    summary_client = _make_client(SUMMARY_MODEL) or next(iter(clients.values()))
    if summary_client.model_key != SUMMARY_MODEL:
        print(f"\n[提示] DeepSeek 不可用，改用 {summary_client.label} 做综合点评。")

    combined = "\n\n".join(f"【{results[k].label}】\n{results[k].text}" for k in results)
    summary_msgs = [
        {"role": "system", "content":
            "你是资深评审专家。下面是三个模型对同一问题的回答。请逐个点评：指出每个回答各自的优势与遗漏，然后给出一个合并后的最佳答案。"},
        {"role": "user", "content": f"问题：{question}\n\n{combined}"},
    ]
    print(f"\n===== 综合点评（{summary_client.label}）=====\n")
    try:
        sresp = summary_client.chat(summary_msgs, temperature=0.3)
        print(sresp.text)
        print_stats(sresp)
        summary_text = sresp.text
    except ModelUnavailableError as e:
        print(f"[综合点评失败] {e}")
        summary_text = ""

    log_entry({
        "mode": "all", "question": question,
        "answers": {k: {"elapsed": round(results[k].elapsed, 3),
                        "prompt_tokens": results[k].prompt_tokens,
                        "completion_tokens": results[k].completion_tokens} for k in results},
        "summary_model": summary_client.model_key,
    })
    answers = {
        k: {"label": results[k].label, "text": results[k].text,
            "elapsed": round(results[k].elapsed, 3),
            "prompt_tokens": results[k].prompt_tokens,
            "completion_tokens": results[k].completion_tokens,
            "error": results[k].error}
        for k in results
    }
    return {"mode": "all", "answers": answers,
            "summary": {"model_label": summary_client.label, "text": summary_text}}


def extract_conclusion(text: str) -> str:
    """提取模型输出里的「最终答案」；找不到则退回最后一行非空文本。"""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        m = re.search(r"最终答案[:：]\s*(.+)", line)
        if m:
            return m.group(1).strip()
    m = re.search(r"最终答案[:：]\s*(.+)", text or "")
    if m:
        return m.group(1).strip()
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def vote_mode(question: str, history: list[dict] | None = None) -> dict | None:
    """举手表决：三模型独立回答客观题，按最终结论多数投票。"""
    print(f"\n=== 举手表决模式 ===\n问题：{question}\n")
    clients = {}
    for k in MODEL_KEYS:
        c = _make_client(k)
        if c:
            clients[k] = c
    if not clients:
        print("[错误] 没有可用模型，无法表决。")
        return None

    messages = [
        {"role": "system", "content":
            "你是答题助手。请独立回答下面的客观题（选择题/判断题）。回答后，在最后单独一行以固定格式给出你的最终结论：\n最终答案：<你的结论>"},
    ] + _messages(history, question)

    async def _run():
        async def _call(k, c):
            try:
                return k, await c.achat(messages)
            except Exception as e:  # noqa: BLE001
                return k, Response(model_key=k, label=MODELS[k]["label"],
                                   text=f"[调用失败] {e}", error=str(e))
        return await asyncio.gather(*(_call(k, c) for k, c in clients.items()))

    results = dict(asyncio.run(_run()))

    conclusions: dict[str, str] = {}
    for k in MODEL_KEYS:
        if k not in results:
            continue
        resp = results[k]
        print(f"\n===== {resp.label} 回答 =====\n{resp.text}")
        print_stats(resp)
        concl = extract_conclusion(resp.text)
        conclusions[k] = concl
        print(f"[结论] {resp.label}: {concl or '(未提取到)'}")

    valid = {k: c for k, c in conclusions.items() if c}
    total = len(valid)
    if total == 0:
        print("\n[表决结果] 未能提取到任何结论，请用更明确的客观题提问。")
        return None

    tally: dict[str, list[str]] = {}
    for k, c in valid.items():
        tally.setdefault(c, []).append(k)

    top_ans, top_voters = sorted(tally.items(), key=lambda kv: -len(kv[1]))[0]
    top_count = len(top_voters)

    if top_count > total - top_count:
        conf = top_count / total
        print(f"\n[表决结果] 多数一致：{top_ans}（{top_count}/{total} 票，置信度 {conf:.0%}）")
        if top_count < total:
            minority = "；".join(f"{MODELS[k]['label']}: {conclusions[k]}"
                                 for k in valid if conclusions[k] != top_ans)
            print(f"[分歧详情] 少数意见：{minority}")
        result = top_ans
    else:
        print("\n[表决结果] 无多数共识，存在分歧：")
        for k in valid:
            print(f"  - {MODELS[k]['label']}: {conclusions[k]}")
        result = None

    log_entry({"mode": "vote", "question": question,
               "conclusions": {MODELS[k]['label']: c for k, c in conclusions.items()},
               "result": result})
    answers = {
        k: {"label": results[k].label, "text": results[k].text,
            "conclusion": conclusions.get(k, ""), "error": results[k].error}
        for k in results
    }
    return {"mode": "vote", "answers": answers, "result": result,
            "confident": result is not None}
