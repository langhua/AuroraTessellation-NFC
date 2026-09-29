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

import sch_net                       # ★ 网标签规则（**唯一实现** ✓，2026-09-29 ✓）

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

# ★★ **脚名**只能从 `.fzz` **自带的那份 `.fzp`** 里读 ✓ —— 草图里只写 `connectorId="connector20"` ✗
#   （实例块里**没有**脚名 ✗）⇒ 要判“这只脚是不是 VSS/GND”就必须看件定义 ✓。
#   ★ 这条只为**接地符号规则**服务 ✓（`sch_net.grounded_connectors` ✓，2026-09-29 ✓）。
mod_conn_names = {}
for _n in z.namelist():
    if not _n.endswith(".fzp"):
        continue
    try:
        _t = ET.fromstring(z.read(_n))
    except ET.ParseError:
        continue
    _mm = _t.get("moduleId") or (_t.findtext("moduleId") or "")
    if not _mm:
        continue
    mod_conn_names[_mm] = {_c.get("id"): (_c.get("name") or "")
                           for _c in _t.iter("connector") if _c.get("id")}

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

# ★★★ 2026-09-29 ✓ **网标签：同名即同网** ✓（用户 09-26 定 ✓、09-29 要求落到判定器 ✓）——
#   网标签是**元件实例** ✓（`moduleIdRef` 带 `NetLabel` ✓），**实例标题 = 网名** ✓
#   （实测 `pixel-schematic-v29_netlabel.fzz` ✓：4 个实例标题 = `RC`/`RC`/`GND`/`GND` ✓）
#   ⇒ **同名的所有标签脚并成一个网** ✓ —— 这就是“**抽象连接**” ✓（只适用原理图 ✓）。
#   ✗ 以前不认它 ⇒ 同一张网被拆成两段 ✗（实测：`GND` 与 `RC` 各被拆成 2 段 ✗）。
#   ★ 判据只在 `sch_net.py` 一份 ✓（别在这里再写一遍“怎么算网标签” ✗）。
_lb = {}
_LBLT = set()                        # ★ 网标签实例的**标题** ✓（下面各表是按标题建的 ✓）
for _mi in title:
    if _mi in skip or title[_mi].startswith("Wire"):
        continue
    _n = sch_net.net_name(mid[_mi], title[_mi])
    if _n:
        _lb.setdefault(_n, []).append(_mi)
        _LBLT.add(title[_mi])
_lbp = 0
for _n, _ms in sorted(_lb.items()):
    _first = None
    for _mi in _ms:
        for _cid in (cids.get(_mi) or []):
            if _first is None:
                _first = (_mi, _cid)
            else:
                union(_first, (_mi, _cid))
                _lbp += 1
print("网标签：%d 个网名 / %d 个实例 ⇒ **同名合并 %d 对** ✓（%s）"
      % (len(_lb), sum(len(v) for v in _lb.values()), _lbp,
         "、".join("%s×%d" % (k, len(v)) for k, v in sorted(_lb.items())) or "（本图没有网标签 ✓）"))


# ★★★ 2026-09-29 ✓ **接地符号**（core `GroundModuleID` ✓）—— 用户当天把 `GND` 网标签换成
#   接地符号后让我“检查” ✓，本判定器当场报「`GND` 被拆成 2 段」✗ ⇒ 查下去发现是**判定器缺规则** ✓：
#   ★ 规则**不是**“两个符号互连” ✗ —— 接地符号把**全图「脚名 ∈ {GND,VSS,GROUND}」的连接器**
#     一把拉成一张网 ✓（证据在 Fritzing 源码里 ✓，逐条抄在 `sch_net.py` 那段注释 ✓）。
#   ⇒ 本图：`U1.connector3`（**VSS** ✓）与 `LED2.connector1`（**GND** ✓）被拉进来 ✓，
#     而它俩各自所在的那两段正好就是被拆的两段 ✓ ⇒ 一合，`GND` 就是**一张网** ✓✓。
_gl = sch_net.ground_links(mid, mod_conn_names, cids)
for _a, _b in _gl:
    union(_a, _b)
_g1 = sch_net.grounded_connectors(mid, mod_conn_names, cids)
print("接地符号：%s ⇒ 按 Fritzing 规则把「**脚名 ∈ {GND,VSS,GROUND}**」的 **%d 只脚**"
      "并成一张网 ✓（合并 %d 对 ✓）｜%s"
      % ("有" if _g1 else "无", len(_g1), len(_gl),
         "、".join("%s.%s" % (title.get(mi, mi), cid) for mi, cid in _g1) or
         "（没有符号 ⇒ 不合并 ✓）"))
# ★ 接地符号跟网标签一样是**桥** ✓、**不是电气成员** ✗ ⇒ 对照 `EXPECT` 时不计入 ✓
#   （它的脚本来就“只为把别人拉起来”而存在 ✓；算成成员就会报“多了 Ground1.connector0” ✗ = 假报 ✗）。
_GNDT = {title[_mi] for _mi in title if sch_net.is_ground_symbol(mid[_mi])}


# ★ 网标签是**桥** ✓，**不是电气成员** ✗ ⇒ 对照 `EXPECT` 时**不计入** ✓
#   （它的作用就是“同名即连通” ✓；把它当成员会报“多了 GND.connector0” ✗ = 假报 ✗）。
def _ismem(_t):
    """这个脚是**电气成员**吗 ✓ —— 网标签 / 接地符号**不算成员** ✓（它们是**桥** ✓）"""
    return _t not in _LBLT and _t not in _GNDT

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
        sf = {"%s.%s" % t for t in v}                 # 全部脚（含标签 ✓）—— 用来“找到这一段” ✓
        s = {"%s.%s" % t for t in v if _ismem(t[0])}  # 只留**电气成员** ✓（标签是桥 ✗）
        if pins & sf:
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
        _extra = sorted(segs[0] - pins)
        _miss = sorted(pins - segs[0])
        note = ""
        if _extra:
            note += "  ⚠ **多了** %s ✗（= 和别的网**粘连** ✗）" % ",".join(_extra)
        if _miss:
            note += "  ⚠ **少了** %s ✗（= 有脚**没连上** ✗）" % ",".join(_miss)
    print("  %-9s %s  应有 %-42s 实际 %s%s"
          % (net, "✓" if ok else "✗", ",".join(sorted(pins)),
             ",".join(sorted(got)) or "（缺）", note))
print("\n判定: %s" % ("✓ %d 个网全对" % len(EXPECT) if not bad else "✗ %d 个网对不上" % bad))
#   ★ 2026-09-29 修 ✓：这句原来写死“**10** 个网”✗ —— `EXPECT` 实际是 **9** 个 ✗
#     （COIL_A/COIL_B/GND/BR+/RC/5V/DATA_IN/DATA_OUT/LED_DIN ✓）⇒ 改成**从表里算** ✓，
#     免得又出现“报的数”和“查的表”对不上 ✗（与 `render_sch.py` 的「9 张网」一致 ✓）。
# ★★★ 2026-09-30 ✓ **退出码** ✗✗（本次最贵的一条教训 ✓）：
#   ✗ 本脚本以前**从不设退出码** ✗ ⇒ “判定：✗ 1 个网对不上”照样 **exit 0** ✗ ⇒
#     我拿“七道闸门全 exit 0”当合格线 ⇒ **这一道是橡皮图章** ✗✗：
#     实测 `pixel-schematic-v36.fzz` —— 它**明明打出了**「5V ✗ 少了 C2.connector0 ✗」✓，
#     而退出码是 **0** ✗ ⇒ 我以为它过了 ✗，真错漏到了交付版里 ✗（用户看图才发现的 ✓）。
#   ⇒ 定下：**判定行与退出码必须一致** ✓（✗ ⇒ 1 ✓；跑不起来 ⇒ 2 ✓ ⇒ 绝不静默放行 ✗）。
#   ★ 顺带一条通则 ✓：**“退出码 0”不等于“过”** ✗ —— 每个核对器都得有**负例自检** ✓
#     （拿一个**已知有错**的文件跑一遍，确认它会**非 0** ✓）。
raise SystemExit(2 if bad is None else (1 if bad else 0))
