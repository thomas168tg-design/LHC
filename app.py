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
from core import draws, prediction
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
    """实时内存监控接口"""
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
            flash(
                f"更新完成：新增 {r['added']} 期 "
                f"（{r['first_issue']} → {r['last_issue']}），耗时 {elapsed}s",
                "success",
            )
        else:
            flash(
                f"没有新期，本地已是最新（{r['latest_before']}），耗时 {elapsed}s",
                "info",
            )
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
        r = prediction.run_unified_prediction(
            target_issue=target, display_method=display_method,
        )
    except Exception as e:
        flash(f"预测失败：{type(e).__name__}: {e}", "danger")
        return redirect(url_for("predict"))

    r["wall"] = round(time.time() - t0, 1)
    r["consensus_n"] = consensus_n
    r["recent_n"] = recent_n
    return render_template("predict.html", r=r, default_issue=None)


# ============================================================
#            区域盲测
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
    
    # 接收号码组
    top_ks_str = request.form.getlist("top_ks")
    top_ks = [int(k) for k in top_ks_str] if top_ks_str else [5, 10, 12, 20]
    
    # 接收模型选择
    selected_methods = request.form.getlist("methods")
    if not selected_methods:
        selected_methods = [prediction.DEFAULT_METHOD]

    t0 = time.time()
    r = prediction.run_backtest(start_issue, end_issue, top_ks, use_timing, methods=selected_methods)
    r["wall"] = round(time.time() - t0, 1)
    
    return render_template("backtest.html", r=r, min_issue=start_issue, max_issue=end_issue, all_methods=prediction.ALL_METHODS.keys())


# ============================================================
#            连不中统计
# ============================================================

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

# ============================================================
#            冷号监控
# ============================================================

@app.route("/cold")
@login_required
def cold():
    t0 = time.time()
    r = prediction.run_cold_watch()
    r["wall"] = round(time.time() - t0, 1)
    return render_template("cold.html", r=r)


# ============================================================
#            状态查看
# ============================================================

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


# ============================================================
#            模型对比面板
# ============================================================

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
#            保本递进注（占位）
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
    
    if request.method == "POST" and "calc" in request.form:
        model_name = request.form["model_name"]
        target_issue = int(request.form["target_issue"])
        miss_str = request.form.get("manual_miss", "").strip()
        loss_str = request.form.get("manual_loss", "").strip()
        override_target_str = request.form.get("override_target", "").strip()
        
        manual_miss = int(miss_str) if miss_str else None
        manual_loss = float(loss_str) if loss_str else None
        override_target = float(override_target_str) if override_target_str else None
        
        show_sim = request.form.get("show_sim") == "1"
        show_365 = request.form.get("show_365") == "1"
        
        result = insurance.calc_issue(selected_plan, model_name, target_issue, manual_miss, manual_loss, override_target)
        
        if result and not result.get("error"):
            # 沙盘推演
            if show_sim:
                plan_amts = next((p["config"]["amts"] for p in plans if p["name"] == selected_plan), [])
                result["sim_table"] = insurance.calc_miss_simulation(plan_amts, result["target_profit"], 20)
            else:
                result["sim_table"] = []
                
            # 365期历史连黑分布
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
        
        if actual_num and actual_num in bet_numbers:
            hit_idx = bet_numbers.index(actual_num)
            hit_amt = float(custom_amts[hit_idx]) if custom_amts[hit_idx] else 0
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

    row = query_one("SELECT SUM(cost), SUM(profit) FROM betting_records WHERE plan_name = ?", [selected_plan])
    pool_cost = row[0] or 0
    pool_profit = row[1] or 0
    pool = {"cost": pool_cost, "profit": pool_profit, "loss": -pool_profit if pool_profit < 0 else 0}
    pool["roi"] = (pool_profit / pool_cost * 100) if pool_cost > 0 else 0

    limit_str = request.values.get("limit", "10")
    limit = int(limit_str) if limit_str != "all" else 0
    records = insurance.get_records(selected_plan, limit)
    
    for r in records:
        match = df[df["期数"] == r["issue"]]
        if not match.empty:
            r["actual_num"] = int(match.iloc[0]["特码"])
        else:
            r["actual_num"] = None

    return render_template("insurance.html", plans=plans, selected_plan=selected_plan,
                           result=result, pool=pool, records=records, max_issue=max_issue,
                           limit=limit, models=prediction.ALL_METHODS.keys())

# ============================================================
#            本地测试入口
# ============================================================

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print("=" * 60)
    print(f"Flask 启动中... debug={debug}")
    print("浏览器打开：http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=debug, threaded=True)