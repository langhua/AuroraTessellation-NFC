# -*- coding: utf-8 -*-
r"""把我的**原理图**渲染成 PNG ✓（"看得见" ✓ —— 本机 Fritzing 命令行导出是坏的 ✗）

══ 摆放模型（2026-09-27 **机验钉死** ✓，证据见 `--verify-export`）══

    sketch = geometry.(x,y) + M · ( k · (局部用户坐标 − viewBox原点) )

  · `M` = `<geometry>/<transform m11…m32>` ✓（**没有就是单位阵** ✓ —— 注意它是**子元素** ✗
    不是属性 ✗，我为此白查了一轮 ✓）；旋转（如 C1/C2 的 180°）就写在这里 ✓
    —— 直接调 `part_box.tf_of` ✓（**与算本体包围盒同一套数学** ✓，不另写 ✗）。
  · `k` = 声明物理尺寸 / viewBox宽 × **3.5433** ✓ —— ★★ **1mm = 3.5433 sketch 单位（1/90in）** ✓✓
    ⇒ **原理图与面包板同一套单位** ✓（`render_bb.py` 的 `SK` 一致 ✓）。

  ★ 我在这上面**错过一次** ✗，记下来别再犯 ✗：
    把我自己导出的 `pixel-schematic_图示.svg` 的 `viewBox 371.41 / 5.15847in = 72` ✗
    当成"原理图 1 单位 = 1/72in" ✗ —— 那是**导出文件自己的**单位 ✓（导出把 sketch ×0.8 出图 ✓，
    72/90 = 0.8 ✓）。**判据**（三条独立证据，逐位相符 ✓）：
      ① 导线 `Wire90012727` 起点 (0,−123.269) 就是 `J1` 的 pin0 ✓ ⇒ pin0 距原点 9.106 单位
         ÷ 局部 2.57mm = **3.5433 单位/mm** ✓（< 1/72in 的 2.83465 ✗）；
      ② 导出里零件组平移 = **0.8×sketch + 常数** ✓（9 件全对 ✓）；
      ③ 导线线宽 `mils 9.7222` ⇒ `×90/1000 = 0.875` 单位 ✓ ⇒ 导出里 `×0.8 = 0.699998` ✓✓。

  · **连接点 = `connectorNterminal`** ✓（**不是** pin 线中点 ✗ —— 对 pin 中点会差 12.8 单位 ✗）。
  · 图层名**照 fzp 的 `schematicView/layers/layer@layerId` 取** ✓（不写死 `schematic` ✗：
    `breadboard2.fzp` 的 schematicView 指向 `breadboardbreadboard` ✗）。
  · **面包板本体不画** ✓（Fritzing 自己也不画 ✓，导出可证 ✓：10 个零件组里没有它 ✓）。
  · **BOM 属性文本**：位号行 = instance `title` ✓；后续行 = fzp 里 `showInLabel="yes"` 的字段 ✓
    （导出实测：`C1`+`16V` ✓、`U3`+`BAS70BRW` ✓）。位置 = `titleGeometry` ✓、DroidSans 5 ✓ 黑 ✓。

══ 用法 ══

    py -3.13 render_sch.py <sketch.fzz> <out.png> [<px宽>]
    py -3.13 render_sch.py <sketch.fzz> <out.png> --view schematicView
    py -3.13 render_sch.py <sketch.fzz> out.png --verify-export <Fritzing导出的.svg>   # ★ 独立核对 ✓

★ **不许自证** ✓：本渲染器只是"眼睛" ✓；它的**对外结论**（"画得对"）必须由
  `--verify-export`（拿 Fritzing 自己的导出当尺子 ✓）或**用户的眼睛**给出 ✓。
"""
import collections
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import toolpaths                                                  # noqa: E402
import part_box as PB                                             # noqa: E402

SK_U_PER_MM = PB.MM                       # 3.5433 ✓（1/90 in ✓）
UMM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "px": 25.4 / 72.0, "pt": 25.4 / 72.0,
       "": 25.4 / 1000.0}                 # 无单位 = 1/1000in ✓（Fritzing 零件约定 ✓）
HDR = re.compile(r"<(?:svg:svg|svg)\b[^>]*?/?>", re.S)            # ★ 单引号/`svg:` 前缀都要认 ✓
ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def tag(e):
    return e.tag.split("}")[-1]


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def enum(el, n, d=0.0):
    """读 **XML 元素**的属性 ✓"""
    return num(el.get(n), d)


def attrs(s):
    """读 **文本**里的属性（单双引号通吃 ✓）"""
    return {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3))
            for m in ATTR_RE.finditer(s)}


def inner(svg_text):
    t = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", svg_text or "")
    t = re.sub(r"<!DOCTYPE[^>]*>", "", t, flags=re.S)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    m = HDR.search(t)
    if not m:
        return ""
    body = t[m.end():]
    return body[:body.rfind("</svg>")] if "</svg>" in body else body


def head_of(t):
    m = HDR.search(t or "")
    return attrs(m.group(0)) if m else {}


def viewbox_of(t):
    h = head_of(t)
    vb = h.get("viewbox")
    if not vb:
        return None
    p = [float(x) for x in re.split(r"[ ,]+", vb.strip()) if x]
    return tuple(p) if len(p) == 4 else None


def scale_of(t):
    """零件/板子 svg 的 **k**（用户单位 → sketch 单位 ✓）与 `viewBox` 原点 ✓

    ★ 只有**一条**规则 ✓：k = 声明物理尺寸（mm）/ viewBox宽 × 3.5433 ✓
      （没有 viewBox ⇒ 用户单位本身就是长度 ✓；没有 width ⇒ 报错**不静默** ✓）
    """
    h = head_of(t)
    wv = h.get("width")
    vb = viewbox_of(t)
    org = (vb[0], vb[1]) if vb else (0.0, 0.0)
    if wv is None:
        return None, org, "**没有 width** ✗"
    m = re.match(r"\s*([\d.]+)\s*([a-z%]*)", wv)
    if not m:
        return None, org, "width=%r 认不出 ✗" % wv
    w, unit = float(m.group(1)), (m.group(2) or "").lower()
    if unit not in UMM:
        return None, org, "没见过的单位 %r ✗" % unit
    mm = w * UMM[unit]
    if not vb or not vb[2]:
        return mm * SK_U_PER_MM, org, "width=%s（无 viewBox ⇒ 单位即长度 ✓）" % wv
    return mm / vb[2] * SK_U_PER_MM, org, "width=%s ÷ viewBox宽%s × 3.5433 ✓" % (wv, vb[2])


def layer_of(txt, layer):
    """取 `<g id="层名">` 的**内容** ✓（★ **按标签配平扫描** ✓ —— 非贪婪正则只截到第一个
    `</g>` ✗；并且**必须认自闭合 `<g/>`** ✗，否则配平会跑飞 ✗）"""
    body = inner(txt)
    if not body:
        return None, "**没有 <svg> 头** ✗"
    toks = [(m.start(), m.end(), m.group(0))
            for m in re.finditer(r"<g\b[^>]*>|</g>", body)]
    depth, start, sdepth = 0, None, None
    for s, e, tok in toks:
        if tok == "</g>":
            if start is not None and depth == sdepth:
                return body[start:s], "层 `%s` ✓" % layer
            depth -= 1
        else:
            selfc = tok.rstrip().endswith("/>")
            if start is None and not selfc and (attrs(tok).get("id") or "") == layer:
                start, sdepth = e, depth + 1
            if not selfc:
                depth += 1
    return None, "层 `%s` **找不到** ✗" % layer


def anchors(txt_root):
    """零件 svg 里每个脚的**连接点**（根用户单位 ✓，走完祖先 transform ✓）

    ★ 优先 `connectorNterminal` ✓（原理图的连接点在这儿 ✓）；
      退回 `connectorNpin` 线的**中点** ✓（并标明用的是哪种 ✓，不静默 ✓）。
    """
    term, pin, bad = {}, {}, []

    def walk(el, m):
        if tag(el) == "defs":
            return
        for c in el:
            t = c.get("transform")
            mc = PB.mul(m, PB.parse_tf(t)) if t else m
            eid = c.get("id") or ""
            mt, mp = re.match(r"^(connector\d+)terminal$", eid), re.match(r"^(connector\d+)pin$", eid)
            if mt or mp:
                if tag(c) == "rect":
                    p = (enum(c, "x") + enum(c, "width") / 2.0,
                         enum(c, "y") + enum(c, "height") / 2.0)
                elif tag(c) in ("line", "polyline"):
                    p = ((enum(c, "x1") + enum(c, "x2")) / 2.0,
                         (enum(c, "y1") + enum(c, "y2")) / 2.0)
                elif tag(c) == "circle":
                    p = (enum(c, "cx"), enum(c, "cy"))
                else:
                    p = None
                if p is None:
                    bad.append("%s=<%s>（认不出参考点 ✗）" % (eid, tag(c)))
                else:
                    (term if mt else pin)[(mt or mp).group(1)] = PB.apply(mc, p[0], p[1])
            walk(c, mc)

    walk(txt_root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return term, pin, bad


def resolve(fzp_path, image):
    """按 fzp 的 `image=` 找真 svg ✓；顺带报出**试过哪些地方** ✓（不静默 ✗）"""
    base = os.path.dirname(os.path.dirname(fzp_path))
    tried = []
    for sub in ("user", "core", "contrib", ""):
        cand = os.path.normpath(os.path.join(base, "svg", sub, (image or "").replace("/", os.sep)))
        tried.append(cand)
        if os.path.isfile(cand):
            return cand, tried
    return None, tried


def to_sketch(g, A, p):
    """零件 svg 的**用户坐标** `p` → sketch 绝对坐标 ✓

    ★ 仿射是**完整**的 2×3：`x' = A0·x + A2·y + A4` ✓ —— **`A4/A5` 不能漏** ✗✗
      （它们就是 `−k×viewBox原点` ✓）。我在第一版漏过 ✗，症状**很隐蔽**：
      原点为 (0,0) 的件**看不出来** ✓，只有 `U1`（`viewBox="-190 -190 …"` ✓）的脚
      **一律偏 17.124 单位** ✗（= 0.09×190 ✓ ⇒ 恰好被自检的"离最近脚还差 17.124"抓出来 ✓）。
      ⇒ 教训：**自检要能报出"差多少"** ✓ —— 17.124 这个数直接把算式指出来了 ✓。
    """
    return (enum(g, "x") + A[0] * p[0] + A[2] * p[1] + A[4],
            enum(g, "y") + A[1] * p[0] + A[3] * p[1] + A[5])


# ═══════════════ 主流程 ═══════════════
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {}
for i, a in enumerate(sys.argv[1:]):
    if a.startswith("--") and "=" in a:
        k_, v_ = a[2:].split("=", 1)
        opts[k_] = v_
    elif a.startswith("--") and i + 1 < len(sys.argv[1:]):
        opts[a[2:]] = sys.argv[i + 2]
VIEW = opts.get("view", "schematicView")
path, out = args[0], args[1]
PXW = float(args[2]) if len(args) > 2 else 1800.0
MMU = 25.4 / 90.0                                   # 1 sketch 单位 = 1/90 in ✓

z = zipfile.ZipFile(path)
fzname = [n for n in z.namelist() if n.endswith(".fz")][0]
root = ET.fromstring(z.read(fzname))
packed = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".svg")}
print("== %s ▶ %s（%d 字节）" % (path, fzname, os.path.getsize(path)))

# ── ① 零件 ──
body_parts, PIN_SK, ALL_PTS = [], [], []
skipped = []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if mid.startswith("Wire"):
        continue
    ttl = (el.findtext("title") or "").strip()
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    g = next((c for c in sv if tag(c) == "geometry"), None)
    if g is None:
        continue                                    # 这一视图里没摆位的（如 PCB1 ✓）
    fzp = (el.get("path") or "").replace("/", os.sep)
    if not os.path.isfile(fzp):
        skipped.append((ttl, "fzp 不存在 ⇒ %s" % fzp))
        continue
    fr = ET.parse(fzp).getroot()
    fam = next((p.get("value") for p in fr.iter("property") if p.get("name") == "family"), None)
    tax = (fr.findtext("taxonomy") or "")
    lay = fr.find(".//%s/layers" % VIEW)
    layerid = None
    if lay is not None:
        l0 = next((c for c in lay if tag(c) == "layer"), None)
        layerid = l0.get("layerId") if l0 is not None else None
    image = lay.get("image") if lay is not None else None
    if "breadboard" in tax.lower() or (fam or "").lower() == "breadboard":
        skipped.append((ttl, "**面包板本体：Fritzing 的原理图不画它** ✓（导出可证 ✓）"))
        continue
    txt, src = None, None
    if image:
        # ★ **磁盘上零件本体优先** ✓（Fritzing 就是从 fzp 旁边加载 ✓）；包内副本只是备份 ✓（会注明 ✓）
        cand, tried = resolve(fzp, image)
        if cand:
            txt, src = open(cand, encoding="utf-8", errors="replace").read(), cand
        else:
            want = os.path.basename(image)
            for n, t in packed.items():
                if n.endswith(want):
                    txt, src = t, n + "（**包内副本** ✓）"
                    break
        if txt is None:
            skipped.append((ttl, "svg 取不到（image=%s；找过 %s）" % (image, " ; ".join(tried))))
            continue
    if txt is None:
        skipped.append((ttl, "fzp 里 `%s/layers@image` 为空 ✗" % VIEW))
        continue
    k, org, khow = scale_of(txt)
    if k is None:
        skipped.append((ttl, "k 算不出：%s" % khow))
        continue
    want_layer = layerid or "schematic"
    laytxt, lnote = layer_of(txt, want_layer)
    if laytxt is None:
        laytxt, lnote = inner(txt), lnote + " ⇒ 退回整张 svg 的 body ⚠"
    m = PB.tf_of(g)
    A = PB.mul(m, (k, 0.0, 0.0, k, -k * org[0], -k * org[1]))
    e, f = enum(g, "x") + A[4], enum(g, "y") + A[5]
    body_parts.append((ttl, "%s" % lnote,
                       '<g transform="matrix(%.6f %.6f %.6f %.6f %.6f %.6f)">%s</g>'
                       % (A[0], A[1], A[2], A[3], e, f, laytxt)))
    # 脚的 sketch 坐标 ✓（自检/核对用 ✓）：**一处算清** ✓
    #   ★ `A` 里已经含了「减 viewBox 原点」✓（A = M·(k,0,0,k,−k·原点) ✓）
    #     ⇒ 映射就是 `geom + A·p` ✓ —— **不要再减一次原点** ✗（我在草稿里就重复扣减过 ✗）。
    try:
        term, pin, bad = anchors(ET.fromstring(txt))
    except Exception as ex:
        term, pin, bad = {}, {}, ["<svg 解析不了：%s>" % ex]
    pins, kind = (term, "terminal") if term else (pin, "pin")
    for cid, p in pins.items():
        PIN_SK.append((ttl, cid, to_sketch(g, A, p)))
    # 本体包围盒（sketch ✓）—— 同样走 `A` ✓
    bb = PB.shape_bbox(ET.fromstring(txt))
    if bb:
        for cx, cy in ((bb[0], bb[1]), (bb[2], bb[1]), (bb[0], bb[3]), (bb[2], bb[3])):
            ALL_PTS.append(to_sketch(g, A, (cx, cy)))
    print("   %-12s img=%-42s 用了 %s" % (ttl, image or "（无）", os.path.basename(src)))
    print("        k=%.5f｜原点=(%g,%g)｜%s｜脚 %d 个（%s ✓）｜%s"
          % (k, org[0], org[1], khow, len(pins), kind, lnote))
    for b in bad:
        print("        ⚠ %s" % b)

# ── ② 导线 ──
wires, widx = [], []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if not mid.startswith("Wire"):
        continue
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    g = next((c for c in sv if tag(c) == "geometry"), None)
    if g is None:
        continue
    ttl = (el.findtext("title") or "").strip()
    col, mils = "#404040", None
    for c in sv.iter():
        if tag(c) == "wireExtras":
            col, mils = c.get("color") or col, c.get("mils")
    x, y = enum(g, "x"), enum(g, "y")
    a = (x + enum(g, "x1"), y + enum(g, "y1"))
    b = (x + enum(g, "x2"), y + enum(g, "y2"))
    w = (float(mils) * 90.0 / 1000.0) if mils else 0.875          # mils → 1/90in 单位 ✓；默认 9.7222mil ✓
    wires.append((ttl, a, b, col, w))
    widx.append((ttl, a, b))
    ALL_PTS += [a, b]
print("── 导线 %d 根 ｜ 颜色 %s ｜ 线宽 %s ──"
      % (len(wires), dict(collections.Counter(w[3] for w in wires)),
         sorted({round(w[4], 6) for w in wires})))
tot = sum(math.dist(w[1], w[2]) for w in wires)
print("   总长 %.1f 单位 = %.1f mm" % (tot, tot * MMU))

# ★ 接点圆点 ✓（Fritzing 在导线**接头**上画实心小圆 ✓）
#   半径由导出**实测** ✓：导出里 `r=0.72` ✓ 而导出 = sketch×0.8 ✓ ⇒ sketch 里 **0.9 单位** ✓。
#   判据**由导出反推** ✓（`_scratch/dot_diff.py` ✓）：**≥2 个导线端点重合** ⇒ 画点 ✓
#   （实测：导出 40 个 ↔ 判据给出 35 个 ✓ —— 差 5 个是 Fritzing 在**导线与引脚相接处**也点了 ✓，
#     我暂时只在**线↔线**接头画 ✓；差异已量化 ✓ 不影响读数 ✓）。
#   ★ 聚容差 0.01 单位**必须有** ✗：Fritzing 自己存的同一接头会差 0.001 ✓
#     （实测 `186.513` vs `186.512` ✓）⇒ 按小数位分组会把接头拆成两个 ✗ ⇒ 圆点一个都不出来 ✗。
DOT_R = 0.9
JTOL = 0.01
ends = [p for _t, a, b, _c, _w in wires for p in (a, b)]
clusters = []
for p in ends:
    hit = next((c for c in clusters if math.dist(p, c[0]) < JTOL), None)
    if hit:
        hit[1] += 1
    else:
        clusters.append([p, 1])
dots = [c[0] for c in clusters if c[1] >= 2]      # ★ 试一下 ≥2（Fritzing 似乎连**拐点**也画点 ✓）


def on_seg(p, a, b, tol=0.05):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return False
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2
    if not (0.02 < t < 0.98):
        return False
    return math.dist(p, (ax + t * dx, ay + t * dy)) < tol


for _t, a, b, _c, _w in wires:
    for p in (a, b):
        if any(on_seg(p, w1, w2) for _t2, w1, w2, _c2, _w2 in wires if (w1, w2) != (a, b)):
            dots.append(p)
dots = sorted(set((round(x, 3), round(y, 3)) for x, y in dots))
print("   接点圆点 %d 个 ✓（半径 %.2f 单位 = 导出 0.72 ÷ 0.8 ✓）" % (len(dots), DOT_R))

# ── ③ 位号文本 ──
labels = []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if mid.startswith("Wire"):
        continue
    ttl = (el.findtext("title") or "").strip()
    if not ttl:
        continue
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    tg = next((c for c in sv if tag(c) == "titleGeometry"), None)
    if tg is None or (tg.get("visible") or "true") == "false":
        continue
    lines = [ttl]
    fzp = (el.get("path") or "").replace("/", os.sep)
    vals = {c.get("name"): c.get("value") for c in el if tag(c) == "property"}
    if os.path.isfile(fzp):
        props = [p.get("name") for p in ET.parse(fzp).getroot().iter("property")]
        # ★ 规则**由 Fritzing 导出的实测数据定** ✓（9 件逐件对过 ✓，见 `--verify-export` 一节）：
        #   · `showInLabel="yes"` 的属性 ⇒ 值；**按 fzp 属性顺序的逆序** ✓
        #     （实测：`R1` = `±5%`,`220Ω` ✓；`C1` = `16V`,`100 nF` ✓ 均是逆序 ✓）
        #   · 空值**不出行** ✓（`R1` 的 `power` 标了 yes 但值空 ⇒ 未出 ✓）
        #   · 没一个标 yes 的件 ⇒ 出实例的 `part number` ✓
        #     （实测：`LED2`→`WS2812B-1010` ✓、`J1/J2`→`SH1.0-3P-LT` ✓、`U1`/`D3` 同 ✓）
        #   ⚠ 这条是**近似** ✓：Fritzing 的内部顺序没有官方文档，我是拿导出反推的 ✓，
        #     不保证所有零件都对 ✓ —— 但**位置**（titleGeometry）与**行距**（字号 5 ✓）是机验过的 ✓。
        yes = [(p.get("name"), (p.text or "").strip())
               for p in ET.parse(fzp).getroot().iter("property")
               if (p.get("showInLabel") or "").lower() in ("yes", "true")]
        for nm, dflt in reversed(yes):
            # ★ 实例的值优先 ✓；fzp 的**默认值在元素文本里** ✓（不是 `value=` 属性 ✗）
            v = vals.get(nm) or dflt
            if v and v not in lines:
                lines.append(v)
        if len(lines) == 1:
            v = vals.get("part number")
            if v:
                lines.append(v)
        _ = props
    labels.append((ttl, (enum(tg, "x"), enum(tg, "y")), float(enum(tg, "fontSize", 5.0)),
                   tg.get("textColor") or "#000000", lines))
print("── 位号 %d 个：%s" % (len(labels), ", ".join("%s(%s)" % (l[0], "+".join(l[4][1:]) or "—") for l in labels)))

# ── ④ 自检：悬空端点 / 没接线的脚 ✓（**如实报** ✓ 不偷偷吸附 ✗）──
dang = []
for ttl, a, b in widx:
    for which, pt in (("起", a), ("止", b)):
        best = min(((math.dist(pt, p[2]), p) for p in PIN_SK), default=(1e18, None))
        joint = any(math.dist(pt, q[1]) < 0.01 or math.dist(pt, q[2]) < 0.01
                    for q in widx if q[0] != ttl)
        if best[0] > 0.5 and not joint:
            dang.append((best[0], ttl, which, pt, best[1]))
if PIN_SK and widx:
    hung = 0
    for p in PIN_SK:
        near = min(math.dist(p[2], a) for _t, a, _b in widx)
        near = min(near, min(math.dist(p[2], b) for _t, _a, b in widx))
        if near > 0.5:
            hung += 1
    print("── 脚位自检：脚 %d 个 ⇒ 接上导线 %d 个 ✓ ｜ **悬空 %d 个** ✓（原理图本来就允许悬空 ✓）"
          % (len(PIN_SK), len(PIN_SK) - hung, hung))
print("── 悬空导线端 %d 个 %s" % (len(dang), "✓" if not dang else "（**如实报出** ✓，不吸附 ✗）"))
for d, ttl, which, pt, hit in sorted(dang, reverse=True)[:10]:
    print("     ⚠ %-14s %s端 (%.3f,%.3f) 离最近脚 %s.%s 还差 **%.3f 单位（%.3f mm）**"
          % (ttl, which, pt[0], pt[1], hit[0], hit[1], d, d * MMU))
for t, why in skipped:
    print("   ⊘ 跳过 %-12s %s" % (t, why))

# ── ⑤ 出图 ──
xs = [p[0] for p in ALL_PTS] or [0.0, 100.0]
ys = [p[1] for p in ALL_PTS] or [0.0, 100.0]
PAD = 40.0
x0, x1 = min(xs) - PAD, max(xs) + PAD
y0, y1 = min(ys) - PAD, max(ys) + PAD
w, h = x1 - x0, y1 - y0
body = ['<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff"/>' % (x0, y0, w, h)]
body += [b[2] for b in body_parts]
for ttl, a, b, col, wd in wires:
    body.append('<line x1="%.4f" y1="%.4f" x2="%.4f" y2="%.4f" stroke="%s" '
                'stroke-width="%.4f" stroke-linecap="round"/>' % (a[0], a[1], b[0], b[1], col, wd))
for cx, cy in dots:                                   # ★ 接点圆点画在导线**之上** ✓
    body.append('<circle cx="%.4f" cy="%.4f" r="%.4f" fill="#000000" stroke="none"/>'
                % (cx, cy, DOT_R))
for ttl, (lx, ly), fs, col, lines in labels:
    body.append('<g font-family="DroidSans" font-size="%.3f" fill="%s">' % (fs, col))
    for i, s in enumerate(lines):
        body.append('<text x="%.4f" y="%.4f">%s</text>'
                    % (lx, ly + fs * i, s.replace("&", "&amp;").replace("<", "&lt;")))
    body.append("</g>")
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%.3fmm" height="%.3fmm" '
       'viewBox="%.3f %.3f %.3f %.3f">%s</svg>' % (w * MMU, h * MMU, x0, y0, w, h, "".join(body)))
svgtmp = os.path.splitext(out)[0] + ".svg"
open(svgtmp, "w", encoding="utf-8").write(svg)
print("── 画布 %.1f × %.1f mm（%.0f × %.0f 单位 ✓）零件 %d ✓ 导线 %d ✓ 位号 %d ✓"
      % (w * MMU, h * MMU, w, h, len(body_parts), len(wires), len(labels)))
import cairosvg                                                   # noqa: E402
cairosvg.svg2png(url=svgtmp, write_to=out, output_width=round(PXW),
                 output_height=round(PXW * h / w), background_color="white")
print("写入 %s（同时留了 %s ✓）" % (out, svgtmp))

# ── ⑥ ★ 独立核对：拿 Fritzing 自己导出的 svg 当尺子 ✓ ──
if "verify-export" in opts:
    exp = opts["verify-export"]
    raw = open(exp, encoding="utf-8", errors="replace").read()
    grp = {}
    for m in re.finditer(r'<g partID="(\d+)"\s*>', raw):
        pid, depth, i = m.group(1), 1, m.end()
        while depth and i < len(raw):
            n1, n2 = raw.find("<g", i), raw.find("</g>", i)
            if n2 < 0:
                break
            if n1 >= 0 and n1 < n2:
                # ★ 自闭合 `<g/>` **不加深** ✓（我为此错过一次 ✗）
                if raw[n1:n1 + 60].split(">")[0].rstrip().endswith("/"):
                    i = raw.find(">", n1) + 1
                    continue
                depth += 1
                i = n1 + 2
            else:
                depth -= 1
                i = n2 + 4
        grp[pid] = raw[m.end():i]
    # 我的模型预测的"内容原点"位置 ✓（sketch 单位）
    mine = {}
    for el in root.iter("instance"):
        mid = el.get("moduleIdRef") or ""
        if mid.startswith("Wire") or not el.get("modelIndex"):
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
        g = next((c for c in sv if tag(c) == "geometry"), None) if sv is not None else None
        if g is None:
            continue
        ttl = (el.findtext("title") or "").strip()
        one = next((b for b in body_parts if b[0] == ttl), None)
        fzp = (el.get("path") or "").replace("/", os.sep)
        img = None
        if one is not None and os.path.isfile(fzp):
            lay = ET.parse(fzp).getroot().find(".//%s/layers" % VIEW)
            img = lay.get("image") if lay is not None else None
        if img is None:
            continue
        txt = None
        want = os.path.basename(img)
        for n, t in packed.items():
            if n.endswith(want):
                txt = t
                break
        if txt is None:
            cand, _ = resolve(fzp, img)
            txt = open(cand, encoding="utf-8", errors="replace").read() if cand else None
        if txt is None:
            continue
        k, org, _ = scale_of(txt)
        m = PB.tf_of(g)
        A = PB.mul(m, (k, 0.0, 0.0, k, -k * org[0], -k * org[1]))
        mine[str(el.get("modelIndex")) + "0"] = (ttl, enum(g, "x") + A[4], enum(g, "y") + A[5])
    print("── ★ 独立核对（对着 Fritzing 导出的 %s）──" % os.path.basename(exp))
    pairs = []
    for pid, (ttl, mx, my) in mine.items():
        blk = grp.get(pid)
        if blk is None:
            print("   ⊘ %-12s 导出里没有它的组（Fritzing 没画它 ✓ 例如面包板 ✓）" % ttl)
            continue
        cut = re.split(r"<g\b[^>]*\bid\s*=\s*[\"'](?:schematic|schematicLabel)[\"']", blk)[0]
        tx = ty = 0.0
        for o in re.finditer(r"(translate|matrix)\s*\(([^)]*)\)", cut):
            a = [float(x) for x in re.split(r"[ ,]+", o.group(2).strip()) if x]
            if o.group(1) == "translate":
                tx += a[0]
                ty += a[1] if len(a) > 1 else 0.0
            elif len(a) == 6:
                tx, ty = tx + a[4], ty + a[5]
        pairs.append((ttl, mx, my, tx, ty))
    if pairs:
        # 用**第一件**标定导出与 sketch 的常数平移 ✓（导出 = 0.8×sketch + c ✓），其余件**逐件验证** ✓
        s = 0.8
        c = (pairs[0][3] - s * pairs[0][1], pairs[0][4] - s * pairs[0][2])
        worst = 0.0
        for ttl, mx, my, tx, ty in pairs:
            d = max(abs(tx - (s * mx + c[0])), abs(ty - (s * my + c[1])))
            worst = max(worst, d)
            print("   %-12s 导出(%9.4f,%9.4f) ← 0.8×我的(%9.4f,%9.4f)+(%7.4f,%7.4f) ⇒ Δ=%.5f"
                  % (ttl, tx, ty, mx, my, c[0], c[1], d))
        print("   ⇒ 标定常数 (%.4f, %.4f) ✓；逐件最大 Δ = **%.5f 单位**（%.5f mm）⇒ %s"
              % (c[0], c[1], worst, worst * MMU,
                 "✓✓ **与 Fritzing 完全一致** ✓✓" if worst < 0.01
                 else "✗ 不一致 ✗（别急着下结论 ✓ 先查哪一件 ✗）"))
        # ★ 接点数对账 ✓（导出：`fill="black"` + `r="0.72"` 才是接点 ✓
        #   —— `r=0.56 / fill="#000000"` 是**零件符号自己的图元** ✗，别混 ✓）
        dots_exp = len(re.findall(r'<circle\b[^>]*fill="black"[^>]*r="0\.72"', raw)) + \
            len(re.findall(r'<circle\b[^>]*r="0\.72"[^>]*fill="black"', raw))
        print("   ★ 接点对账：导出的接点圆点 %d 个 ↔ 我画的 %d 个 ⇒ %s"
              % (dots_exp, len(dots),
                 "✓ 一致 ✓" if dots_exp == len(dots) else "⚠ 不一致 ⚠（我 %s ✓）"
                 % ("多了" if len(dots) > dots_exp else "少了")))
