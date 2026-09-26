# -*- coding: utf-8 -*-
r"""零件"本体"在 sketch 里的包围盒（2026-09-26 定稿 ✓）

为什么要它：判"哪些面包板孔被元件挡住"要用**本体** ——
  · 只按 svg 的 width/height（= 画布）会**高估**：画布常带留白 ✗
    （反例：NFC 线圈画布 24×24mm，实际绿色板只画了 20×20mm ⇒ 多遮了一整行孔 ✗）
  · 直接数几何坐标也不行 ✗：`<path d>` 常带**相对命令**、坐标又在 `<g transform>` 里 ✓

本模块干三件事：
  ① `shape_bbox(svg_root)`：把**画出来**的东西（含嵌套 transform ✓）的包围盒算出来，
     单位 = svg 自己的**用户单位**；看不出来/不可信 ⇒ 返回 None ✓（调用方退回画布 ✓）
  ② `to_sketch(box, attrs)`：用户单位 → sketch 单位（Fritzing 惯例：把 svg 的
     width/height 当物理尺寸，viewBox 当坐标系 ✓；1mm = 3.5433 sketch 单位 ✓）
  ③ `place(loc, m, box)`：再按实例的 `<transform>` 矩阵搬到 sketch 绝对坐标 ✓
     —— 零件摆放 = `sketch = loc + M·(局部 sketch 单位) + (m31,m32)` ✓

用法：
    import part_box as pb
    box = pb.body_box(svg_path)              # (x0,y0,x1,y1) sketch 单位（相对画布原点）
    rect = pb.place(loc, tf_matrix, box)     # sketch 绝对矩形
"""
import re
import xml.etree.ElementTree as ET

MM = 3.5433                     # 1 mm = 3.5433 sketch 单位 ✓（1/90 in ✓）


def tag(e):
    return e.tag.split("}")[-1]


# ── 2×3 矩阵（SVG 约定：[a,b,c,d,e,f] = (m11,m12,m21,m22,m31,m32) ✓）───────────
def mul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def parse_tf(s):
    """解析 transform 串（translate/scale/matrix/rotate ✓）→ 2×3 矩阵"""
    import math
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, arg in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.split(r"[,\s]+", arg.strip()) if x]
        if name == "translate":
            m = mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0))
        elif name == "scale":
            m = mul(m, (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0))
        elif name == "matrix":
            m = mul(m, tuple(v[:6]))
        elif name == "rotate":
            a = math.radians(v[0])
            t = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:                        # rotate(a cx cy) ✓
                t = mul(mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
            m = mul(m, t)
    return m


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def tf_of(el):
    """实例 geometry 里的 <transform m11…m32> ✓；没有 ⇒ 单位阵 ✓"""
    t = next((c for c in el if tag(c) == "transform"), None)
    if t is None:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    n = lambda k, d: float(t.get(k) or d)          # noqa: E731
    return (n("m11", 1), n("m12", 0), n("m21", 0), n("m22", 1), n("m31", 0), n("m32", 0))


def _nums(s):
    return [float(v) for v in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", s or "")]


def _path_pts(d):
    """把 path 的**坐标点**取出来（只认**参数个数固定**的绝对命令 ✓）
       相对命令（小写 m/l/h/v 等）坐标不是绝对坐标 ⇒ 整条跳过 ✓（宁可少算，由调用方兜底 ✓）"""
    if not d:
        return None
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    out, i, cur = [], 0, None
    narg = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    while i < len(toks):
        c = toks[i]
        if not c.isalpha():
            return None                        # 命令之间夹了裸数字 ⇒ 解析不了 ⇒ 放弃 ✓
        if c not in narg:
            return None                        # 出现相对命令 ⇒ 放弃 ✓
        i += 1
        if c == "Z":
            continue
        while i + narg[c] <= len(toks) and not toks[i].isalpha():
            v = [float(x) for x in toks[i:i + narg[c]]]
            i += narg[c]
            v = list(v)
            if c == "H":
                cur = (v[0], cur[1] if cur else 0.0)
            elif c == "V":
                cur = (cur[0] if cur else 0.0, v[0])
            elif c == "A":
                cur = (v[5], v[6])
            else:
                for k in range(0, len(v) - 1, 2):
                    out.append((v[k], v[k + 1]))
                cur = (v[-2], v[-1])
            if c in ("H", "V", "A"):
                out.append(cur)
            if i < len(toks) and toks[i].isalpha():
                break
            if i + narg[c] > len(toks):
                break
    return out or None


def shape_bbox(root):
    """画出来的一切的包围盒（**用户单位**、含嵌套 transform ✓）；不可信 ⇒ None ✓"""
    xs, ys = [], []

    def walk(el, m):
        t = el.get("transform")
        m = mul(m, parse_tf(t)) if t else m
        if tag(el) == "defs":
            return
        for c in el:
            walk(c, m)

        def add(x, y):
            px, py = apply(m, x, y)
            xs.append(px)
            ys.append(py)

        t2 = tag(el)
        try:
            if t2 == "rect":
                x, y = float(el.get("x") or 0), float(el.get("y") or 0)
                w, h = float(el.get("width") or 0), float(el.get("height") or 0)
                for dx in (0, w):
                    for dy in (0, h):
                        add(x + dx, y + dy)
            elif t2 == "circle":
                cx, cy, r = (float(el.get(k) or 0) for k in ("cx", "cy", "r"))
                for dx, dy in ((-r, -r), (r, r), (r, -r), (-r, r)):
                    add(cx + dx, cy + dy)
            elif t2 == "ellipse":
                cx, cy = float(el.get("cx") or 0), float(el.get("cy") or 0)
                rx, ry = float(el.get("rx") or 0), float(el.get("ry") or 0)
                for dx, dy in ((-rx, -ry), (rx, ry), (rx, -ry), (-rx, ry)):
                    add(cx + dx, cy + dy)
            elif t2 == "line":
                add(float(el.get("x1") or 0), float(el.get("y1") or 0))
                add(float(el.get("x2") or 0), float(el.get("y2") or 0))
            elif t2 in ("polyline", "polygon"):
                v = _nums(el.get("points"))
                for k in range(0, len(v) - 1, 2):
                    add(v[k], v[k + 1])
            elif t2 == "path":
                for p in (_path_pts(el.get("d")) or []):
                    add(p[0], p[1])
            elif t2 == "text":
                add(float(el.get("x") or 0), float(el.get("y") or 0))
        except (TypeError, ValueError):
            pass
    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    if len(xs) < 2:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def pin_points(root):
    """`id="connector<N>pin"` 的**参考点**（根用户单位、走完祖先 transform ✓）

    ⇒ `({id: (x, y)}, 认不出的清单 ✓)`；认不出**要点名报出** ✓（不静默跳过 ✗）。

    ★★ 为什么必须走 transform 链 ✓（2026-09-27 实测 ✓，我为此连错三次 ✗）：
      `WS2812B_1010` 的 4 个焊盘各在一个 `translate(…, …)` 组里 ✓：
        · 组 translate：34.035 → 234.035 ⇒ 差 **200**（**假的** ✗）；
        · 组内 `<rect x>`：−31.584 → −217.184 ⇒ 差 **−186** ✓；
        ⇒ **两个大数互抵**，真脚距只有 **14.401** ✓（21.600 在 y ✓）。
      只看元素自己的 x/y ⇒ 会拿到 200 这种假值 ✗；**相邻两个数字之差 ≠ 几何** ✗。
    """
    got, legs, bad = {}, {}, []

    def ref(el):
        t = tag(el)
        if t in ("circle", "ellipse"):
            return (float(el.get("cx") or 0), float(el.get("cy") or 0))
        if t == "rect":
            return (float(el.get("x") or 0) + float(el.get("width") or 0) / 2.0,
                    float(el.get("y") or 0) + float(el.get("height") or 0) / 2.0)
        if t == "line":
            return ((float(el.get("x1") or 0) + float(el.get("x2") or 0)) / 2.0,
                    (float(el.get("y1") or 0) + float(el.get("y2") or 0)) / 2.0)
        return None

    def ends(el):
        """`<line>` 的两端 ✓（腿只认 line ✓）"""
        if tag(el) != "line":
            return None
        return ((float(el.get("x1") or 0), float(el.get("y1") or 0)),
                (float(el.get("x2") or 0), float(el.get("y2") or 0)))

    def walk(el, m):
        if tag(el) == "defs":
            return
        for c in el:
            if tag(c) == "svg":                 # 嵌套视口没处理 ⇒ 明说 ✓（别当没事 ✗）
                bad.append("<嵌套 <svg> 视口（未处理 ✗）>")
                continue
            t = c.get("transform")
            mc = mul(m, parse_tf(t)) if t else m
            eid = c.get("id") or ""
            if re.match(r"^connector\d+pin$", eid):
                p = ref(c)
                if p is None:
                    bad.append("%s=<%s>（认不出参考点 ✗）" % (eid, tag(c)))
                else:
                    got[eid] = apply(mc, p[0], p[1])
            ml = re.match(r"^(connector\d+)leg$", eid)
            if ml:
                e2 = ends(c)
                if e2 is None:
                    bad.append("%s=<%s>（腿不是 <line> ✗）" % (eid, tag(c)))
                else:
                    legs[ml.group(1)] = (apply(mc, e2[0][0], e2[0][1]),
                                         apply(mc, e2[1][0], e2[1][1]))
            walk(c, mc)

    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    # ★★ 有 `legId`（**core 件约定** ✓）⇒ **连接点在腿尖** ✓（2026-09-27 机验钉死 ✓）：
    #   core 的 .fzp 写的是 `<p layer="breadboard" svgId="connector0pin" legId="connector0leg"/>` ✓
    #   —— "腿尖才是插进孔的那个点" ✓；而 `svgId` 那个小 rect 是**看不见的标记**
    #   （`fill="none"` ✗，宽 3 高 1 ✓）⇒ 拿它当连接点会错 ✓。
    #   证据 ✓：C1 两条腿的**远端** → `pin16J`/`pin17J` ⇒ **Δ=0.00 / 0.02** ✓✓
    #   （若取标记中心 ⇒ Δ=26.55 ✗✗，就是一条假警报 ✗）。
    #   "远端" = 离**图形包围盒中心**较远的那一端 ✓（电容腿朝下 ✓、电阻腿朝左右 ✓ 都成立 ✓）。
    #   ✗ 已知例外（**core 自己的桩画错了** ✗，不是我们的 ✗）：
    #     · `ceramic_capacitor_blue_leg.svg` 的 `connector1leg` 与
    #     · `resistor_220.svg` 的 `connector1leg`
    #     都离**真正的腿尖**差 **10 用户单位（= 9 sketch 单位 = 2.54mm = 1 孔）** ✗
    #     ⇒ 这两个脚仍报 Δ=9 ✓。**判据**：用户自己手工做的 `pixel-breadboard43_byHand.fzz`
    #     里**一模一样** ✓（Fritzing 自己写下的记录与它自己的图形不符 ✓）⇒ 不属于我们的错 ✗。
    bb = shape_bbox(root)
    for cid, (pa, pb) in legs.items():
        if bb is None:
            tip = pa
        else:
            cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
            tip = pb if ((pb[0] - cx) ** 2 + (pb[1] - cy) ** 2) > \
                        ((pa[0] - cx) ** 2 + (pa[1] - cy) ** 2) else pa
        got["%spin" % cid] = tip
    return got, bad


def resolve_svg(fzp_path, image):
    """按 fzp 的 `breadboardView/layers@image` 找到真 svg ✓

    照 Fritzing 的目录约定：`<parts>/svg/{'',core,contrib,user}/<image>` ✓
    （user 件在 `…/Documents/Fritzing/parts/user/x.fzp` ✓，svg 在 `…/parts/svg/user/breadboard/x.svg` ✓）
    找不到 ⇒ None ✓（**不静默** ✓：调用方要报出来 ✓）。
    """
    if not image or not fzp_path:
        return None
    import os                       # ★ 本模块原本不 import os ✓（函数内导入最稳 ✓，不动文件头 ✓）
    base = os.path.dirname(os.path.dirname(fzp_path))
    for s2 in ("", "core", "contrib", "user"):
        cand = os.path.normpath(os.path.join(base, "svg", s2, image.replace("/", os.sep)))
        if os.path.isfile(cand):
            return cand
    return None


def canvas_mm(attrs):
    """svg 的 width/height → mm ✓（mm/cm/in/mil/px/pt ✓），取不到 ⇒ None ✓

    ★★ 2026-09-27 修 ✓：`px` 由 **25.4/96 ✗ 改成 25.4/72** ✓（= 1/72 英寸 ✓）。
      原来按 96dpi 算 ⇒ **px 件的本体小 25%** ✗ ⇒ “本体遮住了哪些孔”**少算** ✗
      ⇒ 可能把线布到元件底下 / 审计漏报 ✗（§5b 第 4 条那条硬规则形同虚设 ✗）。
      证据 ✓（与 `render_bb.scale_of` **同一条规则** ✓，两边都是 1/72 ✓）：
        · 面包板 `468.238px` ⇒ **165.2mm** ✓ ≈ 孔阵 `576 单位 = 162.6mm` ✓；
        · `WS2812B_1010` 面包板 4 脚中心差 `14.401×21.600` 用户单位 → `18×27` sketch
          单位 ✓ = 它插的孔 `col31→col33` / `rowE→rowF` ✓。
      ★ 教训：**同一件事只能有一份口径** ✗ —— 这里曾和渲染器不一致（96 vs 72 ✗）。
      ★ 无单位（`width="25"`）**故意不支持** ✓ ⇒ 返回 None ⇒ 上层视为“不知道” ✓，
        而不是**算一个错的**出来 ✗（宁可少算、由调用方兜底 ✓，与 `shape_bbox` 同一个保守原则 ✓）。
    """
    UNIT = {"mm": 1.0, "cm": 10.0, "in": 25.4, "mil": 0.0254,
            "px": 25.4 / 72.0, "pt": 25.4 / 72.0}

    def one(s):
        if not s:
            return None
        m = re.match(r"\s*(-?[\d.]+)\s*([a-z%]*)\s*$", s)
        if not m:
            return None
        v, u = float(m.group(1)), m.group(2)
        return v * UNIT[u] if u in UNIT else None

    return one(attrs.get("width")), one(attrs.get("height"))


def body_box(svg_path):
    """元件**本体**在 sketch 单位下的矩形（相对画布原点 ✓）；不可信 ⇒ None ✓"""
    root = ET.parse(svg_path).getroot()
    wmm, hmm = canvas_mm(root.attrib)
    if not wmm or not hmm:
        return None
    vb = _nums(root.get("viewBox"))
    if len(vb) == 4 and vb[2] and vb[3]:
        k = wmm / vb[2]                       # mm / 用户单位 ✓
        ox, oy = vb[0], vb[1]
    else:
        k, ox, oy = wmm / (float(root.get("width").rstrip("a-z%") or 1)), 0.0, 0.0
    c = shape_bbox(root)
    if c is None:
        return None
    box = ((c[0] - ox) * k * MM, (c[1] - oy) * k * MM,
           (c[2] - ox) * k * MM, (c[3] - oy) * k * MM)
    # ★★ 2026-09-27 修 ✓：**不要因为"内容超出画布"就返回 None** ✗ ——
    #   core 的 `ceramic_capacitor_blue_leg.svg` / `resistor_220.svg` 都把**引脚腿画到画布外** ✓，
    #   那是**合理的画法** ✓（腿本来就伸出去 ✓）⇒ 旧写法让这两件**永远量不出框** ✗
    #   ⇒ 审计里一直卡在"未验证"✗（是用户报 `Wire90012903` 那一轮才暴露出来的第二个洞 ✓）。
    #   ⇒ 现在**照实返回内容包围盒** ✓（腿占的地方也算它占的 ✓），
    #     只在**离谱**溢出（> 4 倍画布 ✗ = 多半是相对 path 命令没解析对 ✗）时才 None ✓。
    lim = 4.0 * max(wmm * MM, hmm * MM, 1e-6)
    if (box[0] < -lim or box[1] < -lim
            or box[2] > wmm * MM + lim or box[3] > hmm * MM + lim):
        return None
    return box


def place(loc, m, box):
    """把（相对画布原点的）矩形按实例矩阵搬到 sketch 绝对坐标 ✓"""
    xs, ys = [], []
    for u in (box[0], box[2]):
        for v in (box[1], box[3]):
            p = apply(m, u, v)
            xs.append(loc[0] + p[0])
            ys.append(loc[1] + p[1])
    return (min(xs), min(ys), max(xs), max(ys))
