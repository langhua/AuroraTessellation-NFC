# -*- coding: utf-8 -*-
r"""★★ 拿 Fritzing **自己另存出来的** `.fzz` 跟我的文件逐条比 `<connect>` ✓
—— 这是"**只听一个声音**"的硬办法 ✓（用户 2026-10-02 提出 ✓）：

做法 ✓：Fritzing 载入 → 它按**自己的运行时状态**重写每个 connector 的 `<connects>` ✓
⇒ 把它另存的文件拿回来，逐 modelIndex 比连接集合 ✓ ⇒ **差出来的那些**就是
"它认 / 我不认" 的地方 ✓ ✓（不用猜源码 ✗）。

用法 ✓：`fz_conn_diff.py <我的.fzz> <Fritzing另存的.fzz>`
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


def load(path):
    """⇒ {modelIndex: {(connectorId, 目标的 modelIndex)}} ✓ ＋ 标题表 ✓"""
    zin = zipfile.ZipFile(path)
    fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
    text = zin.read(fz).decode("utf-8")
    conn, title = {}, {}
    for _i, b in PW.blocks(text):
        mi = re.search(r'modelIndex="(\d+)"', b)
        if not mi:
            continue
        mi = mi.group(1)
        ti = re.search(r"<title>([^<]*)</title>", b)
        if ti:
            title[mi] = ti.group(1)
        pv = re.search(r"(?ms)<pcbView\b[^>]*>(.*?)</pcbView>", b)
        if not pv:
            continue
        for cm in re.finditer(r'(?s)<connector connectorId="([\w]+)"[^>]*>(.*?)</connector>',
                              pv.group(1)):
            for x in re.finditer(r'<connect connectorId="[\w]+" modelIndex="(\d+)"', cm.group(2)):
                conn.setdefault(mi, set()).add((cm.group(1), x.group(1)))
    return conn, title


a, ta = load(sys.argv[1])
b, tb = load(sys.argv[2])
print("== 比 `<connect>` ==")
print("   %-28s：%d 个实例有连接记录 ✓" % (os.path.basename(sys.argv[1]), len(a)))
print("   %-28s：%d 个实例有连接记录 ✓" % (os.path.basename(sys.argv[2]), len(b)))
only_b = only_a = 0
for k in sorted(set(a) | set(b), key=lambda z: int(z)):
    sa, sb = a.get(k, set()), b.get(k, set())
    if sa == sb:
        continue
    t = "`%s`(index=%s)" % (ta.get(k) or tb.get(k) or "?", k)
    if sb - sa:
        only_b += len(sb - sa)
        print("\n   仅 **Fritzing 另存的**里有 ✓ ⇒ %s" % t)
        for cid, tmi in sorted(sb - sa):
            print("      `%s` → index %s（%s）" % (cid, tmi, tb.get(tmi) or ta.get(tmi) or "?"))
    if sa - sb:
        only_a += len(sa - sb)
        print("\n   仅 **我这边**有 ✗ ⇒ %s" % t)
        for cid, tmi in sorted(sa - sb):
            print("      `%s` → index %s（%s）" % (cid, tmi, ta.get(tmi) or tb.get(tmi) or "?"))
print("\n★ 汇总 ✓：Fritzing 多出 %d 条、我多出 %d 条" % (only_b, only_a))
if only_b == 0 and only_a == 0:
    print("   ⇒ 两边**逐条相同** ✓（那就是我在自己这边多算的，不在文件里 ✓）")
