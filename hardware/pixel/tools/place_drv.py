# -*- coding: utf-8 -*-
r"""★ 挪位搜索（**用驱动器本人当尺子** ✓）—— 仓规 §13「只允许一个声音」✓

✗ 与 `place_greedy.py` 的区别 ✗（2026-10-06 ✓）：那个**自己抄了一份路由口径** ✗
  （虽然实测与交付那把开关**逐字相同** ✓，但那是"碰巧一致" ✗，不是保证 ✗）
⇒ 这个每一步都调 `measure.py` ✓ ⇒ 调驱动器 `--measure-only` ✓ ⇒ **一份实现** ✓。

★ 判据 = 交付同一把尺子 ✓：`(还差几条连接, 连通网数, 线长)` ✓（差 0 ⟺ 全通 ✓）。
★ 结构闸门 ✓：每一步先过 `pcb_check` 的 ①–④·⑥⑧ ✓（压件/出板/过孔 ✓，**不跑** ⑤⑫ ✗）。
★ 用法：
    py -3.13 tools\place_drv.py --start=<起点.fzz> --parts=U1,R1,C1,D3 --rounds=2
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
WORK = os.path.join(PIX, "_work")     # ★ 候选/日志/底图仍写草稿区 ✓（保持工具目录干净 ✓）
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from place_greedy import legal, flip_zip, write_zip       # noqa: E402
from measure import measure                                # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 为 import toolpaths ✓
import toolpaths                                 # ★ 库仓 tools 进 sys.path ✓
from beep import done                            # ★ beep 已搬进库仓 ✓（2026-10-07 ✓）
from mutate import rot_zip, joint_zip                      # noqa: E402

# ★ 只挪**电子件** ✓（`H1/H2` 安装孔、`L1` 传感线圈、`J1/J2` 对插件 = 机械/功能意义 ⇒ 不动 ✗）
# ★★ 偏移单位 = **mm** ✓（`nudge()` 里 `du = dx_mm / SK` ✓，1 草图单位 = 0.28222 mm ✓）
#   ⇒ 之前跑的 ±1/±2 = **1/2 mm** ✓ —— 那是**粗格** ✗ ⇒ 亚毫米这一层**从没碰过** ✗
#     （栅格 0.15 mm ⇒ 挪 0.25 mm ≈ 1.7 格 ✓，是真能改走线的量 ✓）。
OFF_AX = [(1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)]
OFF_DIA = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
OFF_FINE = [(0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25),
            (0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5)]


def _tag(title, dx, dy):
    """候选名 ✓（整数不带小数 ✓、亚毫米带三位 ✓，便于看表时一眼分清两族 ✓）。"""
    def f(v):
        return "%+d" % v if float(v).is_integer() else "%+.3f" % v
    return "%s %s %s" % (title, f(dx), f(dy))


def key(r):
    ok, _nets, miss, ln, _vias, _bad = r
    return (miss, -ok, ln)


def fmt(r):
    ok, nets, miss, ln, vias, bad = r
    return ("还差 **%2d** 条 ✓｜连通 %d/%d ✓｜线长 %5.1f ✓｜过孔 %2d ✓｜未通 %s"
            % (miss, ok, nets, ln, vias, bad))


def build_cands(parts, offs, want_flip, rot_parts, rot_step,
                joint_parts, joint_offs):
    """★ 候选集 = **平移** ✓ ＋ **翻面** ✓ ＋ **旋转** ✓ ＋ **双件联挪** ✓

    ★ 旋转（用户 2026-10-06 定 ✓）：步长 **15°** ✓（「90° 太粗了」✗）⇒
      `15, 30, …, 345` ✓，绕**该件自己焊盘的重心** ✓（见 `mutate.py` ✓）。
    ★ 双件联挪（同一轮新加 ✓）：一对件 **同向** ✓ 与 **反向**（一把向外、一把向内 ✓）
      两种都试 ✓ —— 反向那种是“给中间腾地方”的典型手法 ✓。
    """
    out = []
    for title in parts:
        out += [(_tag(title, dx, dy),
                 (lambda s, d, ti=title, a=dx, b=dy: write_zip(s, d, ti, a, b)))
                for (dx, dy) in offs]
        if want_flip:
            out.append(("%s 翻面" % title,
                        (lambda s, d, ti=title: flip_zip(s, d, ti))))
    for title in rot_parts:
        for deg in range(rot_step, 360, rot_step):
            out.append(("%s 转%d" % (title, deg),
                        (lambda s, d, ti=title, g=deg: rot_zip(s, d, ti, g))))
    for i in range(len(joint_parts)):
        for j in range(i + 1, len(joint_parts)):
            a, b = joint_parts[i], joint_parts[j]
            for (dx, dy) in joint_offs:
                for sgn, nm in ((1, "同向"), (-1, "反向")):
                    mv = [(a, dx, dy), (b, sgn * dx, sgn * dy)]
                    out.append(("%s+%s %s %s" % (a, b, _tag("", dx, dy).strip(), nm),
                                (lambda s, d, m=mv: joint_zip(s, d, m))))
    return out


def main(argv):
    start = next((a.split("=", 1)[1] for a in argv if a.startswith("--start=")), None)
    start = start or os.path.join(WORK, "v69_bare.fzz")
    parts = [s for a in argv if a.startswith("--parts=")
             for s in a.split("=", 1)[1].split(",") if s]
    rounds = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--rounds=")), "2"))
    dia = "--diag" in argv
    if "--only-fine" in argv:
        offs = OFF_FINE
    elif "--fine" in argv:
        offs = OFF_AX + OFF_FINE + (OFF_DIA if dia else [])
    else:
        offs = OFF_AX + (OFF_DIA if dia else [])
    # ★ 旋转（步长 15° ✓）—— `--rot` 开、`--rot-only` 只要旋转 ✓
    rot_step = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--rot-step=")),
                        "15"))
    only_rot = "--rot-only" in argv
    only_joint = "--joint-only" in argv
    rot_parts = [s for a in argv if a.startswith("--rot-parts=")
                 for s in a.split("=", 1)[1].split(",") if s]
    if ("--rot" in argv or only_rot) and not rot_parts:
        rot_parts = parts
    if only_rot or only_joint:
        offs = []
    # ★ 双件联挪 ✓（一对件 × 4 个单格轴偏移 × 同向/反向 ✓）
    joint_parts = [s for a in argv if a.startswith("--joint-parts=")
                   for s in a.split("=", 1)[1].split(",") if s]
    if "--joint" in argv or only_joint:
        if not joint_parts:
            joint_parts = parts
    else:
        joint_parts = []
    joint_offs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    all_c = build_cands(parts, offs, not (only_rot or only_joint), rot_parts,
                        rot_step, joint_parts, joint_offs)

    log = open(os.path.join(WORK, "_pd_log.txt"), "w", encoding="utf-8")

    def say(s):
        print(s)
        log.write(s + "\n")
        log.flush()

    say("== 挪位搜索 ✓｜尺子 = 驱动器本人 ✓｜起点 %s ==" % os.path.basename(start))
    say("   平移可挪 %s ✓（偏移 %d 个 ✓）｜旋转 %s ✓（步长 %d° ✓）｜联挪 %s ✓｜%d 轮 ✓｜候选 %d 个/轮"
        % (",".join(parts) or "无", len(offs), ",".join(rot_parts) or "无", rot_step,
           ",".join(joint_parts) or "无", rounds, len(all_c)))
    cur = start
    r_cur = measure(cur)
    if r_cur is None:
        say("   ✗ 起点量不出来 ⇒ 停 ✗")
        return 2
    say("   起点  %s" % fmt(r_cur))
    for rnd in range(1, rounds + 1):
        if r_cur[2] == 0:
            say("   ✓ 已经全通 ⇒ 停 ✓")
            break
        say("   ── 第 %d 轮 ──" % rnd)
        best = None
        if True:
            for tag, maker in all_c:
                dst = os.path.join(WORK, "_pd_r%d_%s.fzz"
                                   % (rnd, tag.replace(" ", "_").replace("+", "p")
                                      .replace("-", "m").replace(".", "_")))
                try:
                    maker(cur, dst)
                except SystemExit as exc:
                    say("      %-16s ✗ 做不出来（%s）" % (tag, exc))
                    continue
                ill = legal(dst)
                if ill:
                    say("      %-16s ✗ 结构非法：%s" % (tag, ill))
                    continue
                r = measure(dst)
                if r is None:
                    say("      %-16s ✗ 量不出来" % tag)
                    continue
                mark = ""
                # ★★ 2026-10-06 修 bug ✗：原来是 `if best is None or key(r) < key(best[3])`
                #   ⇒ `best` 一开始是 `None` ⇒ **第一个候选无条件当"最好"** ✗
                #   ⇒ 一整轮**全都更差**时，它照样"采纳"第一个 ✗✗
                #   （实测：转 `C1` 那一轮"采纳"了 `转180 ⇒ 差 2`，比原样 `差 1` 还差 ✗）。
                #   ★ 之前几轮没被坑到，只因**第一个候选恰好打平** ✗ —— 是**运气**，不是对 ✓。
                #   ⇒ 修法：**必须同时**比当前状态（`r_cur`）✓ 与已找到的最好 ✓。
                if key(r) < key(r_cur) and (best is None or key(r) < key(best[3])):
                    best = (tag, dst, cur, r)
                    mark = "   ← **更好** ✓"
                say("      %-16s %s%s" % (tag, fmt(r), mark))
        if best is None:
            say("   ✗ 这一轮没有更好的 ⇒ 停 ✓")
            break
        say("   ⇒ 第 %d 轮采纳 ✓：%s ⇒ %s｜文件 %s"
            % (rnd, best[0], fmt(best[3]), os.path.basename(best[1])))
        cur, r_cur = best[1], best[3]
        if r_cur[2] == 0:
            say("   ✓✓ **全通** ✓ ⇒ 停 ✓")
            break
    say("\n⇒ 收工 ✓：`%s` ⇒ %s" % (os.path.basename(cur), fmt(r_cur)))
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
