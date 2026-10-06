# -*- coding: utf-8 -*-
r"""★★ **唯一的一把尺子** ✓ —— 量一个候选摆位，只调**驱动器本人** ✓。

✗ 为什么必须这样 ✗（2026-10-06 实测 ✓，仓规 §13「只允许一个声音」✓）：
  我的「贪心挪位搜索」**自己抄了一份路由口径** ✗ ⇒ 它报 `8/9 ✓ 差 2` ✓，
  我用**默认开关**去复核 ⇒ 报 `4/9 ✗ 差 7` ✗ ⇒ 我以为"改进是假的" ✗；
  再用**交付那把开关**（`--no-lock --first= --escape-cost=0.3 --no-mid-keep …` ✓）
  复核 ⇒ `ok=8 miss=2` ✓ —— **和我的一字不差** ✓。
⇒ 教训（**两头都栽过** ✓）：尺子不是"驱动器 vs 我" ✗，而是**"哪一套开关"** ✗。
  所以这里把**交付那把开关**写死成 `BASE` ✓，谁要量都走这一个入口 ✓。

★ 开关次序有讲究 ✗：驱动器取 `--first=` / `--mil=` 这类是 **`next(第一个匹配)`** ✓
  ⇒ **调用方给的额外开关要放在前面** ✓（后面 `BASE` 里的 `--first=` 才会被忽略 ✓）。
★ 用法：
    py -3.13 tools\measure.py <候选.fzz>                 # 量一个
    py -3.13 tools\measure.py <候选.fzz> --sweep         # 在它上面扫一组次序开关
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
WORK = os.path.join(PIX, "_work")     # ★ 候选/日志/底图仍写草稿区 ✓（保持工具目录干净 ✓）
PY = sys.executable
DRV = os.path.join(PIX, "gen_routes.py")
NETS = os.path.join(PIX, "pixel_nets.py")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from beep import done                                      # noqa: E402

# ★ **交付那把开关** ✓（出处：`_work/gen_v70.cmd` / `verify_check.cmd` ✓，
#   2026-10-06 用 `--measure-only` 逐项复现 `ok=7 miss=3 len=282.8` ✓）
BASE = ["--mil=8", "--no-lock", "--first=", "--escape-cost=0.3",
        "--no-mid-keep", "--blockers=16", "--passes=8", "--layer-pen=0.35"]

RE_M = re.compile(r"^MEASURE ok=(\d+) nets=(\d+) miss=(\d+) len_mm=([\d.]+) "
                  r"vias=(\d+) bad=(\S+)$")


def measure(fzz, extra=()):
    """⇒ `(ok, nets, miss, len_mm, vias, bad)` ✓；读不出 ⇒ `None` ✗。"""
    cmd = ([PY, "-u", "-X", "utf8", DRV, fzz, "_", "--nets=" + NETS,
            "--measure-only"] + list(extra) + BASE)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    txt = p.stdout.decode("utf-8", "replace")
    for line in txt.splitlines():
        m = RE_M.match(line.strip())
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    float(m.group(4)), int(m.group(5)), m.group(6))
    return None


SWEEP = [
    ("（原样）", []),
    ("--first=RC", ["--first=RC"]),
    ("--first=5V,RC", ["--first=5V,RC"]),
    ("--first=GND", ["--first=GND"]),
    ("--last=GND", ["--last=GND"]),
    ("--first=RC --last=GND", ["--first=RC", "--last=GND"]),
    ("--first=RC,DATA_IN", ["--first=RC,DATA_IN"]),
    ("--first=RC --last=GND,5V", ["--first=RC", "--last=GND,5V"]),
]

# ★★ 第二族（**路由器参数** ✓）：次序这族已经在两个摆位上到底 ✗ ⇒ 换旋钮 ✓。
#   ★ 这些是**布线器的工作参数** ✓（栅格细度 / 过孔贵贱 / 换层罚 / 最小脚距 ✓），
#     **不改硬规矩** ✓（禁落区 / 铜距 / 安装孔那些一律照旧 ✓）。
SWEEP_PARAM = [
    ("（原样）", []),
    ("--cell=0.10", ["--cell=0.10"]),
    ("--cell=0.125", ["--cell=0.125"]),
    ("--via=4", ["--via=4"]),
    ("--via=16", ["--via=16"]),
    ("--escape-cost=0.6", ["--escape-cost=0.6"]),
    ("--escape-cost=0.15", ["--escape-cost=0.15"]),
    ("--layer-pen=0.2", ["--layer-pen=0.2"]),
    ("--layer-pen=0.5", ["--layer-pen=0.5"]),
    ("--pitch=0.50", ["--pitch=0.50"]),
    ("--pitch=0.30", ["--pitch=0.30"]),
]

# ★★ 第三族（**更细的旋钮** ✓，2026-10-06 ✓）：六族摆位/次序/参数都到顶之后 ✓，
#   这一族的**特点是不动布局** ✗ —— 只把搜索分辨率（栅格 ✓）与偏好（影子半径 ✓、
#   过孔贵贱 ✓、脚距阈值 ✓、层罚 ✓）再拧细一档 ✓。
SWEEP_PARAM_FINE = [
    ("（原样）", []),
    ("--cell=0.075", ["--cell=0.075"]),
    ("--escape-r=0.3", ["--escape-r=0.3"]),
    ("--escape-r=0.6", ["--escape-r=0.6"]),
    ("--escape-r=1.2", ["--escape-r=1.2"]),
    ("--via=2", ["--via=2"]),
    ("--via=6", ["--via=6"]),
    ("--pitch=0.40", ["--pitch=0.40"]),
    ("--layer-pen=0.1", ["--layer-pen=0.1"]),
    ("--escape-cost=0.45", ["--escape-cost=0.45"]),
    ("--escape-cost=0.45 --escape-r=0.6", ["--escape-cost=0.45", "--escape-r=0.6"]),
]


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    fzz = argv[0]
    log = open(os.path.join(WORK, "_measure_log.txt"), "w", encoding="utf-8")

    def say(s):
        print(s)
        log.write(s + "\n")
        log.flush()

    if "--sweep-param-fine" in argv:
        todo = SWEEP_PARAM_FINE
    elif "--sweep-param" in argv:
        todo = SWEEP_PARAM
    elif "--sweep" in argv:
        todo = SWEEP
    else:
        todo = [("（原样）", [])]
    say("== 量 %s ✓｜开关 = 交付那把 ✓ ==" % os.path.basename(fzz))
    say("   %-26s %-6s %-6s %-6s %s" % ("开关", "连通", "还差", "线长", "未通"))
    best = None
    for tag, extra in todo:
        r = measure(fzz, extra)
        if r is None:
            say("   %-26s ✗ 量不出来（见 _measure_log.txt 上方的原始输出）" % tag)
            continue
        ok, nets, miss, ln, vias, bad = r
        say("   %-26s %d/%d   %-6d %-6.1f %s" % (tag, ok, nets, miss, ln, bad))
        if best is None or (miss, -ok, ln) < best[0]:
            best = ((miss, -ok, ln), tag, extra, r)
    if best:
        say("   ⇒ 最好 ✓：%s ⇒ 还差 **%d** 条 ✓（连通 %d/%d ✓｜线长 %.1f ✓｜过孔 %d ✓）"
            % (best[1], best[3][2], best[3][0], best[3][1], best[3][3], best[3][4]))
    log.close()
    return 0


if __name__ == "__main__":
    # ★ 收工**响一声** ✓（2026-10-06 用户要的 ✓）：成功上行三声 ✓ / 失败下行两声 ✓
    try:
        _rc = main(sys.argv[1:])
    except BaseException:
        done(ok=False)
        raise
    done(ok=(_rc == 0))
    sys.exit(_rc)
