"""冒烟测试：不依赖真实 key，验证路由逻辑与解析（mock 分类结果和 API 响应）。

运行：
  python3 test_smoke.py
"""
from __future__ import annotations

import sys
from unittest import mock

from router import parse_label, keyword_classify, route, classify
from config import LABEL_TO_MODEL


def test_parse_label_pure():
    assert parse_label("code_math") == "code_math"
    assert parse_label('"chinese_writing"') == "chinese_writing"
    assert parse_label('{"label": "general"}') == "general"
    assert parse_label("嗯，这应该是代码问题：code_math。") == "code_math"
    assert parse_label("随便说点别的") is None


def test_keyword_classify():
    assert keyword_classify("帮我用Python写一个快速排序") == "code_math"
    assert keyword_classify("帮我写一条小红书风格的奶茶店开业文案") == "chinese_writing"
    assert keyword_classify("介绍一下中国的四大发明") == "general"


def test_label_mapping():
    assert LABEL_TO_MODEL["code_math"] == "deepseek"
    assert LABEL_TO_MODEL["chinese_writing"] == "qwen"
    assert LABEL_TO_MODEL["general"] == "kimi"


def test_route_keyword_fallback_without_classifier():
    label, source, model, _ = route("写一段产品介绍文案", classifier_client=None)
    assert label == "chinese_writing"
    assert source == "keyword"
    assert model == "qwen"


def test_route_uses_qwen_classifier_when_available():
    fake = mock.MagicMock()
    fake.chat.return_value = mock.MagicMock(text="code_math")
    label, source, model, _ = route("帮我写个排序算法", classifier_client=fake)
    assert label == "code_math"
    assert source == "qwen"
    assert model == "deepseek"


def test_classify_retries_on_bad_parse_then_qwen():
    fake = mock.MagicMock()
    fake.chat.side_effect = [mock.MagicMock(text="我也不知道算哪个"), mock.MagicMock(text="general")]
    label, source, _ = classify("今天天气怎么样", classifier_client=fake)
    assert label == "general"
    assert source == "qwen"
    assert fake.chat.call_count == 2


def test_classify_keyword_when_classifier_raises():
    from client import ModelUnavailableError
    fake = mock.MagicMock()
    fake.chat.side_effect = ModelUnavailableError("boom")
    label, source, _ = classify("帮我写个函数", classifier_client=fake)
    assert label == "code_math"
    assert source == "keyword"


def test_route_mode_degrades_when_selected_model_fails():
    """选中的模型调用失败（如填错 key 返回 401）时，自动降级到下一个可用模型。"""
    import modes
    from client import ModelUnavailableError, Response

    labels = {"deepseek": "DeepSeek", "qwen": "Qwen", "kimi": "Kimi"}

    def fake_make(model_key):
        c = mock.MagicMock()
        c.model_key = model_key
        c.label = labels[model_key]
        if model_key == "deepseek":
            c.chat.side_effect = ModelUnavailableError("HTTP 401 Unauthorized")
        else:
            c.chat.return_value = Response(model_key=model_key, label=c.label, text="答案",
                                           elapsed=0.1, prompt_tokens=5, completion_tokens=2)
        return c

    with mock.patch.object(modes, "_make_client", side_effect=fake_make), \
         mock.patch.object(modes, "log_entry", return_value=None):
        result = modes.route_mode("帮我写个排序", stream=False)

    assert result is not None
    assert result["model"] == "qwen"  # DeepSeek 失败 -> 降级到 Qwen


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
