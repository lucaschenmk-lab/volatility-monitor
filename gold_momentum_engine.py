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
    cmd = ["curl", "-s", XAU_API]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except:
        return None

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
# 交易信号引擎 (追击模式 v2)
# ============================================================
# 激进参数 — 每次波段目标净赚 100-300 元
PROFIT_TARGET = 0.12      # 止盈阈值 0.12% ≈ +1.0元/克 ≈ +114元
STOP_LOSS_PCT = -0.30     # 止损阈值 -0.30%
REBUY_DISCOUNT = 0.30     # 回购折扣：比卖出价低 0.30% 才买回（覆盖价差+微利）
BREAKOUT_CONFIRM = 0.15   # 突破确认幅度
LONDON_LEAD = 0.20        # 伦敦金领先阈值 (%)

# 全局状态（跨循环记忆 + 文件持久化）
_last_sell_price = None   # 上次卖出价，用于计算回购时机
_last_sell_time = None
_trade_log = []            # 交易日志
STATE_FILE = "gold_engine_state.json"  # 云端持久化文件

def load_state():
    """从文件加载状态（GitHub Actions 跨运行持久化）"""
    global _last_sell_price, _last_sell_time, _trade_log
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                s = json.load(f)
            _last_sell_price = s.get("last_sell_price")
            _last_sell_time = s.get("last_sell_time")
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
                "trade_log": _trade_log[-20:],  # 只保留最近20条
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, f, indent=2)
    except:
        pass

def generate_signal(market, london, history, asset):
    """生成激进交易信号 — 追击模式"""
    global _last_sell_price, _last_sell_time, _trade_log
    
    if not market or not history:
        return {"action": "HOLD", "reason": "数据不足"}
    
    buy_price = float(market["buyPrice"])
    sell_price = float(market["sellPrice"])
    spread = buy_price - sell_price
    
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
    
    # ============================================
    # 🔥 追击模式 — 卖出信号
    # ============================================
    if hold_weight > 0:
        # 🎯 微利止盈：盈利 ≥ 0.12% + 3分钟动量转负
        if profit_pct >= PROFIT_TARGET and m3 < -0.1:
            signal["action"] = "SELL_PROFIT"
            signal["reason"] = f"微利止盈 +{profit_pct:.2f}% 3m动量{m3:+.1f}"
        
        # 🏔️ 高位衰竭：日内高位 80%+ 且 5分钟动量快速转负
        elif sr and sr["position"] > 80 and m5 < -0.5:
            signal["action"] = "SELL_PEAK"
            signal["reason"] = f"高位衰竭 {sr['position']:.0f}% 5m动量{m5:+.1f}"
        
        # ⚡ 动量急转：15分钟连续下跌 + 跌破均价
        elif m15 < -1.0 and sr and buy_price < sr["avg"]:
            signal["action"] = "STOP_LOSS"
            signal["reason"] = f"动量急转 15m{m15:+.1f} 跌破均线{sr['avg']}"
        
        # 🛑 硬止损：亏损 ≥ 0.30%
        elif profit_pct <= STOP_LOSS_PCT:
            signal["action"] = "STOP_LOSS"
            signal["reason"] = f"硬止损 {profit_pct:.2f}% 保护本金"
        
        # 🚀 突破回踩：短暂突破前高后回落（假突破出货）
        elif sr and float(sr["high"]) > 0 and buy_price < float(sr["high"]) - 1.0 and m5 < -0.3 and profit_pct > 0:
            signal["action"] = "SELL_PEAK"
            signal["reason"] = f"假突破回踩 高{sr['high']} 现{buy_price:.1f}"
    
    # ============================================
    # 🔥 追击模式 — 买入信号
    # ============================================
    if available > 1500:
        # 🎯 回购：相对上次卖出价有足够折扣
        if _last_sell_price and hold_weight == 0:
            discount_pct = (_last_sell_price - buy_price) / _last_sell_price * 100
            if discount_pct >= REBUY_DISCOUNT and m3 > 0:
                signal["action"] = "BUY_REBUY"
                signal["reason"] = f"回购 卖{_last_sell_price:.1f}→买{buy_price:.1f} 折扣{discount_pct:.2f}%"
        
        # 📈 V型反转：15分钟急跌 + 3分钟急涨
        if m15 < -1.5 and m3 > 0.6:
            signal["action"] = "BUY_V"
            signal["reason"] = f"V反! 15m{m15:+.1f}→3m{m3:+.1f}"
        
        # 🌊 支撑抄底：价格在日内低位 15%- 且动量转正
        if sr and sr["position"] < 15 and score > 0.15:
            signal["action"] = "BUY_DIP"
            signal["reason"] = f"支撑抄底 {sr['position']:.0f}% 动量{score:+.1f}"
        
        # 🔥 伦敦金领先：伦敦金涨但积存金未跟（套利）
        if london_gram > 0 and implied_cn > 0:
            london_pct = (london_gram / (london_gram + 0.01) - 1) * 100  # 近似
            if m3 > 0.3 and buy_price < implied_cn * 0.998:
                signal["action"] = "BUY_ARB"
                signal["reason"] = f"伦敦金套利 隐含价{implied_cn:.1f} 现价{buy_price:.1f}"
        
        # 📊 突破追涨：突破日内高点 + 动量加速
        if sr and float(sr["high"]) > 0:
            breakout = (buy_price - float(sr["high"])) / float(sr["high"]) * 100
            if breakout > 0.05 and score > 0.4:
                signal["action"] = "BUY_BREAK"
                signal["reason"] = f"突破追涨 +{breakout:.2f}% 动量{score:+.1f}"
    
    # 金价接近强支撑 870
    if buy_price <= 872.5:
        signal["note"] = "⚠️ 逼近870强支撑，准备抄底"
    
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
    
    # 并行获取数据
    london = get_london_gold()
    market = get_market_current()
    history = get_minute_history(30)
    asset = get_asset()
    
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
    global _last_sell_price, _last_sell_time, _trade_log
    
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
        tag = {"SELL_PROFIT": "💰止盈", "SELL_PEAK": "🏔️逃顶", "STOP_LOSS": "🛑止损"}.get(action, "🔻卖出")
        print(f"   {tag} {vol}g × {sell_price} = {amount}元")
        
        resp = trade_sell(vol, amount, sell_price, sell_id)
        if resp:
            try:
                ds = resp["data"]["raw_result"]["body"]["data"]["downstream_response"]
                if ds.get("success"):
                    r = ds["result"]
                    _last_sell_price = sell_price
                    _last_sell_time = datetime.now().strftime("%H:%M:%S")
                    _trade_log.append({
                        "time": _last_sell_time,
                        "action": "SELL",
                        "vol": r.get("cfmVol"),
                        "price": r.get("cfmPrice"),
                        "balance": r.get("availableBalance"),
                    })
                    profit_est = (float(r.get("cfmPrice", sell_price)) - hold_cost) * float(r.get("cfmVol", vol))
                    print(f"   ✅ 成交! {r.get('cfmVol')}g @ {r.get('cfmPrice')} | 余额:{r.get('availableBalance')} | 实盈≈{profit_est:.0f}")
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
        if action in ("BUY_REBUY", "BUY_V", "BUY_DIP", "BUY_ARB", "BUY_BREAK"):
            amount = max_amount
        else:
            amount = max_amount
        
        if amount < 1500:
            amount = 1500
        
        tag = {
            "BUY_REBUY": "🔄回购",
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
                    print(f"   ✅ 成交! {r.get('cfmVol')}g @ {r.get('cfmPrice')} | 余额:{r.get('availableBalance')}{rebuy_gain}")
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
    parser.add_argument("--interval", type=int, default=60,
                       help="daemon 模式扫描间隔(秒), 默认60")
    parser.add_argument("--cooldown", type=int, default=120,
                       help="交易冷却时间(秒), 默认120")
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

            # 获取数据
            market = get_market_current()
            if not market:
                print(f"[{now_str}] ⚠️ 行情获取失败，30秒后重试...")
                time.sleep(30)
                continue

            history = get_minute_history(30)
            asset = get_asset()
            london = get_london_gold()

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
            
            print(f"[{now_str}] #{loop_count} {cooldown_mark} 买{buy:.1f}{lx_str} 动量{score:+.1f}{vol_str} {pos_str}{profit_str} → {action}")

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
