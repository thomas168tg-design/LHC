# -*- coding: utf-8 -*-
"""
test_pingte_ultimate.py
=======================
升级版盲测：排1黑2触发动态矩阵，黑3买1，黑4-8停手，黑9重置。
初始样本 2023001-2023060，每10期滑动更新一次模型。
"""
import os, csv
from datetime import datetime
from collections import defaultdict

CSV_PATH = "data/pingte_draws.csv"
LUNAR_NEW_YEAR = [
    (datetime(2027, 2, 6), "羊"), (datetime(2026, 2, 17), "马"), (datetime(2025, 1, 29), "蛇"),
    (datetime(2024, 2, 10), "龙"), (datetime(2023, 1, 22), "兔"), (datetime(2022, 2, 1), "虎"),
    (datetime(2021, 2, 12), "牛"), (datetime(2020, 1, 25), "鼠"), (datetime(2019, 2, 5), "猪"),
    (datetime(2018, 2, 16), "狗"), (datetime(2017, 1, 28), "鸡"), (datetime(2016, 2, 8), "猴"),
]
ZODIAC_ORDER = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

def get_year_zodiac(dt):
    for start_date, zodiac in LUNAR_NEW_YEAR:
        if dt >= start_date: return zodiac
    return "马"

def num_to_zodiac(num, year_zodiac):
    base_idx = ZODIAC_ORDER.index(year_zodiac)
    return ZODIAC_ORDER[(base_idx - (num - 1)) % 12]

def load_data():
    if not os.path.exists(CSV_PATH): return []
    draws = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                date_str = row["开奖日期"].strip()
                fmt = "%Y/%m/%d" if "/" in date_str else "%Y-%m-%d"
                dt = datetime.strptime(date_str, fmt)
                nums = [int(row[f"正码{i}"]) for i in range(1, 7)] + [int(row["特码"])]
                draws.append({"issue": row["开奖期数"].strip(), "dt": dt, "nums": nums})
            except: continue
    return draws

def get_ranking(history, i, window=5):
    """计算第 i 期的排1-12名"""
    hw = {z: 0 for z in ZODIAC_ORDER}
    for k in range(max(0, i-window), i):
        for z in ZODIAC_ORDER:
            if history[k]["hits"][z]: hw[z] += 1
    return sorted(ZODIAC_ORDER, key=lambda z: (-hw[z], ZODIAC_ORDER.index(z)))

def update_model(history, end_idx):
    """用过去 60 期的样本进行滚动训练，记录每种状态下买排1-12的真实盈亏"""
    status_profits = defaultdict(lambda: [0]*12)
    start_idx = max(0, end_idx - 60)
    
    for i in range(start_idx, end_idx - 1):
        sorted_z = get_ranking(history, i)
        
        # 当期排1-3的命中状态
        st = (
            1 if history[i]["hits"][sorted_z[0]] else 0,
            1 if history[i]["hits"][sorted_z[1]] else 0,
            1 if history[i]["hits"][sorted_z[2]] else 0
        )
        
        # 下一期的开奖结果
        next_z = history[i+1]
        for rank in range(12):
            z = sorted_z[rank]
            is_hit = next_z["hits"][z]
            is_benming = (z == next_z["yz"])
            profit = (100 * (1.8 if is_benming else 2.0) - 100) if is_hit else -100
            status_profits[st][rank] += profit
            
    return status_profits

def run_backtest():
    draws = load_data()
    if not draws: return
    
    history = []
    for d in draws:
        yz = get_year_zodiac(d["dt"])
        hits = {z: False for z in ZODIAC_ORDER}
        for n in d["nums"]: hits[num_to_zodiac(n, yz)] = True
        history.append({"issue": d["issue"], "year": d["dt"].year, "yz": yz, "hits": hits})

    start_idx = 60
    status_profits = {}
    
    results = []
    miss_streak = 0
    
    # 记录黑2时的触发次数，以及矩阵推荐胜率
    trigger_count = 0
    trigger_hits = 0
    
    for i in range(start_idx, len(history) - 1):
        curr = history[i]
        next_draw = history[i+1]
        
        # 每 10 期更新一次模型
        if (i - start_idx) % 10 == 0:
            status_profits = update_model(history, i)
            
        sorted_z = get_ranking(history, i)
        
        # 上一期的排名与状态
        prev_z = get_ranking(history, i-1)
        prev_st = (
            1 if history[i-1]["hits"][prev_z[0]] else 0,
            1 if history[i-1]["hits"][prev_z[1]] else 0,
            1 if history[i-1]["hits"][prev_z[2]] else 0
        )
        
        # 规则判定
        buy_rank = 1
        is_triggered = False
        if miss_streak == 0 or miss_streak == 1:
            buy_rank = 1
        elif miss_streak == 2:
            is_triggered = True
            # 触发矩阵：找该状态下历史最赚的排位
            if prev_st in status_profits and sum(status_profits[prev_st]) != 0:
                best_rank_idx = status_profits[prev_st].index(max(status_profits[prev_st]))
                buy_rank = best_rank_idx + 1
            else:
                buy_rank = 1
        elif miss_streak == 3:
            buy_rank = 1
        elif 4 <= miss_streak <= 8:
            buy_rank = 0  # 空仓
        elif miss_streak >= 9:
            buy_rank = 1
            miss_streak = 0
            
        # 结算
        profit = 0
        if buy_rank > 0:
            chosen_z = sorted_z[buy_rank - 1]
            is_hit = next_draw["hits"][chosen_z]
            is_benming = (chosen_z == next_draw["yz"])
            profit = (100 * (1.8 if is_benming else 2.0) - 100) if is_hit else -100
            
            if is_triggered:
                trigger_count += 1
                if is_hit: trigger_hits += 1
                
        results.append({
            "issue": next_draw["issue"],
            "year": next_draw["year"],
            "miss_streak": miss_streak,
            "buy_rank": buy_rank,
            "is_triggered": is_triggered,
            "profit": profit
        })
        
        # 当前期排1是否命中，决定连黑
        if curr["hits"][sorted_z[0]]:
            miss_streak = 0
        else:
            miss_streak += 1

    # 输出报告
    total_profit = 0
    by_year = {}
    bets = 0
    hits = 0
    
    for r in results:
        by_year.setdefault(r["year"], {"profit": 0, "bets": 0, "hits": 0})
        if r["buy_rank"] > 0:
            bets += 1
            by_year[r["year"]]["bets"] += 1
            if r["profit"] > 0:
                hits += 1
                by_year[r["year"]]["hits"] += 1
            total_profit += r["profit"]
            by_year[r["year"]]["profit"] += r["profit"]
            
    print("=== 升级版盲测: 黑2动态矩阵 + 黑3买1 + 黑4-8停手 + 黑9重置 ===")
    print(f"【总体表现】总盈亏: {total_profit:+.0f} | 总下注: {bets} 期 | 胜率: {hits/bets*100:.2f}%")
    if trigger_count > 0:
        print(f"【黑2矩阵触发】触发次数: {trigger_count} | 命中率: {trigger_hits/trigger_count*100:.2f}%")
    
    print("\n【分年表现】")
    for y in sorted(by_year):
        d = by_year[y]
        if d["bets"]:
            print(f"  {y}年: {d['profit']:+.0f} | 下注 {d['bets']} 期 | 胜率 {d['hits']/d['bets']*100:.1f}%")

if __name__ == "__main__":
    run_backtest()