# -*- coding: utf-8 -*-
r"""**接地符号几何**核对（出厂检查 ⑤ ✓，2026-09-30 ✓）—— **只读** ✓、**另一份实现** ✓

用法（在本目录 ✓）：
    py -3.13 check_grounds.py <a.fzz> [b.fzz ...]      # 退出码 0 = 全合格 ✓；1 = 有不合规 ✗；2 = 拒判 ✗

★★ 为什么要**另写一份** ✗（不许自证 ✓，`AGENTS §5b` / `docs` 那条 ✓）：
  生成器挑挂点时用的是 `sch_net.ground_box()` ✓ —— 若本文件也调它 ✗，
  那么 `ground_box` 一旦写错，**生成器与核对器会一起错** ✗✗、报"合格 ✓" ✗ ——
  这一手**真的踩到了** ✗：第一版核对器把"终止在脚上的那根线"**整根豁免** ✗，
  于是那个"线从符号身上穿过去"的错版照样报 ✓（= 用户眼睛先看出来的那个错 ✗）。
  ⇒ 本文件的常数**自己写死** ✓，来源与 `render_sch.py` 那份实测盒子**同一处** ✓
    （用户导出 `pixel-schematic-v32_图示.svg` 里 Fritzing 自己画的接地符号 ✓）。

查三件事（都从**文件自己的数字**读 ✓，不调生成器 ✓）：
  ① **脚上确实有导线端点** ✓（±0.05 ✓）—— 否则就是"符号挂在空气里" ✗
  ② **没有线穿过那块看得见的图形** ✗ —— 只豁免**脚周围 1 单位**那一小截 ✓
     （线本来就要接在脚上 ✓）；**整根豁免是错的** ✗（见上 ✓）。
  ③ **没有引脚落在那块图形里** ✗（脚压符号 ⇒ 图上分不清谁接谁 ✗）

★ 灵敏度过 ✓（2026-09-30 ✓，同一份文件跑三版）：
    `pixel-schematic-v32.fzz`（用户手改 ✓）= **0/2** ✓ ｜ 第一版错版 = **2/2 ✗** ｜
    `pixel-schematic-v33.fzz`（最终 ✓）= **0/2** ✓
★ 图里**没有接地符号** ⇒ **拒判**（退出码 2 ✓）—— 不许"空集当通过" ✗（与 `check_flags.py` 同一条 ✓）。
"""
import math
import sys
import xml.etree.ElementTree as ET
import zipfile

# ── 常数（**另一份实现** ✓）：脚 = 原点 + (9.001, 0.596) ✓（用户手改版两处反推，两个样本一样 ✓）；
#    看得见的那块（相对**脚** ✓）= 内层墨迹框 x 0.5…13.9、y 0.375…13.175（导出单位 ✓）× 1.25 ✓。
PIN_DX, PIN_DY = 9.001, 0.596
SCALE = 1.25
INNER = (0.5, 0.0, 13.9, 13.175)          # 内层墨迹框 ✓（含竖杆 + 三根横线 ✓）
INNER_PIN = (7.201, 0.375)                # 内层脚位 ✓
BOX = ((INNER[0] - INNER_PIN[0]) * SCALE, (INNER[1] - INNER_PIN[1]) * SCALE,
       (INNER[2] - INNER_PIN[0]) * SCALE, (INNER[3] - INNER_PIN[1]) * SCALE)
TOL = 0.05                                 # 端点重合容差 ✓（与生成器/渲染器同一档 ✓）
EXEMPT = 1.0                               # 脚周围豁免的长度 ✓（单位 ✓）


def tag(el):
    return el.tag.split("}")[-1]


def kid(el, name):
    for c in el:
        if tag(c) == name:
            return c
    return None


def load(path):
    """⇒ `(接地符号[(mi, 脚)], 导线[(mi, p, q)], 引脚[(ref.cid, x, y)])` ✓（只读 schematicView ✓）"""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    inst = kid(root, "instances")
    grounds, wires, pins = [], [], []
    for e in (list(inst) if inst is not None else []):
        if tag(e) != "instance":
            continue
        mid = e.get("moduleIdRef") or ""
        vw = kid(e, "views")
        sv = next((c for c in vw if tag(c) == "schematicView"), None) if vw is not None else None
        g = kid(sv, "geometry") if sv is not None else None
        if g is None:
            continue
        if mid == "GroundModuleID":
            grounds.append((str(e.get("modelIndex")),
                            (float(g.get("x")) + PIN_DX, float(g.get("y")) + PIN_DY),
                            kid(g, "transform") is not None))
        elif mid.startswith("Wire"):
            p = (float(g.get("x")), float(g.get("y")))
            wires.append((str(e.get("modelIndex")), p,
                          (p[0] + float(g.get("x2") or 0), p[1] + float(g.get("y2") or 0))))
        else:
            for c in (sv.iter() if sv is not None else []):
                if tag(c) == "connector":
                    gc = kid(c, "geometry")
                    if gc is not None:
                        pins.append(("%s.%s" % (e.get("modelIndex"), c.get("connectorId")),
                                     float(gc.get("x") or 0), float(gc.get("y") or 0)))
    return grounds, wires, pins


def clip(a, b, P):
    r"""把**终止在脚上**的那一端往里收 `EXEMPT` ✓（只豁免脚周围一小截 ✓ —— ✗ 整根豁免是自证 ✗）"""
    L = math.dist(a, b)
    if L <= 1e-9:
        return a, b
    if math.dist(a, P) < TOL:
        return (a[0] + (b[0] - a[0]) * EXEMPT / L, a[1] + (b[1] - a[1]) * EXEMPT / L), b
    if math.dist(b, P) < TOL:
        return a, (b[0] + (a[0] - b[0]) * EXEMPT / L, b[1] + (a[1] - b[1]) * EXEMPT / L)
    return a, b


def check(path):
    grounds, wires, pins = load(path)
    print("== %s ｜ 接地符号 %d ｜ 导线 %d ｜ 引脚 %d" % (path, len(grounds), len(wires), len(pins)))
    if not grounds:
        print("   ⊘ **图里没有接地符号** ⇒ **拒判** ✗（退出码 2 ✓）—— 不许“空集当通过” ✗")
        return 2
    bad = 0
    for (mi, P, tf) in grounds:
        if tf:
            print("   ⚠ %s 有 `transform` ✗ —— 本实现只核过**不旋转**那份（用户手改版 ✓）"
                  "⇒ 只按原点算，结论可能不准 ✗" % mi)
        box = (P[0] + BOX[0], P[1] + BOX[1], P[0] + BOX[2], P[1] + BOX[3])
        on_pin = [w[0] for w in wires if math.dist(w[1], P) < TOL or math.dist(w[2], P) < TOL]
        cross = []
        for (wmi, a, b) in wires:
            aa, bb = clip(a, b, P)
            n = max(2, int(max(abs(bb[0] - aa[0]), abs(bb[1] - aa[1]))) + 1)
            for k in range(n + 1):
                t = k / n
                x, y = aa[0] + (bb[0] - aa[0]) * t, aa[1] + (bb[1] - aa[1]) * t
                if box[0] < x < box[2] and box[1] < y < box[3]:
                    cross.append(wmi)
                    break
        pinin = [nm for (nm, x, y) in pins if box[0] < x < box[2] and box[1] < y < box[3]]
        ok = bool(on_pin) and not cross and not pinin
        bad += 0 if ok else 1
        print("   %s %s 脚 (%.3f,%.3f) ｜ 盒 (%.1f,%.1f→%.1f,%.1f)"
              % ("✓" if ok else "✗", mi, P[0], P[1], box[0], box[1], box[2], box[3]))
        print("      ① 接上的线 %s ｜ ② 穿图形的线 %s ｜ ③ 盒里的脚 %s"
              % ("、".join(on_pin) if on_pin else "**没有** ✗",
                 "、".join(cross) if cross else "无 ✓",
                 "、".join(pinin) if pinin else "无 ✓"))
    print("   ⇒ **不合规 %d / %d** %s" % (bad, len(grounds), "✓✓" if not bad else "✗✗"))
    return 1 if bad else 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    rc = 0
    for p in argv:
        rc = max(rc, check(p))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
