# -*- coding: utf-8 -*-
r"""★★ 迭代式收拾"跨网太近/短接" ✓ —— 反复跑闸门 ✓、每轮挪一颗过孔 ✓，直到达标 ✓

用户 2026-10-02：「**全部收拾了**」✓（4 处真接触 + 42 处 <0.15 mm ✓）

口径 ✓（与 `fz_net_short.py --all` 同源 ✓）：
  · 网 = 按文件里的 `<connect>` 走通的片 ✓（脚/线/孔 ✓）—— ✗ 不比同网的 ✓
  · 焊盘真形状 ✓、走线 = 有宽度的线段 ✓、过孔圆心 = 文件 x,y + `ring_off_mm` ✓
  · **跨网**目标净距 ✓：牵涉**过孔** ⇒ ≥ **0.25 mm** ✓（本仓 `VIA_SAFE_MM` ✓）；
    线↔线 ⇒ ≥ **0.20 mm** ✓（制造可做 ✓）。同网**不管** ✓。

手段 ✓（只能做"**可逆、局部、几何等价**"的改动 ✓）：
  挪一颗过孔 ⇒ 只改 **3 处数字** ✓（过孔 `x,y` ✓ ＋ 它两条短线各自的"过孔那侧"端点 ✓）；
  **远端一个像素不动** ✓（Fritzing 的走线 = `x,y` + 相对端点 ⇒ 重写时以远端为原点 ✓）。
✗ 挪不动的（纯线↔线、两端都焊死在焊盘上 ✓）**明确列出来** ✓，不装作修好了 ✓。

用法 ✓：`fz_fix_clearance.py <in.fzz> <out.fzz> [轮数=40]`
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
TIGHT_VIA = 0.25           # mm ✓ 牵涉过孔
TIGHT_WIRE = 0.20          # mm ✓ 线↔线
src, dst = sys.argv[1], sys.argv[2]
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 40

zin = zipfile.ZipFile(src)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")


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


def load(txt):
    """⇒ (pads, wires, vias, nets 的并查集 ✓, stub 表 ✓)"""
    pads, wires, vias, adj = {}, {}, {}, {}
    for q in PC.collect(src)["pads"]:
        pads["%s.%s" % (q.get("mi"), q["cid"])] = q

    def link(a, b):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    stubs = {}
    for _i, b in PW.blocks(txt):
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
            vias[mi.group(1)] = dict(mi=mi.group(1), off=off,
                                     c=(float(x.group(1)) + off, float(x.group(2)) + off),
                                     R=(hole / 2 + ring) / SK)
            stubs[mi.group(1)] = []
        me = ("W:" + mi.group(1)) if mid.startswith("Wire") else \
             (("V:" + mi.group(1)) if mid.startswith("Via") else None)
        for cm in re.finditer(r'(?s)<connector connectorId="(\w+)"[^>]*>(.*?)</connector>',
                              g.group(1)):
            cid = cm.group(1)
            src_ = ("P:%s.%s" % (mi.group(1), cid)) if ("%s.%s" % (mi.group(1), cid)) in pads \
                else me
            if src_ is None:
                continue
            for x in re.finditer(r'<connect connectorId="(\w+)" modelIndex="(\d+)"', cm.group(2)):
                t, tcid = x.group(2), x.group(1)
                for cand in (("W:" + t if t in wires else None),
                             ("V:" + t if t in vias else None),
                             (("P:%s.%s" % (t, tcid)) if ("%s.%s" % (t, tcid)) in pads else None)):
                    if cand:
                        link(src_, cand)
                        if src_.startswith("V:") and cand.startswith("W:"):
                            stubs[src_[2:]].append(cand[2:])
                        if src_.startswith("W:") and cand.startswith("V:"):
                            stubs.setdefault(cand[2:], []).append(src_[2:])
    return pads, wires, vias, adj, stubs


def gap(a, b):
    (k1, x1), (k2, x2) = a, b
    if k1 == "pad" and k2 == "pad":
        if x1["layer"] != "both" and x2["layer"] != "both" and x1["layer"] != x2["layer"]:
            return None
        r1 = x1["circle"][1] if x1.get("circle") else 0.0
        r2 = x2["circle"][1] if x2.get("circle") else 0.0
        return max(0.0, math.hypot(x1["c"][0] - x2["c"][0], x1["c"][1] - x2["c"][1]) - r1 - r2)
    if k1 == "pad" and k2 == "wire":
        if x1["layer"] != "both" and x1["layer"] != x2["layer"].replace("trace", ""):
            return None
        return max(0.0, d_seg(x1["c"], x2["a"], x2["b"]) - x2["half"])
    if k1 == "wire" and k2 == "pad":
        return gap(b, a)
    if k1 == "wire" and k2 == "wire":
        if x1["layer"] != x2["layer"]:
            return None
        return max(0.0, d_seg2(x1["a"], x1["b"], x2["a"], x2["b"]) - x1["half"] - x2["half"])
    if k1 == "via" and k2 == "via":
        return max(0.0, math.hypot(x1["c"][0] - x2["c"][0], x1["c"][1] - x2["c"][1])
                   - x1["R"] - x2["R"])
    if k1 == "via":
        if k2 == "pad":
            return max(0.0, math.hypot(x1["c"][0] - x2["c"][0], x1["c"][1] - x2["c"][1]) - x1["R"])
        return max(0.0, d_seg(x1["c"], x2["a"], x2["b"]) - x1["R"] - x2["half"])
    if k2 == "via":
        return gap(b, a)
    return None


def copper_of(key, pads, wires, vias):
    if key.startswith("P:"):
        q = pads.get(key[2:])
        return ("pad", q) if q else None
    if key.startswith("W:"):
        w = wires.get(key[2:])
        return ("wire", w) if w else None
    v = vias.get(key[2:])
    return ("via", v) if v else None


def violations(txt):
    pads, wires, vias, adj, stubs = load(txt)
    root = {}

    def find(x):
        root.setdefault(x, x)
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    for k in list(adj):
        find(k)
    for a, ns in adj.items():
        for b in ns:
            if find(a) != find(b):
                root[find(a)] = find(b)
    grp = {}
    for k in list(adj):
        grp.setdefault(find(k), []).append(k)
    nets = [v for v in grp.values() if any(x.startswith("P:") for x in v)]
    out = []
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            for ka in nets[i]:
                xa = copper_of(ka, pads, wires, vias)
                if xa is None:
                    continue
                for kb in nets[j]:
                    xb = copper_of(kb, pads, wires, vias)
                    if xb is None:
                        continue
                    d = gap(xa, xb)
                    if d is None:
                        continue
                    lim = TIGHT_VIA if ("via" in (xa[0], xb[0])) else TIGHT_WIRE
                    if d * SK < lim:
                        out.append((d * SK, ka, kb, ka if ka.startswith("V:") else
                                    (kb if kb.startswith("V:") else None)))
    out.sort()
    return out, pads, wires, vias, stubs, adj


def apply_via_move(txt, vmi, newc):
    """挪一颗过孔 ✓：改它的 x,y ＋ 它两条短线"过孔那侧"的端点 ✓（远端不动 ✓）"""
    pads, wires, vias, adj, stubs = load(txt)[:5]
    kk = [k for k in (stubs.get(vmi) or []) if ("W:" + k) in adj or True]
    v = vias[vmi]

    def fix_via(m):
        return '<geometry z="%s" x="%s" y="%s"' % (
            m.group(1), PW.fmt(newc[0] - v["off"]), PW.fmt(newc[1] - v["off"]))

    def fix_stub(m):
        z, x, y, x1, y1, x2, y2 = m.groups()
        X, Y = float(x), float(y)
        a = (X + float(x1), Y + float(y1))
        b = (X + float(x2), Y + float(y2))
        far = b if (math.hypot(a[0] - v["c"][0], a[1] - v["c"][1])
                    < math.hypot(b[0] - v["c"][0], b[1] - v["c"][1])) else a
        return ('<geometry z="%s" x="%s" y="%s" x1="%s" y1="%s" x2="%s" y2="%s"'
                % (z, PW.fmt(far[0]), PW.fmt(far[1]), PW.fmt(newc[0] - far[0]),
                   PW.fmt(newc[1] - far[1]), "0", "0"))

    out = txt
    pat = re.compile(r'(?s)<instance\b[^>]*\bmodelIndex="%s"[^>]*>.*?</instance>' % vmi)
    blk = pat.search(out).group(0)
    out = out.replace(blk, re.sub(r'<geometry z="([\d.]+)" x="[-\d.]+" y="[-\d.]+"',
                                  fix_via, blk, count=1), 1)
    for k in kk:
        p2 = re.compile(r'(?s)<instance\b[^>]*\bmodelIndex="%s"[^>]*>.*?</instance>' % k)
        b2 = p2.search(out).group(0)
        nb = re.sub(r'<geometry z="([\d.]+)" x="([-\d.]+)" y="([-\d.]+)" x1="([-\d.]+)" '
                    r'y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', fix_stub, b2, count=1)
        if nb != b2:
            out = out.replace(b2, nb, 1)
    return out, len(kk)


print("== 收拾 `%s` ⇒ `%s` ✓（过孔目标 %.2f mm ✓ / 线线目标 %.2f mm ✓）=="
      % (os.path.basename(src), os.path.basename(dst), TIGHT_VIA, TIGHT_WIRE))
done = set()
for rd in range(1, ROUNDS + 1):
    vio, pads, wires, vias, stubs, _ = violations(text)
    if not vio:
        print("   ✓ 第 %d 轮：**全部达标** ✓（跨网净距都 ≥ 目标 ✓）" % rd)
        break
    # 挑一处"牵涉过孔"的 ✓（优先最差的 ✓）
    pick = next(((d, a, b, v) for (d, a, b, v) in vio if v), None)
    if pick is None:
        print("   ⚠ 第 %d 轮：剩 %d 处，**都不牵涉过孔** ✗（纯线↔线 ✓）⇒ 需要重画走线 ✓"
              % (rd, len(vio)))
        for d, a, b, _v in vio[:12]:
            print("        %6.4f mm  `%s` ↔ `%s`" % (d, a, b))
        break
    d0, ka, kb, vkey = pick
    vmi = vkey[2:]
    if vmi in done:
        # 这颗已经挪过没用 ⇒ 换下一颗 ✓
        nxt = next(((d, a, b, v) for (d, a, b, v) in vio if v and v[2:] not in done), None)
        if nxt is None:
            print("   ⚠ 第 %d 轮：牵涉过孔的违规里，能挪的都挪过了 ⇒ 剩下 %d 处" % (rd, len(vio)))
            for d, a, b, _v in vio[:12]:
                print("        %6.4f mm  `%s` ↔ `%s`" % (d, a, b))
            break
        d0, ka, kb, vkey = nxt
        vmi = vkey[2:]
    V = vias[vmi]
    # 搜位置 ✓：先按"离**所有外来铜**最远"选 ✓
    own = set()
    _, _, _, adj2, _ = load(text)[:5]
    seen, st = set(["V:" + vmi]), ["V:" + vmi]
    while st:
        n = st.pop()
        for m in adj2.get(n, ()):
            if m not in seen:
                seen.add(m)
                st.append(m)
    own = seen

    def minclear(c):
        best = None
        # ★★ 硬约束 ✓：跟**任何**过孔（**含同网** ✗）的铜环净距都要 ≥0.10 mm ✓
        #   —— 实测教训：不加这条时，挪动会把同网的两颗孔挤到只隔 0.416 mm ✗
        #   （两个 0.6 mm 环压在一起 ✓ 不是短路 ✓ 但制造上不行 ✗）。返回 −9 表示"不合格" ✓。
        for k, o in vias.items():
            if k == vmi:
                continue
            dd = math.hypot(c[0] - o["c"][0], c[1] - o["c"][1]) - V["R"] - o["R"]
            if dd * SK < 0.10:
                return -9.0
        for k, w in wires.items():
            if ("W:" + k) in own:
                continue
            dd = d_seg(c, w["a"], w["b"]) - V["R"] - w["half"]
            best = dd if best is None else min(best, dd)
        for k, q in pads.items():
            if ("P:" + k) in own:
                continue
            r = q["circle"][1] if q.get("circle") else 0.0
            dd = math.hypot(c[0] - q["c"][0], c[1] - q["c"][1]) - V["R"] - r
            best = dd if best is None else min(best, dd)
        for k, o in vias.items():
            if k == vmi or ("V:" + k) in own:
                continue
            dd = math.hypot(c[0] - o["c"][0], c[1] - o["c"][1]) - V["R"] - o["R"]
            best = dd if best is None else min(best, dd)
        return best * SK

    cur = minclear(V["c"])
    best = (cur, None)
    for r_mm in (0.2, 0.3, 0.4, 0.5, 0.7, 0.9, 1.2, 1.5):
        for i in range(24):
            ang = 2 * math.pi * i / 24
            c = (V["c"][0] + (r_mm / SK) * math.cos(ang),
                 V["c"][1] + (r_mm / SK) * math.sin(ang))
            dd = minclear(c)
            if dd > best[0] + 1e-9:
                best = (dd, c)
    if best[1] is None:
        done.add(vmi)
        print("   · 第 %d 轮：`%s` 挪不出更好的位置（当前 %.4f mm）⇒ 先放过 ✓"
              % (rd, vmi, cur))
        continue
    text, nstub = apply_via_move(text, vmi, best[1])
    print("   ✓ 第 %d 轮：挪过孔 `%s`（带 %d 条短线 ✓）：最小外来净距 %.4f → **%.4f mm** ✓"
          "（本轮最差违规 %.4f mm 在 `%s` ↔ `%s` ✓）"
          % (rd, vmi, nstub, cur, best[0], d0, ka, kb))
    done.add(vmi)

zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
for n in zin.namelist():
    zout.writestr(n, text.encode("utf-8") if n == fz else zin.read(n))
zout.close()
print("✓ 写出 `%s` ✓" % os.path.basename(dst))
vio, *_ = violations(text)
print("   最终剩余违规（跨网净距 < 目标 ✓）：**%d** 处" % len(vio))
for d, a, b, _v in vio[:15]:
    print("      %6.4f mm  `%s` ↔ `%s`" % (d, a, b))
