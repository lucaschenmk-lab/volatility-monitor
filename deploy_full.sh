#!/bin/bash
"""
每日波动率监测 — 云端长期部署脚本
===================================
在你的 Mac 终端执行此脚本即可一键完成：
  1. 安装 GitHub CLI 并登录
  2. 创建 GitHub 仓库并推送代码
  3. 连接 Railway 并一键部署
  4. 后续每次 git push 自动触发重新部署

用法:
  bash ~/.reasonix/global-workspace/deploy_full.sh
"""

set -e

DIR="$HOME/.reasonix/global-workspace"
echo "========================================="
echo "  ☁️  波动率监测 — 云端长期部署"
echo "========================================="
echo ""

mkdir -p "$DIR" && cd "$DIR"

# ─── 1. 安装 GitHub CLI ────────────────────────
if ! command -v gh &>/dev/null; then
    echo "📦 安装 GitHub CLI..."
    if command -v brew &>/dev/null; then
        brew install gh
    else
        # 直接下载二进制
        curl -fsSL "https://github.com/cli/cli/releases/download/v2.65.0/gh_2.65.0_macOS_arm64.zip" -o /tmp/gh.zip
        mkdir -p "$HOME/.local/bin"
        (cd /tmp && unzip -q gh.zip && mv gh_*/bin/gh "$HOME/.local/bin/" && rm -rf gh.zip gh_*)
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "  ✅ gh $(gh --version 2>&1 | head -1)"
fi
export PATH="$HOME/.local/bin:$PATH"

# ─── 2. GitHub 登录 ────────────────────────────
echo ""
echo "🔑 GitHub 登录..."
if ! gh auth status &>/dev/null; then
    echo "   浏览器将打开，请登录 GitHub"
    echo "   登录后自动继续..."
    gh auth login --web
fi
echo "  ✅ GitHub 已登录: $(gh api user -q .login 2>/dev/null || echo 'ok')"

# ─── 3. 创建 GitHub 仓库 ───────────────────────
echo ""
echo "📁 创建 GitHub 仓库..."
REPO_NAME="volatility-monitor"

# 检查是否已有远程仓库
if ! git remote get-url origin &>/dev/null; then
    # 确保本地有 commit
    git add -A
    git commit -m "Initial deploy" 2>/dev/null || true
    # 创建 GitHub 仓库并推送
    if ! gh repo create "$REPO_NAME" --public --push --source="$DIR"; then
        echo "  仓库可能已存在，尝试推送..."
        # 获取用户名
        GH_USER=$(gh api user -q .login 2>/dev/null)
        git remote add origin "git@github.com:${GH_USER}/${REPO_NAME}.git"
        git branch -M main
        git push -u origin main 2>&1 || echo "  推送完成（或已有更新）"
    fi
else
    echo "  远程仓库已配置，推送最新代码..."
    git push -u origin main
fi
echo "  ✅ 代码已推送到 GitHub"

# ─── 4. Railway 部署 ───────────────────────────
echo ""
echo "🚂 连接 Railway..."
if ! command -v railway &>/dev/null; then
    npm install -g @railway/cli --registry=https://registry.npmmirror.com 2>/dev/null
fi

if ! railway whoami &>/dev/null; then
    echo "   浏览器将打开，请登录 Railway（用 GitHub 账号）"
    echo "   登录后自动继续..."
    railway login
fi
echo "  ✅ Railway 已登录"

# 创建或连接项目
echo "   创建 Railway 项目..."
railway init --name "$REPO_NAME" 2>/dev/null || echo "  项目已存在，使用现有项目"

# 连接 GitHub 仓库实现自动部署
echo "   连接 GitHub → Railway..."
railway link 2>/dev/null || true

# 部署
echo ""
echo "📤 部署中..."
railway up --detach 2>&1

# 获取 URL
echo ""
echo "⏳ 等待部署..."
sleep 5
DOMAIN=$(railway domain 2>/dev/null | grep -oE 'https?://[^ ]+' | head -1)

echo ""
echo "========================================="
echo "  ✅ 部署成功！"
echo "========================================="
if [ -n "$DOMAIN" ]; then
    echo "  公开访问: $DOMAIN"
    echo "  数据API:  $DOMAIN/api/data"
    echo ""
    echo "  在任意设备打开上述网址即可查看"
fi
echo ""
echo "📌 后续更新:"
echo "  cd ~/.reasonix/global-workspace"
echo "  git add -A && git commit -m 'update'"
echo "  git push"
echo "  # Railway 自动重新部署 🚀"
echo "========================================="
