#!/usr/bin/env python3
"""
每日波动率监测清单 — CLI 版本
===============================
用法：
  python3 volatility_monitor.py [--date YYYY-MM-DD] [--fred-key KEY]
"""

import argparse
import sys
import os

# 确保可以从同目录导入 monitor_core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor_core import fetch_all_indicators, FRED_API_KEY


def main():
    parser = argparse.ArgumentParser(description="每日波动率监测清单")
    parser.add_argument("--date", type=str, default="",
                        help="监测日期 (YYYY-MM-DD)")
    parser.add_argument("--fred-key", type=str, default="",
                        help="FRED API Key")
    args = parser.parse_args()

    result = fetch_all_indicators(fred_key=args.fred_key or "",
                                   date_str=args.date)
    data = result["monitor_date"]
    inds = result["indicators"]

    print("=" * 72)
    print("  每日波动率监测清单")
    print("=" * 72)
    print(f"  监测日期: {data}")
    print(f"  规则: 4项中≥2项同时触发 → 进入「高回撤风险期」→ 降仓或买保护")
    print(f"  说明: 看百分位/变化方向，不看绝对值")
    print("-" * 72)
    print()

    print(f"{'监测指标':<22} {'当前读数':<14} {'触发阈值':<22} {'触发?':<8} {'解读/领先性'}")
    print("-" * 100)

    labels = ["①", "②", "③", "④"]
    for i, ind in enumerate(inds):
        v = str(ind["value"]) if ind["value"] is not None else "N/A"
        flag = "🔴是" if ind["triggered"] else "🟢否"
        print(f"{labels[i]} {ind['name']:<18} {v:<14} {ind['threshold']:<22} {flag:<8} {ind['interpretation']}")

    print("-" * 100)
    print(f"\n{'触发数量合计':<22} {result['triggered_count']:<14} {'≥2触发即进入高回撤风险期':<38}")
    print()
    print(f"{'风险状态':<22} {result['risk_text']}")
    print()

    print("─" * 72)
    print("  指标详细数据")
    print("─" * 72)
    labels_detail = ["① VIX历史百分位", "② VIX期限结构", "③ RV/IV比值", "④ 信用利差"]
    for label, ind in zip(labels_detail, inds):
        print(f"  {label}: {ind['detail']}")
    print()

    print("─" * 72)
    print("  数据来源速查")
    print("─" * 72)
    print("  · VIX实时+历史:    Yahoo Finance (^VIX)")
    print("  · VIX期限结构:     Yahoo Finance (^VIX9D, ^VIX, ^VIX3M)")
    print("  · Realized Vol:    自算：过去20日收益率标准差×√252")
    print("  · Implied Vol:     股指用VIX代替")
    print("  · 信用利差HY-IG:   ETF代理 (HYG/LQD)")
    print()

    print("─" * 72)
    print("  常见误区")
    print("─" * 72)
    print("  · VIX 40+往往还有最后一跌（2020/3到82）")
    print("  · 低波动期常积累杠杆与拥挤，反转更狠")
    print("  · 波动率只给概率区间，抓不住黑天鹅")
    print("  · 单一指标不够，须结合信用利差与宏观判断")
    print("=" * 72)


if __name__ == "__main__":
    main()
