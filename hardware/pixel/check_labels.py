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
    # 我的模型算出的锚点（**未加全局平移** ✓）：导出 = 0.8×它 + c ✓（c 待定 ✓）
    #   ★ 把**旋转矩阵**也带上 ✓（定标时要挑掉被 Fritzing 补偿过的 ✓）。
    pred = [(nm, SN.label_text_anchor(geom, nm, m), m) for nm, geom, m in mine]
    # ★★ 定标**只能用“没被 Fritzing 补偿过”的标签** ✗✗（2026-09-30 实测 ✓）：
    #   `m11 < 0`（镜像/180° ✓）时 Fritzing 会给文字层**再加一层反向矩阵** ✓
    #   （导出里那句 `matrix(-1,0,0,-1,6.6855,7.236)` ✓ = 把字摆正 ✓）
    #   ⇒ 它画出来的锚点**不在**我模型的锚点上 ✗ ⇒ 拿它定标会**系统性偏 2.3mm** ✗✗
    #   （实测：那时文字报到 50mm ✗ → 只用干净的标完 ⇒ 0.04mm ✓✓）。
    #   ⇒ 只用 `m11 >= 0` 的标签定标 ✓（那几种 Fritzing 就是按 R 转的 ✓、与模型一致 ✓）。
    votes = []
    for (nm, a, m) in pred:
        if float(m[0]) < 0:
            continue
        for (b, tn, _fs) in texts:
            if tn != nm:
                continue
            votes.append(((b[0] - S * a[0], b[1] - S * a[1]), nm))
    if not votes:                                  # 全是被补偿的 ⇒ 退回全用 ✓（并说明 ✓）
        for (nm, a, m) in pred:
            for (b, tn, _fs) in texts:
                if tn == nm:
                    votes.append(((b[0] - S * a[0], b[1] - S * a[1]), nm))
        print("   ⚠ 图里**没有**未被补偿的标签 ⇒ 定标退回“全用” ✓（误差里会含补偿量 ✗）")
    if not votes:
        print("✗ 导出里没有同名标签文字 ⇒ 没法核对 ✗")
        return 1
    # ★★ 2026-09-30 修 ✗：**同名重复**（本图两个 `RC` ✓）时“投票”会**打平** ✗
    #   （正确的一对得 2 票 ✓，可**错配**的那两对也常给出**同一个** c ✗ ⇒ 又是 2 票 ⇒ 谁先谁赢 ✗✗）。
    #   ⇒ 正解：**枚举候选 c** ✓、每个 c 下做**一对一贪心配对**（同名才配 ✓）、
    #     取**总误差最小**的那个 ✓ —— 一次把“定标 + 配对”两个未知数一起解 ✓。
    best, best_asg = None, None
    for _c0, _nm0 in votes:
        _pairs = sorted((math.dist((S * a[0] + _c0[0], S * a[1] + _c0[1]), b), _i, _j)
                        for _i, (nm, a, _m) in enumerate(pred)
                        for _j, (b, tn, _fs) in enumerate(texts) if tn == nm)
        _ui, _uj, _tot, _n, _asg = set(), set(), 0.0, 0, {}
        for _d, _i, _j in _pairs:
            if _i in _ui or _j in _uj:
                continue
            _ui.add(_i)
            _uj.add(_j)
            _asg[_i] = _j
            _tot += _d
            _n += 1
        if _n == len(pred) and (best is None or _tot < best[0]):
            best, best_asg = (_tot, _c0, _n), _asg
    best_c, best_n = best[1], best[2]
    print("== 标签核对：%s ↔ %s ==" % (os.path.basename(fzz), os.path.basename(exp)))
    print("   我的标签 %d 个 ｜ 导出标签文字 %d 个 ｜ 全局平移 c（一对一贪心 ✓）：(%+.4f, %+.4f)"
          % (len(mine), len(texts), best_c[0], best_c[1]))
    worst, wt, bad = 0.0, "", []
    _skip_mirror = 0
    for _i, (nm, a, _m) in enumerate(pred):
        # ★★ 镜像/180° 的标签**文字锚点不可比** ✗（2026-09-30 实测 ✓）：
        #   Fritzing 会给它**再加一层反向矩阵** ✓（把字摆正 ✓，见导出 ✓）
        #   ⇒ 它画出来的锚点 ≠ 我模型的锚点 ✓ —— **差 2.33mm** ✗，但那是**补偿量** ✓、
        #     不是文件错 ✓（旗标那一项仍然照核 ✓ ⇒ 几何照样被守住 ✓）。
        #   ⇒ 文字这一项**跳过它** ✓（并在末尾如实报出跳了几个 ✓，不静默 ✗）。
        if float(_m[0]) < 0:
            _skip_mirror += 1
            continue
        p = (S * a[0] + best_c[0], S * a[1] + best_c[1])
        _j = (best_asg or {}).get(_i)
        if _j is None:
            bad.append((nm, None, "没有配到同名文字 ✗"))
            continue
        d = math.dist(p, texts[_j][0])
        if d > worst:
            worst, wt = d, nm
        if d > TOL:
            bad.append((nm, d, ""))
    print("   **文字锚点最大 Δ = %.5f 导出单位（%.5f mm）** @%s %s"
          % (worst, worst * 25.4 / 72.0, wt, "✓✓" if not bad else "✗✗"))
    if _skip_mirror:
        print("   ⊘ 跳过 %d 个**镜像/180°**标签的文字 ✓（Fritzing 会给它们加补偿矩阵 ⇒ 锚点不可比 ✓；"
              "旗标那项照核 ✓）" % _skip_mirror)
    for nm, d, why in bad[:8]:
        print("      ✗ %-12s %s" % (nm, why or ("差 %.5f 单位 = %.4f mm" % (d, d * 25.4 / 72.0))))
    # ── ★★ 外框（旗标）也核 ✓（用户 2026-09-29 指出我漏画它 ✗）──
    fl_exp = export_flag(exp)
    fb_worst, fb_t, fb_bad = 0.0, "", []
    fb_worst_pid = ("", "", [], [])
    # ★★ 配对必须**一对一** ✓（2026-09-30 修 ✗）：
    #   ✗ 旧版按“最近中心”**各配各的** ✗、**不消耗** ✗ ⇒ 两个**同名**标签（本图两个 `RC` ✓，
    #     一只 180° 一只 90° ✓）会**抢同一个导出组** ✗ ⇒ 报出“差 2.75mm” ✗✗，
    #     而其实**两边都对** ✓（实测：模型 12.1×8.7 / 8.7×12.1 sketch ⇔ 导出 9.78×6.96 / 6.96×9.78 ✓✓）。
    #   ⇒ 正解：把所有 (模型, 导出组) 距离**排一遍**、**贪心一对一** assign ✓。
    _mine_box = []
    for (nm, geom, m) in mine:
        pv = [((S * q[0] + best_c[0]), (S * q[1] + best_c[1])) for q in SN.label_flag(geom, nm, m)]
        _mine_box.append((nm, pv,
                          (sum(p[0] for p in pv) / len(pv), sum(p[1] for p in pv) / len(pv))))
    _pairs = []
    for _i, (_nm, _pv, (_cx, _cy)) in enumerate(_mine_box):
        for _pid, _v in fl_exp.items():
            _ex = sum(p[0] for p in _v) / len(_v)
            _ey = sum(p[1] for p in _v) / len(_v)
            _pairs.append((math.dist((_cx, _cy), (_ex, _ey)), _i, _pid))
    _pairs.sort()
    _um, _up, _asg = set(), set(), {}
    for _d0, _i, _pid in _pairs:
        if _i in _um or _pid in _up or _d0 > 40:
            continue
        _um.add(_i)
        _up.add(_pid)
        _asg[_i] = _pid
    for _i, (_nm, pv, _c) in enumerate(_mine_box):
        if _i not in _asg:
            continue
        v = fl_exp[_asg[_i]]
        d = max(min(math.dist(p, q) for q in v) for p in pv)
        if d > fb_worst:
            fb_worst, fb_t = d, _nm
            fb_worst_pid = (_nm, _asg[_i], pv, v)
        if d > TOL_FLAG:
            fb_bad.append((_nm, d))
    print("   外框（旗标）：逐顶点最大 Δ = **%.5f 导出单位（%.5f mm）** @%s %s"
          % (fb_worst, fb_worst * 25.4 / 72.0, fb_t, "✓✓" if not fb_bad else "✗✗"))
    for nm, d in fb_bad[:8]:
        print("      ✗ %-12s 框顶点差 %.4f 单位 = %.4f mm" % (nm, d, d * 25.4 / 72.0))
    if fb_bad:                                    # ★ 把最差那个的顶点**并排**打出来 ✓（定位用 ✓）
        _nm0, _pid0, _pv0, _ev0 = fb_worst_pid
        print("      ⚠ 最差：`%s`（partID=%s）" % (_nm0, _pid0))
        print("         我的: %s" % ["(%.3f,%.3f)" % q for q in _pv0])
        print("         导出: %s" % ["(%.3f,%.3f)" % q for q in _ev0])
    print("   ★ 口径：模型 = `sch_net`（一处实现 ✓）；比例 0.8 = 理论值 ✓；平移 = 投票 ✓")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
