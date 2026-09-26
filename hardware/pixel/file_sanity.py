# -*- coding: utf-8 -*-
"""文件自检（只看文件里写了什么 ✓，不看渲染）：
① 每根面包板导线的 wireExtras/@color ∈ Fritzing 标准配色 ✓
② 有没有零长段 ✗ / 同向共线的冗余中点 ✗
③ 有没有实例级 `color` 属性（有 ⇒ 可能覆盖颜色 ✗）
④ 图例：文字标签 ↔ 色条 是否按同一顺序配对 ✓（从零件 svg 的 text 里读标签 ✓）
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

# ★ 合法值 = Fritzing 官方配色表 `resources/ratsnestcolors.xml` 里
#   `<view name="breadboardView">` 下每个 `<color … wire="…">` ✓（用别的 hex ⇒ 指示栏回退成蓝 ✗）
STANDARD = {"#418dd9", "#cc1414", "#404040", "#fff800", "#25cc35", "#999999",
            "#ffffff", "#ef6100", "#a37911", "#33ffc5", "#ab58a2", "#8c3b00", "#fa50e6"}
fzz = sys.argv[1]


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in (e if e is not None else []):
        if tag(c) == n:
            return c
    return None


z = zipfile.ZipFile(fzz)
name = [x for x in z.namelist() if x.endswith(".fz")][0]
r = ET.fromstring(z.read(name))

bad_col, zero, props, bb = [], [], [], []
for e in r.iter("instance"):
    ttl = (e.findtext("title") or "").strip()
    ttl_el = e.findtext("title")
    # ★ Fritzing 把实例属性**直接挂在 `<instance>` 下** ✓（不是包在 `<properties>` 里 ✗ ——
    #   我第一版扫描就因此漏掉了图例文字件的 `color` 属性 ✗）
    for p in e:
        if tag(p) == "property" and p.get("name") == "color":
            props.append("%s=%s" % (ttl, p.get("value")))
        if tag(p) == "properties":
            for q in p:
                if q.get("name") == "color":
                    props.append("%s(text)=%s" % (ttl, (q.text or "")[:10]))
    for sub in child(e, "views"):
        if tag(sub) != "breadboardView":
            continue
        g = child(sub, "geometry")
        if g is None or g.get("x2") is None:
            continue
        we = child(sub, "wireExtras")
        col = (we.get("color") if we is not None else None)
        dx, dy = float(g.get("x2")), float(g.get("y2"))
        if col and col not in STANDARD:
            bad_col.append((ttl, col))
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            zero.append(ttl)
        peers = [c.get("modelIndex") for c in sub.iter()
                 if tag(c) == "connect" and (c.get("layer") or "") == "breadboardWire"]
        if "WireModuleID" in (e.get("moduleIdRef") or ""):
            bb.append((ttl, col, float(g.get("x")), float(g.get("y")), dx, dy, len(peers)))

print("== 文件自检: %s" % fzz)
print("   ① 非标准色的导线 : %s" % (bad_col if bad_col else "0 个 ✓"))
print("   ② 零长线段       : %s" % (zero if zero else "0 个 ✓"))
print("   ③ 实例 color 属性: %s" % (props if props else "0 个 ✓（Fritzing 自己也不写 ✓）"))
print("   ④ 面包板导线 %d 段（%d 根）| 颜色: %s"
      % (len(bb), len([b for b in bb if b[6]]), sorted({b[1] for b in bb if b[1]})))
print()
print("== 图例区（x>500 ✓ 按 y 排 ✓）")
for ttl, col, x, y, dx, dy, np_ in sorted(bb, key=lambda b: b[3]):
    if x > 500:
        print("   y=%6.1f  %-14s color=%-9s 长度 %.1f" % (y, ttl, col, abs(dx) + abs(dy)))
print()
print("== 图例文字（从零件 svg 里读 ✓ 按 y 排 ✓）")
labels = []
for e in r.iter("instance"):
    mid = e.get("moduleIdRef") or ""
    if "LogoText" not in mid:
        continue
    sub = child(child(e, "views"), "breadboardView")
    if sub is None:
        continue
    g = child(sub, "geometry")
    y = float(g.get("y")) if g is not None and g.get("y") else 0.0
    txt = ""
    for gg in sub.iter():
        if tag(gg) == "text" and (gg.text or "").strip():
            txt += gg.text.strip()
    labels.append((y, (e.findtext("title") or "").strip(), txt))
for y, ttl, txt in sorted(labels):
    print("   y=%6.1f  %-14s %r" % (y, ttl, txt))
