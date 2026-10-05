# -*- coding: utf-8 -*-
r"""**保线清单** ✓ —— 把"他画的 PCB 走线/过孔"读出来 ⇒ 每段属于哪张网、接到哪个焊盘 ✓

用法 ✓：`fz_keep_set.py <file.fzz> [<输出.py>]`
产出（纯数据 ✓，可 `--check` 复核 ✓）：
  `KEEP`  = `[(net, lay, (x, y), (x, y))]` ✓ 走线（**草图单位** ✓，与文件里一致 ✓）
  `KEEP_V`= `[(net, (x, y))]` ✓ 过孔
  `REPS`  = `{net: [(位号, connectorN), …]}` ✓ 每条链的**代表脚**（同网的链各取一个 ✓）
  `DONE`  = `{net: [脚, …]}` ✓ 该链**已经连到**的脚 ✓

判据 ✓（**只用文件里写的东西** ✓，不猜 ✗）：
  · 走线/过孔 = 带 `pcbView` 的 `Wire`/`Via` ✓；
  · 归属 = `<connect>` 连成的链 ✓ ⇒ 链上的焊盘 ∩ `EXPECT[net]` 非空 ⇒ 属于该网 ✓；
  · 链与链**分开**（同网两条链要各给代表脚 ✓ —— 例 GND 有两条 ✓）。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))      # = 本目录（`hardware\pixel` ✓）
PIX = HERE
sys.path.insert(0, PIX)
import toolpaths                                                  # noqa: E402,F401
import projdata                                                    # noqa: E402
import pcb_wire as PW                                             # noqa: E402

EXPECT = projdata.load(os.path.join(PIX, "pixel_nets.py"), need=("EXPECT",)).EXPECT
PAD2NET = {}
for _n, _s in EXPECT.items():
    for _p in _s:
        PAD2NET.setdefault(_p, _n)


def blocks(text):
    out = []
    for m in re.finditer(r"<title>([^<]*)</title>", text):
        a = text.rfind("<instance", 0, m.start())
        b = text.find("</instance>", m.end())
        if a < 0 or b < 0:
            continue
        out.append((m.group(1), text[a:b + len("</instance>")]))
    return out


def main(argv):
    z = zipfile.ZipFile(argv[0])
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    B = blocks(z.read(fz).decode("utf-8", "replace"))
    by_mi, pcb = {}, {}
    for ttl, blk in B:
        q = re.search(r'modelIndex="([^"]+)"', blk)
        if not q:
            continue
        by_mi[q.group(1)] = ttl
        mid = re.search(r'moduleIdRef="([^"]+)"', blk)
        if mid and mid.group(1).startswith(("Wire", "Via")) and "<pcbView" in blk:
            pcb[q.group(1)] = (ttl, mid.group(1), blk)

    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    for mi, (_t, _m, blk) in pcb.items():
        find(mi)
        seg = blk[blk.find("<pcbView"):]
        for c in re.finditer(r"<connect\b[^>]*/>", seg):
            q = re.search(r'modelIndex="([^"]+)"', c.group(0))
            cid = re.search(r'connectorId="([^"]*)"', c.group(0))
            if not q:
                continue
            peer = by_mi.get(q.group(1), q.group(1))
            if peer.startswith(("Wire", "Via")):
                uni(mi, q.group(1))
            else:
                uni(mi, "%s.%s" % (peer, cid.group(1) if cid else "?"))

    comp = {}
    for k in list(par):
        comp.setdefault(find(k), []).append(k)

    KEEP, KEEP_V, REPS, DONE, UNKNOWN = [], [], {}, {}, []
    for _r, nodes in sorted(comp.items()):
        pads = sorted(n for n in nodes if not n.isdigit())
        nets = {PAD2NET[p] for p in pads if p in PAD2NET}
        if not nodes or not any(n in pcb for n in nodes):
            continue                                   # 无走线的组件（纯焊盘）✗ 跳过 ✓
        net = (sorted(nets)[0] if len(nets) == 1 else None)
        if net is None:
            UNKNOWN.append(pads)
            continue
        for n in nodes:
            if n not in pcb:
                continue
            ttl, mid, blk = pcb[n]
            # ★★ 几何**只认库里的那一份读法** ✓（`pcb_wire.parse_trace` ✓）：
            #   · 它**按标签配对**切段 ✓（`<pcbView …>(.*?)</pcbView>` ✓，见 `pcb_wire.py:87` ✓）
            #   · 绝对端点 = `(x+x1, y+y1)` / `(x+x2, y+y2)` ✓（`abs_ends` ✓，见 `pcb_wire.py:109` ✓）
            #  ✗✗ 我原来的写法是 `blk[blk.find("<pcbView"):]` —— **一路切到块尾** ✗ ⇒
            #     把后面 `schematicView` 的几何**当成 PCB 的读进来** ✗ ⇒ 障碍框位置全错 ✗
            #     （实测 `Wire90013354`：pcb 段 (53.00,23.01)→(55.01,18.00) ✓、
            #      而原理图段是另一条 ✗ —— 两者被混在一起过 ✓）。
            t = PW.parse_trace(blk)
            if t is None:
                continue
            lay = t.get("layer") or "copper0trace"
            lay = lay[:7] if lay.startswith("copper") else lay
            if mid.startswith("Via"):
                a, _b = PW.abs_ends(t["geo"])
                KEEP_V.append((net, (a[0], a[1])))
            else:
                # ★★★ 2026-10-03 ✓：走线可能是**贝塞尔曲线** ✗（实测 17 根 ✓）——
                #   一律**按曲线采样成折线** ✓（直线也走这条路 ✓，只是两点 ✓）
                #   ✗ 旧写法只存两端 ⇒ 布线器把弯铜当**直线**框 ✗ ⇒ 障碍框落在错的格上 ✗
                #     （很可能就是“起点格空”的元凶 ✓）。
                pts = PW.curve_pts(t["geo"], t.get("bezier"), 16)
                # ★★ 2026-10-05 补**线宽** ✓（用户点名「布线器留距要按线半宽算」✓）：
                #   ✗ 旧写法只存形状 ✓ ⇒ 消费方只能用**全局 24 mil 代理** ✗
                #     ⇒ 一条 **8 mil** 的线被按 24 mil 算 ✗ ⇒ 多封锁 0.2 mm/边 ✗
                #     （实测：`LED2.connector2` 的起步格就是被这样「保线:5V」封死的 ✗）。
                #   `mils` 不在就按 Fritzing 默认 **12 mil** ✓（写清来源 ✓，不猜 ✗）。
                KEEP.append((net, lay, [(p[0], p[1]) for p in pts],
                             t.get("mils") or 12.0))
        got = [p for p in pads if p in PAD2NET and PAD2NET[p] == net]
        if got:
            REPS.setdefault(net, []).append(got[0])
            DONE.setdefault(net, []).extend(got)

    print("== 保线清单 ✓（%s）==" % os.path.basename(argv[0]))
    for net in sorted(set(n for n, _l, _p, _m in KEEP) | set(n for n, _q in KEEP_V)):
        w = sum(1 for n, _l, _p, _m in KEEP if n == net)
        seg = sum(len(p) - 1 for n, _l, p, _m in KEEP if n == net)
        v = sum(1 for n, _p in KEEP_V if n == net)
        print("  %-5s 走线 %2d ✓｜过孔 %d ✓｜代表脚 %s ✓"
              % (net, w, v, "、".join(REPS.get(net, [])) or "✗ 无"))
        print("      已连到 ✓：%s" % "、".join(sorted(DONE.get(net, []))))
    if UNKNOWN:
        print("  ⚠️ 认不出网的链 %d 条 ✗（焊盘：%s）" % (len(UNKNOWN), UNKNOWN))
    if len(argv) > 1:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-\n")
            f.write("# **保线清单**（由 `fz_keep_set.py` 生成 ✓ 纯数据 ✓，别手改 ✗）\n")
            f.write("#   KEEP   = 保留的走线 (net, lay, (x, y), (x, y)) ✓ 草图单位 ✓\n")
            f.write("#   KEEP_V = 保留的过孔 (net, (x, y)) ✓\n")
            f.write("#   REPS   = 每张网、**每条链**取一个代表脚 ✓（网表用它 ⇒ 新线从这里往外接 ✓）\n")
            f.write("#   DONE   = 该网**链上已经连到**的脚 ✓（这些脚**不需要**再布线 ✓）\n")
            f.write("KEEP = [\n")
            for it in KEEP:
                f.write("    %r,\n" % (it,))
            f.write("]\nKEEP_V = [\n")
            for it in KEEP_V:
                f.write("    %r,\n" % (it,))
            f.write("]\nREPS = %r\nDONE = %r\n" % (REPS, DONE))
        print("   已写出 ✓：%s" % argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
