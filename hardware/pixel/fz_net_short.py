# -*- coding: utf-8 -*-
r"""★★ 查"两个网在 **PCB 铜** 上到底短没短" ✓（用户 2026-10-02：原理图报 5V 与 GND 短路 ✗）

做法 ✓（都是已被验证过的口径 ✓）：
  1. 用**记录**从两个种子脚各自收齐一个网 ✓（脚/线/过孔 ✓，穿过过孔 ✓）；
  2. 把每个网的铜列出来 ✓：焊盘真形状 ✓ / 走线（有宽度的线段 ✓）/ 过孔圆 ✓
     （过孔铜心 = 文件 x,y ＋ `part_box.ring_off_mm` ✓）；
  3. 逐对算**净距** ✓（同层才比 ✓，过孔两层都有铜 ✓）⇒ 报**最小**的几对 ✓：
     · 净距 ≤ 0 ⇒ **真短上** ✗（铜压铜 ✓）；
     · 净距 > 0 ⇒ 没短 ✓（顺便报"最近还有多远" ✓ = 制造余量 ✓）。

用法 ✓：`fz_net_short.py <sketch.fzz> <种子脚A> <种子脚B>`
  种子脚写法 ✓：`U1.connector5`（modelIndex.connectorId ✓）
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import part_box as PB                                              # noqa: E402
import pcb_check as PC                                             # noqa: E402
import pcb_wire as PW                                              # noqa: E402

SK = 25.4 / 90.0
M = lambda u: u * SK                                               # noqa: E731
path, seedA, seedB = sys.argv[1], sys.argv[2], sys.argv[3]

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

pads, wires, vias, adj = {}, {}, {}, {}


def link(a, b):
    adj.setdefault(a, set()).add(b)
    adj.setdefault(b, set()).add(a)


for q in PC.collect(path)["pads"]:
    pads["%s.%s" % (q.get("mi"), q["cid"])] = q

# ★ 种子脚可以用**名字**给 ✓（`U1.connector5` ✓ ⇒ 内部键 = `90011078.connector5` ✓）
name2key = {}
for k, q in pads.items():
    name2key.setdefault("%s.%s" % (q["title"], q["cid"]), k)
    if q.get("nm"):
        name2key.setdefault("%s.%s" % (q["title"], q["nm"]), k)
for _v in (seedA, seedB):
    if _v not in pads and _v not in name2key:
        print("✗ 找不到种子脚 `%s` ✓ ⇒ 可用名字（如 `U1.connector5` ✓）或 `mi.cid` ✓" % _v)
        sys.exit(1)
seedA = name2key.get(seedA, seedA)
seedB = name2key.get(seedB, seedB)
print("   种子解析 ✓：A=`%s` ✓ B=`%s` ✓" % (seedA, seedB))
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi):
        continue
    mid = mo.group(1)
    g = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    if not g:
        continue
    if mid.startswith("Wire"):
        t = PW.parse_trace(b)
        if t is None:
            continue
        a, bb = PW.abs_ends(t["geo"])
        wires[mi.group(1)] = dict(a=a, b=bb, layer=t["layer"],
                                  half=(t.get("mils") or 24) * 0.0254 / 2 / SK)
    elif mid.startswith("Via"):
        x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
        hs = re.search(r'<property name="hole size" value="([\d.]+)mm,([\d.]+)mm"', b)
        if not x:
            continue
        hole, ring = (float(hs.group(1)), float(hs.group(2))) if hs else (0.3, 0.15)
        off = PB.ring_off_mm(hole, ring) / SK
        vias[mi.group(1)] = dict(c=(float(x.group(1)) + off, float(x.group(2)) + off),
                                 R=(hole / 2 + ring) / SK)
    # ── 这一块的"身份" ✓：焊盘 = `P:mi.cid` ✓；走线 = `W:mi` ✓；过孔 = `V:mi` ✓ ──
    me = ("W:" + mi.group(1)) if mid.startswith("Wire") else \
         (("V:" + mi.group(1)) if mid.startswith("Via") else None)
    for cm in re.finditer(r'(?s)<connector connectorId="(\w+)"[^>]*>(.*?)</connector>',
                          g.group(1)):
        cid = cm.group(1)
        src = ("P:%s.%s" % (mi.group(1), cid)) if ("%s.%s" % (mi.group(1), cid)) in pads else me
        if src is None:
            continue
        for x in re.finditer(r'<connect connectorId="(\w+)" modelIndex="(\d+)"', cm.group(2)):
            t, tcid = x.group(2), x.group(1)
            for cand in (("W:" + t) if t in wires else None,
                         ("V:" + t) if t in vias else None,
                         (("P:%s.%s" % (t, tcid)) if ("%s.%s" % (t, tcid)) in pads else None)):
                if cand:
                    link(src, cand)


def reach(seed):
    seen, st = set([seed]), [seed]
    while st:
        n = st.pop()
        for m in adj.get(n, ()):
            if m not in seen:
                seen.add(m)
                st.append(m)
    return seen


def copper(net):
    """网里的铜 ✓ ⇒ [(说明, 形状)]；形状 = ('pad',q) / ('wire',w) / ('via',v)"""
    out = []
    for k in net:
        if k.startswith("P:"):
            q = pads.get(k[2:])
            if q:
                out.append(("%s.%s" % (q["title"], q["nm"] or q["cid"]), ("pad", q)))
        elif k.startswith("W:"):
            w = wires.get(k[2:])
            if w:
                out.append(("Wire" + k[2:], ("wire", w)))
        elif k.startswith("V:"):
            v = vias.get(k[2:])
            if v:
                out.append(("Via" + k[2:], ("via", v)))
    return out


A = copper(reach("P:" + seedA))
B = copper(reach("P:" + seedB))
print("== %s ==" % os.path.basename(path))
print("   网A（种子 `%s` ✓）：%d 样铜 ✓" % (seedA, len(A)))
print("   网B（种子 `%s` ✓）：%d 样铜 ✓" % (seedB, len(B)))


def d_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L <= 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy))


def d_seg2(a, b, c, d):
    best = min(d_seg(a, c, d), d_seg(b, c, d), d_seg(c, a, b), d_seg(d, a, b))
    cr = lambda o, p, q: (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    if ((cr(a, b, c) > 0) != (cr(a, b, d) > 0)) and ((cr(c, d, a) > 0) != (cr(c, d, b) > 0)):
        return 0.0
    return best


def gap(x, y):
    """净距 ✓（sketch 单位 ✓）；`None` = 不同层、不可比 ✓"""
    k1, a = x
    k2, b = y
    if k1 == "pad" and k2 == "pad":
        if a["layer"] != "both" and b["layer"] != "both" and a["layer"] != b["layer"]:
            return None
        r1 = a["circle"][1] if a.get("circle") else 0.0
        r2 = b["circle"][1] if b.get("circle") else 0.0
        return max(0.0, math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) - r1 - r2)
    if k1 == "pad" and k2 == "wire":
        if a["layer"] != "both" and a["layer"] != b["layer"].replace("trace", ""):
            return None
        return max(0.0, d_seg(a["c"], b["a"], b["b"]) - b["half"])
    if k1 == "wire" and k2 == "pad":
        return gap(y, x)
    if k1 == "wire" and k2 == "wire":
        if a["layer"] != b["layer"]:
            return None
        return max(0.0, d_seg2(a["a"], a["b"], b["a"], b["b"]) - a["half"] - b["half"])
    # 过孔：两层都有铜 ✓ ⇒ 跟谁都比 ✓
    if k1 == "via" and k2 == "via":
        return max(0.0, math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1])
                   - a["R"] - b["R"])
    if k1 == "via":
        if k2 == "pad":
            return max(0.0, math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) - a["R"])
        return max(0.0, d_seg(a["c"], b["a"], b["b"]) - a["R"] - b["half"])
    if k2 == "via":
        return gap(y, x)
    return None


res = []
for na, xa in A:
    for nb, xb in B:
        d = gap(xa, xb)
        if d is not None:
            res.append((d, na, nb, xa, xb))
res.sort(key=lambda z: z[0])
print("\n★★ 网A ↔ 网B 最近的几对铜 ✓（前 8 ✓）：")
for d, na, nb, xa, xb in res[:8]:
    print("   %8.3f mm  %s  `%s` ↔ `%s`"
          % (M(d), "✗ **短了** ✓" if d <= 0 else "（没短 ✓）", na, nb))
zero = [z for z in res if z[0] <= 0]
print("\n★★ **所有**净距 ≤ 0 的对（= 真短 ✓）：%d 对" % len(zero))
for d, na, nb, xa, xb in zero[:20]:
    cx, cy = None, None
    if xa[0] == "via":
        cx, cy = M(xa[1]["c"][0]), M(xa[1]["c"][1])
    elif xb[0] == "via":
        cx, cy = M(xb[1]["c"][0]), M(xb[1]["c"][1])
    else:
        pa = xa[1]["c"] if xa[0] == "pad" else xa[1]["a"]
        cx, cy = M(pa[0]), M(pa[1])
    print("   ✗ A侧 `%s` ↔ B侧 `%s` ✓  约在 (%.3f, %.3f) mm" % (na, nb, cx, cy))
if res:
    print("\n   ⇒ 最小净距 **%.4f mm** ✓ ⇒ %s"
          % (M(res[0][0]), "✗✗ **这两个网在 PCB 铜上真的连上了** ✓（真短路 ✓）"
             if res[0][0] <= 0 else "✓ **没短**（PCB 铜是分开的 ✓）"))
