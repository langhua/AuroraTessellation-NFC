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

# ★★ 2026-09-27 修 ✓：**只认"自己旁边"的模块** ✓ ——
#   原来还 `insert(0, r"f:\git\_scratch")` ✗ ⇒ `_scratch` 里的**旧副本**会顶掉仓库这份 ✗
#   ⇒ 我刚加的 `part_box.pin_points` **根本没加载到** ✗（日志原话：`module 'part_box' has no
#   attribute 'pin_points'` ✓）—— 而且它**不报错、不退出** ✗，只是脚位自检全部沦陷为"未验证" ✗。
#   ★ 教训：**同一个工具只能有一份** ✓（`_scratch` 是草稿区 ✓，**绝不能进 import 路径** ✗）；
#     "路径里有旧副本"这种坑不会报错 ✗ ⇒ 只会在结果里静静变错 ✗。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import part_box as PB                                             # noqa: E402
import bb_compare as BC                                           # ★ 孔位/遮挡同一份实现 ✓

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


UNIT_MM = {"": 25.4 / 1000.0,          # ★ 无单位 = 1/1000 英寸 ✓（Fritzing 零件约定 ✓）
           "px": 25.4 / 72.0,          # ★★ `px` = **1/72 英寸** ✓（2026-09-27 实测钉死 ✓）
           "pt": 25.4 / 72.0,
           "mm": 1.0, "cm": 10.0, "in": 25.4}


def scale_of(svg_text):
    """svg 的**用户单位 → sketch 单位** ✓（**只有一条规则** ✓，不分"有没有 viewBox" ✗）

        w_mm = width值 × UNIT_MM[单位]
        有 viewBox ⇒ 1 用户单位 = w_mm / viewBox宽
        没有 viewBox ⇒ 1 用户单位 = UNIT_MM[单位]
        k = 每用户单位 mm × 3.5433（= 1mm 的 sketch 单位数 ✓）

    ★★★ 2026-09-27 **实测钉死** ✓（我在单位上连错三次 ✗，每次都被用户点出来 ✓，记下来别再犯 ✗）：
      · **`px` = 1/72 英寸 = 0.35278 mm** ⇒ k = **1.2500** ✓
        证据①（**面包板自己** ✓）：`width="468.238px" viewBox="0 0 468.238 …"` ⇒ 468.238px = **165.2mm** ✓
          ≈ 孔阵 `576 单位 = 162.6mm` ✓（差 9 单位 = 端部留边 ✓ 合理 ✓）；
        证据②（**LED2 的 `WS2812B_1010`** ✓）：`width="19.54px" viewBox="1.03 0 19.54 28.8"` ⇒ 同样 k=1.25 ✓
          ⇒ 4 脚中心差 **14.401 × 21.600 用户单位** → **18.00 × 27.00 sketch 单位** ✓
          = 它插的孔 `col31→col33`（18 ✓）与 `rowE→rowF`（27 ✓）
          ⇒ **两个方向各自独立算出 1.2500** ✓✓ ⇒ 规则成立 ✓（板子与零件**同一条规则** ✓，板子不是特例 ✓）。
      · **无单位 = 1/1000 英寸 = 0.0254 mm** ✓。
      ✗ 作废的错法：`px`/无单位一律 0.09 ✗（⇒ 板子小 14 倍 ✗ / LED2 变"一粒米" ✗）；
        "有 viewBox 就算 90dpi" ✗（⇒ 板子 132mm ✗、小 20% ✗ ⇒ 底部 X/W 两条轨落到板外 ✗）。
      ✗ 我为什么会算错 ✓：把焊盘组的 `translate` 之差（34.035→234.035 = **200** ✓）当成脚距 ✗，
        而组内 `<rect x>` 是 −31.584→−217.184（差 **−186** ✓）⇒ **两个大数互抵**，真脚距只有
        **14.401** ✓ —— 教训：**动 svg 前必须把 transform 链真算出来** ✓（`part_box.pin_points` ✓
        一份实现 ✓），别拿"相邻两个数字之差"当几何 ✗。
    """
    head = re.search(r"<svg\b[^>]*>", svg_text, flags=re.S)
    if not head:
        print("      [!] 这张 svg 连 `<svg>` 头都没有 ✗")
        return 1.0
    h = head.group(0)
    m = re.search(r'width="([\d.]+)\s*(mm|cm|in|px|pt)?"', h)
    if not m:
        print("      [!] 这张 svg 连 width 都没有 ⇒ 只能按「用户单位＝sketch 单位」画 ✗")
        return 1.0
    v = float(m.group(1))
    u = m.group(2) or ""
    umm = UNIT_MM.get(u)
    if umm is None:
        print("      [!] 没见过的单位 `%s` ⇒ 按**无单位**（1/1000in）画 ✗" % u)
        umm = UNIT_MM[""]
    vb = re.search(r'viewBox="([^"]+)"', h)
    if not vb:
        return umm * SK                          # 没有 viewBox ⇒ 用户单位本身就是长度 ✓
    parts = [float(x) for x in re.split(r"[ ,]+", vb.group(1).strip()) if x]
    if len(parts) != 4 or not parts[2]:
        return umm * SK
    return v * umm * SK / parts[2]               # ★ **唯一**的规则 ✓


def vb_origin(svg_text):
    """`viewBox` 的 **(min-x, min-y)** ✓；没有 ⇒ (0, 0) ✓

    ★★ 为什么要它 ✓（2026-09-27 **机验钉死** ✓）：`viewBox` 的 min-x/min-y 是**视口原点** ✓
      ⇒ `sketch = loc + M·(k·(用户坐标 − 原点))` ✓ ⇒ **必须减** ✓。
      证据 ✓（不是推理 ✗）：`LED2` 的 `viewBox="1.03 0 19.54 28.8"` ⇒ 4 个脚**一律**
      偏 `+1.29 单位 = 1.03 × 1.25` ✓✓（x 偏 / y 不偏 ✓ = min-y 为 0 ✓）；减掉后 Δ=0.00 ✓✓。
    """
    m = re.search(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)', svg_text or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


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
    if key in svg_cache:
        # ★★ 2026-09-27 修 ✓：命中缓存时**也要把"用了哪个文件"带出来** ✓ ——
        #   上一版这里直接 `return` ✗ ⇒ 第二个实例（C1 与 C2 同件 ✓、J1 与 J2 同件 ✓）
        #   会打成"用了（**找不到** ✗）"✗ ⇒ **报告在说谎** ✗（文件其实取到了 ✓）。
        #   我自己的规矩：**不许有会误导的输出** ✓ ⇒ 缓存里连"出处"一起存 ✓。
        LAST_PICK[0] = svg_cache[key][1]
        return svg_cache[key][0]
    LAST_PICK[0] = None
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
    svg_cache[key] = (txt, LAST_PICK[0])      # ★ 连"出处"一起缓存 ✓（上面命中时要报 ✓）
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
    _ox, _oy = vb_origin(txt)        # ★ viewBox 原点**必须减** ✓（证据见下面 matrix 那段 ✓）
    _subx = m[0] * k * _ox + m[2] * k * _oy
    _suby = m[1] * k * _ox + m[3] * k * _oy
    # ★★ 交叉验算 ✓（2026-09-27 ✓）：**面包板**（几百个圆 ✓）**声明的宽**必须 ≈ 孔阵宽 ✓
    #   `468.238 × 1/72in = 165.2mm` ✓ ≈ 孔阵 `576 单位 = 162.6mm` ✓（差 9 单位 = 端部留边 ✓）
    #   ⇒ `scale_of` 那条规则**由板子自己验过** ✓（不再需要"圆多就强制 72dpi"那种特例 ✗）。
    if len(re.findall(r"<circle", txt)) >= 100:
        _m2 = re.search(r'width="([\d.]+)\s*(mm|cm|in|px|pt)?"', txt)
        if _m2:
            _wmm = float(_m2.group(1)) * k / SK        # 声明值 × 每用户单位 mm ✓
            print("   %-6s **板子对账** ✓：声明宽 %s%s = **%.1f mm** ↔ 孔阵 576 单位 = 162.6mm ⇒ %s"
                  % (ttl, _m2.group(1), _m2.group(2) or "(无单位)", _wmm,
                     "✓ 对得上 ✓" if 150.0 < _wmm < 180.0 else "✗ **对不上** ✗"))
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
    # ★★★ 2026-09-27 **修** ✓（用户报"preview 是错的"✗，而 Fritzing 里 LED2 位置正确 ✓）：
    #   脚位**参考点**必须走完 svg 的祖先 `transform` 链 ✓ —— 上一版只认 `<circle>` 且直接用
    #   `cx/cy` ✗ ⇒ ① 焊盘画在 `<rect>` 里的件（LED2/J1/J2/L1/C1/C2/R1 ✓）**一个都查不到** ✗
    #   ⇒ 全报"未验证"✗；② 就算查得到，忽略 `translate` 组也会得到**假坐标** ✗。
    #   现在统一用 `part_box.pin_points` ✓（**一份实现** ✓，与算本体包围盒同一套矩阵数学 ✓）。
    _pts, _badref = {}, []
    try:
        _pts, _badref = PB.pin_points(ET.fromstring(txt))
    except Exception as _ex:       # ★ 有些 svg 带 DOCTYPE 实体 ⇒ 解析不了也要**明说** ✓（不静默 ✗）
        _badref = ["<XML 解析不了：%s>" % _ex]
    _nchk = _bad = 0
    _unv = 0
    _maxd = 0.0                    # ★ 最大 Δ 也要报 ✓（"✓"必须带数字 ✓，不是口号 ✓）
    for _cid2, _hid2 in sorted(_ph.items()):
        _p2 = _pts.get("%spin" % _cid2)
        _xy2 = BC.hole_xy(_hid2) if _hid2 else None
        if _p2 is None or _xy2 is None:
            _unv += 1
            continue               # ★ 认不出 ⇒ **记入"未验证"** ✓（不许静默跳过 ✗）
        _nchk += 1
        _lu, _lv = _p2[0] * k, _p2[1] * k
        _padx = num(g.get("x")) + m[0] * _lu + m[2] * _lv + m[4] - _subx
        _pady = num(g.get("y")) + m[1] * _lu + m[3] * _lv + m[5] - _suby
        _dx, _dy = _padx - _xy2[0], _pady - _xy2[1]
        _dd = (_dx * _dx + _dy * _dy) ** 0.5
        _maxd = max(_maxd, _dd)
        # ★★ 阈值收紧到 **0.3 单位（0.08mm）** ✓（2026-09-27 ✓）：原来 1.0 ✗ ⇒ LED2 那种
        #   **1.29 单位**的错**差点漏掉** ✗（只超出 29% ✗）。**对的件实测 Δ=0.00** ✓
        #   （U1/D3/J1/J2/L1 ✓）⇒ 阈值可以贴地 ✓；"差一点点"在这里是**可算**的，不该给宽容 ✗。
        if _dd > 0.3:
            _bad += 1
            print("      ✗ 脚 %-16s 画在 (%7.1f,%7.1f)，孔 %-8s 在 (%7.1f,%7.1f)"
                  " ⇒ Δ=%.2f 单位 (%.2f mm) **悬空** ✗"
                  % (_cid2, _padx, _pady, _hid2, _xy2[0], _xy2[1], _dd, _dd * 25.4 / 90.0))
    if _nchk or _unv:
        _verdict = ("✓ 全落在孔上 ✓（最大 Δ=%.2f 单位）" % _maxd if not _bad else
                    "✗ **%d 个悬空** ✗（最大 Δ=%.2f 单位）" % (_bad, _maxd)) \
            if _nchk else "**一个都没查到 ⇒ 未验证 ✗（别当它是对的 ✗）**"
        print("      脚位自检：查到 %d 个脚 ⇒ %s ｜认不出/未验证 %d 个 %s"
              % (_nchk, _verdict, _unv, "✓" if not _unv else "✗（这些件只能靠人眼 ✓）"))
    if _badref:
        print("      ⚠ 参考点没能算出来的：%s" % "；".join(_badref[:6]))
    a, b, c, d = k * m[0], k * m[1], k * m[2], k * m[3]
    e, f = num(g.get("x")) + m[4] - _subx, num(g.get("y")) + m[5] - _suby
    # ★★★ 2026-09-27 **证据推翻了我昨天的"撤掉"** ✗✓：**viewBox 的原点必须减** ✓ ——
    #   早先我把 `translate(-minX,-minY)` 撤了 ✗，理由是"这只是坐标重映射、不是摆视口" ✗ ——**错** ✓。
    #   硬证据 ✓（机验 ✓，不是推理 ✗）：`LED2` 的 `viewBox="1.03 0 …"` ⇒ 四个脚**一律**偏
    #   **+1.29 单位 = 1.03 × 1.25** ✓✓（x 偏、y 不偏 ✓ = min-y 为 0 ✓）—— 偏移量与 `min×k`
    #   **逐位相符** ✓ ⇒ 真凶就是它 ✓；减掉后四脚 Δ=0.00 ✓✓。
    #   ★ 判据：**偏移量必须等于 min×k** ✓（"差一点点"在这里是**可算**的 ✓，不是审美 ✗）。
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
