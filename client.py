"""OpenAI 兼容客户端：统一封装三家 API，仅 base_url / api_key / model 不同。

提供同步 / 异步 / 流式三种调用方式，统一返回 Response 结构。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Iterator

import httpx

import config as cfg


class ModelUnavailableError(Exception):
    """模型无 key 或调用失败时抛出，供上层做降级。"""


def estimate_tokens(text: str) -> int:
    """无 usage 字段时的粗略 token 估算。

    规则：CJK 汉字 1 字 ≈ 1 token，其余字符约 4 字符 ≈ 1 token。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk + (len(text) - cjk + 3) // 4


@dataclass
class Response:
    """一次回答的完整结果。"""
    model_key: str = ""
    label: str = ""
    text: str = ""
    elapsed: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class OpenAICompatibleClient:
    def __init__(self, model_key: str):
        meta = cfg.MODELS[model_key]
        self.model_key = model_key
        self.label = meta["label"]
        self.base_url = meta["base_url"].rstrip("/")
        self.model = meta["model"]
        self.api_key = cfg.api_key(model_key) or ""
        if not self.api_key:
            raise ModelUnavailableError(
                f"{self.label} 未配置 API key（请在 .env 中设置 {meta['api_key_env']}）"
            )

    @property
    def endpoint(self) -> str:
        # DeepSeek / GLM / Kimi 三家均在 base_url 下追加 /chat/completions
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, messages, temperature=0.0, max_tokens=None, stream=False) -> dict:
        fixed = cfg.MODELS[self.model_key].get("temperature_fixed")
        if fixed is not None:
            temperature = fixed  # 推理模型（如 Kimi K 系列）锁定 temperature
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        return payload

    def _parse(self, data: dict, resp: Response) -> None:
        resp.text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = data.get("usage") or {}
        resp.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        resp.completion_tokens = int(usage.get("completion_tokens") or 0)
        if not resp.completion_tokens:  # 部分 provider 不回 usage，退回估算
            resp.completion_tokens = estimate_tokens(resp.text)

    # ---- 同步（非流式）----
    def chat(self, messages, temperature=0.0, max_tokens=None) -> Response:
        resp = Response(model_key=self.model_key, label=self.label)
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                r = client.post(self.endpoint, headers=self._headers(),
                                json=self._payload(messages, temperature, max_tokens))
                if r.status_code != 200:
                    raise ModelUnavailableError(
                        f"{self.label} 调用失败 HTTP {r.status_code}：{r.text[:200]}"
                    )
                try:
                    self._parse(r.json(), resp)
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    raise ModelUnavailableError(f"{self.label} 响应解析失败：{e}") from e
        except httpx.HTTPError as e:
            raise ModelUnavailableError(f"{self.label} 网络/调用异常：{e}") from e
        resp.elapsed = time.perf_counter() - start
        return resp

    # ---- 同步（流式）----
    def chat_stream(self, messages, temperature=0.0) -> Iterator[str]:
        """逐段 yield 文本增量，供上层边收边打印。"""
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                with client.stream(
                    "POST", self.endpoint, headers=self._headers(),
                    json=self._payload(messages, temperature, stream=True),
                ) as r:
                    if r.status_code != 200:
                        body = "".join(r.iter_text())
                        raise ModelUnavailableError(
                            f"{self.label} 调用失败 HTTP {r.status_code}：{body[:200]}"
                        )
                    for line in r.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("content"):
                            yield delta["content"]
        except httpx.HTTPError as e:
            raise ModelUnavailableError(f"{self.label} 网络/调用异常：{e}") from e

    # ---- 异步（流式）----
    async def achat_stream(self, messages, temperature=0.0, max_tokens=None):
        """异步逐段 yield 文本增量（async generator），供 SSE 实时推送。

        容错：connect 超时放宽到 20s；若在产出任何内容之前就失败（连接抖动、
        限流 429、解析失败），自动重试一次，避免偶发抖动被当成「调用失败」。
        """
        produced = False
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(
                        timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                    async with client.stream(
                        "POST", self.endpoint, headers=self._headers(),
                        json=self._payload(messages, temperature, max_tokens, stream=True),
                    ) as r:
                        if r.status_code != 200:
                            body = ""
                            async for chunk in r.aiter_text():
                                body += chunk
                            raise ModelUnavailableError(
                                f"{self.label} 调用失败 HTTP {r.status_code}：{body[:200]}"
                            )
                        async for line in r.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[len("data:"):].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                            if delta.get("content"):
                                produced = True
                                yield delta["content"]
                return
            except ModelUnavailableError as e:
                if produced or attempt == 2:
                    raise
            except httpx.HTTPError as e:
                if produced or attempt == 2:
                    raise ModelUnavailableError(
                        f"{self.label} 网络/调用异常：{e}") from e
            await asyncio.sleep(0.6)

    # ---- 异步（非流式）----
    async def achat(self, messages, temperature=0.0, max_tokens=None) -> Response:
        resp = Response(model_key=self.model_key, label=self.label)
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                r = await client.post(self.endpoint, headers=self._headers(),
                                      json=self._payload(messages, temperature, max_tokens))
                if r.status_code != 200:
                    raise ModelUnavailableError(
                        f"{self.label} 调用失败 HTTP {r.status_code}：{r.text[:200]}"
                    )
                try:
                    self._parse(r.json(), resp)
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    raise ModelUnavailableError(f"{self.label} 响应解析失败：{e}") from e
        except httpx.HTTPError as e:
            raise ModelUnavailableError(f"{self.label} 网络/调用异常：{e}") from e
        resp.elapsed = time.perf_counter() - start
        return resp
