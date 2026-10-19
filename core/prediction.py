# -*- coding: utf-8 -*-
"""
core/prediction.py

从 MCSX3V9.9_统一预测_L30状态加权默认.py 改造

【2026-10 重大更新】
为了适配 Render 免费版 512MB 内存限制，彻底弃用了耗内存的 Pandas DataFrame 切片。
底层计算全部改用 Python 原生 list 和 dict，保持原有算法逻辑 100% 不变。
"""

import json
import math
import time
import hashlib
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

from config import TAIL_W, ODDS
from database import execute, query, query_one, _post, init_tables
from core.draws import get_all_draws


# ============================================================
#            全局常量（与 9.9 一致）
# ============================================================

RANDOM_MRR = 0.09141

RANGE_K = 13
RANGE_L = 35
RANGE_TOP_K = 6
RANGE_BOOST = 2.0

ODDS_PAYOUT = ODDS          # 46
ODDS_COST = 10
ODDS_BREAKEVEN_SINGLE = 1.0 / ODDS_PAYOUT  # 每号打平线

TIMING_WINDOW = 100
BET_AMOUNTS = {5: 40, 10: 20, 20: 10}

# 状态加权参数（从 config 读）
TAIL_WEIGHT_JUST_OUT = TAIL_W[0]   # 0.85
TAIL_WEIGHT_SHORT = TAIL_W[1]      # 1.00
TAIL_WEIGHT_MID = TAIL_W[2]        # 1.15
TAIL_WEIGHT_LONG = TAIL_W[3]       # 0.95

POSITION_HISTORY_WINDOW = 150
DYN_WINDOW = 100

MODELS_4 = [
    "排名位置_L30",
    "综合集成_动态_W100",
    "综合集成_动态_W100_状态加权",
    "L30_状态加权",
]


# ============================================================
#            Turso meta 辅助
# ============================================================

def _get_meta(key):
    row = query_one("SELECT value FROM meta WHERE key = ?", [key])
    return row[0] if row else None


def _set_meta(key, value):
    execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        [key, str(value)],
    )


def _data_signature(df):
    raw = "\n".join(
        f"{int(r.期数)},{int(r.特码)}"
        for r in df[["期数", "特码"]].itertuples(index=False)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
#            基础计算（全面改为基于 list 和 dict，防内存溢出）
# ============================================================

def compute_ranking_from_list(history_nums):
    if not history_nums:
        return []
    latest_pos = {}
    for i, n in enumerate(history_nums):
        latest_pos[int(n)] = i
    total = len(history_nums)
    items = []
    for n in range(1, 50):
        omission = total - 1 - latest_pos[n] if n in latest_pos else total
        items.append({"号码": n, "遗漏": omission})
    items.sort(key=lambda x: (-x["遗漏"], x["号码"]))
    for rank, item in enumerate(items, 1):
        item["排名"] = rank
    return items


def compute_features_from_list(history_nums, windows=(10, 30, 60)):
    total = len(history_nums)
    positions = defaultdict(list)
    for i, n in enumerate(history_nums):
        positions[n].append(i)
    
    freq_by_window = {}
    for w in windows:
        sub = history_nums[-w:] if w <= total else history_nums
        freq_by_window[w] = Counter(sub)

    features = {}
    for n in range(1, 50):
        pos_list = positions.get(n, [])
        omission = total - 1 - pos_list[-1] if pos_list else total
        if len(pos_list) >= 2:
            gaps = [pos_list[i + 1] - pos_list[i] for i in range(len(pos_list) - 1)]
            gaps.append(total - 1 - pos_list[-1])
            gaps.sort()
            mid = len(gaps) // 2
            median_gap = (gaps[mid - 1] + gaps[mid]) / 2 if len(gaps) % 2 == 0 else gaps[mid]
        elif len(pos_list) == 1:
            median_gap = max(1.0, total / 2)
        else:
            median_gap = max(1.0, float(total))
        overdue_ratio = omission / median_gap if median_gap > 0 else 1.0
        f = {"omission": omission, "median_omission": median_gap,
             "overdue_ratio": overdue_ratio}
        for w in windows:
            f[f"freq_{w}"] = freq_by_window[w].get(n, 0)
        features[n] = f
    return features


def build_13_intervals():
    intervals = []
    start = 1
    while start <= 49:
        end = min(49, start + 3)
        intervals.append((start, end))
        start = end + 1
    return intervals


_INTERVALS_13 = build_13_intervals()


def position_to_range_idx(pos):
    for idx, (a, b) in enumerate(_INTERVALS_13):
        if a <= pos <= b:
            return idx
    return None


# ============================================================
#            学习库（Turso 版，仅做初始化用）
# ============================================================

def _read_events():
    _, rows = query(
        "SELECT issue, base_issue, actual_number, actual_rank, history_samples "
        "FROM events ORDER BY issue ASC"
    )
    if not rows:
        return pd.DataFrame(columns=["期数", "基准期数", "实际特码", "实际排名", "开奖前历史样本数"])
    return pd.DataFrame(rows, columns=["期数", "基准期数", "实际特码", "实际排名", "开奖前历史样本数"])


def _write_events_to_turso(events_df):
    execute("DELETE FROM events")
    stmts = []
    for r in events_df.itertuples(index=False):
        stmts.append((
            "INSERT INTO events (issue, base_issue, actual_number, actual_rank, history_samples) "
            "VALUES (?, ?, ?, ?, ?)",
            [int(r.期数), int(r.基准期数), int(r.实际特码), int(r.实际排名), int(r.开奖前历史样本数)],
        ))
    if stmts:
        _post(stmts)


def _rebuild_library(df):
    events, ranks = [], []
    for idx in range(1, len(df)):
        target = df.iloc[idx]
        history = df.iloc[:idx]
        ranking = compute_ranking_from_list(history["特码"].astype(int).tolist())
        rank_by_number = {x["号码"]: x["排名"] for x in ranking}
        actual_num = int(target["特码"])
        actual_rank = int(rank_by_number[actual_num])
        events.append({
            "期数": int(target["期数"]),
            "基准期数": int(df.iloc[idx - 1]["期数"]),
            "实际特码": actual_num,
            "实际排名": actual_rank,
            "开奖前历史样本数": len(history),
        })
        # ranks 暂时不写，只写 events 加速
    events_df = pd.DataFrame(events)
    _write_events_to_turso(events_df)
    _set_meta("library_signature", _data_signature(df))
    return events_df


def rebuild_ranks(df=None):
    if df is None:
        df = get_all_draws()
    if df.empty: return 0
    events, ranks = [], []
    for idx in range(1, len(df)):
        target = df.iloc[idx]
        history = df.iloc[:idx]
        nums = history["特码"].astype(int).tolist()
        ranking = compute_ranking_from_list(nums)
        rank_by_number = {x["号码"]: x["排名"] for x in ranking}
        actual_num = int(target["特码"])
        for item in ranking:
            ranks.append({
                "期数": int(target["期数"]),
                "号码": item["号码"],
                "开奖前遗漏": item["遗漏"],
                "开奖前排名": item["排名"],
                "是否实际特码": int(item["号码"] == actual_num),
            })
    execute("DELETE FROM ranks")
    stmts = []
    total = 0
    for r in ranks:
        stmts.append((
            "INSERT INTO ranks (issue, number, omission, rank, is_actual) VALUES (?, ?, ?, ?, ?)",
            [r["期数"], r["号码"], r["开奖前遗漏"], r["开奖前排名"], r["是否实际特码"]],
        ))
        if len(stmts) >= 500:
            _post(stmts)
            total += len(stmts)
            stmts = []
    if stmts:
        _post(stmts)
        total += len(stmts)
    _set_meta("ranks_signature", _data_signature(df))
    return total


def read_library(df, force_rebuild=False):
    init_tables()
    sig = _data_signature(df)
    if not force_rebuild and _get_meta("library_signature") == sig:
        events = _read_events()
        if not events.empty and int(events["期数"].max()) == int(df["期数"].max()):
            return events
    return _rebuild_library(df)


# ============================================================
#            基础方法（5个）
# ============================================================

def compute_base_scores_from_list(prior_ranks, ranking, features):
    res = {}
    res["冷号遗漏"] = {n: f["omission"] for n, f in features.items()}
    res["冷号超期比"] = {n: f["overdue_ratio"] for n, f in features.items()}
    
    # 排名位置_L30
    recent30 = prior_ranks[-30:] if 30 < len(prior_ranks) else prior_ranks
    counts = Counter(recent30)
    num_by_rank = {r["排名"]: r["号码"] for r in ranking}
    res["排名位置_L30"] = {num_by_rank[r]: counts.get(r, 0) for r in range(1, 50)}

    # 排名位置衰减_H30
    n = len(prior_ranks)
    decay = math.log(2) / 30
    scores_by_rank = {r: 0.0 for r in range(1, 50)}
    for i, r in enumerate(prior_ranks):
        age = n - 1 - i
        scores_by_rank[r] += math.exp(-decay * age)
    res["排名位置衰减_H30"] = {num_by_rank[r]: scores_by_rank[r] for r in range(1, 50)}

    # 区间13_L35_Top6
    recent35 = prior_ranks[-RANGE_L:] if RANGE_L < len(prior_ranks) else prior_ranks
    range_counts = Counter()
    for pos in recent35:
        idx = position_to_range_idx(pos)
        if idx is not None:
            range_counts[idx] += 1
    top_ranges = set(idx for idx, _ in range_counts.most_common(RANGE_TOP_K))
    
    base_scores = res["排名位置衰减_H30"]
    final = {}
    for rank_pos in range(1, 50):
        num = num_by_rank[rank_pos]
        base = base_scores.get(num, 0.0)
        idx = position_to_range_idx(rank_pos)
        if idx is not None and idx in top_ranges:
            final[num] = base * RANGE_BOOST
        else:
            final[num] = base
    res["区间13_L35_Top6"] = final
    
    return res


BASE_METHODS = {
    "冷号遗漏": "冷号遗漏",
    "冷号超期比": "冷号超期比",
    "排名位置_L30": "排名位置_L30",
    "排名位置衰减_H30": "排名位置衰减_H30",
    "区间13_L35_Top6": "区间13_L35_Top6",
}

DYN_METHODS = ["排名位置_L30", "排名位置衰减_H30"]
DEFAULT_METHOD = "L30_状态加权"


# ============================================================
#            动态权重 + 聚合
# ============================================================

def compute_dynamic_weights(position_history, current_issue, window=100, methods=None):
    if methods is None:
        methods = DYN_METHODS
    all_periods = set()
    for m in methods:
        for p in position_history.get(m, {}).keys():
            if p < current_issue:
                all_periods.add(p)
    periods = sorted(all_periods)[-window:]
    if len(periods) < 20:
        return {m: 1.0 / len(methods) for m in methods}
    mrr = {}
    for m in methods:
        ps = [position_history[m][p] for p in periods
              if p in position_history.get(m, {}) and position_history[m][p] > 0]
        mrr[m] = sum(1.0 / p for p in ps) / len(ps) if ps else 0.0
    survivors = {m: v for m, v in mrr.items() if v > RANDOM_MRR}
    if not survivors:
        survivors = mrr
    total = sum(survivors.values())
    if total <= 0:
        return {m: 1.0 / len(survivors) for m in survivors}
    return {m: survivors[m] / total for m in survivors}


def aggregate_equal(base_scores, position_history, current_issue, history_nums=None):
    keys = list(base_scores.keys())
    return {n: sum(base_scores[m].get(n, 0) for m in keys) / len(keys)
            for n in range(1, 50)}


def aggregate_dynamic(base_scores, position_history, current_issue, history_nums=None, window=100):
    weights = compute_dynamic_weights(position_history, current_issue, window=window)
    return {n: sum(weights.get(m, 0) * base_scores[m].get(n, 0) for m in weights)
            for n in range(1, 50)}


def compute_tail_streaks(history_data):
    if hasattr(history_data, "empty"):
        numbers = history_data["特码"].astype(int).tolist()
    else:
        numbers = history_data
        
    last_pos = {}
    for i, n in enumerate(numbers):
        last_pos[n % 10] = i
    total = len(numbers)
    streaks = {}
    for t in range(10):
        if t in last_pos:
            streaks[t] = total - 1 - last_pos[t]
        else:
            streaks[t] = total
    return streaks


def tail_weight(streak):
    if streak <= 1: return TAIL_WEIGHT_JUST_OUT
    elif streak <= 5: return TAIL_WEIGHT_SHORT
    elif streak <= 15: return TAIL_WEIGHT_MID
    else: return TAIL_WEIGHT_LONG


def aggregate_dynamic_with_state(base_scores, position_history, current_issue, history_nums=None, window=100):
    base = aggregate_dynamic(base_scores, position_history, current_issue, history_nums, window=window)
    if not history_nums: return base
    streaks = compute_tail_streaks(history_nums)
    final = {}
    for n in range(1, 50):
        w = tail_weight(streaks[n % 10])
        final[n] = base[n] * w
    return final


def aggregate_L30_with_state(base_scores, position_history, current_issue, history_nums=None, window=None):
    l30 = base_scores["排名位置_L30"]
    if not history_nums: return l30
    streaks = compute_tail_streaks(history_nums)
    final = {}
    for n in range(1, 50):
        w = tail_weight(streaks[n % 10])
        final[n] = l30.get(n, 0) * w
    return final


AGG_METHODS = {
    "综合集成_等权":                lambda bs, ph, ci, hn: aggregate_equal(bs, ph, ci, hn),
    "综合集成_动态_W60":            lambda bs, ph, ci, hn: aggregate_dynamic(bs, ph, ci, hn, window=60),
    "综合集成_动态_W100":           lambda bs, ph, ci, hn: aggregate_dynamic(bs, ph, ci, hn, window=100),
    "综合集成_动态_W150":           lambda bs, ph, ci, hn: aggregate_dynamic(bs, ph, ci, hn, window=150),
    "综合集成_动态_W100_状态加权":   lambda bs, ph, ci, hn: aggregate_dynamic_with_state(bs, ph, ci, hn, window=100),
    "L30_状态加权":                 lambda bs, ph, ci, hn: aggregate_L30_with_state(bs, ph, ci, hn),
}

ALL_METHODS = {**BASE_METHODS, **AGG_METHODS}

_CACHE_MEM = {"end_issue": None, "method_positions": None, "sig": None}


# ============================================================
#            核心降内存计算逻辑
# ============================================================

def _compute_all_method_positions(df, events, end_issue):
    all_issues = sorted(df[df["期数"] <= end_issue]["期数"].tolist())
    position_history = {m: {} for m in BASE_METHODS}
    method_positions = {m: {} for m in ALL_METHODS}

    df_dict = df.set_index("期数").to_dict("index")
    events_dict = {row["期数"]: row for row in events.to_dict("records")}
    
    for i, t in enumerate(all_issues):
        prior_issues = all_issues[:i]
        if len(prior_issues) < 4: continue
            
        prior_nums = [df_dict[iss]["特码"] for iss in prior_issues]
        prior_ranks = [events_dict[iss]["实际排名"] for iss in prior_issues if iss in events_dict]
        if len(prior_ranks) < 4: continue
            
        ranking = compute_ranking_from_list(prior_nums)
        features = compute_features_from_list(prior_nums)
        base_scores = compute_base_scores_from_list(prior_ranks, ranking, features)
        
        actual = df_dict[t]["特码"]
        
        for m, s in base_scores.items():
            ranked = sorted(s.keys(), key=lambda n: (-s[n], n))
            if actual in ranked:
                position_history[m][t] = ranked.index(actual) + 1

        for method_name in ALL_METHODS:
            if method_name in base_scores:
                scores = base_scores[method_name]
            elif method_name in AGG_METHODS:
                scores = AGG_METHODS[method_name](base_scores, position_history, t, prior_nums)
            else:
                continue
            ranked_nums = sorted(scores.keys(), key=lambda n: (-scores[n], n))
            if actual in ranked_nums:
                method_positions[method_name][t] = ranked_nums.index(actual) + 1

    return method_positions


def _build_cache(df, events, end_issue, force=False):
    end_issue = int(end_issue)
    sig = _data_signature(df)

    if (not force and _CACHE_MEM["end_issue"] == end_issue
            and _CACHE_MEM["method_positions"] is not None
            and _CACHE_MEM["sig"] == sig):
        return _CACHE_MEM["method_positions"]

    if not force:
        cached_sig = _get_meta("cache_signature")
        cached_end = _get_meta("cache_end_issue")
        if cached_sig == sig and cached_end is not None and int(cached_end) == end_issue:
            raw = _get_meta("cache_method_positions")
            if raw:
                try:
                    mp_raw = json.loads(raw)
                    mp = {m: {int(k): int(v) for k, v in kv.items()} for m, kv in mp_raw.items()}
                    _CACHE_MEM.update({"end_issue": end_issue, "method_positions": mp, "sig": sig})
                    return mp
                except Exception:
                    pass

    t0 = time.time()
    mp = _compute_all_method_positions(df, events, end_issue)
    _CACHE_MEM.update({"end_issue": end_issue, "method_positions": mp, "sig": sig})

    try:
        mp_json = {m: {str(k): int(v) for k, v in d.items()} for m, d in mp.items()}
        _set_meta("cache_method_positions", json.dumps(mp_json, ensure_ascii=False))
        _set_meta("cache_signature", sig)
        _set_meta("cache_end_issue", str(end_issue))
    except Exception:
        pass

    print(f"[cache] 重算 method_positions 用时 {time.time() - t0:.1f} 秒，end_issue={end_issue}")
    return mp


def get_prediction(df, events, target_issue, method_name):
    df_dict = df.set_index("期数").to_dict("index")
    events_dict = {row["期数"]: row for row in events.to_dict("records")}
    
    prior_issues = sorted([iss for iss in df_dict.keys() if iss < target_issue])
    if len(prior_issues) < 2: return None
        
    prior_nums = [df_dict[iss]["特码"] for iss in prior_issues]
    prior_ranks = [events_dict[iss]["实际排名"] for iss in prior_issues if iss in events_dict]
    if len(prior_ranks) < 4: return None

    ranking = compute_ranking_from_list(prior_nums)
    features = compute_features_from_list(prior_nums)
    base_scores = compute_base_scores_from_list(prior_ranks, ranking, features)

    if method_name in AGG_METHODS:
        recent = prior_issues[-POSITION_HISTORY_WINDOW:]
        position_history = {m: {} for m in BASE_METHODS}
        for t in recent:
            t_idx = prior_issues.index(t)
            sub_nums = prior_nums[:t_idx]
            if len(sub_nums) < 2: continue
            
            sub_ranking = compute_ranking_from_list(sub_nums)
            sub_features = compute_features_from_list(sub_nums)
            sub_ranks = [events_dict[iss]["实际排名"] for iss in prior_issues[:t_idx] if iss in events_dict]
            if len(sub_ranks) < 4: continue
                
            bs = compute_base_scores_from_list(sub_ranks, sub_ranking, sub_features)
            ac = df_dict[t]["特码"]
            for m, s in bs.items():
                r = sorted(s.keys(), key=lambda n: (-s[n], n))
                if ac in r:
                    position_history[m][t] = r.index(ac) + 1
                    
        scores = AGG_METHODS[method_name](base_scores, position_history, target_issue, prior_nums)
    elif method_name in BASE_METHODS:
        scores = base_scores[method_name]
    else:
        return None

    ranked = sorted(scores.keys(), key=lambda n: (-scores[n], n))
    return {
        "target_issue": int(target_issue),
        "method": method_name,
        "ranked_numbers": [(n, scores[n]) for n in ranked],
    }


# ============================================================
#            对外 6 个接口
# ============================================================

def run_unified_prediction(target_issue=None, display_method=None):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    if target_issue is None: target_issue = int(df["期数"].max()) + 1
    target_issue = int(target_issue)

    events = read_library(df)
    mp = _build_cache(df, events, target_issue - 1)

    t0 = time.time()
    all_predictions = {}
    for method_name in ALL_METHODS:
        result = get_prediction(df, events, target_issue, method_name)
        if result is None: continue
        all_predictions[method_name] = [n for n, _ in result["ranked_numbers"]]

    if not all_predictions: return {"error": "历史样本不足"}

    if display_method not in all_predictions:
        display_method = DEFAULT_METHOD
    signal_method = display_method

    signals = {}
    for top_k in [5, 10, 12, 20]:
        sig = compute_signal(mp, signal_method, target_issue - 1, top_k)
        if sig: signals[top_k] = sig

    counts5 = Counter()
    for m, ranked in all_predictions.items():
        for n in ranked[:5]:
            counts5[n] += 1
    consensus_all = sorted(counts5.items(), key=lambda x: (-x[1], x[0]))

    recent_issues = sorted(df[df["期数"] < target_issue]["期数"].tolist())[-100:]
    recent_history = []
    for iss in recent_issues:
        row = df[df["期数"] == iss]
        if row.empty: continue
        actual = int(row.iloc[0]["特码"])
        if display_method in mp and iss in mp[display_method]:
            pos = mp[display_method][iss]
            recent_history.append({
                "issue": int(iss), "actual": actual, "pos": pos,
                "t5": pos <= 5, "t10": pos <= 10, "t20": pos <= 20,
            })

    return {
        "target_issue": target_issue,
        "display_method": display_method,
        "signal_method": signal_method,
        "signals": signals,
        "all_predictions": all_predictions,
        "consensus_all": consensus_all,
        "recent_history": recent_history,
        "ranked": all_predictions[display_method],
        "base_methods": list(BASE_METHODS.keys()),
        "agg_methods": list(AGG_METHODS.keys()),
        "elapsed": round(time.time() - t0, 2),
    }


def _max_miss(arr):
    mx = 0; cur = 0
    for h in arr:
        if h == 0:
            cur += 1
            if cur > mx: mx = cur
        else: cur = 0
    return mx


def compute_signal(mp, method_name, end_issue, top_k, window=TIMING_WINDOW):
    if method_name not in mp: return None
    items = sorted(mp[method_name].items())
    items = [(i, p) for i, p in items if i <= end_issue]
    recent = items[-window:]
    if len(recent) < window: return None
    hits = [1 if p <= top_k else 0 for _, p in recent]
    rate = sum(hits) / len(hits)
    breakeven = top_k * ODDS_BREAKEVEN_SINGLE
    cm = 0
    for h in reversed(hits):
        if h == 1: break
        cm += 1
    recent30 = hits[-30:]
    rate30 = sum(recent30) / len(recent30) if recent30 else 0
    return {
        "top_k": top_k, "rate": rate, "rate30": rate30, "breakeven": breakeven,
        "should_bet": rate >= breakeven and rate30 >= breakeven,
        "consecutive_miss": cm, "max_miss_100": _max_miss(hits), "max_miss_30": _max_miss(recent30),
    }


def run_backtest(start_issue, end_issue, top_ks, use_timing, methods=None):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    events = read_library(df)
    mp = _build_cache(df, events, int(end_issue))
    if not methods: methods = [DEFAULT_METHOD]

    summary = []
    for method_name in methods:
        if method_name not in mp: continue
        all_items = sorted(mp[method_name].items())
        idx_by_issue = {iss: gi for gi, (iss, _) in enumerate(all_items)}
        items = [(i, p) for i, p in all_items if start_issue <= i <= end_issue]

        for top_k in top_ks:
            per_number = BET_AMOUNTS.get(top_k, 10)
            cost_per_period = top_k * per_number
            breakeven = top_k * ODDS_BREAKEVEN_SINGLE
            bet_count = hit_count = revenue = invested = 0
            running = max_dd = peak = 0

            for issue, pos in items:
                gi = idx_by_issue.get(issue)
                if gi is None: continue
                should_bet = True
                if use_timing:
                    if gi < TIMING_WINDOW: should_bet = False
                    else:
                        past = all_items[gi - TIMING_WINDOW:gi]
                        past_hits = [1 if p <= top_k else 0 for _, p in past]
                        past_rate = sum(past_hits) / len(past_hits)
                        past30 = past_hits[-30:]
                        past_rate30 = sum(past30) / len(past30) if past30 else 0
                        should_bet = past_rate >= breakeven and past_rate30 >= breakeven
                if not should_bet: continue
                bet_count += 1
                invested += cost_per_period
                if pos <= top_k:
                    hit_count += 1
                    revenue += ODDS_PAYOUT * per_number
                    period_profit = ODDS_PAYOUT * per_number - cost_per_period
                else:
                    period_profit = -cost_per_period
                running += period_profit
                if running > peak: peak = running
                dd = peak - running
                if dd > max_dd: max_dd = dd

            profit = revenue - invested
            roi = profit / invested if invested > 0 else 0
            hit_rate = hit_count / bet_count if bet_count > 0 else 0
            summary.append({
                "method": method_name, "top_k": top_k, "timing": bool(use_timing),
                "bet_count": bet_count, "hit_count": hit_count, "hit_rate": round(hit_rate, 4),
                "invested": invested, "revenue": revenue, "profit": profit,
                "roi": round(roi, 4), "max_dd": max_dd,
            })
    return {"start_issue": int(start_issue), "end_issue": int(end_issue), "top_ks": list(top_ks), "use_timing": bool(use_timing), "summary": summary}


def run_streak_view(end_issue=None, methods=None, top_ks=[5, 10, 12, 20], windows=["all"]):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    if end_issue is None: end_issue = int(df["期数"].max())
    end_issue = int(end_issue)
    events = read_library(df)
    mp = _build_cache(df, events, end_issue)
    
    if not methods: methods = [DEFAULT_METHOD]
    
    # 历史窗口定义
    def get_sub_items(all_items, w_key):
        if w_key == "all": return all_items
        if w_key == "2026": return [(i, p) for i, p in all_items if i >= 2026001]
        if w_key == "100": return all_items[-100:]
        if w_key == "30": return all_items[-30:]
        # 支持年份季度比如 2026Q1
        if len(w_key) == 6 and w_key.endswith("Q1"): 
            year = int(w_key[:4])
            return [(i, p) for i, p in all_items if year*1000+1 <= i <= year*1000+90]
        if len(w_key) == 6 and w_key.endswith("Q2"):
            year = int(w_key[:4])
            return [(i, p) for i, p in all_items if year*1000+91 <= i <= year*1000+180]
        if len(w_key) == 6 and w_key.endswith("Q3"):
            year = int(w_key[:4])
            return [(i, p) for i, p in all_items if year*1000+181 <= i <= year*1000+270]
        if len(w_key) == 6 and w_key.endswith("Q4"):
            year = int(w_key[:4])
            return [(i, p) for i, p in all_items if year*1000+271 <= i <= year*1000+366]
        return all_items

    results = []
    for method in methods:
        if method not in mp: continue
        all_items = sorted(mp[method].items())
        all_items = [(i, p) for i, p in all_items if i <= end_issue]
        
        for w_key in windows:
            sub_items = get_sub_items(all_items, w_key)
            if not sub_items: continue
            
            for top_k in top_ks:
                hits = [1 if p <= top_k else 0 for _, p in sub_items]
                st = _streak_stats(hits, w_key)
                if st is not None:
                    # 统计连开(0)和连黑(>0)
                    streaks_dict = Counter()
                    cur = 0
                    for h in hits:
                        if h == 0: cur += 1
                        else:
                            if cur >= 0: streaks_dict[cur] += 1
                            cur = 0
                    if cur >= 0: streaks_dict[cur] += 1
                    
                    st["streak_counts"] = dict(sorted(streaks_dict.items()))
                    st["method"] = method
                    st["window"] = w_key
                    st["top_k"] = top_k
                    results.append(st)
                    
    return {"end_issue": end_issue, "results": results}

def _streak_stats(hits, label):
    n = len(hits)
    if n == 0: return None
    total_hits = sum(hits)
    rate = total_hits / n
    streaks = []
    cur = 0
    for h in hits:
        if h: streaks.append(cur); cur = 0
        else: cur += 1
    if cur > 0: streaks.append(cur)
    cur_miss = 0
    for h in reversed(hits):
        if h == 1: break
        cur_miss += 1
    max_miss = max(streaks) if streaks else 0
    avg_miss = sum(streaks) / len(streaks) if streaks else 0
    if streaks:
        ss = sorted(streaks)
        p50 = ss[len(ss) // 2]
        p90 = ss[int(len(ss) * 0.90)] if len(ss) >= 10 else ss[-1]
        p95 = ss[int(len(ss) * 0.95)] if len(ss) >= 20 else ss[-1]
    else:
        p50 = p90 = p95 = 0
    return {"label": label, "n": n, "hits": total_hits, "rate": rate, "cur_miss": cur_miss, "max_miss": max_miss, "avg_miss": avg_miss, "p50": p50, "p90": p90, "p95": p95}


def run_cold_watch(target_issue=None):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    if target_issue is None: target_issue = int(df["期数"].max()) + 1
    target_issue = int(target_issue)
    history = df[df["期数"] < target_issue]
    if history.empty: return {"error": "没有历史数据"}
    numbers = history["特码"].astype(int).tolist()
    total = len(numbers)
    last_pos = {}
    for i, n in enumerate(numbers): last_pos[n] = i
    omissions = {n: (total - 1 - last_pos[n] if n in last_pos else total) for n in range(1, 50)}
    per_number_gaps = {}
    all_gaps_global = []
    for num in range(1, 50):
        pos_list = [i for i, x in enumerate(numbers) if x == num]
        if not pos_list: per_number_gaps[num] = []; continue
        gaps = [pos_list[i + 1] - pos_list[i] for i in range(len(pos_list) - 1)]
        if gaps: all_gaps_global.extend(gaps)
        per_number_gaps[num] = gaps
    sorted_all = sorted(all_gaps_global)
    def quantile(q):
        if not sorted_all: return 0
        return sorted_all[min(len(sorted_all) - 1, int(len(sorted_all) * q))]
    q75, q90, q95, q99 = quantile(0.75), quantile(0.90), quantile(0.95), quantile(0.99)
    q_max = sorted_all[-1] if sorted_all else 0
    sorted_items = sorted(omissions.items(), key=lambda x: -x[1])
    rows = []
    for num, om in sorted_items:
        if om < q75: continue
        max_gap_num = max(per_number_gaps.get(num, [0]))
        if om >= q99: mark = "★★★ ≥99%"
        elif om >= q95: mark = "★★ ≥95%"
        elif om >= q90: mark = "★ ≥90%"
        else: mark = "≥75%"
        rows.append({"number": num, "omission": om, "max_gap": max_gap_num, "mark": mark})
    buckets = []
    for name, lo, hi in [("≥99%", q99, 10**9), ("≥95%", q95, q99), ("≥90%", q90, q95), ("≥75%", q75, q90)]:
        nums = [n for n, om in omissions.items() if lo <= om < hi]
        if nums: buckets.append({"name": name, "count": len(nums), "numbers": sorted(nums)})
    return {"target_issue": target_issue, "history_total": total, "quantiles": {"q75": q75, "q90": q90, "q95": q95, "q99": q99, "q_max": q_max}, "rows": rows, "buckets": buckets}


def run_state_view(target_issue=None, recent_n=10):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    if target_issue is None: target_issue = int(df["期数"].max()) + 1
    target_issue = int(target_issue)
    
    events = read_library(df)
    events_dict = {row["期数"]: row for row in events.to_dict("records")}
    
    # 极速优化：直接转成 list 操作
    all_issues = df[df["期数"] < target_issue]["期数"].tolist()
    all_specials = df[df["期数"] < target_issue]["特码"].tolist()
    if len(all_issues) < 60: return {"error": "历史不足"}
    
    def get_rank_and_num(issue):
        if issue in events_dict:
            return events_dict[issue]["实际排名"], events_dict[issue]["实际特码"]
        return 99, 0

    idx_now, idx_prev = len(all_issues) - 1, len(all_issues) - 2
    issue_now, issue_prev = all_issues[idx_now], all_issues[idx_prev]
    
    prev_rank, actual_num = get_rank_and_num(issue_now)
    prev_prev_rank, prev_num = get_rank_and_num(issue_prev)
    rank_diff = prev_rank - prev_prev_rank
    
    # 上上期权重详情
    hist_prev_prev_nums = all_specials[:idx_prev]
    streaks_prev_prev = compute_tail_streaks(hist_prev_prev_nums)
    prev_prev_tail = prev_num % 10
    prev_prev_weight = tail_weight(streaks_prev_prev[prev_prev_tail])
    
    # 上期权重详情
    hist_prev_nums = all_specials[:idx_now]
    streaks_prev = compute_tail_streaks(hist_prev_nums)
    prev_tail = actual_num % 10
    prev_weight = tail_weight(streaks_prev[prev_tail])
    
    def w_desc_fn(w):
        if w > 1.0: return "升权(中遗漏)"
        elif w < 1.0: return "降权(冷门)"
        else: return "正常"
        
    is_correct = prev_weight >= 1.0

    # 近 N 期历史验证 (O(N) 纯原生操作，瞬间完成)
    recent_list = []
    hits = 0
    start_i = max(1, len(all_issues) - recent_n)
    for i in range(start_i, len(all_issues)):
        issue = all_issues[i]
        prev_issue = all_issues[i-1]
        
        sub_nums = all_specials[:i]
        streaks = compute_tail_streaks(sub_nums)
        
        rank_now, actual = get_rank_and_num(issue)
        rank_prev, _ = get_rank_and_num(prev_issue)
        diff = rank_now - rank_prev
        tail = actual % 10
        weight = tail_weight(streaks[tail])
        
        w_desc = w_desc_fn(weight)
        if weight >= 1.0:
            hits += 1
            is_c = True
        else:
            is_c = False
            
        recent_list.append({
            "issue": issue, "actual": actual, "tail": tail,
            "rank_now": rank_now, "rank_prev": rank_prev, "diff": diff,
            "weight": weight, "w_desc": w_desc, "is_correct": is_c
        })
    recent_list.reverse()
    accuracy = hits / len(recent_list) if recent_list else 0

    # 当前遗漏
    current_streaks = compute_tail_streaks(all_specials)
    tail_rows = []
    for t in range(10):
        s = current_streaks[t]; w = tail_weight(s)
        if s <= 1: desc = "刚出（降权）"
        elif s <= 5: desc = "短遗漏（正常）"
        elif s <= 15: desc = "★ 中遗漏（升权）"
        else: desc = "长遗漏（降权）"
        tail_rows.append({"tail": t, "streak": s, "weight": w, "desc": desc})
        
    mp = _build_cache(df, events, target_issue - 1)
    method = DEFAULT_METHOD
    model_100 = []
    if method in mp:
        items = sorted(mp[method].items())
        items = [(i, p) for i, p in items if i < target_issue]
        recent = items[-100:]
        n = len(recent)
        if n > 0:
            for top_k in [5, 10, 12, 20]:
                r_hits = sum(1 for _, p in recent if p <= top_k)
                rate = r_hits / n
                breakeven = top_k * ODDS_BREAKEVEN_SINGLE
                model_100.append({"top_k": top_k, "rate": rate, "breakeven": breakeven, "diff": rate - breakeven, "above": rate - breakeven > 0})
                
    return {
        "target_issue": target_issue, 
        "recent_n": recent_n,
        "accuracy": accuracy,
        "diff": {
            "prev_prev_rank": prev_prev_rank, "prev_prev_num": prev_num, "prev_prev_tail": prev_prev_tail, 
            "prev_prev_weight": prev_prev_weight, "prev_prev_w_desc": w_desc_fn(prev_prev_weight),
            "prev_rank": prev_rank, "prev_num": actual_num, "prev_tail": prev_tail, 
            "prev_weight": prev_weight, "prev_w_desc": w_desc_fn(prev_weight),
            "is_correct": is_correct,
            "rank_diff": rank_diff
        }, 
        "tail_streaks": tail_rows, 
        "model_100": model_100, 
        "method": method,
        "recent_list": recent_list
    }


def run_model_panel(end_issue=None, top_ks=[5, 10, 12, 20]):
    df = get_all_draws()
    if df.empty: return {"error": "数据为空"}
    if end_issue is None: end_issue = int(df["期数"].max())
    end_issue = int(end_issue)
    events = read_library(df)
    mp = _build_cache(df, events, end_issue)
    windows = [5, 10, 20, 30, 60, 100, 200]
    result = {"end_issue": end_issue, "windows": windows, "by_model": {}, "top_ks": top_ks}
    
    for m in MODELS_4:
        if m not in mp: continue
        all_items = sorted(mp[m].items())
        all_items = [(i, p) for i, p in all_items if i <= end_issue]
        
        model_data = {"mrr": {}}
        for k in top_ks: model_data[f"top{k}"] = {}
        
        for w in windows:
            sub = all_items[-w:] if w <= len(all_items) else all_items
            if not sub:
                model_data["mrr"][w] = None
                for k in top_ks: model_data[f"top{k}"][w] = None
                continue
            
            model_data["mrr"][w] = round(sum(1.0 / max(p, 1) for _, p in sub) / len(sub), 5)
            for k in top_ks:
                model_data[f"top{k}"][w] = round(sum(1 for _, p in sub if p <= k) / len(sub), 4)
                
        result["by_model"][m] = model_data

    # 计算每个窗口的最优
    result["best"] = {}
    for key in ["mrr"] + [f"top{k}" for k in top_ks]:
        result["best"][key] = {}
        for w in windows:
            best_m, best_v = None, -1
            for m, d in result["by_model"].items():
                v = d[key].get(w)
                if v is not None and v > best_v:
                    best_v = v
                    best_m = m
            result["best"][key][w] = (best_m, best_v)
    return result