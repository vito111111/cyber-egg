"""cyber-egg · 采集层

源清单来自 config/sources.json（可在第二屏「库区」启停与改地址），不再硬编码。
抓不到的源不视为失败——kind=doc / x 的源本就只能人工复核，
本轮会记录可达性但不阻断管道。
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, ".cache")
CONFIG_DIR = os.path.join(ROOT, "config")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 这些 kind 的源拿不到结构化数据是预期内的，不算失败
SOFT_KINDS = {"doc", "x"}


def load_sources() -> dict:
    p = os.path.join(CONFIG_DIR, "sources.json")
    if not os.path.exists(p):
        raise FileNotFoundError(f"缺少信息源配置：{p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _ctx() -> ssl.SSLContext:
    """本机代理链路存在证书替换，故关闭校验（仅用于只读公开数据）。"""
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _get(url: str, timeout: int = 40) -> tuple[bool, str, int]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            raw = r.read()
        return True, raw.decode("utf-8", "replace"), len(raw)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", 0
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", 0


def fetch_one(key: str, spec: dict, retries: int = 2, timeout: int = 40) -> dict:
    """直连 → 镜像 依次尝试。API 源要求 JSON 可解析；doc/x 源只求可达。"""
    urls = [spec["url"]] + list(spec.get("mirrors") or [])
    kind = spec.get("kind", "api")
    soft = kind in SOFT_KINDS
    tried = []

    for attempt in range(retries):
        for u in urls:
            ok, text, nbytes = _get(u, timeout=timeout)
            host = u.split("/")[2] if "//" in u else u
            rec = {"url": u, "ok": ok, "msg": None if ok else text, "bytes": nbytes}
            tried.append(rec)
            if not ok:
                continue

            data = None
            if not soft:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    rec["ok"] = False
                    rec["msg"] = f"JSONDecodeError: {e}"
                    continue

            return {
                "key": key,
                "label": spec["label"],
                "kind": kind,
                "ok": True,
                "soft": soft,
                "via": host,
                "bytes": nbytes,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "data": data,
                "raw_text": text,
                "tried": tried,
            }
        if attempt < retries - 1:
            time.sleep(1.2 * (attempt + 1))

    return {
        "key": key,
        "label": spec["label"],
        "kind": kind,
        "ok": False,
        "soft": soft,
        "via": None,
        "bytes": 0,
        "sha256": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": None,
        "raw_text": None,
        "tried": tried,
    }


def fetch_all(only: list[str] | None = None, quiet: bool = False,
              include_soft: bool = True, probe_x: bool = False) -> dict:
    """抓取启用中的源。

    - kind=api  → 必须拿到可解析 JSON，失败算硬失败
    - kind=doc  → 只求可达，失败不阻断
    - kind=x    → 实测不可达且重试代价高（每源 2 分钟），默认整轮跳过，
                 只有 probe=true 或显式 --probe-x 时才真正发起请求
    """
    cfg = load_sources()
    policy = cfg.get("fetch_policy") or {}
    timeout = int(policy.get("timeout_seconds") or 40)
    retries = int(policy.get("retries") or 2)

    day = datetime.now().strftime("%Y-%m-%d")
    raw_dir = os.path.join(CACHE_DIR, "raw", day)
    os.makedirs(raw_dir, exist_ok=True)

    def _skip(key, spec, msg):
        return {
            "key": key, "label": spec["label"], "kind": spec.get("kind"),
            "ok": False, "soft": spec.get("kind") in SOFT_KINDS,
            "skipped": True, "via": None, "bytes": 0, "sha256": None,
            "fetched_at": None, "data": None, "raw_text": None,
            "tried": [], "msg": msg,
        }

    results = {}
    for spec in cfg.get("sources") or []:
        key = spec["key"]
        if only and key not in only:
            continue
        if not spec.get("enabled", True) and not only:
            results[key] = _skip(key, spec, "已在库区停用")
            continue
        if not include_soft and spec.get("kind") in SOFT_KINDS:
            results[key] = _skip(key, spec, "本轮跳过（人工复核源）")
            continue
        # X：默认不探测，避免每轮白等
        if spec.get("kind") == "x" and not spec.get("probe") and not probe_x and not only:
            results[key] = _skip(key, spec, "已知不可达，本轮未探测（加 --probe-x 可验证）")
            continue

        # X 与 doc 用更短的超时，失败要快
        t = 12 if spec.get("kind") in ("x", "doc") else timeout
        r_ = 1 if spec.get("kind") == "x" else retries

        if not quiet:
            print(f"  · {spec['label']} ...", end="", flush=True)
        r = fetch_one(key, spec, retries=r_, timeout=t)
        results[key] = r

        if r["ok"] and r.get("raw_text"):
            with open(os.path.join(raw_dir, f"{key}.json"), "w", encoding="utf-8") as f:
                f.write(r["raw_text"])
            if not quiet:
                tag = "可达" if r["soft"] else "OK"
                print(f" {tag}  {r['bytes'] / 1024:.1f}KB  via {r['via']}")
        else:
            if not quiet:
                suffix = "（人工复核源，预期可能不可达）" if r["soft"] else ""
                print(f" 不可用{suffix}")
                for t_ in r["tried"][:2]:
                    print(f"      - {t_['url'][:76]} → {t_['msg']}")
    return results


def hard_ok(results: dict) -> tuple[int, int]:
    """统计硬源（api）的成功数，不算 doc/x。"""
    hard = [r for r in results.values() if not r.get("soft")]
    return sum(1 for r in hard if r["ok"]), len(hard)
