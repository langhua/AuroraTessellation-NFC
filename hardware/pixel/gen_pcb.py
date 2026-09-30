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

# ★★ 所在面（**用户 2026-09-30 定** ✓，原话：「要，而且，J1/J2 也要在底层，正面只有线圈和 LED」）
#   ⇒ 正面（`copper1`）只留：线圈 `L1`（它的绕组本来就画在 copper1 ✓）＋ `LED2`（要看得见 ✓）
#   ⇒ 其余全部翻到**底层**（`copper0` + `bottom="true"` ✓）—— 好处：**绕组占了顶层** ✗，
#     而底层只有两个通孔盘（实测 ✓）⇒ 布线空间大得多 ✓
TOP_SIDE = ("L1", "LED2")
# 两个总线口的朝向（**用户 2026-09-30 点名要调** ✓）：焊盘朝**板内** ⇒ 线从板外插进来 ✓
#   · 件的局部 `+y` 方向是焊盘那侧 ✓ ⇒ 要把它转到：J1 朝 **+x**（左边那个口 ✓）
#     ⇒ `-sinθ = 1` ⇒ θ = **270°** ✓；J2 朝 **-x**（右边 ✓）⇒ θ = **90°** ✓
#   · 两个口这么转是**镜像**的 ✓ ⇒ 同一根排线直着插两边时，两口的 pin1 在同侧 ✓
EDGE_ROT = {"J1": 270, "J2": 90}
ROTS = (0, 90, 180, 270)       # 其余件的候选朝向 ✓（4 个直角方位 ✓）


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


def rot_about_canvas(th, w, h):
    """绕**画布中心**转 `th` 度的实例矩阵 ✓（2×3 ✓，与 `PB.tf_of` 同口径 ✓）

    ★★ 口径来源（**证据，不是猜** ✗）：Fritzing 自己给 `L1` 写的是
      `<transform m11="0" m12="1" m13="0" m21="-1" m22="0" m23="0" m31="85.0394"
       m32="0" m33="1"/>` ✓ —— 本函数取 `th=90°`、`w=h=85.0394`（= 24 mm 画布 ✓）
      算出来就是它 ✓✓（`e = w/2 − (a·w/2 + c·h/2) = 85.04` ✓、`f = 0` ✓）。
      ⇒ “件的实例矩阵 = 绕**画布中心**旋转” ✓（不是绕件原点 ✗）。
    """
    import math as _m
    a, b = _m.cos(_m.radians(th)), _m.sin(_m.radians(th))
    c, d = -b, a
    cx, cy = w / 2.0, h / 2.0
    return (a, b, c, d, cx - (a * cx + c * cy), cy - (b * cx + d * cy))


def variants(p):
    """件的 `(面, 角度) → {connectorN: 局部焊盘框}` ✓（4 × 2 种 ✓）

    ★★ 几何**一律走 `pcb_pads.part_pads`** ✓（把它摆在 `loc=(0,0)` ✓、给它候选的
      `M`/`pv` ✓）—— 不另写一份旋转/镜像运算 ✗（那样迟早两边不一致 ✗）。
      得到的框是**局部 sketch 单位** ✓ ⇒ 真正摆位时只需加 `loc` ✓（便宜 ✓）。
    """
    root = ET.fromstring(p["svg_text"])
    k, (ox, oy) = PB.svg_k(root)
    wmm, hmm = PB.canvas_mm(root.attrib)
    out = {}
    for bottom in (False, True):
        for th in ROTS:
            M = rot_about_canvas(th, wmm * SK, hmm * SK)
            pv = {"layer": "copper0" if bottom else "copper1"}
            if bottom:
                pv["bottom"] = "true"
            fake = dict(p, loc=(0.0, 0.0), M=M, pv=pv)
            got, _ex, _bad, _nt = PP.part_pads(fake)
            if got:
                out[(bottom, th)] = {cid: (q["absbox"][0], q["absbox"][1],
                                           q["absbox"][2], q["absbox"][3])
                                     for cid, q in got.items()}
    return out


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
        # 件自己的**铜箔**包围盒 ✓（环心要它 ✓，见 `cu_box` 注释 ✓）＋ **画布尺寸** ✓（写朝向要用 ✓）
        wmm = hmm = None
        try:
            root = ET.fromstring(p["svg_text"])
            k, (ox, oy) = PB.svg_k(root)
            wmm, hmm = PB.canvas_mm(root.attrib)
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
                        cubox=cb, ntrack=ntrack, raw=p, canvas=(wmm * SK, hmm * SK),
                        var=variants(p)))
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
    placed = {}                  # 已放好的件 ✓（`costs` 要用它判"别太近" ✓）

    def vbox(p, key):
        return union(p["var"][key].values())

    # ★ ①②（线圈 / 两个总线口）**必须放在 `costs`/`hpwl` 定义之后** ✗ ——
    #   它们要调这两个函数 ✓（第一版写在前面 ⇒ `UnboundLocalError` ✗）。
    #   现在它们在下面 `costs()` 之后 ✓。

    def abs_pads(p, loc, key):
        """该件在该 `(面,角度)` 变体下、摆在 `loc` 时的**绝对焊盘框** ✓"""
        vb = p["var"].get(key) or p["var"][(True, 0)]
        return {cid: (b[0] + loc[0], b[1] + loc[1], b[2] + loc[0], b[3] + loc[1])
                for cid, b in vb.items()}

    def abs_box(p, loc, key):
        return union(abs_pads(p, loc, key).values())

    def hpwl(title, loc, key):
        """该件落在这个 `(面,角度)` ＋ `loc` 时，它**参与的每个网**的半周长之和 ✓（mm ✓）"""
        tot = 0.0
        mine = abs_pads(by[title], loc, key)
        for _net, ks in net_flat.items():
            if not any(t == title for t, _c in ks):
                continue
            xs, ys = [], []
            for t2, c2 in ks:
                if t2 == title:
                    b = mine.get(c2)
                elif t2 in new:
                    b = abs_pads(by[t2], new[t2][0], (new[t2][1], new[t2][2])).get(c2)
                else:
                    b = None
                if b:
                    cx, cy = ctr(b)
                    xs.append(cx)
                    ys.append(cy)
            if len(xs) >= 2:
                tot += ((max(xs) - min(xs)) + (max(ys) - min(ys))) / SK
        return tot

    def costs(p, loc, key):
        """⇒ `(cost, 说明 ✓)`；硬约束不满足 ⇒ `(None, 原因 ✓)`"""
        b = abs_box(p, loc, key)
        for ab in abs_pads(p, loc, key).values():
            if (ab[0] < r[0] + EDGE or ab[1] < r[1] + EDGE
                    or ab[2] > r[2] - EDGE or ab[3] > r[3] - EDGE):
                return None, "出板边"
        for t, q in placed.items():
            qq = abs_pads(q, new[t][0], (new[t][1], new[t][2]))
            for ab in abs_pads(p, loc, key).values():
                for qb in qq.values():
                    if ovl(ab, qb, CL):
                        return None, "和 %s 太近" % t
        cc = ctr(b)
        d = math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK          # 到板心 mm ✓
        cost = max(0.0, d - 4.0) ** 2 * 3.0                     # φ8 外重罚 ✓
        cost += d * 0.35                                        # 轻微往中间收 ✓（对称 ✓）
        cost += hpwl(p["title"], loc, key) * W_NET              # 走线**尽量短** ✓（§6.1 ✓）
        return cost, ""

    # ① 线圈：**正面** ✓（用户定 ✓）、保留它自己那个 90° 朝向 ✓（= Fritzing 原来写的 transform ✓）、
    #   把**铜箔（绕组）包围盒**中心对到板心 ✓（★ 不是焊盘包围盒 ✗ —— 环心比焊盘中心偏
    #   ~6.4 mm ✓，用焊盘定心会把环顶出板外 ✗，用户就是这样看出来的 ✗）
    coil = by.get("L1")
    if coil:
        cb = coil.get("cubox") or coil["box"]
        new["L1"] = ((c[0] - ctr(cb)[0], c[1] - ctr(cb)[1]), False, 90)
        placed["L1"] = coil
        print("   线圈：**正面** ✓、朝 90° ✓（照它原本的 transform ✓）、铜箔中心对板心 ✓"
              "（焊盘包围盒中心相对环心差 (%.2f, %.2f) mm ✓）"
              % ((ctr(coil["box"])[0] - ctr(cb)[0]) / SK,
                 (ctr(coil["box"])[1] - ctr(cb)[1]) / SK))
    # ② 两个总线口：**底层** ✓、朝向固定 ✓（焊盘朝板内 ⇒ 线从板外插 ✓）、
    #   两只**共用同一个 y** ✓（对称 ✓），y 取使两口的 HPWL 之和最小者 ✓
    def edge_loc(p, key, side, y):
        """把该口的**焊盘包围盒**贴到板边内侧（`LEAD` ✓）⇒ 反推实例 `loc` ✓"""
        bb = vbox(p, key)
        cx = (r[0] + LEAD - bb[0]) if side == "L" else (r[2] - LEAD - bb[2])
        return (cx, y - ctr(bb)[1])
    edges = [(ttl, sd) for ttl, sd in (("J1", "L"), ("J2", "R")) if ttl in by]
    if edges:
        bestr = None
        nc = int(RMAX / GRID)
        for iy in range(-nc, nc + 1):
            y = c[1] + iy * GRID
            cost, ok = 0.0, True
            for ttl, sd in edges:
                p, key = by[ttl], (True, EDGE_ROT[ttl])
                loc = edge_loc(p, key, sd, y)
                cst, _why = costs(p, loc, key)
                if cst is None:
                    ok = False
                    break
                cost += cst + hpwl(ttl, loc, key) * W_NET
            if ok and (bestr is None or cost < bestr[0]):
                bestr = (cost, y)
        if bestr is None:
            print("   ✗ 两个总线口找不到位置 ⇒ 保持原位 ✗")
        for ttl, sd in edges:
            p, key = by[ttl], (True, EDGE_ROT[ttl])
            loc = edge_loc(p, key, sd, bestr[1] if bestr else c[1])
            new[ttl] = (loc, True, EDGE_ROT[ttl])
            placed[ttl] = p
            print("   · %-5s 底层 ✓ 朝 %3d° ⇒ 焊盘中心 (%.2f, %.2f) mm（到板心 %.2f mm ✓）"
                  % (ttl, EDGE_ROT[ttl], MM(ctr(vbox(p, key))[0] + loc[0] - r[0]),
                     MM(ctr(vbox(p, key))[1] + loc[1] - r[1]),
                     math.hypot(ctr(vbox(p, key))[0] + loc[0] - c[0],
                                ctr(vbox(p, key))[1] + loc[1] - c[1]) / SK))

    # ③ 其余件（**全部底层** ✓ 用户定 ✓）：从大到小贪心 ✓，**所在面与 4 个朝向一起搜** ✓
    todo = [t for t in by if t not in new]
    todo.sort(key=lambda t: -((vbox(by[t], (True, 0))[2] - vbox(by[t], (True, 0))[0])
                              * (vbox(by[t], (True, 0))[3] - vbox(by[t], (True, 0))[1])))
    for t in todo:
        p = by[t]
        best, bestc, bestkey, bestwhy = None, None, None, []
        nc = int(RMAX / GRID)
        keys = [(False, th) for th in ROTS] if t in TOP_SIDE else [(True, th) for th in ROTS]
        for key in keys:
            if key not in p["var"]:
                continue
            bb = vbox(p, key)
            for ix in range(-nc, nc + 1):
                for iy in range(-nc, nc + 1):
                    loc = (c[0] + ix * GRID - ctr(bb)[0], c[1] + iy * GRID - ctr(bb)[1])
                    cost, why = costs(p, loc, key)
                    if cost is None:
                        if why not in bestwhy:
                            bestwhy.append(why)
                        continue
                    if bestc is None or cost < bestc - 1e-9:
                        best, bestc, bestkey = loc, cost, key
        if best is None:
            print("   ✗ %s **找不到位置**（%s）⇒ 保持原位 ✗" % (t, "; ".join(bestwhy[:3])))
            new[t] = (p["loc"], p["bottom"], 0)
            placed[t] = p
            continue
        new[t] = (best, bestkey[0], bestkey[1])
        placed[t] = p
        if verbose:
            cc = ctr(abs_box(p, best, bestkey))
            print("   · %-5s %s ✓朝 %3d° 放到 (%.2f, %.2f) mm（到板心 %.2f mm）cost=%.2f"
                  % (t, "底层" if bestkey[0] else "正面", bestkey[1],
                     MM(cc[0] - r[0]), MM(cc[1] - r[1]),
                     math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK, bestc))
    return new, c


# ── 写回（**只动 pcbView** ✓）────────────────────────────────────────────────
def transform_block(block, newlocs, canvas):
    """只改这个实例 **pcbView** 里的件：位置 ✓＋**所在面** ✓＋**朝向** ✓

    ★ 为什么要"块内"改 ✗：同一个实例在**三个视图**里各有一份几何 ✓ ⇒ 拿全局正则改 x/y
      会把面包板/原理图一起改掉 ✗（那两张图是已交付的 ✓）。
    ★★ 旧版的错 ✗（本次一并修 ✓）：它用 `"<pcbView" + 旧开标签从第一个 > 起的尾巴`
      拼回去 ✗ ⇒ **把 `layer`/`bottom` 属性整个丢掉了** ✗（= 件的所在面被抹掉 ✗）。
      现在：开标签**显式重写** ✓（正面 `layer="copper1"` 且**无** `bottom` ✓；
      背面 `layer="copper0"` ＋ `bottom="true"` ✓ —— 照 bb104 里 Fritzing 自己的写法 ✓）。
    ★ 朝向：`θ ≠ 0` 才写 `<transform m11..m33/>` ✓（绕**画布中心** ✓，口径由 `L1` 自己那份
      transform 验过 ✓）；`θ = 0` 就把 transform **删掉** ✓（Fritzing 不转的件就是没有 ✓）。
    """
    ttl = re.search(r"<title>([^<]*)</title>", block)
    mid = re.search(r'moduleIdRef="([^"]+)"', block)
    if not ttl or not mid or ttl.group(1) not in newlocs:
        return block
    if mid.group(1).startswith(("Wire", "Via")):
        return block
    spec = newlocs[ttl.group(1)]
    loc, bot, th = spec if isinstance(spec, tuple) else (spec, False, 0)
    old = re.search(r"<pcbView\b[^>]*>(.*?)</pcbView>", block, re.S)
    if not old:
        return block
    # ★★ 开标签**必须拆成"属性串 + >"两步** ✗ —— 2026-09-30 实测踩到 ✓：
    #   把整个 `<pcbView layer="copper1">`（**带 `>`** ✗）交给 `set_attr` 追加属性 ⇒
    #   结果变成 `'<pcbView layer="copper1"> bottom="true"'` ✗ —— 属性掉到标签**外面** ✗
    #   ⇒ Fritzing 读不到 `bottom` ✗（`layer` 因为本来就有、走的是替换分支 ✓ 所以"看着像好的" ✗）
    #   ⇒ 症状：U1/D3/J1/J2 都写成了 `layer="copper0"` 却**没有 `bottom="true"`** ✗。
    m_open = re.search(r"<pcbView\b([^>]*)>", block)
    attrs2 = set_attr(m_open.group(1), "layer", "copper0" if bot else "copper1")
    attrs2 = (set_attr(attrs2, "bottom", "true") if bot
              else re.sub(r'\s*bottom="[^"]*"', "", attrs2))
    # ★★ 拼回去时**必须自己补一个空格** ✗ —— `set_attr` 末尾 `.strip()` 会把属性串开头的
    #   空格吃掉 ✓ ⇒ 直接 `"<pcbView" + attrs2` 会写成 `<pcbViewlayer="copper0"` ✗
    #   ⇒ **整个文件不再是合法 XML** ✗（Fritzing 打不开 ✗；我这边 `ET.fromstring` 当场报
    #   "not well-formed" ✓ 才没流出去 ✓）。
    new_open = "<pcbView " + attrs2.strip() + ">"
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
    nx, ny = loc[0], loc[1]
    ga = set_attr(set_attr(g.group(1), "x", PW.fmt(nx)), "y", PW.fmt(ny))
    inner, after = "", g.end()
    selfclosed = g.group(2) in ("/>", "/ >")
    if not selfclosed:                             # `<geometry …>…</geometry>` ⇒ 把里面的
        close = body.find("</geometry>", g.end())  #   `<transform/>` 拿掉（要不要写回去由 θ 定 ✓）
        if close < 0:
            return block                           # ★ 认不出 ⇒ **一个字不动** ✓（不瞎写 ✗）
        span = body[g.end():close]
        m2 = re.search(r"<transform\b[^>]*?/>", span)
        inner = (span[:m2.start()] + span[m2.end():]) if m2 else span
        after = close + len("</geometry>")
    tf = ""
    if th % 360:
        w, h = canvas.get(ttl.group(1), (0.0, 0.0))
        if not w or not h:
            print("   ⚠️ `%s` 画布尺寸读不出 ⇒ **不写朝向** ✗（宁可不动 ✓）" % ttl.group(1))
        else:
            a, b, c2, d, e, f = rot_about_canvas(th, w, h)
            tf = ('<transform m11="%s" m12="%s" m13="0" m21="%s" m22="%s" '
                  'm23="0" m31="%s" m32="%s" m33="1"/>'
                  % tuple(PW.fmt(v) for v in (a, b, c2, d, e, f)))
    if selfclosed:
        newgeo = "<geometry " + ga + ("/>" if not tf else ">" + tf + "</geometry>")
    else:
        newgeo = "<geometry " + ga + ">" + tf + inner + "</geometry>"
    body2 = body[:g.start()] + newgeo + body[after:]
    # 位号标签跟着挪 ✓（不挪的话字还留在老地方 ✗）
    tg = re.search(r"<titleGeometry\b([^>]*?)>", body2)
    if tg:
        ta = tg.group(1)
        tx = float(re.search(r'\bx="([-\d.eE+]+)"', ta).group(1)) + (nx - ox)
        ty = float(re.search(r'\by="([-\d.eE+]+)"', ta).group(1)) + (ny - oy)
        ta2 = set_attr(set_attr(ta, "x", PW.fmt(tx)), "y", PW.fmt(ty))
        body2 = body2[:tg.start()] + "<titleGeometry " + ta2 + ">" + body2[tg.end():]
    return block[:old.start()] + new_open + body2 + "</pcbView>" + block[old.end():]


def write_back(base, out, newlocs, canvas):
    """把新的 (loc, 面, 朝向) 写进各实例的 **pcbView** ✓；别的视图 / 别的文件**逐字节不动** ✓"""
    zin = zipfile.ZipFile(base)
    fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
    text = zin.read(fz).decode("utf-8")
    chunks, pos, n_moved = [], 0, 0
    for m in re.finditer(r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>", text):
        nb = transform_block(m.group(0), newlocs, canvas)
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
    n = write_back(base, out, new, {p["title"]: p["canvas"] for p in parts})
    print("   写回：挪了 %d 个实例的 pcbView ✓（面包板/原理图视图**未动** ✓）" % n)

    # 摆位报告 ✓
    print("\n== 摆位报告（相对板左上角 mm ✓）==")
    print("   %-5s %-6s %-5s %-16s %-10s %-9s %s"
          % ("位号", "所在面", "朝向", "焊盘中心", "到板心", "在 φ8 内", "备注"))
    tot_a = 0.0
    sx = sy = 0.0
    for p in sorted(parts, key=lambda q: q["title"]):
        loc, bot, th = new[p["title"]]
        pad_bb = union(p["var"][(bot, th)].values())   # 该 (面, 朝向) 的**局部焊盘**包围盒 ✓
        bb = pad_bb
        if p["title"] == "L1" and p.get("cubox"):
            # ★ 线圈的"到板心"要按**铜箔（环）**算 ✓ —— 按焊盘报会说"到板心 6.4 mm"✗
            #   （那是引线的偏移 ✓）；但**面积账仍旧用焊盘框** ✗（拿 19×20.2 的铜箔框进
            #   面积 ⇒ 报 422 mm² ✗，把 47.7 的账算爆了 ✗）
            bb = p["cubox"]
        cc = (ctr(bb)[0] + loc[0], ctr(bb)[1] + loc[1])
        d = math.hypot(cc[0] - c[0], cc[1] - c[1]) / SK
        a = (pad_bb[2] - pad_bb[0]) * (pad_bb[3] - pad_bb[1]) / (SK * SK)
        tot_a += a
        sx += MM(cc[0] - r[0]) * a
        sy += MM(cc[1] - r[1]) * a
        why = "✅ φ8 内" if d <= 4.0 else ("⚠️ 压绕组区（§6.1 允许但尽量避免 ✓）" if d <= 9.5 else "❌ 在绕组外")
        print("   %-5s %-6s %-5d %-16s %-10.2f %-9s %s"
              % (p["title"], "底层" if bot else "正面", th,
                 "%.2f, %.2f" % (MM(cc[0] - r[0]), MM(cc[1] - r[1])),
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
