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
import re
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
# ★★ `ROTJ1`：**把 `J1` 转 180°** ✓（`--rotj1=1` ✓，默认**关** ✗）—— 2026-09-28 ✓ 用户提的路 ✓
#   病 ✓（实测 ✓）：`J1` 的引脚在**左缘** ✓、本体在右 ✗ ⇒ 而线要从右边 `U1` 过来 ✗
#     ⇒ 要么**绕**（band0 就是这么走的 ✓ 4 段 57.7 ✓ 干净 ✓）、要么**穿本体**（band1 ✗ 58.6 ✗）
#     ⇒ “穿”又短又（在松口径下 ✗）免费 ⇒ 它选了穿 ✗（用户：「不行，`J1.3` 穿自己了」✗）。
#   ✓ 转 180° ⇒ 引脚改到**右缘、面向电路** ✓ ⇒ “从右边过来”变成**合法且最短** ✓
#     ⇒ 诱惑自己消失 ✓，**路由口径一个字不用动** ✓（本仓那句「不是路由问题，是摆位问题」✓）。
#   ★ 写法取自**源件里已有的实例** ✓（不猜 ✗）：`C2` 面包板实例就是 180°：
#     `m11=-1, m12=0, m13=0, m21=0, m22=-1, m23=0, m31=16.9524, m32=22.3444, m33=1` ✓；
#     原理图实例**一个 transform 都没有** ✗ ⇒ 所以这一条要**用户开 Fritzing 看一眼**验收 ✓。
#   ★ `m31 = 盒左+盒右`、`m32 = 盒上+盒下` ✓（= 2×中心 ✓ 与原点在哪无关 ✓）。
#   ★★ 父元素必须是 **`geometry` 的子元素** ✗（`README.md` 第十一手 / `set_rot.py` 头 ✓）：
#     我第一版写成 `schematicView` 的**兄弟** ✗ ⇒ **Fritzing 直接无视** ✗（用户实测「`J1` 没有旋转」✗）。
#   ★★ **默认开 ✓**（2026-09-28 ✓ 用户开 Fritzing 验收通过 ✓）：引脚跑到**右缘朝内** ✓、
#     行对齐 `J1.c2 ↔ U1.c2` 仍然 Δ=0 ✓、本体落在脚列上方 ✓（180° 的必然结果 ✓）。
#     要回到旧朝向 ✗：`--rotj1=0` ✓。
ROTJ1 = True
# ★★ `--by-bb=<面包板.fzz>`：**按成功面包板的排布**摆 ✓（2026-09-28 ✓ 用户定的新逻辑 ✓）
#  用户原话 ✓：「咱们已经有了**成功的面包板布线图**，完全可以从面包板布线图出发，来绘制原理图……
#    面包板和原理图的重要区别，是少了**天地轨的约束**，带来了 5V 和 GND 穿体问题。所以，
#    提出了**先画天地轨**，然后再在中间**按面包板排布元件**，然后再连 5V 和 GND 线，
#    最后是其它线，**从上到下，从左到右**。」
#  ★ 为什么应该这么做 ✓（同一天量出来的证据 ✓）：原理图里那 6 段“穿体”**全是长横线** ✗
#    （`GND 157.2` / `DATA_OUT 157.2` / `5V 151.6` 单位 ✓，都是从右边 J2 的脚列横穿到左边 U1 ✗），
#    而**面包板上没有这种线** —— 因为面包板有**天地轨**：电源脚就近上/下轨 ✓（用户的判断 ✓）。
#  ★ 数据来源 = 面包板图里每件**占的孔** ✓（`breadboardView/connectors/*/connects` ✓）；
#    行 y / 列距 / 孔 id 解析一律用 `bb_route4` 那一份 ✓（一份实现 ✓ 不抄 ✗）。
#  ★ 槽位用**行字母集合**判 ✓（✗ 不用拍 y 阈值 ✗）：
#      含 `Z/Y` ⇒ `rail`（**贴在电源轨上** ✓ —— 面包板上它插的就是轨的孔 ✓，如 C2 ✓）
#      只含 `F..J` ⇒ `up`（上半区 ✓）；只含 `A..E` ⇒ `down`（下半区 ✓）；
#      两边都含 ⇒ `mid`（**跨中缝** ✓ —— 两排针的模块只能这样 ✓ 见库仓 AGENTS §5b ⑪ ✓）。
BY_BB = None


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


def read_bb_slots(fzz):
    r"""从**面包板图**读 `件 → (槽位, 列号)` ✓（列号取占孔列的**中位** ✓）

    见 `BY_BB` 那段（用户的新逻辑 + 为什么该照它摆 ✓）。
    """
    import bb_route4 as BB                        # ★ 行 y / 孔解析**一份实现** ✓
    UP, DOWN, RAIL = set("FGHIJ"), set("ABCDE"), set("ZYXW")
    z = zipfile.ZipFile(fzz)
    root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    out = {}
    for el in root.iter("instance"):
        if (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        t = (el.findtext("title") or "").strip()
        vw = child(el, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        cb = child(sub, "connectors") if sub is not None else None
        if cb is None:
            continue
        cols, rows = [], set()
        for c in cb:
            for cs in c:
                for cn in cs:
                    m = re.fullmatch(r"pin(\d+)([A-Z])", cn.get("connectorId") or "")
                    if m and m.group(2) in BB.ROW_Y:
                        cols.append(int(m.group(1)))
                        rows.add(m.group(2))
        if not cols:
            continue
        if rows & RAIL:
            slot = "rail"
        elif (rows & UP) and (rows & DOWN):
            slot = "mid"
        elif rows & UP:
            slot = "up"
        elif rows & DOWN:
            slot = "down"
        else:
            slot = "mid"
        out[t] = (slot, sorted(cols)[len(cols) // 2])
    return out


def layout_by_bb(P, slots):
    r"""**按面包板的排布**摆 ✓（用户 2026-09-28 定的新逻辑第 ② 步 ✓）

    做法 ✓（每步都能说出理由 ✓）：
      ① 分四个**行槽** ✓：`mid`（跨中缝件 ✓ = 中间一行）、`up`（上半区 ✓）、
         `down`（下半区 ✓）、`rail`（贴在电源轨上的件 ✓ —— 摆在最上 ✓）；
      ② 每个槽**内部**按面包板的**列号左→右**排 ✓（这就是“从左到右” ✓），
         间距沿用 **`GAP_X`** ✓（= v18 那个 2 格 ✓ 不新拍数 ✗）；
      ③ 纵向以 **`mid` 为基行** ✓：`up` 摞在它上方、`rail` 再摞在 `up` 上方 ✓、
         `down` 叠在下方 ✓；行间留 **`GAP_Y`** ✓（同样沿用 v18 的数 ✓）。
    ★ 为什么这样就能治穿体 ✓：电源脚在**上排件的上方 / 下排件的下方**都是一片空地 ✓
      ⇒ 接天地轨的支线**不需要横穿别的元件** ✓（面包板上就是这个道理 ✓）。
    """
    order = sorted(slots, key=lambda t: (slots[t][1], t))
    buckets = {"rail": [], "up": [], "mid": [], "down": []}
    for t in order:
        if t in P:
            buckets[slots[t][0]].append(t)
    rowbox = {}
    for name, ts in buckets.items():
        if not ts:
            continue
        x = 0.0
        for i, t in enumerate(ts):
            P[t].x = 0.0 if i == 0 else x - P[t].box[0]
            P[t].y = 0.0
            x = P[t].x + P[t].box[2] + GAP_X
        rowbox[name] = (min(P[t].absbox()[1] for t in ts),
                        max(P[t].absbox()[3] for t in ts))

    def shift(ts, dy):
        for t in ts:
            P[t].y += dy

    cur_top, cur_bot = rowbox.get("mid", (0.0, 0.0))
    if buckets["up"]:
        ut, ub = rowbox["up"]
        dy = cur_top - GAP_Y - ub
        shift(buckets["up"], dy)
        cur_top = ut + dy
    if buckets["rail"]:
        rt, rb = rowbox["rail"]
        dy = cur_top - GAP_Y - rb
        shift(buckets["rail"], dy)
        cur_top = rt + dy
    if buckets["down"]:
        dt, db = rowbox["down"]
        dy = cur_bot + GAP_Y - dt
        shift(buckets["down"], dy)
        cur_bot = db + dy
    print("   行槽 ✓：rail=%s ｜ up=%s ｜ mid=%s ｜ down=%s"
          % tuple(",".join(buckets[k]) or "(空)"
                  for k in ("rail", "up", "mid", "down")))


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

    # ── ★★ ⑥ C2（去耦电容）的摆位见**函数末尾** ✓（2026-09-28 改 ✓）——
    #   ✗ 原来在**这里**（贴 U1 下方 ✗）—— 用户看图后的判断 ✓（原话：「**C2 的位置不合适，
    #     它没有被挪到合适的位置，导致了两次穿体**」✓）：贴在 U1 下方 ⇒ 它的 5V 脚朝上（要
    #     穿过整个 U1 才到上轨 ✗）、GND 脚朝下（要穿过 D3 ✗）⇒ 实测两次穿体 ✗
    #     （`t56_0`：`(49.4,57.6)→(49.4,-57.6)` 蹭 U1 左排脚 ✗、`(55.0,84.6)→(55.0,199.2)` 穿 D3 ✗）。
    #   ✓ 挪到**图右侧外侧、顶部齐最上** ⇒ 5V 脚朝上直接接**上 5V 轨** ✓（短 ✓ 不穿 ✓）；
    #     GND 脚朝下沿**右侧空地**走到**下 GND 轨** ✓（长 ✓ 但一路无元件 ✓ ——
    #     用户明确说过“原理图不用考虑线长约束、图纸大小约束”✓）。
    #   ⇒ 必须放在**末尾**（要等其它件都摆完才知道“右侧外侧”在哪 ✓）。

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
    main_bot = max(P[t].absbox()[3] for t in main)
    br_top = min(P[t].absbox()[1] for t in ("L1", "D3", "R1", "C1"))
    dy = (main_bot + 2 * GAP_Y) - br_top
    for t in ("L1", "D3", "R1", "C1"):
        P[t].y += dy
    # 整块左右移，使 D3 落在 U1 左下方 ✓（缩短到 U1 左列那些脚的线的水平距离 ✓）
    dx = P["D3"].box_cx() - P["U1"].absbox()[0]
    for t in ("L1", "D3", "R1", "C1"):
        P[t].x -= dx

    # ── ★★ ⑥ C2：放到**图右侧外侧、顶部与最上的件齐** ✓（2026-09-28 改 ✓，用户点名的 ✓）
    #   为什么是“右侧外侧、顶部” ✓（不是为了好看 ✗，是**为了让它的两根脚各走一边** ✓）：
    #     · 它是全图**唯一**“两根脚分属两个网、且一上一下”的件 ✓（5V 在上 / GND 在下 ✓）
    #       ⇒ 面包板上它是**跨在两条电源轨之间**的 ✓（孔 `pin28Z` + `pin29Y` ✓ = GND 轨行 + 5V 轨行 ✓）。
    #     · 摆到**最右**（其它件右边之外 ✓）⇒ 它的 GND 支线**沿右侧空地**直下 ✓，
    #       一路上**没有任何元件** ✓（这正是它原来穿 U1、穿 D3 的原因 —— 原来它被夹在中间 ✓）。
    #     · 顶部**齐最上** ⇒ 5V 脚朝上，到**上 5V 轨**的距离最短 ✓。
    _others = [t for t in P if t != "C2"]
    if _others:
        _xr = max(P[t].absbox()[2] for t in _others)
        _yt = min(P[t].absbox()[1] for t in _others)
        P["C2"].x = (_xr + GAP_X) - P["C2"].box[0]
        P["C2"].y = _yt - P["C2"].box[1]


def main(src, dst, pinfile, snap=False):
    pins, boxes, title, LAB = load_pins(pinfile)
    P = {t: L(t, mi, pins[mi], boxes[mi]) for mi, t in title.items()}
    if ROTJ1 and "J1" in P:                # ★★ `--rotj1` ✓：J1 局部坐标转 180° ✓（见 ROTJ1 注释 ✓）
        _d = P["J1"]
        _b = _d.box
        _mx, _my = _b[0] + _b[2], _b[1] + _b[3]
        _d.pins = {c: (_mx - _px, _my - _py) for c, (_px, _py) in _d.pins.items()}
        print("★ ROTJ1 ✓：`J1` 局部坐标转 180°（m31=%.3f m32=%.3f ✓）⇒ 引脚改到右缘、面向电路 ✓"
              "（渲染器会自动按 `<transform>` 算 ✓，与 Fritzing 同口径 ✓）" % (_mx, _my))
        for _c, _p in sorted(_d.pins.items()):
            print("      %s → (%.3f, %.3f)" % (_c, _p[0], _p[1]))
    # ★★ `--by-bb` ✓：按**面包板排布**（用户 2026-09-28 定的新逻辑 ✓）—— 否则走旧规则 ✓
    if BY_BB:
        _sl = read_bb_slots(BY_BB)
        _miss = [t for t in P if t not in _sl]
        print("★ 按**面包板排布**摆 ✓（源 %s ✓）：%s%s"
              % (BY_BB,
                 ", ".join("%s=%s@%d" % (t, _sl[t][0], _sl[t][1])
                           for t in sorted(_sl, key=lambda a: _sl[a][1])),
                 (" ｜ ⚠ 图里没找到孔的件：%s" % ",".join(_miss)) if _miss else ""))
        layout_by_bb(P, _sl)
    else:
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
    if ROTJ1 and "J1" in P:
        # ★★ 2026-09-28 ✓：`J1` **不额外左移** ✗ —— 试过，实测**在交付档上两败** ✗，已撤 ✓。
        #   起因 ✓：转 180° 后 band0 的 `J1` 引脚列（15.378 ✓）与 `U1` 左排的出脚走廊
        #     （`17.578 = U1左缘 29.78 − ESC_PIN 12.2` ✓）只差 **2.2** ✗ ⇒ 一根 `RC` 竖线
        #     擦过 `c0/c1/c2`（2.20 单位 ✗）⇒ band0 贴脚 7 → 9 ✗。
        #   ✗ 试法：`P["J1"].x -= 7.2` ✓ ⇒ 实测 **band1 贴脚 1 → 6** ✗✗、**交叉 15 → 18** ✗✗
        #     （band0 只把交叉 16 → 15 ✓、画布 95.7 → 93.6 ✓）⇒ **交付档优先** ⇒ **撤** ✓。
        #   ★ 结论 ✓（记下来，别再试 ✗）：那 2.2 单位的擦脚属于「`J1` 换向的几何后效」✓，
        #     **不值得为它牺牲交付档** ✗ ⇒ band0 的贴脚 7 → 9 **照实记录** ✓。
        pass
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
        # ★★ `--rotj1` ✓：给 J1 写 180° 的 `<transform>` ✓
        #   ✗ **父元素必须是 `geometry`** ✗（`README.md` 第十一手 / `set_rot.py` 头 ✓）：
        #     我第一版写成 `schematicView` 的**兄弟** ✗ ⇒ **Fritzing 直接无视** ✗
        #     （用户实测：「`J1` 没有旋转」✗ ⇒ 白验一轮 ✓）。
        #   ✓ 形态照 `set_rot.py`：`<geometry …><transform m11…m33/></geometry>` ✓。
        #   ★ `m31 = 盒左+盒右`、`m32 = 盒上+盒下` ✓（= 2×中心 ✓）；没有就新建 ✓、有就覆盖 ✓。
        if ROTJ1 and ttl == "J1":
            _b = d.box
            _tf = next((c for c in g if c.tag.split("}")[-1] == "transform"), None)
            if _tf is None:
                _tf = ET.SubElement(g, "transform")
            _tf.attrib.update({"m11": "-1", "m12": "0", "m13": "0",
                               "m21": "0", "m22": "-1", "m23": "0",
                               "m31": "%g" % (_b[0] + _b[2]),
                               "m32": "%g" % (_b[1] + _b[3]), "m33": "1"})
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
    if "by-bb" in opts:                      # ★★ 按面包板排布 ✓（用户 2026-09-28 ✓）
        BY_BB = opts["by-bb"]
        print("★ BY_BB ← %s ✓（按**面包板**的行槽位 + 列序排元件 ✓）" % BY_BB)
    if "socket" in opts:
        SOCKET_EXTRA = float(opts["socket"]) * GRID
        print("★ SOCKET_EXTRA ← %.2f 格（%.0f 单位 ✓）" % (float(opts["socket"]), SOCKET_EXTRA))
    if "pos-from" in opts:                     # ★★ 抄摆位 ✓（2026-09-28 ✓ 用户要求 ✓）
        POS_FROM = opts["pos-from"]
        print("★ POS_FROM ← %s ✓（照搬该文件的 (x,y) ✓；位号随后重算 ✓）" % POS_FROM)
    if "rotj1" in opts:                        # ★★ J1 转 180° ✓（**默认开** ✓；`--rotj1=0` 关 ✗）
        ROTJ1 = opts["rotj1"] not in ("0", "false", "False")
        print("★ ROTJ1 ← %s ✓（`J1` 引脚改到右缘、面向电路 ✓；用户 2026-09-28 开 Fritzing 验收通过 ✓）"
              % ROTJ1)
    main(args[0], args[1],
         opts.get("pins", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pins_v2.py")),
         snap=bool(opts.get("snap")))
