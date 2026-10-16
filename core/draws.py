# -*- coding: utf-8 -*-
"""
core/draws.py

开奖数据读写 + 从 macaujc 抓取更新

数据流：
- Turso 的 draws 表是唯一权威数据源（issue, special, updated_at）
- data/draws.csv 只用于首次初始化导入
- TM_KAIJIAN 的抓取逻辑改为 update_from_web()：从最新期+1开始抓，
  抓到未开奖为止；每抓到一期立刻写 Turso
"""

import os
import json
import time
import urllib.request
from datetime import datetime

import pandas as pd

from config import CSV_PATH
from database import _post, execute, query, query_one, init_tables


# ============================================================
#            本地 CSV 读取（只用于首次导入）
# ============================================================

def csv_exists() -> bool:
    return os.path.isfile(CSV_PATH)


def _read_csv_rows():
    """
    读取 data/draws.csv，兼容 8 列或 2 列格式
    返回 [(issue:int, special:int), ...]，按期数升序，去重保留最后一个
    """
    if not csv_exists():
        return []

    last_err = None
    df = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            df = pd.read_csv(CSV_PATH, encoding=enc, low_memory=False)
            break
        except Exception as e:
            last_err = e
    if df is None:
        raise RuntimeError(f"CSV 读取失败：{last_err}")

    # 兼容列名（你的实际 CSV 用「开奖期数」「特码」）
    cols = {str(c).strip(): c for c in df.columns}
    issue_col = None
    special_col = None
    for name in ("开奖期数", "期数", "期號", "开奖期號"):
        if name in cols:
            issue_col = cols[name]
            break
    for name in ("特码", "特碼", "特别号", "特別號"):
        if name in cols:
            special_col = cols[name]
            break
    if issue_col is None or special_col is None:
        raise RuntimeError(f"CSV 列名不符合预期，实际列：{list(df.columns)}")

    seen = {}
    for _, r in df.iterrows():
        try:
            iss = int(float(str(r[issue_col]).strip()))
            sp = int(float(str(r[special_col]).strip()))
        except Exception:
            continue
        if 1 <= sp <= 49:
            seen[iss] = sp
    return sorted(seen.items())


# ============================================================
#            Turso 读写
# ============================================================

def get_all_draws() -> pd.DataFrame:
    _, rows = query("SELECT issue, special, numbers FROM draws ORDER BY issue ASC")
    if not rows:
        return pd.DataFrame(columns=["期数", "特码", "号码"])
    return pd.DataFrame(rows, columns=["期数", "特码", "号码"])


def get_latest_issue():
    """返回最新期数，空库返回 None"""
    row = query_one("SELECT MAX(issue) FROM draws")
    if row is None or row[0] is None:
        return None
    return int(row[0])


def get_last_n(n: int) -> pd.DataFrame:
    _, rows = query(
        "SELECT issue, special, numbers FROM draws ORDER BY issue DESC LIMIT ?",
        [int(n)],
    )
    if not rows:
        return pd.DataFrame(columns=["期数", "特码", "号码"])
    df = pd.DataFrame(rows, columns=["期数", "特码", "号码"])
    return df.sort_values("期数").reset_index(drop=True)


def upsert_draw(issue: int, special: int, numbers: str = None) -> None:
    """单期插入/更新（覆盖）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "INSERT INTO draws (issue, special, numbers, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(issue) DO UPDATE SET special=excluded.special, "
        "numbers=excluded.numbers, updated_at=excluded.updated_at",
        [int(issue), int(special), numbers, now],
    )


def upsert_draws(rows) -> int:
    """批量写入（首次导入用）。rows=[(issue, special), ...]"""
    if not rows:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    statements = [
        (
            "INSERT OR IGNORE INTO draws (issue, special, numbers, updated_at) VALUES (?, ?, ?, ?)",
            [int(iss), int(sp), None, now],
        )
        for iss, sp in rows
    ]
    _post(statements)
    return len(statements)


def init_from_csv() -> int:
    """首次导入：把 data/draws.csv 写入 Turso，已存在的期数跳过。返回尝试写入的条数"""
    init_tables()
    rows = _read_csv_rows()
    if not rows:
        return 0
    upsert_draws(rows)
    return len(rows)


def stats() -> dict:
    """返回 {'total': 总期数, 'min_issue': ..., 'max_issue': ...}"""
    row = query_one("SELECT COUNT(*), MIN(issue), MAX(issue) FROM draws")
    if row is None:
        return {"total": 0, "min_issue": None, "max_issue": None}
    total, mn, mx = row
    return {
        "total": int(total or 0),
        "min_issue": int(mn) if mn is not None else None,
        "max_issue": int(mx) if mx is not None else None,
    }


# ============================================================
#            macaujc 抓取（从 TM_KAIJIAN.py 移植，去掉了本地文件逻辑）
# ============================================================

def fetch_from_macaujc(target_issue: str):
    """
    查询 macaujc 指定期
    未开奖/网络错误/数据异常 → 返回 None
    成功 → 返回 {'issue', 'date', 'numbers'(7个), 'special'}
    """
    api_url = f"https://history.macaumarksix.com/history/macaujc2/expect/{target_issue}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, dict) or data.get("code") not in (0, 200):
        return None

    result = data.get("data")
    if not result:
        return None

    if isinstance(result, list):
        if not result:
            return None
        item = result[0]
    elif isinstance(result, dict):
        item = result
    else:
        return None

    web_issue = str(item.get("expect", ""))
    if web_issue != str(target_issue):
        return None

    open_code = str(item.get("openCode", "")).strip()
    open_code = open_code.replace("，", ",").replace(" ", "")
    raw_numbers = [x.strip() for x in open_code.split(",") if x.strip()]
    if len(raw_numbers) != 7:
        return None

    try:
        numbers = [int(x) for x in raw_numbers]
    except Exception:
        return None

    if not all(1 <= n <= 49 for n in numbers):
        return None

    numbers_str = ",".join(str(n) for n in numbers)

    return {
        "issue": web_issue,
        "date": item.get("openTime", ""),
        "numbers": numbers,
        "numbers_str": numbers_str,
        "special": numbers[6],
    }

def update_from_web(max_new: int = 20) -> dict:
    """
    从本地最新期+1开始，连续抓取直到未开奖或达到 max_new
    每抓到一期立刻写 Turso

    返回 {'added', 'first_issue', 'last_issue', 'elapsed', 'latest_before'}
    """
    init_tables()

    latest = get_latest_issue()
    if latest is None:
        # 空库：先尝试用 CSV 初始化
        init_from_csv()
        latest = get_latest_issue()
        if latest is None:
            return {
                "added": 0,
                "first_issue": None,
                "last_issue": None,
                "elapsed": 0.0,
                "latest_before": None,
                "note": "空库且 data/draws.csv 无有效数据，请检查",
            }

    start = time.time()
    next_issue = int(latest) + 1
    added = 0
    first_issue = None
    last_issue = None

    while added < max_new:
        data = fetch_from_macaujc(str(next_issue))
        if data is None:
            break
        upsert_draw(int(data["issue"]), int(data["special"]), data.get("numbers_str"))
        if first_issue is None:
            first_issue = data["issue"]
        last_issue = data["issue"]
        added += 1
        next_issue += 1

    elapsed = round(time.time() - start, 2)
    return {
        "added": added,
        "first_issue": first_issue,
        "last_issue": last_issue,
        "elapsed": elapsed,
        "latest_before": int(latest),
    }


# ============================================================
#            本地自测入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("core/draws.py 自测")
    print("=" * 60)

    print("\n[1] 建表")
    init_tables()
    print("  OK")

    print("\n[2] 当前 Turso 状态")
    s0 = stats()
    print(f"  {s0}")

    print("\n[3] 从 data/draws.csv 导入")
    n = init_from_csv()
    print(f"  CSV 存在：{csv_exists()}")
    print(f"  尝试写入 {n} 条")

    print("\n[4] 导入后状态")
    s1 = stats()
    print(f"  {s1}")

    print("\n[5] 最近 5 期")
    df = get_last_n(5)
    print(df.to_string(index=False))

    print("\n[6] 尝试从 macaujc 抓下一期（只抓 3 期就停）")
    r = update_from_web(max_new=3)
    print(f"  {r}")

    print("\n[7] 更新后状态")
    s2 = stats()
    print(f"  {s2}")

    print("\n完成。")