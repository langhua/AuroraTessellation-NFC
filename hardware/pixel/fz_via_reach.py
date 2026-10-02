# -*- coding: utf-8 -*-
r"""按「虚线的另一头」反查是哪颗过孔 ✓（Fritzing 会重新编号过孔 ✗ ⇒ 名字对不上 ✗）

做法 ✓：从每颗过孔出发，**穿过走线和别的过孔**（只有过孔过不去 ✗）把链走完 ✓，
列出路上接到的**脚名**（照 `.fzp` 的 `connector name` ✓，和 Fritzing 显示的一致 ✓）。
用法 ✓：`fz_via_reach.py <sketch.fzz> [C1 L1]`（后两个是要找的件名 ✓）
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT2, "fritzing-parts-langhua", "tools"))
sys.path.insert(0, os.path.dirname(HERE))
import pcb_check as PC                                             # noqa: E402
import pcb_wire as PW                                              # noqa: E402

path = sys.argv[1]
namelist = [n for n in sys.argv[2:]] or ["C1", "L1"]

zin = zipfile.ZipFile(path)
fz = [n for n in zin.namelist() if n.endswith(".fz")][0]
text = zin.read(fz).decode("utf-8")

wire, via = {}, {}
for _i, b in PW.blocks(text):
    mo = re.search(r'moduleIdRef="([^"]+)"', b)
    mi = re.search(r'modelIndex="(\d+)"', b)
    if not (mo and mi):
        continue
    if mo.group(1).startswith("Wire"):
        t = PW.parse_trace(b)
        if t is None:
            continue
        wire[mi.group(1)] = dict(mi=mi.group(1), ends=t.get("ends") or {})
    elif mo.group(1).startswith("Via"):
        g = re.search(r"(?s)<pcbView\b[^>]*>(.*?)</pcbView>", b)
        ti = re.search(r"<title>([^<]*)</title>", b)
        via[mi.group(1)] = dict(mi=mi.group(1), title=ti.group(1) if ti else mi.group(1),
                                ends={})
        for y in re.finditer(r'<connect connectorId="([\w]+)" modelIndex="(\d+)" layer="([\w]+)"',
                             g.group(1)):
            via[mi.group(1)]["ends"].setdefault(0, []).append(
                (y.group(1), y.group(2), y.group(3)))

pads = {}
for q in PC.collect(path)["pads"]:
    pads[(q.get("mi"), q.get("cid"))] = q


def reach(start):
    """从 start（`("W"/"V", mi)` ✓）出发，把整条链走完 ✓ ⇒ 接到的脚 ✓（**穿过过孔** ✓）"""
    seen, st, out = set([start]), [start], []
    while st:
        tag, mi = st.pop()
        lst = (wire.get(mi) if tag == "W" else via.get(mi))
        for _e, arr in (lst["ends"] or {}).items():
            for (cid, tmi, _lay) in arr:
                if tmi in wire and ("W", tmi) not in seen:
                    seen.add(("W", tmi))
                    st.append(("W", tmi))
                elif tmi in via and ("V", tmi) not in seen:
                    seen.add(("V", tmi))
                    st.append(("V", tmi))
                elif tmi not in wire and tmi not in via:
                    q = pads.get((tmi, cid))
                    out.append("%s.%s" % (q["title"], q["nm"] or cid) if q
                               else "%s.%s" % (tmi, cid))
    return out, {s for s in seen if s[0] == "V"}


hits = {}
for k, v in via.items():
    got, others = reach(("V", k))
    if got:
        hits[v["title"]] = (sorted(set(got)), sorted(via[o[1]]["title"] for o in others))
for nm in namelist:
    print("\n=== 链能通到 `%s.*` 的过孔 ===" % nm)
    found = False
    for title, (got, others) in sorted(hits.items()):
        mine = [g for g in got if g.split(".")[0] == nm]
        if mine:
            found = True
            print("   `%s` → 通到 %s ✓   （整条链上的孔：%s）"
                  % (title, "、".join("`%s`" % m for m in mine),
                     ",".join(others) or "只有它自己"))
    if not found:
        print("   （没有 ✓）")
