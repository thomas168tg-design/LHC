# -*- coding: utf-8 -*-
import json
import math
from datetime import datetime
from database import query, query_one, execute
from core import draws, prediction
from collections import Counter

STEP = 5  # 下注金额以5元为单位递增

def ceil_to_step(x, step=STEP):
    return math.ceil(x / step) * step

# ---------------- 方案管理 ----------------
def get_plans():
    _, rows = query("SELECT name, config_json FROM betting_plans ORDER BY id ASC")
    return [{"name": r[0], "config": json.loads(r[1])} for r in rows]

def save_plan(name, config):
    execute(
        "INSERT INTO betting_plans (name, config_json, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET config_json=excluded.config_json",
        [name, json.dumps(config), datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    )

def delete_plan(name):
    execute("DELETE FROM betting_plans WHERE name = ?", [name])

# ----------- 获取近365期的连黑分布-----------
def get_365_miss(model_name, codes_count, df, events):
    """获取近365期的连黑分布"""
    mp = prediction._build_cache(df, events, int(df["期数"].max()))
    items = sorted(mp.get(model_name, {}).items())[-365:]
    if not items: return {}
    
    hits = [1 if p <= codes_count else 0 for _, p in items]
    streaks_dict = Counter()
    cur = 0
    for h in hits:
        if h == 0: cur += 1
        else:
            if cur > 0: streaks_dict[cur] += 1
            cur = 0
    if cur > 0: streaks_dict[cur] += 1
    
    return dict(sorted(streaks_dict.items()))


# ---------------- 战报记录管理 ----------------
# 替换 get_records
def get_records(plan_name, limit=10):
    if limit == 0:
        sql = "SELECT id, issue, cost, revenue, profit, is_hit, bet_numbers, bet_amts FROM betting_records WHERE plan_name = ? ORDER BY issue DESC"
        _, rows = query(sql, [plan_name])
    else:
        sql = "SELECT id, issue, cost, revenue, profit, is_hit, bet_numbers, bet_amts FROM betting_records WHERE plan_name = ? ORDER BY issue DESC LIMIT ?"
        _, rows = query(sql, [plan_name, int(limit)])
        
    result = []
    for r in rows:
        result.append({
            "id": r[0], "issue": r[1], "cost": r[2], "revenue": r[3], 
            "profit": r[4], "hit": bool(r[5]), 
            "bet_numbers": r[6] if r[6] else "", 
            "bet_amts": r[7] if r[7] else ""
        })
    return result

def delete_record(record_id):
    execute("DELETE FROM betting_records WHERE id = ?", [record_id])

def save_auto_record(issue, plan_name, cost, revenue, profit, is_hit, bet_numbers="", bet_amts=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "INSERT INTO betting_records (issue, plan_name, cost, revenue, profit, is_hit, created_at, bet_numbers, bet_amts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(issue, plan_name) DO UPDATE SET "
        "cost=excluded.cost, revenue=excluded.revenue, profit=excluded.profit, is_hit=excluded.is_hit, created_at=excluded.created_at, bet_numbers=excluded.bet_numbers, bet_amts=excluded.bet_amts",
        [issue, plan_name, cost, revenue, profit, 1 if is_hit else 0, now, bet_numbers, bet_amts]
    )

# ---------------- 连黑沙盘推演 ----------------
def calc_miss_simulation(base_amts, target, max_miss=20):
    """生成1-N期连黑的建议下注推演表（仅针对保本递进）"""
    min_amt = min(base_amts)
    base_cost = sum(base_amts)
    min_gain = 46 * min_amt - base_cost
    
    if min_gain <= 0: return []
    
    L = 0
    rows = []
    for T in range(1, max_miss+1):
        need_scale = (L + T * target) / min_gain
        if need_scale < 1.0: need_scale = 1.0
        
        curr_amts = [ceil_to_step(a * need_scale) for a in base_amts]
        cost = sum(curr_amts)
        
        rev_high = 46 * max(curr_amts)
        rev_low = 46 * min(curr_amts)
        
        profit_high = rev_high - cost
        profit_low = rev_low - cost
        
        avg_high = (profit_high - L) / T
        avg_low = (profit_low - L) / T
        
        rows.append({
            "T": T,
            "amts": curr_amts,
            "cost": cost,
            "cum_cost": L + cost,
            "profit_high": profit_high,
            "profit_low": profit_low,
            "avg_high": round(avg_high, 1),
            "avg_low": round(avg_low, 1)
        })
        L += cost
    return rows

# ---------------- 核心自动计算 ----------------
def calc_issue(plan_name, model_name, target_issue, manual_miss=None, manual_loss=None, override_target=None):
    plans = get_plans()
    plan = next((p for p in plans if p["name"] == plan_name), None)
    if not plan: return {"error": "方案不存在"}
        
    config = plan["config"]
    strategy = config.get("strategy", "平注")
    
    raw_amts = config.get("amts", [])
    if isinstance(raw_amts, dict):
        amts = [int(v) for k, v in sorted(raw_amts.items(), key=lambda x: int(x[0]))]
    else:
        amts = [int(x) for x in raw_amts]
    if not amts: return {"error": "方案未配置下注金额"}

    codes_count = len(amts)
    base_cost = sum(amts)
    
    # 目标利润支持临时覆盖
    plan_target = config.get("target_profit", 100)
    target = override_target if override_target is not None else plan_target

    df = draws.get_all_draws()
    events = prediction.read_library(df)
    pred = prediction.get_prediction(df, events, target_issue, model_name)
    if not pred: return {"error": f"无法获取 {target_issue} 期的预测，可能数据不足"}
    
    bet_numbers = [n for n, _ in pred["ranked_numbers"][:codes_count]]
    
    # 自动获取（基于模型连黑和方案的累计亏损）
    mp = prediction._build_cache(df, events, int(df["期数"].max()))
    items = sorted([(i, p) for i, p in mp.get(model_name, {}).items() if i < target_issue])
    auto_miss = 0
    for iss, pos in reversed(items):
        if pos > codes_count: auto_miss += 1
        else: break

    row = query_one("SELECT SUM(profit) FROM betting_records WHERE plan_name = ? AND issue < ?", [plan_name, target_issue])
    auto_loss = -row[0] if row and row[0] is not None and row[0] < 0 else 0

    current_miss = manual_miss if manual_miss is not None else auto_miss
    history_loss = manual_loss if manual_loss is not None else auto_loss

    T = current_miss + 1
    final_amts = []
    total_cost = base_cost
    
    if strategy == "保本递进注":
        min_amt = min(amts)
        min_gain = 46 * min_amt - base_cost
        if min_gain <= 0:
            return {"error": f"当前配比命中后利润({min_gain})<=0，无法保本，请加大注金"}
        
        need_scale = (history_loss + T * target) / min_gain
        if need_scale < 1.0: need_scale = 1.0
        
        total_cost = 0
        for v in amts:
            new_v = ceil_to_step(v * need_scale)
            final_amts.append(new_v)
            total_cost += new_v
    else:
        final_amts = amts

    actual_row = df[df["期数"] == target_issue]
    actual_num = None
    hit_idx = -1
    revenue = profit = 0
    is_hit = False
    
    if not actual_row.empty:
        actual_num = int(actual_row.iloc[0]["特码"])
        if actual_num in bet_numbers:
            hit_idx = bet_numbers.index(actual_num)
            is_hit = True
            revenue = 46 * final_amts[hit_idx]
            profit = revenue - total_cost
        else:
            profit = -total_cost

    # 连黑沙盘模拟 (最多展示到20期或当前最大连黑)
    max_sim = max(20, current_miss + 5)
    sim_table = calc_miss_simulation(amts, target, max_sim) if strategy == "保本递进注" else []

    return {
        "plan_name": plan_name, "model_name": model_name, "target_issue": target_issue,
        "strategy": strategy, "codes_count": codes_count,
        "auto_miss": auto_miss, "auto_loss": auto_loss,
        "manual_miss": manual_miss, "manual_loss": manual_loss,
        "current_miss": current_miss, "history_loss": history_loss,
        "target_profit": target, "plan_target": plan_target,
        "bet_numbers": bet_numbers, "final_amts": final_amts, "total_cost": total_cost,
        "actual_num": actual_num, "hit_idx": hit_idx,
        "revenue": revenue, "profit": profit, "is_hit": is_hit,
        "sim_table": sim_table
    }