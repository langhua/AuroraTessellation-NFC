# -*- coding: utf-8 -*-
r"""像素板原理图 **v3：数据驱动摆位**（本体居中 + 相邻脚同高 + 紧凑 ✓）

★ 为什么要重做（v1 的错 ✗，2026-09-27 用户的眼睛 + 指标一起发现的 ✓）：
  v1 是"**拍**一组坐标" ✗ —— 我当时**不赌**各件符号原点居不居中 ✗，于是给了一堆
  宽松的整数坐标 ✓。后果（v2 渲染出来才看见 ✓）：
    · 主链各件的**本体**高低不齐 ✗（锚点在一条线上 ✗，本体各挂各的 ✗）；
    · 块间空得太大 ✗、块内不紧凑 ✗；
    · 量化：**十字交叉 12 处** ✓、**导线穿别的元件本体 10 段** ✓、总长 4229.5 单位 ✓。

★ 这一版的口径（全部**从数据算** ✓，没有手拍的魔数 ✓）：
  零件几何由 `render_sch.py --pins-out` 给出 ✓（**同一个模型** ✓，已对 Fritzing 导出
  逐点验平 Δ≤0.0004 单位 ✓）：
      PINS[mi][cid] = (dx, dy)   各脚相对**零件锚点** ✓
      BOX[mi]       = (x0,y0,x1,y1)  本体框（含引脚线 ✓）相对锚点 ✓
  规则（每条都能说出"让哪两个脚同高" ✓）：
    ① **主链 `J1→U1→LED2→J2` 的本体框中心**都落在主链行 `Y0` ✓（先定高 ✓）；
    ② **相邻本体框**水平间隙 = `GAP_X` ✓（紧凑 ✓）；
    ③ `J1.c2`（DATA_IN ✓）与 `U1.c2`（PA2 ✓）**同高** ✓ ⇒ 这根信号线是**直的** ✓；
    ④ `LED2.c2`（DI ✓）与 `U1.c12`（PC6 ✓）同高 ✓；`J2.c2`（DATA_OUT ✓）与 `U1.c4`（PD0 ✓）同高 ✓；
    ⑤ 采集支路 `L1→D3→R1→C1` 下沉到 `Y1` ✓：`L1.c0`（inner ✓）与 `D3.c5`（AC1 ✓）同高 ✓；
       `R1.c0`（BR+ ✓）与 `D3.c4`（C2 ✓）同高 ✓；`C1.c0`（RC ✓）与 `R1.c1`（RC ✓）同高 ✓；
    ⑥ `C2`（去耦 ✓）贴在 **U1 下方**（`VDD = c5` 在 U1 底边 ✓）✓，`C2` 与 U1 的水平位置
       对齐到 VDD 脚所在列 ✓。

  ①③④⑤⑥ 是"脚对齐" ✓、② 是"紧凑" ✓ —— 都不靠眼睛估 ✗。

★ 与 v1 相同的两条不变式（不许破 ✗）：源文件不改 ✓；**面包板视图一个字不动** ✓
  （本脚本只碰 `schematicView` ✓，且只删 `Wire*` 的 ✓）。

用法：
    py -3.13 render_sch.py <参考.fzz> _t.png --pins-out pins_ref.py     # 先出几何数据 ✓
    py -3.13 gen_schematic_layout.py <源.fzz> <输出.fzz> --pins pins_ref.py
"""
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

GRID = 7.2                       # Fritzing 原理图网格 0.1in ✓（仅用于"整数格"美观 ✓）
GAP_X = 2 * GRID                 # 相邻本体框水平间隙 ≈ 4.06mm ✓
GAP_Y = 3 * GRID                 # 行间间隙 ≈ 3.05mm ✓


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def load_pins(path):
    """读 `render_sch.py --pins-out` 的纯数据 ✓（不 import 渲染器 ✗ —— 它一 import 就出图 ✗）"""
    ns = {}
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), ns)          # noqa: S102 —— 本项目自己的数据文件 ✓
    pins = {mi: {k: v for k, v in d.items() if k != "__title__"}
            for mi, d in ns["PINS"].items()}
    title = {mi: d["__title__"] for mi, d in ns["PINS"].items() if "__title__" in d}
    return pins, ns["BOX"], title


class L:
    """一件的几何（相对锚点 ✓）与算出来的锚点 ✓"""

    def __init__(self, ttl, mi, pins, box):
        self.ttl, self.mi = ttl, mi
        self.pins = pins                       # {cid: (dx, dy)}
        self.box = box
        self.x = self.y = 0.0

    def pin(self, cid):
        return self.pins[cid]

    def box_cy(self):
        return (self.box[1] + self.box[3]) / 2.0

    def box_cx(self):
        return (self.box[0] + self.box[2]) / 2.0

    def absbox(self):
        return (self.x + self.box[0], self.y + self.box[1],
                self.x + self.box[2], self.y + self.box[3])

    def abspin(self, cid):
        dx, dy = self.pins[cid]
        return (self.x + dx, self.y + dy)


def layout(P):
    """算锚点 ✓（规则见文件头 ✓，全部是"让两个脚同高/居中" ✓）"""
    # ── ① 主链：本体框中心对齐 Y0 ✓；② 左→右按 GAP_X 铺开 ✓
    Y0 = 0.0
    main = ["J1", "U1", "LED2", "J2"]
    x = 0.0
    for i, t in enumerate(main):
        P[t].x = x if i == 0 else x - P[t].box[0]
        P[t].y = Y0 - P[t].box_cy()
        x = P[t].x + P[t].box[2] + GAP_X
    # ── ③④ 用**脚同高**去调主链的 y ✓（取代"本体居中" ✓ —— 让信号线是直的 ✓）
    #    J1.c2 = U1.c2 ✓（DATA_IN）；LED2.c2 = U1.c12 ✓；J2.c2 = U1.c4 ✓
    P["J1"].y = P["U1"].y + P["U1"].pin("connector2")[1] - P["J1"].pin("connector2")[1]
    P["LED2"].y = P["U1"].y + P["U1"].pin("connector12")[1] - P["LED2"].pin("connector2")[1]
    P["J2"].y = P["U1"].y + P["U1"].pin("connector4")[1] - P["J2"].pin("connector2")[1]

    # ── ⑥ C2 贴 U1 **下方**，水平对齐到 VDD 脚那一列 ✓
    P["C2"].x = P["U1"].abspin("connector5")[0] - P["C2"].box_cx()
    P["C2"].y = (P["U1"].absbox()[3] + GAP_Y) - P["C2"].box[1]

    # ── ⑤ 采集支路 ✓：先把 **x 链** 铺开（L1→D3→R1 左→右 ✓），再按"脚同高/同 x"定 y ✓，
    #      最后**整块**搬到主链下方 ✓ —— ✗ 我第一版把 C1 的 x 算在 R1.x 赋值**之前** ✗
    #      （用了 R1 的旧值 ✗ ⇒ C1 飞到 x=17.8 ✗、与 D3 重叠 ✗）；**顺序**在这里是有意义的 ✓。
    P["L1"].x = 0.0
    P["D3"].x = P["L1"].x + P["L1"].box[2] + GAP_X - P["D3"].box[0]
    P["R1"].x = P["D3"].x + P["D3"].box[2] + GAP_X - P["R1"].box[0]
    P["D3"].y = 0.0
    P["L1"].y = P["D3"].pin("connector5")[1] - P["L1"].pin("connector0")[1]   # L1.c0 = D3.AC1 ✓
    P["R1"].y = P["D3"].pin("connector4")[1] - P["R1"].pin("connector0")[1]   # R1.c0 = D3.C2 ✓
    P["C1"].x = P["R1"].abspin("connector1")[0] - P["C1"].pin("connector0")[0]   # 与 R1.c1 **同 x** ✓
    P["C1"].y = (P["R1"].absbox()[3] + GAP_Y) - P["C1"].box[1]                # 留行间缝 ✓
    # 整块搬到主链下方 ✓（用"主链 + 支路"的实际包围盒算 ✓，不拍数 ✓）
    main_bot = max(P[t].absbox()[3] for t in main + ["C2"])
    br_top = min(P[t].absbox()[1] for t in ("L1", "D3", "R1", "C1"))
    dy = (main_bot + 2 * GAP_Y) - br_top
    for t in ("L1", "D3", "R1", "C1"):
        P[t].y += dy
    # 整块左右移，使 D3 落在 U1 左下方 ✓（缩短到 U1 左列那些脚的线的水平距离 ✓）
    dx = P["D3"].box_cx() - P["U1"].absbox()[0]
    for t in ("L1", "D3", "R1", "C1"):
        P[t].x -= dx


def main(src, dst, pinfile, snap=False):
    pins, boxes, title = load_pins(pinfile)
    P = {t: L(t, mi, pins[mi], boxes[mi]) for mi, t in title.items()}
    layout(P)
    if snap:                             # 可选：把锚点吸到网格上（默认**不吸** ✓ ——
        for d in P.values():             # 吸了会破坏"脚同高" ✓，那才是要的 ✓）
            d.x = round(d.x / GRID) * GRID
            d.y = round(d.y / GRID) * GRID

    zin = zipfile.ZipFile(src)
    fzname = [n for n in zin.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(zin.read(fzname))
    moved, dropped, miss = [], [], []
    for el in root.iter("instance"):
        vw = child(el, "views")
        sub = child(vw, "schematicView") if vw is not None else None
        if sub is None:
            continue
        mid = el.get("moduleIdRef") or ""
        ttl = (el.findtext("title") or "").strip()
        if mid.startswith("Wire"):
            vw.remove(sub)
            dropped.append(ttl)
            continue
        if ttl not in P:
            continue
        g = child(sub, "geometry")
        if g is None:
            continue
        d = P[ttl]
        g.set("x", "%g" % d.x)
        g.set("y", "%g" % d.y)
        # ★ 位号必须跟着搬 ✓（`titleGeometry.(x,y) = geometry + (xOffset,yOffset)` ✓ 机验 ✓）
        tg = child(sub, "titleGeometry")
        if tg is not None and (tg.get("visible") or "true") != "false":
            tg.set("x", "%g" % (d.x + float(tg.get("xOffset") or 0.0)))
            tg.set("y", "%g" % (d.y + float(tg.get("yOffset") or 0.0)))
        moved.append((ttl, d.x, d.y))
    want = set(P)
    miss = [t for t in want if t not in [m[0] for m in moved]]

    out = ET.tostring(root, encoding="utf-8", xml_declaration=False).decode("utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zin.namelist():
            zo.writestr(n, out if n == fzname else zin.read(n))

    print("== 原理图 v3（数据驱动摆位 ✓）：%s" % dst)
    print("   摆放 %d 件（间隙 GAP_X=%g / GAP_Y=%g ✓）" % (len(moved), GAP_X, GAP_Y))
    for t, x, y in sorted(moved, key=lambda r: (round(r[2], 1), r[1])):
        d = P[t]
        bb = d.absbox()
        print("      %-6s 锚点(%9.3f,%9.3f)  本体框 x %8.2f…%8.2f  y %8.2f…%8.2f"
              % (t, x, y, bb[0], bb[2], bb[1], bb[3]))
    print("   删掉原理图导线 %d 根 ✓（面包板视图与其它成员原样保留 ✓）" % len(dropped))
    # ★ 自检：把"脚同高"的规则**逐条量出来报** ✓（不喊口号 ✓）
    def dy2(a, ca, b, cb):
        return P[a].abspin(ca)[1] - P[b].abspin(cb)[1]

    def dx2(a, ca, b, cb):
        return P[a].abspin(ca)[0] - P[b].abspin(cb)[0]
    print("   ★ 脚对齐自检（应当 = 0 ✓）：")
    for nm, v in (("J1.c2 ↔ U1.c2  (DATA_IN) **同高**", dy2("J1", "connector2", "U1", "connector2")),
                  ("LED2.c2 ↔ U1.c12 (LED_DIN) **同高**", dy2("LED2", "connector2", "U1", "connector12")),
                  ("J2.c2 ↔ U1.c4  (DATA_OUT) **同高**", dy2("J2", "connector2", "U1", "connector4")),
                  ("L1.c0 ↔ D3.c5  (COIL_A) **同高**", dy2("L1", "connector0", "D3", "connector5")),
                  ("R1.c0 ↔ D3.c4  (BR+) **同高**", dy2("R1", "connector0", "D3", "connector4")),
                  ("C1.c0 ↔ R1.c1  (RC) **同 x**", dx2("C1", "connector0", "R1", "connector1"))):
        print("      %-32s Δ = %8.4f 单位 %s" % (nm, v, "✓" if abs(v) < 0.01 else "⚠"))
    # ★ 重叠自检 ✓（本体框两两不许相交 ✓ —— 我没赌"原点居中" ✗，所以这里必须量 ✓）
    ov = []
    ts = sorted(P)
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            a, b = P[ts[i]].absbox(), P[ts[j]].absbox()
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                ov.append((ts[i], ts[j]))
    print("   ★ 重叠自检：本体框相交 **%d 对** %s" % (len(ov), "✓" if not ov else
                                                    "✗ " + ", ".join("%s×%s" % o for o in ov)))
    if miss:
        print("   ✗ 摆位表里这些位号在图中没找到：%s" % ", ".join(miss))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a[2:].split("=")[0]: a[2:].split("=")[1] for a in sys.argv[1:]
            if a.startswith("--") and "=" in a}
    main(args[0], args[1],
         opts.get("pins", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pins_v2.py")),
         snap=bool(opts.get("snap")))
