#!/usr/bin/env python3
"""
核心数据获取与指标计算模块
========================
被 CLI 版本 (volatility_monitor.py) 和 GUI 版本 (app.py) 共用。
"""

import warnings
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# ─── 配置 ───
FRED_SERIES_HY = "BAMLH0A0HYM2"
FRED_SERIES_IG = "BAMLC0A0CM"
FRED_API_KEY = ""

ETF_HYG = "HYG"
ETF_LQD = "LQD"

VIX_SYMBOL = "^VIX"
VIX9D_SYMBOL = "^VIX9D"
VIX3M_SYMBOL = "^VIX3M"
SPX_SYMBOL = "^GSPC"

RV_WINDOW = 20
TRADING_DAYS = 252
CREDIT_STD_LOOKBACK = 60


# ─── 数据获取 ───

def fetch_yf(symbol: str, period: str = "1y") -> Optional:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def get_credit_spread_fred(series_id: str, days: int = 90) -> Optional:
    if not FRED_API_KEY:
        return None
    try:
        import requests
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}"
            f"&file_type=json&observation_start={start}&observation_end={end}"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        obs = data.get("observations", [])
        vals = [float(o["value"]) for o in obs if o["value"] != "."]
        return np.array(vals) if vals else None
    except Exception:
        return None


def get_credit_spread_etf_proxy(days: int = 90) -> Optional:
    hy_df = fetch_yf(ETF_HYG, f"{days}d")
    lqd_df = fetch_yf(ETF_LQD, f"{days}d")
    if hy_df is None or lqd_df is None or hy_df.empty or lqd_df.empty:
        return None
    common = hy_df["Close"].index.intersection(lqd_df["Close"].index)
    if len(common) < 10:
        return None
    ratio = hy_df["Close"].loc[common] / lqd_df["Close"].loc[common]
    return (-np.log(ratio)).values


def get_credit_spread_etf_yield_diff(days: int = 90) -> Optional:
    hy_df = fetch_yf(ETF_HYG, f"{days}d")
    lqd_df = fetch_yf(ETF_LQD, f"{days}d")
    if hy_df is None or lqd_df is None:
        return None
    hy_ret = hy_df["Close"].pct_change().dropna()
    lqd_ret = lqd_df["Close"].pct_change().dropna()
    common_idx = hy_ret.index.intersection(lqd_ret.index)
    if len(common_idx) < 10:
        return None
    spread_change = lqd_ret.loc[common_idx] - hy_ret.loc[common_idx]
    return spread_change.cumsum().values


# ─── 指标计算 ───

def calc_vix_percentile(df) -> dict:
    r = {"value": None, "threshold": ">过去1年80分位", "triggered": False,
         "detail": "", "raw_value": None, "name": "VIX历史百分位",
         "short": "VIX百分位", "interpretation": "从低位翻倍领先回撤约1-4周"}
    if df is None or len(df) < 20:
        r["detail"] = "数据不足"
        return r
    close = df["Close"].dropna()
    if len(close) < 20:
        r["detail"] = "数据不足"
        return r
    current = close.iloc[-1]
    p80 = np.percentile(close, 80)
    min_vix = close.min()
    doubled = (current / min_vix) >= 2.0 if min_vix > 0 else False
    percentile = (close < current).mean() * 100
    above_p80 = current > p80
    triggered = above_p80 and doubled

    r["value"] = f"{current:.2f}"
    r["raw_value"] = current
    r["triggered"] = triggered
    r["percentile"] = round(percentile, 0)
    r["p80"] = round(p80, 1)
    r["min_vix"] = round(min_vix, 1)
    r["doubled"] = doubled
    r["detail"] = (f"当前VIX={current:.1f} | {percentile:.0f}百分位 | "
                   f"80分位={p80:.1f} | 1年最低={min_vix:.1f} | "
                   f"{'✅翻倍' if doubled else '未翻倍'}")
    return r


def calc_vix_term_structure(df9d, df, df3m) -> dict:
    r = {"value": None, "threshold": "比值>1=倒挂", "triggered": False,
         "detail": "", "raw_value": None, "name": "VIX期限结构(VIX9D/VIX3M)",
         "short": "VIX期限结构", "interpretation": "Contango突转倒挂=大回撤最强信号之一"}
    if any(x is None for x in [df9d, df, df3m]):
        r["detail"] = "数据不足"
        return r
    try:
        vix9d = df9d["Close"].dropna()
        vix = df["Close"].dropna()
        vix3m = df3m["Close"].dropna()
        if any(len(x) < 2 for x in [vix9d, vix, vix3m]):
            r["detail"] = "数据不足"
            return r

        cur9d = vix9d.iloc[-1]
        cur = vix.iloc[-1]
        cur3m = vix3m.iloc[-1]
        ratio = cur9d / cur3m if cur3m > 0 else 0

        min_p = min(20, len(vix9d), len(vix3m))
        recent_ratios = (vix9d.iloc[-min_p:] / vix3m.iloc[-min_p:].values).values
        was_contango = recent_ratios[:-1].mean() < 0.98
        is_backwardation = ratio > 1.0
        ctb = was_contango and is_backwardation
        triggered = ctb or ratio > 1.02

        r["value"] = f"{ratio:.3f}"
        r["raw_value"] = ratio
        r["triggered"] = triggered
        r["vix9d"] = round(cur9d, 1)
        r["vix"] = round(cur, 1)
        r["vix3m"] = round(cur3m, 1)
        r["is_backwardation"] = is_backwardation
        r["ctb"] = ctb
        r["detail"] = (f"VIX9D={cur9d:.1f} | VIX={cur:.1f} | VIX3M={cur3m:.1f} | "
                       f"比值={ratio:.3f} | "
                       f"{'🔴倒挂' if ratio > 1 else 'Contango'}"
                       f"{' ⚠转倒挂' if ctb else ''}")
    except Exception as e:
        r["detail"] = f"计算异常: {e}"
    return r


def calc_rv_iv_ratio(spx_df, vix_df) -> dict:
    r = {"value": None, "threshold": "比值>1(RV突破IV)", "triggered": False,
         "detail": "", "raw_value": None, "name": "RV/IV比值",
         "short": "RV/IV比值", "interpretation": "市场低估风险，回撤可能超预期"}
    if spx_df is None or vix_df is None:
        r["detail"] = "数据不足"
        return r
    try:
        spx_c = spx_df["Close"].dropna()
        vix_c = vix_df["Close"].dropna()
        if len(spx_c) < RV_WINDOW + 5 or len(vix_c) < 2:
            r["detail"] = "数据不足"
            return r

        spx_ret = spx_c.pct_change().dropna()
        rv = spx_ret.iloc[-RV_WINDOW:].std() * np.sqrt(TRADING_DAYS)
        iv = vix_c.iloc[-1] / 100
        ratio = rv / iv if iv > 0 else 0
        triggered = ratio > 1.0

        r["value"] = f"{ratio:.2f}"
        r["raw_value"] = ratio
        r["triggered"] = triggered
        r["rv"] = round(rv * 100, 1)
        r["iv"] = round(iv * 100, 1)
        r["detail"] = (f"RV(20日)={rv*100:.1f}% | IV(VIX)={iv*100:.1f}% | "
                       f"RV/IV={ratio:.2f} | "
                       f"{'🔴RV突破IV' if triggered else 'IV覆盖RV'}")
    except Exception as e:
        r["detail"] = f"计算异常: {e}"
    return r


def calc_credit_spread(spx_df=None) -> dict:
    r = {"value": None, "threshold": "快速走扩/突破均值+1.5σ", "triggered": False,
         "detail": "", "raw_value": None, "name": "信用利差HY-IG(变化)",
         "short": "信用利差", "interpretation": "利差走扩确认系统性风险，非单一资产"}
    hy_vals = get_credit_spread_fred(FRED_SERIES_HY)
    ig_vals = get_credit_spread_fred(FRED_SERIES_IG)
    if hy_vals is not None and ig_vals is not None and len(hy_vals) > 10:
        spread = hy_vals - ig_vals
    else:
        spread = get_credit_spread_etf_yield_diff()
        if spread is None:
            spread = get_credit_spread_etf_proxy()
        if spread is None:
            r["detail"] = "无信用利差数据源"
            return r
    try:
        lookback = min(len(spread), CREDIT_STD_LOOKBACK)
        recent = spread[-lookback:]
        mean = np.mean(recent[:-1])
        std = np.std(recent[:-1])
        current = recent[-1]
        daily_change = current - recent[-5] if len(recent) >= 5 else 0
        threshold_val = mean + 1.5 * std
        triggered = current > threshold_val

        r["value"] = f"{current:.3f}"
        r["raw_value"] = current
        r["triggered"] = triggered
        r["mean"] = round(mean, 3)
        r["std"] = round(std, 3)
        r["threshold_val"] = round(threshold_val, 3)
        r["daily_change"] = round(daily_change, 3)
        r["detail"] = (f"当前利差={current:.3f} | 均值={mean:.3f} | "
                       f"1.5σ阈值={threshold_val:.3f} | "
                       f"近5日变化={daily_change:+.3f} | "
                       f"{'🔴突破阈值' if triggered else '正常区间'}")
    except Exception as e:
        r["detail"] = f"计算异常: {e}"
    return r


# ─── 统一入口 ───

def fetch_all_indicators(fred_key: str = "", date_str: str = "") -> Dict:
    """一次性获取所有指标，返回结构化结果"""
    global FRED_API_KEY
    if fred_key:
        FRED_API_KEY = fred_key

    monitor_date = date_str if date_str else datetime.now().strftime("%Y-%m-%d")

    vix_df = fetch_yf(VIX_SYMBOL, "1y")
    vix9d_df = fetch_yf(VIX9D_SYMBOL, "6mo")
    vix3m_df = fetch_yf(VIX3M_SYMBOL, "6mo")
    spx_df = fetch_yf(SPX_SYMBOL, "1y")

    indicators = [
        calc_vix_percentile(vix_df),
        calc_vix_term_structure(vix9d_df, vix_df, vix3m_df),
        calc_rv_iv_ratio(spx_df, vix_df),
        calc_credit_spread(spx_df),
    ]

    triggered_count = sum(1 for ind in indicators if ind["triggered"])

    if triggered_count >= 2:
        risk_level = "high"
        risk_text = "🔴 高回撤风险期 — 建议降仓或买保护"
    elif triggered_count == 1:
        risk_level = "watch"
        risk_text = "🟡 关注 — 已有1项触发，持续监控"
    else:
        risk_level = "low"
        risk_text = "🟢 低风险 — 所有指标正常"

    return {
        "monitor_date": monitor_date,
        "indicators": indicators,
        "triggered_count": triggered_count,
        "risk_level": risk_level,
        "risk_text": risk_text,
        "success": True,
    }
