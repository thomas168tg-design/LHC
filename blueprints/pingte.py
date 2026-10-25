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
    get_year_zodiac, num_to_zodiac, ZODIAC_ORDER, LUNAR_NEW_YEAR,
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
        latest_date_str = draws[-1][1]
        fmt = "%Y/%m/%d" if "/" in latest_date_str else "%Y-%m-%d"
        try:
            latest_dt = datetime.strptime(latest_date_str.split(" ")[0], fmt)
            current_year = latest_dt.year
        except: current_year = 2026
            
        spring_festival = datetime(current_year, 1, 1)
        for d, z in LUNAR_NEW_YEAR:
            if d.year == current_year:
                spring_festival = d
                break
                
        default_start = f"{current_year}001"
        for d in draws:
            fmt = "%Y/%m/%d" if "/" in d[1] else "%Y-%m-%d"
            try:
                dt = datetime.strptime(d[1].split(" ")[0], fmt)
                if dt >= spring_festival:
                    default_start = str(d[0])
                    break
            except: continue

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
        
        yz = get_year_zodiac(date_str)
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
        latest_date_str = draws[-1][1]
        fmt = "%Y/%m/%d" if "/" in latest_date_str else "%Y-%m-%d"
        try:
            latest_dt = datetime.strptime(latest_date_str.split(" ")[0], fmt)
            current_year = latest_dt.year
        except: current_year = 2026
            
        spring_festival = datetime(current_year, 1, 1)
        for d, z in LUNAR_NEW_YEAR:
            if d.year == current_year:
                spring_festival = d
                break
                
        default_start = f"{current_year}001"
        for d in draws:
            fmt = "%Y/%m/%d" if "/" in d[1] else "%Y-%m-%d"
            try:
                dt = datetime.strptime(d[1].split(" ")[0], fmt)
                if dt >= spring_festival:
                    default_start = str(d[0])
                    break
            except: continue

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
        yz = get_year_zodiac(date_str)
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
        yz = get_year_zodiac(date_str)
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
# 3. 下注台
# ==========================================
@pingte_bp.route('/betting')
def betting():
    try:
        query("SELECT actual_bet FROM pingte_bets LIMIT 1")
    except Exception:
        execute("DROP TABLE IF EXISTS pingte_bets")
        execute("""
            CREATE TABLE pingte_bets (
                issue TEXT PRIMARY KEY, chosen_zodiac TEXT, base_amount REAL, streak REAL,
                actual_bet REAL, odds REAL, is_hit INTEGER, profit REAL, created_at TEXT
            )
        """)

    draws = get_all_pingte_draws()
    if not draws:
        return "无数据，请先更新"
        
    latest_issue = draws[-1][0]
    latest_date = draws[-1][1]
    latest_yz = get_year_zodiac(latest_date)
    
    _, unsolved = query("SELECT issue, chosen_zodiac, actual_bet, odds FROM pingte_bets WHERE is_hit IS NULL")
    for u in unsolved:
        u_issue, u_zodiac, u_bet, u_odds = u
        draw = next((d for d in draws if str(d[0]) == str(u_issue)), None)
        if draw:
            nums = list(draw[2:8]) + [draw[8]]
            yz = get_year_zodiac(draw[1])
            actual_zodiacs = [num_to_zodiac(n, yz) for n in nums]
            
            is_hit = 1 if u_zodiac in actual_zodiacs else 0
            profit = (u_bet * u_odds - u_bet) if is_hit else -u_bet
            execute("UPDATE pingte_bets SET is_hit=?, profit=? WHERE issue=?", [is_hit, profit, u_issue])

    _, all_bets = query("SELECT is_hit FROM pingte_bets ORDER BY issue DESC")
    streak = 0
    for b in all_bets:
        if b[0] is not None and b[0] == 0: streak += 1
        elif b[0] == 1: break
            
    history = get_processed_history()
    recent_20 = history[-20:] if len(history)>=20 else history
    h20 = {z: 0 for z in ZODIAC_ORDER}
    for item in recent_20:
        for z in ZODIAC_ORDER:
            if item["hits"][z]: h20[z] += 1
            
    sorted_z = sorted(ZODIAC_ORDER, key=lambda z: (-h20[z], ZODIAC_ORDER.index(z)))
    top3 = []
    for i in range(3):
        z_name = sorted_z[i]
        cur_miss = 0
        for item in reversed(history):
            if item["hits"][z_name]: break
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
        
        top3.append({
            "zodiac": z_name, "count": h20[z_name], 
            "cur_miss": cur_miss, "max_miss": max_miss
        })

    _, records = query("SELECT issue, chosen_zodiac, actual_bet, odds, is_hit, profit FROM pingte_bets ORDER BY issue DESC LIMIT 50")
    total_profit = sum([float(r[5]) for r in records if r[5] is not None])
    
    return render_template('pingte/betting.html', 
                           latest_issue=str(int(latest_issue)+1),
                           latest_yz=latest_yz, streak=streak, top3=top3,
                           records=records, total_profit=total_profit, zodiacs=ZODIAC_ORDER)

@pingte_bp.route('/api/save_bet', methods=['POST'])
def save_bet():
    data = request.json
    issue = data.get("issue")
    zodiac = data.get("zodiac")
    bet = float(data.get("bet"))
    
    bet = round(bet / 5) * 5
    if not issue or not zodiac or bet <= 0:
        return jsonify({"status": "error", "msg": "参数缺失或金额非法"})
        
    draws = get_all_pingte_draws()
    target_draw = next((d for d in draws if str(d[0]) == str(issue)), None)
    
    if target_draw:
        yz = get_year_zodiac(target_draw[1])
        odds = 1.8 if zodiac == yz else 2.0
    else:
        yz = get_year_zodiac(draws[-1][1])
        odds = 1.8 if zodiac == yz else 2.0
        
    execute(
        "INSERT OR REPLACE INTO pingte_bets (issue, chosen_zodiac, base_amount, streak, actual_bet, odds, is_hit, created_at) VALUES (?,?,?,?,?,?,NULL,?)",
        [issue, zodiac, data.get("base"), data.get("streak"), bet, odds, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    )
    return jsonify({"status": "ok"})

@pingte_bp.route('/api/delete_bet', methods=['POST'])
def delete_bet():
    issue = request.json.get("issue")
    if issue:
        execute("DELETE FROM pingte_bets WHERE issue = ?", [issue])
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"})