# -*- coding: utf-8 -*-
r"""**接线点（Fritzing 画的那些小圆点）**核对（出厂检查 ⑦ ✓，2026-09-30 ✓）—— **只读** ✓

用法（在本目录 ✓）：
    py -3.13 check_junctions.py <a.fzz> [b.fzz ...]     # 0 = 合格 ✓；1 = 有多余接线点 ✗；2 = 拒判 ✗

★★ 为什么要这一条 ✗（2026-09-30 用户指着截图说「**红色线上多了一个接线点**」✓）：
  生成器的“改接”把 5V 那条长横线**切成了两段共线的线** ✗
  （`(29.78,-57.60)→(49.38,-57.60)` ＋ `(49.38,-57.60)→(180.38,-57.60)` ✗）——
  两段**在一条直线上** ✓，而 Fritzing 在**每一个接头处都会画一个小圆点** ✓
  ⇒ 图上就是"平平一条红线中间凭空多了一个点" ✗；用户手改版那条是**一整根** ✓ ⇒ 没有点 ✓。

判据（**缺陷 == 共线切分** ✓，纯几何 ✓、自足 ✓）：
  · **不合格 ✗**：某一点上**恰好只有两个线端** ✓、且两根线从该点伸出去的方向**严格反向**
    （叉积 ≈ 0 ✓ 且 点积 ≤ −0.999 ✓）⇒ 那就是"把一根直线切成了两段" ✗ ⇒ 计数 ✓。
  · **仅供参考 ✓（不算缺陷 ✓）**：端点恰好两个但**成折角** ✓（手改版里 16 处都是这类 ✓、
    用户没意见 ✓）；**≥3 个线端** ✓（真分叉 ✓）；**T 形**（端点落在别人**中段**上 ✓）。

★ 为什么"折角不算 ✗、共线才算 ✗"：折角处那个点是**必要的** ✓（线在那儿拐弯 ✓）；
  共线处那个点**什么都不干** ✓（两段合成一段几何完全一样 ✓）⇒ 只有它该消掉 ✓。
★ 图里**没有导线** ⇒ **拒判**（退出码 2 ✓）—— 不许"空集当通过" ✗（与 ④⑤⑥ 同一条 ✓）。
"""
import math
import sys
import xml.etree.ElementTree as ET
import zipfile

TOL = 0.05                                      # 端点重合容差 ✓（与生成器/渲染器同一档 ✓）
COLL_TOL = 1e-3                                 # "共线"的角容差 ✓（≈0.06° ✓）
OPP_MAX = -0.999                                # "反向"的点积上限 ✓


def tag(el):
    return el.tag.split("}")[-1]


def kid(el, name):
    for c in el:
        if tag(c) == name:
            return c
    return None


def load(path):
    r"""⇒ `(导线[(mi, p, q, 颜色)], 引脚点集合)` ✓（只读 schematicView ✓；**颜色就是网** ✓）

    ★ “哪一点是**引脚**”从**连接表自己**读 ✓：某根线的某个端口的 `<connect>` 里，
      **伙伴的 layer 不是 `schematicTrace`** ⇒ 伙伴是**元件脚** ✓（生成器 `add_conn` 的
      口径：线↔线用 `schematicTrace` ✓、线↔脚用元件自己视图的 layer ✓）。
      ⇒ 那一端就是“落在脚上” ✓ —— **脚上出现两根共线的线是正常的** ✓（脚本来就是交汇点 ✓、
      Fritzing 在那里画点是对的 ✓）；**中途**切一刀才是毛病 ✗。
    """
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    inst = kid(root, "instances")
    out, pinpts = [], set()
    for e in (list(inst) if inst is not None else []):
        if tag(e) != "instance" or not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        vw = kid(e, "views")
        sv = None
        for v in (list(vw) if vw is not None else []):
            if tag(v) == "schematicView":
                sv = v
        g = kid(sv, "geometry") if sv is not None else None
        if g is None or g.get("x") is None:
            continue
        x, y = float(g.get("x")), float(g.get("y"))
        we = kid(sv, "wireExtras")
        mi = e.get("modelIndex")
        out.append((mi, (x, y), (x + float(g.get("x2", 0)), y + float(g.get("y2", 0))),
                    (we.get("color") if we is not None else "") or ""))
        for c in e.iter("connector"):                # 端口级的 connects ✓（Fritzing 1.0 只读这份 ✓）
            cid = c.get("connectorId")
            for cn in c.iter("connect"):
                if (cn.get("layer") or "") != "schematicTrace":
                    pinpts.add((round(x if cid == "connector0" else x + float(g.get("x2", 0)), 3),
                                round(y if cid == "connector0" else y + float(g.get("y2", 0)), 3)))
    return out, pinpts


def check(path):
    print("── %s" % path)
    ws, pinpts = load(path)
    if not ws:
        print("   ⊘ 图里没有导线 ⇒ **拒判** ✗（退出码 2 ✓ —— 不许“空集当通过” ✗）")
        return 2
    pts = {}
    for (mi, p, q, c) in ws:
        for e in (p, q):
            pts.setdefault((round(e[0], 3), round(e[1], 3)), []).append((mi, c, e, p, q))

    split, multi, tee = [], [], []
    for k, lst in sorted(pts.items()):
        if len(lst) == 2:
            (mi1, c1, e1, p1, q1), (mi2, c2, e2, p2, q2) = lst
            if mi1 == mi2 or c1 != c2:
                continue
            if k in pinpts:
                continue                            # ★ 落在**脚**上 ⇒ 正常 ✓（脚是交汇点 ✓）
            o1 = q1 if (round(p1[0], 3), round(p1[1], 3)) == k else p1
            o2 = q2 if (round(p2[0], 3), round(p2[1], 3)) == k else p2
            va = (o1[0] - k[0], o1[1] - k[1])
            vb = (o2[0] - k[0], o2[1] - k[1])
            la, lb = math.hypot(*va), math.hypot(*vb)
            if la > 1e-6 and lb > 1e-6:
                cr = abs(va[0] * vb[1] - va[1] * vb[0]) / (la * lb)
                dt = (va[0] * vb[0] + va[1] * vb[1]) / (la * lb)
                if cr <= COLL_TOL and dt <= OPP_MAX:
                    split.append((k, mi1, mi2))
        elif len(lst) >= 3:
            multi.append((k, lst))
    for (mi, p, q, c) in ws:                    # T 形：端点落在**别人中段**上 ✓
        for (mi2, p2, q2, c2) in ws:
            if mi2 == mi or c2 != c:
                continue
            dx, dy = q2[0] - p2[0], q2[1] - p2[1]
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            for e in (p, q):
                t = ((e[0] - p2[0]) * dx + (e[1] - p2[1]) * dy) / L2
                if t <= 0.02 or t >= 0.98:
                    continue
                if math.dist((p2[0] + dx * t, p2[1] + dy * t), e) <= TOL:
                    tee.append((round(e[0], 3), round(e[1], 3), mi, mi2))
    print("   导线 %d 根 ✓ ｜ 接头 %d 点 ✓ ｜ 落在脚上的接头 %d 点 ✓（**正常 ✓**，不算 ✗）"
          % (len(ws), len(pts), sum(1 for k in pts if k in pinpts)))
    for (k, mi1, mi2) in split:
        print("   ✗ **共线切分** @ (%.2f,%.2f) ⇒ %s ＋ %s ⇒ 合成一根 ✗"
              "（两段在一条直线上 ⇒ 那个点什么都不干 ⇒ Fritzing 照样画个圆点 ✗）"
              % (k[0], k[1], mi1, mi2))
    print("   · 折角接头（仅供参考 ✓，必要的拐弯 ✓）：**%d** 处 ✓"
          % (len(pts) - len(split) - len(multi) - sum(1 for k in pts if k in pinpts)))
    print("   · ≥3 个线端的真分叉（参考 ✓）：**%d** 处 ✓" % len(multi))
    print("   · T 形（端点落在别人中段 ✓，参考 ✓）：**%d** 处 ✓" % len(tee))
    if split:
        print("   ⇒ ❌ 多余接线点 **%d** 处 ✗（合成共线两段即可消掉 ✓）" % len(split))
        return 1
    print("   ⇒ ✅ 没有共线切分 ⇒ 没有多余的接线点 ✓")
    return 0


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[3].strip())
        print("\n请给至少一个 .fzz ✓（如：py -3.13 check_junctions.py pixel-schematic-v34.fzz）")
        return 2
    rc = 0
    for p in argv:
        rc = max(rc, check(p))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
