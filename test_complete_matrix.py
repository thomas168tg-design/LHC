# -*- coding: utf-8 -*-
"""
test_matrix_v3_exact.py
全玩法全组数对齐盲测系统（V3终极精准赔率版）
特点：
1. 严格实现本命肖组合降水逻辑（含本命肖：一肖1.8 / 二连3.5 / 三连9 / 四连28）。
2. 严格实现0尾特殊赔率（普通1.8 / 0尾2.0）与连尾赔率（二连3 / 三连6 / 四连16）。
3. 包含全历史 + 分年度（2024、2025、2026）战报输出与 CSV 导出。
"""

import csv
import os
import sys
from itertools import combinations
from collections import defaultdict

CSV_PATH = "data/pingte_draws.csv"  
BET_UNIT = 10                       

# 严格对齐您提供的最新规则矩阵
RULE_MATRIX = {
    "特码": [5, 12],
    "特肖": [1, 2, 3, 4, 5],
    "平特一肖": [1],
    "二连肖": [1, 2],
    "三连肖": [1, 2, 3, 4, 5],
    "四连肖": [1, 2, 3, 4, 5, 8, 10, 12, 15],
    "平特一尾": [1],
    "二连尾": [1, 2],
    "三连尾": [1, 2, 3],
    "四连尾": [1, 2, 3, 4, 5, 6, 7, 8]
}

def get_zodiac(num, year_str):
    """根据年份和号码获取对应生肖"""
    zodiacs = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']
    base_year = 2024 # 2024龙年
    try:
        offset = (int(year_str) - base_year) % 12
    except:
        offset = 0
    return zodiacs[(num - 1 + offset * 4) % 12]

def get_current_year_zodiac(year_str):
    """获取当年的本命生肖"""
    zodiacs = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']
    base_year = 2024
    try:
        offset = (int(year_str) - base_year) % 12
    except:
        offset = 0
    return zodiacs[offset]

def get_tail(num):
    return num % 10

def load_data(path=CSV_PATH):
    draws = []
    if not os.path.exists(path):
        print(f"❌ 找不到数据文件: {path}")
        return draws
    with open(path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 9: continue
            try:
                pingma = [int(row[2]), int(row[3]), int(row[4]), int(row[5]), int(row[6]), int(row[7])]
                special = int(row[8])
                all_7_balls = pingma + [special]
            except ValueError: continue
            draws.append({
                "issue": row[0].strip(), "date": row[1].strip(),
                "pingma": pingma, "special": special, "all_7_balls": all_7_balls
            })
    draws.sort(key=lambda x: x["issue"])
    return draws

def calc_num_scores(history_draws):
    l30_draws = history_draws[-30:] if len(history_draws) >= 30 else history_draws
    l30_freq = defaultdict(int)
    for d in l30_draws:
        for n in d["all_7_balls"]: l30_freq[n] += 1
        
    w100_draws = history_draws[-100:] if len(history_draws) >= 100 else history_draws
    w100_freq = defaultdict(int)
    for d in w100_draws:
        for n in d["all_7_balls"]: w100_freq[n] += 1

    total_len = len(history_draws)
    last_pos = {}
    tail_counts = defaultdict(int)
    for i, d in enumerate(history_draws[-50:]):
        for n in d["all_7_balls"]:
            last_pos[n] = i
            tail_counts[n % 10] += 1
            
    weighted = {}
    for n in range(1, 50):
        omiss = total_len - 1 - last_pos.get(n, -1)
        weighted[n] = (tail_counts[n % 10] * 0.4) + (l30_freq[n] * 0.4) + ((omiss / 10.0) * 0.2)
        
    agg = {n: l30_freq[n] + w100_freq[n] + weighted[n] for n in range(1, 50)}
    return {
        "L30_Model": {n: l30_freq[n] for n in range(1, 50)},
        "W100_Model": {n: w100_freq[n] for n in range(1, 50)},
        "Weighted_Model": weighted,
        "Aggregated_Ensemble": agg
    }

def run_matrix_backtest(draws, start_issue, end_issue):
    test_draws = []
    start_idx = 0
    for idx, d in enumerate(draws):
        if d["issue"] >= start_issue: start_idx = idx; break
    if start_idx < 30: start_idx = 30

    for idx in range(start_idx, len(draws)):
        current_draw = draws[idx]
        if end_issue and current_draw["issue"] > end_issue: break
        test_draws.append((idx, current_draw))

    if not test_draws: return None

    # 存储结构: results[play_name][group_cnt][model_name] = [record_dict]
    results = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    print(f"\n🚀 开始执行精准盘口赔率对齐盲测，共测试 {len(test_draws)} 期 (期号: {test_draws[0][1]['issue']} ~ {test_draws[-1][1]['issue']})...")

    for count, (idx, target_draw) in enumerate(test_draws):
        history_draws = draws[:idx]
        year_str = target_draw["issue"][:4]
        current_year_zodiac = get_current_year_zodiac(year_str)
        
        actual_special = target_draw["special"]
        actual_special_zodiac = get_zodiac(actual_special, year_str)
        
        actual_7_balls = target_draw["all_7_balls"]
        actual_7_zodiacs = set(get_zodiac(n, year_str) for n in actual_7_balls)
        actual_7_tails = set(get_tail(n) for n in actual_7_balls)

        scores_by_model = calc_num_scores(history_draws)

        for play_name, groups in RULE_MATRIX.items():
            for g_cnt in groups:
                for m_name, num_scores in scores_by_model.items():
                    cost = g_cnt * BET_UNIT
                    revenue = 0
                    is_hit = False
                    
                    # ----------------------------------------------------
                    # 1. 特码（46.0倍）
                    # ----------------------------------------------------
                    if play_name == "特码":
                        sorted_nums = sorted(num_scores.keys(), key=lambda x: num_scores[x], reverse=True)
                        picked = sorted_nums[:g_cnt]
                        if actual_special in picked:
                            is_hit = True
                            revenue = 46.0 * BET_UNIT
                            
                    # ----------------------------------------------------
                    # 2. 特肖（普通 11.0倍 / 本命肖 10.0倍）
                    # ----------------------------------------------------
                    elif play_name == "特肖":
                        zod_scores = defaultdict(float)
                        for n, s in num_scores.items(): zod_scores[get_zodiac(n, year_str)] += s
                        sorted_zods = sorted(zod_scores.keys(), key=lambda x: zod_scores[x], reverse=True)
                        picked = sorted_zods[:g_cnt]
                        if actual_special_zodiac in picked:
                            is_hit = True
                            odds = 10.0 if actual_special_zodiac == current_year_zodiac else 11.0
                            revenue = odds * BET_UNIT

                    # ----------------------------------------------------
                    # 3. 平特一肖 / 连肖（本命肖降水判定）
                    # ----------------------------------------------------
                    elif "肖" in play_name:
                        zod_scores = defaultdict(float)
                        for n, s in num_scores.items(): zod_scores[get_zodiac(n, year_str)] += s
                        sorted_zods = sorted(zod_scores.keys(), key=lambda x: zod_scores[x], reverse=True)
                        
                        combo_size = 1
                        if "二连" in play_name: combo_size = 2
                        elif "三连" in play_name: combo_size = 3
                        elif "四连" in play_name: combo_size = 4
                        
                        if combo_size == 1:
                            combos = [[item] for item in sorted_zods[:g_cnt]]
                        else:
                            pool = sorted_zods[:min(len(sorted_zods), combo_size + 4)]
                            all_combos = list(combinations(pool, combo_size))
                            combos = [list(c) for c in sorted(all_combos, key=lambda c: sum(zod_scores[x] for x in c), reverse=True)[:g_cnt]]
                            
                        hit_cnt = 0
                        for c in combos:
                            if set(c).issubset(actual_7_zodiacs):
                                hit_cnt += 1
                                # 动态判断组合内是否包含本命肖
                                has_benming = current_year_zodiac in c
                                if combo_size == 1:
                                    odds = 1.8 if has_benming else 2.0
                                elif combo_size == 2:
                                    odds = 3.5 if has_benming else 4.0
                                elif combo_size == 3:
                                    odds = 9.0 if has_benming else 10.0
                                elif combo_size == 4:
                                    odds = 28.0 if has_benming else 30.0
                                revenue += odds * BET_UNIT
                                
                        if hit_cnt > 0:
                            is_hit = True

                    # ----------------------------------------------------
                    # 4. 平特一尾 / 连尾（0尾及连尾赔率判定）
                    # ----------------------------------------------------
                    elif "尾" in play_name:
                        tail_scores = defaultdict(float)
                        for n, s in num_scores.items(): tail_scores[get_tail(n)] += s
                        sorted_tails = sorted(tail_scores.keys(), key=lambda x: tail_scores[x], reverse=True)
                        
                        combo_size = 1
                        if "二连" in play_name: combo_size = 2
                        elif "三连" in play_name: combo_size = 3
                        elif "四连" in play_name: combo_size = 4
                        
                        if combo_size == 1:
                            combos = [[item] for item in sorted_tails[:g_cnt]]
                        else:
                            pool = sorted_tails[:min(len(sorted_tails), combo_size + 4)]
                            all_combos = list(combinations(pool, combo_size))
                            combos = [list(c) for c in sorted(all_combos, key=lambda c: sum(tail_scores[x] for x in c), reverse=True)[:g_cnt]]

                        hit_cnt = 0
                        for c in combos:
                            if set(c).issubset(actual_7_tails):
                                hit_cnt += 1
                                if combo_size == 1:
                                    odds = 2.0 if 0 in c else 1.8
                                elif combo_size == 2:
                                    odds = 3.0
                                elif combo_size == 3:
                                    odds = 6.0
                                elif combo_size == 4:
                                    odds = 16.0
                                revenue += odds * BET_UNIT
                                
                        if hit_cnt > 0:
                            is_hit = True

                    profit = revenue - cost
                    results[play_name][g_cnt][m_name].append({
                        "issue": target_draw["issue"],
                        "year": year_str,
                        "is_hit": is_hit,
                        "cost": cost,
                        "profit": profit
                    })
                    
        if (count + 1) % 200 == 0 or (count + 1) == len(test_draws):
            print(f"  -> 已完成进度: {count + 1} / {len(test_draws)} 期...")

    return results

def print_and_export_reports(results):
    if not results: return
    summary_rows = []

    def print_section(title, filter_year=None):
        print("\n" + "="*95)
        print(f"📊 {title}")
        print("="*95)
        print(f"{'玩法名称':<12} | {'组数':<6} | {'模型名称':<20} | {'命中期数':<8} | {'胜率(%)':<8} | {'净盈亏(元)':<12} | {'ROI(%)'}")
        print("-" * 95)

        for play_name, group_dict in RULE_MATRIX.items():
            for g_cnt in group_dict:
                for m_name in ["L30_Model", "W100_Model", "Weighted_Model", "Aggregated_Ensemble"]:
                    raw_res = results[play_name][g_cnt][m_name]
                    if filter_year:
                        res = [r for r in raw_res if r["year"] == filter_year]
                    else:
                        res = raw_res
                        
                    periods = len(res)
                    if periods == 0: continue
                    hits = sum(1 for r in res if r["is_hit"])
                    total_cost = sum(r["cost"] for r in res)
                    total_profit = sum(r["profit"] for r in res)
                    win_rate = (hits / periods) * 100
                    roi = (total_profit / total_cost) * 100 if total_cost > 0 else 0
                    
                    print(f"{play_name:<12} | {g_cnt:<6} | {m_name:<20} | {hits:<8} | {win_rate:<8.2f} | {total_profit:<12,.0f} | {roi:<8.2f}%")
                    
                    if filter_year is None: # 仅全历史数据录入 CSV 汇总
                        summary_rows.append({
                            "玩法": play_name, "下注组数": g_cnt, "模型": m_name,
                            "测试期数": periods, "命中期数": hits, "胜率(%)": round(win_rate, 2),
                            "净盈亏(元)": total_profit, "ROI(%)": round(roi, 2)
                        })
            print("-" * 95)

    # 1. 输出全历史总战报
    print_section("全历史盲测综合战报 (共计 1027 期 | 严格对齐最新含本命肖降水赔率)")

    # 2. 输出分年度战报
    sample_res = list(results.values())[1][1]["L30_Model"]
    years = sorted(list(set(r["year"] for r in sample_res)))
    for y in years:
        print_section(f"{y} 年度拆解战报", filter_year=y)

    # 导出 CSV
    csv_file = "matrix_backtest_results_v3.csv"
    with open(csv_file, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_rows[0].keys())
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"\n✅ 细分赔率后的 V3 终极结果已成功保存为 CSV 文件: {os.path.abspath(csv_file)}")

if __name__ == "__main__":
    draws = load_data()
    if draws:
        results = run_matrix_backtest(draws, "2024001", draws[-1]["issue"])
        if results:
            print_and_export_reports(results)