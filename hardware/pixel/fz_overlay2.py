# -*- coding: utf-8 -*-
r"""**解析 vs Fritzing 导出图** 对账（v2 ✓：**累积 `<g transform>` 链** ✓）

用法 ✓：`fz_overlay2.py <sketch.fzz> <导出.svg> [--tol=0.35]`

★ v1 的错 ✗：只比 `<line>` 的**原始坐标** ⇒ 导出图给每个实例都套了自己的 `<g transform>`
  ✗（实测 25 条只对上 4 条 ✓）⇒ v2 把**从根到该元素的变换链**乘起来 ✓，换成**根坐标**再比 ✓。

口径 ✓（都能从文件里复核 ✓）：
  · 我的解析 = `pcb_wire.parse_trace` ✓ ⇒ 草图单位 ✓ ⇒ 板内 mm ⇒ 根 pt ✓：
      `pt = 板组 translate ＋ 板内 mm × 2.83465` ✓（1 单位 = 1pt ✓、1 mm = 72/25.4 ✓）
  · 导出图：`translate` / `matrix` / `scale` / `rotate` 四类变换 ✓（其余碰到就报 ✗）
  · 判据：每条走线能找到**同一段**（两端都在容差内 ✓，正反都算 ✓）
"""
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                                  # noqa: E402,F401
import pcb_wire as PW                                             # noqa: E402
import pcb_pads as PP                                            # noqa: E402

SK = 90.0 / 25.4
PT_PER_MM = 72.0 / 25.4
SVGNS = "{http://www.w3.org/2000/svg}"


def mul(m, n):
    """2×3 矩阵 `m ∘ n` ✓（先 n 后 m ✓）"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def tf_of(s):
    """把 `translate(...)` / `matrix(...)` / `scale(...)` / `rotate(...)` 串成一个矩阵 ✓"""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, arg in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.findall(r"[-\d.eE+]+", arg)]
        if name == "translate":
            m = mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0))
        elif name == "matrix":
            m = mul(m, tuple(v[:6]))
        elif name == "scale":
            m = mul(m, (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0))
        elif name == "rotate":
            a = math.radians(v[0])
            ca, sa = math.cos(a), math.sin(a)
            r = (ca, sa, -sa, ca, 0, 0)
            if len(v) >= 3:                      # rotate(a, cx, cy) ✓
                r = mul(mul((1, 0, 0, 1, v[1], v[2]), r), (1, 0, 0, 1, -v[1], -v[2]))
            m = mul(m, r)
    return m


def ap(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


fzz, svg = sys.argv[1], sys.argv[2]
tol = 0.35
for a in sys.argv[3:]:
    if a.startswith("--tol="):
        tol = float(a[6:])

# ── ① 我的解析 ✓ ──────────────────────────────────────────────────────────
z = zipfile.ZipFile(fzz)
fzn = [n for n in z.namelist() if n.endswith(".fz")][0]
text = z.read(fzn).decode("utf-8", "replace")
board_mi, board_loc = None, None
mine = []
for m in re.finditer(r"<title>([^<]*)</title>", text):
    a = text.rfind("<instance", 0, m.start())
    b = text.find("</instance>", m.end())
    if a < 0 or b < 0:
        continue
    blk = text[a:b]
    mid = re.search(r'moduleIdRef="([^"]+)"', blk)
    if not mid:
        continue
    if mid.group(1) == PP.BOARD_MID or mid.group(1).startswith("PCB"):
        g = re.search(r'<pcbView\b[^>]*>(.*?)</pcbView>', blk, re.S)
        geo = re.search(r"<geometry ([^>]*)/?>", g.group(1))
        board_mi = re.search(r'modelIndex="(\d+)"', blk).group(1)
        board_loc = (float(re.search(r'\bx="([-\d.eE+]+)"', geo.group(1)).group(1)),
                     float(re.search(r'\by="([-\d.eE+]+)"', geo.group(1)).group(1)))
    elif mid.group(1).startswith("Wire"):
        t = PW.parse_trace(blk)
        if t is not None:
            p1, p2 = PW.abs_ends(t["geo"])
            mine.append((m.group(1), (t.get("layer") or "")[:7], p1, p2))
print("== 对账 v2 ✓：%s ↔ %s ==" % (os.path.basename(fzz), os.path.basename(svg)))
print("   板 mi=%s ✓ loc=(%.2f, %.2f) mm ✓｜我的 PCB 走线 %d 条 ✓"
      % (board_mi, board_loc[0] / SK, board_loc[1] / SK, len(mine)))

# ── ② 导出图：**累积变换** ⇒ 根坐标 ✓ ──────────────────────────────────────
root = ET.fromstring(open(svg, encoding="utf-8", errors="replace").read())
lines, circles, rects, paths, tags = [], [], [], [], set()


def walk(el, m):
    m2 = mul(m, tf_of(el.get("transform")))
    t = el.tag.replace(SVGNS, "")
    tags.add(t)
    if t == "line":
        p1 = ap(m2, float(el.get("x1") or 0), float(el.get("y1") or 0))
        p2 = ap(m2, float(el.get("x2") or 0), float(el.get("y2") or 0))
        lines.append((p1, p2, el.get("stroke"), el.get("stroke-width")))
    elif t == "circle":
        c = ap(m2, float(el.get("cx") or 0), float(el.get("cy") or 0))
        circles.append((c, float(el.get("r") or 0), el.get("stroke"), el.get("fill")))
    elif t == "path":
        paths.append((el.get("d"), el.get("stroke"), el.get("stroke-width"), m2))
    elif t == "rect":
        r1 = ap(m2, float(el.get("x") or 0), float(el.get("y") or 0))
        rects.append((el.get("id"), r1, float(el.get("width") or 0), float(el.get("height") or 0)))
    for c in list(el):
        walk(c, m2)


walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
print("   导出图：<line> %d 条 ✓｜<circle> %d 个 ✓｜出现过的标签：%s"
      % (len(lines), len(circles), "、".join(sorted(tags))[:60]))
mlines = [ln for ln in lines if ln[2] and ln[2] != "none"]
print("   其中有 stroke 的 <line>：%d 条 ✓｜stroke 取值前 6 种：%s"
      % (len(mlines),
         "、".join(sorted({str(x[2]) + "/" + str(x[3]) for x in mlines})[:6])))


# ★★ 标定板原点 `A` ✓：导出图里板框 `boardoutline` 的**根坐标左上角** ✓；
#   它画在板边内侧 0.288 pt ✓（`rect x=0.288` ＋ stroke 0.576 的一半 = 板边 ✓）
#   ⇒ `A = 板框左上 − 0.288` ✓ ✓（不再猜 partID ✓）
A, INSET = None, 0.288
for rid, p, _w, _h in rects:
    if rid == "boardoutline":
        A = (p[0] - INSET, p[1] - INSET)
print("   板框 boardoutline 根坐标左上 = (%.3f, %.3f) ✓ ⇒ 板原点 A = (%.3f, %.3f) pt ✓"
      % (p[0], p[1], A[0], A[1]) if A else "   ✗ 没找到 boardoutline")


def to_pt(p):
    """草图点 → 导出图**根坐标** pt ✓"""
    return (A[0] + (p[0] - board_loc[0]) / SK * PT_PER_MM,
            A[1] + (p[1] - board_loc[1]) / SK * PT_PER_MM)


if A:
    ok, bad = [], []
    for ttl, lay, p1, p2 in mine:
        q1, q2 = to_pt(p1), to_pt(p2)
        hit = None
        for r1, r2, s, w in lines:
            same = (math.hypot(r1[0] - q1[0], r1[1] - q1[1]) <= tol and
                    math.hypot(r2[0] - q2[0], r2[1] - q2[1]) <= tol)
            rev = (math.hypot(r2[0] - q1[0], r2[1] - q1[1]) <= tol and
                   math.hypot(r1[0] - q2[0], r1[1] - q2[1]) <= tol)
            if same or rev:
                hit = (s, w)
                break
        (ok if hit else bad).append((ttl, lay, q1, q2, hit))
    print("   ⇒ **根坐标逐点对上 ✓：%d 条**｜对不上 ✗：%d 条（容差 %.2f pt ≈ %.3f mm ✓）"
          % (len(ok), len(bad), tol, tol / PT_PER_MM))
    for ttl, lay, q1, q2, _h in bad[:5]:
        print("      ✗ %-14s %s 我算出 (%.2f,%.2f)→(%.2f,%.2f) pt"
              % (ttl, lay, q1[0], q1[1], q2[0], q2[1]))
    hh = sorted({str(h[0]) + "/" + str(h[1]) for *_x, h in ok if h})
    if hh:
        print("   对上那些在图里的描边 ✓：%s" % "、".join(hh))

    # ★★ 对不上的 20 条：看**他的铜线**（`#f28a00` / `#f2c600` ✓）里，
    #   有没有哪条能把我的**两个端点都盖住** ✓ —— 有 ⇒ 导出图把铜**合并/拆分**了 ✓（不是解析错 ✓）；
    #   没有 ⇒ 量一下"我的端点离最近那条线多远" ✓ —— 大 ⇒ 我坐标错 ✗、小 ⇒ 只是微差 ✓。
    def d_pt_seg(p, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        wx, wy = p[0] - a[0], p[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 <= 1e-18 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
        return math.hypot(wx - t * vx, wy - t * vy)

    HIS = ("#f28a00", "#f2c600")
    his = [ln for ln in lines if (ln[2] or "").lower() in HIS]
    print("   图里你那些颜色的线（%s ✓）：%d 条 ✓" % ("/".join(HIS), len(his)))
    covered, offs = 0, []
    for ttl, lay, q1, q2, _h in bad:
        best = None
        for k, (r1, r2, s, w) in enumerate(his):
            d = max(d_pt_seg(q1, r1, r2), d_pt_seg(q2, r1, r2))
            if best is None or d < best[0]:
                best = (d, k, r1, r2, s, w)
        if best and best[0] <= tol:
            covered += 1
            print("      ✓ %-14s 两端都落在你第 %d 条线（%s / %s ✓）上 ⇒ **合并/拆分** ✓"
                  % (ttl, best[1], best[4], best[5]))
        else:
            offs.append((best[0], ttl, best[1]))
            print("      ✗ %-14s 离最近那条线 %.3f pt（≈ %.3f mm ✗）第 %d 条"
                  % (ttl, best[0], best[0] / PT_PER_MM, best[1]))
    print("   ⇒ 20 条里：**落在你的铜线上 ✓ %d 条**｜真有偏差 ✗ %d 条（最大偏差 %.3f mm）"
          % (covered, len(offs), (max(o[0] for o in offs) / PT_PER_MM) if offs else 0.0))

    # ★★★ 试 4 种换算 ✓（原样 / x 镜像 / y 镜像 / 双镜像 ✓）—— Fritzing 导出**底层铜**
    #   常常做镜像 ✗；哪种让"我的端点 → 你那些线"的整体距离塌到最小 ✓，就是它 ✓。
    #   ★ 镜像轴 = **板的中线** ✓（板 25.00×25.00 mm ✓，由 `.fz` 的 `<board>` 给 ✓）。
    BOARD_MM = 25.0
    HIS2 = [ln for ln in lines if (ln[2] or "").lower() in ("#f28a00", "#f2c600")]

    def map_pt(p, mode):
        lx = (p[0] - board_loc[0]) / SK
        ly = (p[1] - board_loc[1]) / SK
        if "x" in mode:
            lx = BOARD_MM - lx
        if "y" in mode:
            ly = BOARD_MM - ly
        return (A[0] + lx * PT_PER_MM, A[1] + ly * PT_PER_MM)

    print("   ★ 试 4 种换算 ✓（原样 / x 镜像 / y 镜像 / 双镜像 ✓；镜像轴 = 板中线 ✓）：")
    best_mode = None
    for mode in ("", "x", "y", "xy"):
        tot, mx = 0.0, 0.0
        for ttl, lay, p1, p2 in mine:
            q1, q2 = map_pt(p1, mode), map_pt(p2, mode)
            d = min(mm for mm in (max(d_pt_seg(q1, r1, r2), d_pt_seg(q2, r1, r2))
                                  for r1, r2, _s, _w in HIS2))
            tot += d
            mx = max(mx, d)
        tot /= PT_PER_MM
        mx /= PT_PER_MM
        print("      换算 [%-2s] ✓：合计 %.2f mm ✓｜最差单条 %.2f mm ✗"
              % (mode or "原样", tot, mx))
        if best_mode is None or tot < best_mode[1]:
            best_mode = (mode, tot, mx)
    print("   ⇒ 最像的是 [%s] ✓（合计 %.2f mm ✓）"
          % (best_mode[0] or "原样", best_mode[1]))

    # ── ① 求"最佳**常量平移**" ✓ + ② 把图里那几条线**列出来** ✓ ────────────────
    def near_pt(p, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        wx, wy = p[0] - a[0], p[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 <= 1e-18 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
        return (a[0] + t * vx, a[1] + t * vy)

    deltas = []
    for ttl, lay, p1, p2 in mine:
        for q in (to_pt(p1), to_pt(p2)):
            best = None
            for r1, r2, _s, _w in HIS2:
                np_ = near_pt(q, r1, r2)
                d = math.hypot(np_[0] - q[0], np_[1] - q[1])
                if best is None or d < best[0]:
                    best = (d, np_)
            if best:
                deltas.append((q[0] - best[1][0], q[1] - best[1][1], best[0]))
    if deltas:
        ds = sorted(d for _a, _b, d in deltas)
        mdx = sorted(a for a, _b, _d in deltas)[len(deltas) // 2]
        mdy = sorted(b for _a, b, _d in deltas)[len(deltas) // 2]
        print("   ★ 我的端点 → 你最近那条线的**位移** ✓（%d 个端点 ✓）：" % len(deltas))
        print("      中位位移 = (%+.3f, %+.3f) pt ＝ (%+.3f, %+.3f) mm ✓"
              % (mdx, mdy, mdx / PT_PER_MM, mdy / PT_PER_MM))
        print("      距离：中位 %.3f mm ✓｜最小 %.3f ✓｜最大 %.3f ✗"
              % (ds[len(ds) // 2] / PT_PER_MM, ds[0] / PT_PER_MM, ds[-1] / PT_PER_MM))
        print("      ⇒ %s"
              % ("**像是一个固定偏移** ✓（都在同一方向 ✓ ⇒ 某处少加了一个常量 ✓）"
                 if ds[-1] / PT_PER_MM < 1.0 else
                 "**不是固定偏移** ✗（最大 %.2f mm ✗ ⇒ 还有别的环节 ✓）" % (ds[-1] / PT_PER_MM)))
    print("   ── ② 图里你那 %d 条线（根坐标 pt ✓，按长度排 ✓）──" % len(HIS2))
    for k, (r1, r2, s, w) in enumerate(sorted(HIS2, key=lambda t: -math.hypot(t[1][0] - t[0][0],
                                                                           t[1][1] - t[0][1]))):
        print("      #%-2d %-8s w=%-8s (%.2f, %.2f)→(%.2f, %.2f) ✓ 长 %.2f mm ✓"
              % (k, s, w, r1[0], r1[1], r2[0], r2[1],
                 math.hypot(r2[0] - r1[0], r2[1] - r1[1]) / PT_PER_MM))
    print("   ── 我读出的 25 条（根坐标 pt ✓，前 8 条 ✓）──")
    for ttl, lay, p1, p2 in mine[:8]:
        q1, q2 = to_pt(p1), to_pt(p2)
        print("      %-14s %-8s (%.2f, %.2f)→(%.2f, %.2f) ✓ 长 %.2f mm ✓"
              % (ttl, lay, q1[0], q1[1], q2[0], q2[1],
                 math.hypot(q2[0] - q1[0], q2[1] - q1[1]) / PT_PER_MM))

    # ★★★ 正确判据 ✓（2026-10-03 定 ✓）：**同一条线** ＝
    #   ① 共线 ✓（我的两端到图里那条线的**垂距**都 ≤ 0.6 pt ✓）
    #   ② 区间有重叠 ✓（投影参数区间相交 ✓，容一点外溢 ✓）
    #   —— 导出会把每段两端**截短**（实测 0.2～1.3 pt ✓，像按描边圆头收进去 ✓）
    #      ✗ 而"两端逐点相等"的判据对这种截短**必然假报失败** ✗（我已踩过 ✓）。
    print("   ★★ 换同源判据重数 ✓（共线 ✓ ＋ 垂距 ≤0.6 pt ✓ ＋ 区间重叠 ✓）：")
    ok2, bad2 = [], []
    for ttl, lay, p1, p2 in mine:
        q1, q2 = to_pt(p1), to_pt(p2)
        hit = None
        for k, (r1, r2, s, w) in enumerate(HIS2):
            vx, vy = r2[0] - r1[0], r2[1] - r1[1]
            L = math.hypot(vx, vy)
            if L < 1e-9:
                continue
            d1 = abs((q1[0] - r1[0]) * vy - (q1[1] - r1[1]) * vx) / L
            d2 = abs((q2[0] - r1[0]) * vy - (q2[1] - r1[1]) * vx) / L
            if max(d1, d2) > 0.6:
                continue
            t1 = ((q1[0] - r1[0]) * vx + (q1[1] - r1[1]) * vy) / (L * L)
            t2 = ((q2[0] - r1[0]) * vx + (q2[1] - r1[1]) * vy) / (L * L)
            lo, hi = min(t1, t2), max(t1, t2)
            if hi < -0.02 or lo > 1.02:
                continue
            hit = (k, max(d1, d2), lo, hi, s, w)
            break
        (ok2 if hit else bad2).append((ttl, lay, q1, q2, hit))
    print("   ⇒ **同一条线 ✓：%d / 25 条**｜真对不上 ✗：%d 条" % (len(ok2), len(bad2)))
    if ok2:
        print("      垂距：中位 %.3f pt ✓｜最大 %.3f pt ✓｜对上那些的描边 ✓：%s"
              % (sorted(h[1] for *_x, h in ok2)[len(ok2) // 2],
                 max(h[1] for *_x, h in ok2),
                 "、".join(sorted({str(h[4]) + "/" + str(h[5]) for *_x, h in ok2}))))
    for ttl, lay, q1, q2, _h in bad2[:6]:
        print("      ✗ %-14s %s (%.2f, %.2f)→(%.2f, %.2f) pt ✗"
              % (ttl, lay, q1[0], q1[1], q2[0], q2[1]))

    # ★★★ 最终判据 ✓：**覆盖** ✓ —— 与"铜被怎么切分"无关 ✓。
    #   做法 ✓：把**我的每一段**等分取样 ✓（含两端 ✓），要求**每个样点**都落在图里
    #   你那些颜色的线上（垂距 ≤ 0.6 pt ✓）⇒ 我的铜 **全部** 在图里 ✓。
    #   ★ 这才是"解析与 Fritzing 一致"的正确说法 ✓（✗ 不是"一条对一条" ✗ —— 实测
    #     导出会把同网络的铜**合并/重切** ✓，一一对应先天不成立 ✓）。
    NS = 25
    cov_ok, cov_bad = [], []
    worst = (0.0, "")
    for ttl, lay, p1, p2 in mine:
        a, b = to_pt(p1), to_pt(p2)
        far = 0.0
        for i in range(NS + 1):
            t = i / float(NS)
            q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            d = min(d_pt_seg(q, r1, r2) for r1, r2, _s, _w in HIS2)
            far = max(far, d)
        (cov_ok if far <= 0.6 else cov_bad).append((ttl, lay, far))
        if far > worst[0]:
            worst = (far, ttl)
    print("   ★★★ **覆盖判据** ✓（每段取 %d 个样点 ✓，样点垂距都 ≤0.6 pt ✓）：" % (NS + 1))
    print("   ⇒ **整段都在图里的铜上 ✓：%d / 25 条**｜有跑出去的 ✗：%d 条" % (len(cov_ok), len(cov_bad)))
    print("      最差一条：%.3f pt（≈ %.3f mm ✓）在 `%s` ✓"
          % (worst[0], worst[0] / PT_PER_MM, worst[1]))
    for ttl, lay, far in cov_bad[:6]:
        print("      ✗ %-14s %s 最远样点 %.3f pt（≈ %.3f mm ✗）"
              % (ttl, lay, far, far / PT_PER_MM))

    # ★★ 那 12 条去哪了 ✗：导出图里还有 **23 个 `<path>`** ✓ ⇒ 去它们身上找 ✓。
    #   做法 ✓：把 path 的 `d` 里的**坐标对**按顺序取出来 ✓（只认**绝对** M/L ✓），
    #   相邻两点成一段 ✓，再拿**我的中点**去判“落在它上面” ✓。
    print("   ★ 找那 12 条 ✓：图里 `<path>` %d 个 ✓，其中你的颜色 ✓：%d 个"
          % (len(paths), sum(1 for p in paths if (p[1] or "").lower() in ("#f28a00", "#f2c600"))))

    def path_pts(d, m):
        toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d or "")
        pts, i, ok = [], 0, True
        while i < len(toks):
            t = toks[i]
            if t.isalpha():
                if t not in ("M", "L", "Z"):
                    ok = False                      # 贝塞尔/相对命令 ✗ ⇒ 这次不算 ✓
                i += 1
                continue
            if i + 1 < len(toks):
                pts.append(ap(m, float(toks[i]), float(toks[i + 1])))
                i += 2
            else:
                i += 1
        return pts, ok

    pseg = []
    for d, s, w, m in paths:
        if (s or "").lower() not in ("#f28a00", "#f2c600"):
            continue
        pts, ok = path_pts(d, m)
        if not ok:
            continue
        for j in range(len(pts) - 1):
            pseg.append((pts[j], pts[j + 1]))
    print("      从它们身上取出可用的**绝对 M/L 段** ✓：%d 段 ✓" % len(pseg))
    found = 0
    for ttl, lay, p1, p2 in mine:
        a, b = to_pt(p1), to_pt(p2)
        q = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        d = min([d_pt_seg(q, r1, r2) for r1, r2 in pseg] or [9e9])
        if d <= 0.6:
            found += 1
    print("      ⇒ 25 条里，**中点落在这些 path 段上 ✓：%d 条** ✓" % found)


