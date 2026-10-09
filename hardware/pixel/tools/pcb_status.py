# -*- coding: utf-8 -*-
r"""pcb_status（**项目侧薄入口** ✓）：就是库仓 `tools\pcb_status.py` 的**命令行** ✓（2026-10-10 ✓）

★ 为什么有这么一层 ✗✓：出厂检查第 **⑨** 条（「状态栏可信度」✓，见 `hardware/pixel/README.md`
  §★ 交付前机器检查 ✓）要能在**本项目目录里照清单原样跑** ✓；而引擎（照 Fritzing 源码复刻的
  状态栏仿真 ✓）**只有一份** ✓ —— 在库仓 `f:\git\fritzing-parts-langhua\tools\pcb_status.py` ✓
  （仓规：通用工具只有一份 ✓，见 `toolpaths.py` 头 ✓）⇒ 这里**不抄第二份** ✗，只转发 ✓。

用法 ✓（cwd = `hardware/pixel/` ✓）：
    py -X utf8 tools\pcb_status.py <a.fzz> [<b.fzz> …] [--nets=pixel_nets.py]   rem 逐视图 M/K ＋ 文案
    py -X utf8 tools\pcb_status.py <a.fzz> --sens                                rem 虚拟删线灵敏度
退出码 ✓：`0` = A/B/C 全过 ✓；`1` = 有 ✗；`2` = 没给文件 ✓（细则见库仓那件 ✓）。
项目侧更细的逐网版 = `tools\pcb_rats_probe.py` ✓（**同一个 `Status` 引擎** ✓）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import toolpaths                                                # noqa: E402 ← 已把库仓 tools\ 放进 sys.path ✓
import pcb_status as ST                                         # noqa: E402 ← **唯一实现**在那儿 ✓

# ★ 防"认到别处的一份" ✗（同名件被 `tools/` 目录顶掉是本仓踩过的坑 ✓，见 `toolpaths.py` 头 ✓）
if os.path.abspath(os.path.dirname(ST.__file__)) != os.path.abspath(toolpaths.TOOLS):
    raise SystemExit("✗ `pcb_status` 认到的不是库仓那一份 ✗：%s" % ST.__file__)

if __name__ == "__main__":
    raise SystemExit(ST.main(sys.argv[1:]))
