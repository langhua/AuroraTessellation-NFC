# -*- coding: utf-8 -*-
r"""锁 / 姿态清单 ✓（**独立读取** ✓ —— 摆位器不许自证 ✓）

用法 ✓：`fz_locks.py <file.fzz> [--only-locked]`
读法 ✓（**逐字按文件**，不猜 ✓）：`<instance><views><pcbView locked="true" ...>`
  · 锁 = Fritzing 的 **`m_moveLock`（移动锁 ✓）** —— 见源码 `itembase.cpp:294`（写 ✓）、
    `sketchwidget.cpp:281`（读 ✓）、`:318`（`setMoveLock(true)` ✓）、
    `:1076 / :2442 / :7162`（拦移动 ✓）、`connectoritem.cpp:2508`（连着的线也拦 ✓）、
    `resizableboard.cpp:1228`（板角也拦 ✓）。
  · 朝向 θ：从 `<geometry>` 里的 `<transform>` 反解 ✓ `θ = atan2(m12, m11)` ✓
    （口径由 Fritzing 给 `L1` 亲笔写的 `m11=0 m12=1` ⇒ 90° 验过 ✓，见 `gen_pcb.rot_about_canvas` ✓）。
  · `loc` 给的是**草图单位**与 **mm（相对板左上角 ✓）**两种 ✓。
"""
import math
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

SK = 90.0 / 25.4                     # 1 mm = 3.5433 草图单位 ✓（与库仓一致 ✓）


def tag(e):
    return e.tag.split("}")[-1]


def main(argv):
    path = argv[0]
    only = "--only-locked" in argv
    z = zipfile.ZipFile(path)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(fz))
    board = root.find(".//board")
    bx = by = 0.0
    bw = bh = 0.0
    if board is not None:
        bw = float("".join(c for c in (board.get("width") or "0") if c in "0123456789."))
        bh = float("".join(c for c in (board.get("height") or "0") if c in "0123456789."))
        if (board.get("width") or "").endswith("cm"):
            bw *= 10.0
        if (board.get("height") or "").endswith("cm"):
            bh *= 10.0
    # 板原点 = 板实例（`moduleIdRef` 以 `PCB` 开头 ✓）的 pcbView 几何 ✓（mm 相对它算 ✓）
    for q in root.iter("instance"):
        if (q.get("moduleIdRef") or "").startswith("PCB"):
            for vw in q.findall("views"):
                gq = vw.find("geometry")
                if gq is not None:
                    bx, by = float(gq.get("x") or 0), float(gq.get("y") or 0)
                    break
            break
    for p in root.iter("instance"):
        if (p.get("moduleIdRef") or "").startswith(("Wire", "Via")):
            continue
        pv = None
        for vw in p.findall("views"):
            for c in vw:
                if tag(c) == "pcbView":
                    pv = c
        if pv is None:
            continue
        g = pv.find("geometry")
        if g is None:
            continue
        locked = (pv.get("locked") or "").lower() == "true"
        if only and not locked:
            continue
        x, y = float(g.get("x") or 0), float(g.get("y") or 0)
        a, b = 1.0, 0.0
        tf = g.find("transform")
        if tf is not None:
            a = float(tf.get("m11") or 1)
            b = float(tf.get("m12") or 0)
        th = int(round(math.degrees(math.atan2(b, a)))) % 360
        mi = p.get("modelIndex") or "?"
        print("  %-14s mi=%-10s %-4s %-8s %3d°  loc=(%7.2f, %7.2f) mm"
              % ((p.findtext("title") or "?"), mi,
                 "★锁" if locked else "  ", (pv.get("layer") or "-"),
                 th, (x - bx) / SK, (y - by) / SK))
    print("  板 ✓：%.2f × %.2f mm" % (bw, bh))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
