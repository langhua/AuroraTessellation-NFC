# -*- coding: utf-8 -*-
r"""**网标签的脚真的落在导线上吗**核对（出厂检查 ⑥ ✓，2026-09-30 ✓）—— **只读** ✓

用法（在本目录 ✓）：
    py -3.13 check_label_touch.py <a.fzz> [b.fzz ...]   # 0 = 全合格 ✓；1 = 有浮空标签 ✗；2 = 拒判 ✗

★★ 为什么会需要这一条 ✗（2026-09-30 实测 ✓，**五道判据全绿也没拦住** ✗✗）：
  生成器给标签**新拉的那截引线**，被随后的"清断头"当成悬空叶子**删掉了** ✗
  ⇒ 标签的脚离最近的导线 **11.5 单位（3.2mm）** ✗ = 图上"标签挂在空气里" ✗；
  而 ① 网表 ✓ ② (A)/(B) ✓ ④ 被穿旗标 ✓ ⑤ 接地符号 ✓ **全过** ✗ ——
  因为它们查的是**连接表**与**别的几何** ✓，**没人量"标签的脚到导线的距离"** ✗。

★ 单看连接表为什么不够 ✗（与出厂检查那条结构性事实同一条 ✓）：Fritzing 的连接**只记在
  `<connects>` 里** ✓ ⇒ 表里写着"接着" ✓、图上线压根不在那儿 ✗，照样"合格" ✗。

查两件事 ✓：
  ① **几何** ✓：标签**画出来的脚** ⇒ 到最近导线（线段 ✓，含中段 ✓）的距离必须 **≤ 0.05** ✓；
  ② **声明** ✓：该标签的 `<connect>` 里必须**正好**指向那根导线 ✓（表与图两边都得对 ✓）。

★ 口径说明（诚实起见 ✓）：**“哪里是脚”那套模型是共享的** ✓（`sch_net.label_pin` ✓ ——
  与渲染器/生成器同一份 ✓；另写一份只会多一个错处 ✗，这个模型是从 Fritzing 源码 +
  用户手画数据反推出来的 ✓）。本文件**独立**的地方是：**不调生成器任何代码** ✓、
  只读 `.fzz` ✓ ⇒ "生成器自己以为接上了"骗不过它 ✓✓（这正是上面那个 bug 被量出来的原因 ✓）。
★ 图里**没有网标签** ⇒ **拒判**（退出码 2 ✓）—— 不许"空集当通过" ✗（与 ④⑤ 同一条 ✓）。
"""
import math
import sys
import xml.etree.ElementTree as ET
import zipfile

import sch_net                                   # ★ 只有“脚在哪”这一份模型 ✓（见上 ✓）

TOL = 0.05                                       # 端点重合容差 ✓（与生成器/渲染器同一档 ✓）


def tag(el):
    return el.tag.split("}")[-1]


def kid(el, name):
    for c in el:
        if tag(c) == name:
            return c
    return None


def load(path):
    r"""⇒ `(标签[(mi, 网名, 脚, 声明的邻居 mi)], 导线[(mi, p, q)])` ✓（只读 schematicView ✓）"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    inst = kid(root, "instances")
    labels, wires = [], []
    for e in (list(inst) if inst is not None else []):
        if tag(e) != "instance":
            continue
        mid = e.get("moduleIdRef") or ""
        vw = kid(e, "views")
        sv = None
        for v in (list(vw) if vw is not None else []):
            if tag(v) == "schematicView":
                sv = v
        if sv is None:
            continue
        g = kid(sv, "geometry")
        if g is None or g.get("x") is None:
            continue
        x, y = float(g.get("x")), float(g.get("y"))
        if mid.startswith("Wire"):
            wires.append((e.get("modelIndex"), (x, y),
                          (x + float(g.get("x2", 0)), y + float(g.get("y2", 0)))))
            continue
        prop = {p.get("name"): p.get("value") for p in e.iter("property")}
        ttl = (e.findtext("title") or "").strip()
        name = sch_net.net_name(mid, ttl, prop.get("label"))
        if not name:
            continue
        tf = kid(g, "transform")
        m = None
        if tf is not None and tf.get("m11") is not None:
            m = (float(tf.get("m11")), float(tf.get("m12")),
                 float(tf.get("m21")), float(tf.get("m22")))
        pin = sch_net.label_pin((x, y), name, m, go_left=(prop.get("direction") == "left"))
        told = []
        for c in e.iter("connect"):
            told.append(str(c.get("modelIndex")))
        labels.append((e.get("modelIndex"), name, pin, told))
    return labels, wires


def dist_to_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + dx * t, a[1] + dy * t))


def check(path):
    print("── %s" % path)
    labels, wires = load(path)
    if not labels:
        print("   ⊘ 图里没有网标签 ⇒ **拒判** ✗（退出码 2 ✓ —— 不许“空集当通过” ✗）")
        return 2
    print("   网标签 %d 个 ✓ ｜ 导线 %d 根 ✓" % (len(labels), len(wires)))
    rc = 0
    for (mi, name, pin, told) in labels:
        best, who = 1e9, None
        for (wmi, a, b) in wires:
            d = dist_to_seg(pin, a, b)
            if d < best:
                best, who = d, str(wmi)
        ok = best <= TOL
        dec = (who in told) if ok else None
        print("   · 标签 %s（%s）脚 (%.3f,%.3f) ⇒ 最近导线 %s 距离 %.3f %s ｜ 声明 %s %s"
              % (mi, name, pin[0], pin[1], who, best,
                 "✓ 落在它上面" if ok else "✗ **浮空**！",
                 "、".join(told) if told else "（无 ✗）",
                 "✓ 一致" if dec else ("✗ **表里没写**！" if ok else "")))
        if not ok or dec is False:
            rc = 1
    if rc == 0:
        print("   ⇒ ✅ 全部标签的脚都落在导线上、且声明一致 ✓")
    else:
        print("   ⇒ ❌ 有标签浮空 / 声明不一致 ✗")
    return rc


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[3].strip())
        print("\n请给至少一个 .fzz ✓（如：py -3.13 check_label_touch.py pixel-schematic-v34.fzz）")
        return 2
    rc = 0
    for p in argv:
        rc = max(rc, check(p))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
