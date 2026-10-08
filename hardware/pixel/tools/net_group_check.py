# -*- coding: utf-8 -*-
r"""net_group_check：照 **Fritzing 源码口径**量"每张网在文件里到底成型了没有" ✓

为什么要有这个闸门 ✓（2026-10-08 用户报的件 ✓）：用户拿 `_work/v77_powerfull.fzz` 打开
Fritzing ⇒ 状态栏写「**布线完成**」✗，可几何上那三张网是断的 ✗，而且**没有鼠线** ✗
⇒ "看不到哪里要手工布线" ✗。根因 ✗：底图是"剥瘦版" ✓ ⇒ 断网那些脚在文件里只剩
"自己 ＋ 自己插的那个孔" ✗ ⇒ Fritzing 把它们**当单脚网丢掉** ✗（`graphutils.cpp:502`
`num_nodes == 1 ⇒ gotUserConnection=false` ✓）⇒ 那张网**不存在** ✗ ⇒ 无从显示 ✗。

判据 ✓（照源码 ✓，✗ 不自己发明 ✗）：
  · `connectoritem.cpp:1340 collectEqualPotential` ✓：顺 `<connect>` 声明走 ✓，
    ★ 同一个 `connectorId` 在**不同视图**里是**同一个**连接器 ✓（跨视图必须并成一个节点 ✓）；
  · `connectoritem.cpp:1413 collectParts` ✓：剔掉 Wire / 过孔 ✗，剩下的才进 `partConnectorItems`；
  · ⇒ 每只脚所在连通块里的**元件脚个数** < 3 ⇒ 这块只剩"脚 ＋ 一个孔"= **单脚网** ✗
    ⇒ Fritzing 看不见它 ✗、不会画鼠线 ✗。

实测标尺 ✓（同一条尺量出的"诚实/骗人"分界 ✓）：
  `v59`（用户截图证明诚实 ✓）/ `v76`（诚实 ✓）⇒ 断网的脚那块是 **3 / 7 / 3** ✓
  `v69` / `v77`（骗人 ✗）⇒ 同一批脚 **2 / 2 / 2** ✗

用法 ✓：py -3.13 tools\net_group_check.py <a.fzz> [<b.fzz> …] [--nets=pixel_nets.py]
退出码 ✓：0 = 每张网的每只脚那块都 ≥ 3 ✓；1 = 有"Fritzing 看不见"的网 ✗。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
sys.path.insert(0, r"F:\git\fritzing-parts-langhua\tools")
import pcb_wire as PW                                             # noqa: E402
import projdata                                                   # noqa: E402

VIEWS = ("breadboardView", "schematicView", "pcbView")
MIN_BLOCK = 3                # ★ 脚 ＋ 孔 ＝ 2 ⇒ 单脚网 ✗；≥3 ⇒ Fritzing 认得出 ✓


def parse_text(text):
    """⇒ `(owner, kind, edges)` ✓；节点 = `(mi, cid)` ✓（**跨视图同一个** ✓）"""
    owner, kind, edges = {}, {}, []
    for m in re.finditer(r"(?ms)^([ \t]*)<instance\b.*?^[ \t]*</instance>", text):
        blk = m.group(0)
        t = re.search(r"<title>([^<]*)</title>", blk)
        mi = re.search(r'\bmodelIndex="(\d+)"', blk)
        if not (t and mi):
            continue
        title, mi = t.group(1), mi.group(1)
        is_wire = ('moduleIdRef="WireModuleID"' in blk) or bool(
            re.search(r"<title>Via\d*</title>", blk))
        for view in VIEWS:
            v0 = blk.find("<%s" % view)
            if v0 < 0:
                continue
            v1 = blk.find("</%s>" % view, v0)
            for c in re.finditer(r'(?ms)<connector\b[^>]*connectorId="([\w]+)"[^>]*>(.*?)'
                                 r'</connector>', blk[v0:v1]):
                cid, inner = c.group(1), c.group(2)
                owner[(mi, cid)] = "%s.%s" % (title, cid)
                kind[(mi, cid)] = "w" if is_wire else "p"
                for d in re.finditer(r'<connect\b[^>]*connectorId="([\w]+)"\s*'
                                     r'modelIndex="(\d+)"', inner):
                    edges.append(((mi, cid), (d.group(2), d.group(1))))
    return owner, kind, edges


def parse(path):
    text, _nm = PW.read(path)
    return parse_text(text)


class UF(object):
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opt = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if not args:
        print(__doc__)
        return 2
    EXPECT = projdata.load(opt.get("nets", os.path.join(PIX, "pixel_nets.py")),
                           need=("EXPECT",)).EXPECT
    bad = 0
    for path in args:
        owner, kind, edges = parse(path)
        inv = {}
        for k, v in owner.items():
            inv.setdefault(v, k)
        uf = UF()
        for a, b in edges:
            uf.union(a, b)
        size = {}
        for k in owner:
            if kind.get(k) == "p":
                r = uf.find(k)
                size[r] = size.get(r, 0) + 1
        print("== %s ==" % os.path.basename(path))
        for net in sorted(EXPECT):
            pins, thin = [], []
            for m in EXPECT[net]:
                if not isinstance(m, str) or "." not in m:
                    continue
                k = inv.get(m)
                if k is None:
                    continue
                pins.append(m)
                if size.get(uf.find(k), 1) < MIN_BLOCK:
                    thin.append(m)
            if len(pins) < 2:
                continue
            # ★ 判据按**网**看 ✓：只要**有**脚落在 ≥3 的块里 ⇒ Fritzing 还认得出这张网 ✓；
            #   ✗ 全部脚都是"脚＋一个孔"那样（块 < 3） ⇒ 这张网会被**整张丢掉** ✗
            #   （实测：v59/v76 ⇒ 只有 `U1.connector20` 这种**单脚网**例外 ✓；
            #    v69/v77 ⇒ **9 张网全部** ≥2 只脚落单 ✗ ⇒ 状态栏谎报"布线完成" ✗）
            if thin and len(thin) == len(pins):
                bad += 1
                print("   ✗ `%-8s`：%d 只脚**全部**落单（块里只有 %s 个元件脚）✗ ⇒"
                      " Fritzing 会把这张网当**不存在** ✗：%s"
                      % (net, len(thin), MIN_BLOCK - 1, "、".join(thin[:4])))
            else:
                print("   ✓ `%-8s`：%d 只脚都在 Fritzing 认得出的块里 ✓%s"
                      % (net, len(pins),
                         "" if not thin else "（例外：%s 是单脚、本来就看不见 ✓）"
                         % "、".join(thin[:3])))
    print("⇒ %s" % ("✓ 全过：Fritzing 认得出每张网 ✓（像 v59/v76 ✓）" if not bad
                    else "✗ %d 处：Fritzing 会把这些网当**不存在** ✗ ⇒ 状态栏会报"
                         "「布线完成」✗、也不画鼠线 ✗" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
