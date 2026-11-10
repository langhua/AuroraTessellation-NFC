# -*- coding: utf-8 -*-
r"""把 `D4` 从 `U1` 的脚列里**挪出去**（方案 A ✓，2026-11-10 用户定）

用法: py -3.13 -u move_d4.py <in.fzz> <out.fzz>

**为什么要挪** ✗（用户实测指出 ✓）：`D4` 原来插在
  · 阴极 `pin19H` —— 与 `U1.connector8`（**PC2**）同一列（同一 bus）✗
  · 阳极 `pin23H` —— 与 `U1.connector4`（**PD0**）同一列 ✗
而这一列又用跳线 `pin19J → pin19Y` 接到了 **5 V 轨**
⇒ 等于把 **`PC2` 并进 5 V、`PD0` 并进 `RC`** ✗
（面包板"一列 = 一根铜片"，插进同一列就是连上 ✓，电气上没错、但是隐患 ✗）

**挪到哪** ✓（cols 7–11 是空的，一个孔都没占 ✓）：
```
阴极 pin7H  ──`D4`（本体占 cols 8–10，那一带全空）──  阳极 pin11H
   └ 跳线 pin7J  → pin7Y   （col7 的 Y 轨孔 = 5 V ✓）
                       └ 跳线 pin11J → pin16G  （col16 上半 bus = `RC` ✓）
```
★ 为什么不去 col12/col20：`col12` 上半是 `COIL_A`（`D3` 在 `pin12F`）✗、
  `col20` 是 `U1` 的脚 ✗ —— `D4` 跨 4 列（36 单位），两边都不合适 ✓
★ 颜色照官方配色表 ✓：5 V = 红 `#cc1414`、`RC` = 橙 `#ef6100`（`pixel_nets.COLOR`）✓
★ 只动 `breadboardView` ✓：`schematicView` / `pcbView` 一个字不碰 ✓
"""
import re
import sys
import zipfile

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
OX, OY = 9.0, 18.0
BOARD_MI = "5785"
D4_MI = 90015689

# 旧 → 新（阴极、阳极）
# ★ 2026-11-10 第二版：阳极直接插进 `RC` 的 col27 下半 bus（`PD6` 也在那一条 ✓）
#   ⇒ 只需**一根**短跳线（阴极 → col30 的 5 V bus）✓
#   ★ 为什么不去左边（col7/col11）：`col16` 的 RC 被 `R1`（col13H→col16I 的本体）挡住 ✗，
#     任何从左侧接进 `pin16G/H` 的线都会压 `R1` 本体 ✗（实测 ⑥ 报过 ✓）
#   ★ `D4` 跨度 4 列（36 单位）⇒ 阳极在 col27、阴极就在 **col31**（不是 23）✓
#     ⇒ 必须把本体**转 180°**，色带（阴极）才朝右 ✓
MOVE = {"pin19H": "pin31D", "pin23H": "pin27D"}
NEW_X = None                            # 改用 transform（rot180），不再只改 x ✗
T_M31, T_M32 = 288.04, 139.5375         # 屏幕坐标 = (m31 - 局部x, m32 - 局部y) ✓

# 要删的三根旧线：(title, modelIndex)
DEL = [("Wire90015705", 90015705),      # 5 V → PC2 那一列 ✗
       ("Wire90015724", 90015724),      # RC → col23 的桥（阳极已搬走 ⇒ 不再需要）
       ("Wire90015725", 90015725)]

# 新加的一根：(起点, 终点, 颜色) —— 阴极 bus（col31 下半）→ col30 上半的 5 V bus ✓
#   ★ 落点选 `pin30G` 而不是 `pin30H`：`pin30H` 已被 `Wire90015710` 占着 ✗
NEW = [("pin31E", "pin30G", "#cc1414")]


def num(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


def hole_xy(h):
    m = re.fullmatch(r"pin(\d+)([A-Z])", h)
    return (int(m.group(1)) * 9.0 + OX, ROW_Y[m.group(2)] + OY)


def wire_block(mi, a, b, color):
    ax, ay = hole_xy(a)
    bx, by = hole_xy(b)
    return (
        '        <instance moduleIdRef="WireModuleID" modelIndex="%d" path=":/resources/parts/core/wire.fzp">\n'
        '            <title>Wire%d</title>\n'
        '            <views>\n'
        '                <breadboardView layer="breadboardWire">\n'
        '                    <geometry z="3.50103" x="%s" y="%s" x1="0" y1="0" x2="%s" y2="%s" wireFlags="64"/>\n'
        '                    <wireExtras mils="22.2222" color="%s" opacity="1" banded="0"/>\n'
        '                    <connectors>\n'
        '                        <connector connectorId="connector0" layer="breadboardWire">\n'
        '                            <geometry x="0" y="0"/>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                        <connector connectorId="connector1" layer="breadboardWire">\n'
        '                            <geometry x="0" y="0"/>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                    </connectors>\n'
        '                </breadboardView>\n'
        '            </views>\n'
        '        </instance>\n'
        % (mi, mi, num(ax), num(ay), num(bx - ax), num(by - ay), color,
           a, BOARD_MI, b, BOARD_MI))


def drop_instance(text, title):
    # ★ 行尾可能是 LF 也可能是 CRLF（本图两段混着 ✓）⇒ 不要要求 `</instance>\n` ✗
    for m in re.finditer(r"[ \t]*<instance\b.*?</instance>", text, re.S):
        if "<title>%s</title>" % title in m.group(0):
            end = m.end()
            while end < len(text) and text[end] in "\r\n":
                end += 1
            return text[:m.start()] + text[end:]
    raise SystemExit("找不到实例 %s ✗" % title)


def board_rename_hole(bblk, old, new, mi):
    """板件里把"某孔插着 mi 的某个 connector"整条换成新孔名 ✓"""
    i = bblk.find('connectorId="%s" layer="breadboardbreadboard"' % old)
    if i < 0:
        raise SystemExit("板件里没有孔 %s ✗" % old)
    j = bblk.find("</connector>", i)
    seg = bblk[i:j + 12]
    if 'modelIndex="%d"' % mi not in seg:
        raise SystemExit("孔 %s 上没有 modelIndex=%d ✗" % (old, mi))
    return bblk[:i] + seg.replace('"%s"' % old, '"%s"' % new) + bblk[j + 12:]


def board_drop_wire(bblk, mi):
    bblk = re.sub(r'<connect connectorId="connector\d+" modelIndex="%d" layer="breadboardWire"/>' % mi,
                  "", bblk)
    # 顺手收掉因此变空的孔条目 ✓（行尾 LF/CRLF 都可能 ⇒ 用 \s* 收 ✓）
    return re.sub(r'[ \t]*<connector connectorId="pin\d+[A-Z]" layer="breadboardbreadboard">\s*'
                  r'<geometry[^>]*/>\s*<connects>\s*</connects>\s*</connector>\s*', "", bblk)


def board_add_hole(bblk, hole, mi, cid):
    anchor = 'connectorId="%s" layer="breadboardbreadboard"' % hole
    newc = '<connect connectorId="%s" modelIndex="%d" layer="breadboardWire"/>' % (cid, mi)
    if anchor in bblk:
        i = bblk.index("<connects>", bblk.index(anchor)) + len("<connects>")
        return bblk[:i] + newc + bblk[i:]
    j = bblk.rindex("</connectors>")
    add = ('            <connector connectorId="%s" layer="breadboardbreadboard">'
           '<geometry x="0" y="0"/><connects>%s</connects></connector>\n        ' % (hole, newc))
    return bblk[:j] + add + bblk[j:]


def main(argv):
    src, out = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    items = [(i, z.read(i.filename)) for i in z.infolist()]
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")

    if '<connectorId="pin31D"' in text:
        raise SystemExit("看起来已经挪过了 ✗（pin31D 已存在）")

    mi0 = max(int(x) for x in re.findall(r'modelIndex="(\d{6,})"', text)) + 1
    mi5 = mi0 + 1
    print("新线的 modelIndex：%d / %d" % (mi0, mi5))

    # ── ① 板件：改 D4 的两个孔名、删旧线回指、补新线孔声明 ──
    bm = re.search(r'<instance [^>]*moduleIdRef="Breadboard-[^"]*"[^>]*>.*?</instance>', text, re.S)
    bblk, nb = bm.group(0), bm.group(0)
    nb = board_rename_hole(nb, "pin19H", MOVE["pin19H"], D4_MI)
    nb = board_rename_hole(nb, "pin23H", MOVE["pin23H"], D4_MI)
    for _t, mi in DEL:
        nb = board_drop_wire(nb, mi)
    nb = board_add_hole(nb, NEW[0][0], mi0, "connector0")
    nb = board_add_hole(nb, NEW[0][1], mi0, "connector1")
    text = text.replace(bblk, nb)

    # ── ② D4 自己：只动 breadboardView 的 x 与两个孔名 ──
    dblk = None
    for m in re.finditer(r"[ \t]*<instance\b.*?</instance>", text, re.S):
        if "<title>D4</title>" in m.group(0):
            dblk = m.group(0)
            break
    if dblk is None:
        raise SystemExit("找不到 D4 ✗")
    bv = re.search(r"<breadboardView\b.*?</breadboardView>", dblk, re.S)
    bvv = bv.group(0)
    nvv = bvv
    old_geo = '<geometry z="2.50475" x="179.96" y="76.4625"/>'
    if old_geo not in nvv:
        raise SystemExit("D4 的 breadboardView 里找不到原始 geometry ✗")
    nvv = nvv.replace(old_geo,
                      '<geometry z="2.50475" x="0" y="0">\n'
                      '                        <transform m11="-1" m12="0" m13="0"'
                      ' m21="0" m22="-1" m23="0" m31="%s" m32="%s" m33="1"/>\n'
                      '                    </geometry>' % (num(T_M31), num(T_M32)), 1)
    for old, new in MOVE.items():
        nvv = nvv.replace('connectorId="%s"' % old, 'connectorId="%s"' % new)
    text = text.replace(dblk, dblk.replace(bvv, nvv))

    # ── ③ 删三根旧线、加两根新线 ──
    for t, _mi in DEL:
        text = drop_instance(text, t)
    add = wire_block(mi0, NEW[0][0], NEW[0][1], NEW[0][2])
    i = text.rindex("</instances>")
    text = text[:i] + add + text[i:]

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == name:
                data = text.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)

    print("✓ D4：阴极 pin19H→%s、阳极 pin23H→%s（转 180°）"
          % (MOVE["pin19H"], MOVE["pin23H"]))
    print("✓ 删旧线：%s" % ", ".join(t for t, _ in DEL))
    print("✓ 加新线：%s→%s（5 V 红）" % (NEW[0][0], NEW[0][1]))
    print("⇒ 写出 %s" % out)
    return 0


sys.exit(main(sys.argv[1:]))
