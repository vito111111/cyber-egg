"""cyber-egg · 看板构建层

双屏结构：
  第一屏 feed    —— 福利展示（限时活动 / 重置追踪 / 周期白嫖 / 新户赠额 / 折扣）
  第二屏 library —— 库区（信息源配置 / 厂商覆盖审计 / 排名同步 / 全部厂商 / 运行日志）

产物：
  site/index.html   数据内联，双击可开
  site/data.json    给其他程序消费
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime

from . import feeds, registry
from .schema import FREE_TYPE_LABEL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, "site")
TPL_PATH = os.path.join(ROOT, "templates", "dashboard.html")

VERSION = "2.0.0"

_DROP_FROM_PAYLOAD = {"raw", "updated_at", "anchor", "in_guide"}


def _clean_records(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        d = {k: v for k, v in r.items() if k not in _DROP_FROM_PAYLOAD}
        for k, v in list(d.items()):
            if v == "":
                d[k] = None
        # pinned 不进数据库（FIELDS 里没有），从 sources 推断：
        # 人工事件库补出来的都是 watchlist 里的 S 级关注厂商，前端要排在最前。
        d["pinned"] = "manual_events" in (r.get("sources") or [])
        out.append(d)
    return out


def _stats(records: list[dict], changes: list[dict]) -> dict:
    qc = Counter(r["quality"] for r in records)
    rc = Counter(r["region"] for r in records)
    kc = Counter(r["kind"] for r in records)
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "total": len(records),
        "by_quality": {k: qc.get(k, 0) for k in ("A", "B", "C", "D")},
        "by_region": {"cn": rc.get("cn", 0), "global": rc.get("global", 0)},
        "by_kind": dict(kc),
        "by_free_type": dict(Counter(r["free_type"] for r in records)),
        "no_card": sum(1 for r in records if r["card_required"] == 0),
        "need_card": sum(1 for r in records if r["card_required"] == 1),
        "verified": sum(1 for r in records if r.get("reviewed")),
        "today_changes": sum(1 for c in changes if c.get("date") == today),
    }


def _source_rows(raw: dict) -> list[dict]:
    """把采集结果与配置合并成库区要展示的信息源表。"""
    cfg = feeds.load_json("sources.json")
    rows = []
    for spec in cfg.get("sources") or []:
        key = spec["key"]
        r = raw.get(key) or {}
        via = r.get("via")
        off = via == "cache"
        rows.append({
            "key": key,
            "label": spec["label"],
            "group": spec.get("group") or "其他",
            "kind": spec.get("kind") or "api",
            "url": spec.get("url"),
            "mirrors": spec.get("mirrors") or [],
            "enabled": bool(spec.get("enabled", True)),
            "feeds_screen": spec.get("feeds_screen"),
            "contributes": spec.get("contributes"),
            "cadence": spec.get("cadence"),
            "note": spec.get("note"),
            "ok": bool(r.get("ok")),
            "skipped": bool(r.get("skipped")),
            "soft": bool(r.get("soft")),
            "offline": off,
            "via": via,
            "bytes": r.get("bytes", 0),
            "fetched_at": (r.get("fetched_at") or "")[:19].replace("T", " "),
            "msg": r.get("msg"),
        })
    return rows


def _payload(records, raw, nstats, changes, upstream, prev_exists) -> dict:
    now = datetime.now()
    sources = _source_rows(raw)

    feed = feeds.build_feed(upstream, records)

    # 排名与审计
    claw = (raw.get("claw_models") or {}).get("data") or {}
    ranking = registry.ranking_from_models(claw, records)
    ranking["staleness"] = registry.ranking_staleness(ranking.get("updated_at"))
    audit = registry.audit_coverage(records)

    hard_ok, hard_total = 0, 0
    for s in sources:
        if s["kind"] not in ("doc", "x"):
            hard_total += 1
            if s["ok"]:
                hard_ok += 1

    library = {
        "sources": sources,
        "source_groups": sorted({s["group"] for s in sources}),
        "audit": audit,
        "ranking": ranking,
        "cfg_events_count": len(feeds.load_json("events.json").get("events") or []),
        "cfg_trackers_count": len(feeds.load_json("events.json").get("reset_trackers") or []),
        "watchlist_meta": {
            k: v for k, v in (feeds.load_json("watchlist.json") or {}).items()
            if k in ("version", "updated", "rotation")
        },
        "hard_ok": hard_ok,
        "hard_total": hard_total,
    }

    return {
        "meta": {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "today": now.strftime("%Y-%m-%d"),
            "weekday": "一二三四五六日"[now.weekday()],
            "version": VERSION,
            "cross_matched": nstats["counts"].get("cross_matched", 0),
            "is_first_run": not prev_exists,
            "errors": nstats.get("errors", [])[:10],
            "free_type_labels": FREE_TYPE_LABEL,
        },
        "stats": _stats(records, changes),
        "feed": feed,
        "library": library,
        "changes": changes,
        "upstream_changes": upstream,
        "providers": _clean_records(records),
    }


def build_all(conn, records, raw, nstats, changes, prev_exists: bool = True) -> dict:
    from . import store

    os.makedirs(SITE_DIR, exist_ok=True)

    upstream = store.load_upstream_changes(conn, days=120)
    db_changes = store.load_changes(conn, days=30)
    payload = _payload(records, raw, nstats, db_changes, upstream, prev_exists)

    json_path = os.path.join(SITE_DIR, "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    with open(TPL_PATH, encoding="utf-8") as f:
        tpl = f.read()

    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_js = data_js.replace("</", "<\\/")

    html = tpl.replace("{{DATA_JSON}}", data_js)
    html_path = os.path.join(SITE_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"html": html_path, "json": json_path, "bytes": len(html)}
