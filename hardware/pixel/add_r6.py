# -*- coding: utf-8 -*-
r"""给台架图加 `R6` = **1 MΩ 泄放电阻**（`BR+` → `GND`）✓

用法: py -3.13 -u add_r6.py <in.fzz> <out.fzz>

**为什么要它** ✗（2026-11-10 实测 ✓，见 `data-acquisition.md` §10.10）：
`BR+`（`D3` 两阴极 ＋ `R1` 上端）对地**没有直流通路**（`D3` 反偏、`C1` 隔直）
⇒ 电平由泄漏平衡决定 ⇒ 无信号时读数在 0.1–0.5 V 之间**分钟级漂移**
⇒ 灯在「浅蓝 ↔ 绿」之间自己跳 ✗。加 1 MΩ 到地 ⇒ `50 nA × 1 MΩ = 50 mV` ⇒ 稳定在暖白区 ✓。

**摆法**（不碰任何已用孔 ✓）：
```
col13 上半 bus = BR+（D3 在 pin13F、R1 在 pin13H）
   └─ 跳线 pin13G → pin15G（同一行，2 列，col14 那格空着 ✓）
        └─ col15 上半 bus ← R6 上脚 pin15J
             └─ R6 下脚 pin15Z = **Z 轨 = GND** ✓（竖放，两脚正好 36 单位 = 4 行 ✓）
```
★ 不竖放在 col13 的原因 ✗：本体 10.9 mm（≈38.6 单位）会**盖住 `pin13H`**（`R1` 的脚）✗
⇒ 按"本体不许遮住已用的孔"的规则，挪到旁边空列 ✓。
"""
import re
import sys
import zipfile

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
OX, OY = 9.0, 18.0                      # v111 这块板的实测偏移 ✓
BOARD_MI = "5785"
MODULE = "R0603_36137a0f26fc46e91e48eb74468f61a7_1-5BandResistorModuleID"
MI_R6 = 90018121
MI_W = 90018131
COL_R6 = 15                             # R6 所在列 ✓
JMP = ("pin13G", "pin15G")              # BR+ bus → R6 所在的 bus ✓
C_BR = "#ab58a2"                        # 官方配色表里 BR+ 的紫 ✓
R_HOLES = ("pin15J", "pin15Z")          # 上脚(经跳线到 BR+) / 下脚(GND 轨) ✓


def num(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


def hole_xy(h):
    m = re.fullmatch(r"pin(\d+)([A-Z])", h)
    return (int(m.group(1)) * 9.0 + OX, ROW_Y[m.group(2)] + OY)


def r6_block():
    """0603 竖放（`m11=0 m12=-1 m21=1 m22=0` ⇒ 引脚沿 y 排开 ✓），两脚正好落孔 ✓"""
    #   局部引脚（= `<geometry>` ＋ `<leg>` 末点，与 R2 同一套模板 ✓）
    p0 = (2.63167 - 1.29830, 4.5405)      # (1.33337, 4.5405)
    p1 = (36.0026 + 1.33070, 4.5405)      # (37.33330, 4.5405)
    x0, _ = hole_xy(R_HOLES[0])
    y_top = ROW_Y[R_HOLES[0][-1]] + OY     # pin15J = 63
    y_bot = ROW_Y[R_HOLES[1][-1]] + OY     # pin15Z = 27
    #   x' =  y + m31 ；y' = -x + m32  ⇒  两个脚 x 相同 ✓、y 相差 36 ✓
    m31 = x0 - p0[1]
    m32 = y_top + p0[0]
    assert abs((-p1[0] + m32) - y_bot) < 1e-3, (m32, y_bot)
    return (
        '        <instance moduleIdRef="%s" modelIndex="%d"'
        ' path="C:/Users/shi.jinghai-honor/Documents/Fritzing/parts/user/%s.fzp">\n'
        '            <property name="tolerance" value="±1%%"/>\n'
        '            <property name="power" value="1/10W"/>\n'
        '            <property name="resistance" value="1M"/>\n'
        '            <property name="pin spacing" value="400 mil"/>\n'
        '            <title>R6</title>\n'
        '            <views>\n'
        '                <breadboardView layer="breadboard">\n'
        '                    <geometry z="2.50196" x="0" y="0">\n'
        '                        <transform m11="0" m12="-1" m13="0" m21="1" m22="0" m23="0"'
        ' m31="%s" m32="%s" m33="1"/>\n'
        '                    </geometry>\n'
        '                    <connectors>\n'
        '                        <connector connectorId="connector0" layer="breadboard">\n'
        '                            <geometry x="2.63167" y="4.5405"/>\n'
        '                            <leg><point x="0" y="0"/><bezier/><point x="-1.2983" y="0"/><bezier/></leg>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                        <connector connectorId="connector1" layer="breadboard">\n'
        '                            <geometry x="36.0026" y="4.5405"/>\n'
        '                            <leg><point x="0" y="0"/><bezier/><point x="1.3307" y="0"/><bezier/></leg>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                    </connectors>\n'
        '                </breadboardView>\n'
        '            </views>\n'
        '        </instance>\n'
        % (MODULE, MI_R6, MODULE, num(m31), num(m32),
           R_HOLES[0], BOARD_MI, R_HOLES[1], BOARD_MI))


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


def main(argv):
    src, out = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    items = [(i, z.read(i.filename)) for i in z.infolist()]
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")
    if "<title>R6</title>" in text:
        raise SystemExit("这张图里已经有 R6 了 ✗（不重复加 ✓）")

    add = r6_block() + wire_block(MI_W, JMP[0], JMP[1], C_BR)
    i = text.rindex("</instances>")
    text = text[:i] + add + text[i:]

    # 板件里补"被线用到的那颗孔"的回指（与 add_rc_bridge / bb_route4 同一套口径 ✓）
    bm = re.search(r'<instance [^>]*moduleIdRef="Breadboard-[^"]*"[^>]*>.*?</instance>', text, re.S)
    bblk = bm.group(0)
    hv = re.search(r"<breadboardView[^>]*>.*?</breadboardView>", bblk, re.S)
    bv = hv.group(0)
    nv = bv
    for hole in JMP:
        anchor = 'connectorId="%s" layer="breadboardbreadboard"' % hole
        if anchor in nv:
            j = nv.index("<connects>", nv.index(anchor)) + len("<connects>")
            nv = nv[:j] + ('<connect connectorId="connector0" modelIndex="%d" layer="breadboardWire"/>' % MI_W) + nv[j:]
        else:
            j = nv.rindex("</connectors>")
            nv = (nv[:j]
                  + ('            <connector connectorId="%s" layer="breadboardbreadboard">'
                     '<geometry x="0" y="0"/><connects>'
                     '<connect connectorId="connector0" modelIndex="%d" layer="breadboardWire"/>'
                     '</connects></connector>\n        ' % (hole, MI_W))
                  + nv[j:])
            print("  ＋补板件孔声明 %s ✓" % hole)
    text = text.replace(bv, nv)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == name:
                data = text.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 加 R6（1 MΩ，col%d：%s→%s）＋跳线 %s→%s ⇒ 写出 %s"
          % (COL_R6, R_HOLES[0], R_HOLES[1], JMP[0], JMP[1], out))
    return 0


sys.exit(main(sys.argv[1:]))
