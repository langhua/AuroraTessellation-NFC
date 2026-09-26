# -*- coding: utf-8 -*-
r"""把一个 .fzz 里**面包板导线**的 `<geometry>` 元素逐条打出来 ✓

目的（2026-09-27 ✓）：钉死 Fritzing 的导线几何口径 ——
  · 折线到底是**一个 geometry 多段** ✗ 还是**多个 geometry** ✓？
  · 每个 geometry 的 `x2/y2` 是**相对 (x,y)** ✓ 还是相对**上一段终点** ✗？
定这个口径是为了修 `render_bb.py`（当时它只画第一段 ✗，图全错 ✗）。

用法：py -3.13 f:\git\_scratch\wire_dump.py <sketch.fzz>
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET


def tag(e):
    return e.tag.split("}")[-1]


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def main(path):
    z = zipfile.ZipFile(path)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(fz))
    n_wire = 0
    for el in root.iter("instance"):
        if not (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        if vw is None:
            continue
        bv = next((c for c in vw if tag(c) == "breadboardView"), None)
        if bv is None:
            continue                      # 只看面包板视图 ✓
        n_wire += 1
        geo = [c for c in bv.iter() if tag(c) == "geometry"]
        we = next((c for c in bv.iter() if tag(c) == "wireExtras"), None)
        con = [c for c in bv.iter() if tag(c) == "connect"]
        print("-- %s  (geometry %d 个, color=%s)"
              % (el.findtext("title") or el.get("modelIndex"), len(geo),
                 (we.get("color") if we is not None else None)))
        for i, g in enumerate(geo):
            print("     [%d] x=%-9s y=%-9s x2=%-9s y2=%-9s  layer=%s"
                  % (i, g.get("x"), g.get("y"), g.get("x2"), g.get("y2"),
                     g.get("layer")))
        for c in con:
            print("     connect: connectorId=%s layer=%s modelIndex=%s"
                  % (c.get("connectorId"), c.get("layer"), c.get("modelIndex")))
    print("面包板导线 %d 根" % n_wire)


if __name__ == "__main__":
    main(sys.argv[1])
