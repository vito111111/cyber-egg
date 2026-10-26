#!/usr/bin/env python3
"""cyber-egg · 一键入口

    python run.py              # 采集 → 归一 → 入库 → 变更检测 → 生成看板
    python run.py --no-build   # 只跑数据管道
    python run.py --offline    # 不联网，用今日缓存重算并重建看板
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# Windows 控制台默认 GBK，重定向到文件时中文会乱码，这里强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import fetch, normalize, store  # noqa: E402


def _load_cache() -> dict:
    """离线模式：从 .cache/raw/<今天>/ 读回原始快照。"""
    day = datetime.now().strftime("%Y-%m-%d")
    raw_dir = os.path.join(fetch.CACHE_DIR, "raw", day)
    cfg = fetch.load_sources()
    out = {}
    for spec in cfg.get("sources") or []:
        key = spec["key"]
        kind = spec.get("kind", "api")
        soft = kind in fetch.SOFT_KINDS
        p = os.path.join(raw_dir, f"{key}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                txt = f.read()
            data = None
            if not soft:
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    data = None
            out[key] = {
                "key": key, "label": spec["label"], "kind": kind,
                "ok": data is not None or soft, "soft": soft, "via": "cache",
                "bytes": len(txt), "sha256": None, "fetched_at": day,
                "data": data, "raw_text": txt, "tried": [],
            }
        else:
            out[key] = {"key": key, "label": spec["label"], "kind": kind,
                        "ok": False, "soft": soft, "data": None,
                        "bytes": 0, "via": None, "sha256": None, "fetched_at": None,
                        "raw_text": None, "tried": []}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="cyber-egg 免费 Token 探测器")
    ap.add_argument("--no-build", action="store_true", help="跳过看板生成")
    ap.add_argument("--offline", action="store_true", help="使用本地缓存，不联网")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--fast", action="store_true", help="跳过 doc/x 人工复核源，只抓结构化 API")
    ap.add_argument("--probe-x", action="store_true", help="真正探测 X 源可达性（会很慢）")
    ap.add_argument("--sync-ranking", action="store_true",
                    help="重拉免费模型榜并刷新排名与缺口清单（每周一跑）")
    args = ap.parse_args()

    t0 = datetime.now()
    print("\n\x1b[1mcyber-egg\x1b[0m  ·  免费 Token 探测器")
    print("─" * 62)

    # 1. 采集
    print("[1/5] 采集上游源")
    raw = _load_cache() if args.offline else fetch.fetch_all(
        quiet=args.quiet, include_soft=not args.fast, probe_x=args.probe_x)
    hok, htotal = fetch.hard_ok(raw)
    soft_n = sum(1 for v in raw.values() if v.get("soft"))
    if hok == 0:
        print("\n\x1b[31m所有结构化数据源均不可用，中止。\x1b[0m")
        return 1
    print(f"      结构化源 {hok}/{htotal} 可用 · 人工复核源 {soft_n} 个（不计算成败）")

    # 2. 归一
    print("[2/5] 归一化与跨源合并")
    records, nstats = normalize.normalize(raw)
    print(f"      intel {nstats['counts'].get('intel', 0)} 条 · "
          f"paco {nstats['counts'].get('paco', 0)} 条 · "
          f"跨源合并 {nstats['counts'].get('cross_matched', 0)} 组 → "
          f"共计 {len(records)} 家厂商")
    for e in nstats["errors"][:5]:
        print(f"      \x1b[33m! {e}\x1b[0m")

    # 2b. 补上只存在于人工事件库的厂商（如 WorkBuddy 国际版、通义听悟）
    from src import registry as _reg
    records, n_added = _reg.augment_from_events(records)
    if n_added:
        print(f"      \x1b[36m+ 人工事件库补充 {n_added} 家（上游源未覆盖）\x1b[0m")

    # 3. 入库 + 变更检测
    print("[3/5] 入库与变更检测")
    conn = store.connect()
    store.init_db(conn)

    today = store._now_date()
    existing = {r["id"]: r for r in store.load_providers(conn)}
    prev = store.previous_snapshot(conn, today)

    # 补 first_seen
    for r in records:
        old = existing.get(r["id"])
        r["first_seen"] = (old or {}).get("first_seen") or today
        r["last_changed"] = (old or {}).get("last_changed")
        r["changed_fields"] = (old or {}).get("changed_fields") or []

    if prev is None:
        print("      首次运行，无历史快照，本次不产生变更记录")
        changes = []
    else:
        changes = store.diff_records(prev, records)
        # 回填 last_changed / changed_fields
        touched: dict[str, list[str]] = {}
        for c in changes:
            if c["change_type"] == "field":
                touched.setdefault(c["provider_id"], []).append(c["field"])
            elif c["change_type"] == "new":
                touched.setdefault(c["provider_id"], []).append("(新增)")
        for pid, flds in touched.items():
            for r in records:
                if r["id"] == pid:
                    r["last_changed"] = today
                    r["changed_fields"] = flds
                    break
        n_field = sum(1 for c in changes if c["change_type"] == "field")
        n_new = sum(1 for c in changes if c["change_type"] == "new")
        n_rm = sum(1 for c in changes if c["change_type"] == "removed")
        print(f"      字段变化 {n_field} · 新增 {n_new} · 移除 {n_rm}")

    store.save_providers(conn, records)
    store.save_snapshot(conn, records, today)
    n_changes = store.save_changes(conn, changes, today)

    n_up = 0
    if raw.get("intel_changes", {}).get("ok"):
        n_up = store.save_upstream_changes(conn, raw["intel_changes"]["data"])
        print(f"      上游政策变化流 {n_up} 条已同步")

    store.log_run(conn, len(records), n_changes, hok, htotal,
                  json.dumps(nstats["counts"], ensure_ascii=False))

    # 4. 分级统计 + 福利情报 + 覆盖审计
    print("[4/5] 分级 · 福利情报 · 覆盖审计")
    from collections import Counter
    from src import feeds, registry

    qc = Counter(r["quality"] for r in records)
    rc = Counter(r["region"] for r in records)
    print(f"      分级  A={qc.get('A',0)}  B={qc.get('B',0)}  C={qc.get('C',0)}  D={qc.get('D',0)}"
          f"  |  国内={rc.get('cn',0)} 海外={rc.get('global',0)}")

    upstream = store.load_upstream_changes(conn, days=120)
    feed = feeds.build_feed(upstream, records)
    fs = feed["summary"]
    print(f"      第一屏  {fs['total']} 条福利（在效 {fs['live']} · "
          f"48h 内到期 {fs['urgent']} · 已过期 {fs['expired']}）")
    print(f"              人工核实 {fs['manual']} 条 + 自动提取 {fs['auto']} 条 · "
          f"重置追踪 {fs['reset_trackers']} 个")

    audit = registry.audit_coverage(records)
    a = audit["stats"]
    print(f"      覆盖  关注清单 {a['total_watched']} 家 · 已收录 {a['present']} 家 "
          f"({a['coverage_pct']}%)")
    if a["missing"]:
        print(f"      \x1b[33m! 待补 {a['missing']} 家："
              + ", ".join(m["name_cn"] for m in audit["missing"][:6]) + "\x1b[0m")

    if args.sync_ranking:
        claw = (raw.get("claw_models") or {}).get("data") or {}
        rk = registry.ranking_from_models(claw, records)
        if rk["available"]:
            print(f"      排名同步  免费模型榜 {rk['total_models']} 个模型 · "
                  f"{len(rk['by_vendor'])} 家厂商 · 补全建议 {len(rk['suggestions'])} 条")

    # 5. 看板
    if not args.no_build:
        print("[5/5] 生成看板（双屏）")
        from src import build
        out = build.build_all(conn, records, raw, nstats, changes,
                              prev_exists=prev is not None)
        print(f"      {out['html']}  ({out['bytes'] / 1024:.0f}KB)")
        print(f"      {out['json']}")
    else:
        print("[5/5] 跳过看板生成")

    conn.close()
    dt = (datetime.now() - t0).total_seconds()
    print("─" * 62)
    print(f"完成 · 耗时 {dt:.1f}s · 结构化源 {hok}/{htotal}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
