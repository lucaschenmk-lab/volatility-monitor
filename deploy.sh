#!/bin/bash
"""
每日波动率监测 — 云端部署脚本
==============================
自动检测可用平台并部署。

用法:
  bash deploy.sh                         # 自动部署
  bash deploy.sh --railway               # 指定 Railway
  bash deploy.sh --vercel                # 指定 Vercel
  bash deploy.sh --token RAILWAY_TOKEN   # 使用 Token 部署
  bash deploy.sh --guide                 # 显示详细部署指南
"""

DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

echo "========================================="
echo "  ☁️  波动率监测 — 云端部署"
echo "========================================="
echo ""

cd "$DIR" || exit 1

# 显示详细指南
if [ "$1" == "--guide" ]; then
    echo "📖 云端部署指南（3种方式）"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "方式1: GitHub → Railway 自动部署"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  1. 创建 GitHub 仓库:"
    echo "     gh repo create volatility-monitor --public"
    echo "     git remote add origin <your-repo-url>"
    echo "     git push -u origin main"
    echo ""
    echo "  2. 打开 https://railway.app/new"
    echo "     选择「Deploy from GitHub repo」"
    echo "     连接你的仓库 → 自动部署"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "方式2: Railway CLI (推荐)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  railway login           # 浏览器登录"
    echo "  railway init            # 初始化项目"
    echo "  railway up              # 部署"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "方式3: Railway Token (CI/CD)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Railway Dashboard → Settings → Tokens"
    echo "  生成 Token 后运行:"
    echo "  RAILWAY_TOKEN=xxx railway up"
    echo "========================================="
    exit 0
fi

# 检查 Git 仓库
if [ ! -d ".git" ]; then
    echo "📁 初始化 Git 仓库..."
    git init
    git add -A
    git commit -m "init: 每日波动率监测系统"
fi

# 检查 Railway CLI
if ! command -v railway &>/dev/null; then
    echo "📦 安装 Railway CLI..."
    npm install -g @railway/cli --registry=https://registry.npmmirror.com 2>/dev/null
fi

# 检查 Vercel CLI
if ! command -v vercel &>/dev/null && [ "$1" == "--vercel" ]; then
    echo "📦 安装 Vercel CLI..."
    npm install -g vercel --registry=https://registry.npmmirror.com 2>/dev/null
fi

# 检测 Token 方式
if [ "$1" == "--token" ] && [ -n "$2" ]; then
    echo "🔑 使用 Token 部署..."
    export RAILWAY_TOKEN="$2"
fi

# Railway 部署
if [ "$1" == "--vercel" ]; then
    echo "🚀 部署到 Vercel..."
    echo "   注: Vercel 部署需要调整项目结构"
    vercel --prod
else
    echo "🚀 部署到 Railway..."
    echo ""

    # 登录检测
    if ! railway whoami &>/dev/null; then
        if [ -z "$RAILWAY_TOKEN" ]; then
            echo "🔑 需要登录..."
            echo "   浏览器将自动打开，请使用 GitHub/Google 登录"
            echo "   登录后脚本自动继续"
            railway login
        fi
    fi

    # 初始化项目
    if [ ! -f ".railway/config.json" ]; then
        railway init --name volatility-monitor 2>/dev/null || true
    fi

    # 部署
    echo ""
    echo "📤 部署中... (约 2-3 分钟)"
    railway up --detach 2>&1

    # 获取 URL
    echo ""
    echo "⏳ 等待部署完成..."
    sleep 8
    DOMAIN=$(railway domain 2>/dev/null | grep -oP 'https://[^\s]+' | head -1)

    echo ""
    echo "✅ 部署完成"
    if [ -n "$DOMAIN" ]; then
        echo "  公开访问: $DOMAIN"
    else
        echo "  请前往 https://railway.app/dashboard 查看 URL"
    fi
fi
