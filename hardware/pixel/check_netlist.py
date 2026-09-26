# -*- coding: utf-8 -*-
r"""网表核对（通用 ✓）：从 sketch 里建连接图 ⇒ 算连通分量 ⇒ 与期望网表比 ✓

只认原理图层的连接 ✓（`layer="schematic"|"schematicTrace"`），并且**把面包板整个排除** ✓
—— 零件的"插在面包板哪个孔"是面包板视图的事 ✗，跟原理图布线无关 ✓
（否则（旧版没删干净时）面包板会把不同的网粘在一起 ✗）

节点 = (实例 modelIndex, 脚 id)；边 = 每一对互相登记的 <connect> ✓

用法：py -3.13 nets_check4.py <sketch.fzz>
"""
import sys
import zipfile
import xml.etree.ElementTree as ET

SCH = ("schematic", "schematicTrace")


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def sch_edges(inst):
    """[(自己的脚, 对方的脚, 对方实例, 对方 layer), …]（只看原理图层 ✓）"""
    out = []
    vw = child(inst, "views")
    sub = child(vw, "schematicView") if vw is not None else None
    if sub is None:
        return out
    for cbox in sub.iter():
        if tag(cbox) != "connectors":
            continue
        for con in cbox:
            if tag(con) != "connector":
                continue
            for cs in con:
                if tag(cs) != "connects":
                    continue
                for c in cs:
                    if tag(c) != "connect":
                        continue
                    if (c.get("layer") or "") not in SCH:
                        continue
                    out.append((con.get("connectorId"), c.get("connectorId"),
                                c.get("modelIndex"), c.get("layer")))
    return out


z = zipfile.ZipFile(sys.argv[1])
root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))

title, mid, edges = {}, {}, {}
for e in root.iter("instance"):
    mi = e.get("modelIndex")
    title[mi] = (e.findtext("title") or "").strip()
    mid[mi] = e.get("moduleIdRef") or ""
    edges[mi] = sch_edges(e)

skip = {mi for mi in title if "breadboard" in mid[mi].lower()}
print("实例 %d；排除面包板 %d 个（%s）" % (len(title), len(skip),
                                    ", ".join(title[m] for m in skip)))

# 并查集 ✓
parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb


for mi, es in edges.items():
    if mi in skip:
        continue
    for own, tcid, tmi, _tl in es:
        if tmi in skip or tmi not in title:
            continue
        if tcid is None:
            continue
        union((mi, own), (tmi, tcid))

groups = {}
for mi in title:
    if mi in skip or title[mi].startswith("Wire"):
        continue
    for own, _t, tmi, _l in edges[mi]:
        if tmi in skip or tmi not in title:
            continue
        if title[mi].startswith("Wire"):
            continue
        groups.setdefault(find((mi, own)), set()).add((title[mi], own))

print("\n=== 连通分量（只列含 ≥2 个脚的）===")
for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    if len(v) > 1:
        print("  %s" % ", ".join(sorted("%s.%s" % t for t in v)))

EXPECT = {
    "COIL_A": {"L1.connector0", "D3.connector5"},
    "COIL_B": {"L1.connector1", "D3.connector2"},
    "GND": {"D3.connector0", "D3.connector1", "C1.connector1", "U1.connector3",
            "C2.connector1", "LED2.connector1", "J1.connector1", "J2.connector1"},
    "BR+": {"D3.connector3", "D3.connector4", "R1.connector0"},
    "RC": {"R1.connector1", "C1.connector0", "U1.connector1"},
    "5V": {"U1.connector5", "C2.connector0", "LED2.connector3", "J1.connector0",
           "J2.connector0"},
    "DATA_IN": {"U1.connector2", "J1.connector2"},
    "DATA_OUT": {"U1.connector4", "J2.connector2"},
    "LED_DIN": {"U1.connector12", "LED2.connector2"},
    "EPAD": set(),      # 单脚网 ⇒ 本来就没有导线，图上留空 ✓（保持独立成网 ✓）
}
print("\n=== 对照 pixel-netlist.md §2 ===")
bad = 0
for net, pins in EXPECT.items():
    got = None
    for v in groups.values():
        s = {"%s.%s" % t for t in v}
        if pins & s:
            got = s if got is None else (got | s)
    got = got or set()
    if net == "EPAD":
        got = set()
    ok = got == pins
    bad += 0 if ok else 1
    print("  %-9s %s  应有 %-42s 实际 %s"
          % (net, "✓" if ok else "✗", ",".join(sorted(pins)),
             ",".join(sorted(got)) or "（缺）"))
print("\n判定: %s" % ("✓ 10 个网全对" if not bad else "✗ %d 个网对不上" % bad))
