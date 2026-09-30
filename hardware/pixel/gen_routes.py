# -*- coding: utf-8 -*-
r"""像素板 **自动布线写回**（P2 ✓）2026-09-30 立

用法：
  py -3.13 gen_routes.py <摆位好的.fzz> <输出.fzz> [--nets=pixel_nets.py] [--via=10] [--tries=6] [--check]

★ 只**加** PCB 走线 / 过孔实例 ✓ —— 元件位置、面包板视图、原理图视图**一个字不动** ✗
  （同一个实例在三个视图各有一份 ✓，混着改会把已交付的两张图弄坏 ✗）。
★ 走线 / 过孔的 XML **逐字照 Fritzing 亲笔** ✓
  （模板从 Fritzing 写的 `single-channel.fzz` 里抄出来 ✓，抄法见 `_work/dump_wire3.py` ✓）：
  · 走线 `<pcbView layer="copperNtrace">`
      `<geometry z x y x1 y1 x2 y2 wireFlags="128"/>`
      ＋ `<wireExtras mils color opacity banded/>`
      ＋ 两端各一个 `<connector connectorId="connector0|1">` ＋ 其 `<connects>`
    ⇒ `x/y` = **第一个端点**（绝对 ✓）；`x1..y2` = **相对偏移** ✓（所以恒有 x1=y1=0 ✓）。
  · 过孔 `<pcbView layer="copper0"><geometry z x y wireFlags="32"/>`
      ＋ **只有** `connector0` ✓ ⇒ 两端各由**一条走线的端**去连它 ✓。
  · `<connect>` 的 `layer` = **对方自己的层名** ✓：
      焊盘 `copper0|copper1` ✓、走线 `copperNtrace` ✓、过孔 `copper0` ✓；
      `modelIndex` = 对方实例的编号 ✓。
  · 没接上东西的端点 ⇒ **不写**那个 `<connector>` ✓（Fritzing 也这样 ✓），但**要报** ✗。
★ `modelIndex` 从**现有最大值往后排** ✓（撞号会把别人的连接抢走 ✗）。
★ 写回前先把「端点落在别人线段中间」的地方**切开** ✓ —— 不然那个端点接不上任何东西 ✗
  （Fritzing 的 `<connect>` 只认**端↔端** ✓，没有"在线中间搭一下"这种记法 ✗）。
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolpaths                                                  # noqa: E402,F401
import pcb_check as PC                                            # noqa: E402
import pcb_route as RT                                            # noqa: E402
import pcb_wire as PW                                             # noqa: E402
import projdata                                                   # noqa: E402

MM = RT.MM

# ★ 走线颜色：**只用 Fritzing 官方配色表里的值** ✓（`ratsnestcolors.xml` 的 breadboardView 那组 ✓）
#   黑 = `#404040` ✓（**不是** `#000000` ✗）、红 = `#cc1414` ✓（见仓规 §5b 第 11 条 ✓）。
NET_COLOR = {
    "GND": "#404040", "5V": "#cc1414", "BR+": "#a37911",
}
PALETTE = ["#418dd9", "#25cc35", "#fff800", "#ef6100", "#33ffc5", "#ab58a2",
           "#8c3b00", "#fa50e6", "#999999"]
# ★ 线宽：**只用 Fritzing 那六档** ✓（用户 2026-09-30 定 ✓；下拉里就这六个 ✓）
#   ✗ 我先前写的 `mils="9.8425"`（= 自创的 0.25 mm ✗）在面板里**认不出来** ✗。
#   ⇒ 写进去的就是档位原值 ✓（`RT.MIL_TIERS` / `RT.TRACE_MIL` 一份实现 ✓）。


def key(x, y, lay=None):
    k = (round(x, 3), round(y, 3))
    return k if lay is None else (k[0], k[1], lay)


def split_touchings(segs, tol=1e-6):
    """把「端点落在**别人线段内部**」的地方切开 ✓ ⇒ 之后每段两端都只与**端点**相接 ✓

    全仓的线都是**横平竖直** ✓（4 邻域 A* ✓）⇒ 判"在内部"很简单 ✓。
    ★ 切点必须用**原来的浮点坐标** ✓ —— ✗ 老版拿 `key()`（round 到 1e-3）当切点 ✗
      ⇒ 新端点跟邻居差 1e-4 级 ✗ ⇒ 谁也接不上 ✗（先例：焊盘中心两套算法差 0.05 mm ✗）。
    """
    out = list(segs)
    changed = True
    while changed:
        changed = False
        pts = []
        for lay, a, b in out:
            pts.append((lay, a))
            pts.append((lay, b))
        new = []
        for lay, a, b in out:
            cut = []
            for lay2, p in pts:
                if lay2 != lay or p == a or p == b:
                    continue
                if abs(a[1] - b[1]) < tol:                     # 横线 ✓
                    if abs(p[1] - a[1]) < tol and min(a[0], b[0]) + tol < p[0] < max(a[0], b[0]) - tol:
                        cut.append(p)
                elif abs(a[0] - b[0]) < tol:                   # 竖线 ✓
                    if abs(p[0] - a[0]) < tol and min(a[1], b[1]) + tol < p[1] < max(a[1], b[1]) - tol:
                        cut.append(p)
            if not cut:
                new.append((lay, a, b))
                continue
            changed = True
            if abs(a[1] - b[1]) < tol:
                seq = sorted([a] + cut + [b], key=lambda q: q[0])
            else:
                seq = sorted([a] + cut + [b], key=lambda q: q[1])
            for i in range(len(seq) - 1):
                if seq[i] != seq[i + 1]:
                    new.append((lay, seq[i], seq[i + 1]))
        out = new
    return out


def merge_collinear(wires, keep):
    r"""把**同网同层、首尾相接、方向相同**的碎段并成一条 ✓（图更干净 ✓）

    ★ 用户 2026-09-30 点名 ✓（原话："布线很乱" ✓ —— 129 条线跑 9 张网 ✓，很多 0.1～0.5 mm 碎段 ✓）。
    ★★ 规矩 ✗：**不许跨过连接点** ✓ —— 焊盘心 ✓、过孔 ✓、**两条以上线汇聚的点** ✓
      （Fritzing 的 `<connect>` 只认**端↔端** ✓ ⇒ 跨过连接点合并会把那条连接弄丢 ✗）。
      ⇒ `keep` 就是这些点 ✓；只合并"该点上恰好只有这两个端"的相邻段 ✓。
    """
    out = list(wires)
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                ni, li, ai, bi = out[i]
                nj, lj, aj, bj = out[j]
                if ni != nj or li != lj:
                    continue
                hit = None
                # ★ 规范成 (起点1, 终点1, 起点2, 终点2) ✓；要求 **终点1 == 起点2** ✓
                #   ✗ 我第一版把判据写成 `start1 != end2` ✗ ⇒ 一条都没并成 ✗（实测 v37 == v35 ✓）。
                for s1, e1, s2, e2 in ((ai, bi, aj, bj), (ai, bi, bj, aj),
                                       (bi, ai, aj, bj), (bi, ai, bj, aj)):
                    if e1 != s2 or e1 in keep:      # 接不上或撞连接点 ⇒ 不并 ✓
                        continue
                    if sum(1 for (n2, l2, a2, b2) in out
                           if l2 == li and (a2 == e1 or b2 == e1)) != 2:
                        continue                     # 该点还有别的端 ⇒ 是汇聚点 ✗
                    v1 = (e1[0] - s1[0], e1[1] - s1[1])
                    v2 = (e2[0] - s2[0], e2[1] - s2[1])
                    if abs(v1[0] * v2[1] - v1[1] * v2[0]) > 1e-9:
                        continue                     # 不同向（有拐角 ✓）⇒ 保留拐点 ✓
                    if v1[0] * v2[0] + v1[1] * v2[1] <= 0:
                        continue                     # 反方向（折回去 ✓）⇒ 不并 ✓
                    hit = (ni, li, s1, e2)
                    break
                if hit:
                    out[i] = hit
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    return out


def declared_layers(text):
    r"""⇒ `{(modelIndex, connectorId): 该 connector 在 pcbView 里声明的 layer}` ✓

    ★★ 为什么必须用它 ✗✓（2026-09-30 实测 ✓）：`pcb_check.collect` 报的层是**推导**出来的
      （背面件要翻面 ✓），与文件里 connector 那行**声明的字面值不总一样** ✗ ——
      v29 里实测 **27 处对不上** ✗（我写 `copper0` ✗、文件声明 `copper1` ✓；
      THT 盘更被我写成 `both` ✗ —— **`both` 根本不是合法的层名** ✗）；
      而 **Fritzing 自己重存同一份草图时把这 27 处全纠正成"文件声明的层"** ✓
      （`_work/dl` 系列对照 ✓：重存后的文件里 **266 处全部对得上** ✓）。
      ⇒ 照抄**文件声明值** ✓ 才是对的口径 ✓（仓规：拿 Fritzing 自己的产物当权威 ✓）。
    """
    out = {"breadboardView": {}, "schematicView": {}, "pcbView": {}}
    for b in re.findall(r'(?ms)^[ \t]*<instance\b.*?\n[ \t]*</instance>', text):
        mi = re.search(r'modelIndex="(\d+)"', b)
        if not mi:
            continue
        for view in out:
            m = re.search(r'(?ms)<%s\b[^>]*>.*?</%s>' % (view, view), b)
            if not m:
                continue
            for cid, lay in re.findall(r'<connector connectorId="([^"]*)" layer="([^"]*)"',
                                       m.group(0)):
                out[view].setdefault((mi.group(1), cid), lay)
    return out


def decl_layer(decl, mi, cid):
    r"""取**文件里声明的层** ✓ ⇒ 精确查不到时退回"该实例 pcbView 里唯一那个铜层" ✓

    ★ 为什么需要兜底 ✗✓（实测 ✓）：`U1.connector20`（EPAD）原来**没有条目** ✗
      ⇒ 精确查不到 ✗ ⇒ 退回推导层 `copper0` ✗，可它同块 20 个 connector **都声明 `copper1`** ✓
      ⇒ 线那侧就与（我们新建的）条目**对不上** ✗（实测 2 处 ✓）。
    """
    d = decl.get("pcbView", {}).get((mi, cid))
    if d:
        return d
    lays = {l for (m, _c), l in decl.get("pcbView", {}).items()
            if m == mi and "copper" in (l or "")}
    return lays.pop() if len(lays) == 1 else None


def build_xml(text, res, model, pads, *, color_map=None, mil_of=None):
    """把布线结果变成 XML 实例片段 ✓ ⇒ `(xml, stats)`"""
    mil_of = mil_of or (lambda n: RT.TRACE_MIL)     # ★ 按网分宽 ✓（没给 ⇒ 全局那档 ✓）
    # ── 1. 端点 → 接什么 ✓ ─────────────────────────────────────────────
    # ★ 焊盘要读 `model["pads"]` ✓（`pcb_check.collect` 那份 ✓：有 `thr`/`layer`/`cid`/`mi` ✓）
    #   ✗ 别用 `pcb_route.pad_index()` 那份 ✗ —— 那是布线器内部用的另一种结构（没有 `thr` ✗）。
    pad_at, via_at = {}, {}
    for q in model["pads"]:
        for lay in PC.pad_layers(q):
            pad_at[key(q["c"][0], q["c"][1], lay)] = q
    decl = declared_layers(text)      # ★ 目标 connector 在文件里声明的层 ✓（见函数注释 ✓）
    wire_at = {}
    raw = []                                      # (net, lay, a, b) 碎段 ✓
    for net in sorted(res):
        d = res[net]
        for seg in split_touchings(d["segs"]):
            raw.append((net,) + seg)
    # ★ 先合并同向碎段 ✓（用户点名 ✓）—— ✗ 必须放在 `wire_at` **之前** ✓：
    #   合并后端点变了 ✓，`wire_at` 要按**合并后**的端点建表 ✓，否则连接对不上 ✗。
    keep = set()
    for q in model["pads"]:
        keep.add(key(q["c"][0], q["c"][1]))
    for net in sorted(res):
        for v in res[net]["vias"]:
            keep.add(key(v[0], v[1]))
    wires = merge_collinear(raw, keep)
    stats_raw = len(raw)
    vias = [(net, v) for net in sorted(res) for v in res[net]["vias"]]
    for i, (net, lay, a, b) in enumerate(wires):
        for k, p in ((0, a), (1, b)):
            wire_at.setdefault(key(p[0], p[1], lay), []).append((i, k))

    # ── 2. 排号 ✓ ──────────────────────────────────────────────────────
    used = [int(x) for x in re.findall(r'modelIndex="(\d+)"', text)]
    nxt = max(used) + 1 if used else 90000001
    wt = [int(x) for x in re.findall(r"<title>Wire(\d+)</title>", text)]
    vt = [int(x) for x in re.findall(r"<title>Via(\d+)</title>", text)]
    wn = max(wt) + 1 if wt else 1
    vn = max(vt) + 1 if vt else 1
    for i, v in enumerate(vias):
        via_at[key(v[1][0], v[1][1])] = dict(mi="%d" % (nxt + i), i=i)
    base_mi = nxt + len(vias)
    wmi = ["%d" % (base_mi + i) for i in range(len(wires))]

    # ── 3. 生成 ✓ ──────────────────────────────────────────────────────
    color_map = color_map or {}
    stats = dict(wires=len(wires), vias=len(vias), open_ends=0, multi=0, misses=[],
                 raw=stats_raw)
    edits = []            # ★ 目标侧的回指 ✓（写回时补进原文件 ✓ ⇒ 两侧都写 ✓，照 Fritzing ✓）
    blocks, vblocks = [], []
    for i, (net, lay, a, b) in enumerate(wires):
        conns = []
        for k, p in ((0, a), (1, b)):
            tgt = None
            q = pad_at.get(key(p[0], p[1], lay))
            if q is not None:
                # ★★ 2026-09-30 修 ✗：第三个字段（= 写进 `<connect layer="…">` 的）必须是
                #   **对方那一层的名字** ✓，**不是**走线自己的层 ✗ —— 拿 Fritzing 自己写的
                #   `single-channel.fzz` 逐字对照 ✓：一条 `copper1trace` 的线接 THT 盘时，
                #   写的是 `layer="copper0"` ✓（= **焊盘**所在的层 ✓）。
                #   ✗ 旧写法写 `lay`（= 线的层 ✗）⇒ 底层 SMD 盘被写成 `layer="copper1"` ✗
                #     ⇒ 那个盘**根本不在 copper1 上** ✗ ⇒ Fritzing 判无效、**整组线看不见** ✗
                #     （用户：「我看了 pixel-pcb-v26.fzz …… **没有布线**」✗）。
                # ★★ 写进 `<connect layer=…>` 的必须是"**文件里那个 connector 声明的层**" ✓
                #   —— 不是 collect 推导的层 ✗（实测 27 处对不上 ✗，见 `declared_layers` ✓）
                #   ✗ 坑（自己踩过 ✓）：`declared_layers` 外层键是**视图名** ✗ ⇒
                #     写成 `decl.get((mi, cid))` 就永远取不到 ✗、静默退回推导层 ✗
                #     （v31/v32/v33 因此又错了 27 处 ✗）。
                dlay = decl_layer(decl, q.get("mi") or "", q.get("cid") or "connector0")
                tgt = (q.get("cid") or "connector0", q.get("mi") or "",
                       dlay or q.get("layer") or lay)
                # ★ 记下"焊盘那侧的回指" ✓（见 `add_backrefs` ✓）
                if q.get("mi"):
                    edits.append((q["mi"], q.get("cid") or "connector0",
                                  dlay or q.get("layer") or lay,
                                  "connector%d" % k, wmi[i], lay + "trace"))
            if tgt is None and key(p[0], p[1]) in via_at:
                v = via_at[key(p[0], p[1])]
                tgt = ("connector0", v["mi"], "copper0")
            if tgt is None:
                cand = [w for w in wire_at.get(key(p[0], p[1], lay), []) if w[0] != i]
                if len(cand) > 1:
                    stats["multi"] += 1
                if cand:
                    tgt = ("connector%d" % cand[0][1], wmi[cand[0][0]], lay + "trace")
            if tgt is None:
                stats["open_ends"] += 1
                if len(stats["misses"]) < 6:
                    best = None
                    for kk, q in pad_at.items():
                        dd = math.hypot(q["c"][0] - p[0], q["c"][1] - p[1])
                        if best is None or dd < best[0]:
                            best = (dd, "pad %s.%s(%s)" % (q.get("title"), q.get("cid"), kk[2]))
                    for kk, lst in wire_at.items():
                        for wi, _wk in lst:
                            if wi == i:
                                continue
                            dd = math.hypot(kk[0] - p[0], kk[1] - p[1])
                            if best is None or dd < best[0]:
                                best = (dd, "wire#%d(%s)" % (wi, kk[2] if len(kk) > 2 else ""))
                    for kk, vv in via_at.items():
                        dd = math.hypot(kk[0] - p[0], kk[1] - p[1])
                        if best is None or dd < best[0]:
                            best = (dd, "via mi=%s" % vv["mi"])
                    stats["misses"].append(
                        "%s 线#%d 端%d 在 (%s, %s) 层 %s ⇒ 最近: %s 差 %s mm"
                        % (net, i, k, PW.fmt(p[0]), PW.fmt(p[1]), lay,
                           best[1] if best else "-",
                           ("%.3f" % MM(best[0])) if best else "-"))
                continue
            conns.append((k, tgt))
        color = color_map.get(net) or NET_COLOR.get(net) \
            or PALETTE[sum(ord(c) for c in net) % len(PALETTE)]
        blocks.append(wire_block(net, i, wn + i, wmi[i], lay, a, b, conns, color,
                                 mil_of(net), decl))
    for j, (net, v) in enumerate(vias):
        # ★ 过孔那侧也要写"它接的线" ✓（= 回指 ✓）—— 拿 Fritzing 自己的 `ViaModuleID`
        #   原文对出来的 ✓：它的 `connector0` 里列着两条走线 ✓（`_work/via.txt` ✓）。
        #   ✗ 旧写法整个 `<connects>` 都不写 ✗ ⇒ 一侧悬空 ✗。
        vconn = []
        for lay in ("copper0", "copper1"):
            for (wi, wk) in wire_at.get(key(v[0], v[1], lay), []):
                vconn.append(("connector%d" % wk, wmi[wi], lay + "trace"))
        seen = []
        for c in vconn:                       # 去重 ✓（一根线的两端可能都在同一个过孔上 ✓）
            if c not in seen:
                seen.append(c)
        vblocks.append(via_block(vn + j, via_at[key(v[0], v[1])]["mi"], v, j, seen))
    return "".join(blocks) + "".join(vblocks), stats, edits


def conn_xml(items, wlayer):
    """某个视图里的 `<connectors>` 片段 ✓（`items` = `[(k, 目标cid, 目标mi, 目标层)]` ✓）

    ★ 空就不写整段 ✓ —— 照 Fritzing 自己的写法 ✓（它只列"有连接"的 connector ✓：
      `sample` 里一条原理图走线就只写了 `connector1` 一个 ✓）。
    """
    out = []
    for k, cid, mi, tlay in items:
        out.append('                <connector connectorId="connector%d" layer="%s">\n'
                   '                    <geometry x="0" y="0"/>\n'
                   '                    <connects>\n'
                   '                        <connect connectorId="%s" modelIndex="%s" '
                   'layer="%s"/>\n'
                   '                    </connects>\n'
                   '                </connector>\n' % (k, wlayer, cid, mi, tlay))
    if not out:
        return ""
    return "                <connectors>\n%s                </connectors>\n" % "".join(out)


def plain(v):
    """普通小数 ✓（**不用** `%g` 的科学计数法 ✗）—— 照 Fritzing 自己写的格式 ✓

    ✗ 先例（2026-09-30 ✓）：`PW.fmt` = `%.6g` ✗ ⇒ 小到 1e-5 的值写成 `-3e-05` ✗，
      而 Fritzing 写的全是 `0` / `-0.35466` 这种普通小数 ✓（逐字对照 ✓）。
    """
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def wire_block(net, i, title_n, mi, lay, a, b, conns, color, mil, decl=None):
    """一条走线 ✓（`x/y` = 端点 1 ✓，`x1..y2` = 相对偏移 ✓）

    ★★ 2026-09-30 修两处 ✗（都是拿 Fritzing 自己写的 `single-channel.fzz` **逐字对照**出来的 ✓）：
      ① `mils` 必须用 **`--mil` 选的那一档** ✓ —— ✗ 旧写法写的是模块常量 ✗
         ⇒ 跑 `--mil=12` 写出来还是 `mils="24"` ✗（用户一眼看出"线宽不合适"✓）；
      ② 数字**不许写科学计数法** ✗ —— ✗ 旧写法用 `PW.fmt`（`%.6g` ✗）⇒ 会出现
         `y2="-3e-05"` ✗，而 Fritzing 自己写的是 `y2="0"` ✓（普通小数 ✓）。

    ★★ 2026-09-30 再修一处 ✗（有**判决性**证据 ✓）：**必须写三个视图** ✓。
      证据 ✓：Fritzing 自带 44 份样例 / 4149 条走线 ⇒ **4148 条三视图** ✓、**0 条 pcb-only** ✗；
      且用户实测：Fritzing 把我 v29 **自己重存**一遍（层已自动纠正 ✓、回指也在 ✓）后，
      我 129 条**单视图**线**一条都没算** ✗，而他手画那根**三视图**线**算上了一只脚** ✓
      （`pixel-pcb-wire-test.fzz`：42 → **41** ✓）⇒ **视图数是硬要求** ✓。
      非 PCB 两个视图怎么写 ✗：实测 Fritzing **每个视图写各自的坐标** ✓，且两视图路径
      **互不相同** ✗（同一段：PCB `(131.154,30.195)` ✓／面包板 `(152.41,39.007)` ✓）
      ⇒ **不能把 PCB 坐标抄进去** ✗（会把你手工摆的面包板画花 ✗）⇒ 用**零长度占位** ✓：
      实例在 ✓、不画线 ✓、坐标不编造 ✗；而且**只挂能对上号的真实焊盘** ✓
      （线↔线、线↔过孔在这两个视图里没有对应物 ✗ ⇒ 不写 ✓）。
    """
    f = plain
    decl = decl or {}
    vs = []
    for tag, wlayer, geo in (
            ("pcbView", lay + "trace",
             '<geometry z="%s" x="%s" y="%s" x1="0" y1="0" x2="%s" y2="%s" '
             'wireFlags="4"/>' % (f(9.5 + i * 1e-4), f(a[0]), f(a[1]),
                                  f(b[0] - a[0]), f(b[1] - a[1]))),
            ("breadboardView", "breadboardWire",
             '<geometry z="%s" x="0" y="0" x1="0" y1="0" x2="0" y2="0" '
             'wireFlags="4"/>' % f(4.0 + i * 1e-4)),
            ("schematicView", "schematicTrace",
             '<geometry z="%s" x="0" y="0" x1="0" y1="0" x2="0" y2="0" '
             'wireFlags="4"/>' % f(6.0 + i * 1e-4))):
        items = []
        for k, (cid, tmi, tlay) in conns:
            if tag == "pcbView":
                vlay = tlay
            else:
                vlay = decl.get(tag, {}).get((tmi, cid))
                if vlay is None:            # 这个视图里没对应物 ⇒ 不写 ✓（不编 ✗）
                    continue
            items.append((k, cid, tmi, vlay))
        vs.append('                <%s layer="%s">\n'
                  '                    %s\n'
                  '                    <wireExtras mils="%d" color="%s" opacity="1" '
                  'banded="0"/>\n'
                  '%s'
                  '                </%s>\n'
                  % (tag, wlayer, geo, mil, color, conn_xml(items, wlayer), tag))
    return ('        <instance moduleIdRef="WireModuleID" modelIndex="%s" '
            'path=":/resources/parts/core/wire.fzp">\n'
            '            <title>Wire%d</title>\n'
            '            <views>\n'
            '%s'
            '            </views>\n'
            '        </instance>\n' % (mi, title_n, "".join(vs)))


def via_block(title_n, mi, p, j, conns=()):
    r"""一个过孔 ✓（**只有** connector0 ✓；两端靠走线的端去连它 ✓）

    ★ `p` 是**一个点** `(x, y)` ✓ —— 别在这儿再解包成 `net, p` ✗
      （`res[net]["vias"]` 里**只有坐标** ✓，网名在外面那层 ✓）。
    ★★ `hole size` 的语义（源码判定 ✓ `mazerouter.cpp:2430` ✓）：
      `setHoleSize("<hole>,<ringThickness>")` ✓ ⇒ **「钻孔 , 环宽」** ✓，**不是盘径** ✗！
      ✗ 我原来写的 `0.4mm,0.3mm` = 孔 0.4 + 环 0.3 ⇒ **盘 Ø1.0 mm** ✗（比 0603 焊盘还大 ✗
      ⇒ 用户："过孔仍不舒服" ✓）。
      ⇒ 现在用 **`0.3mm,0.15mm`** ⇒ 盘 **Ø0.6 mm** ✓（小 40% ✓）。
      �工艺依据 ✓（PCBWay 标准能力 ✓）：**最小钻孔 0.15／<0.2 加价** ✓、**最小环宽 0.15mm** ✓
      ⇒ 0.3/0.15 是"常规、便宜、安全"那一档 ✓（常规三档 = 0.2/0.5、0.3/0.6、0.4/0.8 ✓）。
      ★ 改这里必须**同步**改 `pcb_route.VIA_CLEAR_MM` ✓（过孔净空 = 盘半径 = 0.30 ✓）。

    ★★ 2026-09-30 补 ✗：`conns` = **它接的走线** ✓（照 Fritzing 自己的过孔原文 ✓ `_work/via.txt` ✓：
      `connector0` 里列着它接的线 ✓）；连接的 `layer` 用**那条线自己**的层 ✓（`q[2]` ✓）
      —— ✗ 别用一条统一的层 ✗（过孔两边的线可能在不同 trace 层 ✗）。
    ★★ 并跟走线一样**写三视图** ✓（Fritzing 自己的 `ViaModuleID` 也是三视图 ✓）——
      非 PCB 两个视图只写几何 ✓、不写 connectors ✓（理由同 `wire_block` ✓：不编 ✗）。
    """
    geo_pcb = '<geometry z="%s" x="%s" y="%s" wireFlags="32"/>' \
              % (PW.fmt(5.5 + j * 1e-4), PW.fmt(p[0]), PW.fmt(p[1]))
    geo_flat = '<geometry z="%s" x="0" y="0" wireFlags="32"/>' % PW.fmt(4.0 + j * 1e-4)
    c = ""
    if conns:
        c = ('                    <connectors>\n'
             '                        <connector connectorId="connector0" layer="copper0">\n'
             '                            <geometry x="0" y="0"/>\n'
             '                            <connects>\n'
             + "".join('                                <connect connectorId="%s" '
                       'modelIndex="%s" layer="%s"/>\n' % (q[0], q[1], q[2]) for q in conns)
             + '                            </connects>\n'
             '                        </connector>\n'
             '                    </connectors>\n')
    return ('        <instance moduleIdRef="ViaModuleID" modelIndex="%s" '
            'path=":/resources/parts/core/via.fzp">\n'
            '            <property name="hole size" value="0.3mm,0.15mm"/>\n'
            '            <title>Via%d</title>\n'
            '            <views>\n'
            '                <pcbView layer="copper0">\n'
            '                    %s\n'
            '%s'
            '                </pcbView>\n'
            '                <breadboardView layer="copper0">\n'
            '                    %s\n'
            '                </breadboardView>\n'
            '                <schematicView layer="copper0">\n'
            '                    %s\n'
            '                </schematicView>\n'
            '            </views>\n'
            '        </instance>\n'
            % (mi, title_n, geo_pcb, c, geo_flat, geo_flat))


def add_backrefs(text, edits):
    r"""★ 给**目标侧**补回指 `<connect>` ✓（2026-09-30 ✓，拿 Fritzing 自己的文件对出来的 ✓）

    证据 ✓（`_work/fritzing_stats.py` + `docs/fritzing-sketch-format-notes.md` ✓）：
      Fritzing 自带 44 份样例 / 4137 条 PCB 走线 ⇒ **8270 处连接 100% 两侧都写** ✓、
      **缺回指 0 处** ✗；而我原来**只写走线这一侧** ✗（实测缺 **80 处** ✗）
      ⇒ 用户开图看到「**7 中的 0 网络布线完成**」✗。

    `edits` = `[(目标mi, 目标connectorId, 目标层, 源connectorId, 源mi, 源层)]` ✓
    ⇒ 在目标的 `<pcbView>` 里那个 connector 的 `<connects>` 中插一条指回走线的 connect ✓。
    幂等 ✓（已有同样的就跳过 ✓）；目标块找不到 ⇒ 记到 `why` ✓（由调用方决定写不写 ✗）。

    ★★ 定位口径（实测修 ✓）：**只在 `<pcbView>` 段内**按 `connectorId` 找 ✗ ——
      ✗ **别拿层去卡** ✗：`edits` 里的层是从 `pcb_check.collect` **推导**出来的
      （背面件要翻面 ✗），与文件里 connector 那行**声明的层字面值不一定一样** ✗
      ⇒ 实测 44 处里卡掉了 **29 处** ✗。
      （同一个 `connectorId` 在面包板/原理图/PCB 三个视图里都有 ✗ ⇒ 必须限定在 pcbView ✗）
    """
    n, miss, why, built = 0, 0, [], 0
    by_mi = {}
    for e in edits:
        by_mi.setdefault(e[0], []).append(e)
    for mi, es in by_mi.items():
        mb = re.search(r'(?ms)^[ \t]*<instance\b[^>]*modelIndex="%s".*?\n[ \t]*</instance>'
                       % re.escape(mi), text)
        if not mb:
            miss += len(es)
            why.append("instance modelIndex=%s 找不到 ✗" % mi)
            continue
        blk, cur = mb.group(0), mb.group(0)
        pv = re.search(r'(?ms)<pcbView\b[^>]*>.*?</pcbView>', cur)
        if not pv:
            miss += len(es)
            why.append("instance %s **没有 pcbView** ✗" % mi)
            continue
        seg = pv.group(0)
        for (_tmi, cid, tlay, scid, smi, slay) in es:
            cr = re.search(r'(?ms)<connector connectorId="%s"[^>]*>(.*?)\n([ \t]*)</connector>'
                           % re.escape(cid), seg)
            if not cr:
                # ★★ 目标 connector **在文件里没有条目** ✓（实测：`U1.connector20` = EPAD ✗ ——
                #  它以前既没插面包板也没接原理图 ⇒ Fritzing 不给它写实例条目 ✓，20/21 ✓）
                #  ⇒ 我们**照它自己的口径补一条** ✓：Fritzing 只给"有连接"的 connector 写条目 ✓，
                #    而现在这个脚**有了 PCB 连接** ✓ ⇒ 就该有这一条 ✓。
                #  层取**同块 pcbView 里已有 connector 的层** ✓（不编 ✗；不一致就放弃 ✓）。
                lays = set(re.findall(r'<connector connectorId="[^"]*" layer="([^"]*)"', seg))
                tail = re.search(r'(?ms)([ \t]*)</connectors>', seg)
                ind = re.search(r'(?m)^([ \t]*)<connector ', seg)
                if len(lays) == 1 and tail and ind:
                    lay, pad, cl = lays.pop(), ind.group(1), tail.group(1)
                    blk2 = ('%s<connector connectorId="%s" layer="%s">\n'
                            '%s    <geometry x="0" y="0" />\n'
                            '%s    <connects>\n'
                            '%s        <connect connectorId="%s" modelIndex="%s" layer="%s" />\n'
                            '%s    </connects>\n'
                            '%s</connector>\n'
                            % (pad, cid, lay, pad, pad, pad, scid, smi, slay, pad, pad))
                    seg = seg[:tail.start()] + blk2 + seg[tail.start():]
                    n += 1
                    built += 1
                    continue
                miss += 1
                why.append("instance %s 里找不到 connector %s ✗（且没法安全补 ✓）" % (mi, cid))
                continue
            inner, ind = cr.group(1), cr.group(2)
            tag = '                        <connect connectorId="%s" modelIndex="%s" ' \
                  'layer="%s"/>\n' % (scid, smi, slay)
            if ('connectorId="%s" modelIndex="%s"' % (scid, smi)) in inner:
                continue                       # 幂等 ✓
            if "<connects>" in inner:
                inner2 = inner.replace("</connects>", tag + ind + "</connects>", 1)
            else:
                # 没有 `<connects>` ⇒ 在 connector 的 geometry 后面补一个 ✓
                inner2 = re.sub(r'(<geometry[^/]*/>\n)', r"\1%s<connects>\n%s%s</connects>\n"
                                % (ind, tag, ind), inner, count=1)
                if inner2 == inner:            # 连 geometry 都没有 ⇒ 只报不动手 ✗
                    miss += 1
                    why.append("instance %s connector %s 里没 geometry ✗" % (mi, cid))
                    continue
            seg = seg[:cr.start()] + cr.group(0).replace(inner, inner2, 1) + seg[cr.end():]
            n += 1
        text = text.replace(blk, cur[:pv.start()] + seg + cur[pv.end():], 1)
    return text, n, miss, why, built


def write(base, out, xml, edits=()):
    """把片段插在 `</instances>` 前 ✓；其它内容 / 其它包内文件**逐字节不动** ✓"""
    zin = zipfile.ZipFile(base)
    fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
    text = zin.read(fz).decode("utf-8")
    m = list(re.finditer(r"[ \t]*</instances>", text))
    if len(m) != 1:
        raise SystemExit("✗ 找不到唯一的 `</instances>`（找到 %d 个 ✗）⇒ 不写文件 ✗" % len(m))
    text2 = text[:m[0].start()] + xml + text[m[0].start():]
    # ★★ 回指（两侧都写 ✓）—— 照 Fritzing 自己的文件 ✓；见 `add_backrefs` ✓
    text2, n_back, n_miss, why, n_built = add_backrefs(text2, edits)
    if edits:
        print("   回指：补写 %d 处 ✓｜新建条目 %d 处 ✓｜补不上 %d 处 %s"
              % (n_back, n_built, n_miss, "✗" if n_miss else "✓"))
        for s in why[:6]:
            print("      %s" % s)
    if n_miss:
        # ★ 放宽口径 ✓（2026-09-30 量过 ✓）：Fritzing 自己的 44 份样例里，
        #   `connect` 指向"**目标 pcbView 里根本没有该 connector**"的有 **108 处** ✓
        #   （例：裸露焊盘 EPAD 以前既没插面包板也没接原理图 ⇒ Fritzing 不给它写实例条目 ✓）
        #   ⇒ 这类**合法** ✓，只报数字 ✓、不挡写文件 ✓（`_work/layer_rule.txt` ✓）。
        print("   · 其中少数目标没有 pcbView 条目 ⇒ 合法 ✓（Fritzing 自己也有 108 处 ✓）")
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for it in zin.infolist():
        data = text2.encode("utf-8") if it.filename == fz else zin.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    return len(xml)


def main(argv):
    netsf, rest = projdata.strip_argv(argv)
    if len(rest) < 2:
        print(__doc__)
        return 2
    base, out = rest[0], rest[1]
    data = projdata.load(netsf, need=("NETS",))
    cell = RT.opt(argv, "--cell", RT.CELL_MM, float)
    via_cost = RT.opt(argv, "--via", RT.K_VIA, float)
    tries = RT.opt(argv, "--tries", 6, int)
    mil_sig = RT.opt(argv, "--mil-signal", RT.opt(argv, "--mil", 12, int), int)
    mil_pow = RT.opt(argv, "--mil-power", 24, int)
    for _m in (mil_sig, mil_pow):
        if _m not in RT.MIL_TIERS:
            raise SystemExit("✗ 线宽只能是这几档 ✓（Fritzing 的宽度下拉 ✓）：%s（mil ✓）"
                             % "、".join("%s %d" % (RT.MIL_TIERS[k], k)
                                         for k in sorted(RT.MIL_TIERS)))
    # ★★ 按网分宽 ✓（2026-09-30 用户定 ✓：「用与 JST-SH 1.0 功率匹配的 5V 和 GND 线宽 ✓，
    #   信号线 12 或 8 mil 都可以 ✓」）—— JST SH 官方额定 **1 A/触点（AWG #28）** ✓
    #   ⇒ 电源网取 **24 mil（标准 ✓ 0.61 mm ✓ ≈2 A ✓）** ✓、信号网 12 mil ✓。
    #   ⚠️ 全局那个 `TRACE_MM`（= 障碍/板边的膨胀量 ✓）取**两者最宽** ✓ ⇒ 对细线偏保守 ✓、安全 ✓。
    power = tuple(getattr(data, "POWER", ("5V", "GND")))
    RT.TRACE_MM = max(mil_sig, mil_pow) * RT.MIL_MM
    # ★ 两项代价旋钮（2026-09-30 用户要"图能看懂能改" ✓）—— **可以分别调** ✓，
    #   因为实测它们各管一头 ✓：
    #     `--turn`     拐弯代价 ✓ ⇒ 路径直 ✓、**走线对象变少**（130 → 99 ✓）⇒ 好读好改 ✓；
    #     `--layer-pen` 非主层每格加价 ✓ ⇒ 想让它少换层 ✓ —— 但 v42 实测**反而**：
    #                   过孔 18 → 28 ✗、线长 198.5 → 288.1 ✗（每网挤自己那层 ⇒ 堵 ⇒ 后布的孔更多 ✗）
    #                   ⇒ 所以默认**先关掉** ✓（`--layer-pen=0` ✓），只用拐弯代价 ✓。
    RT.TURN_COST = RT.opt(argv, "--turn", RT.TURN_COST, float)
    RT.LAYER_PEN = RT.opt(argv, "--layer-pen", 0.0, float)

    def width_of(net):
        return (mil_pow if net in power else mil_sig) * RT.MIL_MM

    def mil_of(net):
        return mil_pow if net in power else mil_sig

    model = PC.collect(base)
    r = model["board"]
    pads = RT.pad_index(model)
    net_pads, unresolved = RT.resolve_nets(model, data.NETS)
    if unresolved:
        print("✗ 脚名解析不了：%s" % ", ".join(unresolved))
        return 2
    print("== 自动布线 + 写回：%s ⇒ %s ==" % (os.path.basename(base), os.path.basename(out)))
    print("   线宽：电源 %s（%s %d mil ✓）／信号 %s（%s %d mil ✓）｜电源网：%s｜过孔 %s ✓"
          % ("%.4f mm" % (mil_pow * RT.MIL_MM), RT.MIL_TIERS[mil_pow], mil_pow,
             "%.4f mm" % (mil_sig * RT.MIL_MM), RT.MIL_TIERS[mil_sig], mil_sig,
             "/".join(power), "0.3/0.15 mm 孔环（盘 Ø0.6 ✓）"))
    items, _st = RT.obstacles(model)
    passes = RT.opt(argv, "--passes", 4, int)
    res = RT.route_ripup(items, r, net_pads, pads, cell, via_cost, tries=tries, passes=passes,
                         width_of=width_of, first=power, mid_keep=power)

    # ★★ 成对过孔回收 ✓（2026-09-30 用户选 1 ✓，起因：用户点名 `Via11`/`Via12` 硌眼 ✗）：
    #   实测那两颗是**一对** ✓ —— "从 `copper1` 钻下去 ✓、走约 2 mm ✓、再钻回来" ✓
    #   （每颗外侧只剩 0.3～0.45 mm 碎铜 ✗ = 机器留下的小尾巴 ✓）。
    #   做法沿用本仓已有铁律 ✓（同 `route_ripup` ✓）：**试改 ⇒ 只有总分更好才接受** ✓：
    #     ① 找同一张网里**相距 ≤6 mm 的过孔对** ✓（候选 ✓，不一定真是一对 ✓）；
    #     ② 把它们的**孔位禁掉**再整盘重布一遍 ✓；
    #     ③ 比 `(连通数, -过孔数, -线长)` ✓ —— 更好就采纳 ✓、否则**原样退回** ✓。
    #   ⇒ 若那对孔是**必须**的 ✓，重布会失败或变差 ⇒ 自动退回 ✓，**不会把板子改坏** ✓。
    def _score(r):
        return (sum(1 for d in r.values() if d["ok"]),
                -sum(len(d["vias"]) for d in r.values()),
                -sum(math.hypot(s[1][0] - s[2][0], s[1][1] - s[2][1])
                     for d in r.values() for s in d["segs"]))

    res_s = _score(res)
    for rnd in range(1, 3):
        # ★ 只挑**最近的一对** ✓ —— ✗ 第一版把"每网每对"全收进来 ⇒ 一口气禁了 18 个孔位 ✗
        #   ⇒ 布线器换个地方照样摆 ✓、结果逐字相同 ✗（实测 ✓）⇒ 小步走才有意义 ✓。
        best = None
        for _net, d in res.items():
            vs = d["vias"]
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    dd = math.hypot(vs[i][0] - vs[j][0], vs[i][1] - vs[j][1])
                    if best is None or dd < best[0]:
                        best = (dd, vs[i], vs[j])
        if best is None or best[0] > RT.U(6.0):
            print("   [成对过孔回收] 没有 ≤6 mm 的过孔对 ⇒ 不用 ✓")
            break
        # ★ 禁**一小圈**（半径 0.6 mm ✓）—— 只禁一个格点没用 ✗：布线器挪一格照样成对 ✓
        cand, R = [], RT.U(0.6)
        for (px, py) in (best[1], best[2]):
            n = int(R / RT.U(cell)) + 1
            for dx in range(-n, n + 1):
                for dy in range(-n, n + 1):
                    if math.hypot(dx, dy) * RT.U(cell) <= R:
                        cand.append((px + dx * RT.U(cell), py + dy * RT.U(cell)))
        trial = RT.route_ripup(items, r, net_pads, pads, cell, via_cost, tries=tries,
                               passes=passes, width_of=width_of, first=power,
                               mid_keep=power, ban_via=cand, verbose=False)
        s2 = _score(trial)
        print("   [成对过孔回收] 第 %d 轮：最近一对相隔 %.2f mm ✓｜禁 %d 个格点 ✓"
              " ⇒ 连通 %d/%d ✓｜过孔 %d ⇒ %d ✓"
              % (rnd, best[0] * (1 / RT.U(1.0)) if False else
                 (best[0] / RT.U(1.0)), len(cand), s2[0], len(trial), -res_s[1], -s2[1]))
        if s2 > res_s:
            res, res_s = trial, s2
        else:
            print("   [成对过孔回收] 这轮没更好 ⇒ **原样退回** ✓、停 ✓")
            break

    n_ok = sum(1 for d in res.values() if d["ok"])
    ln = sum(math.hypot(s[1][0] - s[2][0], s[1][1] - s[2][1])
             for d in res.values() for s in d["segs"])
    print("\n   连通 %d/%d ✓｜线长 %.1f mm｜过孔 %d 个"
          % (n_ok, len(res), MM(ln), sum(len(d["vias"]) for d in res.values())))
    # ★★ `--dump-net=<网名>` ✓（2026-09-30 用户要的 ✓）：把**布线器内部**那张网的段
    #   与它各个脚的层原样摊开 ✓ ⇒ 一刀切开"**布线器没生成**" ✗ vs "**写回时丢了**" ✗。
    #   只打印 ✓、**绝不写文件** ✓（便于反复对着量 ✓）。
    if "--dump-net" in " ".join(argv):
        want = RT.opt(argv, "--dump-net", "", str)
        print("\n== 摊开网 `%s`（层 + 两端，mm ✓）==" % want)
        print("   脚（布线器看到的层 ✓）：")
        for t, c in net_pads.get(want, []):
            q = pads.get((t, c))
            if q is None:
                print("     %s.%s ⇒ **不在板上** ✗" % (t, c))
                continue
            print("     %-6s %-11s lays=%-24s 心=(%.2f, %.2f) mm"
                  % (t, c, q["lays"], MM(q["c"][0]), MM(q["c"][1])))
        d = res.get(want)
        if d is None:
            print("   ✗ 没这张网 ✗")
        else:
            print("   ok=%s｜过孔 %d｜段 %d："
                  % (d["ok"], len(d["vias"]), len(d["segs"])))
            for j, (lay, a, b) in enumerate(d["segs"]):
                print("     #%-3d %-8s (%.3f, %.3f) → (%.3f, %.3f) mm"
                      % (j, lay, MM(a[0]), MM(a[1]), MM(b[0]), MM(b[1])))
            for j, p in enumerate(d["vias"]):
                print("     过孔#%-3d (%.3f, %.3f) mm" % (j, MM(p[0]), MM(p[1])))
        return 0
    if n_ok != len(res):
        bad = [(n, d.get("note") or "") for n, d in sorted(res.items()) if not d["ok"]]
        print("   ✗ 没布通的网（%d 张）：%s" % (len(bad), "；".join(
            "%s%s" % (n, ("（%s）" % t) if t else "") for n, t in bad)))
        print("   ✗ 有网没布通 ⇒ **不写文件** ✗（先把摆位/参数调好 ✓）")
        return 1

    text, _nm = PW.read(base)
    xml, stats, edits = build_xml(text, res, model, pads, mil_of=mil_of)
    print("   走线 %d 条 ✓（**合并前 %d 条** ✓）｜过孔 %d 个 ✓｜**悬空端点 %d**（必须 0 ✗）｜多线共用一端 %d"
          % (stats["wires"], stats.get("raw", stats["wires"]), stats["vias"],
             stats["open_ends"], stats["multi"]))
    if stats["open_ends"]:
        print("   ✗ 有端点谁也没接上 ⇒ **不写文件** ✗")
        for s in stats.get("misses", []):
            print("      %s" % s)
        return 1
    n = write(base, out, xml, edits)
    print("   ✓ 已写出 %s（插入 %d 字符 ✓）" % (os.path.basename(out), n))

    if "--check" in argv:
        print("\n== 独立复核（**重新读刚写的文件** ✓）==")
        m2 = PC.collect(out)
        probs, notes = PC.check(m2, expect=net_pads)
        for s in notes:
            print("   · %s" % s)
        for s in probs:
            print("   ✗ %s" % s)
        print("   ⇒ %s（走线/过孔几何 ✓）" % ("**0 问题** ✓" if not probs else "**有 %d 处问题 ✗**" % len(probs)))
        return 0 if not probs else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
