# -*- coding: utf-8 -*-
r"""把南侧那条 5V 改成**绕板子下边走**（用户 2026-11-10 定 ✓「AB」✓）

用法：py -3.13 _work\patch_5v_south.py <in.fzz> <out.fzz>

★ 改的是**具体这几根线**（不是通用规则）✗ —— 所以写成一次性补丁工具 ✓，
  改完必须过 `pcb_check`（④ 同层重叠 / ⑦ 净距 / ⑤ 连通 ✓）。
★ 原路径（穿三只件的两排焊盘之间）：
    D4.0 (46.510,31.590) → (46.526,30.572) → (41.026,30.572) → R2.1 (41.000,29.880)
  新路径（绕南侧 ✓，全部在 copper0，不新增过孔 ✓）：
    D4.0 → (46.510,32.450) → (40.200,32.450) → (40.200,29.880) → R2.1
  ★ 顺带治好"两条分支差 0.1 mm"那个错位 ✓（西向分支现在从焊盘**向南**出发 ✓）。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"f:\git\fritzing-parts-langhua\tools")
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pcb_pads as PP                                            # noqa: E402
if "path" not in PP.PADLIKE:
    PP.PADLIKE = tuple(PP.PADLIKE) + ("path",)
import gen_routes as GR                                          # noqa: E402

SK = 25.4 / 90.0
U = lambda mm: round(mm / SK, 5)                                  # noqa: E731


def find_wire(text, a_mm, b_mm, tol=0.02):
    """按两端点（mm ✓）找走线实例块 ✓ ⇒ `(modelIndex, block, a, b)` 或 None"""
    A = (U(a_mm[0]), U(a_mm[1]))
    B = (U(b_mm[0]), U(b_mm[1]))
    for m in re.finditer(r'(?ms)^[ \t]*<instance\b[^>]*modelIndex="(\d+)".*?\n[ \t]*</instance>',
                         text):
        blk = m.group(0)
        if "WireModuleID" not in blk or "<pcbView" not in blk:
            continue
        g = re.search(r'<pcbView[^>]*>\s*<geometry\s+([^>]*)/>', blk)
        if not g:
            continue
        d = dict(re.findall(r'([\w]+)="([^"]*)"', g.group(1)))
        x, y = float(d["x"]), float(d["y"])
        x2, y2 = float(d.get("x2", 0)), float(d.get("y2", 0))
        p, q = (x, y), (x + x2, y + y2)
        for s, e in ((p, q), (q, p)):
            if abs(s[0] - A[0]) <= tol / SK and abs(s[1] - A[1]) <= tol / SK and \
               abs(e[0] - B[0]) <= tol / SK and abs(e[1] - B[1]) <= tol / SK:
                return m.group(1), blk, p, q
    return None


def find_part(text, title):
    """按 `<title>D4</title>` 找元件实例 ⇒ `(modelIndex, connector->layer, block)` ✓

    ★ 层**只在 `pcbView` 段里取** ✗ —— 一个块里面包板/原理图/PCB 三个视图都有 connector ✓，
      整块扫会拿到 `schematic` ✗（第一版就这么错 ✓：写出 `<connect layer="schematic">` ✗）。
    """
    for m in re.finditer(r'(?ms)^[ \t]*<instance\b[^>]*modelIndex="(\d+)".*?\n[ \t]*</instance>',
                         text):
        blk = m.group(0)
        t = re.search(r"<title>([^<]*)</title>", blk)
        if not t or t.group(1) != title:
            continue
        pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", blk)
        seg = pv.group(1) if pv else ""
        lay = dict(re.findall(r'<connector connectorId="(connector\d+)" layer="([^"]*)"', seg))
        return m.group(1), lay, blk
    return None, None, None


def main(argv):
    src, dst = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    names = z.namelist()
    data = {n: z.read(n) for n in names}
    key = [n for n in names if n.endswith(".fz")][0]
    text = data[key].decode("utf-8")

    # ── 1. 找要删的三根（西向那条链 ✓）
    chain = [((46.510, 31.590), (46.526, 30.572)),
             ((46.526, 30.572), (41.026, 30.572)),
             ((41.026, 30.572), (41.000, 29.880))]
    dels = []
    for (a, b) in chain:
        hit = find_wire(text, a, b)
        if not hit:
            print("✗ 找不到走线 (%.3f,%.3f)→(%.3f,%.3f) ✗" % (a[0], a[1], b[0], b[1]))
            return 1
        dels.append(hit)
        print("  · 待删 %s（%.3f,%.3f）→（%.3f,%.3f）" % (hit[0], hit[2][0] * SK, hit[2][1] * SK,
                                                       hit[3][0] * SK, hit[3][1] * SK))

    d4_mi, d4_lay, _ = find_part(text, "D4")
    r2_mi, r2_lay, _ = find_part(text, "R2")
    if not d4_mi or not r2_mi:
        print("✗ 找不到 D4 / R2 ✗")
        return 1
    print("  · D4 = %s（connector0 层 %s）｜R2 = %s（connector1 层 %s）"
          % (d4_mi, d4_lay.get("connector0"), r2_mi, r2_lay.get("connector1")))

    # ── 2. 删掉旧块
    for (mi, blk, _p, _q) in dels:
        text = text.replace(blk, "", 1)
    print("  ✓ 删掉 %d 根旧走线 ✓" % len(dels))

    # ── 3. 造新块
    mi0 = max(int(x) for x in re.findall(r'modelIndex="(\d+)"', text)) + 1
    wt = [int(x) for x in re.findall(r"<title>Wire(\d+)</title>", text)]
    n0 = max(wt) + 1 if wt else 1
    P = [(46.510, 31.590), (46.510, 32.450), (40.200, 32.450), (40.200, 29.880), (41.000, 29.880)]
    U4 = [(U(p[0]), U(p[1])) for p in P]
    mis = ["%d" % (mi0 + k) for k in range(4)]
    lay = "copper0"
    tlay = "copper0trace"
    d4_cid, d4_decl = "connector0", d4_lay.get("connector0", "copper0")
    r2_cid, r2_decl = "connector1", r2_lay.get("connector1", "copper0")

    blocks = []
    for k in range(4):
        conns = []
        # 起端
        if k == 0:
            conns.append((0, (d4_cid, d4_mi, d4_decl)))
        else:
            conns.append((0, ("connector1", mis[k - 1], tlay)))
        # 终端
        if k == 3:
            conns.append((1, (r2_cid, r2_mi, r2_decl)))
        else:
            conns.append((1, ("connector0", mis[k + 1], tlay)))
        blocks.append(GR.wire_block("5V", 900 + k, n0 + k, mis[k], lay,
                                    U4[k], U4[k + 1], conns, "#cc1414", 8))
    print("  ✓ 新造 %d 段（%s ✓）：%s" % (len(blocks), lay,
                                        " → ".join("(%.2f,%.2f)" % p for p in P)))

    # ── 4. 插到最后一个 Wire 实例之后
    last = None
    for m in re.finditer(r'(?ms)^[ \t]*<instance\b[^>]*WireModuleID.*?\n[ \t]*</instance>\n', text):
        last = m
    if last is None:
        print("✗ 找不到可插入的位置 ✗")
        return 1
    text = text[:last.end()] + "".join(blocks) + text[last.end():]

    # ── 5. 焊盘侧回指 ✓（与生成器同一套 ✓）
    edits = [(d4_mi, d4_cid, d4_decl, "connector0", mis[0], tlay),
             (r2_mi, r2_cid, r2_decl, "connector1", mis[3], tlay)]
    text, n, miss, why, _b = GR.add_backrefs(text, edits)
    print("  ✓ 焊盘回指补 %d 处（补不上 %d）" % (n, miss))
    for w in why:
        print("      %s" % w)

    # ── 6. 清掉指向已删走线的声明 ✗（否则 ⑫ 悬空声明 ✗）
    text, n_rm, n_odd = GR.prune_dangling(text)
    print("  ✓ 清掉悬空声明 %d 条 ✓（写法异常没敢动 %d 条）" % (n_rm, n_odd))

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
