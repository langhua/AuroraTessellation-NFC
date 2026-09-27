# -*- coding: utf-8 -*-
r"""像素板原理图 **v1：只摆元件**（干净画布 ✓，无线 ✓）—— 接力第一手 ✓

约定（用户 2026-09-27 定 ✓）：
  · 第一版**只摆元件** ✓（接线是下一手 ✓，交给既有管线 `gen_schematic_wires.py` ✓）；
  · 摆位口径照 netlist §4「左 → 右」+ 用户加的拓扑语义：
      主链一条水平线 `J1(上游) → U1 → J2(下游)` ✓
      采集支路（`L1 → D3 → R1/C1` ✓ 只接 `U1.PA1` ✓ 不是主链 ✗）**下沉**到 U1 左下方 ✓
      去耦 `C2` **贴 U1 正上方** ✓；`LED2`（本地指示灯 ✓）在 `U1` 右侧 ✓
  · 坐标**吸附 Fritzing 原理图网格**：0.1in = **7.2 单位**（原理图 1 单位 = 1/72 in ✓，
    由用户导出的 `pixel-schematic_图示.svg` 头部取证 ✓：`371.41×217.902` 单位 = 5.16×3.03 in ✓）
  · 块间留 ≥100 单位（≈35mm ✓）—— 各件 svg 的**原点不一定居中** ✗（实测 U1 锚点 266.4、
    符号画出范围约 228…280 ✓）⇒ 宁可留宽 ✓，不赌 ✗。

本版**只改两件事** ✓：
  ① 每个元件在 `schematicView` 里的 `<geometry x y>` ✓；
  ② **删掉原理图导线** ✓（只删 `Wire*` 实例的 `<schematicView>` 子树 ✓；
     **面包板视图一根不动** ✓ —— 那份是布线管线的输入 ✓）。
源文件**不改** ✓；输出另存一份 ✓。

用法：py -3.13 gen_schematic_layout.py <源.fzz> <输出.fzz> [版本号]
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

GRID = 7.2          # 0.1in ✓（原理图 1 单位 = 1/72 in ✓）

# ── 摆位表（sketch 单位 ✓；y 向**下**为正 ✓ —— 见 dump：J1 y=-132 在最上方 ✓）──
#   每个值都是 7.2 的整数倍 ✓（= 落在 Fritzing 原理图网格上 ✓）
POS = {
    # 主链（y = 0 ✓，一条水平线 ✓）
    "J1":   (0,     0),      # 上游接口 ✓ 最左
    "U1":   (360.0, 0),      # MCU ✓ 中间
    "LED2": (540.0, 0),      # 本地指示灯 ✓ U1 右侧
    "J2":   (720.0, 0),      # 下游接口 ✓ 最右
    # 去耦（贴 U1 正上方 ✓）
    "C2":   (360.0, -100.8),
    # 采集支路（下沉到 U1 左下方 ✓）
    "L1":   (36.0,  129.6),
    "D3":   (180.0, 129.6),
    "R1":   (288.0, 129.6),
    "C1":   (288.0, 201.6),
}


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def main(src, dst):
    zin = zipfile.ZipFile(src)
    fzname = [n for n in zin.namelist() if n.endswith(".fz")][0]
    raw = zin.read(fzname).decode("utf-8")
    root = ET.fromstring(raw)
    moved, dropped = [], []
    for el in root.iter("instance"):
        vw = child(el, "views")
        sub = child(vw, "schematicView") if vw is not None else None
        if sub is None:
            continue
        mid = el.get("moduleIdRef") or ""
        ttl = (el.findtext("title") or "").strip()
        if mid.startswith("Wire"):
            vw.remove(sub)                      # ★ 只删原理图导线 ✓（面包板视图不动 ✓）
            dropped.append(ttl)
            continue
        if ttl not in POS:
            continue                            # 没点名的（Breadboard1 等）**一个字不动** ✗
        x, y = POS[ttl]
        x = round(x / GRID) * GRID              # ★ 吸附网格 ✓
        y = round(y / GRID) * GRID
        g = child(sub, "geometry")
        if g is None:
            continue
        g.set("x", "%g" % x)
        g.set("y", "%g" % y)
        # ★★ 位号文字**必须一起搬** ✗✗（2026-09-27 v1 踩坑 ✓：只搬 geometry ⇒ 位号留在原地 ✗，
        #    渲染出来就是"标签四处乱飘" ✗ —— 是 `render_sch.py` 一眼看出来的 ✓）。
        #    关系（机验 ✓）：`titleGeometry.(x,y) = geometry.(x,y) + titleGeometry.(xOffset,yOffset)`
        #    （实测 U1：266.35+97.2=363.55 ✓、J1：0+19.842=19.842 ✓、y：0+(-14)=-14 ✓）。
        tg = child(sub, "titleGeometry")
        if tg is not None and (tg.get("visible") or "true") != "false":
            ox = float(tg.get("xOffset") or 0.0)
            oy = float(tg.get("yOffset") or 0.0)
            tg.set("x", "%g" % (x + ox))
            tg.set("y", "%g" % (y + oy))
        moved.append((ttl, x, y))
    out = ET.tostring(root, encoding="utf-8", xml_declaration=False).decode("utf-8")

    # ★ 与源保持一致：ET 会丢掉声明/换行风格 ⇒ 用**源文本 + 定点替换**太脆 ✗；
    #   这里直接以 ET 结果为准 ✓（Fritzing 读得进即可 ✓），但**必须**保留包内其它成员 ✓。
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zin.namelist():
            if n == fzname:
                zo.writestr(n, out)
            else:
                zo.writestr(n, zin.read(n))

    print("== 原理图 v1（只摆元件 ✓）：%s" % dst)
    print("   摆放 %d 件（网格 0.1in = %g 单位 ✓）：" % (len(moved), GRID))
    for t, x, y in sorted(moved, key=lambda r: (r[2], r[1])):
        print("      %-6s x=%7.1f  y=%7.1f" % (t, x, y))
    print("   删掉原理图导线 %d 根 ✓（面包板视图与其它成员**原样保留** ✓）" % len(dropped))
    miss = [t for t in POS if t not in [m[0] for m in moved]]
    if miss:
        print("   ✗ 摆位表里这些位号在图中**没找到**：%s" % ", ".join(miss))


if __name__ == "__main__":
    a = sys.argv[1], sys.argv[2]
    main(*a)
