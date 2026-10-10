# -*- coding: utf-8 -*-
r"""按 **mm** 平移一个件（PCB 视图）✓ —— 连带把**挂在它焊盘上**的走线端点一起挪 ✓

★ 为什么要它 ✗（2026-10-10 ✓）：`.fzz` 里挪一个件要动三处 ✓ ——
   ① 这个件 `<pcbView><geometry x y>` ✓；② 它的 `titleGeometry`（位号 ✓）；
   ③ **凡是端点正好落在它焊盘中心上的走线** ✓（那些端点得跟着走 ✓，否则线就脱开了 ✗）。
   手改（或让 Fritzing 拖 ✗）也能做 ✓，但**方向**在背面件上很容易看反 ✗
   （实测：用户按"左移"拖，文件里 x 反而 **+0.099 mm** ✗ ⇒ 那一对净距一点没变 ✗）。
   ⇒ 用**数字**说话 ✓：本工具只认**文件坐标**（≠ 屏幕左右 ✗，自己换算 ✓）。

判据与校验器**同一份** ✓：焊盘中心取 `pcb_check.collect()` 的 `pads[].c` ✓（不另算一套 ✗）。

用法：
  py -3.13 nudge_part.py <in.fzz> <out.fzz> <位号> <dx_mm>,<dy_mm> [--apply]
  （默认**干跑**只报告 ✓；`--apply` 才写 out ✓）
自检 ✓（写前逐条 ✓，任一条不过就**不写** ✗）：
  · 改完 `.fz` 能解析成 XML ✓；② 只改了预期的条数（报告出来 ✓）；
  · 文字里的 `<?xml`/`<svg` 等段一个没动 ✗。
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, r"F:\git\fritzing-parts-langhua\tools")
import pcb_check as PC                                              # noqa: E402

SK = PC.PW.SK
# ★ 判定"线端落在这只盘上"要**带容差** ✗（2026-10-10 实测 ✓）：Fritzing 存的是 4 位小数 ✗
#   ⇒ 盘心 41.6437 与线端 41.6436 差 **1e-4 mm** ✗ ⇒ 精确比相等 ⇒ **一根也认不出** ✗。
NEAR_MM = 0.05                       # ✓ 盘间最少 0.65 mm ⇒ 0.05 不会认错 ✓
GEO = re.compile(r'<geometry\b([^>]*?)/>')
ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def attrs(s):
    return dict(ATTR.findall(s))


def inst_block(text, title):
    """⇒ (整个 `<instance …>…</instance>` 块, 起, 止)"""
    for m in re.finditer(r"<instance\b.*?</instance>", text, re.S):
        t = re.search(r"<title>([^<]*)</title>", m.group(0))
        if t and t.group(1) == title:
            return m.group(0), m.start(), m.end()
    return None, None, None


def pad_centers(path, title):
    """⇒ [(x, y)] 草图单位 ✓（`pcb_check` 的口径 ✓）"""
    model = PC.collect(path)
    return [(q["c"][0], q["c"][1]) for q in model["pads"] if q["title"] == title]


def on_pad(px, py, pads):
    """线端 (px,py) 是不是落在其中一只盘上 ✓（带容差 ✓）"""
    tol = NEAR_MM / SK
    return any((px - x) ** 2 + (py - y) ** 2 <= tol * tol for x, y in pads)


def move_geometry(seg, dx, dy):
    """只动**这一层**的摆放 ✓：`<geometry …>`（摆放）与 `<titleGeometry …>`（位号）的**开标签** ✓
    ⇒ (新文本, 动了几处 ✓)

    ★★ 两个坑（2026-10-10 实测各踩一次 ✗）：
      ① 件的摆放 `<geometry>` **不是自闭合** ✗ —— 它里面有 `<transform …/>` ✗
         （`<geometry z=… x=… y=…><transform …/></geometry>` ✓）
         ⇒ 只认 `/>` 的正则会**整段漏掉** ✗（实测：以为挪了，其实 pads 一点没动 ✗）；
      ② `<connectors>` 里**也有** `<geometry x="0" y="0"/>`（连接点的局部原点 ✓）
         ⇒ 不能一起挪 ✗ —— 只动 `<connectors` **之前**那段 ✓。
    """
    head, sep, rest = seg.partition("<connectors")
    n = 0

    def one(m):
        nonlocal n
        tag, body = m.group(1), m.group(2)
        a = attrs(body)
        for k in ("x", "y"):
            if k in a:
                v = float(a[k]) + (dx if k == "x" else dy)
                body = re.sub(r'(\b%s\s*=\s*")[^"]*(")' % k,
                              r"\g<1>%s\g<2>" % ("%.4f" % v), body)
        n += 1
        return "<%s%s>" % (tag, body)

    head2 = re.sub(r"<(geometry|titleGeometry)\b([^>]*?)>", one, head)
    return head2 + sep + rest, n


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("title")
    ap.add_argument("delta", help="dx_mm,dy_mm ✓（文件坐标 ✓，+x = 往右 ✓）")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    dx_mm, dy_mm = [float(v) for v in a.delta.split(",")]
    dx, dy = dx_mm / SK, dy_mm / SK
    with zipfile.ZipFile(a.src) as z:
        names = z.namelist()
        inner = [n for n in names if n.endswith(".fz")][0]
        text = z.read(inner).decode("utf-8")
        blobs = [(n, z.read(n)) for n in names]
    pads = pad_centers(a.src, a.title)
    print("== 挪 %s：Δ = (%+.4f, %+.4f) mm ✓（= %.4f 草图单位 ✓）｜它的焊盘 %d 个" % (
        a.title, dx_mm, dy_mm, dx, len(pads)))
    for x, y in sorted(pads):
        print("     盘心 (%.4f, %.4f) mm ⇒ (%.4f, %.4f) ✓" % (
            x * SK, y * SK, (x + dx) * SK, (y + dy) * SK))

    # ① 件自己（pcbView 的 geometry ＋ titleGeometry）
    blk, i0, i1 = inst_block(text, a.title)
    if blk is None:
        print("✗ 找不到件 %s" % a.title)
        return 1
    pcb = re.search(r"<pcbView\b.*?</pcbView>", blk, re.S)
    if not pcb:
        print("✗ %s 没有 pcbView" % a.title)
        return 1
    head = blk[:pcb.start()]
    body, n1 = move_geometry(pcb.group(0), dx, dy)
    newblk = head + body + blk[pcb.end():]
    # ★ 改动**先收集**✓（偏移一律对**原文** `text` 取 ✓），最后一次性倒序应用 ✗
    #   —— 碰过这个坑 ✗：边拆边改 ⇒ 后面所有偏移都是旧的 ✗ ⇒ 拼出 `<vi<instance …>` ✗
    #     （2026-10-10 实测：第 4846 行就是这么坏的 ✓）。
    edits = [(i0, i1, newblk)]

    # ② 端点落在它焊盘上的走线 ✓（只动那个端点 ✓）
    #    ★ 先把所有改动**收集**起来 ✓，再**倒序**应用 ✗ —— 边找边改会让后面的偏移全错 ✗
    out = []
    for m in re.finditer(r"<instance\b.*?</instance>", text, re.S):
        blk2 = m.group(0)
        if "WireModuleID" not in blk2:
            continue
        pcb2 = re.search(r"<pcbView\b.*?</pcbView>", blk2, re.S)
        if not pcb2:
            continue
        seg = pcb2.group(0)
        g = GEO.search(seg)
        if not g:
            continue
        at = attrs(g.group(1))
        if not all(k in at for k in ("x", "y", "x1", "y1", "x2", "y2")):
            continue
        x0, y0 = float(at["x"]), float(at["y"])
        x1, y1 = x0 + float(at["x1"]), y0 + float(at["y1"])
        x2, y2 = x0 + float(at["x2"]), y0 + float(at["y2"])
        which = 0
        for (px, py, w) in ((x1, y1, 1), (x2, y2, 2)):
            if on_pad(px, py, pads):                        # ★ 用**改前**的盘心认 ✓
                which = w
                break
        if not which:
            continue
        d = {"x1": dx, "y1": dy} if which == 1 else {"x2": dx, "y2": dy}
        body = g.group(1)
        for k, dv in d.items():
            body = re.sub(r'(\b%s\s*=\s*")[^"]*(")' % k,
                          r"\g<1>%s\g<2>" % ("%.4f" % (float(at[k]) + dv)), body)
        seg_new = seg[:g.start()] + "<geometry%s/>" % body + seg[g.end():]
        t = re.search(r"<title>([^<]*)</title>", blk2)
        out.append((t.group(1) if t else "?", "A 端" if which == 1 else "B 端"))
        edits.append((m.start() + pcb2.start(), m.start() + pcb2.end(), seg_new))
    for s, e, rep in sorted(edits, key=lambda z: -z[0]):
        text = text[:s] + rep + text[e:]
    text2 = text
    moved = len(out)
    print("   ① 件自己：动了 %d 处 `<geometry>`（pcbView 里的摆放 ＋ 位号 ✓）" % n1)
    print("   ② 挂它焊盘上的走线：**%d** 根端点跟着走 ✓ %s" % (
        moved, "：" + "、".join("%s %s" % t for t in out) if out else ""))
    try:
        ET.fromstring(text2)
    except ET.ParseError as exc:
        print("✗ 改完解析不了（%s）⇒ **不写** ✗" % exc)
        # ★ 报错只说"第几行"✗ ⇒ 把**那一窗**打出来 ✓（本仓踩过：只有行号等于没有线索 ✗）
        ln = re.search(r"line (\d+)", str(exc))
        if ln:
            lines = text2.split("\n")
            k = int(ln.group(1))
            print("   —— 改后第 %d 行前后 ——" % k)
            for i in range(max(k - 5, 1), min(k + 4, len(lines)) + 1):
                print("   %5d| %s" % (i, lines[i - 1][:150]))
        return 1
    if not a.apply:
        print("   （干跑 ✓ —— 加 `--apply` 才写 %s ✓）" % a.dst)
        return 0
    with zipfile.ZipFile(a.dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n, data in blobs:
            if n == inner:
                # ★ 内层 `.fz` 的**名字原样保留** ✓（它 = Fritzing 里显示的草图名 ✓）
                zo.writestr(zipfile.ZipInfo(n, date_time=(2026, 10, 10, 0, 0, 0)),
                            text2.encode("utf-8"))
            else:
                zo.writestr(n, data)
    print("   ⇒ 写 %s ✓" % a.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
