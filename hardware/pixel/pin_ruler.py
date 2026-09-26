# -*- coding: utf-8 -*-
r"""用 Fritzing 自己导出的 SVG 当尺子，算出每个脚在 sketch 里的**精确位置**（带自证 ✓）。

原理（2026-09-26）：
  · 导出 SVG 里每个实例是一个 `<g partID="<modelIndex>">` ✓，里面层层 `<g transform=…>` ✓
    ⇒ 把祖先 transform 累乘，就能得到该实例坐标 → 导出坐标的映射 ✓
  · 导出单位 = 1/72 in（源码 IllustratorDPI = 72；本文件 viewBox 370.36 / 5.14389in = 72 ✓）
  · sketch 的单位与它差一个**全局比例 + 平移**：`sketch = ratio·导出 + C`
    ⇒ 拿**同一型号的两个实例**（如 J1/J2、C1/C2）联立解出 ratio ✓，用**其余实例**验证 ✓（自证 ✓）

用法：py -3.13 tools\pin_ruler.py <sketch.fzz> <fritzing导出.svg>
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import part_measure as pm


def mul(m, n):
    """2x3 矩阵相乘（SVG 约定）✓"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def parse_tf(s):
    """解析 transform 串 → 2x3 矩阵（只用到 translate/matrix/scale ✓）"""
    m = (1, 0, 0, 1, 0, 0)
    for name, arg in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.split(r"[,\s]+", arg.strip()) if x]
        if name == "translate":
            m = mul(m, (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0))
        elif name == "scale":
            m = mul(m, (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0))
        elif name == "matrix":
            m = mul(m, tuple(v[:6]))
        elif name == "rotate":
            import math
            a = math.radians(v[0])
            m = mul(m, (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0))
    return m


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def main(argv):
    fzz, svg = argv[0], argv[1]

    # ── A) 解析导出 SVG：partID → 原点 + 各脚位置（导出坐标）────────────────
    root = ET.parse(svg).getroot()
    parts = {}

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("partID"):
            pid = el.get("partID")
            parts.setdefault(pid, {"origin": None, "pins": {}, "ng": 0})
            parts[pid]["ng"] += 1
        # ★ 原点要取 <g id="schematic"> 那一层（part 的绘图原点 = 它在画布上的位置 ✓）
        if i0 := (el.get("id") == "schematic"):
            if pid in parts and parts[pid]["origin"] is None:
                parts[pid]["origin"] = apply(m2, 0, 0)
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm and pid in parts and el.get("x") is not None and el.get("y") is not None:
            parts[pid]["pins"].setdefault("connector" + mm.group(1),
                                          apply(m2, float(el.get("x")), float(el.get("y"))))
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)
    for pid, d in parts.items():
        if d["origin"] is None:
            d["origin"] = (0.0, 0.0)
    print("导出 SVG: 实例 %d 个" % len(parts))
    for pid, d in sorted(parts.items()):
        print("   partID=%-10s 原点=(%9.3f,%9.3f)  脚 %d 个" % (pid, d["origin"][0], d["origin"][1], len(d["pins"])))

    # ── B) sketch 里的实例（modelIndex → 位号/loc）───────────────────────────
    z = zipfile.ZipFile(fzz)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(fz))
    inst = {}
    for e in sroot.iter("instance"):
        mi = e.get("modelIndex")
        vw = pm.child(e, "views")
        sub = pm.child(vw, "schematicView") if vw is not None else None
        g = pm.child(sub, "geometry") if sub is not None else None
        if g is not None and g.get("x") is not None:
            inst[mi] = {"title": (e.findtext("title") or "").strip(),
                        "mid": e.get("moduleIdRef"),
                        "loc": (pm.num(g.get("x")), pm.num(g.get("y")))}
    # 导出里的 partID 比 modelIndex 多一位尾数（源码 ItemBase::getNextID(modelIndex) ✓）
    # ⇒ 按“前缀吻合 + 只多一位”配对 ✓
    def find_pid(mi):
        cands = [p for p in parts if p.startswith(mi) and len(p) == len(mi) + 1]
        return cands[0] if len(cands) == 1 else (mi if mi in parts else None)

    pairs = []
    for m, d in inst.items():
        pid = find_pid(m)
        if pid:
            pairs.append((m, d, parts[pid]))
    print("\nsketch 实例: %d 个（与导出对上的：%d）" % (len(inst), len(pairs)))
    if len(pairs) < 2:
        raise SystemExit("✗ 对不上的实例太少，标定不了（导出 SVG 是不是这份 sketch 的？）")
    by_mid = {}
    for m, d, p in pairs:
        by_mid.setdefault(d["mid"], []).append((m, d, p))
    est = []
    for mid, lst in by_mid.items():
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                (_, da, pa), (_, db, pb) = lst[i], lst[j]
                sx, sy = da["loc"][0] - db["loc"][0], da["loc"][1] - db["loc"][1]
                ex, ey = pa["origin"][0] - pb["origin"][0], pa["origin"][1] - pb["origin"][1]
                if abs(ex) > 1e-6:
                    est.append(("x", sx / ex, mid))
                if abs(ey) > 1e-6:
                    est.append(("y", sy / ey, mid))
    if not est:
        raise SystemExit("✗ 没有可用的配对来标定比例")
    ratios = sorted(r for _a, r, _m in est)
    ratio = ratios[len(ratios) // 2]
    print("\n标定: ratio = %.6f 单位/导出单位（来自 %d 组配对；散布 %.6f…%.6f）"
          % (ratio, len(est), ratios[0], ratios[-1]))
    for axis in ("x", "y"):
        rs = [r for a, r, _m in est if a == axis]
        if rs:
            lo, hi = min(rs), max(rs)
            print("   %s 轴: %.6f … %.6f（相对散差 %.4f%%）"
                  % (axis, lo, hi, (hi - lo) / (abs(lo) + 1e-9) * 100))
    if ratio <= 0:
        raise SystemExit("✗ ratio 非正 —— 导出与 sketch 不是同一份/同一朝向 ✗")

    cs = [(d["loc"][0] - ratio * p["origin"][0], d["loc"][1] - ratio * p["origin"][1], d["title"])
          for _m, d, p in pairs]
    cx = sum(c[0] for c in cs) / len(cs)
    cy = sum(c[1] for c in cs) / len(cs)
    worst = max(((c[0] - cx) ** 2 + (c[1] - cy) ** 2) ** 0.5 for c in cs)
    print("   平移常数 C = (%.4f, %.4f)；各实例偏离最大 %.4f 单位 = %.4f mm  %s"
          % (cx, cy, worst, worst * 25.4 / 90, "✓ 自证通过" if worst < 1.0 else "✗ 偏差过大"))

    # ── D) 每个实例每个脚在 sketch 里的位置 ────────────────────────────────
    #   ★ 正确模型：脚位置 = loc + ratio·(脚导出坐标 − 该元件的绘图原点导出坐标)
    #     （不能用全局平移 ✗——元件的绘图原点与它的 loc 之间的偏心是因件而异的 ✓）
    print("\n脚位置（sketch 单位；×0.2822 = mm）：")
    table = {}
    bad = 0
    for m, d, p in sorted(pairs, key=lambda r: r[1]["title"]):
        ox, oy = p["origin"]
        rows, pts = [], []
        for cid, (ex, ey) in sorted(p["pins"].items(), key=lambda kv: kv[0]):
            sx = d["loc"][0] + ratio * (ex - ox)
            sy = d["loc"][1] + ratio * (ey - oy)
            table[(d["title"], cid)] = (sx, sy)
            pts.append((sx, sy))
            rows.append("%s=(%.1f,%.1f)" % (cid.replace("connector", ""), sx, sy))
        # 自证：脚该落在元件附近（用 loc 为中心的半径）
        far = [q for q in pts if ((q[0] - d["loc"][0]) ** 2 + (q[1] - d["loc"][1]) ** 2) ** 0.5 > 120]
        bad += len(far)
        print("   %-8s %s%s" % (d["title"], "  ".join(rows),
                              "   ← 有 %d 个脚离元件太远 ✗" % len(far) if far else ""))
    print("\n自证: 离元件过远的脚 %d 个 %s" % (bad, "✓" if not bad else "✗"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
