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
EDGE = U(0.3)                  # 焊盘/本体离板边的最小距离 ✓
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
# ★★ 四个角的摆位规格（用户 2026-09-30 定 ✓）：
#    "两个对角是 J1/J2，另两个是安装孔" ✓；对角由我定 ✓（用户"你来定" ✓）
#    ⇒ **J1 左上 ↔ J2 右下** ✓、安装孔在**右上 / 左下** ✓（对角交错 ✓）。
# ★ 安装孔用 **Fritzing 核心库的 `HoleModuleID`** ✓（用户 2026-09-30 定 ✓），
#   写法**逐字照** `hardware/pixel/holes_pads.fzz` 里 Fritzing 自己写出来的那份 ✓
#   （**零猜测** ✓）：`path="…/core/hole.fzp"` + `<property name="hole size" value="2.2mm,0.0mm"/>` ✓
#   + 三视图裸 `<geometry>` ✓ + **没有任何 connector** ✓。
#   ★ 用户另定 ✓：孔**只在 PCB 视图显示** ✓（原理图/面包板里不要它 ✗）。
CORNER = {"J1": "TL", "J2": "BR"}          # 总线口：各占一个角 ✓（互为对角 ✓）
CORNER_ROT = {"J1": 0}        # ★ J1 的朝向**按用户手工摆定的**钉住 ✓（2026-09-30 v9b/v9d ✓：
                              #   用户在 Fritzing 里把 J1 摆成 **0°** ✓（不是摆位器挑的 180° ✗）
                              #   ⇒ 尊重手工结果 ✓；J2 留给摆位器按"焊盘朝内"自己挑 ✓。
HOLE_CORNER = {"H1": "TR", "H2": "BL"}     # 安装孔：占另两个角 ✓
# ★★ 规范数字（`pcb-placement-rules.md` §2 ✓；用户 2026-09-30 认可 ✓）：
HOLE_MM = 3.0              # 孔心离两条板边的距离 ✓（IPC-2221C：≥3.0 ✓；v6 给 2.0 ⇒ 不合格 ✗）
HOLE_KEEP_MM = 4.0         # 孔周**免铜免件**环 Ø ✓（M2 螺钉头 + 免铜 0.3 ✓）= 用户最初说的"盘 Ø4.0" ✓
COIL_CLR_MM = 0.3          # 件/孔 离**绕组铜箔**的净空 ✓（§6.1「尽量别压绕组」＋用户指正 ✓）
K_COIL = 400.0             # 压绕组的软代价系数 ✓（= 侵入 1 mm 罚 400 ⇒ 远远够重 ✓；
                           #   用户选 (a) ✓：允许压 ✓ 但尽量不压 ✓；系数可调 ✓）
COPPER_EDGE_MM = 0.3       # 免铜到板边 ✓（≥ 0.25 ✓）
# ★ 孔件的**环心偏移** = `图上环心 − <geometry>` ✓（实测得到 ✓；**必须按板校准** ✗）：
#   ！大板上量到的是 (−46.50, −21.11) mm ✗ ⇒ 用到 25 mm 板会把孔推到板外 ✗（v6 实测 ✗）
#   ⇒ 默认 (0,0)＝"geometry 即孔心" ✓；校准：拿**这块板**的一张导出 svg ✓ 量出环心 ✓
#     传到 `--hole-off-mm "dx,dy"` ✓（两边用**同一个定义** ✓：drawn = geometry + off ✓）。
HOLE_OFF_MM = (0.0, 0.0)
# ★★ 底层件**局部框**的经验修正量 —— **已作废 = (0, 0)** ✗（2026-09-30 撤 ✓）
#   历史（存档，别再用 ✗）：曾取 (0.479, 0.821) mm，出处是"用户把 J1 中间焊盘对准板左上角"
#     那次手工对准 ✓；当时它"能对上"✓，但**原因是错的** ✗ ——
#     它其实是在替 `cu_box`/`ink_box` 把"件当前朝向的 `M`"也乘进去那个 bug 打补丁 ✗
#     （= 件自家框被**转了两遍** ✗，同一个病的第三处 ✓）。
#   撤掉它的**判据**（不是感觉 ✓）：基准系统一后，实测**模型预测**与**文件里的真值**差得
#     正好是这一对数 ✓ —— J1 焊盘中心 预测 (2.97, 4.05) vs 文件 (3.45, 4.87) ⇒ 差 (0.48, 0.82) ✓
#     ⇒ 现在模型不带任何补丁就**与文件对上** ✓（对照工具：`_work/margins.py` ✓ 只读 ✓）。
BOT_FIX_MM = (0.0, 0.0)
HOLE_SIZE = "2.2mm,0.0mm"                      # ★ 照核心件的原值 ✓（内径 2.2 ✓ / 外径 0 ✓ = 无铜盘 ✓）
ROTS = (0, 90, 180, 270)       # 其余件的候选朝向 ✓（4 个直角方位 ✓）

# ★★ 件自家框的**基准系** ✓（2026-09-30 立 ✓）：
#   “件在这个草图上的占位” = `loc + 框` ✓ ⇒ 框必须是**局部 sketch 单位** ✓（与 `loc` 同一系 ✓）。
#   而朝向 θ 的旋转 = **绕画布中心** ✓（`rot_about_canvas` ✓）、背面件再**水平镜像** ✓ ——
#   这两件事**只做一次** ✓：要么由 `variants()`/`body_local()` 做 ✓（本文件的写法 ✓），
#   ✗ 千万别把实例**当前的那个** `M` 再乘进去 ✗（那就等于转了两遍 ✗，实测 J2 因此
#     把丝印挂到板外 **0.87 mm** ✗）。
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# ★★ **钉在板心**的件（用户 2026-09-30 定 ✓，原话：
#    「**LED2 应在正中央，从正面看，它是中心，这是这个 pcb 设计的硬性要求**」✓）。
#    ⇒ 不只是"尽量靠中心"的软代价 ✓ —— 它的落点**只有一个**（焊盘框中心 = 板心 ✓），
#      摆位器**不许**再为了缩短走线把它挪开 ✗（HPWL 只能去选**朝向** ✓）。
#    物理意义：LED 就是这颗"像素"的灯 ✓ ⇒ 阵列拼起来才是**等距灯点阵** ✓；
#      线圈环心也已在板心 ✓（上面 ① ✓）⇒ 灯与环**同心** ✓。
PIN_CENTER = ("LED2",)


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
    """`NETS` 里的脚名 → `connectorN` ✓ —— **转调库仓那份唯一实现** ✓

    （口径与坑的说明在 `pcb_pads.cid_of` ✓；本文件里原来自己写了一份 ✗ ⇒ 已收抗 ✓）
    """
    return PP.cid_of(part["names"], part["cids"], name)


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
    ★ 用 `IDENT` 算 ✓（基准系 ✓ —— 见上面 `IDENT` 的注释 ✓）：本函数只管“**件自己长什么样**” ✓，
      转到哪个朝向/哪一面是 `body_local()` 的事 ✓。
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
                p = PB.apply(IDENT, (x - ox) * k, (v - oy) * k)
                xs.append(p[0])
                ys.append(p[1])
    return (min(xs), min(ys), max(xs), max(ys))

def ink_box(part, svg_root, k, ox, oy, vbw, flip):
    """件**画出来的一切**（铜 + 丝印 + 文字 ✓）的包围盒（局部 sketch 单位 ✓，相对 loc ✓）

    ★★ 2026-09-30 补 ✗（发现 `pcb_pads.absbox` 那个镜像 bug 的同一轮 ✓）：
      **板边、避让、贴角都该用"真占地"** ✓ —— 而 `cubox`（铜箔框）对**连接器**是错的 ✗：
      `SH-1.0-3P-V` 的 pcb 图只有 **3 个带 `connectorN` 的信号焊盘** ✗，
      两头的**固定焊盘**与**本体丝印**都没 id ✗ ⇒ 铜箔框只有 **2.5 × 1.2 mm** ✗，
      而件真正占的是 **4.35 × 5.33 mm** ✓（差 ~3 mm ✗）。
      ⇒ 实测（v19）：按铜箔框贴角 ⇒ **J1 丝印出左边 0.64 mm ✗、J2 出下边 0.87 mm ✗**
        —— 用户看到的就是"J2 挂在板外"✗（同一个病、第二次 ✓）。
    ★ 与 `margins.py` 的墨迹框、`part_box.shape_bbox` **同一份实现** ✓（不另写一份 ✗）。
    ★ 用 `IDENT` 算 ✓（基准系 ✓ —— 同 `cu_box` ✓）。
    """
    c = PB.shape_bbox(svg_root)
    if c is None:
        return None
    xs, ys = [], []
    for u in (c[0], c[2]):
        for v in (c[1], c[3]):
            x = (2.0 * ox + vbw - u) if flip else u
            q = PB.apply(IDENT, (x - ox) * k, (v - oy) * k)
            xs.append(q[0])
            ys.append(q[1])
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
        # 件自己的**铜箔**包围盒 ✓（环心要它 ✓，见 `cu_box` 注释 ✓）＋ **画出来的一切** ✓（板边/避让要它 ✓）
        # ★★ 两个框都必须在**同一个基准系**里算 ✗（2026-09-30 修 ✗，同一个病的第三处 ✓）：
        #   件自家框 = **不转、不镜像**的那一系 ✓（= `variants()` 用的 `rot_about_canvas(0)` = 单位阵 ✓）；
        #   朝向 θ 的旋转与背面件的镜像，交给 `body_local()` 做**一次** ✓。
        #   ✗ 旧写法把实例**当前的** `M` 也乘进去 ⇒ 已经转过一次的框又被 `body_local()`
        #     转一次 = **转两遍** ✗（J2 是 90° ⇒ 变 180° ✗ ⇒ 框整体偏 ✗）。
        #   实测（v20）：J2 丝印仍出下边 **0.87 mm** ✗ —— 就是这个双重旋转 ✗。
        wmm = hmm = None
        cb = ib = None
        try:
            root = ET.fromstring(p["svg_text"])
            k, (ox, oy) = PB.svg_k(root)
            wmm, hmm = PB.canvas_mm(root.attrib)
            vb = PB._nums(root.get("viewBox"))
            vbw = vb[2] if len(vb) == 4 and vb[2] else None
            cb = cu_box(p, root, k, ox, oy, vbw, False) if k else None
            ib = ink_box(p, root, k, ox, oy, vbw, False) if k else None
        except Exception:                                     # noqa: BLE001
            cb = ib = None
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
                        cubox=cb, inkbox=ib, ntrack=ntrack, raw=p,
                        canvas=(wmm * SK, hmm * SK),
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
    holes = {}                   # ②a 里填 ✓（`costs` 的 Ø4.0 硬环要用 ✓ ⇒ 必须先于 `costs` 定义 ✓）
    coil_r_out = None            # 绕组的**外半径**（sketch 单位 ✓）⇒ "不许压绕组"的硬约束 ✓
    coil_side = None             # 绕组在哪一面/层 ✓（`copper0`/`copper1` ✓）⇒ "同面=短路"必需 ✓
    coil_abs = None              # 绕组铜箔的**绝对框** ✓（只用于报告/调试 ✓）

    def rot_box_canvas(box, th, cw, ch):
        """局部框 ⇒ "**绕画布中心**转 θ°"后的轴对齐包围框 ✓（四角算，精确 ✓）

        ★ 与 Fritzing 的 `transform` 同一口径 ✓（转轴 = **画布中心** ✗ 不是本位中心 ✗）。
        ★★ 本函数与 `ppcb_pads.part_pads` 是**同一件事的第二份实现** ✗ —— 允许存在 ✓，
           但**结论由 `audit_placement.py` 从文件上独立量** ✓（不许拿它自证 ✓）。
        """
        a = math.radians(int(round(th)) % 360)
        ca, sa = math.cos(a), math.sin(a)
        xs, ys = [], []
        for px in (box[0], box[2]):
            for py in (box[1], box[3]):
                dx, dy = px - cw / 2.0, py - ch / 2.0
                xs.append(cw / 2.0 + ca * dx - sa * dy)
                ys.append(ch / 2.0 + sa * dx + ca * dy)
        return (min(xs), min(ys), max(xs), max(ys))

    def abs_body(p, loc, key):
        """该件的**本体/铜箔框**（绝对 ✓）；没量到 ⇒ None ✓（那就只卡焊盘 ✓、并会报 ✗）"""
        bb = body_local(p, key)
        if bb is None:
            return None
        return (bb[0] + loc[0], bb[1] + loc[1], bb[2] + loc[0], bb[3] + loc[1])

    def pad_local(p, key):
        """该件在该 `(面,角度)` 下的**焊盘框**（局部 ✓、已含底层修正 ✓）

        ★★ 与 `abs_pads` **同一份几何** ✓ —— ✗ 直接用 `vbox()`（未修正 ✗）会跟 `abs_pads`
          差一个 `BOT_FIX_MM` ✗ ⇒ "贴角时以为在里面、检查时说出板" ✗（2026-09-30 实测 ✗）。
        """
        bb = vbox(p, key)
        if key[0]:
            bb = (bb[0] - U(BOT_FIX_MM[0]), bb[1] - U(BOT_FIX_MM[1]),
                  bb[2] - U(BOT_FIX_MM[0]), bb[3] - U(BOT_FIX_MM[1]))
        return bb

    def body_local(p, key):
        """该件在该 `(面, 角度)` 下的**本体/丝印框**（局部 ✓ —— 已含底层的画布镜像 ✓）

        ★★ 2026-09-30 改 ✗：**取"画出来的一切"**（`inkbox` ✓）—— ✗ 原来取 `cubox`（铜箔 ✓）
          对**连接器**是错的 ✗：它只有 3 个带 id 的焊盘 ✗（固定焊盘 + 丝印没算 ✗）
          ⇒ 以为贴住了角、实际丝印出板 ✗（实测 J1 出 0.64 mm ✗ / J2 出 0.87 mm ✗）。
          量不到 `inkbox` ⇒ 退回 `cubox` ✓（宁可保守、不静默 ✗）。

        ★★ 贴角/避让都要用它 ✗ 不能用焊盘框 ✗：2026-09-30 实测 ✓ ——
          J1 本体 6.13×5.47 mm ✓，按**焊盘**贴角 ⇒ 本体伸出板外 0.8～3.5 mm ✗
          （用户看到的就是这个 ✓「J2 在 PCB 板外面」✗）＋ 伸进绕组带 ✗（「J1 侵入了线圈」✗）。
        ★ 底层件再减 `BOT_FIX_MM` ✓ —— 那是拿用户的手工对准量出来的**原点差** ✓；
          不减的话 J1 按 0.3 mm 边距贴角会"预测出板" ✗（实测理由：出板边×1 ✓）。
        """
        cb = p.get("inkbox") or p.get("cubox")
        if cb is None:
            return None
        cw, ch = p.get("canvas") or (0.0, 0.0)
        # ★★ 顺序必须与 `pcb_pads.part_pads` **一个字一致** ✗（2026-09-30 修 ✗，同一个病的第四处 ✓）：
        #   那边是 `x = mirror(u)` 之后才 `apply(M, …)` ✓ ⇒ = **先镜像、后旋转** ✓。
        #   ✗ 旧写法先 `rot_box_canvas` 再镜像 ✗ ⇒ θ = 90/270 时两者差一个"反向旋转" ✗
        #     ⇒ **本体框与焊盘框各朝一边** ✗（实测：J2 的朝向被选成 270° ✗ —— 用户
        #       确认过的 90° 是"固定焊盘在右、3 焊盘朝左"✓）。
        if key[0]:
            cb = (cw - cb[2], cb[1], cw - cb[0], cb[3])
        return rot_box_canvas(cb, key[1], cw, ch)

    def vbox(p, key):
        return union(p["var"][key].values())

    # ★ ①②（线圈 / 两个总线口）**必须放在 `costs`/`hpwl` 定义之后** ✗ ——
    #   它们要调这两个函数 ✓（第一版写在前面 ⇒ `UnboundLocalError` ✗）。
    #   现在它们在下面 `costs()` 之后 ✓。

    def abs_pads(p, loc, key):
        """该件在该 `(面,角度)` 变体下、摆在 `loc` 时的**绝对焊盘框** ✓

        ★ 底层件要减 `BOT_FIX_MM` ✓ —— 与 `body_local` **同一个修正** ✓（同一份几何 ✓）；
          ✗ 不加会出现\"本体在里面✓、焊盘却在外面\"这种自相矛盾 ✓（2026-09-30 ✗）。
        """
        vb = p["var"].get(key) or p["var"][(True, 0)]
        fx, fy = (U(BOT_FIX_MM[0]), U(BOT_FIX_MM[1])) if key[0] else (0.0, 0.0)
        return {cid: (b[0] + loc[0] - fx, b[1] + loc[1] - fy,
                      b[2] + loc[0] - fx, b[3] + loc[1] - fy)
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
        # ★★ 硬约束：**本体/铜箔**也不许出板 ✗（用户 2026-09-30："J2 在 PCB 板外面了" ✗ ——
        #    我原来只卡**焊盘**框 ✗ ⇒ 丝印/本体出板看不见 ✗）
        bb = abs_body(p, loc, key)
        if bb is not None and (bb[0] < r[0] + U(COPPER_EDGE_MM)
                               or bb[1] < r[1] + U(COPPER_EDGE_MM)
                               or bb[2] > r[2] - U(COPPER_EDGE_MM)
                               or bb[3] > r[3] - U(COPPER_EDGE_MM)):
            return None, "本体出板边"
        # ★★ 硬约束：不许压**绕组** ✗（用户 2026-09-30：「J1 侵入了线圈的范围」✗）
        #     ★ 判据必须用**径向** ✓ —— 绕组是个**环** ✗：用包围盒会把四个角全判死 ✗
        #       （环心在板心、外半径 ≈10 mm ⇒ 四个角落在包围盒里但**那里没有铜** ✓）。
        #     ⇒ 每个角点算离**板心**的距离 ✓：要么整体 ≤ φ8 内 ✓（§6.1「优先塞进中心 φ8」✓）、
        #       要么整体 ≥ 外半径 + 净空 ✓；夹在环带里 ⇒ 压绕组 ✗。

        # ★★ 硬约束：不许进安装孔的**免件环（Ø4.0 ✓）** ✗
        for hn, (hx, hy) in (holes or {}).items():
            kr = U(HOLE_KEEP_MM / 2.0)
            for ab in abs_pads(p, loc, key).values():
                cx = min(max(hx, ab[0]), ab[2])
                cy = min(max(hy, ab[1]), ab[3])
                if math.hypot(cx - hx, cy - hy) < kr:
                    return None, "进 %s 的 Ø%.0f 环" % (hn, HOLE_KEEP_MM)
            if bb is not None:
                cx = min(max(hx, bb[0]), bb[2])
                cy = min(max(hy, bb[1]), bb[3])
                if math.hypot(cx - hx, cy - hy) < kr:
                    return None, "本体进 %s 的 Ø%.0f 环" % (hn, HOLE_KEEP_MM)
        for t, q in placed.items():
            # ★★ **只在同一面**才要间距 ✓（用户 2026-09-30 纠正 ✗）：
            #   双面板上**异面元件互不干涉** ✓ —— 顶面的 LED2 放在底面 U1 头上完全没问题 ✓；
            #   ✗ 我原来不分面 ⇒ 把 LED2（顶面）和 U1（底面）判成\"太近\" ✗ ⇒ 它无处可放 ✗（已修 ✓）。
            #   同面才需要：① 不互相遮盖 ✓ ② 留出走线空间 ✓（= 本条的净空 CL ✓）。
            if (q.get("side") or "?") != (p.get("side") or "?"):
                continue
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
        # ★★ 绕组规则（用户 2026-09-30 定 ✓）—— **分面** ✓：
        #   · **与绕组同面**的件（例：LED2 ✓）：压上 = **短路** ✗ ⇒ **硬性**：整体必须在绕组外 ✓；
        #   · **异面**的件：只算"尽量避免" ✓（§6.1 ✓）⇒ **软代价** ✓。
        #   ★ 判据用**径向** ✓（环是空的 ✗，包围盒不行 ✗）；内边界 = φ8（中心净空 ✓）+ 0.15 容差 ✓。
        #   ✗ 放在 `cost` 算完之后 ✓ —— 放前面会 `UnboundLocalError`（已踩 ✗）。
        if coil_r_out is not None:
            cl = U(COIL_CLR_MM)
            rin = U(4.0 + 0.15)
            same_face = (coil_side is not None and p.get("side") == coil_side)
            worst = 0.0
            for bx in ((bb,) if bb is None else (bb, b)):
                rs = []
                for px in (bx[0], (bx[0] + bx[2]) / 2.0, bx[2]):
                    for py in (bx[1], (bx[1] + bx[3]) / 2.0, bx[3]):
                        rs.append(math.hypot(px - c[0], py - c[1]))
                if max(rs) <= rin or min(rs) >= coil_r_out + cl:
                    continue
                if same_face:
                    return None, "与绕组**同面**且压上 ✗（会短路 ✗）"
                deep = min(max(0.0, max(rs) - rin), max(0.0, coil_r_out + cl - min(rs)))
                worst = max(worst, deep)
            if worst > 0.0:
                cost += (worst / SK) ** 2 * K_COIL
        return cost, ""

    # ① 线圈：**正面** ✓（用户定 ✓）、保留它自己那个 90° 朝向 ✓（= Fritzing 原来写的 transform ✓）、
    #   把**铜箔（绕组）包围盒**中心对到板心 ✓（★ 不是焊盘包围盒 ✗ —— 环心比焊盘中心偏
    #   ~6.4 mm ✓，用焊盘定心会把环顶出板外 ✗，用户就是这样看出来的 ✗）
    coil = by.get("L1")
    if coil:
        cb = coil.get("cubox") or coil["box"]
        new["L1"] = ((c[0] - ctr(cb)[0], c[1] - ctr(cb)[1]), False, 90)
        placed["L1"] = coil
        # ★ 记下绕组的**绝对铜箔框** ✓ —— 后面"谁都不许压绕组"的硬约束就靠它 ✓
        _cbb = rot_box_canvas(cb, 90, *(coil.get("canvas") or (0.0, 0.0)))
        coil_abs = (_cbb[0] + new["L1"][0][0], _cbb[1] + new["L1"][0][1],
                    _cbb[2] + new["L1"][0][0], _cbb[3] + new["L1"][0][1])
        # ★ 外半径 = 铜箔框的**半长边**（转 90° 后长宽对调 ✓ 但最大值不变 ✓）
        coil_r_out = max(cb[2] - cb[0], cb[3] - cb[1]) / 2.0
        coil_side = coil.get("side")
        print("   绕组：外半径 ≈ %.2f mm、在 **%s** ✓（§6.1：件优先塞进中心 φ8 ✓；"
              "**同面**件硬性让开 %.1f mm ✓、异面件只提醒 ✓）"
              % (coil_r_out / SK, coil_side, COIL_CLR_MM))
        print("   线圈：**正面** ✓、朝 90° ✓（照它原本的 transform ✓）、铜箔中心对板心 ✓"
              "（焊盘包围盒中心相对环心差 (%.2f, %.2f) mm ✓）"
              % ((ctr(coil["box"])[0] - ctr(cb)[0]) / SK,
                 (ctr(coil["box"])[1] - ctr(cb)[1]) / SK))
    # ②a 先把两个安装孔的**目标孔心**定下来 ✓（纯几何 ✓）——
    #     ★ 必须早于 J1/J2 ✓：它们摆位时要按 Ø4.0 环**硬避让** ✓，那时就得知道孔在哪 ✓。
    #     ★ 规范 ✓：孔心离两条板边 **3.0 mm** ✓（`HOLE_MM` ✓，IPC-2221C ✓）。
    for nm, corner in sorted(HOLE_CORNER.items()):
        hx = (r[0] + U(HOLE_MM)) if corner in ("TL", "BL") else (r[2] - U(HOLE_MM))
        hy = (r[1] + U(HOLE_MM)) if corner in ("TL", "TR") else (r[3] - U(HOLE_MM))
        holes[nm] = (hx, hy)
        print("   · %-5s 安装孔 %s ✓ 占 **%s 角** ⇒ 孔心 (%.2f, %.2f) mm（离两条板边 %.2f mm ✓）"
              % (nm, HOLE_SIZE, corner, MM(hx - r[0]), MM(hy - r[1]), HOLE_MM))

    # ② J1/J2：**底层** ✓、各占一个**对角**（`CORNER` ✓）、**焊盘朝板内** ✓
    #    ★ 朝向**不是写死的** ✗ —— 4 个朝向里挑"焊盘簇离板心最近"的那个 ✓
    #      （对底层的件 `abs_pads` 已含 Fritzing 的左右镜像 ✓ ⇒ 挑的是**真实几何** ✓）。
    def corner_loc(bb, corner, margin):
        """把包围盒贴到该角（外沿离两条板边各 `margin` ✓）⇒ 实例 `loc` ✓"""
        x = (r[0] + margin - bb[0]) if corner in ("TL", "BL") else (r[2] - margin - bb[2])
        y = (r[1] + margin - bb[1]) if corner in ("TL", "TR") else (r[3] - margin - bb[3])
        return (x, y)

    for ttl, corner in sorted(CORNER.items()):
        p = by.get(ttl)
        if not p:
            continue
        best, bestk, bestd = None, None, None
        whys = {}                                # ★ 按**频次**记理由 ✓（前 8 条会误导 ✗）
        for th in ([CORNER_ROT[ttl]] if ttl in CORNER_ROT else ROTS):
            key = (True, th)
            if key not in p["var"]:
                continue
            # ★ 贴角的框 = **本体/铜箔框 ∪ 焊盘框** ✓ —— 只用 `cubox` 会\"本体贴角、焊盘出板\" ✗
            #   （2026-09-30 实测：J1 因此一直报\"出板边×1\" ✗）；两个框都已含底层修正 ✓。
            e0 = body_local(p, key)
            e1 = pad_local(p, key)
            box = union([b for b in (e0, e1) if b]) or e1
            loc = corner_loc(box, corner, EDGE)
            cst, why = costs(p, loc, key)
            if cst is None:
                whys[why] = whys.get(why, 0) + 1
                continue
            pc = ctr(union(abs_pads(p, loc, key).values()))       # 焊盘簇中心 ✓
            d = math.hypot(pc[0] - c[0], pc[1] - c[1])            # 离板心越近 = 越朝内 ✓
            if bestd is None or d < bestd:
                best, bestk, bestd = loc, key, d
        if best is None:
            print("   ✗ %s 在 %s 角放不下 ⇒ 保持原位 ✗（理由：%s）"
                  % (ttl, corner, "; ".join("%s×%d" % (k, v) for k, v in
                                            sorted(whys.items(), key=lambda kv: -kv[1])[:5])))
            continue
        new[ttl] = (best, True, bestk[1])
        placed[ttl] = p
        pc = ctr(union(abs_pads(p, best, bestk).values()))
        print("   · %-5s **底层** ✓ 占 **%s 角** ✓ 朝 %3d° ⇒ 焊盘中心 (%.2f, %.2f) mm"
              "（离板心 %.2f mm ✓ = 焊盘朝板内 ✓）"
              % (ttl, corner, bestk[1], MM(pc[0] - r[0]), MM(pc[1] - r[1]),
                 math.hypot(pc[0] - c[0], pc[1] - c[1]) / SK))

    # ②b（孔位已在 ②a 算好 ✓ —— 这里不再重复算 ✗，免得两处一套 ✗）

    # ③ 其余件（**全部底层** ✓ 用户定 ✓）：从大到小贪心 ✓，**所在面与 4 个朝向一起搜** ✓
    todo = [t for t in by if t not in new]
    todo.sort(key=lambda t: -((vbox(by[t], (True, 0))[2] - vbox(by[t], (True, 0))[0])
                              * (vbox(by[t], (True, 0))[3] - vbox(by[t], (True, 0))[1])))
    for t in todo:
        p = by[t]
        best, bestc, bestkey, bestwhy = None, None, None, {}
        nc = int(RMAX / GRID)
        keys = [(False, th) for th in ROTS] if t in TOP_SIDE else [(True, th) for th in ROTS]
        for key in keys:
            if key not in p["var"]:
                continue
            bb = pad_local(p, key)
            # ★★ 钉心的件：**只试"正心"这一个落点** ✓（用户 2026-09-30 定 ✓，见 `PIN_CENTER` ✓）
            if t in PIN_CENTER:
                cands = [(c[0] - ctr(bb)[0], c[1] - ctr(bb)[1])]
            else:
                cands = [(c[0] + ix * GRID - ctr(bb)[0], c[1] + iy * GRID - ctr(bb)[1])
                         for ix in range(-nc, nc + 1) for iy in range(-nc, nc + 1)]
            for loc in cands:
                cost, why = costs(p, loc, key)
                if cost is None:
                    bestwhy[why] = bestwhy.get(why, 0) + 1        # ★ 按频次 ✓
                    continue
                if bestc is None or cost < bestc - 1e-9:
                    best, bestc, bestkey = loc, cost, key
        if best is None:
            print("   ✗ %s **找不到位置**（%s）⇒ 保持原位 ✗"
                  % (t, "; ".join("%s×%d" % (k, v) for k, v in
                                  sorted(bestwhy.items(), key=lambda kv: -kv[1])[:5])))
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
    return new, c, holes


# ── 写回（**只动 pcbView** ✓）────────────────────────────────────────────────
def hole_block(title, mi, p):
    r"""Fritzing 核心库**安装孔**实例 ✓（写法**逐字照** `holes_pads.fzz` 里它自己写的 ✓）

    ★ 用户定 ✓：**只给 `pcbView`** ✓（原理图 / 面包板里不要它 ✗）；
    ★ 它**没有任何 connector** ✓ ⇒ 不进网表 ✓、也不参与布线连接 ✓；
    ★ `hole size="2.2mm,0.0mm"` ⇒ **外径 0 = 无铜盘** ✓ ⇒ 走线不算它障碍 ✓
      （但**不许压住这颗孔** ✓ —— 那由自检单独查 ✓，距离 = Ø2.2/2 + 净空 ✓）。
    """
    return ('        <instance moduleIdRef="HoleModuleID" modelIndex="%s" '
            'path=":/resources/parts/core/hole.fzp">\n'
            '            <property name="hole size" value="%s"/>\n'
            '            <title>%s</title>\n'
            '            <views>\n'
            '                <pcbView layer="copper0">\n'
            '                    <geometry z="5.5" x="%s" y="%s"/>\n'
            '                </pcbView>\n'
            '            </views>\n'
            '        </instance>\n' % (mi, HOLE_SIZE, title, PW.fmt(p[0]), PW.fmt(p[1])))


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


def write_back(base, out, newlocs, canvas, extra=""):
    """把新的 (loc, 面, 朝向) 写进各实例的 **pcbView** ✓；别的视图 / 别的文件**逐字节不动** ✓

    `extra` = 要**新插**进实例表的 XML ✓（本版：两个安装孔 ✓）
    ★ 找不到唯一的 `</instances>` ⇒ **报错、不写文件** ✗（宁可不交，不交坏文件 ✓）。
    """
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
    if extra:
        m2 = list(re.finditer(r"[ \t]*</instances>", text2))
        if len(m2) != 1:
            raise SystemExit("✗ 找不到唯一的 `</instances>`（找到 %d 个 ✗）⇒ 不写文件 ✗" % len(m2))
        text2 = text2[:m2[0].start()] + extra + text2[m2[0].start():]
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
    global HOLE_OFF_MM
    if "--hole-off-mm" in argv:            # ``dx,dy``（mm ✓）＝ `图上环心 − <geometry>` ✓
        HOLE_OFF_MM = tuple(float(v) for v in
                            argv[argv.index("--hole-off-mm") + 1].split(","))
    nets = projdata.load(netsf, need=("NETS",)).NETS
    parts, board = load(base)
    r = board_rect(PP.read_fzz(base)[0], board)
    print("== 摆位：%s ⇒ %s ==" % (os.path.basename(base), os.path.basename(out)))
    print("   板框 = (%.2f,%.2f)-(%.2f,%.2f) mm（%.2f × %.2f mm ✓）"
          % (MM(r[0]), MM(r[1]), MM(r[2]), MM(r[3]), MM(r[2] - r[0]), MM(r[3] - r[1])))
    print("   件的**朝向/所在面**照原样保留 ✓（本版只平移 ✓）：")
    for p in sorted(parts, key=lambda q: q["title"]):
        cb = p.get("cubox")
        ib = p.get("inkbox")
        print("      %-5s layer=%-8s bottom=%-5s 焊盘 %2d 个｜铜箔框 %s｜**画出来的一切** %s"
              % (p["title"], p["side"], p["bottom"], len(p["pads"]),
                 ("%.2f × %.2f mm" % (MM(cb[2] - cb[0]), MM(cb[3] - cb[1]))) if cb
                 else "（量不到 ✗）",
                 ("%.2f × %.2f mm" % (MM(ib[2] - ib[0]), MM(ib[3] - ib[1]))) if ib
                 else "（量不到 ⇒ 退回铜箔框 ✗）"))
    by = {p["title"]: p for p in parts}
    print("   放置 ✓")
    new, c, holes = place(parts, r, nets)
    # ★ 安装孔：新插两个核心库实例 ✓（`modelIndex` 从现有最大值往后排 ✓，不撞号 ✗）
    used = [int(x) for x in re.findall(r'modelIndex="(\d+)"', PW.read(base)[0])]
    nxt = max(used) + 1 if used else 90000000
    extra = "".join(hole_block(nm, "%d" % (nxt + i),
                               (holes[nm][0] - U(HOLE_OFF_MM[0]),
                                holes[nm][1] - U(HOLE_OFF_MM[1])))
                    for i, nm in enumerate(sorted(holes)))
    n = write_back(base, out, new, {p["title"]: p["canvas"] for p in parts}, extra)
    print("   写回：挪了 %d 个实例的 pcbView ✓（面包板/原理图视图**未动** ✓）" % n)
    print("   安装孔：插入 %d 个 `HoleModuleID` 实例 ✓（**只给了 pcbView** ✓，`modelIndex` 从 %d 起 ✓）"
          % (len(holes), nxt))
    if HOLE_OFF_MM == (0.0, 0.0):
        print("   ⚠️ 孔偏移按 (0,0) 写 ✓（= 拿 `<geometry>` 当孔心 ✓）"
              "—— 它**未必等于图上环心** ✗ ⇒ 请导一张这板的 PCB 图示 ✓ 让我按板校准 ✓")
    else:
        print("   孔偏移按 %s mm 补偿 ✓（定义：drawn = geometry + off ✓）" % (HOLE_OFF_MM,))

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
