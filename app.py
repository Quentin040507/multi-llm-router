"""CLI 入口。

用法：
  python app.py "我的问题"                      # 智能路由（默认）
  python app.py "问题" --mode all               # 三模型对比
  python app.py "问题" --mode vote              # 举手表决
  python app.py "问题" --model deepseek         # 强制指定模型
  python app.py "问题" --stream                 # 流式输出（路由模式）
"""
from __future__ import annotations

import argparse
import sys

from modes import route_mode, all_mode, vote_mode


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="三模型分工协作的 LLM 智能路由系统（DeepSeek / GLM / Kimi）",
    )
    parser.add_argument("question", nargs="+", help="要提问的问题")
    parser.add_argument("--mode", choices=["route", "all", "vote"], default="route",
                        help="运行模式：route=智能路由(默认) all=三模型对比 vote=举手表决")
    parser.add_argument("--model", choices=["deepseek", "glm", "kimi"],
                        help="强制指定模型（仅 route 模式有效）")
    parser.add_argument("--stream", action="store_true", help="流式输出（仅 route 模式有效）")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        parser.error("问题不能为空")

    if args.mode != "route" and (args.model or args.stream):
        print("[提示] --model / --stream 仅在 route 模式下生效，已忽略。")

    if args.mode == "all":
        result = all_mode(question)
    elif args.mode == "vote":
        result = vote_mode(question)
    else:
        result = route_mode(question, stream=args.stream, force_model=args.model)

    if result is None:  # 全部模型不可用
        sys.exit(1)


if __name__ == "__main__":
    main()
