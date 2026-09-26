# -*- coding: utf-8 -*-
"""清掉 sketch 里**悬空**的连接记录 ✓（指向不存在实例的 `<connect>` ✗）

为什么要它（2026-09-26 用户实测 ✗）：删掉旧导线后，若"孔 → 那根线"的记录还留着 ✗，
Fritzing 会把那些孔显示成接在一根不存在的线上 ✗ ⇒ 悬停一个孔、一大片孔都亮 ✗。
实测我以前的版本各有 **12 处** ✗、用户手画版 **0 处** ✓。

用法: py -3.13 fix_connects.py <in.fzz> <out.fzz>
"""
import sys
import zipfile
import xml.etree.ElementTree as ET


def tag(e):
    return e.tag.split("}")[-1]


src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(src) as z:
    names = z.namelist()
    data = {n: z.read(n) for n in names}
sk = [n for n in names if n.endswith(".fz")][0]
root = ET.fromstring(data[sk])
live = {e.get("modelIndex") for e in root.iter("instance")}
removed = []
for parent in list(root.iter()):
    for c in list(parent):
        if tag(c) != "connect":
            continue
        mi = c.get("modelIndex")
        if mi and mi not in live:
            parent.remove(c)
            removed.append((mi, c.get("connectorId")))
data[sk] = ET.tostring(root, encoding="utf-8")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.writestr(n, data[n])
print("悬空记录：删掉 %d 条 %s（实例 %d 个 ✓）"
      % (len(removed), sorted({m for m, _ in removed})[:4], len(live)))
print("写入 %s" % out)
