# -*- coding: utf-8 -*-
r"""fz_trim_construct_views：**只删「建构用」零件的 `pcbView` 视图段** ✓（只读/写新件 ✓）

用法 ✓：
```
py -X utf8 tools\fz_trim_construct_views.py <in.fzz> --check        # 只查（合格 ⇒ 退出码 0 ✓）
py -X utf8 tools\fz_trim_construct_views.py <in.fzz> <out.fzz>      # 修（写新 .fzz ✓）
```

## 为什么要有它 ✗✓（2026-10-10 第五十二轮 ✓）

用户 ✓：「`pixel-pcb-v82.fzz` 三个视图**都是布线完成**，可我在三个视图里**随意删掉任意一根导线，
**也还是布线完成**」✗ —— 那句话背后的机理本项目已经量清 ✓（见 `tools\pcb_rats_probe.py` 文件头 ✓）：

  · **面包板是"建构用"件** ✓：它**只在面包板视图里可见** ✗
    （`sketch/pcbsketchwidget.cpp:441`、`schematicsketchwidget.cpp:146` 都
     `setVisible(false); setEverVisible(false)` ✓）—— 它在 PCB／原理图视图里**只是"为了
    让连接更容易同步"而留着** ✓（源码原话 ✓）；
  · 上一轮（第五十一轮 ✓）已经把 `pcbView` 段里那 94 条**跨视图记录**删了 ✓（`fz_deglue_records.py` ✓）
    ⇒ 这个段现在**一条声明都不剩** ✓ ⇒ 它已经**对 Fritzing 的网表毫无作用** ✓，只剩 46 条
    **空 `<connector>` 记录** ＋ 一段看不见的 `<geometry>` ✗；
  · ⇒ 本工具把这**整个 `pcbView` 段**删掉 ✓：让"建构用件只活在面包板视图里"这条**原则**落到
    文件结构上 ✓ ⇒ 以后谁再往里写记录 ✗ 也不会**悄悄**在 PCB 视图里生效 ✗。

★ **范围（硬约束 ✓）**：只动**面包板类件**的 **`pcbView`** 段 ✓。
  · **原理图视图**用户已"定稿不改" ✗ ⇒ 它的 `schematicView` 段**只报告、不执行** ✓
    （同一条约束下，`breadboardView` 段更不许动 ✗）；
  · 所以本工具**只认 `--views=pcbView`** ✓（缺省 ✓）；点别的视图 ⇒ **拒绝** ✗。

★ **安全性（实测 ✓）**：删段前先断言该段里 **`<connect>` 记录数 = 0** ✓（有记录 ⇒ 拒绝 ✗）；
  删段后断言 **`schematicView`／`breadboardView` 段逐字节未动** ✓、**除这段之外一行未动** ✓、
  产出仍能解析 ✓。渲染层面：该件在 PCB 视图**不可见** ✓ ⇒ 渲染 **逐字节相同** ✓（验收里量 ✓）。
""" 
import difflib
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

INST_RE = re.compile(r"(?ms)^([ \t]*)<instance\b.*?\n\1</instance>")


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


def view_span(text, view):
    """⇒ `(实例标题, 段起点, 段终点, 段文本, 段内 <connect> 条数)` 列表 ✓"""
    out = []
    for m in INST_RE.finditer(text):
        blk = m.group(0)
        if not is_breadboard(blk):
            continue
        vm = re.search(r"(?s)<%s\b[^>]*>.*?</%s>" % (view, view), blk)
        if not vm:
            continue
        a = m.start() + vm.start()
        body = vm.group(0)
        out.append((title_of(blk), a, a + len(body), body,
                    body.count("<connect ")))
    return out


def check(text, view="pcbView"):
    """⇒ `(rows, bad)` ✓；`bad` = 还没删干净（段里还有记录 ✗ 或段还在 ✓）"""
    rows = view_span(text, view)
    bad = [r for r in rows if r[4] > 0]
    return rows, bad


def strip_whole_line(text, a, b):
    """把 `[a, b)` 连**它独占的整行**（含尾换行 ✓）一起去掉 ✓"""
    ls = text.rfind("\n", 0, a) + 1
    le = text.find("\n", b)
    le = len(text) if le < 0 else le + 1
    assert text[ls:a].strip() == "" and text[b:le].strip() == "", \
        "要删的段不是独占整块 ✗（别删错 ✓）"
    return text[:ls] + text[le:], ls, le


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opt = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if not args:
        print(__doc__)
        return 2
    view = opt.get("views", "pcbView")
    if view != "pcbView":
        print("✗ 本工具**只许动 `pcbView`** ✗（原理图/面包板视图用户已定稿 ✓ ⇒ 只报告、不执行 ✓）")
        return 3
    src = args[0]
    z, inner, text = read_fz(src)
    rows, bad = check(text, view)
    print("== %s（包内 `%s`）==" % (os.path.basename(src), inner))
    print("   面包板类件的 `<%s>` 段 %d 个 ✓，其中**段内还有 `<connect>` 记录**的 %d 个 %s"
          % (view, len(rows), len(bad), "✗" if bad else "✓"))
    for ttl, _a, _b, body, n in rows:
        print("     %s %-12s 段长 %5d 字节 ｜ 声明 %d 条 ｜ 连接器 %d 条"
              % ("✗" if n else "✓", ttl, len(body), n, body.count("<connector ")))
    if "--check" in argv:
        okall = (not rows)
        print("   ⇒ %s" % ("✓ 合格：已经没有「建构用件」的 `pcbView` 段了 ✓" if okall else
                           ("✗ 还没清：还有 %d 段 ✗（跑一次不带 `--check` 的修即可 ✓）" % len(rows))))
        return 0 if okall else 1
    if bad:
        print("   ✗ 段里还有 `<connect>` 声明 ✗ ⇒ **拒绝执行** ✗（先删声明 ✓："
              "`fz_deglue_records.py` ✓）")
        return 1
    if not rows:
        print("   ✓ 已经是目标状态 ✓（无需改 ✓）")
    if len(args) < 2:
        print("✗ 要写新件得给两个参数：<in.fzz> <out.fzz> ✓")
        return 2
    dst = args[1]
    spans = sorted(((r[1], r[2]) for r in rows), reverse=True)
    out, cut, allowed = text, 0, set()
    for a, b in spans:
        line_no = text.count("\n", 0, a)
        out, ls, le = strip_whole_line(out, a, b)
        nlines = text.count("\n", ls, le)
        allowed |= set(range(line_no, line_no + nlines))
        cut += 1
    ET.fromstring(out)
    for vn in ("schematicView", "breadboardView"):
        old = re.findall(r"(?s)<%s\b[^>]*>.*?</%s>" % (vn, vn), text)
        new = re.findall(r"(?s)<%s\b[^>]*>.*?</%s>" % (vn, vn), out)
        assert old == new, "%s 段被动了 ✗" % vn
    la, lb = text.splitlines(keepends=True), out.splitlines(keepends=True)
    odd = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for k in range(i1, i2):
            if k not in allowed:                    # ★ 只许删"那段 `pcbView` 里的行" ✓
                odd.append(la[k])
        for l in lb[j1:j2]:                         # ★ 一行都不许加/改 ✓
            if l.strip():
                odd.append(l)
    assert not odd, "有非预期改动 ✗：%r" % odd[:3]
    print("   ⇒ 逐行核 ✓：删掉的全是那 %d 段 `%s` 的行 ✓（`schematicView`／`breadboardView` "
          "逐字节未动 ✓）" % (cut, view))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in z.namelist():
            zi = z.getinfo(n)
            zi.compress_type = zipfile.ZIP_STORED if n == inner else zipfile.ZIP_DEFLATED
            zo.writestr(zi, out.encode("utf-8") if n == inner else z.read(n))
    print("   ⇒ 写 **%s** ✓（%d 字节）" % (dst, os.path.getsize(dst)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
