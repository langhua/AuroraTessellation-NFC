# -*- coding: utf-8 -*-
r"""16 颗过孔排一张表 ✓：找"Fritzing 认的"和"它不认的（Via1/Via8）"差在哪 ✗

每行 ✓：名字 / `wireFlags` / 连接器声明的层 / 邻居（走线）几条 / 邻居**自己的层** /
       邻居**记这颗孔时写的层** / 两侧层是否**不同**（换层孔 ✓）
用法 ✓：`fz_via_table.py <sketch.fzz>`
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_wire as PW                                              # noqa: E402

path = sys.argv[1]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

wire = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Wire"):
        continue
    t = PW.parse_trace(b)
    if t is None:
        continue
    wire[mi.group(1)] = dict(mi=mi.group(1), layer=t["layer"])

vias = []
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Via"):
        continue
    g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    body = g.group(1)
    ti = re.search(r"<title>([^<]*)</title>", b)
    fl = re.search(r'wireFlags="(\d+)"', body)
    cl = re.search(r'<connector connectorId="\w+"\s+layer="(\w+)"', body)
    recs = [(y.group(1), y.group(2), y.group(3)) for y in re.finditer(
        r'<connect connectorId="([\w]+)" modelIndex="(\d+)" layer="([\w]+)"', body)]
    vias.append(dict(title=ti.group(1) if ti else mi.group(1), mi=mi.group(1),
                     flags=int(fl.group(1)) if fl else None,
                     clayer=cl.group(1) if cl else "?", recs=recs))

print("%-6s %-6s %-9s %-4s %-28s %-28s %s"
      % ("孔", "flags", "连接器层", "邻居", "邻居自己的层", "邻居记这颗孔的层", "换层?"))
for v in vias:
    own, rec = [], []
    for (_cid, wmi, lay) in v["recs"]:
        w = wire.get(wmi)
        own.append(w["layer"].replace("trace", "") if w else "?")
        rec.append(lay.replace("trace", ""))
    diff = "★ 是" if len(set(own)) > 1 else "否"
    mark = "  ← Fritzing 报不认" if v["title"] in ("Via1", "Via8") else ""
    print("%-6s %-6s %-9s %-4d %-28s %-28s %s%s"
          % (v["title"], v["flags"], v["clayer"], len(v["recs"]),
             ",".join(own) or "-", ",".join(rec) or "-", diff, mark))
