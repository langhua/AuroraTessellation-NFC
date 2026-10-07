# -*- coding: utf-8 -*-
r"""★★ 版本差异图 ＋ 差异清单 ✓（2026-10-07 用户要的「**第三步**」✓）

用户原话 ✓：「截图所示的这种 PNG 的（并排预览），**不是目标**，继续做之前说的第三步吧？」✓
⇒ 并排比对只是手段 ✗；要的是**一张图看出变化** ✓ ＋ **一段话说清改了什么** ✓。

本工具输出**两个**东西 ✓：

① **叠合差异图** ✓（`diff\diff-<A>-<B>.svg` ＋ `.png`）——
   A 版画成**蓝** ✓、B 版画成**红** ✓、两版都有 ⇒ **深色** ✓：
   · 只有**蓝** ⇒ A 有、B 没有（**删掉了** ✗）
   · 只有**红** ⇒ B 新增（**加上了** ✓）
   · **深色** ⇒ 两版重合（没动 ✓）
   两版都用 `--board-only` 同一取景 ✓（板框 25×25 一样 ✓）⇒ 像素级**可叠** ✓。

② **差异清单** ✓（控制台 ＋ 同名 `.md` ✓）：按**人能读的名字**报 ✓ ——
   · 元件摆位：`C2` 挪了 **0.83 mm**（Δ=(+0.35, −0.75) ✓）
   · 连线：`U1.connector1 ↔ J1.connector1` 3 段 4.2 mm ⇒ 5 段 6.8 mm ✓
   · 过孔：挪动/新增/删除各几颗 ✓
   · 汇总：段数/总长/过孔数 ✓

★ 几何**不另写一套** ✗：走线/焊盘/过孔全部来自元件库 `pcb_check.collect()` ✓
（= 校验器同一个世界模型 ✓）；渲染用 `render_pcb.render()` ✓。AGENTS §13「只允许一个声音」✓。

用法 ✓（版本名或路径都行 ✓）：
  py tools\diff_revs.py v59 v76
  py tools\diff_revs.py --last 2            # 最后两版 ✓
  py tools\diff_revs.py v69 pixel-pcb-v76.fzz --px 24
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
except Exception:                            # noqa: BLE001  老解释器没这方法 ⇒ 忽略 ✓
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)

# ★★ 颜色口径（2026-10-07 用户定 ✓，原话：「双面板的**颜色差异看不出来了**」✗）：
#   **色相 = 层**（顶 = 暖 ✓ / 底 = 冷 ✓）、**深浅 = 版**（浅 = A 旧 ✓ / 深 = B 新 ✓）、
#   **非铜**（丝印/板框/位号/孔）= 中性灰（A 浅 ✓ / B 深 ✓）。
#   ✗ 旧口径「整版一色（A 蓝 / B 红）」把 copper0 与 copper1 **刷成一色** ✗ ⇒ 层分不出来 ✗。
A_TOP, B_TOP = "#f0a868", "#b8440a"      # 顶层：浅橙 ⇒ 深橙红 ✓
A_BOT, B_BOT = "#8ab4f8", "#1a4fd0"      # 底层：浅蓝 ⇒ 深蓝 ✓
A_OTH, B_OTH = "#cfcfcf", "#5a5a5a"      # 丝印/板框/位号/孔：浅灰 ⇒ 深灰 ✓
JOINT = 0.01             # 认定"没动"的阈值（mm ✓）
# ★ 1 sketch 单位 = 25.4/90 mm ✓（= 元件库 `pcb_wire.SK` ✓ 同一口径 ✓）
SK = 25.4 / 90.0


def _lib_tools():
    d = HERE
    for _ in range(6):
        d = os.path.dirname(d)
        cand = os.path.join(d, "fritzing-parts-langhua", "tools")
        if os.path.isfile(os.path.join(cand, "render_pcb.py")):
            return cand
    raise SystemExit("找不到元件库 tools\\render_pcb.py ✗")


def _resolve(arg, have):
    """`v59` / `pixel-pcb-v59.fzz` / 绝对路径 ⇒ 文件路径 ✓。"""
    if os.path.isfile(arg):
        return arg
    name = arg if arg.endswith(".fzz") else None
    num = re.sub(r"^v", "", os.path.splitext(arg)[0])
    hits = [f for f in have if num.isdigit() and _vnum(f) == int(num)]
    if name:
        hits = [f for f in have if f == name] or hits
    if not hits:
        raise SystemExit("找不到这一版：%s ✗（本目录有 %d 版 ✓）" % (arg, len(have)))
    return os.path.join(PIX, hits[0])


def _vnum(f):
    m = re.match(r"^.*?-v(\d+)", os.path.splitext(f)[0])
    return int(m.group(1)) if m else -1


def _vtxt(f):
    stem = os.path.splitext(os.path.basename(f))[0]
    m = re.match(r"^.*?-v(\d+)(.*)$", stem)
    if not m:
        return stem
    suf = m.group(2).strip("_-")
    return "v%d%s" % (int(m.group(1)), ("_" + suf) if suf else "")


# ── 差异清单 ───────────────────────────────────────────────────────────────
def _pad_map(model):
    """`(件名, connectorId)` ⇒ 焊盘 ✓（★ 别按 `modelIndex` 配 ✗ —— 另存会重编号 ✗）。"""
    m = {}
    for q in model["pads"]:
        m.setdefault((q["title"], q["cid"]), []).append(q)
    return m


def _netmap(pix):
    """项目网表 ⇒ `(位号, connectorN / @脚名) → 网名` ✓（`NETS` 在 `pixel_nets.py` ✓）。

    ★ 为什么借项目的表 ✗：用户嘴里的网名是 **`GND` / `RC` / `5V`** ✓ —— 报告里写
      `U1.connector1 ↔ C2.connector1` 是对不上的 ✗（2026-10-07 实测：第一版清单就是这么
      读不懂的 ✗）。表里的 `#N` = **第 N 个脚** ⇒ `#1` = `connector0` ✓（不是 1-based 的 cid ✗）。
    """
    d = os.path.dirname(pix)
    if not os.path.isfile(os.path.join(pix, "pixel_nets.py")):
        return {}
    sys.path.insert(0, pix)
    sys.path.insert(1, d)
    try:
        import pixel_nets as PN                                        # noqa: PLC0415
    except ImportError:
        return {}
    m = {}
    for net, lst in (getattr(PN, "NETS", None) or {}).items():
        for ref, conn in lst:
            if str(conn).startswith("#"):
                m[(ref, "connector%d" % (int(str(conn)[1:]) - 1))] = net
            else:
                m[(ref, "@" + str(conn).upper())] = net
    return m


def _find(par, x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


def _nets(model, netmap):
    """⇒ `[(网名, [铜块]), …]` ✓ —— **口径与 Fritzing 同源** ✓：一张网 = 走线**链** ✓
    （`Wire::collectChained` ✓）＋ 声明 ✓；过孔当**接头** ✓（它两端的走线**都声明它** ✓
    ⇒ 链自然跨层连上 ✓，本工具**不需要**懂过孔内部 ✗）。

    ★★ 实测（2026-10-07 ✓）：走线两端的声明**多数指向"另一条走线"** ✗（`copper0trace` ✓）
      ⇒ ✗ 按**单条线**的名字去对网 ⇒ 只能得到 `connector0 ↔ connector1` 这种废话 ✗
      （第一版清单就是这么废的 ✗）⇒ 必须**先并链** ✓。
    铜块 = 一个连通分量 ✓；**块 > 1 ⇒ 这张网有地方没连上** ✗（就是 Fritzing 说的"还要布线"✓）。
    """
    mi2t = {}
    for q in model["pads"]:
        if q.get("mi"):
            mi2t.setdefault(str(q["mi"]), q["title"])
    for v in model["vias"]:                       # ★ 过孔只在 `vias[].inst` 里有 mi ✗（`mi=None` ✓）
        if v.get("inst"):
            mi2t.setdefault(str(v["inst"]), v.get("ttl") or "Via?")

    par = {}

    def find(x):
        par.setdefault(x, x)
        return _find(par, x)

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    wires = {}
    for tr in model["traces"]:
        w = ("w", str(tr.get("inst")))
        wires[w] = tr
        find(w)
        for k in sorted(tr.get("ends") or {}):
            for v in (tr["ends"][k] or []):
                cid, mi, lay = (list(v) + [None, None, None])[:3]
                t = ("w", str(mi)) if str(lay or "").endswith("trace") \
                    else ("t", str(mi), str(cid))
                find(t)
                uni(w, t)

    comp = {}
    for k in list(par):
        comp.setdefault(find(k), []).append(k)
    out = []
    for _root, keys in comp.items():
        ws = [k for k in keys if k[0] == "w"]
        if not ws:                                   # 只有焊盘、没有走线 ⇒ 不算"一块铜" ✓
            continue
        terms, ln, layers = [], 0.0, {}
        for w in ws:
            tr = wires.get(w)
            if tr is None:
                continue
            ln += ((tr["b"][0] - tr["a"][0]) ** 2 + (tr["b"][1] - tr["a"][1]) ** 2) ** 0.5
            layers[tr["layer"]] = layers.get(tr["layer"], 0) + 1
        for k in keys:
            if k[0] != "t":
                continue
            t = mi2t.get(k[1], "?")
            if re.match(r"^Via\d+$", t):             # ★ 过孔是**接头** ✗ 不是"网的一只脚" ✗
                continue
            terms.append((t, k[2]))
        nm = ""
        for t, cid in terms:
            pad = next((q for q in model["pads"]
                        if q["title"] == t and q["cid"] == cid), None)
            for key in ((t, cid), (t, "@" + str((pad or {}).get("nm") or "").upper())):
                if key in netmap:
                    nm = netmap[key]
                    break
            if nm:
                break
        out.append((nm, dict(n=len(ws), mm=ln * SK, layers=layers, terms=terms)))
    return out


def _net_summary(nets):
    """把「每块铜」按**网名**汇总 ✓ ⇒ `{网名: [块, …]}`（没名字的块归到 `""` ✓）。"""
    d = {}
    for nm, c in nets:
        d.setdefault(nm, []).append(c)
    return d



def _foot(c):
    """一块铜挂的脚 ⇒ 一行字 ✓（脚名照 Fritzing 的写法 `U1.connector3` ✓ 见 AGENTS §13 ✓）。"""
    s = ["%s.%s" % (t, cid) for t, cid in c["terms"]]
    return "、".join(s[:4]) + ("…（共 %d ✓）" % len(s) if len(s) > 4 else "")


def report(a_fzz, b_fzz, ma, mb, netmap):
    """⇒ 差异清单（`list[str]` ✓）"""
    L = ["# 差异清单：%s ⇒ %s" % (_vtxt(a_fzz), _vtxt(b_fzz)), "",
         "| 图 `diff-%s-%s.png` ✓：**顶层 = 暖色（橙）** ✓、**底层 = 冷色（蓝）** ✓，"
         "**浅 = A（旧）** ✓、**深 = B（新）** ✓，丝印/板框/位号 = 中性灰 ✓（A 浅 / B 深 ✓）；"
         "两版重合处会叠得更深（= 没动 ✓）。" % (_vtxt(a_fzz), _vtxt(b_fzz)), ""]

    # ① 元件摆位 ✓
    pa, pb = _pad_map(ma), _pad_map(mb)
    moved, gone, new = [], [], []
    for k in sorted(set(pa) | set(pb)):
        if k not in pb:
            gone.append(k)
            continue
        if k not in pa:
            new.append(k)
            continue
        ca, cb = pa[k][0]["c"], pb[k][0]["c"]
        dx, dy = (cb[0] - ca[0]) * SK, (cb[1] - ca[1]) * SK
        d = (dx * dx + dy * dy) ** 0.5
        if d > JOINT:
            moved.append((k[0], k[1], dx, dy, d))
    L.append("## ① 元件摆位")
    if not moved and not gone and not new:
        L.append("- **没动** ✓（每个焊盘都在原位 ✓，`modelIndex` 被重编号的也按件名对上了 ✓）")
    for t, cid, dx, dy, d in moved:
        L.append("- `%s.%s` 挪了 **%.3f mm**（Δ = (%+.3f, %+.3f) ✓）" % (t, cid, d, dx, dy))
    if moved:
        by = {}
        for t, _c, _dx, _dy, d in moved:
            s = by.setdefault(t, [0, 0.0])
            s[0] += 1
            s[1] = max(s[1], d)
        L.append("- ⇒ 涉及 **%d** 个件：%s" % (len(by), "、".join(
            "`%s`（%d 脚，最大 %.3f mm）" % (t, v[0], v[1]) for t, v in sorted(by.items()))))
    if gone:
        L.append("- ✗ **没了**：%s" % "、".join("`%s.%s`" % k for k in gone))
    if new:
        L.append("- ✓ **新增**：%s" % "、".join("`%s.%s`" % k for k in new))

    # ② 按**项目网名**报（GND / 5V / RC … ✓），并报**块数** = 这张网分成了几段铜 ✓
    sa, sb = _net_summary(_nets(ma, netmap)), _net_summary(_nets(mb, netmap))
    L.append("")
    L.append("## ② 网（名字取项目网表 `pixel_nets.py` ✓；**铜块 > 1 ⇒ 这张网有地方没连上** ✗；"
             "长度是两端直线近似 ⚠️ 曲线不算 ✗）")
    n_chg, split = 0, []
    for k in sorted(set(sa) | set(sb), key=lambda x: (x == "", x)):
        A, B = sa.get(k, []), sb.get(k, [])
        na, nA, ma_, mB = len(A), len(B), sum(c["n"] for c in A), sum(c["n"] for c in B)
        la = sum(c["mm"] for c in A)
        lb = sum(c["mm"] for c in B)
        nm = "`%s`" % k if k else "**（没有网名的残段 ✓）**"
        chg = (na != nA or ma_ != mB or abs(la - lb) > 0.05)
        if chg:
            n_chg += 1
        L.append("- %s：铜块 **%d ⇒ %d**%s｜走线 %d ⇒ %d 段 ✓｜%.1f ⇒ **%.1f mm** ✓"
                 % (nm, na, nA, " ✗" if na != nA else "", ma_, mB, la, lb))
        for tag, cs in (("A", A), ("B", B)):
            if len(cs) > 1:
                split.append((k, tag, len(cs)))
                for i, c in enumerate(cs, 1):
                    L.append("    · %s 第 %d 块：%d 段 %.1f mm ✓ —— 脚：%s"
                             % (tag, i, c["n"], c["mm"], _foot(c) or "（没接到任何脚 ✗）"))
    if not split:
        L.append("- ★ 每张网都只有**一块铜** ✓（没有「还差一根线」的网 ✓）")
    else:
        L.append("- ★ **块 > 1 的网**（= 这里还差布线 ✗）：%s"
                 % "、".join(sorted(set("%s（%s 版）" % (k or "残段", t) for k, t, _n in split))))

    # ③ 过孔 ✓（按几何就近配 ✓）
    va = [v["p"] for v in ma["vias"]]
    vb = [v["p"] for v in mb["vias"]]
    used, vmoved = set(), 0
    for xa in va:
        best, bj = None, None
        for j, xb in enumerate(vb):
            if j in used:
                continue
            d = ((xb[0] - xa[0]) ** 2 + (xb[1] - xa[1]) ** 2) ** 0.5 * SK
            if best is None or d < best:
                best, bj = d, j
        if bj is not None and best < 0.05:
            used.add(bj)
            if best > JOINT:
                vmoved += 1
    L.append("")
    L.append("## ③ 过孔")
    L.append("- 颗数：**%d ⇒ %d** ✓｜基本没动（<0.05 mm）**%d** 颗 ✓｜挪动 %d ✓｜"
             "删 %d ✗｜增 %d ✓"
             % (len(va), len(vb), len(used), vmoved, len(va) - len(used), len(vb) - len(used)))

    # ④ 结论 ✓
    L.append("")
    L.append("## ④ 结论")
    L.append("- " + ("**逐项相同** ✓（这一版等于上一版 ✓）"
                     if not (moved or gone or new or n_chg or vmoved
                             or len(va) != len(vb)) else
                     "有改动 ✓：摆位 %d 处 ✓｜网 %d 张有变化 ✓｜过孔 %d ⇒ %d 颗 ✓"
                     % (len(moved), n_chg, len(va), len(vb))))
    return L



# ── 叠合差异图 ─────────────────────────────────────────────────────────────
def _frame(svg):
    vb = re.search(r'viewBox="([^"]+)"', svg)
    wh = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', svg)
    return (vb.group(1) if vb else None,
            float(wh.group(1)) if wh else 0.0, float(wh.group(2)) if wh else 0.0)


def _inner(svg):
    """去掉 xml 声明 / 根标签 / **白底矩形** ✓（白底不扔 ⇒ 后画的那版会把前版盖掉 ✗）。"""
    b = re.sub(r'^.*?<svg\b[^>]*>', '', svg, flags=re.S)
    b = re.sub(r'</svg>\s*$', '', b)
    return b.replace('<rect width="100%" height="100%" fill="#ffffff"/>', '')


def overlay(svg_a, svg_b, name_a, name_b):
    """两版叠合 ✓：A 蓝、B 红、重合深色 ✓。"""
    import render_pcb as R
    va, wa, ha = _frame(svg_a)
    vb, wb, hb = _frame(svg_b)
    if va != vb or abs(wa - wb) > 0.5 or abs(ha - hb) > 0.5:
        print("⚠️ 两版取景不一致 ✗（%s vs %s ✓）⇒ 叠合会用 A 的取景 ✓，"
              "位置对不上不是内容差异 ✗" % (va, vb))
    # 板框的**底色**要清掉 ✓（否则 A 的板底一铺，B 就看不见了 ✗）；描边留着 ✓ ⇒ 会各自染色 ✓
    ia = _inner(svg_a).replace('fill="%s"' % R.C_BRD_FILL, 'fill="none"')
    ib = _inner(svg_b).replace('fill="%s"' % R.C_BRD_FILL, 'fill="none"')
    # ★★ “**认色换色**”而不是“刷成一色” ✗：层色是渲染器的**固定常量** ✓
    #   （面 `C_CU0/C_CU1` ✓、线 `C_W0/C_W1` ✓、过孔 `C_VIA_*` ✓）⇒ 按表逐项换 ✓；
    #   表里没写到的（丝印/板框/位号/孔）⇒ `default` 中性灰 ✓。
    def pal(top, bot, oth):
        return ({R.C_CU1: top, R.C_W1: top, R.C_VIA_TOP: top,
                 R.C_CU0: bot, R.C_W0: bot, R.C_VIA_BOT: bot}, oth)

    ta, oa = pal(A_TOP, A_BOT, A_OTH)
    tb, ob = pal(B_TOP, B_BOT, B_OTH)
    ia = R.remap_colors(ia, ta, oa)
    ib = R.remap_colors(ib, tb, ob)
    # ★★ 图例**只能用 ASCII** ✗（2026-10-07 实测 ✓）：中文 + `font-family=DroidSans` 在 cairosvg
    #   里**渲不出字** ✗（实测：左上角只剩几个像素的痕迹 ✓）。
    # ★★★ 而且字号必须**按画布比例算** ✗（同日第二个坑 ✗）：这个渲染器的 `--px` 存进去后
    #   画布宽达 **8043 单位** ✗（实测 ✓）⇒ 写死 12 单位 = **2 像素** ✗ ⇒ 等于没画 ✓。
    fs = max(13.0, wa * 0.0105)         # ★ 字号**按画布比例** ✓（写死 ⇒ 看不见 ✗）；
    #   ⚠️ 且要比直觉小 ✗：cairosvg 的字体实际占高比 `font-size` 大 ⇒ 行距得给到 `2×fs` ✓
    #   （实测：`1.35×fs` 上下行会撞 ✗、`1.75×fs` 仍然紧 ✗ —— 别再在这上面反复微调 ✗，一次给足 ✓）

    def sw(y, c, label):
        """图例一行：色块 ＋ 说明 ✓（色块就是**真用的那个颜色** ✓，不是近似 ✓）。"""
        return ('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="%s" '
                'stroke="#999999" stroke-width="%.1f"/>\n'
                '<text x="%.0f" y="%.0f" font-family="sans-serif" font-size="%.0f" '
                'fill="#333333">%s</text>\n'
                % (fs * 0.6, y, fs * 1.5, fs * 1.15, c, fs * 0.05,
                   fs * 2.7, y + fs * 1.15, fs, label))

    rows = [(A_TOP, "A = %s  top   (light)" % name_a),
            (B_TOP, "B = %s  top   (dark)" % name_b),
            (A_BOT, "A = %s  bottom(light)" % name_a),
            (B_BOT, "B = %s  bottom(dark)" % name_b),
            (A_OTH, "silk/board: A light"),
            (B_OTH, "            B dark")]
    leg = [('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="#ffffff" '
            'fill-opacity="0.9" stroke="#bbbbbb" stroke-width="%.1f"/>'
            % (fs * 0.3, fs * 0.3, fs * 19.0, fs * (2.0 * len(rows) + 0.9), fs * 0.05))]
    for i, (c, lab) in enumerate(rows):
        leg.append(sw(fs * (0.9 + 2.0 * i), c, lab))
    leg = "\n".join(leg)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
        'viewBox="%s">\n'
        '<rect width="100%%" height="100%%" fill="#ffffff"/>\n'
        '%s'
        '<g id="A" opacity="0.75">%s</g>\n'
        '<g id="B" opacity="0.55">%s</g>\n'
        '</svg>\n'
    ) % (wa, ha, va, leg, ia, ib)


def main(argv):
    # ★ `--px 5` ⇒ 画布约 1700 单位 ✓（实测：这个渲染器的画布 ≈ `px × 358` ✓ —— `--px 24`
    #   是 8043 ✗，一个字就占了整个屏幕的比例 ✗，实测图例因此看不见 ✓）
    px, out, last, pos = 5.0, os.path.join(PIX, "diff"), None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--px" and i + 1 < len(argv):
            px = float(argv[i + 1]); i += 2; continue
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]; i += 2; continue
        if a == "--last" and i + 1 < len(argv):
            last = int(argv[i + 1]); i += 2; continue
        pos.append(a); i += 1

    have = sorted([f for f in os.listdir(PIX) if re.match(r"^pixel-pcb-v\d+.*\.fzz$", f)],
                  key=lambda f: _vnum(f))
    if last:
        pos = have[-last:] if last >= 2 else None
        if not pos:
            raise SystemExit("`--last` 至少给 2 ✓")
    if len(pos) != 2:
        print(__doc__)
        return 2
    a_fzz = _resolve(pos[0], have)
    b_fzz = _resolve(pos[1], have)

    # ★★ 元件库的 tools 要先挂上路径 ✗（2026-10-07 实测漏过一次：`_lib_tools()` 写了却没调 ✓
    #   ⇒ `import pcb_check` 直接 ImportError ✓）
    sys.path.insert(0, _lib_tools())
    sys.path.insert(0, os.path.dirname(HERE))
    import pcb_check as PC
    import render_pcb as R
    ma, mb = PC.collect(a_fzz), PC.collect(b_fzz)
    # ★ 同一取景 ⇒ 用 `--board-only` ✓（两版板框都是 25×25 ✓）⇒ 叠得上 ✓
    sa = R.render(ma, px, ("--board-only",))
    sb = R.render(mb, px, ("--board-only",))

    if not os.path.isdir(out):
        os.makedirs(out)
    na, nb = _vtxt(a_fzz), _vtxt(b_fzz)
    stem = "diff-%s-%s" % (na, nb)
    svg_p = os.path.join(out, stem + ".svg")
    open(svg_p, "w", encoding="utf-8", newline="\n").write(
        overlay(sa, sb, na, nb))
    print("✓ 叠合差异图 %s（层 = 色相：顶橙 ✓ 底蓝 ✓；版 = 深浅：浅 A %s ✓ 深 B %s ✓）"
          % (svg_p, na, nb))
    try:
        import cairosvg
        png_p = os.path.join(out, stem + ".png")
        cairosvg.svg2png(url=svg_p, write_to=png_p, scale=1.0, background_color="white")
        print("✓ %s" % png_p)
    except ImportError:
        print("（没装 cairosvg ⇒ 只出 svg ✓）")

    lines = report(a_fzz, b_fzz, ma, mb, _netmap(PIX))
    md_p = os.path.join(out, stem + ".md")
    open(md_p, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print()
    print("\n".join(lines))
    print()
    print("（同一份清单也写到 %s ✓）" % md_p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
