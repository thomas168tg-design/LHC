# -*- coding: utf-8 -*-
"""
app.py — Flask 主程序
"""

import os
import time
import psutil
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)

from config import LOGIN_PASSWORD, SECRET_KEY
from core import draws, prediction, insurance
from database import init_tables, query_one, execute

app = Flask(__name__)
app.secret_key = SECRET_KEY

# 确保启动时建表
with app.app_context():
    try:
        init_tables()
    except Exception as e:
        print(f"初始化数据库失败: {e}")

# ============================================================
#            系统接口
# ============================================================

@app.route("/api/memory")
def api_memory():
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / 1024 / 1024
    return jsonify({"mem": round(mem_mb, 1)})

# ============================================================
#            登录鉴权
# ============================================================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == LOGIN_PASSWORD:
            session["logged_in"] = True
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
        flash("密码错误", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("login"))

# ============================================================
#            首页
# ============================================================

@app.route("/")
@login_required
def index():
    s = draws.stats()
    return render_template("index.html", stats=s)

# ============================================================
#            数据管理
# ============================================================

@app.route("/draws")
@login_required
def draws_list():
    limit_raw = request.args.get("limit", "10")
    try:
        limit = int(limit_raw)
    except Exception:
        limit = 10

    if limit <= 0:
        df = draws.get_all_draws()
    else:
        df = draws.get_last_n(limit)

    records = df.iloc[::-1].to_dict("records")
    latest = records[0] if records else None
    s = draws.stats()
    return render_template("draws.html", records=records, latest=latest, stats=s, limit=limit)

@app.route("/draws/update", methods=["POST"])
@login_required
def draws_update():
    t0 = time.time()
    try:
        r = draws.update_from_web(max_new=20)
        elapsed = round(time.time() - t0, 1)
        if r["added"] > 0:
            flash(f"更新完成：新增 {r['added']} 期（{r['first_issue']} → {r['last_issue']}），耗时 {elapsed}s", "success")
        else:
            flash(f"没有新期，本地已是最新（{r['latest_before']}），耗时 {elapsed}s", "info")
    except Exception as e:
        flash(f"更新失败：{type(e).__name__}: {e}", "danger")
    return redirect(url_for("draws_list"))

@app.route("/draws/add", methods=["POST"])
@login_required
def draws_add():
    try:
        issue = int(str(request.form["issue"]).strip())
        special = int(str(request.form["special"]).strip())
        if not (1 <= special <= 49):
            raise ValueError("特码必须在 1-49")
        draws.upsert_draw(issue, special)
        flash(f"已录入 {issue} 期：特码 {special}", "success")
    except Exception as e:
        flash(f"录入失败：{e}", "danger")
    return redirect(url_for("draws_list"))

# ============================================================
#            单期预测
# ============================================================

@app.route("/predict", methods=["GET", "POST"])
@login_required
def predict():
    if request.method == "GET":
        df = draws.get_all_draws()
        default_issue = (int(df["期数"].max()) + 1) if not df.empty else None
        return render_template("predict.html", r=None, default_issue=default_issue)

    target_raw = request.form.get("target_issue", "").strip()
    display_method = request.form.get("display_method", "").strip() or None
    consensus_raw = request.form.get("consensus_n", "10").strip()
    recent_raw = request.form.get("recent_n", "10").strip()

    target = None
    if target_raw:
        try:
            target = int(target_raw)
        except Exception:
            flash(f"目标期数无效：{target_raw}", "warning")

    try:
        consensus_n = max(1, min(20, int(consensus_raw)))
    except Exception:
        consensus_n = 10

    try:
        recent_n = max(10, min(100, int(recent_raw)))
    except Exception:
        recent_n = 10

    t0 = time.time()
    try:
        r = prediction.run_unified_prediction(target_issue=target, display_method=display_method)
    except Exception as e:
        flash(f"预测失败：{type(e).__name__}: {e}", "danger")
        return redirect(url_for("predict"))

    r["wall"] = round(time.time() - t0, 1)
    r["consensus_n"] = consensus_n
    r["recent_n"] = recent_n
    return render_template("predict.html", r=r, default_issue=None)

# ============================================================
#            区域盲测 / 连不中 / 冷号 / 状态 / 面板 (保持原样)
# ============================================================

@app.route("/backtest", methods=["GET", "POST"])
@login_required
def backtest():
    if request.method == "GET":
        df = draws.get_all_draws()
        max_issue = int(df["期数"].max()) if not df.empty else 0
        min_issue = int(df["期数"].min()) if not df.empty else 0
        return render_template("backtest.html", r=None, min_issue=min_issue, max_issue=max_issue, all_methods=prediction.ALL_METHODS.keys())
    
    start_issue = int(request.form.get("start_issue", 2023001))
    end_issue = int(request.form.get("end_issue", 2026289))
    use_timing = request.form.get("use_timing") == "1"
    
    top_ks_str = request.form.getlist("top_ks")
    top_ks = [int(k) for k in top_ks_str] if top_ks_str else [5, 10, 12, 20]
    selected_methods = request.form.getlist("methods")
    if not selected_methods:
        selected_methods = [prediction.DEFAULT_METHOD]

    t0 = time.time()
    r = prediction.run_backtest(start_issue, end_issue, top_ks, use_timing, methods=selected_methods)
    r["wall"] = round(time.time() - t0, 1)
    
    return render_template("backtest.html", r=r, min_issue=start_issue, max_issue=end_issue, all_methods=prediction.ALL_METHODS.keys())

@app.route("/streak", methods=["GET", "POST"])
@login_required
def streak():
    methods = request.values.getlist("methods")
    if not methods: methods = [prediction.DEFAULT_METHOD]
    top_ks_str = request.values.getlist("top_ks")
    top_ks = [int(k) for k in top_ks_str] if top_ks_str else [5, 10, 12, 20]
    windows = request.values.getlist("windows")
    if not windows: windows = ["all"]
    
    t0 = time.time()
    r = prediction.run_streak_view(methods=methods, top_ks=top_ks, windows=windows)
    r["wall"] = round(time.time() - t0, 1)
    r["selected_methods"] = methods
    r["selected_topks"] = top_ks
    r["selected_windows"] = windows
    r["all_methods"] = prediction.ALL_METHODS.keys()
    return render_template("streak.html", r=r)

@app.route("/cold")
@login_required
def cold():
    target_raw = request.args.get("target_issue", "").strip()
    target = int(target_raw) if target_raw else None
    t0 = time.time()
    r = prediction.run_cold_watch(target_issue=target)
    r["wall"] = round(time.time() - t0, 1)
    return render_template("cold.html", r=r)

@app.route("/api/cold_backtest")
@login_required
def api_cold_backtest():
    target = int(request.args.get("target_issue"))
    periods_raw = request.args.get("periods", "90")
    periods = [int(x) for x in periods_raw.split(",") if x.strip()]
    res = prediction.run_cold_backtest(target, periods)
    return jsonify(res)

@app.route("/api/cold_history365")
@login_required
def api_cold_history365():
    target = int(request.args.get("target_issue"))
    res = prediction.run_cold_history_365(target)
    return jsonify(res)

@app.route("/state")
@login_required
def state():
    recent_raw = request.args.get("recent_n", "10")
    try:
        recent_n = int(recent_raw)
    except Exception:
        recent_n = 10
    t0 = time.time()
    r = prediction.run_state_view(recent_n=recent_n)
    r["wall"] = round(time.time() - t0, 1)
    return render_template("state.html", r=r)

@app.route("/panel", methods=["GET", "POST"])
@login_required
def panel():
    top_ks_str = request.values.getlist("top_ks")
    top_ks = [int(k) for k in top_ks_str] if top_ks_str else [5, 10, 12, 20]
    t0 = time.time()
    r = prediction.run_model_panel(end_issue=None, top_ks=top_ks)
    r["wall"] = round(time.time() - t0, 1)
    r["selected_topks"] = top_ks
    return render_template("panel.html", r=r)

# ============================================================
#            递进注主路由 (核心逻辑修复)
# ============================================================

@app.route("/insurance", methods=["GET", "POST"])
@login_required
def insurance_view():
    plans = insurance.get_plans()
    plan_name_from_req = request.values.get("plan_name")
    selected_plan = plan_name_from_req if plan_name_from_req else (plans[0]["name"] if plans else "")

    df = draws.get_all_draws()
    events = prediction.read_library(df)
    max_issue = int(df["期数"].max()) if not df.empty else 0
    result = None
    
    # 处理 POST 请求
    if request.method == "POST" and "calc" in request.form:
        model_name = request.form["model_name"]
        target_issue = int(request.form["target_issue"])
        miss_str = request.form.get("manual_miss", "").strip()
        loss_str = request.form.get("manual_loss", "").strip()
        override_target_str = request.form.get("override_target", "").strip()
        
        manual_miss = int(miss_str) if miss_str else None
        override_target = float(override_target_str) if override_target_str else None
        
        show_sim = request.form.get("show_sim") == "1"
        show_365 = request.form.get("show_365") == "1"
        
        # ★ 核心修复：计算前先极速对账，算出真实的亏损/盈利
        df_dict = df.set_index("期数")["特码"].to_dict()
        all_records = insurance.get_records(selected_plan, 0)
        real_profit = 0
        for r in all_records:
            cost_val = float(r["cost"]) if str(r["cost"]).strip() else 0.0
            actual = df_dict.get(r["issue"])
            if actual is not None:
                if r.get("bet_numbers") and r["bet_numbers"] != "None":
                    try:
                        bet_nums = [int(x) for x in r["bet_numbers"].split(",") if x.strip()]
                        bet_amts = [float(x) for x in r["bet_amts"].split(",") if x.strip()]
                        if actual in bet_nums:
                            idx = bet_nums.index(actual)
                            amt = bet_amts[idx]
                            if amt > 0:
                                real_profit += (46 * amt - cost_val)
                            else:
                                real_profit += -cost_val
                        else:
                            real_profit += -cost_val
                    except Exception:
                        real_profit += -cost_val
                else:
                    real_profit += -cost_val
            else:
                real_profit += -cost_val

        real_loss = -real_profit if real_profit < 0 else 0
        final_loss = float(loss_str) if loss_str else real_loss
        
        result = insurance.calc_issue(selected_plan, model_name, target_issue, manual_miss, final_loss, override_target)
        
        if result and not result.get("error"):
            # 强行用真实的亏损覆盖掉数据库查出的错误值，防止页面显示错误
            result["auto_loss"] = real_loss         
        if result and not result.get("error"):
            if show_sim:
                plan_amts = next((p["config"]["amts"] for p in plans if p["name"] == selected_plan), [])
                result["sim_table"] = insurance.calc_miss_simulation(plan_amts, result["target_profit"], 20)
            else:
                result["sim_table"] = []
            if show_365:
                result["stats_365"] = insurance.get_365_miss(model_name, result["codes_count"], df, events)
            else:
                result["stats_365"] = None
        
    if request.method == "POST" and "save_record" in request.form:
        target_issue = int(request.form["target_issue"])
        plan_name = request.form["plan_name"]
        
        custom_amts = request.form.getlist("custom_amts")
        actual_cost = sum([float(x) if x else 0 for x in custom_amts])
        
        actual_num = int(request.form["actual_num"]) if request.form.get("actual_num") else None
        bet_numbers_str = request.form.get("bet_numbers", "")
        bet_numbers = [int(x) for x in bet_numbers_str.split(",")] if bet_numbers_str else []
        
        revenue = 0
        profit = -actual_cost
        is_hit = False
        
        # 判中逻辑：必须存在该号码，且下注金额 > 0
        if actual_num and actual_num in bet_numbers:
            hit_idx = bet_numbers.index(actual_num)
            hit_amt = float(custom_amts[hit_idx]) if custom_amts[hit_idx] else 0
            if hit_amt > 0:  # ★ 核心修复：没下注算没中
                revenue = 46 * hit_amt
                profit = revenue - actual_cost
                is_hit = True

        amts_str = ",".join(custom_amts)
        insurance.save_auto_record(target_issue, plan_name, actual_cost, revenue, profit, is_hit, bet_numbers_str, amts_str)
        flash(f"{target_issue} 期战报已保存！", "success")
        return redirect(url_for("insurance_view", plan_name=plan_name))

    if request.method == "POST" and "save_plan" in request.form:
        name = request.form["new_plan_name"]
        strategy = request.form["new_strategy"]
        target_profit = int(request.form.get("new_target", 100))
        amts_str = request.form["amts_list"].replace("，", ",")
        raw_amts = [int(x.strip()) for x in amts_str.split(",") if x.strip()]
        config = {"strategy": strategy, "target_profit": target_profit, "amts": raw_amts}
        insurance.save_plan(name, config)
        flash("方案已保存/更新！", "success")
        return redirect(url_for("insurance_view", plan_name=name))

    if request.method == "POST" and "delete_plan" in request.form:
        try:
            execute("DELETE FROM betting_plans WHERE name = ?", [request.form["delete_name"]])
            flash("方案已删除", "info")
        except Exception as e:
            flash(f"删除失败：{type(e).__name__}", "danger")
        return redirect(url_for("insurance_view"))
        
    if request.method == "POST" and "delete_record" in request.form:
        try:
            rec_id = int(request.form["delete_record"])
            execute("DELETE FROM betting_records WHERE id = ?", [rec_id])
            flash("战报已删除", "info")
        except Exception as e:
            flash(f"删除战报失败：{type(e).__name__}", "danger")
        return redirect(url_for("insurance_view", plan_name=selected_plan))

    # ================= 极速对账与盘面计算 =================
    df_dict = df.set_index("期数")["特码"].to_dict()
    all_records = insurance.get_records(selected_plan, 0)
    
    real_cost = 0
    real_profit = 0
    real_hit_count = 0
    total_bets = len(all_records)
    
    for r in all_records:
        cost_val = float(r["cost"]) if str(r["cost"]).strip() != "" else 0.0
        r["cost"] = cost_val
        
        actual_num = df_dict.get(r["issue"])
        
        if actual_num is not None:
            r["actual_num"] = actual_num
            if r.get("bet_numbers") and r.get("bet_numbers") != "None":
                try:
                    bet_nums = [int(x) for x in r["bet_numbers"].split(",") if x.strip()]
                    bet_amts = [float(x) for x in r["bet_amts"].split(",") if x.strip()]
                    if actual_num in bet_nums:
                        idx = bet_nums.index(actual_num)
                        amt = bet_amts[idx]
                        if amt > 0:  # ★ 核心修复
                            r["hit"] = True
                            r["revenue"] = int(46 * amt)
                            r["profit"] = r["revenue"] - cost_val
                            real_hit_count += 1
                        else:
                            r["hit"] = False
                            r["revenue"] = 0
                            r["profit"] = -cost_val
                    else:
                        r["hit"] = False
                        r["revenue"] = 0
                        r["profit"] = -cost_val
                except Exception:
                    r["hit"] = False
                    r["revenue"] = 0
                    r["profit"] = -cost_val
            else:
                r["hit"] = False
                r["revenue"] = 0
                r["profit"] = -cost_val
        else:
            r["actual_num"] = None
            r["hit"] = False
            r["revenue"] = 0
            r["profit"] = -cost_val
            
        real_cost += cost_val
        real_profit += r["profit"]
        
    pool = {
        "cost": int(real_cost),
        "profit": int(real_profit),
        "loss": -int(real_profit) if real_profit < 0 else 0,
        "roi": round((real_profit / real_cost * 100), 2) if real_cost > 0 else 0,
        "hit_rate": round((real_hit_count / total_bets * 100), 1) if total_bets > 0 else 0
    }
    
    limit_str = request.values.get("limit", "10")
    limit = int(limit_str) if limit_str != "all" else 0
    records = all_records[:limit] if limit > 0 else all_records

    return render_template("insurance.html", plans=plans, selected_plan=selected_plan,
                           result=result, pool=pool, records=records, max_issue=max_issue,
                           limit=limit, models=prediction.ALL_METHODS.keys())


@app.route("/api/global_stats")
@login_required
def api_global_stats():
    plans = insurance.get_plans()
    df = draws.get_all_draws()
    df_dict = df.set_index("期数")["特码"].to_dict()
    
    global_stats = []
    total_cost_sum = 0
    total_profit_sum = 0
    total_hits_sum = 0
    total_bets_sum = 0

    for p in plans:
        p_records = insurance.get_records(p["name"], 0)
        p_cost = 0
        p_profit = 0
        p_hits = 0
        p_bets = 0
        
        for r in p_records:
            cost_val = float(r["cost"]) if str(r["cost"]).strip() != "" else 0.0
            actual = df_dict.get(r["issue"])
            
            if actual is not None:
                if r.get("bet_numbers") and r["bet_numbers"] != "None":
                    try:
                        bet_nums = [int(x) for x in r["bet_numbers"].split(",") if x.strip()]
                        bet_amts = [float(x) for x in r["bet_amts"].split(",") if x.strip()]
                        if actual in bet_nums:
                            idx = bet_nums.index(actual)
                            amt = bet_amts[idx]
                            if amt > 0:  # ★ 核心修复
                                p_hits += 1
                                prof = (46 * amt) - cost_val
                            else:
                                prof = -cost_val
                        else:
                            prof = -cost_val
                    except Exception:
                        prof = -cost_val
                else:
                    prof = -cost_val
            else:
                prof = -cost_val
            
            p_cost += cost_val
            p_profit += prof
            p_bets += 1
            
        p_rate = round((p_hits / p_bets * 100), 1) if p_bets > 0 else 0
        global_stats.append({
            "name": p["name"], "cost": int(p_cost), "profit": int(p_profit),
            "hits": p_hits, "bets": p_bets, "rate": p_rate
        })
        
        total_cost_sum += p_cost
        total_profit_sum += p_profit
        total_hits_sum += p_hits
        total_bets_sum += p_bets

    global_summary = {
        "cost": int(total_cost_sum), "profit": int(total_profit_sum),
        "hits": total_hits_sum, "bets": total_bets_sum,
        "rate": round((total_hits_sum / total_bets_sum * 100), 1) if total_bets_sum > 0 else 0
    }
    
    return jsonify({"stats": global_stats, "summary": global_summary})


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug, threaded=True)