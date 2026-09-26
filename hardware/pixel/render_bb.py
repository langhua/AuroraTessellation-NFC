# -*- coding: utf-8 -*-
"""把 .fzz 的**面包板视图**渲染成 PNG ✓（为了"看得见" ✓）

做法（不自创几何 ✓，全部按 Fritzing 的摆放规矩来 ✓）：
  · 零件摆放 = `sketch = loc + M·(k·局部用户单位) + (m31,m32)` ✓ —— 矩阵与缩放
    直接用 `part_box.py`（`tf_of` / `parse_tf` / `mul` ✓）那套 ✓，
    它算"本体包围盒"时用的同一套数学 ✓（**不另写一份** ✗）；
  · 导线 = `geometry x/y/x2/y2`（x2/y2 是**相对** ✓）+ `wireExtras/@color` ✓，线宽 2 单位 ✓；
  · 零件/板子的 svg 从 .fzz 包里取 ✓；包里没有（core 件）就从它的 fzp 路径旁边取 ✓。

用法：py -3.13 f:\\git\\_scratch\\render_bb.py <sketch.fzz> <out.png> [<px宽>]
"""
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # ★ 先找"自己旁边" ✓（入库后
sys.path.insert(0, r"f:\git\_scratch")                           #   在 hardware/pixel/ 里也能跑 ✓）
import part_box as PB                                             # noqa: E402
try:
    import bb_compare as BC                                       # ★ 孔位/遮挡同一份实现 ✓
except ImportError:                                               # 从 _scratch 跑 ⇒ 指到仓库那份 ✓
    sys.path.insert(0, r"f:\git\AuroraTessellation-NFC\hardware\pixel")
    import bb_compare as BC                                       # noqa: E402

path, out = sys.argv[1], sys.argv[2]
PXW = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0
SK = 3.5433                    # 1mm = 3.5433 sketch 单位 ✓


def tag(e):
    return e.tag.split("}")[-1]


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def inner(svg_text):
    t = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", svg_text)
    m = re.search(r"<svg\b[^>]*>", t, flags=re.S)
    if not m:
        return ""
    body = t[m.end():]
    body = body[:body.rfind("</svg>")] if "</svg>" in body else body
    return body


def scale_of(svg_text):
    """svg 的 用户单位 → sketch 单位 ✓

    ★★ 2026-09-27 修 ✓（用户定位的 bug ✗：「preview.svg 的**面包板尺寸**错误 ⇒ 看起来不对」✓）：
      老写法是「**没有 viewBox 就 return 1.0**」✗ —— 而**面包板 svg 恰恰没有 viewBox** ✗
      （`breadboard2.svg` 头：`width="468.238px" height="151.2px"` ✓ 无 viewBox ✗）
      ⇒ 板子按"用户单位＝sketch 单位"画 ✗ ⇒ **板子小了 ~20%** ✗（正确值 1.2502 ✓）
      ⇒ 零件/导线相对板子偏大、看着"落不到孔上" ✗ = 用户看到的现象 ✓。
      ★ 两种 px 要分清 ✓（2026-09-27 **实测钉死** ✓，别再猜 ✗）：
        · **有 viewBox 的 px/无单位** = 90dpi ✓（Fritzing 新惯例 ✓）；
        · **没有 viewBox 的老 svg** ＝ **72dpi（"点"）** ✓ —— 面包板就是这种 ✓：
          `468.238px × 25.4/72 = 165.2mm` ✓ ≈ 孔阵 `576 单位 = 162.6mm` ✓（对上了 ✓）；\
          若按 90dpi 算得 132mm ✗ ⇒ **板子画小一圈** ✗ ⇒ 底部 X/W 两条轨落到板外 ✗
          ⇒ 看着像"导线悬到板外" ✗（用户看到的正是这个 ✗）。
    """
    head = re.search(r"<svg\b[^>]*>", svg_text, flags=re.S)
    if not head:
        return 1.0
    h = head.group(0)
    m = re.search(r'width="([\d.]+)(mm|in|px)?"', h)
    vb = re.search(r'viewBox="([^"]+)"', h)
    if not m:
        print("      [!] 这张 svg 连 width 都没有 ⇒ 只能按「用户单位＝sketch 单位」画 ✗")
        return 1.0
    v = float(m.group(1))
    u = m.group(2) or ""
    if u == "mm":
        umm = 1.0
    elif u == "in":
        umm = 25.4
    else:
        umm = 25.4 / (90.0 if vb else 72.0)       # ★ 有 viewBox=90dpi ✓ / 无 viewBox=72dpi ✓
    if not vb:
        return umm * SK                          # 没有 viewBox ⇒ 用户单位本身就是长度 ✓
    parts = [float(x) for x in re.split(r"[ ,]+", vb.group(1).strip()) if x]
    if len(parts) != 4 or not parts[2]:
        return umm * SK
    return v * umm * SK / parts[2]


z = zipfile.ZipFile(path)
fzname = [n for n in z.namelist() if n.endswith(".fz")][0]
root = ET.fromstring(z.read(fzname))

packed = {}
for n in z.namelist():
    if n.endswith(".svg"):
        packed[n] = z.read(n).decode("utf-8", "replace")

svg_cache = {}
LAST_PICK = [None]          # ★ 刚才那个零件到底用了哪个 svg ✓（要点名 ✓，不静默 ✓）


def svg_for(fzp_path, img, view="breadboard"):
    """取零件的视图 svg 文本 ✓：先看包里 ✓，再按 fzp 路径旁边找 ✓"""
    key = (fzp_path, img)
    LAST_PICK[0] = None
    if key in svg_cache:
        return svg_cache[key]
    txt = None
    want = os.path.basename(img or "")
    for n, t in packed.items():
        if want and n.endswith(want):
            txt = t
            LAST_PICK[0] = n
            break
    if txt is None and fzp_path and img:
        base = os.path.dirname(os.path.dirname(fzp_path))
        for s2 in ("", "core", "contrib", "user"):
            cand = os.path.normpath(os.path.join(base, "svg", s2, img.replace("/", os.sep)))
            if os.path.isfile(cand):
                txt = open(cand, encoding="utf-8").read()
                LAST_PICK[0] = cand
                break
    svg_cache[key] = txt
    return txt


lay_body, wires = [], []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    ttl = (el.findtext("title") or "").strip()
    vw = next((c for c in el if tag(c) == "views"), None)
    if vw is None:
        continue
    bv = next((c for c in vw if tag(c) == "breadboardView"), None)
    if bv is None:
        continue
    g = next((c for c in bv if tag(c) == "geometry"), None)
    if g is None:
        continue
    if mid.startswith("Wire"):
        col = "#404040"
        we = next((c for c in bv.iter() if tag(c) == "wireExtras"), None)
        if we is not None and we.get("color"):
            col = we.get("color")
        x, y = num(g.get("x")), num(g.get("y"))
        x2, y2 = num(g.get("x2")), num(g.get("y2"))
        if abs(x2) + abs(y2) > 1e-9:
            wires.append((x, y, x + x2, y + y2, col))
        continue
    if ttl.startswith("TXT"):        # 图例文字件：不画正文（免得挡住视图 ✓）
        continue
    fzp = (el.get("path") or "").replace("/", os.sep)
    lay = ET.parse(fzp).getroot().find(".//breadboardView/layers") if os.path.isfile(fzp) else None
    img = lay.get("image") if lay is not None else None
    txt = svg_for(fzp, img)
    if txt is None:
        continue
    # ★★ 2026-09-27 ✓：**点名报出**这个零件到底用了哪个 svg ✓（用户报"preview 全不对" ✗ ⇒
    #   不许再拿"渲染没报错"当证据 ✗ —— 要把"取了哪个文件"打出来，人能核对 ✓）
    print("   %-6s image=%-42s 用了 %s（%d 字节）"
          % (ttl, img or "（无）",
             os.path.basename(LAST_PICK[0]) if LAST_PICK[0] else "（**找不到** ✗）",
             len(txt)))
    m = PB.tf_of(g)
    k = scale_of(txt)
    # ★★ 面包板（旧 Illustrator 导出的 px svg ✓）：**px = 1/72 in** ✓（2026-09-27 ✓）
    #   为什么不能靠 `scale_of` 的"有 viewBox ⇒ 90dpi" ✗：这块板子**有** viewBox
    #   （`0 0 468.238 …` ✓）⇒ 会被算成 `468.238px = 132.1mm` ✗，而它必须是 **165.2mm** ✓
    #   （72dpi ✓）—— 否则**板子画小一圈** ✗ ⇒ 底部 X/W 两条轨落到板外 ✗
    #   ⇒ 看着像"导线悬在板外" ✗（用户看到的正是这个 ✓）。
    #   ★ 判据（可核对 ✓）：`468.238 × 25.4/72 = 165.2mm` ✓ ≈ 孔阵 `576 单位 = 162.6mm` ✓
    #     （相差 9 单位 = 一列留边 ✓ 合理 ✓）；按 90dpi 得 132.1mm ✗ ⇒ 明显对不上板子 ✓。
    #   ⇒ 圆 ≥100 个（= 面包板 ✓）时，px/无单位一律按 **72dpi** ✓，并把尺寸打出来 ✓。
    if len(re.findall(r"<circle", txt)) >= 100:
        _m2 = re.search(r'width="([\d.]+)px"', txt) or re.search(r'width="([\d.]+)"', txt)
        if _m2:
            _wmm = float(_m2.group(1)) * 25.4 / 72.0
            print("   %-6s **面包板按 72dpi** ✓：宽 %.3fpx = **%.1f mm** ✓（孔阵 = 576 单位 = 162.6mm ✓）"
                  % (ttl, float(_m2.group(1)), _wmm))
            if _m2.group(1) and float(_m2.group(1)) > 0:
                _vbw = re.search(r'viewBox="[\d.]+\s+[\d.]+\s+([\d.]+)', txt)
                if _vbw and abs(float(_vbw.group(1)) - float(_m2.group(1))) < 1e-6:
                    k = 25.4 / 72.0 * SK       # ★ 用户单位 = px ⇒ k = (1/72 in) × 3.5433 ✓
                    print("        ⇒ 自标定 k = %.4f ✓（原 %.4f ✗）" % (k, scale_of(txt)))
    # ★★ 2026-09-27 ✓（用户定位 ✗：`preview.svg` 的**面包板尺寸错** ⇒ 看起来不对 ✓）：
    #   把**每张 svg 的头部声明**和**我算出的 k** 打出来 ✓ —— 才能看出是哪一件、错在哪 ✗。
    #   （`scale_of` 里：无单位按 90dpi ✓、`%` 或解析不到 ⇒ 直接**退化 k=1.0** ✗✗
    #     ⇒ 那件就按"用户单位＝sketch 单位"画 ✗ = **尺寸全错** ✓。）
    _hdr = re.search(r"<svg\b[^>]*>", txt, flags=re.S)
    # ★★ 自检 ✓（2026-09-27 ✓）：把这次画的尺寸换成 **mm** 报出来 ✓ ——
    #   板子/零件的物理尺寸人手一算就能对账 ✓（不再"渲染没报错就算对" ✗）。
    _vbm = re.search(r'viewBox="[\d.]+[\s,]+[\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)"', txt)
    _phys = ""
    if _vbm:
        _phys = "本体 %.1f×%.1f mm" % (float(_vbm.group(1)) * k * 25.4 / 90.0,
                                        float(_vbm.group(2)) * k * 25.4 / 90.0)
    print("   %-6s svg头: %s ‖ k=%.4f %s"
          % (ttl,
             " ".join(re.findall(r'[a-zA-Z:-]+="[^"]*"', _hdr.group(0))) if _hdr else "（无头 ✗）",
             k, _phys))
    # ★★★ 脚位自检 ✓✓（2026-09-27 用户报 ✗："1010 板的 4 个引脚都是悬空的" ✓）：
    #   把每个脚**画出来的位置**算出来 ✓（part svg 里 `id="connectorNpin"` 的圆心 ✓，
    #   与布线器算 EPAD 焊盘用的是同一套数学 ✓），再跟它**声称插进的孔** ✗ 比 ✓
    #   ⇒ Δ 应当 ≈ 0 ✓；**Δ 大 = "脚悬空"** ✗（正是用户一眼看到的 ✓）。
    _ph = {}                       # 脚 id → 它插进的孔 id ✓（从 <connector> 下的 <connect> 读 ✓）
    for _cn in bv.iter():
        if tag(_cn) != "connector":
            continue
        for _cs2 in _cn.iter():
            if tag(_cs2) == "connect" and _cs2.get("layer") == "breadboardbreadboard":
                _ph[_cn.get("connectorId")] = _cs2.get("connectorId")
    _circles = re.findall(r"<(?:circle|ellipse)[^>]*>", txt)
    _nchk = _bad = 0
    _unv = 0
    for _cid2, _hid2 in sorted(_ph.items()):
        _el2 = next((s for s in _circles if 'id="%spin"' % re.escape(str(_cid2)) in s), None)
        if _el2 is None:
            _unv += 1
            continue               # ★ 认不出 ⇒ **记入"未验证"** ✓（不许静默跳过 ✗）
        _cx = re.search(r'\bcx="([-\d.]+)"', _el2)
        _cy = re.search(r'\bcy="([-\d.]+)"', _el2)
        _xy2 = BC.hole_xy(_hid2) if _hid2 else None
        if not (_cx and _cy) or _xy2 is None:
            continue
        _nchk += 1
        _lu, _lv = float(_cx.group(1)) * k, float(_cy.group(1)) * k
        _padx = num(g.get("x")) + m[0] * _lu + m[2] * _lv + m[4]
        _pady = num(g.get("y")) + m[1] * _lu + m[3] * _lv + m[5]
        _dx, _dy = _padx - _xy2[0], _pady - _xy2[1]
        _dd = (_dx * _dx + _dy * _dy) ** 0.5
        if _dd > 1.0:              # 1 单位 = 0.28mm ✓；超过就是"脚没落在孔上" ✗
            _bad += 1
            print("      ✗ 脚 %-16s 画在 (%7.1f,%7.1f)，孔 %-8s 在 (%7.1f,%7.1f)"
                  " ⇒ Δ=%.2f 单位 (%.2f mm) **悬空** ✗"
                  % (_cid2, _padx, _pady, _hid2, _xy2[0], _xy2[1], _dd, _dd * 25.4 / 90.0))
    if _nchk or _unv:
        _verdict = ("✓ 全落在孔上 ✓" if not _bad else "✗ **%d 个悬空** ✗" % _bad) \
            if _nchk else "**一个都没查到 ⇒ 未验证 ✗（别当它是对的 ✗）**"
        print("      脚位自检：查到 %d 个脚 ⇒ %s ｜认不出/未验证 %d 个 %s"
              % (_nchk, _verdict, _unv, "✓" if not _unv else "✗（这些件只能靠人眼 ✓）"))
    a, b, c, d = k * m[0], k * m[1], k * m[2], k * m[3]
    e, f = num(g.get("x")) + m[4], num(g.get("y")) + m[5]
    # ★★ 2026-09-27 **撤掉**早先那个 `translate(-minX,-minY)` ✗（用户报 ✗："1010 板被移动了一点儿，
    #   4 个引脚都悬空" ✓）：我在这里做的是把**用户坐标**重映射到 sketch ✓，
    #   **不是**在摆 viewport ✗ ⇒ **viewBox 的原点不该减** ✗。减了以后，
    #   **原点非 0 的那个件**（全批次只有 `LED2` ✓：`viewBox="1.03 0 19.54 28.8"`）
    #   就整体偏移 **1.03 单位 ≈ 0.29mm** ✗ ⇒ 四个脚落到孔外 ✗ ✓（图看着就是"脚悬空"✓）。
    #   （当年加它的"理论"是错的 ✗：那套"原点非 0 要补偿"只对**贴图/视口**成立 ✗。）
    lay_body.append('<g transform="matrix(%.6f %.6f %.6f %.6f %.6f %.6f)">%s</g>'
                    % (a, b, c, d, e, f, inner(txt)))

xs, ys = [0.0, 576.0], [0.0, 189.0]
for x1, y1, x2, y2, _c in wires:
    xs += [x1, x2]
    ys += [y1, y2]
x0, x1 = min(xs) - 12, max(xs) + 12
y0, y1 = min(ys) - 12, max(ys) + 12
w, h = x1 - x0, y1 - y0
body = ['<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#f7f7f7"/>' % (x0, y0, w, h)]
body += lay_body
for x1_, y1_, x2_, y2_, col in wires:
    body.append('<line x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f" stroke="%s" '
                'stroke-width="2" stroke-linecap="round"/>' % (x1_, y1_, x2_, y2_, col))
# ★★ 2026-09-27 修 ✓（用户定位 ✗：「preview.svg 的**面包板尺寸错误** ⇒ 看起来不对；
#   我在 Inkscape 里放大就对了」✓）：
#   `width="1800" height="615"` **不带单位** ✗ ⇒ Inkscape/浏览器按 **CSS px** 解释 ✗
#   ⇒ 文档变成 **1800/96 in = 476mm 宽** ✗，而图里的内容只有 **623 单位 = 175.8mm** ✗
#   ⇒ 尺寸声明与实际内容不符 ⇒ 「面包板尺寸错误」✓；按内容看（放大 ✓）就是对的 ✓。
#   ⇒ 现在把 `width/height` 显式写成 **mm** ✓（1 单位 = 25.4/90 mm ✓）。
MMU_ = 25.4 / 90.0
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%.2fmm" height="%.2fmm" '
       'viewBox="%.2f %.2f %.2f %.2f">%s</svg>'
       % (w * MMU_, h * MMU_, x0, y0, w, h, "".join(body)))
svgtmp = os.path.splitext(out)[0] + ".svg"
open(svgtmp, "w", encoding="utf-8").write(svg)
print("   预览画布 = %.1f × %.1f mm（板子孔阵 576 单位 = 162.6mm ⇒ 应比它略大 ✓）"
      % (w * MMU_, h * MMU_))

import cairosvg                                                   # noqa: E402
cairosvg.svg2png(url=svgtmp, write_to=out, output_width=round(PXW),
                 output_height=round(PXW * h / w), background_color="white")
print("零件 %d 个 ✓ | 导线 %d 段 ✓ | 画布 %.0f×%.0f 单位" % (len(lay_body), len(wires), w, h))
print("写入 %s（同时留了 %s ✓）" % (out, svgtmp))
