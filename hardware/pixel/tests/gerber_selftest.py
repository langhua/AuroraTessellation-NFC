# -*- coding: utf-8 -*-
r"""**本板 Gerber 的可送板性**自测 ✓（2026-10-10 立 ✓；用户当轮要求 ✓）

★ 它测什么 ✓：拿**库仓那把尺子**（`tools/gerber_check.py` ✓ 通用件只有一份 ✓）量
  `hardware/pixel/gerber/` 里**用户刚导出的这一批** ✓，并把**已知状态钉死**：
  · 层齐全 ✓ / 单位格式原点 ✓ / 板框闭合 ＋ 尺寸对得上 ✓ / 钻孔逐孔对得上 ✓ /
    焊盘 ＋ 45° 旋转盘对得上 ✓ / 铜层**逐格覆盖**对得上 ✓ —— 这些都必须是 ✓；
  · **唯一的硬伤** = 铜层多出来的 0.12 mm 细线（**丝印漏到铜层** ✗）与 J2 的 24 mil 线
    只隔 **0.0906 mm**（3.57 mil ✗ < 5 mil）⇒ 结论 = **不可送板** ✗（`exit 1` ✓）。
  ★ 根因不在 `.fzz` 也不在导出器 ✗ —— 是**库里那件** `SH-1.0-3P-V` 的 pcb svg 把
    `<g id="silkscreen">` **嵌在** `<g id="copper1">` 里面 ✗ ⇒ Fritzing 按"在铜组里"当**铜**导出 ✓。
  ★ 修法（本轮**只报告、不执行** ✗，见用户硬约束 ✓）：把那 7 条丝印线**移出**铜组（与
    `WS2812B_1010_1_pcb.svg` 一样放在 `<svg>` 根下 ✓）⇒ 重新导出。
  ⇒ **件修好之后**：本测试的期望要改成 `rc == 0` ＋ 那句"可送板" ✓（解析见 `EXPECT` ✓）。

★ 反例（人为破坏 ✓）：把导出目录**复制一份**再动刀 ✗（`_work/` 下的临时副本 ✓，
  跑完即删 ✓，**绝不碰用户的 `gerber/`** ✓）：
  · 删掉 `_maskTop.gts` ⇒ **缺层** ⇒ `exit 2` ✓（拒判 ✓）；
  · 把板框那条闭合边**挪走** ⇒ **不闭合** ⇒ `exit 1` ✓；
  · 把某把刀**改粗**（0.3 → 0.6）⇒ 过孔对不上 ⇒ `exit 1` ✓。
"""
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # hardware/pixel/tests
PIX = os.path.dirname(HERE)                                 # hardware/pixel
sys.path.insert(0, PIX)
import toolpaths                                            # noqa: E402  （把库仓 tools 放进 path ✓）

TOOL = os.path.join(toolpaths.TOOLS, "gerber_check.py")
GERBER = os.path.join(PIX, "gerber")
FZZ = os.path.join(PIX, "pixel-pcb-v83.fzz")
WORK = os.path.join(PIX, "_work", "gerber-v83", "selftest")

# ★ 期望（**钉死已知状态** ✓；件修好后把 `RC` 改成 0、把 `MUST_FAIL` 清空 ✓）
RC = 1
MUST_OK = ("必需层齐全", "对模型板框", "过孔：模型 5 个", "安装孔", "G36 区域里对上", "都 ≥ 0",
           "模型有、Gerber 没有", "板框")
MUST_FAIL = ("低于 5 mil", "丝印漏到铜层")
MUST_SEE = ("0.0906", "0.1200 mm")          # 那道缝的数值 ＋ 那根细线的光圈 ✓


def run(folder, *args):
    p = subprocess.run([sys.executable, "-X", "utf8", TOOL, folder] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout.decode("utf-8", "replace")


def bad_cases(bad):
    """反例目录 ✓（复制 ＋ 动刀 ✓）⇒ [(名字, 目录, 期望退出码, 期望出现的字 ✓)]"""
    out = []
    shutil.rmtree(bad, ignore_errors=True)
    os.makedirs(bad)

    def _copy(tag):
        d = os.path.join(bad, tag)
        shutil.copytree(GERBER, d)
        for fn in os.listdir(d):
            if fn.lower().endswith(".png"):
                os.remove(os.path.join(d, fn))
        return d

    d1 = _copy("no-mask")
    os.remove(os.path.join(d1, "pixel-pcb-v83_maskTop.gts"))
    out.append(("删掉顶层阻焊 ⇒ 缺层", d1, 2, "缺层"))

    d2 = _copy("open-outline")
    f = os.path.join(d2, "pixel-pcb-v83_contour.gm1")
    # ★ **整份重写** ✓（别靠 `str.replace` ✗ —— 实测没换掉 ⇒ 反例"没生效"比"没测"更坏 ✗）：
    #   只写 3 条边 ⇒ 路径末端 (4,4) ≠ 起点 (4,980) ⇒ 不闭合 ✓
    io.open(f, "w", encoding="utf-8", newline="\n").write(
        "G04 MADE WITH FRITZING*\n%ASAXBY*%\n%FSLAX23Y23*%\n%MOIN*%\n%OFA0B0*%\n%SFA1.0B1.0*%\n"
        "%ADD10C,0.008000*%\n%LNCONTOUR*%\nG90*\nG70*\nG54D10*\n"
        "X4Y980D02*\nX980Y980D01*\nX980Y4D01*\nX4Y4D01*\nD02*\nG04 End of contour*\nM02*\n")
    out.append(("板框被扯开 ⇒ 不闭合", d2, 1, "不闭合"))

    d3 = _copy("fat-drill")
    f = os.path.join(d3, "pixel-pcb-v83_drill.txt")
    t = io.open(f, encoding="utf-8").read().replace("T100C0.011811", "T100C0.023622")
    io.open(f, "w", encoding="utf-8", newline="\n").write(t)
    out.append(("过孔刀改粗一倍 ⇒ 与模型对不上", d3, 1, "过孔"))
    return out


def main():
    if not os.path.isdir(GERBER):
        print("✗ 没有 `%s` ⇒ 跳过（不是失败 ✓）" % GERBER)
        return 0
    if not os.path.isfile(FZZ):
        print("✗ 没有 `%s` ⇒ 跳过 ✓" % FZZ)
        return 0
    bad = []
    rc, out = run(GERBER, "--fzz", FZZ)
    print("── 正例（**用户这一批** ✓）：exit %d（期望 %d）" % (rc, RC))
    for s in MUST_OK:
        if s not in out:
            bad.append("正例缺了「%s」" % s)
            print("   ✗ 报告里**没找到**：%s" % s)
    for s in MUST_FAIL:
        if s not in out:
            bad.append("正例缺了「%s」" % s)
            print("   ✗ 报告里**没找到**：%s" % s)
    for s in MUST_SEE:
        if s not in out:
            bad.append("正例缺了数值「%s」" % s)
            print("   ✗ 报告里**没找到数值**：%s" % s)
    if rc != RC:
        bad.append("正例退出码 %d ≠ %d" % (rc, RC))
    print("   %s（🞂 摘录：%s）"
          % ("✓" if not bad else "✗",
             "；".join(l.strip()[:70] for l in out.splitlines()
                      if ("低于 5 mil" in l or "丝印漏到铜层" in l or "缺的地方" in l))[:200]))

    for name, d, want_rc, want_txt in bad_cases(WORK):
        r2, o2 = run(d, "--fzz", FZZ)
        ok = (r2 == want_rc) and (want_txt in o2)
        print("── 反例：%s ⇒ exit %d（期望 %d）%s" % (name, r2, want_rc, "✓" if ok else "✗"))
        if not ok:
            bad.append(name)
            for ln in o2.splitlines():
                if "✗" in ln:
                    print("   | " + ln.strip()[:150])
    shutil.rmtree(WORK, ignore_errors=True)
    print("\n⇒ %s" % ("✓ 全过" if not bad else "✗ **不过**：%s" % "；".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
