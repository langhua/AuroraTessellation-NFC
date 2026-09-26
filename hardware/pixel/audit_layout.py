# -*- coding: utf-8 -*-
"""面包板布局**合法性检查器**（独立实现 ✓，不调生成器的任何代码 ✗）

用法: py -3.13 audit_layout.py <a.fzz> [<b.fzz> ...]

检查 6 条硬约束（2026-09-26 用户定的次序与原则 ✓）：
  ① 一个孔最多一个导线端点 ✓（且导线端点不得落在插了脚的孔上 ✗）
  ② 引线不得盖住"已接线的孔" > 30% ✓（孔开口 vs 导线带 ✓，正反两向都查 ✓）
  ③ 两根引线不得重叠（共线叠在一起 ✗）
  ④ **用到的孔（元件脚 + 导线端点）不得落在「别的元件」的本体框内** ✓
    （框 = `part_box.body_box`（画布尺寸×内容包围盒）+ `place`（实例矩阵）✓
      与生成器**同一份实现** ✓ —— 所以 ④ 是**共用实现**、非独立 ✓（旧版只是一行占位 ✗）
      框边也算压住 ✓（孔心在框内即算 ✓）；离最近边 ≤1 单位时标为
      **贴着框边 ⚠ 需人判断**（不替人下结论 ✗ —— 用户 2026-09-27 的手工版里就有这种写法 ✓）；
      拿不到框的元件**会报出来** ✓，不静默 ✗）
  ⑤ 一条 bus（5 孔/50 孔铜片 ✓）上不得挂两个不同网络的脚 ✗（会实物短接 ✓）
  ⑥ 每个网络的脚必须由"孔+引线+bus"连通 ✓

验收方式（硬 ✓）：必须能复现已知答案 —— v12 = ①..③⑥ 全过、② 0 处 ✓；v19 ② 1 处 ✓；v8 ② 2 处 ✓
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

PIX = os.path.dirname(os.path.abspath(__file__))                 # ★ 自定位 ✓（不写死机器路径 ✗）
import toolpaths                                                 # noqa: E402
# ★ 通用工具（`bb_compare` / `part_box`）**只在库仓 tools/ 一份** ✓（本项目不留副本 ✗）
import bb_compare as BC                                          # noqa: E402
import part_box as PB                                            # noqa: E402  ④ 的本体框
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


def body_rects(fzz):
    """每个**非面包板**元件实例的本体框（sketch 绝对坐标 ✓）⇒ [(标题, (x0,y0,x1,y1))]

    框的算法与生成器**同一份** ✓（`part_box.body_box` + `place` ✓）。
    拿不到 svg / 量不出框的元件 ⇒ 归到第三个返回值里 **报出来** ✓（不静默跳过 ✗）。
    """
    out, missed = [], []
    for e in sketch_root(fzz).iter("instance"):
        ttl = (e.findtext("title") or "").strip()
        mid = e.get("moduleIdRef") or ""
        if mid.startswith("Wire") or ttl.startswith("TXT") or "readboard" in mid:
            continue
        vw = child(e, "views")
        sub = child(vw, "breadboardView") if vw is not None else None
        if sub is None:
            continue
        fzp = (e.get("path") or "").replace("/", os.sep)
        if not os.path.isfile(fzp):
            missed.append("%s（fzp 不在磁盘 ✓ %s）" % (ttl, fzp))
            continue
        img = None
        lay = ET.parse(fzp).getroot().find(".//breadboardView/layers")
        if lay is not None:
            img = lay.get("image")
        svg = PB.resolve_svg(fzp, img)
        if not svg:
            missed.append("%s（找不到 svg ✗ image=%s）" % (ttl, img))
            continue
        box = PB.body_box(svg)
        if box is None:
            missed.append("%s（`body_box` 量不出框 ✗ %s）" % (ttl, os.path.basename(svg)))
            continue
        g = child(sub, "geometry")
        if g is None:
            missed.append("%s（没有 <geometry> ✗）" % ttl)
            continue
        loc = (float(g.get("x") or 0), float(g.get("y") or 0))
        out.append((ttl, PB.place(loc, PB.tf_of(g), box)))
    return out, missed


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

    # ④ **用到的孔不得落在别的元件的本体框内** ✓（用户 2026-09-27 报：
    #    `Wire90012903` 接在 `pin32E`(288,108) ✓，而它在 LED2 本体框 277.6..298.4 × 79.6..109.4 内 ✗
    #    ⇒ 物理上插不进去 ✓；旧版这里只是一行占位字符串 ✗ ⇒ **从来没查过** ✓）
    v4 = []
    rects, missed = body_rects(path)
    for hid, who in sorted(ends.items()):
        hp = BC.hole_xy(hid)
        if hp is None:
            continue
        owners = {w.split(":", 1)[1].split(".")[0] for w in who if w.startswith("脚:")}
        for ttl, r in rects:
            if ttl in owners:
                continue                       # 自己的脚当然在自己板子底下 ✓
            if not (r[0] - 1e-6 <= hp[0] <= r[2] + 1e-6
                    and r[1] - 1e-6 <= hp[1] <= r[3] + 1e-6):
                continue
            # ★ 分两档**如实**报 ✓（2026-09-27 ✓）：用户手工的两版里都有"孔心正好压在框边"的写法 ✓
            #   ⇒ 该不该算违规**由用户定** ✗ ⇒ 工具只分档，不替人下结论 ✗。
            m = min(hp[0] - r[0], r[2] - hp[0], hp[1] - r[1], r[3] - hp[1])
            v4.append("%s（%s）在 %s 的本体框内 —— %s（框 %g,%g..%g,%g ✓ 孔 (%g,%g) ✓ 离最近边 %.2f 单位 ✓）"
                      % (hid, "、".join(who), ttl,
                         "**深在框内 ⇒ 物理插不进** ✗" if m > 1.0
                         else "**贴着框边 ⚠ 需人判断**",
                         r[0], r[1], r[2], r[3], hp[0], hp[1], m))
    for m in missed[:6]:
        v4.append("⚠ 量不到框 ⇒ **未验证** ✗：%s" % m)
    bad["④ 孔在本体下"] = v4

    # ⑤ 一条 bus 两个网（★★ 2026-09-27 扩到**整条 bus** ✓ —— 原来只比"同一个孔" ✗，
    #    §5b-5② 的"实物短接"（同一块 5 孔/50 孔铜片上挂两个网 ✓）根本查不出来 ✗）
    #    ★ 用的孔→网映射来自 `net_terminals()` ✓（与 ⑥ 连通检查**同一份** ✓，不另写 ✗）。
    v5 = []
    net_of_hole = {}
    for net, terms in net_terminals(path).items():
        for t in terms:
            if re.match(r"^pin\d+[A-Za-z]$", t):
                net_of_hole.setdefault(t, set()).add(net)
    for i, bus in enumerate(board_buses(path), 1):
        got = {}
        for hid in bus:
            for net in net_of_hole.get(hid, ()):
                got.setdefault(net, []).append(hid)
        if len(got) > 1:
            v5.append("bus#%d %s 上挂着 %s ⇒ **实物短接** ✗"
                      % (i, ",".join(bus),
                         " / ".join("%s@%s" % (n, ",".join(h)) for n, h in sorted(got.items()))))
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
    return sum(len(v) for k, v in bad.items())


def main(paths):
    rc = 0
    for p in paths:
        rc += check(p)
    print("\n合计违规 %d 处" % rc)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
