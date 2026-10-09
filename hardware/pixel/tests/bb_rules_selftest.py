# -*- coding: utf-8 -*-
r"""bb_rules_selftest：面包板两条规则（① 就近选孔 ✓ ② 能直就直 ✓）的**单元自测** ✓

★ 位置（仓规 ✓）：项目自己的测试放 `hardware/pixel/tests/` ✓（通用工具的测试在库仓
  `fritzing-parts-langhua/tools/tests/` ✓）；命名保留 `*_selftest.py` ✓；
  一行跑全部见 `tests\run_all.py` ✓。
★ 路径：库仓工具**只从 `toolpaths.py` 认** ✓（唯一实现 ✓），不写死机器路径 ✗。

三段 ✓：
  ① **小尺子**（规则② 的判据 ✓）：`route_len()` —— 同行/同列 ⇒ 0 拐点 ✓、否则 L 1 拐点 ✓；
  ② **交付件锁**（回归锁 ✓）：`tools\bb_probe.py` 跑 `pixel-pcb-v81.fzz` ⇒ **全过** ✓
     ＋ 三个关键数（跳线段数 28 ✓ / 拐点直方图 ✓ / 总长 337.1 mm ✓）**钉死** ✓
     —— 以后谁改坏了面包板，这里先红 ✓（不要"改期望值"来消红 ✗）。
  ③ **开关默认关**（零副作用的前提 ✓）：生成器里两个开关的缺省必须是 `False` ✓。

用法：py -X utf8 tests\bb_rules_selftest.py
"""
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                            # noqa: E402
sys.path.insert(0, toolpaths.TOOLS)

ok = True


def chk(name, cond, extra=""):
    global ok
    print("  %s %s %s" % ("✓" if cond else "✗", name, extra))
    if not cond:
        ok = False


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


print("== ① 规则② 的小尺子 `route_len()`（同行/同列 ⇒ 0 拐点 ✓）==")
probe = load(os.path.join(PIX, "tools", "bb_probe.py"), "bb_probe_t")
chk("同行 ⇒ (0, 曼哈顿)", probe.route_len((0.0, 54.0), (135.0, 54.0)) == (0, 135.0))
chk("同列 ⇒ (0, 曼哈顿)", probe.route_len((153.0, 54.0), (153.0, 171.0)) == (0, 117.0))
chk("不同行不同列 ⇒ 1 拐点", probe.route_len((297.0, 63.0), (288.0, 126.0)) == (1, 72.0))

print("\n== ② 交付件锁：`pixel-pcb-v81.fzz` 的面包板探针 = 全过 ✓ ==")
v81 = os.path.join(PIX, "pixel-pcb-v81.fzz")
if not os.path.isfile(v81):
    chk("交付件在（`pixel-pcb-v81.fzz` ✓）", False)
else:
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(PIX, "tools", "bb_probe.py"), v81],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=toolpaths.TOOLS))
    out = (r.stdout or "") + (r.stderr or "")
    chk("探针 exit 0（11 项全过 ✓）", r.returncode == 0,
        "" if r.returncode == 0 else "\n" + out[-1200:])
    chk("跳线 19 根 = 28 段 ✓", "跳线 19 根 = 28 段" in out)
    chk("拐点直方图钉死 {0:11, 1:7, 2:1} ✓", "{0: 11, 1: 7, 2: 1}" in out)
    chk("总长钉死 337.1 mm ✓", "总长 337.1 mm" in out)
    chk("「不是最近孔」= 0 ✓", "✓ ⑧ 「不是最近孔」的跳线数 = 0" in out)

print("\n== ③ 生成器的两个开关缺省**关** ✓（零副作用的前提 ✓）==")
src = open(os.path.join(toolpaths.TOOLS, "bb_route4.py"), encoding="utf-8").read()
chk("`--near-hole` 开关在（且缺省 False ✓）",
    'NEAR_HOLE = "--near-hole" in FLG' in src)
chk("`--straight` 开关在（且缺省 False ✓）",
    'STRAIGHT = "--straight" in FLG' in src)
chk("两条规则的实现都在（`pass_near_hole` / `pass_straight` ✓）",
    "def pass_near_hole(" in src and "def pass_straight(" in src)
chk("**不比交叉** ✓：规则的小尺子只看（拐点, 总长 ✓）",
    "def _score(pts):" in src and "不含交叉" in src)

print("\n⇒ %s" % ("✓ 全过" if ok else "✗ 有不过"))
sys.exit(0 if ok else 1)
