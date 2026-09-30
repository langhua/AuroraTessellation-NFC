# -*- coding: utf-8 -*-
r"""像素板 **PCB 生成器**（P1 摆位 ✓；P2 布线随后 ✓）2026-09-30 立

规矩出处 ✓（都写进代码里，免得换个人就不知道凭啥 ✓）：
  · 板 = **25 × 25 mm** ✓（`README.md` §6 ✓；`<board width="2.5cm">` ✓ 实测 ✓）
  · ❌ **不铺大片铜 / 地平面**、⚠️ **尽量别压绕组**、✅ **优先塞进中心 φ8 孔** ✓（§6.1 ✓）
    ⇒ φ8 = 线圈内圈净空 ✓（φ8 面积 = π·4² = **50.3 mm²** ✓，与 §6 的"50 mm² / 面"对得上 ✓）
  · 元件金属**尽量对称** ✓、走线**尽量短** ✓（§6.1 ✓）
  · ★ 摆位**只动 `pcbView`** ✓ —— 面包板视图 / 原理图视图**一个字不动** ✗
    （同一个实例在三个视图各有一份几何 ✓，混着改就把已交付的两张图弄坏了 ✗）

★ 几何一律走 **库仓通用工具** ✓（`toolpaths` 指过去 ✓，项目里不留副本 ✗）：
  `pcb_pads`（焊盘 ✓）、`pcb_wire`（走线写法 ✓）、`part_box`（矩阵 ✓）。

用法：
  py -3.13 gen_pcb.py <基准.fzz> <输出.fzz> [--report]
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolpaths                                                  # noqa: E402,F401  （把库仓 tools/ 放进 sys.path ✓）
import part_box as PB                                             # noqa: E402
import pcb_pads as PP                                             # noqa: E402
import pcb_wire as PW                                             # noqa: E402
import projdata                                                   # noqa: E402

SK = PB.MM                     # 1 mm = 3.5433 sketch 单位 ✓
MM = lambda u: u / SK          # sketch 单位 → mm ✓
U = lambda m: m * SK           # mm → sketch 单位 ✓

PHI8_R = U(4.0)                # 中心净空圆半径 ✓（φ8 ✓）
CL = U(0.5)                    # 件与件之间的净空 ✓（布线要地方 ✓）
EDGE = U(0.3)                  # 焊盘离板边的最小距离 ✓
LEAD = U(0.8)                  # 连接器焊盘离板边的距离 ✓
GRID = U(0.25)                 # 搜索格 ✓（0.25 mm ✓）
RMAX = U(6.0)                  # 中心搜索半径 ✓
W_NET = 0.6                    # 走线长度在代价里的权重 ✓（系数可调 ✓）


# ── 小工具 ─────────────────────────────────────────────────────────────────
def union(boxes):
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def ctr(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def ovl(a, b, cl=0.0):
    """两矩形**净距 < cl** ⇒ True ✓"""
    return not (a[2] + cl <= b[0] or b[2] + cl <= a[0]
                or a[3] + cl <= b[1] or b[3] + cl <= a[1])


def cid_of(part, name):
    """`NETS` 里的脚名 → `connectorN` ✓（大小写不敏感 ✓）

    ★ `#N` = **第 N 个脚（1 起算 ✓）** ⇒ `#1` → `connector0` ✗（不是 `connector1` ✗ ——
      这一条把 `C1.#2` / `J1.#3` 全映射错了，摆位报告里当场报出来 ✓）。
      出处：`pixel_nets.py` 表头「`#N` = 第 N 个脚 ✓（core 件没有名字 ✓）」。
    """
    nm = (name or "").strip().lower()
    if nm.startswith("#"):
        try:
            cid = "connector%d" % (int(nm[1:]) - 1)
        except ValueError:
            return None
        return cid if cid in part["cids"] else None
    for cid, n in part["names"].items():
        if (n or "").strip().lower() == nm:
            return cid
    return None


def set_attr(attrs, key, val):
    if re.search(r'\b%s="[^"]*"' % key, attrs):
        return re.sub(r'\b%s="[^"]*"' % key, '%s="%s"' % (key, val), attrs, count=1)
    return (attrs + ' %s="%s"' % (key, val)).strip()


# ── 读基准 + 量每个件的"相对几何" ──────────────────────────────────────────
def cu_box(part, svg_root, k, ox, oy, vbw, flip):
    """件自己的**铜箔包围盒**（局部 sketch 单位 ✓，相对实例 loc ✓）

    ★★ 为什么要它 ✗（2026-09-30 用户一眼看出「元件偏离了 pcb 板」✗）：线圈这种件，
      **环心 ≠ 焊盘中心** ✗ —— 实测：环画在局部 (0,0) 附近，而两个焊盘在 (3.3,0)/(10.7,0) ✓
      ⇒ 拿**焊盘**包围盒去对板心 ✗，环就整整偏了 **~7 mm** ✗（Fritzing 导出的图上，
      环直接挂到板上边外面 ✗）。
      ⇒ 环心要按**铜箔**算 ✓：取**无 id** 的铜层图元（= 绕组线条 ✓；焊盘都带
      `connectorN*` 的 id ✓）的包围盒 ✓；一个无 id 的都没有 ⇒ 退回全部铜 ✓。
    """
    shapes, _bad = PP.copper_shapes(svg_root)
    cu = [s for s in shapes if s["layer"] in ("copper0", "copper1")]
    pick = [s for s in cu if not s["id"]] or cu
    if not pick:
        return None
    xs, ys = [], []
    for s in pick:
        for u in (s["box"][0], s["box"][2]):
            for v in (s["box"][1], s["box"][3]):
                x = (2.0 * ox + vbw - u) if flip else u
                p = PB.apply(part["M"], (x - ox) * k, (v - oy) * k)
                xs.append(p[0])
                ys.append(p[1])
    return (min(xs), min(ys), max(xs), max(ys))


def load(base):
    parts, board = PP.read_fzz(base)
    out = []
    for p in parts:
        mid = p.get("moduleId") or ""
        if mid == PP.BOARD_MID or mid.startswith("Breadboard") or mid.startswith("Via"):
            continue
        if p.get("fzp") is None:
            continue
        got, extra, bad, ntrack = PP.part_pads(p)
        if not got:
            continue
        # 件自己的**铜箔**包围盒 ✓（环心要它 ✓，见 `cu_box` 注释 ✓）
        try:
            root = ET.fromstring(p["svg_text"])
            k, (ox, oy) = PB.svg_k(root)
            vb = PB._nums(root.get("viewBox"))
            vbw = vb[2] if len(vb) == 4 and vb[2] else None
            flip = ((p.get("pv") or {}).get("bottom") or "").lower() == "true"
            if not (flip and vbw):
                flip = False
            cb = cu_box(p, root, k, ox, oy, vbw, flip) if k else None
        except Exception:                                     # noqa: BLE001
            cb = None
        loc = p["loc"]
        pads = {}
        for cid, q in got.items():
            pads[cid] = dict(box=tuple(v - (loc[0] if i % 2 == 0 else loc[1])
                                      for i, v in enumerate(q["absbox"])),
                             nm=q["nm"], layer=q["layer"], thr=bool(q["hole_mm"]))
        out.append(dict(title=p["title"], mid=mid, loc=loc, M=p["M"], pads=pads,
                        names={c: q["nm"] for c, q in pads.items()},
                        cids=set(pads), geo=p["geo"], side=(p.get("pv") or {}).get("layer"),
                        bottom=((p.get("pv") or {}).get("bottom") or "").lower() == "true",
                        box=union([q["box"] for q in pads.values()]),
                        cubox=cb, ntrack=ntrack))
    return out, board


def board_rect(parts_all, board):
    """板框（sketch 单位 ✓）：`<board>` 尺寸 ＋ PCB1 的 loc ✓"""
    if not board:
        return None
    w = float(re.sub(r"[a-z%]", "", board[0] or "0")) * {"cm": 10.0, "mm": 1.0}.get((board[0] or "")[-2:], 1.0)
    h = float(re.sub(r"[a-z%]", "", board[1] or "0")) * {"cm": 10.0, "mm": 1.0}.get((board[1] or "")[-2:], 1.0)
    loc = next((p["loc"] for p in parts_all
                if p.get("moduleId") == PP.BOARD_MID and "loc" in p), None)
    if not loc or not w or not h:
        return None
    return (loc[0], loc[1], loc[0] + U(w), loc[1] + U(h))


# ── 摆位 ───────────────────────────────────────────────────────────────────
def place(parts, r, nets_map, verbose=True):
    """⇒ `{位号: 新 loc ✓}`（sketch 单位 ✓；只平移 ✓、不动朝向 ✗）"""
    c = ctr(r)
    by = {p["title"]: p for p in parts}
    # 网表展开成 `net ⇒ [(位号, connectorN)]` ✓（HPWL 要用 ✓；脚名认不出的**当场报** ✗）
    net_flat = {}
    for net, lst in nets_map.items():
        ks = []
        for t, nm in lst:
            if t not in by:
                print("   ⚠️ 网 `%s` 里的 `%s.%s` 不在板上 ⇒ 忽略 ✓" % (net, t, nm))
                continue
            cid = cid_of(by[t], nm)
            if cid is None:
                print("   ⚠️ 网 `%s`：`%s` 的脚名 `%s` 对不上任何 connector ✗" % (net, t, nm))
                continue
            ks.append((t, cid))
        net_flat[net] = ks
    new = {}

    # ① 线圈：把它的**铜箔（绕组）包围盒**中心对到板心 ✓（★ 不是焊盘包围盒 ✗ ——
    #   环心比焊盘中心偏 ~7 mm ✓，用焊盘定心会把环顶出板外 ✗，用户就是这样看出来的 ✗）
    coil = by.get("L1")
    if coil:
        cb = coil.get("cubox") or coil["box"]
        new["L1"] = (c[0] - ctr(cb)[0], c[1] - ctr(cb)[1])
        print("   线圈定心：用**铜箔**包围盒 ✓（环心）；焊盘包围盒中心相对它差 (%.2f, %.2f) mm ✓"
              % (((ctr(coil["box"])[0] - ctr(cb)[0]) / SK),
                 ((ctr(coil["box"])[1] - ctr(cb)[1]) / SK)))
    # ② 两个总线口：左右各一个 ✓、**对称** ✓、焊盘贴着板边内侧 ✓（线从板外进来 ✓）
    for ttl, side in (("J1", "L"), ("J2", "R")):
        p = by.get(ttl)
        if not p:
            continue
        w = (p["box"][2] - p["box"][0]) / 2.0
        cx = (r[0] + LEAD + w) if side == "L" else (r[2] - LEAD - w)
        new[ttl] = (cx - ctr(p["box"])[0], c[1] - ctr(p["box"])[1])
    # ③ MCU：正中 ✓（φ8 最里 ✓、EPAD 朝下好接 GND ✓）
    if "U1" in by:
        p = by["U1"]
        new["U1"] = (c[0] - ctr(p["box"])[0], c[1] - ctr(p["box"])[1])

    placed = {t: p for t, p in by.items() if t in new}

    def abs_pads(p, loc):
        return {cid: (q["box"][0] + loc[0], q["box"][1] + loc[1],
                      q["box"][2] + loc[0], q["box"][3] + loc[1])
                for cid, q in p["pads"].items()}

    def abs_box(p, loc):
        return union(abs_pads(p, loc).values())

    def hpwl(title, loc):
        """该件落在 `loc` 时，它**参与的每个网**的半周长之和 ✓（mm ✓；伙伴取已放好的 ✓）"""
        tot = 0.0
        mine = abs_pads(by[title], loc)
        for _net, ks in net_flat.items():
            if not any(t == title for t, _c in ks):
                continue
            xs, ys = [], []
            for t2, c2 in ks:
                if t2 == title:
                    b = mine.get(c2)
                elif t2 in new:
                    b = abs_pads(by[t2], new[t2]).get(c2)
                else:
                    b = None
                if b:
                    cx, cy = ctr(b)
                    xs.append(cx)
                    ys.append(cy)
            if len(xs) >= 2:
                tot += ((max(xs) - min(xs)) + (max(ys) - min(ys))) / SK
        return tot

    def costs(p, loc):
        """⇒ `(cost, 说明 ✓)`；硬约束不满足 ⇒ `(None, 原因 ✓)`"""
        b = abs_box(p, loc)
        for ab in abs_pads(p, loc).values():
            if (ab[0] < r[0] + EDGE or ab[1] < r[1] + EDGE
                    or ab[2] > r[2] - EDGE or ab[3] > r[3] - EDGE):
                return None, "出板边"
        for t, q in placed.items():
            qq = abs_pads(q, new[t])
            for ab in abs_pads(p, loc).values():
                for qb in qq.values():
                    if ovl(ab, qb, CL):
                        return None, "和 %s 太近" % t
        cc = ctr(b)
        d = math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK          # 到板心 mm ✓
        cost = max(0.0, d - 4.0) ** 2 * 3.0                     # φ8 外重罚 ✓
        cost += d * 0.35                                        # 轻微往中间收 ✓（对称 ✓）
        cost += hpwl(p["title"], loc) * W_NET                   # 走线**尽量短** ✓（§6.1 ✓）
        return cost, ""

    # ④ 其余 SMD：从大到小贪心 ✓（小的去填缝 ✓）
    todo = [t for t in by if t not in new]
    todo.sort(key=lambda t: -(by[t]["box"][2] - by[t]["box"][0])
              * (by[t]["box"][3] - by[t]["box"][1]))
    for t in todo:
        p = by[t]
        best, bestc, bestwhy = None, None, []
        nc = int(RMAX / GRID)
        for ix in range(-nc, nc + 1):
            for iy in range(-nc, nc + 1):
                loc = (c[0] + ix * GRID - ctr(p["box"])[0], c[1] + iy * GRID - ctr(p["box"])[1])
                cost, why = costs(p, loc)
                if cost is None:
                    if why not in bestwhy:
                        bestwhy.append(why)
                    continue
                if bestc is None or cost < bestc - 1e-9:
                    best, bestc = loc, cost
        if best is None:
            print("   ✗ %s **找不到位置**（%s）⇒ 保持原位 ✗" % (t, "; ".join(bestwhy[:3])))
            new[t] = p["loc"]
            placed[t] = p
            continue
        new[t] = best
        placed[t] = p
        if verbose:
            cc = ctr(abs_box(p, best))
            print("   · %-5s 放到 (%.2f, %.2f) mm（到板心 %.2f mm）cost=%.2f"
                  % (t, MM(cc[0] - r[0]), MM(cc[1] - r[1]),
                     math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK, bestc))
    return new, c


# ── 写回（**只动 pcbView** ✓）────────────────────────────────────────────────
def transform_block(block, newlocs):
    """只改这个实例 **pcbView** 里的件位置 ✓ ⇒ 新 block（不改就原样返回 ✓）

    ★ 为什么要"块内"改 ✗：同一个实例在**三个视图**里各有一份几何 ✓ ⇒ 拿全局正则改 x/y
      会把面包板/原理图一起改掉 ✗（那两张图是已交付的 ✓）。
    """
    ttl = re.search(r"<title>([^<]*)</title>", block)
    mid = re.search(r'moduleIdRef="([^"]+)"', block)
    if not ttl or not mid or ttl.group(1) not in newlocs:
        return block
    if mid.group(1).startswith(("Wire", "Via")):
        return block
    old = re.search(r"<pcbView\b[^>]*>(.*?)</pcbView>", block, re.S)
    if not old:
        return block
    body = old.group(1)
    g = None
    for cand in re.finditer(r"<geometry\b([^>]*?)(/?>)", body):
        if "z=" in cand.group(1):
            g = cand
            break
    if g is None:
        return block
    ox = float(re.search(r'\bx="([-\d.eE+]+)"', g.group(1)).group(1))
    oy = float(re.search(r'\by="([-\d.eE+]+)"', g.group(1)).group(1))
    nx, ny = newlocs[ttl.group(1)]
    ga = set_attr(set_attr(g.group(1), "x", PW.fmt(nx)), "y", PW.fmt(ny))
    body2 = body[:g.start()] + "<geometry " + ga + g.group(2) + body[g.end():]
    # 位号标签跟着挪 ✓（不挪的话字还留在老地方 ✗）
    tg = re.search(r"<titleGeometry\b([^>]*?)>", body2)
    if tg:
        ta = tg.group(1)
        tx = float(re.search(r'\bx="([-\d.eE+]+)"', ta).group(1)) + (nx - ox)
        ty = float(re.search(r'\by="([-\d.eE+]+)"', ta).group(1)) + (ny - oy)
        ta2 = set_attr(set_attr(ta, "x", PW.fmt(tx)), "y", PW.fmt(ty))
        body2 = body2[:tg.start()] + "<titleGeometry " + ta2 + ">" + body2[tg.end():]
    return block[:old.start()] + "<pcbView" + old.group(0)[old.group(0).index(">"):] \
        .replace(body, body2, 1) + block[old.end():]


def write_back(base, out, newlocs):
    """把新的 loc 写进各实例的 **pcbView** ✓；别的视图 / 别的文件**逐字节不动** ✓"""
    zin = zipfile.ZipFile(base)
    fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
    text = zin.read(fz).decode("utf-8")
    chunks, pos, n_moved = [], 0, 0
    for m in re.finditer(r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>", text):
        nb = transform_block(m.group(0), newlocs)
        if nb != m.group(0):
            n_moved += 1
        chunks.append(text[pos:m.start()])
        chunks.append(nb)
        pos = m.end()
    chunks.append(text[pos:])
    text2 = "".join(chunks)
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for it in zin.infolist():
        data = text2.encode("utf-8") if it.filename == fz else zin.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    return n_moved


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    base, out = argv[0], argv[1]
    netsf, rest = projdata.strip_argv(argv)
    nets = projdata.load(netsf, need=("NETS",)).NETS
    parts, board = load(base)
    r = board_rect(PP.read_fzz(base)[0], board)
    print("== 摆位：%s ⇒ %s ==" % (os.path.basename(base), os.path.basename(out)))
    print("   板框 = (%.2f,%.2f)-(%.2f,%.2f) mm（%.2f × %.2f mm ✓）"
          % (MM(r[0]), MM(r[1]), MM(r[2]), MM(r[3]), MM(r[2] - r[0]), MM(r[3] - r[1])))
    print("   件的**朝向/所在面**照原样保留 ✓（本版只平移 ✓）：")
    for p in sorted(parts, key=lambda q: q["title"]):
        print("      %-5s layer=%-8s bottom=%-5s 焊盘 %2d 个"
              % (p["title"], p["side"], p["bottom"], len(p["pads"])))
    by = {p["title"]: p for p in parts}
    print("   放置 ✓")
    new, c = place(parts, r, nets)
    n = write_back(base, out, new)
    print("   写回：挪了 %d 个实例的 pcbView ✓（面包板/原理图视图**未动** ✓）" % n)

    # 摆位报告 ✓
    print("\n== 摆位报告（相对板左上角 mm ✓）==")
    print("   %-5s %-16s %-16s %-10s %-9s %s" % ("位号", "焊盘中心", "件中心", "到板心", "在 φ8 内", "备注"))
    tot_a = 0.0
    sx = sy = 0.0
    for p in sorted(parts, key=lambda q: q["title"]):
        loc = new[p["title"]]
        cc = ctr(union([(v["box"][0] + loc[0], v["box"][1] + loc[1],
                        v["box"][2] + loc[0], v["box"][3] + loc[1])
                       for v in p["pads"].values()]))
        d = math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK
        a = (p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1]) / (SK * SK)
        tot_a += a
        sx += MM(cc[0] - r[0]) * a
        sy += MM(cc[1] - r[1]) * a
        why = "✅ φ8 内" if d <= 4.0 else ("⚠️ 压绕组区（§6.1 允许但尽量避免 ✓）" if d <= 9.5 else "❌ 在绕组外")
        print("   %-5s %-16s %-16s %-10.2f %-9s %s"
              % (p["title"], "%.2f, %.2f" % (MM(cc[0] - r[0]), MM(cc[1] - r[1])),
                 "%.2f, %.2f" % (MM(ctr(p["box"])[0] + loc[0] - r[0]),
                                 MM(ctr(p["box"])[1] + loc[1] - r[1])),
                 d, "✓" if d <= 4.0 else "✗", why))
    print("   元件面积合计 ≈ %.1f mm²（φ8 净空 = %.1f mm² ✓）" % (tot_a, math.pi * 16))
    print("   金属**重心** = (%.2f, %.2f) mm ⇒ 偏离板心 (%.2f, %.2f) mm %s"
          % (sx / tot_a, sy / tot_a, sx / tot_a - MM(r[2] - r[0]) / 2,
             sy / tot_a - MM(r[3] - r[1]) / 2,
             "✓ 对称" if abs(sx / tot_a - MM(r[2] - r[0]) / 2) < 1.0
             and abs(sy / tot_a - MM(r[3] - r[1]) / 2) < 1.0 else "✗ 有点偏"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
