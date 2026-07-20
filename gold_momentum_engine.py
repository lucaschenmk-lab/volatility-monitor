#!/usr/bin/env python3
"""
积存金模拟大赛 — 动量高频交易引擎
双轨策略：伦敦金(XAU/USD)宏观动量 + 积存金微观波动
目标：总榜第一 + 每周AI冠军
"""

import subprocess
import json
import time
import sys
import os
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 配置
# ============================================================
API_KEY = os.environ.get("TTFUND_APIKEY", "")
GATEWAY = "https://skills.tiantianfunds.com/ai-smart-skill-service/openapi/skill/invoke"
GROUP_ID = "20260720"
SIM_ACCOUNT = "337576973610618880"
VERSION = "1.0.2"

# 交易参数
SPREAD = 3.80          # 买卖价差 (buy - sell)
MIN_WAVE = SPREAD + 1.0  # 最小波段幅度，覆盖价差后有利润
COST_PRICE = 876.32    # 当前持仓成本
HOLD_WEIGHT = 114.10   # 当前持仓克重

# 伦敦金参数
XAU_API = "https://api.gold-api.com/price/XAU"
OZ_TO_GRAM = 31.1035
CNY_USD_EST = 6.78     # 估算汇率

# ============================================================
# API 调用
# ============================================================
def call_gateway(action, extra=None):
    """调用天天基金 Skill 网关"""
    body = {
        "skill_id": "SIM_GOLD_MATCH",
        "_skill_version": VERSION,
        "action": action
    }
    if extra:
        body.update(extra)
    
    cmd = [
        "curl", "-s", "-X", "POST", GATEWAY,
        "-H", "Content-Type: application/json",
        "-H", f"X-API-Key: {API_KEY}",
        "-d", json.dumps(body)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except:
        return None

def get_london_gold():
    """获取伦敦金 XAU/USD 实时价格"""
    cmd = ["curl", "-s", "--connect-timeout", "5", "--max-time", "8", XAU_API]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except:
        return None

def fetch_all():
    """并行获取全部数据 — 4路并发，总耗时≈最慢那路"""
    results = {"market": None, "history": None, "asset": None, "london": None}
    tasks = {
        "market": lambda: get_market_current(),
        "history": lambda: get_minute_history(20),  # 减少到20根K线提速
        "asset": lambda: get_asset(),
        "london": lambda: get_london_gold(),
    }
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn): key for key, fn in tasks.items()}
        for fut in as_completed(futures, timeout=12):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except:
                pass
    return results["market"], results["history"], results["asset"], results["london"]

def get_market_current():
    """获取积存金当前行情"""
    resp = call_gateway("market_current")
    if not resp or resp.get("code") != 0:
        return None
    try:
        ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
        return ds["result"]
    except:
        return None

def get_asset():
    """获取资产概览"""
    resp = call_gateway("asset_overview", {
        "groupId": GROUP_ID,
        "simAccountId": SIM_ACCOUNT
    })
    if not resp or resp.get("code") != 0:
        return None
    try:
        ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
        return ds["result"]
    except:
        return None

def get_minute_history(limit=30):
    """获取分钟K线"""
    resp = call_gateway("market_history", {
        "periodType": "MINUTE",
        "limit": limit
    })
    if not resp or resp.get("code") != 0:
        return None
    try:
        ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
        return ds["result"]
    except:
        return None

def trade_buy(amount, price, price_id):
    """买入"""
    resp = call_gateway("trade_buy", {
        "groupId": GROUP_ID,
        "simAccountId": SIM_ACCOUNT,
        "appAmount": str(amount),
        "appPrice": str(price),
        "appPriceId": price_id
    })
    return resp

def trade_sell(vol, amount, price, price_id):
    """卖出"""
    resp = call_gateway("trade_sell", {
        "groupId": GROUP_ID,
        "simAccountId": SIM_ACCOUNT,
        "appVol": str(vol),
        "appAmount": str(amount),
        "appPrice": str(price),
        "appPriceId": price_id
    })
    return resp

# ============================================================
# 动量计算
# ============================================================
def calc_momentum(prices, periods=[5, 10, 15, 30]):
    """
    计算多周期动量
    prices: list of (time, close_price)
    返回: {period: momentum_value}
    """
    result = {}
    closes = [p[1] for p in prices]
    
    for period in periods:
        if len(closes) > period:
            momentum = closes[-1] - closes[-(period+1)]
            pct = momentum / closes[-(period+1)] * 100
            result[f"m{period}"] = {"abs": round(momentum, 2), "pct": round(pct, 4)}
    
    # 加权动量得分
    if len(closes) >= 30:
        weights = {5: 0.45, 10: 0.30, 15: 0.15, 30: 0.10}
        score = 0
        for period, w in weights.items():
            if len(closes) > period:
                score += (closes[-1] - closes[-(period+1)]) * w
        result["score"] = round(score, 2)
    
    return result

def calc_support_resistance(prices):
    """计算日内支撑和阻力位"""
    closes = [p[1] for p in prices]
    if not closes:
        return None
    
    high = max(p[3] for p in prices) if len(prices[0]) > 3 else max(closes)
    low = min(p[4] for p in prices) if len(prices[0]) > 4 else min(closes)
    current = closes[-1]
    avg = sum(closes) / len(closes)
    
    return {
        "high": round(high, 2),
        "low": round(low, 2),
        "current": round(current, 2),
        "avg": round(avg, 2),
        "range": round(high - low, 2),
        "position": round((current - low) / (high - low) * 100, 1) if high != low else 50
    }

# ============================================================
# 交易信号引擎 (追击模式 v3 — 全激进)
# ============================================================

# ---- 时段感知参数 ----
# 死水期 11:30-14:30 | 欧盘 15:00-17:30 | 美盘 20:00-23:00 | 其余为过渡期
def get_session_params():
    """根据北京时间返回当前时段的激进参数"""
    h = datetime.now().hour
    m = datetime.now().minute
    t = h + m / 60.0
    
    if 11.5 <= t < 14.5:
        # 🕐 死水期：波动小，收紧止盈，放宽止损防毛刺
        return {
            "name": "死水期",
            "profit_target": 0.30,     # 0.30% ≈ 2.6元/克，覆盖价差后微利
            "stop_loss": -0.55,         # 宽止损防毛刺
            "stop_loss_lowvol": -0.70,
            "rebuy_discount": 0.20,
            "chase_threshold": 0.20,
            "momentum_stop": -1.2,      # 动量急转阈值（较低，死水期少见）
        }
    elif 15.0 <= t < 17.5:
        # 🇪🇺 欧盘：波动放大，正常止盈+紧止损
        return {
            "name": "欧盘",
            "profit_target": 0.45,     # 覆盖价差(0.43%)+利润
            "stop_loss": -0.35,
            "stop_loss_lowvol": -0.50,
            "rebuy_discount": 0.30,
            "chase_threshold": 0.30,
            "momentum_stop": -1.8,
        }
    elif 20.0 <= t < 23.0:
        # 🇺🇸 美盘：最大波动，激进止盈+适度止损
        return {
            "name": "美盘",
            "profit_target": 0.55,     # 大波段目标
            "stop_loss": -0.30,
            "stop_loss_lowvol": -0.40,
            "rebuy_discount": 0.35,
            "chase_threshold": 0.35,
            "momentum_stop": -2.0,
        }
    else:
        # 🌅 过渡期：均衡参数
        return {
            "name": "过渡期",
            "profit_target": 0.40,
            "stop_loss": -0.40,
            "stop_loss_lowvol": -0.55,
            "rebuy_discount": 0.25,
            "chase_threshold": 0.25,
            "momentum_stop": -1.5,
        }

# ---- 背离检测 ----
def detect_divergence(prices):
    """
    检测价格与动量的背离
    返回: 'bearish' (价创新高但动量衰减) | 'bullish' (价创新低但动量回升) | None
    """
    if len(prices) < 15:
        return None
    
    closes = [p[1] for p in prices]
    highs = [p[3] for p in prices if len(p) > 3]
    lows = [p[4] for p in prices if len(p) > 4]
    
    if not highs or not lows:
        return None
    
    # 最近5分钟 vs 前10分钟
    recent = closes[-5:]
    earlier = closes[-15:-5]
    
    recent_high = max(highs[-5:]) if len(highs) >= 5 else max(recent)
    earlier_high = max(highs[-15:-5]) if len(highs) >= 15 else max(earlier)
    recent_low = min(lows[-5:]) if len(lows) >= 5 else min(recent)
    earlier_low = min(lows[-15:-5]) if len(lows) >= 15 else min(earlier)
    
    recent_momentum = sum(recent) / len(recent) - sum(earlier) / len(earlier)
    
    # 顶背离：价格创新高但动量衰减
    if recent_high > earlier_high and recent_momentum < -0.2:
        return "bearish"
    
    # 底背离：价格创新低但动量回升
    if recent_low < earlier_low and recent_momentum > 0.2:
        return "bullish"
    
    return None

# 全局状态（跨循环记忆 + 文件持久化）
_last_sell_price = None   # 上次卖出价，用于计算回购时机
_last_sell_time = None
_last_trade_time = 0       # 上次交易时间戳（防频繁交易）
_last_trade_dir = None     # 上次交易方向 'BUY'/'SELL'
_trade_log = []            # 交易日志
STATE_FILE = "gold_engine_state.json"  # 云端持久化文件
SAME_DIR_COOLDOWN = 1800   # 同方向冷却 30 分钟
CHASE_REQUIRE_DISCOUNT = True  # 追回必须低于卖出价

def load_state():
    """从文件加载状态（GitHub Actions 跨运行持久化）"""
    global _last_sell_price, _last_sell_time, _trade_log
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                s = json.load(f)
            _last_sell_price = s.get("last_sell_price")
            _last_sell_time = s.get("last_sell_time")
            _last_trade_time = s.get("last_trade_time", 0)
            _last_trade_dir = s.get("last_trade_dir")
            _trade_log = s.get("trade_log", [])
            return True
    except:
        pass
    return False

def save_state():
    """保存状态到文件"""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "last_sell_price": _last_sell_price,
                "last_sell_time": _last_sell_time,
                "last_trade_time": _last_trade_time,
                "last_trade_dir": _last_trade_dir,
                "trade_log": _trade_log[-20:],
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, f, indent=2)
    except:
        pass

def generate_signal(market, london, history, asset):
    """生成激进交易信号 — 追击模式"""
    global _last_sell_price, _last_sell_time, _trade_log, _last_trade_time, _last_trade_dir
    
    if not market or not history:
        return {"action": "HOLD", "reason": "数据不足"}
    
    buy_price = float(market["buyPrice"])
    sell_price = float(market["sellPrice"])
    spread = buy_price - sell_price
    
    # ⛔ 同方向冷却检查：30分钟内不重复同向交易
    same_dir_blocked = False
    if _last_trade_time and _last_trade_dir:
        elapsed = time.time() - _last_trade_time
        if elapsed < SAME_DIR_COOLDOWN:
            same_dir_blocked = True
    
    # 解析K线数据
    klines = history.get("list", [])
    prices = []
    for k in klines:
        try:
            prices.append((k["priceTime"], float(k["closePrice"]), 
                          float(k["openPrice"]), float(k["highPrice"]), float(k["lowPrice"])))
        except:
            continue
    
    momentum = calc_momentum(prices)
    sr = calc_support_resistance(prices)
    
    # 额外动量周期
    m3_prices = [(p[0], p[1]) for p in prices]
    m3 = calc_momentum(m3_prices, periods=[3]).get("m3", {}).get("abs", 0)
    
    # 伦敦金价格
    london_price = london.get("price", 0) if london else 0
    london_gram = london_price / OZ_TO_GRAM if london_price else 0
    
    # 伦敦金隐含积存金价格
    implied_cn = london_gram * CNY_USD_EST if london_gram else 0
    
    # 资产数据
    asset_data = asset or {}
    hold_weight = float(asset_data.get("holdWeight", 0))
    hold_cost = float(asset_data.get("holdCost", COST_PRICE))
    available = float(asset_data.get("availableBalance", 0))
    profit = float(asset_data.get("holdProfit", 0))
    total_asset = float(asset_data.get("totalAsset", 100000))
    
    score = momentum.get("score", 0)
    m5 = momentum.get("m5", {}).get("abs", 0)
    m15 = momentum.get("m15", {}).get("abs", 0)
    
    # 波动率（最近30分钟标准差）
    closes_30 = [p[1] for p in prices[-30:]]
    if len(closes_30) >= 5:
        avg_c = sum(closes_30) / len(closes_30)
        volatility = (sum((c - avg_c)**2 for c in closes_30) / len(closes_30)) ** 0.5
    else:
        volatility = 1.0
    
    signal = {
        "action": "HOLD",
        "reason": "",
        "buy_price": buy_price,
        "sell_price": sell_price,
        "momentum": momentum,
        "support_resistance": sr,
        "london_xau": london_price,
        "london_gram": round(london_gram, 2) if london_gram else 0,
        "implied_cn": round(implied_cn, 2) if implied_cn else 0,
        "profit": profit,
        "total_asset": total_asset,
        "volatility": round(volatility, 2),
    }
    
    # 仓位状态
    if hold_weight == 0:
        position = "空仓"
    elif hold_weight < 30:
        position = "轻仓"
    elif hold_weight < 80:
        position = "半仓"
    else:
        position = "满仓"
    signal["position"] = position
    
    profit_pct = (buy_price - hold_cost) / hold_cost * 100 if hold_cost > 0 else 0
    signal["profit_pct"] = round(profit_pct, 3)

    # 时段参数
    sess = get_session_params()
    signal["session"] = sess["name"]
    
    # 背离检测
    divergence = detect_divergence(prices)
    if divergence:
        signal["divergence"] = divergence
    
    # ============================================
    # 🔥 v3 卖出信号
    # ============================================
    if hold_weight > 0:
        sell_blocked = same_dir_blocked and _last_trade_dir == "SELL"
        
        # 🚨 顶背离：价格创新高但动量衰减 → 最佳逃顶点
        if divergence == "bearish" and profit_pct > 0.15 and not sell_blocked:
            signal["action"] = "SELL_DIVERGENCE"
            signal["reason"] = f"顶背离! 价创新高+动量衰减 盈利{profit_pct:.2f}%"
        
        # 🎯 止盈：时段自适应阈值 + 3分钟动量转负
        elif profit_pct >= sess["profit_target"] and m3 < -0.1 and not sell_blocked:
            signal["action"] = "SELL_PROFIT"
            signal["reason"] = f"止盈 +{profit_pct:.2f}% [{sess['name']}阈值{sess['profit_target']:.2f}%] 3m动量{m3:+.1f}"
        
        # 🏔️ 高位衰竭：日内高位 75%+ 且 5分钟动量急转
        elif sr and sr["position"] > 75 and m5 < -0.6 and not sell_blocked:
            signal["action"] = "SELL_PEAK"
            signal["reason"] = f"高位衰竭 {sr['position']:.0f}% 5m动量{m5:+.1f}"
        
        # ⚡ 动量急转：时段自适应阈值 + 跌破均价
        elif m15 < sess["momentum_stop"] and sr and buy_price < sr["avg"] and volatility > 0.5:
            signal["action"] = "STOP_LOSS"
            signal["reason"] = f"动量急转 15m{m15:+.1f} 跌破均线 [{sess['name']}]"
        
        # 🛑 硬止损：波动率自适应
        elif profit_pct <= (sess["stop_loss_lowvol"] if volatility < 0.5 else sess["stop_loss"]):
            if volatility >= 0.5 or m5 < -0.15:
                signal["action"] = "STOP_LOSS"
                signal["reason"] = f"止损 {profit_pct:.2f}% σ{volatility:.1f} [{sess['name']}]"
        
        # 🚀 假突破回踩
        elif sr and float(sr["high"]) > 0 and buy_price < float(sr["high"]) - 0.8 and m5 < -0.3 and profit_pct > 0 and not sell_blocked:
            signal["action"] = "SELL_PEAK"
            signal["reason"] = f"假突破 高{sr['high']} 现{buy_price:.1f}"
        
        elif sell_blocked:
            signal["note"] = f"⛔ 卖出冷却中 ({int(SAME_DIR_COOLDOWN - (time.time() - _last_trade_time))}s)"
    
    # ============================================
    # 🔥 v3 买入信号
    # ============================================
    if available > 1500:
        buy_blocked = same_dir_blocked and _last_trade_dir == "BUY"
        # 💡 底背离：价格创新低但动量回升 → 最佳抄底点
        if divergence == "bullish" and hold_weight == 0:
            signal["action"] = "BUY_DIVERGENCE"
            signal["reason"] = f"底背离! 价创新低+动量回升"
        
        # 🔄 回购/追回逻辑（空仓时）
        if _last_sell_price and hold_weight == 0:
            gain_pct = (_last_sell_price - buy_price) / _last_sell_price * 100
            
            # ① 折扣回购
            if gain_pct >= sess["rebuy_discount"] and m3 > 0:
                signal["action"] = "BUY_REBUY"
                signal["reason"] = f"回购 卖{_last_sell_price:.1f}→买{buy_price:.1f} 折扣{gain_pct:.2f}%"
            
            # ② 追回：趋势反转确认 + ⛔必须低于卖出价
            elif (m5 > sess["chase_threshold"] and m15 > -0.2 
                  and sr and sr["position"] > 30 
                  and (not CHASE_REQUIRE_DISCOUNT or gain_pct > 0)):
                signal["action"] = "BUY_CHASE"
                signal["reason"] = f"追回! 5m{m5:+.1f} 15m{m15:+.1f} [{sess['name']}]"
        
        # 📈 V型反转
        if m15 < -1.5 and m3 > 0.6 and not buy_blocked:
            signal["action"] = "BUY_V"
            signal["reason"] = f"V反! 15m{m15:+.1f}→3m{m3:+.1f}"
        
        # 🌊 支撑抄底
        if sr and sr["position"] < 15 and score > 0.15 and not buy_blocked:
            signal["action"] = "BUY_DIP"
            signal["reason"] = f"抄底 {sr['position']:.0f}% 动量{score:+.1f}"
        
        # 💱 伦敦套利
        if london_gram > 0 and implied_cn > 0 and not buy_blocked:
            if m3 > 0.3 and buy_price < implied_cn * 0.998:
                signal["action"] = "BUY_ARB"
                signal["reason"] = f"伦敦套利 隐含{implied_cn:.1f} 现价{buy_price:.1f}"
        
        # 🚀 突破追涨
        if sr and float(sr["high"]) > 0 and not buy_blocked:
            breakout = (buy_price - float(sr["high"])) / float(sr["high"]) * 100
            if breakout > 0.03 and score > 0.4:
                signal["action"] = "BUY_BREAK"
                signal["reason"] = f"突破 +{breakout:.2f}% 动量{score:+.1f}"
        
        if buy_blocked and not signal["action"].startswith("BUY"):
            signal["note"] = f"⛔ 买入冷却中 ({int(SAME_DIR_COOLDOWN - (time.time() - _last_trade_time))}s)"
    
    # 金价接近强支撑 870
    if buy_price <= 872.5:
        signal["note"] = "⚠️ 逼近870强支撑，准备抄底"
    
    # ============================================
    # ⚡ 高波剥头皮模式（波动率 > 0.8，阈值 ≥ 0.5%）
    # ============================================
    if volatility > 0.8 and not signal["action"].startswith(("SELL", "BUY", "STOP")):
        sell_blocked = same_dir_blocked and _last_trade_dir == "SELL"
        # 持仓时：利润 ≥ 0.5% 才剥，防小波动折腾
        if hold_weight > 0 and profit_pct >= 0.50 and m3 < -0.1 and not sell_blocked:
            signal["action"] = "SELL_SCALP"
            signal["reason"] = f"⚡剥头皮 +{profit_pct:.2f}% 高波{volatility:.1f}"
        # 空仓剥头皮买入已禁用（太危险）
    
    return signal

# ============================================================
# 主循环
# ============================================================
def run_once():
    """执行一次监控+决策"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'='*60}")
    print(f"🕐 {now} | 积存金动量交易引擎")
    print(f"{'='*60}")
    
    # ⚡ 4路并发获取数据
    market, history, asset, london = fetch_all()
    
    if not market:
        print("❌ 无法获取行情数据")
        return None
    
    # 打印行情快照
    buy = float(market["buyPrice"])
    sell = float(market["sellPrice"])
    london_price = london.get("price", 0) if london else 0
    london_gram = london_price / OZ_TO_GRAM if london_price else 0
    implied_rate = buy / london_gram if london_gram > 0 else 0
    
    print(f"🏅 伦敦金: ${london_price:.0f}/oz (${london_gram:.1f}/g)")
    print(f"🇨🇳 积存金: 买 {buy:.2f} | 卖 {sell:.2f} | 价差 {buy-sell:.2f} | 汇率 {implied_rate:.4f}")
    
    if asset:
        profit = float(asset.get("holdProfit", 0))
        total = float(asset.get("totalAsset", 100000))
        weight = float(asset.get("holdWeight", 0))
        available = float(asset.get("availableBalance", 0))
        cost = float(asset.get("holdCost", 0))
        profit_pct = float(asset.get("holdProfitRate", 0)) * 100
        print(f"📊 持仓: {weight:.2f}g | 成本: {cost:.2f} | 盈亏: {profit:.2f} ({profit_pct:.3f}%)")
        print(f"💰 总资产: {total:.2f} | 可用: {available:.2f}")
    
    # 生成信号
    signal = generate_signal(market, london, history, asset)
    
    if signal:
        print(f"\n📡 动量得分: {signal['momentum'].get('score', 'N/A')} | 波动率: {signal.get('volatility', '?')}")
        if signal.get("support_resistance"):
            sr = signal["support_resistance"]
            print(f"📏 区间: {sr['low']}-{sr['high']} | 当前位置: {sr['position']}%")
        lx = signal.get("london_gram", 0)
        ic = signal.get("implied_cn", 0)
        if lx and ic:
            print(f"💱 伦敦金折价: {ic:.1f} vs 积存金 {signal['buy_price']:.1f} (差{signal['buy_price']-ic:.1f})")
        print(f"⚡ 信号: {signal['action']} | {signal.get('reason', '-')}")
        if signal.get("note"):
            print(f"📝 备注: {signal['note']}")
    
    return signal

def execute_trade(signal, market, asset):
    """根据信号执行交易 — 追击模式"""
    global _last_sell_price, _last_sell_time, _trade_log, _last_trade_time, _last_trade_dir
    
    action = signal.get("action", "HOLD")
    if action == "HOLD":
        return
    
    buy_price = float(market["buyPrice"])
    sell_price = float(market["sellPrice"])
    buy_id = market["buyPriceId"]
    sell_id = market["sellPriceId"]
    
    hold_weight = float(asset.get("holdWeight", 0))
    available = float(asset.get("availableBalance", 0))
    hold_cost = float(asset.get("holdCost", 0))
    
    # === 卖出 ===
    if action.startswith("SELL") or action == "STOP_LOSS":
        if hold_weight <= 0:
            print("   ⚠️ 无持仓可卖")
            return
        
        # 全仓卖出（激进模式不做半仓）
        vol = round(hold_weight, 2)
        if vol < 1.0:
            print(f"   ⚠️ 持仓{vol}g不足1g，无法普通卖出")
            return
        
        amount = round(vol * sell_price, 2)
        tag = {"SELL_PROFIT": "💰止盈", "SELL_DIVERGENCE": "🚨背离", "SELL_SCALP": "⚡剥头皮", "SELL_PEAK": "🏔️逃顶", "STOP_LOSS": "🛑止损"}.get(action, "🔻卖出")
        print(f"   {tag} {vol}g × {sell_price} = {amount}元")
        
        resp = trade_sell(vol, amount, sell_price, sell_id)
        if resp:
            try:
                ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
                if ds.get("success"):
                    r = ds["result"]
                    _last_sell_price = sell_price
                    _last_sell_time = datetime.now().strftime("%H:%M:%S")
                    _last_trade_time = time.time()
                    _last_trade_dir = "SELL"
                    _trade_log.append({
                        "time": _last_sell_time,
                        "action": "SELL",
                        "vol": r.get("cfmVol"),
                        "price": r.get("cfmPrice"),
                        "balance": r.get("availableBalance"),
                    })
                    profit_est = (float(r.get("cfmPrice", sell_price)) - hold_cost) * float(r.get("cfmVol", vol))
                    print(f"   ✅ 成交! {r.get('cfmVol')}g @ {r.get('cfmPrice')} | 余额:{r.get('availableBalance')} | 实盈≈{profit_est:.0f}")
                    save_state()  # 持久化
                else:
                    print(f"   ❌ 失败: {ds.get('message', 'unknown')}")
            except Exception as e:
                print(f"   ❌ 解析失败: {e}")
    
    # === 买入 ===
    elif action.startswith("BUY"):
        if available < 1500:
            print(f"   ⚠️ 余额{available}元 < 1500，无法买入")
            return
        
        max_amount = int(available)
        # 激进模式：全仓买入
        if action in ("BUY_REBUY", "BUY_CHASE", "BUY_DIVERGENCE", "BUY_V", "BUY_DIP", "BUY_ARB", "BUY_BREAK"):
            amount = max_amount
        else:
            amount = max_amount
        
        if amount < 1500:
            amount = 1500
        
        tag = {
            "BUY_REBUY": "🔄回购",
            "BUY_CHASE": "🏃追回",
            "BUY_DIVERGENCE": "💡底背离",
            "BUY_V": "📈V反",
            "BUY_DIP": "🌊抄底",
            "BUY_ARB": "💱套利",
            "BUY_BREAK": "🚀追涨",
        }.get(action, "🔺买入")
        
        print(f"   {tag} {amount}元 @ {buy_price} (预估{amount/buy_price:.2f}g)")
        
        resp = trade_buy(amount, buy_price, buy_id)
        if resp:
            try:
                ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
                if ds.get("success"):
                    r = ds["result"]
                    # 记录回购收益
                    rebuy_gain = ""
                    if _last_sell_price and action == "BUY_REBUY":
                        gain_per_g = _last_sell_price - float(r.get("cfmPrice", buy_price))
                        gain_total = gain_per_g * float(r.get("cfmVol", 0))
                        rebuy_gain = f" | 波段收益≈{gain_total:.0f}元"
                    _trade_log.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "action": "BUY",
                        "vol": r.get("cfmVol"),
                        "price": r.get("cfmPrice"),
                        "balance": r.get("availableBalance"),
                    })
                    _last_trade_time = time.time()
                    _last_trade_dir = "BUY"
                    print(f"   ✅ 成交! {r.get('cfmVol')}g @ {r.get('cfmPrice')} | 余额:{r.get('availableBalance')}{rebuy_gain}")
                    save_state()  # 持久化
                    # 重置卖出价
                    if action == "BUY_REBUY":
                        _last_sell_price = None
                else:
                    print(f"   ❌ 失败: {ds.get('message', 'unknown')}")
            except Exception as e:
                print(f"   ❌ 解析失败: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="积存金动量交易引擎")
    parser.add_argument("mode", nargs="?", default="monitor",
                       choices=["monitor", "auto", "daemon", "cloud"],
                       help="monitor=诊断, auto=单次交易, daemon=本地守护, cloud=GitHub Actions模式")
    parser.add_argument("--interval", type=int, default=20,
                       help="daemon 模式扫描间隔(秒), 默认20")
    parser.add_argument("--cooldown", type=int, default=30,
                       help="交易冷却时间(秒), 默认30")
    args = parser.parse_args()

    if args.mode == "cloud":
        # GitHub Actions 云端模式：加载状态 → 单次扫描 → 交易 → 保存状态 → 退出
        load_state()
        if _last_sell_price:
            print(f"📂 加载状态: 上次卖出价 {_last_sell_price}, 日志 {len(_trade_log)} 条")
        signal = run_once()
        if signal and signal["action"] != "HOLD":
            market = get_market_current()
            asset = get_asset()
            if market and asset:
                execute_trade(signal, market, asset)
        else:
            print("📊 无交易信号")
        save_state()
        print("💾 状态已保存")

    elif args.mode == "daemon":
        load_state()  # 启动时加载持久化状态
        if _last_sell_price:
            print(f"📂 加载状态: 上次卖出价 {_last_sell_price}, 日志 {len(_trade_log)} 条")
        print("🤖 全自动交易守护进程启动")
        print(f"   扫描间隔: {args.interval}s | 冷却时间: {args.cooldown}s")
        print(f"   交易时间: 09:10 - 次日 02:00")
        last_trade_time = 0
        trade_count = 0
        loop_count = 0

        while True:
            loop_count += 1
            now_ts = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            # 检查是否在交易时段
            hour = datetime.now().hour
            # 跳过凌晨2:00-9:10的休市时间
            if 2 <= hour < 9:
                if loop_count == 1:
                    print("⏸️ 当前在休市时段 (02:00-09:10)，等待开盘...")
                time.sleep(60)
                continue

            # 冷却期检查
            cooldown_remaining = args.cooldown - (now_ts - last_trade_time)
            in_cooldown = cooldown_remaining > 0

            # ⚡ 4路并发获取数据
            t0 = time.time()
            market, history, asset, london = fetch_all()
            if not market:
                print(f"[{now_str}] ⚠️ 行情获取失败，15秒后重试...")
                time.sleep(15)
                continue

            # 生成信号
            signal = generate_signal(market, london, history, asset)

            buy = float(market["buyPrice"])
            action = signal.get("action", "HOLD") if signal else "HOLD"
            score = signal.get("momentum", {}).get("score", 0) if signal else 0

            # 紧凑日志
            cooldown_mark = f"⏳{int(cooldown_remaining)}s" if in_cooldown else "⚡"
            profit_str = f" P/L:{signal.get('profit_pct', 0):.2f}%" if signal and signal.get("profit_pct") is not None else ""
            lx_str = f" XAU:{london.get('price',0):.0f}" if london else ""
            pos_str = signal.get("position", "?") if signal else "?"
            vol_str = f" σ:{signal.get('volatility',0):.1f}" if signal else ""
            
            sess = signal.get("session", "?") if signal else "?"
            div = f" {signal.get('divergence','')}" if signal and signal.get("divergence") else ""
            ms = int((time.time() - t0) * 1000)
            print(f"[{now_str}] #{loop_count} {cooldown_mark} 买{buy:.1f}{lx_str} 动量{score:+.1f}{vol_str} {pos_str}{profit_str} [{sess}]{div} {ms}ms → {action}")

            # 执行交易
            if action != "HOLD" and not in_cooldown and asset:
                execute_trade(signal, market, asset)
                last_trade_time = time.time()
                trade_count += 1
                print(f"   📊 累计交易: {trade_count} 笔")

            time.sleep(args.interval)

    elif args.mode == "auto":
        # 单次自动交易模式
        print("🤖 自动交易模式启动")
        signal = run_once()
        if signal and signal["action"] != "HOLD":
            market = get_market_current()
            asset = get_asset()
            if market and asset:
                execute_trade(signal, market, asset)
        else:
            print("📊 无交易信号，跳过")
    else:
        # 监控诊断模式
        signal = run_once()
