#!/usr/bin/env python3
"""CI 摘要：读 site/data.json 打印一行关键指标，写进 Actions 日志与 step summary。

独立成文件而不是在 workflow 里内联 python -c，是因为 PowerShell 的
here-string 终止符必须顶格，放进 YAML 的缩进块里必然失效。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data.json")


def main() -> int:
    if not os.path.exists(DATA):
        print(f"[report] site/data.json 不存在：{DATA}", file=sys.stderr)
        return 1

    with open(DATA, encoding="utf-8") as f:
        d = json.load(f)

    s = d["feed"]["summary"]
    meta = d.get("meta") or {}
    lib = d.get("library") or {}
    stats = (lib.get("audit") or {}).get("stats") or {}

    lines = [
        f"厂商 {len(d.get('providers') or [])} 家 · 福利 {s['total']} 条"
        f"（在效 {s['live']} / 过期 {s['expired']}）",
        f"第一梯队 {s.get('tier1', 0)} 条 · 图像视频 {s.get('multimodal', 0)} 条"
        f" · 7 天内到期 {s.get('expiring_week', 0)} 条",
        f"人工核实 {s.get('manual', 0)} + 自动提取 {s.get('auto', 0)}",
        f"关注清单覆盖率 {stats.get('coverage_pct', '—')}%"
        f"（S 级 {stats.get('s_total', '—')} 家，缺失 {stats.get('s_missing', '—')}）",
        f"结构化源 {lib.get('hard_ok', '—')}/{lib.get('hard_total', '—')}"
        f" 正常 · 生成于 {meta.get('generated_at', '—')}",
    ]

    for ln in lines:
        print(ln)

    # 同时写 GitHub Actions 的任务摘要面板
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("### cyber-egg 刷新结果\n\n")
            for ln in lines:
                f.write(f"- {ln}\n")
            f.write("\n")
            changes = d.get("changes") or []
            if changes:
                f.write(f"**今日变化 {len(changes)} 条**\n\n")
                f.write("| 厂商 | 字段 | 前值 | 后值 |\n|---|---|---|---|\n")
                for c in changes[:15]:
                    old = str(c.get("old_value") or "—").replace("|", "\\|")[:40]
                    new = str(c.get("new_value") or "—").replace("|", "\\|")[:40]
                    f.write(f"| {c.get('provider_name', '—')} | {c.get('field', '—')} "
                            f"| {old} | {new} |\n")
            else:
                f.write("今日无字段级变化。\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
