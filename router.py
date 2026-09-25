"""路由：GLM 分类 + 本地关键词兜底。

分类优先用最便宜的 GLM-4-Flash，只让它输出一个标签；
解析失败重试一次，仍失败或调用异常时退回本地关键词规则。
"""
from __future__ import annotations

import json
import re
import time

from client import ModelUnavailableError
from config import LABEL_TO_MODEL

VALID_LABELS = {"code_math", "chinese_writing", "general"}

CLASSIFY_SYSTEM_PROMPT = (
    "你是一个问题分类器。判断用户问题属于哪个领域，只输出一个标签，"
    "不要输出任何其他内容、解释或标点。\n"
    "可选标签：\n"
    "- code_math：代码、编程、数学、逻辑推理、算法、公式、证明、计算、调试\n"
    "- chinese_writing：中文写作、文案、标题、润色、改写、邮件、总结、办公文档\n"
    "- general：其他所有问题（通用知识、翻译、多语言、长文理解、生活常识等）\n"
    "只输出上述三个标签之一。"
)

# ---- 本地关键词规则（分类器失败时兜底）----
CODE_MATH_WORDS = (
    "代码", "函数", "bug", "程序", "编程", "算法", "数学", "证明", "计算",
    "排序", "sql", "python", "正则", "调试", "报错", "接口", "api", "代码",
    "爬虫", "脚本", "递归", "复杂度", "数据结构",
)
CHINESE_WRITING_WORDS = (
    "写", "文案", "标题", "润色", "邮件", "总结", "改写", "演讲稿", "周报",
    "日报", "朋友圈", "小红书", "公众号", "介绍信", "求职信", "宣传语", "口号",
)


def keyword_classify(question: str) -> str:
    q = question.lower()
    for w in CODE_MATH_WORDS:  # 代码/数学优先判断，避免「写代码」误判为写作
        if w in q:
            return "code_math"
    for w in CHINESE_WRITING_WORDS:
        if w in q:
            return "chinese_writing"
    return "general"


def parse_label(text: str) -> str | None:
    """从分类器输出中解析标签，容忍 JSON / 引号 / 多余文字。解析不出返回 None。"""
    t = (text or "").strip()
    if t in VALID_LABELS:
        return t
    t = t.strip('"').strip("'").strip("`").strip()
    if t in VALID_LABELS:
        return t
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            for key in ("label", "category", "tag", "result", "answer"):
                if isinstance(obj.get(key), str) and obj[key].strip() in VALID_LABELS:
                    return obj[key].strip()
        elif isinstance(obj, str):
            return parse_label(obj)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"(code_math|chinese_writing|general)", t)
    return m.group(1) if m else None


def classify(question: str, classifier_client=None) -> tuple[str, str, float]:
    """返回 (标签, 来源, 耗时)。来源为 'glm' 或 'keyword'。"""
    start = time.perf_counter()
    label = None
    source = "keyword"
    if classifier_client is not None:
        msgs = [
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        for _ in (1, 2):  # 解析失败最多重试一次
            try:
                resp = classifier_client.chat(msgs, temperature=0.0)
                label = parse_label(resp.text)
                if label is not None:
                    source = "glm"
                    break
            except ModelUnavailableError:
                break  # 分类器不可用，直接走关键词
    if label is None:
        label = keyword_classify(question)
    elapsed = time.perf_counter() - start
    return label, source, elapsed


def route(question: str, classifier_client=None) -> tuple[str, str, str, float]:
    """返回 (标签, 来源, 选中模型 key, 耗时)。"""
    label, source, elapsed = classify(question, classifier_client)
    model_key = LABEL_TO_MODEL[label]
    return label, source, model_key, elapsed
