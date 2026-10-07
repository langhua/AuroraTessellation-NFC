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

用法 ✓（版本名 / `.fzz` / **svg** 都行；**带网表清单的只有两个 `.fzz`** ✓）：
  py tools\diff_revs.py v59 v76                    # 两个 fzz ⇒ 图 ＋ 清单 ✓
  py tools\diff_revs.py --last 2                   # 最后两版 ✓
  py tools\diff_revs.py "pixel-pcb-v47_图示.svg" v47   # **Fritzing 导出的 svg ⇔ fzz** ✓（推荐 ✓）
  py tools\diff_revs.py a.svg b.svg                # 两个 svg 也行 ✓（锚靠各自 board 组 ✓）
★ 比 svg 时**锚 = 板框** ✓（见 README §10.4 ✓）—— ✗ 不要拿我们自己渲的**带取景**预览
  当输入 ✗（那种文件里 `stroke=#111111` 的 rect 是**取景框** ✗ 不是板框 ✗ ⇒ 会整体平移 ✗）；
  fzz 那一侧**直接给 .fzz** ✓，工具会自己用 `--board-only` 现渲 ✓。
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
# ★ 「点清单一条 ⇒ 图上高亮」用的**强调色** ✓（2026-10-07 用户要的 ✓）——
#   得跟上面六种颜色都分得开 ✓ ⇒ 取玫红 ✓（蓝/橙/灰都不是它 ✓）。
A_COLOR_HI = "#d81b60"
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



def _board_px(svg, R):
    """从**已经渲好的** svg 里量出「板框 rect」的 px 位置与尺寸 ✓ ⇒ `(x, y, w, h)` ✓。

    ★ 为什么量它 ✗（而不是照 `render()` 的内部公式再算一遍 ✗）：本仓老规矩 —— **同一件事
      只留一份实现** ✓。`--board-only` 渲出来的那个 rect 就是板框 ✓（实测 ✓），
      拿它当"坐标换算锚" ⇒ 我在下面把 sketch 单位换成 px 时用的公式，只依赖
      `model["board"]` ✓ ＋ 这个 rect ✓（都是公开量 ✓），**不碰 render 的内部** ✓。
    """
    m = re.search(r'<rect\b[^>]*\bx="([\d.]+)"\s+y="([\d.]+)"\s+width="([\d.]+)"\s+height="([\d.]+)"'
                  r'[^>]*\bfill="%s"' % re.escape(getattr(R, "C_BRD_FILL", "\0")), svg)
    if not m:                       # 兜底：按描边色找（白底 rect 没有 stroke ✓）
        m = re.search(r'<rect\b[^>]*\bx="([\d.]+)"\s+y="([\d.]+)"\s+width="([\d.]+)"\s+height="([\d.]+)"'
                      r'[^>]*\bstroke="%s"' % re.escape(getattr(R, "C_BRD_EDGE", "\0")), svg)
    return tuple(float(v) for v in m.groups()) if m else None


def _hit_layer(ma, mb, svg_a, svg_b, name_a, name_b):
    """★ 「点清单里一条 ⇒ 图上高亮对应变化」用的**隐藏**图层 ✓（2026-10-07 用户要的 ✓）。

    用户原话 ✓：「在元件摆位下，点一条信息，图里面的相应变化，能高亮显示出来」✓

    做法 ✓（省事又不会两处算坐标 ✗）：
      · 这里**先**把每个"挪过 / 新增 / 删掉"的脚写成一组元素 ✓，`display:none` 藏着 ✓；
      · 扩展那边**只负责**点行 ⇒ 把对应那组 `display` 打开 ✓ ⇒ **坐标换算只有这一份** ✓。
    每组画三样 ✓：A 的旧位置（空心圈 ✓）、B 的新位置（实心圈 ✓）、两者之间一条引线 ＋
    一个标签（脚名 ＋ 位移 mm ✓）。
    """
    import render_pcb as R
    ra, rb = _board_px(svg_a, R), _board_px(svg_b, R)
    if not (ra and rb and ma.get("board") and mb.get("board")):
        return ""
    pair = []
    for (mA, sv, r) in ((ma, svg_a, ra), (mb, svg_b, rb)):       # 两侧各求一个「单位→px」映射 ✓
        bw = mA["board"][2] - mA["board"][0]
        bh = mA["board"][3] - mA["board"][1]
        if bw <= 0 or bh <= 0:
            return ""
        kx, ky = r[2] / bw, r[3] / bh
        pair.append(lambda u, v: (r[0] + (u - mA["board"][0]) * kx,
                                  r[1] + (v - mA["board"][1]) * ky))
    (put_a, put_b) = pair

    pa, pb = _pad_map(ma), _pad_map(mb)
    W = max(ra[2], rb[2])
    o = ['<g id="pd-hits">']
    for k in sorted(set(pa) | set(pb)):
        qa = pa.get(k, [{}])[0].get("c")
        qb = pb.get(k, [{}])[0].get("c")
        if k[0] == "PCB1":
            continue
        pid = "%s.%s" % k
        o.append('<g id="pd-%s" style="display:none">' % re.sub(r"[^\w.-]", "_", pid))
        if qa:
            x, y = put_a(*qa)
            o.append('<circle cx="%.1f" cy="%.1f" r="%.3f" fill="none" stroke="%s" stroke-width="%.2f"/>'
                     % (x, y, W * 0.022, A_COLOR_HI, W * 0.004))
        if qb:
            x2, y2 = put_b(*qb)
            o.append('<circle cx="%.1f" cy="%.1f" r="%.3f" fill="%s" fill-opacity="0.85" stroke="#ffffff" '
                     'stroke-width="%.2f"/>' % (x2, y2, W * 0.022, A_COLOR_HI, W * 0.004))
        if qa and qb:
            x, y = put_a(*qa)
            dx = (qb[0] - qa[0]) * SK
            dy = (qb[1] - qa[1]) * SK
            d = (dx * dx + dy * dy) ** 0.5
            o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.2f" '
                     'stroke-dasharray="%.1f %.1f"/>'
                     % (x, y, x2, y2, A_COLOR_HI, W * 0.0035, W * 0.012, W * 0.008))
            o.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="%.1f" '
                     'fill="%s">%s  Δ %.3f mm</text>'
                     % (x2 + W * 0.03, y2 - W * 0.02, W * 0.024, A_COLOR_HI,
                        esc(pid), d))
        elif qb:
            x2, y2 = put_b(*qb)
            o.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="%.1f" fill="%s">'
                     '%s  新增</text>' % (x2 + W * 0.03, y2 - W * 0.02, W * 0.024, A_COLOR_HI, esc(pid)))
        else:
            x, y = put_a(*qa)
            o.append('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="%.1f" fill="%s">'
                     '%s  没了</text>' % (x + W * 0.03, y - W * 0.02, W * 0.024, A_COLOR_HI, esc(pid)))
        o.append('</g>')
    o.append('</g>')
    return "\n".join(o)


def esc(s):
    """XML 转义 ✓（脚名是 ASCII ✓，但别赌 ✗）。"""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _foot(c):
    """一块铜挂的脚 ⇒ 一行字 ✓（脚名照 Fritzing 的写法 `U1.connector3` ✓ 见 AGENTS §13 ✓）。"""
    s = ["%s.%s" % (t, cid) for t, cid in c["terms"]]
    return "、".join(s[:4]) + ("…（共 %d ✓）" % len(s) if len(s) > 4 else "")


# ── ★★ 也能比「Fritzing 导出的 svg」✓（2026-10-07 用户问 ✓）────────────────────────
#   用户原话 ✓：「如果我从 Fritzing 导出一个 svg，是不是也能这样比较了？」✓
#   ⇒ 能 ✓，但**两个前提**要先处理 ✗（都是实测出来的 ✓，不是猜 ✗）：
#     ① **取景要换算** ✗：Fritzing 导出是 **1in = 72 单位** 且有留白/水印 ✓
#        （实测 `width="1.2278in"` + `viewBox="0 0 88.4 100.7"` ✓ 且带 `<g id="watermark">` ✓）
#        ⇒ 先按**单位换算成 mm** ✓ 再按**墨迹包围盒**对齐 ✓（✗ 直接叠会错位 ✗）。
#     ② **层色口径不同** ✗：导出里**只有走线/过孔**带层色 ✓（`#f28a00` 底 / `#f2c600` 顶 ✓
#        = 同一套 ✓）；**元件自己的铜箔保留原色** ✗（线圈 `#f7bf13` ✓）
#        ⇒ 那些件在两版里都画成**灰** ✓（反正两版一样 ⇒ 灰 = 没动 ✓，信息不丢 ✓）。


def _root(svg):
    """⇒ `dict(vb=(x,y,w,h), u2mm=None|float, w=…, h=…)` ✓（`u2mm=None` ⇒ 比例未知 ✗）。"""
    m = re.search(r"<svg\b[^>]*>", svg)
    a = dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', m.group(0) if m else ""))
    vbn = [float(x) for x in re.findall(r"[-+0-9.eE]+", a.get("viewBox", ""))]
    if len(vbn) == 4:
        vb = tuple(vbn)
    else:
        w = re.match(r"^([\d.]+)", a.get("width", "") or "")
        h = re.match(r"^([\d.]+)", a.get("height", "") or "")
        vb = (0.0, 0.0, float(w.group(1)) if w else 100.0,
              float(h.group(1)) if h else 100.0)

    def mm(v):
        """`width`/`height` ⇒ mm ✓；**无单位或 px ⇒ None** ✗（那个比例不可信 ✗）。"""
        m2 = re.match(r"^\s*([\d.]+)\s*([a-zA-Z%]*)\s*$", v or "")
        if not m2:
            return None
        n, u = float(m2.group(1)), m2.group(2).lower()
        if u in ("", "px", "%"):
            return None
        return {"mm": n, "cm": n * 10.0, "in": n * 25.4, "pt": n * 25.4 / 72.0}.get(u)

    wmm, hmm = mm(a.get("width")), mm(a.get("height"))
    u2mm = None
    if wmm and vb[2]:
        u2mm = wmm / vb[2]
        if hmm and vb[3] and abs(hmm / vb[3] - u2mm) > 1e-4 * u2mm:
            print("⚠️ 这份 svg 的 x/y 比例不一致 ✗（width %.4f vs height %.4f mm/单位 ✓）"
                  "⇒ 按 x 算 ✓" % (u2mm, hmm / vb[3]))
    return dict(vb=vb, u2mm=u2mm, w=wmm, h=hmm)


def _drop_group(svg, gid):
    """整段删 `<g id="X">…</g>` ✓（**配平扫描** ✓ —— 非贪婪正则只会截到第一个 `</g>` ✗）。"""
    out, i = [], 0
    while True:
        m = re.search(r'<g\b[^>]*\bid="%s"[^>]*>' % re.escape(gid), svg[i:])
        if not m:
            break
        s = i + m.start()
        if m.group(0).rstrip().endswith("/>"):
            out.append(svg[i:i + m.end()])
            i += m.end()
            continue
        depth, j = 1, i + m.end()
        while j < len(svg) and depth:
            n = re.search(r"<(/?)g\b", svg[j:])
            if not n:
                break
            k = j + n.start()
            if n.group(1):
                depth -= 1
            else:
                t = svg.find(">", k)
                if not (t >= 0 and svg[k:t].rstrip().endswith("/")):
                    depth += 1
            j = j + n.end()
            if depth == 0:
                break
        out.append(svg[i:s])
        i = j
    out.append(svg[i:])
    return "".join(out)


def _ink_bbox(png_bytes):
    """量**墨迹包围盒**（px ✓）—— 用来对齐 ✓。

    ★ 两条判据缺一不可 ✗（2026-10-07 实测 ✓）：① **透明**不是墨 ✗（cairosvg 可以透明底 ✓）；
      ② **近白**也不是墨 ✗ —— 导出里有一大片白底/白丝印 ✓ ⇒ 只看 alpha 会把整张画布当墨 ✗。
    """
    import io
    from PIL import Image, ImageChops
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    a = im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    g = im.convert("L").point(lambda v: 0 if v >= 245 else 255)
    return ImageChops.multiply(a, g).getbbox()


def _recolor_svg(svg, top, bot, oth):
    """按层色认色换色 ✓；表里没有的（元件的自有颜色 / 丝印 / 板框）⇒ `oth`（灰 ✓）。

    ★ 层色的**权威来源**是渲染器的常量 ✓（`C_W0/C_W1` 走线 ✓、`C_CU0/C_CU1` 面 ✓、
      `C_VIA_*` 过孔 ✓）—— Fritzing 导出用的是**同一套** ✓（实测 ✓）⇒ 两边都能认 ✓。
    """
    import render_pcb as R
    tab = {R.C_W0: bot, R.C_W1: top, R.C_CU0: bot, R.C_CU1: top,
           R.C_VIA_BOT: bot, R.C_VIA_TOP: top}
    return R.remap_colors(svg, tab, oth)        # oth = 两版都一样的东西 ✓


def _wrap(root_tag, inner):
    """把一段内容包回**原来的根标签** ✓ —— ✗ 别自己写 `<svg>` ✗：原标签带着
    `xmlns:svg` / `baseProfile` 等声明 ✓（Fritzing 导出的就有 ✓），丢了会解析失败 ✗。"""
    return "<?xml version='1.0' encoding='UTF-8'?>\n%s%s</svg>" % (root_tag, inner)


def _extract_group(svg, gid):
    """取出 `<g id="X">…</g>` 整段 ✓（配平扫描 ✓）；没有 ⇒ None ✓。

    ★★ 2026-10-07 实测踩到 ✗：配平扫描里 `j += n.end()` 只是**走到 `g` 后面** ✗，
      它还**没有吃掉 `>`** ✗ ⇒ 切出来的片段尾巴是 `<…</g` ✗（实测包装后解析报
      `not well-formed (invalid token): line 4, column 6` ✓，打出来一看是 `</g</svg>` ✗）。
      ⇒ 回片时必须**把 `</g>` 的 `>` 也带上** ✓。
    """
    m = re.search(r'<g\b[^>]*\bid="%s"[^>]*>' % re.escape(gid), svg)
    if not m:
        return None
    if m.group(0).rstrip().endswith("/>") :
        return m.group(0)
    depth, j = 1, m.end()
    while j < len(svg) and depth:
        n = re.search(r"<(/?)g\b", svg[j:])
        if not n:
            break
        k = j + n.start()
        if n.group(1):
            depth -= 1
        else:
            t = svg.find(">", k)
            if not (t >= 0 and svg[k:t].rstrip().endswith("/")):
                depth += 1
        j += n.end()
        if depth == 0:
            t = svg.find(">", k)                     # ★ 连 `</g>` 的 `>` 一起收 ✓
            return svg[m.start():(t + 1 if t >= 0 else j)]
    return None


def _board_box(txt, r):
    """**只画板框**渲一遍 ⇒ 量出板框的**用户单位**范围 ✓（对齐的锚 ✓）。

    ★★ 为什么不能拿**整幅墨迹**对齐 ✗（2026-10-07 实测 ✓）：两边包含的东西不一样
      （留白 ✓、位号位置 ✓、导出的白底 ✓）⇒ 按整幅宽度归一 ⇒ **比例就偏了** ✗
      ⇒ 实测两张图里的线圈**同心却错开** ✗（一眼看就是没对齐 ✓）。**板框才是物理锚** ✓。
    """
    import cairosvg
    import render_pcb as R
    chunk = _extract_group(txt, "board")                     # Fritzing 导出 ✓
    if not chunk:                                           # 我们渲染的：认板框 rect ✓
        # ★★ 2026-10-07 实测踩到两个坑 ✗（都靠证据定位 ✓，不是猜 ✗）：
        #   ① **`C_BRD_FILL` 就是 `#ffffff`** ✗ ⇒ 只按 fill 找会抓到渲染器开头的
        #      **整幅白底**矩形 ✗（`<rect width="100%" height="100%" fill="#ffffff"/>` ✓）；
        #   ② 改认 `stroke=C_BRD_EDGE` 之后**又抓错了一个** ✗ —— 量出来 3802.9×**3782.7**
        #      “板框” ✗（板框是 **25×25 方的** ✓，一看就不对 ✓）。
        #   ⇒ 正解：把候选**全收齐**，取**面积最大**那个 ✓（板框必然是这张图上最大的矩形 ✓），
        #     并排除 `%` 尺寸（那是背景 ✓）。★ 自检就在判据里 ✓：量出来必须是**近似正方形** ✓。
        best, best_a = None, -1.0
        for m2 in re.finditer(r"<rect\b[^>]*/?>", txt):
            tag = m2.group(0)
            if ('stroke="%s"' % getattr(R, "C_BRD_EDGE", "\0")) not in tag and \
               ('fill="%s"' % getattr(R, "C_BRD_FILL", "\0")) not in tag:
                continue
            if re.search(r'\b(width|height)="[^"]*%"', tag):
                continue
            at = dict(re.findall(r'([\w:-]+)="([^"]*)"', tag))
            try:
                ar = float(at.get("width", 0) or 0) * float(at.get("height", 0) or 0)
            except ValueError:
                continue
            if ar > best_a:
                best, best_a = tag, ar
        chunk = best
    if not chunk:
        return None
    root = re.search(r"<svg\b[^>]*>", txt)
    if not root:
        return None
    W = 2000
    png = cairosvg.svg2png(bytestring=_wrap(root.group(0), chunk).encode("utf-8"),
                           output_width=W)
    bb = _ink_bbox(png)
    if not bb:
        return None
    k = W / r["vb"][2]                                       # 参考栅格的 px/单位 ✓
    return dict(u=(bb[0] / k, bb[1] / k, bb[2] / k, bb[3] / k))


def _side(path_or_fzz, px_mm, PC, R):
    """一侧的 svg 文本 ＋ 它的「板框锚」来源说明 ✓。

    ★★ 为什么 **fzz 这一侧要自己渲** ✗（2026-10-07 实测踩到 ✓）：
      ✗ 直接拿 `render_revs` 渲好的预览当输入 ⇒ 那个文件**默认带墨迹取景** ✗
        ⇒ `render_pcb.py:246` 会把 `r` **胀成「板框 ∪ 全部墨迹」** ✗ ⇒ 里面的
        “板框 rect”其实是**取景框** ✗ ⇒ 拿它对锚 ⇒ **整体平移** ✗（实测：线圈/安装孔
        全部错开约 0.5 mm ✓，而板框却“碰巧”看着对齐 ✓）。
      ⇒ 正解：这一侧用 **`--board-only`** 现渲 ✓（那时 `r` = 真板框 ✓）✓。
      ★ 顺带一条真相 ✓：不带 `--board-only` 时，预览里那个 `stroke=#111111` 的 rect
        **不是板框** ✗（= 取景框 ✓）——以前拿它当板框用会错 ✗。
    """
    if path_or_fzz.lower().endswith(".fzz"):
        return R.render(PC.collect(path_or_fzz), px_mm, ("--board-only",)), \
            "我们自己渲的（fzz ⇒ `--board-only` ✓ 锚 = 真板框 ✓）"
    return open(path_or_fzz, encoding="utf-8").read(), \
        "svg 自带的 `<g id=\"board\">` ✓"


def _svg_mode(a_f, b_f, out, px_mm, have=()):
    """比**两个 svg** ✓ —— 也可以是「**一个 fzz ＋ 一个 (Fritzing 导出的) svg**」✓。"""
    import cairosvg
    import sys as _sys

    _sys.path.insert(0, _lib_tools())
    _sys.path.insert(0, os.path.dirname(HERE))
    import pcb_check as PC
    import render_pcb as R

    ta, sa = _side(a_f, px_mm, PC, R)
    tb, sb = _side(b_f, px_mm, PC, R)
    ra, rb = _root(ta), _root(tb)
    ia, ib = _drop_group(ta, "watermark"), _drop_group(tb, "watermark")   # 水印要去掉 ✗
    na, nb = _vtxt(a_f), _vtxt(b_f)
    if not (a_f.lower().endswith(".fzz") or b_f.lower().endswith(".fzz")):
        print("⚠️ 两边都是**外部 svg** ✗：锚只能靠各自自带的 `<g id=\"board\">` ✓；"
              "✗ 若某一边那份**没有** board 组（比如取的是我们自己渲的**带取景**预览 ✗），"
              "锚就会落在“取景框”上 ✗ ⇒ 画面会整体平移 ✗。⇒ **fzz 那一侧请直接给 .fzz** ✓。")
    print("   锚：A = %s；B = %s" % (sa, sb))

    Ba, Bb = _board_box(ta, ra), _board_box(tb, rb)
    if not (Ba and Bb):
        raise SystemExit("量不出板框 ✗（这两份 svg 里都没有 `<g id=\"board\">` 或已知板框 rect ✗）"
                         "⇒ 先在 Fritzing 里导出**当前板**的 svg 再比 ✓")
    wa, wb = Ba["u"][2] - Ba["u"][0], Bb["u"][2] - Bb["u"][0]      # 板框宽（各自用户单位 ✓）
    ha, hb = Ba["u"][3] - Ba["u"][1], Bb["u"][3] - Bb["u"][1]
    # ★ A 有单位就按**物理尺寸**定标 ✓（mm ✓）；否则随便定一个 ✓（叠合只看相对 ✓）
    ka = (px_mm * ra["u2mm"]) if ra["u2mm"] else (1000.0 / ra["vb"][2])
    kb = ka * (wa / wb)                                            # 让两块板框同宽 ✓
    print("   板框：A %.4f×%.4f 单位%s ✓；B %.4f×%.4f 单位 ✓；比例 B×%.4f ✓；"
          "A 的板框 = %.2f×%.2f mm ✓"
          % (wa, ha, ("（×%.4f mm/单位 ⇒ 实为 ✓）" % ra["u2mm"]) if ra["u2mm"] else "✗（无单位）",
             wb, hb, kb / ka, wa * (ra["u2mm"] or 0), ha * (ra["u2mm"] or 0)))

    def tf(t, r, k, b):
        # 板框左上角 ⇒ 画布左上角（留 20 px 边 ✓）
        dx = 20.0 - b["u"][0] * k
        dy = 20.0 - b["u"][1] * k
        return "translate(%.4f,%.4f) scale(%.8f) translate(%.4f,%.4f)" % (
            dx, dy, k, -r["vb"][0], -r["vb"][1])

    # ★ 画布 = **板框的像素尺寸** ✓（✗ 2026-10-07 实测踩到：写成 `max(单位宽) × max(k)`
    #   = 把两边的量纲混乘 ✗ ⇒ cairo 报 `CAIRO_STATUS_INVALID_SIZE` ✗）
    W = max(wa * ka, wb * kb) + 40
    H = max(ha * ka, hb * kb) + 40
    la = _recolor_svg(_inner(ia), A_TOP, A_BOT, A_OTH)
    lb = _recolor_svg(_inner(ib), B_TOP, B_BOT, B_OTH)
    fs = max(13.0, W * 0.0105)
    rows = [(A_TOP, "A = %s  top" % re.sub(r"[^\x20-\x7e]", "?", na)),
            (B_TOP, "B = %s  top" % re.sub(r"[^\x20-\x7e]", "?", nb)),
            (A_BOT, "A = %s  bottom" % re.sub(r"[^\x20-\x7e]", "?", na)),
            (B_BOT, "B = %s  bottom" % re.sub(r"[^\x20-\x7e]", "?", nb)),
            (A_OTH, "grey = silk / board / part-copper"),
            (B_OTH, "(light = A / dark = B)")]

    def sw(y, c, label):
        return ('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="%s" stroke="#999999" '
                'stroke-width="%.1f"/>\n<text x="%.0f" y="%.0f" font-family="sans-serif" '
                'font-size="%.0f" fill="#333333">%s</text>\n'
                % (fs * 0.6, y, fs * 1.5, fs * 1.15, c, fs * 0.05, fs * 2.7, y + fs * 1.15, fs, label))

    leg = [('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="#ffffff" '
            'fill-opacity="0.9" stroke="#bbbbbb" stroke-width="%.1f"/>'
            % (fs * 0.3, fs * 0.3, fs * 27.0, fs * (2.0 * len(rows) + 0.9), fs * 0.05))]
    for i, (c, lb2) in enumerate(rows):
        leg.append(sw(fs * (0.9 + 2.0 * i), c, lb2))
    svg = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
           'viewBox="0 0 %.1f %.1f">\n'
           '<rect width="100%%" height="100%%" fill="#ffffff"/>\n'
           '%s\n'
           '<g id="A" opacity="0.75" transform="%s">%s</g>\n'
           '<g id="B" opacity="0.55" transform="%s">%s</g>\n'
           '</svg>\n'
           % (W, H, W, H, "\n".join(leg),
              tf(ia, ra, ka, Ba), la, tf(ib, rb, kb, Bb), lb))
    if not os.path.isdir(out):
        os.makedirs(out)
    stem = "diff-%s-%s" % (re.sub(r"[^\w.-]", "_", na), re.sub(r"[^\w.-]", "_", nb))
    p = os.path.join(out, stem + ".svg")
    open(p, "w", encoding="utf-8", newline="\n").write(svg)
    cairosvg.svg2png(url=p, write_to=os.path.join(out, stem + ".png"), scale=1.0,
                     background_color="white")
    print("✓ 叠合差异图 %s ✓（锚 = **板框** ✓，不靠整幅留白 ✓ —— 见 README §10.4 ✓）" % p)
    print("（svg 输入**没有网表清单** ✗ —— 要清单就得给两个 `.fzz` ✓）")
    return 0



def report(a_fzz, b_fzz, ma, mb, netmap):
    """⇒ 差异清单（`list[str]` ✓）"""
    L = ["# 差异清单：%s ⇒ %s" % (_vtxt(a_fzz), _vtxt(b_fzz)), "",
         # ★ 行首的 `> ` 是 **markdown 引用** ✗ —— 2026-10-07 被我改层色口径时**弄丢过一次** ✗
         #   （变成 `| 图 …` ✓）⇒ 扩展的单测抳出来了 ✓（清单渲染出来不再是引用块 ✓）。
         "> 图 `diff-%s-%s.png` ✓：**顶层 = 暖色（橙）** ✓、**底层 = 冷色（蓝）** ✓，"
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
    L.append("> 在 VS Code 的**合并视图**里点下面任一条 ✓ ⇒ 图上会高亮那处变化 ✓"
             "（旧位置 = 空心圈 ✓、新位置 = 实心圈 ✓、虚线 = 位移 ✓）。")
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
    n_svg = sum(1 for p in pos if p.lower().endswith(".svg"))
    if n_svg:
        if n_svg == 2:
            print("—— 两个 svg ⇒ **不比网表** ✗，只出叠合差异图 ✓（Fritzing 导出的也算 ✓）")
            return _svg_mode(pos[0], pos[1], out, 40.0)
        # ★ 一个 fzz ＋ 一个 svg ✓ = **推荐用法** ✓（fzz 那侧我们自己渲 ⇒ 锚准 ✓）
        svg_p = [p for p in pos if p.lower().endswith(".svg")][0]
        fzz_p = _resolve([p for p in pos if p != svg_p][0], have)
        print("—— 一个 fzz ＋ 一个 svg ⇒ **不比网表** ✗，只出叠合差异图 ✓")
        return _svg_mode(svg_p, fzz_p, out, 40.0)
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
    body = overlay(sa, sb, na, nb)
    # ★★ 把「点清单一条 ⇒ 图上高亮」用的**隐藏图层**塞进去 ✓（2026-10-07 ✓）——
    #   连样式一起写进 svg 本体 ✓ ⇒ 它**单文件也能用** ✓（不是在扩展里才亮 ✓）。
    hits = _hit_layer(ma, mb, sa, sb, na, nb)
    if hits:
        body = body.replace("</svg>",
                            '<style>svg.pd-focus #A, svg.pd-focus #B {opacity:.16}'
                            '</style>\n' + hits + "\n</svg>")
        print("✓ 高亮层：%d 组（点清单里 ① 的条目 ⇒ 扩展会亮对应那组 ✓）"
              % hits.count('<g id="pd-'))
    open(svg_p, "w", encoding="utf-8", newline="\n").write(body)
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
