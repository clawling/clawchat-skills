#!/usr/bin/env bash
# ============================================================
# Tarot Liveware — 启动服务 + 绑定隧道
# ============================================================
# 职责: 启动服务器 → 绑定隧道（假设 setup 已完成）
# 用法: bash start.sh <app-id> [port]
#   参数: app-id 必填（首次由 setup.py 创建）
#         port   可选，默认 5080
# ============================================================
set -euo pipefail

# 脚本在 tarot-arcana/liveware/scripts/start.sh
# 技能根目录 = 上两级
SKILL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIVEWARE_DIR="$SKILL_ROOT/liveware"
APP_ID_FILE="${HOME}/.clawling/tarot-app-id"

# 读取 app ID：优先用参数，否则从 ~/.clawling/tarot-app-id 读取
if [ -n "${1:-}" ]; then
  APP_ID="$1"
elif [ -f "$APP_ID_FILE" ]; then
  APP_ID=$(cat "$APP_ID_FILE")
  echo "📄 从 $APP_ID_FILE 读取 app ID: $APP_ID"
else
  echo "❌ 未提供 app ID，且找不到 $APP_ID_FILE"
  echo "   用法: bash liveware/scripts/start.sh <app-id>"
  echo "   或先运行 python3 liveware/scripts/setup.py 完成首次安装"
  exit 1
fi
PORT="${2:-5080}"

echo "🃏 Tarot Liveware — 激活"
echo ""

# ── 1. Kill existing server if any ────────────────────────
EXISTING_PID=$(lsof -ti ":$PORT" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
  echo "📌 检测到已有进程占用端口 $PORT (PID: $EXISTING_PID)"
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 1
  echo "   已停止旧进程"
fi

# ── 2. Start server ───────────────────────────────────────
echo "📡 启动本地服务器 (port $PORT)..."
cd "$LIVEWARE_DIR"
nohup python3 server.py --port "$PORT" > /tmp/tarot-server.log 2>&1 &
SERVER_PID=$!
echo "   PID: $SERVER_PID (日志: /tmp/tarot-server.log)"

# 等待服务器就绪
for i in $(seq 1 10); do
  if curl -s -o /dev/null -w "" "http://127.0.0.1:$PORT/" 2>/dev/null; then
    echo "   ✅ 服务器就绪"
    break
  fi
  sleep 1
done

# ── 3. Bind tunnel ────────────────────────────────────────
echo ""
echo "🔗 绑定隧道..."
liveware tunnel bind "$APP_ID" "http://127.0.0.1:$PORT"

echo ""
echo "═══════════════════════════════════════════"
echo "✅ Tarot Liveware 已激活!"
echo "   App:  $APP_ID"
echo "   公网: https://${APP_ID}.apps.clawling.io"
echo "   本地: http://127.0.0.1:$PORT"
echo "═══════════════════════════════════════════"
