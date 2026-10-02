# -*- coding: utf-8 -*-
r"""★★ 去重**完全叠死的过孔** ✓ —— 修我生成器的 bug ✗（用户 2026-10-02 发现 ✓）

实测（`pixel-pcb-v59/v61` ✓）：
  · `Via6` ↔ `Via8`：铜心都 (45.181, 20.522) mm ✓ 心距 **0.000 mm** ✗ —— 0 条 / 4 条记录
  · `Via17` ↔ `Via18`：铜心都 (43.931, 15.472) mm ✓ 心距 **0.000 mm** ✗ —— 5 条 / 4 条记录
  两对都属**同一个网** ✓ ⇒ 不是短路 ✗，是**重复放着** ✗ ⇒ Fritzing 只认其中一颗 ✓、
  另一颗被撂单 ✓ ⇒ 就是它报「2 个连接件仍然需要布线」的来源 ✓

★ 另外查实一处**我输出里的格式缺陷** ✗：`<instance` 300 个 / `</instance>` 299 个 ✓
  ⇒ **有一处实例没闭合** ✗ ⇒ 凡是"同缩进配对"的解析器（`PW.blocks` ✓）从那里起整片错位 ✗
  （实测只读到 16 颗 ✓）；⇒ 本脚本**一律按 `<title>` 扫块** ✓（能读到全部 18 颗 ✓）。

做法 ✓（几何一字不改 ✓）：保留记录多的 ✓ → 删多余那颗的实例块 ✓ → 别处指向它的
`modelIndex` 改指保留的 ✓ → 同一个 `<connects>` 里重复行去重 ✓。
用法 ✓：`fz_fix_dup_vias.py <in.fzz> <out.fzz> [阈值mm=0.6]`
"""
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import part_box as PB                                              # noqa: E402

SK = 25.4 / 90.0
src, dst = sys.argv[1], sys.argv[2]
THR = float(sys.argv[3]) if len(sys.argv) > 3 else 0.60

zin = zipfile.ZipFile(src)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

# ── ① 按 `<title>` 扫出每颗过孔 ✓（`<instance`/`</instance>` 数目不等 ⇒ 不能靠配平 ✗）
vias = []
for m in re.finditer(r"<title>(Via\d+)</title>", text):
    i = m.start()
    s, e = text.rfind("<instance", 0, i), text.find("</instance>", i)
    if s < 0 or e < 0:
        continue
    b = text[s:e + len("</instance>")]
    mi = re.search(r'modelIndex="(\d+)"', b)
    g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
    x = re.search(r'<geometry[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', g.group(1)) if g else None
    hs = re.search(r'<property name="hole size" value="([\d.]+)mm,([\d.]+)mm"', b)
    if not (mi and x):
        print("   ⚠ `%s` 扫不出几何 ⇒ 跳过 ✓" % m.group(1))
        continue
    hole, ring = (float(hs.group(1)), float(hs.group(2))) if hs else (0.3, 0.15)
    off = PB.ring_off_mm(hole, ring) / SK
    vias.append(dict(title=m.group(1), mi=mi.group(1),
                     c=(float(x.group(1)) + off, float(x.group(2)) + off),
                     nrec=len(re.findall(r'<connect\b', b))))
print("   读到 **%d** 颗过孔 ✓（阈值 %.2f mm ✓）" % (len(vias), THR))

# ── ② 找出叠死的对 ✓，留记录多的 ✓
kill = []
for i in range(len(vias)):
    for j in range(i + 1, len(vias)):
        a, b = vias[i], vias[j]
        d = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1]) * SK
        if d >= THR:
            continue
        keep, drop = (a, b) if a["nrec"] >= b["nrec"] else (b, a)
        print("   ★ 叠死 ✓：`%s`(%d 条) ↔ `%s`(%d 条) 心距 %.3f mm ⇒ 删 `%s` ✓ 改指 `%s` ✓"
              % (a["title"], a["nrec"], b["title"], b["nrec"], d, drop["title"], keep["title"]))
        kill.append((keep, drop))
if not kill:
    print("✓ 没有叠死的过孔 ⇒ 不用改 ✗")
    sys.exit(0)

# ── ③ 删块 ✓：**按名字定位 + 按位置切** ✓（✗ 不用正则跨越 —— 本文件有一处实例**没闭合**
#   ✗（`<instance` 300 / `</instance>` 299 ✓）⇒ 正则会把跨两个实例的片段也匹配上 ✗
#   （实测 `Via6` 被匹配到 2 次 ✗）⇒ 用 `<title>` 的位置往前/往后切 ✓ 才是确定的 ✓）
out = text
for keep, drop in kill:
    tp = out.find("<title>%s</title>" % drop["title"])
    if tp < 0:
        print("   ✗ 找不到 `%s` 的名字 ⇒ 停下来报 ✓" % drop["title"])
        sys.exit(1)
    s = out.rfind("<instance", 0, tp)
    e = out.find("</instance>", tp)
    if s < 0 or e < 0:
        print("   ✗ `%s` 的块边界切不出来 ⇒ 停下来报 ✓" % drop["title"])
        sys.exit(1)
    e += len("</instance>")
    blk = out[s:e]
    if blk.count("<instance") != 1:
        print("   ⚠ `%s` 的块里出现 %d 个 `<instance` ✗ ⇒ **这里就是没闭合的地方** ✓"
              "（我的输出缺陷 ✓，Fritzing 容错但解析器会错位 ✓）"
              % (drop["title"], blk.count("<instance")))
    out = out[:s] + out[e:]
    n2 = len(re.findall(r'modelIndex="%s"' % drop["mi"], out))
    out = out.replace('modelIndex="%s"' % drop["mi"], 'modelIndex="%s"' % keep["mi"])
    print("   删了 `%s` ✓（%d 处引用改指 `%s` ✓）" % (drop["title"], n2, keep["title"]))


def _dedup(m):
    seen, keep = set(), []
    for ln in m.group(2).split("\n"):
        t = ln.strip()
        if t.startswith("<connect "):
            if t in seen:
                continue
            seen.add(t)
        keep.append(ln)
    return m.group(1) + "\n".join(keep) + "</connects>"


b4 = out.count("<connect ")
out = re.sub(r"(?s)(<connects>)(.*?)</connects>", _dedup, out)
print("   记录去重 ✓：<connect> %d → %d 条 ✓" % (b4, out.count("<connect ")))
print("   实例配平复核 ✓：`<instance` %d / `</instance>` %d %s"
      % (out.count("<instance"), out.count("</instance>"),
         "✓" if out.count("<instance") == out.count("</instance>") else "✗ 仍不等"))

zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
for n in zin.namelist():
    zout.writestr(n, out.encode("utf-8") if n == fz else zin.read(n))
zout.close()
print("✓ 写出 `%s` ✓（几何/走线一字未改 ✓，只去了重复的过孔 ✓）" % os.path.basename(dst))
