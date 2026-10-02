# -*- coding: utf-8 -*-
r"""★ 核实"`<instance` 300 / `</instance>` 299 差 1"到底是什么 ✓

怀疑 ✓：Fritzing 把实例包在 **`<instances>`** 里 ✓，而 `<instances` 自身**含** `<instance`
这个子串 ✓ ⇒ 用 `count("<instance")` 数必然**多 1** ✓ ⇒ **不是缺陷** ✗（用户猜是 Fritzing
的 bug ✓ —— 得先把这一点核准 ✓，不能拿错的结论去报 ✗）。

做法 ✓：把 `<instance`、`<instances`、`</instance>`、`</instances>` **分开数** ✓；
再拿真 XML 解析器过一遍 ✓（能解析 ⇒ 结构合法 ✓）。
用法 ✓：`check_instance_tags.py <sketch.fzz>`
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

path = sys.argv[1]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

print("== %s ==" % os.path.basename(path))
print("   `<instances`（**外层容器** ✓）      : %d" % len(re.findall(r"<instances\b", text)))
print("   `</instances>`                     : %d" % len(re.findall(r"</instances>", text)))
print("   `<instance `（**真实例** ✓，带空格）: %d" % len(re.findall(r"<instance[\s>]", text)))
print("   `</instance>`                      : %d" % len(re.findall(r"</instance>", text)))
print("   —— 若「真实例」== `</instance>` ⇒ **配平是好的** ✓，先前那个「差 1」是")
print("      `count(\"<instance\")` 把 `<instances>` 也数进去了 ✗（我的计数 bug ✗）")

try:
    ET.fromstring(text)
    print("   ✓ 真 XML 解析器**通过** ⇒ 结构合法 ✓（没有没闭合的标签 ✓）")
except ET.ParseError as e:
    print("   ✗ XML 解析失败 ✓：%s ⇒ 确有结构问题 ✗（这条才值得报 ✓）" % e)
