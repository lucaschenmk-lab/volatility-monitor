#!/usr/bin/env python3
"""
每日波动率监测清单 — 桌面应用
"""
import sys, os, threading, traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor_core import fetch_all_indicators

import tkinter as tk
from tkinter import ttk

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_debug.log")
def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")


class App:
    def __init__(self):
        log("init start")
        self.root = tk.Tk()
        self.root.title("每日波动率监测清单")
        self.root.geometry("1100x700")
        self.root.minsize(900, 550)

        # macOS style
        style = ttk.Style()
        style.theme_use("aqua")  # macOS native theme

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Main frame
        self.main = ttk.Frame(self.root, padding=12)
        self.main.grid(row=0, column=0, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=1)

        # ── Row 0: Header ──
        self._build_header()

        # ── Row 1: Risk banner ──
        self.banner_var = tk.StringVar(value="⏳ 正在获取数据...")
        self.banner = ttk.Label(self.main, textvariable=self.banner_var,
                                 font=("Helvetica", 13, "bold"),
                                 foreground="#666", background="#E8F0FE")
        self.banner.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # ── Row 2: Cards area ──
        self.cards_frame = ttk.Frame(self.main)
        self.cards_frame.grid(row=2, column=0, sticky="nsew")
        self.cards_frame.columnconfigure(tuple(range(4)), weight=1)

        # 占位文字
        self.placeholder = ttk.Label(self.cards_frame,
                                      text="⏳ 正在获取市场数据...\n请稍候",
                                      font=("Helvetica", 14))
        self.placeholder.grid(row=0, column=0, columnspan=4, pady=80)

        # ── Row 3: Detail toggle ──
        self.detail_frame = ttk.Frame(self.main)
        self.detail_frame.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        # ── Row 4: Source footer ──
        self.footer = ttk.Label(self.main, text="数据来源: Yahoo Finance + ETF代理",
                                 font=("Helvetica", 9), foreground="#999")
        self.footer.grid(row=4, column=0, sticky="ew", pady=(6, 0))

        # 首次加载
        self.result = None
        self._monitoring = False
        self.root.after(300, self._start_load)
        log("init done")

    def _build_header(self):
        hdr = ttk.Frame(self.main)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hdr.columnconfigure(0, weight=1)

        ttk.Label(hdr, text="📊 每日波动率监测清单",
                  font=("Helvetica", 18, "bold")).grid(row=0, column=0, sticky="w")

        ctrl = ttk.Frame(hdr)
        ctrl.grid(row=0, column=1, sticky="e")

        self.status_var = tk.StringVar(value="")
        ttk.Label(ctrl, textvariable=self.status_var,
                  font=("Helvetica", 10)).pack(side="left", padx=(0, 6))

        self.refresh_btn = ttk.Button(ctrl, text="⟳ 刷新",
                                       command=self._manual_refresh)
        self.refresh_btn.pack(side="left", padx=(0, 4))

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="自动", variable=self.auto_var,
                         command=self._toggle_auto).pack(side="left")

    def _start_load(self):
        self.status_var.set("⏳ 获取数据中...")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _manual_refresh(self):
        if self._monitoring:
            return
        self.refresh_btn.configure(text="⟳ 刷新中...", state="disabled")
        self.status_var.set("⏳ 刷新中...")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        self._monitoring = True
        log("fetch start")
        try:
            r = fetch_all_indicators()
            self.result = r
            log(f"fetch ok: {r['triggered_count']}/4")
            self.root.after(0, self._update, r)
        except Exception as e:
            log(f"fetch error: {e}\n{traceback.format_exc()}")
            self.root.after(0, self._show_error, str(e))
        finally:
            self._monitoring = False

    def _show_error(self, msg):
        self.status_var.set("⚠ 数据获取失败")
        self.banner_var.set("⚠️ 数据获取失败 — 请检查网络后点击「⟳ 刷新」重试")
        self.refresh_btn.configure(text="⟳ 重试", state="normal")
        self.placeholder.configure(text=f"⚠️ 错误: {msg}")

    def _update(self, r):
        log("update UI")
        inds = r["indicators"]
        cnt = r["triggered_count"]

        # Banner
        if cnt >= 2:
            txt = f"🔴 风险: 进入高回撤风险期 ({cnt}/4 触发) — 建议降仓"
            color = "#FEE"
        elif cnt == 1:
            txt = f"🟡 关注: 已有 {cnt}/4 项触发，持续监控"
            color = "#FFF3CD"
        else:
            txt = f"🟢 低风险: 所有指标正常 ({cnt}/4 触发)"
            color = "#D4EDDA"
        self.banner_var.set(txt)
        self.banner.configure(background=color, foreground="#333")

        # 卡片
        self.placeholder.grid_remove()

        card_names = [
            ("①", "VIX历史百分位", ">过去1年80分位 / 从最低翻倍"),
            ("②", "VIX期限结构", ">1 = 倒挂 / Contango突转倒挂"),
            ("③", "RV/IV比值", ">1 = RV突破IV / 市场低估风险"),
            ("④", "信用利差HY-IG", "突破均值+1.5σ / 系统性风险"),
        ]

        for col in range(4):
            ind = inds[col] if col < len(inds) else {}
            num, name, desc = card_names[col]
            val = ind.get("value", "N/A")
            triggered = ind.get("triggered", False)
            detail = ind.get("detail", "")

            # Card frame with border
            card = tk.Frame(self.cards_frame, bg="white",
                            highlightbackground="#DDD", highlightthickness=1,
                            bd=0, padx=0, pady=0)
            card.grid(row=0, column=col, padx=5, pady=5, sticky="nsew")

            # Title
            tk.Label(card, text=f"{num} {name}",
                     bg="white", fg="#555",
                     font=("Helvetica", 10, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))

            # Value
            tk.Label(card, text=val,
                     bg="white", fg="#111",
                     font=("Helvetica", 30, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(0, 2))

            # Status
            dot_color = "#D32F2F" if triggered else "#2E7D32"
            dot_text = "● 触发" if triggered else "● 正常"
            tk.Label(card, text=dot_text,
                     bg="white", fg=dot_color,
                     font=("Helvetica", 11),
                     anchor="w").pack(fill="x", padx=12, pady=(0, 4))

            # Description
            tk.Label(card, text=desc,
                     bg="white", fg="#888",
                     font=("Helvetica", 9),
                     anchor="w", wraplength=220, justify="left"
                     ).pack(fill="x", padx=12, pady=(0, 2))

            # Detail line
            if detail:
                detail_short = detail[:60] + "..." if len(detail) > 60 else detail
                tk.Label(card, text=detail_short,
                         bg="white", fg="#AAA",
                         font=("Helvetica", 8),
                         anchor="w", wraplength=220,
                         ).pack(fill="x", padx=12, pady=(0, 10))

        # Detail toggle
        for w in self.detail_frame.winfo_children():
            w.destroy()

        self.detail_shown = False

        def toggle_d():
            self.detail_shown = not self.detail_shown
            if self.detail_shown:
                for w in detail_content.winfo_children():
                    w.destroy()
                names = ["① VIX历史百分位", "② VIX期限结构", "③ RV/IV比值", "④ 信用利差"]
                for nm, ind in zip(names, inds):
                    d = ind.get("detail", "无数据")
                    tk.Label(detail_content, text=f"  {nm}: {d}",
                             bg="#F5F5F5", fg="#555",
                             font=("Helvetica", 9),
                             anchor="w", wraplength=900, justify="left").pack(anchor="w", pady=1)
                detail_content.pack(fill="x", padx=16, pady=(0, 6))
                toggle_btn.configure(text="▼  收起详细数据")
            else:
                for w in detail_content.winfo_children():
                    w.destroy()
                detail_content.pack_forget()
                toggle_btn.configure(text="▶  展开详细数据")

        toggle_btn = ttk.Label(self.detail_frame, text="▶  展开详细数据",
                                font=("Helvetica", 10, "bold"),
                                cursor="hand2")
        toggle_btn.pack(anchor="w")
        toggle_btn.bind("<Button-1>", lambda e: toggle_d())
        detail_content = tk.Frame(self.detail_frame, bg="#F5F5F5")

        # Status
        self.status_var.set(f"✅ {datetime.now().strftime('%H:%M:%S')}")
        self.refresh_btn.configure(text="⟳ 刷新", state="normal")
        log("update done")

    def _toggle_auto(self):
        if self.auto_var.get():
            self._schedule_auto()
        else:
            if hasattr(self, '_auto_id'):
                self.root.after_cancel(self._auto_id)
                self._auto_id = None

    def _schedule_auto(self):
        if self.auto_var.get():
            self._auto_id = self.root.after(1800000, self._auto_cb)

    def _auto_cb(self):
        self._manual_refresh()
        self._schedule_auto()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    log("=== 启动 ===")
    try:
        app = App()
        log("进入主循环")
        app.run()
    except Exception as e:
        log(f"崩溃: {traceback.format_exc()}")
        raise
