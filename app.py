# -*- coding: utf-8 -*-
"""
app.py — Flask 主程序

路由总览：
    /login                登录
    /logout               退出
    /                     首页
    /draws                开奖数据列表
    /draws/update         从 macaujc 更新（POST）
    /draws/add            手动录入（POST）
    /predict              单期预测
    /backtest             区域盲测（待开发）
    /streak               连不中统计（待开发）
    /cold                 冷号监控（待开发）
    /state                状态查看（待开发）
    /panel                模型对比面板（待开发）
    /insurance            保本递进注（待开发）
"""

import os
import time
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash)

from config import LOGIN_PASSWORD, SECRET_KEY
from core import draws, prediction


app = Flask(__name__)
app.secret_key = SECRET_KEY


# ============================================================
#            登录
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
#            预测
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
#            其他（待开发）
# ============================================================

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
        return render_template("backtest.html", r=None, min_issue=min_issue, max_issue=max_issue)

    start_issue = int(request.form.get("start_issue", 2023001))
    end_issue = int(request.form.get("end_issue", 2026289))
    use_timing = request.form.get("use_timing") == "1"
    
    top_ks_str = request.form.getlist("top_ks")
    top_ks = [int(k) for k in top_ks_str] if top_ks_str else [5, 10, 20]

    t0 = time.time()
    r = prediction.run_backtest(start_issue, end_issue, top_ks, use_timing)
    r["wall"] = round(time.time() - t0, 1)
    
    return render_template("backtest.html", r=r, min_issue=start_issue, max_issue=end_issue)

# ============================================================
#            连不中统计
# ============================================================
@app.route("/streak")
@login_required
def streak():
    t0 = time.time()
    r = prediction.run_streak_view()
    r["wall"] = round(time.time() - t0, 1)
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
    t0 = time.time()
    r = prediction.run_state_view()
    r["wall"] = round(time.time() - t0, 1)
    return render_template("state.html", r=r)

# ============================================================
#            模型对比面板
# ============================================================
@app.route("/panel")
@login_required
def panel():
    t0 = time.time()
    r = prediction.run_model_panel()
    r["wall"] = round(time.time() - t0, 1)
    return render_template("panel.html", r=r)

@app.route("/insurance")
@login_required
def insurance():
    return render_template("coming_soon.html", name="保本递进注")


# ============================================================
#            本地测试入口
# ============================================================

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print("=" * 60)
    print(f"Flask 启动中... debug={debug}")
    print("浏览器打开：http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=debug)