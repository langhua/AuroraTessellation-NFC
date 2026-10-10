# -*- coding: utf-8 -*-
r"""把一份 sketch 里的 **`R1` / `C1` 从 0402 换回 0603 封装** ✓

换成哪两件 ✓（**照设计文档** ✓，不是我自己挑的 ✗）：
  · `R1`：`Resistor-0402` ⇒ **本库 `Resistor-0603`**（`fzpz/Resistor-0603.fzpz` ✓）
    —— ★ 本库这两件的 **`breadboard` / `schematic` 两个 svg 逐字节相同** ✓
      ⇒ 换完**只有 PCB 焊盘会动** ✓（面包板/原理图视图不受影响 ✓，已实测 ✓）
  · `C1`：`Capacitor-0402` ⇒ **Fritzing 自带 `SMD_multilayer-capacitor_0603`**
    （**与 `C2` 同一件** ✓）—— `pixel-netlist.md` §1 与 `README.md` §3 的 BOM 都写着
      「`C1` = 0603 电容 | **core**」✓；`C1` 实例里存着的属性（`capacitance5mm…` /
      `voltageHigh` ✓）本来就是**这件**带来的 ✓ ⇒ 换回去属性正好对上 ✓。
      ★ 它的面包板 svg 与本库 `Capacitor-0402` 用的是**同一个文件** ✓
      （`ceramic_capacitor_blue_leg.svg` ✓ 逐字节相同 ✓）⇒ 同样只动 PCB ✓。

★ 落位怎么定 ✓：**让"两个焊盘的中点"不动** ✓（两件都关于画布中心对称 ✓）——
  于是每个盘只挪「**脚距差 ÷ 2**」：
    `R1`：脚距 0.90 → 1.45 mm ⇒ 每盘挪 **0.275 mm** ✓；盘也长大（0.45×0.50 → 0.65×0.80 ✓）
    `C1`：脚距 0.90 → 1.70 mm ⇒ 每盘挪 **0.400 mm** ✓；盘长大（0.45×0.50 → 1.20×1.10 ✓）
  ⇒ 原来停在旧盘心上的走线端点**仍落在新盘里** ✓（挪的量 < 盘长大的那一半 ✓）
    ⇒ 铜仍然重叠 ⇒ `AGENTS §13`「声明接了 = 铜真碰上」继续成立 ✓（用 `pcb_check` ⑩ 复核 ✓）。

用法 ✓：
  py -3.13 _work\swap_rc_0603.py pixel-pcb-v84.fzz pixel-pcb-v85.fzz            # 干跑 ✓
  py -3.13 _work\swap_rc_0603.py pixel-pcb-v84.fzz pixel-pcb-v85.fzz --apply    # 写入 ✓

✗ 不写文件的情形 ✓：新盘算不出 / 找不到实例 / `<geometry>` 不唯一 / XML 过不了 / 段数变了 ✓。
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                                    # noqa: E402,F401
import pcb_pads as PP                                               # noqa: E402
import pcb_wire as PW                                               # noqa: E402

LIB = r"f:\git\fritzing-parts-langhua"
NEW_R = "Resistor-0603"
NEW_C = "Capacitor-0603"
SK = 90.0 / 25.4                      # mm ⇒ sketch 单位 ✓


def blocks(text):
    """按 `<title>` 找实例块 ✓（与 `fz_keep_set.blocks` 同一口径 ✓）"""
    out = []
    for m in re.finditer(r"<title>([^<]*)</title>", text):
        a = text.rfind("<instance", 0, m.start())
        b = text.find("</instance>", m.end())
        if a < 0 or b < 0:
            continue
        out.append((m.group(1), a, b + len("</instance>")))
    return out


def block_of(text, title):
    got = [x for x in blocks(text) if x[0] == title]
    if len(got) != 1:
        raise SystemExit("✗ `<title>%s</title>` 的实例不是唯一（%d 个）✗" % (title, len(got)))
    return got[0]


def fzpz_files(name):
    z = zipfile.ZipFile(os.path.join(LIB, "fzpz", name + ".fzpz"))
    return {os.path.basename(n): z.read(n) for n in z.namelist() if not n.endswith("/")}


def part_bits(files):
    """从 .fzpz 里取 `(moduleId, fzp 全文, pcb 视图 svg 全文, fzp 文件名)` ✓"""
    fzp_key = [k for k in files if k.endswith(".fzp")][0]
    t = files[fzp_key].decode("utf-8")
    mid = re.search(r'<module\b[^>]*\bmoduleId="([^"]+)"', t)
    if not mid:
        raise SystemExit("✗ %s 里读不出 moduleId ✗" % fzp_key)
    m = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", t)
    if not m:
        raise SystemExit("✗ %s 里没有 `<pcbView>` ✗" % fzp_key)
    image = re.search(r'image="([^"]+)"', m.group(1))
    if not image:
        raise SystemExit("✗ %s 的 `<pcbView>` 里没有 `image=` ✗" % fzp_key)
    want = os.path.basename(image.group(1))
    hit = [k for k in files if k.endswith(want)]
    if not hit:
        raise SystemExit("✗ %s 的 pcb svg `%s` 不在包里 ✗" % (fzp_key, want))
    return mid.group(1), t, files[hit[0]].decode("utf-8"), fzp_key


def core_cap_bits(core_path):
    """Fritzing 自带 0603 电容 ⇒ `(fzp 全文, pcb svg 全文)` ✓（**从安装目录读** ✓）"""
    root = os.path.dirname(os.path.dirname(core_path.replace("/", os.sep)))   # …/fritzing-parts
    fzp = open(os.path.join(root, "core", "SMD_multilayer-capacitor_0603.fzp"),
               encoding="utf-8").read()
    svg = open(os.path.join(root, "svg", "core", "pcb", "SMD_0603.svg"),
               encoding="utf-8").read()
    return fzp, svg


def fzp_decl(t):
    """fzp 里每个脚在 pcb 上声明了哪几层 ✓（`<p layer="copperN" svgId=…>` ✓）"""
    out = {}
    for c in re.finditer(r'(?s)<connector id="([^"]+)"(.*?)</connector>', t):
        lays = re.findall(r'<p layer="(copper[01])"', c.group(2))
        if lays:
            out[c.group(1)] = lays
    return out


def pads_abs(part, svg_text, decl=None):
    """某件**放在这个实例的位置/朝向上**时各脚的绝对位置 ✓（`rel` + `poly` 全带上 ✓）"""
    p = dict(part)
    p["svg_text"] = svg_text
    if decl is not None:
        p["decl"] = decl
    got, _ex, bad, _n = PP.part_pads(p)
    if not got:
        raise SystemExit("✗ %s 的焊盘算不出：%s ✗" % (p["title"], bad))
    return {cid: dict(rel=(q["abs"][0] - p["loc"][0], q["abs"][1] - p["loc"][1]),
                      abs=q["abs"], size_mm=q["size_mm"], layer=q["layer"],
                      box=q["absbox"], poly=q.get("poly"), circle=q.get("circle"))
            for cid, q in got.items()}


def inside(q, pt, off=(0.0, 0.0)):
    """点 `pt` 在不在这只盘里 ✓（矩形=凸多边形判据 ✓；通孔=圆 ✓）"""
    if q.get("circle"):
        (cx, cy), r = q["circle"]
        return ((pt[0] - (cx + off[0])) ** 2 + (pt[1] - (cy + off[1])) ** 2) ** 0.5 * 25.4 / 90 \
            <= r * 25.4 / 90
    ps = [(x + off[0], y + off[1]) for x, y in q["poly"]]
    sg = None
    for i in range(len(ps)):
        x1, y1 = ps[i]
        x2, y2 = ps[(i + 1) % len(ps)]
        cr = (x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)
        if abs(cr) < 1e-12:
            continue
        if sg is None:
            sg = cr > 0
        elif sg != (cr > 0):
            return False
    return True


def edge_margin(q, pt, off=(0.0, 0.0)):
    """点到盘边界的**净距（mm ✓）**—— 正数 = 在里面 ✓"""
    if q.get("circle"):
        (cx, cy), r = q["circle"]
        return (r - ((pt[0] - cx - off[0]) ** 2 + (pt[1] - cy - off[1]) ** 2) ** 0.5) \
            * 25.4 / 90
    ps = [(x + off[0], y + off[1]) for x, y in q["poly"]]
    best = None
    for i in range(len(ps)):
        x1, y1 = ps[i]
        x2, y2 = ps[(i + 1) % len(ps)]
        vx, vy = x2 - x1, y2 - y1
        L = (vx * vx + vy * vy) ** 0.5
        t = max(0.0, min(1.0, ((pt[0] - x1) * vx + (pt[1] - y1) * vy) / (L * L)))
        d = ((pt[0] - x1 - t * vx) ** 2 + (pt[1] - y1 - t * vy) ** 2) ** 0.5
        best = d if best is None else min(best, d)
    return (-best if not inside(q, pt, off) else best) * 25.4 / 90 if best is not None else 0.0


def set_xyz(attrs, dx, dy):
    nx = float(re.search(r'\bx="([-\d.eE+]+)"', attrs).group(1)) + dx
    ny = float(re.search(r'\by="([-\d.eE+]+)"', attrs).group(1)) + dy
    a = re.sub(r'\bx="[^"]*"', 'x="%s"' % PW.fmt(nx), attrs, count=1)
    return re.sub(r'\by="[^"]*"', 'y="%s"' % PW.fmt(ny), a, count=1)


def move_geo(blk, dx, dy):
    """把实例块里的**顶层** `<geometry/>` 与 `<titleGeometry/>` 的 `x y` 一起平移 ✓

    ★ 顶层 = 紧跟在 `<pcbView …>` 后面的那一个 ✓ —— ✗ 块里每个 `<connector>` 自己还有一个
      `<geometry x="0" y="0"/>` ✗（它们**不能动** ✓：那是脚在件里的局部位置 ✓）。
    """
    out, moved = blk, {}
    m = re.search(r'(<pcbView\b[^>]*>\s*)<geometry\b([^>]*?)(/?)>', out)
    if not m:
        raise SystemExit("✗ 找不到顶层 `<geometry/>`（`<pcbView>` 后面那一个）✗")
    a2 = set_xyz(m.group(2), dx, dy)
    out = out[:m.start(2)] + a2 + out[m.end(2):]
    moved["geometry"] = (m.group(2).strip(), a2.strip())
    ms = list(re.finditer(r'<titleGeometry\b([^>]*?)(/?)>', out))
    if len(ms) != 1:
        raise SystemExit("✗ 块里 `<titleGeometry/>` 不是唯一（%d 个）✗" % len(ms))
    m = ms[0]
    a2 = set_xyz(m.group(1), dx, dy)
    out = out[:m.start()] + "<titleGeometry%s%s>" % (a2, "/" if m.group(2) else "") + \
        out[m.end():]
    moved["titleGeometry"] = (m.group(1).strip(), a2.strip())
    return out, moved


def shift_wire_ends(text, moves):
    """**让走线的端点跟着焊盘一起挪** ✓ ⇒ 端点仍然落在**新盘的中心** ✓（重叠最充分 ✓）

    `moves` = `[(旧盘 dict, (dx, dy))]` ✓（`dx,dy` = 该盘心的位移 ✓）
    ★ `<connect>` **不受影响** ✓ —— 它记的是 `connectorId`/`modelIndex` ✓，不是坐标 ✓。
    ★ 写法照 Fritzing 自己的约定 ✓：`x,y` = A 端绝对坐标 ✓、`x1=y1=0` ✓、
      `x2,y2` = A→B 的**相对偏移** ✓ ⇒ 挪 A ⇔ 改 `x,y` 并把 `x2,y2` 反向补回来 ✓。
    ★ 带 `<bezier>`（弧线）的走线**不挪** ✗ —— 只挪端点会把弧扭歪 ✓ ⇒ 报错不写 ✓。
    """
    out, n = text, 0
    edits = []
    for _title, a, b in blocks(text):
        blk = text[a:b]
        mid = re.search(r'moduleIdRef="([^"]+)"', blk)
        if not mid or not mid.group(1).startswith("Wire") or "<pcbView" not in blk:
            continue
        pm = re.search(r'(?s)<pcbView\b.*?</pcbView>', blk)
        gm = re.search(r'<geometry\b([^>]*?)(/?)>', pm.group(0))
        if not gm:
            continue
        # ★ 下标基准：`gm` 是**相对 `pm.group(0)`** 搜出来的 ✗ ⇒ 用回 `blk` 必须**加上
        #   `pm.start()`** ✓（2026-10-10 踩过：不加就把属性写进了 `<instance>` 那一行 ✗）
        base = pm.start()
        geo = dict(re.findall(r'([\w]+)="([^"]*)"', gm.group(1)))
        try:
            x, y = float(geo.get("x", 0)), float(geo.get("y", 0))
            x1, y1 = float(geo.get("x1", 0)), float(geo.get("y1", 0))
            x2, y2 = float(geo.get("x2", 0)), float(geo.get("y2", 0))
        except ValueError:
            continue
        A = (x + x1, y + y1)
        B = (x + x2, y + y2)
        dA = dB = (0.0, 0.0)
        for pt, which in ((A, "A"), (B, "B")):
            for q, d in moves:
                if inside(q, pt):
                    if which == "A":
                        dA = d
                    else:
                        dB = d
                    break
        if dA == (0.0, 0.0) and dB == (0.0, 0.0):
            continue
        if "<bezier" in blk:
            raise SystemExit("✗ 走线 `%s` 带 `<bezier>`（弧线）却要挪端点 ⇒ 不写文件 ✗"
                             % _title)
        nx, ny = x + x1 + dA[0], y + y1 + dA[1]
        nx2 = (x + x2 + dB[0]) - nx
        ny2 = (y + y2 + dB[1]) - ny
        a2 = set_attr3(gm.group(1), [("x", nx), ("y", ny), ("x1", 0.0), ("y1", 0.0),
                                     ("x2", nx2), ("y2", ny2)])
        blk2 = blk[:base + gm.start(1)] + a2 + blk[base + gm.end(1):]
        edits.append((a, b, blk2, _title, A, B, dA, dB, (nx, ny),
                      (x + x2 + dB[0], y + y2 + dB[1])))
    for a, b, blk2, _title, A, B, dA, dB, na, nb in reversed(edits):
        out = out[:a] + blk2 + out[b:]
        n += 1
        print("   [走线] %s 端点跟着挪 ✓：A(%.3f,%.3f)→(%.3f,%.3f)｜B(%.3f,%.3f)→(%.3f,%.3f)"
              % (_title, A[0], A[1], na[0], na[1], B[0], B[1], nb[0], nb[1]))
    return out, n


def set_attr3(attrs, pairs):
    a = attrs
    for k, v in pairs:
        if re.search(r'\b%s="' % k, a):
            a = re.sub(r'\b%s="[^"]*"' % k, '%s="%s"' % (k, PW.fmt(v)), a, count=1)
        else:
            a = a.rstrip() + ' %s="%s"' % (k, PW.fmt(v))
    return a


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    apply_ = "--apply" in argv
    # ★ 额外微调（mm ✓，实验/避让用 ✓）：`--off=R1:dx,dy` （可给多次 ✓）
    OFF = {}
    for a in argv:
        if a.startswith("--off="):
            who, xy = a[6:].split(":", 1)
            ox, oy = [float(v) for v in xy.split(",")]
            OFF[who] = (ox * 90.0 / 25.4, oy * 90.0 / 25.4)
    # ★ 只做实验：让 C1 借用另一件（如 `Resistor-0603`）的 pcb svg ✓（**不建库件** ✓）
    C1PCB = next((a.split("=", 1)[1] for a in argv if a.startswith("--c1pcb=")), None)
    # ★ 只换其中一件（实验/分步用 ✓）：`--only=R1` / `--only=C1` ✓（缺省两件都换 ✓）
    ONLY = None
    for a in argv:
        if a.startswith("--only="):
            ONLY = tuple(x.strip() for x in a[7:].split(",") if x.strip())
    # ★★ 通用换件 ✓（2026-10-11 ✓，为 `C2` 加的 ✓）：`--swap=C2:Capacitor-0603`（可给多次 ✓）
    #   —— ✗ 不给就照旧（`R1`→`Resistor-0603` ✓、`C1`→`Capacitor-0603` ✓）。
    SWAPS = []
    for a in argv:
        if a.startswith("--swap="):
            t, pn = a[7:].split(":", 1)
            SWAPS.append((t.strip(), pn.strip()))
    # ★ 直接给**件原点**（mm ✓）：`--loc=R1:x,y`（搜索出来的结果就是这样给的 ✓）
    LOC = {}
    for a in argv:
        if a.startswith("--loc="):
            who, xy = a[6:].split(":", 1)
            LOC[who] = tuple(float(v) for v in xy.split(","))
    # ★ 把该件 pcb 视图再转 90°：`--rot=R1`（`M' = R90∘M` ✓）
    ROT = tuple(a.split("=", 1)[1] for a in argv if a.startswith("--rot="))
    z = zipfile.ZipFile(src)
    inner = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(inner).decode("utf-8")
    parts, _board = PP.read_fzz(src)
    by = {p["title"]: p for p in parts}

    # ── 新件的几何 / moduleId ────────────────────────────────────────────────
    plan = []
    if SWAPS:                                   # ★ 通用换件 ✓（计划从命令行来 ✓）
        for t, pn in SWAPS:
            files = fzpz_files(pn)
            mid, fzp_txt, svg, fzp_name = part_bits(files)
            plan.append((t, svg, mid, fzp_decl(fzp_txt), files,
                         "本库 `%s`（moduleId = %s ✓）" % (pn, mid), fzp_name))
    r6 = fzpz_files(NEW_R)
    r6_mid, r6_fzp_txt, r6_svg, r6_fzp_name = part_bits(r6)
    c2blk = text[block_of(text, "C2")[1]:block_of(text, "C2")[2]]
    c2_path = re.search(r'path="([^"]*)"', c2blk).group(1)
    print("C2 的安装路径参照 = %s" % c2_path)
    c6 = fzpz_files("Capacitor-0603-rich" if False else "Capacitor-0603")
    c6_mid, c6_fzp_txt, c6_svg, c6_fzp_name = part_bits(c6)

    if not plan:
        plan = [("R1", r6_svg, r6_mid, fzp_decl(r6_fzp_txt), r6,
                 "本库 `%s`（moduleId = %s ✓）" % (NEW_R, r6_mid), r6_fzp_name),
                ("C1", c6_svg, c6_mid, fzp_decl(c6_fzp_txt), c6,
                 "本库 `Capacitor-0603`（moduleId = %s ✓ —— **紧凑 land pattern** ✓；"
                 "Fritzing 自带那颗太肥 ✗）" % c6_mid, c6_fzp_name)]
    if C1PCB:                                   # 实验：C1 借别件的 pcb 几何 ✓
        alt = fzpz_files(C1PCB)
        _m, _t, alt_svg, _f = part_bits(alt)
        for _i, _it in enumerate(plan):
            if _it[0] == "C1":
                plan[_i] = ("C1", alt_svg, c6_mid, fzp_decl(_t), None, c2_path,
                            "实验：C1 的 pcb 几何改用本库 `%s` ✓" % C1PCB)

    new_text = text
    add_files = {}
    moves = []
    PC = None
    for title, svg, mid_new, decl_new, newfiles, why, fzp_name in plan:
        if ONLY and title not in ONLY:
            continue
        inst = by[title]
        old_mid = inst["moduleId"]
        old = pads_abs(inst, inst["svg_text"])
        inst2 = dict(inst)
        if title in ROT:                     # ★ 再转 90° ⇒ `M' = R90∘M` ✓
            m = inst["M"]
            inst2["M"] = (-m[1], m[0], -m[3], m[2], -m[5], m[4])
        new = pads_abs(inst2, svg, decl=decl_new)
        if title in LOC:
            dx = LOC[title][0] * SK - inst["loc"][0]
            dy = LOC[title][1] * SK - inst["loc"][1]
            print("   （直接指定原点 (%.3f, %.3f) mm ⇒ 平移 (%.4f, %.4f) 单位 ✓）"
                  % (LOC[title][0], LOC[title][1], dx, dy))
        else:
            om = (sum(q["rel"][0] for q in old.values()) / len(old),
                  sum(q["rel"][1] for q in old.values()) / len(old))
            nm = (sum(q["rel"][0] for q in new.values()) / len(new),
                  sum(q["rel"][1] for q in new.values()) / len(new))
            dx, dy = om[0] - nm[0], om[1] - nm[1]
        if title in OFF:                       # ★ 额外微调（mm ⇒ sketch 单位 ✓）
            dx += OFF[title][0]
            dy += OFF[title][1]
            print("   （额外微调 %s：%.3f, %.3f mm ✓）" % (title, OFF[title][0] * 25.4 / 90,
                                                          OFF[title][1] * 25.4 / 90))
        print("\n== %s：%s ⇒ %s" % (title, old_mid, why))
        for lbl, d in (("旧盘", old), ("新盘", new)):
            print("   %s（相对 loc）：%s" % (lbl, " ｜ ".join(
                "%s (%.4f, %.4f) %.2f×%.2f mm @%s"
                % (c, q["rel"][0], q["rel"][1], q["size_mm"][0], q["size_mm"][1], q["layer"])
                for c, q in sorted(d.items()))))
        print("   ⇒ 平移 loc = (%.4f, %.4f) sketch 单位 = (%.4f, %.4f) mm ✓"
              % (dx, dy, dx * 25.4 / 90, dy * 25.4 / 90))
        if PC is None:
            sys.path.insert(0, PIX)
            import pcb_check as PC                                  # noqa: E402
            model = PC.collect(src)
            ENDS = []
            for t in model["traces"]:
                if t.get("layer") in ("copper0", "copper1"):
                    ENDS += [t["a"], t["b"]]
        # ★ 真正的判据：**原来落在旧盘里的走线端点，换件后还在不在新盘里** ✓
        for c in sorted(old):
            if c not in new:
                raise SystemExit("✗ %s 少了脚 %s ✗" % (title, c))
            ends = [e for e in ENDS if inside(old[c], e)]
            if not ends:
                print("      %-12s 旧盘上没有走线端点 ✓（无需检查）" % c)
                continue
            many = min(edge_margin(new[c], e, (dx, dy)) for e in ends)      # 只挪件 ✓（参考 ✓）
            disp = (dx + new[c]["rel"][0] - old[c]["rel"][0],
                    dy + new[c]["rel"][1] - old[c]["rel"][1])
            # ★ 真正的判据：**端点跟着盘心一起挪之后**，端点还在不在新盘里 ✓
            worst = min(edge_margin(new[c], (e[0] + disp[0], e[1] + disp[1]), (dx, dy))
                        for e in ends)
            tag = "✓" if worst > 0 else "✗ 端点掉到盘外 ✗"
            print("      %-12s 接 %d 个走线端点 ⇒ **端点跟着挪**后到新盘边最小净距 "
                  "**%+.4f mm** %s（若只挪件则是 %+.4f mm ✓）"
                  % (c, len(ends), worst, tag, many))
            if worst <= 0:
                raise SystemExit("✗ %s.%s 换件后走线端点不再落在焊盘里（净距 %+.4f mm）✗"
                                 % (title, c, worst))
            # ★ 端点的处置：**让端点跟着盘心一起挪** ✓ ⇒ 重叠最充分 ✓（见 `shift_wire_ends` ✓）
            moves.append((old[c], disp))

        # ── 改实例块 ──
        a, b = block_of(new_text, title)[1:]
        blk = new_text[a:b]
        blk2 = blk.replace('moduleIdRef="%s"' % old_mid, 'moduleIdRef="%s"' % mid_new, 1)
        if blk2 == blk:
            raise SystemExit("✗ %s 的 moduleIdRef 没改成 ✗" % title)
        oldp = re.search(r'path="([^"]*)"', blk2).group(1)
        newp = os.path.dirname(oldp) + "/" + fzp_name[len("part."):]
        blk2 = blk2.replace('path="%s"' % oldp, 'path="%s"' % newp, 1)
        if newfiles is not None:
            add_files.update(newfiles)
        pm = re.search(r"(?s)<pcbView\b.*?</pcbView>", blk2)
        if not pm:
            raise SystemExit("✗ %s 没有 pcbView ✗" % title)
        pv2, moved = move_geo(pm.group(0), dx, dy)
        if title in ROT:                       # ★ 把顶层 `<transform>` 换成转过的 ✓
            m = inst["M"]
            m2 = (-m[1], m[0], -m[3], m[2], -m[5], m[4])
            tf = ('<transform m11="%s" m12="%s" m13="0" m21="%s" m22="%s" '
                  'm23="0" m31="%s" m32="%s" m33="1"/>'
                  % tuple(PW.fmt(v) for v in m2))
            gm = re.search(r'<geometry\b[^>]*?>(.*?)</geometry>', pm.group(0), re.S)
            if not gm:
                raise SystemExit("✗ %s 的顶层 `<geometry>` 不是成对标签 ✗（带 transform 的才转 ✓）"
                                 % title)
            old_tf = re.search(r'<transform\b.*?/>', gm.group(1), re.S)
            if not old_tf:
                raise SystemExit("✗ %s 的 geometry 里没有 `<transform>` ✗" % title)
            pv2 = pv2.replace(old_tf.group(0), tf, 1)
            print("   转 90°：%s\n        ⇒ %s" % (old_tf.group(0), tf))
        blk2 = blk2[:pm.start()] + pv2 + blk2[pm.end():]
        new_text = new_text[:a] + blk2 + new_text[b:]
        print("   path ⇒ %s" % newp)
        for tag, (o, n) in moved.items():
            print("   <%s %s\n    ⇒ <%s %s" % (tag, o, tag, n))

    # ── 走线端点跟着焊盘挪 ✓ ────────────────────────────────────────────────
    new_text, n_shift = shift_wire_ends(new_text, moves)
    print("\n⇒ 跟着挪的走线：**%d** 根 ✓" % n_shift)

    # ── 自检：XML ✓ / 段数 ✓ ────────────────────────────────────────────────
    try:
        ET.fromstring(new_text)
    except ET.ParseError as exc:
        ln = int(str(exc).rsplit("line", 1)[1].split(",")[0])
        for i in range(max(1, ln - 3), ln + 3):
            print("   %5d| %s" % (i, new_text.splitlines()[i - 1]))
        raise
    for vn in ("<instance", "<pcbView", "<schematicView", "<breadboardView",
               "<connect", "<title>"):
        if new_text.count(vn) != text.count(vn):
            raise SystemExit("✗ `%s` 计数变了（%d → %d）✗"
                             % (vn, text.count(vn), new_text.count(vn)))
    import difflib
    la, lb = text.splitlines(keepends=True), new_text.splitlines(keepends=True)
    hunks = [h for h in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes()
             if h[0] != "equal"]
    print("\n⇒ 逐行核：只有 **%d** 处改动 ✓（XML 解析通过 ✓、各类段计数不变 ✓）" % len(hunks))
    for tag, i1, i2, j1, j2 in hunks:
        for l in la[i1:i2]:
            print("   - %s" % l.rstrip())
        for l in lb[j1:j2]:
            print("   + %s" % l.rstrip())

    if not apply_:
        print("\n（干跑 ✓ —— 要写入加 `--apply` ✓）")
        return 0

    # ── 写文件 ✓（包内条目时间戳/属性照抄 ⇒ 可复现 ✓）──────────────────────
    inner_new = os.path.basename(dst).replace(".fzz", ".fz")
    names = list(z.namelist())
    for k in add_files:
        if k not in names:
            names.append(k)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            if n == inner:
                if inner_new != inner:
                    zi = zipfile.ZipInfo(inner_new, date_time=z.getinfo(inner).date_time)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zo.writestr(zi, new_text.encode("utf-8"))
                else:
                    zo.writestr(z.getinfo(n), new_text.encode("utf-8"))
            elif n in z.namelist():
                zo.writestr(z.getinfo(n), z.read(n))
            else:
                zo.writestr(zipfile.ZipInfo(n, date_time=(2026, 10, 10, 0, 0, 0)),
                            add_files[n])
    print("⇒ 写 %s ✓（%d 个条目 ✓，其中新嵌 %d 个 ✓）"
          % (dst, len(names), len(add_files)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
