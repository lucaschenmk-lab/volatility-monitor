#!/bin/bash
"""
每日波动率监测 — 微信推送安装脚本
==================================
一键安装定时推送任务到 macOS launchd。

用法:
  bash setup_push.sh

安装后:
  - 每个交易日 9:30 和 14:30 自动运行监测
  - 结果推送到微信
  - 日志保存在 ~/.reasonix/global-workspace/monitor_logs/

重启 Reasonix 后 Bot Control API 才会生效，否则仅生成消息。
"""

DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$DIR/com.volatility.monitor.push.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.volatility.monitor.push.plist"

echo "========================================"
echo "  每日波动率监测 — 微信推送安装"
echo "========================================"
echo ""

# 1. 检查文件
if [ ! -f "$PLIST_SRC" ]; then
    echo "❌ 找不到 plist 文件: $PLIST_SRC"
    exit 1
fi

# 2. 复制 plist 到 LaunchAgents
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
echo "✅ plist 已安装到: $PLIST_DST"

# 3. 卸载旧的任务（如果有）
launchctl unload "$PLIST_DST" 2>/dev/null && echo "  已卸载旧任务"

# 4. 加载新任务
launchctl load "$PLIST_DST"
if [ $? -eq 0 ]; then
    echo "✅ 定时任务已加载"
else
    echo "❌ 定时任务加载失败"
    echo "   请尝试: launchctl load -w \"$PLIST_DST\""
fi

echo ""
echo "📋 任务状态:"
launchctl list com.volatility.monitor.push 2>&1 || echo "  （未运行，等待定时触发）"

echo ""
echo "📊 定时计划:"
echo "  · 交易日 09:30 — 开盘推送"
echo "  · 交易日 14:30 — 收盘前推送"
echo "  （交易日 = 周一至周五，自动跳过周末）"
echo ""
echo "📝 日志位置:"
echo "  · 消息日志: $DIR/monitor_logs/push.log"
echo "  · 标准输出: $DIR/monitor_logs/stdout.log"
echo "  · 错误日志: $DIR/monitor_logs/stderr.log"
echo ""
echo "💡 重要: 如果 Bot Control API 尚未生效"
echo "   请重启 Reasonix 以使 Bot Control API 激活"
echo "   重启后，监测结果会自动推送到微信"
echo ""
echo "🔍 手动测试推送:"
echo "   python3 $DIR/push_monitor.py"
echo "========================================"
