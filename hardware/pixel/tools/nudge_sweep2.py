# -*- coding: utf-8 -*-
r"""临时 ✓（干净版 ✓）：**挪一个件的 PCB 位置**（只动副本 ✓）＋ **量那两口封死的口袋** ✓

用法：py -3.13 -X utf8 tools\nudge_sweep2.py [<bare.fzz>]

为什么 ✗：库自己的诊断把病点名了 —— 差的两张网是**目标脚被几何封成小口袋** ✗
（`RC` 的 `U1.connector1` 33 格 ✓、`GND` 的 `C1.connector1` 109 格 ✓），
围它的大头是**邻脚的盘** ✗（不是线 ✗）⇒ 那两口的**几何底子**多大 ✓、
**挪一点点能不能开** ✓ —— 这是**量**出来的 ✓，不是猜 ✓。

★ 三条口径 ✓：
  · 只动**副本** ✓（✗ 不碰交付件 ✓）；
  · 判据用**库自己的** `flood` ✓（✗ 不另写 BFS ✓）；
  · 挪位只动 `<pcbView>` 里**第一个** `<geometry>` ✓（= 摆放位 ✓）＋ `titleGeometry` ✓
    —— ✗ 其余 `<geometry>` 是**焊盘自己的**（相对件 ✓），挪了就错 ✗。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
WORK = os.path.join(PIX, "_work")     # ★ 候选/日志/底图仍写草稿区 ✓（保持工具目录干净 ✓）


def _find_tools(start):
    d = start
    for _ in range(6):
        cand = os.path.join(d, "fritzing-parts-langhua", "tools")
        if os.path.isdir(cand):
            return cand
        d = os.path.dirname(d)
    raise SystemExit("✗ 找不到 tools ✓")


sys.path.insert(0, _find_tools(PIX))
sys.path.insert(0, PIX)

import pcb_check as PC        # noqa: E402
import pcb_route as RT        # noqa: E402
import projdata              # noqa: E402

SK = RT.SK                                   # 1 草图单位 = 0.28222 mm ✓

GEOM = re.compile(r'(<geometry\b[^>]*?\bx=")([-0-9.eE]+)("[^>]*?\by=")([-0-9.eE]+)(")')
TGEOM = re.compile(r'(<titleGeometry\b[^>]*?\bx=")([-0-9.eE]+)("[^>]*?\by=")'
                   r'([-0-9.eE]+)(")')


def _bump(pat, s, du, dv, count=0):
    def rep(m):
        return "%s%.6f%s%.6f%s" % (m.group(1), float(m.group(2)) + du,
                                   m.group(3), float(m.group(4)) + dv, m.group(5))
    return pat.subn(rep, s, count=count)


def fz_text(path):
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        name = [n for n in z.namelist() if n.endswith(".fz")][0]
        return name, z.read(name).decode("utf-8")
    return None, open(path, encoding="utf-8").read()


def nudge(text, title, dx_mm, dy_mm):
    """挪 `<title>` 实例的 PCB 摆放位 ✓（只动第一个 `<geometry>` ＋ `titleGeometry` ✓）"""
    du, dv = dx_mm / SK, dy_mm / SK
    for m in re.finditer(r"<instance\b", text):
        end = text.find("</instance>", m.start())
        if end < 0:
            continue
        blk = text[m.start():end]
        if ("<title>%s</title>" % title) not in blk:
            continue
        v0 = blk.find("<pcbView")
        if v0 < 0:
            raise SystemExit("✗ %s 没有 pcbView ✓" % title)
        v1 = blk.find("</pcbView>", v0)
        view = blk[v0:v1]
        new, n1 = _bump(GEOM, view, du, dv, count=1)      # ★ 只挪第一个 ✓
        new, n2 = _bump(TGEOM, new, du, dv, count=1)
        if n1 != 1 or n2 != 1:
            raise SystemExit("✗ 命中数不对：geometry=%d, title=%d ✓" % (n1, n2))
        return text[:m.start()] + blk[:v0] + new + blk[v1:] + text[end:]
    raise SystemExit("✗ 找不到实例 %s ✓" % title)


def write_zip(src, dst, title, dx, dy):
    z = zipfile.ZipFile(src)
    name, text = fz_text(src)
    out = nudge(text, title, dx, dy)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as w:
        for n in z.namelist():
            w.writestr(n, out.encode("utf-8") if n == name else z.read(n))
    return dst


def pockets(fzz, want):
    """`want` = [(网, "位号.connectorN")] ⇒ [(网, 脚, 口袋格数)] ✓"""
    data = projdata.load(os.path.join(PIX, "pixel_nets.py"), need=("NETS",))
    m = PC.collect(fzz)
    pads = RT.pad_index(m)
    net_pads, _u = RT.resolve_nets(m, data.NETS)
    m["net_pads"] = net_pads
    items, _st = RT.obstacles(m)
    out = []
    for net, key in want:
        g = RT.make_grid(m["board"], RT.CELL_MM, items)
        RT.carve_pads(g, pads, net_pads[net], RT.U(RT.TRACE_MM / 2 + RT.CLEAR_MM))
        q = pads.get(tuple(key.split(".", 1)))
        if not q:
            out.append((net, key, -1))
            continue
        best = None
        for lay in (q.get("lays") or ()):
            if lay not in g.g:
                continue
            n = len(RT.flood(g, lay, q["c"]))
            best = n if best is None else min(best, n)
        out.append((net, key, -1 if best is None else best))
    return out


def main(argv):
    base = argv[0] if argv else os.path.join(WORK, "v69_bare.fzz")
    RT.TRACE_MM = 8 * RT.MIL_MM
    want = [("RC", "U1.connector1"), ("GND", "C1.connector1")]

    def show(tag, fzz):
        print("   %-24s ⇒ %s" % (tag, "  ".join("%s %-15s %5d 格" % t
                                                for t in pockets(fzz, want))))
    print("== 基线 ✓ ==")
    show(os.path.basename(base), base)
    print("\n== 挪动扫描 ✓（每次 1 mm ✓，只动副本 ✓）==")
    for title in ("C1", "R1", "L1", "D3", "U1"):
        for (dx, dy) in ((1.0, 0), (-1.0, 0), (0, 1.0), (0, -1.0)):
            dst = os.path.join(WORK, "_nudge_%s_%+d_%+d.fzz" % (title, dx, dy))
            try:
                write_zip(base, dst, title, dx, dy)
            except SystemExit as exc:
                print("   %-24s ⇒ %s" % ("%s %+g,%+g mm" % (title, dx, dy), exc))
                continue
            show("%s %+g,%+g mm" % (title, dx, dy), dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
