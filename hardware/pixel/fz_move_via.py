# -*- coding: utf-8 -*-
r"""★★ 把一颗过孔（连同它两条短线的**对口端**）挪开，直到离**外来铜** ≥ 目标值 ✓
—— 用户 2026-10-02 选的**方案 A** ✓：挪 `Via13`，让它的铜环离 GND 的 `Wire90014147` ≥0.25mm ✓

关键事实 ✓（看原始块得到 ✓）：Fritzing 的走线几何 = **`x,y` ＋ 相对端点 (`x1,y1`)→(`x2,y2`)** ✓
⇒ 挪过孔只要改 **3 处数字** ✓：
  · 过孔自己的 `geometry x,y`（= 新铜心 − `ring_off_mm` ✓）；
  · 短线A（`Wire90014086` ✓ 过孔那侧是 `x,y` ✓）⇒ 改 `x,y` 为过孔新铜心 ✓；
  · 短线B（`Wire90014087` ✓ 过孔那侧也是 `x,y` ✓）⇒ 改 `x,y` ✓ 且 `x2,y2` 要**反向补偿** ✓
    以保住**远端不动** ✓。
★ 远端（`Via12` / `Wire90014088`）**一个像素都不动** ✓。

口径 ✓：与 `fz_net_short.py` 同一套（焊盘真形状 ✓、线宽 ✓、过孔圆心含 `ring_off_mm` ✓）。
用法 ✓：`fz_move_via.py <in.fzz> <out.fzz> <Via标题> <目标净距mm=0.30>`
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
src, dst, want = sys.argv[1], sys.argv[2], sys.argv[3]
TARGET = float(sys.argv[4]) if len(sys.argv) > 4 else 0.30

zin = zipfile.ZipFile(src)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

# ── 收齐铜 ✓（口径同 fz_net_short ✓）────────────────────────────────────────
pads, wires, vias = {}, {}, {}
for q in PC.collect(src)["pads"]:
    pads["%s.%s" % (q.get("mi"), q["cid"])] = q
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi):
        continue
    g = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    if not g:
        continue
    if mo.group(1).startswith("Wire"):
        t = PW.parse_trace(b)
        if t is None:
            continue
        a, bb = PW.abs_ends(t["geo"])
        wires[mi.group(1)] = dict(a=a, b=bb, layer=t["layer"],
                                  half=(t.get("mils") or 24) * 0.0254 / 2 / SK)
    elif mo.group(1).startswith("Via"):
        x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
        hs = re.search(r'<property name="hole size" value="([\d.]+)mm,([\d.]+)mm"', b)
        if not x:
            continue
        hole, ring = (float(hs.group(1)), float(hs.group(2))) if hs else (0.3, 0.15)
        off = PB.ring_off_mm(hole, ring) / SK
        ti = re.search(r"<title>([^<]*)</title>", b)
        vias[mi.group(1)] = dict(mi=mi.group(1), title=ti.group(1) if ti else "?",
                                 raw=(float(x.group(1)), float(x.group(2))), off=off,
                                 c=(float(x.group(1)) + off, float(x.group(2)) + off),
                                 R=(hole / 2 + ring) / SK)

tgt = [v for v in vias.values() if v["title"] == want]
if len(tgt) != 1:
    print("✗ 名字 `%s` 对应 %d 颗过孔 ⇒ 停下 ✓" % (want, len(tgt)))
    sys.exit(1)
V = tgt[0]
# 它的两条短线 ✓（从块的 `<connect>` 里找 ✓）
stubs = []
for _i, b in PW.blocks(text):
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not mi or mi.group(1) not in wires:
        continue
    g = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    if V["mi"] in (g.group(1) or ""):
        stubs.append(mi.group(1))
print("== 挪 `%s`（铜心 %.3f, %.3f mm ✓）前：两条短线 %s ✓"
      % (V["title"], M(V["c"][0]), M(V["c"][1]), stubs))


def d_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L <= 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy))


def min_clear(c, exclude):
    """过孔铜环在中心 c 时，离**外来铜**的最小净距（sketch 单位 ✓）"""
    best = None
    for k, w in wires.items():
        if k in exclude:
            continue
        d = d_seg(c, w["a"], w["b"]) - V["R"] - w["half"]
        best = d if best is None else min(best, d)
    for k, q in pads.items():
        r = q["circle"][1] if q.get("circle") else 0.0
        d = math.hypot(c[0] - q["c"][0], c[1] - q["c"][1]) - V["R"] - r
        best = d if best is None else min(best, d)
    for k, o in vias.items():
        if k == V["mi"]:
            continue
        d = math.hypot(c[0] - o["c"][0], c[1] - o["c"][1]) - V["R"] - o["R"]
        best = d if best is None else min(best, d)
    return best


print("   现在的最小外来净距 ✓：**%.4f mm**" % (min_clear(V["c"], set()) * SK))
best = None
for r_mm in (0.30, 0.40, 0.50, 0.60, 0.80, 1.00):
    for i in range(24):
        ang = 2 * math.pi * i / 24
        c = (V["c"][0] + (r_mm / SK) * math.cos(ang),
             V["c"][1] + (r_mm / SK) * math.sin(ang))
        d = min_clear(c, set()) * SK
        if best is None or d > best[0] + 1e-9:
            best = (d, c, r_mm, math.degrees(ang))
print("   最佳候选 ✓：挪 %.2f mm、方向 %.0f° ⇒ 最小外来净距 **%.4f mm** ✓（目标 %.2f ✓）"
      % (best[2], best[3], best[0], TARGET))
if best[0] < TARGET:
    print("✗ 找不到满足 %.2f mm 的位置 ⇒ 停下来报 ✓（不动文件 ✓）" % TARGET)
    sys.exit(1)

newc = best[1]
# ── 改 3 处数字 ✓（过孔 x,y ✓；两条短线各自"过孔那侧"的端点 ✓，远端不动 ✓）────────
out = text


def fix_via(blk, newc):
    def sub(m):
        return '<geometry z="%s" x="%s" y="%s"' % (
            m.group(1), PW.fmt((newc[0] - V["off"])), PW.fmt((newc[1] - V["off"])))
    return re.sub(r'<geometry z="([\d.]+)" x="[-\d.]+" y="[-\d.]+"', sub, blk, count=1)


def fix_stub(blk, newc):
    """把 `pcbView` 里那条 geometry 的**过孔一侧**端点搬到 newc ✓（远端不动 ✓）"""
    def sub(m):
        z, x, y, x1, y1, x2, y2 = m.groups()
        X, Y = float(x), float(y)
        a = (X + float(x1), Y + float(y1))
        b = (X + float(x2), Y + float(y2))
        # 哪一端离过孔旧位置近 ⇒ 那一端是"过孔那侧" ✓
        da = math.hypot(a[0] - V["c"][0], a[1] - V["c"][1])
        db = math.hypot(b[0] - V["c"][0], b[1] - V["c"][1])
        far = b if da < db else a
        near_new = newc
        # 以 far 为新原点重写 ✓（只改数字，语义不变 ✓）
        return ('<geometry z="%s" x="%s" y="%s" x1="%s" y1="%s" x2="%s" y2="%s"'
                % (z, PW.fmt(far[0]), PW.fmt(far[1]),
                   PW.fmt(near_new[0] - far[0]), PW.fmt(near_new[1] - far[1]),
                   "0", "0"))
    return re.sub(r'<geometry z="([\d.]+)" x="([-\d.]+)" y="([-\d.]+)" x1="([-\d.]+)" '
                  r'y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', sub, blk, count=1)


# 过孔块 ✓
pat = re.compile(r'(?s)<instance\b[^>]*\bmodelIndex="%s"[^>]*>.*?</instance>' % V["mi"])
blk = pat.search(out).group(0)
out = out.replace(blk, fix_via(blk, newc), 1)
# 两条短线 ✓
for k in stubs:
    p2 = re.compile(r'(?s)<instance\b[^>]*\bmodelIndex="%s"[^>]*>.*?</instance>' % k)
    b2 = p2.search(out).group(0)
    out = out.replace(b2, fix_stub(b2, newc), 1)
print("   ✓ 已改：过孔 `x,y` ✓ ＋ %d 条短线的过孔侧端点 ✓（远端未动 ✓）" % len(stubs))

zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
for n in zin.namelist():
    zout.writestr(n, out.encode("utf-8") if n == fz else zin.read(n))
zout.close()
print("✓ 写出 `%s` ✓" % os.path.basename(dst))
