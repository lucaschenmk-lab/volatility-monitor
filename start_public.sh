#!/bin/bash
"""
每日波动率监测 — 一键公开访问启动器
=====================================
用法:
  bash start_public.sh                  # 启动本地 + 隧道
  bash start_public.sh --local-only     # 仅启动本地服务器
  bash start_public.sh --cloud-deploy   # 显示云端部署指南

启动后:
  - 本地访问: http://127.0.0.1:18989
  - 公开访问: https://volatility-monitor.loca.lt
"""

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/monitor_logs"
PID_FILE="/tmp/volatility-monitor-pids.txt"

mkdir -p "$LOG_DIR"

echo "========================================="
echo "  每日波动率监测 — 公开访问启动器"
echo "========================================="

# ─── 云端部署指南 ─────────────────────────────────────
if [ "$1" == "--cloud-deploy" ]; then
    echo ""
    echo "☁️  云端部署指南 (24/7 全天候可用)"
    echo "========================================="
    echo ""
    echo "方案1: Railway (推荐)"
    echo "  1. 打开 https://railway.app/new"
    echo "  2. 选择「Deploy from repo」或「Empty Project」"
    echo "  3. 上传以下文件或连接 GitHub 仓库:"
    echo "      - monitor_server.py"
    echo "      - monitor_core.py"
    echo "      - requirements.txt"
    echo "      - Dockerfile"
    echo "  4. Railway 会自动检测 Dockerfile 并部署"
    echo "  5. 部署后获得 https://xxx.railway.app"
    echo ""
    echo "方案2: Render"
    echo "  1. 打开 https://dashboard.render.com/select-repo"
    echo "  2. 选择「Web Service」"
    echo "  3. 连接你的 GitHub 仓库"
    echo "  4. 选择「Docker」作为环境"
    echo "  5. 部署后获得 https://xxx.onrender.com"
    echo ""
    echo "方案3: Fly.io"
    echo "  flyctl launch --dockerfile Dockerfile"
    echo "  flyctl deploy"
    echo "  获得 https://xxx.fly.dev"
    echo ""
    echo "部署前准备:"
    echo "  git init && git add . && git commit -m 'init'"
    echo "  # 然后 push 到 GitHub 并连接部署平台"
    echo "========================================="
    exit 0
fi

# ─── 本地服务器 ────────────────────────────────────────
echo ""
echo "📡 启动本地服务器..."

# 清理旧进程
kill $(lsof -t -i:18989) 2>/dev/null
pkill -f "lt --port 18989" 2>/dev/null
sleep 1

# 启动服务器
cd "$DIR"
/usr/bin/python3 -W ignore monitor_server.py &
SERVER_PID=$!
echo "  服务器 PID: $SERVER_PID"

# 等待服务器就绪
echo "  等待数据加载..."
for i in $(seq 1 20); do
    sleep 1
    if curl -s -o /dev/null -w "" http://127.0.0.1:18989/ 2>/dev/null; then
        echo "  ✅ 服务器已就绪"
        break
    fi
done

# ─── 公开隧道 ────────────────────────────────────────
if [ "$1" != "--local-only" ]; then
    echo ""
    echo "🔗 启动公开隧道..."
    export PATH="$HOME/.local/bin:$PATH"

    # 尝试创建隧道
    LT_OUTPUT=$(lt --port 18989 --subdomain volatility-monitor 2>&1)
    LT_PID=$!
    PUBLIC_URL=$(echo "$LT_OUTPUT" | grep "your url is:" | head -1)

    if [ -z "$PUBLIC_URL" ]; then
        # 子域名可能被占用，用随机子域名
        echo "  子域名 volatility-monitor 可能被占用，尝试随机..."
        LT_OUTPUT=$(lt --port 18989 2>&1 &)
        LT_PID=$!
        sleep 3
        PUBLIC_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])")
    fi

    if [ -n "$PUBLIC_URL" ]; then
        echo "  ✅ 隧道已建立"
        echo "  公开 URL: $PUBLIC_URL"
    else
        echo "  ⚠ 隧道可能未完全建立"
        echo "  稍后查看 localtunnel 输出确认"
    fi
fi

# ─── 保存 PID ──────────────────────────────────────────
echo "$SERVER_PID" > "$PID_FILE"
echo "" >> "$PID_FILE"
echo "$LT_PID" >> "$PID_FILE"

# ─── 显示信息 ──────────────────────────────────────────
echo ""
echo "========================================="
echo "  ✅ 已启动"
echo "========================================="
echo "  本地访问: http://127.0.0.1:18989"
echo "  公开访问: https://volatility-monitor.loca.lt"
echo ""
echo "  停止: kill \$(lsof -t -i:18989)"
echo "  日志: $LOG_DIR/"
echo "========================================="

# 等待
wait
