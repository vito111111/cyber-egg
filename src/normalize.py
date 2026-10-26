"""cyber-egg · 归一化层

把四个异构数据源揉成一套统一 Provider 记录。这是整个项目真正的脏活所在：
1. 清 Markdown 富文本（上游字段里带 **加粗**、`反引号`、[链接]()）
2. 从中文散文里启发式抽取「是否绑卡 / 是否要实名」这类布尔事实
3. 推断免费类型与可用性分级
4. 用别名表把两个源的同一厂商合并成一条，避免重复计数
"""
from __future__ import annotations

import re
from typing import Any

from .schema import (
    ALIAS_INTEL_TO_PACO,
    INTEL_PART4_GLOBAL,
    INTEL_PART_MAP,
    PACO_CN_SLUGS,
    PACO_SPECIALIZED,
)

# ---------------------------------------------------------------- 文本清洗

_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.S)
_RE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_WS = re.compile(r"[ \t\u3000]+")
_RE_MULTI_NL = re.compile(r"\n{2,}")


def clean_md(text: Any) -> str:
    """去掉 Markdown 修饰，只保留可读纯文本。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    s = _RE_IMG.sub("", text)
    s = _RE_LINK.sub(r"\1", s)          # [文字](url) → 文字
    s = _RE_BOLD.sub(r"\1", s)
    s = _RE_ITALIC.sub(r"\1", s)
    s = _RE_CODE.sub(r"\1", s)
    s = s.replace("\\|", "|").replace("\u00a0", " ")
    s = _RE_WS.sub(" ", s)
    s = _RE_MULTI_NL.sub("\n", s)
    return s.strip()


def clean_list(val: Any) -> list[str]:
    """把可能是 str / list / dict 的字段统一成非空字符串列表。"""
    out: list[str] = []
    if val is None:
        return out
    if isinstance(val, str):
        s = clean_md(val)
        if s:
            out.append(s)
        return out
    if isinstance(val, dict):
        for v in val.values():
            out.extend(clean_list(v))
        return out
    if isinstance(val, (list, tuple)):
        for item in val:
            out.extend(clean_list(item))
    return out


def dedup(seq: list[str]) -> list[str]:
    seen, out = set(), []
    for x in seq:
        k = x.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ---------------------------------------------------------------- 事实抽取

# 绑卡：命中任一强信号即视为需要付款方式（但先排除明确的「无需绑卡」表述）
_RE_NO_CARD = re.compile(r"(无需|免|不用|不需要)(绑定)?(信用卡|银行卡|绑卡|付款方式|payment)", re.I)
_RE_CARD = re.compile(r"(信用卡|银行卡|绑卡|付款方式|payment method|credit card)", re.I)
_RE_PHONE = re.compile(r"(实名|手机号|手机号码|短信验证|身份认证|身份证|手机认证)", re.I)
_RE_CHARGE = re.compile(r"(充值|预付|预存|最低消费|首充)", re.I)


def infer_card_required(*texts: str) -> int | None:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    if _RE_NO_CARD.search(blob):
        return 0
    if _RE_CARD.search(blob):
        return 1
    return None


def infer_phone_required(*texts: str) -> int | None:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    return 1 if _RE_PHONE.search(blob) else None


def infer_free_type(validity: str, tiers: list[str], free_quota: str) -> str:
    """从有效期 / 分级标签 / 额度描述推断免费类型。"""
    v = validity or ""
    tset = {str(t).lower() for t in (tiers or [])}
    blob = f"{v} {free_quota or ''}"

    if re.search(r"(永久|长期有效|长期免费|不限期|永不过期)", v):
        return "perpetual"
    if re.search(r"(每日|每天|按日|次日刷新|滚动重置|每月|按月)", blob):
        return "renewing-quota"
    if "onetime" in tset or re.search(r"(一次性|仅一次|开通赠送|新手礼|注册赠送|注册即送)", blob):
        return "one-time"
    if "trial" in tset or re.search(r"(试用|限时免费|活动期)", blob):
        return "trial-credit"
    if re.search(r"\d+\s*(天|日|个月|年)", v):
        return "one-time"
    return "unknown"


# ---------------------------------------------------------------- 免费额度存在性
# 上游有相当多记录是「曾经免费、现已取消」或「全量按量计费」，
# 必须单独判一次，否则会被 free_type 的宽松匹配错判成可白嫖。
_RE_NO_FREE_HARD = re.compile(
    r"(无免费模型层|无免费 API 模型层|无免费模型|不提供免费模型|"
    r"免费用户无免费额度|免费用户无额度|已取消.{0,16}免费额度|"
    r"不支持 API Key 接入|全量模型按量计费)"
)
_RE_TRIAL_ONLY = re.compile(r"(自托管|共享端点|Playground|网页体验|网页端|体验版)")
_RE_HAS_QUOTA_WORD = re.compile(r"(免费额度|免费 tokens|免费推理|每日|每月|每小时)")


def free_availability(rec: dict) -> str:
    """判定免费额度的实际存在性：real / partial / none / unknown。"""
    fmodels = " ".join(rec.get("free_models") or [])
    quota = rec.get("free_quota") or ""
    blob = f"{fmodels} {quota}"

    if _RE_NO_FREE_HARD.search(blob):
        return "none"
    if not fmodels.strip() and not quota.strip():
        return "unknown"

    # 云厂商常把「自托管永久免费」「网页体验免费」写进免费项，
    # 但那不是可调用的托管 API 额度，只能算部分免费。
    if rec.get("kind") == "cloud_platform":
        if _RE_TRIAL_ONLY.search(fmodels) and not _RE_HAS_QUOTA_WORD.search(blob):
            return "partial"
    return "real"


def grade_quality(rec: dict) -> tuple[str, str]:
    """可用性分级。核心问题是「能不能当长期免费的 API 供应源」。"""
    kind = rec.get("kind")
    cat = rec.get("category") or "unknown"
    ft = rec.get("free_type") or "unknown"
    card = rec.get("card_required")
    phone = rec.get("phone_required")

    if kind == "coding_tool":
        return "D", "只在编辑器内使用，不发可外带 API Key"

    # 先判定「到底有没有免费额度」—— 上游有大量「已取消免费」「按量付费」的记录，
    # 若不拦截会把它们错判成可白嫖。
    avail = free_availability(rec)
    if avail == "none":
        return "D", "官方已明确无免费额度或已取消"
    if avail == "partial":
        return "B", "仅网页体验/自托管免费，托管 API 需付费"

    if cat == "trial" or ft in ("trial-credit", "one-time"):
        reasons = ["一次性/试用额度，会过期"]
        if card == 1:
            reasons.append("需绑卡")
        if _RE_CHARGE.search(rec.get("preconditions") or ""):
            reasons.append("需充值才生效")
        return "C", "；".join(reasons)

    if ft == "perpetual" and card == 0:
        return "A", "永久免费档且明确免绑卡"

    if ft in ("renewing-quota", "perpetual", "recurring-credit"):
        gates = []
        if card == 1:
            gates.append("需绑卡")
        elif card is None:
            gates.append("绑定要求未标注")
        if phone == 1:
            gates.append("需实名/手机号")
        if not rec.get("validity"):
            gates.append("有效期未公示")
        if gates:
            return "B", "周期免费但" + "、".join(gates)
        return "A", "周期刷新免费额度且无硬门槛"

    if card == 1:
        return "C", "免费额度需绑卡，且类型未明确"
    return "D", "官方未明示免费政策"


# ---------------------------------------------------------------- 源适配器


def from_intel(v: dict) -> dict:
    """free-llm-intel · quotas.json 单条 → 统一记录。"""
    vid = v["id"]
    part = int(v.get("part") or 2)
    region, kind = INTEL_PART_MAP.get(part, ("global", "llm_api"))
    if part == 4 and vid in INTEL_PART4_GLOBAL:
        region = "global"

    free_models = dedup(clean_list(v.get("free_models")))
    caveats = dedup(clean_list(v.get("tier_caveats")))
    precond = clean_md(v.get("preconditions"))
    validity = clean_md(v.get("validity"))
    quota = clean_md(v.get("free_quota"))
    promo = clean_md(v.get("promotions"))
    tiers = [str(t) for t in (v.get("tiers") or [])]

    card = infer_card_required(precond, validity, quota, " ".join(caveats))
    phone = infer_phone_required(precond, quota)

    compat = v.get("openai_compat") or None
    base_url = compat.get("base_url") if isinstance(compat, dict) else None
    if base_url:
        base_url = clean_md(base_url)

    links = []
    for pair in v.get("links") or []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            links.append([clean_md(pair[0]), str(pair[1])])

    rec = {
        "id": vid,
        "name": clean_md(v.get("name")),
        "name_en": None,
        "region": region,
        "kind": kind,
        "category": "unknown",
        "free_type": infer_free_type(validity, tiers, quota),
        "free_quota": quota,
        "validity": validity,
        "free_models": free_models,
        "rate_limits": "",
        "preconditions": precond,
        "promotions": promo,
        "caveats": caveats,
        "card_required": card,
        "phone_required": phone,
        "commercial_ok": None,
        "openai_compat": 1 if base_url else None,
        "base_url": base_url,
        "env_key": None,
        "homepage": clean_md(v.get("homepage")),
        "docs_url": links[0][1] if links else None,
        "links": links,
        "reviewed": (v.get("reviewed") or "")[:10] or None,
        "quality": None,
        "quality_reason": None,
        "sources": ["intel_quotas"],
        "rank": v.get("rank"),
    }
    # intel 没有 ongoing/trial 字段，用 free_type 反推
    if rec["free_type"] in ("perpetual", "renewing-quota", "recurring-credit"):
        rec["category"] = "ongoing"
    elif rec["free_type"] in ("one-time", "trial-credit"):
        rec["category"] = "trial"
    return rec


def from_paco(p: dict) -> dict:
    """pacocartones/free-llm-api-hub · providers.json 单条 → 统一记录。"""
    slug = p["slug"]
    region = "cn" if slug in PACO_CN_SLUGS else "global"
    kind = "specialized_api" if slug in PACO_SPECIALIZED else "llm_api"

    fl = p.get("free_limits") or {}
    rate_parts = []
    if fl:
        if fl.get("requests_per_minute"):
            rate_parts.append(f"{fl['requests_per_minute']} RPM")
        if fl.get("requests_per_day"):
            rate_parts.append(f"{fl['requests_per_day']} RPD")
        if fl.get("tokens_per_day"):
            rate_parts.append(f"{fl['tokens_per_day']:,} TPD")
    rate_limits = " · ".join(rate_parts) or clean_md(p.get("rate_limits"))

    notes = clean_md(p.get("notes"))
    caveats = []
    if p.get("data_policy"):
        dp = p["data_policy"]
        if dp.get("trains_on_prompts") is True:
            caveats.append("免费层输入可能被用于训练")
        elif dp.get("trains_on_prompts") is False:
            caveats.append("官方声明不用于训练")
        if dp.get("retention"):
            caveats.append(f"数据保留：{clean_md(dp['retention'])}")
    if notes and re.search(r"(not allowed|prohibit|restricted|may not|不得|禁止)", notes, re.I):
        caveats.append(f"条款限制：{notes[:200]}")

    rec = {
        "id": slug,
        "name": clean_md(p.get("name")),
        "name_en": clean_md(p.get("name")),
        "region": region,
        "kind": kind,
        "category": p.get("category") or "unknown",
        "free_type": p.get("free_type") or "unknown",
        "free_quota": clean_md(p.get("free_tier")),
        "validity": (clean_md(p.get("expires")) or ("永久有效" if p.get("no_expiry") else "")),
        "free_models": dedup(clean_list(p.get("models_free"))),
        "rate_limits": rate_limits,
        "preconditions": clean_md(p.get("notes")),
        "promotions": "",
        "caveats": dedup(caveats),
        "card_required": 1 if p.get("card_required") is True else (0 if p.get("card_required") is False else None),
        "phone_required": 1 if p.get("phone_required") is True else (0 if p.get("phone_required") is False else None),
        "commercial_ok": 1 if p.get("commercial_ok") is True else (0 if p.get("commercial_ok") is False else None),
        "openai_compat": 1 if p.get("openai_compatible") else 0,
        "base_url": p.get("openai_base_url"),
        "env_key": p.get("env_key"),
        "homepage": p.get("docs_url"),
        "docs_url": p.get("docs_url"),
        "links": [[("官方文档" if p.get("docs_url") else "来源"), p.get("docs_url")]] if p.get("docs_url") else [],
        "reviewed": (p.get("last_verified") or "")[:10] or None,
        "quality": None,
        "quality_reason": None,
        "sources": ["paco_providers"],
        "best_for": clean_md(p.get("best_for")),
        "model_tier": p.get("model_tier"),
    }
    return rec


# ---------------------------------------------------------------- 合并策略

# 合并时优先取 intel 的字段（中文可读性更好），paco 补齐结构化布尔值
_PREFER_INTEL = {
    "name", "free_quota", "validity", "free_models", "caveats",
    "preconditions", "promotions", "docs_url", "links", "reviewed", "homepage",
}
_PREFER_PACO = {
    "card_required", "phone_required", "commercial_ok", "openai_compat",
    "base_url", "env_key", "rate_limits", "category", "free_type",
}


def merge(a: dict, b: dict) -> dict:
    """合并同一厂商的两条记录（a=intel, b=paco）。"""
    out = dict(a)
    for k in b:
        if k in ("id", "sources", "quality", "quality_reason"):
            continue
        bv = b.get(k)
        if bv in (None, "", [], {}):
            continue
        av = out.get(k)
        if k in _PREFER_PACO:
            # paco 的结构化布尔/枚举更可靠
            if bv is not None:
                out[k] = bv
        elif av in (None, "", [], {}):
            out[k] = bv
        elif k in ("free_models",):
            out[k] = dedup(list(av) + list(bv if isinstance(bv, list) else [bv]))
        elif k in ("caveats",):
            out[k] = dedup(list(av) + list(bv if isinstance(bv, list) else [bv]))
        elif k == "links":
            out[k] = list(av) + [x for x in (bv or []) if x not in (av or [])]

    # base_url 以 intel 为准：paco 对国内厂商给的是国际站端点
    # （如阿里云 dashscope-intl），对国内用户不可达。
    if a.get("base_url"):
        out["base_url"] = a["base_url"]
    out["sources"] = dedup(list(a.get("sources", [])) + list(b.get("sources", [])))
    return out


def normalize(raw: dict) -> tuple[list[dict], dict]:
    """把 fetch 结果转成统一记录列表，并返回统计信息。"""
    stats: dict[str, Any] = {"errors": [], "counts": {}}
    intel_recs: list[dict] = []
    paco_recs: list[dict] = {}

    if raw.get("intel_quotas", {}).get("ok"):
        vendors = raw["intel_quotas"]["data"].get("vendors") or []
        for v in vendors:
            try:
                intel_recs.append(from_intel(v))
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"intel/{v.get('id')}: {e}")
        stats["counts"]["intel"] = len(intel_recs)
    else:
        stats["errors"].append("intel_quotas 源不可用")

    if raw.get("paco_providers", {}).get("ok"):
        provs = raw["paco_providers"]["data"].get("providers") or []
        for p in provs:
            try:
                rec = from_paco(p)
                paco_recs[rec["id"]] = rec
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"paco/{p.get('slug')}: {e}")
        stats["counts"]["paco"] = len(paco_recs)
    else:
        stats["errors"].append("paco_providers 源不可用")

    # ---- 合并
    merged: dict[str, dict] = {}
    matched_paco: set[str] = set()

    for rec in intel_recs:
        slug = ALIAS_INTEL_TO_PACO.get(rec["id"])
        if slug and slug in paco_recs:
            merged[rec["id"]] = merge(rec, paco_recs[slug])
            matched_paco.add(slug)
        else:
            merged[rec["id"]] = rec

    for slug, rec in paco_recs.items():
        if slug in matched_paco:
            continue
        merged[slug] = rec

    records = list(merged.values())

    # ---- 分级
    for r in records:
        q, reason = grade_quality(r)
        r["quality"] = q
        r["quality_reason"] = reason

    stats["counts"]["merged"] = len(records)
    stats["counts"]["cross_matched"] = len(matched_paco)
    return records, stats
