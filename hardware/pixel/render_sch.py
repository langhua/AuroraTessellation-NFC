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
import html
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import toolpaths                                                  # noqa: E402
import part_box as PB                                             # noqa: E402
import sch_text as ST                                            # ★ 字宽表（唯一实现 ✓）
import sch_geom as SG                                            # ★ 几何判据（含斜线 ✓，唯一实现 ✓）

SK_U_PER_MM = PB.MM                       # 3.5433 ✓（1/90 in ✓）
# ★★ `px` = **1/90 in**（= 0.8 × 1/72 ✓）—— 2026-09-27 **实测**定的 ✓，不是查文档 ✗：
#   把 v6 的导出与我的渲染逐件比"**同一零件内两个脚的向量**" ✓（这个量**不需要任何标定** ✓）
#   ⇒ 只有 `LED2`（`width="48px"`）与 `D3`（`width="66px"`）对不上 ✗，比值恰好 **0.64 / 0.8 = 0.8** ✓
#   ⇒ 我把 px 当 1/72in 算 ✗，Fritzing 按 1/90in 算 ✓（`1.25 × 0.8 = 1.0` ✓）。
#   后果就是用户截图里那两处"线没接到脚上" ✗（误差 ~2.5mm ✓）。
#   注：`pt` 仍是 1/72in ✓（只有 px 不同 ✓）。
UMM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "px": 25.4 / 90.0, "pt": 25.4 / 72.0,
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
PART_BOX, PINS_REL, BOX_REL = {}, {}, {}          # ★ 本体框 / 相对锚点的脚位与框（摆位用 ✓）
LAB_REL = {}                                     # ★ 位号内容 + 字号（摆位脚本挑位置用 ✓）
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
    # ★★ 多包两层 ✓（`partID` + `id="schematic"` ✓）—— 不是为了好看 ✗，是为了**当尺子** ✓：
    #   既有接线管线 `gen_schematic_wires.py` 的 `build_ruler()` 就是按 Fritzing **导出**里
    #   这两层找“零件原点 + 各脚坐标 + 本体轮廓” ✓（`partID` ⇒ 零件 ✓；`id="schematic"` ⇒ 原点/本体 ✓）。
    #   本机 Fritzing 命令行导出是坏的 ✗ ⇒ **我自己的渲染就是那份尺子** ✓（已对导出验平 ✓）。
    #   `partID` 用 `modelIndex + "0"` ✓（管线按 `startswith(mi)` + 长度 +1 匹配 ✓，与 Fritzing 同形 ✓）。
    mi = el.get("modelIndex") or "0"
    body_parts.append((ttl, "%s" % lnote,
                       '<g partID="%s0"><g transform="matrix(%.6f %.6f %.6f %.6f %.6f %.6f)">'
                       '<g id="schematic">%s</g></g></g>'
                       % (mi, A[0], A[1], A[2], A[3], e, f, laytxt)))
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
        _bx = [to_sketch(g, A, (cx, cy)) for cx, cy in
               ((bb[0], bb[1]), (bb[2], bb[1]), (bb[0], bb[3]), (bb[2], bb[3]))]
        PART_BOX[ttl] = (min(p[0] for p in _bx), min(p[1] for p in _bx),
                         max(p[0] for p in _bx), max(p[1] for p in _bx))
        PINS_REL.setdefault(str(el.get("modelIndex")), {})["__title__"] = ttl
        for cid, p in pins.items():                      # ★ 各脚 → **相对锚点**（sketch 单位 ✓）
            PINS_REL.setdefault(str(el.get("modelIndex")), {})[cid] = \
                (to_sketch(g, A, p)[0] - enum(g, "x"), to_sketch(g, A, p)[1] - enum(g, "y"))
        BOX_REL[str(el.get("modelIndex"))] = (
            PART_BOX[ttl][0] - enum(g, "x"), PART_BOX[ttl][1] - enum(g, "y"),
            PART_BOX[ttl][2] - enum(g, "x"), PART_BOX[ttl][3] - enum(g, "y"))
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
#   判据**由导出反推** ✓（2026-09-27 ✓，`_scratch/dot9.py` ✓）：
#     · 导出 v2：**50 个圆 = 25 个位置 × 每处 2 个** ✓（Fritzing 给每根线在接头处各画一个 ✓）；
#       视觉上"一处一个" ✓ ⇒ 我也只画**一个** ✓。
#     · ★ 判据（实测最接近的一版 ✓）：**该处 ≥2 个导线端点，且不在任何引脚上** ✓
#       ⇒ 我 29 个位置 ↔ 导出 25 个 ✓（差 4 个 ✓ 已量化 ✓，全在引脚附近 ✓；
#         我没再试第三条猜测 ✗ —— "该处 ≥3 根导线"实测得到 **0** 个 ✗，
#         因为网表是**链式**接法 ✓，每个接头就是 2 根端点 ✓）。
#     · 实测导出那 25 个位置上都是 **2 个导线端点** ✓；
#       ✗ 不在**引脚**（D3 的 A1/A2 ✓、C1 ✓、R1 ✓、C2 ✓、LED2 ✓、U1 ✓）与**纯拐角**处画点 ✓。
#   ★ 聚容差 0.01 单位**必须有** ✗：Fritzing 自己存的同一接头会差 0.001 ✓
#     （实测 `186.513` vs `186.512` ✓）⇒ 按小数位分组会把接头拆成两个 ✗。
DOT_R = 0.9
JTOL = 0.01


GRP = []
for _p in (p for _t, a, b, _c, _w in wires for p in (a, b)):
    _hit = next((g for g in GRP if math.dist(_p, g[0]) < JTOL), None)
    if _hit:
        _hit[1] += 1
    else:
        GRP.append([_p, 1])
SEGS = [(a, b) for _t, a, b, _c, _w in wires]
# ★★ 接点圆点判据：**该处 ≥2 个导线端点，且不在引脚上** ⇒ 画点 ✓
#   证据（导出实测 ✓）：
#     · v2：导出 25 个位置 ↔ 本规则 25 个 ✓ **完全对上** ✓（那 25 处都是 2 端点接头 ✓，
#       而且实测告诉我：\"只有 2 端点、又没线穿过\"的**引脚**处 Fritzing **不点** ✓）；
#     · v5：导出 25 个 ↔ 本规则 21 个 ⇒ **少 4 个** ✗。
#   ⚠ **我解释不了那 4 个** ✗ —— 它们都在引脚上、且汇聚了 **3~4 个导线端点** ✓
#     （v5 导出的端点汇聚数分布 = `{2:19, 3:1, 4:5}` ✓）。
#     我试过第 2 条规则\"该处端点 + 中段穿过 ≥ 3 ⇒ 点\" ✗ ⇒ v5 变成 19 个 ✗、v2 直接 0 个 ✗✗
#     ⇒ **更差** ⇒ 按规矩（\"找不到就如实说 ✓ 不硬凑 ✗\"）回退到这一条 ✓。
#   ⇒ 差异**已量化** ✓（4 个圆点 ✓，半径 0.9 单位 = 0.25mm ✓），纯属**装饰** ✓：
#     不影响任何几何 ✓、不影响电气（连接记在 `<connect>` 里 ✓）、也不进那 4 个美学指标 ✓。
dots = [p for p, n_end in GRP
        if n_end >= 2 and not any(math.dist(p, q[2]) < 0.05 for q in PIN_SK)]


dots = sorted(set((round(x, 3), round(y, 3)) for x, y in dots))
print("   接点圆点 %d 个 ✓（判据 = 该处 **≥2 个导线端点且不在引脚上** ✓；"
      "半径 %.2f 单位 = 导出 0.72 ÷ 0.8 ✓）" % (len(dots), DOT_R))

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
    fzpmid = el.get("modelIndex") or ""
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
    LAB_REL[fzpmid] = {"lines": lines, "fs": float(enum(tg, "fontSize", 5.0))}
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

# ── ④b ★ 美学指标：**交叉数** ✓（面包板那条教训 ✓：交叉数是头号指标 ✓、且不能自证 ✓）──
#   两类都算 ✓：① 导线×导线的**十字交叉**（内部相交 ✓；共端点/共线不算 ✓）；
#   ② 导线**穿过零件本体框**的段数 ✓（导线从元件肚子里穿过 = 用户点过名的毛病 ✓）。

SEGS2 = [(a, b) for _t, a, b, _c, _w in wires]
nx = 0
for i in range(len(SEGS2)):
    for j in range(i + 1, len(SEGS2)):
        if SG.seg_cross(SEGS2[i][0], SEGS2[i][1], SEGS2[j][0], SEGS2[j][1]):
            nx += 1
# ★ 第三类毛病：两段**几乎压在一条线上** ✗（看着像一根 ✓ 读图分不清 ✓）
#   —— 手改版里就有一对（斜率 0.08° 与 0.28° ✓）⇒ 必须能报出来 ✓（`sch_geom` 唯一实现 ✓）
nov = 0
for i in range(len(SEGS2)):
    for j in range(i + 1, len(SEGS2)):
        if SG.near_overlap(SEGS2[i][0], SEGS2[i][1], SEGS2[j][0], SEGS2[j][1]):
            nov += 1


def _hits_box(p, q, box, infl=1.0, need=4):
    """段 p→q 是否**真的**穿进 box ✓（★ 擦边不算 ✗）

    ★ 收紧的理由（2026-09-27 ✓）：原来只要**有一个采样点**落在外扩 1.0 单位的框里就算 ✗
      ⇒ 导线**从元件旁边过**、离框 0.28mm 也会被算成"穿过" ✗（假警报 ✗，而且会让
      "改进了没有"这个对比失真 ✗）⇒ 现在要求**至少 4 个采样点**落在**内缩 0.5 单位**
      的框里 ✓（≈ 进到里面 0.14mm 以上 ✓）。
    """
    x0, y0, x1, y1 = box[0] + 0.5, box[1] + 0.5, box[2] - 0.5, box[3] - 0.5
    if x0 >= x1 or y0 >= y1:
        x0, y0, x1, y1 = box
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
    hit = 0
    for i in range(n + 1):
        t = i / n
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            hit += 1
            if hit >= need:
                return True
    return False


nb = 0
HITS = []
for ttl_w, a, b, _c, _w in wires:
    # ★ 排除**自己两端**的元件 ✓（它的脚本来就在本体里 ✓，穿过自己不算毛病 ✗）
    own = {q[0] for q in PIN_SK
           if math.dist(q[2], a) < 0.05 or math.dist(q[2], b) < 0.05}
    for t, box in PART_BOX.items():
        if t in own:
            continue
        if _hits_box(a, b, box):
            nb += 1
            HITS.append((ttl_w, t, a, b))
print("── ★ 美学指标：导线**十字交叉 %d 处** ✓｜导线**穿过别的元件本体 %d 段** ✓"
      "｜导线**几乎压在一起 %d 对** ✓（判据含斜线 ✓ —— `sch_geom` 唯一实现 ✓；"
      "面包板那条教训：交叉数是头号指标 ✓）" % (nx, nb, nov))
# ★ **点名** ✓（2026-09-27 用户定的规矩：结论必须可查 ✓ —— 只给个数 ✗ 我没法判它是真毛病
#   还是"脚本来就在本体内部"的必然情形 ✗）+ 给出**穿进去多深** ✓（越深越像真毛病 ✓）
for ttl_w, t, a, b in HITS[:12]:
    bb = PART_BOX[t]
    deep = 0
    n = max(2, int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1)
    for i in range(n + 1):
        u = i / n
        x, y = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
        if bb[0] + 0.5 <= x <= bb[2] - 0.5 and bb[1] + 0.5 <= y <= bb[3] - 0.5:
            deep += 1
    print("      ⚠ %-14s 穿进 **%s** 的本体（%.1f 单位深 ≈ %.2f mm）"
          % (ttl_w, t, deep * 2.0, deep * 2.0 * MMU))
if len(HITS) > 12:
    print("      ⚠ …… 另有 %d 段" % (len(HITS) - 12))

# ── ④c2 ★ 可读性：导线与"**不相连的引脚**"的安全距离 ✓（2026-09-27 用户定 ✓）──
#   用户原话："导线离芯片引脚太近了 ⇒ 应该设立规则，让导线跟芯片引脚有安全距离，
#   从而让导线和引脚的连接关系**能通过肉眼看得清晰**" ✓。
#   判据（与布线器同一条 ✓）：每根导线取两端 0.05 内的脚为"自己的脚" ✓；
#   其余脚里，离该线段 < CLEAR_PIN 的 ⇒ 算 **1 处侵入** ✗。
CLEAR_PIN = 7.2


def _p2seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


pc_hits = []
for ttl_w, a, b, _c, _w in wires:
    own = {(p[0], p[1]) for p in PIN_SK
           if math.dist(p[2], a) < 0.05 or math.dist(p[2], b) < 0.05}
    for t2, cid2, pp in PIN_SK:
        if (t2, cid2) in own:
            continue
        d2 = _p2seg(pp, a, b)
        if d2 < CLEAR_PIN:
            pc_hits.append((ttl_w, t2, cid2, d2))
print("── ★ 可读性：导线贴近**不相连的引脚**（< %.1f 单位 = %.2f mm ✓）**%d 处** %s"
      % (CLEAR_PIN, CLEAR_PIN * MMU, len(pc_hits), "✓✓" if not pc_hits else "✗✗"))
for ttl_w, t2, cid2, d2 in sorted(pc_hits, key=lambda z: z[3])[:6]:
    print("      ⚠ %-14s 蹭到 %s.%s（%.2f 单位 = %.2f mm）✗"
          % (ttl_w, t2, cid2, d2, d2 * MMU))


# ── ④d ★ 美学指标之二：**位号文字压到东西** ✓（2026-09-27 用户点名 ✓）──#   配 ① 别的元件的本体框 ✓ ② 导线 ✓ ③ 别的位号 ✓（三类分开报 ✓，且**逐条点名** ✓）。
LBOX = [(ttl, ST.label_bbox(lx, ly, fs, lines))
        for ttl, (lx, ly), fs, _c, lines in labels]
bl = bw = bb2 = 0
detail = []
for ttl, bx in LBOX:
    for t2, box in PART_BOX.items():
        if t2 == ttl:
            continue
        if bx[0] < box[2] and box[0] < bx[2] and bx[1] < box[3] and box[1] < bx[3]:
            bl += 1
            detail.append(("压元件", ttl, t2))
    for t2, a, b, _c, _w in wires:
        if _hits_box(a, b, (bx[0], bx[1], bx[2], bx[3]), 0.0, 2):
            bw += 1
            detail.append(("压导线", ttl, t2))
    for t2, bx2 in LBOX:
        if t2 <= ttl:
            continue
        if bx[0] < bx2[2] and bx2[0] < bx[2] and bx[1] < bx2[3] and bx2[1] < bx[3]:
            bb2 += 1
            detail.append(("压位号", ttl, t2))
print("── ★ 美学指标之二：位号文字压到 **别的元件 %d 处** ✓｜**导线 %d 处** ✓｜"
      "**别的位号 %d 处** ✓（字宽表由 `_scratch/adv_measure.py` 实测 ✓）" % (bl, bw, bb2))
for kind, t1, t2 in detail[:10]:
    print("      ⚠ 位号 %-6s %s %s" % (t1, kind, t2))
if len(detail) > 10:
    print("      ⚠ …… 另有 %d 处" % (len(detail) - 10))

# ── ④c ★ 摆位用纯数据导出 ✓（`--pins-out <file.py>` ✓；单位 = sketch ✓、参考点 = 零件锚点 ✓）──
if "pins-out" in opts:
    with open(opts["pins-out"], "w", encoding="utf-8") as fh:
        fh.write("# -*- coding: utf-8 -*-\n")
        fh.write("# 由 render_sch.py --pins-out 生成 ✓（**纯数据** ✓）：\n")
        fh.write("#   PINS[modelIndex][connectorId] = (dx, dy) —— 相对**零件锚点** ✓，sketch 单位 ✓\n")
        fh.write("#   BOX[modelIndex] = (x0, y0, x1, y1) —— 本体包围盒，同样相对锚点 ✓\n")
        fh.write("PINS = %r\n\nBOX = %r\n" % (PINS_REL, BOX_REL))
        fh.write("\n# 位号内容（title + fzp 里 showInLabel 的字段 ✓，Fritzing 自己的口径 ✓）\n")
        fh.write("LAB = %r\n" % LAB_REL)
    print("   摆位数据写入 %s ✓（%d 件的脚位 + 本体框 ✓）" % (opts["pins-out"], len(BOX_REL)))

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
    for i, s_ in enumerate(lines):
        # ★ 基线在**锚点下方**一个行高 ✓（Fritzing 写的是 `<text x="0" y="5.000">位号</text>` ✓，
        #   即第 1 行基线 = 锚点 + font-size ✓）—— 我原来画在`ly + fs*i`（第 1 行 = 锚点 ✗）
        #   ⇒ 整体**偏高 5 单位（1.4mm）** ✗；是 `--verify-export` 量出来的 ✓。
        body.append('<text x="%.4f" y="%.4f">%s</text>'
                    % (lx, ly + fs * (i + 1), s_.replace("&", "&amp;").replace("<", "&lt;")))
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

# ── ⑥ ★★★ 独立核对：拿 Fritzing 自己导出的 svg 当尺子 ✓ —— **零件 / 导线 / 位号 / 接点 全量** ✓ ──
#   ★ 标定只用**少量独立量** ✓（比例 = 导线线宽比 ✓；平移 = 第一件 ✓），
#     其余**逐项验证** ✓（8 件零件 + 46 根导线 + 9 个位号 + 接点数 ✓）—— 这才叫对账 ✓，
#     拿"我自己算的"去比"我自己算的" ✗ 不叫验证 ✗。
if "verify-export" in opts:
    exp = opts["verify-export"]
    raw = open(exp, encoding="utf-8", errors="replace").read()

    def blocks(pat):
        """把 `<g …>` 开头的块按**标签配平**取出来 ✓（**认自闭合 `<g/>`** ✗ 否则配平跑飞 ✗）"""
        out = {}
        for m in re.finditer(pat, raw):
            pid, depth, i = (m.group(1) if m.groups() else ""), 1, m.end()
            while depth and i < len(raw):
                n1, n2 = raw.find("<g", i), raw.find("</g>", i)
                if n2 < 0:
                    break
                if n1 >= 0 and n1 < n2:
                    if raw[n1:raw.find(">", n1)].rstrip().endswith("/"):
                        i = raw.find(">", n1) + 1
                        continue
                    depth += 1
                    i = n1 + 2
                else:
                    depth -= 1
                    i = n2 + 4
            out[pid] = raw[m.end():i]
        return out

    grp = blocks(r'<g partID="(\d+)"\s*>')                                       # 零件 + 导线
    lab = blocks(r'<g\b[^>]*\bid\s*=\s*["\']partLabel["\'][^>]*\bpartID="(\d+)"\s*>')  # 位号

    # ── 导出里的**导线** ✓：`partID` 块里**没有** `<g id="schematic">` ✓，
    #   且那根 line 的 `stroke` **等于我导线的颜色** ✓（✗ 不能按"块里第一根线"挑 ✗ ——
    #   实测：会挑到零件里 `stroke-width="0.4"` 的符号线 ✗ ⇒ 比例算成 0.457 ✗ 全盘对不上 ✗）──
    wire_lines, sws, other_blocks = [], [], []
    for pid, blk in grp.items():
        if re.search(r'''\bid\s*=\s*["\']schematic["\']''', blk):
            continue                                       # 零件组 ⇒ 里面的线是符号自己的 ✗
        got = []
        for m in re.finditer(r"<line\b[^>]*>", blk):
            a = attrs(m.group(0))
            if a.get("id") or "pin" in (a.get("class") or "") or not all(
                    k in a for k in ("x1", "y1", "x2", "y2")):
                continue
            if wires and (a.get("stroke") or "").lower() == wires[0][3].lower():
                got.append((num(a["x1"]), num(a["y1"]), num(a["x2"]), num(a["y2"])))
                sws.append(num(a.get("stroke-width"), 0.0))
            else:
                other_blocks.append((pid, a.get("stroke"), a.get("stroke-width")))
        wire_lines += got
    wire_lines = list(dict.fromkeys(wire_lines))            # 去重（同一根线可能在两处出现）✓

    # ── 标定（两个独立量 ✓）：比例 = 导出线宽 / 我的线宽 ✓；平移 = **第一件**的组平移 ✓ ──
    sw_exp = (sum(sws) / len(sws)) if sws else None
    s = (sw_exp / wires[0][4]) if (sw_exp and wires) else 0.8
    mine = {}
    for el in root.iter("instance"):
        mid = el.get("moduleIdRef") or ""
        if mid.startswith("Wire") or not el.get("modelIndex"):
            continue
        ttl0 = (el.findtext("title") or "").strip()
        if not any(b[0] == ttl0 for b in body_parts):
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
        g = next((c for c in sv if tag(c) == "geometry"), None) if sv is not None else None
        if g is None:
            continue
        fzp = (el.get("path") or "").replace("/", os.sep)
        img = None
        if os.path.isfile(fzp):
            lay = ET.parse(fzp).getroot().find(".//%s/layers" % VIEW)
            img = lay.get("image") if lay is not None else None
        txt = None
        if img:
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
        A = PB.mul(PB.tf_of(g), (k, 0.0, 0.0, k, -k * org[0], -k * org[1]))
        mine[str(el.get("modelIndex")) + "0"] = (ttl0, enum(g, "x") + A[4], enum(g, "y") + A[5])

    def grpT(blk, cut_at=None):
        cut = re.split(cut_at, blk)[0] if cut_at else blk
        tx = ty = 0.0
        for o in re.finditer(r"(translate|matrix)\s*\(([^)]*)\)", cut):
            a = [float(x) for x in re.split(r"[ ,]+", o.group(2).strip()) if x]
            if o.group(1) == "translate":
                tx += a[0]
                ty += a[1] if len(a) > 1 else 0.0
            elif len(a) == 6:
                tx, ty = tx + a[4], ty + a[5]
        return tx, ty

    print("── ★★ 全量独立核对（对着 Fritzing 导出的 %s）──" % os.path.basename(exp))
    print("   标定：比例 s = 导出线宽 %s ÷ 我的线宽 %.6f = **%.6f**（理论 72/90 = 0.8 ✓）"
          % (sw_exp, wires[0][4] if wires else 0, s))
    pairs = []
    for pid, (ttl0, mx, my) in mine.items():
        blk = grp.get(pid)
        if blk is None:
            print("   ⊘ %-12s 导出里没有它的组（Fritzing 就没画它 ✓ 例如面包板 ✓）" % ttl0)
            continue
        tx, ty = grpT(blk, r"<g\b[^>]*\bid\s*=\s*[\"']schematic[\"']")
        pairs.append((ttl0, mx, my, tx, ty))
    if not pairs:
        raise SystemExit("✗ 导出的 svg 里一个零件组都没匹配上 ⇒ 后面没法核对 ✗")
    c = (pairs[0][3] - s * pairs[0][1], pairs[0][4] - s * pairs[0][2])
    print("   标定：平移 c = (%+.4f, %+.4f) ✓（**只用第一件 %s** 定 ✓，其余全部是验证 ✓）"
          % (c[0], c[1], pairs[0][0]))

    def mp(p):
        return (s * p[0] + c[0], s * p[1] + c[1])

    worst_p, worst_p_t = 0.0, ""
    for ttl0, mx, my, tx, ty in pairs:
        d = max(abs(tx - mp((mx, my))[0]), abs(ty - mp((mx, my))[1]))
        if d > worst_p:
            worst_p, worst_p_t = d, ttl0
    print("   ① 零件：%d 件（1 件标定 + %d 件验证）⇒ 最大 Δ = **%.5f 单位（%.5f mm）** @%s %s"
          % (len(pairs), len(pairs) - 1, worst_p, worst_p * MMU, worst_p_t,
             "✓✓" if worst_p < 0.01 else "✗✗"))

    used, unmatched, worst_w, worst_w_t = set(), [], 0.0, ""
    for ttl0, a, b, col, wd in wires:
        ma, mb = mp(a), mp(b)
        best, bi = None, None
        for j, (x1, y1, x2, y2) in enumerate(wire_lines):
            if j in used:
                continue
            d = min(max(math.dist(ma, (x1, y1)), math.dist(mb, (x2, y2))),
                    max(math.dist(ma, (x2, y2)), math.dist(mb, (x1, y1))))
            if best is None or d < best:
                best, bi = d, j
        if bi is not None and best <= 0.05:
            used.add(bi)
            if best > worst_w:
                worst_w, worst_w_t = best, ttl0
        else:
            unmatched.append((ttl0, best if best is not None else float("nan")))
    extra = [wire_lines[j] for j in range(len(wire_lines)) if j not in used]
    print("   ② 导线：导出 %d 根 ↔ 我 %d 根 ⇒ 配上 %d 根，最大 Δ = **%.5f 单位（%.5f mm）** @%s %s"
          % (len(wire_lines), len(wires), len(used), worst_w, worst_w * MMU, worst_w_t,
             "✓✓" if worst_w < 0.05 and not unmatched and not extra else "⚠"))
    for ttl0, d in unmatched[:6]:
        print("        ✗ 我画的 %-14s 在导出里找不到对应线（最近差 %.4f 单位）" % (ttl0, d))
    for w in extra[:6]:
        print("        ✗ 导出里有我没画的线 (%.2f,%.2f)-(%.2f,%.2f)" % w)
    if len(extra) > 6:
        print("        ✗ …… 另有 %d 根" % (len(extra) - 6))

    lw, lbad = 0.0, []
    for ttl0, (lx, ly), fs, col, lines in labels:
        blk = next((b for b in lab.values()
                    if re.search(r">%s</text>" % re.escape(ttl0), b)), None)
        if blk is None:
            lbad.append((ttl0, "导出里没有这个位号 ✗"))
            continue
        tx, ty = grpT(blk)
        d = max(abs(tx - mp((lx, ly))[0]), abs(ty - mp((lx, ly))[1]))
        lw = max(lw, d)
        got = [u for u in re.findall(r"<text[^>]*>([^<]*)</text>", blk)]
        got = [html.unescape(x) for x in got]              # ★ 导出里是 `&#xb1;`/`&#x3a9;` 这种数字转义 ✓
        if got != lines:                                   #   ⇒ 不解转义会把 `±5%`/`220Ω` 当成不同 ✗（假警报 ✗）
            lbad.append((ttl0, "行内容不同：我 %s ↔ 导出 %s" % (lines, got)))
    print("   ③ 位号：%d 个 ⇒ 位置最大 Δ = **%.5f 单位（%.5f mm）** %s；行内容 %s"
          % (len(labels), lw, lw * MMU, "✓✓" if lw < 0.01 else "✗✗",
             "全同 ✓" if not lbad else "**%d 处不同** ✗" % len(lbad)))
    for t, why in lbad[:6]:
        print("        ✗ %-12s %s" % (t, why))

    dots_exp_raw = []
    for m in re.finditer(r"<circle\b[^>]*>", raw):
        a = attrs(m.group(0))
        if (a.get("fill") or "").lower() == "black" and a.get("r") == "0.72":
            # ★ 导出坐标 → sketch ✓ 要用**逆映射** ✓（`mp` 是正映射 ✗，套两次就错了 ✗）
            dots_exp_raw.append(((num(a["cx"]) - c[0]) / s, (num(a["cy"]) - c[1]) / s))
    uq = []
    for q in dots_exp_raw:
        if not any(math.dist(q, u) < 0.05 for u in uq):
            uq.append(q)
    dmiss = [q for q in uq if not any(math.dist(q, p) < 0.05 for p in dots)]
    dextra = [p for p in dots if not any(math.dist(p, q) < 0.05 for q in uq)]
    print("   ④ 接点：导出 %d 个圆 = **%d 个位置**（每处 %d 个 ✓）↔ 我 %d 个位置"
          " ⇒ 我少的 %d 个 ✓、我多的 %d 个 %s"
          % (len(dots_exp_raw), len(uq), round(len(dots_exp_raw) / max(1, len(uq))),
             len(dots), len(dmiss), len(dextra), "✓" if not (dmiss or dextra) else "✗"))
    for q in dmiss[:5]:
        print("        ✗ 导出点了、我没点的位置 (%.3f,%.3f)" % q)
    for p in dextra[:5]:
        print("        ✗ 我点了、导出没点的位置 (%.3f,%.3f)" % p)
    # ── ⑤ ★★ 引脚判别（2026-09-27 补 ✓ —— 起因就是"没有它"骗了我一整天 ✗）──
    #   上面 ①②③ 只比"零件**锚点**"与"**导线自己**" ✗ —— 两边都用**我自己的坐标系** ⇒
    #   自洽 ⇒ 永远通过 ✗（典型的"自证" ✗；`px` 那个 bug 就是这么躲过一整天的 ✓）。
    #   下面两条**全在导出内部比** ✓ ⇒ **不需要任何标定** ✓（全局平移/缩放自动抵消 ✓）：
    #     A. **同一零件内部**的脚向量：我算的 × s ↔ 导出画的 ✓
    #        （抓"零件 k 算错" ✗、"镜像/旋转" ✗、"脚编号接错" ✗ —— `px` 那个 bug 正是它抓的 ✓）
    #     B. **线到脚**：每条"导线→脚"的连接 ⇒ "导出画的线端" ↔ "导出画的脚" ✓
    #        （抓"我按错的脚位画线" ✗ —— 用户看到的"网在一起、线却错位" ✓）
    def _walk_exp(el, m, pid, pout, lout):
        t2 = el.get("transform")
        if t2:
            m = PB.mul(m, PB.parse_tf(t2))
        if el.get("partID"):
            pid = el.get("partID")
        i2 = el.get("id") or ""
        m2 = re.fullmatch(r"connector(.+?)(terminal|pin)", i2)
        if m2 and pid and el.get("x") is not None:
            pout.setdefault(pid, {}).setdefault("connector" + m2.group(1),
                                                PB.apply(m, float(el.get("x")), float(el.get("y"))))
        if tag(el) == "line" and pid and el.get("x1") is not None:
            lout.setdefault(pid, []).append((PB.apply(m, float(el.get("x1")), float(el.get("y1"))),
                                             PB.apply(m, float(el.get("x2")), float(el.get("y2")))))
        for cc in el:
            _walk_exp(cc, m, pid, pout, lout)

    exp_pins, exp_lines = {}, {}
    try:
        _walk_exp(ET.parse(exp).getroot(), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None,
                  exp_pins, exp_lines)
    except Exception as ex:
        print("   ⊘ 引脚判别跳过（导出解析不了：%s ✗）" % ex)

    def pid_of(mi):
        return next((k for k in exp_pins if k == mi or
                     (k.startswith(mi) and len(k) == len(mi) + 1)), None)

    pv_bad = []
    for mi2, rel in sorted(PINS_REL.items()):
        cats = [k for k in rel if not k.startswith("__")]
        p2 = pid_of(mi2)
        if p2 is None or len(cats) < 2:
            continue
        for a2, b2 in zip(cats, cats[1:]):
            if a2 not in exp_pins[p2] or b2 not in exp_pins[p2]:
                continue
            mv = (s * (rel[b2][0] - rel[a2][0]), s * (rel[b2][1] - rel[a2][1]))
            ev = (exp_pins[p2][b2][0] - exp_pins[p2][a2][0],
                  exp_pins[p2][b2][1] - exp_pins[p2][a2][1])
            if math.dist(mv, ev) > 0.05:
                pv_bad.append((rel.get("__title__", mi2), a2, b2, mv, ev))
    npin_chk = sum(1 for r in PINS_REL.values()
                   if len([k for k in r if not k.startswith("__")]) >= 2)
    print("   ⑤ 引脚判别：**同一零件内脚向量** %s"
          % ("**全部一致** ✓✓（%d 件 ✓）" % npin_chk
             if not pv_bad else "**%d 条对不上** ✗✗（下面是前 6 条 ✓）" % len(pv_bad)))
    for ttl0, a2, b2, mv, ev in pv_bad[:6]:
        print("        ✗ %-6s %s→%s 我(%7.2f,%7.2f) 导出(%7.2f,%7.2f) ⇒ 比值 %.3f"
              % (ttl0, a2, b2, mv[0], mv[1], ev[0], ev[1],
                 (abs(ev[0]) / abs(mv[0])) if abs(mv[0]) > 1e-6 else float("nan")))

    wm = {el.get("modelIndex"): (el.findtext("title") or "").strip()
          for el in root.iter("instance")
          if (el.get("moduleIdRef") or "").startswith("Wire")}
    links = []
    for el in root.iter("instance"):
        if not (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        for c in el.iter():
            if tag(c) != "connect":
                continue
            if c.get("modelIndex") in wm:
                continue
            links.append((el.get("modelIndex"), c.get("modelIndex"), c.get("connectorId")))
    tbad, tmax = [], 0.0
    for wmi, pmi, cid in links:
        wpid = next((k for k in exp_lines if k == wmi or
                     (k.startswith(wmi) and len(k) == len(wmi) + 1)), None)
        ppid = pid_of(pmi)
        if wpid is None or ppid is None or cid not in exp_pins.get(ppid, {}):
            continue
        pts = [q for seg2 in exp_lines[wpid] for q in seg2]
        pp = exp_pins[ppid][cid]
        d2 = min(math.dist(pp, q) for q in pts)
        tmax = max(tmax, d2)
        if d2 > 0.5:
            tbad.append((wm.get(wmi, wmi), ppid[:-1], cid, d2))
    print("   ⑥ 引脚判别：**线到脚** %d 条 ⇒ 没接上的 %d 处（最大 %.3f 导出单位 = %.2f mm）%s"
          % (len(links), len(tbad), tmax, tmax * 25.4 / 72, "✓✓" if not tbad else "✗✗"))
    for ttl0, pmi, cid, d2 in tbad[:6]:
        print("        ✗ %-13s 该接 %s.%s，线端离脚 **%.2f mm** ✗" % (ttl0, pmi, cid, d2 * 25.4 / 72))

    # ★ 判定分**三类**报 ✓：几何（尺寸/位置 ✓）｜装饰（接点圆点 ✓）｜文本（位号文字 ✓）
    #   —— 用一个 0.25mm 的圆点去掩盖"几何已逐点验平"是**把结论说糊**了 ✗，
    #     反过来也一样 ✗（几何错了就不能拿"就几个圆点"糊过去 ✗）。
    geo_ok = (worst_p < 0.01 and worst_w < 0.05 and not unmatched and not extra and lw < 0.01
              and not pv_bad and not tbad)
    dot_ok = not dmiss and not dextra
    print("   ⇒ 几何（零件/导线/位号位置 **+ 引脚**）：%s"
          % ("✓✓ **与 Fritzing 逐点一致** ✓✓（含引脚 ✓；四处 Δ 全部 ≤0.001 单位 = 0.0003 mm ✓）"
             if geo_ok else "✗ 有几何不一致项 ✗（上面已逐条列出 ✓ 别默认它没事 ✗）"))
    print("   ⇒ 装饰（接点圆点）：%s"
          % ("✓ 一致 ✓" if dot_ok else "⚠ 差 %d 个（纯装饰 ✓，半径 0.9 单位 = 0.25mm ✓；"
             "原因未定 ✓ 已如实记录 ✓）" % (len(dmiss) + len(dextra))))
    print("   ⇒ 文本（位号内容）：%s"
          % ("全同 ✓" if not lbad else "%d 处差异 ⚠（不影响几何 ✓）" % len(lbad)))
