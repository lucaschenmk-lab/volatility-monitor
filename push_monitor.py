#!/usr/bin/env python3
"""
每日波动率监测 — 推送版
=======================
每天 9:30 / 14:30 自动运行，多渠道推送监测结果。

推送渠道（按优先级）:
  1. Reasonix Bot Control API → 微信（需 Reasonix 服务器版，桌面版不支持）
  2. 写入 monitor_server 仪表盘（用户可打开 http://127.0.0.1:18989 查看）
  3. macOS 原生通知
  4. 日志文件

使用方式:
  python3 push_monitor.py           # 正常推送
  python3 push_monitor.py --force   # 周末也推送（测试用）
"""

import sys, os, json, subprocess, urllib.request, urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor_core import fetch_all_indicators

# ─── 配置 ───────────────────────────────────────────────────────────
LOG_DIR = os.path.expanduser("~/.reasonix/global-workspace/monitor_logs")
MSG_FILE = os.path.expanduser("~/.reasonix/global-workspace/monitor_logs/latest_push.txt")
DASHBOARD_URL = "http://127.0.0.1:18989"
BOT_API = "http://127.0.0.1:37913"
TOKEN = os.environ.get("REASONIX_BOT_CONTROL_TOKEN", "")


def log(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "push.log"), "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def is_trading_day():
    return datetime.now().weekday() < 5


def format_message(result) -> str:
    inds = result["indicators"]
    cnt = result["triggered_count"]
    risk = result["risk_level"]
    date = result["monitor_date"]
    risk_icon = {"high": "🔴", "watch": "🟡", "low": "🟢"}.get(risk, "🟢")

    lines = [f"📊 波动率监测日报 | {date}", ""]
    lines.append(f"{risk_icon} 风险状态: {result['risk_text']}")
    lines.append(f"   触发指标: {cnt}/4 项")
    lines.append("")

    for i, ind in enumerate(inds):
        nums = ["①", "②", "③", "④"]
        names = ["VIX历史百分位", "VIX期限结构", "RV/IV比值", "信用利差HY-IG"]
        triggered = ind.get("triggered", False)
        val = ind.get("value", "N/A")
        status = "🔴 触发" if triggered else "🟢 正常"
        detail = ind.get("detail", "")
        short = detail.split("|")[0] if "|" in detail else detail[:40]
        lines.append(f"{nums[i]} {names[i]}")
        lines.append(f"   读数: {val}  |  {status}")
        lines.append(f"   {short}")
        lines.append("")

    lines.append("— — — — — — — — — —")
    lines.append("盘中自动监测 · 随市场波动更新")
    return "\n".join(lines)


# ─── 推送渠道 ──────────────────────────────────────────────────────

def try_bot_control_api(text: str) -> bool:
    """渠道1: Reasonix Bot Control API"""
    if not TOKEN:
        log("  渠道1 跳过: 无 TOKEN")
        return False
    log(f"  渠道1: 尝试 Bot Control API...")
    for path in ["/send", "/api/bot/send", "/v1/send"]:
        try:
            payload = json.dumps({
                "connection_id": "weixin-weixin",
                "user_id": "o9cq800aXEAKDSjzZKmCDgw02wKI@im.wechat",
                "content": text, "platform": "weixin"
            }).encode()
            req = urllib.request.Request(
                f"{BOT_API}{path}",
                data=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {TOKEN}"},
                method="POST")
            resp = urllib.request.urlopen(req, timeout=3)
            log(f"  渠道1 ✅ {path}: {resp.status}")
            return True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log(f"  渠道1 ⚠ {path}: HTTP {e.code}")
        except Exception as e:
            log(f"  渠道1 ⚠ {path}: {e}")
    log("  渠道1 ❌ Bot Control API 不可用")
    return False


def try_macos_notification(text: str) -> bool:
    """渠道2: macOS 原生通知"""
    try:
        title = "📊 波动率监测"
        subtitle = text.split("\n")[2] if len(text.split("\n")) > 2 else ""
        # 截断太长内容（macOS 通知有长度限制）
        body = text[:200].replace('"', "'")
        script = f'display notification "{body}" with title "{title}" subtitle "{subtitle}"'
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=5)
        log(f"  渠道2 ✅ macOS 通知已发送")
        return True
    except Exception as e:
        log(f"  渠道2 ⚠ macOS 通知失败: {e}")
        return False


def save_to_dashboard(text: str) -> bool:
    """渠道3: 保存到文件，供 monitor_server 仪表盘展示"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(MSG_FILE, "w") as f:
            f.write(f"更新于: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}")
        log(f"  渠道3 ✅ 已保存到仪表盘文件")
        return True
    except Exception as e:
        log(f"  渠道3 ⚠ 保存失败: {e}")
        return False


def send_via_server_api(text: str) -> bool:
    """渠道4: 推送到本地 monitor_server"""
    try:
        payload = json.dumps({"message": text, "source": "scheduled_push"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:18989/api/push",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST")
        resp = urllib.request.urlopen(req, timeout=3)
        log(f"  渠道4 ✅ monitor_server: {resp.status}")
        return True
    except Exception as e:
        log(f"  渠道4 ⚠ {e}")
        return False


# ─── 主流程 ─────────────────────────────────────────────────────────

def main():
    log("=== 开始监测推送 ===")

    # 交易日检查
    if not is_trading_day() and "--force" not in sys.argv:
        log("⏭ 非交易日，跳过")
        print("⏭ 非交易日，跳过推送")
        return

    # 获取数据
    log("获取数据中...")
    try:
        result = fetch_all_indicators()
    except Exception as e:
        log(f"❌ 数据获取失败: {e}")
        print(f"❌ 错误: {e}")
        return

    message = format_message(result)
    log(f"消息已生成 ({len(message)} chars)")

    print(message)
    print()
    print("—" * 30)
    print("推送状态:")

    # 多渠道推送
    channels = [
        ("Bot Control → 微信", try_bot_control_api),
        ("macOS 通知", try_macos_notification),
        ("仪表盘文件", save_to_dashboard),
        ("monitor_server", send_via_server_api),
    ]

    success_count = 0
    for name, func in channels:
        result_msg = "✅" if func(message) else "⬜"
        print(f"  {result_msg} {name}")
        if result_msg == "✅":
            success_count += 1

    print()
    if success_count > 0:
        print(f"✅ {success_count}/{len(channels)} 渠道推送成功")
    else:
        print("⚠ 所有推送渠道均失败，消息已保存至日志")
        print(f"   日志: {LOG_DIR}/push.log")

    log(f"推送完成: {success_count}/{len(channels)} 渠道成功")


if __name__ == "__main__":
    main()
