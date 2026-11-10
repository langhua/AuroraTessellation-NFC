# -*- coding: utf-8 -*-
r"""给面包板图里**接点不在孔上**的脚补/改 `<leg>`（腿）✓ ⇒ `bb_precheck` ② 通过

用法: py -3.13 -u fix_pin_geometry.py <in.fzz> <out.fzz> [--tol=0.6]

**口径**（与 `bb_precheck.py` ② 逐字同一套 ✓，✗ 不另造 ✓）：
```
接点 = loc + apply(M, <geometry x,y> + <leg>最后一个<point>)     ← 有 <leg>
     = loc + apply(M, <geometry x,y>)                          ← 没有 <leg>
M = <transform m11..m32>（**含 m31/m32 平移** ✓ —— 第一版漏了它 ⇒ 修完还对不上 ✗，实测 ✓）
```
⇒ 让**腿端恰好落在孔心** ✓：`<point> = M⁻¹·(孔 − loc − (m31,m32)) − <geometry>` ✓。

★ 只改**不达标**的脚（≤ tol 一律不动 ✓）；只动 `breadboardView` ✓；`<connects>` 原样保留 ✓。
★ 第一版两个 bug（都实测出来了 ✓）：① 忘了 `m31/m32` ✗；② "补 `<leg>`" 用整段 `re.sub(count=1)`
  ⇒ 每只脚都往**第一个** connector 里塞 ✗ ⇒ `U1` 的脚一只都没修到 ✗。
"""
import re
import sys
import zipfile

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
COL = 9.0
SK_MM = 25.4 / 90.0
ID = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def hole_xy(h):
    m = re.fullmatch(r"pin(\d+)([A-Z])", h)
    return (int(m.group(1)) * COL, ROW_Y[m.group(2)])


def num(v):
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def tf_of(txt):
    t = re.search(r"<transform ([^/>]*)/?>", txt)
    if not t:
        return ID
    a = dict(re.findall(r'(m\d\d)="([-\d.eE+]+)"', t.group(1)))
    return (float(a.get("m11", 1)), float(a.get("m12", 0)), float(a.get("m21", 0)),
            float(a.get("m22", 1)), float(a.get("m31", 0)), float(a.get("m32", 0)))


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def solve(m, tx, ty):
    """解 `apply(m, u) = (tx, ty)` ✓（`u` = 局部坐标 ✓）"""
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return (tx, ty)
    px, py = tx - e, ty - f
    return ((d * px - c * py) / det, (-b * px + a * py) / det)


def rebuild(block, loc, m, hole):
    """把这个 `<connector>` 的腿端对到孔心 ✓；返回 (新 block, 原差 mm)"""
    cg = re.search(r'<geometry x="([-\d.]+)" y="([-\d.]+)"', block)
    gx, gy = (float(cg.group(1)), float(cg.group(2))) if cg else (0.0, 0.0)
    lg = re.search(r"<leg>(.*?)</leg>", block, re.S)
    pts = list(re.finditer(r'<point x="([-\d.]+)" y="([-\d.]+)"', lg.group(1))) if lg else []
    if pts:
        lx, ly = float(pts[-1].group(1)), float(pts[-1].group(2))
        p = apply(m, gx + lx, gy + ly)
    else:
        p = apply(m, gx, gy)
    cur = (((loc[0] + p[0] - hole[0]) ** 2 + (loc[1] + p[1] - hole[1]) ** 2) ** 0.5) * SK_MM
    want = solve(m, hole[0] - loc[0], hole[1] - loc[1])
    pt = (want[0] - gx, want[1] - gy)
    newpt = '<point x="%s" y="%s" />' % (num(pt[0]), num(pt[1]))
    if lg:
        body = lg.group(1)
        body = body[:pts[-1].start()] + newpt + body[pts[-1].end():]
        new = block.replace(lg.group(0), "<leg>%s</leg>" % body)
    else:
        # 没有 <leg> ⇒ 在这个 connector 的 <geometry> 后面补一条（✗ 不是往第一个 connector 里塞 ✗）
        leg = ('<leg><point x="0" y="0" /><bezier />%s<bezier /></leg>' % newpt)
        new = re.sub(r'(<geometry x="[-\d.]+" y="[-\d.]+"\s*/>)', lambda mm: mm.group(1) + leg,
                     block, count=1)
        if new == block:
            raise SystemExit("补腿失败 ✗：%s" % block[:120])
    return new, cur


def main(argv):
    src, out = argv[0], argv[1]
    tol = 0.6
    for a in argv[2:]:
        if a.startswith("--tol="):
            tol = float(a.split("=")[1])
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")
    items = [(i, z.read(i.filename)) for i in z.infolist()]

    n_fix = 0
    for m in list(re.finditer(r'<instance [^>]*>.*?</instance>', text, re.S)):
        blk = m.group(0)
        # ★★ 2026-11-10 修 ✗：原来是 `if 'layer="breadboardWire"' in blk` ⇒
        #   **`U1` 的实例里正好有一根接 EPAD 的导线** ⇒ 整件被当成导线跳过 ✗
        #   （实测：`U1` 的 20 只脚一只都没修到 ✓，② 一直差 7.62 mm ✓）
        #   ⇒ 按**实例自己的 moduleIdRef** 判 ✓，不按"块里出现过什么" ✗
        if 'moduleIdRef="WireModuleID"' in blk or "Breadboard-" in blk:
            continue
        bb = re.search(r"<breadboardView[^>]*>.*?</breadboardView>", blk, re.S)
        if not bb:
            continue
        g = re.search(r'<geometry z="[^"]*" x="([-\d.]+)" y="([-\d.]+)"', bb.group(0))
        if not g:
            continue
        loc = (float(g.group(1)), float(g.group(2)))
        mtx = tf_of(bb.group(0))
        ttl = (re.search(r"<title>([^<]*)</title>", blk) or [None, "?"])[1]
        nb = bb.group(0)
        for cm in list(re.finditer(r'<connector connectorId="connector\d+" layer="breadboard">.*?</connector>',
                                   bb.group(0), re.S)):
            holes = re.findall(r'connectorId="(pin\d+[A-Z])"[^>]*layer="breadboardbreadboard"', cm.group(0))
            if len(holes) != 1:
                continue
            new, cur = rebuild(cm.group(0), loc, mtx, hole_xy(holes[0]))
            if cur is None or cur <= tol:
                continue
            nb = nb.replace(cm.group(0), new, 1)
            n_fix += 1
            print("  %-6s → %-7s 原差 %6.2f mm ⇒ 腿端对到孔心 ✓" % (ttl, holes[0], cur))
        if nb != bb.group(0):
            text = text.replace(bb.group(0), nb, 1)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == name:
                data = text.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 写出 %s（补/改 %d 只脚的腿 ✓）" % (out, n_fix))
    return 0


sys.exit(main(sys.argv[1:]))
