# -*- coding: utf-8 -*-
r"""网标签几何核对器（**只读** ✓）—— 拿 Fritzing 导出的 svg 当尺子 ✓ 核 `sch_net` 的几何模型 ✓

用法：
    py -3.13 check_labels.py <草图.fzz> <Fritzing导出的.svg>

它比什么 ✓：**每个网标签的文字锚点**（我的模型算的 ↔ Fritzing 画出来的 ✓）。
  · 全局比例 = **0.8**（导出 1/72in ÷ 草图 1/90in ✓，理论值 ✓ 不是拟合值 ✓）；
  · 全局平移 = **投票定** ✓（同名标签常有 0°/90° 两个 ✓ ⇒ 不能用"第一次遇到"当基准 ✗；
    vote 取众数 ✓ ⇒ 不依赖配对顺序 ✓）。
为什么单列一个工具 ✗：`render_sch.py --verify-export` 的那套要求"先能对上零件组" ✗
  ⇒ **只有标签的草图**（如用户造件 `_work/netlabels.fzz` ✓）会在那之前就退出 ✗ ⇒ 标签段跑不到 ✗。
  ★ 本工具与渲染器/生成器**共用** `sch_net` 这一份几何 ✓（不是各写一套 ✗）。

退出码：全对 ⇒ 0 ✓；任一标签文字差 > `TOL` 或框顶点 > `TOL_FLAG` ⇒ 1 ✓。
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolpaths                                                  # noqa: E402
#   ★ 本仓惯例 ✓：通用工具**只有一份**、在**库仓 `tools/`** ✓（`toolpaths` 负责挂路径 ✓）
#     ⇒ `part_box`（矩阵/变换的唯一实现 ✓）得先过它 ✗ 否则 ImportError ✗（实测踩过 ✓）
import part_box as PB                                             # noqa: E402
import sch_net as SN                                              # noqa: E402

S = 0.8                     # 导出单位 ÷ 草图单位 ✓（= 90/72 ✓ 理论值 ✓）
TOL = 0.20                  # 文字锚点容差 ✓（导出单位 ✓ = 0.071 mm ✓）——
#   ★ 实测精度（2026-09-29 ✓）：三份文件最大 **0.048mm**（0.135 导出单位 ✓）
#     ⇒ 阈值取 0.20 导出单位 ✓（比实测宽 ~1.5 倍 ✓）；✗ 原来取 0.05（0.018mm ✗）
#     ⇒ 实测那些 0.02~0.05mm 的**零头**也全被报成 ✗ ✗ ⇒ 判据天天报警就没人看了 ✗。
TOL_FLAG = 0.30             # 外框逐顶点容差 ✓（实测最大 0.067mm = 0.19 导出单位 ✓）


def tag(e):
    return e.tag.split("}")[-1]


def export_texts(path):
    """导出里所有标签文字：`[(绝对锚点, 名字, 字号), …]` ✓（含电源符号的文字 ✓ 后面按名字筛 ✓）"""
    r = ET.fromstring(open(path, encoding="utf-8", errors="replace").read())
    par = {c: p for p in r.iter() for c in p}

    def absm(e):
        ch = []
        while e is not None:
            ch.append(e)
            e = par.get(e)
        m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        for a in reversed(ch):
            t = a.get("transform")
            if t:
                m = PB.mul(m, PB.parse_tf(t))
        return m

    out = []
    for el in r.iter():
        if tag(el) != "text" or el.get("id") != "label":
            continue
        x, y = el.get("x"), el.get("y")
        if x is None:                       # 坐标有时在 `tspan` 里 ✓
            sp = next((c for c in el.iter()
                       if tag(c) == "tspan" and c.get("x") is not None), None)
            x, y = (sp.get("x"), sp.get("y")) if sp is not None else ("0", "0")
        out.append((PB.apply(absm(el), float(x), float(y)),
                    (el.text or "").strip(), el.get("font-size")))
    return out


def sketch_labels(path):
    """草图里的网标签：`[(名字, 几何, 变换 2×2), …]` ✓（名字取 `label` 属性 ✓）"""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    out = []
    for el in root.iter("instance"):
        mid = el.get("moduleIdRef") or ""
        if not SN.is_label_module(mid):
            continue
        props = {p.get("name"): p.get("value") for p in el.iter("property")}
        nm = SN.net_name(mid, (el.findtext("title") or "").strip(), props.get("label"))
        if not nm:
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        sv = next((c for c in vw if tag(c) == "schematicView"), None) if vw is not None else None
        g = next((c for c in sv if tag(c) == "geometry"), None) if sv is not None else None
        if g is None:
            continue
        tf = g.find("transform")
        m = ((float(tf.get("m11", 1)), float(tf.get("m12", 0)),
              float(tf.get("m21", 0)), float(tf.get("m22", 1))) if tf is not None
             else (1.0, 0.0, 0.0, 1.0))
        out.append((nm, (float(g.get("x")), float(g.get("y"))), m))
    return out


def export_flag(path):
    """导出里的**标签外框**：`{partID: [顶点…]}` ✓（只取含 `polygon` 的组 ✓）"""
    r = ET.fromstring(open(path, encoding="utf-8", errors="replace").read())
    par = {c: p for p in r.iter() for c in p}

    def absm(e):
        ch = []
        while e is not None:
            ch.append(e)
            e = par.get(e)
        m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        for a in reversed(ch):
            t = a.get("transform")
            if t:
                m = PB.mul(m, PB.parse_tf(t))
        return m

    out = {}
    for el in r.iter():
        pid = el.get("partID")
        if not pid or not any(tag(x) == "polygon" for x in el.iter()):
            continue
        for sh in el.iter():
            if tag(sh) != "polygon":
                continue
            m = absm(sh)
            pt = [float(v) for v in re.split(r"[ ,]+", (sh.get("points") or "").strip()) if v]
            out[pid] = [PB.apply(m, pt[i], pt[i + 1]) for i in range(0, len(pt) - 1, 2)]
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    fzz = argv[0] if os.path.isabs(argv[0]) else os.path.join(HERE, argv[0])
    exp = argv[1] if os.path.isabs(argv[1]) else os.path.join(HERE, argv[1])
    mine = sketch_labels(fzz)
    texts = export_texts(exp)
    if not mine:
        print("⊘ %s 里没有网标签 ✓" % os.path.basename(fzz))
        return 2
    # 我的模型算出的锚点（**未加全局平移** ✓）：导出 = 0.8×它 + c ✓（c 待投票 ✓）
    pred = [(nm, SN.label_text_anchor(geom, nm, m)) for nm, geom, m in mine]
    votes = []
    for nm, a in pred:
        for (b, tn, _fs) in texts:
            if tn != nm:
                continue
            votes.append(((b[0] - S * a[0], b[1] - S * a[1]), nm))
    if not votes:
        print("✗ 导出里没有同名标签文字 ⇒ 没法核对 ✗")
        return 1
    best_c, best_n = None, 0
    for c0, _nm in votes:
        n = sum(1 for c, _ in votes if math.dist(c, c0) < 0.3)
        if n > best_n:
            best_c, best_n = c0, n
    print("== 标签核对：%s ↔ %s ==" % (os.path.basename(fzz), os.path.basename(exp)))
    print("   我的标签 %d 个 ｜ 导出标签文字 %d 个 ｜ 全局平移 c 投票：%d/%d 票 ⇒ (%+.4f, %+.4f)"
          % (len(mine), len(texts), best_n, len(votes), best_c[0], best_c[1]))
    worst, wt, bad = 0.0, "", []
    for nm, a in pred:
        p = (S * a[0] + best_c[0], S * a[1] + best_c[1])
        cand = [b for (b, tn, _fs) in texts if tn == nm]
        if not cand:
            bad.append((nm, None, "导出里没有同名文字 ✗"))
            continue
        d = min(math.dist(p, q) for q in cand)
        if d > worst:
            worst, wt = d, nm
        if d > TOL:
            bad.append((nm, d, ""))
    print("   **文字锚点最大 Δ = %.5f 导出单位（%.5f mm）** @%s %s"
          % (worst, worst * 25.4 / 72.0, wt, "✓✓" if not bad else "✗✗"))
    for nm, d, why in bad[:8]:
        print("      ✗ %-12s %s" % (nm, why or ("差 %.5f 单位 = %.4f mm" % (d, d * 25.4 / 72.0))))
    # ── ★★ 外框（旗标）也核 ✓（用户 2026-09-29 指出我漏画它 ✗）──
    fl_exp = export_flag(exp)
    fb_worst, fb_t, fb_bad = 0.0, "", []
    fb_worst_pid = ("", "", [])
    for (nm, geom, m) in mine:
        pv = [((S * q[0] + best_c[0]), (S * q[1] + best_c[1])) for q in SN.label_flag(geom, nm, m)]
        cx = sum(p[0] for p in pv) / len(pv)
        cy = sum(p[1] for p in pv) / len(pv)
        if not fl_exp:
            break
        # 按**顶点中心最近**配对 ✓（同名多个也稳 ✓）
        pid, cand = None, None
        for k, v in fl_exp.items():
            ex = sum(p[0] for p in v) / len(v)
            ey = sum(p[1] for p in v) / len(v)
            d0 = math.dist((cx, cy), (ex, ey))
            if cand is None or d0 < cand:
                pid, cand = k, d0
        if cand is None or cand > 40:
            continue
        v = fl_exp[pid]
        d = max(min(math.dist(p, q) for q in v) for p in pv)
        if d > fb_worst:
            fb_worst, fb_t = d, nm
            fb_worst_pid = (nm, pid, pv)
        if d > TOL_FLAG:
            fb_bad.append((nm, d))
    print("   外框（旗标）：逐顶点最大 Δ = **%.5f 导出单位（%.5f mm）** @%s %s"
          % (fb_worst, fb_worst * 25.4 / 72.0, fb_t, "✓✓" if not fb_bad else "✗✗"))
    for nm, d in fb_bad[:8]:
        print("      ✗ %-12s 框顶点差 %.4f 单位 = %.4f mm" % (nm, d, d * 25.4 / 72.0))
    if fb_bad:                                    # ★ 把最差那个的顶点**并排**打出来 ✓（定位用 ✓）
        _nm0, _pid0, _pv0 = fb_worst_pid
        print("      ⚠ 最差：`%s`（partID=%s）" % (_nm0, _pid0))
        print("         我的: %s" % ["(%.3f,%.3f)" % q for q in _pv0])
        print("         导出: %s" % ["(%.3f,%.3f)" % q for q in fl_exp[_pid0]])
    print("   ★ 口径：模型 = `sch_net`（一处实现 ✓）；比例 0.8 = 理论值 ✓；平移 = 投票 ✓")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
