# -*- coding: utf-8 -*-
"""
core/pingte/logic.py
平特一肖独立计算引擎，不依赖原 prediction.py，防 OOM
"""
from datetime import datetime
from collections import defaultdict
from database import query, execute, query_one
from core.draws import fetch_from_macaujc
from database import _post

# 农历年节点
LUNAR_NEW_YEAR = [
    (datetime(2027, 2, 6),  "羊"), (datetime(2026, 2, 17), "马"),
    (datetime(2025, 1, 29), "蛇"), (datetime(2024, 2, 10), "龙"),
    (datetime(2023, 1, 22), "兔"), (datetime(2022, 2, 1),  "虎"),
    (datetime(2021, 2, 12), "牛"), (datetime(2020, 1, 25), "鼠"),
    (datetime(2019, 2, 5),  "猪"), (datetime(2018, 2, 16), "狗"),
    (datetime(2017, 1, 28), "鸡"), (datetime(2016, 2, 8),  "猴"),
]
ZODIAC_ORDER = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

def get_year_zodiac(dt_str):
    """根据日期字符串返回当年的太岁生肖"""
    try:
        if "/" in dt_str:
            dt = datetime.strptime(dt_str.split(" ")[0], "%Y/%m/%d")
        else:
            dt = datetime.strptime(dt_str.split(" ")[0], "%Y-%m-%d")
    except:
        return "马"
    for start_date, zodiac in LUNAR_NEW_YEAR:
        if dt >= start_date:
            return zodiac
    return "马"

def num_to_zodiac(num, year_zodiac):
    """号码转生肖"""
    base_idx = ZODIAC_ORDER.index(year_zodiac)
    return ZODIAC_ORDER[(base_idx - (num - 1)) % 12]

def get_all_pingte_draws():
    """获取所有平特开奖数据，按期号升序"""
    _, rows = query("SELECT issue, draw_date, n1, n2, n3, n4, n5, n6, special FROM pingte_draws ORDER BY issue ASC")
    return rows

def import_from_csv(csv_rows):
    """批量打包导入，极速防超时"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stmts = []
    
    for row in csv_rows:
        stmts.append((
            "INSERT OR IGNORE INTO pingte_draws (issue, draw_date, n1, n2, n3, n4, n5, n6, special, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [row["issue"], row["draw_date"], row["n1"], row["n2"], row["n3"], row["n4"], row["n5"], row["n6"], row["special"], now]
        ))
    
    # 每次发 200 条，避免单次数据包过大
    chunk_size = 200
    total = len(stmts)
    count = 0
    
    for i in range(0, total, chunk_size):
        chunk = stmts[i:i + chunk_size]
        try:
            _post(chunk)
            count += len(chunk)
            print(f"已导入 {count} / {total} 期...")
        except Exception as e:
            print(f"分块导入失败 (索引 {i}): {e}")
            
    print(f"✅ 平特数据导入完成，共尝试写入 {total} 期。")

def update_pingte_data():
    """从 web 更新平特数据"""
    row = query_one("SELECT MAX(issue) FROM pingte_draws")
    latest = int(row[0]) if row and row[0] else 0
    next_issue = latest + 1
    added = 0
    
    while added < 10:
        data = fetch_from_macaujc(str(next_issue))
        if not data: break
        nums = data["numbers"]
        execute(
            "INSERT OR IGNORE INTO pingte_draws (issue, draw_date, n1, n2, n3, n4, n5, n6, special, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [str(next_issue), data.get("date", ""), nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], nums[6], datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        )
        next_issue += 1
        added += 1
    return added

# ==========================================
# 核心算法：数据预处理与预测
# ==========================================

def get_processed_history():
    """将原始数据转为带生肖命中状态的结构"""
    draws = get_all_pingte_draws()
    history = []
    for d in draws:
        issue, date_str, n1, n2, n3, n4, n5, n6, sp = d
        yz = get_year_zodiac(date_str)
        nums = [n1, n2, n3, n4, n5, n6, sp]
        hits = {z: False for z in ZODIAC_ORDER}
        for n in nums:
            hits[num_to_zodiac(n, yz)] = True
            
        history.append({
            "issue": str(issue), "date": date_str, "year": get_year_zodiac(date_str),
            "nums": nums, "yz": yz, "hits": hits
        })
    return history

def predict_m6_rank_jump(history):
    """6_排名跃升(短15长20) - 主力模型"""
    if len(history) < 20: return None
    recent_15 = history[-15:]
    recent_20 = history[-20:]
    
    def get_hits(seg):
        c = {z: 0 for z in ZODIAC_ORDER}
        for item in seg:
            for z in ZODIAC_ORDER:
                if item["hits"][z]: c[z] += 1
        return c

    h15 = get_hits(recent_15)
    h20 = get_hits(recent_20)
    rank_15 = {z: sorted(ZODIAC_ORDER, key=lambda x: -h15[x]).index(z) + 1 for z in ZODIAC_ORDER}
    rank_20 = {z: sorted(ZODIAC_ORDER, key=lambda x: -h20[x]).index(z) + 1 for z in ZODIAC_ORDER}
    
    best_z = max(ZODIAC_ORDER, key=lambda z: rank_20[z] - rank_15[z])
    return best_z

def predict_m10_benming_miss(history):
    """10_本命肖连黑2期后追"""
    if not history: return None
    yz = history[-1]["yz"]
    om = 0
    for item in reversed(history):
        if item["hits"][yz]: break
        om += 1
    return yz if om >= 2 else None

def get_current_predictions():
    """获取当前所有模型的推荐"""
    history = get_processed_history()
    if not history: return {"error": "无数据"}
    
    return {
        "m6_rank_jump": predict_m6_rank_jump(history),
        "m10_benming": predict_m10_benming_miss(history),
        "last_issue": history[-1]["issue"],
        "next_issue": str(int(history[-1]["issue"]) + 1),
        "year_zodiac": history[-1]["yz"]
    }

def calculate_recent_stats(history, model_func, window=100):
    """计算某模型在近 N 期的真实命中率"""
    if len(history) <= 20: return {"hits": 0, "total": 0, "rate": 0}
    
    start = max(20, len(history) - window)
    hits = 0
    total = 0
    
    for i in range(start, len(history)):
        pred_z = model_func(history[:i])
        if not pred_z: continue
        
        actual = history[i]
        if actual["hits"][pred_z]: hits += 1
        total += 1
        
    return {"hits": hits, "total": total, "rate": round(hits/total*100, 1) if total else 0}

# ==========================================
# 冷肖监控与连黑统计
# ==========================================
def get_cold_stats():
    """计算当前 12 生肖的遗漏、历史极值、近30期出球数"""
    history = get_processed_history()
    if not history: return []
    
    stats = []
    for z in ZODIAC_ORDER:
        om = 0
        for item in reversed(history):
            if item["hits"][z]: break
            om += 1
            
        # 历史连黑极值
        miss_streaks = []
        cur = 0
        for item in history:
            if item["hits"][z]:
                if cur > 0: miss_streaks.append(cur)
                cur = 0
            else: cur += 1
        max_miss = max(miss_streaks) if miss_streaks else 0
        
        # 近30期出球数（含平特）
        balls_30 = 0
        recent_30 = history[-30:] if len(history) >= 30 else history
        for item in recent_30:
            yz = item["yz"]
            for n in item["nums"]:
                if num_to_zodiac(n, yz) == z: balls_30 += 1
                
        stats.append({
            "zodiac": z,
            "omission": om,
            "max_miss": max_miss,
            "balls_30": balls_30,
            "is_current_year": (z == history[-1]["yz"])
        })
        
    return sorted(stats, key=lambda x: -x["omission"])