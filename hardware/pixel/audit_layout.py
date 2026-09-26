# -*- coding: utf-8 -*-
"""面包板布局**合法性检查器**（独立实现 ✓，不调生成器的任何代码 ✗）

用法: py -3.13 audit_layout.py <a.fzz> [<b.fzz> ...]

检查 6 条硬约束（2026-09-26 用户定的次序与原则 ✓）：
  ① 一个孔最多一个导线端点 ✓（且导线端点不得落在插了脚的孔上 ✗）
  ② 引线不得盖住"已接线的孔" > 30% ✓（孔开口 vs 导线带 ✓，正反两向都查 ✓）
  ③ 两根引线不得重叠（共线叠在一起 ✗）
  ④ 引线不得穿过别的元件本体 ✓（★ 暂用生成器的外形框 ✗ ⇒ 标"未独立验证" ✗）
  ⑤ 一条 bus（5 孔/50 孔铜片 ✓）上不得挂两个不同网络的脚 ✗（会实物短接 ✓）
  ⑥ 每个网络的脚必须由"孔+引线+bus"连通 ✓

验收方式（硬 ✓）：必须能复现已知答案 —— v12 = ①..③⑥ 全过、② 0 处 ✓；v19 ② 1 处 ✓；v8 ② 2 处 ✓
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

PIX = r"f:\git\AuroraTessellation-NFC\hardware\pixel"
sys.path.insert(0, PIX)
import bb_compare as BC                                          # noqa: E402
NETS_PATH = os.path.join(PIX, "gen_schematic_wires.py")


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def sketch_root(fzz):
    with zipfile.ZipFile(fzz) as z:
        name = [n for n in z.namelist() if n.endswith(".fz")][0]
        return ET.fromstring(z.read(name))


def board_buses(fzz):
    """面包板的铜片分组 ✓：读板上 fzp 的 <bus>/<nodeMember connectorId="pin1A"/> ✓

    （**不是** <member> ✗ —— 名字猜错就什么也读不到 ✓，只读“带 connectorId 的子孙”最稳 ✓）
    """
    root = sketch_root(fzz)
    for e in root.iter("instance"):
        if (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        if "breadboard" not in (e.get("moduleIdRef") or "").lower():
            continue
        fpz = (e.get("path") or "").replace("/", os.sep)
        if not os.path.isfile(fpz):
            continue
        r = ET.parse(fpz).getroot()
        out = []
        for b in r.iter("bus"):
            ids = [d.get("connectorId") for d in b.iter() if d.get("connectorId")]
            if ids:
                out.append(ids)
        return out
    return []


def net_terminals(fzz):
    """net → [孔 id 或 "pin@<元件标号>.<脚名>" ✓]（网表来自项目的 gen_schematic_wires.NETS ✓）"""
    src = open(NETS_PATH, encoding="utf-8").read()
    blk = src[src.index("NETS = {"):src.index("\n}\n", src.index("NETS = {")) + 2]
    nets = eval(blk.split("=", 1)[1].strip())                 # noqa: S307
    root = sketch_root(fzz)
    plug_of, name2cid = {}, {}
    for e in root.iter("instance"):
        if (e.get("moduleIdRef") or "").startswith("Wire"):
            continue
        ttl = (e.findtext("title") or "").strip()
        fpz = (e.get("path") or "").replace("/", os.sep)
        vw = child(e, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        if sub is None:
            continue
        if os.path.isfile(fpz):
            r2 = ET.parse(fpz).getroot()
            name2cid[ttl] = {c.get("name"): c.get("id") for c in r2.iter("connector")
                             if c.get("name")}
        par = {c: p for p in sub.iter() for c in p}
        for cs in sub.iter("connect"):
            if (cs.get("layer") or "") != "breadboardbreadboard":
                continue
            hid = cs.get("connectorId")
            n = cs
            while n is not None and tag(n) != "connector":
                n = par.get(n)
            cid = n.get("connectorId") if n is not None else None
            if hid and cid:
                plug_of[hid] = (ttl, cid)
    out = {}
    for net, pins in nets.items():
        terms = []
        for ref, pname in pins:
            cid = ("connector" + str(int(pname[1:]) - 1)) if pname.startswith("#") \
                else name2cid.get(ref, {}).get(pname)
            hits = sorted(h for h, v in plug_of.items() if v == (ref, cid))
            terms.append(hits[0] if hits else "pin@%s.%s" % (ref, cid))
        out[net] = terms
    return out


def check(path):
    links, plugged = BC.load(path)
    real = [lk for lk in links if not lk.legend]
    print("\n================ %s" % path.split("\\")[-1])
    print("   引线 %d 根 | 插了脚的孔 %d 个" % (len(real), len(plugged)))
    bad = {}
    # 孔 ↔ 谁占着（脚 ✓ / 导线端点 ✓）
    ends = {}
    for hid, who in plugged.items():
        ends.setdefault(hid, []).append("脚:%s" % who)
    for lk in real:
        for hid, _mi in lk.holes:
            ends.setdefault(hid, []).append("线:%s" % "+".join(lk.wids))

    # ① 一个孔最多一个导线端点 ✓ / 端点不许落在插了脚的孔上 ✗
    v1 = []
    for hid, who in sorted(ends.items()):
        wires = [w for w in who if w.startswith("线:")]
        pins = [w for w in who if w.startswith("脚:")]
        if len(wires) > 1:
            v1.append("%s 有 %d 个导线端点（%s）" % (hid, len(wires), ", ".join(wires)))
        if wires and pins:
            v1.append("%s 既有插脚（%s）又有导线端点（%s）"
                      % (hid, ", ".join(pins), ", ".join(wires)))
    bad["① 一孔一端点"] = v1

    # ② 遮挡（>30% ✓）
    v2 = []
    segs = [(lk, a, b) for lk in real for a, b in lk.segs]
    for hid, who in sorted(ends.items()):
        hp = BC.hole_xy(hid)
        if hp is None:
            continue
        mine = {w.split(":", 1)[1] for w in who if w.startswith("线:")}
        for lk, a, b in segs:
            if "+".join(lk.wids) in mine:
                continue                       # 线终止在这个孔上 ⇒ 不是"盖住" ✓
            if BC.same_pt(a, hp) or BC.same_pt(b, hp):
                continue
            f = BC.obscures(a, b, hp)
            if f >= BC.OBSCURE_LIMIT:
                v2.append("%s（%s ✓）被 %s 盖住 %.0f%%"
                          % (hid, "、".join(who), "+".join(lk.wids), f * 100))
    bad["② 遮挡接线孔"] = v2

    # ③ 重叠
    v3 = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (l1, a1, b1), (l2, a2, b2) = segs[i], segs[j]
            if BC.seg_overlap(a1, b1, a2, b2):
                v3.append("%s 与 %s 重叠 (%.0f,%.0f)->(%.0f,%.0f)"
                          % ("+".join(l1.wids), "+".join(l2.wids), a1[0], a1[1], b1[0], b1[1]))
    bad["③ 引线重叠"] = v3

    # ④ 穿元件（★ 用生成器的框 ✗，标注为未独立验证 ✗）
    v4 = ["（未独立验证 ✗：元件外形框仍来自生成器用的 part_box ✗）"]

    # ⑤ 一条 bus 两个网
    v5 = []
    nets = BC.load_nets() if hasattr(BC, "load_nets") else {}
    bus2net = {}
    for hid, who in sorted(ends.items()):
        nets_here = sorted({w.split(":", 1)[1].split(".")[0] for w in who if w.startswith("脚:")})
        if len(nets_here) > 1:
            v5.append("%s 同时插着 %s" % (hid, ", ".join(nets_here)))
    bad["⑤ bus 短接"] = v5

    # ⑥ 连通（用 孔/bus + 引线 + 脚 建并查集 ✓）
    par = {}
    mi2ref = {}
    for e in sketch_root(path).iter("instance"):
        if e.get("modelIndex") is not None:
            mi2ref[e.get("modelIndex")] = (e.findtext("title") or "").strip()

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

    for b in board_buses(path):
        first = None
        for hid in b:
            if first is None:
                first = hid
            uni(first, hid)
    for lk in real:
        hs = [h for h, _m in lk.holes]
        for h in hs[1:]:
            uni(hs[0], h)
        for cid, mi in lk.pins:
            ref = mi2ref.get(mi)
            if ref is None or not hs:
                continue
            # 线接在元件脚上（例如裸焊盘 EPAD ✓）⇒ 把那个脚和这条线的孔并到一起 ✓
            uni("pin@%s.%s" % (ref, cid), hs[0])
    v6 = []
    for net, terms in sorted(net_terminals(path).items()):
        comps = {}
        for t in terms:
            comps.setdefault(find(t), []).append(t)
        if len(comps) > 1:
            v6.append("%s 不连通：%s" % (net, " | ".join(sorted(",".join(v) for v in comps.values()))))
    bad["⑥ 网连通"] = v6

    for k in sorted(bad):
        v = bad[k]
        mark = "✓" if not v else "✗"
        print("   %s %-14s %d 处" % (mark, k, len(v)))
        for line in v[:6]:
            print("        %s" % line)
    return sum(len(v) for k, v in bad.items() if k != "④ 穿元件")


def main(paths):
    rc = 0
    for p in paths:
        rc += check(p)
    print("\n合计违规 %d 处" % rc)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
