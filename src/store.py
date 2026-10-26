"""cyber-egg · 存储与变更检测层

设计要点：
- providers 表存「当前状态」，每次刷新覆盖
- snapshots 表存「每日全量快照」，用于回溯与自己做 diff
- changes 表存「本人检测到的字段级变化」，与上游的 changes 流互相印证
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from .schema import DIFF_FIELDS, FIELDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "cyber-egg.db")
SNAP_DIR = os.path.join(DATA_DIR, "snapshots")

_LIST_FIELDS = {"free_models", "caveats", "links", "sources", "changed_fields"}


def _now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cols = []
    for f in FIELDS:
        if f in _LIST_FIELDS:
            cols.append(f'"{f}" TEXT')      # 以 JSON 存储
        elif f in ("card_required", "phone_required", "commercial_ok", "openai_compat"):
            cols.append(f'"{f}" INTEGER')   # 0/1/NULL 三态
        elif f == "model_tier":
            cols.append(f'"{f}" INTEGER')
        else:
            cols.append(f'"{f}" TEXT')

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS providers (
            {", ".join(cols)},
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            date TEXT PRIMARY KEY,
            taken_at TEXT,
            count INTEGER,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            provider_id TEXT,
            provider_name TEXT,
            change_type TEXT,       -- new | removed | field
            field TEXT,
            old_value TEXT,
            new_value TEXT
        );
        CREATE TABLE IF NOT EXISTS upstream_changes (
            date TEXT,
            kind TEXT,
            vendor TEXT,
            brand TEXT,
            title TEXT,
            text TEXT,
            url TEXT,
            PRIMARY KEY (date, vendor, title)
        );
        CREATE TABLE IF NOT EXISTS run_log (
            run_at TEXT PRIMARY KEY,
            providers INTEGER,
            changes INTEGER,
            sources_ok INTEGER,
            sources_total INTEGER,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_changes_date ON changes(date);
        CREATE INDEX IF NOT EXISTS idx_changes_pid ON changes(provider_id);
        """
    )
    conn.commit()


# ---------------------------------------------------------------- 序列化


def _enc(rec: dict) -> dict:
    out = {}
    for f in FIELDS:
        v = rec.get(f)
        if f in _LIST_FIELDS:
            out[f] = json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)
        elif f in ("card_required", "phone_required", "commercial_ok", "openai_compat", "model_tier"):
            out[f] = int(v) if isinstance(v, (int, bool)) else None
        else:
            out[f] = v if v is None or isinstance(v, str) else str(v)
    out["updated_at"] = _now_iso()
    return out


def _dec(row: sqlite3.Row) -> dict:
    out = dict(row)
    for f in _LIST_FIELDS:
        if f in out and out[f]:
            try:
                out[f] = json.loads(out[f])
            except (json.JSONDecodeError, TypeError):
                out[f] = []
        elif f in out:
            out[f] = []
    return out


# ---------------------------------------------------------------- 读写


def save_providers(conn: sqlite3.Connection, records: list[dict]) -> None:
    """全量替换当前状态（保留 first_seen / last_changed 等由 diff 维护的字段）。"""
    existing = {r["id"]: _dec(r) for r in conn.execute("SELECT * FROM providers")}

    for rec in records:
        prev = existing.get(rec["id"])
        if prev:
            rec["first_seen"] = prev.get("first_seen") or _now_date()
        else:
            rec["first_seen"] = _now_date()

    conn.execute("DELETE FROM providers")
    cols = FIELDS + ["updated_at"]
    sql = 'INSERT INTO providers (%s) VALUES (%s)' % (
        ", ".join(f'"{c}"' for c in cols),
        ", ".join("?" * len(cols)),
    )
    for rec in records:
        enc = _enc(rec)
        conn.execute(sql, [enc.get(c) for c in cols])
    conn.commit()


def load_providers(conn: sqlite3.Connection) -> list[dict]:
    return [_dec(r) for r in conn.execute("SELECT * FROM providers")]


def save_snapshot(conn: sqlite3.Connection, records: list[dict], date: str | None = None) -> str:
    date = date or _now_date()
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT OR REPLACE INTO snapshots (date, taken_at, count, payload) VALUES (?,?,?,?)",
        (date, _now_iso(), len(records), payload),
    )
    conn.commit()
    with open(os.path.join(SNAP_DIR, f"{date}.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1, sort_keys=True)
    return date


def previous_snapshot(conn: sqlite3.Connection, before: str) -> list[dict] | None:
    row = conn.execute(
        "SELECT payload FROM snapshots WHERE date < ? ORDER BY date DESC LIMIT 1", (before,)
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- 变更检测


def _norm_for_diff(v) -> str:
    """把字段值规范成可比字符串：列表排序、空值统一。"""
    if v is None:
        return ""
    if isinstance(v, list):
        return " | ".join(sorted(str(x) for x in v))
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v).strip()


def diff_records(prev: list[dict], cur: list[dict]) -> list[dict]:
    """字段级 diff。返回 change 列表。"""
    changes: list[dict] = []
    pmap = {r["id"]: r for r in prev}
    cmap = {r["id"]: r for r in cur}

    for pid, rec in cmap.items():
        old = pmap.get(pid)
        if not old:
            changes.append({
                "provider_id": pid, "provider_name": rec.get("name"),
                "change_type": "new", "field": None, "old_value": None, "new_value": None,
            })
            continue
        for f in DIFF_FIELDS:
            a, b = _norm_for_diff(old.get(f)), _norm_for_diff(rec.get(f))
            if a != b:
                changes.append({
                    "provider_id": pid, "provider_name": rec.get("name"),
                    "change_type": "field", "field": f,
                    "old_value": a[:2000], "new_value": b[:2000],
                })

    for pid, old in pmap.items():
        if pid not in cmap:
            changes.append({
                "provider_id": pid, "provider_name": old.get("name"),
                "change_type": "removed", "field": None, "old_value": None, "new_value": None,
            })
    return changes


def save_changes(conn: sqlite3.Connection, changes: list[dict], date: str | None = None) -> int:
    """写入变更记录。

    同一天可重复运行：diff 的基准始终是「前一份快照」，因此同日结果幂等。
    为避免重复累积，先清掉当天已有的自动检测记录再整体写入。
    """
    date = date or _now_date()
    conn.execute("DELETE FROM changes WHERE date = ?", (date,))
    if not changes:
        conn.commit()
        return 0
    conn.executemany(
        """INSERT INTO changes
           (date, provider_id, provider_name, change_type, field, old_value, new_value)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (date, c["provider_id"], c["provider_name"], c["change_type"], c["field"],
             c["old_value"], c["new_value"])
            for c in changes
        ],
    )
    conn.commit()
    return len(changes)


def save_upstream_changes(conn: sqlite3.Connection, raw_changes: dict) -> int:
    """把 free-llm-intel 的政策变化流落库（作为外部佐证）。"""
    fields = raw_changes.get("fields") or []
    items = raw_changes.get("items") or []
    rows = []
    for it in items:
        d = dict(zip(fields, it)) if isinstance(it, list) else it
        rows.append((
            d.get("date"), d.get("kind"), d.get("vendor"), d.get("brand"),
            d.get("title"), d.get("text"), d.get("url"),
        ))
    if not rows:
        return 0
    conn.executemany(
        """INSERT OR REPLACE INTO upstream_changes
           (date, kind, vendor, brand, title, text, url) VALUES (?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def load_changes(conn: sqlite3.Connection, days: int = 30) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM changes
           WHERE date >= date('now', ?) ORDER BY date DESC, id DESC""",
        (f"-{days} day",),
    ).fetchall()
    return [dict(r) for r in rows]


def load_upstream_changes(conn: sqlite3.Connection, days: int = 60) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM upstream_changes
           WHERE date >= date('now', ?) ORDER BY date DESC""",
        (f"-{days} day",),
    ).fetchall()
    return [dict(r) for r in rows]


def log_run(conn: sqlite3.Connection, providers: int, changes: int,
            ok: int, total: int, notes: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO run_log (run_at, providers, changes, sources_ok, sources_total, notes)"
        " VALUES (?,?,?,?,?,?)",
        (_now_iso(), providers, changes, ok, total, notes),
    )
    conn.commit()


def last_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM run_log ORDER BY run_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None
