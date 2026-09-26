# -*- coding: utf-8 -*-
"""通用工具的**唯一定位处** ✓（2026-09-27 用户定 ✓）

★ 约定（用户明确纠正过一次 ✗）：**通用工具只有一份，就在元件库仓**
  `f:\\git\\fritzing-parts-langhua\\tools\\` ✓ —— 本项目 `hardware/pixel/` 里
  **不留副本** ✗。

  反面教训（同一个坑我犯过两次 ✗）：
    ① 把 `f:\\git\\_scratch` 插进 import 路径 ✗ ⇒ 草稿区旧副本顶掉当前那份 ✗，
       而且**不报错、不退出** ✗，只让脚位自检静静退化成"未验证" ✗；
    ② 又把库仓的 `part_measure.py` / `pin_ruler.py` / `part_box.py` … 拷了一份进项目 ✗
       ⇒ 又是"两份实现"✗（改一处不生效 ✗、"自证通过" ✗）。

  ⇒ 所以：**只从 `TOOLS` 导入** ✓；`TOOLS` 默认按**相对路径**指向同级仓 ✓
    （不写死机器路径 ✗），环境变量 `FRITZING_TOOLS` 可覆盖 ✓。

用法（项目里的脚本一句话即可 ✓）：
    import toolpaths            # 已在 import 时就把它放进 sys.path 了 ✓
    import part_box as PB       # 来自 TOOLS ✓
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 相对定位：hardware/pixel/ → hardware → <项目> → git → fritzing-parts-langhua/tools ✓
TOOLS = os.environ.get("FRITZING_TOOLS") or os.path.normpath(
    os.path.join(HERE, os.pardir, os.pardir, os.pardir, "fritzing-parts-langhua", "tools"))


def use():
    """把 `TOOLS` 放进 `sys.path` 最前 ✓（幂等 ✓）⇒ 通用工具只认库仓那一份 ✓"""
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    return TOOLS


use()
