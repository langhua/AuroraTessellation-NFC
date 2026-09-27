# -*- coding: utf-8 -*-
r"""全接线布线：正交（0°/90°）折线 → 每段一根实体导线 ✓（不再用网标签 ✗）

依据（2026-09-26 从源码 + 用户自己的 sketch 取证 ✓，详见 tools/README.md）：
  · 导线折点：Fritzing **没有**折线导线 ✗ —— 只有「两点直线」✓ 或「两点 + <bezier>」曲线 ✓
    （`items/wire.cpp:856` 调 `m_bezier->write()`；`utils/bezier.cpp:195` 写
     `<bezier><cp0 x y/><cp1 x y/></bezier>`）
    ⇒ **直角拐弯 = 两段导线端点相接** ✓（端点相接即电气相连 ✓）
  · junction **不存文件** ✗，由连接图推出（`wire.cpp:1449` `collectDirectWires`），
    只在 **>2 根线** 交汇处画圆点 ✓ ⇒ 用"两两相连的链"接法就不会出现 junction 点 ✓
  · 连接仍是**连接器级、两端各记一份** ✓

用法：
  py -3.13 f:\git\_scratch\route_build.py <干净画布.fzz> <尺子.svg> <输出.fzz> [--preview 预览.svg]
"""
import copy
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SCRATCH = os.path.dirname(os.path.abspath(__file__))
# ★★ 2026-09-27（用户定 ✓）：通用工具只有一份，在**库仓 tools/** ✓（定位见 `toolpaths.py` ✓）
import toolpaths                                 # noqa: E402
import part_measure as pm                       # noqa: E402
import sch_geom as SG                           # ★ 几何判据（唯一实现 ✓，含斜线 ✓）
import sch_text as ST                           # ★ 字宽表（与渲染器、摆位脚本同一份 ✓）
import pins_ref as PR                           # ★ 生成的位号数据（行/字号 ✓，入库 ✓）
from pin_ruler import apply, mul, parse_tf       # noqa: E402

# ── 网表（照 `hardware/pixel/pixel-netlist.md` §2 ✓；脚名按 .fzp 的连接器名，
#    大小写不敏感 ✓；"#N" = 第 N 个脚（core 件没有名字 ✓））────────────────────────
NETS = {
    "COIL_A":   [("L1", "inner"), ("D3", "AC1")],
    "COIL_B":   [("L1", "outer"), ("D3", "AC2")],
    "GND":      [("D3", "A1"), ("D3", "A2"), ("C1", "#2"), ("U1", "VSS"), ("C2", "#2"),
                 ("LED2", "GND"), ("J1", "#2"), ("J2", "#2"),
     # ★ 裸焊盘/底板必须接地（2026-09-26 用户定 ✓）：原来写成"独立成网、单脚网无线"是错的 ✗
     #   —— EPAD 要**接到 GND** ✓（原理图上就接过来 ✓；元件库里它仍是独立脚 ✓ 见 AGENTS §5 ✓）
                 ("U1", "EPAD")],
    "BR+":      [("D3", "C1"), ("D3", "C2"), ("R1", "#1")],
    "RC":       [("R1", "#2"), ("C1", "#1"), ("U1", "PA1")],
    "5V":       [("U1", "VDD"), ("C2", "#1"), ("LED2", "VDD"), ("J1", "#1"), ("J2", "#1")],
    "DATA_IN":  [("U1", "PA2"), ("J1", "#3")],
    "DATA_OUT": [("U1", "PD0"), ("J2", "#3")],
    "LED_DIN":  [("U1", "PC6"), ("LED2", "DI")],
}


def build_ruler(svg):
    r"""从 Fritzing 导出的 SVG 建"尺子"：partID → {绘图原点, 各脚坐标}（导出坐标 ✓）

    注：这套坐标只用于**元件内部**的相对量取 ✓；跨元件的绝对换算必须用 recal_pins.py
    从渲染反推的全局映射 ✗（2026-09-26 踩坑：逐元件公式跨元件不成立 ✓）。
    """
    root = ET.parse(svg).getroot()
    ruler = {}

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("partID"):
            pid = el.get("partID")
            ruler.setdefault(pid, {"origin": None, "pins": {}})
        if pid in ruler and el.get("id") == "schematic" and ruler[pid]["origin"] is None:
            ruler[pid]["origin"] = apply(m2, 0, 0)
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm and pid in ruler and el.get("x") is not None:
            ruler[pid]["pins"].setdefault("connector" + mm.group(1),
                                          apply(m2, float(el.get("x")), float(el.get("y"))))
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)
    return ruler

RATIO = 1.25
CLEAR = 6.0            # 导线离元件本体至少留这么远（sketch 单位；6 ≈ 1.7mm ✓）
CH_OFFS = (CLEAR, 12.0, 22.0, 34.0)
DIAG_PEN = 1.25        # ★ 斜线的小罚分（“长度 × 1.25 才等于” ✓）
# ★★ K：一个“交集”值多少长度 ✓（面包板规则 ⑧ ✓：**K = 10mm/交集** ✓）
#   —— 这是**人为选的经验值** ✓（不是从数据推的 ✗），**是个可以调的系数** ✓：
#     调大 = 更看重少交叉 ✓；调小 = 更看重短而直 ✓。代码里就这一行 ✓。
#   单位换算：10mm × 3.5433 = **35.4 sketch 单位** ✓。
K_INTER = 35.4
# ★★ K_OUT：**一根线跑到"所有零件包围盒之外"的那部分长度**值多少倍 ✓
#   （2026-09-27 ✓，从**用户手改版**里学来的性格 ✓）
#   ✗ 我的 v8 有一根线先向左跑 **61 单位**（比 J1 还左 ✗）再横着回来 ⇒
#     画布被撑到 90.9×90.5mm ✗、中间空出一大块 ✗、还横穿 3 根线 ✗（用户：“扎眼” ✗）；
#   ✓ 他的手改版：画布 **78.7×83.1mm** ✓、每根线都待在零件之间 ✓。
#   ⇒ 跑出去的长度按 K_OUT 倍罚 ✓（只罚“出去”那一段 ✓，出界一点点（标签/45° 小拐角）不受怨 ✓）。
K_OUT = 10.0
OUT_MARGIN = 7.2      # 包围盒外扩（1 格 ✓）：小出界不算往外跑 ✓
# ★★ `CLEAR_PIN`：**导线与“不相连的引脚”之间要留的安全距离** ✓（2026-09-27 用户定 ✓）
#   用户原话："导线离芯片引脚太近了 ⇒ 应该有安全距离，让导线和引脚的连接关系**肉眼看得清**" ✓。
#   实测（把导出放大看 ✓）：U1 右侧 `14/15/12/11` 的**引脚线末端正好落在导线上** ✗、
#   上侧 `20..16` 与下侧 `7..10` 那么贴着导线 ✗ ⇒ 谁接了、谁没接，**图上分不出来** ✗。
#   取 **1 格（7.2 单位 = 2.03mm）** ✓（引脚间距本身是 9∼15 单位 ✓ ⇒ 7.2 能既留出可辨的距离、
#   又不会无路可走 ✓）。规则放在**交叉数之前**的档位 ✓（它是可读性规则 ✓ 不是审美点缀 ✓）。
CLEAR_PIN = 7.2
ESC_PIN = CLEAR_PIN + 5.0      # “沿引脚轴向逃出去”的长度 ✓（出口就已超过安全距离 ✓）
P_STEP = 2.0          # 判定用的采样步长（单位 ✓，与其余判据同一套口径 ✓）
USE45 = True           # 是否允许 45° dogleg 候选 ✓（`--no45` 关掉 ✓，A/B 用 ✓）
#   ★ 为什么是“罚”不是“禁” ✗（2026-09-27 用户定 ✓：“允许 45° 斜线” ✓）：
#     · 用户指明了允许斜线 ✓；
#     · 我**量了他手改的那一版** ✓ —— 里面的斜线**不是** 45° ✗，而是 **20.1° / 23.4° /
#       28.8° / 2:1…** ✓ ⇒ 他实际的做法是“**两脚之间直接连一根直线**” ✓；
#     ⇒ 实现成**任意角直线**（含 45° ✓），并像面包板那样给斜线一点小罚分 ✓
#       （`bb_route4.py` 的 `DIAG_PEN` 同一个系数 ✓），让它只有在**躲开交叉/避让元件**
#       时才被选中 ✓。`,

# ★ 标定过的脚位置（由 recal_pins.py 从 Fritzing 自己的渲染反推 ✓）：
#   {modelIndex: {connectorId: (x, y)}} —— 有它就用它 ✓（逐元件公式跨元件不成立 ✗，2026-09-26）
PINS_FIX = {}


def tag(el):
    return el.tag.split("}")[-1]


def shape_pts(el):
    a, t = el.attrib, tag(el)
    n = lambda k: pm.num(a.get(k))            # noqa: E731
    if t == "rect":
        x, y, w, h = n("x"), n("y"), n("width"), n("height")
        return [(x, y), (x + w, y + h)] if None not in (x, y, w, h) else []
    if t == "line":
        return [(n("x1"), n("y1")), (n("x2"), n("y2"))]
    if t == "circle":
        cx, cy, r = n("cx"), n("cy"), n("r")
        return [(cx - r, cy - r), (cx + r, cy + r)] if None not in (cx, cy, r) else []
    if t == "ellipse":
        cx, cy, rx, ry = n("cx"), n("cy"), n("rx"), n("ry")
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)] if None not in (cx, cy, rx, ry) else []
    if t in ("polyline", "polygon", "path"):
        key = "points" if t in ("polyline", "polygon") else "d"
        v = [float(x) for x in re.findall(r"-?[\d.]+", a.get(key) or "")]
        return list(zip(v[0::2], v[1::2]))
    return []


def body_pts(el, m, out):
    """本体的导出坐标点 ✓

    ★★ 2026-09-27 修（实测 ✓）：原来**跳过** `class="pin"` 与 `*terminal` ✗
      ⇒ keep-out 盒**只框住本体矩形** ✗（实测 `U1(41.5,-31.5→104.5,31.5)` ✓ 63×63 ✓，
        而 U1 的引脚线伸到 x=29.8…116.2 ✓）⇒ 布线器就钻了空子 ✗：
        在 **x=106.13** 竖着走 135 单位 ✓ —— 正好在 **U1 引脚线那一带** ✗
        ⇒ 导线从**引脚线之间**穿过去 ✗（视觉上就像接上了 ✗ **最容易误导人** ✗）。
      ✓ 现在把引脚线也算进本体框 ✓（与 `render_sch.py` 的量尺**同口径** ✓），
        这样"贴着一排脚的外侧"就不再是可走的走廊 ✓。
      ⚠ 注意：引脚**末端**就在框边界上 ✓ ⇒ 导线从**外面**接到脚上不会因此被挡 ✗
        （自己的元件本来就有豁免 ✓，且豁免已收紧到"端点 R 单位以内" ✓）。
    """
    if tag(el) == "text":
        return
    for (x, y) in shape_pts(el):
        out.append(apply(m, x, y))
    t = el.get("transform")
    m2 = pm_mul(m, t)
    for c in el:
        body_pts(c, m2, out)


def pm_mul(m, t):
    from pin_ruler import mul, parse_tf
    return mul(m, parse_tf(t)) if t else m


# ─────────────────────────── 几何 ───────────────────────────
def load_geom(fzz, svg):
    ruler = build_ruler(svg)
    root = ET.parse(svg).getroot()
    boxes = {}

    def walk(el, m, pid):
        m2 = pm_mul(m, el.get("transform"))
        if el.get("partID"):
            pid = el.get("partID")
        if pid and el.get("id") == "schematic" and pid not in boxes:
            pts = []
            body_pts(el, m2, pts)
            boxes[pid] = pts
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)

    z = zipfile.ZipFile(fzz)
    sroot = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    conname, con_of = {}, {}
    for n in z.namelist():
        if n.startswith("part.") and n.endswith(".fzp"):
            r = ET.fromstring(z.read(n))
            conname[r.get("moduleId")] = {c.get("id"): (c.get("name") or "")
                                          for c in r.iter("connector")}
    insts = {}
    for e in sroot.iter("instance"):
        vw = pm.child(e, "views")
        sub = pm.child(vw, "schematicView") if vw is not None else None
        g = pm.child(sub, "geometry") if sub is not None else None
        if g is None or g.get("x") is None:
            continue
        mi = e.get("modelIndex")
        title = (e.findtext("title") or "").strip()
        loc = (pm.num(g.get("x")), pm.num(g.get("y")))
        pid = next((p for p in ruler if p.startswith(mi) and len(p) == len(mi) + 1),
                   mi if mi in ruler else None)
        ox, oy = ruler[pid]["origin"] if pid else (0, 0)
        # ★★★ `sk`：尺子坐标 → sketch 坐标 ✓ —— **只有一句：乘一个比例** ✓✓
        #   ✗ 旧写法 `loc + RATIO*(x - ox)`（`ox` = 尺子里"用户坐标 (0,0)"的位置）**是错的** ✗：
        #     `ox` ≠ 零件锚点 ✗ ⇒ 它会**减掉每个零件自己的平移** ✗ ⇒
        #     凡 `viewBox 原点 ≠ (0,0)` 或**带旋转**的零件，脚位一律偏 ✗
        #     （2026-09-27 实测 ✓，`_scratch/diag_pins.py` 逐件对出来的 ✓）：
        #       D3/L1/LED2/R1（原点 (0,0)）差 **0.0001 单位** ✓ 看不出问题 ✗；
        #       J1/J2（`viewBox="0.00 -0.50 …"`）差 **1.7718 = k×0.5mm** ✗；
        #       U1（`viewBox="-190 -190 …"`）差 **17.1 = k×190** ✗；
        #       C1/C2（再加旋转 180°）差 **31.37** ✗。
        #     ⇒ 后果：**画出来的导线够不到脚** ✗（用户原图里那 6 个"悬空端"就是这么来的 ✓，
        #       不是手画错 ✗ —— 我当时误判成用户的图 ✗，记下来别再犯 ✗）。
        #   ✓ 正解：尺子本身就是"一张按比例画的 sketch" ✓ ⇒ `sketch = RATIO × 尺子坐标` ✓；
        #     比例由**尺子的单位**定：Fritzing 导出（1/72in）= **1.25** ✓；
        #     本项目 `render_sch.py` 出图（就是 sketch 单位）= **1.0** ✓（`--ratio` ✓）。
        sk = lambda x, y: (RATIO * x, RATIO * y)                     # noqa: E731
        pins, pins_export = {}, {}
        if pid:
            for cid, (ex, ey) in ruler[pid]["pins"].items():
                pins_export[cid] = (ex, ey)
                pins[cid] = sk(ex, ey)
        if PINS_FIX.get(mi):                  # ★ 优先用标定值 ✓（精确 ✓）
            for cid, p in PINS_FIX[mi].items():
                if cid in pins:
                    pins[cid] = p
        pts = [sk(x, y) for (x, y) in boxes.get(pid, [])] if pid else []
        box = None
        if pts:
            box = (min(p[0] for p in pts), min(p[1] for p in pts),
                   max(p[0] for p in pts), max(p[1] for p in pts))
        # ★ 位号框避让 —— **试过、实测不划算、已回退** ✗（2026-09-27 ✓）：
        #   让布线器认识位号框后，位号压导线只从 **3 → 2** ✗（剩下的是 `L1`：
        #   它旁边根本没有别的通道 ✓），代价却是 **压线 8 → 10** ✗、总长 +13 ✗
        #   ⇒ 净亏 ✓。位号那条得靠**位号自己挪**（布线完再重摆 ✓ = 下一手 ✓），
        #   不是让导线绕 ✗ —— 按规矩：“修一个小问题要叠第二个补偿性改动 ⇒ 停手” ✓。
        insts[title] = {"mi": mi, "mid": e.get("moduleIdRef"), "el": e, "sub": sub,
                        "loc": loc, "pins": pins, "box": box, "names": conname,
                        "ox": (ox, oy) if pid else None, "pins_export": pins_export}

    # ★ 全局映射：拿"同一个脚在 sketch 与在导出 SVG 里的坐标"最小二乘拟合 ✓
    #   （2026-09-26：原以为能用 `导出 = ox − loc/1.25` 逐元件推 ✗ —— 实测离散 22 单位 ✗，
    #    说明那个关系只是**逐元件内部**自洽，不能当全局映射 ✓；脚是地面真值 ✓）
    def lin_fit(pairs):
        n = len(pairs)
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        den = sum((p[0] - mx) ** 2 for p in pairs)
        s = sum((p[0] - mx) * (p[1] - my) for p in pairs) / den if den else 1.0
        a = my - s * mx
        return s, a, max(abs(p[1] - (a + s * p[0])) for p in pairs)

    xp, yp = [], []
    for d in insts.values():
        for cid, (ex, ey) in d["pins_export"].items():
            sx, sy = d["pins"][cid]
            xp.append((sx, ex))
            yp.append((sy, ey))
    fit = {"x": lin_fit(xp), "y": lin_fit(yp), "n": len(xp)}
    return sroot, insts, z, fit


def pin_of(insts, ref, name):
    d = insts[ref]
    cmap = d["names"].get(d["mid"], {})
    if name.startswith("#"):
        cid = "connector" + str(int(name[1:]) - 1)
    else:
        cid = next((c for c, nm in cmap.items() if nm.lower() == name.lower()), None)
        if cid is None:
            raise SystemExit("✗ %s 找不到名叫 %s 的脚（有：%s）"
                             % (ref, name, ", ".join("%s=%s" % kv for kv in cmap.items())))
    if cid not in d["pins"]:
        raise SystemExit("✗ 导出里没有 %s 的 %s" % (ref, cid))
    return cid, d["pins"][cid]


# ─────────────────────────── 布线 ───────────────────────────
def seg_hits_box(p, q, box, clear):
    """线段 p→q 是否穿过 box（外扩 clear ✓）"""
    if box is None:
        return False
    x0, y0, x1, y1 = box[0] - clear, box[1] - clear, box[2] + clear, box[3] + clear
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
    for i in range(n + 1):
        t = i / n
        x = p[0] + (q[0] - p[0]) * t
        y = p[1] + (q[1] - p[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def overlap(a, b, c, d, tol=0.5):
    """两段是否**压在一条直线上** ✗（外壳 —— 真正实现在 `sch_geom.near_overlap` ✓

    ★ 为什么删掉自己的实现 ✗（2026-09-27 ✓）：`render_sch.py` 和这里原本**各一份**
      ⇒ 一旦允许斜线，两份会给出**不同**的数 ✗（面包板那天的教训：判碰只能一份实现 ✓）。
      现在这里只是包装 ✓ —— 而且换成**通用**判据（不再只认轴对齐 ✗）✓。
    """
    return SG.near_overlap(a, b, c, d, tol)


def candidates(a, b, chx, chy):
    """候选路径 ✓（★ 含**真正的 45° 斜线** ✓ —— 2026-09-27 用户定 ✓）

    ★ 为什么**不是“任意角直连”** ✗（实测推翻了我自己的实现 ✓）：
      ① 先按用户原话“允许 45°” ✓，又去量了他手改版里的 15 根斜线 ✓ ⇒
         角度是 `20.1° / 23.4° / 28.8° / 2:1…` ✗ —— 不是 45° ✓；
      ② 于是我改成“任意角直连” ✓（想跟他的手画一致 ✓）⇒ **实测大幅变差** ✗✗：
         交叉 **8 → 37∼42** ✗、压线 19 → **88∼100** ✗、总长 2496 → **4941** ✗
         （因为直连线**横穿全图** ✗，且开头几根就把后面的路全堵了 ✗）。
      ⇒ 结论：**只有 45° 的“小斜切”能用** ✓ —— 它只会把拐角“抹掉一点” ✓，
        不会拉出一根横穿全图的斜线 ✗。这就是**工程上的 45° 布线**本意 ✓。
      ★ 斜切只在**省长度**时才被选中 ✓（`diag_extra` 只在最后一档 ✓）：
        斜边 1.414 优于两边 2.0 ✓ ⇒ 对齐得好的地方会自然长出 45° ✓。
    """
    out = []
    if abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6:
        out.append([a, b])                     # ★ **只在轴对齐时**才给直连 ✓
        #   ✗ 非轴对齐的“直连”= **任意角** ✗ ⇒ 实测交叉 8 → 40 ✗✗（它会横穿全图 ✓）
        #   ⇒ 不许 ✓：非轴对齐只走 L 形 / 45° dogleg / 走通道 ✓
    out.append([a, (b[0], a[1]), b])           # L 形
    out.append([a, (a[0], b[1]), b])
    dx, dy = b[0] - a[0], b[1] - a[1]
    sx = 1.0 if dx >= 0 else -1.0
    sy = 1.0 if dy >= 0 else -1.0
    if USE45 and abs(dx) > 1e-6 and abs(dy) > 1e-6:
        # ③④⑤⑥ 45° + 正交的 "dogleg" ✓ —— **四种**落法 × 两侧 = 8 条 ✓
        #   （每一条里**恰有一段是 45°** ✓、另一段正交 ✓ ⇒ 全路径只有 45° 和 0°/90° ✓）
        #   落法：`斜段靠在 a 端`（跑到 b 的列 / 行 ✓）、`斜段靠在 b 端` ✓
        for s in (1.0, -1.0):
            out.append([a, (b[0], a[1] + s * abs(dx)), b])          # 斜段→跑到 b 的列 ✓
            out.append([a, (a[0] + s * abs(dy), b[1]), b])          # 斜段→跑到 b 的行 ✓
            out.append([a, (a[0], b[1] - s * abs(dx)), b])          # 斜段在 b 端，先竖直 ✓
            out.append([a, (b[0] - s * abs(dy), a[1]), b])          # 斜段在 b 端，先水平 ✓
    for x in chx:
        out.append([a, (x, a[1]), (x, b[1]), b])
    for y in chy:
        out.append([a, (a[0], y), (b[0], y), b])
    return out


def bends(path):
    return max(0, len(path) - 2)


def out_len(path, ubox, margin=OUT_MARGIN):
    """路径**跑在“所有零件包围盒”之外**的那部分长度 ✓（2026-09-27 ✓，从用户手改版学的 ✓）

    ★ 为什么只罚“出去的那段”而不是禁 ✗：标签、45° 小拐角、引脚伸出的线都会
      略微出框 ✓ —— 那不算往外跑 ✗；真正要打的是“跑到比所有元件还左/还下”的长途绕行 ✓。
    ★ 采样口径与别的判据一致 ✓（每 2 单位一个中点 ✓，用段长 × 命中数 ✓）。
    """
    if not ubox:
        return 0.0
    x0, y0, x1, y1 = (ubox[0] - margin, ubox[1] - margin,
                      ubox[2] + margin, ubox[3] + margin)
    tot = 0.0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
        step = seg / n
        for k in range(n):
            tm = (k + 0.5) / n
            x, y = p[0] + (q[0] - p[0]) * tm, p[1] + (q[1] - p[1]) * tm
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                tot += step
    return tot


def pin_intr(path, own, pins_all):
    r"""路径**贴到几个“不相连的引脚”**上 ✓（< CLEAR_PIN 就算 ✓）

    ★ 为什么要这条（2026-09-27 用户定 ✓，原话："导线离芯片引脚太近了…让导线和引脚的连接
      关系**肉眼看得清**" ✓）：引脚线本来就有长度 ✓，导线从它末端擦过去 ⇒ 读图的人分不出
      "接上了"还是"路过" ✗ ⇒ 必须拉开一段可辨的距离 ✓。
    ★ `own` = 这根线自己两端的引脚 ✓ ⇒ 它们当然要“贴上” ✓（那是连接点 ✓ 不算侵入 ✗）。
    """
    if not pins_all:
        return 0
    n = 0
    for (ref, cid, px, py) in pins_all:
        if (ref, cid) in own:
            continue
        hit = False
        for i in range(len(path) - 1):
            p, q = path[i], path[i + 1]
            steps = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / P_STEP) + 1)
            for k in range(steps + 1):
                tt = k / steps
                x, y = p[0] + (q[0] - p[0]) * tt, p[1] + (q[1] - p[1]) * tt
                if math.dist((x, y), (px, py)) < CLEAR_PIN:
                    hit = True
                    break
            if hit:
                break
        if hit:
            n += 1
    return n


def diag_extra(path):
    """斜线比正交**多算**的那部分长度 ✓（= `DIAG_PEN` 罚分 ✓；正交段为 0 ✓）

    ★ 只在**最后一档**（长度）里加 ✓ ⇒ 它压不过"少交叉""不穿本体""不出界" ✓
      —— "正交比斜线好看" ✓，但"斜线能换掉一个交叉 / 缩短一截"时仍然选斜线 ✓。
    """
    e = 0.0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        if abs(p[0] - q[0]) > 1e-6 and abs(p[1] - q[1]) > 1e-6:
            e += (DIAG_PEN - 1.0) * math.hypot(q[0] - p[0], q[1] - p[1])
    return e


def plen(path):
    return sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
               for i in range(len(path) - 1))


def inside_count(path, own_boxes, shrink=0.5):
    """路径有多少采样点落在**自己两端元件的本体里** ✓（用一个很小的罚分去避 ✓）

    ★ 为什么要它（2026-09-27 用户的眼睛发现 ✓）：原来对 `my_boxes` **整个豁免** ✗
      ⇒ 导线为了走直线，会从 **U1 / D3 / LED2 的本体里穿过去** ✗（v3 图上很明显 ✗）。
      ✗ 但不能改成"一律禁止" ✗ —— 有的脚（D3 的 `AC1/AC2` ✓）**本来就在本体内部** ✓，
      禁了就无路可走 ✗。⇒ 改成**记代价** ✓：先选不改路 ✓，再选穿得**最少**的路 ✓。
      判据用**采样点数**当代理长度 ✓（与 `seg_hits_box` 同一套采样 ✓）。
    """
    n = 0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        for box in own_boxes:
            if seg_hits_box(p, q, box, -shrink):
                steps = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
                for k in range(steps + 1):
                    t = k / steps
                    x = p[0] + (q[0] - p[0]) * t
                    y = p[1] + (q[1] - p[1]) * t
                    if (box[0] + shrink <= x <= box[2] - shrink
                            and box[1] + shrink <= y <= box[3] - shrink):
                        n += 1
    return n


def seg_cross(p, q, r, s, eps=0.05):
    """两段导线的**内部十字交叉** ✓（外壳 ⇒ `sch_geom.seg_cross` ✓，含斜线 ✓）

    ★ 原来是**正交专用**的本地实现 ✗ ⇒ 一放开斜线，“交叉数”就**少算** ✗✗
      （实测：用户手改版按旧判据是 4 ✗、按新判据是 **18** ✓ —— 拿假数字下过结论 ✗）。
      面包板还教过：判据**只能一份实现** ✓。
    """
    return SG.seg_cross(p, q, r, s)


def cross_count(path, used):
    """这条路径会与**已布好的线**十字交叉几处 ✓（用于代价排序 ✓）"""
    n = 0
    for k in range(len(path) - 1):
        for (p2, q2) in used:
            if seg_cross(path[k], path[k + 1], p2, q2):
                n += 1
    return n


def hits_own_body(path, own_boxes, R=10.0):
    """路径是否**穿过了自己两端元件的本体** ✓（隔端点 R 单位**以外**才算 ✗）

    ★★ 为什么要这条硬限制（2026-09-27 实测 ✓）：
      ✗ 原来对 `my_boxes` **整个豁免** ✗（因为脚往往就在本体边界上 ✓，不允许碰就无路可走 ✓）
        ⇒ 但这样一来，布线器发现了一条**漏洞** ✗✗：
        **在元件肚子里走，谁也遇不到 ⇒ 交叉数最低** ✗ ⇒ 它专挑这种路 ✗
        （实测：一段竖直总线从 `U1` 肚子里穿了 **48.5 mm** ✗、还有一段穿 `J1` 9.6 mm ✗）。
      ✓ 现在：自己的本体只允许在**路径两端 R 单位以内**碰 ✓（= "从脚上走出来" ✓）；
        隔得远还在本体里 ⇒ 一律不许 ✓。R = 10 单位 ≈ 2.8 mm ✓（够离开引脚与边界 ✓）。
    """
    for k in range(len(path) - 1):
        p, q = path[k], path[k + 1]
        for box in own_boxes:
            if not seg_hits_box(p, q, box, -0.5):
                continue
            n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
            for i in range(n + 1):
                t = i / n
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                if (box[0] + 0.5 <= x <= box[2] - 0.5 and box[1] + 0.5 <= y <= box[3] - 0.5
                        and min(math.dist((x, y), path[0]),
                                math.dist((x, y), path[-1])) > R):
                    return True
    return False


def main(argv):
    fzz, svg, out_path = argv[0], argv[1], argv[2]
    if "--ratio" in argv:
        # ★ 尺子的单位换算以**尺子自己**为准 ✓（2026-09-27 加 ✓）：
        #   · Fritzing 导出的 svg = **1/72 in** 一套 ⇒ sketch(1/90in) = 导出 × 1.25 ✓（默认 ✓）；
        #   · 本项目 `render_sch.py` 出的尺子 = **sketch 单位**一套 ⇒ RATIO = **1.0** ✓
        #     （渲染器已对 Fritzing 导出验平 Δ≤0.0004 单位 ✓ ⇒ 不必再让用户手导图 ✗）
        global RATIO
        RATIO = float(argv[argv.index("--ratio") + 1])
        print("尺子换算：RATIO = %.4f（导出尺子 1.25 ✓ / 渲染尺子 1.0 ✓）" % RATIO)
    if "--Kout" in argv:                      # “出界长度”的倍率 ✓（默认 10 ✓）
        global K_OUT
        K_OUT = float(argv[argv.index("--Kout") + 1])
        print("出界代价 K_OUT = %.1f（越大越不许线跑出零件包围盒 ✓）" % K_OUT)
    if "--K" in argv:                         # 一个“交集”值多少长度 ✓（默认 35.4 = 10mm ✓）
        global K_INTER
        K_INTER = float(argv[argv.index("--K") + 1])
        print("交集当量 K_INTER = %.1f sketch 单位（= %.1f mm ✓；越大越看重少交叉 ✓）"
              % (K_INTER, K_INTER * 25.4 / 90.0))
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
    if "--no45" in argv:                     # A/B 用 ✓：关掉 45° 候选（只留正交 ✓）
        global USE45
        USE45 = False
        print("45° 斜线：**关闭** ✓（只走正交 ✓，用于 A/B 对照 ✓）")
    if "--diag" in argv:                      # 斜线罚分可调 ✓（默认 1.25 ✓）
        global DIAG_PEN
        DIAG_PEN = float(argv[argv.index("--diag") + 1])
        print("斜线罚分 DIAG_PEN = %.2f（1.0 = 斜线与正交同价 ✓；越大越少用斜线 ✓）" % DIAG_PEN)
    orig = [argv[argv.index("--orig") + 1]] if "--orig" in argv else [None]
    if "--pins" in argv:                      # 载入标定过的脚位置 ✓
        import importlib.util
        p = argv[argv.index("--pins") + 1]
        spec = importlib.util.spec_from_file_location("pins_fixed", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PINS_FIX.update(mod.PINS)
        print("标定脚位置: 载入 %d 个元件（%s）" % (len(PINS_FIX), p))

    sroot, insts, z, fit = load_geom(fzz, svg)
    print("画布: %d 个实例（%s）" % (len(insts), ", ".join(sorted(insts))))
    print("映射: %d 个脚拟合 ⇒ x: 导出=%.6f·sketch+%.3f（残差 %.4f）✓  y: 导出=%.6f·sketch+%.3f（残差 %.4f）✓"
          % (fit["n"], fit["x"][0], fit["x"][1], fit["x"][2],
             fit["y"][0], fit["y"][1], fit["y"][2]))

    chx, chy = set(), set()
    for d in insts.values():
        b = d["box"]
        # ✗ 试过把“走廊从含引脚的边界起算” ✗ ⇒ 实测侵入反而 13 → **19 处** ✗（回退 ✓）。
        #   原因：通道集里本来就有“引脚自己的坐标” ✓（要能拐到脚上 ✓）⇒ 主干照样能挑中
        #   那条刚好穿过一脚末端的列 ✗；真正要治的是“**谁该占哪条走廊**” ✗（面包板的“留路” ✓）
        #   和“贪婪抢占” ✗（要“抽出重排” ✓）—— 按规矩“要叠第二个补偿改动就停手” ✓ 先回退 ✓。
        if b:
            chx.update(b[0] - o for o in CH_OFFS)
            chx.update(b[2] + o for o in CH_OFFS)
            chy.update(b[1] - o for o in CH_OFFS)
            chy.update(b[3] + o for o in CH_OFFS)
        for p in d["pins"].values():
            chx.add(p[0])
            chy.add(p[1])
    # ✗ 另试过“沿引脚轴向逃出去”的通道（ESC_PIN ✓）⇒ 侵入 13 → **15** ✗（也回退 ✓）：
    #   剩下的侵入不是“离开自己的脚时蹭到”✗，而是**主干型长线从一整排脚前面经过** ✗
    #   （实测 `012917` 正好穿过 `U1.connector0/1/2` 三个脚末端 ✗）⇒ 那是“走廊归属”问题 ✓。
    boxes = {t: d["box"] for t, d in insts.items() if d["box"]}
    # ★ 零件**总包围盒** ✓（“出界”代价项的参照 ✓）：
    UBOX = None
    if boxes:
        UBOX = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
                max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values()))
        print("零件总包围盒 %.1f,%.1f → %.1f,%.1f（外扩 %.1f 单位 ✓；出界的长按 K_OUT=%.1f 倍罚 ✓）"
              % (UBOX[0], UBOX[1], UBOX[2], UBOX[3], OUT_MARGIN, K_OUT))
    print("keep-out 盒: %s" % ", ".join("%s(%.1f,%.1f→%.1f,%.1f)" % ((t,) + b)
                                       for t, b in sorted(boxes.items())))

    used, nets_segs, warn = [], {}, []
    # ★ 全图的**引脚点表** ✓（安全距离规则用 ✓）：绝对 sketch 坐标 ✓
    PIN_ALL = [(t, cid, p[0], p[1]) for t, d in insts.items()
               for cid, p in d["pins"].items()]
    print("引脚点表 %d 个 ✓；安全距离 CLEAR_PIN = %.1f 单位（%.2f mm ✓）"
          % (len(PIN_ALL), CLEAR_PIN, CLEAR_PIN * 25.4 / 90.0))
    # ★ 布线**次序**：先把电源/地布完 ✓、再布信号 ✓（面包板规则 ⑩ ✓：
    #   “先布电源/地，但**要把中间走廊留给后面的信号线**” ✓）。
    #   这里先只做前半条（次序 ✓）；后半条（给电源/地的“走中间”加权 ✓）还没做 ✗。
    POWER_FIRST = ("GND", "5V")
    net_order = [n for n in POWER_FIRST if n in NETS] + \
                [n for n in sorted(NETS) if n not in POWER_FIRST]
    for net in net_order:
        pins = NETS[net]
        if len(pins) < 2:
            print("网 %-9s 只有 %d 个脚 ⇒ 没有线可画 ✓（保持独立 ✓）" % (net, len(pins)))
            continue
        pts = []
        for ref, name in pins:
            cid, p = pin_of(insts, ref, name)
            pts.append({"ref": ref, "cid": cid, "p": p})
        pts.sort(key=lambda d: (round(d["p"][0], 3), round(d["p"][1], 3)))
        segs = []
        for i in range(len(pts) - 1):
            a, b = pts[i]["p"], pts[i + 1]["p"]
            mine = {pts[i]["ref"], pts[i + 1]["ref"]}
            own_pins = {(pts[i]["ref"], pts[i]["cid"]),
                        (pts[i + 1]["ref"], pts[i + 1]["cid"])}
            # 三级：① 不碰本体 + 不与已布线段共线重叠 ✓ ② 只要求不碰本体 ✓ ③ 兜底（否则端点接不上 ✗）
            best, best_key = None, None
            own_boxes = [box for t, box in boxes.items() if t in mine]
            for path in candidates(a, b, sorted(chx), sorted(chy)):
                # ★ 一个代价函数排完所有候选 ✓（不再"先跳掉不合格的" ✗）——
                #   因为放开斜线后，"第一条候选"可能正是最差的一条 ✗，
                #   兜底绝不能瞎拿一条 ✗（2026-09-27 实测：那次兜底把线直穿元件 ✗）。
                nv = 0                       # ① 碰到**别的元件**本体（越少越好 ✓）
                for k in range(len(path) - 1):
                    for t, box in boxes.items():
                        if t not in mine and seg_hits_box(path[k], path[k + 1], box, CLEAR):
                            nv += 1
                # ② **与已布好的线压在同一条直线上** ✗✗ —— v5 实测 **18 对** ✗
                #    （`J1` 三只脚的线**全在同一列上竖着走** ✗ ⇒ 图上像三只脚短路了 ✗）
                #    判据用 `sch_geom.near_overlap` ✓（唯一实现 ✓，含斜线 ✓）
                nov = 0
                for k in range(len(path) - 1):
                    for (p2, q2) in used:
                        if SG.near_overlap(path[k], path[k + 1], p2, q2):
                            nov += 1
                # ★★ 目标函数 = **长度 + K × 交集** ✓（面包板规则 ⑧ ✓，2026-09-27 搬到原理图 ✓）
                #   交集 = 碰别的元件本体 + 与已布线压同一条直线 + 十字交叉 ✓
                #   （面包板当天修正过：“交集”= X 形 + T 形 + 从元件下穿过**三类都算** ✓）。
                #   ★ 为什么要两段式：
                #     · 先只按**交集数**排 ✓（头号指标 ✓）；
                #     · 再按 `长度 + K×交集` 算账 ✓ —— 全程加权会到处加交叉 ✗（实测 ✓）。
                #   ✗ 我先前后试过两个错版（都实测过 ✗，记下来别再试 ✗）：
                #     ① `弯数` 排在 `长度` 前 ✗ ⇒ 宁可拉长斜线换弯 ✗；
                #     ② `长度` 排在 `弯数` 前、且**没有 K** ✗ ⇒ 全变一根直线 ✓ 短 ✓
                #        但**交叉 7 → 42** ✗✗（长直线开头就把后面的路全堵了 ✗）。
                # ★ 代价顺序 = v5 验证过的那一套 ✓（先硬闸门 ✓、再交叉数 ✓、再弯/长 ✓）
                #   · `nv`（碰别的元件）与 `nov`（压在同一条直线上）**当硬闸门** ✓ ——
                #     ✗ 改成“小罚分”实测会把交叉从 8 拉到 40 ✗（漏一角的本体比交叉划算 ✗）✓
                #   · 交叉数保持**头号指标** ✓（面包板教训 ✓）
                # ★★ 代价是**字典序元组** ✗ —— 这是我一再踩的坑 ✓（面包板规则 ⑧ 也栽在这 ✓）：
                #   写在最后一档（长度）里的系数，只有前面**全平**时才起作用 ✗ ⇒
                #   实测 `K_OUT` 0→30 六组结果**一模一样** ✗、`DIAG_PEN` 1.25→1.00 也一样 ✗。
                #   ⇒ “跑到零件外面去”要想真起作用，必须**跟交叉数同级** ✓（放在它**前面** ✓）。
                #   ★ “出界几格”用**格数**（每 7.2 单位 ✓）而不是长度 ✓：
                #     两档之间差一格 ✓ ⇒ “出界一点点”不会被当成“跑出去一大截” ✓。
                ostep = int(out_len(path, UBOX) / 7.2 + 0.9999)
                # ★ **贴近“不相连的引脚”几个** ✓（用户定的可读性规则 ✓ —— 放在交叉数之前 ✓）
                pintr = pin_intr(path, own_pins, PIN_ALL)
                # ★★ `nov`（压在一条直线上）**单独提一档、排在交叉数前面** ✓
                #   （2026-09-27 用户定 ✓）：两段压在同一条直线上 ⇒ 读图的人会以为
                #   **那两根线是一根**（像短路 ✗），比"十字交叉"更该躲 ✓；
                #   用户手改版就是这个取舍 ✓（交叉 12 ✓ 但压线只有 3 ✓）。
                #   ✗ 原来写成 `nov + cross_count(...)` 合成一个数 ⇒ 1 个压线 = 1 个交叉 ✗
                #     （实测压线 8 ✗、手改版 3 ✓）。
                key = (1 if hits_own_body(path, own_boxes) else 0,
                       1 if nv else 0,
                       ostep,
                       pintr,
                       nov,
                       cross_count(path, used),
                       inside_count(path, own_boxes),
                       bends(path),
                       plen(path) + diag_extra(path) + K_OUT * out_len(path, UBOX))
                if best_key is None or key < best_key:
                    best, best_key = path, key
            if best is None:
                warn.append("%s: %s→%s 没找到不碰本体的路径 ✗" % (net, pts[i]["ref"], pts[i + 1]["ref"]))
                best = candidates(a, b, sorted(chx), sorted(chy))[0]
            for k in range(len(best) - 1):
                used.append((best[k], best[k + 1]))
            segs.append({"a": best[0], "b": best[-1], "path": best,
                         "from": pts[i], "to": pts[i + 1]})
        nets_segs[net] = segs
        print("网 %-9s %d 个脚 → %d 段（弯 %d）"
              % (net, len(pts), len(segs), sum(bends(s["path"]) for s in segs)))

    # ── ★ 布完线再重摆位号 ✓（2026-09-27 用户定 ✓）──
    relabel(insts, boxes, used)

    if preview:
        draw_preview(preview, svg, insts, nets_segs, fit)
        print("预览: %s" % preview)
    if warn:
        print("\n⚠ %d 处需要人看：" % len(warn))
        for w in warn:
            print("   " + w)

    if orig[0]:
        emit(sroot, insts, z, nets_segs, orig[0], out_path)
    return 0


def fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else ("%.4f" % v)


def build_wire(tmpl, w):
    """克隆模板导线 → 只留 schematicView + 设本段几何 ✓（连接留到后面统一写 ✓）"""
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", w["mi"])
    t = pm.child(e, "title")
    if t is not None:
        t.text = "Wire" + w["mi"]
    vw = pm.child(e, "views")
    for sub in list(vw):
        if not tag(sub) == "schematicView":
            vw.remove(sub)
    sub = pm.child(vw, "schematicView")
    sub.set("layer", "schematicTrace")
    g = pm.child(sub, "geometry")
    if g is None:
        g = ET.SubElement(sub, "geometry")
    dx, dy = w["q"][0] - w["p"][0], w["q"][1] - w["p"][1]
    # ★ wireFlags 是**位标**（`viewgeometry.h:42`）：NoFlag=0, RoutedFlag=2, PCBTraceFlag=4,
    #   ObsoleteJumperFlag=8, RatsnestFlag=16, AutoroutableFlag=32, NormalFlag=64,
    #   **SchematicTraceFlag=128**
    #   原理图导线的 trace flag 就是 128 ✓（`schematicsketchwidget.cpp:358`）；
    #   少了这一位，`modelbase.cpp` 的 `checkOldSchematics()` 会把线当"旧版导线" ⇒
    #   **不算布线** ✗ ⇒ Fritzing 画虚线、状态栏显示"仍有 N 个插接件需要布线" ✗
    #   （2026-09-26 用户截图发现 ✓；模板是面包板导线，它的值是 64 ✗ 不能照抄 ✓）
    g.attrib.update({"x": fmt(w["p"][0]), "y": fmt(w["p"][1]),
                     "x1": "0", "y1": "0", "x2": fmt(dx), "y2": fmt(dy),
                     "wireFlags": "128"})
    if pm.child(sub, "wireExtras") is None:
        ET.SubElement(sub, "wireExtras", {"mils": "9.7222", "color": "#404040",
                                          "opacity": "1", "banded": "0"})
    for boxel in sub.iter():                     # 清掉模板带来的旧连接 ✗
        if tag(boxel) == "connects":
            for c in list(boxel):
                if tag(c) == "connect":
                    boxel.remove(c)
    return e


def add_conn(view, owner_cid, other_cid, other_mi, other_layer, fallback_layer):
    """把一条连接写进**连接器级** ✓（Fritzing 1.0 只读这一份 ✗）"""
    box = None
    for c in view:
        if tag(c) == "connectors":
            box = c
    if box is None:
        box = ET.SubElement(view, "connectors")
    conn = None
    for c in box:
        if tag(c) == "connector" and c.get("connectorId") == owner_cid:
            conn = c
    if conn is None:
        conn = ET.SubElement(box, "connector", {"connectorId": owner_cid,
                                                 "layer": view.get("layer") or fallback_layer})
        ET.SubElement(conn, "geometry", {"x": "0", "y": "0"})
    cs = pm.child(conn, "connects")
    if cs is None:
        cs = ET.SubElement(conn, "connects")
    ET.SubElement(cs, "connect", {"connectorId": other_cid,
                                   "modelIndex": str(other_mi), "layer": other_layer})


def relabel(insts, boxes, used):
    r"""★ 布完线再把位号重摆一遍 ✓（2026-09-27 用户定 ✓）

    ★ 为什么要在**线布完之后**摆 ✗：摆位脚本那时候还不知道导线在哪 ✗（导线是后布的 ✓）
      ⇒ 实测总有 **3 处**"位号压导线" ✗。
    ★ 为什么不让**导线**避位号 ✗：试过了 ✓ —— 位号压导线只从 3 降到 2 ✗，
      代价是"压线 8→10、总长 +13" ✗ ⇒ **净亏** ✓（已回退 ✓）。
      正解在这头 ✓：**位号可以自由挪** ✓、导线挪一次要牵动全局 ✗。
    ★ 候选位与摆位脚本**同一套 7 个** ✓（上·左/右/中 ✓、下·左/右 ✓、左/右 ✓）；
      判碰只有 `sch_text.label_bbox` 一个实现 ✓（字宽表唯一 ✓）；
      权重：压**别的元件** 10 ✓、压**导线** 5 ✓、压**已放的位号** 5 ✓。
    """
    items = []
    for t, d in insts.items():
        lab = PR.LAB.get(d["mi"]) or {}
        ln, fs = lab.get("lines") or [], lab.get("fs", 5.0)
        tg = pm.child(d["sub"], "titleGeometry")
        if not ln or tg is None or (tg.get("visible") or "true") == "false":
            continue
        items.append((t, d, tg, ln, fs,
                      max(ST.twidth(s, fs) for s in ln), fs * len(ln)))

    def score(b, t):
        sc = 0
        for t2, box in boxes.items():
            if t2 != t and box and _ov2(b, box):
                sc += 10
        for (p, q) in used:
            if _seg_in_box(p, q, b):
                sc += 5
        for t2, b2 in placed:
            if _ov2(b, b2):
                sc += 5
        return sc

    # 长位号先放（大的先占位 ✓，与摆位脚本同一策略 ✓）
    items.sort(key=lambda z: -z[5])
    placed, moved, before, after = [], 0, [0, 0, 0], [0, 0, 0]
    for t, d, tg, ln, fs, w, h in items:                     # 先量"现状" ✓
        b = ST.label_bbox(pm.num(tg.get("x")), pm.num(tg.get("y")), fs, ln)
        before[0] += sum(1 for t2, box in boxes.items() if t2 != t and box and _ov2(b, box))
        before[1] += sum(1 for (p, q) in used if _seg_in_box(p, q, b))
        before[2] += sum(1 for _t2, b2 in placed if _ov2(b, b2))
        placed.append((t, b))
    placed = []
    for t, d, tg, ln, fs, w, h in items:
        bx, gap = boxes.get(t), 7.2
        if bx is None:
            continue
        cand = [(bx[0], bx[1] - gap - h), (bx[2] - w, bx[1] - gap - h),
                ((bx[0] + bx[2] - w) / 2.0, bx[1] - gap - h),
                (bx[0], bx[3] + gap), (bx[2] - w, bx[3] + gap),
                (bx[0] - gap - w, bx[1]), (bx[2] + gap, bx[1])]
        old = ST.label_bbox(pm.num(tg.get("x")), pm.num(tg.get("y")), fs, ln)
        best, bk = None, None
        for x, y in cand:
            b = (x, y, x + w, y + h)
            sc = score(b, t)
            if bk is None or sc < bk:
                best, bk = b, sc
        if best is None:
            continue
        if (abs(best[0] - old[0]) > 0.01 or abs(best[1] - old[1]) > 0.01):
            tg.set("x", fmt(best[0]))
            tg.set("y", fmt(best[1] - 0.25 * fs))            # `label_bbox` 的盒上缘 = y + 0.25fs ✓
            d2 = insts[t]
            tg.set("xOffset", fmt(best[0] - d2["loc"][0]))
            tg.set("yOffset", fmt(best[1] - 0.25 * fs - d2["loc"][1]))
            moved += 1
        placed.append((t, best))
        after[0] += sum(1 for t2, box in boxes.items() if t2 != t and box and _ov2(best, box))
        after[1] += sum(1 for (p, q) in used if _seg_in_box(p, q, best))
        after[2] += sum(1 for _t2, b2 in placed[:-1] if _ov2(best, b2))
    print("── ★ 位号**布完线重摆** ✓：动 %d 个 ✓ ｜ 压元件 %d→%d ✓ ｜ 压导线 %d→%d ✓"
          " ｜ 压位号 %d→%d ✓" % (moved, before[0], after[0], before[1], after[1],
                                  before[2], after[2]))


def _ov2(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _seg_in_box(p, q, b):
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
    hit = 0
    for k in range(n + 1):
        tt = k / n
        x, y = p[0] + (q[0] - p[0]) * tt, p[1] + (q[1] - p[1]) * tt
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            hit += 1
            if hit >= 3:                     # ★ 与渲染器的判法一致：≥3 个采样点才算"压到" ✓
                return True
    return False


def emit(sroot, insts, z, nets_segs, orig_path, out_path):
    """把每对脚的正交路径拆成「一段一根导线」✓；两端各记一份连接 ✓（链式，不出现 junction 点 ✓）"""
    oz = zipfile.ZipFile(orig_path)
    oroot = ET.fromstring(oz.read([n for n in oz.namelist() if n.endswith(".fz")][0]))
    tmpl = next((copy.deepcopy(e) for e in oroot.iter("instance")
                 if (e.get("moduleIdRef") or "").startswith("Wire")), None)
    if tmpl is None:
        raise SystemExit("✗ 原文件里没有 Wire 模板")
    host = pm.child(sroot, "instances")
    host = sroot if host is None else host
    next_mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1

    wires, links = [], []
    for net in sorted(nets_segs):
        for s in nets_segs[net]:
            chain = []
            for k in range(len(s["path"]) - 1):
                p, q = s["path"][k], s["path"][k + 1]
                if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                    continue
                chain.append({"mi": str(next_mi), "p": p, "q": q,
                              "start_tgt": None, "end_tgt": None})
                next_mi += 1
            if not chain:
                continue
            chain[0]["start_tgt"] = ("pin", s["from"])
            chain[-1]["end_tgt"] = ("pin", s["to"])
            for k in range(len(chain) - 1):
                chain[k]["end_tgt"] = ("wire", chain[k + 1], "connector0")
                chain[k + 1]["start_tgt"] = ("wire", chain[k], "connector1")
            wires.extend(chain)

    for w in wires:                              # 建实例 ✓
        w["el"] = build_wire(tmpl, w)
        host.append(w["el"])
        w["view"] = pm.child(pm.child(w["el"], "views"), "schematicView")
    wire_by_mi = {w["mi"]: w for w in wires}
    part_by_mi = {d["mi"]: d for d in insts.values()}

    for w in wires:                              # 收集两端归属 ✓
        for cid, tgt in (("connector0", w["start_tgt"]), ("connector1", w["end_tgt"])):
            if tgt is None:
                continue
            if tgt[0] == "pin":
                p = tgt[1]
                links.append((w["mi"], cid, "schematicTrace",
                              insts[p["ref"]]["mi"], p["cid"], "schematic"))
            else:
                ow = tgt[1]
                links.append((w["mi"], cid, "schematicTrace",
                              ow["mi"], tgt[2], "schematicTrace"))

    # ★ 去重（2026-09-26）：链上同一对"导线↔导线"会从两头各收集一次 ✗ ⇒
    #   不去重就会写出两条一模一样的 <connect> ✗（实测 Wire…connector1 里出现两条 ✓）
    seen, uniq = set(), []
    for L in links:
        key = tuple(sorted([(L[0], L[1]), (L[3], L[4])]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(L)
    links = uniq

    for (a_mi, a_cid, a_layer, b_mi, b_cid, b_layer) in links:   # 两侧各记一份 ✓
        if a_mi in wire_by_mi:
            add_conn(wire_by_mi[a_mi]["view"], a_cid, b_cid, b_mi, b_layer, a_layer)
        else:
            add_conn(part_by_mi[a_mi]["sub"], a_cid, b_cid, b_mi, b_layer, a_layer)
        if b_mi in wire_by_mi:
            add_conn(wire_by_mi[b_mi]["view"], b_cid, a_cid, a_mi, a_layer, b_layer)
        else:
            add_conn(part_by_mi[b_mi]["sub"], b_cid, a_cid, a_mi, a_layer, b_layer)

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n.endswith(".fz") else z.read(n))
    print("写入: %s（%d 根导线、%d 条连接 ✓）" % (out_path, len(wires), len(links)))


COLORS = ["#c00000", "#0070c0", "#00a050", "#c08000", "#8000c0",
          "#00a0a0", "#c060a0", "#606060", "#a0a000", "#004080"]


def draw_preview(path, base_svg, insts, nets_segs, fit):
    r"""预览 = **Fritzing 自己导出的 SVG**（真符号 ✓）+ 我的走线叠在上面 ✓

    ★ 2026-09-26 用户指出：不许自创一套元件图标 ✗ —— 元件图形完全来自 Fritzing 导出 ✓。
    叠层用**拟合出来的**全局映射 ✓（导出 = s·sketch + A ✓，s≈0.8 = 1/1.25 ✓）。
    """
    txt = open(base_svg, encoding="utf-8").read()
    sx, ax, rx = fit["x"]
    sy, ay, ry = fit["y"]
    print("预览映射: x %.6f/%.3f（残差 %.4f）  y %.6f/%.3f（残差 %.4f）"
          % (sx, ax, rx, sy, ay, ry))
    L = ['<g transform="translate(%.4f,%.4f) scale(%.6f,%.6f)" fill="none">' % (ax, ay, sx, sy)]
    for i, (net, segs) in enumerate(sorted(nets_segs.items())):
        c = COLORS[i % len(COLORS)]
        for s in segs:
            d = " ".join("%s%.1f,%.1f" % ("M" if k == 0 else "L", p[0], p[1])
                         for k, p in enumerate(s["path"]))
            L.append('<path d="%s" stroke="%s" stroke-width="1.15"/>' % (d, c))
        p = segs[0]["path"][0]                 # 网名只作汇总标注（不入 .fzz ✓）
        L.append('<text x="%.1f" y="%.1f" font-size="14" fill="%s" stroke="none">%s</text>'
                 % (p[0] + 6, p[1] - 5, c, net))
    L.append("</g>")
    out = txt.replace("</svg>", "\n".join(L) + "\n</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
