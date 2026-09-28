# -*- coding: utf-8 -*-
r"""网标签（net label）规则 —— **全仓唯一实现** ✓

★ 规则（用户 2026-09-26 定 ✓；2026-09-29 用户要求落到判定器 ✓）：
  **同名网标签 = 同一张网** ✓ —— 这是**抽象连接** ✓ ⇒ **只适用原理图** ✓
  （面包板 / PCB 要物理连接 ✗ —— 见 `fritzing-parts-langhua/docs/breadboard-routing-rules.md` ✓）。

★ 怎么认（实测取证 ✓，`hardware/pixel/pixel-schematic-v29_netlabel.fzz` ✓）：
  · 网标签是**元件实例** ✓，其 `moduleIdRef` 里带 `NetLabel` ✓
    —— 核心库 = `NetLabelModuleID` ✓；本库 = `NetLabel-Pad` ✓；
  · **实例标题（`<title>`）= 网名** ✓（该草图里 4 个实例标题为 `RC` / `RC` / `GND` / `GND` ✓，
    两个 `RC` 与两个 `GND` 各自互为同一张网 ✓）。

★ 消费方式（两个判定器都调这两行 ✓，别各写一份 ✗）：
    name = sch_net.net_name(module_id_ref, instance_title)      # 不是网标签 ⇒ None ✓
    # 然后：把**同名**的所有标签脚 union 到一起 ✓
"""
import re

_MOD = re.compile(r'moduleIdRef\s*=\s*"([^"]*)"')
_TTL = re.compile(r"<title>(.*?)</title>", re.S)
_MI = re.compile(r'modelIndex\s*=\s*"([^"]*)"')


def is_label_module(module_id):
    """这个 `moduleIdRef` 是不是**网标签**元件 ✓"""
    _m = (module_id or "").lower()
    return "netlabel" in _m or "net label" in _m


def net_name(module_id, title):
    """网标签 ⇒ **网名**（= 实例标题 ✓）；不是网标签 ⇒ `None` ✓"""
    if not is_label_module(module_id):
        return None
    _t = (title or "").strip()
    return _t or None


def label_pins(text):
    """从**草图 XML 文本**里取 `{网名: [(modelIndex, 实例标题, 脚 id), …]}` ✓（只含网标签实例 ✓）

    ★ 给“手上只有文本”的消费者用 ✓；已经有实例模型的（如 `check_netlist.py` ✓）
      直接调 `net_name()` 即可 ✓ —— **判据仍是这一份** ✓。
    ★ 要带 **modelIndex** 回来 ✓：**同名标签是两个不同实例** ✓ ⇒ 只靠标题去重会把它们并成一个 ✗
      （实测 2026-09-29 ✓：两个 `GND` / 两个 `RC` 各只剩 1 个 ⇒ 第二个标签的脚**并不进网** ✗）。
    """
    out = {}
    for blk in re.findall(r"<instance[^>]*>.*?</instance>", text, re.S):
        m = _MOD.search(blk)
        t = _TTL.search(blk)
        if not m or not t:
            continue
        _n = net_name(m.group(1), t.group(1))
        if not _n:
            continue
        # ★ 草图里写的是 **`connectorId="connector0"`** ✓（实测 2026-09-29 ✓：
        #   `pixel-schematic-v29_netlabel.fzz` 的标签块 = `<connector connectorId="connector0" …>` ✓
        #   —— **没有** 独立的 `id` 属性 ✗；我第一版按 `\bid=` 抓 ⇒ 一个也抓不到 ✗）。
        #   ★ 同一个标签**每个视图各有一份 `<connectors>`** ✓（breadboard/pcb/schematic ✓，
        #   id 都是 `connector0` ✓）⇒ **只对本实例去重** ✓（按网名去重会把第二个实例吃掉 ✗）。
        _t = t.group(1).strip()
        _mi = _MI.search(blk)
        _seen = set()
        for _cid in re.findall(r"<connector\b[^>]*\bconnectorId\s*=\s*\"([^\"]*)\"", blk):
            if _cid in _seen:
                continue
            _seen.add(_cid)
            out.setdefault(_n, []).append((_mi.group(1) if _mi else "?", _t, _cid))
    return out
