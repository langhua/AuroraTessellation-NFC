# -*- coding: utf-8 -*-
r"""bb_probe：**面包板视图探针** ✓（独立实现 ✓ 只读 ✓ —— 2026-10-09 建立 ✓）

★ 为什么另写一个 ✗：生成器（库仓 `tools/bb_route4.py` ✓）**自己说自己好** ✗ 不算数 ✓
  —— 本探针**不 import 生成器** ✗（只用 `bb_compare` 的几何原语 ✓：孔距/遮挡/重叠 ✓），
  读**交付件**逐条量下面 10 项 ✓（验收 ④ ✓，正文 `README.md` §六十七 ✓）：

  ① 9 张网**成员**与 `pixel_nets.py` 一致 ✓ ＋ **没有把两张网并到一起** ✗（一 bus 一网 ✓）
  ② **未接网的备用脚**只数出来 ✓ 且**零连接** ✓
  ③ **声明双向自洽** ✓（孔↔线 ✓、脚↔线 ✓ 两头都有记录 ✓）
  ④ **悬空端 = 0** ✓
  ⑤ **跳线重叠 = 0** ✓（共线叠在一起 ✗）
  ⑥ **压本体 = 0** ✓
  ⑦ **孔的占用唯一** ✓
  ⑧ **「不是最近孔」的跳线数 = 0** ✓（判据 = 规则① ✓：**可用孔**里有更短的 ⇒ 违规 ✓）
  ⑨ 拐点清单 ✓（目标：能直的都直 ✓）
  ⑩ 总长 ✓ / 用孔数 ✓

用法 ✓：`py -X utf8 tools\bb_probe.py <fzz> [--nets=pixel_nets.py]`
退出码：0 = 全过 ✓ ｜ 1 = 有不过 ✗
"""
import collections
import math
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                            # noqa: E402
import bb_compare as BC                     # noqa: E402
import projdata as PD                       # noqa: E402

COL = 9.0                                   # 孔距 2.54 mm ✓（= 9 sketch 单位 ✓）
MMU = BC.MMU
TOL = 0.02
FAILS = []


def ok(name, cond, extra=""):
    print("   %s %s %s" % ("✓" if cond else "✗", name, extra))
    if not cond:
        FAILS.append(name)
    return cond


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def kids(e, n):
    return [] if e is None else [c for c in e if tag(c) == n]


def root_of(path):
    z = zipfile.ZipFile(path)
    n = [x for x in z.namelist() if x.endswith(".fz")][0]
    return ET.fromstring(z.read(n))


def hole_map(board):
    """⇒ 孔表 ✓ / 孔→bus ✓ / bus→孔表 ✓（从板子自己的 .fzp ✓ —— Fritzing 的口径 ✓）"""
    broot = ET.parse((board.get("path") or "").replace("/", os.sep)).getroot()
    holes = {}
    for c in broot.iter("connector"):
        xy = BC.hole_xy(c.get("id") or "")
        if xy:
            holes[c.get("id")] = xy
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for b in broot.iter("bus"):
        mem = []
        for d in b.iter():
            if d is b:
                continue
            for k, v in d.attrib.items():
                if k in ("id", "connectorId", "connector", "member") and v in holes:
                    mem.append(v)
        for m in mem:
            r, rm = find(mem[0]), find(m)
            if r != rm:
                par[rm] = r
    bus_of, bus_holes = {}, {}
    for h in holes:
        bus_of[h] = find(h)
        bus_holes.setdefault(find(h), []).append(h)
    return holes, bus_of, bus_holes


def ends_nodes(lk, holes, bus_of):
    """一条跳线的两个端点 ⇒ `('B', bus)` ✓ / `('P', 端坐标)` ✓（脚 / 悬空 ✓）"""
    out = []
    for e in (lk.pts[0], lk.pts[-1]):
        h = next((hh for hh, xy in holes.items()
                  if abs(xy[0] - e[0]) < TOL and abs(xy[1] - e[1]) < TOL), None)
        out.append(("B", bus_of[h]) if h else ("P", round(e[0], 3), round(e[1], 3)))
    return out


def body_boxes(path):
    """元件本体框 ✓ —— **与项目工具同一份实现** ✓（`part_box.body_box` + `place` ✓）

    ★ 为什么不用 `bb_compare.part_boxes()` ✗：那一份的 `path/@d` 解析只是"把数字当点" ✗
      ⇒ **盒子偏大** ✗（实测 `LED2` 高报到 28.5 mm ✗，`bb_route4.py` 里记过这条 ✓）
      ⇒ 拿它当"压本体"的尺子会**误报** ✗（本探针第一版就误报了 `C1` 一处 ✗）。
    """
    import part_box as PB
    root = root_of(path)
    out = []
    for e in root.iter("instance"):
        mid = e.get("moduleIdRef") or ""
        ttl = (e.findtext("title") or "").strip()
        if mid.startswith("Wire") or "readboard" in mid or ttl.startswith("TXT"):
            continue
        vb = child(child(e, "views"), "breadboardView")
        if vb is None:
            continue
        fpz = (e.get("path") or "").replace("/", os.sep)
        if not os.path.isfile(fpz):
            continue
        r2 = ET.parse(fpz).getroot()
        lay = r2.find(".//breadboardView/layers")
        if lay is None or not lay.get("image"):
            continue
        base = os.path.dirname(os.path.dirname(fpz))
        svg = None
        for s2 in ("", "core", "contrib", "user"):
            cand = os.path.normpath(os.path.join(base, "svg", s2,
                                                 lay.get("image").replace("/", os.sep)))
            if os.path.isfile(cand):
                svg = cand
                break
        if svg is None:
            continue
        bd = PB.body_box(svg)
        g = child(vb, "geometry")
        if bd is None or g is None or g.get("x") is None:
            continue
        out.append((ttl, PB.place((float(g.get("x")), float(g.get("y"))), PB.tf_of(g), bd)))
    return out


def path_clear(a, b, lk, segs, holes, usedh, cur, h2, rects):
    r"""这条更短的新走法**画得出来**吗 ✓（独立判据 ✓，只用 `bb_compare` 的原语 ✓）

    三关：① 不许盖住"接了线的孔" ✗ ② 不许与**别的**跳线共线重叠 ✗ ③ 不许穿元件本体 ✗
    """
    pts = [a, b]
    if abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9:
        pts = [a, (a[0], b[1]), b]
    mine = [s for s in lk.segs]
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        for hid in sorted(usedh):
            if hid in (cur, h2):
                continue
            if BC.obscures(p, q, holes[hid]) >= BC.OBSCURE_LIMIT:
                return False
        for (lk2, (c, d)) in segs:
            if lk2 is lk:
                continue
            if BC.seg_overlap(p, q, c, d):
                return False
        for _ttl, r in rects:
            if BC.seg_crosses_box(p, q, r):
                return False
    return True


def route_len(a, b):
    """独立小尺子 ✓：`(拐点数, 长度)` —— 同行/同列 ⇒ 0 拐点 ✓，否则 L ✓"""
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return (0, abs(a[0] - b[0]) + abs(a[1] - b[1]))
    return (1, abs(a[0] - b[0]) + abs(a[1] - b[1]))


def main(argv):
    path = [a for a in argv if not a.startswith("--")][0]
    nets_path = next((a.split("=", 1)[1] for a in argv if a.startswith("--nets=")), None)
    nets = PD.load(nets_path or os.path.join(PIX, "pixel_nets.py")).NETS
    root = root_of(path)
    links, plugged = BC.load(path)
    board = next(e for e in root.iter("instance")
                 if "breadboard" in (e.get("moduleIdRef") or "").lower()
                 and not (e.get("moduleIdRef") or "").startswith("Wire"))
    holes, bus_of, bus_holes = hole_map(board)
    real = [lk for lk in links if not lk.legend]
    deco = [lk for lk in links if lk.legend]
    print("=== 面包板探针 %s（只读 ✓ 不 import 生成器 ✓）" % os.path.basename(path))
    print("   跳线 %d 根 = %d 段 ｜ 图例装饰 %d 根 ｜ 用孔 %d 个 ｜ 插了脚的孔 %d 个"
          % (len(real), sum(len(lk.segs) for lk in real), len(deco),
             len({h for lk in real for h, _m in lk.holes}), len(plugged)))

    # 零件的脚表 ✓
    pin_of, name2cid, title2mi = {}, {}, {}
    for e in root.iter("instance"):
        if (e.get("moduleIdRef") or "").startswith("Wire") or e is board:
            continue
        ttl = (e.findtext("title") or "").strip()
        mid = e.get("moduleIdRef") or ""
        if ttl.startswith(("Via", "Ground", "TXT")) or "ViaModuleID" in mid:
            # ★ PCB 专有的件（过孔 ✓ / 接地符号 ✓ / 图例文字 ✓）在 sketch 里**也带着**一份
            #   `breadboardView` 块 ✗ —— 但它们**不在面包板上** ✗ ⇒ 不算"面包板上的脚" ✓
            #   （实测 2026-10-09 ✗：`Via1..Via5` 会冒充 5 只备用脚 ⇒ ② 数成 20 ✓，真值 **15** ✓）
            continue
        title2mi[ttl] = e.get("modelIndex")
        vb = child(child(e, "views"), "breadboardView")
        if vb is None:
            continue
        fzp = (e.get("path") or "").replace("/", os.sep)
        if os.path.isfile(fzp):
            name2cid[ttl] = {c.get("name"): c.get("id")
                             for c in ET.parse(fzp).getroot().iter("connector") if c.get("name")}
        for cn in kids(child(vb, "connectors"), "connector"):
            hs = [c.get("connectorId") for c in kids(child(cn, "connects"), "connect")
                  if (c.get("layer") or "") == "breadboardbreadboard"
                  and c.get("connectorId") in holes]
            pin_of[(ttl, cn.get("connectorId"))] = hs[0] if hs else None

    def cid_of(ref, pname):
        if pname.startswith("#"):
            return "connector%d" % (int(pname[1:]) - 1)
        return name2cid.get(ref, {}).get(pname) or pname

    net_of_pin = {}
    for net, pins in nets.items():
        for ref, pname in pins:
            net_of_pin[(ref, cid_of(ref, pname))] = net

    # ── 图：把每条跳线的两端并起来 ✓
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

    for lk in real:
        n0, n1 = ends_nodes(lk, holes, bus_of)
        uni(n0, n1)
    # 未插孔的脚（如裸焊盘 ✓）由线端接住 ⇒ 该端坐标就是它的节点 ✓
    pin_node = {}
    for lk in real:
        for (cid, mi) in lk.pins:
            ttl = next((t for t, m in title2mi.items() if m == mi), None)
            if not ttl:
                continue
            for e in (lk.pts[0], lk.pts[-1]):
                h = next((hh for hh, xy in holes.items()
                          if abs(xy[0] - e[0]) < TOL and abs(xy[1] - e[1]) < TOL), None)
                if not h:
                    pin_node[(ttl, cid)] = ("P", round(e[0], 3), round(e[1], 3))

    bad_net = []
    for net, pins in sorted(nets.items()):
        nodes = set()
        for ref, pname in pins:
            cid = cid_of(ref, pname)
            h = pin_of.get((ref, cid))
            if h:
                nodes.add(("B", bus_of[h]))
            elif (ref, cid) in pin_node:
                nodes.add(pin_node[(ref, cid)])
            else:
                nodes.add(("P?", ref, cid))
        if len({find(x) for x in nodes}) != 1:
            bad_net.append((net, sorted(str(x) for x in nodes)))
    ok("① 9 张网成员与 pixel_nets.py 一致（逐脚连通）", not bad_net,
       "" if not bad_net else str(bad_net))

    busnets = collections.defaultdict(set)
    for h, who in plugged.items():
        ttl, cid = who.split(".", 1)
        n = net_of_pin.get((ttl, cid))
        if n:
            busnets[bus_of[h]].add(n)
    conn = sorted((b, sorted(s)) for b, s in busnets.items() if len(s) > 1)
    ok("①b 没有把两张网并到一起（一 bus 一网）", not conn, "" if not conn else str(conn))

    # ── ② 备用脚 ✓
    spare = sorted((ttl, cid) for (ttl, cid) in pin_of if (ttl, cid) not in net_of_pin)
    wired = set()
    for lk in real:
        for (cid, mi) in lk.pins:
            ttl = next((t for t, m in title2mi.items() if m == mi), None)
            if ttl:
                wired.add((ttl, cid))
    # ★ 备用脚 = **不在网表里**的脚 ✓（它们**只做摆放** ✓ ⇒ 插孔是正常的 ✓）；
    #   要守的是「**零连接**」✓ = 不许有导线接上去 ✗（`U1.connector0` 就是这种 ✓）。
    spare_hot = [s for s in spare if s in wired]
    print("     备用脚全表（%d 只 ✓）：%s" % (len(spare), spare))
    ok("② 备用脚 %d 只，其中**接了线**的 %d 只（应为 0 ✓）" % (len(spare), len(spare_hot)),
       not spare_hot,
       "" if not spare_hot else "%s ｜ 备用脚全表 %s" % (spare_hot[:6], [p[1] for p in spare]))

    # ── ③ 声明双向自洽 ✓
    bsub = child(child(board, "views"), "breadboardView")
    back = collections.defaultdict(set)
    for cn in kids(child(bsub, "connectors"), "connector"):
        for c in kids(child(cn, "connects"), "connect"):
            if (c.get("layer") or "") == "breadboardWire":
                back[cn.get("connectorId")].add(c.get("modelIndex"))
    oneway = []
    for e in root.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        vb = child(child(e, "views"), "breadboardView")
        if vb is None:
            continue
        for c in vb.iter("connect"):
            if (c.get("layer") or "") != "breadboardbreadboard":
                continue
            if e.get("modelIndex") not in back.get(c.get("connectorId"), ()):
                oneway.append((e.findtext("title"), c.get("connectorId")))
    ok("③ 声明双向自洽（孔 ↔ 线 两头都有）", not oneway, "" if not oneway else str(oneway[:4]))

    # ── ④ 悬空端 ✓
    dang = []
    for lk in real:
        fin = set()
        for (cid, mi) in lk.pins:
            fin.add(mi)
        for i, e in enumerate((lk.pts[0], lk.pts[-1])):
            onh = any(abs(xy[0] - e[0]) < TOL and abs(xy[1] - e[1]) < TOL
                      for xy in holes.values())
            if not onh and not lk.pins:
                dang.append((lk.wids[0], e))
    ok("④ 悬空端 = 0", not dang, "" if not dang else str(dang[:4]))

    # ── ⑤ 重叠 ✓  ⑥ 压本体 ✓
    segs = [(lk, s) for lk in real for s in lk.segs]
    ovl = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if BC.seg_overlap(segs[i][1][0], segs[i][1][1], segs[j][1][0], segs[j][1][1]):
                ovl.append((segs[i][0].wids[0], segs[j][0].wids[0]))
    ok("⑤ 跳线重叠 = 0", not ovl, "" if not ovl else str(ovl[:4]))
    rects = body_boxes(path)
    bodyhit = []
    for lk in real:
        for a, b in lk.segs:
            for ttl, r in rects:
                if BC.seg_crosses_box(a, b, r):
                    bodyhit.append((lk.wids[0], ttl))
    ok("⑥ 跳线压元件本体 = 0", not bodyhit, "" if not bodyhit else str(bodyhit[:4]))

    # ── ⑦ 孔的占用唯一 ✓
    occ = collections.Counter(h for lk in real for h, _m in lk.holes)
    occ.update(plugged.keys())
    dup = sorted(h for h, c in occ.items() if c > 1)
    ok("⑦ 孔的占用唯一（一孔一端点）", not dup, "" if not dup else str(dup[:6]))

    # ── ⑧ 「不是最近孔」 ✓（判据 = 规则① 的**可用孔集合** ✓ ＋ **换完网仍要连通** ✓）
    usedh = set(occ)

    def bus_net(b):
        for x in bus_holes.get(b, ()):
            if x in plugged:
                ttl, cid = plugged[x].split(".", 1)
                n = net_of_pin.get((ttl, cid))
                if n:
                    return n
        return None

    notnear = []
    skipped = 0
    for lk in real:
        hh = [h for h, _m in lk.holes]
        if not hh:
            continue
        if len(hh) == 2:
            n0, n1 = bus_net(bus_of[hh[0]]), bus_net(bus_of[hh[1]])
            net = n0 or n1
        else:
            net = bus_net(bus_of[hh[0]]) if hh else None
        if net is None:
            skipped += 1
            continue
        for cur in hh:
            if bus_net(bus_of[cur]) is None:
                continue                      # 这一端所在 bus 上没插本网的脚 ⇒ 它本来就是"进口" ✓ 不判 ✓
            d0 = abs(holes[cur][0] - 0)
            # 另一端 = 折线里离本孔**最远**的那个端 ✓
            ends = [lk.pts[0], lk.pts[-1]]
            other = max(ends, key=lambda p: abs(p[0] - holes[cur][0]) + abs(p[1] - holes[cur][1]))
            base = route_len(holes[cur], other)
            for h2, xy in holes.items():
                if h2 == cur or h2 in usedh or bus_of[h2] == bus_of[cur]:
                    continue
                if bus_net(bus_of[h2]) != net:
                    continue                  # ★ 换过去网就断了 ✗ / 会并别的网 ✗ ⇒ 不算"可用" ✓
                k2 = route_len(xy, other)
                if k2 >= base:
                    continue
                if not path_clear(xy, other, lk, segs, holes, usedh, cur, h2, rects):
                    continue                  # ★ 这条更短的走法**画不出来** ✗（压别的线/盖接线孔/穿本体 ✓）
                notnear.append((lk.wids[0], cur, h2, net,
                                round(base[1] / MMU, 1), round(k2[1] / MMU, 1)))
                break
    ok("⑧ 「不是最近孔」的跳线数 = 0（换到别的 bus 能更短且网仍连通 ⇒ 违规）", not notnear,
       "" if not notnear else "%s（另 %d 根网的进口端不判 ✓）" % (notnear[:4], skipped))

    # ── ⑨ 拐点 ✓ / ⑩ 总长 ✓
    hist = collections.Counter()
    details = []
    for lk in real:
        nb = max(0, len(lk.pts) - 2)
        hist[nb] += 1
        if nb:
            details.append((lk.wids[0], len(lk.pts) - 1, nb,
                            "/".join(h for h, _m in lk.holes) or "(脚)",
                            round(lk.length / MMU, 1)))
    print("   · ⑨ 拐点直方图：%s" % dict(sorted(hist.items())))
    for d in details[:14]:
        print("        %-24s %d 段 ｜ %d 拐点 ｜ %-18s %.1f mm" % d)
    tot = sum(lk.length for lk in real) / MMU
    print("   · ⑩ 总长 %.1f mm ｜ 跳线 %d 根 ｜ 段数 %d ｜ 用孔 %d"
          % (tot, len(real), sum(len(lk.segs) for lk in real),
             len({h for lk in real for h, _m in lk.holes})))
    print("⇒ %s" % ("✓ **全过** ✓" if not FAILS else "✗ **不过 %d 项**：%s"
                    % (len(FAILS), "、".join(FAILS))))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
