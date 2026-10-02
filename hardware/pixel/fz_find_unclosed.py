# -*- coding: utf-8 -*-
r"""★ 找那一处**没闭合的 `<instance>`** ✓（`<instance` 比 `</instance>` 多 1 个 ✗）
做法 ✓：按 `<title>` 扫块（本仓唯一稳定的切法 ✓），块里出现 **2 个 `<instance`** 的就是它 ✓
用法 ✓：`fz_find_unclosed.py <sketch.fzz>`
"""
import os
import re
import sys
import zipfile

path = sys.argv[1]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")
print("== %s ==" % os.path.basename(path))
print("   `<instance` %d / `</instance>` %d ⇒ 差 **%d** ✓"
      % (text.count("<instance"), text.count("</instance>"),
         text.count("<instance") - text.count("</instance>")))
hits = 0
for m in re.finditer(r"<title>([^<]*)</title>", text):
    i = m.start()
    s, e = text.rfind("<instance", 0, i), text.find("</instance>", i)
    if s < 0 or e < 0:
        continue
    b = text[s:e + 11]
    if b.count("<instance") != 1:
        hits += 1
        mi = re.search(r'modelIndex="(\d+)"', b)
        mo = re.search(r'moduleIdRef="([^"]+)"', b)
        print("   ✗ `%s`（index=%s ✓ %s）的块里 `<instance` **%d 个** ✗"
              % (m.group(1), mi.group(1) if mi else "?", mo.group(1) if mo else "?",
                 b.count("<instance")))
        # 把这一段的前后文也印出来 ✓（好判断缺的是哪个 `</instance>` ✓）
        print("      块首：%s" % b[:160].replace("\n", " "))
        print("      块尾：%s" % b[-200:].replace("\n", " "))
print("   ⇒ 命中 **%d** 处 ✓" % hits)

# ★ 另一种签名 ✓：某个 `<instance` 之后、下一个 `<instance` 之前**没有** `</instance>` ✗
#   ⇒ 就是它**没闭合** ✓（可能是文件里最后一个实例 ✓，也可能夹在别处 ✓）
starts = [m.start() for m in re.finditer(r"<instance\b", text)]
ends = [m.start() for m in re.finditer(r"</instance>", text)]
for k, s in enumerate(starts):
    nxt_s = starts[k + 1] if k + 1 < len(starts) else len(text)
    inner = [e for e in ends if s < e < nxt_s]
    if not inner:
        ti = re.search(r"<title>([^<]*)</title>", text[s:s + 1200])
        mo = re.search(r'moduleIdRef="([^"]+)"', text[s:s + 400])
        mi = re.search(r'modelIndex="(\d+)"', text[s:s + 400])
        print("   ✗ 没闭合的实例 ✓：偏移 %d ✓ title=`%s` ✓ modelIdRef=`%s` ✓ index=%s ✓"
              % (s, ti.group(1) if ti else "?", mo.group(1) if mo else "?",
                 mi.group(1) if mi else "?"))
        print("      开头：%s" % text[s:s + 200].replace("\n", " "))
        if nxt_s < len(text) - 1:
            print("      它后面紧跟着：%s" % text[nxt_s:nxt_s + 160].replace("\n", " "))
        else:
            print("      ⇒ **它是文件里最后一个实例** ✓（末尾少了 `</instance>` ✓）")
