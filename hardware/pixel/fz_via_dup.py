# -*- coding: utf-8 -*-
r"""★ 查**重位的过孔** ✓（用户 2026-10-02 发现：`Via8` 跟 `Via6` 叠在一起 ✓）

背景 ✓（这是**我生成器的 bug** ✗）：过孔放重 ⇒ 线只会接到其中一颗 ✓、另一颗被撂单 ✓
⇒ Fritzing 就报"还有 N 个连接件没布线" ✓（它那 2 个就是这么来的 ✓）。

口径 ✓：铜心 = 文件 x,y ＋ `part_box.ring_off_mm(孔径, 环宽)` ✓（实测 Δ=0.8644mm ✓）；
        外半径 R = 孔径/2 + 环宽 = 0.30 mm ✓ ⇒ 两颗孔**心距 < 2R = 0.60 mm** 就算叠 ✗。
用法 ✓：`fz_via_dup.py <sketch.fzz> [阈值mm]`
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
import pcb_wire as PW                                              # noqa: E402

SK = 25.4 / 90.0
M = lambda u: u * SK                                               # noqa: E731
path = sys.argv[1]
THR = float(sys.argv[2]) if len(sys.argv) > 2 else 0.60            # mm ✓

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

vias = []
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
    nrec = len(re.findall(r'<connect\b', g.group(1)))
    vias.append(dict(title=ti.group(1) if ti else mi.group(1), mi=mi.group(1),
                     c=(float(x.group(1)) + off, float(x.group(2)) + off),
                     R=(hole / 2 + ring), nrec=nrec))

print("== %s：共 %d 颗过孔 ✓（阈值 %.2f mm ✓）==" % (os.path.basename(path), len(vias), THR))
for v in sorted(vias, key=lambda z: z["title"]):
    print("   %-6s 铜心 (%7.3f,%7.3f) mm  R=%.2f mm  文件里记了 %d 条连接 %s"
          % (v["title"], M(v["c"][0]), M(v["c"][1]), v["R"], v["nrec"],
             "✗ **一条都没有**" if v["nrec"] == 0 else ""))

bad = []
for i in range(len(vias)):
    for j in range(i + 1, len(vias)):
        d = math.hypot(vias[i]["c"][0] - vias[j]["c"][0],
                       vias[i]["c"][1] - vias[j]["c"][1]) * SK
        if d < THR:
            bad.append((d, vias[i], vias[j]))
print("\n★★ 心距 < %.2f mm 的过孔对（= **叠在一起** ✗）：%d 对" % (THR, len(bad)))
for d, a, b in sorted(bad, key=lambda z: (z[0], z[1]["title"], z[2]["title"])):
    print("   `%s` ↔ `%s`：心距 **%.3f mm** ✗（两倍外半径 = %.2f mm ⇒ %s）"
          "｜记录数 %d / %d"
          % (a["title"], b["title"], d, 2 * 0.3,
             "完全叠死" if d < 0.01 else "压在一起", a["nrec"], b["nrec"]))

# ★ 关键追问 ✓：同一对里的两颗孔**是不是同一个网** ✗ —— 若不同网 ⇒ 那就是**短路** ✓
#   口径 ✓：沿文件里的 `<connect>` 走 ✓，只把**走线/过孔**当中间节点 ✓（焊盘是端点 ✓）
byid, wireset, adj = {}, set(), {}


def link(x, y):
    adj.setdefault(x, set()).add(y)
    adj.setdefault(y, set()).add(x)


for _i, b in PW.blocks(text):
    mi = re.search(r'modelIndex="(\d+)"', b)
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    if not (mi and mo):
        continue
    g = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    if not g:
        continue
    byid[mi.group(1)] = mo.group(1)
    if mo.group(1).startswith(("Wire", "Via")):
        wireset.add(mi.group(1))
        for x in re.finditer(r'<connect connectorId="[\w]+" modelIndex="(\d+)"', g.group(1)):
            link(mi.group(1), x.group(1))


def reach(root):
    seen, st = set([root]), [root]
    while st:
        n = st.pop()
        for m in adj.get(n, ()):
            if m in wireset and m not in seen:
                seen.add(m)
                st.append(m)
    return seen


for d, a, b in bad:
    same = b["mi"] in reach(a["mi"])
    print("   ⇒ `%s` 和 `%s` %s" % (a["title"], b["title"],
                                    "**同一个网** ✓（只是重复放着 ⇒ 多余的那颗要删 ✗）"
                                    if same else
                                    "**不是同一个网** ✗✗ ⇒ 叠在一起就是**短路** ✓"))
