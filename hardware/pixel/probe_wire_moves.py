# -*- coding: utf-8 -*-
r"""独立复核：**换件之后，哪些走线的端点动了** ✓（只读 ✓，不写任何文件 ✗）

★ 为什么要单独一个工具 ✗（2026-10-11 ✓，为 `C2` 换 0603 加的 ✓）：
  `swap_rc_0603.py` 换完件会**报**"平移 loc = …" ✓，但那是**它自己的说法** ✗ ——
  本仓规矩：**不许自证** ✗（同一份几何自己写、自己核 ⇒ 两边一起错也看不出来 ✓）。
  本工具**只读两个 `.fzz` 的原文** ✓、按 `<geometry>` 换算绝对端点 ✓，与换件工具**零共享代码** ✓
  ⇒ 谁对谁错，拿它对一眼就知道 ✓。

判据（就一条 ✓，量出来的 ✓）：
  同一条走线（按 `<title>` 认 ✓，✗ 不认 modelIndex ✗ —— 另存会重编号 ✓）在两个文件里的
  **两个绝对端点** 各差多少 ✓；> 1e-6 mm 就算"动了" ✓。

用法：py -3.13 probe_wire_moves.py <改前.fzz> <改后.fzz> [--min 0.001]
退出码：恒 0 ✓（这是**量尺**，不是闸门 ✗）。
"""
import argparse
import re
import sys
import zipfile

MM = 25.4 / 90.0                      # 草图单位 → mm ✓（1 单位 = 1/90 in ✓）
GEO = re.compile(
    r'<geometry[^>]*\bx="(-?[\d.]+)"\s+y="(-?[\d.]+)"[^>]*'
    r'\bx1="(-?[\d.]+)"\s+y1="(-?[\d.]+)"[^>]*'
    r'\bx2="(-?[\d.]+)"\s+y2="(-?[\d.]+)"')


def read_fz(path):
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist() if n.endswith(".fz")][0]
        return z.read(name).decode("utf-8")


def wire_ends(text):
    """⇒ {title: (ax, ay, bx, by)}（mm ✓，绝对坐标 ✓）"""
    out = {}
    for m in re.finditer(r'<instance moduleIdRef="WireModuleID".*?</instance>', text, re.S):
        blk = m.group(0)
        t = re.search(r"<title>([^<]+)</title>", blk)
        g = GEO.search(blk)
        if not (t and g):
            continue
        v = [float(g.group(i)) for i in range(1, 7)]
        out[t.group(1)] = ((v[0] + v[2]) * MM, (v[1] + v[3]) * MM,
                           (v[0] + v[4]) * MM, (v[1] + v[5]) * MM)
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--min", type=float, default=1e-6, help="超过它才算动了（mm ✓）")
    a = ap.parse_args(argv)
    wa, wb = wire_ends(read_fz(a.before)), wire_ends(read_fz(a.after))
    print("== 走线端点变化：%s → %s ==" % (a.before, a.after))
    print("   改前 %d 条 ✓／改后 %d 条 ✓" % (len(wa), len(wb)))
    moved, same, gone, new = 0, 0, [], []
    for t in sorted(set(wa) | set(wb)):
        if t not in wa:
            new.append(t)
            continue
        if t not in wb:
            gone.append(t)
            continue
        d = [wb[t][i] - wa[t][i] for i in range(4)]
        n = max(abs(v) for v in d)
        if n <= a.min:
            same += 1
            continue
        moved += 1
        which = ("A" if max(abs(d[0]), abs(d[1])) > abs(d[2]) else "B")
        print("   %-14s %s 端动了 ✓  Δmax %.4f mm ｜ A (%.4f,%.4f)→(%.4f,%.4f) ｜ "
              "B (%.4f,%.4f)→(%.4f,%.4f)" % (
                  t, which, n, wa[t][0], wa[t][1], wb[t][0], wb[t][1],
                  wa[t][2], wa[t][3], wb[t][2], wb[t][3]))
    print("\n⇒ 端点动了的 **%d** 条 ✓；没动 %d 条 ✓；删掉 %d 条；新增 %d 条" % (
        moved, same, len(gone), len(new)))
    if gone:
        print("   删掉：" + "、".join(gone))
    if new:
        print("   新增：" + "、".join(new))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
