# -*- coding: utf-8 -*-
r"""全接线布线：正交（0°/90°）折线 → 每段一根实体导线 ✓（不再用网标签 ✗）

依据（2026-09-26 从源码 + 用户自己的 sketch 取证 ✓，详见 tools/README.md）：
  · 导线折点：Fritzing **没有**折线导线 ✗ —— 只有「两点直线」✓ 或「两点 + <bezier>」曲线 ✓
    （`items/wire.cpp:856` 调 `m_bezier->write()`；`utils/bezier.cpp:195` 写
     `<bezier><cp0 x y/><cp1 x y/></bezier>`）
    ⇒ **直角拐弯 = 两段导线端点相接** ✓（端点相接即电气相连 ✓）
  · junction **不存文件** ✗，由连接图推出（`wire.cpp:1449` `collectDirectWires`），
    只在 **>2 根线** 交汇处画圆点 ✓ ⇒ 用"两两相连的链"接法就不会出现 junction 点 ✓
  · 连接仍是**连接器级、两端各记一份** ✓

用法：
  py -3.13 f:\git\_scratch\route_build.py <干净画布.fzz> <尺子.svg> <输出.fzz> [--preview 预览.svg]
"""
import copy
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SCRATCH = os.path.dirname(os.path.abspath(__file__))
# ★★ 2026-09-27（用户定 ✓）：通用工具只有一份，在**库仓 tools/** ✓（定位见 `toolpaths.py` ✓）
import toolpaths                                 # noqa: E402
import part_measure as pm                       # noqa: E402
from pin_ruler import apply, mul, parse_tf       # noqa: E402

# ── 网表（照 `hardware/pixel/pixel-netlist.md` §2 ✓；脚名按 .fzp 的连接器名，
#    大小写不敏感 ✓；"#N" = 第 N 个脚（core 件没有名字 ✓））────────────────────────
NETS = {
    "COIL_A":   [("L1", "inner"), ("D3", "AC1")],
    "COIL_B":   [("L1", "outer"), ("D3", "AC2")],
    "GND":      [("D3", "A1"), ("D3", "A2"), ("C1", "#2"), ("U1", "VSS"), ("C2", "#2"),
                 ("LED2", "GND"), ("J1", "#2"), ("J2", "#2"),
     # ★ 裸焊盘/底板必须接地（2026-09-26 用户定 ✓）：原来写成"独立成网、单脚网无线"是错的 ✗
     #   —— EPAD 要**接到 GND** ✓（原理图上就接过来 ✓；元件库里它仍是独立脚 ✓ 见 AGENTS §5 ✓）
                 ("U1", "EPAD")],
    "BR+":      [("D3", "C1"), ("D3", "C2"), ("R1", "#1")],
    "RC":       [("R1", "#2"), ("C1", "#1"), ("U1", "PA1")],
    "5V":       [("U1", "VDD"), ("C2", "#1"), ("LED2", "VDD"), ("J1", "#1"), ("J2", "#1")],
    "DATA_IN":  [("U1", "PA2"), ("J1", "#3")],
    "DATA_OUT": [("U1", "PD0"), ("J2", "#3")],
    "LED_DIN":  [("U1", "PC6"), ("LED2", "DI")],
}


def build_ruler(svg):
    r"""从 Fritzing 导出的 SVG 建"尺子"：partID → {绘图原点, 各脚坐标}（导出坐标 ✓）

    注：这套坐标只用于**元件内部**的相对量取 ✓；跨元件的绝对换算必须用 recal_pins.py
    从渲染反推的全局映射 ✗（2026-09-26 踩坑：逐元件公式跨元件不成立 ✓）。
    """
    root = ET.parse(svg).getroot()
    ruler = {}

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("partID"):
            pid = el.get("partID")
            ruler.setdefault(pid, {"origin": None, "pins": {}})
        if pid in ruler and el.get("id") == "schematic" and ruler[pid]["origin"] is None:
            ruler[pid]["origin"] = apply(m2, 0, 0)
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm and pid in ruler and el.get("x") is not None:
            ruler[pid]["pins"].setdefault("connector" + mm.group(1),
                                          apply(m2, float(el.get("x")), float(el.get("y"))))
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)
    return ruler

RATIO = 1.25
CLEAR = 6.0            # 导线离元件本体至少留这么远（sketch 单位；6 ≈ 1.7mm ✓）
CH_OFFS = (CLEAR, 12.0, 22.0, 34.0)

# ★ 标定过的脚位置（由 recal_pins.py 从 Fritzing 自己的渲染反推 ✓）：
#   {modelIndex: {connectorId: (x, y)}} —— 有它就用它 ✓（逐元件公式跨元件不成立 ✗，2026-09-26）
PINS_FIX = {}


def tag(el):
    return el.tag.split("}")[-1]


def shape_pts(el):
    a, t = el.attrib, tag(el)
    n = lambda k: pm.num(a.get(k))            # noqa: E731
    if t == "rect":
        x, y, w, h = n("x"), n("y"), n("width"), n("height")
        return [(x, y), (x + w, y + h)] if None not in (x, y, w, h) else []
    if t == "line":
        return [(n("x1"), n("y1")), (n("x2"), n("y2"))]
    if t == "circle":
        cx, cy, r = n("cx"), n("cy"), n("r")
        return [(cx - r, cy - r), (cx + r, cy + r)] if None not in (cx, cy, r) else []
    if t == "ellipse":
        cx, cy, rx, ry = n("cx"), n("cy"), n("rx"), n("ry")
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)] if None not in (cx, cy, rx, ry) else []
    if t in ("polyline", "polygon", "path"):
        key = "points" if t in ("polyline", "polygon") else "d"
        v = [float(x) for x in re.findall(r"-?[\d.]+", a.get(key) or "")]
        return list(zip(v[0::2], v[1::2]))
    return []


def body_pts(el, m, out):
    """本体图形（跳过 pin / terminal / text ✓）的导出坐标点 ✓

    ★ 坑（2026-09-26）：不能按"有没有 x 属性"来判断 ✗ —— `<rect>` 本体**也带** x ✓，
      那样写会把所有矩形本体都跳过 ✗（U1/LED2/C1/C2 的本体框就成了空 ✗）
    """
    if tag(el) == "text" or el.get("class") == "pin" or (el.get("id") or "").endswith("terminal"):
        return
    for (x, y) in shape_pts(el):
        out.append(apply(m, x, y))
    t = el.get("transform")
    m2 = pm_mul(m, t)
    for c in el:
        body_pts(c, m2, out)


def pm_mul(m, t):
    from pin_ruler import mul, parse_tf
    return mul(m, parse_tf(t)) if t else m


# ─────────────────────────── 几何 ───────────────────────────
def load_geom(fzz, svg):
    ruler = build_ruler(svg)
    root = ET.parse(svg).getroot()
    boxes = {}

    def walk(el, m, pid):
        m2 = pm_mul(m, el.get("transform"))
        if el.get("partID"):
            pid = el.get("partID")
        if pid and el.get("id") == "schematic" and pid not in boxes:
            pts = []
            body_pts(el, m2, pts)
            boxes[pid] = pts
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)

    z = zipfile.ZipFile(fzz)
    sroot = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    conname, con_of = {}, {}
    for n in z.namelist():
        if n.startswith("part.") and n.endswith(".fzp"):
            r = ET.fromstring(z.read(n))
            conname[r.get("moduleId")] = {c.get("id"): (c.get("name") or "")
                                          for c in r.iter("connector")}
    insts = {}
    for e in sroot.iter("instance"):
        vw = pm.child(e, "views")
        sub = pm.child(vw, "schematicView") if vw is not None else None
        g = pm.child(sub, "geometry") if sub is not None else None
        if g is None or g.get("x") is None:
            continue
        mi = e.get("modelIndex")
        title = (e.findtext("title") or "").strip()
        loc = (pm.num(g.get("x")), pm.num(g.get("y")))
        pid = next((p for p in ruler if p.startswith(mi) and len(p) == len(mi) + 1),
                   mi if mi in ruler else None)
        ox, oy = ruler[pid]["origin"] if pid else (0, 0)
        sk = lambda x, y: (loc[0] + RATIO * (x - ox), loc[1] + RATIO * (y - oy))   # noqa: E731
        pins, pins_export = {}, {}
        if pid:
            for cid, (ex, ey) in ruler[pid]["pins"].items():
                pins_export[cid] = (ex, ey)
                pins[cid] = sk(ex, ey)
        if PINS_FIX.get(mi):                  # ★ 优先用标定值 ✓（精确 ✓）
            for cid, p in PINS_FIX[mi].items():
                if cid in pins:
                    pins[cid] = p
        pts = [sk(x, y) for (x, y) in boxes.get(pid, [])] if pid else []
        box = None
        if pts:
            box = (min(p[0] for p in pts), min(p[1] for p in pts),
                   max(p[0] for p in pts), max(p[1] for p in pts))
        insts[title] = {"mi": mi, "mid": e.get("moduleIdRef"), "el": e, "sub": sub,
                        "loc": loc, "pins": pins, "box": box, "names": conname,
                        "ox": (ox, oy) if pid else None, "pins_export": pins_export}

    # ★ 全局映射：拿"同一个脚在 sketch 与在导出 SVG 里的坐标"最小二乘拟合 ✓
    #   （2026-09-26：原以为能用 `导出 = ox − loc/1.25` 逐元件推 ✗ —— 实测离散 22 单位 ✗，
    #    说明那个关系只是**逐元件内部**自洽，不能当全局映射 ✓；脚是地面真值 ✓）
    def lin_fit(pairs):
        n = len(pairs)
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        den = sum((p[0] - mx) ** 2 for p in pairs)
        s = sum((p[0] - mx) * (p[1] - my) for p in pairs) / den if den else 1.0
        a = my - s * mx
        return s, a, max(abs(p[1] - (a + s * p[0])) for p in pairs)

    xp, yp = [], []
    for d in insts.values():
        for cid, (ex, ey) in d["pins_export"].items():
            sx, sy = d["pins"][cid]
            xp.append((sx, ex))
            yp.append((sy, ey))
    fit = {"x": lin_fit(xp), "y": lin_fit(yp), "n": len(xp)}
    return sroot, insts, z, fit


def pin_of(insts, ref, name):
    d = insts[ref]
    cmap = d["names"].get(d["mid"], {})
    if name.startswith("#"):
        cid = "connector" + str(int(name[1:]) - 1)
    else:
        cid = next((c for c, nm in cmap.items() if nm.lower() == name.lower()), None)
        if cid is None:
            raise SystemExit("✗ %s 找不到名叫 %s 的脚（有：%s）"
                             % (ref, name, ", ".join("%s=%s" % kv for kv in cmap.items())))
    if cid not in d["pins"]:
        raise SystemExit("✗ 导出里没有 %s 的 %s" % (ref, cid))
    return cid, d["pins"][cid]


# ─────────────────────────── 布线 ───────────────────────────
def seg_hits_box(p, q, box, clear):
    """线段 p→q 是否穿过 box（外扩 clear ✓）"""
    if box is None:
        return False
    x0, y0, x1, y1 = box[0] - clear, box[1] - clear, box[2] + clear, box[3] + clear
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
    for i in range(n + 1):
        t = i / n
        x = p[0] + (q[0] - p[0]) * t
        y = p[1] + (q[1] - p[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def overlap(a, b, c, d, tol=0.5):
    """两段是否**共线重叠**（同 net 以外的线不许叠一起 ✓）"""
    if abs(a[0] - b[0]) < tol and abs(c[0] - d[0]) < tol and abs(a[0] - c[0]) < tol:
        lo1, hi1 = sorted((a[1], b[1]))
        lo2, hi2 = sorted((c[1], d[1]))
        return min(hi1, hi2) - max(lo1, lo2) > tol
    if abs(a[1] - b[1]) < tol and abs(c[1] - d[1]) < tol and abs(a[1] - c[1]) < tol:
        lo1, hi1 = sorted((a[0], b[0]))
        lo2, hi2 = sorted((c[0], d[0]))
        return min(hi1, hi2) - max(lo1, lo2) > tol
    return False


def path_ok(path, boxes, my_boxes, used):
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        if abs(p[0] - q[0]) > 1e-6 and abs(p[1] - q[1]) > 1e-6:
            return False                      # 非正交 ✗
        for title, box in boxes.items():
            if title in my_boxes:
                continue
            if seg_hits_box(p, q, box, CLEAR):
                return False
        for (p2, q2) in used:
            if overlap(p, q, p2, q2):
                return False
    return True


def candidates(a, b, chx, chy):
    out = []
    if abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6:
        out.append([a, b])
    out.append([a, (b[0], a[1]), b])
    out.append([a, (a[0], b[1]), b])
    for x in chx:
        out.append([a, (x, a[1]), (x, b[1]), b])
    for y in chy:
        out.append([a, (a[0], y), (b[0], y), b])
    return out


def bends(path):
    return max(0, len(path) - 2)


def plen(path):
    return sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
               for i in range(len(path) - 1))


def main(argv):
    fzz, svg, out_path = argv[0], argv[1], argv[2]
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
    orig = [argv[argv.index("--orig") + 1]] if "--orig" in argv else [None]
    if "--pins" in argv:                      # 载入标定过的脚位置 ✓
        import importlib.util
        p = argv[argv.index("--pins") + 1]
        spec = importlib.util.spec_from_file_location("pins_fixed", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PINS_FIX.update(mod.PINS)
        print("标定脚位置: 载入 %d 个元件（%s）" % (len(PINS_FIX), p))

    sroot, insts, z, fit = load_geom(fzz, svg)
    print("画布: %d 个实例（%s）" % (len(insts), ", ".join(sorted(insts))))
    print("映射: %d 个脚拟合 ⇒ x: 导出=%.6f·sketch+%.3f（残差 %.4f）✓  y: 导出=%.6f·sketch+%.3f（残差 %.4f）✓"
          % (fit["n"], fit["x"][0], fit["x"][1], fit["x"][2],
             fit["y"][0], fit["y"][1], fit["y"][2]))

    chx, chy = set(), set()
    for d in insts.values():
        b = d["box"]
        if b:
            chx.update(b[0] - o for o in CH_OFFS)
            chx.update(b[2] + o for o in CH_OFFS)
            chy.update(b[1] - o for o in CH_OFFS)
            chy.update(b[3] + o for o in CH_OFFS)
        for p in d["pins"].values():
            chx.add(p[0])
            chy.add(p[1])
    boxes = {t: d["box"] for t, d in insts.items() if d["box"]}
    print("keep-out 盒: %s" % ", ".join("%s(%.1f,%.1f→%.1f,%.1f)" % ((t,) + b)
                                       for t, b in sorted(boxes.items())))

    used, nets_segs, warn = [], {}, []
    for net, pins in NETS.items():
        if len(pins) < 2:
            print("网 %-9s 只有 %d 个脚 ⇒ 没有线可画 ✓（保持独立 ✓）" % (net, len(pins)))
            continue
        pts = []
        for ref, name in pins:
            cid, p = pin_of(insts, ref, name)
            pts.append({"ref": ref, "cid": cid, "p": p})
        pts.sort(key=lambda d: (round(d["p"][0], 3), round(d["p"][1], 3)))
        segs = []
        for i in range(len(pts) - 1):
            a, b = pts[i]["p"], pts[i + 1]["p"]
            mine = {pts[i]["ref"], pts[i + 1]["ref"]}
            # 三级：① 不碰本体 + 不与已布线段共线重叠 ✓ ② 只要求不碰本体 ✓ ③ 兜底（否则端点接不上 ✗）
            best, best_key = None, None
            for path in candidates(a, b, sorted(chx), sorted(chy)):
                no_box = all(not seg_hits_box(path[k], path[k + 1], box, CLEAR)
                             for k in range(len(path) - 1)
                             for t, box in boxes.items() if t not in mine)
                if not no_box:
                    continue
                free = all(not overlap(path[k], path[k + 1], p2, q2)
                           for k in range(len(path) - 1) for (p2, q2) in used)
                key = (0 if free else 1, bends(path), plen(path))
                if best_key is None or key < best_key:
                    best, best_key = path, key
            if best is None:
                warn.append("%s: %s→%s 没找到不碰本体的路径 ✗" % (net, pts[i]["ref"], pts[i + 1]["ref"]))
                best = candidates(a, b, sorted(chx), sorted(chy))[0]
            for k in range(len(best) - 1):
                used.append((best[k], best[k + 1]))
            segs.append({"a": best[0], "b": best[-1], "path": best,
                         "from": pts[i], "to": pts[i + 1]})
        nets_segs[net] = segs
        print("网 %-9s %d 个脚 → %d 段（弯 %d）"
              % (net, len(pts), len(segs), sum(bends(s["path"]) for s in segs)))

    if preview:
        draw_preview(preview, svg, insts, nets_segs, fit)
        print("预览: %s" % preview)
    if warn:
        print("\n⚠ %d 处需要人看：" % len(warn))
        for w in warn:
            print("   " + w)

    if orig[0]:
        emit(sroot, insts, z, nets_segs, orig[0], out_path)
    return 0


def fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else ("%.4f" % v)


def build_wire(tmpl, w):
    """克隆模板导线 → 只留 schematicView + 设本段几何 ✓（连接留到后面统一写 ✓）"""
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", w["mi"])
    t = pm.child(e, "title")
    if t is not None:
        t.text = "Wire" + w["mi"]
    vw = pm.child(e, "views")
    for sub in list(vw):
        if not tag(sub) == "schematicView":
            vw.remove(sub)
    sub = pm.child(vw, "schematicView")
    sub.set("layer", "schematicTrace")
    g = pm.child(sub, "geometry")
    if g is None:
        g = ET.SubElement(sub, "geometry")
    dx, dy = w["q"][0] - w["p"][0], w["q"][1] - w["p"][1]
    # ★ wireFlags 是**位标**（`viewgeometry.h:42`）：NoFlag=0, RoutedFlag=2, PCBTraceFlag=4,
    #   ObsoleteJumperFlag=8, RatsnestFlag=16, AutoroutableFlag=32, NormalFlag=64,
    #   **SchematicTraceFlag=128**
    #   原理图导线的 trace flag 就是 128 ✓（`schematicsketchwidget.cpp:358`）；
    #   少了这一位，`modelbase.cpp` 的 `checkOldSchematics()` 会把线当"旧版导线" ⇒
    #   **不算布线** ✗ ⇒ Fritzing 画虚线、状态栏显示"仍有 N 个插接件需要布线" ✗
    #   （2026-09-26 用户截图发现 ✓；模板是面包板导线，它的值是 64 ✗ 不能照抄 ✓）
    g.attrib.update({"x": fmt(w["p"][0]), "y": fmt(w["p"][1]),
                     "x1": "0", "y1": "0", "x2": fmt(dx), "y2": fmt(dy),
                     "wireFlags": "128"})
    if pm.child(sub, "wireExtras") is None:
        ET.SubElement(sub, "wireExtras", {"mils": "9.7222", "color": "#404040",
                                          "opacity": "1", "banded": "0"})
    for boxel in sub.iter():                     # 清掉模板带来的旧连接 ✗
        if tag(boxel) == "connects":
            for c in list(boxel):
                if tag(c) == "connect":
                    boxel.remove(c)
    return e


def add_conn(view, owner_cid, other_cid, other_mi, other_layer, fallback_layer):
    """把一条连接写进**连接器级** ✓（Fritzing 1.0 只读这一份 ✗）"""
    box = None
    for c in view:
        if tag(c) == "connectors":
            box = c
    if box is None:
        box = ET.SubElement(view, "connectors")
    conn = None
    for c in box:
        if tag(c) == "connector" and c.get("connectorId") == owner_cid:
            conn = c
    if conn is None:
        conn = ET.SubElement(box, "connector", {"connectorId": owner_cid,
                                                 "layer": view.get("layer") or fallback_layer})
        ET.SubElement(conn, "geometry", {"x": "0", "y": "0"})
    cs = pm.child(conn, "connects")
    if cs is None:
        cs = ET.SubElement(conn, "connects")
    ET.SubElement(cs, "connect", {"connectorId": other_cid,
                                   "modelIndex": str(other_mi), "layer": other_layer})


def emit(sroot, insts, z, nets_segs, orig_path, out_path):
    """把每对脚的正交路径拆成「一段一根导线」✓；两端各记一份连接 ✓（链式，不出现 junction 点 ✓）"""
    oz = zipfile.ZipFile(orig_path)
    oroot = ET.fromstring(oz.read([n for n in oz.namelist() if n.endswith(".fz")][0]))
    tmpl = next((copy.deepcopy(e) for e in oroot.iter("instance")
                 if (e.get("moduleIdRef") or "").startswith("Wire")), None)
    if tmpl is None:
        raise SystemExit("✗ 原文件里没有 Wire 模板")
    host = pm.child(sroot, "instances")
    host = sroot if host is None else host
    next_mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1

    wires, links = [], []
    for net in sorted(nets_segs):
        for s in nets_segs[net]:
            chain = []
            for k in range(len(s["path"]) - 1):
                p, q = s["path"][k], s["path"][k + 1]
                if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                    continue
                chain.append({"mi": str(next_mi), "p": p, "q": q,
                              "start_tgt": None, "end_tgt": None})
                next_mi += 1
            if not chain:
                continue
            chain[0]["start_tgt"] = ("pin", s["from"])
            chain[-1]["end_tgt"] = ("pin", s["to"])
            for k in range(len(chain) - 1):
                chain[k]["end_tgt"] = ("wire", chain[k + 1], "connector0")
                chain[k + 1]["start_tgt"] = ("wire", chain[k], "connector1")
            wires.extend(chain)

    for w in wires:                              # 建实例 ✓
        w["el"] = build_wire(tmpl, w)
        host.append(w["el"])
        w["view"] = pm.child(pm.child(w["el"], "views"), "schematicView")
    wire_by_mi = {w["mi"]: w for w in wires}
    part_by_mi = {d["mi"]: d for d in insts.values()}

    for w in wires:                              # 收集两端归属 ✓
        for cid, tgt in (("connector0", w["start_tgt"]), ("connector1", w["end_tgt"])):
            if tgt is None:
                continue
            if tgt[0] == "pin":
                p = tgt[1]
                links.append((w["mi"], cid, "schematicTrace",
                              insts[p["ref"]]["mi"], p["cid"], "schematic"))
            else:
                ow = tgt[1]
                links.append((w["mi"], cid, "schematicTrace",
                              ow["mi"], tgt[2], "schematicTrace"))

    # ★ 去重（2026-09-26）：链上同一对"导线↔导线"会从两头各收集一次 ✗ ⇒
    #   不去重就会写出两条一模一样的 <connect> ✗（实测 Wire…connector1 里出现两条 ✓）
    seen, uniq = set(), []
    for L in links:
        key = tuple(sorted([(L[0], L[1]), (L[3], L[4])]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(L)
    links = uniq

    for (a_mi, a_cid, a_layer, b_mi, b_cid, b_layer) in links:   # 两侧各记一份 ✓
        if a_mi in wire_by_mi:
            add_conn(wire_by_mi[a_mi]["view"], a_cid, b_cid, b_mi, b_layer, a_layer)
        else:
            add_conn(part_by_mi[a_mi]["sub"], a_cid, b_cid, b_mi, b_layer, a_layer)
        if b_mi in wire_by_mi:
            add_conn(wire_by_mi[b_mi]["view"], b_cid, a_cid, a_mi, a_layer, b_layer)
        else:
            add_conn(part_by_mi[b_mi]["sub"], b_cid, a_cid, a_mi, a_layer, b_layer)

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n.endswith(".fz") else z.read(n))
    print("写入: %s（%d 根导线、%d 条连接 ✓）" % (out_path, len(wires), len(links)))


COLORS = ["#c00000", "#0070c0", "#00a050", "#c08000", "#8000c0",
          "#00a0a0", "#c060a0", "#606060", "#a0a000", "#004080"]


def draw_preview(path, base_svg, insts, nets_segs, fit):
    r"""预览 = **Fritzing 自己导出的 SVG**（真符号 ✓）+ 我的走线叠在上面 ✓

    ★ 2026-09-26 用户指出：不许自创一套元件图标 ✗ —— 元件图形完全来自 Fritzing 导出 ✓。
    叠层用**拟合出来的**全局映射 ✓（导出 = s·sketch + A ✓，s≈0.8 = 1/1.25 ✓）。
    """
    txt = open(base_svg, encoding="utf-8").read()
    sx, ax, rx = fit["x"]
    sy, ay, ry = fit["y"]
    print("预览映射: x %.6f/%.3f（残差 %.4f）  y %.6f/%.3f（残差 %.4f）"
          % (sx, ax, rx, sy, ay, ry))
    L = ['<g transform="translate(%.4f,%.4f) scale(%.6f,%.6f)" fill="none">' % (ax, ay, sx, sy)]
    for i, (net, segs) in enumerate(sorted(nets_segs.items())):
        c = COLORS[i % len(COLORS)]
        for s in segs:
            d = " ".join("%s%.1f,%.1f" % ("M" if k == 0 else "L", p[0], p[1])
                         for k, p in enumerate(s["path"]))
            L.append('<path d="%s" stroke="%s" stroke-width="1.15"/>' % (d, c))
        p = segs[0]["path"][0]                 # 网名只作汇总标注（不入 .fzz ✓）
        L.append('<text x="%.1f" y="%.1f" font-size="14" fill="%s" stroke="none">%s</text>'
                 % (p[0] + 6, p[1] - 5, c, net))
    L.append("</g>")
    out = txt.replace("</svg>", "\n".join(L) + "\n</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
