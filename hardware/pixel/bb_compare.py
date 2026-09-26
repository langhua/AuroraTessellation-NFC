# -*- coding: utf-8 -*-
r"""对比两个 fzz 的**面包板跳线**：结构差异 + 布线指标（交叉 / 段数 / 长度 / 遮挡 …）✓

用法:
  py -3.13 bb_compare.py <A.fzz> [<B.fzz>]        # 给两个 ⇒ 差异对比；给一个 ⇒ 只打指标
  py -3.13 bb_compare.py <A.fzz> <B.fzz> --all    # 连"每根线"的明细也打出来

为什么要有这个工具（2026-09-26 用户定 ✓）：
  用户手改过的版本存在 `*_byHand.fzz`（草稿，不入库 ✓）。要能**量**出两边差在哪、
  哪边更好 —— 不能靠肉眼比 "哪张图好看" ✗。
  ★ 用户原则：**引线尽可能少相交** ✓ ⇒ 所以「交叉数」是本工具的头号指标 ✓
  （在 `breadboard-wiring.md` §0b ⑤ 与库仓 `AGENTS.md` §5b 第 10 条有记 ✓）。

几何约定（**只用 fzz 自己 + 面包板行列规律** ✓，不依赖任何仓外文件 ✓）：
  孔 id = `pin<列号><行字母>` ✓；sketch 坐标 x = 9.0000 × 列号 ✓、
  y 见 ROW_Y ✓（1 孔距 = 2.54mm = 9 sketch 单位 ✓；已用 fzz 里线的端点坐标实测核对 ✓）。
"""
import math
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

UNIT_MM = 25.4 / 90.0            # 1 sketch 单位 = 1/90 in = 0.28222 mm ✓
MMU = 3.5433                     # 1mm ≈ 3.5433 sketch 单位 ✓
ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0,
         "F": 81.0, "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
HOLE_R = 1.496                   # 孔的开口半径（sketch 单位 ✓）
WIRE_H = 1.0                     # 跳线半宽（22.2222 mil ⇒ 宽 2.0 单位 ✓）
OBSCURE_LIMIT = 0.05             # ★ 2026-09-27 收紧 ✓（原 **0.30** ✗）：
#   用户报 ✗："v57 里 Wire90012900 违规了，没有检查出来？" —— 实测那根 GND `pin47Z→pin31D`
#   压到 5V 的接线孔 `pin32E`，**只盖 17.7%** ✗（中心距 1.80 单位 = 0.51mm ⇒ 已经**切进孔口** ✗）
#   ⇒ 旧阈值 30% 判"不算遮挡" ✗ 就漏网了 ✓。实物上盖住一点点也插不进跳线 ✓ ⇒ 收到 **5%** ✓。
NEAR_DIST = 6.0                  # 拥挤度：离得比这个近（单位 ✓）算"挤" ✓

COLOR_NAME = {"#404040": "GND(黑)", "#cc1414": "5V(红)", "#418dd9": "DATA_IN(蓝)",
              "#33ffc5": "DATA_OUT(青)", "#25cc35": "LED_DIN(绿)",
              "#ef6100": "RC(橙)", "#ab58a2": "BR+(紫)", "#8c3b00": "COIL_A(棕)",
              "#fa50e6": "COIL_B(粉)", "#999999": "灰", "#ffffff": "白",
              "#fff800": "黄", "#a37911": "赭"}


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in (e if e is not None else []):
        if tag(c) == n:
            return c
    return None


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def hole_xy(hid):
    """孔 id → sketch 坐标（None = 不是孔 id ✓）"""
    m = re.fullmatch(r"pin(\d+)([A-Z])", hid or "")
    if not m or m.group(2) not in ROW_Y:
        return None
    return (9.0 * int(m.group(1)), ROW_Y[m.group(2)])


# ---------------------------------------------------------------- 几何（与路由器同一定义 ✓）
def seg_intersect(p1, q1, p2, q2):
    def o(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    return o(p2, q2, p1) * o(p2, q2, q1) < 0 and o(p1, q1, p2) * o(p1, q1, q2) < 0


def seg_overlap(p1, q1, p2, q2):
    d1 = (q1[0] - p1[0], q1[1] - p1[1])
    d2 = (q2[0] - p2[0], q2[1] - p2[1])
    if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 1e-9:
        return False
    if abs(d1[0]) < 1e-9 and abs(d1[1]) < 1e-9:
        return False
    for t in (p2, q2):
        if abs((t[0] - p1[0]) * d1[1] - (t[1] - p1[1]) * d1[0]) > 1e-6:
            return False
    ax = 0 if abs(d1[0]) > abs(d1[1]) else 1
    a0, a1 = sorted((p1[ax], q1[ax]))
    b0, b1 = sorted((p2[ax], q2[ax]))
    return min(a1, b1) - max(a0, b0) > 1e-6


def on_seg(p, a, b):
    if abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) > 1e-6:
        return False
    return (min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9)


def t_touch(p1, q1, p2, q2):
    """T 形：**一方的端点搭在对方段内** ✗（两条线的**公共端点**不算 ✓ ——
    同一根跳线的各段串接、或两根线接同一个孔，都是正常的 ✓）
    """
    for p in (p1, q1):
        if p in (p2, q2):
            continue
        if on_seg(p, p2, q2):
            return True
    for p in (p2, q2):
        if p in (p1, q1):
            continue
        if on_seg(p, p1, q1):
            return True
    return False


def same_pt(a, b, tol=1e-6):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def pair_kind(a, b, c, d):
    """两条引线相碰的类型 ✓（**唯一实现** ✓，度量与优化器都用它 ✓）

    「交集」（用户判据 ✓）= **X 形交叉 + T 形搭线** ✓ 各算 1 次 ✓；
    **公共端点**（两根线接同一个孔 / 同一根线的串接段 ✓）不算 ✗；
    重叠（共线叠在一起 ✗）另报 ✓（那是布线错误 ✗）。
    """
    if seg_overlap(a, b, c, d):
        return "overlap"
    if seg_intersect(a, b, c, d):
        return "cross"
    for p in (a, b):
        if same_pt(p, c) or same_pt(p, d):
            continue
        if on_seg(p, c, d):
            return "touch"
    for p in (c, d):
        if same_pt(p, a) or same_pt(p, b):
            continue
        if on_seg(p, a, b):
            return "touch"
    return None


def point_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _cap(t):
    """圆盘（半径 HOLE_R ✓）在 **y ≤ t** 这一侧的面积 ✓

    ★ 2026-09-26 修 bug ✓：原来写的是 `r²·acos(-t/r) - t·√(r²-t²)` ✗ ——
    平方根项的**符号反了** ✗ ⇒ 算出来的覆盖面积只有真值的 ~1/5 ✗
    （实测：一根线正好穿过孔心时，真值 ≈85%、旧公式报 15% ✗）
    ⇒ “不许把接线了的孔盖住 >30%” 这条硬规则一直形同虚设 ✗。
    正确：圆盘面积 − 上半弓形（`r²·acos(t/r) − t·√(r²-t²)` ✓）
    """
    r = HOLE_R
    if t <= -r:
        return 0.0
    if t >= r:
        return math.pi * r * r
    seg_above = r * r * math.acos(t / r) - t * math.sqrt(r * r - t * t)
    return math.pi * r * r - seg_above


def obscures(p, q, hpt):
    """导线带（沿 p-q ✓）盖住 hpt 处孔开口的面积比 ✓"""
    s = point_seg_dist(hpt, p, q)
    if s >= HOLE_R + WIRE_H:
        return 0.0
    frac = (_cap(WIRE_H - s) - _cap(-WIRE_H - s)) / (math.pi * HOLE_R * HOLE_R)
    return max(0.0, min(1.0, frac))


# ---------------------------------------------------------------- 读 fzz
class Link(object):
    """一根跳线（可能是多段 Wire 串起来的 ✓）"""

    def __init__(self, wid):
        self.wids = [wid]
        self.color = ""
        self.segs = []               # [(p, q), …] sketch 坐标 ✓
        self.holes = []              # 两端接的孔 ✓
        self.pins = []               # 两端接的**元件脚**（未插孔 ✓，如 EPAD 焊盘 ✓）

    @property
    def legend(self):
        """装饰线（图例色条 ✓）：两头都没接东西 ⇒ 不算接线 ✓，不进指标 ✓"""
        return not self.holes and not self.pins

    @property
    def pts(self):
        """按顺序拼出折线点列 ✓"""
        if not self.segs:
            return []
        out = [self.segs[0][0], self.segs[0][1]]
        for p, q in self.segs[1:]:
            out.append(q if on_seg(out[-1], p, q) or p == out[-1] else q)
        return out

    @property
    def length(self):
        return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in self.segs)


def load(path):
    """读出：跳线表 ✓、孔 → 插在上面的元件脚 ✓、导线 id → Link ✓"""
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(name))

    plugged = {}
    for e in root.iter("instance"):
        if (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        vw = child(e, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        if sub is None:
            continue
        ttl = (e.findtext("title") or "").strip()
        for con in sub.iter():
            if tag(con) != "connector":
                continue
            # ★ 标签要写**元件自己的脚名** ✓（以前拿的是孔号 ✗ ⇒ 显示成 "U1.pin32F" 会
            #   让人以为 U1 有个脚叫 pin32F ✗）
            pname = con.get("connectorId") or "?"
            for c in con.iter():
                if tag(c) != "connect":
                    continue
                if (c.get("layer") or "") != "breadboardbreadboard":
                    continue
                plugged[c.get("connectorId")] = "%s.%s" % (ttl, pname)

    links, by_wid, wid_by_mi = [], {}, {}
    for e in root.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        ttl = (e.findtext("title") or "").strip()
        vw = child(e, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        if sub is None:
            continue                                   # 原理图导线 ✓ 跳过
        g = child(sub, "geometry")
        x, y = num(g.get("x")), num(g.get("y"))
        p = (x + num(g.get("x1")), y + num(g.get("y1")))
        q = (x + num(g.get("x2")), y + num(g.get("y2")))
        we = child(sub, "wireExtras")
        lk = Link(ttl)
        lk.color = (we.get("color") or "") if we is not None else ""
        lk.segs = [(p, q)]
        for c in sub.iter():
            if tag(c) != "connect":
                continue
            lay = c.get("layer") or ""
            cid = c.get("connectorId") or ""
            if lay == "breadboardbreadboard" and hole_xy(cid):
                lk.holes.append((cid, c.get("modelIndex")))
            elif lay == "breadboard":
                lk.pins.append((cid, c.get("modelIndex")))
        links.append(lk)
        by_wid[ttl] = lk
        if e.get("modelIndex") is not None:
            wid_by_mi[e.get("modelIndex")] = ttl

    # 把「同一根跳线的各段」合成一条（Wire ↔ Wire 的连接 ✓）
    parent = {lk.wids[0]: lk.wids[0] for lk in links}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k, lk in by_wid.items():            # dsu 初始化（每段各成一组 ✓）
        parent.setdefault(k, k)
    for e in root.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        ttl = (e.findtext("title") or "").strip()
        vw = child(e, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        if sub is None:
            continue
        for c in sub.iter():
            if tag(c) != "connect" or (c.get("layer") or "") != "breadboardWire":
                continue
            # ★ 连接里记的是对方的 **modelIndex** ✓（不是名字 ✓）—— 按它就对了 ✓
            peer = wid_by_mi.get(c.get("modelIndex"))
            if peer and peer in parent and ttl in parent:
                a, b = find(ttl), find(peer)
                if a != b:
                    parent[a] = b

    merged = {}
    for lk in links:
        merged.setdefault(find(lk.wids[0]), []).append(lk)
    out = []
    for _k, group in merged.items():
        lk = Link(group[0].wids[0])
        lk.wids = [g.wids[0] for g in group]
        lk.color = group[0].color
        lk.segs = [s for g in group for s in g.segs]
        lk.holes = [h for g in group for h in g.holes]
        lk.pins = [p for g in group for p in g.pins]
        out.append(lk)
    return out, plugged


def _mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _parse_tf(t):
    if not t:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for fn, arg in re.findall(r"(\w+)\s*\(([^)]*)\)", t):
        v = [float(x) for x in re.split(r"[ ,]+", arg.strip()) if x]
        if fn == "translate":
            m = _mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0))
        elif fn == "scale":
            m = _mul(m, (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0))
        elif fn == "rotate":
            a = math.radians(v[0])
            m = _mul(m, (math.cos(a), math.sin(a), -math.sin(a), math.cos(a),
                         v[1] if len(v) > 2 else 0.0, v[2] if len(v) > 2 else 0.0))
        elif fn == "matrix" and len(v) == 6:
            m = _mul(m, tuple(v))
    return m


def _apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _local_bbox(sroot):
    """svg 里所有图元（含嵌套 transform ✓）的坐标包围盒（局部单位 ✓）"""
    pts = []

    def nums(s):
        return [float(x) for x in re.findall(r"-?\d*\.?\d+", s or "")]

    def walk(el, m):
        m2 = _mul(m, _parse_tf(el.get("transform"))) if el.get("transform") else m
        t = tag(el)
        g = lambda k, d=0.0: float(el.get(k) or d)          # noqa: E731
        if t == "rect":
            for x, y in ((g("x"), g("y")), (g("x") + g("width"), g("y")),
                         (g("x"), g("y") + g("height")),
                         (g("x") + g("width"), g("y") + g("height"))):
                pts.append(_apply(m2, x, y))
        elif t == "circle":
            cx, cy, r = g("cx"), g("cy"), g("r")
            for x, y in ((cx - r, cy - r), (cx + r, cy + r)):
                pts.append(_apply(m2, x, y))
        elif t == "ellipse":
            cx, cy, rx, ry = g("cx"), g("cy"), g("rx"), g("ry")
            for x, y in ((cx - rx, cy - ry), (cx + rx, cy + ry)):
                pts.append(_apply(m2, x, y))
        elif t in ("line", "polyline", "polygon"):
            v = nums(el.get("points") or "")
            for i in range(0, len(v) - 1, 2):
                pts.append(_apply(m2, v[i], v[i + 1]))
            if t == "line":
                for x, y in ((g("x1"), g("y1")), (g("x2"), g("y2"))):
                    pts.append(_apply(m2, x, y))
        elif t == "path":
            v = nums(el.get("d") or "")
            for i in range(0, len(v) - 1, 2):
                pts.append(_apply(m2, v[i], v[i + 1]))
        for c in el:
            walk(c, m2)

    walk(sroot, (1, 0, 0, 1, 0, 0))
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def part_boxes(fzz):
    """元件本体包围盒（**只作指示** ✓）：用零件面包板 svg 里**画出来的东西**算 ✓。"""
    z = zipfile.ZipFile(fzz)
    name = [x for x in z.namelist() if x.endswith(".fz")][0]
    r = ET.fromstring(z.read(name))
    out = []
    for e in r.iter("instance"):
        mid = e.get("moduleIdRef") or ""
        if mid.startswith("Wire") or "Breadboard" in mid or "LogoText" in mid:
            continue
        ttl = (e.findtext("title") or "").strip()
        sub = child(child(e, "views"), "breadboardView")
        g = child(sub, "geometry") if sub is not None else None
        if g is None:
            continue
        base = re.sub(r"\.fzp$", "", (e.get("path") or "").replace("/", "\\").split("\\")[-1])
        entry = next((n for n in z.namelist()
                      if n.startswith("svg.breadboard.%s_breadboard" % base)), None)
        if entry is None:
            continue
        sroot = ET.fromstring(z.read(entry))
        lb = _local_bbox(sroot)
        if lb is None:
            continue
        w = sroot.get("width") or ""
        mm = float(re.sub(r"[^0-9.]+", "", w) or 0)
        if w.strip().endswith("in"):
            mm *= 25.4
        vb = [float(x) for x in re.split(r"[ ,]+", (sroot.get("viewBox") or "").strip()) if x]
        if not (mm and len(vb) == 4 and vb[2]):
            continue
        k = mm * MMU / vb[2]
        # ★ 局部坐标要先减去 viewBox 原点 ✓（否则 svg 里 "viewBox=8 8 20 20"
        #   这种会整体偏一截 ✗ —— 实测 LED2 的盒子就是这么跑偏的 ✗）
        ox, oy = (vb[0], vb[1]) if len(vb) == 4 else (0.0, 0.0)
        tf = child(g, "transform")
        m = (float(tf.get("m11") or 1), float(tf.get("m12") or 0), float(tf.get("m21") or 0),
             float(tf.get("m22") or 1), float(tf.get("m31") or 0), float(tf.get("m32") or 0)) \
            if tf is not None else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        gx, gy = float(g.get("x") or 0), float(g.get("y") or 0)
        p0 = _apply(m, (lb[0] - ox) * k, (lb[1] - oy) * k)
        p1 = _apply(m, (lb[2] - ox) * k, (lb[3] - oy) * k)
        out.append((ttl, (min(p0[0], p1[0]) + gx, min(p0[1], p1[1]) + gy,
                          max(p0[0], p1[0]) + gx, max(p0[1], p1[1]) + gy)))
    return out


def seg_hits_box(p, q, box):
    """段是否穿过矩形（slab 法 ✓）"""
    x0, y0, x1, y1 = box
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pp) < 1e-9:
            if qq < 0:
                return False
            continue
        t = qq / pp
        if pp < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return t1 - t0 > 1e-9


def seg_crosses_box(p, q, box):
    """段**穿过**矩形内部 ✓（**两端都在框外** ⇒ 真的从模块底下钻过去 ✗）；
    端点落在框内/只擦边 ✗ ⇒ 不算 ✓（导线接在模块脚上、或从模块身边经过 ✓ 都是正常的 ✓）
    """
    x0, y0, x1, y1 = box
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pp) < 1e-9:
            if qq < 0:
                return False
            continue
        t = qq / pp
        if pp < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return t0 > 1e-9 and t1 < 1 - 1e-9


def metrics(links, plugged, fzz=None, verbose=False):
    links = [lk for lk in links if not lk.legend]      # 图例色条不参与指标 ✓
    segs, ends = [], {}
    for lk in links:
        segs.extend(lk.segs)
        for h in lk.holes:
            ends[h[0]] = ends.get(h[0], 0) + 1
    cross = ovl = 0
    cross_pairs = []
    for i, (p, q) in enumerate(segs):
        for j in range(i + 1, len(segs)):
            p2, q2 = segs[j]
            if seg_overlap(p, q, p2, q2):
                ovl += 1
            elif seg_intersect(p, q, p2, q2):
                cross += 1
                cross_pairs.append((segs[i], segs[j]))
    # 遮挡：每段 vs 每个"接线了的孔"（孔自己那两个端点不算 ✓）
    #   ★ "接线了的孔" = **线端点** ✓ + **插了元件脚的孔** ✓（后者以前漏了 ✗ —— 2026-09-26 修 ✓）
    watch = set(ends) | set(plugged)
    hidden = {}
    for lk in links:
        ends_here = {h[0] for h in lk.holes}
        for a, b in lk.segs:
            for h in watch:
                if h in ends_here:
                    continue
                f = obscures(a, b, hole_xy(h))
                if f >= OBSCURE_LIMIT:
                    hidden[h] = max(hidden.get(h, 0.0), f)
    # 端点落在"已插孔的脚"上 ✗（一个脚只能插孔或接一根引线 ✓）
    bad_end = sorted({h for lk in links for a, b in lk.segs for h in ends
                      if h in plugged and not any(h == x[0] for x in lk.holes)
                      and on_seg(hole_xy(h), a, b)})
    # 拥挤度
    crowd = 0
    for i, (a, b) in enumerate(segs):
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        for j, (c, d) in enumerate(segs):
            if i == j:
                continue
            if point_seg_dist(mid, c, d) < NEAR_DIST or point_seg_dist(c, a, b) < NEAR_DIST:
                crowd += 1
    dup = sorted(h for h, n in ends.items() if n > 1)
    # ★ 「斜线段数」（2026-09-26 用户美学 ✓）：正交（水平/垂直）的线好看 ✓、斜线不好看 ✗
    diag = [(p, q) for p, q in segs
            if abs(p[0] - q[0]) > 1e-6 and abs(p[1] - q[1]) > 1e-6]
    # ★★ 「交集」要算全（2026-09-26 用户追问后修 ✓）：以前只数 **X 形交叉** ✗，
    #    漏了 ① **T 形搭线**（一端搭在别人段内 ✗）② **穿过元件本体** ✗ ——
    #    而用户判据是「与引线/元件的交集都算」✓ ⇒ 这里把三种都数出来 ✓
    t_touches = 0
    for i, (p, q) in enumerate(segs):
        for j in range(i + 1, len(segs)):
            if pair_kind(p, q, segs[j][0], segs[j][1]) == "touch":
                t_touches += 1
    part_hits = []
    # ✗ 不用本文件里自算的包围盒 ✗（我对 `path/@d` 的解析不准 ⇒ 盒子偏大 ✗）——
    #   “穿元件”由生成器（`bb_route4.py`，用它已验证的 `pbox.body_box` ✓）单独报 ✓。
    # ★ 每根线的交集数（用户要看"这一根几个相交" ✓）—— 用同一套 `pair_kind` ✓
    per_wire = {}
    for lk in links:
        n = 0
        for p, q in lk.segs:
            for p2, q2 in segs:
                if (p, q) == (p2, q2):
                    continue
                if pair_kind(p, q, p2, q2):
                    n += 1
        if n:
            per_wire["+".join(lk.wids)] = n
    m = {
        "links": len(links), "segs": len(segs),
        "mm": sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in segs) * UNIT_MM,
        "cross": cross, "overlap": ovl, "holes": len(ends), "dup": dup,
        "hidden": hidden, "bad_end": bad_end, "plugged": len(plugged),
        "crowd": crowd / max(1, len(segs)), "cross_pairs": cross_pairs,
        "diag": len(diag), "touch": t_touches, "part_hits": part_hits,
        "per_wire": per_wire,
    }
    return m


def key_of(lk):
    hs = tuple(sorted(x[0] for x in lk.holes))
    ps = tuple(sorted(x[0] for x in lk.pins))
    return (lk.color, hs, ps)


def show(path, links, plugged, m, detail=False, tagv=""):
    nlg = len([lk for lk in links if lk.legend])
    print("%s%s" % (tagv, path))
    print("    线 %d 根 = %d 段 | 总长 %.1f mm (均 %.1f) | 用孔 %d 个 | 插了脚的孔 %d 个 | 图例装饰 %d"
          % (m["links"], m["segs"], m["mm"], m["mm"] / max(1, m["segs"]),
             m["holes"], m["plugged"], nlg))
    print("    ★交集 = 交叉 %d + 搭线(T形) %d + 穿元件 %d = **%d**　| 斜线段 %d | 重叠 %d | "
          "端点落在已插孔的脚上 %d | 遮挡接线孔 %d | 拥挤度 %.2f"
          % (m["cross"], m["touch"], len(m["part_hits"]),
             m["cross"] + m["touch"] + len(m["part_hits"]),
             m["diag"], m["overlap"], len(m["bad_end"]), len(m["hidden"]), m["crowd"]))
    for ttl, p, q in m["part_hits"]:
        print("      [穿元件 ✗] %s  段 (%.1f,%.1f)->(%.1f,%.1f)"
              % (ttl, p[0], p[1], q[0], q[1]))
    if m.get("per_wire"):
        print("      每根线的交集：%s"
              % "，".join("%s=%d" % kv for kv in sorted(m["per_wire"].items(),
                                                      key=lambda kv: -kv[1])))
    if m["dup"]:
        print("    [!] 一个孔被两根线的端点占用 ✗: %s" % ", ".join(m["dup"]))
    if m["bad_end"]:
        print("    [!] 引线落在已插孔的脚上 ✗: %s"
              % ", ".join("%s(%s)" % (h, plugged.get(h, "")) for h in m["bad_end"]))
    if m["hidden"]:
        print("    [!] 引线遮挡了接线孔 ✗: %s"
              % ", ".join("%s(%.0f%%)" % (h, f * 100) for h, f in sorted(m["hidden"].items())))
    if detail:
        for lk in sorted([x for x in links if not x.legend],
                         key=lambda l: (l.color, sorted(x[0] for x in l.holes))):
            print("      %-8s %-24s 段=%d 长=%5.1fmm  端点=%s" % (
                COLOR_NAME.get(lk.color, lk.color), "+".join(lk.wids),
                len(lk.segs), lk.length * UNIT_MM,
                " → ".join([("%s[%s]" % (h, plugged.get(h, ""))) for h, _mi in lk.holes]
                           + ["脚 %s" % c for c, _mi in lk.pins])))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    detail = "--all" in argv
    files = [a for a in argv if not a.startswith("--")]
    data = {}
    for f in files[:2]:
        links, plugged = load(f)
        data[f] = (links, plugged, metrics(links, plugged, f))
    for f in files[:2]:
        links, plugged, m = data[f]
        show(f, links, plugged, m, detail=detail)
        print("")

    if len(data) == 2:
        (fa, (la, pa, ma)), (fb, (lb, pb, mb)) = list(data.items())
        print("—— 差异 ——")
        la = [x for x in la if not x.legend]
        lb = [x for x in lb if not x.legend]
        ka = {}
        for lk in la:
            ka.setdefault(key_of(lk), []).append(lk)
        kb = {}
        for lk in lb:
            kb.setdefault(key_of(lk), []).append(lk)
        onlya = [k for k in ka if k not in kb]
        onlyb = [k for k in kb if k not in ka]
        both = [k for k in ka if k in kb]

        def desc(k, plugged, lks):
            col, hs, ps = k
            return "%-10s %s" % (COLOR_NAME.get(col, col),
                                 " → ".join(["%s[%s]" % (h, plugged.get(h, "")) for h in hs]
                                            + ["脚 %s" % c for c in ps]))
        print("① 两边都有 %d 根" % len(both))
        for k in sorted(both, key=lambda k: -max(len(x.segs) for x in ka[k])):
            A = ka[k][0]
            B = kb[k][0]
            ra = "%d 段 %.1fmm" % (len(A.segs), A.length * UNIT_MM)
            rb = "%d 段 %.1fmm" % (len(B.segs), B.length * UNIT_MM)
            flag = "  ←同" if ra == rb else "  ←**改道**"
            print("   %s   A: %s | B: %s%s" % (desc(k, pa, ka[k]), ra, rb, flag))
        print("② 只有 A 有 %d 根（B 里被删/换了接法）" % len(onlya))
        for k in sorted(onlya):
            print("   %s   %d 段 %.1fmm" % (desc(k, pa, ka[k]), len(ka[k][0].segs),
                                            ka[k][0].length * UNIT_MM))
        print("③ 只有 B 有 %d 根（B 里新增）" % len(onlyb))
        for k in sorted(onlyb):
            print("   %s   %d 段 %.1fmm" % (desc(k, pb, kb[k]), len(kb[k][0].segs),
                                            kb[k][0].length * UNIT_MM))
        print("")
        print("★ 结论：交叉 A=%d / B=%d   ⇒ %s" % (
            ma["cross"], mb["cross"],
            "A 更少 ✓" if ma["cross"] < mb["cross"] else
            ("B 更少 ✓" if mb["cross"] < ma["cross"] else "相同")))
        print("   段数 A=%d / B=%d | 总长 A=%.1f / B=%.1f mm | 用孔 A=%d / B=%d"
              % (ma["segs"], mb["segs"], ma["mm"], mb["mm"], ma["holes"], mb["holes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
