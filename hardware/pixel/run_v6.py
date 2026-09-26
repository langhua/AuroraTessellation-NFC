# -*- coding: utf-8 -*-
r"""跑 pixel 面包板的完整流水线（一条命令、无 shell 引号问题 ✓）

 1) 原理图：EPAD → LED2.GND           fix_epad_ground.py  bb_src2 → bb_src3
 2) 面包板布线：EPAD → GND 电源轨       bb_route4.py        bb_src3 → bb_v6_raw
 3) 视图内图例                        bb_legend3.py       bb_v6_raw → pixel-breadboard6
 4) 核对：网表 / 自检对比 / 两版对比     check_netlist.py + bb_compare.py

用法：py -3.13 hardware/pixel/run_v6.py [输入 .fzz] [版本号] [对比参照 .fzz]
（★ 2026-09-27 入库：工具与中间产物都不再依赖草稿区 ✓）
"""
import os
import subprocess
import sys

# ★★ 2026-09-27（用户定 ✓）：本管线自定位 ✓（不写死机器路径 ✗）；
#   中间产物 → `_work/` ✓；成品 → 本目录 ✓；**通用工具在库仓 tools/** ✓（见 `toolpaths.py` ✓）。
PIXEL = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(PIXEL, "_work")
os.makedirs(WORK, exist_ok=True)
import toolpaths                                            # noqa: E402
TOOLS = toolpaths.TOOLS
PY = sys.executable

# 用法：py -3.13 run_v6.py [输入 .fzz] [版本号] [对比参照 .fzz]
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PIXEL, "pixel-breadboard43_byHand.fzz")
ver = sys.argv[2] if len(sys.argv) > 2 else "7"
ref = sys.argv[3] if len(sys.argv) > 3 else os.path.join(PIXEL, "pixel-breadboard43_byHand.fzz")
sch_fixed = os.path.join(WORK, "sch_epad_fixed.fzz")
raw = os.path.join(WORK, "bb_raw.fzz")
final = os.path.join(PIXEL, "pixel-breadboard%s.fzz" % ver)

STEPS = [
    ("1 原理图 EPAD→LED2.GND", [PY, os.path.join(PIXEL, "fix_epad_ground.py"),
                                src, sch_fixed]),
    ("2 面包板布线（EPAD→GND 电源轨）", [PY, os.path.join(PIXEL, "bb_route4.py"),
                                        sch_fixed, raw]),
    ("3 图例写进视图", [PY, os.path.join(TOOLS, "bb_legend3.py"), raw, final,
                        "590", "12", "12", "19", "-3",
                        os.path.join(PIXEL, "pixel-breadboard59.fzz")]),
    ("4a 网表核对", [PY, os.path.join(PIXEL, "check_netlist.py"), final]),
    ("4b 与参照版对比", [PY, os.path.join(TOOLS, "bb_compare.py"), ref, final]),
    ("4c 文件自检（颜色/零长/属性 ✓）", [PY, os.path.join(TOOLS, "file_sanity.py"), final]),
    # ★ 悬空连接记录清扫 ✓（2026-09-26 用户实测 ✗）：删了旧导线，但“孔 → 那根线”的记录
    #   还留着 ✗ ⇒ Fritzing 里那些孔显示接在不存在的线上 ✗（悬停时一大片亮 ✓）。
    #   实测我以前的版本各 **12 处** ✗、用户手画版 **0 处** ✓ ⇒ 交付前清掉 ✓。
    ("4d 清悬空连接记录", [PY, os.path.join(TOOLS, "fix_connects.py"), final, final]),
]

for title, cmd in STEPS:
    print("\n" + "=" * 78)
    print("== %s" % title)
    print("   %s" % " ".join(os.path.basename(c) if i == 1 else c for i, c in enumerate(cmd)))
    print("=" * 78)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(l for l in out.splitlines() if l.strip()))
    print("   [exit %d]" % r.returncode)
    if r.returncode != 0:
        print("!! 第 %s 步失败 ⇒ 停下（不继续往下跑）" % title)
        sys.exit(r.returncode)

print("\n全部完成 ✓  产物: %s" % final)
