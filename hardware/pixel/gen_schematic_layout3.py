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

import sch_text as ST                 # ★ 字宽表（唯一实现 ✓，与渲染器同一份 ✓）

GRID = 7.2                       # Fritzing 原理图网格 0.1in ✓（仅用于"整数格"美观 ✓）
# ★★ `GAP_X`：水平间隙从 **1 格 → 2 格** ✓（2026-09-28 ✓ **用户观察 + 实测** 定 ✓）
#   用户原话（2026-09-28）：「**先抄我手改版的元件间距，我觉得现在明显是间距不够**」✓
#   两条证据 ✓：
#     ① **量出来**（同一套量法 ✓，`_scratch/t37.py` ✓）：最近间隙 手改版 **13.27 单位（3.75mm）** ✓
#        ／ 自动 v17 **7.20（2.03mm）** ✗；且 v17 有 **5 对**正好卡在 7.2 ✗
#        （J1↔U1、J2↔LED2、D3↔L1、D3↔R1、LED2↔U1 ✓）；换成 2 格 = **14.4 单位** ✓
#        ⇒ 忠实对应用户手改版的 13.3 ✓（**抄间距** ✓，不是抄绝对坐标 ✗）；
#     ② **A/B 实测**（`_scratch/t40.py` ✓，只动这一项 ✓）：
#          1 格（旧默认 ✗）：重叠 0 ｜ 贴脚 11 ｜ 交叉 **10** ｜ 穿体 **10** ✗ ｜ 总长 2060 ｜ 83.2×82.9
#          2 格（新默认 ✓）：重叠 0 ｜ 贴脚 11 ｜ 交叉 **10** ✓ ｜ 穿体 **6** ✓✓ ｜ 总长 **2025** ✓ ｜ 89.3×82.9
#        ⇒ **穿体 10 → 6** ✓✓，交叉/贴脚**一项都没变差** ✓，总长还略短 ✓；代价只有**画布宽 +6mm** ✗。
#   ★ 同批还测了「**照搬用户手改版的 (x,y)**」（`--pos-from` ✓）⇒ **更差** ✗（贴脚 16 ✗、交叉 13 ✗、
#     总长 2507 ✗、画布 105.6 ✗✗）⇒ **抄间距行、抄绝对坐标不行** ✓（他那套摆位是配**他手画的走线**的 ✓）。
#   ★ 回旧行为：`--gapx=1` ✓。
GAP_X = 2 * GRID                 # 相邻本体框水平间隙 ≈ 4.06mm ✓（原来是 1 格 ≈ 2.03mm ✗）
GAP_Y = 2 * GRID                 # 行间间隙 ≈ 4.06mm ✓
# ★ 这两个数是**扫出来的** ✓（2026-09-27 ✓，`_scratch/sweep_layout.py` 全流程实测 ✓）：
#   起因：`px` 那个 bug 修掉后 `LED2`/`D3` 小了 20% ✓ ⇒ 旧间距（2/3 格）是照**错的尺寸**调的 ✗ ⇒
#   布线器为了绕开空档，交叉升到 12 ✗、画布也撑大了 ✗。
#   扫 6 组 ⇒ **1 格 / 2 格** 明显最优 ✓：交叉 **12 → 9** ✓、总长 **2386.9 → 2137.3**（−10% ✓）、
#   画布 **97.0×96.6 → 90.9×90.5** ✓；位号压导线 3 处**与间距无关** ✗（要另修 ✓）。
# ★ 插座（首尾两件）跟核心电路**再多留一段** ✓（2026-09-27 用户洞察 ✓：
#   “接口插座要跟核心电路拉开更大的距离” ✓）。
#   ★ 这个 **4 格**不是我拍的 ✓ —— 我把**用户手改的那一版**里 J1 的位移量出来 ✓：
#     他把我 v5 的 J1 往左挪了 **28.8 单位 = 4 × GRID（7.2）= 8.13mm** ✓
#     ⇒ 这就是他要的额外间距 ✓（“找数据、不猜” ✓）。
#   ✗ **实测不划算 ⇒ 默认关掉（0）** ✓（2026-09-27 ✓）：加上 4 格后
#     **交叉 8 → 10** ✗、总长 +9% ✗、画布 98.9 → **116.2mm 宽** ✗✗（“导线还绕出零件范围外了” ✗）
#     ⇒ 它是**审美取舍**（把接口和核心分开 ✓ = 信息层次 ✓）而**不是**指标上的改善 ✗，
#     所以默认 0 ✓、保留成开关 ✓，由用户定要不要 ✓（按规矩：不硬凑数字 ✓）。
#   ★★ **`--socket 4 / 7` 也复测过 ⇒ 仍然不划算 ✗**（2026-09-28 ✓，`_scratch/t32.py` 三档 ✓）：
#       档位     重叠 贴脚 交叉 穿体   总长   画布
#       socket0   0    11   23    9   2274   82.0×86.3
#       socket4   0    15   23    5   2440   91.5×86.3
#       socket7   0    12   23    5   2621   105.4×86.3
#     ⇒ **交叉 23/23/23 一动不动** ✗（我原以为“插座让路 ⇒ 交叉明显下降” ✗ —— 错 ✗）、
#       **总长 +15%** ✗、**画布 +29%** ✗、贴脚更差 ✗；唯一收益是**穿体 9→5** ✓。
#     ★ 根因（三次失败同一个 ✓）：本布线器的**通道集是从元件盒算出来的** ✓（`CH_OFFS` 相对
#       元件边 ✓）⇒ **一挪元件，通道集跟着乱** ✗ ⇒ 挪摆位这条轴**结构上就不可能赢** ✗
#       （而用户手改版是**贴着实际空地在画** ✓，不依赖这条网格 ✓）。
SOCKET_EXTRA = 0
POS_FROM = None        # ★★ `--pos-from=<fzz>`：抄那一份的摆位 ✓（2026-09-28 ✓ 用户要求 ✓）


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
    return pins, ns["BOX"], title, ns.get("LAB", {})


def _ov(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_labels(P, LAB, title, gap=7.2):
    r"""位号摆位 ✓：默认放本体**上方留一格** ✓；从几个候选位里挑**碰撞最少**的 ✓

    ★ 为什么要挑 ✗（2026-09-27 实测 ✓）：`L1` 的位号是 `L1` + `NFC-Coil-20-6T` ✓
      （宽 ≈ 35 单位 ✓）而 L1 的本体只宽 **4.5** 单位 ✗ ⇒ 放哪都会**伸到邻居身上** ✗
      ⇒ 把候选位置都算一遍 ✓，取"压到别人最少"的那个 ✓
      （压**元件**权 10 ✓、压**已放的位号**权 5 ✓；长位号先放 ✓ = 大的先占位 ✓）。
    ⚠ 导线这时还不知道 ✗（要布完线才知道 ✓）⇒ 位号与导线的关系只能事后量 ✓、
      必要时再把位号框交给布线器当 keep-out ✓。
    """
    fs_of = {t: LAB[mi]["fs"] for mi, t in title.items() if mi in LAB}
    ln_of = {t: LAB[mi]["lines"] for mi, t in title.items() if mi in LAB}
    out, placed = {}, []
    order = sorted((t for t in P if t in ln_of),
                   key=lambda t: -max(ST.twidth(s, fs_of[t]) for s in ln_of[t]))
    for t in order:
        d, bx, fs = P[t], P[t].absbox(), fs_of[t]
        w = max(ST.twidth(s, fs) for s in ln_of[t])
        h = fs * len(ln_of[t])
        cand = [(bx[0], bx[1] - gap - h), (bx[2] - w, bx[1] - gap - h),
                ((bx[0] + bx[2] - w) / 2.0, bx[1] - gap - h),
                (bx[0], bx[3] + gap), (bx[2] - w, bx[3] + gap),
                (bx[0] - gap - w, bx[1]), (bx[2] + gap, bx[1])]
        best, bk = None, None
        for x, y in cand:
            b = (x, y, x + w, y + h)
            sc = 0
            for t2, d2 in P.items():
                if t2 != t and _ov(b, d2.absbox()):
                    sc += 10
            sc += 5 * sum(1 for _t2, b2 in placed if _ov(b, b2))
            if bk is None or sc < bk:
                best, bk = b, sc
        placed.append((t, best))
        # 反推锚点 ✓：`label_bbox` 里盒上缘 = 锚点y + 0.25fs ✓（第1行基线 = y+fs ✓）
        out[t] = (best[0] - d.x, best[1] - 0.25 * fs - d.y)
    return out


def read_positions(fzz):
    r"""从一份 `.fzz` 读每件的**摆位** ✓ ⇒ `[(标题, x, y), …]`

    ★★ 位置在哪里 ✓（2026-09-28 ✓ 我先读错过一次 ✗）：写在
      `instance / views / schematicView` 的**直接子** `geometry` 的 `x`/`y` ✓；
      ✗ **不能**用“子树里最后一个 geometry” ✗ —— 那是**连接器**的相对坐标 ✓，全是 `(0, 0)` ✗
      （我第一版就这么读的 ✗，得到“两版位置一模一样” 的假结果 ✗）。
    """
    import xml.etree.ElementTree as _ET
    import zipfile as _zip
    z = _zip.ZipFile(fzz)
    root = _ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    out = []
    for el in root.iter("instance"):
        t = (el.findtext("title") or "").strip()
        if not t or (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        for ch in el:
            if ch.tag.split("}")[-1] != "views":
                continue
            for sub in ch:
                if sub.tag.split("}")[-1] != "schematicView":
                    continue
                for gg in sub:                      # ★ 只看**直接子** ✓
                    if gg.tag.split("}")[-1] == "geometry":
                        try:
                            out.append((t, float(gg.get("x")), float(gg.get("y"))))
                        except (TypeError, ValueError):
                            pass
    return out


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
    # ★ 两条“插座边”多留 SOCKET_EXTRA ✓（J1↔U1 ✓、LED2↔J2 ✓）；中间那条保持 GAP_X ✓
    socket_edge = {("J1", "U1"), ("LED2", "J2")}
    x = 0.0
    for i, t in enumerate(main):
        P[t].x = x if i == 0 else x - P[t].box[0]
        P[t].y = Y0 - P[t].box_cy()
        g = GAP_X + (SOCKET_EXTRA if i + 1 < len(main) and (t, main[i + 1]) in socket_edge else 0)
        x = P[t].x + P[t].box[2] + g
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
    pins, boxes, title, LAB = load_pins(pinfile)
    P = {t: L(t, mi, pins[mi], boxes[mi]) for mi, t in title.items()}
    layout(P)
    # ★★ `--pos-from=<fzz>`：**整体抄另一份的摆位** ✓（2026-09-28 ✓ 用户要求：「先抄我手改版
    #   的元件间距」✓）—— 用户手改版的最小间隙是 **13.3 单位（3.75mm）** ✓，
    #   而我们自动版有 **5 对卡在 7.2 单位（2.03mm）** ✗（就是 `--gapx/--gapy` 那一格 ✓）。
    #   ⇒ 把源件的 `(x, y)` **照搬** ✓（不猜偏移量 ✗）；**位号随后由 `place_labels` 重算** ✓
    #     ⇒ 抄的是**摆位**，不是位号偏移 ✓（那本来就该跟着重算 ✓）。
    if POS_FROM:
        _n = 0
        for _t, _x, _y in read_positions(POS_FROM):
            if _t in P:
                P[_t].x, P[_t].y = _x, _y
                _n += 1
        print("★ 抄摆位 POS_FROM ← %s ✓：%d 件坐标被覆盖 ✓（位号随后重算 ✓，可用 --gapx/--gapy 微调其它件 ✓）"
              % (POS_FROM, _n))
    LOFF = place_labels(P, LAB, title) if LAB else {}
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
        #   ★★ 而且 Offset 现在由 `place_labels()` **算** ✓（不再是零件自带的 ✗）：
        #     v4 的"位号压导线 8 处"就是这么来的 ✗ ⇒ 改成"上方留一格 + 候选位挑碰撞最少" ✓。
        tg = child(sub, "titleGeometry")
        if tg is not None and (tg.get("visible") or "true") != "false":
            ox, oy = LOFF.get(ttl, (float(tg.get("xOffset") or 0.0),
                                    float(tg.get("yOffset") or 0.0)))
            tg.set("xOffset", "%g" % ox)
            tg.set("yOffset", "%g" % oy)
            tg.set("x", "%g" % (d.x + ox))
            tg.set("y", "%g" % (d.y + oy))
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
    if LOFF:
        SEG = []
        for t, (ox, oy) in LOFF.items():
            d = P[t]
            fs = LAB[[mi for mi, x in title.items() if x == t][0]]["fs"]
            ln = LAB[[mi for mi, x in title.items() if x == t][0]]["lines"]
            SEG.append((t, ST.label_bbox(d.x + ox, d.y + oy, fs, ln)))
        bad = [(t1, t2) for i, (t1, b1) in enumerate(SEG) for t2, b2 in SEG[i + 1:] if _ov(b1, b2)]
        bad += [(t, t2) for t, b in SEG for t2, d2 in P.items() if t != t2 and _ov(b, d2.absbox())]
        print("   ★ 位号自检：压位号/压元件 **%d 处** %s（导线要布完线才能量 ✓）"
              % (len(bad), "✓" if not bad else "✗ " + ", ".join("%s×%s" % b for b in bad[:6])))
    if miss:
        print("   ✗ 摆位表里这些位号在图中没找到：%s" % ", ".join(miss))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a[2:].split("=")[0]: a[2:].split("=")[1] for a in sys.argv[1:]
            if a.startswith("--") and "=" in a}
    # ★ 摆位参数可调 ✓（2026-09-27 加 ✓）：尺寸修正后（`px` 那个 bug ✓）原来的间距是照
    #   **错的尺寸**调的 ✗ ⇒ 用这几个开关**扫一遍**、按指标挑 ✓（`_scratch/sweep_layout.py` ✓）。
    if "gapx" in opts:
        GAP_X = float(opts["gapx"]) * GRID
        print("★ GAP_X ← %.2f 格（%.0f 单位 ✓）" % (float(opts["gapx"]), GAP_X))
    if "gapy" in opts:
        GAP_Y = float(opts["gapy"]) * GRID
        print("★ GAP_Y ← %.2f 格（%.0f 单位 ✓）" % (float(opts["gapy"]), GAP_Y))
    if "socket" in opts:
        SOCKET_EXTRA = float(opts["socket"]) * GRID
        print("★ SOCKET_EXTRA ← %.2f 格（%.0f 单位 ✓）" % (float(opts["socket"]), SOCKET_EXTRA))
    if "pos-from" in opts:                     # ★★ 抄摆位 ✓（2026-09-28 ✓ 用户要求 ✓）
        POS_FROM = opts["pos-from"]
        print("★ POS_FROM ← %s ✓（照搬该文件的 (x,y) ✓；位号随后重算 ✓）" % POS_FROM)
    main(args[0], args[1],
         opts.get("pins", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pins_v2.py")),
         snap=bool(opts.get("snap")))
