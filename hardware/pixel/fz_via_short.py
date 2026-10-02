# -*- coding: utf-8 -*-
r"""量指定过孔的**铜环**跟别人压没压在一起 ✓（= 用户 2026-10-02 的怀疑：Via1/Via8 短路 ✓）

★ 这是**制造判据**（我自己的 ✓），**不是** Fritzing 的判据 ✗ —— Fritzing 根本没有短路检查
（全树 0 处 `ShortCircuit` ✓）。所以这个工具的结论要单独说、别混进"Fritzing 会怎么说" ✓。

几何口径 ✓（只有一份实现 ✓）：
  · 过孔铜心 = 文件里的 x,y ＋ `part_box.ring_off_mm(孔径, 环宽)` ✓（实测 Δ = 0.8644 mm ✓）
  · 铜环外半径 R = 孔径/2 ＋ 环宽 ✓（`hole size="0.3mm,0.15mm"` ⇒ R = 0.30 mm ✓）
  · 焊盘形状用 `pcb_pads` 给的**真几何** ✓（`poly` 旋转真矩形 ✓ / `circle` 真圆 ✓）
  · 走线是一条有宽度的线段 ✓（宽 = `mils` ✓）
  · 过孔两层都有铜 ✓ ⇒ 跟**任何一层**压上都算 ✗
  · 先排除"它自己声明连着的"那些 ✓（那些压着是正常的 ✓）
用法 ✓：`fz_via_short.py <sketch.fzz> [Via1 Via8]`
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import part_box as PB                                              # noqa: E402
import pcb_check as PC                                             # noqa: E402
import pcb_wire as PW                                              # noqa: E402

SK = 25.4 / 90.0
M = lambda u: u * SK                                               # noqa: E731
path = sys.argv[1]
want = sys.argv[2:] or ["Via1", "Via8"]

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

# ── 走线 ✓（端点 + 层 + 宽度）───────────────────────────────────────────────
wire = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Wire"):
        continue
    t = PW.parse_trace(b)
    if t is None:
        continue
    a, bb = PW.abs_ends(t["geo"])
    w = t.get("mils") or 24
    wire[mi.group(1)] = dict(mi=mi.group(1), layer=t["layer"], a=a, b=bb,
                             half=w * 0.0254 / 2 / SK * SK,          # 半宽（mm ✓）
                             mils=w, ends=t.get("ends") or {})

# ── 过孔 ✓（铜心 + 外半径 + 自己声明连着的）────────────────────────────────
via = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Via"):
        continue
    g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
    if not x:
        continue
    ti = re.search(r"<title>([^<]*)</title>", b)
    hs = re.search(r'<property name="hole size" value="([\d.]+)mm,([\d.]+)mm"', b)
    hole, ring = (float(hs.group(1)), float(hs.group(2))) if hs else (0.3, 0.15)
    off = PB.ring_off_mm(hole, ring) / SK
    nei = set(re.findall(r'<connect connectorId="[\w]+" modelIndex="(\d+)"', g.group(1)))
    via[mi.group(1)] = dict(mi=mi.group(1), title=ti.group(1) if ti else "",
                            c=(float(x.group(1)) + off, float(x.group(2)) + off),
                            R=(hole / 2 + ring) / SK, nei=nei)

pads = [(q, (q.get("mi"), q.get("cid"))) for q in PC.collect(path)["pads"]]

# ── 谁跟谁"本来就连着" ✓（沿文件里记的连接走 ✓）—— 先把这些排除 ✓
#   ✗ 不排除的话，这颗孔**自己那条链的下一跳**会被报成"压上了" ✗（实测假报 ✓）
adj = {}

def link(a, b):
    adj.setdefault(a, set()).add(b)
    adj.setdefault(b, set()).add(a)

for k, w in wire.items():
    for _e, lst in w["ends"].items():
        for (cid, tmi, _l) in lst:
            if tmi in wire:
                link(("W", k), ("W", tmi))
            elif tmi in via:
                link(("W", k), ("V", tmi))
            else:
                link(("W", k), ("P", (tmi, cid)))
for _i, b in PW.blocks(text):                       # 焊盘那侧也记着 ✓
    mi = re.search(r'modelIndex="(\d+)"', b)
    pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    if not (mi and pv):
        continue
    for cm in re.finditer(r'(?s)<connector connectorId="(\w+)"[^>]*>(.*?)</connector>',
                          pv.group(1)):
        for x in re.finditer(r'<connect connectorId="[\w]+" modelIndex="(\d+)"',
                             cm.group(2)):
            tmi = x.group(1)
            if tmi in wire:
                link(("P", (mi.group(1), cm.group(1))), ("W", tmi))
            elif tmi in via:
                link(("P", (mi.group(1), cm.group(1))), ("V", tmi))


def reach(root):
    """沿记录能走到的全部东西 ✓（= 电气上"同一个网"的那些 ✓）"""
    seen, st = set([root]), [root]
    while st:
        n = st.pop()
        for m in adj.get(n, ()):
            if m not in seen:
                seen.add(m)
                st.append(m)
    return seen


def d_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L <= 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy))


def d_pad(p, q):
    """点到焊盘**真形状**的距离（在形状里 ⇒ 0 ✓）；单位 = sketch 单位 ✓"""
    if q.get("circle"):
        (cx, cy), r = q["circle"]
        return max(0.0, math.hypot(p[0] - cx, p[1] - cy) - r)
    poly = q.get("poly")
    if not poly:
        bx = q["box"]
        cx = min(max(p[0], bx[0]), bx[2])
        cy = min(max(p[1], bx[1]), bx[3])
        inside = bx[0] <= p[0] <= bx[2] and bx[1] <= p[1] <= bx[3]
        return 0.0 if inside else math.hypot(p[0] - cx, p[1] - cy)
    sg = None
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        cr = (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)
        if abs(cr) < 1e-12:
            continue
        if sg is None:
            sg = cr > 0
        elif sg != (cr > 0):
            sg = "out"
            break
    if sg != "out":
        return 0.0
    return min(d_seg(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


for v in via.values():
    if want and v["title"] not in want:
        continue
    mine = reach(("V", v["mi"]))                    # ★ 这颗孔"自己那一片" ✓
    print("\n=== %s（铜心 %.3f,%.3f mm ✓ 环外半径 %.3f mm ✓）==="
          % (v["title"], M(v["c"][0]), M(v["c"][1]), M(v["R"])))
    print("   它自己那一片里有 %d 样东西 ✓（下面一律不算短路 ✓）" % (len(mine) - 1))
    hits = []
    for q, key in pads:                                   # 焊盘 ✓
        if ("P", key) in mine:
            continue
        d = d_pad(v["c"], q) * SK
        if d < M(v["R"]):
            hits.append((d - M(v["R"]), "焊盘 `%s.%s`（%s 层 ✓）"
                         % (q["title"], q["nm"] or q["cid"], q["layer"])))
    for w in wire.values():                               # 走线 ✓
        if ("W", w["mi"]) in mine:
            continue
        d = d_seg(v["c"], w["a"], w["b"]) * SK
        if d < M(v["R"]) + w["half"]:
            hits.append((d - M(v["R"]) - w["half"],
                         "走线 `Wire%s`（层=%s ✓ 宽 %s mil ✓）"
                         % (w["mi"], w["layer"], w["mils"])))
    for v2 in via.values():                               # 其它过孔 ✓
        if v2["mi"] == v["mi"] or ("V", v2["mi"]) in mine:
            continue
        d = (math.hypot(v["c"][0] - v2["c"][0], v["c"][1] - v2["c"][1]) * SK
             - M(v2["R"]))
        if d < M(v["R"]):
            hits.append((d - M(v["R"]), "过孔 `%s`" % v2["title"]))
    if not hits:
        print("   ✓ 没压到任何**别人**的铜（不构成短路 ✓）")
    for gap, what in sorted(hits):
        print("   ✗ 压上了 %s ⇒ **净间隙 %.3f mm**（负 = 重叠 ✗）" % (what, gap))
