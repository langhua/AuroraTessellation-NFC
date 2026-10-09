# -*- coding: utf-8 -*-
r"""探针 ✓：指定的几只脚，量「最近走线端点到它多远 ✓、在不在盘的真形状里 ✓」
（用来判 `v59` 的 `C2` 到底算不算接上 ✓ —— 0.354 mm 很贴边 ✓）"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# ★ 兄弟仓相对推导 ✓（同本目录其它 `fz_*.py` ✓）
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_check as PC                                          # noqa: E402
import pcb_wire as PW                                           # noqa: E402

SK = 25.4 / 90.0
path = sys.argv[1]
want = [w.split(".") for w in sys.argv[2:]] or [["C2", "connector0"], ["C2", "connector1"]]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")
pads = {(q["title"], q["cid"]): q for q in PC.collect(path)["pads"]}
pts = []
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Wire"):
        continue
    t = PW.parse_trace(b)
    if t is None:
        continue
    pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b).group(1)
    fl = re.search(r'wireFlags="(\d+)"', pv)
    a, bb = PW.abs_ends(t["geo"])
    for e, p in ((0, a), (1, bb)):
        pts.append((mi.group(1), int(fl.group(1)) if fl else None, t["layer"], e, p))


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


for t, cid in want:
    q = pads.get((t, cid))
    if q is None:
        print("%s.%s ✗ 找不到" % (t, cid))
        continue
    print("\n%s.%s  lay=%s  n=%s  c=(%.4f,%.4f)  size_mm=%s"
          % (t, cid, q["layer"], q["nm"], q["c"][0], q["c"][1], q.get("size_mm")))
    print("   poly=%s" % (q.get("poly") and [(round(a, 3), round(b, 3)) for a, b in q["poly"]]))
    print("   circle=%s" % (q.get("circle") and ((round(q["circle"][0][0], 3),
                                                 round(q["circle"][0][1], 3)),
                                                round(q["circle"][1], 3))))
    tbl = []
    for (mi, fl, lay, e, p) in pts:
        d = ((p[0] - q["c"][0]) ** 2 + (p[1] - q["c"][1]) ** 2) ** .5 * SK
        tbl.append((d, mi, fl, lay, e, p, inside(p, q)))
    tbl.sort()
    for d, mi, fl, lay, e, p, ins in tbl[:5]:
        print("   %7.3f mm  Wire%s 端%d flags=%s layer=%-12s 在盘里=%s"
              % (d, mi, e, fl, lay, ins))
