#!/usr/bin/env python3
"""生成 logo 方案对比页。

六版共用画布（viewBox 0 0 40 40）与品牌绿渐变底，只在图形语言上区分。
每个 SVG 都由带显式尺寸的 .ico 容器包裹 —— 内联 SVG 无宽高会塌陷。
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(BASE, "logo-lookbook.tpl.html")
OUT = os.path.join(BASE, "logo-lookbook.html")

BG = (
    '<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#17b0a0"/>'
    '<stop offset="1" stop-color="#0a5b72"/>'
    "</linearGradient></defs>"
    '<rect width="40" height="40" rx="11" fill="url(#{gid})"/>'
)

# 下半蛋壳：3 峰、峰在正中、浅青 + 白色断口线
SHELL = (
    '<path d="M10.7 26.6 L14.7 30.4 L20 26.1 L25.3 30.4 L29.3 26.6 '
    'C29.3 34.2 25.1 37.2 20 37.2 C14.9 37.2 10.7 34.2 10.7 26.6 Z" fill="#cfe9e3"/>'
    '<path d="M10.7 26.6 L14.7 30.4 L20 26.1 L25.3 30.4 L29.3 26.6" fill="none" '
    'stroke="#fff" stroke-width="1.15" stroke-linejoin="round" opacity=".9"/>'
)

PLANS: list[dict] = [
    {
        "key": "A",
        "name": "正面探头",
        "body": (
            '<line x1="20" y1="13" x2="20" y2="9.2" stroke="#fff" '
            'stroke-width="1.7" stroke-linecap="round"/>'
            '<circle cx="20" cy="7.6" r="2.2" fill="#ffce4d"/>'
            '<rect x="12.4" y="12.4" width="15.2" height="15.6" rx="5" fill="#fff"/>'
            '<circle cx="16.8" cy="18.6" r="1.85" fill="#0a5b72"/>'
            '<circle cx="23.2" cy="18.6" r="1.85" fill="#0a5b72"/>'
            '<path d="M17.9 22.2h4.2" stroke="#0a5b72" stroke-width="1.25" '
            'stroke-linecap="round" opacity=".5"/>' + SHELL
        ),
        "desc": "方头机器人从蛋壳正中顶出，天线带黄色小球。信息量最完整："
                "天线、双眼、蛋壳三层都齐。",
        "pro": "故事完整，一眼看懂「破壳」",
        "con": "16px 下天线和眼睛容易糊在一起",
    },
    {
        "key": "B",
        "name": "独眼发光",
        "body": (
            '<rect x="12.6" y="11.4" width="14.8" height="15.6" rx="5" fill="#0b2830"/>'
            '<circle cx="20" cy="19.2" r="5" fill="#3fe0c8" opacity=".14"/>'
            '<ellipse cx="20" cy="19.2" rx="2.7" ry="3.7" fill="#4ae6d2"/>'
            '<circle cx="19" cy="17.8" r="1" fill="#fff" opacity=".85"/>'
            '<path d="M13.6 12.6 L20 11.4 L26.4 12.6" stroke="#4ae6d2" '
            'stroke-width="1.1" stroke-linecap="round" opacity=".45"/>' + SHELL
        ),
        "desc": "深色机身配一只发光青眼，蛋壳自下方托住。冷峻、有机械感，"
                "像探测器在暗处睁眼。",
        "pro": "对比度最强，小尺寸下最抢眼",
        "con": "少了机器人的拟人感",
    },
    {
        "key": "C",
        "name": "蛋形芯片",
        "body": (
            # 蛋形轮廓（上下略尖，与纯圆区分）
            '<path d="M20 6.8C13.6 6.8 9.8 14.2 9.8 20.4C9.8 27.8 14.3 32.8 20 32.8'
            'C25.7 32.8 30.2 27.8 30.2 20.4C30.2 14.2 26.4 6.8 20 6.8Z" '
            'fill="none" stroke="#fff" stroke-width="1.75"/>'
            # 六边形芯片体
            '<path d="M17.4 15.4h5.2l2.6 3v3.6l-2.6 3h-5.2l-2.6-3v-3.6Z" '
            'fill="#8af2e0"/>'
            # 左右各三条引脚 + 焊点
            '<path d="M14.8 17.6h-2.4M14.8 20.2h-2.4M14.8 22.8h-2.4'
            'M25.2 17.6h2.4M25.2 20.2h2.4M25.2 22.8h2.4" '
            'stroke="#8af2e0" stroke-width="1.15" stroke-linecap="round"/>'
            '<circle cx="12.1" cy="17.6" r=".95" fill="#ffce4d"/>'
            '<circle cx="12.1" cy="22.8" r=".95" fill="#ffce4d"/>'
            '<circle cx="27.9" cy="17.6" r=".95" fill="#ffce4d"/>'
            '<circle cx="27.9" cy="22.8" r=".95" fill="#ffce4d"/>'
            # 芯片中心的小方孔
            '<rect x="18.9" y="18.9" width="2.2" height="2.2" rx=".5" fill="#0a5b72"/>'
        ),
        "desc": "蛋形轮廓里嵌一枚六边形芯片，左右各三条引脚、末端黄色焊点，"
                "中心留一个小方孔。只保留「蛋 + 赛博」两个符号。",
        "pro": "最克制、最像正经品牌标识，缩放不损失信息",
        "con": "没有活物感，少了「破壳」的动作",
    },
    {
        "key": "D",
        "name": "斜戴壳帽",
        "body": (
            '<rect x="13.1" y="12.8" width="13.8" height="14.6" rx="5" fill="#fff"/>'
            '<circle cx="17.2" cy="19" r="1.8" fill="#0a5b72"/>'
            '<circle cx="22.8" cy="19" r="1.8" fill="#0a5b72"/>'
            '<path d="M17.9 22.4h4.2" stroke="#0a5b72" stroke-width="1.2" '
            'stroke-linecap="round" opacity=".5"/>'
            '<line x1="20" y1="11.8" x2="20" y2="9.4" stroke="#fff" '
            'stroke-width="1.5" stroke-linecap="round"/>'
            '<circle cx="20" cy="8" r="1.65" fill="#ffce4d"/>'
            # 破壳后的下半碗（头从碗里长出）
            '<path d="M11.6 24.2 C11.6 30.6 15.4 33.6 20 33.6 '
            'C24.6 33.6 28.4 30.6 28.4 24.2 L25 27.2 L22.4 24 L20 26.6 '
            'L17.6 24 L15 27.2 Z" fill="#cfe9e3"/>'
            '<path d="M11.6 24.2 L15 27.2 L17.6 24 L20 26.6 L22.4 24 L25 27.2 L28.4 24.2" '
            'fill="none" stroke="#fff" stroke-width="1.1" stroke-linejoin="round" opacity=".9"/>'
            # 斜扣在头上的壳帽（rotate -22°），锯齿下沿
            '<g transform="rotate(-20 20 12.6)">'
            '<path d="M13.4 15.2 C13.4 8.6 26.6 8.6 26.6 15.2 '
            'L24 12.4 L21.4 15.6 L18.6 12.4 L16 15.6 Z" fill="#eaf8f5"/>'
            '<path d="M13.4 15.2 C13.4 8.6 26.6 8.6 26.6 15.2 '
            'L24 12.4 L21.4 15.6 L18.6 12.4 L16 15.6 Z" fill="none" '
            'stroke="#0a5b72" stroke-width=".9" stroke-linejoin="round" opacity=".28"/>'
            '</g>'
        ),
        "desc": "头顶斜扣着一片锯齿状的壳帽，身体下半是破开后的壳碗 —— "
                "刚出壳、帽子还没抖掉的样子。",
        "pro": "「刚孵化」的状态最具体，头脸完整且有表情",
        "con": "元素偏多，16px 时帽子和天线会挤在一起",
    },
    {
        "key": "E",
        "name": "裂口透光",
        "body": (
            '<path d="M20 6.6C13.5 6.6 9.6 13.6 9.6 20.2C9.6 27.9 14.2 33 20 33'
            'C25.8 33 30.4 27.9 30.4 20.2C30.4 13.6 26.5 6.6 20 6.6Z" fill="#f2fbf9"/>'
            # 细锯齿裂缝：一道亮青主线 + 外发光，读作「裂缝」而非「色块」
            '<path d="M10.2 21.4 L13.3 18.2 L16.4 22.2 L19.6 17.2 L22.9 22.2 '
            'L26 18.2 L29.8 21.4" fill="none" stroke="#1fb9a5" stroke-width="3.4" '
            'stroke-linejoin="round" stroke-linecap="round" opacity=".28"/>'
            '<path d="M10.2 21.4 L13.3 18.2 L16.4 22.2 L19.6 17.2 L22.9 22.2 '
            'L26 18.2 L29.8 21.4" fill="none" stroke="#0a5b72" stroke-width="1.9" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
            '<path d="M10.2 21.4 L13.3 18.2 L16.4 22.2 L19.6 17.2 L22.9 22.2 '
            'L26 18.2 L29.8 21.4" fill="none" stroke="#7dffe8" stroke-width=".9" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
            # 裂缝右端溅出一小片碎屑
            '<path d="M28.6 15.8l1.5-1.1.4 1.8Z" fill="#cfe9e3"/>'
        ),
        "desc": "整颗蛋被一道细锯齿裂缝横切，缝里透着青光，右上方溅出一小片壳屑。"
                "不画机器人，只画「即将破壳」的那一瞬间。",
        "pro": "图形最独特，16px 下仍是一道清晰的闪电形符号",
        "con": "不画机器人，得靠品牌名才知道是什么",
    },
    {
        "key": "F",
        "name": "蛋形机头",
        "body": (
            '<line x1="20" y1="8.6" x2="20" y2="5.2" stroke="#fff" '
            'stroke-width="1.5" stroke-linecap="round"/>'
            '<circle cx="20" cy="4" r="1.8" fill="#ffce4d"/>'
            '<path d="M20 8.2C14.2 8.2 10.4 14.8 10.4 20.6C10.4 27.6 14.6 32.4 20 32.4'
            'C25.4 32.4 29.6 27.6 29.6 20.6C29.6 14.8 25.8 8.2 20 8.2Z" fill="#fff"/>'
            '<circle cx="16.6" cy="19.4" r="2" fill="#0a5b72"/>'
            '<circle cx="23.4" cy="19.4" r="2" fill="#0a5b72"/>'
            '<path d="M17.5 23.6 C18.8 24.9 21.2 24.9 22.5 23.6" fill="none" '
            'stroke="#0a5b72" stroke-width="1.4" stroke-linecap="round" opacity=".65"/>'
        ),
        "desc": "最简一版：蛋本身就是头，两只圆眼 + 天线，没有壳也没有身体。"
                "只有一张脸。",
        "pro": "小尺寸最清晰，亲和、可爱",
        "con": "「破壳」完全消失，只剩「蛋 + 机器人」",
    },
]

_counter = 0


def render(body: str) -> str:
    global _counter
    _counter += 1
    return (
        '<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">'
        + BG.format(gid=f"lg{_counter}")
        + body
        + "</svg>"
    )


def ico(body: str, size: int, flat: bool = False) -> str:
    cls = "ico flat" if flat else "ico"
    return f'<span class="{cls}" style="width:{size}px;height:{size}px">{render(body)}</span>'


def main() -> int:
    with open(TPL, encoding="utf-8") as f:
        tpl = f.read()

    row = "".join(
        f'<div class="strip-item"><span class="lb">{p["key"]}</span>'
        f'{ico(p["body"], 31)}</div>'
        for p in PLANS
    )

    cards = []
    for p in PLANS:
        sizes = "".join(
            f'<div class="sz">{ico(p["body"], s, flat=(s <= 24))}'
            f'<span class="n">{s}</span></div>'
            for s in (31, 20, 16)
        )
        cards.append(f'''<article class="card">
  <div class="head"><span class="tag">{p["key"]}</span><span class="name">{p["name"]}</span></div>
  <div class="stage">
    {ico(p["body"], 88)}
    <div class="sizes">{sizes}</div>
  </div>
  <p class="desc">{p["desc"]}</p>
  <div class="verdict">
    <b class="p">优点</b><span>{p["pro"]}</span>
    <b class="c">缺点</b><span>{p["con"]}</span>
  </div>
</article>''')

    html = tpl.replace("__ROW__", row).replace("__CARDS__", "\n".join(cards))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    left = [p for p in ("__ROW__", "__CARDS__") if p in html]
    print(f"✓ 生成 {OUT}")
    print(f"  SVG 副本 {html.count('<svg viewBox')} 个 · 占位符残留 {left or '无'}")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
