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
    """[(自己的脚, 对方的脚, 对方实例, 对方 layer), …]（**不过滤 layer** ✗，2026-09-28 改 ✓）

    ★★★ 为什么把 layer 过滤拿掉 ✗✗（这是本轮最该记住的一处 ✓ —— **自证盲区** ✓）：
      ✗ 原来写的是 `if layer not in ("schematic", "schematicTrace"): continue` ✗
        —— 看着很合理（“只看原理图的连接”✓），**实际上正好把真凶过滤掉了** ✗：
        实测 `t67_report.txt` ✓ —— **元件实例的 `schematicView` 里**，每只插在面包板上的脚
        都挂着一条 `layer="breadboardbreadboard"` 的 connect ✗（指向面包板实例 ✓）。
      ⇒ **Fritzing 在原理图视图里照它连通** ✗ ⇒ 插在**同一列孔**上的脚**粘成一片** ✗
        ⇒ 用户实测：点那条飞线时 **GND 与 RC 两个网同时高亮** ✗（= Fritzing 认为它们同网 ✗）。
      ⇒ 而生成器又**恰好按同一套 layer 口径**去清 ✗ ⇒ 两边一起错、检查永远通过 ✗✗
        —— 这就是“**不许自证**”那条 ✓：检查器必须比生成器**更严格** ✓。
      ⇒ 现在改成：**`schematicView` 下的连接一律算** ✓（layer 是别的视图也照算 ✓，
        因为 Fritzing 就是这么干的 ✗，得能把它抓出来 ✓）。
      ★ 同理 **不再用 `skip` 跳过面包板的边** ✗（面包板实例在 schematicView 里若还挂着连接，
        那就是**会让 Fritzing 粘网**的东西 ✗）；`skip` 只用于“**别把面包板的 690 个孔当脚报告**”✓。
    """
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
                    out.append((con.get("connectorId"), c.get("connectorId"),
                                c.get("modelIndex"), c.get("layer")))
    return out


def sch_connector_ids(inst):
    """该实例在**原理图视图**里登记过的 `connectorId` 集合 ✓（不依赖有没有 <connect> ✓）"""
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
            cid = con.get("connectorId")
            if cid and cid not in out:
                out.append(cid)
    return out


z = zipfile.ZipFile(sys.argv[1])
root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))

title, mid, edges, cids = {}, {}, {}, {}
for e in root.iter("instance"):
    mi = e.get("modelIndex")
    title[mi] = (e.findtext("title") or "").strip()
    mid[mi] = e.get("moduleIdRef") or ""
    edges[mi] = sch_edges(e)
    cids[mi] = sch_connector_ids(e)

skip = {mi for mi in title if "breadboard" in mid[mi].lower()}
print("实例 %d；面包板 %d 个（%s）—— 它们的**脚不列入报告** ✓，但**边照算** ✓（2026-09-28 改 ✓）"
      % (len(title), len(skip), ", ".join(title[m] for m in skip)))

# 并查集 ✓
parent = {}
_stat = {"ok": 0, "ghost": 0, "bb": 0, "none": 0}


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
    for own, tcid, tmi, tlayer in es:
        if tmi not in title:
            _stat["ghost"] += 1
            continue
        if tcid is None:
            _stat["none"] += 1
            continue
        if (tlayer or "") not in SCH:
            # ★ 照样 union ✓（Fritzing 就是这么算的 ✗）⇒ 但**报出来** ✓：
            #   生成器本该把这种“跨视图复制过来的连接”清掉 ✓（见 `gen_schematic_wires.py`
            #   的「原理图去粘」✓）⇒ 它一旦出现就是**粘网**的源头 ✗
            _stat["xview"] = _stat.get("xview", 0) + 1
        if tmi in skip:
            _stat["bb"] += 1
        union((mi, own), (tmi, tcid))
        _stat["ok"] += 1
print("边自检：总 %d ｜ **union 成功 %d** ｜ 跳过（幽灵 mi %d ｜ 对方脚空 %d）"
      % (sum(len(v) for v in edges.values()), _stat["ok"],
         _stat["ghost"], _stat["none"]))
print("   ★ **跨视图的连接（layer 不属于本视图）%d 条** %s"
      % (_stat.get("xview", 0),
         "✗✗ **会让 Fritzing 在原理图里粘网** ✗ ⇒ 生成器的「去粘」没生效 ✗"
         if _stat.get("xview", 0) else "✓（去粘生效 ✓）"))
print("   （其中连到面包板的 %d 条 ✓ —— 面包板的边**照算** ✓，不再跳过 ✗）" % _stat["bb"])

# ★★★ 2026-09-28 补 ✗✗ —— **这是本轮最关键的漏** ✓：
#   **导线自己是导体** ✓ ⇒ 同一根导线的两端 **天然连通** ✓（不需要任何人写 <connect> ✓）
#   ✗ 少了这一条 ⇒ 并查集只能“实例 ↔ 实例”跳 ✗ ⇒ “元件脚 A → 线段1 → 线段2 → …
#     → 元件脚 B”这条链 **永远走不通** ✗ ⇒ **每只脚各自为政** ✗
#   ★ 实测（就是它把我误导了半天 ✗）：`union 成功 196 次`，可
#     `分量共 30 个 ｜ 最大的那个含 1 个脚` ✗ —— 196 次合并**一点没通** ✗。
#   ★ 交叉验证（两个独立口径都说文件是好的 ✓）：
#     · `check_fake_wires.py` 的 (A)(B)(C) 全 **0** ✓（连接表与几何一致 ✓）；
#     · 用户实测：Fritzing 底部提示「**9 中的 8 网络布线完成**」✓。
#   ⇒ 结论：**错的是检查器** ✗，不是文件 ✓（这就是“不许自证”那条 ✓ ——
#     用户的眼睛 / Fritzing 自己的计数才是权威 ✓）。
#   ★ 只对 **Wire…** 实例合并 ✓ —— **元件的各个脚不许合并** ✗（元件内部靠网表 ✓）。
_br = 0
for mi in title:
    if mi in skip or not title[mi].startswith("Wire"):
        continue
    _c = cids.get(mi) or []
    for k in range(1, len(_c)):
        union((mi, _c[0]), (mi, _c[k]))
        _br += 1
print("导线自导通：%d 对 ✓（同一根导线的两端天然连通 ✓ —— 它们是导体 ✓）" % _br)

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
_alone = 0
for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    if len(v) > 1:
        print("  %s" % ", ".join(sorted("%s.%s" % t for t in v)))
    else:
        _alone += 1
# ★ 2026-09-28 加 ✓：**孤脚数**必须报出来 ✗ —— 起因：档 0 的文件里连通分量表**是空的**
#   （⇒ 每只脚各自一个分量 = **根本没连上** ✗），可下面的对照却报「✓ 10 个网全对」✗✗
#   ⇒ 那种“**空**表”最该被看见 ✓，不能让它悄悄过去 ✗。
print("  —— 单脚分量（= 没连到任何东西的脚）**%d 个** ✓" % _alone)
_sizes = sorted((len(v) for v in groups.values()), reverse=True)
print("  —— 分量共 %d 个 ｜ 最大的那个含 **%d 个脚** ✓（只做参考 ✓）"
      % (len(_sizes), _sizes[0] if _sizes else 0))

EXPECT = {
    "COIL_A": {"L1.connector0", "D3.connector5"},
    "COIL_B": {"L1.connector1", "D3.connector2"},
    "GND": {"D3.connector0", "D3.connector1", "C1.connector1", "U1.connector3",
            "C2.connector1", "LED2.connector1", "J1.connector1", "J2.connector1",
            # ★ EPAD（U1 的裸焊盘 connector20 ✓）**必须接地** ✓（2026-09-26 用户定 ✓）：
            #   上一版把它写成"单脚网、图上留空"是错的 ✗ —— 裸盘要接到 GND ✓
            "U1.connector20"},
    "BR+": {"D3.connector3", "D3.connector4", "R1.connector0"},
    "RC": {"R1.connector1", "C1.connector0", "U1.connector1"},
    "5V": {"U1.connector5", "C2.connector0", "LED2.connector3", "J1.connector0",
           "J2.connector0"},
    "DATA_IN": {"U1.connector2", "J1.connector2"},
    "DATA_OUT": {"U1.connector4", "J2.connector2"},
    "LED_DIN": {"U1.connector12", "LED2.connector2"},
}
print("\n=== 对照 pixel-netlist.md §2 ===")
# ★★ 2026-09-28 修**假通过** ✗✗（这是本轮最该修的一处 ✓）：
#   ✗ 旧写法 `for v in groups: if pins & s: got |= s` ✗ —— 把**与期望网有交集的
#     「所有」分量并起来** ✗ ⇒ 一个网**被打散成 N 段**（典型：**每只脚各自一个分量** = 根本没连 ✗）
#     时，这几段拼起来**恰好等于** pins ⇒ **判 ✓** ✗✗（档 0 就是这么假通过的 ✗）。
#   ✓ 正解：一个网**必须正好落在「一个」分量里** ✓（`len(segs) == 1 and segs[0] == pins`）；
#     段数 > 1 ⇒ 报「**网被拆成 N 段**」✓；分量里混进别网的脚 ⇒ 报「**多了**」✓。
bad = 0
for net, pins in EXPECT.items():
    segs = []
    for v in groups.values():
        s = {"%s.%s" % t for t in v}
        if pins & s:
            segs.append(s)
    got = set().union(*segs) if segs else set()
    ok = len(segs) == 1 and segs[0] == pins
    bad += 0 if ok else 1
    note = ""
    if len(segs) > 1:
        note = "  ⚠ **网被拆成 %d 段** ✗（= 有部分脚**没连上** ✗）：%s" % (
            len(segs), " ｜ ".join(",".join(sorted(s)) for s in
                                   sorted(segs, key=len, reverse=True)))
    elif len(segs) == 1 and segs[0] != pins:
        note = "  ⚠ **多了** %s ✗（= 和别的网**粘连** ✗）" % ",".join(sorted(segs[0] - pins))
    print("  %-9s %s  应有 %-42s 实际 %s%s"
          % (net, "✓" if ok else "✗", ",".join(sorted(pins)),
             ",".join(sorted(got)) or "（缺）", note))
print("\n判定: %s" % ("✓ 10 个网全对" if not bad else "✗ %d 个网对不上" % bad))
