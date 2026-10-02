# -*- coding: utf-8 -*-
r"""看几颗过孔周围这**一小片**是怎么绕的 ✓（评估"去掉 via→via 那一跳"要改多少 ✓）
用法 ✓：`fz_via_local.py <sketch.fzz> Via1 Via2 Via7 Via8 Via9`
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
want = set(sys.argv[2:]) or {"Via1", "Via2", "Via7", "Via8", "Via9"}

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

wire, via = {}, {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi):
        continue
    if mo.group(1).startswith("Wire"):
        t = PW.parse_trace(b)
        if t is None:
            continue
        a, bb = PW.abs_ends(t["geo"])
        pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b).group(1)
        fl = re.search(r'wireFlags="(\d+)"', pv)
        wire[mi.group(1)] = dict(mi=mi.group(1), layer=t["layer"], a=a, b=bb,
                                 mils=t.get("mils"), ends=t.get("ends") or {},
                                 flags=int(fl.group(1)) if fl else None)
    elif mo.group(1).startswith("Via"):
        g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
        x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
        ti = re.search(r"<title>([^<]*)</title>", b)
        rec = [(y.group(1), y.group(2), y.group(3)) for y in re.finditer(
            r'<connect connectorId="([\w]+)" modelIndex="(\d+)" layer="([\w]+)"', g.group(1))]
        via[mi.group(1)] = dict(mi=mi.group(1), title=ti.group(1) if ti else mi.group(1),
                                p=(float(x.group(1)), float(x.group(2))) if x else None,
                                rec=rec)

pads = {(q.get("mi"), q.get("cid")): q for q in PC.collect(path)["pads"]}


def nm(cid, tmi):
    if tmi in wire:
        return "Wire%s(%s)" % (tmi, wire[tmi]["layer"].replace("trace", ""))
    if tmi in via:
        return via[tmi]["title"]
    q = pads.get((tmi, cid))
    return "%s.%s" % (q["title"], q["nm"] or cid) if q else "%s.%s" % (tmi, cid)


for v in via.values():
    if v["title"] not in want:
        continue
    print("\n=== %s（%s ✓ 自己记了 %d 条连接）==="
          % (v["title"], "%.3f,%.3f mm" % (M(v["p"][0]), M(v["p"][1])) if v["p"] else "?",
             len(v["rec"])))
    for (cid, wmi, lay) in v["rec"]:
        w = wire.get(wmi)
        if w is None:
            print("   邻居 %s ✗（不是走线）" % wmi)
            continue
        ln = ((w["a"][0] - w["b"][0]) ** 2 + (w["a"][1] - w["b"][1]) ** 2) ** .5 * SK
        print("   `Wire%s`（%s ✓ %s mil ✓ 长 %.2f mm ✓ **flags=%s**）"
              % (wmi, w["layer"].replace("trace", ""), w["mils"], ln, w["flags"]))
        for e, lst in w["ends"].items():
            others = "、".join("`%s`" % nm(c2, t2) for (c2, t2, _l2) in lst)
            print("       端%s → %s" % (e, others))
