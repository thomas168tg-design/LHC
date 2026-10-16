# -*- coding: utf-8 -*-
"""
Turso 数据库连接（HTTP API）
不依赖编译库，跨平台可用
"""

import requests
from config import TURSO_URL, TURSO_TOKEN


def _http_url():
    u = TURSO_URL
    if u.startswith("libsql://"):
        u = u.replace("libsql://", "https://", 1)
    if not u.endswith("/v2/pipeline"):
        u = u.rstrip("/") + "/v2/pipeline"
    return u


def _to_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _from_cell(c):
    if c is None:
        return None
    t = c.get("type")
    v = c.get("value")
    if t == "null":
        return None
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    return v


def _post(statements):
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": s, "args": [_to_arg(a) for a in (args or [])]}}
            for s, args in statements
        ] + [{"type": "close"}]
    }
    r = requests.post(
        _http_url(),
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])


def execute(sql, params=None):
    """执行单条 SQL，不返回数据"""
    results = _post([(sql, params or [])])
    first = results[0]
    if first.get("type") != "ok":
        raise Exception(first.get("error", "unknown"))
    return first["response"]["result"]


def query(sql, params=None):
    """执行查询，返回 (columns, rows)"""
    results = _post([(sql, params or [])])
    first = results[0]
    if first.get("type") != "ok":
        raise Exception(first.get("error", "unknown"))
    resp = first["response"]["result"]
    cols = [c["name"] for c in resp.get("cols", [])]
    rows = [[_from_cell(c) for c in row] for row in resp.get("rows", [])]
    return cols, rows


def query_one(sql, params=None):
    cols, rows = query(sql, params)
    return rows[0] if rows else None


def init_tables():
    """建表（首次运行或表不存在时）"""
    statements = [
        """CREATE TABLE IF NOT EXISTS draws (
            issue INTEGER PRIMARY KEY,
            special INTEGER NOT NULL,
            numbers TEXT,
            updated_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS events (
            issue INTEGER PRIMARY KEY,
            base_issue INTEGER,
            actual_number INTEGER,
            actual_rank INTEGER,
            history_samples INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS ranks (
            issue INTEGER,
            number INTEGER,
            omission INTEGER,
            rank INTEGER,
            is_actual INTEGER,
            PRIMARY KEY (issue, number)
        )""",
        """CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue INTEGER,
            method TEXT,
            top5 TEXT,
            top10 TEXT,
            top20 TEXT,
            full_order TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS insurance_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT,
            n_codes INTEGER,
            base_amt INTEGER,
            target_profit REAL,
            total_cost REAL,
            total_profit REAL,
            max_miss INTEGER,
            max_miss_cost REAL,
            max_miss_loss REAL,
            created_at TEXT
        )""",
    ]
    _post([(s, []) for s in statements])

    # 兼容老库：给 draws 加 numbers 列
    try:
        execute("ALTER TABLE draws ADD COLUMN numbers TEXT")
    except Exception:
        pass   # 列已存在，忽略