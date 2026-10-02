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


def by_title(conn, title):
    """★ 按**部件名**归 ✓ —— Fritzing 另存时会把 modelIndex **重新编号** ✗
    ⇒ 按 id 比会整片错位 ✓（实测：它给 194 个实例全换了号 ✓）。"""
    out = {}
    for mi, s in conn.items():
        out.setdefault(title.get(mi, "index" + mi), set()).update(
            (cid, title.get(tmi, "index" + tmi)) for (cid, tmi) in s)
    return out


a, ta = load(sys.argv[1])
b, tb = load(sys.argv[2])
A, B = by_title(a, ta), by_title(b, tb)
print("== 比 `<connect>`（**按部件名** ✓，因为另存会重编号 ✗）==")
print("   %-30s：%d 个带连接记录的部件 ✓" % (os.path.basename(sys.argv[1]), len(A)))
print("   %-30s：%d 个带连接记录的部件 ✓" % (os.path.basename(sys.argv[2]), len(B)))
only_b = only_a = 0
for k in sorted(set(A) | set(B)):
    sa, sb = A.get(k, set()), B.get(k, set())
    if sa == sb:
        continue
    if sb - sa:
        only_b += len(sb - sa)
        print("\n   仅 **Fritzing 另存的**里有 ✓ ⇒ `%s`" % k)
        for cid, t in sorted(sb - sa):
            print("      `%s` → `%s`" % (cid, t))
    if sa - sb:
        only_a += len(sa - sb)
        print("\n   仅 **我这边**有 ✗ ⇒ `%s`" % k)
        for cid, t in sorted(sa - sb):
            print("      `%s` → `%s`" % (cid, t))
print("\n★ 汇总 ✓：Fritzing 多出 %d 条、我多出 %d 条" % (only_b, only_a))
if only_b == 0 and only_a == 0:
    print("   ⇒ 两边**逐条相同** ✓（那我多算的那几个网不在文件里 ✓，是**算法**差异 ✓）")
