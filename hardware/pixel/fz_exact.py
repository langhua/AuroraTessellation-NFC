# -*- coding: utf-8 -*-
r"""★★ **照 Fritzing 源码逐条实现**的「接线 / 连通」判据 ✓（只读 `.fzz` ✓，只写屏 ✓）——

目的 ✓（用户 2026-10-02 定，见 `AGENTS.md` §13 ✓）：**只说一个声音** ✓ ——
我报的东西必须能用 Fritzing 的**同一句话**指同一件事 ✓，用户才好照着手工改 ✓。

## 逐条对应（都可复查 ✓）

| 我这里的做法 | Fritzing 源码 |
|---|---|
| ★★ **分网**（谁跟谁算同一个网 ✓）：沿 `connectedToItems` 走 ✓ ＋ 跨层同脚 ✓ ＋ **同 `bus()`** ✓；**只跳过带 `RatsnestFlag` 的走线** ✓（走线的**其它** flags 不参与分网 ✗） | `sketch/sketchwidget.cpp:6998`：`ConnectorItem::collectEqualPotential(connectorItems, true, ViewGeometry::RatsnestFlag)` ✓ ⇒ `connectoritem.cpp:1340` ✓（`busConnectorItems` 那一段 ✓需 `skipBuses==false` ✓）|
| 网的**节点只留"件脚"** ✓（走线/过孔/跳线不算节点 ✓、单脚的网不数 ✓） | 同处 `sketchwidget.cpp:7013`：`ConnectorItem::collectParts(…, includeSymbols(), ViewLayer::NewTopAndBottom)` ＋ `if (partConnectorItems.count() <= 1) continue;` ✓ |
| PCB 的「算不算铜」闸门 = `wireFlags & 4` ✓ | `sketch/pcbsketchwidget.cpp:1983`：`PCBSketchWidget::getTraceFlag()` ⇒ `ViewGeometry::PCBTraceFlag` ✓ |
| ★ 闸门**只作用在与脚直接相接的那条走线**上 ✓ | `utils/graphutils.cpp:550`：`if (!(wire->getViewGeometry().wireFlags() & myTrace)) continue;` —— 那个 `wire` 就是 `toConnectorItem->attachedTo()` = 与脚相接的那条 ✓ |
| 线串成链时**穿过过孔**继续走 ✓ | `items/wire.cpp:1137` `Wire::collectChained` ✓ —— Fritzing 的**过孔就是 `Wire`**（`moduleIdRef="ViaModuleID"` ✓）⇒ 链里当走线穿 ✓、**不当连接件数** ✓ |
| 链上遇到不是线的（脚）才算「链端」 ✓ | `items/wire.cpp:1146` `collectChained(connectorItem,…)`：`qobject_cast<Wire*>` 为空 ⇒ 收进 `ends` ✓ |
| 判**接没接上**用**几何**（真矩形/真圆 ✓），不信文件里那份 `<connect>` 缓存 ✓ | `connectors/connectoritem.cpp:1972`：`scene()->items(sceneAdjustedTerminalPoint())` = **场景命中测试** ✓（点落在对方**自己的形状**里 ✓）—— **不是**"离盘心多近" ✗，也**不是**"文件里写着连着" ✗ |
| 同件同 `bus()` 的脚直接相连 ✓ | `scoreOneNet`：`if (to->bus() == from->bus()) add_edge(…)` ✓ |
| **不同件的两只脚只算"有用户连接"、不加边** ✗ | `scoreOneNet`：`if (to->attachedTo() != from->attachedTo()) { gotUserConnection = true; continue; }` ✓ |
| 一整网**没有任何用户连接** ⇒ **不数它** ✓ | `if (!gotUserConnection) return false;` ✓ ⇒ `m_netCount++` ✓ |
| ★★ **「还剩几个连接件」= 该网的连通片数 − 1** ✓（**不是**没连上的脚数 ✗） | `scoreOneNet` 末尾的 `check[]` 扫法 ✓（已被覆盖的 j 划掉 ✓ ⇒ 等价于"片数 − 1" ✓）。源码注释原话：*we can minimally span the set with n-1 wires, so even if multiple connections are missing from a given connector, **count it as one*** ✓ |
| 状态栏那句 ✓ | `mainwindow/mainwindow.cpp:2298`：`"%1 of %2 nets routed - %n connector(s) still to be routed"` ✓ |

★ 已知还差一口 ✓（**老实写在这里 ✗**）：拿本板 `pixel-pcb-v59.fzz` 量，本判据给
**9 个网 / 全通** ✗，而用户 Fritzing 截图是 **7 个网 / 还有 2 个连接件** ✓ ⇒ 还差**一条**我
没读到的规则（网数 9≠7 ✓、以及那 2 个"没布"是怎么来的 ✗）。**不要用猜的补齐** ✗ ——
要么再回源码找 ✓，要么请用户在 Fritzing 里点一下那两条虚线的两端是什么 ✓（见 `AGENTS.md` §13 ✓）。


用法 ✓：`fz_exact.py <sketch.fzz>`（`--flags=N` 可换闸门做对照 ✓）。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# ★ 两个仓是**兄弟目录**（`f:\git\<仓>` ✓）⇒ 用相对位置推 ✓；✗ 别写死本机盘符
#   （`AGENTS.md` §5「脚本不得依赖仓库外文件」的精神 ✓ —— 换机器/换盘符还能跑 ✓）
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_check as PC                                          # noqa: E402
import pcb_wire as PW                                           # noqa: E402

SK = 25.4 / 90.0
M = lambda u: u * SK                                            # noqa: E731
PCB_TRACE = 4                       # ★ `ViewGeometry::PCBTraceFlag` ✓
path = sys.argv[1]
GATE = PCB_TRACE
for a in sys.argv[2:]:
    if a.startswith("--flags="):
        GATE = int(a[8:])
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

# ── ① 件脚（= `ConnectorItem` 里 `ModelPart::Part` 那些 ✓）────────────────────
m = PC.collect(path)
pads = m["pads"]
pin = {}                            # key=(mi,cid) → dict ✓（同一个脚的两层 = 一个节点 ✓）
for q in pads:
    k = (q.get("mi"), q.get("cid"))
    if None in k:
        continue
    pin[k] = dict(title=q["title"], cid=q["cid"], mi=q["mi"], lay=q["layer"],
                  c=q["c"], box=q["box"], poly=q.get("poly"), circ=q.get("circle"))

# ── ② 走线 ✓（`wireFlags` 只取 pcbView 那份 ✓）＋ 端点 ＋ 它自己记的 `<connect>` ──
wire = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Wire"):
        continue
    t = PW.parse_trace(b)           # ★ 只认有 `<pcbView layer=…>` 的 ✓（= 它在 PCB 视图里存在 ✓）
    if t is None:
        continue
    pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b).group(1)
    fl = re.search(r'wireFlags="(\d+)"', pv)
    a, bb = PW.abs_ends(t["geo"])   # ★ `parse_trace` 给的是 `geo` ✓，端点要用 `abs_ends` ✓
    wire[mi.group(1)] = dict(mi=mi.group(1), flags=int(fl.group(1)) if fl else None,
                             layer=t["layer"], a=a, b=bb,
                             ends=t.get("ends") or {})

# ── ③ 过孔 ✓（本判据里当**走线**用 ✓：链会穿过去 ✓、不当连接件数 ✓）──────────────
via = {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi) or not mo.group(1).startswith("Via"):
        continue
    g = re.search(r'(?s)<pcbView\b[^>]*>(.*?)</pcbView>', b)
    x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1))
    if not x:
        continue
    fl = re.search(r'wireFlags="(\d+)"', g.group(1))
    via[mi.group(1)] = dict(mi=mi.group(1), p=(float(x.group(1)), float(x.group(2))),
                            flags=int(fl.group(1)) if fl else None, ends={})

# ── ④ `<buses>`（从包里各 `.fzp` 读 ✓，按 `moduleIdRef` 对上实例 ✓）─────────────
mid2bus = {}
for n in zin.namelist():
    if not n.endswith(".fzp"):
        continue
    t = zin.read(n).decode("utf-8")
    mid = re.search(r"<moduleId>([^<]+)</moduleId>", t)
    if not mid:
        continue
    buses = {}
    for bm in re.finditer(r'(?s)<bus[^>]*\bid="([^"]*)"[^>]*>(.*?)</bus>', t):
        for cid in re.findall(r'<member[^>]*\bconnectorId="([^"]+)"', bm.group(2)):
            buses[cid] = bm.group(1) or "bus"
    mid2bus[mid.group(1)] = buses
inst2mid = {}
for _i, b in PW.blocks(text):
    mi = re.search(r'modelIndex="(\d+)"', b)
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    if mi and mo:
        inst2mid.setdefault(mi.group(1), mo.group(1))


def bus_of(key):
    return mid2bus.get(inst2mid.get(key[0], ""), {}).get(key[1])


# ── ⑤ ★★ 几何命中（与 Fritzing 同源 ✓）：点落在**焊盘真形状**里才算接上 ✓ ──────
def lay_base(l):
    return (l or "").replace("trace", "")


def hit(pt, layer, q):
    if q["lay"] != "both" and q["lay"] != layer:
        return False
    if q["circ"]:
        (cx, cy), r = q["circ"]
        return (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 <= r * r
    p = q["poly"]
    if not p:
        return False
    sgn = None
    for i in range(len(p)):                     # 凸多边形：叉积同号 ⇒ 点在里 ✓
        x1, y1 = p[i]
        x2, y2 = p[(i + 1) % len(p)]
        cr = (x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)
        if abs(cr) < 1e-9:
            continue
        s = cr > 0
        if sgn is None:
            sgn = s
        elif sgn != s:
            return False
    return True


def pads_under(pt, layer):
    return [k for k, q in pin.items() if hit(pt, layer, q)]


# ── ⑥ 邻接（片 = `collectEqualPotential` ✓）────────────────────────────────
#   · 走线/过孔 ↔ 走线/过孔：按**文件里记的** ✓（那是接线柱自己写下的 ✓，线一动就重写 ✓）
#   · 走线/过孔 ↔ 焊盘：按**几何** ✓（✗ 不认文件里那份缓存 —— `v59` 的 `C2` 被挪过 0.354 mm，
#     文件里还写着"连着" ✗，而 Fritzing 一打开就报"2 个连接件没布" ✓ ⇒ 缓存不是判据 ✓）
adj = {}


def link(a, b):
    adj.setdefault(a, set()).add(b)
    adj.setdefault(b, set()).add(a)


allW = {("W", k): v for k, v in wire.items()}
allV = {("V", k): v for k, v in via.items()}
for k in list(allW) + list(allV) + [("P", k) for k in pin]:
    adj.setdefault(k, set())


def wired(cid, tmi):
    for tag in ("W", "V"):
        if (tag, tmi) in allW or (tag, tmi) in allV:
            return (tag, tmi)
    return None


for k, w in allW.items():
    for _e, lst in w["ends"].items():
        for (_cid, tmi, _l) in lst:
            t = wired(None, tmi)
            if t:
                link(k, t)                                          # 线↔线 / 线↔孔 ✓（按记录 ✓）
    for pt in (w["a"], w["b"]):                                     # ★ 只认**两个端点** ✓
        for pk in pads_under(pt, lay_base(w["layer"])):             #   中段压过焊盘**不算连** ✗
            link(k, ("P", pk))                                      #   （`wire.cpp:1133` 只查自由端 ✓）
for k, v in allV.items():
    for pk in pads_under(v["p"], "copper0") + pads_under(v["p"], "copper1"):
        link(k, ("P", pk))                                          # 过孔落在盘上（EPAD 那种 ✓）
_lk = sum(1 for k, ns in adj.items() if k[0] in ("W", "V") for n in ns if n[0] == "P")
print("   [dbg] 走线/过孔↔焊盘命中 **%d** 条 ✓｜adj 节点 %d ✓｜有 poly 的盘 %d ✓｜盘 %d ✓"
      % (_lk, len(adj), len([1 for q in pin.values() if q["poly"]]), len(pin)))
if os.environ.get("DBG"):
    print("   [dbg] 过孔的 wireFlags：%s"
          % sorted(set(v["flags"] for v in via.values())))
    for k, ns in adj.items():
        if k[0] != "P" or not ns:
            continue
        vs = [n for n in ns if n[0] == "V"]
        if vs:
            _p = pin[k[1]]
            print("   [dbg] 挂在过孔上的脚：`%s.%s`（hub 过孔 %s，viäflags=%s）"
                  % (_p["title"], _p["cid"], [v[1] for v in vs],
                     [via[v[1]]["flags"] for v in vs]))

# ── ⑦ 片 ✓（含**脚**的片才是"网" ✓；过孔只是通道 ✓、自己不成网 ✓）───────────────
parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry


for k in adj:
    find(k)
for k, ns in adj.items():
    for n in ns:
        union(k, n)
# ★★ 同 `bus()` 的脚进**同一网** ✓（`collectEqualPotential` 里 `busConnectorItems(...)` 那一段 ✓）
#   —— 注意 ✓：这一步是**分网**（`True` 的那个参数只跳过 `RatsnestFlag` 的线 ✓，
#   走线的 flags **不参与** ✓），与 `scoreOneNet` 里 `flags & 4` 的**加边**闸门是两回事 ✗。
for k in list(pin):
    b = bus_of(k)
    if not b:
        continue
    for k2 in pin:
        if k2 != k and k2[0] == k[0] and bus_of(k2) == b:
            union(("P", k), ("P", k2))
for k in pin:
    find(("P", k))
comp = {}
for k in adj:
    comp.setdefault(find(k), []).append(k)
nets = []
for root, members in comp.items():
    pins = [kk for kk in members if kk[0] == "P"]
    if pins:
        nets.append((root, pins, members))


# ── ⑧ 逐网跑 `scoreOneNet` ✓ ────────────────────────────────────────────────
def chain(nod):
    """`Wire::collectChained` ✓：把这条链收齐（**过孔当走线穿过去** ✓）
    ⇒ 返回（链上的走线/过孔 ✓、链端接到的**脚** ✓）"""
    chained, ends, stack = set([nod]), set(), [nod]
    while stack:
        n = stack.pop()
        for x in adj.get(n, ()):
            if x[0] in ("W", "V"):
                if x not in chained:
                    chained.add(x)
                    stack.append(x)
            else:
                ends.add(x)
    return chained, ends


netCount = routed = leftToRoute = 0
print("== %s（Fritzing 判据 ✓：闸门 `wireFlags & %d` ✓ ＋ **几何命中** ✓）=="
      % (os.path.basename(path), GATE))
print("   件脚 %d ✓ 走线 %d ✓ 过孔 %d ✓｜网（含脚的片）%d ✓"
      % (len(pin), len(wire), len(via), len(nets)))
badflags = []
for root, pins, members in sorted(nets, key=lambda z: (-len(z[1]), len(z[2]))):
    ids = [kk[1] for kk in pins]
    idx = {kk: n for n, kk in enumerate(pins)}
    # ── 建边（照 `scoreOneNet` 第一段 ✓）─────────────────────────────────
    ed = set()
    gotUser = False
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if pin[ids[i]]["mi"] != pin[ids[j]]["mi"]:
                gotUser = True               # 不同件 ⇒ 只记"有用户连接" ✓、**不加边** ✗
                continue
            if bus_of(ids[i]) and bus_of(ids[i]) == bus_of(ids[j]):
                ed.add((i, j))               # 同件同 `bus()` ⇒ 直接相连 ✓
                continue
            gotUser = True
    if not gotUser:
        continue                             # ★ 不数这一网 ✓
    netCount += 1
    if os.environ.get("DBG"):
        print("\n   [dbg] 网 #%d（%d 只脚）%s" % (netCount, len(ids), " ｜ ".join(
            "`%s.%s`" % (pin[x]["title"], x[1]) for x in ids[:14])))
    # ── 走线链 ⇒ 边（照 `scoreOneNet` 第二段 ✓）─────────────────────────────
    for i, p in enumerate(pins):
        for w in list(adj.get(p, ())):
            if w[0] not in ("W", "V"):
                continue                     # 只从"脚上直接挂的走线/过孔"出发 ✓
            fl = (wire.get(w[1]) if w[0] == "W" else via.get(w[1]))["flags"]
            if fl is not None and not (fl & GATE):
                if w not in badflags:
                    badflags.append(w)
                continue                     # ★★ 闸门就在这一层 ✓（`graphutils.cpp:550` ✓）
            _ch, ends = chain(w)
            for q in ends:
                j = idx.get(q)
                if j is not None and j != i:
                    ed.add((i, j) if i < j else (j, i))
    # ── 连通片 ⇒ 「还剩几个连接件」 ✓（片数 − 1 ✓）────────────────────────────
    gadj = {i: set() for i in range(len(ids))}
    for i, j in ed:
        gadj[i].add(j)
        gadj[j].add(i)
    seen, grp = set(), []
    for i in range(len(ids)):
        if i in seen:
            continue
        st, g = [i], []
        seen.add(i)
        while st:
            n = st.pop()
            g.append(n)
            for j2 in gadj[n]:
                if j2 not in seen:
                    seen.add(j2)
                    st.append(j2)
        grp.append(sorted(g))
    left = len(grp) - 1
    leftToRoute += left
    if left == 0:
        routed += 1
        continue
    print("\n   网 ✗ **还没连通** ✓（Fritzing 会在这几片之间画虚线 ✓）——还剩 **%d** 个连接件 ✓："
          % left)
    for g in grp:
        print("      片：%s" % " ｜ ".join(
            "`%s.%s`" % (pin[ids[i]]["title"], pin[ids[i]]["cid"]) for i in g))
    best = None
    for gi in range(len(grp)):
        for gj in range(gi + 1, len(grp)):
            for i in grp[gi]:
                for j in grp[gj]:
                    d = ((pin[ids[i]]["c"][0] - pin[ids[j]]["c"][0]) ** 2 +
                         (pin[ids[i]]["c"][1] - pin[ids[j]]["c"][1]) ** 2) ** .5
                    if best is None or d < best[0]:
                        best = (d, i, j)
    if best:
        d, i, j = best
        print("      ⇒ 最近的两片只差 **%.3f mm** ✓：`%s.%s`(%8.4f,%8.4f) ↔ `%s.%s`(%8.4f,%8.4f)"
              % (M(d), pin[ids[i]]["title"], pin[ids[i]]["cid"],
                 M(pin[ids[i]]["c"][0]), M(pin[ids[i]]["c"][1]),
                 pin[ids[j]]["title"], pin[ids[j]]["cid"],
                 M(pin[ids[j]]["c"][0]), M(pin[ids[j]]["c"][1])))

print("\n★★ **%d of %d nets routed - %d connector(s) still to be routed** ✓"
      % (routed, netCount, leftToRoute))
if badflags:
    print("   ⚠ 这几条走线**不算 PCB 铜**（`wireFlags` 不含 %d ✗）⇒ 挂在它们上的脚一律"
          "当作没布线 ✓：%s" % (GATE, ", ".join(
              "`%s%s`(flags=%s)" % (x[0], x[1], (wire.get(x[1]) or via.get(x[1]))["flags"])
              for x in badflags[:10])))
print("   （上面这句就是 Fritzing 状态栏会说的那句 ✓ —— 对照件 `pixel-pcb-v59.fzz` 应当是"
      "「5 of 7 nets routed - 2 connector(s) to be routed」✓）")
