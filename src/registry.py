"""cyber-egg · 厂商注册与排名同步

解决两件事：
1. **缺口审计**：watchlist 里 S/A 级厂商是否都在 providers 表里。缺失的标红，
   这是「第一屏缺 WorkBuddy / 缺豆包」这类问题的制度化防线。
2. **排名同步**：每周从免费模型榜的 LMArena / 基准分里算厂商排名，
   新进榜但库里没有的厂商自动进缺口清单。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from . import feeds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIER_WEIGHT = {"S": 0, "A": 1, "B": 2, "C": 3}


def load_watchlist() -> dict:
    return feeds.load_json("watchlist.json")


def save_watchlist(data: dict) -> None:
    feeds.save_json("watchlist.json", data)


def audit_coverage(providers: list[dict]) -> dict:
    """比对 watchlist 与 providers，找出缺失与孤儿。

    - missing: watchlist 里有、库里没有（要补）
    - orphan: 库里有、watchlist 没登记（可能是长尾，也可能是新厂商待归档）
    """
    wl = load_watchlist().get("vendors") or []
    by_id = {p["id"]: p for p in providers}
    covered_aliases: set[str] = set()

    rows = []
    for v in wl:
        hit_id = None
        for a in v.get("aliases") or []:
            if a in by_id:
                hit_id = a
                covered_aliases.add(a)
                break
        row = {
            "tier": v["tier"],
            "name": v["name"],
            "name_cn": v.get("name_cn") or v["name"],
            "region": v.get("region"),
            "site": v.get("site"),
            "pricing": v.get("pricing"),
            "why": v.get("why"),
            "aliases": v.get("aliases") or [],
            "present": hit_id is not None,
            "provider_id": hit_id,
        }
        if hit_id:
            p = by_id[hit_id]
            row["quality"] = p.get("quality")
            row["free_type"] = p.get("free_type")
            row["free_quota_short"] = (p.get("free_quota") or "")[:120]
            row["reviewed"] = p.get("reviewed")
            row["card_required"] = p.get("card_required")
            row["phone_required"] = p.get("phone_required")
        rows.append(row)

    rows.sort(key=lambda r: (TIER_WEIGHT.get(r["tier"], 9), not r["present"], r["name"]))

    missing = [r for r in rows if not r["present"]]
    orphans = [p for p in providers if p["id"] not in covered_aliases]

    s_total = sum(1 for r in rows if r["tier"] == "S")
    s_missing = sum(1 for r in missing if r["tier"] == "S")

    return {
        "rows": rows,
        "missing": missing,
        "orphans": sorted(orphans, key=lambda p: p["id"]),
        "stats": {
            "total_watched": len(rows),
            "present": len(rows) - len(missing),
            "missing": len(missing),
            "s_total": s_total,
            "s_missing": s_missing,
            "orphans": len(orphans),
            "coverage_pct": round((len(rows) - len(missing)) / len(rows) * 100, 1) if rows else 0,
        },
    }


def ranking_from_models(claw: dict, providers: list[dict]) -> dict:
    """从免费模型榜提取厂商级排名（按该厂商最好模型的综合分）。

    claw.models[].provider 是模型归属方，zo_score 是本项目上游的综评分。
    这里不自己造分，只做聚合与归一，保留上游原始分。
    """
    models = (claw or {}).get("models") or []
    if not models:
        return {"available": False, "reason": "免费模型榜不可用", "by_vendor": [], "top_models": []}

    agg: dict[str, dict] = {}
    for m in models:
        prov = (m.get("provider") or "").strip()
        if not prov:
            continue
        score = m.get("zo_score") or m.get("score") or 0
        cur = agg.setdefault(prov, {
            "provider": prov, "best_score": 0, "models": 0,
            "best_model": None, "context": 0, "arena": None,
        })
        cur["models"] += 1
        if score > cur["best_score"]:
            cur["best_score"] = score
            cur["best_model"] = m.get("id")
            cur["context"] = m.get("context_window") or 0
        ar = (m.get("arena") or {}).get("overall")
        if ar and (cur["arena"] is None or ar > cur["arena"]):
            cur["arena"] = ar

    by_vendor = sorted(agg.values(), key=lambda x: -x["best_score"])
    for i, v in enumerate(by_vendor, 1):
        v["rank"] = i

    # 交叉：榜上有名但 watchlist 未登记的厂商 → 建议补
    wl = load_watchlist().get("vendors") or []
    known = set()
    for v in wl:
        known.add(v["name"].lower())
        for a in v.get("aliases") or []:
            known.add(a.lower())
        if v.get("name_cn"):
            known.add(v["name_cn"].lower())
    provider_ids = {p["id"] for p in providers}

    suggestions = []
    for v in by_vendor[:25]:
        nm = v["provider"].lower()
        if nm in known or nm in provider_ids:
            continue
        suggestions.append({
            "provider": v["provider"],
            "rank": v["rank"],
            "score": v["best_score"],
            "best_model": v["best_model"],
            "reason": "进入免费模型榜前 25，但库与关注清单里都没有",
        })

    return {
        "available": True,
        "updated_at": (claw or {}).get("updated_at"),
        "total_models": len(models),
        "by_vendor": by_vendor,
        "top_models": sorted(models, key=lambda m: -(m.get("zo_score") or 0))[:12],
        "suggestions": suggestions,
    }


def ranking_staleness(updated_at: str | None) -> dict:
    """排名数据是否该刷新了（上游每周一更新即可）。"""
    if not updated_at:
        return {"stale": True, "days": None, "text": "未知"}
    try:
        d = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return {"stale": True, "days": None, "text": "无法解析"}
    days = (datetime.now() - d).days
    return {
        "stale": days > 8,
        "days": days,
        "text": f"{days} 天前",
    }


def augment_from_events(records: list[dict]) -> tuple[list[dict], int]:
    """把「只存在于人工事件库、上游数据源里没有」的厂商补成 provider 记录。

    这一步解决一个真实缺陷：WorkBuddy 国际版、通义听悟这类厂商没有出现在任何
    上游 JSON 里（上游只覆盖 API 开放平台），但它们确实有免费福利，
    第一屏有卡片、库区却查不到，会显得自相矛盾。

    补出来的记录 source 标为 manual_events，并给一个靠前的 rank，
    否则在「全部厂商」按 rank 排序时会沉到 121 家的末尾，等于看不见。
    """
    cfg = feeds.load_json("events.json")
    events = cfg.get("events") or []
    have = {r["id"] for r in records}

    grouped: dict[str, list[dict]] = {}
    for e in events:
        v = e.get("vendor")
        if not v or v in have:
            continue
        grouped.setdefault(v, []).append(e)

    # 人工补充记录排在自然序之前（rank 用负值，越小越靠前）
    added = []
    for i, (vid, evs) in enumerate(grouped.items(), 1):
        live = [e for e in evs if e.get("ends_at") is None or
                (feeds.parse_dt(e.get("ends_at")) or feeds.now()) > feeds.now()]
        if not live:
            live = evs
        primary = live[0]
        # 额度摘要：把该厂商所有事件拼起来
        quota_bits = []
        for e in live:
            amt = e.get("amount_text")
            ttl = (e.get("title") or "").strip()
            quota_bits.append(f"{ttl}" + (f"（{amt}）" if amt else ""))
        quota = "；".join(quota_bits)[:600]

        valids = [e.get("ends_at") for e in live if e.get("ends_at")]
        if valids:
            validity = "部分活动见截止时间"
        elif any(e.get("cadence") for e in live):
            validity = "长期 / 周期刷新"
        else:
            validity = "以官方页为准"

        # 从事件推断分级
        has_flash = any(e.get("card") == "flash" for e in live)
        all_official = all(e.get("source_grade") == "official" for e in live)
        quality = "B" if not has_flash else "C"
        if all_official and not has_flash:
            quality = "A"

        rec = {
            "id": vid,
            "name": primary.get("vendor_name"),
            "name_en": None,
            "region": primary.get("region") or "cn",
            "kind": "llm_api",
            "category": "ongoing" if not has_flash else "trial",
            "free_type": "perpetual" if not has_flash else "one-time",
            "free_quota": quota,
            "validity": validity,
            "free_models": [],
            "rate_limits": "",
            "preconditions": "",
            "promotions": "",
            "caveats": ["该厂商不在上游结构化数据源覆盖范围内，信息来自人工核实登记"],
            "card_required": None,
            "phone_required": None,
            "commercial_ok": None,
            "openai_compat": None,
            "base_url": None,
            "env_key": None,
            "homepage": primary.get("claim_url"),
            "docs_url": primary.get("source"),
            "links": [[primary.get("source_label") or "官方来源", primary.get("source")]]
                     if primary.get("source") else [],
            "reviewed": max((e.get("verified") or "") for e in live)[:10] or None,
            "quality": quality,
            "quality_reason": "人工核实登记，未接入上游结构化源",
            "sources": ["manual_events"],
            "rank": -1000 + i,   # 负 rank：在「全部厂商」里排到上游记录之前
            "pinned": True,
            "first_seen": None,
            "last_changed": None,
            "changed_fields": [],
        }
        added.append(rec)

    return records + added, len(added)


def ranking_staleness(updated_at: str | None) -> dict:
    """排名数据是否该刷新了（上游每周一更新即可）。"""
    if not updated_at:
        return {"stale": True, "days": None, "text": "未知"}
    try:
        d = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return {"stale": True, "days": None, "text": "无法解析"}
    days = (datetime.now() - d).days
    return {
        "stale": days > 8,
        "days": days,
        "text": f"{days} 天前",
    }
