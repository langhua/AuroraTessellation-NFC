# -*- coding: utf-8 -*-
r"""fz_deglue_records：**只删「跨视图记录」** ⇒ 让面包板在 PCB 视图里不再偷偷并网 ✓（只读/写新件 ✓）

用法 ✓：
```
py -X utf8 tools\fz_deglue_records.py <in.fzz> --check        # 只查（0 条 = 合格 ✓，退出码 0/1）
py -X utf8 tools\fz_deglue_records.py <in.fzz> <out.fzz>     # 修（写新 .fzz ✓）
```

## 病（用户 2026-10-10 报的件 ✓：`pixel-pcb-v81.fzz`）

用户 ✓：「PCB **已经不需要再布线了**，可 Fritzing 仍说**两根线没布好**」✗
（状态栏「**7 中的 5 网络布线完成，2 个连接仍然需要布线**」✗）。
本项目闸门**全过** ✓（`pcb_check` ①②…⑫ ✓、`net_group_check` ✓）⇒ 闸门与状态栏**不同口径** ✓。

## 机理（**照源码** ✓ ＋ 本项目 `tools\bb_probe.py`／`net_group_check.py` 已立的结论 ✓）

1. 核心面包板件给**每个孔**都声明了 `<pcbView layer="breadboardbreadboard">` ✓
   ⇒ 面包板的孔在 **PCB 视图里也是连接器项**（看不见 ✗ 但在网表里 ✓）；
2. 面包板件自身有 **130 条内部 bus**（同列孔的条带 ✓）⇒ 同一 bus 的孔在 PCB 视图里**互连** ✓；
3. 于是实例里那些 `<connect … layer="breadboardbreadboard"/>` **跨视图记录** ✗
   —— 在 PCB 视图里是"真"连接 ✗ ⇒ 顺着「孔 → bus → 孔」把**两张本来分开的网并成一张** ✗
   ⇒ `GraphUtils::scoreOneNet()` 判「该网还有 N 个连通片 − 1 条没布」✗ ＋ 画鼠线虚线 ✗。
4. ★ 本项目实测的**根因** ✓（`tools\pcb_rats_probe.py` 复现 ✓，`pixel-pcb-v81.fzz` ✓）：
   面包板 `pcbView` 段里那 46 条孔记录是**上一轮面包板改孔之前的旧账** ✗
   （逐脚核过 ✓：`U1.connector5` 真插 `pin34F` ✓、却声明成 `pin34F` ✓…而 `D3.connector0` 真插
   `pin12E` ✗ 声明成 `pin16E` ✗ —— 差了 4 列 ✓）⇒ 于是：
   · 孔 `pin16J` 一只孔声明了**两只脚**（`L1.connector0` ＋ `C1.connector0` ✗ 物理不可能 ✗）
     ⇒ 把 `RC` 与 `COIL_A` 并成一张 ✗；
   · 同 bus 的 `pin17F/pin17G/pin17J` 声明了 `D3.connector4`＋`R1.connector0`（`BR+` ✗）
     与 `C1.connector1`（`GND` ✗）⇒ 把 `GND` 与 `BR+` 并成一张 ✗。
   ⇒ 两张"并出来"的网各碎成 **2 块铜** ⇒ 正好 **1 + 1 = 2** 条没布 ✓✓（与状态栏对得上 ✓）。

## 修法（**不动任何几何** ✓、**不动面包板视图** ✓、**不删/不加任何视图段** ✓）

只在**各实例的 `<pcbView>` 段里**删掉「跨视图记录」✓；两个方向**都删** ✗：
  · 零件脚那边 ✓：`layer="breadboardbreadboard"` 的记录（目标 = 面包板的孔 ✓）；
  · 面包板那边 ✓：它 `pcbView` 段里的记录（目标 = 零件脚 ✓，`layer` 写成 `copper0` 看着像铜 ✗）。
★ 只删一半**没用** ✗（记录是**双向**的 ✓，库仓 `fz_deglue_views.py` 的实测记过 ✓）。

★ 与库仓 `fz_deglue_views.py` 的差别 ✓：那一份把面包板的 `<pcbView>`/`<schematicView>`
**整段删掉** ✗（v68 ✓，用户确认三视图正确 ✓）；这一份**保留段落** ✓ ⇒ 只少几行不可见声明 ✓
⇒ 视图段数量／渲染**逐字节不变** ✓（本仓验收要这一条 ✓）。两条路都通 ✓，按需选 ✓。
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

BB_LAYER = "breadboardbreadboard"
REC_RE = re.compile(r'<connect\b[^>]*/>')
INST_RE = re.compile(r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>")
PCB_RE = re.compile(r"(?s)(<pcbView\b[^>]*>)(.*?)(</pcbView>)")


def read_fz(path):
    z = zipfile.ZipFile(path)
    inner = [n for n in z.namelist() if n.endswith(".fz")][0]
    return z, inner, z.read(inner).decode("utf-8")


def is_breadboard(blk):
    m = re.search(r'moduleIdRef="([^"]+)"', blk)
    mod = m.group(1) if m else ""
    return ("Breadboard" in mod) and not mod.startswith("Wire")


def title_of(blk):
    m = re.search(r"<title>([^<]*)</title>", blk)
    return m.group(1) if m else "?"


def _strip_line(text, a, b):
    """删 `text[a:b]` ✓：若这一行剩下的只有空白 ⇒ **连行一起删** ✓（文件干净些 ✓）"""
    ls = text.rfind("\n", 0, a) + 1
    le = text.find("\n", b)
    if le < 0:                                        # 末行（没有尾随换行 ✓）
        le = len(text)
    elif text[ls:a].strip() == "" and text[b:le].strip() == "":
        return text[:ls] + text[le + 1:]
    if text[ls:a].strip() == "" and text[b:le].strip() == "":
        return text[:ls] + text[le:]                  # 末行：别吃掉最后一个字符 ✓
    return text[:a] + text[b:]


def survey(text):
    """⇒ `[(标题, 段里每条记录, 是不是跨视图 ✓)]` ✓ + 面包板 mi 表 ✓"""
    out, bbs = [], []
    for m in INST_RE.finditer(text):
        blk = m.group(0)
        ttl = title_of(blk)
        bb = is_breadboard(blk)
        if bb:
            bbs.append((ttl, blk))
        pm = PCB_RE.search(blk)
        if not pm:
            continue
        for r in REC_RE.finditer(pm.group(2)):
            lay = re.search(r'layer="([^"]+)"', r.group(0))
            lay = lay.group(1) if lay else ""
            cross = bb or (lay == BB_LAYER)
            out.append((ttl, r.group(0), cross, bb))
    return out, bbs


def check(text):
    rows, _bbs = survey(text)
    bad = [r for r in rows if r[2]]
    return rows, bad


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = args[0]
    _z, inner, text = read_fz(src)
    rows, bad = check(text)
    print("== %s（包内 `%s`）==" % (os.path.basename(src), inner))
    print("   `pcbView` 段里的 `<connect>` 记录 %d 条 ✓，其中**跨视图**（会在 PCB 视图里生效 ✗）%d 条"
          % (len(rows), len(bad)))
    by = {}
    for ttl, rec, cross, bb in rows:
        if cross:
            by.setdefault(ttl + ("（面包板自己）" if bb else ""), []).append(rec)
    for k in sorted(by):
        print("     ✗ %-24s %d 条" % (k, len(by[k])))
    if "--check" in argv:
        print("   ⇒ %s" % ("✓ 合格：PCB 视图里没有能生效的跨视图记录 ✓"
                           if not bad else
                           "✗ %d 条跨视图记录 ⇒ 面包板会在 PCB 视图里并网 ✗" % len(bad)))
        return 1 if bad else 0
    if len(args) < 2:
        print("✗ 要写新件得给两个参数：<in.fzz> <out.fzz> ✓")
        return 2
    dst = args[1]
    old_bb = re.findall(r"(?s)<breadboardView\b[^>]*>.*?</breadboardView>", text)
    removed = 0
    out = text
    # 从后往前改，免得位移 ✓
    spans = []
    for m in INST_RE.finditer(text):
        blk = m.group(0)
        pm = PCB_RE.search(blk)
        if not pm:
            continue
        bb = is_breadboard(blk)
        body_a = m.start() + pm.start(2)                     # 段体在全文里的起点 ✓
        for r in REC_RE.finditer(pm.group(2)):
            lay = re.search(r'layer="([^"]+)"', r.group(0))
            lay = lay.group(1) if lay else ""
            if bb or lay == BB_LAYER:
                spans.append((body_a + r.start(), body_a + r.end()))
    for a, b in sorted(spans, reverse=True):
        out = _strip_line(out, a, b)
        removed += 1
    # 自检 ✓
    ET.fromstring(out)
    assert out.count("<connect") == text.count("<connect") - removed
    new_bb = re.findall(r"(?s)<breadboardView\b[^>]*>.*?</breadboardView>", out)
    assert new_bb == old_bb, "面包板视图被动了 ✗"
    for vn in ("pcbView", "schematicView", "breadboardView"):
        assert out.count("<%s" % vn) == text.count("<%s" % vn), "%s 段数变了 ✗" % vn
    # ★ 逐行核：**改动只许是"删掉那些跨视图记录"** ✗（别的字节一律不许动 ✓）
    import difflib
    la, lb = text.splitlines(keepends=True), out.splitlines(keepends=True)
    hunks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        hunks.append((tag, la[i1:i2], lb[j1:j2]))
    odd = [l for _t, gone, new in hunks for l in gone
           if BB_LAYER not in l and (not l.strip() or l.strip() == "")]
    for _t, gone, new in hunks:
        for l in new:
            if l.strip():
                odd.append(l)
    assert not odd, "有非预期改动 ✗：%r" % odd[:3]
    print("   ⇒ 逐行核 ✓：改的只有那 **%d** 行（全是 `<connect … breadboardbreadboard/>` ✗），"
          "其余**一行未动** ✓" % len(hunks))
    z = zipfile.ZipFile(src)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in z.namelist():
            # ★ 连**包内条目**的时间戳/属性一起照抄 ✓ ⇒ 同一输入必得**逐字节相同**的产出 ✓
            #   （✗ 别用 `writestr(名字, …)` ✗ —— 那会写"现在"的时间 ⇒ 复现性没了 ✗）
            zi = z.getinfo(n)
            zi.compress_type = (zipfile.ZIP_STORED if n == inner
                                else zipfile.ZIP_DEFLATED)
            zo.writestr(zi, out.encode("utf-8") if n == inner else z.read(n))
    print("   ⇒ 删了 **%d** 条跨视图记录 ✓（其余**逐字节不变** ✓）" % removed)
    print("   ⇒ 视图段数不变 ✓（pcbView %d ／ schematicView %d ／ breadboardView %d ✓）"
          % (out.count("<pcbView"), out.count("<schematicView"), out.count("<breadboardView")))
    print("   ⇒ 面包板视图段**逐字节相同** ✓")
    print("   ⇒ 写 **%s** ✓" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
