# -*- coding: utf-8 -*-
r"""删掉**指定的走线实例**（按 `<title>` ✓）＋ 清掉指向它们的悬空 `<connect>` ✓

★ 为什么另写 ✗：`_work/del_inst.py` 对**走线**会拒删声明 ✓（它那句
  「该 mi 还归这些实例共用」把"被删实例自己"也算进去了 ✗）⇒ 留下 **⑫ 悬空声明** ✗
  （Fritzing 会顺着声明当成已连通 ⇒ 显示「布线完成」✗ 而铜不在 ✗）。
★ 这里直接复用 `fz_strip_pcb` 的两把函数 ✓（`blocks_of` / `strip_view` ✓）——
  它本来就是"删走线 + 清回指"的正解 ✓。

用法：py -3.13 _work\drop_wires.py <in.fzz> <out.fzz> Wire90013890 Wire90013970
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

PIX = r"f:\git\AuroraTessellation-NFC\hardware\pixel"
sys.path.insert(0, PIX)
import toolpaths                                                    # noqa: E402,F401
import fz_strip_pcb as SP                                           # noqa: E402


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    want = set(argv[2:])
    z = zipfile.ZipFile(src)
    fz = [n for n in z.namelist() if n.endswith(".fz")][0]
    text = z.read(fz).decode("utf-8")
    blks = SP.blocks_of(text)

    drop, removed = set(), set()
    for ttl, a, b in blks:
        if ttl not in want:
            continue
        blk = text[a:b]
        mi = re.search(r'modelIndex="([^"]+)"', blk)
        if not mi:
            raise SystemExit("✗ %s 里没有 modelIndex ✗" % ttl)
        drop.add(a)
        removed.add(mi.group(1))
        print("   · %s（mi=%s）⇒ 整块删 ✓" % (ttl, mi.group(1)))
    if len(drop) != len(want):
        raise SystemExit("✗ 只认出 %d/%d 个标题 ⇒ 不写 ✗" % (len(drop), len(want)))

    parts, pos, n_conn = [], 0, 0
    for ttl, a, b in blks:
        parts.append(text[pos:a])
        if a in drop:
            pos = b                                     # 整块丢掉 ✓
            continue
        nb, k = SP.strip_block(text[a:b], removed)      # 只清 pcbView 段里的回指 ✓
        n_conn += k
        parts.append(nb)
        pos = b
    parts.append(text[pos:])
    text2 = "".join(parts)
    try:
        ET.fromstring(text2)
    except ET.ParseError as e:                          # ★ 不过 ⇒ 不写 ✗
        raise SystemExit("✗ 改完不是合法 XML（%s）⇒ **不写文件** ✗" % e)
    zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
    for it in z.infolist():
        data = text2.encode("utf-8") if it.filename == fz else z.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    print("   ✓ 写出 %s：删实例 %d 个 ✓｜清悬空 `<connect>` %d 条 ✓｜XML 合法 ✓"
          % (os.path.basename(dst), len(drop), n_conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
