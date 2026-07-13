#!/usr/bin/env python3
"""
每日波动率监测 — Web 服务器版
"""
import sys, os, json, threading, webbrowser, traceback
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor_core import fetch_all_indicators

PORT = 18989
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

# 缓存最新数据
CACHE = {"data": None, "time": None, "error": None}
PUSH_CACHE = {"message": None, "time": None, "source": None}

def refresh_data():
    """后台刷新数据"""
    try:
        result = fetch_all_indicators()
        CACHE["data"] = result
        CACHE["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        CACHE["error"] = None
        print(f"[✓] 数据已更新: {result['triggered_count']}/4 触发")
    except Exception as e:
        CACHE["error"] = str(e)
        print(f"[✗] 数据获取失败: {e}")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/data":
            self._json_response()
        elif path == "/api/refresh":
            refresh_data()
            self._json_response()
        else:
            self._serve_html()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/push":
            self._handle_push()
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        resp = {
            "data": self._convert_numpy(CACHE["data"]),
            "time": CACHE["time"],
            "error": CACHE["error"],
        }
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())

    def _convert_numpy(self, obj):
        """递归将 numpy 类型转为 Python 原生类型"""
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: self._convert_numpy(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._convert_numpy(v) for v in obj]
        return obj

    def _serve_html(self):
        html = self._generate_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _generate_html(self):
        result = CACHE["data"]
        error = CACHE["error"]
        update_time = CACHE["time"] or "加载中..."

        if error:
            status_block = f"""
            <div class="alert alert-error">
                ⚠️ 数据获取失败: {error}<br>
                <button onclick="location.reload()">⟳ 重试</button>
            </div>"""
        elif result:
            inds = result["indicators"]
            cnt = result["triggered_count"]
            risk = result["risk_level"]

            if risk == "high":
                banner_cls, banner_icon = "banner-high", "🔴"
            elif risk == "watch":
                banner_cls, banner_icon = "banner-watch", "🟡"
            else:
                banner_cls, banner_icon = "banner-low", "🟢"

            status_block = f"""
            <div class="banner {banner_cls}">
                <span class="banner-icon">{banner_icon}</span>
                <span class="banner-text">{result['risk_text']}</span>
                <span class="banner-count">触发: {cnt}/4 项</span>
            </div>"""

            cards = ""
            for i, ind in enumerate(inds):
                names = ["VIX历史百分位", "VIX期限结构", "RV/IV比值", "信用利差HY-IG"]
                nums = ["①", "②", "③", "④"]
                triggered = ind.get("triggered", False)
                val = ind.get("value", "N/A")
                threshold = ind.get("threshold", "")
                interp = ind.get("interpretation", "")
                detail = ind.get("detail", "")
                card_cls = "card card-triggered" if triggered else "card"
                status_cls = "status-triggered" if triggered else "status-normal"
                status_text = "🔴 触发" if triggered else "🟢 正常"

                cards += f"""
                <div class="{card_cls}">
                    <div class="card-header">{nums[i]} {names[i]}</div>
                    <div class="card-value">{val}</div>
                    <div class="card-status {status_cls}">{status_text}</div>
                    <div class="card-threshold">阈值: {threshold}</div>
                    <div class="card-interp">{interp}</div>
                    <details class="card-detail">
                        <summary>详细数据</summary>
                        <pre>{detail}</pre>
                    </details>
                </div>"""

            status_block += f'<div class="cards-row">{cards}</div>'

            # 详细数据
            detail_rows = ""
            labels = ["① VIX历史百分位", "② VIX期限结构", "③ RV/IV比值", "④ 信用利差"]
            for lbl, ind in zip(labels, inds):
                d = ind.get("detail", "无数据")
                detail_rows += f"<tr><td>{lbl}</td><td>{d}</td></tr>"

            status_block += f"""
            <details class="detail-section">
                <summary>📊 指标详细数据</summary>
                <table><tbody>{detail_rows}</tbody></table>
            </details>"""
        else:
            status_block = """
            <div class="alert alert-loading">
                ⏳ 正在获取市场数据，请稍候...<br>
                <small>首次加载可能需要 10-30 秒</small>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日波动率监测清单</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
    background: #f5f7fa; color: #1a1a2e; padding: 20px;
}}
.container {{ max-width:1200px; margin:0 auto; }}

.header {{
    display:flex; justify-content:space-between; align-items:flex-start;
    margin-bottom:16px; flex-wrap:wrap; gap:10px;
}}
.header-left h1 {{ font-size:22px; font-weight:700; color:#1a1a2e; }}
.header-left .date {{ font-size:13px; color:#888; margin-top:2px; }}
.header-right {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.status-text {{ font-size:12px; color:#666; }}
.btn {{
    padding:6px 16px; border:none; border-radius:6px;
    font-size:13px; font-weight:600; cursor:pointer;
    background:#e8ecf1; color:#333; transition:all .15s;
}}
.btn:hover {{ background:#d0d5dd; }}
.btn-primary {{ background:#4361ee; color:#fff; }}
.btn-primary:hover {{ background:#3651d4; }}
.auto-label {{ font-size:12px; color:#666; display:flex; align-items:center; gap:4px; }}

.banner {{
    padding:12px 20px; border-radius:10px; margin-bottom:16px;
    display:flex; align-items:center; gap:12px; flex-wrap:wrap;
}}
.banner-low {{ background:#d4edda; color:#155724; }}
.banner-watch {{ background:#fff3cd; color:#856404; }}
.banner-high {{ background:#f8d7da; color:#721c24; }}
.banner-icon {{ font-size:18px; }}
.banner-text {{ font-size:15px; font-weight:600; flex:1; }}
.banner-count {{ font-size:14px; font-weight:600; }}

.cards-row {{
    display:grid; grid-template-columns:repeat(4, 1fr); gap:12px;
    margin-bottom:16px;
}}
.card {{
    background:#fff; border-radius:10px; padding:16px;
    border:1px solid #e0e0e0; box-shadow:0 1px 3px rgba(0,0,0,.04);
}}
.card-triggered {{ border-left:3px solid #d32f2f; }}
.card-header {{ font-size:11px; font-weight:600; color:#888; margin-bottom:2px; }}
.card-value {{ font-size:30px; font-weight:700; color:#1a1a2e; font-family:"SF Mono", Menlo, monospace; margin:2px 0; }}
.card-status {{ font-size:12px; font-weight:600; margin-bottom:6px; }}
.status-normal {{ color:#2e7d32; }}
.status-triggered {{ color:#d32f2f; }}
.card-threshold {{ font-size:11px; color:#aaa; margin-bottom:2px; }}
.card-interp {{ font-size:11px; color:#666; }}
.card-detail {{ margin-top:6px; }}
.card-detail summary {{ font-size:10px; color:#999; cursor:pointer; }}
.card-detail pre {{ font-size:9px; color:#666; background:#f5f5f5; padding:6px; border-radius:4px; margin-top:4px; white-space:pre-wrap; }}

.detail-section {{
    background:#fff; border-radius:10px; padding:12px 16px;
    border:1px solid #e0e0e0; margin-bottom:12px;
}}
.detail-section summary {{ font-size:13px; font-weight:600; color:#555; cursor:pointer; }}
.detail-section table {{ width:100%; margin-top:8px; border-collapse:collapse; }}
.detail-section td {{ padding:4px 8px; font-size:11px; color:#666; border-bottom:1px solid #eee; }}
.detail-section td:first-child {{ font-weight:600; color:#444; white-space:nowrap; width:180px; }}

.footer {{
    font-size:11px; color:#aaa; text-align:center; padding:12px 0; border-top:1px solid #eee;
    margin-top:8px;
}}

.alert {{
    text-align:center; padding:40px 20px; border-radius:10px; font-size:14px;
}}
.alert-loading {{ background:#e8f0fe; color:#1967d2; }}
.alert-error {{ background:#fce8e6; color:#c5221f; }}

@media (max-width:800px) {{
    .cards-row {{ grid-template-columns:repeat(2,1fr); }}
}}
@media (max-width:500px) {{
    .cards-row {{ grid-template-columns:1fr; }}
    .header {{ flex-direction:column; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-left">
            <h1>📊 每日波动率监测清单</h1>
            <div class="date">更新于: {update_time}</div>
        </div>
        <div class="header-right">
            <span class="status-text" id="status">{( '✅ 正常' if result else '⏳ 加载中...' )}</span>
            <button class="btn btn-primary" onclick="refresh()">⟳ 刷新</button>
            <label class="auto-label">
                <input type="checkbox" id="autoSwitch" checked onchange="toggleAuto()"> 自动刷新
            </label>
        </div>
    </div>

    {status_block}

    <div class="footer">
        数据来源: Yahoo Finance (^VIX, ^VIX9D, ^VIX3M, ^GSPC) · ETF代理 (HYG/LQD)
    </div>
</div>

<script>
let autoTimer = null;

function refresh() {{
    document.getElementById('status').textContent = '⏳ 刷新中...';
    fetch('/api/refresh')
        .then(r => r.json())
        .then(() => location.reload())
        .catch(e => {{ document.getElementById('status').textContent = '⚠ ' + e.message; }});
}}

function toggleAuto() {{
    if (document.getElementById('autoSwitch').checked) {{
        autoTimer = setInterval(refresh, 1800000);
    }} else {{
        clearInterval(autoTimer);
    }}
}}

// 自动刷新
if (document.getElementById('autoSwitch').checked) {{
    autoTimer = setInterval(refresh, 1800000);
}}
</script>
</body>
</html>"""

    def log_message(self, format, *args):
        pass  # 不打印请求日志

    def _handle_push(self):
        """接收推送消息并存入 PUSH_CACHE"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            data = json.loads(body)
            PUSH_CACHE["message"] = data.get("message", "")
            PUSH_CACHE["time"] = datetime.now().strftime("%H:%M:%S")
            PUSH_CACHE["source"] = data.get("source", "unknown")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            print(f"📥 推送消息已接收 ({len(PUSH_CACHE['message'])} chars)")
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            print(f"⚠ 推送消息接收失败: {e}")


def start_server():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", PORT))
    server = HTTPServer((host, port), Handler)
    print(f"🌐 服务器已启动: http://{host}:{port}")
    print(f"   按 Ctrl+C 停止服务")
    if host == "127.0.0.1":
        webbrowser.open(f"http://{host}:{port}")
    server.serve_forever()


def main():
    print("=" * 50)
    print("  每日波动率监测清单")
    print("=" * 50)
    print()

    # 首次加载数据
    print("⏳ 首次获取数据中...")
    refresh_data()
    if CACHE["error"]:
        print(f"⚠ 初始数据获取失败: {CACHE['error']}")
        print("  服务器仍将启动，可在浏览器中点击刷新重试")
    else:
        print("✅ 初始数据获取成功")

    print(f"\n🚀 启动 Web 服务...")
    print(f"   浏览器将自动打开: http://127.0.0.1:{PORT}")
    print(f"   按 Ctrl+C 停止服务")
    print()

    start_server()


if __name__ == "__main__":
    main()
