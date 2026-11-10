# -*- coding: utf-8 -*-
r"""手工补 `RC` 的**跨界桥**（两根线）✓ ⇒ 让 `RC_U` 与 `RC_L` 合成一张网

用法: py -3.13 -u add_rc_bridge.py <routed.fzz> <out.fzz>

**为什么需要它** ✗：`bb_route4` 对 `RC` 这条要跨中缝的网搜不到解 ✓
（`--near-hole` / `--straight` 都试过 ✗），但它布的 `COIL_A` 就跨过去了 ✓
⇒ 只是这一处搜不到 ✓ ⇒ 先用拆分网表让它把其余全布好 ✓，这里补两根线 ✓。

**桥的走向**（全部按**列**看 bus ✓：一列 5 个孔 `F..J` ／ `A..E` 各一条 ✓）：
```
R1/C1/D4(阳极)  --[col16 上半]--┐
                              ├─ 桥1：col16 跨中缝（上→下）✓
                              └─ 桥2：col16 下半 → col27 下半（PD5/PD6 那条 bus）✓
```
★ 每个孔**只能一根线端点** ✓（规则 ①）⇒ 两座桥不共用孔 ✓；都挑**空闲**孔 ✓。
"""
import re
import sys
import zipfile

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0}
COL = 9.0
BOARD_MI = "5785"
UP = "JIHGF"
LO = "EDCBA"
MI0 = 90019001


def xy(h):
    m = re.fullmatch(r"pin(\d+)([A-Z])", h)
    return (int(m.group(1)) * COL, ROW_Y[m.group(2)])


def num(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def wire_block(mi, a, b, color):
    ax, ay = xy(a)
    bx, by = xy(b)
    return (
        '            <instance moduleIdRef="WireModuleID" modelIndex="%d" path=":/resources/parts/core/wire.fzp">\n'
        '                <title>Wire%d</title>\n'
        '                <views>\n'
        '                    <breadboardView layer="breadboardWire">\n'
        '                        <geometry z="3.50037" x="%s" y="%s" x1="0" y1="0" x2="%s" y2="%s" wireFlags="64" />\n'
        '                        <wireExtras mils="22.2222" color="%s" opacity="1" banded="0" />\n'
        '                        <connectors><connector connectorId="connector0" layer="breadboardWire"><geometry x="0" y="0" />'
        '<connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard" /></connects></connector>'
        '<connector connectorId="connector1" layer="breadboardWire"><geometry x="0" y="0" />'
        '<connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard" /></connects></connector>'
        '</connectors></breadboardView>\n'
        '                </views>\n'
        '            </instance>\n'
        % (mi, mi, num(ax), num(ay), num(bx - ax), num(by - ay), color,
           a, BOARD_MI, b, BOARD_MI))


def main(argv):
    src, out = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")
    items = [(i, z.read(i.filename)) for i in z.infolist()]

    used = set()
    for m in re.finditer(r'<connect connectorId="(pin\d+[A-Z])"[^>]*layer="breadboardbreadboard"', text):
        used.add(m.group(1))
    print("已占用的孔：%d 个 ✓" % len(used))

    def free(col, rows, skip=()):
        for r in rows:
            h = "pin%d%s" % (col, r)
            if h not in used and h not in skip:
                return h
        return None

    # 桥 1：col16 上半 → col16 下半（跨中缝 ✓）
    a1 = free(16, UP)
    b1 = free(16, LO)
    # 桥 2：col16 下半 → col27 下半（`PD5/PD6` 那条 bus ✓）
    a2 = free(16, LO, skip=(b1,))
    b2 = free(27, LO, skip=(a1, b1))
    if not all((a1, b1, a2, b2)):
        raise SystemExit("找不到空闲孔 ✗：%s" % [(a1, b1, a2, b2)])
    print("桥 1：%s → %s（跨中缝 ✓）" % (a1, b1))
    print("桥 2：%s → %s（下半区 ✓）" % (a2, b2))

    add, back = "", []
    for i, (p, q) in enumerate(((a1, b1), (a2, b2))):
        mi = MI0 + i
        add += wire_block(mi, p, q, "#ef6100")
        back += [(p, mi), (q, mi)]

    host_end = text.rindex("</instances>")
    text = text[:host_end] + add + text[host_end:]
    # 孔上的**回指**（`<connect … layer="breadboardWire"/>` ✓ 与布线器写的一致 ✓）
    #   ★★ 实测两条 ✗：
    #     ① 板件里**只声明被用到的孔** ✗（没用到的孔没有 `<connector>` 元素 ✓）
    #        ⇒ 桥选的新孔**必须补一个整 `<connector>` 元素** ✓，不能只往 `<connects>` 里塞 ✗；
    #     ② 每个孔那段的换行/缩进不统一 ✗ ⇒ 用**定位插入**，别整段正则 ✗。
    bm = re.search(r'<instance [^>]*moduleIdRef="Breadboard-[^"]*"[^>]*>.*?</instance>', text, re.S)
    if not bm:
        raise SystemExit("找不到板件实例 ✗")
    bblk = bm.group(0)
    hv = re.search(r"<breadboardView[^>]*>.*?</breadboardView>", bblk, re.S)
    bv = hv.group(0)
    nv = bv
    for hole, mi in back:
        anchor = 'connectorId="%s" layer="breadboardbreadboard"' % hole
        if anchor in nv:
            i = nv.index(anchor)
            j = nv.index("<connects>", i) + len("<connects>")
            nv = (nv[:j] + '<connect connectorId="connector0" modelIndex="%d" layer="breadboardWire" />' % mi
                  + nv[j:])
        else:
            j = nv.rindex("</connectors>")
            nv = (nv[:j]
                  + '            <connector connectorId="%s" layer="breadboardbreadboard">'
                    '<geometry x="0" y="0" />'
                    '<connects><connect connectorId="connector0" modelIndex="%d" layer="breadboardWire" />'
                    '</connects></connector>\n        ' % (hole, mi)
                  + nv[j:])
            print("  ＋补板件里的孔声明 %s ✓" % hole)
    text = text.replace(bv, nv)

    # ★★ 2026-11-10 ✓：清掉**指向已删导线**的悬空声明 ✗
    #   `bb_probe` 报 `P:U1.connector20 → 90013134.connector0`（那条旧导线早被删了 ✗）
    #   ⇒ 这里把"目标 modelIndex 在文件里已不存在"的 `<connect … layer="breadboardWire"/>` 删掉 ✓
    ids = set(re.findall(r'<instance [^>]*modelIndex="(\d+)"', text))
    stale = [m.group(0) for m in re.finditer(
        r'<connect connectorId="[^"]*" modelIndex="(\d+)" layer="breadboardWire" />', text)
        if m.group(1) not in ids]
    for s in stale:
        text = text.replace(s, "")
    if stale:
        print("  清掉悬空声明 %d 条 ✓（指向已删导线 ✗）" % len(stale))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == name:
                data = text.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 写出 %s（补了 2 根线 ✓）" % out)
    return 0

sys.exit(main(sys.argv[1:]))
