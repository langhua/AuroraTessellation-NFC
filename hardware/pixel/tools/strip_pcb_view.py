# -*- coding: utf-8 -*-
r"""★ 只剥**导线**的 `<pcbView>` ✓ —— 留下面包板/原理图（= 网的**成员结构** ✓）

✗✗ 为什么必须这么剥 ✗（2026-10-06 量实 ✓，第三十一 / 三十二轮）：
  老底图 `v69_bare.fzz` 是**整条删**导线实例换来的 ✗ ⇒ 面包板与原理图的走线**一起没了** ✗
  ⇒ 它们留下的声明**全成悬空** ✗ ⇒ Fritzing **认不出 `RC` 是一张网** ✗
  ⇒ 状态栏说「**布线完成**」✗✗（用户开 v71 / v72 两次都撞到 ✓）。
  实测（`_work/_cmp_nets.py` ✓）：底图里 `R1.connector1` 的面包板 3 / 原理图 4 / PCB 2 条声明
  **全部悬空** ✗；而 **v69**（用户看到 **7/9** ✓）是**同样条数、一条不悬空** ✓ —— 差别就在这里 ✓。

★ 口径（照库里 `tools/sch_strip_wires.py` 的老规矩 ✓）：
  · **只删走线实例的 `<pcbView>` 段** ✓ —— 实例本身、它的面包板/原理图视图**原样留着** ✓；
  · **只认走线** ✓（`moduleIdRef="WireModuleID"` ✓）—— ✗ 元件的 `<pcbView>` 里是焊盘 ✗，绝不能碰 ✗；
  · 走线在**别处**留下的声明**一律不动** ✗（实例还在 ✓ ⇒ 它们**不再悬空** ✓，且与 Fritzing 自己
    "实例在、pcbView 里没这个 connector"的**合法**那一类同形 ✓）。

用法 ✓：py -3.13 tools\strip_pcb_view.py <源.fzz> <出.fzz>
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
WIRE_ID = 'moduleIdRef="WireModuleID"'
VIA_RE = re.compile(r"<title>Via\d*</title>")      # ★ 过孔 ✓（Fritzing 自己命名 `Via3`… ✓）


def _is_pcb_item(blk):
    """★ 该剥 `<pcbView>` 的东西 = **走线** ✓ 或 **过孔** ✓

    ✗ 实测教训（2026-10-06 ✓）：第一版**只剥走线** ✗ ⇒ v69 留下的 **11 颗过孔**还在 ✗
      ⇒ 新布的线与它们**撞成一团** ✗（③ 孤立过孔 5 颗 ✓、⑪ 孔距 0.038 mm ✗、⑤ 五张网短接 ✗
      —— 整个文件报废 ✓）。⇒ 过孔**同样**只带 PCB 视图 ✓，一并剥 ✓。
    """
    return (WIRE_ID in blk) or bool(VIA_RE.search(blk))


def strip(text):
    """⇒ `(新文本, 剥了几个走线的 pcbView)` ✓"""
    out, pos, n = [], 0, 0
    for m in re.finditer(r"(?ms)^([ \t]*)<instance\b.*?^[ \t]*</instance>\n?", text):
        blk = m.group(0)
        if not _is_pcb_item(blk):
            continue                                  # ✗ 不是走线/过孔 ⇒ 一个字不碰 ✗
        v0 = blk.find("<pcbView")
        if v0 < 0:
            continue
        v1 = blk.find("</pcbView>", v0)
        if v1 < 0:
            continue
        v1 += len("</pcbView>")
        # ★ 连同它前面那行的缩进/换行一起收掉 ✓（别留空行 ✗）
        s = blk.rfind("\n", 0, v0) + 1
        e = v1 + (1 if blk[v1:v1 + 1] == "\n" else 0)
        new = blk[:s] + blk[e:]
        out.append(text[pos:m.start()] + new)
        pos = m.end()
        n += 1
    if not out:
        return text, 0
    out.append(text[pos:])
    return "".join(out), n


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(name).decode("utf-8")
    n_wire = len([1 for m in re.finditer(r"(?ms)^[ \t]*<instance\b.*?^[ \t]*</instance>\n?", text)
                  if WIRE_ID in m.group(0)])
    n_via = len([1 for m in re.finditer(r"(?ms)^[ \t]*<instance\b.*?^[ \t]*</instance>\n?", text)
                 if VIA_RE.search(m.group(0))])
    new, n = strip(text)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as w:
        for it in z.infolist():
            w.writestr(it, new.encode("utf-8") if it.filename == name else z.read(it.filename))
    print("✓ %s ⇒ %s：走线 %d 条 ✓、过孔 %d 颗 ✓、剥掉 pcbView **%d** 个 ✓"
          "（面包板/原理图原样 ✓）"
          % (os.path.basename(src), os.path.basename(dst), n_wire, n_via, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
