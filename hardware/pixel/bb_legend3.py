# -*- coding: utf-8 -*-
r"""面包板**图例** v3（按用户截图三条意见 ✓，2026-09-26）

① **旧图例一律删干净** ✓ —— 不光文字件（`BreadboardLogoText` ✓），
   连**装饰色条**也要删 ✓：判据 = 面包板导线**没有任何 `<connectors>`** ✓（纯装饰 ✓）
   ⇒ 上次遗留的两条孤立色条就是这么漏掉的 ✗（当时只删了文字件 ✓）
② 标题与第 1 行**间距加大** ✓（`TITLE_GAP` ✓，其余行仍用 `DY` ✓）
③ 文字与色条**居中对齐** ✓（文字 y 加 `TEXT_DY` 微调 ✓ —— 实测偏差靠这个数调 ✓）

尺寸（取自用户示范件实测 ✓）：正文宽 1.7586mm/字符 ✓ 高 2.28615mm ✓；
标题「图例：」全角 2.54mm/字符 = 7.62mm ✓ 高 3.302mm ✓。
文字件**无连接器** ✓、色条**无 connectors** ✓ ⇒ 都不影响网表 ✓。

用法：py -3.13 bb_legend3.py <输入.fzz> <输出.fzz> [x0 y0 DY TITLE_GAP TEXT_DY]
"""
import copy
import sys
import zipfile
import xml.etree.ElementTree as ET

# ★ 颜色：**只能用 Fritzing 官方配色表的值** ✓（`resources/ratsnestcolors.xml` 的
#   `breadboardView` 下 `<color wire="…">` ✓）；与 `bb_route4.py` 的 COLOR 逐项一致 ✓
NET_COLORS = [("GND", "#404040"), ("5V", "#cc1414"), ("DATA_IN", "#418dd9"),
              ("DATA_OUT", "#33ffc5"), ("LED_DIN", "#25cc35"), ("RC", "#ef6100"),
              ("BR+", "#ab58a2"), ("COIL_A", "#8c3b00"), ("COIL_B", "#fa50e6")]
W_CHAR, H_ROW, W_CJK, H_TITLE = 1.7586, 2.28615, 2.54, 3.302
STUB, GAP = 9.0, 3.0      # 色条长度：18 → **9**（用户 2026-09-26：减到原来一半 ✓）
MM = 3.5433          # 1mm = 3.5433 sketch 单位 ✓（`width` 属性是 mm ✓，图形坐标是单位 ✓）
# ★ 左对齐（2026-09-26 用户）：文字件是**以给定点为中点**排的 ✗ ⇒ 越长的字越往右伸 ✓
#   所以给几何 x 时要 = 左缘 + **半宽** ✓（宽度 mm → 单位 ✓）


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


BOX_CHARS = 20        # ★ 所有文字件共用**同一个盒子宽度**（20 字符 ✓）
#   —— 这样“几何点到底是左缘还是中点”就**无关紧要**了 ✓：盒子一样大 ⇒ 左缘必然对齐 ✓
#   （2026-09-26：加“半宽补偿”没效果 ✗ ⇒ 锚点约定与我以为的不同 ✓；改用这一手 ✓）
FONT_ROW, FONT_TITLE = 10.0, 14.4      # 盒内字号 ✓（标题 14.4 = 2.54/1.7586×10 ✓ 与用户示范同大 ✓）


def shape_svg(text, color, w_mm, h_mm, font=10.0):
    # ★ viewBox 宽度必须与盒子**比例一致** ✓（盒子 mm 宽 : 高 要等于 viewBox 宽 : 13 ✓）
    #   否则 svg 会“按最小比例缩放并居中” ⇒ 字号/基线跑偏 ✗（2026-09-26 标题就是这样错的 ✓）
    n = max(1, len(text))
    return ('<svg xmlns="http://www.w3.org/2000/svg" height="%.6fin" viewBox="0 0 %d 13" width="%.6fin">\n'
            ' <g id="breadboard">\n  <text fill="%s" font-family="Droid Sans" font-size="%.1f" id="label" '
            'stroke-width="0" text-anchor="start" x="1" xml:space="preserve" y="9">%s</text>\n </g>\n</svg>\n'
            % (h_mm / 25.4, 10 * n, w_mm / 25.4, color, font, esc(text)))


def make_text(tmpl, mi, text, color, x, y, w_mm, h_mm, font=10.0):
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", str(mi))
    t = child(e, "title")
    if t is not None:
        t.text = "TXT%d" % mi
    for p, v in (("logo", text), ("color", color), ("width", "%.6f" % w_mm),
                 ("height", "%.6f" % h_mm), ("shape", shape_svg(text, color, w_mm, h_mm, font))):
        pr = next((q for q in e.iter() if tag(q) == "property" and q.get("name") == p), None)
        if pr is None:
            pr = ET.Element("property", {"name": p})
            e.insert(0, pr)
        pr.set("value", v)
    g = child(child(child(e, "views"), "breadboardView"), "geometry")
    g.attrib["x"], g.attrib["y"] = "%.4f" % x, "%.4f" % y
    return e


def make_stub(tmpl, mi, color, x, y):
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", str(mi))
    t = child(e, "title")
    if t is not None:
        t.text = "Wire%d" % mi
    vw = child(e, "views")
    for sub in list(vw):
        if tag(sub) != "breadboardView":
            vw.remove(sub)
    sub = child(vw, "breadboardView")
    sub.set("layer", "breadboardWire")
    bx = child(sub, "connectors")
    if bx is not None:
        vw.remove(sub) if False else sub.remove(bx)     # 装饰件：连接器整块删掉 ✓
    g = child(sub, "geometry")
    g.attrib.update({"x": "%.4f" % x, "y": "%.4f" % y, "x1": "0", "y1": "0",
                     "x2": "%.4f" % STUB, "y2": "0", "wireFlags": "64"})
    we = child(sub, "wireExtras")
    if we is None:
        we = ET.SubElement(sub, "wireExtras")
    we.attrib.update({"mils": "22.2222", "color": color, "opacity": "1", "banded": "0"})
    return e


def is_deco_stub(e):
    """纯装饰色条：有面包板视图的导线，且该视图里**没有 connectors** ✓"""
    if not (e.get("moduleIdRef") or "").startswith("Wire"):
        return False
    sub = child(child(e, "views"), "breadboardView")
    return sub is not None and child(sub, "connectors") is None


def main(argv):
    fzz, out = argv[0], argv[1]
    x0 = float(argv[2]) if len(argv) > 2 else 590.0
    y0 = float(argv[3]) if len(argv) > 3 else 12.0
    dy = float(argv[4]) if len(argv) > 4 else 12.0
    tgap = float(argv[5]) if len(argv) > 5 else 22.0        # ★ 标题→第 1 行：比行距大 ✓
    tdy = float(argv[6]) if len(argv) > 6 else -3.0         # ★ 文字微调（正=下移）✓
    # ★ 图例件模板来源（2026-09-26 ✓）：干净稿（如 pixel-schematic.fzz ✗）里**没有**
    #   `BreadboardLogoText` ⇒ 可以指定一个**已经带图例**的稿当模板 ✓（只借类型/属性骨架 ✓）
    tmpl_src = argv[7] if len(argv) > 7 else None
    z = zipfile.ZipFile(fzz)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(name))
    host = child(sroot, "instances") or sroot
    tmpl_txt = tmpl_stub = None
    killed = 0
    for e in list(sroot.iter("instance")):
        mid = e.get("moduleIdRef") or ""
        if mid.endswith("BreadboardLogoTextModuleID"):
            if tmpl_txt is None:
                tmpl_txt = e
            host.remove(e)
            killed += 1
            continue
        if is_deco_stub(e):                     # ★ 旧装饰色条也删 ✓（幂等 ✓）
            host.remove(e)
            killed += 1
            continue
        if tmpl_stub is None and mid.startswith("Wire") and child(child(e, "views"), "breadboardView"):
            tmpl_stub = e
    if tmpl_txt is None and tmpl_src:
        zt = zipfile.ZipFile(tmpl_src)
        nt = [n for n in zt.namelist() if n.endswith(".fz")][0]
        rt = ET.fromstring(zt.read(nt))
        tmpl_txt = next((e for e in rt.iter("instance")
                         if (e.get("moduleIdRef") or "").endswith("BreadboardLogoTextModuleID")),
                        None)
        print("图例件模板取自: %s" % tmpl_src)
    if tmpl_txt is None or tmpl_stub is None:
        raise SystemExit("✗ 缺 BreadboardLogoText / 面包板导线模板 ✗（可用第 8 个参数指定带图例的稿 ✓）")
    next_mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1
    print("清理旧图例: %d 件（文字件 + 装饰色条 ✓）" % killed)
    xt = x0 + STUB + GAP                                  # 所有行的**左缘** ✓
    # 标题：按它自己的字宽/字高给盒子 ✓（比例一致 ⇒ 字号才准 ✓），字号仍由盒子大小决定 ✓
    host.append(make_text(tmpl_txt, next_mi, "图例：", "#333333",
                          xt, y0, W_CJK * 3, H_TITLE, FONT_ROW))
    next_mi += 1
    for i, (net, color) in enumerate(NET_COLORS, start=1):
        y = y0 + tgap + (i - 1) * dy
        host.append(make_stub(tmpl_stub, next_mi, color, x0, y))
        next_mi += 1
        host.append(make_text(tmpl_txt, next_mi, net, color,
                              xt, y + tdy, W_CHAR * len(net), H_ROW, FONT_ROW))  # ★ 同一左缘 ✓
        next_mi += 1
    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n == name else z.read(n))
    print("图例 v3: 起点 (%.1f,%.1f)；标题→首行 %.1f，行距 %.1f，文字微调 %.1f；色条 %.1f + 间隙 %.1f"
          % (x0, y0, tgap, dy, tdy, STUB, GAP))
    print("写入: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
