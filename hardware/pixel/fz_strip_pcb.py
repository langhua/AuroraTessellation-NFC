# -*- coding: utf-8 -*-
r"""剥掉 **PCB 走线 / 过孔** ✓（重摆位前必做 ✗ —— 元件一挪，旧线全是过期的 ✗）

用法 ✓：
  `fz_strip_pcb.py <in.fzz> <out.fzz> [--dry]`

判据（**按文件本身** ✓，不猜 ✓）：
  · **PCB 走线/过孔** = 实例 `moduleIdRef` 以 `Wire`/`Via` 开头 **且块里有 `<pcbView`** ✓
    ⇒ 连**整个实例块**一起删 ✗。
  · **原理图/面包板的走线不动** ✗ —— 它们只有 `schematicView` / `breadboardView` ✓
    （实测 ✓：`Wire90012727` 只有 `schematicView` ✓）。
  · 残下的 `<connect … modelIndex="被删的号">` 一并清掉 ✓（不然是**悬空引用** ✗）；
    某个 `<connects>` 清空了 ⇒ **连壳一起去掉** ✓（不留空元素 ✗）。
  · ★ 只动 `pcbView` 段里的 `<connect>` ✓ —— 别的视图**一个字节不碰** ✗。
  · 写回前 `ET.fromstring` **必须过** ✓（不过 ⇒ 报错、不写 ✗）。
"""
import io
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

WANT = ("Wire", "Via")


def blocks_of(text):
    """逐实例切块 ✓ —— 按 `<title>` 定位，往前找 `<instance` ✓、往后找 `</instance>` ✓

    ★ 不用"同缩进配对" ✗（本仓踩过 ✓：有实例没按 Fritzing 的缩进闭合 ⇒ 整片错位 ✗）。
    """
    out = []
    for m in re.finditer(r"<title>([^<]*)</title>", text):
        a = text.rfind("<instance", 0, m.start())
        b = text.find("</instance>", m.end())
        if a < 0 or b < 0:
            continue
        # 连它前面那一行的缩进/换行一起算进来 ✓（删掉不留空行 ✗）
        a2 = text.rfind("\n", 0, a)
        out.append((m.group(1), a2 + 1 if a2 >= 0 else a, b + len("</instance>")))
    return out


def strip_view(seg, removed):
    """一个**视图段**：删掉指向 `removed` 的 `<connect>` ✓（返回 `(新串, 删了几条 ✓)`）"""
    n = 0

    def repl(m):
        nonlocal n
        q = re.search(r'modelIndex="([^"]+)"', m.group(0))
        if q and q.group(1) in removed:
            n += 1
            return ""
        return m.group(0)

    seg = re.sub(r"[ \t]*<connect\b[^>]*/>[ \t]*\r?\n?", repl, seg)
    seg = re.sub(r"[ \t]*<connects>\s*</connects>[ \t]*\r?\n?", "", seg)
    return seg, n


def strip_block(blk, removed):
    """只处理块里的 `pcbView` 段 ✓（别的视图原样 ✓）"""
    out, pos, tot = [], 0, 0
    for m in re.finditer(r"<pcbView\b.*?</pcbView>", blk, re.S):
        out.append(blk[pos:m.start()])
        s, k = strip_view(m.group(0), removed)
        out.append(s)
        tot += k
        pos = m.end()
    out.append(blk[pos:])
    return "".join(out), tot


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    dry = "--dry" in argv
    z = zipfile.ZipFile(src)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(fz).decode("utf-8")
    blks = blocks_of(text)
    removable = []
    for ttl, a, b in blks:
        blk = text[a:b]
        mid = re.search(r'moduleIdRef="([^"]+)"', blk)
        mi = re.search(r'modelIndex="([^"]+)"', blk)
        if mid and mi and mid.group(1).startswith(WANT) and "<pcbView" in blk:
            removable.append((a, b, ttl, mi.group(1)))
    removed = {mi for _a, _b, _t, mi in removable}
    print("== 剥 PCB 走线/过孔：%s ⇒ %s ==" % (os.path.basename(src), os.path.basename(dst)))
    print("   实例块 %d 个｜**带 pcbView 的 Wire/Via** %d 个 ⇒ 删 ✓｜连着要清的 `<connect>` 号 %d 个"
          % (len(blks), len(removable), len(removed)))
    if dry:
        for _a, _b, ttl, mi in removable[:6]:
            print("      · %s（mi=%s）" % (ttl, mi))
        return 0
    # ① 先按删除集合重排文本 ✓ ② 再清幸存块里指向它们的 `<connect>` ✓
    drop = {a for a, _b, _t, _m in removable}
    parts, pos, n_conn = [], 0, 0
    for ttl, a, b in blks:
        if a in drop:
            parts.append(text[pos:a])                      # 这段之前的内容 ✓
            pos = b                                        # 整块丢掉 ✓
            continue
        parts.append(text[pos:a])
        nb, k = strip_block(text[a:b], removed)
        n_conn += k
        parts.append(nb)
        pos = b
    parts.append(text[pos:])
    text2 = "".join(parts)
    try:
        ET.fromstring(text2)
    except ET.ParseError as e:                             # ★ 不过 ⇒ 不写 ✗
        raise SystemExit("✗ 改完不是合法 XML（%s）⇒ **不写文件** ✗" % e)
    zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
    for it in z.infolist():
        data = text2.encode("utf-8") if it.filename == fz else z.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    print("   删掉实例 %d 个 ✓｜清掉悬空 `<connect>` %d 条 ✓｜XML 合法 ✓" % (len(removable), n_conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
