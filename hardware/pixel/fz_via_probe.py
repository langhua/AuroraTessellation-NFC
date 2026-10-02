# -*- coding: utf-8 -*-
r"""查指定的过孔 ✓：文件名（`<title>`）→ 它自己记的连接 ✓、谁记着它 ✓、它落在哪个焊盘上 ✓

用途 ✓（2026-10-02 用户给的证据 ✓）：Fritzing 说「还剩 2 个连接件」，
两条虚线两端是 **`Via1`↔`C1.pin1`**（黑 ✓ = GND）与 **`L1.inner`↔`Via8`** ✓
⇒ 这两颗过孔在 Fritzing 眼里**没接进网** ✗ —— 这里量清楚"文件里它到底连着谁" ✓。
用法 ✓：`fz_via_probe.py <sketch.fzz> [Via1 Via8]`
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_check as PC                                             # noqa: E402
import pcb_wire as PW                                              # noqa: E402

SK = 25.4 / 90.0
M = lambda u: u * SK                                               # noqa: E731
# ★★ 过孔的**铜心** ≠ 文件里的 x,y ✓：恒差「孔径/2 + 环宽 + 0.56444mm」✓
#   实测（v59 ✓）：Δ = (+3.063, +3.063) sketch 单位 = 0.8644 mm ✓（= 2 单位画布留白 ✓）
RING_OFF = 0.86444                                                 # `hole 0.3, ring 0.15` ✓

path = sys.argv[1]
want = sys.argv[2:] or ["Via1", "Via8"]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

vias = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Via"):
        continue
    g = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
    fl = re.search(r'wireFlags="(\d+)"', g.group(1))
    ti = re.search(r"<title>([^<]*)</title>", b)
    con = [(y.group(1), y.group(2), y.group(3)) for y in re.finditer(
        r'<connect connectorId="([\w]+)" modelIndex="(\d+)" layer="([\w]+)"', g.group(1))]
    vias[mi.group(1)] = dict(
        mi=mi.group(1), title=ti.group(1) if ti else "",
        p=(float(x.group(1)), float(x.group(2))) if x else None,
        flags=int(fl.group(1)) if fl else None, conn=con)

# 谁（走线）记着这颗孔 ✓
ref = {}
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
    ends = {0: a, 1: bb}
    for e, lst in (t.get("ends") or {}).items():
        for (cid, tmi, lay) in lst:
            if tmi in vias:
                ref.setdefault(tmi, []).append(
                    (mi.group(1), int(fl.group(1)) if fl else None, int(e),
                     ends.get(int(e)), lay, t["layer"]))

pads = PC.collect(path)["pads"]
for v in vias.values():
    if want and v["title"] not in want:
        continue
    off = (RING_OFF / SK, RING_OFF / SK)
    c = (v["p"][0] + off[0], v["p"][1] + off[1]) if v["p"] else None
    print("\n=== %s（modelIndex=%s ✓ flags=%s ✓）===" % (v["title"], v["mi"], v["flags"]))
    print("   文件里 x,y = %s ⇒ **铜心** = (%.3f, %.3f) = (%.3f, %.3f) mm"
          % (v["p"], c[0], c[1], M(c[0]), M(c[1])))
    print("   它自己记的连接（%d 条）：%s" % (len(v["conn"]), v["conn"] or "（空 ✗）"))
    r = ref.get(v["mi"], [])
    print("   谁记着它（%d 条 ✓；★ = 记的层与走线**自己的层**对不上 ✗）：" % len(r))
    for (wmi, wfl, e, pt, lay, own) in r:
        d = ((pt[0] - c[0]) ** 2 + (pt[1] - c[1]) ** 2) ** .5 * SK if pt else -1
        mark = "" if lay.replace("trace", "") == own.replace("trace", "") else "  ★ 对不上"
        print("      Wire%s flags=%s 端%d 记的层=%-12s 自己的层=%-12s 端点=(%.3f,%.3f) 离铜心 %.3f mm%s"
              % (wmi, wfl, e, lay, own, pt[0], pt[1], d, mark))
    if not r:
        print("      ✗ **没有任何走线记着它** ⇒ 在文件里就是一颗**孤立的孔** ✓"
              "（Fritzing 因此把它的脚算成「还没布线」✓）")
    for q in pads:                                  # 它落在哪个焊盘上（via-in-pad ✓）
        if q.get("circle"):
            (cx, cy), rr = q["circle"]
            d = ((c[0] - cx) ** 2 + (c[1] - cy) ** 2) ** .5
            if d <= rr:
                print("      ★ 它落在焊盘 `%s.%s`（%s）上 ✓（via-in-pad ✓）" %
                      (q["title"], q["cid"], q["nm"]))
