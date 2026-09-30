# -*- coding: utf-8 -*-
r"""像素板 **摆位审计**（规范机器守 ✓）2026-09-30 立

用法：
  py -3.13 audit_placement.py <sketch.fzz> [--coil L1] [--hole-off-mm "46.50,21.11"]

★ 为什么单独一份 ✓：生成器**自检不算数** ✗ —— 这里的判据全部**从文件上量** ✓，
  且**只信外部口径** ✓：规范见 `pcb-placement-rules.md` ✓（3.0 / Ø4.0 / 0.3 ✓）。

七条（对应规范 §3 ✓）：
  1. 每个安装孔的**实际孔心**到四条板边 ≥ 3.0 mm ✓
  2. Ø4.0 keep-out 内**没有**任何焊盘 ✓（走线由 `pcb_check` 那条线管 ✓）
  3. 所有焊盘框（含 0.2 净空）都落在板内 ✓
  4. 没有件（焊盘框）压到**线圈绕组铜箔**（±0.3 mm）✓
  5. 孔的 keep-out 不进绕组 ✓
  6. 连接器 J1/J2 的**焊盘簇**在板心一侧（= 焊盘朝板内 ✓，**符号判据** ✗ 不比距离 ✗）
  7. 每个件的**本体/焊盘框**都在板内 ✓
  8. ★★ 每个件的**本体/丝印**（= **画出来的一切** ✓）都在板内 ✓ ——
     ✗ 2026-09-30 补 ✗：原第 ③ 条只查了**焊盘** ✗ ⇒ **丝印/本体出板看不见** ✗ ——
       而这正是用户连续两次指出的病 ✓（「J2 在 PCB 板外面了」✗、J1 丝印出左边 0.64 mm ✗）。
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolpaths                                                  # noqa: E402,F401
import part_box as PB                                             # noqa: E402
import pcb_check as PC                                            # noqa: E402
import pcb_pads as PP                                             # noqa: E402
import pcb_wire as PW                                             # noqa: E402

# ★★ 单位换算**只有这一处** ✓（单位/mm ✓）—— ✗ 别再拿 `pcb_wire.SK`（那是 mm/单位 ✗）
#    去除一遍 ✗：2026-09-30 我就是这么把 `board_rect` 误判成"有 bug"的 ✗。
MM = lambda u: u / PB.MM                                          # sketch 单位 → mm ✓
U = lambda m: m * PB.MM                                           # mm → sketch 单位 ✓

# ── 规范数字（`pcb-placement-rules.md` §2 ✓）────────────────────────────────
HOLE_EDGE_MM = 3.0            # 孔心离板边 ✓（IPC-2221C 综述 ✓）
HOLE_KEEP_MM = 4.0            # 孔周免铜免件环 Ø ✓（螺钉头 + 免铜 ✓）
COPPER_EDGE_MM = 0.3          # 免铜到板边 ✓（≥0.25 ✓）
COIL_CLR_MM = 0.3             # 件离绕组铜箔 ✓
# ★ 孔件的**环心偏移** = `drawn − geometry` ✓（实测出来的 ✓；**按板校准** ✓）
#   来源：用户 `holes_pads.fzz` + 导出 `holes_pads_图示.svg`（量法 `_work/svg_probe.py` ✓）
#   ⚠️ **大板上量到的是 (−46.50, −21.11) mm ✗ 不能用到 25 mm 板** ✗（v6 实测反推＝板外 ✗）
#      ⇒ 默认 **(0, 0)** ＝ "把 `<geometry>` 当孔心" ✓；
#        校准：拿**这块板**的一张导出 svg ✓ 量出环心 ⇒ 传 `--hole-off-mm "dx,dy"` ✓。
#   ★ 与 `gen_pcb.py` 用**同一个定义** ✓：`drawn = geometry + off` ✓
HOLE_OFF_MM = (0.0, 0.0)
HOLE_OFF_BIG_BOARD_MM = (-46.50, -21.11)    # 仅存档 ✓（大板上量的 ✓，别用 ✗）

RE_INST = r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>"


def holes_of(text):
    """⇒ `[(title, 实际孔心 mm 相对 sketch 原点), …]` ✓（已补偿环心偏移 ✓）"""
    out = []
    for m in re.finditer(RE_INST, text):
        b = m.group(0)
        if "HoleModuleID" not in b:
            continue
        g = re.search(r'<pcbView[^>]*>\s*<geometry ([^>]*)/>', b)
        if not g:
            continue
        a = dict(re.findall(r'([\w]+)="([^"]*)"', g.group(1)))
        t = re.search(r"<title>([^<]*)</title>", b)
        x = float(a.get("x", 0)) + U(HOLE_OFF_MM[0])               # ← 补偿 ✓（drawn = geometry + off ✓）
        y = float(a.get("y", 0)) + U(HOLE_OFF_MM[1])
        out.append((t.group(1) if t else "?", x, y))
    return out


def copper_box(part):
    """该件 pcb svg 里**铜图形**的包围盒 ✓（sketch 单位、含实例 loc ✓）；没铜 ⇒ None ✓"""
    if not part.get("svg_text"):
        return None
    try:
        root = ET.fromstring(part["svg_text"])
    except ET.ParseError:
        return None
    try:
        groups = PP.copper_shapes(root)
    except Exception:                                             # noqa: BLE001
        return None
    # ★★ `copper_shapes` 是**按层分组**的 ✗：`[[层0…], [层1…]]` ✓ ⇒ 先摊平 ✓
    #    ✗ 当扁平列表用 ⇒ 一条框都取不到 ✗（2026-09-30 实测 ✗，量绕组时踩的 ✓）。
    shapes = []
    for g in groups:
        if isinstance(g, dict):
            shapes.append(g)
        else:
            shapes.extend(g)
    boxes = []
    for s in shapes:
        # ★ `pcb_pads.copper_shapes` 返回的是**元组** ✓（`(lay, id, tag, c, box, r, sw)` ✓）
        #   —— ✗ 别当字典用 ✗、也**别猜下标** ✗（两种形状都兜住 ✓）：
        #   扫一遍，取"那个长度 4、元素全是数"的字段当框 ✓。
        bx = None
        if isinstance(s, dict):
            bx = s.get("box")
        else:
            for v in (s if isinstance(s, (list, tuple)) else ()):
                if (isinstance(v, (list, tuple)) and len(v) == 4
                        and all(isinstance(z, (int, float)) for z in v)):
                    bx = v
                    break
        if bx:
            boxes.append(bx)
    if not boxes:
        return None
    bb = (min(b[0] for b in boxes), min(b[1] for b in boxes),
          max(b[2] for b in boxes), max(b[3] for b in boxes))
    return (bb[0] + part["loc"][0], bb[1] + part["loc"][1],
            bb[2] + part["loc"][0], bb[3] + part["loc"][1])


def ink_box_of(p):
    r"""该实例**画出来的一切**（铜 + 丝印 + 文字 ✓）在板上的绝对框 ✓（sketch 单位 ✓）

    ★★ 为什么校验器要**自己写一份** ✗（而不用 `gen_pcb.ink_box` ✗）：
      本仓铁律「生成器自检不算数 ✗」✓ —— 生成器与校验器**必须是两份实现** ✓，
      且校验器只认**文件里的实例**（`loc` + `M` + `pcbView` 的 `bottom` ✓），
      不信生成器的中间量 ✓。
    ★ 镜像口径与 `pcb_pads.part_pads` 一致 ✓：背面件 `x' = 2·ox + vbw − x` ✓
      （轴 = 画布中线 ✓）；再 `(x' − ox)·k` 转 sketch 单位 ✓。
    """
    if not p.get("svg_text"):
        return None
    try:
        root = ET.fromstring(p["svg_text"])
    except ET.ParseError:
        return None
    k, (ox, oy) = PB.svg_k(root)
    if not k:
        return None
    vb = PB._nums(root.get("viewBox"))
    vbw = vb[2] if len(vb) == 4 and vb[2] else 0.0
    flip = ((p.get("pv") or {}).get("bottom") or "").lower() == "true" and vbw > 0
    c = PB.shape_bbox(root)
    if c is None:
        return None
    xs, ys = [], []
    for u in (c[0], c[2]):
        for v in (c[1], c[3]):
            x = (2.0 * ox + vbw - u) if flip else u
            q = PB.apply(p["M"], (x - ox) * k, (v - oy) * k)
            xs.append(p["loc"][0] + q[0])
            ys.append(p["loc"][1] + q[1])
    return (min(xs), min(ys), max(xs), max(ys))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    fzz = argv[0]
    coil = "L1"
    if "--coil" in argv:
        coil = argv[argv.index("--coil") + 1]
    global HOLE_OFF_MM
    if "--hole-off-mm" in argv:                                   # ``dx,dy``（mm ✓）
        HOLE_OFF_MM = tuple(float(v) for v in
                            argv[argv.index("--hole-off-mm") + 1].split(","))
        print("   ★ 本次按传入的孔偏移校准：%s mm ✓" % (HOLE_OFF_MM,))
    model = PC.collect(fzz)
    r = model["board"]
    text = model["text"]
    if r is None or not text:
        print("✗ 读不到板框 ✗")
        return 2
    b = [MM(v) for v in r]
    print("== 摆位审计：%s ==" % os.path.basename(fzz))
    print("   板框 %.2f × %.2f mm｜规范：孔心离边 ≥ %.1f ✓、孔周 Ø%.1f 免件 ✓、免铜到边 %.2f ✓"
          % (b[2] - b[0], b[3] - b[1], HOLE_EDGE_MM, HOLE_KEEP_MM, COPPER_EDGE_MM))
    bad = []

    # ① 孔：离板边 + ② keep-out
    hs = holes_of(text)
    print("\n① 安装孔（%d 个 ✓；已按实测偏移补偿 ✓）" % len(hs))
    for nm, x, y in hs:
        d = [MM(x - r[0]), MM(y - r[1]), MM(r[2] - x), MM(r[3] - y)]
        ok = min(d) >= HOLE_EDGE_MM - 1e-3        # ★ 容差 ✓：3.00 就是"刚好合规" ✓（浮点 ✗）
        print("   · %-7s 孔心 (%.2f, %.2f) mm｜离四条边 %s ⇒ %s"
              % (nm, MM(x - r[0]), MM(y - r[1]),
                 " / ".join("%.2f" % v for v in d),
                 "✓" if ok else "✗ 不足 %.1f mm ✗" % HOLE_EDGE_MM))
        if not ok:
            bad.append("%s 离板边 %.2f < %.1f ✗" % (nm, min(d), HOLE_EDGE_MM))

    print("\n② Ø%.1f keep-out 里不许有焊盘 ✓" % HOLE_KEEP_MM)
    for nm, hx, hy in hs:
        hits = []
        for q in model["pads"]:
            cx, cy = (q["box"][0] + q["box"][2]) / 2.0, (q["box"][1] + q["box"][3]) / 2.0
            dd = math.hypot(cx - hx, cy - hy) / PB.MM
            # 用"盘心到孔心 − 盘半对角"判是否进环 ✓（保守 ✓）
            half = math.hypot(q["box"][2] - q["box"][0], q["box"][3] - q["box"][1]) / 2.0 / PB.MM
            if dd - half < HOLE_KEEP_MM / 2.0:
                hits.append("%s.%s(%.2fmm)" % (q["title"], q["cid"], dd - half))
        print("   · %-7s %s" % (nm, ("入侵：%s ✗" % ", ".join(hits[:6])) if hits else "干净 ✓"))
        if hits:
            bad.append("%s keep-out 被 %d 个焊盘入侵 ✗" % (nm, len(hits)))

    # ③ / ⑦ 焊盘与本体都在板内 ✓
    print("\n③ 焊盘/本体都在板内（含净空 %.2f mm ✓）" % COPPER_EDGE_MM)
    e = U(COPPER_EDGE_MM)
    n_out = 0
    for q in model["pads"]:
        bx = q["box"]
        if bx[0] < r[0] + e or bx[1] < r[1] + e or bx[2] > r[2] - e or bx[3] > r[3] - e:
            n_out += 1
            print("   ✗ %s.%s 出板边：%.2f,%.2f,%.2f,%.2f mm"
                  % (q["title"], q["cid"], MM(bx[0] - r[0]), MM(bx[1] - r[1]),
                     MM(bx[2] - r[0]), MM(bx[3] - r[1])))
    print("   ⇒ %s" % ("全部在板内 ✓" if not n_out else "**%d 个焊盘出板 ✗**" % n_out))
    if n_out:
        bad.append("%d 个焊盘出板 ✗" % n_out)

    # ④ 不许压绕组 ✓
    cpart = None
    for p in model.get("parts", []):
        if p.get("title") == coil:
            cpart = p
            break
    cb = copper_box(cpart) if cpart else None
    print("\n④ 不许压线圈绕组（%s ✓）" % coil)
    if cb is None:
        print("   ⚠️ 量不到 %s 的铜箔框 ⇒ 这条**没查** ✗（不许当成通过 ✓）" % coil)
        bad.append("量不到线圈铜箔框 ⇒ 第 4 条未查 ✗")
    else:
        clr = U(COIL_CLR_MM)
        hit = []
        for q in model["pads"]:
            if q["title"] == coil:
                continue
            bx = q["box"]
            if (bx[0] < cb[2] + clr and cb[0] - clr < bx[2]
                    and bx[1] < cb[3] + clr and cb[1] - clr < bx[3]):
                hit.append("%s.%s" % (q["title"], q["cid"]))
        print("   绕组铜箔框 = (%.2f,%.2f)-(%.2f,%.2f) mm 相对板 ✓"
              % (MM(cb[0] - r[0]), MM(cb[1] - r[1]), MM(cb[2] - r[0]), MM(cb[3] - r[1])))
        print("   · %s" % ("没压 ✓" if not hit else (
            "有件压上：%s ⚠️（§6.1 允许 ✓，只提醒、不判错 ✓）" % ", ".join(sorted(set(hit))[:8]))))
        print("   ⚠️ 本条的绕组框**还不可靠** ✗（量出来 ≠ 19×20.2 mm ✓）"
              "⇒ 只当提醒看 ✓，**不能**当成通过 ✗。")
        # ★ 不再 `bad.append` ✓（用户 2026-09-30 选 (a)：压绕组**允许** ✓）
        # ⑤ 孔 keep-out 不进绕组 ✓
        for nm, hx, hy in hs:
            kr = U(HOLE_KEEP_MM / 2.0)
            if (hx - kr < cb[2] and cb[0] < hx + kr and hy - kr < cb[3] and cb[1] < hy + kr):
                bad.append("%s 的 keep-out 进绕组 ✗" % nm)
                print("   ✗ %s keep-out 进绕组 ✗" % nm)

    # ⑥ 焊盘朝内（符号判据 ✓）
    #    ✗ 旧版拿"焊盘框中心"当本体中心 ⇒ dot 恒为 0 ✗ ⇒ **空转的判据** ✗（2026-09-30 自查发现 ✗）
    #    ⇒ 改成用**画布中心**（= 件本体在草图上的中心 ✓，与 `render_pcb` 同一算法 ✓）。
    print("\n⑥ 连接器焊盘**朝板内**（符号判据 ✓，本体取**画布中心** ✓）")
    cen = ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)
    for p in model.get("parts", []):
        t = p.get("title") or ""
        if not t.startswith("J") or p.get("fzp") is None or not p.get("svg_text"):
            continue
        mine = [q["box"] for q in model["pads"] if q["title"] == t]
        if not mine:
            continue
        try:
            root = ET.fromstring(p["svg_text"])
            kk, _o = PB.svg_k(root)
            wmm, hmm = PB.canvas_mm(root.attrib)
            uv = PB._nums(root.get("viewBox"))
            q = PB.apply(p["M"], (uv[0] + uv[2] / 2.0 - uv[0]) * kk,
                         (uv[1] + uv[3] / 2.0 - uv[1]) * kk)
            bc = (p["loc"][0] + q[0], p["loc"][1] + q[1])
        except Exception:                                         # noqa: BLE001
            print("   · %-5s ⚠️ 算不出画布中心 ⇒ 这条没查 ✗" % t)
            bad.append("%s 的画布中心算不出 ⇒ 第 6 条未查 ✗" % t)
            continue
        pc = (sum((b2[0] + b2[2]) / 2.0 for b2 in mine) / len(mine),
              sum((b2[1] + b2[3]) / 2.0 for b2 in mine) / len(mine))
        dot = ((pc[0] - bc[0]) * (cen[0] - bc[0]) + (pc[1] - bc[1]) * (cen[1] - bc[1]))
        ok = dot > 0
        print("   · %-5s 焊盘簇 (%.2f,%.2f)｜画布中心 (%.2f,%.2f)｜板心 (%.2f,%.2f) mm｜dot=%+.2f"
              % (t, MM(pc[0] - r[0]), MM(pc[1] - r[1]), MM(bc[0] - r[0]), MM(bc[1] - r[1]),
                 MM(cen[0] - r[0]), MM(cen[1] - r[1]), dot / (PB.MM * PB.MM)))
        # ★★ 不判错 ✗（用户 2026-09-30 已**目视确认** J1/J2 朝向正确 ✓；
        #    而本条用的"画布中心"是个**坏代理量** ✗ —— 连接器的焊盘本来就在画布一角 ✓
        #    ⇒ dot 恒偏负 ✓，拿它判"朝外"会在正确摆位上误报 ✗）。机器判据待做 ✗。
    print("   ⇒ 本条**只打印不判错** ✓（朝向以**用户目视**为准 ✓；机器判据待做 ✗）")

    # ⑧ 本体/丝印（画出来的一切）必须在板内 ✓
    #    ★ 2026-09-30 补 ✗：第 ③ 条只查**焊盘** ✗ ⇒ 丝印出板看不见 ✗（用户两次指出的就是这个 ✗）。
    print("\n⑧ 本体/丝印（**画出来的一切**）在板内（含净空 %.2f mm ✓）" % COPPER_EDGE_MM)
    n_out2, n_unmeas = 0, 0
    for p in model.get("parts", []):
        t = p.get("title") or "?"
        # ★ 跳掉**不是 PCB 件**的那几个 ✓（板框自己 / 面包板件 / 过孔 ✓）——
        #   口径与 `pcb_check.collect` 一致 ✓；✗ 不跳的话面包板（830 孔）会被判"出板"✗
        mid = p.get("moduleId") or ""
        if mid == PP.BOARD_MID or mid.startswith(("Breadboard", "Via")):
            continue
        if not p.get("svg_text"):
            continue
        ib = ink_box_of(p)
        if ib is None:
            n_unmeas += 1
            print("   · %-5s ⚠️ 量不出墨迹框 ⇒ **这条没查** ✗（不许当成通过 ✓）" % t)
            continue
        g = (MM(ib[0] - r[0]), MM(ib[1] - r[1]), MM(r[2] - ib[2]), MM(r[3] - ib[3]))
        if min(g) < COPPER_EDGE_MM - 1e-3:
            n_out2 += 1
            print("   ✗ %-5s 出板：离四条边 %s mm ✗（负 = 出板 ✗）"
                  % (t, " / ".join("%.2f" % v for v in g)))
            bad.append("%s 的本体/丝印出板或贴边（最小 %.2f mm ✗）" % (t, min(g)))
    print("   ⇒ %s"
          % ("全部在板内 ✓" if not n_out2 else "**%d 个件的本体/丝印出板 ✗**" % n_out2))
    if n_unmeas:
        bad.append("%d 个件的墨迹框量不出 ⇒ 第 8 条未查 ✗" % n_unmeas)

    print("\n== 结论：%s ==" % ("**全过 ✓**" if not bad else "**%d 处不合格 ✗**" % len(bad)))
    for s in bad:
        print("   ✗ %s" % s)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
