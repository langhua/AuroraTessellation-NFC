# -*- coding: utf-8 -*-
r"""量出**每根引线"擦过/压住"了哪些孔** ✓ —— 补 `audit_layout.py` 的洞 ✗

起因（2026-09-27 用户报 ✓：「v57 里 Wire90012900 违规了啊！没有检查出来？」✗）：
- 我现有的「遮挡接线孔」判据是**面积 ≥30%** ✗（用户 2026-09-26 允许我定的阈值 ✓）
  ⇒ 一根线**擦着孔边过**（只盖 5% ✗）就**漏网** ✗；
- 用户看实样时，这种"线从孔上划过去"✗ 是一眼可见的违规 ✗（会挡住插线/看着短路 ✓）。

做法（两个独立口径 ✓，都要报 ✓）：
  ① **中心线距离** d（单位 ✓）：线中心到孔心的最近距离 ✓
     —— 判据：d < 孔半径 + 线半宽 ⇒ **有重叠** ✓
  ② **盖住面积比**（复用自己的 `obscures` 口径 ✗ 不重写 ✓）：直接调 `bb_compare.obscures`
用法：py -3.13 f:\git\_scratch\wire_near.py <sketch.fzz> [阈值单位，默认 3.0]
"""
import sys
import zipfile
import xml.etree.ElementTree as ET

PIX = r"f:\git\AuroraTessellation-NFC\hardware\pixel"
sys.path.insert(0, PIX)
import bb_compare as BC                                              # noqa: E402

HOLE_R = 1.496          # 孔开口半径（单位 ✓，见 bb_compare / 文档 ✓）
WIRE_HALF = 1.0         # 引线半宽（写出来的线宽 2 单位 ✓）


def tag(e):
    return e.tag.split("}")[-1]


def seg_dist(p, q, h):
    """点 h 到线段 pq 的距离 ✓（单位）"""
    px, py = p
    qx, qy = q
    hx, hy = h
    dx, dy = qx - px, qy - py
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return ((hx - px) ** 2 + (hy - py) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((hx - px) * dx + (hy - py) * dy) / L2))
    cx, cy = px + t * dx, py + t * dy
    return ((hx - cx) ** 2 + (hy - cy) ** 2) ** 0.5


def main(path, lim=3.0):
    links, plugged = BC.load(path)                # ✓ 复用同一套解释 ✓
    # 已被占用的孔（插了脚 ✓ / 接了线 ✓）—— **这些孔被碰 = 违规 ✓**
    #   （引线那一半在下面统一收 ✓，那里才有 title ✓）
    busy = {}
    for hid, who in plugged.items():
        busy.setdefault(hid, []).append("pin:" + who)
    holes = {}
    z = zipfile.ZipFile(path)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(fz))
    for el in root.iter("instance"):
        if not (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        bv = None
        for c in el.iter():
            if tag(c) == "breadboardView":
                bv = c
        if bv is None:
            continue
        for g in bv.iter():
            if tag(g) != "geometry" or g.get("x2") is None:
                continue
            x, y = float(g.get("x")), float(g.get("y"))
            x2, y2 = float(g.get("x2")), float(g.get("y2"))
            holes[el.findtext("title") or "?"] = ((x, y), (x + x2, y + y2))
    bad = 0
    # ① 先收集"**已占用**的孔" ✓：插了脚的 ✓ + 接了线的 ✓（这两类孔被引线碰 = 违规 ✓）
    busy = {}
    for hid, who in plugged.items():
        busy.setdefault(hid, []).append("pin:" + str(who))
    segs = []
    for lk in links:
        hs = [h for h, _m in lk.holes]
        if len(hs) != 2:                       # 每根实例只有一段 ✓（wire_dump 已验证 ✓）
            continue
        p2, q2 = BC.hole_xy(hs[0]), BC.hole_xy(hs[1])
        if p2 is None or q2 is None:
            continue
        segs.append((getattr(lk, "title", "?"), hs, p2, q2))
        for hid in hs:
            busy.setdefault(hid, []).append("wire:" + str(getattr(lk, "title", "")))
    # ② 逐根量：它的**身子**是否擦/压到别的已占用孔 ✓
    for title, hs, p2, q2 in segs:
        hits = []
        for hid in sorted(busy):               # ★ busy 是"孔 → 为什么被占" ✗ 不是坐标 ✗
            if hid in hs:
                continue                       # 自己的两端不算 ✗
            xy = BC.hole_xy(hid)               # ★ 坐标要问孔表 ✓
            if xy is None:
                continue
            d = seg_dist(p2, q2, xy)
            if d < lim:
                hits.append((d, hid, BC.obscures(p2, q2, xy)))
        if not hits:
            continue
        bad += 1
        print("✗ %s  %s→%s  擦/(压)到已占用的孔 %d 个 ⇒"
              % (title, hs[0], hs[1], len(hits)))
        for d, hid, f in sorted(hits):
            print("      %-8s 中心距 %.2f 单位（= %.2f mm）| 盖住 %5.1f%% | %s | %s"
                  % (hid, d, d * 25.4 / 90.0, f * 100,
                     "✗**重叠**" if d < HOLE_R + WIRE_HALF else "✓未重叠",
                     " ".join(busy[hid][:2])))
    print("合计：%d 根引线擦了已占用的孔 ✗" % bad)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 3.0))
