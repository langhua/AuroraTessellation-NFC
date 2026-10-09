# -*- coding: utf-8 -*-
r"""本项目仓（`hardware/pixel`）**一行跑全部**测试 ✓（2026-10-09 用户定 ✓）

★ 约定（仓规 ✓）：
  · **项目自己的测试放 `hardware/pixel/tests/`** ✓；**通用工具的测试在库仓
    `fritzing-parts-langhua/tools/tests/`** ✓（通用工具只有一份 ✓，见 `toolpaths.py` ✓）；
  · 每个测试脚本**自带 `exit 0/1`** ✓、**零第三方依赖** ✓（只用标准库 ✓）；
  · 命名保留 `*_selftest.py` ✓ —— ✗ 故意不叫 `test_*.py` ✗（pytest 会收集它、
    被模块级 `SystemExit` 打崩 ✓）。

用法：`py -X utf8 tests\run_all.py` ⇒ 全过 print `✓ 全过` ＋ exit 0 ✓；任一不过 exit 1 ✓。
★ `--with-lib` ✓：**顺带把库仓那套也跑一遍** ✓（只用 `toolpaths.py` 定位 ✓，不写死路径 ✗）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                             # noqa: E402


def _run(paths):
    bad = []
    for t in paths:
        print("══ %s ══" % os.path.relpath(t, os.path.dirname(HERE)))
        r = subprocess.run([sys.executable, "-X", "utf8", t],
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        print("   [exit %d]\n" % r.returncode)
        if r.returncode != 0:
            bad.append(t)
    return bad


def main():
    mine = sorted(os.path.join(HERE, f) for f in os.listdir(HERE)
                  if f.endswith("_selftest.py") and f != os.path.basename(__file__))
    if not mine:
        print("✗ `%s` 里没有 `*_selftest.py` ✓" % HERE)
        return 1
    bad = _run(mine)
    n = len(mine)
    if "--with-lib" in sys.argv:
        lib_tests = os.path.join(toolpaths.TOOLS, "tests", "run_all.py")
        if os.path.isfile(lib_tests):
            print("══（--with-lib）库仓 `tools/tests/run_all.py` ══")
            r = subprocess.run([sys.executable, "-X", "utf8", lib_tests],
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            print("   [exit %d]\n" % r.returncode)
            n += 1
            if r.returncode != 0:
                bad.append(lib_tests)
        else:
            print("⚠ 找不到库仓 runner `%s` ✗ ⇒ 只跑本仓 ✓" % lib_tests)
    print("⇒ %s（%d 处 ✓）"
          % ("✓ 全过" if not bad else "✗ **不过 %d 处**：%s" % (len(bad), "、".join(bad)), n))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
