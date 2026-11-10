# -*- coding: utf-8 -*-
r"""把草图里**内嵌**的某个元件（.fzp ＋ 各视图 svg）换成**库仓里那一份** ✓

用法: py -3.13 -u refresh_embed_part.py <in.fzz> <out.fzz> <部件目录（相对 svg/）>

**为什么** ✗：Fritzing 的 `.fzz` 包里**内嵌**着一份元件（fzp ＋ svg）；库里改了件，
包里的还是老副本 ✗ ⇒ 打开草图看到的仍是老样子 ✗（`SH-1.0-3P-V` 就踩过这条 ✓）。

★ 只换**同名条目** ✓（`svg.<view>.<文件名>` ⇔ `<部件目录>/svg.<view>.<文件名>`）；
  其余条目**原样字节**拷回 ✓；每个被换的条目都**报一条** ✓（不静默 ✓）。
★ 换完必须再跑：`bb_precheck` / `bb_probe`（几何会跟着变 ✓）。
"""
import os
import sys
import zipfile

LIB_ROOT = r"f:\git\fritzing-parts-langhua\svg"


def main(argv):
    src, out, part = argv[0], argv[1], argv[2]
    only = ""
    for a in argv[3:]:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
    pdir = os.path.join(LIB_ROOT, part)
    if not os.path.isdir(pdir):
        raise SystemExit("找不到部件目录：%s ✗" % pdir)
    new = {}
    for fn in os.listdir(pdir):
        if fn.endswith(".py"):
            continue
        if only and only not in fn:
            continue
        new[fn] = os.path.join(pdir, fn)
    if not new:
        raise SystemExit("库里有 0 个条目匹配 `--only=%s` ✗" % only)

    zin = zipfile.ZipFile(src)
    items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    hit = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            fn = info.filename
            if fn in new:
                with open(new[fn], encoding="utf-8") as f:
                    data = f.read().replace("\r\n", "\n").encode("utf-8")
                hit.append(fn)
            zi = zipfile.ZipInfo(fn, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    if not hit:
        raise SystemExit("这个草图里没有可换的条目 ✗（库里候选：%s）" % ", ".join(sorted(new)))
    print("✓ 换掉内嵌条目 %d 条：" % len(hit))
    for h in hit:
        print("   ·", h)
    print("✓ 写出", out)
    return 0


sys.exit(main(sys.argv[1:]))
