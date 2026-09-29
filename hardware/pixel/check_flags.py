# -*- coding: utf-8 -*-
r"""机器守：**有没有导线穿过网标签的旗标** ✓（只读 ✓；退出码非 0 ⇒ 不合格 ✓）

用法：
    py -3.13 check_flags.py <sketch.fzz> [--verbose] [--keep]

★ 它守哪条规则 ✓（用户 2026-09-29 定 ✓）：
  「**标签是一个元件**，跟元件一样，适用不能穿体等规则，要有引线连接」✓ ——
  所以“导线从旗标身上穿过去” ✗ 与“导线穿过元件本体” ✗ 同级，必须为 **0** ✓。

★★ 为什么这份判据要**另写**、不许复用生成器的 ✓（2026-09-29 实测教训 ✓，最重要的一条）：
  ✗ 生成器与渲染器的自检**共用** `sch_net.label_box` ✓ —— 而那个盒子当时返回的是**“板”**
    （= 文字墨迹框 ✓ 4.2 高 ✗），**比看得见的旗标小一圈** ✓（旗标宽 **8.7** ✓）
    ⇒ 红 5V 竖线**正从旗标身上穿过** ✗，而生成器打印的却是 **“违例 0”** ✗✗。
  ⇒ 「**自检不算数**」✓（同 `fritzing-parts-langhua/AGENTS.md` §0 第 ⑦ 条 ✓）：
    判据必须能被**另一个实现**或**人的眼睛**推翻 ✓。
  ⇒ 本文件的判据**不看那个盒子** ✓：直接量**画出来的** `<polygon>` 顶点 ✓
    （用**本文件自己**的线段×多边形求交 ✓，不复用仓里任何几何函数 ✓）。

★ 灵敏度**当场验过** ✓（2026-09-29 ✓，不许只说“能跑” ✗）：
    `_work/v34.fzz`（用户截图点名那版）⇒ **3/4 被穿** ✓✓ —— 正好是“竖着的 `GND` + 两个 `RC`”✓，
    横的那个 `GND` 没穿 ✓ = 与用户当时看到的**完全一致** ✓ ⇒ 判据可信 ✓。
    （当时 `v39` 也报 **1/4** ✓，而渲染器自己的指标同时报 **1 段** ✓ ⇒ 两个独立实现互证 ✓。）

★ 两个坑（都当场露馅 ✓，记下免得再踩 ✓）：
  ① svg 带**默认命名空间** ⇒ `iter("g")` 一个也找不到 ✗ ⇒ 会打印“旗标 0 个”**还判 ✓✓**
     —— **空集当然没违例** ✗（与“自检式瞎”同一类 ✓）⇒ 先**脱命名空间** ✓。
  ② `partID` 写在**外层** `<g>` 上、`<polygon>` 在里层 ✗ ⇒ `partID` 必须**往下传** ✓；
     旗标 `<polygon>` 还带 `<g transform=...>` ✗ 而导线 `<line>` 是**绝对坐标** ✗
     ⇒ 必须**带着变换搬** ✓，否则量到的是错的地方 ✓。

★ 与 `check_labels.py` 的分工 ✓（两件不同的事 ✓）：
  · `check_labels.py` = **几何对不对** ✓（拿 Fritzing 自己导出的 svg 比文字锚点 / 旗标顶点 ✓）；
  · 本文件 = **有没有被穿** ✓（不需要 Fritzing 导出 ✓，随时能跑 ✓）。
"""
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

# 导线色 = **原理图那一节**的官方值 ✓（`fritzing-app/resources/ratsnestcolors.xml`
#   → `<view name="schematicView">` ✓；元件引脚灰 `#787878` 与符号黑 `#000000` 不在此列 ✓）
WIRE_STROKES = {"#404040", "#cc1414", "#418dd9", "#fff800", "#25cc35", "#999999",
                "#ff7300", "#a37911", "#33ffc5", "#ab58a2", "#8c3b00", "#fa50e6"}
_TF = re.compile(r"(matrix|translate|rotate|scale)\s*\(([^)]*)\)")


def mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def parse_tf(t, m=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)):
    """极简变换（自己实现 ✓，SVG 口径 ✓）—— `matrix/translate/rotate/scale` ✓"""
    if not t:
        return m
    for kind, args in _TF.findall(t):
        v = [float(x) for x in re.split(r"[,\s]+", args.strip()) if x]
        if kind == "matrix":
            n = tuple(v)
        elif kind == "translate":
            n = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif kind == "scale":
            s = v[1] if len(v) > 1 else v[0]
            n = (v[0], 0.0, 0.0, s, 0.0, 0.0)
        else:                                     # rotate(a [cx cy]) ✓
            a = math.radians(v[0])
            r = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0.0, 0.0)
            if len(v) >= 3:
                cx, cy = v[1], v[2]
                n = mul(mul((1, 0, 0, 1, cx, cy), r), (1, 0, 0, 1, -cx, -cy))
            else:
                n = r
        m = mul(m, n)
    return m


def ap(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def load(svg):
    """从渲染 svg 里取 (旗标 `[(partID, 顶点…)]`, 导线 `[((x1,y1),(x2,y2),色)]`) ✓"""
    root = ET.parse(svg).getroot()
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    for e in root.iter():                        # ★ 坑① ✓：先脱命名空间 ✓
        if ns and e.tag.startswith(ns):
            e.tag = e.tag[len(ns):]
    flags, lines = [], []

    def walk(el, m, pid0):
        t = el.get("transform")
        m2 = parse_tf(t, m) if t else m
        pid = el.get("partID") or pid0            # ★ 坑② ✓：partID 往下传 ✓
        if el.tag == "polygon" and pid:
            p = [(float(a), float(b)) for a, b in
                 (q.split(",") for q in el.get("points", "").split())]
            flags.append((pid, [ap(m2, x, y) for x, y in p]))
        if el.tag == "line":
            lines.append((ap(m2, float(el.get("x1")), float(el.get("y1"))),
                          ap(m2, float(el.get("x2")), float(el.get("y2"))),
                          (el.get("stroke") or "").lower()))
        for c in list(el):
            walk(c, m2, pid)

    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), "")
    return flags, [ln for ln in lines if ln[2] in WIRE_STROKES]


def seg_x_seg(p, q, r, s):
    """两条线段**真交叉** ✓（端点相碰 / 共线**不算** ✗ —— 标签脚就落在线端上 ✓）"""
    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2 = cr(r, s, p), cr(r, s, q)
    d3, d4 = cr(p, q, r), cr(p, q, s)
    return ((d1 > 1e-9) != (d2 > 1e-9)) and ((d3 > 1e-9) != (d4 > 1e-9))


def seg_x_poly(a, b, poly):
    return any(seg_x_seg(a, b, poly[i], poly[(i + 1) % len(poly)])
               for i in range(len(poly)))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    fzz = argv[0]
    verbose = "--verbose" in argv
    if not os.path.exists(fzz):
        print("✗ 找不到 %s" % fzz)
        return 2
    tmp = os.path.join(HERE, "_work", "_flagcheck.png")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    r = subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(HERE, "render_sch.py"), fzz, tmp],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    svg = os.path.splitext(tmp)[0] + ".svg"
    if r.returncode != 0 or not os.path.exists(svg):
        print("✗ 渲染失败（`render_sch.py` 退出码 %d）✗ —— 先修渲染再判 ✓"
              % r.returncode)
        print((r.stdout or "")[-2000:])
        return 2
    flags, wires = load(svg)
    if not flags:
        print("✗ 渲染出来的 svg 里**一个旗标 `<polygon>` 都没有** ✗ —— "
              "这时候“没违例”是**空的** ✓（先查渲染器 / 换版式 ✗）")
        return 2
    print("== 旗标核对：%s ==" % os.path.basename(fzz))
    print("   旗标 %d 个 ✓｜导线 %d 根 ✓（判据：`<polygon>` 真实顶点 × `<line>` ✓；"
          "**不看** `label_box` ✗）" % (len(flags), len(wires)))
    bad = 0
    for pid, poly in flags:
        hit = [ln for ln in wires if seg_x_poly(ln[0], ln[1], poly)]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        if hit:
            bad += 1
        if hit or verbose:
            print("   %s 旗标 (%.1f,%.1f→%.1f,%.1f) ⇒ 被 **%d** 根线穿过 %s"
                  % (pid, min(xs), min(ys), max(xs), max(ys), len(hit),
                     "✗✗" if hit else "✓"))
            for a, b, col in hit[:6]:
                print("         ✗ %s (%.2f,%.2f)→(%.2f,%.2f)"
                      % (col, a[0], a[1], b[0], b[1]))
    print("⇒ **被穿旗标 %d / %d** %s" % (bad, len(flags), "✗✗" if bad else "✓✓"))
    if "--keep" not in argv:
        for p in (tmp, svg):
            try:
                os.remove(p)
            except OSError:
                pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
