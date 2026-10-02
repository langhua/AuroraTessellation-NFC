# -*- coding: utf-8 -*-
r"""从一颗过孔出发 ✓：把它两条走线的**另一端**接到哪些脚/过孔列出来 ✓
（用来确认"过孔把两片并进同一个网、但过孔自己不带边"这条规则 ✓）
用法 ✓：`fz_via_chain.py <sketch.fzz> [Via1]`
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
path = sys.argv[1]
want = sys.argv[2:] or ["Via1"]

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

wire, via = {}, {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi):
        continue
    mid = mo.group(1)
    if mid.startswith("Wire"):
        t = PW.parse_trace(b)
        if t is None:
            continue
        pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b).group(1)
        fl = re.search(r'wireFlags="(\d+)"', pv)
        a, bb = PW.abs_ends(t["geo"])
        wire[mi.group(1)] = dict(mi=mi.group(1), layer=t["layer"], a=a, b=bb,
                                 ends=t.get("ends") or {},
                                 flags=int(fl.group(1)) if fl else None)
    elif mid.startswith("Via"):
        g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
        ti = re.search(r"<title>([^<]*)</title>", b)
        con = [(y.group(1), y.group(2), y.group(3)) for y in re.finditer(
            r'<connect connectorId="([\w]+)" modelIndex="(\d+)" layer="([\w]+)"', g.group(1))]
        via[mi.group(1)] = dict(mi=mi.group(1), title=ti.group(1) if ti else "",
                                conn=con)

pads = {}
for q in PC.collect(path)["pads"]:
    pads[(q.get("mi"), q.get("cid"))] = q

for v in via.values():
    if want and v["title"] not in want:
        continue
    print("\n=== %s ===" % v["title"])
    for (host_cid, wmi, wlay) in v["conn"]:
        w = wire.get(wmi)
        if w is None:
            print("   邻居 %s（不是走线 ✗）" % wmi)
            continue
        print("   邻居 `Wire%s`（自己的层=%s ✓ 长度 %.2f mm ✓）"
              % (wmi, w["layer"],
                 (((w["a"][0] - w["b"][0]) ** 2 + (w["a"][1] - w["b"][1]) ** 2) ** .5) * SK))
        for e, lst in w["ends"].items():
            for (cid, tmi, lay) in lst:
                if tmi in via:
                    print("      端%s → 过孔 `%s`" % (e, via[tmi]["title"]))
                elif tmi in wire:
                    print("      端%s → 走线 `Wire%s`（层=%s ✓）" % (e, tmi, wire[tmi]["layer"]))
                else:
                    q = pads.get((tmi, cid))
                    print("      端%s → 脚 `%s`（%s ✓ 层=%s ✓）"
                          % (e, (q["title"] + "." + (q["nm"] or cid)) if q else tmi,
                             cid, q["layer"] if q else "?"))
