# -*- coding: utf-8 -*-
r"""★ 摆位**突变**集 ✓：**旋转** ✓ 与 **多件联挪** ✓（单件平移 / 翻面在别处 ✓）

★ 为什么单开一个模块 ✗：`place_drv.py` 原来只有"单件平移 + 翻面" ✗ ⇒ 用户 2026-10-06 定：
  **加旋转（步长 15° ✓，90° 太粗 ✗）＋ 加双件联挪** ✓。

★★ 矩阵口径**复用库** ✓（`part_box` 的 6 元组 SVG 约定 `[a,b,c,d,e,f]` = `(m11,m12,m21,m22,m31,m32)`
  ✓、`mul/apply` ✓）—— ✗ 不另写一份矩阵数学 ✗（仓规 §5b ⑨ ②：抄一份就多一个错处 ✓）。
  ★ 但 `.fz` 里 `<transform>` 是**属性写法**（`m11="…"` ✓）而**不是** `matrix(…)` 串 ✗
    ⇒ 读它照 `pcb_pads.tf_of` 的**同一口径**（缺省 = 单位阵 ✓）。

★★ 旋转中心 = **该件全部焊盘的重心** ✓（从 `pcb_check.collect` 的**板坐标**算 ✓）——
  绕"板原点"转会把件甩到板外 ✗；绕"元件框中心"又要另算包围盒 ✗。
★ 数学 ✓（`loc` = `<geometry x/y>` ✓、`M` = 它里面的 `<transform>` ✓、板点 `p = loc + M·u` ✓）：
  要 `p' = c + R·(p − c)` ⇒ **`M' = R·M`** ✓、**`loc' = c + R·(loc − c)`** ✓。
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)


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
sys.path.insert(0, HERE)

import part_box as PB          # noqa: E402
import pcb_check as PC         # noqa: E402
import pcb_route as RT         # noqa: E402
from nudge_sweep2 import fz_text, nudge    # noqa: E402  ★ 单件平移**一个实现** ✓

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _num(s, k, d=0.0):
    m = re.search(r'\b%s="([-0-9.eE]+)"' % k, s or "")
    return float(m.group(1)) if m else d


def tf_attrs(s):
    """`.fz` 的 `<transform m11="…" m33="1"/>` ⇒ 6 元组 ✓（缺失 ⇒ 单位阵 ✓）。"""
    if not s:
        return IDENT
    return (_num(s, "m11", 1), _num(s, "m12", 0), _num(s, "m21", 0),
            _num(s, "m22", 1), _num(s, "m31", 0), _num(s, "m32", 0))


def tf_xml(m):
    return ('<transform m11="%.6f" m12="%.6f" m13="0" m21="%.6f" m22="%.6f" '
            'm23="0" m31="%.6f" m32="%.6f" m33="1"/>'
            % (m[0], m[1], m[2], m[3], m[4], m[5]))


def _R(deg):
    a = math.radians(deg)
    return (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0.0, 0.0)


def centre_of(src, title):
    """该件**全部焊盘的重心** ✓（板坐标 sketch 单位 ✓）⇒ `(cx, cy, 焊盘数)` ✓。"""
    m = PC.collect(src)
    pads = RT.pad_index(m)
    cs = [q["c"] for (t, _c), q in pads.items() if t == title]
    if not cs:
        raise SystemExit("✗ %s 在板上没有焊盘 ⇒ 不转 ✓" % title)
    return (sum(p[0] for p in cs) / len(cs), sum(p[1] for p in cs) / len(cs), len(cs))


def rot_text(text, title, deg, c):
    """把某实例的 PCB 摆放位**绕 `c` 转 `deg` 度** ✓（只动第一个 `<geometry>` ✓）。"""
    R = _R(deg)
    for mm in re.finditer(r"<instance\b", text):
        end = text.find("</instance>", mm.start())
        if end < 0:
            continue
        blk = text[mm.start():end]
        if ("<title>%s</title>" % title) not in blk:
            continue
        v0 = blk.find("<pcbView")
        v1 = blk.find("</pcbView>", v0)
        view = blk[v0:v1]
        g0 = view.find("<geometry")
        if g0 < 0:
            raise SystemExit("✗ %s 的 pcbView 里没有 <geometry> ✓" % title)
        g_close = view.find("</geometry>", g0)
        selfclose = g_close < 0
        if selfclose:
            g_close = view.find("/>", g0)
        open_end = view.find(">", g0)
        open_tag = view[g0:open_end + 1]
        inner = "" if selfclose else view[open_end + 1:g_close]
        # ① 位置：loc' = c + R·(loc − c) ✓
        loc = (_num(open_tag, "x"), _num(open_tag, "y"))
        dx, dy = PB.apply(R, loc[0] - c[0], loc[1] - c[1])
        new_open = re.sub(r'\bx="[-0-9.eE]+"', 'x="%.6f"' % (c[0] + dx), open_tag, count=1)
        new_open = re.sub(r'\by="[-0-9.eE]+"', 'y="%.6f"' % (c[1] + dy), new_open, count=1)
        # ② 姿态：M' = R·M ✓
        M2 = PB.mul(R, tf_attrs(re.search(r"<transform\b[^>]*/>", inner).group(0)
                                if re.search(r"<transform\b[^>]*/>", inner) else ""))
        if re.search(r"<transform\b[^>]*/>", inner):
            new_inner = re.sub(r"<transform\b[^>]*/>", tf_xml(M2), inner, count=1)
        else:
            new_inner = "\n                        " + tf_xml(M2) + inner
        new_view = view[:g0] + new_open + new_inner + ("</geometry>" if not selfclose else "") \
            + view[g_close + (2 if selfclose else 11):]
        # ★ 顺带把**位号**也绕同一个心转 ✓（✗ 不然标签会歪在原地 ✗）
        m2 = re.search(r"<titleGeometry\b[^>]*>.*?</titleGeometry>", new_view, re.S)
        if m2:
            tb = m2.group(0)
            tf = re.search(r"<transform\b[^>]*/>", tb)
            t2 = PB.mul(R, tf_attrs(tf.group(0) if tf else ""))
            nb = (re.sub(r"<transform\b[^>]*/>", tf_xml(t2), tb, count=1) if tf
                  else tb.replace("/>", ">\n" + tf_xml(t2), 1))
            new_view = new_view[:m2.start()] + nb + new_view[m2.end():]
        return text[:mm.start()] + blk[:v0] + new_view + blk[v1:] + text[end:]
    raise SystemExit("✗ 找不到实例 %s ✓" % title)


def _rewrite(src, dst, text):
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as w:
        for n in z.namelist():
            w.writestr(n, text.encode("utf-8") if n == name else z.read(n))
    z.close()
    return dst


def rot_zip(src, dst, title, deg):
    """★ 转一个件 ✓（绕**它自己焊盘的重心** ✓）。"""
    _name, text = fz_text(src)
    cx, cy, n = centre_of(src, title)
    return _rewrite(src, dst, rot_text(text, title, deg, (cx, cy))), (cx, cy, n)


def joint_zip(src, dst, moves):
    """★ **多件联挪** ✓：`moves = [(件, dx_mm, dy_mm), …]` ✓ 一次改完再落盘 ✓。"""
    _name, text = fz_text(src)
    for title, dx, dy in moves:
        text = nudge(text, title, dx, dy)
    return _rewrite(src, dst, text)


def main(argv):
    if len(argv) >= 5 and argv[0] == "rot":
        out, c = rot_zip(argv[1], argv[2], argv[3], float(argv[4]))
        print("✓ %s ⇒ %s（绕焊盘重心 (%.3f, %.3f) mm，%d 个焊盘 ✓）"
              % (argv[3], os.path.basename(out), c[0] * 0.28222, c[1] * 0.28222, c[2]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
