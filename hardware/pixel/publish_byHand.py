# -*- coding: utf-8 -*-
r"""把手改稿 `*_byHand.fzz` 发布成交付件 ✓（内容照搬 ✓，只把内部 `.fz` 条目改名 ✓）

用法: py -3.13 -u publish_byHand.py <in_byHand.fzz> <out.fzz>

★ 为什么只改内部 `.fz` 名 ✓：Fritzing 存草图时条目的名字常留在**旧文件名**上
  （`pixel-breadboard43_byHand.fz` 之类 ✓），交付件里要写清是哪一版 ✓；
  其余条目（元件 fzp / 各视图 svg）**原样字节**搬 ✓。
★ 发布后**必须**再跑 `bb_precheck` / `bb_probe` / `render_bb` ✓（不靠"我觉得搬对了"✗）。
"""
import os
import sys
import zipfile


def main(argv):
    src, out = argv[0], argv[1]
    out_fz = os.path.splitext(os.path.basename(out))[0] + ".fz"

    zin = zipfile.ZipFile(src)
    items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    names = list(zin.namelist())                 # ★ 字符串列表 ✓（不是 ZipInfo ✗）
    fz = [n for n in names if n.endswith(".fz") and not n.startswith("svg.")]
    if len(fz) != 1:
        raise SystemExit("内部 `.fz` 条目应当恰好 1 个，实测 %d 个 ✗：%s" % (len(fz), fz))
    old = fz[0]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            fn = out_fz if info.filename == old else info.filename
            zi = zipfile.ZipInfo(fn, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 发布 %s → %s" % (src, out))
    print("   内部 .fz：%s → %s ✓" % (old, out_fz))
    print("   条目 %d 个（其余原样字节 ✓）" % len(items))
    return 0


sys.exit(main(sys.argv[1:]))
