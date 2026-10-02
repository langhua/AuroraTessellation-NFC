# -*- coding: utf-8 -*-
r"""对账 ✓：文件里**声明**的每条连接 ✓ 与**几何**上真的碰没碰上 ✓ 逐条比 ✓
（Fritzing 载入后按几何判定 ✓ ⇒ **声明了但几何不成立**的那些就是它会算作"没接上"的 ✗）"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# ★ 兄弟仓相对推导 ✓（同 `fz_exact.py` ✓）
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_check as PC                                          # noqa: E402
import pcb_wire as PW                                           # noqa: E402

SK = 25.4 / 90.0
TOL_MM = 0.05                       # 线↔线：Fritzing 的接头是**正好重合**的 ✓（拖动会对齐 ✓）
path = sys.argv[1]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")
pin = {}
for q in PC.collect(path)["pads"]:
    pin[(q.get("mi"), q.get("cid"))] = q
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
    wire[mi.group(1)] = dict(mi=mi.group(1), layer=t["layer"], a=a, b=bb,
                             geo=t["geo"], ends=t.get("ends") or {})
via = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Via"):
        continue
    g = re.search(r'(?s)<pcbView\b[^>]*>(.*?)</pcbView>', b)
    x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
    if x:
        via[mi.group(1)] = (float(x.group(1)), float(x.group(2)))


def seg_pt(p, a, b):
    """点到线段的距离（sketch 单位 ✓）"""
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L <= 0:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** .5
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    q = (a[0] + t * vx, a[1] + t * vy)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** .5


def inside(pt, q):
    if q.get("circle"):
        (cx, cy), r = q["circle"]
        return (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 <= r * r
    p = q.get("poly")
    if not p:
        return None
    sg = None
    for i in range(len(p)):
        x1, y1 = p[i]
        x2, y2 = p[(i + 1) % len(p)]
        cr = (x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)
        if abs(cr) < 1e-12:
            continue
        if sg is None:
            sg = cr > 0
        elif sg != (cr > 0):
            return False
    return True


def lay_base(l):
    return (l or "").replace("trace", "")


bad = []
nlink = 0
for mi, w in wire.items():
    ends = {0: w["a"], 1: w["b"]}
    for e, lst in w["ends"].items():
        p = ends.get(int(e))
        if p is None:
            continue
        for (cid, tmi, lay) in lst:
            nlink += 1
            if tmi in wire:                                     # 线↔线 ✓：端点要落在对方线上 ✓
                d = seg_pt(p, wire[tmi]["a"], wire[tmi]["b"]) * SK
                if d > TOL_MM:
                    bad.append(("线↔线", "Wire%s 端%s" % (mi, e), "Wire%s" % tmi, d, lay))
            elif tmi in via:                                    # 线↔过孔 ✓：端点在孔心 ✓
                q = via[tmi]
                d = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** .5 * SK
                if d > TOL_MM:
                    bad.append(("线↔过孔", "Wire%s 端%s(%.3f,%.3f)" % (mi, e, p[0], p[1]),
                                "Via%s(%.3f,%.3f) Δ=(%.3f,%.3f)" % ((tmi,) + q + (p[0] - q[0], p[1] - q[1])),
                                d, lay))
            else:                                               # 线↔焊盘 ✓：端点在盘真形状里 ✓
                q = pin.get((tmi, cid))
                if q is None:
                    bad.append(("线↔?", "Wire%s 端%s" % (mi, e), "%s.%s" % (tmi, cid), -1, lay))
                elif q["layer"] != "both" and q["layer"] != lay_base(lay):
                    bad.append(("层不对", "Wire%s 端%s(%s)" % (mi, e, lay),
                                "%s.%s(%s)" % (q["title"], cid, q["layer"]), -1, lay))
                elif not inside(p, q):
                    d = ((p[0] - q["c"][0]) ** 2 + (p[1] - q["c"][1]) ** 2) ** .5 * SK
                    bad.append(("线↔焊盘", "Wire%s 端%s" % (mi, e),
                                "%s.%s" % (q["title"], cid), d, lay))
print("== %s：声明连接 %d 条 ✓ ⇒ **几何上不成立** %d 条 ✗" % (os.path.basename(path), nlink, len(bad)))
for k, a, b, d, lay in bad[:40]:
    print("   %-8s %-22s ↔ %-22s 差 %8.3f mm  layer=%s" % (k, a, b, d, lay))
