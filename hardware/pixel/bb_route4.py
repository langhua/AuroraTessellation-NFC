# -*- coding: utf-8 -*-
r"""Breadboard jumper router v4 (ASCII-only source; rewritten 2026-09-26 after a
PowerShell `Get-Content -Raw | Set-Content` mangled the previous file's UTF-8 text).

Rules implemented (user-approved, `AGENTS.md` 5b / `hardware/pixel/breadboard-wiring.md`):
  1. one wire per hole, including wire<->wire (no two wires may share a hole endpoint);
  2. no wire over a part body; no hole under a part body may be used;
  3. hard gate: if one bus carries pins of two different nets, stop and write nothing
     (that is a real short on the board - layout must be fixed, not patched);
  4. bent routes (polyline) are preferred over straight 45-degree lines; no two wires
     may overlap; prefer routes that do not pass over other wires' endpoint holes.

Geometry facts used (measured, see tools/README.md):
  * hole id "pin<col><row>": sketch x = 9 * col, sketch y = ROW_Y[row] (units of 1/90 in);
  * a part's placement is `sketch = loc + M * local + (m31,m32)`, M from <transform>;
  * a part's footprint = bbox of what is drawn (part_box.body_box), not the svg canvas;
  * a jumper is stored as two-point wires; a bend = two wires joined end to end.

Usage: py bb_route4.py <input.fzz> <output.fzz>
"""
import collections
import copy
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SCRATCH = os.path.dirname(os.path.abspath(__file__))
# ★★ 2026-09-27（用户定 ✓）：**通用工具只有一份，就在元件库仓 `tools/`** ✓ ——
#   本项目 hardware/pixel/ 里**不再留副本** ✗（我一度又拷了一份 ⇒ 正是"两份实现" ✗）。
#   ⇒ import 一律从 `TOOLS` 来 ✓；定位写在 `toolpaths.py` ✓（**一处** ✓，不每个脚本各写一遍 ✗）。
import toolpaths                                             # noqa: E402
PIXEL = os.path.dirname(os.path.abspath(__file__))        # ★ 自定位 ✓
import part_measure as pm                        # noqa: E402
import part_box as pbox                          # noqa: E402
# ★ 几何/度量与仓库里的对比工具**共用一份实现** ✓（2026-09-26 ✓）——
#   以前两边各算各的 ✗ ⇒ 盒子算错了也“自检通过” ✗（同源校验骗自己 ✗）
import bb_compare as BC                          # noqa: E402

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0, "X": 171.0, "W": 180.0}
COL_PITCH = 9.0
HOLE_R = 1.496          # radius of the hole opening, sketch units (board svg r=1.197 local)
WIRE_H = 1.0            # half width of a jumper, sketch units (22.2222 mil = 2.0 units wide)
OBSCURE_LIMIT = 0.05     # ★ 2026-09-27 收紧 ✓（原 0.30 ✗）：**与 `bb_compare.OBSCURE_LIMIT` 同值** ✓
#   起因 ✗（用户报 "v57 里 Wire90012900 违规没检查出来" ✓）：这里原来也写了一份 `0.30` ✗
#   ⇒ 改一处忘另一处 ✗；而且 30% 太松 ✗ ⇒ 压住 17.7% 的孔（中心距 0.51mm ✓ 已切进孔口 ✗）逃掉了 ✗。
#   ⚠ 待办 ✓：将来合并成"只引用 bb_compare 那一份" ✓（现在先保证同值 ✓，别的先不改 ✗）。
NEAR_DIST = 6.0         # crowding: neighbours closer than this (sketch units) count as crowded
# ★ 导线颜色：**只能用 Fritzing 官方配色表里的值** ✓（2026-09-26 定位到根 ✓）
#   来源（权威 ✓）：`F:\build-fritzing\fritzing-app\resources\ratsnestcolors.xml`
#                    的 `<view name="breadboardView">` 下每个 `<color … wire="…">` ✓
#   ⇒ 认不出的 hex ⇒ 指示栏的「颜色」下拉回退到**第一项（蓝）** ✗ ——
#     这就是用户截图里"黑线显示蓝"的原因 ✓（`#000000` 不在表里 ✗，官方 black 是 `#404040` ✓）。
COLOR = {"GND": "#404040", "5V": "#cc1414", "DATA_IN": "#418dd9", "DATA_OUT": "#33ffc5",
         "LED_DIN": "#25cc35", "RC": "#ef6100", "BR+": "#ab58a2",
         "COIL_A": "#8c3b00", "COIL_B": "#fa50e6"}
NETS_PATH = r"f:\git\AuroraTessellation-NFC\hardware\pixel\gen_schematic_wires.py"


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def hole_xy(hid):
    m = re.fullmatch(r"pin(\d+)([A-Z])", hid or "")
    if not m or m.group(2) not in ROW_Y:
        return None
    return (int(m.group(1)) * COL_PITCH, ROW_Y[m.group(2)])


def load_nets():
    """net -> [(ref, pin)] from the project's generator (single source of truth)."""
    src = open(NETS_PATH, encoding="utf-8").read()
    blk = src[src.index("NETS = {"):src.index("\n}\n", src.index("NETS = {")) + 2]
    return eval(blk.split("=", 1)[1].strip())


def main(argv):
    fzz, out = argv[0], argv[1]
    z = zipfile.ZipFile(fzz)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(name))
    host = child(sroot, "instances") or sroot

    board = next(e for e in sroot.iter("instance")
                 if "breadboard" in (e.get("moduleIdRef") or "").lower()
                 and not (e.get("moduleIdRef") or "").startswith("Wire"))
    bmi = board.get("modelIndex")
    bfzp = (board.get("path") or "").replace("/", os.sep)
    broot = ET.parse(bfzp).getroot()
    hole_ids = {c.get("id") for c in broot.iter("connector") if re.fullmatch(r"pin\w+", c.get("id") or "")}
    if len(hole_ids) < 800:
        raise SystemExit("hole ids from board fzp: %d (need 800+)" % len(hole_ids))
    hole = {}
    for h in sorted(hole_ids):
        xy = hole_xy(h)
        if xy:
            hole[h] = xy
    print("holes: %d (board fzp declares %d)" % (len(hole), len(hole_ids)))

    # buses: collect every id/connectorId/member under <bus>, then sanity-check the histogram
    buses = []
    for b in broot.iter("bus"):
        mem, seen = [], set()
        for d in b.iter():
            if d is b:
                continue
            for k, v in d.attrib.items():
                if k in ("id", "connectorId", "connector", "member") and v and v not in seen:
                    seen.add(v)
                    mem.append(v)
        if mem:
            buses.append(mem)
    sizes = collections.Counter(len(b) for b in buses)
    print("buses: %d -> %s (expect 4x50 + 126x5)" % (len(buses), dict(sizes)))
    if len(buses) != 130:
        raise SystemExit("bus count is not 130")

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

    for mem in buses:
        for m in mem[1:]:
            uni(mem[0], m)
    bus_of = {}
    for c in hole:
        bus_of.setdefault(find(c), set()).add(c)
    hole_bus = {c: find(c) for c in hole}

    # ★★ 输入可能是**已经布过线**的文件（2026-09-27 实测 ✗）：那就先把旧导线**全部清掉** ✓
    #   —— 只留一根当模板 ✓（写盘要用 ✓）。
    #   反例教训（2026-09-27 ✓，拿 v43 当输入时踩到）：
    #     ① EPAD 那段有个“已经有线就跳过 ✓”的**幂等**检查 ✗ —— 旧导线那一刻**还在文件里**
    #        （要到写盘才删 ✗）⇒ 检查以为“已经有线了” ✗ ⇒ **静默跳过** ✗ ⇒ EPAD 悬空 ✗
    #        （`audit_layout.py` ⑥ 报 GND 裂成两半 ✗，而 `check_netlist.py` 却说 ✓
    #         —— **两套工具打架，独立审计赢了** ✓；这就是“不许自证”的价值 ✓）。
    #     ② 旧导线会在元件脚上留下 `<connect connectorId="WireNNNNN">` 记录 ✗ ⇒ 被当成
    #        “这个脚插进了名叫 WireNNNNN 的孔” ✗ ⇒ 污染 occupied / plug_of ✗。
    WIRE_TMPL = None
    for e2 in list(sroot.iter("instance")):
        if not (e2.get("moduleIdRef") or "").startswith("Wire"):
            continue
        if child(child(e2, "views"), "breadboardView") is None:
            continue
        if WIRE_TMPL is None:
            WIRE_TMPL = ET.fromstring(ET.tostring(e2))
        host.remove(e2)
    inst_ids = {e2.get("modelIndex") for e2 in sroot.iter("instance")}
    if WIRE_TMPL is not None:
        print("清掉输入里的旧导线 ✓（保留 1 根当模板 ✓）")

    # parts: plugged holes + footprint boxes
    occupied, plug_of, name2cid, boxes = set(), {}, {}, []
    plugged_conn = set()          # (元件 modelIndex, 脚 id) —— **已插进孔的脚** ✓
    for e in sroot.iter("instance"):
        mid = e.get("moduleIdRef") or ""
        if mid.startswith("Wire") or e is board:
            continue
        ttl = (e.findtext("title") or "").strip()
        emi = e.get("modelIndex")
        sub = child(child(e, "views"), "breadboardView")
        if sub is None:
            continue
        fpz = (e.get("path") or "").replace("/", os.sep)
        if os.path.isfile(fpz):
            root2 = ET.parse(fpz).getroot()
            name2cid[ttl] = {c.get("name"): c.get("id") for c in root2.iter("connector")
                             if c.get("name")}
            lay = root2.find(".//breadboardView/layers")
            if lay is not None and lay.get("image"):
                base = os.path.dirname(os.path.dirname(fpz))
                for s2 in ("", "core", "contrib", "user"):
                    cand = os.path.normpath(os.path.join(base, "svg", s2,
                                                         lay.get("image").replace("/", os.sep)))
                    if os.path.isfile(cand):
                        g = child(sub, "geometry")
                        bd = pbox.body_box(cand)
                        if bd is not None and g is not None and g.get("x") is not None:
                            mm = pbox.tf_of(g)
                            box = pbox.place((pm.num(g.get("x")), pm.num(g.get("y"))), mm, bd)
                            boxes.append((ttl, box))
                        break
        for cs in sub.iter():
            if tag(cs) != "connect":
                continue
            if (cs.get("layer") or "") != "breadboardbreadboard":
                continue
            occ = cs.get("connectorId")
            if (occ or "").startswith("Wire"):
                continue          # ★ 旧导线留下的记录 ✗ 不是“插进孔” ✓（2026-09-27 ✓）
            occupied.add(occ)
            par2 = {c: p for p in sub.iter() for c in p}
            n = cs
            while n is not None and tag(n) != "connector":
                n = par2.get(n)
            cid_ = n.get("connectorId") if n is not None else "?"
            plug_of[occ] = (ttl, cid_)
            plugged_conn.add((emi, cid_))
    print("pins plugged: %d holes; part boxes: %d" % (len(occupied), len(boxes)))
    # ✗ 试过与 `bb_compare.part_boxes()` 取**并集** ✗ —— 结果盒子偏大（LED2 高 28.5mm ✗）
    #   根因：那个新实现对 SVG `path/@d` 的解析只是“把数字当点” ✗（带相对指令/曲线就错 ✗），
    #   而这里用的 `pbox.body_box()` 是**已验证**过的 ✓ ⇒ 先以它为准 ✓（不混用 ✗）
    for ttl, b in sorted(boxes):
        print("   box %-5s x %7.1f..%7.1f  y %7.1f..%7.1f  (%.1f×%.1f mm)"
              % (ttl, b[0], b[2], b[1], b[3], (b[2] - b[0]) * 25.4 / 90, (b[3] - b[1]) * 25.4 / 90))

    MM = 3.5433
    MMU = 25.4 / 90.0            # 1 sketch 单位 = 1/90 in ✓（提前定义：polish 里要用 ✓）
    blocked, block_src = set(), {}
    for ttl, (bx0, by0, bx1, by1) in boxes:
        for hc, (hx, hy) in hole.items():
            if bx0 - 1 <= hx <= bx1 + 1 and by0 - 1 <= hy <= by1 + 1:
                blocked.add(hc)
                block_src.setdefault(hc, ttl)
    blocked -= occupied
    print("holes under part bodies: %d" % len(blocked))

    # net -> plugged holes
    # ★ 可复现（2026-09-26 ✓）：set 的迭代顺序在 Python 每个进程里都不一样 ✗（字符串哈希随机化 ✓）
    #   ⇒ 同样输入会给出不同选路（实测：两次跑出来的交叉数 3 与 5 不同 ✗）⇒ 一律排序后再遍历 ✓
    hole_at = {v: k for k, v in hole.items()}      # 坐标 → 孔 id ✓（给候选端点用 ✓）

    def sorted_holes(s):
        return sorted(s, key=lambda c: hole[c][0])

    nets = load_nets()
    net_holes = {}
    for net, pins in nets.items():
        hs = set()
        for ref, pname in pins:
            cid = ("connector" + str(int(pname[1:]) - 1)) if pname.startswith("#") \
                else name2cid.get(ref, {}).get(pname)
            for h, owner in plug_of.items():
                if cid and owner == (ref, cid):
                    hs.add(h)
        net_holes[net] = hs

    # ★★ 地网要把**对侧那条电源轨**也算成自己的资源 ✓（2026-09-26 实测 ✓）
    #   证据（实测 ✗）：地网的锚点只有一条轨（EPAD 接上去的那条 ✓，本工程是 **Z** 上轨 ✓），
    #   而**骑中缝的模块**（如 D3：板盖住 G 行..D 行 ✓）**下半区的脚**只能从下方出线 ✗
    #   ⇒ 它被迫翻过自己的板子去够上面那条轨 ✗ ⇒ 实测绕出 **147mm** ✗，最后还是连不上 ✗
    #     （`net GND: 连不上（拆线重排 3 次也不行）`，`pin3E` 孤立 ✓）。
    #   ⇒ 把**下轨 X** 的一个空孔也加进地网 ✓：上半区的脚往上接 ✓、下半区的脚往下接 ✓，
    #     而**两条轨之间的干线由布线器自己拉** ✓（它会把同一个网的所有 bus 连成一棵最小树 ✓）
    #     —— 不写死列 ✓、由代价（长度 + K×交集 ✓）自己挑最省的那一列 ✓。
    #   ★ 只加**同网**的对侧轨 ✓：GND ↔ (Z, X)、5V ↔ (Y, W) ✓（绝不可交叉 ✗ 那是短路 ✗）。
    RAIL_PAIR = {"GND": ("Z", "X"), "5V": ("Y", "W")}
    if os.environ.get("PP_NORAIL"):
        RAIL_PAIR = {}                 # ★ 试验开关 ✓：不加对侧轨（看干线是不是反而亏 ✓）
    # ★★ 新规则（2026-09-27 ✓，依据＝用户手改版 pixel-breadboard43_byHand 实测 ✓）：
    #   **对侧轨是「可选资源」，逐网算账** ✓ —— 不许硬塞进网里 ✗。
    #   证据（实测 ✗）：用户手改版 5V **一步都不下 W 轨** ✓（全走 Y 轨 + 就近成链 ✓，40.0mm ✓），
    #   而我旧版把 Y、W 两条轨都塞进 5V ⇒ 树**必须**连上 W 轨 ⇒ 强制拉一根 45.7mm 的 W↔Y
    #   干线 ✗（5V 94.0mm ✗）；GND 同理 112.2mm vs 用户 55.7mm ✗ —— 两网共长 123.4mm ✗
    #   （正好等于 480.8 − 357.4 ✓）。
    #   ⇒ 主循环里逐网把「带 / 不带对侧轨」都试一遍 ✓，按 **长度 + K×交集** 挑省的那个 ✓。
    HUB_BUS = {}                       # net -> {该网可选的电源轨 bus} ✓（★ 只是可选 ✓）
    HUB_HOLES = {}                     # net -> {该网可选的对侧轨孔} ✓（算账后要能收回去 ✓）
    for net_, rrows in sorted(RAIL_PAIR.items()):
        if net_ not in net_holes:
            continue
        have = {h[-1] for h in net_holes[net_] if h[-1] in ("Z", "Y", "X", "W")}
        for rr in rrows:
            if rr in have:
                continue
            # ★★ 2026-09-27 修 ✓（闸门抓出来的洞 ✗）：这条轨上若**已经插着别的网的脚** ✗，
            #   就**不许**把它当本网的枢纽 ✗ —— 否则同一条轨会同时属于两个网 ✗ = 实物短路 ✗。
            #   实测 ✗：新摆位让 `C2` 跨在 Y、Z 两条轨上（**5V 在 Z ✓、GND 在 Y ✓**，
            #   这本身是**正确接法** ✓ ✓），而我按 `RAIL_PAIR` 的**约定**把 Y 轨当成
            #   5V 的备用轨 ✗ ⇒ 闸门报 `[SHORT] bus Y carries 5V, GND` ✗。
            #   ★ 轨本身**没有极性** ✗（谁说 GND 就该在 Z ✗）—— 一切以**板上实际插着的脚**
            #     为准 ✓（这正是用户 §5b 第 5 条"物理连接才算数"的口径 ✓）。
            other = sorted({n2 for n2, hs2 in net_holes.items() if n2 != net_
                            for h in hs2 if h[-1] == rr})
            if other:
                print("   [!] %s 行已插着别的网的脚（%s）⇒ 不当 %s 的枢纽 ✓（否则同轨两网＝短路 ✗）"
                      % (rr, "/".join(other), net_))
                continue
            free_rail = [h for h in hole
                         if h[-1] == rr and h not in occupied and h not in blocked]
            if not free_rail:
                continue
            h0 = min(free_rail, key=lambda c: hole[c][0])
            net_holes[net_].add(h0)
            HUB_BUS.setdefault(net_, set()).add(find(h0))
            HUB_HOLES.setdefault(net_, set()).add(h0)
            print("   电源轨：把 %s行（%s）的 %s 也算进网 %s ✓（★ 可选 ✓：逐网算账决定用不用 ✓）"
                  % (rr, "上轨" if rr in ("Z", "Y") else "下轨", h0, net_))

    print("net -> holes: %s" % ", ".join("%s=%d" % (n, len(h)) for n, h in sorted(net_holes.items())))

    # HARD GATE: one bus carrying two different nets = real short on the board
    bus_net = {}
    for net, hs in sorted(net_holes.items()):
        for h in sorted_holes(hs):
            bus_net.setdefault(find(h), set()).add(net)
    shorts = {b: ns for b, ns in bus_net.items() if len(ns) > 1}
    if shorts:
        for b, ns in sorted(shorts.items()):
            pins = ", ".join("%s=%s" % (h, "/".join(plug_of[h])) for h in sorted(bus_of[b])
                             if h in plug_of)
            print("[SHORT] bus %s carries %s (%s)" % ("/".join(sorted(b)[:3]),
                                                      ", ".join(sorted(ns)), pins))
        raise SystemExit("layout short: %d bus(es) join two nets -> fix the layout, "
                         "NO file written" % len(shorts))

    used, wire_ends, jumpers, spare = set(), set(), [], []
    used_holes = set(occupied)
    fixed_segs = []            # 额外线（EPAD ✓）的段：当障碍看 ✓（在 checks 前填 ✓）
    extra = []                 # 额外线：[(net, pts, end0, end1, kind)] ✓（EPAD 接地 ✓）
    extra_owner = []           # 额外线所属元件名 ✓（自检时允许它穿过**自己**那块板 ✓）

    def _refix():
        """按当前 jumpers/extra 重算 used / used_holes / wire_ends ✓
        （提前定义 ✓：拆线重排（rip-up）在布线过程中也要用它 ✓）
        """
        u = set()
        for _n, _p, a, b, _k in jumpers:
            u.add(a)
            u.add(b)
        for _n, _p, e0, e1, _k in extra:
            for e0e in (e0, e1):
                if e0e[0] == "hole":
                    u.add(e0e[1])
        used.clear()
        used.update(u)
        wire_ends.clear()
        wire_ends.update(u)
        used_holes.clear()
        used_holes.update(occupied)
        used_holes.update(u)

    def free_bus(b):
        return sorted(bus_of[b] - occupied - blocked - used, key=lambda c: hole[c][0])

    def free_in(h):
        return free_bus(hole_bus[h])

    def dist_h(h1, h2):
        return ((hole[h1][0] - hole[h2][0]) ** 2 + (hole[h1][1] - hole[h2][1]) ** 2) ** 0.5

    def dist_h_pt(p, q):
        return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5

    def seg_hits(p, q, r):
        x0, y0, x1, y1 = r
        dx, dy = q[0] - p[0], q[1] - p[1]
        t0, t1 = 0.0, 1.0
        for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
            if abs(pp) < 1e-9:
                if qq < 0:
                    return False
                continue
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
        return t1 - t0 > 1e-6

    def seg_intersect(p1, q1, p2, q2):
        def o(a, b, c):
            v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
        return o(p2, q2, p1) * o(p2, q2, q1) < 0 and o(p1, q1, p2) * o(p1, q1, q2) < 0

    def seg_overlap(p1, q1, p2, q2):
        d1 = (q1[0] - p1[0], q1[1] - p1[1])
        d2 = (q2[0] - p2[0], q2[1] - p2[1])
        if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 1e-9:
            return False
        if abs(d1[0]) < 1e-9 and abs(d1[1]) < 1e-9:
            return False
        for t in (p2, q2):
            if abs((t[0] - p1[0]) * d1[1] - (t[1] - p1[1]) * d1[0]) > 1e-6:
                return False
        ax = 0 if abs(d1[0]) > abs(d1[1]) else 1
        a0, a1 = sorted((p1[ax], q1[ax]))
        b0, b1 = sorted((p2[ax], q2[ax]))
        return min(a1, b1) - max(a0, b0) > 1e-6

    def on_seg(p, a, b):
        if abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) > 1e-6:
            return False
        return (min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
                and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9)

    def point_seg_dist(p, a, b):
        """distance from point p to segment a-b"""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-12:
            return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5

    def _cap(t):
        """✗ 自己抄的一份已废弃 ✗（平方根项符号写反 ✗ ⇒ 覆盖率只算真值的 1/5 ✗）
        ⇒ 现在统一调 `BC.obscures` ✓（一份实现 ✓）
        """
        r = HOLE_R
        if t <= -r:
            return 0.0
        if t >= r:
            return math.pi * r * r
        return math.pi * r * r - (r * r * math.acos(t / r) - t * (r * r - t * t) ** 0.5)

    def obscures(p, q, hpt):
        """导线带（沿 p-q ✓）盖住 hpt 处孔开口的面积比 ✓ —— **一份实现** ✓

        ★ 2026-09-26 修：以前这里自己抄了一份 `_cap` ✗，而它的平方根项符号写反 ✗
        ⇒ 覆盖率只算真值的 ~1/5 ✗（实测：线正好穿过孔心时真值 ≈85%、旧公式报 15% ✗）
        ⇒ “不许把接线了的孔盖住 >30%” 这条硬规则一直形同虚设 ✗。
        """
        return BC.obscures(p, q, hpt)

    def covered_by_wires(hs):
        """这些孔（准备被新线占用 ✓）是不是已经被**现有引线**盖住了 ✗

        （规矩：一个接线了的孔不许被引线盖住 >30% ✓ —— 布线/重排**谁先谁后**
         都可能造成这种情况 ✗（重排时孔集会变 ✓）⇒ 每次选孔/选路都查一遍 ✓）
        注：线**终止**在这个孔上不算盖住 ✓（那是它自己插在这里 ✓）
        """
        cur = wire_segs()
        for h in hs:
            hp = hole[h]
            for a, b in cur:
                if BC.same_pt(a, hp) or BC.same_pt(b, hp):
                    continue
                if obscures(a, b, hp) >= OBSCURE_LIMIT:
                    return True
        return False

    def crowding(pts):
        """how crowded this route would be (平均每条段附近有几根已有的线靠近 ✗)"""
        """how crowded this route would be (平均每条段附近有几根已有的线靠近 ✗)

        user rule 2026-09-26: 引线要尽量分散均匀，别都挤在一处
        """
        cur = wire_segs()
        if not cur:
            return 0.0
        tot = 0
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        for a, b in segs:
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            for c, d in cur:
                if point_seg_dist(mid, c, d) < NEAR_DIST or point_seg_dist(c, a, b) < NEAR_DIST:
                    tot += 1
        return tot / float(len(segs))

    def wire_segs():
        # ★ 含**额外线**（EPAD 接地 ✓）：它也是障碍 ✓（以前漏在外面 ✗ ⇒ 重排时看不见它 ✗）
        return [(j[1][i], j[1][i + 1]) for j in jumpers for i in range(len(j[1]) - 1)] + fixed_segs

    def _segs(pts):
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    def _plen(pts):
        return sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
                   for i in range(len(pts) - 1))

    def simplify(pts):
        """★ 去冗余点（2026-09-26 用户看到"中间有一个点" ✗）：
        去掉重复点 ✓、去掉**同向共线**的中间点 ✓（三点一线就并成一段 ✓）。
        ⇒ 写出来的导线就不会无故多出一个"连接节点" ✗（Fritzing 里那是一个可见的点 ✗）。
        """
        out = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - out[-1][0]) < 1e-9 and abs(p[1] - out[-1][1]) < 1e-9:
                continue
            out.append(p)
        i = 1
        while i < len(out) - 1:
            a, b, c = out[i - 1], out[i], out[i + 1]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9:
                del out[i]                      # 三点一线 ⇒ 中间那个点没意义 ✓
            else:
                i += 1
        return out

    def bends(pts):
        """折弯数（方向改变次数 ✓）—— 用户：能直着接就别折一下 ✓"""
        sp = simplify(pts)
        n = 0
        for i in range(1, len(sp) - 1):
            d1 = (sp[i][0] - sp[i - 1][0], sp[i][1] - sp[i - 1][1])
            d2 = (sp[i + 1][0] - sp[i][0], sp[i + 1][1] - sp[i][1])
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) > 1e-9:
                n += 1
        return n

    def _cross(pts, others, own=None):
        """★ 交集数（2026-09-26 改 ✓）：**X 形交叉 + T 形搭线 + 从元件底下穿过** ——
        这三类用户都算“相交” ✓（以前只数 X ✗ ⇒ 目标函数和用户看的东西不一致 ✗）
        判碰类型用 `BC.pair_kind` ✓（**度量与优化器同一份实现** ✓，不再各写一套 ✗）
        """
        n = 0
        for p, q in _segs(pts):
            for p2, q2 in others:
                if BC.pair_kind(p, q, p2, q2):
                    n += 1
            for w, r in boxes:
                if w != own and seg_hits(p, q, r):
                    n += 1
        return n

    def clearance(pts):
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        cross = over_pin = over_end = ovl = self_bad = end_on = 0
        hide = 0
        hide_max = 0.0
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i]
                c, d = segs[j]
                if seg_overlap(a, b, c, d) or seg_intersect(a, b, c, d):
                    self_bad += 1
        cur = wire_segs()
        for a, b in segs:
            for c, d in cur:
                if seg_overlap(a, b, c, d):
                    ovl += 1
                elif seg_intersect(a, b, c, d):
                    cross += 1
            for h in sorted_holes(used_holes):
                if h in (pts[0], pts[-1]):
                    continue
                f = obscures(a, b, hole[h])
                if f >= OBSCURE_LIMIT:
                    hide += 1                       # hides a connected hole -> forbidden
                if f > hide_max:
                    hide_max = f
                if f > 0.0:
                    if h in wire_ends:
                        over_end += 1
                    else:
                        over_pin += 1
        for h in (pts[0], pts[-1]):
            for c, d in cur:
                if on_seg(h, c, d):
                    end_on += 1
        # ★ T 形搭线（一方端点搭在对方段内 ✓）也算“交集”✗ —— 用户判据 ✓
        t_touch = 0
        for a, b in segs:
            for c, d in cur:
                if BC.pair_kind(a, b, c, d) == "touch":
                    t_touch += 1
        return cross, over_pin, over_end, ovl, self_bad, end_on, hide, hide_max, t_touch

    def shape_factor(pts):
        """★ 2026-09-26 修正（用户美学原则 ✓）：**斜线不如正交折线好看** ✓ ——
        实测两处"不美"的线（`21H→25D` 黑斜线、`48E→54Y` 红斜线）**都是斜线** ✗，
        而用户点名"美"的线全是**水平 / 垂直或折线** ✓（例：`22H→38H` 水平 ✓）。
        ⇒ 斜线罚得足够重，让"绕一下的正交折线"胜过"直斜线" ✓
          （45° 时正交长度是斜线的 1.41 倍 ⇒ 罚系数要 >1.41 ⇒ 取 **1.5** ✓）。
        折线本身**没有加分** ✓（第 9 条：不许为了折线而绕远路 ✓）。
        """
        if len(pts) > 2:
            return 1.0
        dx, dy = abs(pts[0][0] - pts[1][0]), abs(pts[0][1] - pts[1][1])
        if dx < 1e-9 or dy < 1e-9:
            return 1.0
        return 1.5

    # ★★ 汇率 K：**1 个「交集」= 允许绕多少 mm** ✓
    #    —— 这是个**人为选定、可调的系数** ✓（2026-09-26 用户定 10mm；≈ 4 个孔 ✓）。
    #    含义：代价 = 长度 + K × 交集 ⇒ 为了少 1 个交叉，最多值得多绕 K 毫米 ✓；
    #    超过就不值得 ✗ —— 否则会为了省 1 个交叉绕出 4 倍长度 ✗（实测：EPAD 被绕到 94mm ✗）。
    #    要调只改这一行 ✓（调大＝更看重少交叉 ✓；调小＝更看重短与直 ✓）。
    K_MM = 10.0
    K = K_MM * MMU
    print("汇率 K = %.0f mm / 个交集（人为可调 ✓）" % K_MM)
    # ★ 「就近串链」的门槛 ✓（2026-09-27 ✓）：串链要**比下轨省过这么多**才用 ✓。
    #   同 K_MM 一样，是**人为选定、可调的系数** ✓（要调只改这一行 ✓）：
    #   调大＝更守规则 ⑩（电源/地多走轨与板边 ✓）；调小＝更贪短 ✗（0 = 谁便宜用谁
    #   ⇒ 会退回当年那条 147mm 长蛇 ✗）。
    CHAIN_MARGIN = float(os.environ.get("PP_CHAIN_MARGIN", 2.0)) * COL_PITCH
    print("串链（PP_CHAIN=1 才开 ✓）门槛 = %.2f mm（比下轨省过它才就近串链 ✓）"
          % (CHAIN_MARGIN * MMU))

    # ★★ 规则 a（2026-09-26 用户定 ✓）：先布的**电源/地**走**电源轨与板边** ✓，
    #   **中间走廊留给信号线** ✓ —— “留路不只是给元件、也是给后面的线” ✓。
    #   起因（实测 ✗）：先布的 GND 把 `BR+` 唯一的那条中间走廊（row H，y=63 ✓）占掉 ✗
    #   ⇒ 后布的线无路可走 ✗（`net BR+: 连不上` ✓）。
    #   做法：组 0/1（GND/5V ✓）的代价里，把“走中间”的那段长度加权 ✓；信号线不受此限 ✓。
    CUR_RANK = [2]
    EDGE_L = min(b[0] for _t, b in boxes) - 18.0
    EDGE_R = max(b[2] for _t, b in boxes) + 18.0
    RAIL_Y = (9.0, 18.0, 171.0, 180.0)

    def mid_len(pts):
        """走“中间走廊”的那部分长度（既不在电源轨附近、也不在板边 ✓）—— 单位：sketch 单位 ✓"""
        mid = 0.0
        for a, b in _segs(pts):
            seg_len = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            near_rail = min(abs(my - yy) for yy in RAIL_Y) <= 18.0
            near_edge = mx < EDGE_L or mx > EDGE_R
            if not near_rail and not near_edge:
                mid += seg_len
        return mid

    # ★ 规则 a 的力度（**人为可调** ✓）：走中间的成本 = 正常的 1 + MID_PEN 倍 ✓
    #   —— 乘法软罚太弱 ✗：实测 0.8 倍加成下，GND 仍然沿 row H 横穿 40 单位 ✗，
    #     把 BR+ 唯一的那条中间走廊吃掉 ✗ ⇒ 改成“每单位中间长度加 MID_PEN 单位代价” ✓。
    MID_PEN = 3.0

    LAST = [None, None]      # [判废原因, 挡路的线段] ✓（诊断 + 拆线重排都用 ✓）
    BLOCKS = set()           # 本轮“挡过路”的线段集合 ✓（拆线重排用 ✓）

    def route_cost(pts, allow_overlap=False, own=None):
        """★ 2026-09-26 重写 ✓：**硬约束直接判废 ✗；代价只算“长度 + 拥挤 + K×交集”** ✓

        非法（返回 None ✗）：
          ① 路径自交 / 自叠 ✗
          ② 穿过**别的**元件本体 ✗（自己的元件豁免 ✓）
          ③ 与现有引线**重叠**（共线叠在一起 ✗）
          ④ 盖住“已接线的孔” > 30% ✗（自己的两个端点孔除外 ✓）
          ⑤ 自己要占的孔已被现有引线盖住 ✗
        合法 ⇒ 代价 = 形状加权长度 ×(1 + 0.3×拥挤 ✓) + K ×（与现有引线的交集数 ✓）
        （以前这些约束是乘法惩罚项 ✗ ⇒ 互相掩盖、一处算错就全废 ✗）
        """
        pts = simplify(pts)        # ★ 先去掉重复点/同向共线的中间点 ✓
        #   （2026-09-26 修 ✗：不简化就判"自交"，会把大量**合法**模板误杀 ✗ ——
        #     实测 63 个候选里 37 个被误判 ✗ ⇒ 这类"几何预处理漏做"正是老毛病 ✓）
        segs = _segs(pts)
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i]
                c, d = segs[j]
                if BC.seg_overlap(a, b, c, d) or BC.seg_intersect(a, b, c, d):
                    LAST[0] = "① 路径自交/自叠"
                    return None                                   # ① 自交/自叠
        for a, b in segs:
            for w, r in boxes:
                if w != own and seg_hits(a, b, r):
                    LAST[0] = "② 穿过元件 %s 的本体框" % w
                    return None                                   # ② 穿别的元件
        cur = wire_segs()
        cross = 0
        cov_res = set()          # ★ 本候选压到的“后面还要用”的孔 ✓（规则 ⑩）
        for a, b in segs:
            for c, d in cur:
                if BC.seg_overlap(a, b, c, d):
                    LAST[0] = ("③ 与线段 (%.0f,%.0f)->(%.0f,%.0f) 重叠"
                               % (c[0], c[1], d[0], d[1]))
                    LAST[1] = (c, d)
                    return None                                   # ③ 与现有线重叠
                if BC.pair_kind(a, b, c, d):
                    cross += 1                                    # 交集（计入代价 ✓）
            for h in sorted_holes(used_holes):
                hp = hole[h]
                if BC.same_pt(hp, pts[0]) or BC.same_pt(hp, pts[-1]):
                    continue                                      # 自己的端点孔不算盖住 ✓
                if obscures(a, b, hp) >= OBSCURE_LIMIT:
                    LAST[0] = "④ 盖住了已接线的孔 %s" % h
                    return None                                   # ④ 盖住接线孔
            # ★★ 规则 ⑩「留路」✓（2026-09-26 ✓）：**先把“压到哪些预留孔”记下来** ✓
            #   ★ 判据要**按 bus** 收紧 ✗（第一版按孔判 ✗ ⇒ 把 J 行整条走廊全禁了 ✗，
            #     实测 `DATA_OUT` 就是这样被卡死的 ✗）：一条 bus 里 5 个孔 ✓，
            #     只要**还能剩一个可用孔** ✓，将来那个网就仍能用它 ✓。
            for hid2, htx, hty in RESERVED_XY:
                if htx < min(a[0], b[0]) - 4 or htx > max(a[0], b[0]) + 4 \
                        or hty < min(a[1], b[1]) - 4 or hty > max(a[1], b[1]) + 4:
                    continue                                      # 快筛：离这段远就不管 ✓
                if obscures(a, b, (htx, hty)) >= OBSCURE_LIMIT:
                    cov_res.add(hid2)
        if cov_res:
            # 按 bus 结算：每条被压的 bus，压完之后是否还剩**至少一个可用孔** ✓
            hit_bus = {}
            for h3 in cov_res:
                hit_bus.setdefault(hole_bus[h3], set()).add(h3)
            for b2, cov in sorted(hit_bus.items(), key=lambda kv: sorted(kv[1])[0]):
                remain = [h4 for h4 in bus_of[b2]
                          if h4 not in used_holes and h4 not in cov
                          and not covered_by_wires((h4,))
                          and not any(obscures(s1, s2, hole[h4]) >= OBSCURE_LIMIT
                                      for s1, s2 in segs)]
                if not remain:
                    LAST[0] = ("⑥ 把后面要用的 bus（%s 一带）压到没孔可用（规则⑩ 留路 ✓）"
                               % "/".join(sorted(cov)[:2]))
                    return None
        ends = [hole_at[p] for p in (pts[0], pts[-1]) if p in hole_at]
        if ends and covered_by_wires(ends):
            LAST[0] = "⑤ 要占的孔 %s 已被现有引线盖住" % ",".join(ends)
            return None                                           # ⑤ 新占的孔已被盖住
        ln = _plen(pts) * shape_factor(pts)
        c = ln * (1.0 + 0.30 * crowding(pts)) + K * cross
        if CUR_RANK[0] <= 1:
            c += MID_PEN * mid_len(pts)   # ★ 规则 a ✓：电源/地走中间 = 重罚 ✓
        return c

    def routes(h1, h2):
        return routes_pt(hole[h1], hole[h2])

    def routes_pt(p, q):
        """候选走法（**两条 / 两条元 / 带偏移的折线** ✓）：偏移取所有 9 的整数倍 ✓
        （±9…±180 ✓）—— 以前只列 ±9/18/27/36/54/72/90 ✗ ⇒ 实测正需要 `o=45` 的那种
        “右 → 下 → 左”才能绕开插了脚的孔 ✗，结果只能退回**斜线** ✗（用户看着不美 ✗）
        """
        out = [[p, q], [p, (p[0], q[1]), q], [p, (q[0], p[1]), q]]
        for k in range(1, 21):
            for o in (9.0 * k, -9.0 * k):
                out.append([p, (p[0], q[1] + o), (q[0], q[1] + o), q])
                out.append([p, (p[0] + o, p[1]), (p[0] + o, q[1]), q])
        # ★★ 三折（绕“墙” ✓，2026-09-26 实测补 ✓）：实测 `COIL_A` 失败时，
        #   **两折模板里没有**它需要的那种形状 ✗ —— L1 的脚只能从 **F 行**出 ✓、
        #   D3 的脚只能从 **J 行**出 ✓，而 F 行上横着**别人要用的孔**（`pin8F` ✗）
        #   ⇒ 必须“先离开这一行 ✓ → 横穿两个元件框之间的**空当** ✓ → 再上来 ✓”。
        #   空当候选 = 每个元件框**外侧 ±13.5 单位**（=1.5 孔距 ✓）对齐到 9 的整数倍 ✓；
        #   只留**离直线最近**的 40 组 ✓（否则候选爆炸、跑不动 ✗）。
        gx, gy = set(), set()
        for _t, (bx0, by0, bx1, by1) in boxes:
            for xx in (bx0 - 13.5, bx1 + 13.5):
                gx.add(math.ceil(xx / 9.0) * 9.0)
                gx.add(math.floor(xx / 9.0) * 9.0)
            for yy in (by0 - 13.5, by1 + 13.5):
                gy.add(math.ceil(yy / 9.0) * 9.0)
                gy.add(math.floor(yy / 9.0) * 9.0)
        gx = sorted(v for v in gx if -9.0 <= v <= 576.0)
        gy = sorted(v for v in gy if -9.0 <= v <= 189.0)
        combos = sorted((abs(x2 - (p[0] + q[0]) / 2.0) + abs(y2 - (p[1] + q[1]) / 2.0), x2, y2)
                        for x2 in gx for y2 in gy)[:40]
        for _d2, x2, y2 in combos:
            out.append([p, (x2, p[1]), (x2, y2), (q[0], y2), q])      # 横 → 竖 → 横 ✓
            out.append([p, (p[0], y2), (x2, y2), (x2, q[1]), q])      # 竖 → 横 → 竖 ✓
        # ★★ 绕某一个框的“U 形”走法（4 个弯 ✓，2026-09-26 实测补 ✓）：
        #   实测 `DATA_OUT` 失败时，需要的是“**从框左边下去、从框右边上来**”✗ ——
        #   J1（x 342..378, y 18..63 ✓）是上半区一堵墙 ✗，而它两侧各有空当
        #   （左 333 ✓ 右 387 ✓）、下方 y=81 也空 ✓ ⇒ 正好是 [p,(333,45),(333,81),(387,81),(387,45),q] ✓。
        #   三折模板表达不了这种 ✗ ⇒ 按**框的两侧**成对给候选 ✓（每个框 4 条 ✓，很便宜 ✓）。
        for _t3, (bx0, by0, bx1, by1) in boxes:
            for xa, xb in ((bx0 - 13.5, bx1 + 13.5), (bx1 + 13.5, bx0 - 13.5)):
                for yy in (by0 - 13.5, by1 + 13.5):
                    sa, sb, sy = round(xa / 9.0) * 9.0, round(xb / 9.0) * 9.0, round(yy / 9.0) * 9.0
                    out.append([p, (sa, p[1]), (sa, sy), (sb, sy), (sb, q[1]), q])
                    out.append([p, (p[0], sy), (sa, sy), (sa, p[1]), (sb, p[1]), q])
        return [r for r in out if all(-9.0 <= x <= 576.0 and -9.0 <= y <= 189.0 for x, y in r)]

    def epad_route(p_pad, buses, own_title):
        """裸露焊盘接地线：在给的一批 bus 里挑“最近的几个空闲孔”×「直 / 折两下」✓，
        按**交叉优先**、再看长度挑 ✓；允许穿过**它自己**那块板 ✓，别的规矩一条不松 ✓
        （交叉惩罚 / 不得盖住接线孔 / 不得重叠 / 不得压别的元件 ✓）。
        """
        seen, cand = set(), []
        for b2 in buses:
            for hcx in free_in(b2):
                if hcx not in seen:
                    seen.add(hcx)
                    cand.append(hcx)
        if not cand:
            return None

        def cost(pts_c):
            for i in range(len(pts_c) - 1):
                for w_, r in boxes:
                    if w_ != own_title and seg_hits(pts_c[i], pts_c[i + 1], r):
                        return None
            (cr, op, oe, ov, sb, eo, hd, _hm, tt) = clearance(pts_c)
            if sb or ov or hd:
                return None
            return (_plen(pts_c) * shape_factor(pts_c) * (1.0 + 0.5 * cr)
                    * (1.0 + 0.6 * op) * (1.0 + 3.0 * (oe + eo)) * (1.0 + 3.0 * tt)
                    * (1.0 + 0.30 * crowding(pts_c)))

        best = None
        for hc2 in sorted(cand, key=lambda c: dist_h_pt(hole[c], p_pad))[:24]:
            q2 = hole[hc2]
            if covered_by_wires((hc2,)):
                continue          # ★ 这个孔已被引线盖住 ✗ ⇒ 换一个 ✓
            for pts_c in routes_pt(p_pad, q2):
                cc = cost(pts_c)
                if cc is None:
                    continue
                key = (cc, _cross(pts_c, wire_segs(), own_title), bends(pts_c),
                       _plen(pts_c) * shape_factor(pts_c))
                if best is None or key < best[0]:
                    best = (key, pts_c, hc2)
        return best

    def best_link(ba, bb, allow_overlap=False):
        ca, cb = free_in(ba), free_in(bb)
        if not ca or not cb:
            return None
        pairs = sorted(((hole[h1][0] - hole[h2][0]) ** 2 + (hole[h1][1] - hole[h2][1]) ** 2,
                        h1, h2) for h1 in ca for h2 in cb)[:40]
        best = None
        why = {}
        for _d, h1, h2 in pairs:
            for pts in routes(h1, h2):
                c = route_cost(pts, allow_overlap)
                if c is None:
                    why[LAST[0]] = why.get(LAST[0], 0) + 1
                    continue
                if covered_by_wires((h1, h2)):
                    why["⑤'(重复) 要占的孔已被盖住"] = why.get("⑤'(重复) 要占的孔已被盖住", 0) + 1
                    continue      # ★ 要占的孔已被别的线盖住 ✗ ⇒ 换一对 ✓（2026-09-26 ✓）
                # ★ 两个阶段（2026-09-26 ✓）：
                #   ① 贪婪布线 = **先少交叉** ✓（用户判据 ✓）—— 否则它为了省长度到处加交叉 ✗
                #      （实测：贪婪用加权后直接掉到 9 个交叉 ✗）
                #   ② 收尾的抽出重排 = **加权代价** ✓（允许用 ≤K mm 的长度换 1 个交叉 ✓）
                k = (_cross(pts, wire_segs()), bends(pts),
                     _plen(pts) * shape_factor(pts), c)
                if best is None or k < best[0]:
                    best = (k, pts, h1, h2)
        if best is None and pairs:
            print("      [诊断] 这对 bus 一个合法走法都没有：%d 个候选 → %s"
                  % (sum(why.values()),
                     "; ".join("%s×%d" % kv for kv in sorted(why.items(), key=lambda kv: -kv[1]))))
            if LAST[1]:
                BLOCKS.add(LAST[1])      # ★ 记下挡路的线段 ✓（拆线重排用 ✓）
        return best

    def wire(net, pts, h1, h2, kind):
        # ★ 端点顺序规范化（2026-09-26 ✓）：同一根线可能从任一端开始生成 ⇒ 换成
        #   "先小后大" 的固定方向，输出才逐字节可复现（否则两次跑出的 fzz 哈希不同 ✗）
        if (pts[0][0], pts[0][1]) > (pts[-1][0], pts[-1][1]):
            pts = list(reversed(pts))
            h1, h2 = h2, h1
        used.update((h1, h2))
        used_holes.update((h1, h2))
        wire_ends.update((h1, h2))
        jumpers.append((net, pts, h1, h2, kind))
        print("   加线: %-9s %-7s %s → %s  %d 段 %.1f mm"
              % (net, kind, h1, h2, len(pts) - 1,
                 _plen(pts) * MMU))
        uni(h1, h2)

    def connect_cluster(net, buses_need):
        n = len(buses_need)
        cap = [len(free_in(b)) for b in buses_need]
        if min(cap) == 0:
            # ★ 诊断（2026-09-26 ✓）：**点名**是哪条 bus、上面插着谁、被哪块板子盖住 ✓
            #   —— 不点名就只能靠猜 ✗（用户规矩：结论要能指出来源 ✓）
            for b in buses_need:
                if free_in(b):
                    continue
                hs = sorted(bus_of[b], key=lambda c: (hole[c][1], hole[c][0]))
                occ = ["%s=%s" % (h, "/".join(plug_of[h])) for h in hs if h in plug_of]
                cov = sorted({block_src.get(h, "?") for h in hs if h in blocked})
                print("   [连不上] net %s：bus（列 %s）没有空孔 ⇒ 需要改布局 ✓"
                      % (net, hole[hs[0]][0] / COL_PITCH))
                print("        整条 bus：%s" % "/".join(hs))
                print("        上面插着：%s" % (", ".join(occ) or "（无）"))
                print("        被本体板盖住：%s（盖住的孔 %s）"
                      % (", ".join(cov) or "（无）",
                         ", ".join(h for h in hs if h in blocked) or "（无）"))
            return False
        par2 = list(range(n))
        deg = [0] * n

        def f2(x):
            while par2[x] != x:
                par2[x] = par2[par2[x]]
                x = par2[x]
            return x

        # ★ 次序（2026-09-26 用户定 ✓）：**从左到右 → 从上到下**依次接线 ✓
        #   位置 = 该 bus（铜片条 ✓）最左/最上的孔 ✓；
        #   按位置排好队后一个一个往下接 ✓（每根线内部仍取代价最小的那条路 ✓，
        #   并在最靠前的 3 对里挑最小代价 ✓ —— 保住“以左/上为先”的次序感 ✓）
        def bus_pos(b):
            hs = sorted(bus_of[b])
            return (min(hole[h][0] for h in hs), min(hole[h][1] for h in hs))

        pos = [bus_pos(b) for b in buses_need]

        # ★★ 电源/地：**先让每条 bus 就近接到电源轨** ✓（星形 ✓，2026-09-26 实测 ✓）
        #   实测动机 ✗：让布线器自由配对时，它把 D3 的 E-bus 直接连到很远的 J2 bus ✗
        #   （**147.3mm** ✓，还横着压住了 D3 自己 bus 的孔 ✗）⇒ 最后 `pin3E` 连不上 ✗。
        #   用户规则（§0b ⑩ / §5b ⑩）：**电源/地走轨与板边** ✓、中间走廊留给信号线 ✓。
        #   ⇒ 电源/地按"星形"布：每条非轨 bus 接到**最近的**一条轨 ✓（短竖线 ✓），
        #     轨与轨之间再由下面的通用循环拉干线 ✓（实测会拉在**板边**上 ✓，如 pin59Z→pin59X ✓）。
        def _is_rail_bus(b):
            hs = bus_of[b]
            return len(hs) >= 20 and all(h[-1] in ("Z", "Y", "X", "W") for h in hs)

        # ★★ 「就近串链 vs 下轨」逐条算账 ✓（2026-09-27 定 ✓，抄用户手改版的手法 ✓）
        #   动机（实测 ✗）：用户手改版 GND 用**同排相邻 bus 的 2.54mm 短链**串起来 ✓
        #   （`pin12C→pin13C` 2.5mm ✓），而我的星形阶段让**每条非轨 bus 都必须下轨** ✗
        #   ⇒ 每条 7.6mm 起 ✗ ⇒ GND 175.6mm vs 用户 119.2mm ✗。
        #   但**不能**改回"谁便宜连谁" ✗ —— 那正是当初 D3 的 E-bus 拉出 147mm 长蛇、
        #   把中间走廊占掉的病根 ✗（规则 ⑩：电源/地走轨与板边 ✓）。
        #   ⇒ 折中 ✓：两条候选都算 ✓，**串链要明显更省**（省过 CHAIN_MARGIN ✓）才用 ✓；
        #     否则仍走轨 ✓。CHAIN_MARGIN 默认 2×列距 ≈ 5.08mm ✓（实测案例差 5.1mm ✓）。
        rails_here = [b for b in buses_need if _is_rail_bus(b)]
        if rails_here and net_rank(net) <= 1:
            idx = {b: i for i, b in enumerate(buses_need)}
            for i in sorted(range(n), key=lambda k: pos[k]):
                b = buses_need[i]
                if b in rails_here or deg[i] >= cap[i]:
                    continue
                best = None
                for rb in sorted(rails_here, key=lambda r3: bus_pos(r3)):
                    j = idx[rb]
                    if deg[j] >= cap[j] or f2(i) == f2(j):
                        continue
                    bp = best_link(b, rb)
                    if bp and (best is None or bp[0] < best[0]):
                        best = (bp[0], i, j, bp[1], bp[2], bp[3])
                # ★ 第二条候选：**同排相邻 bus 的短链** ✓（学用户手改版的手法 ✓）
                #   ⚠ 2026-09-27 实测（第一版"全局串链"✗）：串链确实省长度 ✓（GND 128.5→88.3 ✓、
                #   全图 480.8→387.5 ✓），但它让电源/地**不再贴轨** ⇒ 钻进中间走廊 ✗
                #   ⇒ 后面的信号网被迫交叉/压孔 ✗（交集 3~5 ✗、盖住接线孔 1~3 ✗）
                #   ⇒ **两次都被自检闸门拦住、没写文件** ✓。
                #   ★ 收紧版（本次 ✓）：**只许"同一排 + 跨 ≤3 列（≤7.6mm）"** ✓ ——
                #     正是用户手改版那种 `pin12C→pin13C`（2.5mm ✓）的手法 ✓；
                #     距离一短，就不可能"绕去中间走廊"✗ ⇒ 从结构上避开上次的病根 ✓。
                #   ★ 判据仍用**形状加权长度 + CHAIN_MARGIN** ✓（串链要省过门槛才用 ✓，
                #     否则仍走下轨 ✓ = 规则 ⑩ ✓）。`PP_NOCHAIN=1` 可整体关掉 ✓。
                if not os.environ.get("PP_NOCHAIN"):
                    rows_of = {b2: frozenset(h[-1] for h in bus_of[b2]) for b2 in buses_need}
                    for j in range(n):
                        if j == i or f2(i) == f2(j) or deg[j] >= cap[j]:
                            continue
                        bj = buses_need[j]
                        if bj in rails_here:
                            continue
                        if rows_of[b] != rows_of[bj]:          # ★ 必须**同一排** ✓
                            continue
                        if abs(pos[i][0] - pos[j][0]) > 3.0 * COL_PITCH:   # ★ 跨 ≤3 列 ✓
                            continue
                        bp = best_link(b, bj)
                        if bp and (best is None or bp[0][2] + CHAIN_MARGIN < best[0][2]):
                            best = (bp[0], i, j, bp[1], bp[2], bp[3])
                if best is not None:
                    _s, i2, j2, pts, h1, h2 = best
                    wire(net, pts, h1, h2, "sig")
                    deg[i2] += 1
                    deg[j2] += 1
                    par2[f2(i2)] = f2(j2)

        while True:
            comps = {}
            for i in range(n):
                comps.setdefault(f2(i), []).append(i)
            if len(comps) <= 1:
                break
            cand = []
            for i in range(n):
                for j in range(i + 1, n):
                    if f2(i) == f2(j) or deg[i] >= cap[i] or deg[j] >= cap[j]:
                        continue
                    cand.append((min(pos[i][0], pos[j][0]), min(pos[i][1], pos[j][1]), i, j))
            cand.sort()
            best = None
            for _x, _y, i, j in cand[:3]:          # ★ 最靠前（左/上 ✓）的 3 对里挑最小代价 ✓
                bp = best_link(buses_need[i], buses_need[j])
                if bp and (best is None or bp[0] < best[0]):
                    best = (bp[0], i, j, bp[1], bp[2], bp[3])
            if best is None:
                break
            _s, i, j, pts, h1, h2 = best
            wire(net, pts, h1, h2, "sig")
            deg[i] += 1
            deg[j] += 1
            par2[f2(i)] = f2(j)
        # ★ 2026-09-26 重写 ✓：**删掉所有“退化兜底”** ✗
        #   （以前这里会退化成“重叠直连” ✗ 或借闲置 bus 绕一圈 ✗ ⇒ 图是违规的 ✗，
        #     而自检要到收尾才发现 ✗）⇒ 现在：连不上就**停下并报告原因** ✓，绝不写违规几何 ✗
        left = {}
        for i in range(n):
            left.setdefault(f2(i), []).append(i)
        if len(left) > 1:
            show = " | ".join(sorted(",".join(sorted(set(buses_need[i] for i in g)))
                                     for g in left.values()))
            print("   [连不上] net %s：%d 个不连通块：%s" % (net, len(left), show))
            return False
        return True

    def _wire_has_seg(pts, blk):
        """这根线的某段是不是就是挡路那段 ✓"""
        c, d = blk
        for a, b in _segs(pts):
            if (BC.same_pt(a, c) and BC.same_pt(b, d)) or (BC.same_pt(a, d) and BC.same_pt(b, c)):
                return True
        return False

    order = []
    for net, hs in net_holes.items():
        if len(hs) < 2:
            continue
        need, seen = [], set()
        for h in sorted_holes(hs):
            r = find(h)
            if r not in seen:
                seen.add(r)
                need.append(r)
        if len(need) >= 2:
            xs = [hole[h][0] for h in sorted_holes(hs)]
            ys = [hole[h][1] for h in sorted_holes(hs)]
            order.append((net, need, min(xs), min(ys)))

    # ★ 布线次序（2026-09-26 用户定 ✓）：
    #   ② 先布**电源线和地线** ✓（GND / 5V 优先 ✓）
    #   ③ 再布其它线 ✓ —— 两类内部都按 **从左到右 → 从上到下** ✓（用网内最左/最上的孔定位 ✓）
    def net_rank(net):
        u = net.upper()
        if u == "GND":
            return 0
        if u in ("5V", "VCC", "VDD", "+5V", "VBUS"):
            return 1
        return 2

    # ★★ 规则 ⑩「留路」用的**预留孔集合** ✓（2026-09-26 ✓）：
    #   = “**还没布线的**那些网”所涉 bus 里的全部孔 ✓（当前网自己的 bus 除外 ✓）
    #   每换一个网重建一次 ✓（route_cost 拿 RESERVED_XY 快筛 ✓）
    NET_BUSES = {n2: {find(h) for h in hs2} for n2, hs2 in net_holes.items()}
    CUR_NET = [None]
    DONE_NETS = set()
    RESERVED_XY = []

    def rebuild_reserved():
        RESERVED_XY.clear()
        if CUR_NET[0] is None:
            return
        for n2, bs2 in sorted(NET_BUSES.items()):
            if n2 == CUR_NET[0] or n2 in DONE_NETS:
                continue
            for b2 in bs2:
                for h2 in bus_of.get(b2, ()):
                    RESERVED_XY.append((h2, hole[h2][0], hole[h2][1]))
        if RESERVED_XY:
            print("   留路：为 %d 个还没布线的网预留 %d 个孔 ✓"
                  % (len([n2 for n2 in NET_BUSES
                          if n2 != CUR_NET[0] and n2 not in DONE_NETS]), len(RESERVED_XY)))

    # ★★ 逐网算账用的**本网代价** ✓（2026-09-27 ✓）：
    #   只量**这个网新加的那几根线** ✓ ⇒ 「带/不带对侧轨」两种方案的差别**只在这几根线** ✓
    #   （同一时刻 ✓、同一组已经放好的线 ✓、同一批保留孔 ✓）⇒ 两者可比 ✓。
    #   返回 (交集, 本网长度 + K×交集) ✓ —— 判据与全局目标函数一致 ✓。
    def net_score(k0):
        flat = [s for j in jumpers[k0:] for s in _segs(j[1])]
        old = [s for j in jumpers[:k0] for s in _segs(j[1])] + fixed_segs
        n = 0
        for i2 in range(len(flat)):
            for j2 in range(i2 + 1, len(flat)):
                if BC.pair_kind(flat[i2][0], flat[i2][1], flat[j2][0], flat[j2][1]):
                    n += 1
            for s2 in old:
                if BC.pair_kind(flat[i2][0], flat[i2][1], s2[0], s2[1]):
                    n += 1
        tot = sum(((p2[0] - q2[0]) ** 2 + (p2[1] - q2[1]) ** 2) ** 0.5
                  for p2, q2 in flat) * MMU
        return (n, tot + K_MM * n)

    seq = sorted((net_rank(net), x, y, net, need) for net, need, x, y in order)
    for r, _x, _y, net, need in seq:
        print("   布线次序: %-10s 组%d  最左孔 x=%.0f" % (net, r, _x))
        CUR_RANK[0] = r                 # ★ 规则 a ✓：组 0/1（GND/5V）受“别占中间”约束 ✓
        CUR_NET[0] = net
        rebuild_reserved()
        BLOCKS.clear()
        snap = list(jumpers)
        par0 = dict(par)        # ★ 连通性 DSU 也要能回退 ✓（否则回滚后 par 里留着旧 union ⇒ 自检误报"连上了" ✗）
        # ★★ 新规则（对侧轨「可选」✓）：逐网把组合都试一遍，按 **长度 + K×交集** 挑省的 ✓
        hb = HUB_BUS.get(net) or set()
        variants = [("带对侧轨", need)]
        if hb and not os.environ.get("PP_ONERAIL"):
            wo = [b for b in need if b not in hb]
            if len(wo) >= 2:               # 只剩一条 bus ⇒ 不用接线 ⇒ 不试 ✗
                variants.append(("不带对侧轨", wo))
        best_v = None
        blocks_full = []
        for vlabel, need_v in variants:
            jumpers[:] = list(snap)
            par.clear()
            par.update(par0)
            _refix()
            BLOCKS.clear()
            if not connect_cluster(net, need_v):
                print("   [算账] %-10s %-12s ⇒ 这条走不通 ✓" % (net, vlabel))
                if vlabel == "带对侧轨":
                    blocks_full = list(BLOCKS)      # 拆线重排要用完整方案的诊断 ✓
                continue
            sc = net_score(len(snap))
            print("   [算账] %-10s %-12s ⇒ 本网交集 %d | 本网长度 %.1f mm | 代价 %.1f"
                  % (net, vlabel, sc[0], sc[1] - K_MM * sc[0], sc[1]))
            if best_v is None or (sc[1], sc[0]) < (best_v[0][1], best_v[0][0]):
                best_v = (sc, list(jumpers), vlabel)
        if best_v is not None:
            jumpers[:] = best_v[1]
            par.clear()
            par.update(par0)
            for _n2, _p2, _h1, _h2, _k2 in jumpers[len(snap):]:
                uni(_h1, _h2)               # 选中的方案 ⇒ 把它的 union 重放回 DSU ✓
            _refix()
            ok = True
            if len(variants) > 1:
                print("   [算账] %-10s ⇒ 选「%s」✓" % (net, best_v[2]))
            # ★★ 选了「不带对侧轨」⇒ 把那个备用孔**从网里收回去** ✗（2026-09-27 修 ✓）
            #   否则自检还会去要求「pin3W 也得连上」✗（实测：`net 5V is not connected` ✗
            #   明明线都布好了 ✗）—— 而且**后面几个网的“留路”也会白留** ✗（虚占 X/W 轨 ✓）。
            if best_v[2].startswith("不带") and HUB_HOLES.get(net):
                for _h3 in HUB_HOLES[net]:
                    net_holes[net].discard(_h3)
                NET_BUSES[net] = {hole_bus[h] for h in net_holes[net]}
                print("   [算账] %-10s ⇒ 对侧轨（%s）不进网 ✓，也不占“留路” ✓"
                      % (net, ", ".join(sorted(HUB_HOLES[net]))))
        else:
            jumpers[:] = list(snap)
            par.clear()
            par.update(par0)
            _refix()
            # ★★ 2026-09-27 修 ✓：`BLOCKS` 是 **set** ✓（本文件 line 632 `BLOCKS = set()` ✓），
            #   而 `blocks_full` 是 **list** ✓ ⇒ `BLOCKS[:] = blocks_full` 会
            #   `TypeError: 'set' object does not support item assignment` **直接把管线崩掉** ✗
            #   （实测：拿 `43_byHand` 的摆位重布，`BR+` 连不上时就走到这里 ⇒ 整条管线停 ✗）。
            #   ⇒ 恢复"挡过路的线段集合"就用 set 自己的写法 ✓（集合天然去重 ✓、顺序无关 ✓）。
            BLOCKS.clear()
            BLOCKS.update(blocks_full)
            ok = False
        if not ok:
            # ★★ 拆线重排（rip-up & reroute，2026-09-26 ✓）：
            #   某个网连不上 ⇒ 把它**挡路的那几根线**先抽出来 ✗ ⇒ 先让本网连上 ✓
            #   ⇒ 再把那几根重排 ✓ ⇒ **两边都成立**才收 ✓（否则回到快照 ✓）。
            blocks = list(BLOCKS)
            for attempt in range(1, 4):
                victims = [k for k, j in enumerate(snap)
                           if any(_wire_has_seg(j[1], b) for b in blocks)][:attempt + 1]
                if not victims:
                    break
                jumpers[:] = list(snap)
                _refix()
                vinfo = [(jumpers[k][0], jumpers[k][2], jumpers[k][3]) for k in victims]
                for k in sorted(victims, reverse=True):
                    del jumpers[k]
                _refix()
                print("   [拆线重排] 第 %d 次：抽出 %d 根挡路的（%s）⇒ 先连 %s"
                      % (attempt, len(victims), ", ".join(v[0] for v in vinfo), net))
                if connect_cluster(net, need):
                    good = True
                    for net2, h1, h2 in vinfo:
                        bp = best_link(hole_bus[h1], hole_bus[h2])
                        if not bp:
                            good = False
                            break
                        wire(net2, bp[1], bp[2], bp[3], "sig")
                    if good:
                        print("   [拆线重排] ✓ 成功：%s 连上了，挡路的 %d 根也重排好了"
                              % (net, len(victims)))
                        ok = True
                        break
                print("   [拆线重排] 第 %d 次没成 ✓（挡路的 %d 根）" % (attempt, len(victims)))
            if not ok:
                jumpers[:] = list(snap)
                _refix()
                raise SystemExit("net %s: 连不上（拆线重排 %d 次也不行）⇒ 需要改布局 ✓"
                                 % (net, len(BLOCKS)))
        # ★ 这个网布完了 ⇒ 它用到的孔不再算“留路” ✓（后面可以压它了 ✓，只是不许重叠 ✓）
        DONE_NETS.add(net)
        rebuild_reserved()

    # ★★ 裸露焊盘接地（2026-09-26 用户定 ✓）：
    #   元件上名叫 EPAD/EP 的脚，如果**没插进孔**（只是画面上的一个焊盘 ✓），
    #   就给它拉一根线到 **GND 里一个可用孔** ✓ —— 不是接到别的脚上 ✗！
    #   用户新原则：「一个脚只能**插孔**或**接一根线**，二选一」✗ ⇒ 接到已插孔的脚
    #   （比如 U1 自己的 GND 脚 pin36F）就是“既插孔又接线” ✗（用户看图当场指出来了 ✓）。
    # ★ extra / extra_owner 已在上面初始化 ✓（拆线重排要提前用 _refix ✓）
    for title, names in name2cid.items():
        for nm, cid in sorted(names.items()):
            if not nm or not any(k in nm.upper() for k in ("EPAD", "EP")):
                continue
            inst = next((e for e in sroot.iter("instance")
                         if (e.findtext("title") or "").strip() == title), None)
            if inst is None:
                continue
            emi = inst.get("modelIndex")
            if (emi, cid) in plugged_conn:
                continue                       # 已经插在孔里 ⇒ 无需补线 ✓
            # 已经有了线吗？（本文件里已有指向它的 connect ⇒ 跳过 ✓ 幂等 ✓）
            bbv = child(child(inst, "views"), "breadboardView")
            cbox2 = child(bbv, "connectors")
            con2 = next((c for c in (cbox2 if cbox2 is not None else [])
                         if c.get("connectorId") == cid), None)
            # ★ 只算**实例还在**的线 ✓（旧导线已在载入时清掉 ✓ ⇒ 它留下的记录是悬空 ✗，
            #   不再算“已经有线” ✗）—— 2026-09-27 修 ✓（当时它让 EPAD 静默跳过 ✗）。
            if con2 is not None and any((c3.get("modelIndex") or "") in inst_ids
                                        for c3 in (child(con2, "connects") or [])):
                continue
            # 焊盘位置：part svg 里那个 id="<cid>pin" 的图形 + 实例矩阵 ✓
            fpz2 = (inst.get("path") or "").replace("/", os.sep)
            lay2 = ET.parse(fpz2).getroot().find(".//breadboardView/layers")
            svg2 = None
            base2 = os.path.dirname(os.path.dirname(fpz2))
            for s3 in ("", "core", "contrib", "user"):
                c3 = os.path.normpath(os.path.join(base2, "svg", s3,
                                                   (lay2.get("image") or "").replace("/", os.sep)))
                if os.path.isfile(c3):
                    svg2 = c3
                    break
            if svg2 is None:
                continue
            txt2 = open(svg2, encoding="utf-8").read()
            mm2 = re.search(r'<circle[^>]*id="%spin"[^>]*cx="([\d.]+)"[^>]*cy="([\d.]+)"'
                            % re.escape(cid), txt2)
            if not mm2:
                continue
            g2 = child(bbv, "geometry")
            w2 = pm.size_in_mil(ET.parse(svg2).getroot().get("width"))
            vb2 = [float(x) for x in re.split(r"[ ,]+",
                                              (ET.parse(svg2).getroot().get("viewBox") or "").strip())
                   if x]
            k2 = (w2 * 0.0254 * MM / vb2[2]) if len(vb2) == 4 and vb2[2] else 0.09
            m2 = pbox.tf_of(g2)
            lu, lv = float(mm2.group(1)) * k2, float(mm2.group(2)) * k2
            p_pad = (pm.num(g2.get("x")) + m2[0] * lu + m2[2] * lv + m2[4],
                     pm.num(g2.get("y")) + m2[1] * lu + m2[3] * lv + m2[5])
            # ★ 目标（2026-09-26 用户定 ✓）：**GND 电源轨**（第一行 Z 上 / X 下 ✓）
            #   —— 用户原话：「数据手册常说 EPAD 接 VSS，只适用于 PCB。面包板 / 原理图 / PCB
            #   有各自的逻辑和美学」✓ ⇒ **原理图与面包板都要看得见"特意接到地"** ✓；
            #   接到本元件**自己的 GND 脚**所在 bus ⇒ 画出来像"芯片内部就连着" ✗（已废弃 ✗）。
            #   分级回退：① GND 电源轨 ✓ ② 别处的 GND bus ✓ ③ 实在不行才用自己的（会报警 ✓）
            own_gnd = next((h for h in net_holes.get("GND", ())
                            if plug_of.get(h, ("", ""))[0] == title), None)
            own_b = hole_bus.get(own_gnd) if own_gnd else None
            gnd_holes = sorted_holes(net_holes.get("GND", ()))
            tiers = [[], [], []]
            for h in gnd_holes:
                b2 = hole_bus[h]
                if b2 == own_b:
                    continue
                tiers[0 if h[-1] in ("Z", "X") else 1].append(b2)
            if own_b is not None:
                tiers[2].append(own_b)
            best_w = None
            tier_used = None
            for ti, tbus in enumerate(tiers):
                uniq, seen2 = [], set()
                for b2 in tbus:
                    if b2 not in seen2:
                        seen2.add(b2)
                        uniq.append(b2)
                if not uniq:
                    continue
                best_w = epad_route(p_pad, uniq, title)
                if best_w is not None:
                    tier_used = ti
                    break
            if own_gnd is not None:
                _all = sorted(bus_of[own_b], key=lambda c: (hole[c][1], hole[c][0]))
                print("   EPAD: 本元件自己的 GND bus（%s，**不用** ✓）各孔状态: %s" % (
                    own_gnd, " ".join("%s%s" % (h, "*被遮" if h in blocked else
                                                  ("*插了" if h in occupied else
                                                   ("*已用" if h in used else ""))) for h in _all)))
            if best_w is None:
                print("   [!] %s 的 %s 找不到干净的接地线 ⇒ 跳过（需人工看 ✓）" % (title, cid))
                continue
            (_k2, pts_w, hid) = best_w
            used.add(hid)
            used_holes.add(hid)
            wire_ends.add(hid)
            extra.append(("GND", pts_w, ("pin", emi, cid), ("hole", hid), "epad"))
            extra_owner.append(title)
            fixed_segs.extend([(pts_w[k], pts_w[k + 1]) for k in range(len(pts_w) - 1)])
            print("   EPAD 接地: %s 的 %s（焊盘 %.1f,%.1f）→ %s（%s）✓"
                  % (title, cid, p_pad[0], p_pad[1], hid,
                     ("**GND 电源轨** ✓", "别处的 GND bus ✓",
                      "[!] 回退到自己的 GND bus ✗ 不合口径")[tier_used]))

    # ★★ 抽出重排分**两段**（2026-09-26 ✓）：
    #   ① 前几轮 = **先少交叉** ✓（用户判据“交叉数第一” ✓）—— 只按交叉数排 ✓
    #   ② 后几轮 = **算账** ✓（代价 = 长度 + K × 交集 ✓）—— 允许用 ≤K mm 的长度
    #      换 1 个交叉 ✓（这就是把 94mm 长蛇换成 25mm 的那一步 ✓）
    #   （若全程都用加权 ⇒ 它会到处加交叉来减长度 ✗，实测直接掉到 6 个交叉 ✗）
    KEY_MODE = [1]

    # ★★ 抽出重排（2026-09-26 用户原则：**引线尽可能少相交** ✓，压过"长度为主" ✓）
    #   贪婪布线只看"已经放好的线" ✗ ⇒ 后放的看不见前面的选择 ✗（实测会多出交叉 ✗）
    #   ⇒ 收尾把每根"抽出来"，在**看得见其它所有线**的条件下重算它 ✓，
    #     只在「交叉数变少 ✓ / 交叉相同且明显变短 ✓」时才采纳 ✓
    def best_by_cross(ba, bb):
        """在两个 bus 里挑一对孔 + 一条路：键见 `KEY_MODE` ✓
        ① 少交叉阶段：交叉数 → 折弯 → 形状加权长度 ✓
        ② 算账阶段：加权代价（长度 + K×交集）→ 交集 → 折弯 → 长 ✓
        """
        ca, cb = free_in(ba), free_in(bb)
        if not ca or not cb:
            return None
        pairs = sorted((((hole[x][0] - hole[y][0]) ** 2 + (hole[x][1] - hole[y][1]) ** 2),
                        x, y) for x in ca for y in cb)[:60]
        best = None
        for _d, x, y in pairs:
            for pts in routes(x, y):
                c = route_cost(pts)
                if c is None:
                    continue
                if covered_by_wires((x, y)):
                    continue      # ★ 重排后要占的孔被别的线盖住 ✗ ⇒ 这组不算 ✓
                # ★ 键：① 少交叉阶段 = （交集 → 折弯 → 形状加权长度 → 代价）
                #     ② 算账阶段 = （代价 → 交集 → 折弯 → 形状加权长度）（见 KEY_MODE ✓）
                cr0 = _cross(pts, wire_segs())
                if KEY_MODE[0] == 1:
                    k = (cr0, bends(pts), _plen(pts) * shape_factor(pts), c)
                else:
                    k = (c, cr0, bends(pts), _plen(pts) * shape_factor(pts))
                if best is None or k < best[0]:
                    best = (k, pts, x, y)
        return best

    allsegs0 = [s for j in jumpers for s in _segs(j[1])] + fixed_segs
    n_cross_before = sum(1 for i in range(len(allsegs0)) for j in range(i + 1, len(allsegs0))
                         if BC.pair_kind(allsegs0[i][0], allsegs0[i][1],
                                         allsegs0[j][0], allsegs0[j][1]))
    for sweep in range(1, 9):
        KEY_MODE[0] = 1 if sweep <= 4 else 2      # ★ 先少交叉（1-4 轮）→ 再算账（5-8 轮）✓
        moved = 0
        # 交替方向 ✓：只往前扫容易卡在局部最优 ✗（反着扫一遍常能再降一点 ✓）
        order = list(range(len(jumpers)))
        if sweep % 2 == 0:
            order.reverse()
        for i in order:
            if i >= len(jumpers):
                break
            net, pts_old, h1, h2, kind = jumpers[i]
            ba, bb = hole_bus[h1], hole_bus[h2]
            del jumpers[i]
            _refix()
            old_cross = _cross(pts_old, wire_segs())
            old_b = bends(pts_old)
            old_len = _plen(pts_old) * shape_factor(pts_old)
            old_cost = old_len + K * old_cross          # ★ 加权代价 ✓（汇率 K_MM ✓）
            take = best_by_cross(ba, bb)
            if take is not None:
                (k0, k1, k2, k3), pts_new, n1, n2 = take
                if KEY_MODE[0] == 1:
                    k_new = (k0, k1, k2, k3)                    # = (交集,折弯,形状加权长,代价)
                    k_old = (old_cross, old_b, old_len, old_cost)
                    new_cross = k0
                else:
                    k_new = (k3, k0, k1, k2)                    # = (代价,交集,折弯,形状加权长)
                    k_old = (old_cost, old_cross, old_b, old_len)
                    new_cross = k1
                # ★★ 2026-09-27 修 ✓（一笔**亏本买卖** ✗，日志为证 ✓）：
                #   旧闸门是 `new_len <= old_len * 1.5 + 9.0` ✗ —— **写死的 1.5 倍 + 9** ✗，
                #   根本不是汇率 ✓；而且 `new_len` 在两个 mode 里**含义不同** ✗
                #   （mode 1 = 形状加权长 ✗ / mode 2 = 加权代价 ✗）⇒ 一个名字两种含义 ✓。
                #   实测代价 ✗：GND 那根 `pin25X→pin31D`（真长 21.6mm ✓，斜线 ⇒ 形状加权 32.4mm ✓）
                #   被换成 43.2mm ✗，交集 1→0 ⇒ GND 123.5 → **168.0mm** ✗（多绕 **44.5mm** ✗）。
                #   ⇒ 换成用户定的**汇率判据** ✓：**少 1 个交集最多值得多绕 K_MM 毫米** ✓
                #     （"超过就不值得" ✗），而且**两边都用真实长度(mm)** ✓（= 用户的尺子 ✓，
                #      不用形状加权 ✗）⇒ 两个 mode **同一份实现** ✓（判据只有一份 ✓）。
                _old_real = _plen(pts_old) * MMU
                _new_real = _plen(pts_new) * MMU
                _dc = old_cross - new_cross                 # 省下的交集数 ✓
                _dlen = _new_real - _old_real               # 多花的真实长度（mm ✓）
                if k_new < k_old and _dlen <= K_MM * _dc + 1e-9:
                    jumpers.insert(i, (net, pts_new, n1, n2, kind))
                    _refix()
                    moved += 1
                    if (n1, n2) != (h1, h2) or new_cross != old_cross:
                        print("   抽出重排: %-10s %s→%s 换成 %s→%s  交集 %d→%d | 真长 %.1f→%.1f mm"
                              "（Δ%+.1f mm ≤ K×%d = %d ✓）"
                              % (net, h1, h2, n1, n2, old_cross, new_cross,
                                 _old_real, _new_real, _dlen, _dc, round(K_MM * _dc)))
                    continue
            jumpers.insert(i, (net, pts_old, h1, h2, kind))
            _refix()
        # ★ 额外线（EPAD ✓）也一起重排 ✓（它也是"引线" ✓，同样该让交叉更少 ✓）
        for ix in range(len(extra)):
            if ix >= len(extra):
                break
            net_e, pts_e, e0, e1, kind_e = extra[ix]
            if e1[0] != "hole":
                continue
            own = extra_owner[ix] if ix < len(extra_owner) else None
            del extra[ix]
            fixed_segs[:] = [s for _n, p, _a, _b, _k in extra for s in _segs(p)]
            _refix()
            old_cross = _cross(pts_e, wire_segs(), own)   # ★ own 也要传 ✓
            #   （以前这里漏了 own ✗ ⇒ 旧路由把"碰到**自己**那块板"算成 1 个交集 ✗，
            #     而候选路由那边是豁免的 ✓ ⇒ 每次比较都是 1→0 ✗ 永远"改进" ✓ ⇒
            #     同一根线被反复"重排"、全局却一动不动 ✗ —— 本次实测 8 轮重复 ✗）
            old_b = bends(pts_e)
            old_len = _plen(pts_e) * shape_factor(pts_e)
            old_cost = old_len + K * old_cross          # ★ 加权代价 ✓
            take_e = epad_route(pts_e[0], [hole_bus[e1[1]]], own)
            if take_e is not None:
                (ncost, nc, nb, nl), pts_new, nh = take_e
                if KEY_MODE[0] == 1:
                    k_new_e = (nc, nb, nl, ncost)
                    k_old_e = (old_cross, old_b, old_len, old_cost)
                else:
                    k_new_e = (ncost, nc, nb, nl)
                    k_old_e = (old_cost, old_cross, old_b, old_len)
                if k_new_e < k_old_e:
                    _old_re = _plen(pts_e) * MMU
                    _new_re = _plen(pts_new) * MMU
                    _dce = old_cross - nc
                    _dle = _new_re - _old_re
                    # ★★ 与上面同一份汇率判据 ✓（2026-09-27 ✓）：真实长度 ✓ + K_MM×省下的交集 ✓
                    if _dle <= K_MM * _dce + 1e-9:
                        extra.insert(ix, (net_e, pts_new, e0, ("hole", nh), kind_e))
                        fixed_segs[:] = [s for _n, p, _a, _b, _k in extra for s in _segs(p)]
                        _refix()
                        moved += 1
                        print("   抽出重排: %-10s 额外线 %s 换成 %s  交集 %d→%d | 真长 %.1f→%.1f mm"
                              "（Δ%+.1f ≤ K×%d ✓）"
                              % (net_e, e1[1], nh, old_cross, nc,
                                 _old_re, _new_re, _dle, round(K_MM * _dce)))
                        continue
            extra.insert(ix, (net_e, pts_e, e0, e1, kind_e))
            fixed_segs[:] = [s for _n, p, _a, _b, _k in extra for s in _segs(p)]
            _refix()
        allsegs = [s for j in jumpers for s in _segs(j[1])] + fixed_segs
        n_cross = sum(1 for i in range(len(allsegs)) for j in range(i + 1, len(allsegs))
                      if BC.pair_kind(allsegs[i][0], allsegs[i][1],
                                      allsegs[j][0], allsegs[j][1]))
        print("抽出重排 第 %d 轮: 动了 %d 根 | 交集 %d → %d" % (sweep, moved, n_cross_before, n_cross))
        n_cross_before = n_cross
        if not moved:
            break
    _refix()

    # ★★ 成对重排（2-opt，2026-09-26 ✓）：**相交的两根一起抽掉、再按顺序重放** ✓
    #   单根抽出重排会卡死 ✗（每根单独动都会让别的更差 ⇒ 谁都不动 ✓）；
    #   成对重排常能一次解开"两根互相绊住"的局面 ✓。
    #   判据：少交叉阶段比"交集" ✓、算账阶段比"长度 + K×交集" ✓（都用全局值 ✓）
    # ★★ 硬约束违规的**唯一实现** ✓（2026-09-27 ✓）：重排目标函数 + 最终自检**共用这一份** ✓
    #   教训（2026-09-27 ✗）：以前自检里是**独立一份**实现 ✗ ⇒ 重排看不见“接线孔被盖 /
    #   端点被压 / 一孔两线”这些违规 ✗ ⇒ 串链弄出的违规（3 处 ✗）它**解不开** ✗
    #   —— 判据有两份实现 ⇒ 数字对不上、优化器目标 ≠ 用户看到的东西 ✗。
    #   ① dup    ：同一个孔里插了两根线的端点 ✗（一孔只插一根 ✓）
    #   ② bad_ends：一根线的**端点孔**被另一根线压住 ✗（看着接了、其实被压住 ✓）
    #   ③ hidden ：把“已经接了线的孔”盖住 ≥ OBSCURE_LIMIT(30%) ✗（用户 2026-09-26 定 ✓）
    def hard_bad():
        ends_l = [h for _n, _p, h1, h2, _k in jumpers for h in (h1, h2)]
        dup_s = {h for h in ends_l if ends_l.count(h) > 1}
        be = set()
        for i, (_n, pts, _h1, _h2, _k) in enumerate(jumpers):
            for a, b in _segs(pts):
                for j, (_n2, _p2, g1, g2, _k2) in enumerate(jumpers):
                    if i == j:
                        continue
                    for g in (g1, g2):
                        if on_seg(hole[g], a, b):
                            be.add(g)
        hid = {}
        _wsets = [(pts, set((h1, h2))) for _n, pts, h1, h2, _k in jumpers]
        _wsets += [(pts, set(e[1] for e in (e0, e1) if e[0] == "hole"))
                   for _n, pts, e0, e1, _k in extra]
        for pts, _ends_here in _wsets:
            for a, b in _segs(pts):
                for h in sorted_holes(used_holes):
                    if h in _ends_here:
                        continue
                    f = obscures(a, b, hole[h])
                    if f >= OBSCURE_LIMIT:
                        hid[h] = max(hid.get(h, 0.0), f)
        return (dup_s, be, hid)

    # ★ 硬约束在目标函数里的**权重** ✓（人为可调 ✓）：1 个硬违规 = HARD_MM 毫米 ✓
    #   —— 硬约束是“不满足就不许交付” ✗ ⇒ 权重必须压过长度/交叉的任何取舍 ✓。
    HARD_MM = 100.0

    def layout_score():
        sg_all = [s for j in jumpers for s in _segs(j[1])] + fixed_segs
        n = 0
        for i1 in range(len(sg_all)):
            for j1 in range(i1 + 1, len(sg_all)):
                if BC.pair_kind(sg_all[i1][0], sg_all[i1][1],
                                sg_all[j1][0], sg_all[j1][1]):
                    n += 1
        over = 0
        for ix2, (_n2, pts2, _e02, _e12, _k2) in enumerate(extra):
            own2 = extra_owner[ix2] if ix2 < len(extra_owner) else None
            for a2, b2 in _segs(pts2):
                for w2, r2 in boxes:
                    if w2 != own2 and seg_hits(a2, b2, r2):
                        over += 1
        tot = sum(((p2[0] - q2[0]) ** 2 + (p2[1] - q2[1]) ** 2) ** 0.5
                  for p2, q2 in sg_all) * MMU
        # ★ 硬违规（唯一实现 ✓）+ 规则 ⑩ 的“中间走廊”长度（只管电源/地组 0/1 ✓）
        _dup, _be, _hid = hard_bad()
        hard = len(_dup) + len(_be) + len(_hid)
        corr = 0.0
        for _n3, _p3, _h13, _h23, _k3 in jumpers:
            if net_rank(_n3) <= 1:
                corr += mid_len(_p3) * MMU
        return (n + over + hard,
                tot + K_MM * (n + over) + HARD_MM * hard + MID_PEN * corr)

    def better(md, a, b):
        """a 是否比 b 好 ✓：mode 1 先比交集 ✓；mode 2 先比代价 ✓

        ★★ 2026-09-27 修 ✓（一条**亏本买卖** ✗）：mode 1 以前**完全不看长度** ✗ ⇒
          实测（v53 的日志 ✓）为了省 **1** 个交叉，把 GND 那根 `pin25X→pin31D`（21.6mm ✓）
          换成 `pin19X→pin31C`（43.2mm ✗）⇒ GND 从 **123.5 → 168.0mm** ✗（多绕 **44.5mm** ✗）。
          而汇率是用户定的 **K = 10mm / 交集** ✓（"为了少 1 个交叉，最多值得多绕 K 毫米 ✓；
          超过就不值得 ✗"）⇒ 这一笔该**拒收** ✗。
          ⇒ mode 1 保持"**交叉数不许变多** ✓ + 少交叉优先 ✓"，但**多花的长度要按汇率算账** ✓：
             `a[1] <= b[1]` 等价于 `多花长度 ≤ K_MM × 省下的交叉数` ✓（因为 x[1] = 长 + K×交集 ✓）。
        """
        if md == 1:
            if a[0] > b[0]:
                return False                      # 交叉更多 ⇒ 不要 ✗
            if a[0] == b[0]:
                return a[1] < b[1]
            return a[1] <= b[1]                   # ★ 少交叉 ✓ 且 多花的长度 ≤ K×ΔΔ ✓
        return (a[1], a[0]) < (b[1], b[0])

    def crossing_pairs():
        out = []
        for i1 in range(len(jumpers)):
            for j1 in range(i1 + 1, len(jumpers)):
                if any(BC.pair_kind(a2, b2, c2, d2)
                       for a2, b2 in _segs(jumpers[i1][1])
                       for c2, d2 in _segs(jumpers[j1][1])):
                    out.append((i1, j1))
        return out

    for opt in range(1, 5):
        KEY_MODE[0] = 1 if opt <= 2 else 2
        done = 0
        for i0, j0 in crossing_pairs()[:12]:
            if i0 >= len(jumpers) or j0 >= len(jumpers):
                continue
            A, B = jumpers[i0], jumpers[j0]
            keep = list(jumpers)
            before = layout_score()
            rest = [w for k, w in enumerate(keep) if k not in (i0, j0)]
            best_try = None
            for first, second in ((A, B), (B, A)):
                jumpers[:] = rest
                _refix()
                t1 = best_by_cross(hole_bus[first[2]], hole_bus[first[3]])
                w1 = (first[0], t1[1], t1[2], t1[3], first[4]) if t1 else first
                jumpers[:] = rest + [w1]
                _refix()
                t2 = best_by_cross(hole_bus[second[2]], hole_bus[second[3]])
                w2 = (second[0], t2[1], t2[2], t2[3], second[4]) if t2 else second
                jumpers[:] = rest + [w1, w2]
                _refix()
                sc = layout_score()
                if best_try is None or better(KEY_MODE[0], sc, best_try[0]):
                    best_try = (sc, list(jumpers))
            if best_try is not None and better(KEY_MODE[0], best_try[0], before):
                jumpers[:] = best_try[1]
                _refix()
                done += 1
                print("   成对重排: %-10s × %-10s ⇒ 交集 %d→%d | 长 %.1f→%.1f mm"
                      % (A[0], B[0], before[0], best_try[0][0],
                         before[1], best_try[0][1]))
            else:
                jumpers[:] = keep
                _refix()
        sc_now = layout_score()
        print("成对重排 第 %d 轮（模式 %d）: 动了 %d 对 | 交集 %d | 代价 %.1f"
              % (opt, KEY_MODE[0], done, sc_now[0], sc_now[1]))
        if not done:
            break
    _refix()

    # ★★ 破局重排（R&R，2026-09-26 ✓）：卡在局部最优时，把**所有还有交集的线**一起抽掉、
    #   按两种顺序（交集多的先 ✓ / 原顺序 ✓）整批重放 ✓ —— 比 2-opt（只动两根）邻域更大 ✓，
    #   能一次跨过"两根互相绊住"的死胡同 ✓。取全局更优的那版（判据同上一段 ✓）。
    def wire_cross_count(j, idx):
        others2 = [s for k2, j2 in enumerate(jumpers) if k2 != idx for s in _segs(j2[1])] \
            + fixed_segs
        return _cross(j[1], others2)

    for rr in range(1, 4):
        KEY_MODE[0] = 1 if rr <= 2 else 2
        culprits = [k for k, j in enumerate(jumpers) if wire_cross_count(j, k) > 0]
        if len(culprits) < 2 or len(culprits) > 8:
            break
        before = layout_score()
        keep = list(jumpers)
        rest = [w for k, w in enumerate(keep) if k not in culprits]
        best = None
        for desc in (True, False):
            seq = sorted(culprits, key=lambda k: -wire_cross_count(keep[k], k)) \
                if desc else list(culprits)
            cur, ok = list(rest), True
            for k in seq:
                w = keep[k]
                jumpers[:] = cur
                _refix()
                t = best_by_cross(hole_bus[w[2]], hole_bus[w[3]])
                if t is None:
                    ok = False
                    break
                cur = cur + [(w[0], t[1], t[2], t[3], w[4])]
            if not ok:
                continue
            jumpers[:] = cur
            _refix()
            sc = layout_score()
            if best is None or better(KEY_MODE[0], sc, best[0]):
                best = (sc, list(cur))
        if best is not None and better(KEY_MODE[0], best[0], before):
            jumpers[:] = best[1]
            _refix()
            print("   破局重排 第 %d 轮: %d 根整批重放 ⇒ 交集 %d→%d | 代价 %.1f→%.1f"
                  % (rr, len(culprits), before[0], best[0][0], before[1], best[0][1]))
        else:
            jumpers[:] = keep
            _refix()
            print("   破局重排 第 %d 轮: %d 根整批重放 ⇒ 没变好（交集 %d）"
                  % (rr, len(culprits), before[0]))
            break
    _refix()

    # checks
    bad = 0
    for net, hs in net_holes.items():
        if hs and len({find(h) for h in sorted_holes(hs)}) != 1:
            bad += 1
            print("[!] net %s is not connected" % net)
    ends = [h for _n, _p, h1, h2, _k in jumpers for h in (h1, h2)]
    # ★ 硬约束（dup / 端点被压 / 盖住接线孔 ✓）统一调 `hard_bad()` ✓ —— **唯一实现** ✓
    #   （2026-09-27 ✓：以前这里是**第二份**实现 ✗ ⇒ 重排看不见这些违规 ✗）
    _dup_s, bad_ends, hidden = hard_bad()
    dup = sorted(_dup_s)
    segs = [(pts[i], pts[i + 1]) for _n, pts, _h1, _h2, _k in jumpers
            for i in range(len(pts) - 1)]
    # ★ 额外线（EPAD ✓）也要算进去（2026-09-26 修 ✓：以前自检只看 jumpers ✗ ⇒
    #   EPAD 那根线盖住了 U1 插在 pin32F 的脚 50%，自检却报 "hidden 0" ✗）
    ex_segs = [(pts[i], pts[i + 1]) for _n, pts, _e0, _e1, _k in extra
               for i in range(len(pts) - 1)]
    allsegs = segs + ex_segs
    cross = ovl = 0
    for i, (p, q) in enumerate(allsegs):
        for p2, q2 in allsegs[i + 1:]:
            kd = BC.pair_kind(p, q, p2, q2)
            if kd == "overlap":
                ovl += 1
            elif kd:
                cross += 1
    over_body = [(n, h1, h2, w) for n, pts, h1, h2, _k in jumpers
                 for i in range(len(pts) - 1) for w, r in boxes if seg_hits(pts[i], pts[i + 1], r)]
    for _ix, (_n, pts, _e0, _e1, _k) in enumerate(extra):
        _own = extra_owner[_ix] if _ix < len(extra_owner) else None
        for i in range(len(pts) - 1):
            for w, r in boxes:
                if w != _own and seg_hits(pts[i], pts[i + 1], r):
                    over_body.append((_n, "epad", "-", w))
    tot = sum(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 for p, q in allsegs)
    # ★★ 「交集」= X 形交叉 + T 形搭线 + 从元件底下穿过 ✓（上面 `pair_kind` 一次算完 ✓）
    t_touch_all = 0
    for i, (p, q) in enumerate(allsegs):
        for p2, q2 in allsegs[i + 1:]:
            if BC.pair_kind(p, q, p2, q2) == "touch":
                t_touch_all += 1
    own_of = {}
    for ix, (_n, pts, _e0, _e1, _k) in enumerate(extra):
        own_of[id(pts)] = extra_owner[ix] if ix < len(extra_owner) else None
    over_part = []
    for i, (_n, pts, _e0, _e1, _k) in enumerate(extra):
        own = extra_owner[i] if i < len(extra_owner) else None
        for a, b in _segs(pts):
            for w, r in boxes:
                if w != own and seg_hits(a, b, r):
                    over_part.append(("epad", w))
    crowd = 0.0
    for i, (_n, pts, _h1, _h2, _k) in enumerate(jumpers):
        others = [(p, q) for j, (_n2, p2, _a, _b, _k2) in enumerate(jumpers) if j != i
                  for p, q in ((p2[k], p2[k + 1]) for k in range(len(p2) - 1))]
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            for c, d in others:
                if point_seg_dist(mid, c, d) < NEAR_DIST or point_seg_dist(c, a, b) < NEAR_DIST:
                    crowd += 1
    print("check: attach holes %d (dup %d) %s | over body %d | crossings %d | overlap %d | "
          "endpoint holes crossed %d | **connected holes hidden %d** | nets bad %d"
          % (len(ends), len(dup), "OK" if not dup else "FAIL", len(over_body), cross, ovl,
             len(bad_ends), len(hidden), bad))
    print("★★ 交集（用户判据 ✓）= 与引线相交 %d（含 T 形搭线 %d）+ 穿元件 %d = **%d**"
          % (cross, t_touch_all, len(over_part), cross + len(over_part)))
    print("★★ 目标 = 长度 %.1f mm + K(%.0f mm) × 交集 %d = **%.1f**（K 是人为可调系数 ✓）"
          % (tot * MMU, K_MM, cross + len(over_part),
             tot * MMU + K_MM * (cross + len(over_part))))
    for ttl, w in over_part:
        print("   [穿元件 ✗] %s 从 %s 底下穿过" % (ttl, w))
    if hidden:
        for h, f in sorted(hidden.items(), key=lambda kv: -kv[1])[:8]:
            print("   hides %s (%.0f%%) %s" % (h, f * 100, plug_of.get(h, "")))
    print("score: links %d = %d wire segments | length %.1f mm | avg seg %.1f mm | "
          "crowding %.2f (neighbours within %.1f units per segment)"
          % (len(jumpers), len(segs), tot * MMU, tot * MMU / max(1, len(segs)),
             crowd / max(1, len(segs)), NEAR_DIST))
    if dup or over_body or ovl or bad or hidden:
        raise SystemExit("self-checks failed -> NO file written")

    # write
    tmpl = None
    for e in list(sroot.iter("instance")):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        if child(child(e, "views"), "breadboardView") is None:
            continue
        if tmpl is None:
            tmpl = e
        host.remove(e)
    if tmpl is None:
        tmpl = WIRE_TMPL          # ★ 旧导线已在载入时清掉 ✓ ⇒ 用它当时留下的模板 ✓
    if tmpl is None:
        raise SystemExit("no breadboard wire template")
    # ★★ 清掉**旧连接记录** ✓（2026-09-26 用户实测 ✗）：上面删了旧导线 ✓，但板子上
    #   "孔 → 那根线"的记录还留着 ✗ ⇒ Fritzing 里那些孔显示成"接在一根不存在的线上" ✗
    #   ⇒ 悬停一个孔、一大片孔都亮起来 ✗（用户截图 ✓）。
    #   实测：我以前的版本 **12 处悬空引用** ✗，而用户手画版 **0 处** ✓（钉死：记录必须与实例一致 ✓）。
    bsub = child(child(board, "views"), "breadboardView")
    bbox = child(bsub, "connectors")
    if bbox is None:
        bbox = ET.SubElement(bsub, "connectors")
    _cleared = 0
    for con in list(bbox.iter("connector")):
        cs2 = child(con, "connects")
        if cs2 is None:
            continue
        for c2 in list(cs2):
            cs2.remove(c2)
            _cleared += 1
    print("   清理旧记录：板子连接表里 %d 条 ✓（避免悬空引用 ✗）" % _cleared)
    counter = [max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1]

    def new_wire(net, p, q):
        e = copy.deepcopy(tmpl)
        mi = counter[0]
        counter[0] += 1
        e.set("modelIndex", str(mi))
        t = child(e, "title")
        if t is not None:
            t.text = "Wire%d" % mi
        vw = child(e, "views")
        for sub in list(vw):
            if tag(sub) != "breadboardView":
                vw.remove(sub)
        sub = child(vw, "breadboardView")
        sub.set("layer", "breadboardWire")
        g = child(sub, "geometry")
        g.attrib.update({"x": "%.4f" % p[0], "y": "%.4f" % p[1], "x1": "0", "y1": "0",
                         "x2": "%.4f" % (q[0] - p[0]), "y2": "%.4f" % (q[1] - p[1]),
                         "wireFlags": "64"})
        we = child(sub, "wireExtras")
        if we is None:
            we = ET.SubElement(sub, "wireExtras")
        we.attrib.update({"mils": "22.2222", "color": COLOR.get(net, "#418dd9"),
                          "opacity": "1", "banded": "0"})
        # ★ 2026-09-26 **不写**实例的 `color` 属性 ✓ —— 实测：写成元素文本时 Fritzing
        #   读不到值 ✗ ⇒ **整张图所有导线都变蓝** ✗✗（比"面板显示错色"严重得多 ✗）。
        #   且用户自己的 `pixel.fzz` 里彩色导线**根本没有这个属性** ✓ ⇒ Fritzing 只认
        #   `wireExtras/@color` ✓ ⇒ 只写它 ✓（值用标准配色 ✓）。
        for boxel in sub.iter():
            if tag(boxel) == "connects":
                for c in list(boxel):
                    boxel.remove(c)
        vb = child(sub, "connectors")
        if vb is not None:
            sub.remove(vb)
        vb = ET.SubElement(sub, "connectors")
        for cid in ("connector0", "connector1"):
            con = ET.SubElement(vb, "connector", {"connectorId": cid, "layer": "breadboardWire"})
            ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
            ET.SubElement(con, "connects")
        host.append(e)
        return e, mi

    def add_connect(e, cid, peer_cid, peer_mi, layer):
        vb = child(child(child(e, "views"), "breadboardView"), "connectors")
        con = next(c for c in vb if c.get("connectorId") == cid)
        ET.SubElement(child(con, "connects"), "connect",
                      {"connectorId": peer_cid, "modelIndex": str(peer_mi), "layer": layer})

    def board_connect(hcid, wcid, mi):
        con = next((c for c in bbox if tag(c) == "connector"
                    and c.get("connectorId") == hcid), None)
        if con is None:
            con = ET.SubElement(bbox, "connector", {"connectorId": hcid, "layer": "breadboard"})
            ET.SubElement(con, "geometry", {"x": "0", "y": "0"})
        cs = child(con, "connects")
        if cs is None:
            cs = ET.SubElement(con, "connects")
        ET.SubElement(cs, "connect", {"connectorId": wcid, "modelIndex": str(mi),
                                      "layer": "breadboardWire"})

    for net, pts, h1, h2, _k in jumpers:
        pts = simplify(pts)          # ★ 去冗余点 ✓（否则 Fritzing 里会多出一个可见节点 ✗）
        made = [new_wire(net, pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        for k in range(len(made) - 1):
            add_connect(made[k][0], "connector1", "connector0", made[k + 1][1], "breadboardWire")
            add_connect(made[k + 1][0], "connector0", "connector1", made[k][1], "breadboardWire")
        # ★ 两端接的是**孔**（h1 / h2 = 孔 id ✓）—— 这里以前误写成 pts[0]/pts[-1]
        #   （那是**坐标** ✗）⇒ 连接记录里塞进了 "(265.5, 94.5)" 这种假 connectorId ✗
        #   ⇒ Fritzing 认为所有线头都是悬空的 ⇒ **线头全变红圈** ✗（2026-09-26 用户实测 ✓）
        add_connect(made[0][0], "connector0", h1, bmi, "breadboardbreadboard")
        add_connect(made[-1][0], "connector1", h2, bmi, "breadboardbreadboard")
        board_connect(h1, "connector0", made[0][1])
        board_connect(h2, "connector1", made[-1][1])

    # 额外线（裸露焊盘接地 ✓）：一端是**元件脚**（未插孔 ✓）、一端是**孔** ✓
    for net, pts, end0, end1, _kind in extra:
        pts = simplify(pts)          # ★ 同上：去冗余点 ✓
        made = [new_wire(net, pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        for k in range(len(made) - 1):
            add_connect(made[k][0], "connector1", "connector0", made[k + 1][1], "breadboardWire")
            add_connect(made[k + 1][0], "connector0", "connector1", made[k][1], "breadboardWire")
        for wire_el, wi, end, cid in ((made[0][0], made[0][1], end0, "connector0"),
                                      (made[-1][0], made[-1][1], end1, "connector1")):
            if end[0] == "hole":
                add_connect(wire_el, cid, end[1], bmi, "breadboardbreadboard")
                board_connect(end[1], cid, wi)
            else:                       # ("pin", part modelIndex, connectorId)
                add_connect(wire_el, cid, end[2], end[1], "breadboard")
                pinst = next(e for e in sroot.iter("instance") if e.get("modelIndex") == end[1])
                pv = child(child(pinst, "views"), "breadboardView")
                pcb = child(pv, "connectors")
                if pcb is None:
                    pcb = ET.SubElement(pv, "connectors")
                pc = next((c for c in pcb if c.get("connectorId") == end[2]), None)
                if pc is None:
                    pc = ET.SubElement(pcb, "connector", {"connectorId": end[2],
                                                           "layer": "breadboard"})
                    ET.SubElement(pc, "geometry", {"x": "0", "y": "0"})
                pcs = child(pc, "connects")
                if pcs is None:
                    pcs = ET.SubElement(pc, "connects")
                ET.SubElement(pcs, "connect", {"connectorId": cid,
                                               "modelIndex": str(wi),
                                               "layer": "breadboardWire"})

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for n2 in z.namelist():
            o.writestr(n2, body if n2 == name else z.read(n2))

    # ★★ 回读自检（2026-09-26 补 ✓）：把刚写出的文件再读一遍，检查
    #    ① 每根跳线的两端都接在**真实存在的孔 id** 上 ✓
    #    ② 线→孔的连接条数正好 = 2 × 跳线数 ✓
    #   —— 上一版就是这里出的事：把**坐标**当成孔 id 写进了连接记录 ✗
    #   ⇒ Fritzing 里所有线头都是**红圈**（未连接 ✗）。这个检查就是为了让这种事不再发生 ✓
    back = ET.fromstring(zipfile.ZipFile(out).read(name))
    bad_ref, hole_conn = [], 0
    n_hole_ends = 2 * len(jumpers) + sum(1 for _n, _p, e0, e1, _k in extra
                                        for e in (e0, e1) if e[0] == "hole")
    for e in back.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        sub = child(child(e, "views"), "breadboardView")
        if sub is None:
            continue
        for cs in sub.iter():
            if tag(cs) != "connect":
                continue
            if (cs.get("layer") or "") == "breadboardbreadboard":
                hole_conn += 1
                if (cs.get("connectorId") or "") not in hole:
                    bad_ref.append(((e.findtext("title") or "?"), cs.get("connectorId")))
    ok = (not bad_ref) and hole_conn == n_hole_ends
    # 还有**反向**：板子上那些孔必须有指回导线的记录 ✓（两头都要有 ✓）
    bs = child(child(board, "views"), "breadboardView")
    holes_back = set()
    for c in (child(bs, "connectors") if child(bs, "connectors") is not None else []):
        for c2 in (child(c, "connects") if child(c, "connects") is not None else []):
            if tag(c2) == "connect" and (c2.get("layer") or "") == "breadboardWire":
                holes_back.add(c.get("connectorId"))
    missing = sorted({h for _n, _p, h1, h2, _k in jumpers for h in (h1, h2) if h not in holes_back})
    ok = ok and not missing
    # ★ 新原则（2026-09-26 用户定 ✓）：**一个脚只能「插孔」或「接一根线」二选一** ✗
    #   ⇒ 线的端点若是**元件脚**，这个脚必须**没有插在孔里** ✗（否则就是既插孔又接线 ✗）
    double = []
    for e in back.iter("instance"):
        if not (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        sub = child(child(e, "views"), "breadboardView")
        if sub is None:
            continue
        for cs in sub.iter():
            if tag(cs) != "connect":
                continue
            m_ = cs.get("modelIndex")
            if m_ == bmi:
                continue                       # 接在板子（孔）上 ✓
            if (m_, cs.get("connectorId")) in plugged_conn:
                double.append((e.findtext("title"), m_, cs.get("connectorId")))
    ok = ok and not double
    print("round-trip: wire->hole connects %d (expect %d) | invalid hole refs %d | "
          "holes without back-record %d | wires on plugged pins %d %s"
          % (hole_conn, n_hole_ends, len(bad_ref), len(missing), len(double),
             "OK" if ok else "FAIL"))
    for t, m_, c_ in double[:5]:
        print("   [!] %s ends on plugged pin (%s,%s)" % (t, m_, c_))
    if missing:
        print("   [!] holes missing back-record: %s" % ", ".join(missing[:8]))
    if not ok:
        for t, c in bad_ref[:5]:
            print("   [!] %s -> %r" % (t, c))
        raise SystemExit("round-trip check failed -> file is NOT usable")
    print("written: %s (%d links -> %d wire segments; %d holes used)"
          % (out, len(jumpers), sum(len(p) - 1 for _n, p, _a, _b, _k in jumpers), len(used)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
