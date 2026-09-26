# -*- coding: utf-8 -*-
r"""把 U1 的裸焊盘 **EPAD（connector20）** 接到 **LED2 的 GND 脚**（原理图视图 ✓）

口径（2026-09-26 用户定 ✓）：
  · 「数据手册常说 EPAD 接 VSS」**只适用于 PCB** ✓ —— PCB 上焊盘就在芯片肚子底下，
    接邻近的 VSS 焊盘 / 地铜理所当然 ✓；
  · **原理图有自己的逻辑与美学** ✓（用户原话）：「独立成网 ⇒ 特意接到地」要**看得见** ——
    接到 U1 自己的 pin4（VSS）画出来像"芯片内部就连着" ✗，看不出 EPAD 特意去了地 ✗；
  · 所以接 **LED2 的 GND 脚**（脚名 = `GND` ✓，从**零件文件自己的脚名**读 ✓；
    它在 GND 网上 ✓，与 `U1.pin4` 之间本来就有导线 ✓）⇒ 一眼能看出 EPAD 走进了地网 ✓；
  · 面包板上同理走 **GND 电源轨** ✓ —— 那根线由 `bb_route4.py` 生成 ✓，不在本脚本管 ✗。

幂等 ✓：已接在 LED2 的 GND ⇒ 跳过 ✓；接在**别处**（如 U1.pin4）⇒ **自动改接** ✓（拆旧 + 接新 ✓）。

用法：py -3.13 fix_epad_ground.py <sketch.fzz> <输出.fzz>

脚位置来源：仓里的标定表 `pins_calibrated.py` ✓（由 `recal_pins.py` 从 Fritzing 自己的
渲染反推 ✓，单位已是 sketch ✓）—— 且**与文件里已有导线的端点互校** ✓（对不上就不写文件 ✓）。
"""
import copy
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

# ★★ 2026-09-27 入库 ✓：**本地这份优先** ✓（从前元件的工具仓被插在最前 ✗ ⇒ 跨仓依赖 ✗）
sys.path.insert(0, r"f:\git\fritzing-parts-langhua\tools")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import part_measure as pm                        # noqa: E402
from pin_ruler import apply, mul, parse_tf        # noqa: E402


def tf_of(geom):
    """实例 geometry 的 <transform m11…m32> → 2×3 矩阵（没有 ⇒ 单位阵 ✓）

    （不引仓外的模块 ✓ —— AGENTS §5：项目脚本不得依赖仓外文件 ✓）
    """
    t = child(geom, "transform")
    if t is None:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    g = lambda k, d: float(t.get(k) or d)         # noqa: E731
    return (g("m11", 1), g("m12", 0), g("m21", 0), g("m22", 1), g("m31", 0), g("m32", 0))

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0, "X": 171.0, "W": 180.0}


def hole_xy(hid):
    m = re.fullmatch(r"pin(\d+)([A-Z])", hid or "")
    return None if not m or m.group(2) not in ROW_Y \
        else (int(m.group(1)) * 9.0, ROW_Y[m.group(2)])

SCALE = 11.111096                 # 导出单位 / sketch 单位（生成器拟合值 ✓，只需比例 ✓）
GND, EPAD = "connector3", "connector20"          # U1 的 VSS 脚（pin4）/ U1 的裸焊盘
LED_TITLE = "LED2"                # 接地目标所在的元件 ✓（它的脚名里有 GND ✓）
GND_NAMES = ("GND", "VSS")        # 脚名含这些 = 地脚 ✓


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def schematic_connectors(inst):
    sub = child(child(inst, "views"), "schematicView")
    return sub, (child(sub, "connectors") if sub is not None else None)


def ruler_pins(svg_path):
    """partID -> {origin, pins{connectorN: (x, y)}}（导出坐标 ✓）"""
    root = ET.parse(svg_path).getroot()
    out = {}

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("partID"):
            pid = el.get("partID")
            out.setdefault(pid, {"pins": {}})
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm and pid in out and el.get("x") is not None:
            out[pid]["pins"].setdefault("connector" + mm.group(1),
                                        apply(m2, float(el.get("x")), float(el.get("y"))))
        for c in el:
            walk(c, m2, pid)

    walk(root, (1, 0, 0, 1, 0, 0), None)
    return out


def main(argv):
    # ★ 只吃两个参数 ✓：脚位置改从仓里的 `pins_calibrated.py` 读 ✓
    #   （以前要一个 Fritzing 导出的尺子 svg ✗ —— 实测那个文件还可能不是合法 XML ✗）
    fzz, out = argv[0], argv[-1]
    if len(argv) > 2:
        print("（第三个参数 %s 不再需要 ✓ 脚位置改用 pins_calibrated.py ✓）" % argv[1])
    z = zipfile.ZipFile(fzz)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(name))
    host = child(sroot, "instances") or sroot

    u1 = next(e for e in sroot.iter("instance")
              if (e.findtext("title") or "").strip() == "U1")
    umi = u1.get("modelIndex")
    sub, cbox = schematic_connectors(u1)

    # ── LED2 的"地脚"是哪个 connector？从**零件文件自己的脚名**读（不猜 ✓）────
    led = next(e for e in sroot.iter("instance")
               if (e.findtext("title") or "").strip() == LED_TITLE)
    led_mi = led.get("modelIndex")
    pnames = {}
    _want = os.path.basename((led.get("path") or "").replace("/", os.sep))
    for n2 in z.namelist():
        # ★ fzz 里存的是 `part.<名字>.fzp` ✓，而实例的 path 写的是 Fritzing 安装/用户目录里的
        #   `<名字>.fzp` ✗ ⇒ 按**后缀**认（实测踩过 ✓）
        if not n2.endswith(".fzp") or not _want or not n2.endswith(_want):
            continue
        for c2 in ET.fromstring(z.read(n2)).iter("connector"):
            pnames[c2.get("id")] = (c2.get("name") or "").upper()
    led_gnd = next((cid for cid, nm in sorted(pnames.items()) if nm in GND_NAMES), None)
    if led_gnd is None:
        raise SystemExit("✗ 从零件文件里读不到 %s 的地脚 ✗（零件: %s）"
                         % (LED_TITLE, led.get("path")))
    print("%s 的地脚 = %s（脚名 %s ✓，来源：零件文件 %s）"
          % (LED_TITLE, led_gnd, pnames[led_gnd], _want))

    # ── 幂等 / 改接：EPAD 现在连在哪？───────────────────────────────
    def connects_of(cid):
        con = next((c for c in (cbox if cbox is not None else [])
                    if c.get("connectorId") == cid), None)
        return child(con, "connects") if con is not None else None

    stale = []
    for c in (connects_of(EPAD) if connects_of(EPAD) is not None else []):
        if tag(c) != "connect" or (c.get("layer") or "") not in ("schematic", "schematicTrace"):
            continue
        if c.get("modelIndex") == led_mi and c.get("connectorId") == led_gnd:
            print("EPAD 已经接在 %s 的 %s 上 ⇒ 跳过 ✓" % (LED_TITLE, led_gnd))
            return 0
        stale.append(c.get("modelIndex"))
    if stale:
        print("EPAD 原来接在别处（旧导线 %s）⇒ 拆掉、改接到 %s.%s ✓"
              % (", ".join(stale), LED_TITLE, led_gnd))

    # ── U1 的 GND 脚 sketch 坐标：从**已有导线**读（两根线交汇处 ✓）──────────
    hits = []
    for e in sroot.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        s2, c2 = schematic_connectors(e)
        if s2 is None:
            continue
        for cs in s2.iter():
            if tag(cs) != "connect":
                continue
            if cs.get("modelIndex") == umi and cs.get("connectorId") == GND \
                    and (cs.get("layer") or "") in ("schematic", "schematicTrace"):
                g = child(s2, "geometry")
                p0 = (pm.num(g.get("x")), pm.num(g.get("y")))
                p1 = (p0[0] + pm.num(g.get("x2")), p0[1] + pm.num(g.get("y2")))
                hits.append((e.get("modelIndex"), p0, p1))
    if len(hits) < 2:
        raise SystemExit("✗ 找不到 U1 的 GND 脚位置（需要两根已连到它的线）✗")
    # 两根线各自的一个端点 = 同一个点 ⇒ 取出现两次的那个端点 ✓
    ends = [p for _mi, p0, p1 in hits for p in (p0, p1)]
    gnd_pt = max(ends, key=lambda p: ends.count(p))
    print("U1 的 GND 脚（从已有导线读出）: (%.3f, %.3f)（%d 根线交汇 ✓）"
          % (gnd_pt[0], gnd_pt[1], ends.count(gnd_pt)))

    # ── 脚位置：用仓里的标定表 `pins_calibrated.py`（由 recal_pins.py 从 Fritzing
    #    自己的渲染反推 ✓；单位就是 sketch ✓、脚距正好 9.0 = 2.54mm ✓）──────────
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pins_calibrated as cal                                    # noqa: E402
    if umi not in cal.PINS or led_mi not in cal.PINS:
        raise SystemExit("✗ 标定表里没有 U1(%s) / %s(%s) ✗" % (umi, LED_TITLE, led_mi))
    if EPAD not in cal.PINS[umi] or GND not in cal.PINS[umi]:
        raise SystemExit("✗ 标定表里缺 %s / %s ✗" % (EPAD, GND))
    if led_gnd not in cal.PINS[led_mi]:
        raise SystemExit("✗ 标定表里缺 %s.%s ✗" % (LED_TITLE, led_gnd))
    # ★ 标定表可能**过期** ✗（实测：LED2 被垂直挪过 27.6 单位 ⇒ 表里还是老位置 ✗，
    #   而 U1 没动 ✓）⇒ 口径：
    #     · U1 那两个脚**用表的相对量**（EPAD = U1.pin4 + 表内偏移 ✓，抗挪动 ✓）；
    #     · 目标点（LED2.GND）**以文件里已有的导线为准** ✓（那是当前布局的真相 ✓）；
    #     · 表与文件差多少**照实报** ✓，不硬凑 ✗。
    dx = cal.PINS[umi][EPAD][0] - cal.PINS[umi][GND][0]
    dy = cal.PINS[umi][EPAD][1] - cal.PINS[umi][GND][1]
    epad_pt = (gnd_pt[0] + dx, gnd_pt[1] + dy)
    print("标定表（pins_calibrated.py）：U1 的 EPAD − pin4 = (%.3f, %.3f) ⇒ EPAD=(%.3f,%.3f)"
          % (dx, dy, epad_pt[0], epad_pt[1]))
    # 自证 ①：标定表里的 U1 地脚 与 **从文件导线读出的** 那个点必须一致 ✓
    d0 = ((cal.PINS[umi][GND][0] - gnd_pt[0]) ** 2
          + (cal.PINS[umi][GND][1] - gnd_pt[1]) ** 2) ** 0.5
    print("   自证①：标定表 U1.%s 与文件导线交汇点差 %.4f 单位 %s"
          % (GND, d0, "✓" if d0 < 0.05 else "✗"))
    if d0 >= 0.05:
        raise SystemExit("✗ 标定表与文件对不上（差 %.4f）⇒ 不写文件 ✗" % d0)
    # 自证 ②：文件里已有"接在 %s.%s 上的导线" ⇒ 它那个端点就是目标点 ✓
    chk = []
    for e in sroot.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        s2 = child(child(e, "views"), "schematicView")
        if s2 is None or e.get("modelIndex") in stale:
            continue
        if not any(tag(cs) == "connect" and cs.get("modelIndex") == led_mi
                   and cs.get("connectorId") == led_gnd for cs in s2.iter()):
            continue
        g2 = child(s2, "geometry")
        p0 = (pm.num(g2.get("x")), pm.num(g2.get("y")))
        p1 = (p0[0] + pm.num(g2.get("x2")), p0[1] + pm.num(g2.get("y2")))
        chk += [p for p in (p0, p1)
                if abs(p[0] - gnd_pt[0]) > 1e-6 or abs(p[1] - gnd_pt[1]) > 1e-6]
    if not chk:
        raise SystemExit("✗ 文件里找不到接在 %s.%s 上的导线 ⇒ 定位不了目标点 ✗"
                         % (LED_TITLE, led_gnd))
    led_pt = chk[0]
    d2 = ((cal.PINS[led_mi][led_gnd][0] - led_pt[0]) ** 2
          + (cal.PINS[led_mi][led_gnd][1] - led_pt[1]) ** 2) ** 0.5
    print("   自证②：目标点取自**文件里那条线**的端点 (%.3f,%.3f)；标定表写的是 "
          "(%.3f,%.3f) ⇒ 差 %.4f 单位（表过期就直接采用文件值 ✓）"
          % (led_pt[0], led_pt[1], cal.PINS[led_mi][led_gnd][0],
             cal.PINS[led_mi][led_gnd][1], d2))

    # ── 选一条不压别的导线的走法（先直线 ✓，再两段 L ✓）────────────────────
    def seg_pts(p, q):
        return [(p[0], p[1]), (q[0], q[1])]

    def seg_intersect(p1, q1, p2, q2):
        def o(a, b, c):
            v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
        return o(p2, q2, p1) * o(p2, q2, q1) < 0 and o(p1, q1, p2) * o(p1, q1, q2) < 0

    others = []
    for e in sroot.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        if e.get("modelIndex") in stale:            # 马上要拆掉的旧线 ✓ 不算障碍
            continue
        vw2 = child(e, "views")
        if child(vw2, "breadboardView") is not None:
            continue      # 带面包板视图的杂线（画布里的残留 ✗）不是原理图导线 ✓
        s2 = child(vw2, "schematicView")
        if s2 is None:
            continue
        g = child(s2, "geometry")
        p0 = (pm.num(g.get("x")), pm.num(g.get("y")))
        others.append((p0, (p0[0] + pm.num(g.get("x2")), p0[1] + pm.num(g.get("y2")))))
    print("已有原理图导线 %d 根（用来挑不打架的走法 ✓）" % len(others))

    def bad(path):
        segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        for a, b in segs:
            for c, d in others:
                if seg_intersect(a, b, c, d):
                    return True
            for e in sroot.iter("instance"):
                pass
        return False

    def path_len(path):
        return sum(((path[i + 1][0] - path[i][0]) ** 2
                    + (path[i + 1][1] - path[i][1]) ** 2) ** 0.5 for i in range(len(path) - 1))

    def crossings(path):
        segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        return sum(1 for a, b in segs for c, d in others if seg_intersect(a, b, c, d))

    # ★ 挑走法：**交叉最少**优先 ✓、再看长度 ✓（用户在意原理图的美学 ✓ ——
    #   所以不是"第一条不打架的就算" ✗，而是所有候选一起比 ✓）
    mid_x = (epad_pt[0] + led_pt[0]) / 2.0
    cands = [seg_pts(epad_pt, led_pt),
             [epad_pt, (epad_pt[0], led_pt[1]), led_pt],
             [epad_pt, (led_pt[0], epad_pt[1]), led_pt]]
    for o in (9.0, 18.0, 27.0, 36.0, -9.0, -18.0, -27.0, -36.0):
        cands.append([epad_pt, (mid_x, epad_pt[1] + o), (mid_x, led_pt[1] + o), led_pt])
    cands.append([epad_pt, (epad_pt[0], epad_pt[1] - 9.0),
                  (led_pt[0], epad_pt[1] - 9.0), led_pt])          # 从上方绕过
    path = min(cands, key=lambda c: (crossings(c), path_len(c)))
    print("走法（交叉 %d 处、长 %.2f）: %s"
          % (crossings(path), path_len(path), " → ".join("(%.2f,%.2f)" % p for p in path)))
    if crossings(path):
        print("   [!] 这个位置躲不开交叉 ⇒ 已取最少的那条 ✓（若要 0 交叉，得先与用户对布局 ✓）")

    # ── 写：照抄已有原理图导线的字段（layer / flags / mils / color ✓）──────
    # ★ 这一段是**直的导线**（一个 Wire 实例一段 ✓）；折线就是**多段串起来** ✓ ——
    #   本文件里已有的原理图导线就是这么存的 ✓（实测：`Wire90012756 ↔ Wire90012757` ✓、
    #   每根 geometry 只有两个端点 ✓、段间用 `layer="schematicTrace"` 相连 ✓）。
    #   ✗ 反面教训：以前把 3 个点的折线塞进**一个** geometry ✗ ⇒ 中间两个拐点**全丢了** ✗，
    #   在 Fritzing 里会渲染成一条直线 ✗。
    tmpl = next(e for e in sroot.iter("instance")
                if (e.get("moduleIdRef") or "").startswith("Wire")
                and child(child(e, "views"), "schematicView") is not None)
    base = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1
    made = []
    for k in range(len(path) - 1):
        mi_k = base + k
        e = copy.deepcopy(tmpl)
        e.set("modelIndex", str(mi_k))
        t = child(e, "title")
        if t is not None:
            t.text = "Wire%d" % mi_k
        vw = child(e, "views")
        for s2 in list(vw):
            if tag(s2) != "schematicView":
                vw.remove(s2)
        s2 = child(vw, "schematicView")
        s2.set("layer", "schematicTrace")
        g = child(s2, "geometry")
        g.attrib.update({"x": "%.4f" % path[k][0], "y": "%.4f" % path[k][1],
                         "x1": "0", "y1": "0",
                         "x2": "%.4f" % (path[k + 1][0] - path[k][0]),
                         "y2": "%.4f" % (path[k + 1][1] - path[k][1]),
                         "wireFlags": "128"})
        we = child(s2, "wireExtras")
        if we is None:
            we = ET.SubElement(s2, "wireExtras")
        we.attrib.update({"mils": "9.7222", "color": "#404040", "opacity": "1", "banded": "0"})
        vb = child(s2, "connectors")
        if vb is not None:
            s2.remove(vb)
        vb = ET.SubElement(s2, "connectors")
        for cid in ("connector0", "connector1"):
            con = ET.SubElement(vb, "connector", {"connectorId": cid,
                                                  "layer": "schematicTrace"})
            ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
            ET.SubElement(con, "connects")
        host.append(e)
        made.append((e, mi_k))

    def wire_connect(e2, cid, peer_cid, peer_mi, layer):
        vb2 = child(child(child(e2, "views"), "schematicView"), "connectors")
        con = next(c for c in vb2 if c.get("connectorId") == cid)
        ET.SubElement(child(con, "connects"), "connect",
                      {"connectorId": peer_cid, "modelIndex": str(peer_mi), "layer": layer})

    for k in range(len(made) - 1):                     # 段与段串起来 ✓
        wire_connect(made[k][0], "connector1", "connector0", made[k + 1][1], "schematicTrace")
        wire_connect(made[k + 1][0], "connector0", "connector1", made[k][1], "schematicTrace")
    wire_connect(made[0][0], "connector0", EPAD, umi, "schematic")            # 焊盘那端 ✓
    wire_connect(made[-1][0], "connector1", led_gnd, led_mi, "schematic")     # LED2.GND 那端 ✓

    # 两端反向登记 ✓（U1 的 EPAD 原本**没有任何连接** ⇒ 按需新建 ✓）
    for inst2, ttl2, cid, wcid, wmi in ((u1, "U1", EPAD, "connector0", made[0][1]),
                                        (led, LED_TITLE, led_gnd, "connector1", made[-1][1])):
        sub2 = child(child(inst2, "views"), "schematicView")
        cbox2 = child(sub2, "connectors")
        if cbox2 is None:
            cbox2 = ET.SubElement(sub2, "connectors")
        con = next((c for c in cbox2 if c.get("connectorId") == cid), None)
        if con is None:
            con = ET.SubElement(cbox2, "connector", {"connectorId": cid, "layer": "schematic"})
            ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
            print("   （%s 的 %s 原本没有连接记录 ⇒ 新建 ✓）" % (ttl2, cid))
        cs = child(con, "connects")
        if cs is None:
            cs = ET.SubElement(con, "connects")
        ET.SubElement(cs, "connect", {"connectorId": wcid, "modelIndex": str(wmi),
                                      "layer": "schematicTrace"})

    # 拆掉旧线（EPAD 原来接在别处的那些 ✗）：连线本体 + 两端反向登记 ✓
    for e2 in list(sroot.iter("instance")):
        if e2.get("modelIndex") not in stale:
            continue
        for cs in list(sroot.iter("connects")):
            for k in list(cs):
                if k.get("modelIndex") == e2.get("modelIndex"):
                    cs.remove(k)
        host.remove(e2)
        print("   已拆旧导线 Wire%s ✓" % e2.get("modelIndex"))

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n == name else z.read(n))
    print("写入: %s（新增 %d 段原理图导线 Wire%s：EPAD → %s.%s ✓）"
          % (out, len(made), "+".join(str(m) for _e, m in made), LED_TITLE, led_gnd))
    return 0


def main_breadboard(fzz, out):
    r"""已废弃 ✗（2026-09-26 起）：面包板上那根线改由 `f:\git\_scratch\bb_route4.py` 生成 ✓
    —— 它把"接地"和"布线"当同一件事算（避让 / 交叉 / 遮挡 / 抽出重排 ✓），
    而这里的旧写法是"直接接到 U1 自己的 GND 脚" ✗ —— **口径已废** ✗（见文件头 ✓）。
    保留函数名只为把 `--bb` 拦下来并说清楚 ✓；下面那段旧代码**不再使用** ✗。
    """
    raise SystemExit("✗ 面包板那根线现在由 bb_route4.py 生成（走 GND 电源轨 ✓）；"
                     "本脚本只管原理图 ✓")
    z = zipfile.ZipFile(fzz)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(name))
    host = child(sroot, "instances") or sroot
    u1 = next(e for e in sroot.iter("instance")
              if (e.findtext("title") or "").strip() == "U1")
    umi = u1.get("modelIndex")
    bb = child(child(u1, "views"), "breadboardView")
    cbox = child(bb, "connectors")
    # 幂等：EPAD 已经连了？
    con20 = next((c for c in (cbox if cbox is not None else [])
                  if c.get("connectorId") == EPAD), None)
    for cs in (child(con20, "connects") if con20 is not None else []) or []:
        if tag(cs) == "connect" and (cs.get("modelIndex") or "").startswith("9001"):
            print("面包板：EPAD 已经接上了（%s@%s）⇒ 跳过 ✓"
                  % (cs.get("connectorId"), cs.get("modelIndex")))
            return 0
    # GND 脚所在孔（元素里读到 ✓，不猜 ✓）
    gnd_hole = None
    for c in (cbox if cbox is not None else []):
        if c.get("connectorId") != GND:
            continue
        for cs in (child(c, "connects") if child(c, "connects") is not None else []):
            if (cs.get("layer") or "") == "breadboardbreadboard":
                gnd_hole = cs.get("connectorId")
    if gnd_hole is None:
        raise SystemExit("✗ U1 的 GND 脚没插在孔上 ⇒ 得先插孔 ✗")
    gnd_pt = hole_xy(gnd_hole)
    # EPAD 焊盘的 sketch 坐标：实例矩阵搬一下（不猜 ✓）
    fpz = (u1.get("path") or "").replace("/", os.sep)
    lay = ET.parse(fpz).getroot().find(".//breadboardView/layers")
    svg = None
    base = os.path.dirname(os.path.dirname(fpz))
    for s in ("", "core", "contrib", "user"):
        c2 = os.path.normpath(os.path.join(base, "svg", s,
                                          (lay.get("image") or "").replace("/", os.sep)))
        if os.path.isfile(c2):
            svg = c2
            break
    t = open(svg, encoding="utf-8").read()
    m = re.search(r'<circle[^>]*id="%spin"[^>]*cx="([\d.]+)"[^>]*cy="([\d.]+)"' % EPAD, t)
    if not m:
        raise SystemExit("✗ 面包板 svg 里找不到 %s 焊盘 ✗" % EPAD)
    k = 0.09                                  # 用户单位 → sketch（12.70mm / 500 用户单位 ✓）
    local = (float(m.group(1)) * k, float(m.group(2)) * k)
    g = child(bb, "geometry")
    mm = tf_of(g)
    px, py = apply(mm, local[0], local[1])
    epad_pt = (pm.num(g.get("x")) + px, pm.num(g.get("y")) + py)
    print("面包板：EPAD 焊盘 (%.2f,%.2f)；U1 的 GND 脚（孔 %s）(%s,%s)"
          % (epad_pt[0], epad_pt[1], gnd_hole, gnd_pt[0], gnd_pt[1]))
    tmpl = next(e for e in sroot.iter("instance")
                if (e.get("moduleIdRef") or "").startswith("Wire")
                and child(child(e, "views"), "breadboardView") is not None)
    mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", str(mi))
    tt = child(e, "title")
    if tt is not None:
        tt.text = "Wire%d" % mi
    vw = child(e, "views")
    for s2 in list(vw):
        if tag(s2) != "breadboardView":
            vw.remove(s2)
    s2 = child(vw, "breadboardView")
    s2.set("layer", "breadboardWire")
    g2 = child(s2, "geometry")
    g2.attrib.update({"x": "%.4f" % epad_pt[0], "y": "%.4f" % epad_pt[1],
                      "x1": "0", "y1": "0",
                      "x2": "%.4f" % (gnd_pt[0] - epad_pt[0]),
                      "y2": "%.4f" % (gnd_pt[1] - epad_pt[1]), "wireFlags": "64"})
    we = child(s2, "wireExtras")
    if we is None:
        we = ET.SubElement(s2, "wireExtras")
    we.attrib.update({"mils": "22.2222", "color": "#000000", "opacity": "1", "banded": "0"})
    vb = child(s2, "connectors")
    if vb is not None:
        s2.remove(vb)
    vb = ET.SubElement(s2, "connectors")
    for cid, target in (("connector0", EPAD), ("connector1", GND)):
        con = ET.SubElement(vb, "connector", {"connectorId": cid, "layer": "breadboardWire"})
        ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
        ET.SubElement(ET.SubElement(con, "connects"), "connect",
                      {"connectorId": target, "modelIndex": umi, "layer": "breadboard"})
    for cid, wcid in ((EPAD, "connector0"), (GND, "connector1")):
        con = next((c for c in (cbox if cbox is not None else [])
                    if c.get("connectorId") == cid), None)
        if con is None:
            con = ET.SubElement(cbox, "connector", {"connectorId": cid, "layer": "breadboard"})
            ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
            print("   （U1 面包板视图的 %s 原本没记录 ⇒ 新建 ✓）" % cid)
        cs = child(con, "connects")
        if cs is None:
            cs = ET.SubElement(con, "connects")
        ET.SubElement(cs, "connect", {"connectorId": wcid, "modelIndex": str(mi),
                                      "layer": "breadboardWire"})
    host.append(e)
    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n == name else z.read(n))
    print("写入: %s（新增 1 根面包板导线 Wire%d：EPAD 焊盘 → U1 的 GND 脚 ✓）" % (out, mi))
    return 0


if __name__ == "__main__":
    # 原理图：py -3.13 fix_epad_ground.py <sketch.fzz> <ruler.svg> <out.fzz>
    if len(sys.argv) > 1 and sys.argv[1] == "--bb":
        print("✗ 面包板那根线改由 bb_route4.py 生成（走 GND 电源轨 ✓）✓")
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
