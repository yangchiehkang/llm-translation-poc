#!/usr/bin/env bash
# 启动脚本：激活独立 venv，加载 .env，用 uvicorn 拉起 API。
# systemd 与手动启动共用本脚本。翻译逻辑不在这里，只负责把服务拉起来。
set -euo pipefail

# 项目根（api/deploy/run.sh 的上上上级）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

# 独立 venv（装在 /data 下，避免占用根分区）
VENV="${API_VENV:-/data/SERVICE_USER/translation-api/venv}"

# 加载 .env（本地手动启动用；systemd 走 EnvironmentFile，二者取值一致）
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_ROOT/.env"
  set +a
fi

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"
HOST="${HOST:-0.0.0.0}"
# 端口没有默认值：.env 是唯一权威来源。
# 写死过 `${PORT:-8188}`——两台机端口不同之后，任何一次 .env 漏配都会安静地
# 起在 8188 上：服务看起来是活的，但绑的不是对外转发的那个端口。宁可起不来。
PORT="${PORT:?PORT 未设置——请在 .env 中显式配置，本脚本不猜端口}"

exec "$VENV/bin/python" -m uvicorn api.main:app \
  --host "$HOST" --port "$PORT" \
  --workers "${UVICORN_WORKERS:-1}" \
  --log-level "${UVICORN_LOG_LEVEL:-info}"
