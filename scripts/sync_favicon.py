#!/usr/bin/env python3
"""cyber-egg · 从正文 SVG 同步 favicon

问题背景：logo 在 dashboard.html 里出现两次 —— 顶栏内联 SVG 与
<link rel="icon"> 的 data URI。手工改一处会漏另一处，
导致浏览器标签页图标和页面 logo 不是同一个东西。

这个脚本以顶栏 SVG 为唯一真源，重新生成 favicon 的 data URI。
改完 logo 跑一次即可。

用法：
    python scripts/sync_favicon.py            # 同步
    python scripts/sync_favicon.py --check    # 只检查是否一致，不一致退出码 1
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "templates", "dashboard.html")

# 抓顶栏那个 logo SVG（带 aria-label 标识，避免匹配到别处的 svg）
SVG_RE = re.compile(r'(<svg viewBox="0 0 40 40"[\s\S]*?</svg>)')
ICON_RE = re.compile(r'(<link rel="icon" href="data:image/svg\+xml,)([^"]+)(">)')

# data URI 里可以保留不编码的字符（其余一律 percent-encode）
SAFE = "/:=,.()%-"


def load() -> str:
    with open(TPL, encoding="utf-8") as f:
        return f.read()


def extract_svg(html: str) -> str | None:
    m = SVG_RE.search(html)
    return m.group(1) if m else None


def to_data_uri(svg: str) -> str:
    """把 SVG 压成单行再严格 percent-encode。

    空格、#、引号、尖括号全部编码 —— 不编码时 # 会被浏览器当成锚点，
    字符串在首个 # 处被截断，图标直接空白。
    """
    s = " ".join(svg.split())
    return urllib.parse.quote(s, safe=SAFE)


def validate(svg: str) -> list[str]:
    errs = []
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        errs.append(f"SVG 不是合法 XML：{e}")
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        errs.append("SVG 缺少 xmlns 命名空间（作为独立文件渲染时会失败）")
    if 'viewBox="0 0 40 40"' not in svg:
        errs.append("viewBox 不是 0 0 40 40，favicon 尺寸会异常")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="从正文 SVG 同步 favicon")
    ap.add_argument("--check", action="store_true", help="只检查，不写入")
    args = ap.parse_args()

    if not os.path.isfile(TPL):
        print(f"找不到模板：{TPL}", file=sys.stderr)
        return 2

    html = load()
    svg = extract_svg(html)
    if not svg:
        print("模板里找不到 logo SVG（viewBox 0 0 40 40）", file=sys.stderr)
        return 3

    errs = validate(svg)
    if errs:
        print("SVG 校验失败：", file=sys.stderr)
        for e in errs:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    new_uri = to_data_uri(svg)
    m = ICON_RE.search(html)
    if not m:
        print("找不到 <link rel=\"icon\">，无法同步", file=sys.stderr)
        return 4

    old_uri = m.group(2)
    same = (old_uri == new_uri)

    if args.check:
        if same:
            print("✓ favicon 与正文 SVG 一致")
            return 0
        print("✗ favicon 与正文 SVG 不一致，请运行 python scripts/sync_favicon.py",
              file=sys.stderr)
        # 指出差异位置，便于判断是纯格式差异还是图形真的变了
        old_svg = urllib.parse.unquote(old_uri)
        import difflib
        for line in list(difflib.unified_diff(
                old_svg.split("><"), new_uri and urllib.parse.unquote(new_uri).split("><"),
                "favicon", "inline", lineterm="", n=0))[:12]:
            print("   ", line[:150], file=sys.stderr)
        return 1

    if same:
        print("✓ 已一致，无需改动")
        return 0

    html = html[:m.start(2)] + new_uri + html[m.end(2):]
    with open(TPL, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ 已同步 favicon（data URI {len(old_uri)} → {len(new_uri)} 字符）")
    print("  下一步：跑 run.py 重建 site/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
