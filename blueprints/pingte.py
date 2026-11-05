# -*- coding: utf-8 -*-
"""
blueprints/pingte.py
平特一肖独立路由
"""
from datetime import datetime
from collections import Counter
from flask import Blueprint, render_template, request, jsonify
from database import query, execute, query_one
from core.pingte.logic import (
    get_all_pingte_draws, update_pingte_data, 
    get_year_zodiac, num_to_zodiac, ZODIAC_ORDER,
    get_processed_history 
)

pingte_bp = Blueprint('pingte', __name__, url_prefix='/pingte')

@pingte_bp.route('/')
def index():
    draws = get_all_pingte_draws()
    total = len(draws) if draws else 0
    last_update = query_one("SELECT MAX(updated_at) FROM pingte_draws")
    last_update = last_update[0] if last_update and last_update[0] else "尚未更新"

    default_start = "2023001"
    if draws:
        # 👇 直接根据期号获取年份
        current_year = int(str(draws[-1][0])[:4])
        default_start = f"{current_year}001"

    start_issue = request.args.get('start_issue', default_start).strip()
    end_issue = request.args.get('end_issue', '').strip()
    range_type = request.args.get('range_type', '20')
    stat_mode = request.args.get('stat_mode', 'all')
    is_custom = request.args.get('is_custom', '0') == '1'
    
    if not draws:
        return render_template('pingte/dashboard.html', draws=[], total=0, start_issue=default_start, end_issue='', range_type='20', stat_mode='all', zodiacs=ZODIAC_ORDER, last_update=last_update)
        
    if not end_issue: end_issue = draws[-1][0]
        
    if not is_custom:
        if range_type == '5': filtered = draws[-5:]
        elif range_type == '15': filtered = draws[-15:]
        elif range_type == '20': filtered = draws[-20:]
        elif range_type == '30': filtered = draws[-30:]
        elif range_type == '60': filtered = draws[-60:]
        elif range_type == '90': filtered = draws[-90:]
        elif range_type == '120': filtered = draws[-120:]
        elif range_type == '180': filtered = draws[-180:]
        elif range_type == '365': filtered = draws[-365:]
        elif range_type == '2026': filtered = [d for d in draws if str(d[0]).startswith('2026')]
        elif range_type == '2025': filtered = [d for d in draws if str(d[0]).startswith('2025')]
        elif range_type == '2024': filtered = [d for d in draws if str(d[0]).startswith('2024')]
        elif range_type == '2023': filtered = [d for d in draws if str(d[0]).startswith('2023')]
        elif range_type == 'all': filtered = draws
        else: filtered = draws[-20:]
    else:
        filtered = []
        for d in draws:
            iss_str = str(d[0])
            if start_issue <= iss_str <= end_issue:
                filtered.append(d)
        
    recent_draws = filtered[::-1]
    processed_draws = []
    for d in recent_draws:
        issue, date_str, sp = d[0], d[1], d[8]
        date_str = date_str.split(" ")[0].replace("-", "/")
        
        # 👇 核心修改
        yz = get_year_zodiac(str(issue))
        
        nums = list(d[2:8]) + [sp]
        num_zodiacs = [num_to_zodiac(n, yz) for n in nums]
        processed_draws.append({
            "issue": issue, "date": date_str, "nums": nums, 
            "num_zodiacs": num_zodiacs, "special": sp, "year_zodiac": yz
        })
        
    return render_template('pingte/dashboard.html', draws=processed_draws, total=total, start_issue=start_issue, end_issue=end_issue, range_type=range_type, stat_mode=stat_mode, zodiacs=ZODIAC_ORDER, last_update=last_update)

@pingte_bp.route('/rank')
def rank():
    draws = get_all_pingte_draws()
    total = len(draws) if draws else 0
    last_update = query_one("SELECT MAX(updated_at) FROM pingte_draws")
    last_update = last_update[0] if last_update and last_update[0] else "尚未更新"

    default_start = "2023001"
    if draws:
        # 👇 直接根据期号获取年份
        current_year = int(str(draws[-1][0])[:4])
        default_start = f"{current_year}001"

    start_issue = request.args.get('start_issue', default_start).strip()
    end_issue = request.args.get('end_issue', '').strip()
    range_type = request.args.get('range_type', '20')
    is_custom = request.args.get('is_custom', '0') == '1'
    
    if not draws:
        return render_template('pingte/rank.html', draws=[], all_draws=[], total=0, start_issue=default_start, end_issue='', range_type='20', zodiacs=ZODIAC_ORDER, last_update=last_update)
        
    if not end_issue: end_issue = draws[-1][0]
        
    if not is_custom:
        if range_type == '5': filtered = draws[-5:]
        elif range_type == '15': filtered = draws[-15:]
        elif range_type == '20': filtered = draws[-20:]
        elif range_type == '30': filtered = draws[-30:]
        elif range_type == '60': filtered = draws[-60:]
        elif range_type == '90': filtered = draws[-90:]
        elif range_type == '120': filtered = draws[-120:]
        elif range_type == '180': filtered = draws[-180:]
        elif range_type == '365': filtered = draws[-365:]
        elif range_type == '2026': filtered = [d for d in draws if str(d[0]).startswith('2026')]
        elif range_type == '2025': filtered = [d for d in draws if str(d[0]).startswith('2025')]
        elif range_type == '2024': filtered = [d for d in draws if str(d[0]).startswith('2024')]
        elif range_type == '2023': filtered = [d for d in draws if str(d[0]).startswith('2023')]
        elif range_type == 'all': filtered = draws
        else: filtered = draws[-20:]
    else:
        filtered = []
        for d in draws:
            iss_str = str(d[0])
            if start_issue <= iss_str <= end_issue:
                filtered.append(d)
        
    recent_draws = filtered[::-1]
    processed_draws = []
    for d in recent_draws:
        issue, date_str, sp = d[0], d[1], d[8]
        date_str = date_str.split(" ")[0].replace("-", "/")
        
        # 👇 核心修改
        yz = get_year_zodiac(str(issue))
        
        nums = list(d[2:8]) + [sp]
        num_zodiacs = [num_to_zodiac(n, yz) for n in nums]
        processed_draws.append({
            "issue": issue, "date": date_str, "nums": nums, 
            "num_zodiacs": num_zodiacs, "special": sp, "year_zodiac": yz
        })

    all_processed_draws = []
    for d in draws:
        issue, date_str, sp = d[0], d[1], d[8]
        date_str = date_str.split(" ")[0].replace("-", "/")
        
        # 👇 核心修改
        yz = get_year_zodiac(str(issue))
        
        nums = list(d[2:8]) + [sp]
        num_zodiacs = [num_to_zodiac(n, yz) for n in nums]
        all_processed_draws.append({
            "issue": issue, "date": date_str, "nums": nums, 
            "num_zodiacs": num_zodiacs, "special": sp, "year_zodiac": yz
        })
        
    return render_template('pingte/rank.html', draws=processed_draws, all_draws=all_processed_draws, total=total, start_issue=start_issue, end_issue=end_issue, range_type=range_type, zodiacs=ZODIAC_ORDER, last_update=last_update)

@pingte_bp.route('/api/update', methods=['POST'])
def api_update():
    try:
        added = update_pingte_data()
        return jsonify({"status": "ok", "added": added})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


# ==========================================
# 3. 下注台（4 方案：2 生肖 + 2 尾数）
# ==========================================
@pingte_bp.route('/betting')
def betting():
    # 表结构检查（含 plan 列）
    try:
        query("SELECT plan FROM pingte_bets LIMIT 1")
    except Exception:
        execute("DROP TABLE IF EXISTS pingte_bets")
        execute("""
            CREATE TABLE pingte_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan TEXT NOT NULL,
                issue TEXT NOT NULL,
                element TEXT NOT NULL,
                base_amount REAL DEFAULT 0,
                streak REAL DEFAULT 0,
                actual_bet REAL DEFAULT 0,
                odds REAL DEFAULT 2.0,
                is_hit INTEGER DEFAULT NULL,
                profit REAL DEFAULT NULL,
                created_at TEXT,
                UNIQUE(plan, issue)
            )
        """)

    draws = get_all_pingte_draws()
    if not draws:
        return "无数据，请先更新"

    latest_issue = draws[-1][0]
    
    # 👇 核心修改
    latest_yz = get_year_zodiac(str(latest_issue))

    # ==== 自动结算所有方案的待结算记录 ====
    _, unsolved = query("SELECT id, plan, issue, element, actual_bet, odds FROM pingte_bets WHERE is_hit IS NULL")
    for u in unsolved:
        u_id, u_plan, u_issue, u_element, u_bet, u_odds = u
        draw = next((d for d in draws if str(d[0]) == str(u_issue)), None)
        if not draw:
            continue
        nums = list(draw[2:8]) + [draw[8]]
        
        # 👇 核心修改
        yz = get_year_zodiac(str(draw[0]))

        if u_plan.startswith('tail'):
            t = int(u_element)
            is_hit = 1 if any(n % 10 == t for n in nums) else 0
            odds = 2.0 if t == 0 else 1.8
        else:
            actual_zodiacs = [num_to_zodiac(n, yz) for n in nums]
            is_hit = 1 if u_element in actual_zodiacs else 0
            odds = 1.8 if u_element == yz else 2.0

        profit = (u_bet * odds - u_bet) if is_hit else -u_bet
        execute("UPDATE pingte_bets SET is_hit=?, profit=?, odds=? WHERE id=?", [is_hit, profit, odds, u_id])

    # ==== 生肖热度（近20期，按期命中） ====
    history = get_processed_history()
    recent_20 = history[-20:] if len(history) >= 20 else history
    h20 = {z: 0 for z in ZODIAC_ORDER}
    for item in recent_20:
        for z in ZODIAC_ORDER:
            if item["hits"][z]:
                h20[z] += 1
    sorted_z = sorted(ZODIAC_ORDER, key=lambda z: (-h20[z], ZODIAC_ORDER.index(z)))

    zodiac_top3 = []
    for i in range(min(3, len(sorted_z))):
        z_name = sorted_z[i]
        cur_miss = 0
        for item in reversed(history):
            if item["hits"][z_name]:
                break
            cur_miss += 1
        max_miss = 0
        c_miss = 0
        for item in history:
            if item["hits"][z_name]:
                max_miss = max(max_miss, c_miss)
                c_miss = 0
            else:
                c_miss += 1
        max_miss = max(max_miss, c_miss)
        zodiac_top3.append({
            "zodiac": z_name, "count": h20[z_name],
            "cur_miss": cur_miss, "max_miss": max_miss
        })

    # ==== 尾数热度（近20期） ====
    tail_recent_20 = history[-20:] if len(history) >= 20 else history
    tail_hit_counts = {t: 0 for t in range(10)}
    tail_raw_counts = {t: 0 for t in range(10)}
    for item in tail_recent_20:
        seen = set()
        for n in item["nums"]:
            t = n % 10
            tail_raw_counts[t] += 1
            seen.add(t)
        for t in seen:
            tail_hit_counts[t] += 1

    tail_hits_list = []
    for item in history:
        tails = set(n % 10 for n in item["nums"])
        tail_hits_list.append(tails)

    sorted_tails = sorted(range(10), key=lambda t: (-tail_hit_counts[t], -tail_raw_counts[t], t))
    tail_top3 = []
    for t in sorted_tails[:3]:
        cur_miss = 0
        for hits in reversed(tail_hits_list):
            if t in hits:
                break
            cur_miss += 1
        max_miss = 0
        c_miss = 0
        for hits in tail_hits_list:
            if t in hits:
                max_miss = max(max_miss, c_miss)
                c_miss = 0
            else:
                c_miss += 1
        max_miss = max(max_miss, c_miss)
        tail_top3.append({
            "tail": str(t),
            "count_hit": tail_hit_counts[t],
            "count_raw": tail_raw_counts[t],
            "cur_miss": cur_miss,
            "max_miss": max_miss
        })

    # ==== 组装 4 个方案 ====
    def get_plan_data(plan_id, name, ptype, top3):
        _, bets = query(
            "SELECT is_hit FROM pingte_bets WHERE plan=? ORDER BY issue DESC",
            [plan_id]
        )
        streak = 0
        for b in bets:
            if b[0] is not None and b[0] == 0:
                streak += 1
            elif b[0] == 1:
                break

        _, records = query(
            "SELECT issue, element, actual_bet, odds, is_hit, profit FROM pingte_bets WHERE plan=? ORDER BY issue DESC LIMIT 100",
            [plan_id]
        )
        total_profit = sum([float(r[5]) for r in records if r[5] is not None])

        return {
            "name": name,
            "type": ptype,
            "latest_issue": str(int(latest_issue) + 1),
            "latest_yz": latest_yz if ptype == 'zodiac' else None,
            "streak": streak,
            "top3": top3,
            "records": records,
            "total_profit": total_profit
        }

    plans_data = {
        "zodiac_1": get_plan_data("zodiac_1", "平特一肖（方案一）", "zodiac", zodiac_top3),
        "zodiac_2": get_plan_data("zodiac_2", "平特一肖（方案二）", "zodiac", zodiac_top3),
        "tail_1":   get_plan_data("tail_1",   "平特一尾（方案一）", "tail",   tail_top3),
        "tail_2":   get_plan_data("tail_2",   "平特一尾（方案二）", "tail",   tail_top3),
    }

    return render_template('pingte/betting.html', plans_data=plans_data, zodiacs=ZODIAC_ORDER)


@pingte_bp.route('/api/save_bet', methods=['POST'])
def save_bet():
    data = request.json
    plan = data.get("plan")
    issue = data.get("issue")
    element = data.get("element")
    bet = float(data.get("bet", 0))

    if not plan or not issue or not element or bet <= 0:
        return jsonify({"status": "error", "msg": "参数缺失或金额非法"})

    bet = round(bet / 5) * 5

    draws = get_all_pingte_draws()
    if not draws:
        return jsonify({"status": "error", "msg": "无开奖数据"})

    if plan.startswith('tail'):
        t = int(element)
        odds = 2.0 if t == 0 else 1.8
    else:
        target_draw = next((d for d in draws if str(d[0]) == str(issue)), None)
        # 👇 核心修改
        if target_draw:
            yz = get_year_zodiac(str(target_draw[0]))
        else:
            yz = get_year_zodiac(str(draws[-1][0]))
        odds = 1.8 if element == yz else 2.0

    execute(
        "INSERT OR REPLACE INTO pingte_bets (plan, issue, element, base_amount, streak, actual_bet, odds, is_hit, created_at) VALUES (?,?,?,?,?,?,?,NULL,?)",
        [plan, issue, element, data.get("base", 0), data.get("streak", 0), bet, odds, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    )
    return jsonify({"status": "ok"})


@pingte_bp.route('/api/delete_bet', methods=['POST'])
def delete_bet():
    data = request.json
    plan = data.get("plan")
    issue = data.get("issue")
    if plan and issue:
        execute("DELETE FROM pingte_bets WHERE plan=? AND issue=?", [plan, issue])
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "msg": "参数缺失"})