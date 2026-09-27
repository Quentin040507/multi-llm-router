"""配置：模型注册表、环境变量加载、路由标签映射。

所有与「三家模型」相关的可调项都集中在这里：
新增 / 更换模型只需改 MODELS（见 README「如何更换/新增模型」）。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ---- .env 加载（优先 python-dotenv，缺失时手动解析兜底）----
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # 未安装 python-dotenv 时的轻量兜底
    _env_file = BASE_DIR / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


# ---- 模型注册表 ----
# 三家均为 OpenAI 兼容接口，仅 base_url / api_key / model 不同。
MODELS = {
    "deepseek": {
        "name": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "description": "代码、数学、逻辑推理",
    },
    "qwen": {
        "name": "qwen",
        "label": "Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "description": "中文写作、文案、代码辅助、多语言",
    },
    "kimi": {
        "name": "kimi",
        "label": "Kimi",
        "base_url": os.getenv(
            "KIMI_BASE_URL",
            "https://api.moonshot.cn/v1",
        ),
        "model": "kimi-k2.7-code-highspeed",
        "api_key_env": "MOONSHOT_API_KEY",
        "description": "通用对话、长文理解、多语言",
        "temperature_fixed": 1,  # Kimi K 系列为推理模型，仅接受 temperature=1
    },
}

MODEL_KEYS = tuple(MODELS.keys())  # ("deepseek", "qwen", "kimi")

# ---- 路由标签 -> 模型 ----
LABEL_TO_MODEL = {
    "code_math": "deepseek",
    "chinese_writing": "qwen",
    "general": "kimi",
}

# 分类器使用 Qwen；综合点评使用 DeepSeek
CLASSIFIER_MODEL = "qwen"
SUMMARY_MODEL = "deepseek"


def api_key(model_key: str) -> str | None:
    """读取指定模型的 API key，缺失/为空返回 None。"""
    key = os.getenv(MODELS[model_key]["api_key_env"], "").strip()
    return key or None


def available_models() -> list[str]:
    """返回所有已配置 key 的模型标识（用于降级判断）。"""
    return [k for k in MODEL_KEYS if api_key(k)]


def key_status() -> dict[str, bool]:
    """返回各模型 key 是否已配置（布尔），供网页窗口展示。"""
    return {k: bool(api_key(k)) for k in MODEL_KEYS}


# 模型标识 -> .env 变量名
_ENV_FIELD_MAP = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
}


def save_api_keys(keys: dict[str, str]) -> None:
    """把非空 key 写入 .env 并同步到当前进程环境变量，立即生效（无需重启）。

    传空字符串表示「不修改」该模型，保留原值。
    """
    env_file = BASE_DIR / ".env"
    existing: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()

    for field, env_var in _ENV_FIELD_MAP.items():
        val = (keys.get(field) or "").strip()
        if val:
            existing[env_var] = val
            os.environ[env_var] = val

    env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n",
                        encoding="utf-8")
