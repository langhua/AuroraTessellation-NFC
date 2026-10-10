# -*- coding: utf-8 -*-
r"""把 `.fzz` 里**内层 `.fz` 的名字**改成与外层文件同名 ✓（只改名字 ✗，内容一字不动 ✓）

★ 为什么要有它 ✗（2026-10-11 ✓）：Fritzing 的草图名显示的是包里那个 `.fz` 的名字 ✓ ——
  生成器一般按**输出文件名**取名 ✓（`pixel-pcb-v86.fzz` ⇒ 内层 `pixel-pcb-v86.fz` ✓），
  但若先写到草稿名（`_work\_k2.fzz` ✗）再拷成正式名 ✗，**草稿名就跟着进包了** ✗
  ⇒ 用户在 Fritzing 里看到的是 `_g0` ✗ / `_k2` ✗ 这种名字 ✗。
  （已发生 ✓：`pixel-pcb-v85.fzz` 里是 `_g0.fz` ✗。）

口径 ✓：
  · 期望的内层名 = **外层文件名把 `.fzz` 换成 `.fz`** ✓；
  · 只改这一条的**名字** ✓；其**内容**必须与原来**逐字节相同** ✗（不同就**不写** ✗）；
  · 其它条目（各视图 svg ✓、各 `.fzp` ✓）**原样搬运** ✓（保时间戳 ✓）；
  · 改完**回读自检** ✓：条目数不变 ✓、内层名对 ✓、`.fz` 内容 = 原内容 ✓。

用法：py -3.13 retitle_fzz.py <a.fzz> [<b.fzz> ...]
退出码：0 = 都对 ✓；1 = 有错 ✗（出错的文件**没被改** ✓）。
"""
import os
import shutil
import sys
import zipfile


def retitle(path):
    want = os.path.basename(path).replace(".fzz", ".fz")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        inners = [n for n in names if n.endswith(".fz")]
        if len(inners) != 1:
            return False, "✗ 包里有 %d 个 `.fz` ⇒ 不敢动 ✗" % len(inners)
        old = inners[0]
        if old == want:
            return False, "· 内层名已经是 `%s` ✓（不用改 ✓）" % old
        text = z.read(old)
        items = [(z.getinfo(n), z.read(n)) for n in names]
    tmp = path + ".retitle"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == old:
                zi = zipfile.ZipInfo(want, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zo.writestr(zi, data)
            else:
                zo.writestr(info, data)
    # 回读自检 ✓（改前/改后只差一个名字 ✓、内容逐字节相同 ✓）
    with zipfile.ZipFile(tmp) as z:
        names2 = z.namelist()
        if sorted(names2) != sorted([want if n == old else n for n in names]):
            os.remove(tmp)
            return False, "✗ 条目清单对不上 ⇒ 不写 ✗"
        if z.read(want) != text:
            os.remove(tmp)
            return False, "✗ `.fz` 内容变了 ⇒ 不写 ✗"
        if len(z.infolist()) != len(items):
            os.remove(tmp)
            return False, "✗ 条目数变了 ⇒ 不写 ✗"
    shutil.move(tmp, path)
    return True, "✓ 内层 `%s` ⇒ `%s` ✓（其余 %d 条原样 ✓、`.fz` 内容逐字节相同 ✓）" % (
        old, want, len(items) - 1)


def main(argv):
    rc = 0
    for p in argv:
        hit, why = retitle(p)
        print("   %-34s %s" % (os.path.basename(p), why))
        rc |= 1 if why.startswith("✗") else 0
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
