# -*- coding: utf-8 -*-
r"""量 sketch 里各元件的**原理图尺寸**（为"我来排版"做前置取证；只量、不改 ✓）。

量法（三步，都能自证 ✓）：
  1) 元件 → `part.<moduleIdRef>.fzp` → `schematicView/layers/@image` → 对应的 schematic svg ✓
  2) 从 svg 读 ① 根节点 `width/height/viewBox`（元件自身大小 ✓）
     ② 各连接器 `svgId` 指向的元素坐标（引脚在元件里的位置 ✓）
  3) 从 sketch 读"线端 − 元件锚点"（引脚在图上的偏移 ✓，与 pixel_tidy.py 同一套自检 ✓）
     ⇒ 两者一除 = **比例**（各轴、各对引脚都该得到同一个数 ✓ —— 对不上就是量错了 ✗）

用法：py -3.13 tools\part_measure.py <sketch.fzz> [-o 报告.txt]
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET


def resolve_svg(inst_path, base, view="schematic"):
    """包内没有时（core 件不在 .fzz 里 ✓），到本机 Fritzing 目录找 —— **只读** ✓，找不到就 None。"""
    if not base or not inst_path or inst_path.startswith(":/"):
        return None
    d = os.path.dirname(inst_path.replace("/", os.sep))
    for c in (os.path.join(d, view, base),
              os.path.join(d, "..", "svg", view, base),
              os.path.join(d, "..", "svg", "user", view, base),
              os.path.join(d, "..", "svg", "core", view, base)):
        if os.path.isfile(c):
            return c
    return None


def tag(el):
    return el.tag.split("}")[-1]


def child(el, name):
    for c in el:
        if tag(c) == name:
            return c
    return None


def num(s, d=None):
    try:
        return float(s)
    except (TypeError, ValueError):
        return d


def size_in_mil(w):
    """svg 的 width/height **带单位** ⇒ 换算成 sketch 单位（mil，100 = 2.54mm ✓）：
    `in`×1000 ✓；`mm`÷0.0254 ✓；`px`×1000/96 ✓（Fritzing 的 px = 1/96 in ✓）。
    “无单位 / 其他”一律 None ✓（不猜 ✗）。"""
    if not w:
        return None
    t = w.strip().lower()
    v = num(t.rstrip("abcdefghijklmnopqrstuvwxyz"))
    if v is None:
        return None
    if t.endswith("in"):
        return v * 1000.0
    if t.endswith("mm"):
        return v / 0.0254
    if t.endswith("px"):
        return v * 1000.0 / 96.0
    return None


def fmt_mm(mil, size=None):
    if mil is None:
        return "?"
    return "%.2f" % (mil * 0.0254)


def point_of(el):
    """取元素的代表点（并说明取自哪个属性 ✓，不假装精确 ✗）。"""
    a = el.attrib
    if a.get("x") is not None and a.get("y") is not None:
        return num(a["x"]), num(a["y"]), tag(el) + ".x/y"
    if a.get("x1") is not None:
        return num(a["x1"]), num(a["y1"]), tag(el) + ".x1/y1"
    if a.get("cx") is not None:
        return num(a["cx"]), num(a["cy"]), tag(el) + ".cx/cy"
    d = a.get("d") or ""
    m = re.search(r"[Mm]\s*(-?[\d.]+)[,\s]+(-?[\d.]+)", d)
    if m:
        return num(m.group(1)), num(m.group(2)), tag(el) + ".path(起点)"
    return None, None, None


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    src = argv[0]
    out = None
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
    buf = []

    def say(s=""):
        buf.append(s)

    z = zipfile.ZipFile(src)
    fz_name = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(fz_name))

    # ── 1) 元件 → fzp → schematic svg ───────────────────────────────────────
    parts = {}
    for n in z.namelist():
        if n.startswith("part.") and n.endswith(".fzp"):
            r = ET.fromstring(z.read(n))
            img = r.find(".//schematicView/layers")
            base = img.get("image").split("/")[-1] if img is not None else None
            mem = next((m for m in z.namelist() if m.startswith("svg.schematic.")
                        and base and m.endswith(base)), None)
            parts[r.get("moduleId")] = {"fzp": n, "root": r, "svg_base": base, "svg_mem": mem}

    # ── 3) 从 sketch 量"引脚在图上相对元件锚点的偏移" ───────────────────────
    insts, wires = {}, []
    for inst in root.iter("instance"):
        mi = inst.get("modelIndex")
        vw = child(inst, "views")
        sub = child(vw, "schematicView") if vw is not None else None
        if sub is None:
            continue
        geo = child(sub, "geometry")
        conns = [c.attrib for c in sub.iter() if tag(c) == "connect"]
        if geo is not None and geo.get("x1") is not None:
            wires.append((geo, conns))
        elif geo is not None and geo.get("x") is not None:
            insts[mi] = {"title": (inst.findtext("title") or "").strip(),
                         "mid": inst.get("moduleIdRef"), "geo": geo,
                         "path": (inst.get("path") or "")}

    offsets, conflicts = {}, []
    for geo, conns in wires:
        ends = [(num(geo.get("x1")), num(geo.get("y1"))), (num(geo.get("x2")), num(geo.get("y2")))]
        for k in (0, 1):
            if k >= len(conns) or conns[k].get("modelIndex") not in insts:
                continue
            mi = conns[k]["modelIndex"]
            key = (mi, conns[k].get("connectorId"))
            val = (round(ends[k][0] - num(insts[mi]["geo"].get("x")), 4),
                   round(ends[k][1] - num(insts[mi]["geo"].get("y")), 4))
            if key in offsets and offsets[key] != val:
                conflicts.append((key, offsets[key], val))
            offsets[key] = val
    say("配对自检: 冲突 %d 处 %s" % (len(conflicts), "✓" if not conflicts else "✗（量法有问题）"))

    # ── 2) 逐元件：svg 尺寸 + 引脚 svg 坐标，与图上偏移对照 ─────────────────
    for mi, d in sorted(insts.items(), key=lambda kv: kv[1]["title"]):
        p = parts.get(d["mid"])
        if p is None and d["path"] and not d["path"].startswith(":/"):
            # core 件（电阻/电容/面包板…）不在 .fzz 里 ✓ ⇒ 按实例给的**绝对路径**读它的 .fzp（只读 ✓）
            fp = d["path"].replace("/", os.sep)
            if os.path.isfile(fp):
                r2 = ET.fromstring(open(fp, encoding="utf-8", errors="replace").read())
                img = r2.find(".//schematicView/layers")
                p = {"fzp": fp, "root": r2,
                     "svg_base": (img.get("image").split("/")[-1] if img is not None else None),
                     "svg_mem": None}
        where, svg_txt = None, None
        if p and p["svg_mem"]:
            where, svg_txt = "包内", z.read(p["svg_mem"]).decode("utf-8", "replace")
        elif p:
            f = resolve_svg(d["path"], p["svg_base"])
            if f:
                where = "本机Fritzing"
                svg_txt = open(f, encoding="utf-8", errors="replace").read()
        if svg_txt is None:
            say("\n%-10s %-30s ⇒ 找不到 schematic svg ✗（跳过）" % (d["title"], d["mid"]))
            continue
        sroot = ET.fromstring(svg_txt)
        vb = (sroot.get("viewBox") or "").split()
        say("\n%-10s %-30s  [%s]" % (d["title"], d["mid"], where))
        say("   svg: %s  width=%s height=%s viewBox=%s"
            % (p["svg_base"], sroot.get("width"), sroot.get("height"), sroot.get("viewBox")))
        say("   元件在画布上的尺寸 ≈ %s（mil）≈ %s mm"
            % (size_in_mil(sroot.get("width")), fmt_mm(size_in_mil(sroot.get("width")))))
        if len(vb) == 4:
            say("   元件自身尺寸: %s × %s（svg 单位）" % (vb[2], vb[3]))

        # svg 里 id → 坐标（并记"祖先里有没有变换" ✓ —— 有的话数字没折进去 ✗，要标注）
        idpts = {}

        def walk(el, tfdepth):
            for c in el:
                d2 = tfdepth + 1 if (tag(c) == "g" and c.get("transform")) else tfdepth
                i = c.get("id")
                if i:
                    px, py, how = point_of(c)
                    if px is not None:
                        idpts[i] = (px, py, how, d2)
                walk(c, d2)
        walk(sroot, 0)

        # 连接器 → 候选 svg 元素 id（**terminalId 优先** ✓ —— Fritzing 的连线接在 terminal 上 ✓；
        # 拿 pin 的角去量会差一截 ✗）
        c2svg = {}
        for c in p["root"].iter("connector"):
            vws = child(c, "views")
            sch = child(vws, "schematicView") if vws is not None else None
            ids = []
            for e in (list(sch) if sch is not None else []):
                if e.get("terminalId"):
                    ids.append(e.get("terminalId"))
                if e.get("svgId"):
                    ids.append(e.get("svgId"))
            if ids:
                c2svg[c.get("id")] = ids

        got = []
        for (m2, cid), (dx, dy) in sorted(offsets.items()):
            if m2 != mi:
                continue
            hit = None
            for sid in c2svg.get(cid, []):
                if sid in idpts:
                    hit = (sid,) + idpts[sid]
                    break
            if hit is None:
                continue
            sid, sx, sy, how, tfdepth = hit
            got.append((cid, sid, sx, sy, how + (" +g×%d" % tfdepth if tfdepth else ""), dx, dy))
        if not got:
            say("   （没量到引脚：该元件的脚没接线，或 svgId 没在 svg 里 ✓）")
            continue
        say("   脚            svgId               svg坐标           图上偏移(mil)      比例")
        for cid, sid, sx, sy, how, dx, dy in got[:6]:
            say("   %-12s %-18s (%8.2f,%8.2f) (%8.2f,%8.2f) %s"
                % (cid, sid, sx, sy, dx, dy, how))
        # 比例：用两个脚相减（消掉原点偏移 ✓）
        if len(got) >= 2:
            ratios = []
            for i in range(len(got) - 1):
                sdx = got[i + 1][2] - got[i][2]
                sdy = got[i + 1][3] - got[i][3]
                ddx = got[i + 1][5] - got[i][5]
                ddy = got[i + 1][6] - got[i][6]
                if abs(sdx) > 1e-6:
                    ratios.append(("x", ddx / sdx))
                if abs(sdy) > 1e-6:
                    ratios.append(("y", ddy / sdy))
            if ratios:
                say("   ⇒ 图上/svg 比例: %s" % ", ".join("%s=%.6f" % r for r in ratios[:6]))

    txt = "\n".join(buf)
    print(txt)
    if out:
        open(out, "w", encoding="utf-8").write(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
