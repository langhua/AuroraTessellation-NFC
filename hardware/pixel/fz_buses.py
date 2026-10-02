# -*- coding: utf-8 -*-
r"""把包里每个 `.fzp` 的 `<buses>` 打出来 ✓，并指出"哪几个脚被同一个 bus 并起来" ✓
（用来找"Fritzing 把哪两个网并成一个" ✗ —— 我的判据少合并的那一步 ✓）
用法 ✓：`fz_buses.py <sketch.fzz>`
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_wire as PW                                              # noqa: E402

path = sys.argv[1]
zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

# 实例 → moduleIdRef（只列 pcb 视图里用的 ✓）
inst = {}
for _i, b in PW.blocks(text):
    mi = re.search(r'modelIndex="(\d+)"', b)
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    ti = re.search(r"<title>([^<]*)</title>", b)
    if mi and mo:
        inst[mi.group(1)] = (mo.group(1), ti.group(1) if ti else "")

print("== %s：包内 .fzp 的 `<buses>` ==" % os.path.basename(path))
names = [n for n in zin.namelist() if n.endswith(".fzp")]
print("★ 这个 `.fzz` 里 `.fzp` 有 %d 个 ⇒ %s"
      % (len(names), "下面按安装目录解析 ✓" if not names else "直接读包内 ✓"))

# ★★ 关键 ✓：`.fz` 里的 `path=":/resources/parts/…"` 是 **Fritzing 的 Qt 资源路径** ✗
#   ⇒ 磁盘上要去**安装目录 / 源码树**里找 ✓ —— 本仓工具原来**没做这一步** ✗
#   ⇒ "同件同 `bus()`" 从来没生效 ✗（= 用户怀疑的"判据跟 Fritzing 不一样" ✓ 命中 ✓）
ROOTS = [r"F:\build-fritzing\fritzing-app\resources\parts",
         r"C:\Program Files\Fritzing\parts",
         r"C:\Program Files (x86)\Fritzing\parts"]
paths = {}
for _i, b in PW.blocks(text):
    mi = re.search(r'modelIndex="(\d+)"', b)
    pa = re.search(r'path="([^"]+)"', b)
    ti = re.search(r"<title>([^<]*)</title>", b)
    if mi and pa:
        p = pa.group(1).replace(":/resources/parts/", "").replace("/", os.sep)
        paths.setdefault(p, []).append("%s(%s)" % (ti.group(1) if ti else "?", mi.group(1)))

for p, users in sorted(paths.items()):
    hit = None
    for r in ROOTS:
        f = os.path.join(r, p)
        if os.path.exists(f):
            hit = f
            break
    print("\n%-42s ← 本板 %d 处：%s" % (p, len(users), ", ".join(users[:8])))
    if hit is None:
        print("   ✗ 在 %s 里都找不到 ⇒ **读不到它的 `<buses>`** ✗（判据会漏合并 ✓）"
              % " / ".join(ROOTS))
        continue
    t = open(hit, encoding="utf-8", errors="replace").read()
    buses = []
    for bm in re.finditer(r'(?s)<bus[^>]*\bid="([^"]*)"[^>]*>(.*?)</bus>', t):
        mem = re.findall(r'<member[^>]*\bconnectorId="([^"]+)"', bm.group(2))
        buses.append((bm.group(1) or "(无 id)", mem))
    print("   读到 `%s` ✓；`<buses>` %d 条：%s"
          % (hit, len(buses), "" if buses else "**一条都没有** ✗"))
    for bid, mem in buses:
        print("      bus `%s`：%s" % (bid, ", ".join(mem)))
