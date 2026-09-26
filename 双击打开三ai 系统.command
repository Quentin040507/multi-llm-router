#!/bin/bash
# 双击本文件即可打开网页窗口。
# 首次双击若被 macOS 拦截，请右键 -> 打开。
cd "$(dirname "$0")" || exit 1

# Python 解释器：环境变量 PYTHON > WorkBuddy 托管 Python > 系统 python3
if [ -n "$PYTHON" ]; then
  PY="$PYTHON"
elif [ -x "$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3" ]; then
  PY="$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "未找到可用的 Python，请先安装 Python 3.10+ 并安装依赖。"
  exit 1
fi
PORT=8000

# 若端口已被占用，说明服务可能已在运行，直接打开浏览器
if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "端口 $PORT 已被占用（可能已在运行），直接打开浏览器。"
  open "http://127.0.0.1:$PORT"
  exit 0
fi

# 2 秒后自动打开浏览器
(sleep 2 && open "http://127.0.0.1:$PORT") &

echo "三模型路由系统 启动中…"
echo "稍后会自动打开浏览器：http://127.0.0.1:$PORT"
echo "关闭本窗口即停止服务。"
"$PY" -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
