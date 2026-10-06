# -*- coding: utf-8 -*-
r"""像素板 **自动布线写回**（P2 ✓）2026-09-30 立

用法：
  py -3.13 gen_routes.py <摆位好的.fzz> <输出.fzz> [--nets=pixel_nets.py] [--via=10] [--tries=6] [--check]

★ 只**加** PCB 走线 / 过孔实例 ✓ —— 元件位置、面包板视图、原理图视图**一个字不动** ✗
  （同一个实例在三个视图各有一份 ✓，混着改会把已交付的两张图弄坏 ✗）。
★ 走线 / 过孔的 XML **逐字照 Fritzing 亲笔** ✓
  （模板从 Fritzing 写的 `single-channel.fzz` 里抄出来 ✓，抄法见 `_work/dump_wire3.py` ✓）：
  · 走线 `<pcbView layer="copperNtrace">`
      `<geometry z x y x1 y1 x2 y2 wireFlags="128"/>`
      ＋ `<wireExtras mils color opacity banded/>`
      ＋ 两端各一个 `<connector connectorId="connector0|1">` ＋ 其 `<connects>`
    ⇒ `x/y` = **第一个端点**（绝对 ✓）；`x1..y2` = **相对偏移** ✓（所以恒有 x1=y1=0 ✓）。
  · 过孔 `<pcbView layer="copper0"><geometry z x y wireFlags="32"/>`
      ＋ **只有** `connector0` ✓ ⇒ 两端各由**一条走线的端**去连它 ✓。
  · `<connect>` 的 `layer` = **对方自己的层名** ✓：
      焊盘 `copper0|copper1` ✓、走线 `copperNtrace` ✓、过孔 `copper0` ✓；
      `modelIndex` = 对方实例的编号 ✓。
  · 没接上东西的端点 ⇒ **不写**那个 `<connector>` ✓（Fritzing 也这样 ✓），但**要报** ✗。
★ `modelIndex` 从**现有最大值往后排** ✓（撞号会把别人的连接抢走 ✗）。
★ 写回前先把「端点落在别人线段中间」的地方**切开** ✓ —— 不然那个端点接不上任何东西 ✗
  （Fritzing 的 `<connect>` 只认**端↔端** ✓，没有"在线中间搭一下"这种记法 ✗）。
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolpaths                                                  # noqa: E402,F401
import part_box as PB                                             # noqa: E402
import pcb_check as PC                                            # noqa: E402
import pcb_route as RT                                            # noqa: E402
import pcb_wire as PW                                             # noqa: E402
import projdata                                                   # noqa: E402

# ★★ 过孔尺寸 ✓（**唯一来源** ✓）：写进文件的 `hole size` 与开头打印的说明都取它 ✓
#   —— ✗ 以前打印那句是**写死的字符串** ✗ ⇒ 我把尺寸改小了、它还在报"0.3/0.15 mm" ✗
#     （自己报的和写的不一样 ✗ —— 2026-10-01 实测撞到 ✓）。
#   口径 = `「钻孔 , 环宽」` ✓（源码判定 ✓ `mazerouter.cpp:2430` ✓）⇒ 盘径 = 孔 + 2×环 ✓。
_VIA_HOLE_VAL = "0.3mm,0.15mm"                                  # 盘 Ø0.6 mm ✓
_VIA_HOLE_TXT = "0.3/0.15 mm 孔环（盘 Ø0.6 ✓）"
# ★★ 2026-10-02 补 ✓：**画图偏移随尺寸变** ✗（= **铜半径 + 画布留白 0.56444 mm** ✓，
#   见 `part_box.ring_off_mm` ✓ —— 三个独立实测点 ✓）⇒ **从同一份 `_VIA_HOLE_VAL` 解析** ✓，
#   ✗ 别再“写死常数 / 缺省就沿用” ✗ —— 「连 `_VIA_HOLE_VAL` 改了、偏移却没改」
#   正是 2026-10-02 那次误报的病根 ✓：用户手加的 `0.4mm,0.3mm` 过孔被按 0.3/0.15 的偏移量算
#   ⇒ 铜心偏 0.2 mm/轴 ✗ ⇒ 校验器把**接好了的**过孔报成“孤立/悬空” ✗
#   （而 Fritzing 里明明是通的 ✓ —— 文件里 `Wire90014056` 写着
#    `<connect … modelIndex="90014051" layer="copper0"/>` ✓）。
_VIA_SIZE_MM = tuple(float(x) for x in re.findall(r"([\d.]+)\s*mm", _VIA_HOLE_VAL))

# ★★ 「保线」时给**用户画的走线**留的净空基准 ✓（2026-10-03 ✓，见 `main` 里的 `[保线]` ✓）：
#   他线上的**任意中点**到新线**中心线**的下限 = `KEEP_W_MM/2 + CLEAR_MM` ✓。
#   取 **24 mil（标准档 ✓ 0.6096 mm ✓）** —— 宁可**偏保守** ✓：他的线若比这细 ✓，
#   我们也只是**多让一点** ✓（不会压上去 ✗）；✗ 反之（按 8 mil 算）会**少让** ⇒ 有短路风险 ✗。
KEEP_W_MM = 24 * 0.0254

MM = RT.MM

# ★ 走线颜色：**只用 Fritzing 官方配色表里的值** ✓（`ratsnestcolors.xml` 的 breadboardView 那组 ✓）
#   黑 = `#404040` ✓（**不是** `#000000` ✗）、红 = `#cc1414` ✓（见仓规 §5b 第 11 条 ✓）。
NET_COLOR = {
    "GND": "#404040", "5V": "#cc1414", "BR+": "#a37911",
}
PALETTE = ["#418dd9", "#25cc35", "#fff800", "#ef6100", "#33ffc5", "#ab58a2",
           "#8c3b00", "#fa50e6", "#999999"]
# ★ 线宽：**只用 Fritzing 那六档** ✓（用户 2026-09-30 定 ✓；下拉里就这六个 ✓）
#   ✗ 我先前写的 `mils="9.8425"`（= 自创的 0.25 mm ✗）在面板里**认不出来** ✗。
#   ⇒ 写进去的就是档位原值 ✓（`RT.MIL_TIERS` / `RT.TRACE_MIL` 一份实现 ✓）。


def key(x, y, lay=None):
    k = (round(x, 3), round(y, 3))
    return k if lay is None else (k[0], k[1], lay)


# ★★ 端点归并容差 ✓（2026-10-01 ✓）：0.18 内部单位 ≈ **0.051 mm** ✓ ——
#   布线格是 0.15 mm（0.53 单位 ✓）⇒ 容差保持在**半格以内**就不可能把相邻格点并掉 ✓。
SNAP_U = 0.18


def split_touchings(segs, tol=1e-6):
    """把「端点落在**别人线段内部**」的地方切开 ✓ ⇒ 之后每段两端都只与**端点**相接 ✓

    全仓的线都是**横平竖直** ✓（4 邻域 A* ✓）⇒ 判"在内部"很简单 ✓。
    ★ 切点必须用**原来的浮点坐标** ✓ —— ✗ 老版拿 `key()`（round 到 1e-3）当切点 ✗
      ⇒ 新端点跟邻居差 1e-4 级 ✗ ⇒ 谁也接不上 ✗（先例：焊盘中心两套算法差 0.05 mm ✗）。
    """
    out = list(segs)
    changed = True
    while changed:
        changed = False
        pts = []
        for lay, a, b in out:
            pts.append((lay, a))
            pts.append((lay, b))
        new = []
        for lay, a, b in out:
            cut = []
            for lay2, p in pts:
                if lay2 != lay or p == a or p == b:
                    continue
                if abs(a[1] - b[1]) < tol:                     # 横线 ✓
                    if abs(p[1] - a[1]) < tol and min(a[0], b[0]) + tol < p[0] < max(a[0], b[0]) - tol:
                        cut.append(p)
                elif abs(a[0] - b[0]) < tol:                   # 竖线 ✓
                    if abs(p[0] - a[0]) < tol and min(a[1], b[1]) + tol < p[1] < max(a[1], b[1]) - tol:
                        cut.append(p)
            if not cut:
                new.append((lay, a, b))
                continue
            changed = True
            if abs(a[1] - b[1]) < tol:
                seq = sorted([a] + cut + [b], key=lambda q: q[0])
            else:
                seq = sorted([a] + cut + [b], key=lambda q: q[1])
            for i in range(len(seq) - 1):
                if seq[i] != seq[i + 1]:
                    new.append((lay, seq[i], seq[i + 1]))
        out = new
    return out


def split_neck(seg, zones, narrow_mil, wide_mil):
    r"""把一段线在**缩宽区边界**切开 ✓ ⇒ `[(lay, a, b, mil), …]` ✓（2026-10-01 ✓）

    ★★ 为什么必须切 ✗（2026-10-01 定 ✓）：缩宽只是**局部**的 ✓（进细间距件前 1.5 mm ✓）
      —— ✗ 若按“一端落在区里就把**整根**变细”✗ ⇒ 一条跑了 5 mm 的 GND 会变成 10 mil ✗
      （载流能力白丢 ✗）；✗ 反之若整根保持 24 mil ✗ ⇒ 区里那截仍然盖到邻盘 ✗（就是那个短路 ✓）。
    ★ 线都是**横平竖直** ✓（4 邻域 A* ✓）⇒ 只需在直线方向上取区间 ✓。
    """
    lay, a, b = seg
    # ★★ 2026-10-02 补 ✗✓：**缩宽档与本线同宽 ⇒ 切开毫无意义** ✗
    #   实测（用户 2026-10-02 看到「**有些连线上有一些多余的点**」✗）：本板所有线都是 8 mil ✓、
    #   而缩宽档 `NECK_MIL` 也是 8 ✓ ⇒ 切出来的碎段**宽度一模一样** ✗，纯属多余 ✓；
    #   而**每个碎段端点**在 Fritzing / 渲染器里都会**画一个结点** ✗
    #   （实测：区界上留了一堆 **60 µm** 的碎段 ✓，还有成对反向的重复段 ✓）
    #   ⇒ 就是用户看到的那些点 ✓✓。⇒ 同宽不切 ✓。
    if narrow_mil >= wide_mil:
        return [(lay, a, b, wide_mil)]
    hor = abs(a[1] - b[1]) < 1e-6
    ver = abs(a[0] - b[0]) < 1e-6
    if not (hor or ver):
        # ★★ 斜段 ⇒ **不切** ✗（2026-10-01 补 ✓）：切法（下面的 `xs`）只对**横平竖直**成立 ✓
        #   ⇒ ✗ 拿斜段当竖段切 ⇒ 会把端点**搬走** ✗（实测：这就是 17 处悬空端点的**放大器** ✓，
        #     真正的源头是布线器的“吸附端点”造出 33 条斜段 ✓，已在 `pcb_route._snap_ends` 修掉 ✓）。
        #   ⇒ 这里原样放行 ✓（宁可不缩宽，也绝不改几何 ✗）。
        return [(lay, a, b, wide_mil)]
    if hor:
        lo, hi = min(a[0], b[0]), max(a[0], b[0])
    else:
        lo, hi = min(a[1], b[1]), max(a[1], b[1])
    cuts = set()
    for (zb, _w) in zones:
        if hor:
            if not (zb[1] <= a[1] <= zb[3]):
                continue
            lo2, hi2 = max(lo, zb[0]), min(hi, zb[2])
        else:
            if not (zb[0] <= a[0] <= zb[2]):
                continue
            lo2, hi2 = max(lo, zb[1]), min(hi, zb[3])
        if lo2 < hi2:
            cuts.add(lo2)
            cuts.add(hi2)
    if not cuts:
        return [(lay, a, b, wide_mil)]
    xs = sorted({lo, hi} | cuts)
    out = []
    for i in range(len(xs) - 1):
        p, q = xs[i], xs[i + 1]
        mid = (p + q) / 2.0
        px, py = (mid, a[1]) if hor else (a[0], mid)
        mil = narrow_mil if RT.in_neck(px, py, zones) else wide_mil
        pa = (p, a[1]) if hor else (a[0], p)
        pb = (q, a[1]) if hor else (a[0], q)
        out.append((lay, pa, pb, mil))
    # ★ 保持与输入**同向** ✓（a→b ✓）：调用方按端点建表 ✓，方向本身不影响连通 ✓，但保持一致便核对 ✓
    if not hor and b[1] < a[1]:
        out = [(l2, p2, q2, m2) for (l2, p2, q2, m2) in reversed(out)
               for (p2, q2) in ((q2, p2),)]
    elif hor and b[0] < a[0]:
        out = [(l2, q2, p2, m2) for (l2, p2, q2, m2) in reversed(out)]
    return out


def merge_collinear(wires, keep):
    r"""把**同网同层、首尾相接、方向相同**的碎段并成一条 ✓（图更干净 ✓）

    ★ 用户 2026-09-30 点名 ✓（原话："布线很乱" ✓ —— 129 条线跑 9 张网 ✓，很多 0.1～0.5 mm 碎段 ✓）。
    ★★ 规矩 ✗：**不许跨过连接点** ✓ —— 焊盘心 ✓、过孔 ✓、**两条以上线汇聚的点** ✓
      （Fritzing 的 `<connect>` 只认**端↔端** ✓ ⇒ 跨过连接点合并会把那条连接弄丢 ✗）。
      ⇒ `keep` 就是这些点 ✓；只合并"该点上恰好只有这两个端"的相邻段 ✓。
    ★★ `mils` 也必须相同才能并 ✗（2026-10-01 ✓）：缩宽段的 `10 mil` 与粗段的 `24 mil`
      不是同一种铜 ✓ ⇒ 并了就把缩宽作废了 ✗（短路会回来 ✓）。
    """
    out = list(wires)
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                ni, li, ai, bi, mi = out[i]
                nj, lj, aj, bj, mj = out[j]
                if ni != nj or li != lj or mi != mj:
                    continue
                hit = None
                # ★ 规范成 (起点1, 终点1, 起点2, 终点2) ✓；要求 **终点1 == 起点2** ✓
                #   ✗ 我第一版把判据写成 `start1 != end2` ✗ ⇒ 一条都没并成 ✗（实测 v37 == v35 ✓）。
                for s1, e1, s2, e2 in ((ai, bi, aj, bj), (ai, bi, bj, aj),
                                       (bi, ai, aj, bj), (bi, ai, bj, aj)):
                    if e1 != s2 or e1 in keep:      # 接不上或撞连接点 ⇒ 不并 ✓
                        continue
                    if sum(1 for (n2, l2, a2, b2, _m2) in out
                           if l2 == li and (a2 == e1 or b2 == e1)) != 2:
                        continue                     # 该点还有别的端 ⇒ 是汇聚点 ✗
                    v1 = (e1[0] - s1[0], e1[1] - s1[1])
                    v2 = (e2[0] - s2[0], e2[1] - s2[1])
                    if abs(v1[0] * v2[1] - v1[1] * v2[0]) > 1e-9:
                        continue                     # 不同向（有拐角 ✓）⇒ 保留拐点 ✓
                    if v1[0] * v2[0] + v1[1] * v2[1] <= 0:
                        continue                     # 反方向（折回去 ✓）⇒ 不并 ✓
                    hit = (ni, li, s1, e2, mi)
                    break
                if hit:
                    out[i] = hit
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    return out


def declared_layers(text):
    r"""⇒ `{(modelIndex, connectorId): 该 connector 在 pcbView 里声明的 layer}` ✓

    ★★ 为什么必须用它 ✗✓（2026-09-30 实测 ✓）：`pcb_check.collect` 报的层是**推导**出来的
      （背面件要翻面 ✓），与文件里 connector 那行**声明的字面值不总一样** ✗ ——
      v29 里实测 **27 处对不上** ✗（我写 `copper0` ✗、文件声明 `copper1` ✓；
      THT 盘更被我写成 `both` ✗ —— **`both` 根本不是合法的层名** ✗）；
      而 **Fritzing 自己重存同一份草图时把这 27 处全纠正成"文件声明的层"** ✓
      （`_work/dl` 系列对照 ✓：重存后的文件里 **266 处全部对得上** ✓）。
      ⇒ 照抄**文件声明值** ✓ 才是对的口径 ✓（仓规：拿 Fritzing 自己的产物当权威 ✓）。
    """
    out = {"breadboardView": {}, "schematicView": {}, "pcbView": {}}
    for b in re.findall(r'(?ms)^[ \t]*<instance\b.*?\n[ \t]*</instance>', text):
        mi = re.search(r'modelIndex="(\d+)"', b)
        if not mi:
            continue
        for view in out:
            m = re.search(r'(?ms)<%s\b[^>]*>.*?</%s>' % (view, view), b)
            if not m:
                continue
            for cid, lay in re.findall(r'<connector connectorId="([^"]*)" layer="([^"]*)"',
                                       m.group(0)):
                out[view].setdefault((mi.group(1), cid), lay)
    return out


def decl_layer(decl, mi, cid):
    r"""取**文件里声明的层** ✓ ⇒ 精确查不到时退回"该实例 pcbView 里唯一那个铜层" ✓

    ★ 为什么需要兜底 ✗✓（实测 ✓）：`U1.connector20`（EPAD）原来**没有条目** ✗
      ⇒ 精确查不到 ✗ ⇒ 退回推导层 `copper0` ✗，可它同块 20 个 connector **都声明 `copper1`** ✓
      ⇒ 线那侧就与（我们新建的）条目**对不上** ✗（实测 2 处 ✓）。
    """
    d = decl.get("pcbView", {}).get((mi, cid))
    if d:
        return d
    lays = {l for (m, _c), l in decl.get("pcbView", {}).items()
            if m == mi and "copper" in (l or "")}
    return lays.pop() if len(lays) == 1 else None


def _why_miss(res, net, lay, p):
    r"""✗ 报「悬空端点」时顺手查**源头** ✓（2026-10-01 立 ✓，`--why` 打开 ✓）

    `res` = **布线器产物** ✓（它的自检是干净的 ✓：孤立端点 0 ✓，实测 ✓）
    ⇒ 所以只要看：`res` 里离这个悬空端点**最近的端点**在哪、多远 ✓：
      · 差 ≈ 0（≤ 3×`SNAP_U` ✓）⇒ 这个点**本来是端点** ✓、被写回**搬走**了 ✗（元凶 ✓）；
      · 差很大 ⇒ 这个点**本来不是**端点 ✓（是**切段**切出来的新点 ✓）
        ⇒ 那就说明它的**对家那一截丢了** ✗ 或 **mil 不同没并上** ✗。
    """
    segs = (res.get(net) or {}).get("segs") or ()
    best = None
    for (l2, a2, b2) in segs:
        for q2 in (a2, b2):
            dd = math.hypot(q2[0] - p[0], q2[1] - p[1])
            if best is None or dd < best[0]:
                best = (dd, l2, q2)
    for v in (res.get(net) or {}).get("vias") or ():
        dd = math.hypot(v[0] - p[0], v[1] - p[1])
        if best is None or dd < best[0]:
            best = (dd, "过孔", v)
    if best is None:
        return "｜✗ `res` 里这张网没有任何端点"
    same = "同层" if best[1] == lay else ("另层 %s" % best[1])
    # ★ 把**这个点上的搭子**列出来 ✓（`res` 里以该点为端点的**其它**段 ✓ ⇒ 它就是被弄丢的那一截 ✓）：
    near = []
    for (l2, a2, b2) in segs:
        for q2, q3 in ((a2, b2), (b2, a2)):
            if math.hypot(q2[0] - p[0], q2[1] - p[1]) <= SNAP_U:
                near.append("%s 段(%.3f,%.3f)→(%.3f,%.3f)"
                            % (l2, MM(q3[0]), MM(q3[1]), MM(q2[0]), MM(q2[1])))
    for v in (res.get(net) or {}).get("vias") or ():
        if math.hypot(v[0] - p[0], v[1] - p[1]) <= SNAP_U:
            near.append("过孔")
    tail = ("｜该点上的搭子：%s" % "︱".join(near[:3])) if near else "｜该点上**没有搭子** ✗"
    if best[0] <= SNAP_U * 3:
        return ("｜✗ `res` 端点**就在原位**（%s ✓，差 %.3f mm）⇒ 是**写回搬走**的 ✗%s"
                % (same, MM(best[0]), tail))
    return ("｜✓ `res` 最近端点 %s 差 %.3f mm ⇒ 这个点**本是切出来的** ✓"
            "（说明对家那截丢了 ✗ 或 mil 不同没并上 ✗）%s"
            % (same, MM(best[0]), tail))


# ★★ 临时诊断开关 ✓（2026-10-01 ✓）：`--nomerge` ⇒ 跳过最后的「合并同向同 mil 段」✓
#   用途：一次实验就能分辨「断头是**合并**弄的 ✗ 还是**切段/归并**弄的 ✗」。
NO_MERGE = []


def build_xml(text, res, model, pads, *, color_map=None, mil_of=None, net_pads=None):
    """把布线结果变成 XML 实例片段 ✓ ⇒ `(xml, stats)`"""
    # ★★ 焊盘 → 网名 ✓（2026-10-01 加 ✓，给下面那道硬闸门用 ✓）
    pad2net = {}
    for _n, _lst in (net_pads or {}).items():
        for _k in _lst:
            pad2net[_k] = _n
    mil_of = mil_of or (lambda n: RT.TRACE_MIL)     # ★ 按网分宽 ✓（没给 ⇒ 全局那档 ✓）
    # ── 1. 端点 → 接什么 ✓ ─────────────────────────────────────────────
    # ★ 焊盘要读 `model["pads"]` ✓（`pcb_check.collect` 那份 ✓：有 `thr`/`layer`/`cid`/`mi` ✓）
    #   ✗ 别用 `pcb_route.pad_index()` 那份 ✗ —— 那是布线器内部用的另一种结构（没有 `thr` ✗）。
    pad_at, via_at = {}, {}
    for q in model["pads"]:
        for lay in PC.pad_layers(q):
            pad_at[key(q["c"][0], q["c"][1], lay)] = q
    decl = declared_layers(text)      # ★ 目标 connector 在文件里声明的层 ✓（见函数注释 ✓）
    # ★★ 细间距**缩宽区** ✓（2026-10-01 用户定 ✓）：zones = 每个细间距盘框外扩 1.5 mm ✓
    zones = RT.neck_zones(pads)
    wire_at = {}
    raw = []                                      # (net, lay, a, b, mil) 碎段 ✓
    # ★★★ 写回的流水顺序 ✗✓（2026-10-01 定案 ✓，实测把 17 处悬空端点治掉的**唯一**原因 ✓）：
    #     ① 按缩宽区**切段**（只切、先不标 mil ✓）
    #     ② **端点归并**（全局一起做 ✓ —— 两侧必须拿到**同一个 rep** ✓）
    #     ③ **拓扑整理**（`split_touchings` ✓）—— ★ 必须在②**之后** ✗
    #     ④ 按位置标 mil ✓（`in_neck` 看中点 ✓）
    #     ⑤ 合并同向同 mil 段 ✓（`merge_collinear` ✓）
    #   ✗ 旧顺序是 ①→③→② ✗ ⇒ 端点归并把端点挪了 ≤0.051 mm ✓，而它的对家往往是
    #     **另一条线段的中段**（T 型 ✓）⇒ 挪开就**断** ✗。实测证据 ✓：路由器产物自检
    #     **孤立端点 0** ✓（布线器是干净的 ✓），而对账发现 `res` 的端点有 **19 个“消失”** ✗
    #     ＝ 被②搬走了 ✓ ⇒ 对不上 ⇒ 报成 17 处「悬空端点」✗。
    pre = []                                       # (net, lay, a, b) ✓
    for net in sorted(res):
        d = res[net]
        for seg in d["segs"]:
            for (l2, p2, q2, _m2) in split_neck(seg, zones, RT.NECK_MIL, mil_of(net)):
                pre.append((net, l2, p2, q2))
    # ★ 先合并同向碎段 ✓（用户点名 ✓）—— ✗ 必须放在 `wire_at` **之前** ✓：
    #   合并后端点变了 ✓，`wire_at` 要按**合并后**的端点建表 ✓，否则连接对不上 ✗。
    keep = set()
    for q in model["pads"]:
        keep.add(key(q["c"][0], q["c"][1]))
    for net in sorted(res):
        for v in res[net]["vias"]:
            keep.add(key(v[0], v[1]))
    # ★★ 端点归并（vertex snap）✓（2026-10-01 实测定案 ✓，容差 `SNAP_U` = 0.051 mm ✓）：
    #   ✗ 症状：写回器报一堆「端点谁也没接上，最近差 0.025 / 0.050 mm」✗ ——
    #     它们其实是**同一个节点** ✓，只是浮点值相差 < 容差、又正好落在
    #     `key()`（round 到 1e-3 ✓）取整的**两侧** ✗ ⇒ 表里对不上 ✗。
    #   ✓ 做法：把**焊盘心 / 过孔心**当种子 ✓（它们是权威坐标 ✓），其余端点吸附到
    #     容差内已存在的点上 ✓ ⇒ 两侧拿到**同一个值** ✓。
    #   ★★ 容差为什么是 0.18 内部单位（= 0.051 mm ✓）：布线格 = 0.15 mm ✓（0.53 单位 ✓）
    #     ⇒ 容差 < 半格就**不可能**把两个相邻格点并掉 ✓（并错了会把线拉歪 ✗）。
    #   ★★★ 吸附点必须**按网**筛 ✗✓（2026-10-01 定案 ✓，**就是那 4 处短路的根因** ✓）：
    #     ✗ 原来把**所有焊盘中心**都当吸附点 ✗ ⇒ 一个离它 0.03∼0.05 mm 的端点
    #       （= A* **格心** ✓，最大偏半格 0.075 mm ✓）会被硬吸到**隔壁那张网**的盘心上 ✗✗
    #       ⇒ 实测：`U1.connector2`(PA2/DATA_IN) 与 `connector3`(VSS/GND) **只差 0.400 mm** ✓
    #       ⇒ 一步就换来「`DATA_IN` 的线结到 `GND` 的盘」4 处 ✗（独立复核 ④×4 + ⑤×4 ✓）。
    #     ✓ 现在：盘心只有当它**属于本网**时才允许吸附 ✓；过孔心与别的一般端点照旧 ✓。
    pad_net = {}
    for _n, _lst in (net_pads or {}).items():
        for _k in _lst:
            pad_net[_k] = _n
    pad_rep = {}
    reps = []
    for q in model["pads"]:
        r = (q["c"][0], q["c"][1])
        reps.append(r)
        pad_rep[(round(r[0], 6), round(r[1], 6))] = (q["title"], q["cid"])
    for net in sorted(res):
        for v in res[net]["vias"]:
            reps.append((v[0], v[1]))

    def _snap(p, net=None):
        for r in reps:
            if abs(p[0] - r[0]) > SNAP_U or abs(p[1] - r[1]) > SNAP_U:
                continue
            k2 = pad_rep.get((round(r[0], 6), round(r[1], 6)))
            if k2 is not None and net is not None and pad_net.get(k2) != net:
                continue                   # ✗ 别的网的盘心 ⇒ **不许吸** ✓（不然就是短路 ✗）
            return r
        reps.append(p)
        return p

    snapped = []                                   # (net, lay, a, b) ✓（已归并 ✓）
    for (net, lay, a, b) in pre:
        a2, b2 = _snap(a, net), _snap(b, net)
        if a2 != b2:                               # 归并后可能变零长 ⇒ 丢掉 ✗
            snapped.append((net, lay, a2, b2))
    # ★★ 逐阶段追踪 ✓（2026-10-01 ✓，`--why` 打开 ✓）：盯住 `U1` 那两颗**相邻**脚
    #   （`connector2` = PA2 / DATA_IN ✓、`connector3` = VSS / GND ✓，相距 0.400 mm ✓）
    #   ⇒ 看**哪一步**把端点放到了“隔壁那颗脚”的盘心上 ✗（实测写回后 4 处结错网 ✓）。
    def _watch_pts():
        out = []
        for q in model["pads"]:
            if q["title"] == "U1" and q["cid"] in ("connector2", "connector3"):
                out.append((q["cid"], q["c"]))
        return out

    def _stage(tag, seq):
        if not RT.DIAG["on"]:
            return
        for (cid, c) in _watch_pts():
            hits = []
            for it in seq:
                n2, l2, a2, b2 = it[0], it[1], it[2], it[3]
                if ((abs(a2[0] - c[0]) < 1e-6 and abs(a2[1] - c[1]) < 1e-6)
                        or (abs(b2[0] - c[0]) < 1e-6 and abs(b2[1] - c[1]) < 1e-6)):
                    hits.append("%s/%s" % (n2, l2))
            if hits:
                print("      [%s] `U1.%s` 的盘心上有端点：%s"
                      % (tag, cid, " , ".join("%s" % h for h in hits)))
    _stage("①缩宽切段", [(n2, l2, a2, b2) for (n2, l2, a2, b2) in pre])
    _stage("②端点归并", snapped)
    # ③ 拓扑整理 ✓（**按网**做 ✓ —— 不同网相碰是**短路** ✗，绝不能“顺手接上” ✗）
    for net in sorted(res):
        cut = [(l2, p2, q2) for (n2, l2, p2, q2) in snapped if n2 == net]
        wide = mil_of(net)
        for (l2, p2, q2) in split_touchings(cut):
            mx, my = (p2[0] + q2[0]) / 2.0, (p2[1] + q2[1]) / 2.0
            m2 = RT.NECK_MIL if RT.in_neck(mx, my, zones) else wide
            raw.append((net, l2, p2, q2, m2))
    _stage("③拓扑整理", raw)
    # ★★ 端点集合对账 ✓（2026-10-01 立 ✓，`--why` 打开 ✓）：
    #   路由器产物 `res` **自检是干净的** ✓（孤立端点 0 ✓，实测 ✓）—— 所以「悬空端点」一定是
    #   **写回这一段**（缩宽切段 / 拓扑整理 / 端点归并 / `key()` … ✗）弄出来的 ✗。
    #   判据：拿 `res` 的端点集合与写回后 `wires` 的端点集合**对一遍** ✓ ——
    #   ① `res` 有、`wires` 没有 ⇒ 端点被**搬走**了 ✗（元凶 ✓）；② `wires` 多出来的是切段 ✓（正常 ✓）。
    if RT.DIAG["on"]:
        def _ends(segs):
            s = set()
            for (lay, a, b) in segs:
                s.add((key(a[0], a[1], lay)))
                s.add((key(b[0], b[1], lay)))
            return s
        e_res = set()
        for net in sorted(res):
            e_res |= _ends(res[net]["segs"])
            for v in res[net]["vias"]:
                for lay in ("copper0", "copper1"):
                    e_res.add(key(v[0], v[1], lay))
        e_out = set()
        for (net, lay, a, b, _m) in raw:
            e_out.add(key(a[0], a[1], lay))
            e_out.add(key(b[0], b[1], lay))
        gone = sorted(e_res - e_out)
        add = sorted(e_out - e_res)
        print("   ⇒ **端点对账** ✓：`res` %d 个 ✓｜写回后 %d 个 ✓｜**消失 %d** ✗｜新切出 %d ✓"
              % (len(e_res), len(e_out), len(gone), len(add)))
        for k in gone[:8]:
            print("       ✗ 消失：(%.3f, %.3f) 层 %s" % k)
    wires = raw if NO_MERGE else merge_collinear(raw, keep)
    _stage("④合并后", wires)
    stats_raw = len(raw)
    stats_neck = sum(1 for w in wires if w[4] == RT.NECK_MIL)
    vias = [(net, v) for net in sorted(res) for v in res[net]["vias"]]
    for i, (net, lay, a, b, _mil) in enumerate(wires):
        for k, p in ((0, a), (1, b)):
            wire_at.setdefault(key(p[0], p[1], lay), []).append((i, k))
    # ── 1b. ★★ **文件里已有的线 / 过孔**也要当"能接的对象" ✓（2026-10-02 补 ✗）──────
    #   起因（用户 2026-10-02 ✓）：要把**剩下的孤脚接到他手画的总线**上 ✓ ⇒ 新线的另一头
    #     落在**已有线**上 ✗ —— ✗ 旧版只认"本次新写的线" ✗ ⇒ 那端**写不出 `<connect>`** ✗
    #     ⇒ 铜是通的 ✓、但 Fritzing 里显示"没接上" ✗（用户会以为白布了 ✓）。
    #   ★ 查表**带容差** ✓（端点可能被下面的 vertex-snap 挪 ≤ 0.05 mm ✓）。
    #   ★ 同时要给**已有线那一侧**补回指 ✓（`edits` ✓，与焊盘同一套 ✓）。
    ex_wire, ex_via = [], []
    for _t in (model.get("traces") or ()):
        if not _t.get("inst"):
            continue
        for _k2, _p2 in ((0, _t["a"]), (1, _t["b"])):
            ex_wire.append((_p2[0], _p2[1], _t["layer"], _k2, _t["inst"]))
    for _v in (model.get("vias") or ()):
        if _v.get("inst"):            # 过孔贯通两层 ✓ ⇒ 查表不看层 ✓
            ex_via.append((_v["p"][0], _v["p"][1], _v["inst"]))
    EX_SNAP_U = 0.25                  # 草图单位 ✓ ≈ 0.07 mm ✓

    def _near(lst, p, lay=None):
        best = None
        for it in lst:
            if lay is not None and it[2] != lay:
                continue
            d = math.hypot(it[0] - p[0], it[1] - p[1])
            if d <= EX_SNAP_U and (best is None or d < best[0]):
                best = (d, it)
        return None if best is None else best[1]

    # ── 2. 排号 ✓ ──────────────────────────────────────────────────────
    used = [int(x) for x in re.findall(r'modelIndex="(\d+)"', text)]
    nxt = max(used) + 1 if used else 90000001
    wt = [int(x) for x in re.findall(r"<title>Wire(\d+)</title>", text)]
    vt = [int(x) for x in re.findall(r"<title>Via(\d+)</title>", text)]
    wn = max(wt) + 1 if wt else 1
    vn = max(vt) + 1 if vt else 1
    for i, v in enumerate(vias):
        via_at[key(v[1][0], v[1][1])] = dict(mi="%d" % (nxt + i), i=i)
    base_mi = nxt + len(vias)
    wmi = ["%d" % (base_mi + i) for i in range(len(wires))]
    new_mis = set(wmi) | {d["mi"] for d in via_at.values()}   # ★ 本次新写的实例号 ✓
    #   ✗ 别写 `{v["mi"] for v in vias}` ✗ —— 这里的 `vias` 是 `(net, p)` **元组** ✗（踩过 ✓）

    # ── 3. 生成 ✓ ──────────────────────────────────────────────────────
    color_map = color_map or {}
    stats = dict(wires=len(wires), vias=len(vias), open_ends=0, multi=0, misses=[],
                 raw=stats_raw, necks=stats_neck, cross=[])
    edits = []            # ★ 目标侧的回指 ✓（写回时补进原文件 ✓ ⇒ 两侧都写 ✓，照 Fritzing ✓）
    blocks, vblocks = [], []
    for i, (net, lay, a, b, mil) in enumerate(wires):
        conns = []
        for k, p in ((0, a), (1, b)):
            tgt = None
            q = pad_at.get(key(p[0], p[1], lay))
            if q is not None:
                # ★★ 2026-09-30 修 ✗：第三个字段（= 写进 `<connect layer="…">` 的）必须是
                #   **对方那一层的名字** ✓，**不是**走线自己的层 ✗ —— 拿 Fritzing 自己写的
                #   `single-channel.fzz` 逐字对照 ✓：一条 `copper1trace` 的线接 THT 盘时，
                #   写的是 `layer="copper0"` ✓（= **焊盘**所在的层 ✓）。
                #   ✗ 旧写法写 `lay`（= 线的层 ✗）⇒ 底层 SMD 盘被写成 `layer="copper1"` ✗
                #     ⇒ 那个盘**根本不在 copper1 上** ✗ ⇒ Fritzing 判无效、**整组线看不见** ✗
                #     （用户：「我看了 pixel-pcb-v26.fzz …… **没有布线**」✗）。
                # ★★ 写进 `<connect layer=…>` 的必须是"**文件里那个 connector 声明的层**" ✓
                #   —— 不是 collect 推导的层 ✗（实测 27 处对不上 ✗，见 `declared_layers` ✓）
                #   ✗ 坑（自己踩过 ✓）：`declared_layers` 外层键是**视图名** ✗ ⇒
                #     写成 `decl.get((mi, cid))` 就永远取不到 ✗、静默退回推导层 ✗
                #     （v31/v32/v33 因此又错了 27 处 ✗）。
                dlay = decl_layer(decl, q.get("mi") or "", q.get("cid") or "connector0")
                tgt = (q.get("cid") or "connector0", q.get("mi") or "",
                       dlay or q.get("layer") or lay)
                # ★ 记下"焊盘那侧的回指" ✓（见 `add_backrefs` ✓）
                if q.get("mi"):
                    edits.append((q["mi"], q.get("cid") or "connector0",
                                  dlay or q.get("layer") or lay,
                                  "connector%d" % k, wmi[i], lay + "trace"))
            if tgt is None and key(p[0], p[1]) in via_at:
                v = via_at[key(p[0], p[1])]
                tgt = ("connector0", v["mi"], "copper0")
            if tgt is None:
                cand = [w for w in wire_at.get(key(p[0], p[1], lay), []) if w[0] != i]
                if len(cand) > 1:
                    stats["multi"] += 1
                if cand:
                    tgt = ("connector%d" % cand[0][1], wmi[cand[0][0]], lay + "trace")
            # ★★ 2026-10-02 补 ✗：再退一步 —— 接在**文件里已有的线 / 过孔**上也行 ✓
            ex_tgt = False
            if tgt is None:
                _v2 = _near(ex_via, p)
                if _v2 is not None:
                    tgt, ex_tgt = ("connector0", _v2[2], "copper0"), True
            if tgt is None:
                _w2 = _near(ex_wire, p, lay)
                if _w2 is not None:
                    tgt, ex_tgt = ("connector%d" % _w2[3], _w2[4], lay + "trace"), True
            if tgt is None:
                stats["open_ends"] += 1
                if len(stats["misses"]) < 6:
                    best = None
                    for kk, q in pad_at.items():
                        dd = math.hypot(q["c"][0] - p[0], q["c"][1] - p[1])
                        if best is None or dd < best[0]:
                            best = (dd, "pad %s.%s(%s)" % (q.get("title"), q.get("cid"), kk[2]))
                    for kk, lst in wire_at.items():
                        for wi, _wk in lst:
                            if wi == i:
                                continue
                            dd = math.hypot(kk[0] - p[0], kk[1] - p[1])
                            if best is None or dd < best[0]:
                                best = (dd, "wire#%d(%s)" % (wi, kk[2] if len(kk) > 2 else ""))
                    for kk, vv in via_at.items():
                        dd = math.hypot(kk[0] - p[0], kk[1] - p[1])
                        if best is None or dd < best[0]:
                            best = (dd, "via mi=%s" % vv["mi"])
                    stats["misses"].append(
                        "%s 线#%d 端%d 在 (%s, %s) 层 %s ⇒ 最近: %s 差 %s mm%s"
                        % (net, i, k, PW.fmt(p[0]), PW.fmt(p[1]), lay,
                           best[1] if best else "-",
                           ("%.3f" % MM(best[0])) if best else "-",
                           _why_miss(res, net, lay, p) if RT.DIAG["on"] else ""))
                continue
            conns.append((k, tgt))
            # ★ 目标若是**已有线 / 过孔**（不是本次新写的 ✓）⇒ 那侧也要补回指 ✓
            #   （照 Fritzing 自己"两侧都写"的口径 ✓，见 `add_backrefs` 的注释 ✓）
            if ex_tgt and tgt[1] and tgt[1] not in new_mis:
                edits.append((tgt[1], tgt[0], tgt[2], "connector%d" % k, wmi[i], lay + "trace"))
            # ★★ 硬闸门 ③ ✓（2026-10-01 ✓）：这条线的一端结的盘 **不许属于别的网** ✗。
            #   起因（实测 ✓）：文件里出现一根 10 mil 的线，两端正好是 `U1.connector2`（DATA_IN）
            #   与 `U1.connector3`（GND）✗ ⇒ 直接短路 ✗；而**路由器**三条自检全 0 ✓
            #   （含在**最终解**上跑的那条 ✓）⇒ 说明是**写回**把它接错的 ✓。
            if q is not None:
                _pk = (q["title"], q["cid"])
                _pn = pad2net.get(_pk)
                if _pn is not None and _pn != net:
                    stats["cross"].append("%s 线#%d 端%d 结到 `%s.%s`（属 `%s`）✗"
                                          % (net, i, k, _pk[0], _pk[1], _pn))
        color = color_map.get(net) or NET_COLOR.get(net) \
            or PALETTE[sum(ord(c) for c in net) % len(PALETTE)]
        blocks.append(wire_block(net, i, wn + i, wmi[i], lay, a, b, conns, color,
                                 mil, decl))
    for j, (net, v) in enumerate(vias):
        # ★ 过孔那侧也要写"它接的线" ✓（= 回指 ✓）—— 拿 Fritzing 自己的 `ViaModuleID`
        #   原文对出来的 ✓：它的 `connector0` 里列着两条走线 ✓（`_work/via.txt` ✓）。
        #   ✗ 旧写法整个 `<connects>` 都不写 ✗ ⇒ 一侧悬空 ✗。
        vconn = []
        for lay in ("copper0", "copper1"):
            for (wi, wk) in wire_at.get(key(v[0], v[1], lay), []):
                vconn.append(("connector%d" % wk, wmi[wi], lay + "trace"))
        seen = []
        for c in vconn:                       # 去重 ✓（一根线的两端可能都在同一个过孔上 ✓）
            if c not in seen:
                seen.append(c)
        vblocks.append(via_block(vn + j, via_at[key(v[0], v[1])]["mi"], v, j, seen))
    return "".join(blocks) + "".join(vblocks), stats, edits


def conn_xml(items, wlayer):
    """某个视图里的 `<connectors>` 片段 ✓（`items` = `[(k, 目标cid, 目标mi, 目标层)]` ✓）

    ★ 空就不写整段 ✓ —— 照 Fritzing 自己的写法 ✓（它只列"有连接"的 connector ✓：
      `sample` 里一条原理图走线就只写了 `connector1` 一个 ✓）。
    """
    out = []
    for k, cid, mi, tlay in items:
        out.append('                <connector connectorId="connector%d" layer="%s">\n'
                   '                    <geometry x="0" y="0"/>\n'
                   '                    <connects>\n'
                   '                        <connect connectorId="%s" modelIndex="%s" '
                   'layer="%s"/>\n'
                   '                    </connects>\n'
                   '                </connector>\n' % (k, wlayer, cid, mi, tlay))
    if not out:
        return ""
    return "                <connectors>\n%s                </connectors>\n" % "".join(out)


def plain(v):
    """普通小数 ✓（**不用** `%g` 的科学计数法 ✗）—— 照 Fritzing 自己写的格式 ✓

    ✗ 先例（2026-09-30 ✓）：`PW.fmt` = `%.6g` ✗ ⇒ 小到 1e-5 的值写成 `-3e-05` ✗，
      而 Fritzing 写的全是 `0` / `-0.35466` 这种普通小数 ✓（逐字对照 ✓）。
    """
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def wire_block(net, i, title_n, mi, lay, a, b, conns, color, mil, decl=None):
    """一条走线 ✓（`x/y` = 端点 1 ✓，`x1..y2` = 相对偏移 ✓）

    ★★ 2026-09-30 修两处 ✗（都是拿 Fritzing 自己写的 `single-channel.fzz` **逐字对照**出来的 ✓）：
      ① `mils` 必须用 **`--mil` 选的那一档** ✓ —— ✗ 旧写法写的是模块常量 ✗
         ⇒ 跑 `--mil=12` 写出来还是 `mils="24"` ✗（用户一眼看出"线宽不合适"✓）；
      ② 数字**不许写科学计数法** ✗ —— ✗ 旧写法用 `PW.fmt`（`%.6g` ✗）⇒ 会出现
         `y2="-3e-05"` ✗，而 Fritzing 自己写的是 `y2="0"` ✓（普通小数 ✓）。

    ★★ 2026-09-30 再修一处 ✗（有**判决性**证据 ✓）：**必须写三个视图** ✓。
      证据 ✓：Fritzing 自带 44 份样例 / 4149 条走线 ⇒ **4148 条三视图** ✓、**0 条 pcb-only** ✗；
      且用户实测：Fritzing 把我 v29 **自己重存**一遍（层已自动纠正 ✓、回指也在 ✓）后，
      我 129 条**单视图**线**一条都没算** ✗，而他手画那根**三视图**线**算上了一只脚** ✓
      （`pixel-pcb-wire-test.fzz`：42 → **41** ✓）⇒ **视图数是硬要求** ✓。
      非 PCB 两个视图怎么写 ✗：实测 Fritzing **每个视图写各自的坐标** ✓，且两视图路径
      **互不相同** ✗（同一段：PCB `(131.154,30.195)` ✓／面包板 `(152.41,39.007)` ✓）
      ⇒ **不能把 PCB 坐标抄进去** ✗（会把你手工摆的面包板画花 ✗）⇒ 用**零长度占位** ✓：
      实例在 ✓、不画线 ✓、坐标不编造 ✗；而且**只挂能对上号的真实焊盘** ✓
      （线↔线、线↔过孔在这两个视图里没有对应物 ✗ ⇒ 不写 ✓）。
    """
    f = plain
    decl = decl or {}
    vs = []
    for tag, wlayer, geo in (
            ("pcbView", lay + "trace",
             '<geometry z="%s" x="%s" y="%s" x1="0" y1="0" x2="%s" y2="%s" '
             'wireFlags="4"/>' % (f(9.5 + i * 1e-4), f(a[0]), f(a[1]),
                                  f(b[0] - a[0]), f(b[1] - a[1]))),
            ("breadboardView", "breadboardWire",
             '<geometry z="%s" x="0" y="0" x1="0" y1="0" x2="0" y2="0" '
             'wireFlags="4"/>' % f(4.0 + i * 1e-4)),
            ("schematicView", "schematicTrace",
             '<geometry z="%s" x="0" y="0" x1="0" y1="0" x2="0" y2="0" '
             'wireFlags="4"/>' % f(6.0 + i * 1e-4))):
        items = []
        for k, (cid, tmi, tlay) in conns:
            if tag == "pcbView":
                vlay = tlay
            else:
                vlay = decl.get(tag, {}).get((tmi, cid))
                if vlay is None:            # 这个视图里没对应物 ⇒ 不写 ✓（不编 ✗）
                    continue
            items.append((k, cid, tmi, vlay))
        vs.append('                <%s layer="%s">\n'
                  '                    %s\n'
                  '                    <wireExtras mils="%d" color="%s" opacity="1" '
                  'banded="0"/>\n'
                  '%s'
                  '                </%s>\n'
                  % (tag, wlayer, geo, mil, color, conn_xml(items, wlayer), tag))
    return ('        <instance moduleIdRef="WireModuleID" modelIndex="%s" '
            'path=":/resources/parts/core/wire.fzp">\n'
            '            <title>Wire%d</title>\n'
            '            <views>\n'
            '%s'
            '            </views>\n'
            '        </instance>\n' % (mi, title_n, "".join(vs)))


def via_block(title_n, mi, p, j, conns=()):
    r"""一个过孔 ✓（**只有** connector0 ✓；两端靠走线的端去连它 ✓）

    ★ `p` 是**一个点** `(x, y)` ✓ —— 别在这儿再解包成 `net, p` ✗
      （`res[net]["vias"]` 里**只有坐标** ✓，网名在外面那层 ✓）。
    ★★ `hole size` 的语义（源码判定 ✓ `mazerouter.cpp:2430` ✓）：
      `setHoleSize("<hole>,<ringThickness>")` ✓ ⇒ **「钻孔 , 环宽」** ✓，**不是盘径** ✗！
      ✗ 我原来写的 `0.4mm,0.3mm` = 孔 0.4 + 环 0.3 ⇒ **盘 Ø1.0 mm** ✗（比 0603 焊盘还大 ✗
      ⇒ 用户："过孔仍不舒服" ✓）。
      ⇒ 现在用 **`0.3mm,0.15mm`** ⇒ 盘 **Ø0.6 mm** ✓（小 40% ✓）。
      �工艺依据 ✓（PCBWay 标准能力 ✓）：**最小钻孔 0.15／<0.2 加价** ✓、**最小环宽 0.15mm** ✓
      ⇒ 0.3/0.15 是"常规、便宜、安全"那一档 ✓（常规三档 = 0.2/0.5、0.3/0.6、0.4/0.8 ✓）。
      ★★ 2026-10-01 试验后又改回 ✗：曾试过 `0.2mm,0.15mm`（盘 0.5 ✓）与 `0.2mm,0.1mm`（盘 0.4 ✓，
        嘉立创最小 ✓）—— 目的是让"过孔不许压盘"的禁落区小一点、好布通 ✓。
        **实测无效** ✗（连通 8/9 → 7/9 ✓，没变好 ✗）⇒ 按本仓规矩"量完变差就回退" ✓
        改回 **`0.3mm,0.15mm`**（盘 Ø0.6 ✓，常规且便宜那一档 ✓）。
      ★ 改这里必须**同步**改 `pcb_route.VIA_CLEAR_MM`（= 盘半径 ✓）；
        尺寸只此一处 ✓（打印与写文件共用 `_VIA_HOLE_VAL` ✓，免得报的和写的不一样 ✗）。

    ★★ 2026-09-30 补 ✗：`conns` = **它接的走线** ✓（照 Fritzing 自己的过孔原文 ✓ `_work/via.txt` ✓：
      `connector0` 里列着它接的线 ✓）；连接的 `layer` 用**那条线自己**的层 ✓（`q[2]` ✓）
      —— ✗ 别用一条统一的层 ✗（过孔两边的线可能在不同 trace 层 ✗）。
    ★★ 并跟走线一样**写三视图** ✓（Fritzing 自己的 `ViaModuleID` 也是三视图 ✓）——
      非 PCB 两个视图只写几何 ✓、不写 connectors ✓（理由同 `wire_block` ✓：不编 ✗）。
    """
    # ★★ 2026-10-01 定案 ✗：过孔的 `<geometry>` **不是铜的心** —— Fritzing 把 `<geometry>` 当
    #   **svg 画布原点** ✓，铜画在局部 `(2.45039, 2.45039)`（画布单位 = 1/72 in）上 ✓
    #   ⇒ **真铜心 = geometry + (铜半径 + 画布留白 0.56444mm)** ✓ —— ★★ 2026-10-02 修 ✗：
    #     **偏移随尺寸变** ✗（`part_box.ring_off_mm` ✓，三个实测点 ✓）⇒ 一律传
    #     `_VIA_SIZE_MM`（从 `_VIA_HOLE_VAL` 解析 ✓），✗ 不再是死的 0.86444 ✗。
    #   ⇒ 路由算出来的是**铜心** ✓ ⇒ 写文件时**要减掉这个偏移** ✓，否则 Fritzing 里
    #     （以及制造出来的板上 ✗）每个过孔都偏 0.8644 mm ✗ —— 实测：加偏移前的 v48
    #     16 个孔**全部**离开它所连的走线 ✗（19 个悬空端 ✓ + 9 个孤立孔 ✓）。
    off = PB.draw_off_units("via", _VIA_SIZE_MM)
    geo_pcb = '<geometry z="%s" x="%s" y="%s" wireFlags="32"/>' \
              % (PW.fmt(5.5 + j * 1e-4), PW.fmt(p[0] - off), PW.fmt(p[1] - off))
    geo_flat = '<geometry z="%s" x="0" y="0" wireFlags="32"/>' % PW.fmt(4.0 + j * 1e-4)
    c = ""
    if conns:
        c = ('                    <connectors>\n'
             '                        <connector connectorId="connector0" layer="copper0">\n'
             '                            <geometry x="0" y="0"/>\n'
             '                            <connects>\n'
             + "".join('                                <connect connectorId="%s" '
                       'modelIndex="%s" layer="%s"/>\n' % (q[0], q[1], q[2]) for q in conns)
             + '                            </connects>\n'
             '                        </connector>\n'
             '                    </connectors>\n')
    return ('        <instance moduleIdRef="ViaModuleID" modelIndex="%s" '
            'path=":/resources/parts/core/via.fzp">\n'
            '            <property name="hole size" value="%s"/>\n'
            '            <title>Via%d</title>\n'
            '            <views>\n'
            '                <pcbView layer="copper0">\n'
            '                    %s\n'
            '%s'
            '                </pcbView>\n'
            '                <breadboardView layer="copper0">\n'
            '                    %s\n'
            '                </breadboardView>\n'
            '                <schematicView layer="copper0">\n'
            '                    %s\n'
            '                </schematicView>\n'
            '            </views>\n'
            '        </instance>\n'
            % (mi, _VIA_HOLE_VAL, title_n, geo_pcb, c, geo_flat, geo_flat))


def add_backrefs(text, edits):
    r"""★ 给**目标侧**补回指 `<connect>` ✓（2026-09-30 ✓，拿 Fritzing 自己的文件对出来的 ✓）

    证据 ✓（`_work/fritzing_stats.py` + `docs/fritzing-sketch-format-notes.md` ✓）：
      Fritzing 自带 44 份样例 / 4137 条 PCB 走线 ⇒ **8270 处连接 100% 两侧都写** ✓、
      **缺回指 0 处** ✗；而我原来**只写走线这一侧** ✗（实测缺 **80 处** ✗）
      ⇒ 用户开图看到「**7 中的 0 网络布线完成**」✗。

    `edits` = `[(目标mi, 目标connectorId, 目标层, 源connectorId, 源mi, 源层)]` ✓
    ⇒ 在目标的 `<pcbView>` 里那个 connector 的 `<connects>` 中插一条指回走线的 connect ✓。
    幂等 ✓（已有同样的就跳过 ✓）；目标块找不到 ⇒ 记到 `why` ✓（由调用方决定写不写 ✗）。

    ★★ 定位口径（实测修 ✓）：**只在 `<pcbView>` 段内**按 `connectorId` 找 ✗ ——
      ✗ **别拿层去卡** ✗：`edits` 里的层是从 `pcb_check.collect` **推导**出来的
      （背面件要翻面 ✗），与文件里 connector 那行**声明的层字面值不一定一样** ✗
      ⇒ 实测 44 处里卡掉了 **29 处** ✗。
      （同一个 `connectorId` 在面包板/原理图/PCB 三个视图里都有 ✗ ⇒ 必须限定在 pcbView ✗）
    """
    n, miss, why, built = 0, 0, [], 0
    by_mi = {}
    for e in edits:
        by_mi.setdefault(e[0], []).append(e)
    for mi, es in by_mi.items():
        mb = re.search(r'(?ms)^[ \t]*<instance\b[^>]*modelIndex="%s".*?\n[ \t]*</instance>'
                       % re.escape(mi), text)
        if not mb:
            miss += len(es)
            why.append("instance modelIndex=%s 找不到 ✗" % mi)
            continue
        blk, cur = mb.group(0), mb.group(0)
        pv = re.search(r'(?ms)<pcbView\b[^>]*>.*?</pcbView>', cur)
        if not pv:
            miss += len(es)
            why.append("instance %s **没有 pcbView** ✗" % mi)
            continue
        seg = pv.group(0)
        for (_tmi, cid, tlay, scid, smi, slay) in es:
            cr = re.search(r'(?ms)<connector connectorId="%s"[^>]*>(.*?)\n([ \t]*)</connector>'
                           % re.escape(cid), seg)
            if not cr:
                # ★★ 目标 connector **在文件里没有条目** ✓（实测：`U1.connector20` = EPAD ✗ ——
                #  它以前既没插面包板也没接原理图 ⇒ Fritzing 不给它写实例条目 ✓，20/21 ✓）
                #  ⇒ 我们**照它自己的口径补一条** ✓：Fritzing 只给"有连接"的 connector 写条目 ✓，
                #    而现在这个脚**有了 PCB 连接** ✓ ⇒ 就该有这一条 ✓。
                #  层取**同块 pcbView 里已有 connector 的层** ✓（不编 ✗；不一致就放弃 ✓）。
                lays = set(re.findall(r'<connector connectorId="[^"]*" layer="([^"]*)"', seg))
                tail = re.search(r'(?ms)([ \t]*)</connectors>', seg)
                ind = re.search(r'(?m)^([ \t]*)<connector ', seg)
                if len(lays) == 1 and tail and ind:
                    lay, pad, cl = lays.pop(), ind.group(1), tail.group(1)
                    blk2 = ('%s<connector connectorId="%s" layer="%s">\n'
                            '%s    <geometry x="0" y="0" />\n'
                            '%s    <connects>\n'
                            '%s        <connect connectorId="%s" modelIndex="%s" layer="%s" />\n'
                            '%s    </connects>\n'
                            '%s</connector>\n'
                            % (pad, cid, lay, pad, pad, pad, scid, smi, slay, pad, pad))
                    seg = seg[:tail.start()] + blk2 + seg[tail.start():]
                    n += 1
                    built += 1
                    continue
                miss += 1
                why.append("instance %s 里找不到 connector %s ✗（且没法安全补 ✓）" % (mi, cid))
                continue
            inner, ind = cr.group(1), cr.group(2)
            tag = '                        <connect connectorId="%s" modelIndex="%s" ' \
                  'layer="%s"/>\n' % (scid, smi, slay)
            if ('connectorId="%s" modelIndex="%s"' % (scid, smi)) in inner:
                continue                       # 幂等 ✓
            if "<connects>" in inner:
                inner2 = inner.replace("</connects>", tag + ind + "</connects>", 1)
            else:
                # 没有 `<connects>` ⇒ 在 connector 的 geometry 后面补一个 ✓
                inner2 = re.sub(r'(<geometry[^/]*/>\n)', r"\1%s<connects>\n%s%s</connects>\n"
                                % (ind, tag, ind), inner, count=1)
                if inner2 == inner:            # 连 geometry 都没有 ⇒ 只报不动手 ✗
                    miss += 1
                    why.append("instance %s connector %s 里没 geometry ✗" % (mi, cid))
                    continue
            seg = seg[:cr.start()] + cr.group(0).replace(inner, inner2, 1) + seg[cr.end():]
            n += 1
        text = text.replace(blk, cur[:pv.start()] + seg + cur[pv.end():], 1)
    return text, n, miss, why, built


def fill_net_decls(edits, model, net_pads):
    r"""★★ 给**每张网的每只脚**都挂上一条 PCB 声明 ✓ —— 哪怕它那一段**没布通** ✗。

    ✗✗ 病因（2026-10-06 **量实** ✓，推翻了我上一轮的"幽灵"解释 ✗）：
      Fritzing 的「**一张网由哪些脚组成**」是靠**声明**算的 ✓
        （`sketchwidget.cpp:7049` → `ConnectorItem::collectEqualPotential(…RatsnestFlag)` ✓）；
      ✗ 一只脚若在 **pcbView 里 0 条声明** ✗ ⇒ 它**不属于任何一张网** ✗ ⇒
      `scoreOneNet` 里 `num_nodes==1` 的那些"网"因 `gotUserConnection==false`
      **被直接丢掉** ✗（`graphutils.cpp:502` ✓）⇒ **那张网少算一只脚** ⇒
      剩下两只**有走线连着** ✓ ⇒ `anyMissing=false` ⇒ **状态栏说「布线完成」** ✗✗。
      ⇒ v70（`RC` 三只脚一条线都没有 ✗）与 v71（只有 `U1.connector1` 孤着 ✗）**是同一个病** ✓。
      ★★ 铁证 ✓：用户那份 **v69**（它说 **7/9** ✓）里，`RC` 三只脚在 pcbView 里
        **各有 1–2 条声明** ✓（`_work/_cmp_nets.py` ✓ 逐视图量过 ✓）；
        而 v71 的 `U1.connector1` 是 **0 条** ✗ —— 就差这里 ✓。

    ★ 做法（**不编造** ✗）：对每张网取一条**已有的**回指（它带着真的源端
      `源connectorId/源mi/源层` ✓）当**样板** ✓，**克隆**给同网里缺声明的脚 ✓
      （目标的 `mi/cid/lay` 用那只脚**自己的** ✓）。
      ⇒ 与 `add_backrefs` 同一条写入路径 ✓、同样幂等 ✓，✗ 不动任何已有声明 ✗。
    """
    mi2net = {}
    # ★ 焊盘读 `model["pads"]` ✓（`pcb_check.collect` 那份 ✓：有 `title`/`cid`/`mi` ✓）——
    #   ✗ 不是 `RT.pad_index` 那份 ✗（实测 2026-10-06：那份里**没有 `mi`** ✗ ⇒
    #   整个函数静默返回空 ✗ ⇒ 日志里连“补网成员声明”那行都没出 ✗）。
    bykey = {}
    for _q0 in (model.get("pads") or ()):
        if _q0.get("mi"):
            bykey[(_q0.get("title"), _q0.get("cid"))] = _q0
    for _net, _lst in (net_pads or {}).items():
        for (_t, _c) in _lst:
            _q = bykey.get((_t, _c))
            if _q:
                mi2net[(str(_q["mi"]), _c)] = _net
    sample, have = {}, set()
    for e in edits:
        have.add((str(e[0]), e[1]))
        _net = mi2net.get((str(e[0]), e[1]))
        if _net and _net not in sample:
            sample[_net] = e
    add = []
    for _net, _s in sample.items():
        for (_t, _c) in (net_pads or {}).get(_net, ()):
            _q = bykey.get((_t, _c))
            if not _q or not _q.get("mi"):
                continue
            if (str(_q["mi"]), _c) in have:
                continue                    # 已经有回指 ✓ ⇒ 不碰 ✗
            _lays = list(PC.pad_layers(_q) or ())
            _lay = "copper0" if "copper0" in _lays or not _lays else _lays[0]
            add.append((_q["mi"], _c, _lay, _s[3], _s[4], _s[5]))
    return add


def prune_dangling(text):
    """★★ 清掉**悬空声明** ✓ —— 就是 `pcb_check` 第 **⑫** 条判的那一类 ✗（`docs/pr-candidates.md` 的 **P1** ✓）。

    ✗ 为什么要写在**写回这个出口** ✗（2026-10-06 修 P1 根因 ✓）：剥线时把**走线实例**删了 ✗，
      却把它们在**焊盘 `<connects>` 里留下的 `<connect>` 声明**留着 ✗ ⇒ Fritzing 顺着声明走 ✓
      ⇒ 显示「**布线完成**」✗，而**铜并不在** ✗✗（实测 v70：`RC` 三只脚一条线都没有 ✗）。
      实测底图 `_work/v69_bare.fzz` 自带 **100 条** ✗（挂在 `L1.connector0/1` 上 ✓）。
      ⇒ 只要出文件那一刻清掉 ✓，从它派生出来的每一份都自然干净 ✓。

    ★★ **划界**（这条最要紧 ✗，别把合法的一起删了 ✗）：
      删的只许是「**`modelIndex` 指向的实例根本不存在**」✗；
      ✗ **绝不能**碰「实例在、只是它的 pcbView 里没这个 connector」那一类 ✗ ——
      仓里量过：那类在 Fritzing 自己的样例里就有 **108 处** ✓、**合法** ✓（见 `write()` 里那段注释 ✓）。

    ⇒ 返回 `(新文本, 清掉几条, 有几条写法异常没敢动)` ✓。
    """
    have = set(re.findall(r'<instance\b[^>]*\bmodelIndex="(\d+)"', text))
    out, pos, n_del, n_odd = [], 0, 0, 0
    for m in re.finditer(r"[ \t]*<connect\b[^>]*?>[ \t]*\r?\n?", text):
        mi = re.search(r'\bmodelIndex="(\d+)"', m.group(0))
        if not mi or mi.group(1) in have:
            continue
        if not m.group(0).rstrip().endswith("/>") or "</connect>" in text[m.start():m.end() + 20]:
            n_odd += 1                      # ✗ 写法没见过 ⇒ **不碰** ✗（报出来给人看 ✓）
            continue
        out.append(text[pos:m.start()])
        pos = m.end()
        n_del += 1
    out.append(text[pos:])
    return "".join(out), n_del, n_odd


def write(base, out, xml, edits=()):
    """把片段插在 `</instances>` 前 ✓；其它内容 / 其它包内文件**逐字节不动** ✓"""
    zin = zipfile.ZipFile(base)
    fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
    text = zin.read(fz).decode("utf-8")
    m = list(re.finditer(r"[ \t]*</instances>", text))
    if len(m) != 1:
        raise SystemExit("✗ 找不到唯一的 `</instances>`（找到 %d 个 ✗）⇒ 不写文件 ✗" % len(m))
    text2 = text[:m[0].start()] + xml + text[m[0].start():]
    # ★★ 回指（两侧都写 ✓）—— 照 Fritzing 自己的文件 ✓；见 `add_backrefs` ✓
    text2, n_back, n_miss, why, n_built = add_backrefs(text2, edits)
    if edits:
        print("   回指：补写 %d 处 ✓｜新建条目 %d 处 ✓｜补不上 %d 处 %s"
              % (n_back, n_built, n_miss, "✗" if n_miss else "✓"))
        for s in why[:6]:
            print("      %s" % s)
    if n_miss:
        # ★ 放宽口径 ✓（2026-09-30 量过 ✓）：Fritzing 自己的 44 份样例里，
        #   `connect` 指向"**目标 pcbView 里根本没有该 connector**"的有 **108 处** ✓
        #   （例：裸露焊盘 EPAD 以前既没插面包板也没接原理图 ⇒ Fritzing 不给它写实例条目 ✓）
        #   ⇒ 这类**合法** ✓，只报数字 ✓、不挡写文件 ✓（`_work/layer_rule.txt` ✓）。
        print("   · 其中少数目标没有 pcbView 条目 ⇒ 合法 ✓（Fritzing 自己也有 108 处 ✓）")
    # ★★ 清 **悬空声明** ✓（2026-10-06 修 P1 根因 ✓，见 `prune_dangling` ✓）：
    #   ✗ 必须排在 `add_backrefs` **之后** ✗ —— 否则会把自己刚补的回指也删掉 ✗。
    text2, n_dang, n_odd = prune_dangling(text2)
    if n_dang or n_odd:
        print("   ★ 清掉**悬空声明** %d 条 ✓（`<connect>` 指的对象**已不在文件里** ✗ ⇒ Fritzing 会"
              "顺着它当已连通 ✓、显示「布线完成」✗ —— 那就是**幽灵** ✓）%s"
              % (n_dang, "｜✗ 另有 %d 条写法异常、没敢动 ✗" % n_odd if n_odd else ""))
    else:
        print("   ★ 悬空声明 **0 条** ✓（没有幽灵 ✓）")
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for it in zin.infolist():
        data = text2.encode("utf-8") if it.filename == fz else zin.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    return len(xml)


def main(argv):
    netsf, rest = projdata.strip_argv(argv)
    if len(rest) < 2:
        print(__doc__)
        return 2
    base, out = rest[0], rest[1]
    # ★ 布不通时的**诊断** ✓（2026-10-01 ✓）：`--why` ⇒ 每条失败的段都报
    #   「起点能泛洪到多少格 ✓／目标在不在可达集里 ✓」⇒ 一眼分清
    #   「真没路」✗ 与「有路但 A* 没搜到 / 代价把它顶歪」✗（不再猜 ✗）。
    if "--why" in argv:
        RT.DIAG["on"] = True
        # ★★ 2026-10-03 加 ✓：**顺便打开栅格出处记录** ✓ —— 布不通时才能报
        #   「这格是**谁**挡的」✓（旧诊断只能说"可达 39 格 ⇒ 堵死了"✗，等于没说 ✓）。
        #   ★ 只在 `--why` 时开 ✗ ⇒ 正常布线的速度与结果**一个字不变** ✗（见 `Grid.OWN` ✓）。
        RT.Grid.OWN = True
    # ★★ 2026-10-03 ✓：`--via-at-pad` ⇒ 细间距/裸露焊盘**允许盘上打孔** ✗（QFN 扇出标准做法 ✓）
    #   依据（**量出来的** ✓）：`DATA_IN` 的 39 格死胡同四墙全是 `U1` 邻脚净空 ✗
    #   ⇒ 铜0 上根本没出口 ✗，只有"盘上打孔、立刻下铜1"才出得去 ✗（嘉立创 QFN 均如此 ✓）。
    #   ★ 默认关 ✗（2026-09-30 用户定的"过孔不许在起/终点盘上"保持 ✓）；开时**只对** `fine`/`epad` 盘放行 ✓。
    if "--via-at-pad" in argv:
        RT.VIA_AT_PAD = True
        print("   ⚠️ `--via-at-pad` ✓：细间距/裸露焊盘**允许盘上打孔** ✗（QFN 扇出 ✓）")
    if "--nomerge" in argv:
        NO_MERGE.append(1)
    data = projdata.load(netsf, need=("NETS",))
    cell = RT.opt(argv, "--cell", RT.CELL_MM, float)
    # ★★ 线↔线**中心距下限** ✓（2026-10-02 ✓；**默认 0 = 关** ✗ ⇒ 与以前逐项一致 ✓）
    #   病根（实测 ✓）：净空 0.15 + 8 mil 线需要中心距 ≥ **0.4032 mm** ✓，
    #     而 0.15 的栅格**只能给 2 格 = 0.30 mm** ✗ ⇒ 真实净距 **0.0968 mm** ✗
    #     —— **低于嘉立创最小间距 0.127 mm** ✗（v64 实测 33 处 ✓）。
    #   `--pitch=0.45` ⇒ 3 格 ✓ ⇒ 净距 **0.2468 mm** ✓（≥ 仓规 0.20 ✓）。
    #   ✗ 别用 `--cell` 修 ✗：实测 0.225 ⇒ **4/9** ✗、0.25 ⇒ 7/9 ✗（"起点格空" ✗ = 脚口被吃 ✓）。
    RT.PITCH_MIN_MM = RT.opt(argv, "--pitch", RT.PITCH_MIN_MM, float)
    via_cost = RT.opt(argv, "--via", RT.K_VIA, float)
    tries = RT.opt(argv, "--tries", 6, int)
    # ★★ 2026-10-01 用户定 ✗：**全板统一用最窄那档 = 8 mil** ✓
    #   原话：「线宽忽宽忽窄，不好吧？直接使用最窄的，作为整张 pcb 的标准线宽吧」✓
    #   ⇒ 电源与信号**同档 8 mil** ✓（= Fritzing 宽度下拉里最细的“超细”✓）；
    #     `pcb_route.NECK_MIL` 也是 8 ✓ ⇒ 缩宽机制留着 ✓，但两边同值 ⇒ 出图**只有一个宽度** ✓
    #     （病根：12 mil 主体 + 8 mil 缩宽段 = 忽宽忽窄 ✗，就是用户看到的那样 ✗）。
    #   ★ 想改回按网分档：`--mil-signal=12 --mil-power=24` ✓（开关都在 ✓）。
    mil_sig = RT.opt(argv, "--mil-signal", RT.opt(argv, "--mil", 8, int), int)
    mil_pow = RT.opt(argv, "--mil-power", 8, int)
    for _m in (mil_sig, mil_pow):
        if _m not in RT.MIL_TIERS:
            raise SystemExit("✗ 线宽只能是这几档 ✓（Fritzing 的宽度下拉 ✓）：%s（mil ✓）"
                             % "、".join("%s %d" % (RT.MIL_TIERS[k], k)
                                         for k in sorted(RT.MIL_TIERS)))
    # ★★ 按网分宽 ✓（2026-09-30 用户定 ✓：「用与 JST-SH 1.0 功率匹配的 5V 和 GND 线宽 ✓，
    #   信号线 12 或 8 mil 都可以 ✓」）—— JST SH 官方额定 **1 A/触点（AWG #28）** ✓
    #   ⇒ 电源网取 **24 mil（标准 ✓ 0.61 mm ✓ ≈2 A ✓）** ✓、信号网 12 mil ✓。
    #   ⚠️ 全局那个 `TRACE_MM`（= 障碍/板边的膨胀量 ✓）取**两者最宽** ✓ ⇒ 对细线偏保守 ✓、安全 ✓。
    power = tuple(getattr(data, "POWER", ("5V", "GND")))
    # ★★ 2026-10-01 实测后定 ✗（用户选 ② ✓）：**`5V` 不再“避开中间走廊”** ✓
    #   依据（**量出来的** ✓，不是猜 ✗）：`_work/probe_5v_bisect.py` ——
    #     干净栅格（无别人的线 ✓）里，`5V` 四对脚 `astar` **全部有路** ✓
    #     （步骤 1 = 挖开自己的盘 ✓、步骤 2 = 再挡住别人的盘框 ✓ —— 都还是有路 ✓）
    #     ⇒ 它失败**不是板子堵死** ✗，而是**别的网已占位**之后的事 ✓。
    #   而 `5V` 的脚就在**板中间**（`U1` 中心 ✓，实测心 =(47.13, 18.72) mm ✓）
    #     ⇒ 对它罚“不要进中间”是**反作用** ✗ ⇒ `mid_keep` **只留 `GND`** ✓。
    #   ⚠️ “留路”那条规律（仓规 §5b ⑩ ✓）并未废 ✗ —— 只是对**必须进中间**的那个网不适用 ✓。
    mid_keep_nets = tuple(n for n in power if n != "5V")
    # ★★ 2026-10-03 加 ✓：`GND` 排到最后布时，**“罚它走中间”那条是反作用** ✗ ——
    #   `mid_keep` 的用意是“给后面的线留走廊” ✓，可一旦 `GND` **自己就是最后布**的 ✓，
    #   后面没人了 ✗ ⇒ 那条罚只剩“让它更难” ✗（实测 `--last=GND` ⇒ 连通 6/9 ✓
    #   但 `GND` **自己 5 段连不上** ✗）。
    #   ⇒ 做两个开关 ✓（一次一改 ✓）：`--mid-keep=<网名,…>` 点名 ✓、`--no-mid-keep` 清空 ✓。
    _mk = next((a.split("=", 1)[1] for a in argv if a.startswith("--mid-keep=")), None)
    if "--no-mid-keep" in argv:
        mid_keep_nets = ()
    elif _mk is not None:
        mid_keep_nets = tuple(x.strip() for x in _mk.split(",") if x.strip())
    # ★★ 2026-10-03 「甲」✓（用户选定 ✓）：**信号先布、电源/地最后布** ✓ —— `--signals-first`
    #   依据（**诊断量出来的** ✓，不是感觉 ✗）：`GND`/`5V` **先布**就把待接的信号脚**围成小口袋** ✗
    #     —— `DATA_IN` 起点只剩 **39 格** ✓、`DATA_OUT` **44 格** ✗（全板可走 ≈2.7 万 ✓）、
    #     `BR+` 终点只剩 **1321 格** ✓；而围住它们的正是 `线:GND`/`线:5V`/`过孔:5V` ✓
    #     （见 `pcb-tool-findings.md` 末节 ✓）。
    #   ⇒ 反过来：让**信号先走** ✓；电源/地**脚最多** ✓、同网铜相碰又合法 ✓
    #     ⇒ 最会“找绕法”的恰恰是它们 ✓（残局留给它们收拾 ✓）。
    #   ★ “要不要先钉 `5V`”是**另一件事** ✓（`[留走廊]` 那段 ✓）⇒ 由 `--no-lock` 单独管 ✓。
    #   ✗✗ 2026-10-03 实测（2×2 ✓，两件事**分开量** ✗ —— 第一次我一起翻 ✓ ⇒ 4/9 ✗ 分不清是谁的错 ✓）：
    #     | 组 | 次序        | 先钉 5V | 连通 | 过孔 | 失败网            |
    #     | A  | 电源先      | ✓      | 5/9 ✓ |  8  | `BR+`/`DATA_IN`/`DATA_OUT`/`LED_DIN` |
    #     | B1 | “信号先”(**假**) | ✓  | **5/9** ✗ | 8 | 与 A **逐项相同** ✗ |
    #     | B2 | 电源先      | ✗      | **4/9** ✗ | 6 | 5 张（多丢 `COIL_B` ✗）|
    #     | B3 | “信号先”(**假**) | ✗  | **4/9** ✗ | 6 | 5 张 ✗ |
    #   ⇒★★ 第一版结论**是错的** ✗✗（我写成了“甲是中性的” ✗）：B1 与 A **逐项相同**不是中性 ✓，
    #     而是 **`--signals-first` 当时是 no-op** ✗ —— `gen_routes` 还在传 `first=power` ✓，
    #     而排序键 `(0 if in first else 2 if in last …)` **`first` 先判** ✗ ⇒ 电源网照样排第一 ✓。
    #     ⇒ 教训（**比结论值钱** ✓）：**开关没生效时，A/B 会显示“完全相同”** ✓ ——
    #       那不是“中性” ✓，是“没生效” ✗；**必须先验证输入真的变了** ✓
    #       （现已加 `--why` 打印「次序实排」✓，并让 `last` **先判** ✓）。
    #   ⇒ 修好之后**真的生效**了 ✓（`--last=5V` / `--last=GND` / `--last=5V,GND` 三组 ✓）：
    #     | 组 | 排最后的网 | 连通 | 失败的网 |
    #     | A' | —          | 5/9 ✗ | `BR+`/`DATA_IN`/`DATA_OUT`/`LED_DIN` |
    #     | D1 | 只 `5V`    | **5/9** ✗（没用 ✓）| 同 A' ✓ |
    #     | D2 | `GND`      | **6/9** ✓ | `DATA_IN`/`GND`(5 段)/`RC`(2 段) |
    #     | C1 | `5V,GND`   | **6/9** ✓（≡ D2 ✓）| 同 D2 ✓ |
    #   ⇒ 三条结论 ✓：
    #     ① **甲有效** ✓：`GND` 排到最后布 ⇒ **5/9 → 6/9** ✓（`BR+`/`DATA_OUT`/`LED_DIN` 通了 ✓）；
    #     ② 起作用的是 **`GND`** 排最后 ✓（`5V` 排不排**无所谓** ✗ —— D1 与 A' 等价 ✓）；
    #     ③ 代价 ✓：`GND` 自己掉队 ✗（`D3.connector0` 起点被封 ✓，5 段连不上 ✗）
    #        ⇒ 下一步该修的是**它** ✓（不是再翻次序 ✓）。
    #   ✗ 已排除的杠杆 ✓（**用 SHA256 证明三个产物完全相同** ✓，不是“看着一样”✗）：
    #     · `--no-mid-keep`（去掉“罚 `GND` 走中间”✓）⇒ **零影响** ✗
    #       ⇒ 说明那条罚对最终解**从来没起作用** ✓（不是因为开关坏 ✓）；
    #     · `--last=GND,RC` ⇒ 零影响 ✗；`--passes=8` ⇒ 零影响 ✗（拆线重布第 1 轮就停 ✓）。
    signals_first = "--signals-first" in argv
    # ★★ 2026-10-03 加 `--last=网名,…` ✓（**可点名** ✓）：`--signals-first` 等价于
    #   `--last=5V,GND` ✓ —— 因为实测发现“把 `GND` 也排最后”会让 **`GND` 自己掉队** ✗
    #   （5 段连不上 ✓）：`5V`/`GND` 不是一回事 ✓ ⇒ 要能分开试 ✓（一次一改 ✓）。
    _last_s = next((a.split("=", 1)[1] for a in argv if a.startswith("--last=")), None)
    if _last_s is not None:
        _last = tuple(x.strip() for x in _last_s.split(",") if x.strip())
    elif signals_first:
        _last = tuple(power)
    else:
        _last = ()
    RT.TRACE_MM = max(mil_sig, mil_pow) * RT.MIL_MM
    # ★ 两项代价旋钮（2026-09-30 用户要"图能看懂能改" ✓）—— **可以分别调** ✓，
    #   因为实测它们各管一头 ✓：
    #     `--turn`     拐弯代价 ✓ ⇒ 路径直 ✓、**走线对象变少**（130 → 99 ✓）⇒ 好读好改 ✓；
    #     `--layer-pen` 非主层每格加价 ✓ ⇒ 想让它少换层 ✓ —— 但 v42 实测**反而**：
    #                   过孔 18 → 28 ✗、线长 198.5 → 288.1 ✗（每网挤自己那层 ⇒ 堵 ⇒ 后布的孔更多 ✗）
    #                   ⇒ 所以默认**先关掉** ✓（`--layer-pen=0` ✓），只用拐弯代价 ✓。
    RT.TURN_COST = RT.opt(argv, "--turn", RT.TURN_COST, float)
    RT.LAYER_PEN = RT.opt(argv, "--layer-pen", 0.0, float)
    # ★★ `--escape-cost=<mm>` / `--escape-r=<mm>` ✓（2026-10-06 加 ✓）——
    #   库里的"**逐路径脚口代价**" ✓（走别人脚口附近加价 ✓，实测是**第一条真正涨连通数**的规则 ✓：
    #   `7/9 → 8/9` ✓）。✗ 驱动这边原先**没有这个口子** ✗ ⇒ 量出来的好档出不了图 ✓。
    _ec = next((a.split("=", 1)[1] for a in argv if a.startswith("--escape-cost=")), None)
    if _ec is not None:
        RT.ESCAPE_COST_MM = float(_ec)
        print("   [脚口代价] 每格 %.2f mm ✓（影子半径 %.2f mm ✓）"
              % (RT.ESCAPE_COST_MM, RT.ESCAPE_R_MM))
    _er = next((a.split("=", 1)[1] for a in argv if a.startswith("--escape-r=")), None)
    if _er is not None:
        RT.ESCAPE_R_MM = float(_er)

    def width_of(net):
        return (mil_pow if net in power else mil_sig) * RT.MIL_MM

    def mil_of(net):
        return mil_pow if net in power else mil_sig

    model = PC.collect(base)
    r = model["board"]
    pads = RT.pad_index(model)
    net_pads, unresolved = RT.resolve_nets(model, data.NETS)
    # ★★★ 2026-10-03 修 ✗✓（**一行**修掉 4 张网布不通的真凶 ✓）：
    #   `pcb_route.obstacles()` 的**同网豁免**读的是 `model["net_pads"]` ✓（源码注释原话：
    #   「布某张网时，把 `tag == 本网` 的障碍**减掉**」✓），而 `resolve_nets()` **只返回、不写回** ✗
    #   ⇒ 那张表**一直是空的** ✗ ⇒ **每只焊盘都算不出网名** ✗（实测 `_work/probe_start.py` ✓：
    #     4 张网的**每一只脚**都报「判到的网 = None」✗）⇒ 邻居焊盘的盘框**永不被免** ✗
    #   ⇒ 在 0.4 mm 脚距的 `U1`（QFN20 ✓）与 `D3`（SOT363 ✓）上，**起步格被隔壁盘盖住** ✗
    #     ⇒ 布线器报 **“起点格空”** ✗、那 4 张网永远布不通 ✗（`BR+`/`DATA_IN`/`DATA_OUT`/`LED_DIN` ✓）。
    #   ⇒ 把返回的那张表**写回 `model`** ✓ —— 口径一个字没改 ✓（只是把它真的填上 ✓）。
    model["net_pads"] = net_pads
    if unresolved:
        print("✗ 脚名解析不了：%s" % ", ".join(unresolved))
    # ★ 把**路由器眼里的映射**打出来 ✓（2026-10-01 ✓）：核对「`U1` 的哪些脚算进了哪张网」✓
    #   起因：实测有一根线把 `PA2`（DATA_IN）与 `VSS`（GND）连起来 ✗，
    #   而 `pixel_nets.py` 的 `NETS` / `EXPECT` 两边**都是对的** ✓ ⇒ 查路由器这边 ✓。
    if RT.DIAG["on"]:
        for _n in sorted(net_pads):
            _u = sorted(c for (t, c) in net_pads[_n] if t == "U1")
            if _u:
                print("   [--why] 网 `%s` 含 U1 的脚：%s" % (_n, ", ".join(_u)))
    print("== 自动布线 + 写回：%s ⇒ %s ==" % (os.path.basename(base), os.path.basename(out)))
    print("   线宽：电源 %s（%s %d mil ✓）／信号 %s（%s %d mil ✓）｜电源网：%s｜过孔 %s ✓"
          % ("%.4f mm" % (mil_pow * RT.MIL_MM), RT.MIL_TIERS[mil_pow], mil_pow,
             "%.4f mm" % (mil_sig * RT.MIL_MM), RT.MIL_TIERS[mil_sig], mil_sig,
             "/".join(power), _VIA_HOLE_TXT))
    print("   线↔线中心距下限：%s ✓"
          % ("%.3f mm（已开 ✓ ⇒ 8 mil 并排净距 %.4f mm ✓）"
             % (RT.PITCH_MIN_MM, RT.PITCH_MIN_MM - mil_sig * RT.MIL_MM)
             if RT.PITCH_MIN_MM > 0 else "关 ✗（= 与以前逐项一致 ✓）"))
    items, _st = RT.obstacles(model)
    # ★ 障碍出处表 ✓（与 `items` **逐条对齐** ✓）：诊断时栅格用它报“谁堵的” ✓
    #   ★ 用 **list** ✗（不是 tuple ✓）：下面「保线」段会**再往 items 里追加** ✓
    #     ⇒ 这里必须**同步追加** ✓，否则两张表长度不一 ⇒ 索引越界 ✗（实测撞过 ✓）。
    _labels = list(_st.get("labels") or ())
    # ★★ 保线 ✓（2026-10-03 用户定「**甲**」✓）：把他自己画的 PCB 走线 + 过孔
    #   当作**已布好的铜** ✓ —— 四条口径（**逐条都可核 ✓**）：
    #     ① **谁都绕开它** ✗（塞进 `items` ⇒ 与焊盘/件铜/安装孔同等待遇 ✓）；
    #     ② **不重画它** ✗ —— 关键 ✗：**不进 `res`** ✓ ⇒ 后面那套
    #        「拆线重布 / 去白钻对 / 确定性合并 / 回收过孔」全都**碰不到他的线** ✓
    #        （进 `res` 就会被那些 pass 挪/删 ✓ —— 这是本仓踩过的坑 ✓）；
    #     ③ 这几张网**只补缺的脚** ✓：网表里**保留**"每条链一个代表脚" ✓＋"还没连到的脚" ✓，
    #        把链上**已经连到**的脚**删掉** ✗（它们已经有铜了 ✓ ⇒ 不许再画一根 ✗）；
    #     ④ 过孔也当障碍 ✓、并进 `novia` ✓（`tag` 给个**永远不会等于网名**的标记 ✓
    #        ⇒ 新过孔不许落在他的线/孔上 ✗）。
    #   数据来源 ✓：`fz_keep_set.py` 生成的纯数据文件 ✓（`--keep=<file>` ✓；不给 ⇒ 老行为 ✓）。
    keepf = next((a.split("=", 1)[1] for a in argv if a.startswith("--keep=")), None)
    if keepf:
        kd = projdata.load(keepf, need=("KEEP", "KEEP_V", "REPS", "DONE"))
        # ★ 本文件里**没有** `U()` ✓（只有 `MM = RT.MM` 一个方向 ✓）⇒ 换算用 `RT.SK` ✓
        #   （= 每毫米多少草图单位 ✓，`pcb_route` 里的 `SK` ✓）
        KEEP_GROW = RT.SK * (KEEP_W_MM / 2.0 + RT.CLEAR_MM)      # 他线**中点**→新线心的下限 ✓
        KEEP_V_GROW = RT.SK * (RT.VIA_CLEAR_MM + RT.VIA_SAFE_MM)  # 他孔心→新线心的下限 ✓
        n_kw = n_kv = 0
        _kitems, _klabels = RT.keep_obstacles(kd.KEEP, kd.KEEP_V)
        # ★★ 2026-10-05 改 ✓：这份逻辑挪进库里成 **唯一实现** ✓（`pcb_route.keep_obstacles` ✓）
        #   —— 诊断工具要**同一份**口径 ✓（否则两边对不上、又回到“自证” ✗）。
        #   修的两处 ✗：① 宽度用**每条线自己的** `mils` ✓（旧版一律 24 mil ✗）；
        #              ② 每段切 ≤ 0.2 mm 小框 ✓（旧版整段外接框 ✗ ⇒ 斜线过度封锁 ✗）。
        for _it in _kitems:
            items.append(_it)
            if str(_it[3]).startswith("__keep"):
                if _it[1][0] == _it[1][2] and _it[1][1] == _it[1][3]:
                    n_kv += 1
                else:
                    n_kw += 1
        _labels.extend(_klabels)
        # ④ 网表瘦身 ✓（甲 ✓）：链上已连到的脚 ⇒ **从网表里去掉** ✗；每条链留一个代表脚 ✓
        done_keys = {("%s.%s" % (k.split(".", 1)[0], k.split(".", 1)[1]))
                     for _n, lst in kd.DONE.items() for k in lst}
        rep_keys = {k for _n, lst in kd.REPS.items() for k in lst}
        n_cut = 0
        for _net, reps in kd.REPS.items():
            cur = list(net_pads.get(_net) or ())
            newl = []
            for (t, c) in cur:
                # ★★ 2026-10-03 修 ✗：这里原来叫 `key` ✗ —— 它把**模块级函数** `key()`
                #   **遮蔽**掉 ✗ ⇒ 后面（第 1136 行起）`key(q["c"][0], …)` 变成
                #   「'str' object is not callable」✗ ⇒ **main 崩在半路** ✗
                #   ⇒ 打印"为什么布不通"那一段**根本跑不到** ✗
                #   （这就是"诊断明明写了却没出现"的真原因 ✓ —— 不是被截断 ✗，是崩了 ✗）。
                pk = "%s.%s" % (t, c)
                if pk in rep_keys or pk not in done_keys:
                    newl.append((t, c))
                else:
                    n_cut += 1
            net_pads[_net] = newl
        print("   [保线] 用户画的铜 ✓：走线 %d 段 ＋ 过孔 %d 个 ⇒ **当既有铜** ✓"
              "（绕开它 ✗、不重画 ✗；**按各线自己的半宽** ✓、斜线切小段 ✓）"
              % (n_kw, n_kv))
        for _net in sorted(kd.REPS):
            print("      · %-5s 链上已连到 %s ✓ ⇒ **不再布线** ✗；从代表脚 %s ✓ 往外接剩下的脚 ✓"
                  % (_net, "、".join(sorted(kd.DONE.get(_net, []))),
                     "、".join(kd.REPS[_net])))
        print("      ⇒ 网表里去掉已连到的脚 %d 个 ✓（甲：不动他连好的 ✗）" % n_cut)
    passes = RT.opt(argv, "--passes", 4, int)
    # ★ `--blockers=<n>` ✓（2026-10-06 加 ✓）：拆线重布时**最多试几个"对手网"** ✓
    #   （库默认 8 ✓）。实测：同一块板、只改这一项（8 → 16 ✓，即"所有已布通的网都试一遍" ✓）
    #   拆线才走得动 —— 旧尺子下是零影响 ✗，换了尺子（还差几条连接优先 ✓）后才有用 ✓。
    blockers = RT.opt(argv, "--blockers", 8, int)
    # ★★ 元件**画出来的铜**（含 NFC 线圈的螺旋 ✓）⇒ 过孔禁落区 ✓
    #   2026-10-01 用户定 ✗：「通孔不能在元件内，并与有安全距离」✓
    #   （校验器第 ⑦ 条 = 独立实现 ✓；这边是布线时**躲开** ✓）
    copper_keep = [(lay, b) for q in (model.get("bodies") or ())
                   for lay, b, _i in (q.get("shapes") or ())
                   if lay in ("copper0", "copper1")]
    print("   过孔禁落：元件铜 %d 块 ✓（含线圈 ✓）｜同网焊盘也禁 ✓（0.25 mm ✓）"
          "｜**安装孔 %d 颗**（距内壁 ≥ %.2f mm ✓）"
          % (len(copper_keep), len(model.get("holes") or ()), RT.HOLE_CLEAR_MM))
    # ★★ A 案：「**留走廊**」✓（2026-10-01 用户选 A ✓）
    #   依据（量出来的 ✓，不是猜 ✗）：统一 `flood`/`astar` 口径后，`5V` 在**真实规则**下
    #     确实**没路** ✗（`_work/probe_5v_bisect.py`：干净栅格里四对脚全有路 ✓
    #      ⇒ 堵它的是**别的网已占的线** ✓）。
    #   做法（用引擎已有的 `pre` 机制 ✓ —— “已布好、不重布、仍旧当障碍” ✓）：
    #     ① 先把 `5V` **单独**布好 ✓（此刻没任何别的线 ✓，它拿到的就是最短通道 ✓）；
    #     ② 把它**钉住** ✓ ⇒ 后面每一个网的栅格里，它的铜都是**硬障碍** ✓
    #        ⇒ 谁都不许占它的通道 ✓（这就是“留走廊” ✓）；
    #     ③ 代价（说清 ✗）：别的网可能绕远 ✓、个别网可能因此布不通 ✗ ⇒ 用同一套
    #        “**只有总分更好才接受**”的规矩压着 ✓（不行就退回 ✓）。想对比旧行为：`--no-lock` ✓。
    # ★★ 试过：`("5V", "RC")` 两张都钉 ✓ ⇒ **实测两次都不好** ✗（2026-10-01 ✓）：
    #     · `R1` 在原位时：连通不变（8/9 ✓）但过孔 8 → 16 ✗；
    #     · `R1` 挪出线圈后：反而掉到 **7/9** ✗（`BR+` 与 `DATA_IN` 都没通 ✓）。
    # ★★ 又试过：`("5V", "RC", "DATA_IN")` 三张一起钉 ✓ ⇒ **更差** ✗（2026-10-01 实测 ✓，
    #     在**原线圈**（6 匝 / 25 mm 板 ✓）上：**8/9 → 6/9** ✗ —— 同一份底图、
    #     同一套开关，只差这一行 ✓；掉的是 `DATA_IN`/`DATA_OUT`/`GND` ✓）。
    #     ⇒ 静态上"各自都通"✓ **不等于**"钉住就更好" ✗：钉住 = 把**布局自由度**先花掉 ✗，
    #       于是别人的通道被挤没 ✓ —— 这块板的"总容量"才是硬约束 ✓。
    #   ⇒ 回到**只钉 `5V`** ✓（用户选 A 时定的那一条 ✓）。
    prio_list = [p for p in ("5V",) if p in net_pads]      # ★ 钉不钉由 `--no-lock` 管 ✓
    locked = {}
    for prio in (() if "--no-lock" in argv else prio_list):
        _one = RT.route(items, r, {prio: net_pads[prio]}, pads, cell, via_cost,
                        verbose=False, tries=tries, width_of=width_of,
                        copper_keep=[b for _l, b in copper_keep], pre=locked,
                        labels=_labels)
        if _one.get(prio, {}).get("ok"):
            locked[prio] = _one[prio]
            print("   [留走廊] `%s` 先单独布好并**钉住** ✓（段 %d ｜过孔 %d ✓）"
                  "⇒ 后面每张网的栅格里它是硬障碍 ✓"
                  % (prio, len(locked[prio]["segs"]), len(locked[prio]["vias"])))
        else:
            print("   [留走廊] `%s` 单独布都**没通** ✗ ⇒ 不钉 ✓（说明堵它的不是别人占位 ✗）"
                  % prio)
    # ★★ 2026-10-03 加 `--first=网名,…` ✓（**点名排最前** ✓，`--last` 的反面 ✓）：
    #   依据（诊断量出来的 ✓）：`RC` 的起点 `R1.connector1` 可达 **784 格** ⇒ 口袋是一大片
    #     **x 7.95 × y 3.30 mm** ✗、边界是 `线:5V×55`＋`线:BR+×49`＋两者过孔 ✓
    #     ⇒ 是**先布的线把它切断了** ✗ ⇒ 让它**先走** ✓（缺省仍是电源先 ✓，不传就不变 ✗）。
    _fs = next((a.split("=", 1)[1] for a in argv if a.startswith("--first=")), None)
    _first = (tuple(x.strip() for x in _fs.split(",") if x.strip())
              if _fs is not None else power)
    res = RT.route_ripup(items, r, net_pads, pads, cell, via_cost, tries=tries, passes=passes,
                         blockers=blockers,
                         width_of=width_of, first=_first, last=_last, mid_keep=mid_keep_nets,
                         copper_keep=[b for _l, b in copper_keep], pre=locked,
                         labels=_labels)

    # ★★ 成对过孔回收 ✓（2026-09-30 用户选 1 ✓，起因：用户点名 `Via11`/`Via12` 硌眼 ✗）：
    #   实测那两颗是**一对** ✓ —— "从 `copper1` 钻下去 ✓、走约 2 mm ✓、再钻回来" ✓
    #   （每颗外侧只剩 0.3～0.45 mm 碎铜 ✗ = 机器留下的小尾巴 ✓）。
    #   做法沿用本仓已有铁律 ✓（同 `route_ripup` ✓）：**试改 ⇒ 只有总分更好才接受** ✓：
    #     ① 找同一张网里**相距 ≤6 mm 的过孔对** ✓（候选 ✓，不一定真是一对 ✓）；
    #     ② 把它们的**孔位禁掉**再整盘重布一遍 ✓；
    #     ③ 比 `(连通数, -过孔数, -线长)` ✓ —— 更好就采纳 ✓、否则**原样退回** ✓。
    #   ⇒ 若那对孔是**必须**的 ✓，重布会失败或变差 ⇒ 自动退回 ✓，**不会把板子改坏** ✓。
    def _score(r):
        return (sum(1 for d in r.values() if d["ok"]),
                -sum(len(d["vias"]) for d in r.values()),
                -sum(math.hypot(s[1][0] - s[2][0], s[1][1] - s[2][1])
                     for d in r.values() for s in d["segs"]))

    res_s = _score(res)
    # ★★ 路由器**产物自检** ✓（2026-10-01 立 ✓，`--why` 打开 ✓）：
    #   目的 = 分开两件事 ✗（写回端一直报「悬空端点」✗，但到底是**谁**弄断的 ✓ 不知道 ）：
    #     ① 布线器自己就断了（`res` 里端点谁也不靠 ✗）；
    #     ② 布线器是好的 ✓、是**写回**（缩宽切段 / 拓扑整理 / 端点归并 / `key()` 取整 ✗）弄断的 ✓。
    #   判据 = 每个端点必须落在 ① 焊盘心 ✓、② 过孔心 ✓、③ 别的段端点 ✓ 三者之一上 ✓。
    if RT.DIAG["on"]:
        ats = {}
        for q in model["pads"]:
            for lay in PC.pad_layers(q):
                ats.setdefault(key(q["c"][0], q["c"][1], lay), []).append("pad:%s.%s"
                                                                          % (q["title"], q["cid"]))
        for net in sorted(res):
            d = res[net]
            for (lay, a, b) in d["segs"]:
                ats.setdefault(key(a[0], a[1], lay), []).append("seg")
                ats.setdefault(key(b[0], b[1], lay), []).append("seg")
            for v in d["vias"]:
                for lay in ("copper0", "copper1"):
                    ats.setdefault(key(v[0], v[1], lay), []).append("via")
        lone = [(k, v) for k, v in ats.items() if len(v) < 2 and not v[0].startswith("pad")]
        print("   ⇒ **路由器产物自检** ✓：孤立端点 %d 处 ✗（必须 0 ✓）" % len(lone))
        for k, v in sorted(lone)[:8]:
            print("       (%.3f, %.3f) 层 %s ⇒ 只有 %d 个端点 ✗（%s ✓）"
                  % (k[0], k[1], k[2], len(v), ",".join(v)))
        # ★★ 几何级自检 ✓（2026-10-01 补 ✗）：✗ 上面那个只比**点**（还按 `key()` 取整 ✓）
        #   ⇒ 抓不到「**歪段**」✗（实测：`(52.781,25.505)→(52.381,25.472)` 就是歪的 ✓，
        #     可它的两端各自都另有搭子 ⇒ 逐点看都“有主” ✓）。
        #   这里补两条硬判据 ✓：① 每段必须**横平竖直** ✓；② 接点必须**逐位相同** ✓。
        skew, unb = [], []
        for net in sorted(res):
            for (lay, a, b) in res[net]["segs"]:
                if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                    skew.append((net, lay, a, b))
        print("   ⇒ **几何自检** ✓：歪段（既不横也不竖）%d 条 ✗（必须 0 ✓）" % len(skew))
        for (net, lay, a, b) in skew[:8]:
            print("       ✗ %s %s (%.3f,%.3f)→(%.3f,%.3f) ⇒ 斜了 (%.3f,%.3f) mm ✗"
                  % (net, lay, MM(a[0]), MM(a[1]), MM(b[0]), MM(b[1]),
                     MM(b[0] - a[0]), MM(b[1] - a[1])))
        # ★★ 跨网自检已挪到**最终解**上跑 ✓（写回之前 ✓）—— ✗ 排在这里（`[去白钻对]` 之前 ✓）
        #   会漏掉那几轮**改出来**的问题 ✓（实测就是：文件里那根「`DATA_IN` 盘 ↔ `GND` 盘」
        #   的 10 mil 线 ✓，在中途检查里根本看不到 ✗）。
    # ★★ 2026-10-01 定点修 ✗（用户原话：「我对 `Via5` 和 `Via6` 的必要性存疑，为什么要有它们？」✓）：
    #   实测那两颗 **相距 0.30 mm**、属 `BR+` 网，而它们之间那段在 **copper0 上完全畅通**
    #   （`via_pair_why.py` 逐格查过 ✓）⇒ 就是**白钻两颗孔** ✗。
    #   ✗ 旧实现的两处弱点（就是它没能拦住的根因 ✓）：
    #     ① 只挑**全局最近的一对** ✗ ⇒ 挑到"其实必需"的那对 ⇒ 重布失败 ⇒ 退回 ⇒ **白钻那对永远轮不到** ✗；
    #     ② 禁 **半径 0.6 mm = 98 个格点** ✗ ⇒ 过度封禁 ⇒ 重布必然变差 ⇒ 又退回 ✗。
    #   ✓ 现在：**只挑"中间那段在外层本来就畅通"的同网对** ✓（= 可证明多余 ✓），
    #     并且**只禁它俩 + 紧邻一格**（9 个格点 ✓）；轮数放宽到 6 ✓；
    #     接受条件**不变** ✓（`(连通数, −过孔数, −线长)` 更好才采纳 ✓）⇒ 风险不变 ✓。
    grid0 = RT.make_grid(r, cell, items)

    # ★★ ② 确定性合并 ✓（2026-10-01 用户选「做」✓，起因：用户点名「我对 `Via5` 和 `Via6` 的
    #   必要性存疑」✓）：
    #   对一对**已证明多余**的孔（同网 ✓、相距 ≤1.5 mm ✓、**中间那段在外层本来就畅通** ✓）：
    #     · 把中间段**换到外层** ✓（**几何一点不动** ✗，只换层 ✓）
    #     · 删掉那两颗孔 ✓
    #   ⇒ 不走搜索 ✓、结果可验证 ✓（外层那段本来就畅通 ✓；两端外层段同层 ⇒ 接得上 ✓）。
    #   ★ 与「去白钻对」（**重布**一遍 ✓）不同 ✗：这个是**确定性**的 ⇒ 这类对**一定**消失 ✓。
    #   ★ 要在**最终结果**上跑 ✓（✗ 我第一次把它放在「去白钻对」之前 ⇒ 那时 `BR+` 还没长出那对 ✗
    #     ⇒ 一个也没合到 ✓）。
    def _touches(s, p, eps=0.6):
        return (math.hypot(s[1][0] - p[0], s[1][1] - p[1]) <= eps
                or math.hypot(s[2][0] - p[0], s[2][1] - p[1]) <= eps)

    def _free(lay, p, q):
        for t in (0.2, 0.4, 0.6, 0.8):
            x = p[0] + (q[0] - p[0]) * t
            y = p[1] + (q[1] - p[1]) * t
            ii, jj = grid0.rc(x, y)
            if not grid0.g[lay][jj * grid0.nx + ii]:
                return False
        return True

    def _strip_pointless(res_):
        n = 0
        _skip = []
        for _net, d in res_.items():
            again = True
            while again:
                again = False
                for i in range(len(d["vias"])):
                    for j in range(i + 1, len(d["vias"])):
                        va, vb = d["vias"][i], d["vias"][j]
                        if math.hypot(va[0] - vb[0], va[1] - vb[1]) > RT.U(1.5):
                            continue
                        mids = [s for s in d["segs"] if _touches(s, va) and _touches(s, vb)]
                        if len(mids) != 1:
                            _skip.append("%s: 接两孔的段数 %d ✗" % (_net, len(mids)))
                            continue
                        m = mids[0]
                        out = [s for s in d["segs"] if s is not m
                               and (_touches(s, va) or _touches(s, vb))]
                        if len(out) != 2 or out[0][0] != out[1][0] or out[0][0] == m[0]:
                            _skip.append("%s: 外层段 %s（层 %s vs %s）✗"
                                         % (_net, len(out), out[0][0] if out else "-",
                                            out[1][0] if len(out) > 1 else "-"))
                            continue
                        if not _free(out[0][0], m[1], m[2]):
                            _skip.append("%s: 外层那段不畅通 ✗" % _net)
                            continue                  # 外层不畅通 ⇒ 这对**有用** ✓ ⇒ 不动 ✗
                        # ★★ 2026-10-01 补 ✗：`_free` 只看**静态障碍**（焊盘 / 件铜 / 安装孔 ✓
                        #   = 初始 `grid0` ✓）—— ✗ 看不见**别的网的走线/过孔** ✗
                        #   ⇒ 实测真凶 ✓：v62 `[短路计数]` 拆线重布后 **0** 对 ✓、
                        #     确定性合并后 **1** 对 ✗（`DATA_OUT` 换到 copper0 ⇒ 横跨 `BR+` 的竖段 ✓）
                        #   ⇒ 这里加一道**动态闸门** ✓：新段（ + 两个孔位 ✓）与**别的网**的
                        #     线/过孔只要**铜叠**就**不换** ✓（宁可留着那两颗孔 ✗，不许短路 ✓）。
                        #   ★ 只**跳过**、不改几何 ✗ ⇒ 连通性不会因此变差 ✓（最多少合一对孔 ✓）。
                        _ln, _p, _q = out[0][0], m[1], m[2]
                        _hw = RT.U(width_of(_net) / 2.0)
                        _hit = None
                        for _n2, _d2 in res_.items():
                            if _n2 == _net:
                                continue
                            _hw2 = RT.U(width_of(_n2) / 2.0)
                            for _s2 in _d2["segs"]:
                                if RT.copper_overlap((_ln, _p, _q), _hw, _s2, _hw2):
                                    _hit = "线"
                                    break
                            if not _hit:
                                for _v2 in _d2["vias"]:      # 别人家的过孔 ✓（写成退化段 ✓）
                                    if RT.copper_overlap((_ln, _p, _q), _hw,
                                                         (_ln, _v2, _v2),
                                                         RT.U(0.30)):
                                        _hit = "过孔"
                                        break
                            if _hit:
                                _skip.append("%s: 换到外层会与 `%s` 的%s**铜叠** ✗"
                                             % (_net, _n2, _hit))
                                break
                        if _hit:
                            continue
                        d["segs"][d["segs"].index(m)] = (out[0][0], m[1], m[2])
                        d["vias"].remove(va)
                        d["vias"].remove(vb)
                        n += 1
                        again = True
                        break
                    if again:
                        break
        if _skip:
            for s in sorted(set(_skip))[:8]:
                print("   [确定性合并·跳过] %s" % s)
        return n

    # ★ 短路计数 ①：**拆线重布之后**（`--why` 的自检只查"端落在别的网盘心" ✗，
    #   查不到"两根线铜叠上" ✗ ⇒ 先量一下 ✓；口径 = `RT.copper_clashes` ✓ 唯一实现 ✓）
    print("   [短路计数] 拆线重布之后：叠 %d 对 ✓" % len(RT.copper_clashes(res, width_of)))
    for rnd in range(1, 7):
        best = None
        for net, d in res.items():
            vs = d["vias"]
            mem = [(t, c) for t, c in net_pads.get(net, []) if (t, c) in pads]
            if len(vs) < 2 or not mem:
                continue
            g = grid0.clone()                      # ★ 本网焊盘挖回可走 ✓（与布线器同口径 ✓）
            RT.carve_pads(g, pads, mem, RT.U(RT.TRACE_MM / 2 + RT.CLEAR_MM))
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    dd = math.hypot(vs[i][0] - vs[j][0], vs[i][1] - vs[j][1])
                    if dd > RT.U(1.5):
                        continue
                    # 中间那段在**某一层**上是否畅通 ✓（有任一层畅通 ⇒ 白钻 ✗）
                    free = False
                    for lay in g.g:
                        ok = True
                        for t in (0.25, 0.5, 0.75):
                            x = vs[i][0] + (vs[j][0] - vs[i][0]) * t
                            y = vs[i][1] + (vs[j][1] - vs[i][1]) * t
                            ii, jj = g.rc(x, y)
                            if not g.g[lay][jj * g.nx + ii]:
                                ok = False
                                break
                        free = free or ok
                    if free and (best is None or dd < best[0]):
                        best = (dd, vs[i], vs[j], net)
        if best is None:
            print("   [去白钻对] 没有「中间畅通的同网对」⇒ 不用 ✓")
            break
        cand, n = [], 1
        for (px, py) in (best[1], best[2]):
            for dx in range(-n, n + 1):
                for dy in range(-n, n + 1):
                    cand.append((px + dx * RT.U(cell), py + dy * RT.U(cell)))
        trial = RT.route_ripup(items, r, net_pads, pads, cell, via_cost, tries=tries,
                               passes=passes, width_of=width_of, first=_first, last=_last,
                               mid_keep=mid_keep_nets, ban_via=cand, pre=locked,
                               copper_keep=[b for _l, b in copper_keep], verbose=False,
                               labels=_labels)
        s2 = _score(trial)
        print("   [去白钻对] 第 %d 轮：网 `%s` 的一对相隔 %.2f mm ✓（中间畅通 ✓）"
              "｜禁 %d 格 ⇒ 连通 %d/%d ✓｜过孔 %d ⇒ %d ✓"
              % (rnd, best[3], best[0] / RT.U(1.0), len(cand), s2[0], len(trial),
                 -res_s[1], -s2[1]))
        if s2 > res_s:
            res, res_s = trial, s2
        else:
            print("   [去白钻对] 这轮没更好 ⇒ **原样退回** ✓、停 ✓")
            break

    # ★ ② 在**最终结果**上做确定性合并 ✓（顺序很关键 ✗：放前面时 `BR+` 还没长出那对 ✓）
    n_merged = _strip_pointless(res)
    print("   [确定性合并] 合掉 %d 对「白钻孔」（中间段换到外层 ✓、删 %d 颗孔 ✓）"
          % (n_merged, 2 * n_merged))

    # ★ 短路计数 ②：**确定性合并之后** ✓ ⇒ 与 ① 一比就知道是哪一步叠上的 ✓（先量后修 ✓）
    _bad = RT.copper_clashes(res, width_of)
    print("   [短路计数] 确定性合并之后：叠 %d 对 ✓" % len(_bad))
    for (_na, _nb, _sa, _sb, _gp) in _bad[:4]:
        print("      ✗ `%s`×`%s` 叠 %.3f mm ✓：%s (%.3f,%.3f)→(%.3f,%.3f) ／ %s (%.3f,%.3f)→(%.3f,%.3f)"
              % (_na, _nb, -_gp / RT.U(1.0), _sa[0],
                 MM(_sa[1][0]), MM(_sa[1][1]), MM(_sa[2][0]), MM(_sa[2][1]),
                 _sb[0], MM(_sb[1][0]), MM(_sb[1][1]), MM(_sb[2][0]), MM(_sb[2][1])))

    n_ok = sum(1 for d in res.values() if d["ok"])
    ln = sum(math.hypot(s[1][0] - s[2][0], s[1][1] - s[2][1])
             for d in res.values() for s in d["segs"])
    print("\n   连通 %d/%d ✓｜线长 %.1f mm｜过孔 %d 个"
          % (n_ok, len(res), MM(ln), sum(len(d["vias"]) for d in res.values())))
    # ★★ `--measure-only` ✓（2026-10-06 加 ✓）：**只量不写** ✓ —— 打一行**机器可读**
    #   的结论 ✓ 后立刻退出 ✓（✗ 不碰输出文件 ✗，`out` 参数被忽略 ✓）。
    #
    #   ★ 为什么要它 ✗（**实测的教训** ✓，就是仓规 §13「只允许一个声音」那一条 ✓）：
    #     我的「贪心挪位搜索」（`_work/place_greedy.py` ✓）**自己抄了一份路由口径** ✗
    #     ⇒ 它在候选 `D3 +0 -1` 上报 `8/9 ✓ 还差 2 条` ✓，
    #     而**驱动器在同一份文件上只给 `4/9 ✗ 还差 7 条`** ✗（2026-10-06 实测 ✓）。
    #     差的全是这里的**默认流水线** ✗：`[留走廊]` 先把 `5V` 单独布好**钉住** ✓、
    #     `first=power` 排序 ✓、`mid_keep` 罚 `GND` 走中间 ✓、`keep` 禁落区 ✓、
    #     `locked` 既有铜 ✓ —— scratch **一条都没有** ✗。
    #   ⇒ 尺子**只许有一份实现** ✓：搜索**调这一份** ✓（抄一份就多一个错处 ✗）。
    #   ★ 用法 ✓：`gen_routes.py <候选.fzz> _ --measure-only …` ⇒ 解析最后一行 `MEASURE …` ✓。
    if "--measure-only" in argv:
        _miss = sum(int(d.get("miss", 0)) for d in res.values())
        print("MEASURE ok=%d nets=%d miss=%d len_mm=%.1f vias=%d bad=%s"
              % (n_ok, len(res), _miss, MM(ln),
                 sum(len(d["vias"]) for d in res.values()),
                 ",".join(sorted(n for n, d in res.items() if not d["ok"])) or "-"))
        return 0
    # ★★ `--dump-net=<网名>` ✓（2026-09-30 用户要的 ✓）：把**布线器内部**那张网的段
    #   与它各个脚的层原样摊开 ✓ ⇒ 一刀切开"**布线器没生成**" ✗ vs "**写回时丢了**" ✗。
    #   只打印 ✓、**绝不写文件** ✓（便于反复对着量 ✓）。
    if "--dump-net" in " ".join(argv):
        want = RT.opt(argv, "--dump-net", "", str)
        print("\n== 摊开网 `%s`（层 + 两端，mm ✓）==" % want)
        print("   脚（布线器看到的层 ✓）：")
        for t, c in net_pads.get(want, []):
            q = pads.get((t, c))
            if q is None:
                print("     %s.%s ⇒ **不在板上** ✗" % (t, c))
                continue
            print("     %-6s %-11s lays=%-24s 心=(%.2f, %.2f) mm"
                  % (t, c, q["lays"], MM(q["c"][0]), MM(q["c"][1])))
        d = res.get(want)
        if d is None:
            print("   ✗ 没这张网 ✗")
        else:
            print("   ok=%s｜过孔 %d｜段 %d："
                  % (d["ok"], len(d["vias"]), len(d["segs"])))
            for j, (lay, a, b) in enumerate(d["segs"]):
                print("     #%-3d %-8s (%.3f, %.3f) → (%.3f, %.3f) mm"
                      % (j, lay, MM(a[0]), MM(a[1]), MM(b[0]), MM(b[1])))
            for j, p in enumerate(d["vias"]):
                print("     过孔#%-3d (%.3f, %.3f) mm" % (j, MM(p[0]), MM(p[1])))
        return 0
    # ★★ `--partial` ✓（2026-10-01 加 ✓）：布不通 / 有残留违规时**也写文件** ✓ ——
    #   用途**只有一个** ✓：让用户“看到长什么样” ✓（用户原话「2 吧，我看看啥样」✓）。
    #   ✗ 绝不当成交付 ✗：文件里的问题会在下面**逐条打印** ✓，渲染时也会写明“未完成” ✓。
    # ★★ 交付开关 ✓（2026-10-01 用户定 ✓）：
    #   `--partial` = 草稿（只为看效果 ✓）；`--deliver` = **交付** ✓ —— 用户 **明确点头**
    #     接受"已知还剩 N 处问题"时用它 ✓ ⇒ 同样照写 ✓，但日志里**不许**再写"不是交付" ✗。
    partial = "--partial" in argv or "--deliver" in argv
    deliver = "--deliver" in argv
    if deliver:
        print("   ✓ `--deliver`（交付 ✓）：已知问题**原样留在文件里** ✓ —— 用户 2026-10-01 点头 ✓")
    elif partial:
        print("   ⚠️⚠️ `--partial` 模式：**不是交付** ✗ —— 下面报的问题原样留在文件里 ✓，"
              "仅供看效果 ✓")
    if n_ok != len(res):
        bad = [(n, d.get("note") or "") for n, d in sorted(res.items()) if not d["ok"]]
        print("   ✗ 没布通的网（%d 张）：%s" % (len(bad), "；".join(
            "%s%s" % (n, ("（%s）" % t) if t else "") for n, t in bad)))
        if not partial:
            print("   ✗ 有网没布通 ⇒ **不写文件** ✗（先把摆位/参数调好 ✓；想先看图加 `--partial` ✓）")
            return 1
        print("   ⚠️ 照写 ✓（%s ✓）：这份图里有 %d 张网没通 ✓"
              % ("交付" if deliver else "--partial", len(bad)))
    # ★ 交付时把"没通哪几张"**原样写进日志** ✓（不许只写在人脑里 ✗）
    if RT.DIAG["on"] and RT.DIAG["fails"]:
        print("\n   == 为什么布不通（`--why` 诊断 ✓，`flood` 与 A* 同口径 ✓）==")
        # ★★ 2026-10-03 去重 ✓：`DIAG["fails"]` 是**跨所有尝试累加**的 ✓
        #   （6 种次序 × 拆线重布 × 去白钻对 ✓）⇒ 同一张网会重复十几遍 ✗
        #   ⇒ 把真正的新信息淹掉 ✗；这里按**首次出现**去重 ✓、保持原顺序 ✓。
        _seen = set()
        for s in RT.DIAG["fails"]:
            if s in _seen:
                continue
            _seen.add(s)
            print("      %s" % s)

    # ★★ 硬闸门 ②：过孔**铜盘不许压盘** ✓（2026-10-01 补 ✗ —— 用户点名的"通孔严重错误" ✓）
    #   起因（实测 v47 ✗）：18 个过孔里 7 个的铜盘压进邻盘，其中 `Via18`（RC）把
    #   `U1.connector2`（PA2 / DATA_IN）压了 0.20 mm ⇒ **RC 与 DATA_IN 短路** ✗✗。
    #   判据：孔心到盘边的距离 ≥ 盘半径 0.30（同网 ✓）/ ≥ 0.50（异网或空脚 ✓）。
    #   ✗ 非空就**不写文件** ✗ —— 与"悬空端点必须 0"同级 ✓（宁可多几颗孔 ✗，不能短路 ✓）。
    pad_net = {}
    for _n, _lst in (net_pads or {}).items():
        for _k in _lst:
            pad_net[_k] = _n
    vps = [(n, p) for n, d in sorted(res.items()) for p in d["vias"]]
    badv = RT.via_pad_conflicts(vps, pads, pad_net)
    if badv:
        print("   ✗ 过孔铜盘压盘 %d 处 ⇒ %s" % (len(badv), "**照写** ✗（--partial ✓）"
                                              if partial else "**不写文件** ✗："))
        for n, p, ttl, cid, d, need in badv[:12]:
            print("      网 %-9s 过孔(%.2f, %.2f) mm ↔ %s.%s：距边 %.3f mm < 需要 %.3f mm ✗"
                  % (n, MM(p[0]), MM(p[1]), ttl, cid, d, need))
        if len(badv) > 12:
            print("      …（共 %d 处 ✓）" % len(badv))
        if not partial:
            return 1

    text, _nm = PW.read(base)
    # ★★★ 写回前的**最终自检** ✓（2026-10-01 ✓）：必须在**所有 `res` 改动之后**跑 ✗
    #   （`route_ripup` ✓ → `[拆线重布]` ✓ → `[去白钻对]` ✓ → `[确定性合并]` ✓）——
    #   ✗ 排在中途会漏掉后面那几轮改出来的问题 ✓（实测踩过 ✓：文件里那根
    #   「`DATA_IN` 盘 ↔ `GND` 盘」的 **10 mil** 线 ✓，中途检查完全看不到 ✗）。
    if RT.DIAG["on"]:
        _owner = {}
        for _n, _lst in net_pads.items():
            for _k in _lst:
                _owner[_k] = _n
        _centre = {}
        for _k, _q in pads.items():
            _centre[(round(_q["c"][0], 6), round(_q["c"][1], 6))] = _k
        cross = []
        for net in sorted(res):
            for (_lay, a, b) in res[net]["segs"]:
                for (q2, w2) in ((a, "起"), (b, "终")):
                    k2 = _centre.get((round(q2[0], 6), round(q2[1], 6)))
                    if k2 is not None and _owner.get(k2) not in (None, net):
                        cross.append((net, k2, _owner.get(k2), w2))
        print("   ⇒ **跨网自检（最终解）** ✓：段端点落在**别的网**的盘心上 %d 处 ✗（必须 0 ✓）"
              % len(cross))
        for (net, k, own, w2) in cross[:8]:
            print("       ✗ 网 `%s` 的段%s端落在 `%s.%s`（属 `%s`）✗" % (net, w2, k[0], k[1], own))
    xml, stats, edits = build_xml(text, res, model, pads, mil_of=mil_of, net_pads=net_pads)
    # ★★ 2026-10-06 补 ✓：**每张网的每只脚都要挂上声明** ✓（见 `fill_net_decls` ✓）——
    #   ✗ 不补的话，**没布通的那只脚**在 PCB 视图里 0 条声明 ✗ ⇒ Fritzing **不把它算进那张网** ✗
    #     ⇒ 剩下两只连着 ⇒ 它就说「**布线完成**」✗✗（v70 / v71 实测 ✓）。
    # ★★ 但 **2026-10-06 当天就发现它治标不治本** ✗：真病在**底图**✗ ——
    #   老底图 `v69_bare.fzz` 把走线**整条删**了 ✗ ⇒ 面包板/原理图的**网结构**一起没了 ✗
    #   （声明**全悬空** ✗，实测 `_work/_cmp_nets.py` ✓）⇒ Fritzing 认不出 `RC` 是一张网 ✗。
    #   ⇒ 正解 = 换**只剥 `<pcbView>`** 的底图 ✓（`tools/strip_pcb_view.py` ✓，网结构原样 ✓）；
    #     这时底图里那只脚**本来就有**声明 ✓ ⇒ 再"补"就是**伪造连接** ✗（`<connect>` 一挂上，
    #     `Wire::collectChained` 就会顺着链给它加边 ✗）⇒ 所以**默认关** ✗，只在 `--fill-decls` 时补 ✓。
    _add = fill_net_decls(edits, model, net_pads) if "--fill-decls" in argv else []
    if _add:
        print("   ★ 补**网成员声明** %d 条 ✓（每张网的每只脚都得在 PCB 视图里挂一条 ✓；"
              "✗ 缺了它 Fritzing 就不把这只脚算进那张网 ✓ ⇒ 状态栏会说「布线完成」✗）" % len(_add))
    edits = list(edits) + _add
    if stats.get("cross"):
        print("   %s **写回把它接错了**（线的一端结到别的网的盘 ✓）：%d 处 ✗"
              % ("✗✗" if not partial else "⚠️", len(stats["cross"])))
        for _s in stats["cross"][:8]:
            print("      ✗ %s" % _s)
        if not partial:
            print("   ✗ 硬闸门 ③ 不过 ⇒ **不写文件** ✗（想先看图加 `--partial` ✓）")
            return 1
    print("   走线 %d 条 ✓（**合并前 %d 条** ✓）｜过孔 %d 个 ✓｜**悬空端点 %d**（必须 0 ✗）｜多线共用一端 %d"
          "｜**缩宽段 %d 条**（细间距区 %d mil ✓）"
          % (stats["wires"], stats.get("raw", stats["wires"]), stats["vias"],
             stats["open_ends"], stats["multi"], stats.get("necks", 0), RT.NECK_MIL))
    if stats["open_ends"]:
        print("   ✗ 有端点谁也没接上 ⇒ %s" % ("**照写** ✗（--partial ✓）"
                                          if partial else "**不写文件** ✗"))
        for s in stats.get("misses", []):
            print("      %s" % s)
        if not partial:
            return 1
    n = write(base, out, xml, edits)
    print("   ✓ 已写出 %s（插入 %d 字符 ✓）" % (os.path.basename(out), n))

    # ★★ 独立复核 ✓（**总是跑** ✗✓ —— 2026-10-06 改 ✓）：重新读**刚写出来的文件** ✓，
    #   用 `pcb_check` 的**几何判据**核一遍 ✓。
    #   ✗ 以前它挂在 `--check` 底下（选做 ✓）⇒ 我出 `pixel-pcb-v70.fzz` 时**没加** ✗
    #     ⇒ 交付报告里的数字**全来自布线器自己的模型** ✗ ⇒ 出了「**幽灵连接**」✓：
    #     文件里 `RC` 三只脚**一条线都没有** ✗，而 Fritzing **照样显示「布线完成」** ✗
    #     —— 因为它的连通图是顺着**文件里的 `<connect>` 声明**走的 ✓
    #     （`utils/graphutils.cpp` ✓：`Wire::collectChained` ✓），而写回器**沿用了旧声明** ✗。
    #   ★★ 规矩 ✓（仓规 §13）：「Fritzing 说完成」**不等于**「铜真的连上」✗ ——
    #     **文件是我们生成的时候**，必须用**几何**再核一遍 ✓，并把**几何**的数字当交付依据 ✓。
    print("\n== 独立复核（**重新读刚写的文件** ✓｜几何判据 ✓）==")
    m2 = PC.collect(out)
    # ★ 复核器的 `expect` 要 **dict：网名 → [`"位号.connectorN"`, …] 字符串** ✓
    #   （✗ 我先前直接把 `net_pads` 的元组喂进去 ⇒ 33 条假报把真问题淹了 ✗ —— 2026-10-01 实测 ✓）
    expect = {n2: ["%s.%s" % (t, c) for (t, c) in lst]
              for n2, lst in (net_pads or {}).items()}
    probs, notes, _g = PC.check(m2, expect=expect or None)
    for s in notes:
        print("   · %s" % s)
    for s in probs:
        print("   ✗ %s" % s)
    bad = [s for s in probs if s.startswith("⑤ 网 ")]
    if bad:
        print("\n   ⚠ **这份文件不是全通** ✗：%d 张网里有 %d 张断着 ✗" % (len(expect), len(bad)))
        # ★★ 2026-10-06 改准 ✓：写回器现在**出文件那一刻**已清掉**悬空声明** ✓
        #   （`prune_dangling` ✓，实测 v71 清掉 100 条 ✓、⑫ 复核 = 0 条 ✓）
        #   ⇒ ⑫ **为 0** 时，Fritzing 那句就**应当如实**（它顺着 `<connect>` 走 ✓，
        #     而声明已指向真对象 ✓）⇒ ✗ 不能再笼统写"它大概率会骗你" ✗（那是 v70 那时的情形 ✗）。
        _dang = any(s.startswith("⑫") for s in probs)
        if _dang:
            print("      ⚠ 且 ⑫ 报**还有悬空声明** ✗ ⇒ **Fritzing 大概率显示「布线完成」** ✗"
                  "（它顺着文件里的 `<connect>` 走 ✓）；**旧声明**会让它误判 ✗")
        else:
            print("      ✓ 且 ⑫ = **0 条悬空声明** ✓ ⇒ **Fritzing 那句应当是诚实的** ✓"
                  "（`8 of 9 … 1 connector` ✓）—— ✗ 若你仍看到「布线完成」✗，"
                  "那是**新**问题 ✗，请告诉我 ✓")
        print("      ⇒ **别信状态栏，信这一行** ✓（§13：文件是我们生成的，就必须用几何再核 ✓）")
    else:
        print("\n   ✓ **几何核对：%d 张网全部连通** ✓（**这一行**才是交付依据 ✓）" % len(expect))
    print("   ⇒ %s（走线/过孔几何 ✓）"
          % ("**0 问题** ✓" if not probs else "**有 %d 处问题 ✗**" % len(probs)))
    return 0 if not probs else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
