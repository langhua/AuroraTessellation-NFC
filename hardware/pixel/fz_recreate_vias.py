# -*- coding: utf-8 -*-
r"""★ 实验性改动 ✓（用户 2026-10-02 同意"你来改" ✓）：把指定的那颗过孔**当成全新实例**重写 ✓

做的是 ✓：给过孔换一个**新的 `modelIndex`** ✓（几何、走线、`<connect>` 的语义**全不动** ✓）
—— 目的只一个 ✓：让 Fritzing 载入时**从头重建**这颗孔的 connector ✓（= 在 app 里"删掉重放"
的文件级等价物 ✓，用来验证"它那 2 个没布是它自己的账 ✗"）。

不动的东西 ✓（可逐条核 ✓）：
  · 过孔的 `x,y` ✓、`hole size` ✓、`wireFlags` ✓
  · 所有走线的几何 ✓、层 ✓、宽度 ✓、`<connect>` ✓
  · 任何焊盘 ✓、任何别的过孔 ✓
改的只有 ✓：出现该孔旧 `modelIndex` 的地方（= 它自己的实例 ✓ ＋ 邻居走线的 `<connect>` ✓）。

用法 ✓：`recreate_vias.py <in.fzz> <out.fzz> Via1 Via8`
"""
import os
import re
import sys
import zipfile

src, dst = sys.argv[1], sys.argv[2]
want = set(sys.argv[3:]) or {"Via1", "Via8"}

zin = zipfile.ZipFile(src)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

mx = max(int(m) for m in re.findall(r'modelIndex="(\d+)"', text))
mapping = {}
for m in re.finditer(r'(?s)<instance\b[^>]*?moduleIdRef="([^"]+)"[^>]*?modelIndex="(\d+)"[^>]*?>'
                     r'(.*?)(?=<instance\b)', text):
    if not m.group(1).startswith("Via"):
        continue
    ti = re.search(r"<title>([^<]*)</title>", m.group(3))
    if ti and ti.group(1) in want:
        mx += 1
        mapping[m.group(2)] = str(mx)

if not mapping:
    print("✗ 没找到这些孔：%s" % ",".join(sorted(want)))
    sys.exit(1)

out = text
for old, new in mapping.items():
    n = len(re.findall(r'modelIndex="%s"' % old, out))
    out = out.replace('modelIndex="%s"' % old, 'modelIndex="%s"' % new)
    print("   `modelIndex %s → %s` ✓（共替换 %d 处 ✓）" % (old, new, n))

zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
for n in zin.namelist():
    zout.writestr(n, out.encode("utf-8") if n == fz else zin.read(n))
zout.close()
print("✓ 写出 `%s` ✓（只动了 %d 颗孔的 id ✓，几何/走线一字未改 ✓）"
      % (os.path.basename(dst), len(mapping)))
