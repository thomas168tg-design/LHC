# -*- coding: utf-8 -*-
"""
排行123状态机回测（V3版：黑4重置）
窗口：5/15/20
输出：全历史、分年、2026专项、近100/60/30期汇总
及 2026 逐期明细 CSV（累计从2026001期下注前=0开始）
"""

import os
import csv
from datetime import datetime
from collections import defaultdict

CSV_PATH = "data/pingte_draws.csv"
WINDOWS = [5, 15, 20]

LUNAR_NEW_YEAR = [
    (datetime(2027, 2, 6), "羊"), (datetime(2026, 2, 17), "马"),
    (datetime(2025, 1, 29), "蛇"), (datetime(2024, 2, 10), "龙"),
    (datetime(2023, 1, 22), "兔"), (datetime(2022, 2, 1), "虎"),
    (datetime(2021, 2, 12), "牛"), (datetime(2020, 1, 25), "鼠"),
    (datetime(2019, 2, 5), "猪"), (datetime(2018, 2, 16), "狗"),
    (datetime(2017, 1, 28), "鸡"), (datetime(2016, 2, 8), "猴"),
]
ZODIAC_ORDER = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]


def get_year_zodiac(dt):
    for start_date, zodiac in LUNAR_NEW_YEAR:
        if dt >= start_date:
            return zodiac
    return "马"


def num_to_zodiac(num, year_zodiac):
    base_idx = ZODIAC_ORDER.index(year_zodiac)
    return ZODIAC_ORDER[(base_idx - (num - 1)) % 12]


def load_data():
    if not os.path.exists(CSV_PATH):
        print(f"找不到数据文件：{CSV_PATH}")
        return []

    draws = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                date_str = row["开奖日期"].strip()
                fmt = "%Y/%m/%d" if "/" in date_str else "%Y-%m-%d"
                dt = datetime.strptime(date_str, fmt)
                nums = [int(row[f"正码{i}"]) for i in range(1, 7)] + [int(row["特码"])]
                draws.append({
                    "issue": row["开奖期数"].strip(),
                    "dt": dt,
                    "nums": nums
                })
            except Exception:
                continue
    return draws


def build_history(draws):
    history = []
    for d in draws:
        yz = get_year_zodiac(d["dt"])
        hits = {z: False for z in ZODIAC_ORDER}
        for n in d["nums"]:
            hits[num_to_zodiac(n, yz)] = True
        history.append({
            "issue": d["issue"],
            "date": d["dt"].strftime("%Y-%m-%d"),
            "year": d["dt"].year,
            "yz": yz,
            "hits": hits
        })
    return history


def get_ranking(history, i, window):
    cnt = {z: 0 for z in ZODIAC_ORDER}
    start = max(0, i - window)
    for k in range(start, i):
        for z in ZODIAC_ORDER:
            if history[k]["hits"][z]:
                cnt[z] += 1
    return sorted(ZODIAC_ORDER, key=lambda z: (-cnt[z], ZODIAC_ORDER.index(z)))


def max_miss_streak(hit_flags):
    mx = cur = 0
    for h in hit_flags:
        if not h:
            cur += 1
            mx = max(mx, cur)
        else:
            cur = 0
    return mx


def calc_max_cumulative_invest(records):
    if not records:
        return 0
    mx = 0
    cur = 0
    for r in records:
        cur += r["amount"]
        if r["hit"]:
            mx = max(mx, cur)
            cur = 0
    mx = max(mx, cur)
    return mx


def simulate(history, window):
    records = []
    if len(history) <= window + 1:
        return records

    streak = 0

    for i in range(window, len(history) - 1):
        curr_draw = history[i]
        next_draw = history[i + 1]
        curr_rank = get_ranking(history, i, window)
        
        # 记录当前排1-3，以及上期（即当前i期）排1-3的命中情况
        rank_1_3_str = "".join(curr_rank[:3])
        prev_hits = []
        for r in range(3):
            z = curr_rank[r]
            prev_hits.append("1" if curr_draw["hits"][z] else "0")
        prev_hit_1_3_str = ",".join(prev_hits)

        # 状态机下注逻辑
        if streak == 0:
            amount = 100
            target_rank = 1
            tag = "上期中"
        elif streak == 1:
            amount = 200
            target_rank = 1
            tag = "黑1"
        elif streak == 2 or streak == 3:
            amount = 300
            if curr_draw["hits"][curr_rank[1]]:
                target_rank = 2
            elif curr_draw["hits"][curr_rank[2]]:
                target_rank = 3
            else:
                target_rank = 1
            tag = f"黑{streak}"
        else:  # streak == 4
            amount = 100
            target_rank = 1
            tag = "黑4重置"

        chosen_z = curr_rank[target_rank - 1]
        hit = next_draw["hits"][chosen_z]
        is_benming = (chosen_z == next_draw["yz"])
        odds = 1.8 if is_benming else 2.0
        profit = amount * (odds - 1) if hit else -amount

        records.append({
            "window": window,
            "issue": next_draw["issue"],
            "date": next_draw["date"],
            "year": next_draw["year"],
            "rank_1_3": rank_1_3_str,
            "prev_hit_1_3": prev_hit_1_3_str,
            "streak_before": streak,
            "tag": tag,
            "target_rank": target_rank,
            "chosen_z": chosen_z,
            "amount": amount,
            "hit": 1 if hit else 0,
            "odds": odds,
            "is_benming": 1 if is_benming else 0,
            "profit": profit,
        })

        # 更新 streak
        if hit:
            streak = 0
        else:
            if streak == 4:
                streak = 1  # 重置后的第一注依然黑了，视作新的黑1
            else:
                streak += 1

    return records


def summarize(records, window, group_label):
    n = len(records)
    if n == 0:
        return {
            "窗口": window, "分组": group_label, "下注次数": 0, "命中次数": 0, "未中次数": 0,
            "命中率": 0, "最大单注": 0, "最大累计投入": 0, "最长不中": 0, "利润": 0, "总下注额": 0, "ROI": 0
        }

    hits = sum(1 for r in records if r["hit"])
    profit = sum(r["profit"] for r in records)
    stake = sum(r["amount"] for r in records)
    max_single = max(r["amount"] for r in records)
    max_invest = calc_max_cumulative_invest(records)
    max_miss = max_miss_streak([r["hit"] for r in records])

    return {
        "窗口": window, "分组": group_label, "下注次数": n, "命中次数": hits, "未中次数": n - hits,
        "命中率": hits / n, "最大单注": max_single, "最大累计投入": max_invest,
        "最长不中": max_miss, "利润": profit, "总下注额": stake, "ROI": profit / stake if stake else 0
    }


def build_all_summaries(records, window):
    rows = []
    rows.append(summarize(records, window, "全历史"))

    by_year = defaultdict(list)
    for r in records:
        by_year[r["year"]].append(r)
    for y in sorted(by_year):
        rows.append(summarize(by_year[y], window, f"{y}年"))

    rec_2026 = [r for r in records if r["year"] == 2026]
    rows.append(summarize(rec_2026, window, "2026专项"))

    for n in [100, 60, 30]:
        rows.append(summarize(records[-n:], window, f"近{n}期"))
    return rows


def make_2026_detail(records, window):
    rows = []
    cum_stake_2026 = 0
    cum_profit_2026 = 0
    cum_stake_all = 0
    cum_profit_all = 0

    for r in records:
        stake_before_all = cum_stake_all
        profit_before_all = cum_profit_all
        cum_stake_all += r["amount"]
        cum_profit_all += r["profit"]

        if r["year"] != 2026:
            continue

        stake_before_2026 = cum_stake_2026
        profit_before_2026 = cum_profit_2026
        cum_stake_2026 += r["amount"]
        cum_profit_2026 += r["profit"]

        rows.append({
            "window": window,
            "issue": r["issue"],
            "date": r["date"],
            "rank_1_3": r["rank_1_3"],
            "prev_hit_1_3": r["prev_hit_1_3"],
            "streak_before": r["streak_before"],
            "tag": r["tag"],
            "target_rank": r["target_rank"],
            "chosen_z": r["chosen_z"],
            "amount": r["amount"],
            "hit": r["hit"],
            "hit_text": "中" if r["hit"] else "未中",
            "odds": r["odds"],
            "is_benming": r["is_benming"],
            "profit": r["profit"],
            "cum_stake_before_2026": stake_before_2026,
            "cum_stake_after_2026": cum_stake_2026,
            "cum_profit_before_2026": profit_before_2026,
            "cum_profit_after_2026": cum_profit_2026,
            "cum_stake_before_all": stake_before_all,
            "cum_stake_after_all": cum_stake_all,
            "cum_profit_before_all": profit_before_all,
            "cum_profit_after_all": cum_profit_all,
        })
    return rows


def print_summary_table(rows):
    print("\n" + "=" * 150)
    print("排行123状态机回测 V3版（黑4重置）汇总")
    print("=" * 150)
    header = (
        f"{'窗口':>4} {'分组':<10} {'下注':>5} {'命中':>5} {'未中':>5} {'命中率':>8} "
        f"{'最大单注':>8} {'最大累计投入':>12} {'最长不中':>8} {'利润':>10} {'总下注额':>10} {'ROI':>8}"
    )
    print(header)
    print("-" * 150)
    for r in rows:
        print(
            f"{r['窗口']:>4} {r['分组']:<10} {r['下注次数']:>5} {r['命中次数']:>5} "
            f"{r['未中次数']:>5} {r['命中率']*100:>7.2f}% {r['最大单注']:>8} "
            f"{r['最大累计投入']:>12} {r['最长不中']:>8} {r['利润']:>+10.0f} "
            f"{r['总下注额']:>10} {r['ROI']*100:>+7.2f}%"
        )


def save_csv(rows, path):
    if not rows:
        print(f"无数据可保存：{path}")
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"已保存：{path} | 行数：{len(rows)}")


def main():
    draws = load_data()
    if not draws:
        return
    history = build_history(draws)
    print(f"有效数据期数：{len(history)}")

    all_rows = []
    all_2026_rows = []

    for window in WINDOWS:
        records = simulate(history, window)
        rows = build_all_summaries(records, window)
        all_rows.extend(rows)

        detail_2026 = make_2026_detail(records, window)
        all_2026_rows.extend(detail_2026)
        
        save_csv(detail_2026, f"backtest_rank123_2026_detail_w{window}.csv")

    print_summary_table(all_rows)
    save_csv(all_rows, "backtest_rank123_summary_v3.csv")
    save_csv(all_2026_rows, "backtest_rank123_2026_detail_all.csv")


if __name__ == "__main__":
    main()