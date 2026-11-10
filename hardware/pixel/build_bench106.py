# -*- coding: utf-8 -*-
r"""台架图第 2 版（以 **`pixel-pcb-v111.fzz` 的面包板视图**为基线 ✓）⇒ `pixel-breadboard106.fzz`

用法: py -3.13 -u build_bench106.py [--dry]

★ 为什么换基线 ✗（2026-11-10 用户定 ✓）：「我的实际板子跟它一样」✓ —— 实物台架 = v111 的面包板视图
  （830 孔板 ＋ 全部 v0.1.3 元件 ＋ `WCH-LinkE` ＋ 54 根跳线 ✓），`pixel-breadboard105.fzz`
  是拿 v43 时代的骨架拼的 ✗ ⇒ 作废 ✓。

**只做三件事** ✓（其余一字不动 ✓，`schematicView` / `pcbView` 完全保持 v111 ✓）：
1. `R5`（100 Ω）串进 LED 数据线：拆掉原来 `pin20A → 底部 → pin37A` 那三根链 ✗，
   改走 `pin20C`(PC6) → bus col20 → `pin20B`→`pin29B` → bus col29 → `R5` → bus col33 →
   `pin33B`→`pin37B` → bus col37 → `pin37E`(LED2.DI) ✓
2. `C3`（100 µF 电解，核心件）**转 90° 跨在顶部电源轨上**：`+`(connector1)→`Y`(5V)、
   `-`(connector0)→`Z`(GND) ✓ —— 两脚正好落在 `pin50Y` / `pin50Z` ✓，**不需要跳线** ✓
3. 孔位换算：`x = 9*col + 9`、`y = ROW_Y + 18`（= v111 这块板的实测偏移 ✓，拿 `R2`/`pin20A` 反推 ✓）
"""
import re
import sys
import zipfile

SRC = "pixel-pcb-v111.fzz"
OUT = "pixel-breadboard106.fzz"
FZ_NAME = "pixel-breadboard106.fz"

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
OX, OY = 9.0, 18.0          # ★ 板位偏移（实测 ✓）
BOARD_MI = "5785"

C_GND = "#404040"
C_5V = "#cc1414"
C_LED = "#25cc35"

# ── 拆掉的三根旧链（`PC6` → `DI` 直连 ✓）与要新增的两根跳线 ────────────────────
OLD_CHAIN = ("Wire90015728", "Wire90016069", "Wire90016068")
JUMPS = [("pin20B", "pin29B", C_LED),      # `LED_DIN`：col20 下半 ↔ col29 下半（`R5` 的 1 脚）
         ("pin33B", "pin37B", C_LED)]      # `LED_DIN_L`：col33 下半 ↔ col37 下半（`LED2.DI`）
#   ★ 为什么都走 **B 行**（`y=153`）✗：`A` 行要给 `R5` 的两只脚（`pin29A`/`pin33A`）✓；
#     而 `R5` 与跳线**不能共用同一颗孔**（规则 ①）✓ ⇒ 分成两行 ✓。

R5_HOLES = ("pin29A", "pin33A")
#   ★ 电源轨**不是每一列都有孔** ✗（实测 `breadboard2.fzp`：4 个一组、隔一列空 ✓，列 3..61 ✓）
#   ★ C3 放在**板子最左端** col3：机身朝板外挂 ✓（用户：探出板子边缘没关系 ✓），
#     而且 col3 的 `Z`/`Y` 两个轨孔都空着 ✓
C3_HOLES = ("pin3Z", "pin3Y")             # connector0(-)/connector1(+)
MI_R5 = 90018101
MI_C3 = 90018102
MI_W0 = 90018111


def hole_xy(h):
    m = re.fullmatch(r"pin(\d+)([A-Z])", h)
    return (int(m.group(1)) * 9.0 + OX, ROW_Y[m.group(2)] + OY)


def num(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


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


def r5_block():
    """`R5`：照 `R2` 的脚位模板（脚距 36 单位 = 4 列 ✓、无 transform ✓），只换位置/阻值 ✓。"""
    (x0, y0) = hole_xy(R5_HOLES[0])
    locx = x0 - (2.63167 - 1.29830)        # = 孔 x − 1 脚的局部净偏移 ✓
    locy = y0 - 4.5405
    return (
        '        <instance moduleIdRef="R0603_36137a0f26fc46e91e48eb74468f61a7_1-5BandResistorModuleID"'
        ' modelIndex="%d" path="C:/Users/shi.jinghai-honor/Documents/Fritzing/parts/user/'
        'R0603_36137a0f26fc46e91e48eb74468f61a7_1-5BandResistorModuleID.fzp">\n'
        '            <property name="tolerance" value="±1%%"/>\n'
        '            <property name="power" value="1/10W"/>\n'
        '            <property name="resistance" value="100"/>\n'
        '            <property name="pin spacing" value="400 mil"/>\n'
        '            <title>R5</title>\n'
        '            <views>\n'
        '                <breadboardView layer="breadboard">\n'
        '                    <geometry z="2.50196" x="%s" y="%s"/>\n'
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
        % (MI_R5, num(locx), num(locy), R5_HOLES[0], BOARD_MI, R5_HOLES[1], BOARD_MI))


def c3_block():
    """`C3`：核心件中等电解电容 ✓，**转 90°** 跨在 `Z`(GND) / `Y`(5V) 两条轨上 ✓。

    ★★ 2026-11-10 关键发现 ✓（用户报「C3 没插进孔里」后实测 ✓）：
      这份 core svg（100dpi 画的 ✓）里 ——
        · `connectorNpin` 矩形在 **(10.796, 52.401)**（脚位标记 ✓）
        · `connectorNleg` 是一条线 **(10.796, 59.901) → (10.796, 69.901)** ✓
      ⇒ **真正的插入点是引线末端 `y = 69.901`** ✓，比脚位标记再往下 **10 mm 制单位 = 宽 2.54 mm ✓**。
      上一版把**脚位标记**对到孔上 ✗ ⇒ 引线（也就是图上看得见的那两根灰粝）
      **整体多伸出 15.75 sketch 单位 ≈ 4.4 mm** ✗ → 看上去就是“搭在轨上、没插进去” ✗。
      ⇒ 现在把**引线末端**对到孔上 ✓（`69.901 × k(0.9) = 62.910864` ✓）。

    `k` 怎么来的 ✓：`width=0.31495in`、`viewBox` 宽 31.495 ⇒ k = 0.31495×25.4×3.5433 / 31.495 = **0.9** ✓
    （= 100 dpi 图 ÷ 90 dpi sketch ⇒ 0.9 ✓）。旋转 CCW 后两脚**纵向**差 `10 × 0.9 = 9` 单位
    = **一个孔距 2.54 mm** ✓，正好跨两条轨 ✓。
    """
    K = 0.9
    BODY_Y = 59.901 * K         # = 53.9109 ✓ 引线**靠本体那一端**（Fritzing 的 `<geometry>` 就是这个点 ✓）
    TIP_Y = 69.901 * K          # = 62.9109 ✓ 引线**末端**（真正插进孔里的那一点 ✓）
    LEG = 10.0 * K              # = 9.0 ✓ 引线长 10 个 100dpi 单位 = **2.54 mm** ✓
    PIN_X0 = 10.796 * K         # = 9.7164 ✓
    PIN_X1 = 20.796 * K         # = 18.7164 ✓
    x_tip, _ = hole_xy(C3_HOLES[0])
    y_gnd = ROW_Y[C3_HOLES[0][-1]] + OY
    y_5v = ROW_Y[C3_HOLES[1][-1]] + OY
    #   旋转 CCW = (m11,m12,m21,m22) = (0,1,-1,0) ⇒ x' = −y + m31、y' = x + m32 ✓
    #   ★ 让**引线末端**落在孔上 ✓（用户 2026-11-10：「C3 没有插入顶部两轨的孔里」✓）
    m31 = x_tip + TIP_Y                     # 两根引线的 x 相同 ✓
    m32 = y_gnd - PIN_X0                    # connector0(-) 落到 GND 轨 ✓
    assert abs((PIN_X1 + m32) - y_5v) < 1e-3, (PIN_X1 + m32, y_5v)
    return (
        '        <instance moduleIdRef="MediumElectrolyticCapacitorModuleID" modelIndex="%d"'
        ' path="C:/Users/shi.jinghai-honor/AppData/Local/Programs/Fritzing/fritzing-parts/core/'
        'capacitor_electrolytic_medium.fzp">\n'
        '            <property name="capacitance" value="100 µF"/>\n'
        '            <property name="voltage" value="10V"/>\n'
        '            <title>C3</title>\n'
        '            <views>\n'
        '                <breadboardView layer="breadboard">\n'
        '                    <geometry z="2.50196" x="0" y="0">\n'
        '                        <transform m11="0" m12="1" m13="0" m21="-1" m22="0" m23="0"'
        ' m31="%s" m32="%s" m33="1"/>\n'
        '                    </geometry>\n'
        '                    <connectors>\n'
        '                        <connector connectorId="connector0" layer="breadboard">\n'
        '                            <geometry x="%s" y="%s"/>\n'
        '                            <leg><point x="0" y="0"/><bezier/><point x="0" y="%s"/><bezier/></leg>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                        <connector connectorId="connector1" layer="breadboard">\n'
        '                            <geometry x="%s" y="%s"/>\n'
        '                            <leg><point x="0" y="0"/><bezier/><point x="0" y="%s"/><bezier/></leg>\n'
        '                            <connects><connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/></connects>\n'
        '                        </connector>\n'
        '                    </connectors>\n'
        '                </breadboardView>\n'
        '            </views>\n'
        '        </instance>\n'
        % (MI_C3, num(m31), num(m32),
           num(PIN_X0), num(BODY_Y), num(LEG), C3_HOLES[0], BOARD_MI,
           num(PIN_X1), num(BODY_Y), num(LEG), C3_HOLES[1], BOARD_MI))


def main(argv):
    dry = "--dry" in argv
    z = zipfile.ZipFile(SRC)
    items = [(i, z.read(i.filename)) for i in z.infolist()]
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")

    # ── 1. 拆旧链 ──────────────────────────────────────────────────────────
    gone = []
    for ttl in OLD_CHAIN:
        m = re.search(r'<instance [^>]*>\s*(?:<property[^/]*/>\s*)*<title>%s</title>' % ttl, text)
        if not m:
            raise SystemExit("找不到旧导线 %s ✗" % ttl)
        s = m.start()
        e = text.index("</instance>", s) + len("</instance>")
        blk = text[s:e]
        mi = re.search(r'modelIndex="(\d+)"', blk).group(1)
        gone.append((ttl, mi))
        text = text[:s] + text[e:]
    print("拆掉旧链 %d 根 ✓：%s" % (len(gone), ", ".join(t for t, _ in gone)))
    for ttl, mi in gone:
        n = len(re.findall(r'<connect [^>]*modelIndex="%s"[^>]*/>' % mi, text))
        text = re.sub(r'[ \t]*<connect [^>]*modelIndex="%s"[^>]*/>\n?' % mi, "", text)
        print("  清掉指向 %s 的声明 %d 条 ✓" % (ttl, n))

    # ── 2. 加件 ＋ 加线 ────────────────────────────────────────────────────
    add = r5_block() + c3_block()
    for i, (a, b, col) in enumerate(JUMPS):
        add += wire_block(MI_W0 + i, a, b, col)
    host_end = text.rindex("</instances>")
    text = text[:host_end] + add + text[host_end:]
    print("加 `R5`(%s→%s) ✓、`C3`(%s/%s) ✓、跳线 %d 根 ✓"
          % (R5_HOLES[0], R5_HOLES[1], C3_HOLES[0], C3_HOLES[1], len(JUMPS)))

    # ── 3. 板件里补"被线用到的孔"的回指 ✓（`add_rc_bridge` 同一套口径 ✓）──
    bm = re.search(r'<instance [^>]*moduleIdRef="Breadboard-[^"]*"[^>]*>.*?</instance>', text, re.S)
    bblk = bm.group(0)
    hv = re.search(r"<breadboardView[^>]*>.*?</breadboardView>", bblk, re.S)
    bv = hv.group(0)
    nv = bv
    for i, (a, b, _c) in enumerate(JUMPS):
        for hole in (a, b):
            mi = str(MI_W0 + i)
            anchor = 'connectorId="%s" layer="breadboardbreadboard"' % hole
            if anchor in nv:
                j = nv.index("<connects>", nv.index(anchor)) + len("<connects>")
                nv = nv[:j] + ('<connect connectorId="connector0" modelIndex="%s" layer="breadboardWire"/>' % mi) + nv[j:]
            else:
                j = nv.rindex("</connectors>")
                nv = (nv[:j]
                      + ('            <connector connectorId="%s" layer="breadboardbreadboard">'
                         '<geometry x="0" y="0"/><connects>'
                         '<connect connectorId="connector0" modelIndex="%s" layer="breadboardWire"/>'
                         '</connects></connector>\n        ' % (hole, mi))
                      + nv[j:])
                print("  ＋补板件孔声明 %s ✓" % hole)
    text = text.replace(bv, nv)

    # ── 4. 写盘 ────────────────────────────────────────────────────────────
    if dry:
        print("（--dry ⇒ 不写盘 ✓）")
        return 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            fn = info.filename
            if fn == name:
                fn, data = FZ_NAME, text.encode("utf-8")
            zi = zipfile.ZipInfo(fn, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 写出 %s（内部 .fz = %s ✓）" % (OUT, FZ_NAME))
    return 0


sys.exit(main(sys.argv[1:]))
