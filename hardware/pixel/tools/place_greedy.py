# -*- coding: utf-8 -*-
r"""临时 ✓：**贪心套挪** —— 一轮一轮地挪，直到"还差 0 条"或挪不动 ✓

✗ 为什么要它 ✗：首轮单件扫描已经证明**挪动能把"还差几条连接"往下压** ✓（3 → 2 ✓），
  但那只是"挪一件、看一眼" ✗ ⇒ 要真正逼近全通 ✓，得**贪心套挪** ✓：
  接受最好的一步 ⇒ **在它里面继续扫** ✓ ⇒ 直到没改进 ✓。
★ 判据 = 交付同一把尺子 ✓：`(-还差几条连接, 连通网数)` ✓（**差 0 条 ⟺ 全通** ✓）。
★★ **合法闸门** ✓（不许为了连通把件摞在一起 ✗）：每一步都先用 `pcb_check` 的**结构检查**
  （①–④·⑥ ⑧ ✓，**不跑** ⑤ 网表 ✗）过一遍 ✓ —— 压件 / 出板 / 过孔违规一律**不采纳** ✗。
★ 只挪**电子件** ✓：`H1/H2`（安装孔 ✓）、`L1`（**传感线圈** ✓）、`J1/J2`（对插件 ✓）三个
  有机械/功能意义 ⇒ **不动** ✗（依据见 README §44 ✓）。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
WORK = os.path.join(PIX, "_work")     # ★ 候选/日志/底图仍写草稿区 ✓（保持工具目录干净 ✓）


def _find_tools(start):
    d = start
    for _ in range(6):
        cand = os.path.join(d, "fritzing-parts-langhua", "tools")
        if os.path.isdir(cand):
            return cand
        d = os.path.dirname(d)
    raise SystemExit("✗ 找不到 tools ✓")


sys.path.insert(0, _find_tools(PIX))
sys.path.insert(0, PIX)
sys.path.insert(0, HERE)

import pcb_check as PC        # noqa: E402
import pcb_route as RT        # noqa: E402
import projdata              # noqa: E402
from nudge_sweep2 import write_zip       # noqa: E402
from beep import done                    # noqa: E402

PASSES, BLOCKERS, EC = 8, 16, 0.3
OFFS = [(1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2),
        (1, 1), (1, -1), (-1, 1), (-1, -1)]


def flip_zip(src, dst, title):
    """★ **翻面** ✓：给某件的 `<pcbView>` **加/去 `bottom="true"`** ✓（位置不动 ✓）

    ✗ 为什么可以这么简单 ✗（**读实了** ✓）：`C1` 已经就在背面 ✓，而它的 `<transform>`
      是**单位阵** ✓（`m11≈1, m22≈1` ✓）⇒ **“在背面”只靠 `bottom="true"` 一个属性** ✓，
      **镜像由查看器做** ✗（不写进文件 ✗）；而本仓 `pcb_pads.py` 已经**同一个口径** ✓
      （背面件：**铜层 copper0↔copper1 对调** ✓ ＋ **x 镜像** ✓，码里写明 ✓）。
    ★ 于是候选集里多一族 ✓：“**这一件翻到另一面**” ✓（位置不动 ✓）。
    """
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    t = z.read(name).decode("utf-8")
    out = None
    for m in re.finditer(r"<instance\b[^>]*>", t):
        end = t.find("</instance>", m.start())
        blk = t[m.start():end]
        if ("<title>%s</title>" % title) not in blk:
            continue
        v0 = blk.find("<pcbView")
        v1 = blk.find(">", v0)
        tag = blk[v0:v1 + 1]
        if 'bottom="true"' in tag:
            new = tag.replace(' bottom="true"', "")          # 翻回正面
        else:
            new = tag.replace("<pcbView", '<pcbView bottom="true"', 1)
        out = (t[:m.start()] + blk[:v0] + new + blk[v1 + 1:] + t[end:])
        break
    if out is None:
        z.close()
        raise SystemExit("✗ 找不到实例 %s" % title)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as w:
        for n in z.namelist():
            w.writestr(n, out.encode("utf-8") if n == name else z.read(n))
    z.close()
    return dst


def setup(fzz):
    data = projdata.load(os.path.join(PIX, "pixel_nets.py"), need=("NETS",))
    m = PC.collect(fzz)
    pads = RT.pad_index(m)
    net_pads, _u = RT.resolve_nets(m, data.NETS)
    m["net_pads"] = net_pads
    items, st = RT.obstacles(m)
    ck = [b for q in (m.get("bodies") or ()) for lay, b, _i in (q.get("shapes") or ())
          if lay in ("copper0", "copper1")]
    _omg = RT.make_grid
    RT.make_grid = lambda rect, cell, its, extra=(), skip_tag=None, labels=None: \
        _omg(rect, cell, its, extra, skip_tag, labels=st["labels"])
    return m, pads, net_pads, items, ck


def legal(fzz):
    """★ 结构合法吗 ✓（①–④·⑥ ⑧ ✓；**不跑** ⑤ 网表 ✗）—— 压件/出板一律不采纳 ✗

    ★★ ⑫ **必须排除** ✗✓（2026-10-06 实测 ✓）：底图 `v69_bare.fzz` 自己就带着
      **100 条悬空声明** ✗（剥线时把被声明的对象删了 ✓、却把 `<connect>` 留着 ✓）
      ⇒ 从它派生出来的**每一个**候选都脏 ✗ ⇒ 一加 ⑫ 就会**全部**被否 ✗
      （实测：12 个方向 × 3 个件 **全部**报"⑫ 悬空声明 100 条"✗ ⇒ 一步也走不动 ✓）。
    ⇒ 这里只问**几何结构** ✓（压件/出板/过孔 ✓）；**⑫ 是交付闸门** ✓（见 P1 ✓），
      该修的是**写回器**：**它删掉/换掉的对象，对应的 `<connect>` 必须一起清** ✗。
    """
    try:
        m = PC.collect(fzz)
        probs, _n, _g = PC.check(m, expect=None)
    except Exception as exc:                                  # noqa: BLE001
        return "读不出（%s）" % exc
    bad = [p for p in probs if not p.startswith("⑤") and not p.startswith("⑫")]
    return "" if not bad else bad[0][:60]


def score(fzz):
    m, pads, net_pads, items, ck = setup(fzz)
    res = RT.route_ripup(items, m["board"], net_pads, pads, RT.CELL_MM, RT.K_VIA,
                         tries=6, passes=PASSES, blockers=BLOCKERS, copper_keep=ck)
    miss = sum(int(d.get("miss", 0)) for d in res.values())
    ok = sum(1 for d in res.values() if d.get("ok"))
    bad = sorted(n for n in res if not res[n].get("ok"))
    return miss, ok, bad


def main(argv):
    base = argv[0] if argv else os.path.join(WORK, "v69_bare.fzz")
    logf = open(os.path.join(WORK, "_pg_log.txt"), "w", encoding="utf-8")

    class _T(object):                      # ★ 日志写文件 ✓（✗ 上次结果随终端丢失 ✓）
        def write(self, s):
            logf.write(s)
            sys.__stdout__.write(s)
            logf.flush()

        def flush(self):
            pass

    sys.stdout = _T()
    parts = [s for a in argv if a.startswith("--parts=")
             for s in a.split("=", 1)[1].split(",") if s]
    want_flip = "--noflip" not in argv
    rounds = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--rounds=")), "2"))
    RT.TRACE_MIL = 8
    RT.TRACE_MM = 8 * RT.MIL_MM
    RT.ESCAPE_COST_MM = EC
    RT.Grid.OWN = True
    cur = base
    print("== 贪心套挪 ✓（可挪：%s ✓｜%d 轮 ✓｜判据 = 还差几条连接 ✓）=="
          % (",".join(parts), rounds))
    miss, ok, bad = score(cur)
    print("   起点                还差 **%2d** 条 ✓｜连通 %d/9 ✓｜未通 %s"
          % (miss, ok, "、".join(bad) or "无 ✓"))
    key = (miss, -ok)
    for rnd in range(1, rounds + 1):
        if miss == 0:
            print("   ✓ 已经全通 ⇒ 停 ✓")
            break
        best = None
        for title in parts:
            cands = [(("%s %+d %+d" % (title, dx, dy)),
                      (lambda s, d, ti=title, a=dx, b=dy: write_zip(s, d, ti, a, b)))
                     for (dx, dy) in OFFS]
            if want_flip:                  # ★ 翻面这一族 ✓（位置不动 ✓）
                cands.append(("%s 翻面" % title,
                              (lambda s, d, ti=title: flip_zip(s, d, ti))))
            for tag, maker in cands:
                dst = os.path.join(WORK, "_pg_r%d_%s.fzz"
                                   % (rnd, tag.replace(" ", "_").replace("+", "p")
                                      .replace("-", "m")))
                try:
                    maker(cur, dst)
                except SystemExit as exc:
                    print("      %-14s ✗ 挪不动（%s）" % (tag, exc))
                    continue
                ill = legal(dst)
                if ill:
                    print("      %-14s ✗ 结构非法：%s" % (tag, ill))
                    continue
                m2, o2, b2 = score(dst)
                mark = ""
                if (m2, -o2) < key:
                    best = (m2, o2, b2, dst, tag)
                    key = (m2, -o2)
                    mark = "  ← **更好** ✓"
                print("      %-14s 还差 **%2d** 条 ✓｜连通 %d/9 ✓｜未通 %s%s"
                      % (tag, m2, o2, "、".join(b2) or "无 ✓", mark))
        if not best:
            print("   ⇒ 第 %d 轮：**没有一步更好** ⇒ 停 ✓" % rnd)
            break
        print("   ⇒ 第 %d 轮采纳 ✓：挪 %s ⇒ 还差 **%d** 条 ✓（连通 %d/9 ✓）｜文件 %s"
              % (rnd, best[4], best[0], best[1], os.path.basename(best[3])))
        cur = best[3]
        miss, ok = best[0], best[1]
    print("\n⇒ 收工 ✓：`%s` ⇒ 还差 **%d** 条 ✓（连通 %d/9 ✓）" % (os.path.basename(cur), miss, ok))
    return 0


if __name__ == "__main__":
    # ★ 收工**响一声** ✓（2026-10-06 用户要的 ✓）：成功上行三声 ✓ / 失败下行两声 ✓
    try:
        _rc = main(sys.argv[1:])
    except BaseException:
        done(ok=False)
        raise
    done(ok=(_rc == 0))
    raise SystemExit(_rc)
