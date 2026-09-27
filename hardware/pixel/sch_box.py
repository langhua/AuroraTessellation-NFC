# -*- coding: utf-8 -*-
r"""★ **“本体盒”的唯一实现** ✓（2026-09-27 ✓）—— 零件 svg + 一次摆放 ⇒ sketch 坐标下的盒

★★ 为什么要有这个文件（今天的血教训 ✓）：
  原来 `render_sch.py` 与 `gen_schematic_wires.py` **各算一套盒子** ✗
  ⇒ 实测**同一件** `L1` 两边差 **0.43 单位** ✗：
      · 渲染器（判据 ✓）：`(-9.97, 113.40 → -5.47, 167.40)`
      · 布线器（自己 walk 尺子 svg ✗）：`(-10.40, 113.00 → -5.90, 167.40)`
  ⇒ 后果：布线器那道“不许进别人本体”的**硬闸门物理上看不见**渲染器报的那一段 ✗
    （实测那段在 `x = -6.0` ✓：一边在盒里 ✓、一边在盒外 ✓）⇒ 三版闸门**全白改** ✗✗。
  ⇒ 本仓规矩（“**判据只能一份实现**” ✓）：盒子**只在这里算** ✓，
    `render_sch.py`（判据）与 `gen_schematic_wires.py`（布线）都调它 ✓。

★ 下面这些（`HDR/ATTR_RE/UMM/tag/num/enum/attrs/inner/head_of/viewbox_of/scale_of/
  layer_of/to_sketch`）都是从 `render_sch.py` **逐字搬**来的 ✓（搬时**一行未改** ✓）——
  下次要改它们，**只改这里** ✓；`render_sch.py` 已改成从这里 import ✓。
"""
import math
import os
import re
import xml.etree.ElementTree as ET

import part_box as PB

SK_U_PER_MM = PB.MM                       # 3.5433 ✓（1/90 in ✓）
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


def to_sketch(g, A, p):
    """零件 svg 的**用户坐标** `p` → sketch 绝对坐标 ✓

    ★ 仿射是**完整**的 2×3：`x' = A0·x + A2·y + A4` ✓ —— **`A4/A5` 不能漏** ✗✗
      （它们就是 `−k×viewBox原点` ✓）。第一版漏过 ✗，症状**很隐蔽**：
      原点为 (0,0) 的件**看不出来** ✓，只有 `U1`（`viewBox="-190 -190 …"` ✓）的脚
      **一律偏 17.124 单位** ✗（= 0.09×190 ✓）。
    """
    return (enum(g, "x") + A[0] * p[0] + A[2] * p[1] + A[4],
            enum(g, "y") + A[1] * p[0] + A[3] * p[1] + A[5])


# ── ★★ 新增：给“盒子”用的两个入口 ✓（“本体盒”全仓唯一实现 ✓）──
def resolve_parts_svg(fzp_path, image):
    """按 fzp 的 `image=` 在**磁盘**上找真 svg ✓；顺带报出**试过哪些地方** ✓（不静默 ✗）

    ★ 逐字搬自 `render_sch.py` 的 `resolve` ✓（搬时一行未改 ✓）—— 路径约定：
      fzp 在 `<…>/parts/<user|core|contrib>/x.fzp` ✓ ⇒ svg 在它**外公目录**的 `svg/<同名子目录>/` ✓。
    """
    base = os.path.dirname(os.path.dirname(fzp_path))
    tried = []
    for sub in ("user", "core", "contrib", ""):
        cand = os.path.normpath(os.path.join(base, "svg", sub, (image or "").replace("/", os.sep)))
        tried.append(cand)
        if os.path.isfile(cand):
            return cand, tried
    return None, tried


def part_svg_text(fzp_path, packed, image):
    """零件 svg 文本 ✓：**磁盘优先** ✓（Fritzing 就是从 fzp 旁边加载 ✓），包内同名条目兜底 ✓

    ★★ 为什么要有这个函数（2026-09-27 血的教训 ✓）：布线器原来**自己猜**写法 ✗：
      ✗ 以为 svg 名在 `<schematicView image=…>` ✗（实际在 **`<schematicView><layers image=…>`** ✓）；
      ✗ 以为该从 .fzz 里的 `part.<mid>.fzp` 读 ✗（实际要用**实例的 `path=`** ✓，那是磁盘 fzp ✓）⇒
      实测 **10 件全取不到** ✗ ⇒ 本体盒全空 ✗ ⇒ 硬闸门/nv/自家本体**全失效** ✗✗（画布 111.0 ✗）。
    ★ 返回 `(文本, 来源)`；取不到时文本为 `None`，来源是“找过哪里”的说明 ✓（不静默 ✗）。
    """
    cand, tried = resolve_parts_svg(fzp_path, image)
    if cand:
        try:
            return open(cand, encoding="utf-8", errors="replace").read(), cand
        except OSError as ex:
            tried = tried + ["%s（打不开：%s）" % (cand, ex)]
    want = os.path.basename(image or "")
    for n, t in (packed or {}).items():
        if want and n.endswith(want):
            return t, n + "（**包内副本** ✓）"
    return None, "找过 %s" % " ; ".join(tried)


def A_of(part_svg_text, g_el):
    """零件 svg + `<geometry>` 元素 ⇒ **仿射 A**（用户坐标 → sketch 绝对坐标 ✓）

    ★ 与 `render_sch.py` 里原来那两行**同源** ✓：
        `A = PB.mul(PB.tf_of(g), (k, 0, 0, k, -k·orgx, -k·orgy))` ✓
    """
    k, org, _note = scale_of(part_svg_text)
    if k is None:
        return None
    return PB.mul(PB.tf_of(g_el), (k, 0.0, 0.0, k, -k * org[0], -k * org[1]))


def box_of(part_svg_text, g_el, A=None):
    """★ **本体盒** ✓（sketch 单位 ✓）—— 返回 `(box, A, note)`；算不出返回 `(None, A, note)`

    ★ 口径（唯一 ✓）：`PB.shape_bbox(零件 svg)` 的四角 ✓ 过 `A` ✓ 取轴对齐包围盒 ✓。
      `render_sch.py` 与 `gen_schematic_wires.py` 都调它 ⇒ **不会再出现两套尺子** ✓。
    """
    k, org, note = scale_of(part_svg_text)
    if A is None:
        A = A_of(part_svg_text, g_el)
    if k is None or A is None:
        return None, A, note
    try:
        bb = PB.shape_bbox(ET.fromstring(part_svg_text))
    except Exception as ex:                    # ★ 解析不了要**吭声** ✓ 不静默 ✗
        return None, A, "%s｜svg 解析不了：%s" % (note, ex)
    if not bb:
        return None, A, note + "｜shape_bbox 空 ✗"
    pts = [to_sketch(g_el, A, (cx, cy))
           for cx, cy in ((bb[0], bb[1]), (bb[2], bb[1]), (bb[0], bb[3]), (bb[2], bb[3]))]
    return ((min(p[0] for p in pts), min(p[1] for p in pts),
             max(p[0] for p in pts), max(p[1] for p in pts)), A, note)
