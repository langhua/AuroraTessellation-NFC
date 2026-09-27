# -*- coding: utf-8 -*-
r"""位号文字的**宽度表**（唯一实现 ✓）—— 由 `_scratch/adv_measure.py` **实测**得到 ✓

为什么必须量 ✗：要判"位号文字有没有压到导线/别的元件" ✓ 就得有**文字包围盒** ✓；
  随手写个 0.6em ✗ ⇒ 压没压到全凭那个数 ⇒ 结论不可查 ✗（违反"数据要能指出来源" ✓）。

实测结果（2026-09-27 ✓，cairosvg 渲染 + PIL 扫像素 ✓）：
  · **本机没装 DroidSans** ✗ ⇒ cairosvg 退回一个**等宽**字体 ✓
    ⇒ 绝大多数字符的步进**恰好 = 0.5em** ✓（`i` 与 `M` 一样宽 ✓）；
  · 只有 `±` `Ω` 是 **1.0em** ✓。
  ⇒ 表就两条 ✓（等宽是**推断出来的** ✓，实测每个字符都对得上 ✓ —— 见 `adv_measure.py` 的输出 ✓）。
  ★ 换机器、或装了 DroidSans ⇒ **必须重跑 `_scratch/adv_measure.py` 并更新本文件** ✓
    （否则\"压没压到\"的判据就不成立 ✓）。

★ 包围盒口径 ✓：宽 = **步进之和** ✓（比墨迹略宽 ✓ —— 末字右侧边距不算 ✗）
  ⇒ 判"压到"**偏保守** ✓（宁可多报 ✓）。
"""
ADV_DEFAULT = 2.4977          # 0.5em @ 字号 5 ✓（实测 2.4977 ✓）
ADV_SPECIAL = {"\u00b1": 4.9953, "\u03a9": 4.9953}      # ± Ω = 1.0em ✓


def twidth(text, fs=5.0):
    """字符串宽度（sketch 单位 ✓）"""
    return sum(ADV_SPECIAL.get(c, ADV_DEFAULT) for c in (text or "")) * fs / 5.0


def label_bbox(x, y, fs, lines):
    r"""位号文字块的包围盒 ✓（sketch 单位 ✓）

    基线约定（与 Fritzing 一致 ✓，已机验 ✓）：第 i 行的**基线** = 锚点 y + fs×(i+1) ✓
    ⇒ 包围盒 y 从 `y + fs×1 − 0.75fs`（上缘 ✓ = 第 1 行基线往上一个字高 ✓）
      到 `y + fs×(n+1) + 0.2fs`（下缘 ✓ = 末行基线往下一点点 ✓）。
    """
    n = max(1, len(lines))
    w = max((twidth(s, fs) for s in lines), default=0.0)
    return (x, y + fs * 1 - fs * 0.75, x + w, y + fs * (n + 1) + fs * 0.2)
