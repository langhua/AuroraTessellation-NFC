# -*- coding: utf-8 -*-
r"""pcb_rats_probe：照 **Fritzing 状态栏的口径**量「PCB 视图里还剩几条连接没布」✓（只读 ✓）

用法 ✓：`py -X utf8 tools\pcb_rats_probe.py <a.fzz> [<b.fzz> …] [--nets=pixel_nets.py]`
退出码 ✓：0 = **0 条**未布连接 ✓（＝ Fritzing 会说「布线完成」，**而且这话是真的** ✓）；1 = 还有 ✗。

## 为什么要有这第二把尺子 ✗（2026-10-10 用户报的件 ✓）

用户 ✓：「PCB **已经不需要再布线了**，可 Fritzing 仍说**两根线没布好**」✗
—— 而本项目三套闸门**全过** ✓（`pcb_check` ①②…⑫ ✓、`net_group_check` ✓、面包板探针 ✓）。
根因 ✗：闸门量的是「**几何铜**」✗，而 Fritzing 状态栏量的是「**它眼里的网表** ＋ 铜」✓
⇒ **同一个文件、两把尺子** ✓（网表那半年份由 `tools\net_group_check.py` 管 ✓，这里管"还剩几条" ✓）。

## 口径（**逐条照源码** ✓，出处可核 ✓）

| 事 | 出处 |
|---|---|
| 状态栏那句 `%1 of %2 nets routed - %n connector(s) still to be routed` | `mainwindow/mainwindow.cpp:2298` ✓ |
| 计数 = `GraphUtils::scoreOneNet(...)` | `sketch/sketchwidget.cpp:7013` ✓ ＋ `utils/graphutils.cpp:447` ✓ |
| ★「还剩几个」= **该网连通片数 − 1**（**不是**没连上的脚数 ✗） | `scoreOneNet` 末尾 `check[]` ✓（本项目 2026-10-02 读出来的 ✓） |
| 分网 = `ConnectorItem::collectEqualPotential` ＝ **本视图**的 `<connect>` ✓ ＋ 同脚跨层 ✓ ＋ 零件内部 **bus** ✓ | `connectors/connectoritem.cpp:1340` ✓ |
| `<connect>` 目标**只在本视图**里找 | `items/itembase.cpp:559` ✓（`connector->connectorItem(m_viewID)` ✓） |
| 判「接没接上」= **几何命中**（点落在对方真形状里 ✓），✗ 不信文件里的 `<connect>` ✗ | `connectors/connectoritem.cpp:1972` ✓ |
| 一张网要有**两支不同零件、≥2 只脚**才进 `m_netCount` | `sketch/sketchwidget.cpp:7013` ✓ |

★ 「铜块」这一层**不自己再写一遍** ✗ —— 用库仓 `pcb_check.py` ⑤ 那份**已复核过**的实现 ✓
（`check(...) ⇒ (probs, notes, groups)` ✓，`groups` = `铜块 → 该块里的焊盘` ✓；连"弧的线身"
那种坑它都处理过 ✓）⇒ 本探针只补**它没有的那半**：**逐视图的网表** ✓。

## 实测标尺 ✓（本探针在这块板上与**用户读到的**状态栏逐条对上 ✓）

| 文件 | 用户读到的 Fritzing | 本探针 |
|---|---|---|
| `pixel-pcb-v59.fzz` | 「**7 中的 5** 网络布线完成，**2** 个连接件仍然需要布线」✗ | M=7 ✓、K=**2** ✓ |
| `_work/v76.4_byHand.fzz`（v81 的底 ✓） | 「**7 中的 5** …，**2** 个接插件仍然需要布线」✓（已截图核对 ✓） | M=7 ✓、K=**2** ✓ |
| `pixel-pcb-v68.fzz` | **三视图都正确** ✓（用户 2026-10-05 读的 ✓） | M=9 ✓、K=**0** ✓ |
| `pixel-pcb-v81.fzz` | 「… **2 个连接仍然需要布线**」✗（2026-10-10 ✓） | M=7 ✓、K=**2** ✓ |
"""
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                            # noqa: E402
import pcb_wire as PW                                       # noqa: E402
import pcb_check as PC                                      # noqa: E402
import projdata                                             # noqa: E402

VIEWS = ("breadboardView", "schematicView", "pcbView")
MY_TRACE = 4                                                # PCBTraceFlag
INST_RE = re.compile(r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>")


class UF(object):
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def load_insts(text):
    """⇒ 实例表：标题 / mi / `path` / 逐视图的连接器 ＋ 声明 ＋ `wireFlags` ✓"""
    out = []
    for m in INST_RE.finditer(text):
        blk = m.group(0)
        t = re.search(r"<title>([^<]*)</title>", blk)
        mi = re.search(r'modelIndex="([^"]+)"', blk)
        md = re.search(r'moduleIdRef="([^"]+)"', blk)
        pth = re.search(r'\bpath="([^"]*)"', blk)
        if not (t and mi):
            continue
        views = {}
        for vm in re.finditer(r"(?s)<(\w+View)\b[^>]*>(.*?)</\1>", blk):
            vl = re.search(r'wireFlags="(\d+)"', vm.group(2))
            conns = {}
            for cm in re.finditer(r'(?s)<connector\s+connectorId="([^"]+)"\s+'
                                  r'layer="([^"]*)"\s*>(.*?)</connector>', vm.group(2)):
                conns[cm.group(1)] = [
                    (x.group(1), x.group(2)) for x in re.finditer(
                        r'<connect\s+connectorId="([\w]+)"\s+modelIndex="([^"]+)"', cm.group(3))]
            views[vm.group(1)] = dict(conns=conns,
                                      flags=int(vl.group(1)) if vl else None)
        out.append(dict(title=t.group(1), mi=mi.group(1),
                        mod=(md.group(1) if md else ""),
                        path=(pth.group(1) if pth else None), views=views))
    return out


def bus_map(inst):
    """面包板的孔 ⇒ 内部 bus 代表 ✓（读件自己的 `.fzp` ✓，不猜 ✗）"""
    holes = set()
    for v in VIEWS:
        holes |= set(inst["views"].get(v, {}).get("conns", {}))
    if not (inst and inst.get("path")):
        return {}
    try:
        root = ET.parse(inst["path"].replace("/", os.sep)).getroot()
    except (OSError, ET.ParseError):
        return {}
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for b in root.iter("bus"):
        mem = []
        for d in b.iter():
            for k, v in d.attrib.items():
                if k in ("id", "connectorId", "connector", "member") and v in holes:
                    mem.append(v)
        for x in mem[1:]:
            ra, rb = find(mem[0]), find(x)
            if ra != rb:
                par[rb] = ra
    return {h: find(h) for h in holes}


def check(path, nets_path=None):
    """⇒ `(probs, notes, info)` ✓（`net_group_check.py` 也用这一份 ✓）"""
    text, inner = PW.read(path)
    insts = load_insts(text)
    by_mi = {i["mi"]: i for i in insts}
    title_mi = {}
    for i in insts:
        title_mi.setdefault(i["title"], i["mi"])
    model = PC.collect(path)
    pads, traces, vias = model["pads"], model["traces"], model["vias"]
    pad_of = {(q["mi"], q["cid"]): q for q in pads}
    bb = next((i for i in insts if "readboard" in (i["mod"] or "")), None)
    buses = bus_map(bb) if bb else {}
    holes = sorted(bb["views"].get("pcbView", {}).get("conns", {})) if bb else []
    EXPECT = projdata.load(nets_path, need=("EXPECT",)).EXPECT if nets_path else None
    net_of_pad = {}
    for net in (EXPECT or {}):
        for s in EXPECT[net]:
            if isinstance(s, str) and "." in s:
                net_of_pad[s] = net

    # ── ① 铜块（**用库仓那份已复核的实现** ✓）：`groups = 块根 → 焊盘集` ✓
    _p, _n, groups = PC.check(model, EXPECT)
    piece_of = {}
    for root, ps in groups.items():
        for ttl, cid in ps:
            piece_of[(ttl, cid)] = root

    # ── ② Fritzing 的"分网"：声明（**只在本视图里解析** ✓）＋ 面包板内部 bus ＋ 铜块 ✓
    def nd_pad(mi, cid):
        return ("pad", mi, cid)

    def nd_wire(mi):
        return ("wire", mi)

    def nd_via(mi):
        return ("via", mi)

    def nd_hole(cid):
        return ("hole", bb["mi"], cid)

    def nm(k):
        if k[0] == "pad":
            return "%s.%s" % (k[1], k[2])
        if k[0] == "wire":
            return "Wire%s" % k[1]
        if k[0] == "via":
            return "Via%s" % k[1]
        return "孔%s" % k[2]

    name_of = {}
    for q in pads:
        name_of[nd_pad(q["mi"], q["cid"])] = "%s.%s" % (q["title"], q["cid"])

    u = UF()
    for q in pads:
        u.find(nd_pad(q["mi"], q["cid"]))
    for t in traces:
        u.find(nd_wire(t["inst"]))
    for v in vias:
        u.find(nd_via(v["inst"]))
    for cid in holes:
        u.find(nd_hole(cid))
    # 铜块 ⇒ 同一块的焊盘并起来 ✓
    for root, ps in groups.items():
        ks = [nd_pad(title_mi.get(t, t), c) for t, c in sorted(ps)]
        for k in ks[1:]:
            u.union(ks[0], k)

    flag_bad = []
    for t in traces:
        v = by_mi.get(t["inst"], {}).get("views", {}).get("pcbView") or {}
        if not (v.get("flags") is not None and (v["flags"] & MY_TRACE)):
            flag_bad.append(t["inst"])

    glue = []                                    # 跨视图 glue 的**证据** ✓
    dec = 0
    for i in insts:
        v = i["views"].get("pcbView")
        if v is None:
            continue
        for cid, ds in v["conns"].items():
            wire = i["mod"].startswith("Wire")
            src = (nd_via(i["mi"]) if i["mod"].startswith("Via")
                   else nd_wire(i["mi"]) if wire else
                   nd_pad(i["mi"], cid) if (i["mi"], cid) in pad_of else
                   nd_hole(cid) if "readboard" in (i["mod"] or "") else None)
            if src is None:
                continue
            for tcid, tmi in ds:
                j = by_mi.get(tmi)
                if j is None or "pcbView" not in j["views"]:
                    continue
                if tcid not in j["views"]["pcbView"]["conns"]:
                    continue                          # ★ 目标只在本视图里找 ✓
                dst = (nd_via(tmi) if j["mod"].startswith("Via")
                       else nd_wire(tmi) if j["mod"].startswith("Wire")
                       else nd_pad(tmi, tcid) if (tmi, tcid) in pad_of else
                       nd_hole(tcid) if "readboard" in (j["mod"] or "") else None)
                if dst is None:
                    continue
                dec += 1
                u.union(src, dst)
    bus_e = 0
    grp = {}
    for cid in holes:
        if buses.get(cid):
            grp.setdefault(buses[cid], []).append(cid)
    for v in grp.values():
        for cid in v[1:]:
            u.union(nd_hole(v[0]), nd_hole(cid))
            bus_e += 1

    # 孔被"两只不同网的脚"共用 ⇒ 直接的 glue 证据 ✓
    per_hole = collections.defaultdict(set)
    for i in insts:
        v = i["views"].get("pcbView")
        if v is None or "readboard" in (i["mod"] or ""):
            continue
        for cid, ds in v["conns"].items():
            for tcid, tmi in ds:
                if tmi == bb["mi"]:
                    per_hole[tcid].add("%s.%s" % (i["title"], cid))
    for cid, ws in sorted(per_hole.items()):
        ns = {net_of_pad.get(w) for w in ws} - {None}
        if len(ns) > 1:
            glue.append(("孔 %s" % cid, sorted(ws)))
    # ★ 只有"**有脚挂上去**的多孔 bus"才算证据 ✗（改完记录之后，空 bus 无害 ✓，别吓人 ✓）
    for v in grp.values():
        used = [c for c in v if c in per_hole]
        if len(used) > 1:
            glue.append(("bus %s" % v[0], ["%s（%s）" % (c, "、".join(sorted(per_hole[c])))
                                           for c in sorted(used)]))

    # ── ③ 账 ──────────────────────────────────────────────────────────────
    comps = collections.defaultdict(list)
    for q in pads:
        comps[u.find(nd_pad(q["mi"], q["cid"]))].append(q)
    for v in vias:                                   # 过孔也要并进它所在的块 ✓
        comps[u.find(nd_via(v["inst"]))]
    probs, notes = [], []
    info = dict(name=os.path.basename(path), inner=inner, M=0, K=0, nets=[],
                pads=len(pads), traces=len(traces), vias=len(vias), holes=len(holes),
                glue=glue, dec=dec, bus=bus_e)
    nets = []
    for _r, ps in comps.items():
        # ★「一张网」= 有**两支不同零件**、且 ≥2 只**焊盘/过孔**的组 ✓
        #   （`sketchwidget.cpp:7013` ✓；★ 面包板的**孔不算"脚"** ✗ —— 实测算上孔 ⇒ M 变 22 ✗，
        #    而用户在 v59/v76/v81 上读到的都是 **7** ✓）
        if len(ps) < 2 or len({q["title"] for q in ps}) < 2:
            continue
        nets.append(ps)
    nets.sort(key=lambda z: -len(z))
    # D：`EXPECT` 的脚必须在 PCB 视图里有连接器项 ✓
    for s in sorted(net_of_pad):
        ttl, cid = s.split(".", 1)
        mi = title_mi.get(ttl)
        i = by_mi.get(mi) if mi else None
        if i is None or "pcbView" not in i["views"] \
                or cid not in i["views"]["pcbView"]["conns"]:
            probs.append("D 网 `%s` 的 `%s` 在 **PCB 视图里没有连接器项** ✗ ⇒ Fritzing 眼里"
                         "这张网变小了 ⇒ 状态栏会谎报「完成」✗" % (net_of_pad[s], s))
    pieces_seen = 0
    for ps in nets:
        pcs = collections.defaultdict(list)
        for q in ps:
            root = piece_of.get((q["title"], q["cid"]))
            pcs[root].append("%s.%s" % (q["title"], q["cid"]))
        names = sorted({net_of_pad.get("%s.%s" % (q["title"], q["cid"]))
                        for q in ps} - {None})
        n_pads = (len(EXPECT[names[0]]) if EXPECT and len(names) == 1 else len(ps))
        K = len(pcs) - 1
        info["M"] += 1
        info["K"] += K
        pieces_seen += len(pcs)
        info["nets"].append(dict(names=names, pads=len(ps), pieces=len(pcs), K=K,
                                 extra=n_pads - len([q for q in ps
                                                     if "%s.%s" % (q["title"], q["cid"])
                                                     in net_of_pad]),
                                 detail=[sorted(v) for v in pcs.values()]))
        if len(names) > 1:                       # B ✗ 并网 = 短接 ✗
            probs.append("B 网 %s **在 PCB 视图里被并成了一张** ✗（= 短接 ✗）⇒ Fritzing 会按"
                         "「一张网」数 ⇒ 状态栏跟着错 ✗"
                         % "、".join("`%s`" % n for n in names))
        if K:
            probs.append("A 网 %s 在 PCB 视图里碎成 **%d 块** ✗ ⇒ 还差 **%d** 条没布 ✗"
                         % ("、".join("`%s`" % n for n in names) or "（无名）", len(pcs), K))
    # C：`EXPECT` 里每张网都得在 PCB 视图成型 ✓
    for net in sorted(EXPECT or {}):
        want = {s for s in EXPECT[net] if isinstance(s, str) and "." in s}
        got = set()
        for ps in nets:
            for q in ps:
                s = "%s.%s" % (q["title"], q["cid"])
                if s in want:
                    got.add(s)
        if not got:
            probs.append("C 网 `%s` 在 PCB 视图里**一个焊盘都没成型** ✗ ⇒ Fritzing 当它不存在 ✗"
                         % net)
        elif len(got) < 2:
            probs.append("C 网 `%s` 在 PCB 视图里只有 %d 个焊盘 ✗（= 单脚网 ⇒ 被丢掉 ✗）"
                         % (net, len(got)))
    for ms in flag_bad:
        probs.append("⚠ 走线 `%s` 的 `wireFlags & 4` = 0 ✗ ⇒ Fritzing **不算它是布线** ✗" % ms)
    notes.append("PCB 视图：焊盘 %d ✓／走线 %d ✓／过孔 %d ✓／面包板孔 %d ✓｜本视图声明边 %d ✓、"
                 "bus 边 %d ✓｜铜块 %d 个 ✓｜跨视图 glue 证据 %d 条 %s"
                 % (len(pads), len(traces), len(vias), len(holes), dec, bus_e,
                    len(groups), len(glue), "✗" if glue else "✓"))
    return probs, notes, info


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opt = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if not args:
        print(__doc__)
        return 2
    nets_path = opt.get("nets", os.path.join(PIX, "pixel_nets.py"))
    bad = 0
    for path in args:
        probs, notes, info = check(path, nets_path)
        print("== %s（包内 %s）==" % (info["name"], info["inner"]))
        for n in notes:
            print("   · %s" % n)
        for what, who in info["glue"]:
            print("   ⚠ 跨视图 glue ✗：%s 把 %s 牵在一起" % (what, "、".join(who)))
        print("   ⇒ **M（Fritzing 会算成几张网）= %d** ✓｜**K（还剩几条没布）= %d** ✓"
              % (info["M"], info["K"]))
        for r in info["nets"]:
            print("     %s `%s` 焊盘 %d ⇒ **%d 块**%s"
                  % ("✓" if not r["K"] else "✗", "/".join(r["names"]) or "（不在网表里）",
                     r["pads"], r["pieces"],
                     "" if not r["K"] else "：%s" % " ｜ ".join("＋".join(v)
                                                                for v in r["detail"])))
        for p in probs:
            print("   ✗ %s" % p)
        print("   ⇒ 判定：%s" % ("✓ 0 条未布连接 ✓（Fritzing 会说「布线完成」，这话是真的 ✓）"
                                 if not probs else "✗ %d 处 ✗" % len(probs)))
        bad += len(probs)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
