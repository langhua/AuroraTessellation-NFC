# -*- coding: utf-8 -*-
r"""取消两处「过孔对换层」：`Via43/44` 与 `Via45/46`（用户 2026-11-10 定 ✓）

用法：py -3.13 hardware\patch_drop_via_hops.py <in.fzz> <out.fzz>

★ 为什么现在可以 ✗（2026-11-10 ✓）：这四颗孔当初存在的**唯一原因**是——
  那条 5V 在 **y = 30.572** 从 `R2/R3/D4` 两排焊盘之间横穿 ✓，而 `COIL_A` 的两条竖直段
  （x = 45.126 / 42.126）在 copper0 上会**撞上它** ✗ ⇒ 布线器把它们**换到 copper1 跨过去** ✓。
  5V 已于 v109 改绕板子下边（y = 32.450 ✓）⇒ 障碍没了 ✓ ⇒ 两段换层可以直接落回 copper0 ✓。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"f:\git\fritzing-parts-langhua\tools")
sys.path.insert(0, os.path.dirname(HERE))
import pcb_pads as PP                                            # noqa: E402
if "path" not in PP.PADLIKE:
    PP.PADLIKE = tuple(PP.PADLIKE) + ("path",)
import pcb_check as PC                                           # noqa: E402
import gen_routes as GR                                          # noqa: E402

SK = 25.4 / 90.0
HOPS = [((45.126, 29.872), (45.126, 31.272)),
        ((42.126, 29.872), (42.126, 31.272))]


def near(p, q, tol=0.01):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def block_of(text, mi):
    m = re.search(r'(?ms)^[ \t]*<instance\b[^>]*modelIndex="%s".*?\n[ \t]*</instance>'
                  % re.escape(mi), text)
    return m.group(0) if m else None


def main(argv):
    src, dst = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    names = z.namelist()
    data = {n: z.read(n) for n in names}
    key = [n for n in names if n.endswith(".fz")][0]
    text = data[key].decode("utf-8")

    m = PC.collect(src)
    tr, vias = m["traces"], m["vias"]

    del_vias = []
    for (pa, pb) in HOPS:
        A = (pa[0] / SK, pa[1] / SK)
        B = (pb[0] / SK, pb[1] / SK)
        hop = [t for t in tr if t["layer"] == "copper1" and t.get("inst")
               and ((near(t["a"], A) and near(t["b"], B)) or
                    (near(t["a"], B) and near(t["b"], A)))]
        if len(hop) != 1:
            print("✗ 找不到 (%s)→(%s) 的 copper1 换层段（找到 %d）✗" % (pa, pb, len(hop)))
            return 1
        hop = hop[0]
        print("\n· 换层段 %s（%.3f,%.3f）→（%.3f,%.3f）"
              % (hop["inst"], pa[0], pa[1], pb[0], pb[1]))
        repl = {}
        for k, p in ((0, hop["a"]), (1, hop["b"])):
            v = [x for x in vias if near(x["p"], p)]
            if len(v) != 1:
                print("  ✗ 端点 (%.3f,%.3f) 上找不到唯一的过孔（%d）✗"
                      % (p[0] * SK, p[1] * SK, len(v)))
                return 1
            v = v[0]
            if v["inst"] not in del_vias:
                del_vias.append(v["inst"])
            nb = None
            for t2 in tr:
                if t2 is hop or t2["layer"] != "copper0" or not t2.get("inst"):
                    continue
                # ★ `ends` 的**键**才是这根线**自己的** connector 编号 ✓（值是它指向的目标 ✗）
                for k2, lst in (t2.get("ends") or {}).items():
                    for (_cid2, mi2, _l2) in lst:
                        if mi2 == v["inst"]:
                            nb = ("connector%d" % k2, t2["inst"])
            if nb is None:
                print("  ✗ 过孔 %s 上找不到另一根 copper0 线 ✗" % v["inst"])
                return 1
            repl[k] = (nb, v["inst"])
            print("  · 端%d：过孔 %s ⇄ 邻居 %s.%s" % (k, v["inst"], nb[1], nb[0]))

        blk = block_of(text, hop["inst"])
        pv = re.search(r"(?ms)<pcbView\b[^>]*>.*?</pcbView>", blk).group(0)
        seg = pv.replace("copper1trace", "copper0trace")
        # ★★ 必须按**本端 connector 段落**改 ✗ —— `<connect>` 上的 `connectorId` 是**目标**侧的编号 ✓，
        #   按它去正则匹配会改错行 ✗（第一版就踩了 ✓，判据 ⑩ 报"差 1.197 mm"）
        for k in (0, 1):
            (cid_nb, mi_nb), _vmi = repl[k]
            cs = re.search(r'(?ms)(<connector connectorId="connector%d"[^>]*>)(.*?)(</connector>)' % k,
                           seg)
            if not cs:
                print("  ✗ 换层段 %s 里没有 connector%d 段 ✗" % (hop["inst"], k))
                return 1
            inner = cs.group(2)
            inner2 = re.sub(r'(?m)^([ \t]*)<connect\b[^>]*?/>',
                            r'\g<1><connect connectorId="%s" modelIndex="%s" layer="copper0trace"/>'
                            % (cid_nb, mi_nb), inner, count=1)
            seg = seg[:cs.start(2)] + inner2 + seg[cs.end(2):]
        blk2 = blk.replace(pv, seg, 1)
        text = text.replace(blk, blk2, 1)

        for k in (0, 1):
            ((cid_nb, mi_nb), vmi) = repl[k]
            nblk = block_of(text, mi_nb)
            if nblk is None:
                print("  ✗ 找不到邻居块 %s ✗" % mi_nb)
                return 1
            npv = re.search(r"(?ms)<pcbView\b[^>]*>.*?</pcbView>", nblk)
            cr = re.search(r'(?ms)<connector connectorId="%s"[^>]*>(.*?)</connector>'
                           % re.escape(cid_nb), npv.group(0))
            if not cr:
                print("  ✗ 邻居 %s 的 pcbView 里没有 %s ✗" % (mi_nb, cid_nb))
                return 1
            inner = cr.group(1)
            old = re.search(r'(?m)^([ \t]*)<connect\b[^>]*?modelIndex="%s"[^>]*?/>'
                            % re.escape(vmi), inner)
            if not old:
                print("  ✗ 邻居 %s 里没有指向 %s 的声明 ✗" % (mi_nb, vmi))
                return 1
            new = '%s<connect connectorId="connector%d" modelIndex="%s" layer="copper0trace"/>' \
                  % (old.group(1), k, hop["inst"])
            inner2 = inner[:old.start()] + new + inner[old.end():]
            nblk2 = nblk.replace(npv.group(0), npv.group(0).replace(inner, inner2, 1), 1)
            text = text.replace(nblk, nblk2, 1)

    for mi in del_vias:
        blk = block_of(text, mi)
        if blk and "ViaModuleID" in blk:
            text = text.replace(blk, "", 1)
    print("\n  ✓ 删掉过孔 %d 颗：%s" % (len(del_vias), "、".join(del_vias)))

    text, n_rm, n_odd = GR.prune_dangling(text)
    print("  ✓ 清掉悬空声明 %d 条（异常 %d）" % (n_rm, n_odd))

    d2 = dict(data)
    d2[key] = text.encode("utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as w:
        for nm in names:
            w.writestr(nm, d2[nm])
    print("✓ 写出 %s" % dst)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
