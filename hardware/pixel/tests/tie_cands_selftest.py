# -*- coding: utf-8 -*-
r"""tie_cands_selftest：`tie_cands()` 的**单元自测** ✓（不用任何 .fzz ✓ —— 与 `sch_body_selftest.py` 同一手法 ✓）

★ 位置（2026-10-09 用户定 ✓）：**测试一律放 `<项目仓>/tests/`** ✓（通用工具的测试在
  库仓 `fritzing-parts-langhua/tools/tests/` ✓）—— 本项目从 `_work/`（**被忽略** ✗）**上收** ✓。
★ 命名保留 `*_selftest.py` ✓ —— ✗ 故意不叫 `test_*.py` ✗（pytest 会收集它、被模块级
  `SystemExit` 打崩 ✓）；一行跑全部见 `tests\run_all.py` ✓。
★ 路径：库仓工具**只从 `toolpaths.py` 认**（唯一实现 ✓，见该文件头 ✓），不写死机器路径 ✗。

用法：py -X utf8 tests\tie_cands_selftest.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)                  # hardware/pixel ✓
sys.path.insert(0, PIX)
import toolpaths                             # noqa: E402  —— 已把库仓 tools/ 放进 sys.path ✓
sys.path.insert(0, toolpaths.TOOLS)
GEN = os.path.join(PIX, "gen_schematic_wires.py")
spec = importlib.util.spec_from_file_location("gsw", GEN)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ok = True


def chk(name, cond, extra=""):
    global ok
    print("  %s %s %s" % ("✓" if cond else "✗", name, extra))
    if not cond:
        ok = False


print("== `tie_cands()` 单元自测 ==")

# ① 教科书情形：b 在一条已布同网导线的一端上 ⇒ 必须给出「搭到它的另一端」的候选
used = [((58.578, 9.0), (27.378, 9.0), "GND"),
        ((27.378, 9.0), (27.378, -43.2), "GND"),
        ((27.378, -43.2), (74.778, -43.2), "GND")]
out = m.tie_cands((15.378, 9.0), (58.578, 9.0), used, "GND")
paths = [[(round(p[0], 3), round(p[1], 3)) for p in q] for q in out]
chk("① a→(27.378,9) 的直连候选在里", [(15.378, 9.0), (27.378, 9.0)] in paths, str(paths[:3]))
chk("① 候选数 > 0", len(out) > 0, "共 %d 条" % len(out))

# ② 安全判据：b **不在**任何已布同网导线上 ⇒ 一条都不给（宁可不做 ✗，也不许断开网表 ✓）
out2 = m.tie_cands((15.378, 9.0), (100.0, 100.0), used, "GND")
chk("② b 不在同网导线上 ⇒ 0 条", out2 == [])

# ③ 异网不算数：把同一批段标成别的网 ⇒ 0 条
out3 = m.tie_cands((15.378, 9.0), (58.578, 9.0), used, "5V")
chk("③ 异网段 ⇒ 0 条", out3 == [])

# ④ 不会把 a 自己当端点（长度 0 的“点导线”永不成候选）
out4 = m.tie_cands((15.378, 9.0), (58.578, 9.0),
                   used + [((15.378, 9.0), (15.378, 9.0), "GND")], "GND")
chk("④ 退化段不参与", all(len(q) >= 2 and m.math.dist(q[0], q[-1]) > 0.05 for q in out4))

# ⑥ ★ 反过来那一支（`a` 已被主干占住 ⇒ 只画 `b → E` 那半截 ✓，`path[-1]` 必须是 `b` ✓）
out6 = m.tie_cands((58.578, 9.0), (15.378, 9.0), used, "GND")
p6 = [[(round(p[0], 3), round(p[1], 3)) for p in q] for q in out6]
chk("⑥ 反向支给出 [(27.378,9),(15.378,9)]",
    [(27.378, 9.0), (15.378, 9.0)] in p6, str(p6[:3]))
chk("⑥ 反向支的末点都是 b", all(abs(q[-1][0] - 15.378) < 0.05 and abs(q[-1][1] - 9.0) < 0.05
                              for q in out6))

# ⑤ `plen`：`detour` 对“先出再回”的折线必须 > 0 ✓、对单调楼梯必须 = 0 ✓
chk("⑤ 折线 plen 比曼哈顿大", m.plen([(0, 0), (9, 0), (9, 3), (30, 3), (30, 0)]) - 30.0 > 5.0)
chk("⑤ 单调楼梯 = 曼哈顿",
    abs(m.plen([(0, 0), (9, 0), (9, 30)]) - 39.0) < 1e-9)

print("\n⇒ %s" % ("✓ 全过" if ok else "✗ 有不过"))
sys.exit(0 if ok else 1)
