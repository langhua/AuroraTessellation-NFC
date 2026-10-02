# -*- coding: utf-8 -*-
r"""**解析 vs Fritzing 导出图** 对账 ✓ —— 把我读出来的走线，拿到导出 SVG 里逐条找 ✓

用法 ✓：`fz_overlay.py <sketch.fzz> <导出.svg> [--tol=0.3]`
口径 ✓（都能从文件里复核 ✓）：
  · 走线几何 = 库唯一读法 `pcb_wire.parse_trace` ✓（标签配对 ✓、`(x+x1, y+y1)` ✓）
  · 导出图：**1 单位 = 1 pt** ✓、**1 mm = 72/25.4 = 2.83465 单位** ✓
    （`width="1.1058in"` ÷ viewBox 宽 79.6176 ✓；板框 70.866 pt = 25.00 mm ✓）
  · 板原点 = 导出图里**板那一组**的 `translate(...)` ✓（`partID="<板mi>0"` ✓）；
    板内 mm → 图内 pt ✓：`pt = translate + mm_local × 2.83465` ✓
  · 判据 = 每条走线在导出图里能找到**同一段**（两端点都在容差内 ✓，正反都算 ✓）
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                                  # noqa: E402,F401
import pcb_wire as PW                                             # noqa: E402
import pcb_pads as PP                                            # noqa: E402

SK = 90.0 / 25.4
PT_PER_MM = 72.0 / 25.4

fzz, svg = sys.argv[1], sys.argv[2]
tol = 0.3
for a in sys.argv[3:]:
    if a.startswith("--tol="):
        tol = float(a[6:])

# ── ① 我的解析 ✓ ──────────────────────────────────────────────────────────
z = zipfile.ZipFile(fzz)
fzn = [n for n in z.namelist() if n.endswith(".fz")][0]
text = z.read(fzn).decode("utf-8", "replace")

board_mi, board_loc = None, None
for m in re.finditer(r"<title>([^<]*)</title>", text):
    a = text.rfind("<instance", 0, m.start())
    b = text.find("</instance>", m.end())
    if a < 0 or b < 0:
        continue
    blk = text[a:b]
    mid = re.search(r'moduleIdRef="([^"]+)"', blk)
    # ★ 板实例的 `moduleIdRef` **不是** "PCB…" ✗（实测它是库里的 `PP.BOARD_MID` ✓）——
    #   ✗ 旧写法 `startswith("PCB")` ⇒ 找不到板 ⇒ `board_loc` 为 None ⇒ 后面崩 ✓（刚踩 ✓）
    if mid and (mid.group(1) == PP.BOARD_MID or mid.group(1).startswith("PCB")):
        board_mi = re.search(r'modelIndex="(\d+)"', blk).group(1)
        g = re.search(r'<pcbView\b[^>]*>(.*?)</pcbView>', blk, re.S)
        geo = re.search(r"<geometry ([^>]*)/?>", g.group(1))
        board_loc = (float(re.search(r'\bx="([-\d.eE+]+)"', geo.group(1)).group(1)),
                     float(re.search(r'\by="([-\d.eE+]+)"', geo.group(1)).group(1)))
        break
print("== 对账 ✓：%s ↔ %s ==" % (os.path.basename(fzz), os.path.basename(svg)))
print("   板实例 mi=%s ✓ loc=(%.2f, %.2f) mm（草图 mm ✓）"
      % (board_mi, board_loc[0] / SK, board_loc[1] / SK))

mine = []
for m in re.finditer(r"<title>([^<]*)</title>", text):
    a = text.rfind("<instance", 0, m.start())
    b = text.find("</instance>", m.end())
    if a < 0 or b < 0:
        continue
    blk = text[a:b]
    mid = re.search(r'moduleIdRef="([^"]+)"', blk)
    if not mid or not mid.group(1).startswith("Wire"):
        continue
    t = PW.parse_trace(blk)
    if t is None:
        continue
    p1, p2 = PW.abs_ends(t["geo"])
    lay = (t.get("layer") or "")[:7]
    mine.append((m.group(1), lay, p1, p2))
print("   我读出的 PCB 走线：%d 条 ✓" % len(mine))

# ── ② 导出图 ✓ ────────────────────────────────────────────────────────────
s = open(svg, encoding="utf-8", errors="replace").read()
tr = (0.0, 0.0)
gm = re.search(r'<g partID="%s0">\s*<g transform="translate\(([-\d.eE+]+),\s*([-\d.eE+]+)\)"' % board_mi, s)
if gm:
    tr = (float(gm.group(1)), float(gm.group(2)))
print("   导出图里板组 translate = (%.4f, %.4f) ✓" % tr)

lines = []
for m in re.finditer(r"<line\b([^>]*)/?>", s):
    a = m.group(1)
    get = lambda k: (re.search(r'\b%s="([-\d.eE+]+)"' % k, a) or [None, None])[1]   # noqa: E731
    if get("x1") is None:
        continue
    lines.append((float(get("x1")), float(get("y1")), float(get("x2")), float(get("y2"))))
print("   导出图里的 <line>：%d 条 ✓（含元件图形 ✓）" % len(lines))


def to_pt(p):
    return (tr[0] + (p[0] - board_loc[0]) / SK * PT_PER_MM,
            tr[1] + (p[1] - board_loc[1]) / SK * PT_PER_MM)


ok, bad = [], []
for ttl, lay, p1, p2 in mine:
    q1, q2 = to_pt(p1), to_pt(p2)
    hit = None
    for (x1, y1, x2, y2) in lines:
        same = (math.hypot(x1 - q1[0], y1 - q1[1]) <= tol and
                math.hypot(x2 - q2[0], y2 - q2[1]) <= tol)
        rev = (math.hypot(x2 - q1[0], y2 - q1[1]) <= tol and
               math.hypot(x1 - q2[0], y1 - q2[1]) <= tol)
        if same or rev:
            hit = (x1, y1, x2, y2)
            break
    (ok if hit else bad).append((ttl, lay, q1, q2, hit))
print("   ⇒ **对上 ✓：%d 条**｜对不上 ✗：%d 条（容差 %.2f pt ≈ %.3f mm ✓）"
      % (len(ok), len(bad), tol, tol / PT_PER_MM))
for ttl, lay, q1, q2, _h in bad[:6]:
    print("      ✗ %-14s %s  图里应有 (%.2f,%.2f)→(%.2f,%.2f) pt" % (ttl, lay, q1[0], q1[1], q2[0], q2[1]))
