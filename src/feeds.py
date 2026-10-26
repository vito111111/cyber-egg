"""cyber-egg · 福利情报层

把三类素材合成第一屏（福利展示屏）的卡片流：

1. 人工登记的事件（config/events.json）—— 官方页大多是 SPA，纯抓取拿不到正文，
   这部分必须人工核实后结构化登记；每条强制带 source + verified。
2. 上游自动提取（intel_changes / promotions 里带截止日期或活动字样的）——
   作为「候选」，source_grade=aggregator，界面上与已核实事实区分展示。
3. 重置追踪（Tibo 28 天挑战这类）—— 只记录已发生的事实，不对未来时间做预测。

设计红线：任何卡片都必须有可点开的 source。没有来源的不进第一屏。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from .schema import (
    MODALITIES,
    MULTIMODAL_VENDORS,
    TIER1_CN_VENDORS,
    TIER1_DESC,
    TIER1_LABEL,
    TIER1_VENDORS,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")

# 卡片形态
CARD_KINDS = {
    "flash":   {"label": "限时福利", "hint": "有明确截止时间，过期即失效"},
    "reset":   {"label": "额度重置", "hint": "订阅制用量重置，不是 token 赠送"},
    "daily":   {"label": "周期白嫖", "hint": "每日/每月/每 5 小时刷新"},
    "signup":  {"label": "新户赠额", "hint": "注册或首次开通的一次性额度"},
    "deal":    {"label": "折扣降价", "hint": "价格优惠，不是免费额度"},
}

SOURCE_GRADE = {
    "official":   {"label": "官方", "desc": "厂商官网 / 官方文档 / 官方账号"},
    "aggregator": {"label": "聚合", "desc": "第三方汇总，建议点开原链复核"},
    "manual":     {"label": "人工", "desc": "人工核实登记"},
}

_CN_TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 圈层与模态判定

# 模态关键词：命中即认为该福利是「图像 / 视频 / 语音 / 设计」而非纯文本
_RE_MODALITY = [
    ("video", re.compile(r"(视频|短片|片段|Seedance|Veo|Kling|可灵|即梦|文生视频|图生视频|秒级)")),
    ("image", re.compile(r"(图像|图片|画图|绘图|文生图|图生图|Nano ?Banana|Kolors|CogView|万相|海报|插画|icon|图片生成)")),
    ("design", re.compile(r"(设计稿|设计 Agent|设计Agent|品牌|VI|排版|画板|Banner|Lovart)")),
    ("audio", re.compile(r"(语音|TTS|ASR|转写|配音|音色|Whisper|语音合成|识别)")),
]


def infer_modality(card: dict) -> str:
    """判定一张福利卡的生成模态。

    判定顺序很关键：**先只看标题与标签**，命中才算；标题没有模态词时再看详情。
    否则会出现「硅基流动注册送 14 元代金券」因为详情里提了一句画图模型
    就被判成图像类福利 —— 主福利明明是代金券。
    """
    explicit = card.get("modality")
    if explicit in MODALITIES:
        return explicit

    head = " ".join([card.get("title") or "", " ".join(card.get("tags") or [])])
    for mod, pat in _RE_MODALITY:
        if pat.search(head):
            return mod

    body = " ".join([
        card.get("detail") or "",
        " ".join(card.get("free_models") or []),
    ])
    for mod, pat in _RE_MODALITY:
        if pat.search(body):
            return mod
    return "text"


def vendor_tier(vendor: str | None, region: str | None) -> tuple[bool, str | None]:
    """返回 (是否第一梯队, 子分类)。子分类 cn = 国内头部，global = 御三家。"""
    if not vendor:
        return False, None
    if vendor in TIER1_CN_VENDORS:
        return True, "cn"
    if vendor in TIER1_VENDORS:
        return True, "global"
    return False, None


# 「图像视频」筛选包含的模态。音频不在内 —— 语音转写是另一回事，
# 混进「图像视频」会让这个筛选失去意义。
VISUAL_MODALITIES = {"image", "video", "design"}


def annotate(card: dict) -> dict:
    """给卡片补齐圈层与模态标记，供前端筛选。"""
    v = card.get("vendor")
    t1, sub = vendor_tier(v, card.get("region"))
    card["_tier1"] = t1
    card["_tier1_sub"] = sub
    card["_modality"] = infer_modality(card)
    card["_visual"] = card["_modality"] in VISUAL_MODALITIES
    return card


# ---------------------------------------------------------------- 时间处理

def now() -> datetime:
    return datetime.now(_CN_TZ)


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_CN_TZ)
        return d.astimezone(_CN_TZ)
    except (ValueError, TypeError):
        return None


def humanize_delta(dt: datetime | None) -> dict:
    """把「距现在多久」转成可展示的结构。"""
    if dt is None:
        return {"state": "none", "text": "未设截止", "hours": None}

    h = (dt - now()).total_seconds() / 3600
    if h < 0:
        ah = abs(h)
        if ah < 1:
            txt = "刚刚结束"
        elif ah < 24:
            txt = f"已结束 {int(ah)} 小时"
        else:
            txt = f"已结束 {int(ah / 24)} 天"
        return {"state": "expired", "text": txt, "hours": round(h, 1)}

    if h < 1:
        txt = f"剩 {int(h * 60)} 分钟"
    elif h < 24:
        txt = f"剩 {int(h)} 小时"
    elif h < 24 * 7:
        txt = f"剩 {h / 24:.1f} 天"
    else:
        txt = f"剩 {int(h / 24)} 天"
    state = "urgent" if h < 6 else ("soon" if h < 48 else "open")
    return {"state": state, "text": txt, "hours": round(h, 1)}


def countdown_bucket(hours: float | None) -> str:
    """倒计时分级：决定卡片配色。"""
    if hours is None:
        return "none"
    if hours < 0:
        return "expired"
    if hours < 6:
        return "critical"
    if hours < 48:
        return "warn"
    if hours < 24 * 7:
        return "normal"
    return "calm"


# ---------------------------------------------------------------- 加载

def load_json(name: str) -> dict:
    p = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(name: str, data: dict) -> None:
    p = os.path.join(CONFIG_DIR, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 上游自动提取

# 从 intel_changes 的标题里识别「赠送 / 限时免费 / 活动」类情报
_RE_GIFT = re.compile(r"(限时免费|免费领取|赠送|送出|送 \d|赠额|礼包|活动|开放领取|免费额度)")

# 负面信号：福利结束 / 取消 / 移除 / 转收费。这些必须排除，
# 否则「某活动已结束」会被当成「某福利上线」，第一屏直接误导用户。
_RE_NEGATIVE = re.compile(
    r"(已结束|已截止|已过期|恢复收费|恢复为正常收费|取消|移除|下架|下线|终止|"
    r"不再.{0,8}(免费|赠送|提供)|停止.{0,8}(免费|赠送|开放)|不享受|不支持|"
    r"不适用|无法使用|涨价|上调|转为付费|转为预付费|收费模式|需付费订阅|"
    # 限制说明 / 价格校验 / 付费权益 —— 都不是「新增福利」
    r"不可用于|不可抵扣|不可用|仍然没有|没有免费|无免费|不含免费|无额外|"
    r"矛盾|调价|价格表显示|提升至|门槛调整|需充值|要求充值|需付费|不在.{0,12}免费层|"
    r"付费会员|PRO 会员|有误)"
)

# 弱信号：只是索引/公告引用，没有具体额度，价值低
_RE_WEAK = re.compile(r"(详见|见下方|为准|公告页|另有《|入口，但|以控制台)")

_RE_LIMIT_END = re.compile(r"(截止|至|到)\s*(20\d{2})[-/年]?(\d{1,2})?[-/月]?(\d{1,2})?")
_RE_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(亿|万|千)?\s*(?:个)?\s*(?:tokens?|token|Tokens|词元)")


def parse_amount(text: str) -> tuple[str | None, int | None, str | None]:
    """从散文里抠出「5 亿 tokens」这类额度。"""
    m = _RE_AMOUNT.search(text or "")
    if not m:
        return None, None, None
    num, unit = float(m.group(1)), m.group(2) or ""
    mult = {"亿": 100_000_000, "万": 10_000, "千": 1_000}.get(unit, 1)
    val = int(num * mult)
    label = f"{m.group(1)} {unit}".strip()
    return label, val, "tokens"


def is_benefit_news(title: str) -> tuple[bool, str]:
    """判断一条上游动态到底是不是「新增福利」。

    返回 (是否保留, 原因)。这是第一屏准确性的第一道闸门。
    """
    if not title:
        return False, "空标题"
    if _RE_NEGATIVE.search(title):
        return False, "负面消息（福利结束/取消/转收费）"
    if not _RE_GIFT.search(title):
        return False, "非福利类动态"
    if _RE_WEAK.search(title):
        return False, "仅索引性引用，无具体额度"
    return True, "ok"


def extract_from_upstream(upstream_changes: list[dict], providers: list[dict]) -> list[dict]:
    """把上游的政策变化流 + 厂商 promotions 转成候选福利卡片。

    两条硬规则：
    - 负面消息（活动结束 / 取消免费 / 转收费）一律不进第一屏
    - 只做索引性引用、没有具体额度的也剔除
    """
    out: list[dict] = []
    seen: set[str] = set()

    # 1. 变化流里带赠送/活动字样的
    for c in upstream_changes or []:
        title = c.get("title") or ""
        keep, reason = is_benefit_news(title)
        if not keep:
            continue
        amt_label, amt_val, amt_unit = parse_amount(title)
        end = None
        m = _RE_LIMIT_END.search(title)
        if m:
            y, mo, d = m.group(2), m.group(3), m.group(4)
            if y:
                try:
                    end = f"{y}-{int(mo or 1):02d}-{int(d or 1):02d}T23:59:59+08:00"
                except ValueError:
                    end = None
        key = f"up-{c.get('date')}-{c.get('vendor')}-{title[:30]}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": key,
            "vendor": c.get("vendor"),
            "vendor_name": c.get("brand") or c.get("vendor"),
            "card": "flash" if end else "daily",
            "title": title.replace("额度变化 · ", "").strip(),
            "amount_text": amt_label,
            "amount_value": amt_val,
            "amount_unit": amt_unit,
            "detail": (c.get("text") or "")[:400],
            "how_to": "",
            "claim_url": c.get("url"),
            "source": c.get("url") or "https://free-llm-intel.aishort.top/",
            "source_label": "free-llm-intel 政策变化流",
            "source_grade": "aggregator",
            "starts_at": None,
            "ends_at": end,
            "verified": c.get("date"),
            "region": None,
            "tags": ["自动提取"],
        })

    # 2. providers 里 promotions 字段带活动字样的
    for p in providers or []:
        promo = (p.get("promotions") or "").strip()
        if not promo:
            continue
        # promotions 是长文本，用首段做判定，避免后半段否定表述误伤
        head = promo.split("。")[0]
        keep, _ = is_benefit_news(head)
        if not keep:
            continue
        # 额外排除「无法复核 / 不予采信」这类自我否定
        if re.search(r"(无法|不予采信|无记载|未公示|以控制台实际到账为准)", promo[:50]):
            continue
        amt_label, amt_val, amt_unit = parse_amount(promo)
        pid = f"pr-{p.get('id')}"
        if pid in seen:
            continue
        seen.add(pid)
        out.append({
            "id": pid,
            "vendor": p.get("id"),
            "vendor_name": p.get("name"),
            "card": "signup" if amt_val else "daily",
            "title": head[:80],
            "amount_text": amt_label,
            "amount_value": amt_val,
            "amount_unit": amt_unit,
            "detail": promo[:400],
            "how_to": "",
            "claim_url": p.get("homepage") or p.get("docs_url"),
            "source": p.get("docs_url") or p.get("homepage"),
            "source_label": f"{p.get('name')} 官方活动说明",
            "source_grade": "aggregator",
            "starts_at": None,
            "ends_at": None,
            "verified": p.get("reviewed"),
            "region": p.get("region"),
            "tags": ["自动提取"],
        })
    return out


# ---------------------------------------------------------------- 组装第一屏

def build_feed(upstream_changes: list[dict], providers: list[dict]) -> dict:
    """生成第一屏所需的全部结构。"""
    cfg = load_json("events.json")
    manual = cfg.get("events") or []
    trackers = cfg.get("reset_trackers") or []

    # 人工事件：补齐倒计时状态
    cards = []
    for e in manual:
        card = dict(e)
        end_dt = parse_dt(e.get("ends_at"))
        start_dt = parse_dt(e.get("starts_at"))
        d = humanize_delta(end_dt)
        card["_end_dt"] = end_dt.isoformat() if end_dt else None
        card["_state"] = d["state"]
        card["_delta_text"] = d["text"]
        card["_bucket"] = countdown_bucket(d["hours"])
        card["_hours_left"] = d["hours"]
        # 尚未开始的标出来
        if start_dt and start_dt > now():
            card["_state"] = "upcoming"
            card["_delta_text"] = f"{start_dt.strftime('%m-%d %H:%M')} 开始"
            card["_bucket"] = "upcoming"
        card["_origin"] = "manual"
        cards.append(card)

    auto = extract_from_upstream(upstream_changes, providers)
    for a in auto:
        d = humanize_delta(parse_dt(a.get("ends_at")))
        a["_state"] = d["state"]
        a["_delta_text"] = d["text"]
        a["_bucket"] = countdown_bucket(d["hours"])
        a["_hours_left"] = d["hours"]
        a["_origin"] = "auto"
        cards.append(a)

    # 统一补圈层与模态标记（人工 + 自动一视同仁）
    for c in cards:
        annotate(c)

    # 排序：紧急 → 常态 → 无截止 → 已过期
    order = {"critical": 0, "warn": 1, "normal": 2, "calm": 3,
             "upcoming": 4, "none": 5, "expired": 9}
    cards.sort(key=lambda c: (order.get(c["_bucket"], 6),
                              c["_hours_left"] if c["_hours_left"] is not None else 9e9))

    # 重置追踪器：补状态
    tk = []
    for t in trackers:
        tkx = dict(t)
        camp_end = parse_dt(t.get("ends_at"))
        camp_start = parse_dt(t.get("starts_at"))
        d = humanize_delta(camp_end)
        tkx["_campaign_delta"] = d["text"]
        tkx["_campaign_state"] = d["state"]
        tkx["_days_total"] = ((camp_end - camp_start).days
                              if camp_end and camp_start else None)
        tkx["_days_elapsed"] = ((now() - camp_start).days
                                if camp_start else None)
        tkx["_days_left"] = (max(0, (camp_end - now()).days)
                             if camp_end else None)
        hist = t.get("history") or []
        tkx["_reset_count"] = sum(1 for h in hist if h.get("type") == "reset")
        tkx["_banked_count"] = sum(1 for h in hist if h.get("type") == "banked_reset")
        tkx["_last_reset"] = max((h for h in hist if h.get("type") in ("reset", "banked_reset")),
                                 key=lambda h: h["date"], default=None)
        tk.append(tkx)

    # 顶部概览
    live = [c for c in cards if c["_state"] not in ("expired",)]
    urgent = [c for c in live if c["_bucket"] in ("critical", "warn")]
    expired = [c for c in cards if c["_state"] == "expired"]
    week = [c for c in live if c["_bucket"] in ("normal", "calm")]

    summary = {
        "total": len(cards),
        "live": len(live),
        "urgent": len(urgent),
        "expiring_week": len(week),
        "expired": len(expired),
        "manual": sum(1 for c in cards if c["_origin"] == "manual"),
        "auto": sum(1 for c in cards if c["_origin"] == "auto"),
        "reset_trackers": len(tk),
        # 新增两个筛选维度
        "tier1": sum(1 for c in cards if c.get("_tier1")),
        "tier1_cn": sum(1 for c in cards if c.get("_tier1_sub") == "cn"),
        "multimodal": sum(1 for c in cards if c.get("_visual")),
        "by_modality": {
            m: sum(1 for c in cards if c.get("_modality") == m) for m in MODALITIES
        },
    }

    return {
        "cards": cards,
        "trackers": tk,
        "summary": summary,
        "card_kinds": CARD_KINDS,
        "source_grades": SOURCE_GRADE,
        "modalities": MODALITIES,
        "tier1": {
            "label": TIER1_LABEL,
            "desc": TIER1_DESC,
            "vendors": sorted(TIER1_VENDORS),
            "cn_vendors": sorted(TIER1_CN_VENDORS),
        },
        "multimodal_vendors": sorted(MULTIMODAL_VENDORS),
    }
