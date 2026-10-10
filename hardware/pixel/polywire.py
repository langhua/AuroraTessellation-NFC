# -*- coding: utf-8 -*-
r"""给 `.fzz` 加一条**折线走线**（N 段 ⇒ N−1 个 Wire 实例 ✓），**声明/回指一次写全** ✓

★ 端点可以三种写法 ✓（坐标**一律由文件自己算** ✗ 不许手输 ✗）：
  · `件.connectorN`       ⇒ 该焊盘**中心** ✓（记 `layer="copper0"` ✓）
  · `Wire名:connectorN`   ⇒ 那条**已有走线**的某个端点 ✓（记 `layer="copper0trace"` ✓）
  · `x_mm,y_mm`           ⇒ 裸点 ✓（只与**本折线相邻段**相连 ✓ —— 单点连接 ✓）

★ 逐字照 Fritzing 亲笔 ✓（模板抄自 v84 里 Fritzing 自己写的走线 ✓）：
  `<pcbView layer="copper0trace" bottom="true">` ✓ /
  `<geometry z x y x1 y1 x2 y2 wireFlags="4"/>`（`x,y` = A 端 ✓、`x1=y1=0` ✓、`x2,y2` = A→B ✓）/
  `<wireExtras mils color opacity banded/>` ✓ / 两端 `<connector>` ＋ `<connects>` ✓
★ **两级回指都补** ✓（焊盘侧 ✓、走线侧 ✓）—— 少一边 Fritzing 就认不出这条链 ✗。

用法：
  py -3.13 _work\polywire.py <in.fzz> <out.fzz> <名前缀> R1.connector0 42.0,19.0 D3.connector3
"""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

PIX = r"f:\git\AuroraTessellation-NFC\hardware\pixel"
if PIX not in sys.path:
    sys.path.insert(0, PIX)
import toolpaths                                                    # noqa: E402,F401
import pcb_pads as PP                                              # noqa: E402
import pcb_wire as PW                                              # noqa: E402
import fz_strip_pcb as SP                                          # noqa: E402

SEG = """        <instance moduleIdRef="WireModuleID" modelIndex="{mi}" path=":/resources/parts/core/wire.fzp">
            <title>{title}</title>
            <views>
                <pcbView layer="copper0trace" bottom="true">
                    <geometry z="{z}" x="{ax}" y="{ay}" x1="0" y1="0" x2="{dx}" y2="{dy}" wireFlags="4"/>
                    <wireExtras mils="{mils}" color="{color}" opacity="1" banded="0"/>
                    <connectors>
                        <connector connectorId="connector1" layer="copper0trace">
                            <geometry x="0" y="0"/>
                            <connects>
                                <connect connectorId="{bc}" modelIndex="{bmi}" layer="{bl}"/>
                            </connects>
                        </connector>
                        <connector connectorId="connector0" layer="copper0trace">
                            <geometry x="0" y="0"/>
                            <connects>
                                <connect connectorId="{ac}" modelIndex="{ami}" layer="{al}"/>
                            </connects>
                        </connector>
                    </connectors>
                </pcbView>
            </views>
        </instance>
"""


def inst_blk(text, title):
    for ttl, a, b in SP.blocks_of(text):
        if ttl == title:
            return a, b, text[a:b]
    return None, None, None


def model_index(blk):
    return re.search(r'<instance\b[^>]*modelIndex="([^"]+)"', blk).group(1)


def pad_center(path, title, conn):
    parts, _ = PP.read_fzz(path)
    for p in parts:
        if p["title"] == title:
            q, _e, _b, _n = PP.part_pads(p)
            if conn not in q:
                raise SystemExit("✗ %s 没有 %s ✗" % (title, conn))
            return q[conn]["abs"]
    raise SystemExit("✗ 没有件 `%s` ✗" % title)


def resolve(text, path, spec):
    """⇒ (坐标(单位), 目标 dict) ✓ —— 目标 = `{kind, mi, cid, layer}` ✓"""
    if re.match(r"^-?[\d.]+,-?[\d.]+$", spec):
        x, y = [float(v) for v in spec.split(",")]
        return (x * 90.0 / 25.4, y * 90.0 / 25.4), None
    if ":" in spec:
        t, c = spec.split(":")
        _a, _b, blk = inst_blk(text, t)
        if blk is None:
            raise SystemExit("✗ 没有走线 `%s` ✗" % t)
        return None, {"kind": "wire", "title": t, "mi": model_index(blk), "cid": c,
                      "layer": "copper0trace"}
    t, c = spec.split(".")
    if "." not in spec:
        raise SystemExit("✗ 端点写法不认：`%s` ✗" % spec)
    _a, _b, blk = inst_blk(text, t)
    if blk is None:
        raise SystemExit("✗ 没有件 `%s` ✗" % t)
    return pad_center(path, t, c), {"kind": "pad", "title": t, "mi": model_index(blk),
                                    "cid": c, "layer": "copper0"}


def add_backref(text, tgt, mi_wire, cid_of_wire):
    """把「★目标 ★ 连着新线的一个脚」补进目标自己的段里 ✓"""
    a, b, blk = inst_blk(text, tgt["title"])
    lay = tgt["layer"]
    pat = re.compile(r'(<connector connectorId="%s" layer="%s">)(.*?)(</connector>)'
                     % (tgt["cid"], lay), re.S)
    m = pat.search(blk)
    if not m:
        raise SystemExit("✗ `%s` 里找不到 `<connector connectorId=\"%s\" layer=\"%s\">` ✗"
                         % (tgt["title"], tgt["cid"], lay))
    one = ('                                <connect connectorId="%s" modelIndex="%s" '
           'layer="copper0trace"/>\n' % (cid_of_wire, mi_wire))
    seg = m.group(2)
    if "<connects>" in seg:
        seg2 = seg.replace("</connects>", one + "                            </connects>", 1)
    else:
        seg2 = ("\n                            <connects>\n" + one +
                "                            </connects>\n                        ")
    new = m.group(1) + seg2 + m.group(3)
    return text[:a] + blk[:m.start()] + new + blk[m.end():] + text[b:]


def main(argv):
    in_path, out_path, prefix = argv[:3]
    pts = argv[3:]
    if len(pts) < 2:
        print(__doc__)
        return 2
    mils = next((a.split("=", 1)[1] for a in argv if a.startswith("--mils=")), "8")
    color = next((a.split("=", 1)[1] for a in argv if a.startswith("--color=")), "#f28a00")
    z = next((a.split("=", 1)[1] for a in argv if a.startswith("--z=")), "6.50054")

    zf = zipfile.ZipFile(in_path)
    fz = [n for n in zf.namelist() if n.endswith(".fz")][0]
    text = zf.read(fz).decode("utf-8")

    coords, tgts = [], []
    for sp in pts:
        xy, tg = resolve(text, in_path, sp)
        coords.append(xy)
        tgts.append(tg)
    # 裸点由**上一/下一段**补坐标 ✓
    for i, c in enumerate(coords):
        if c is None:
            raise SystemExit("✗ 第 %d 个点是走线端点 ⇒ 暂不支持（本用法里不需要 ✓）✗" % i)

    mi0 = max(int(m) for m in re.findall(r'\bmodelIndex="(\d+)"', text)) + 1
    nseg = len(coords) - 1
    segs = []
    for i in range(nseg):
        mi = mi0 + i
        title = "%s%d" % (prefix, i + 1)
        if "<title>%s</title>" % title in text:
            raise SystemExit("✗ 标题 `%s` 已存在 ✗" % title)
        # ★ A 端的「对方」：有目标就用目标 ✓；裸点 ⇒ **上一段的 connector1** ✓
        if tgts[i]:
            ac, ami, al = tgts[i]["cid"], tgts[i]["mi"], tgts[i]["layer"]
        else:
            if i == 0:
                raise SystemExit("✗ 折线的**起点**不能是裸点 ✗")
            ac, ami, al = "connector1", mi - 1, "copper0trace"
        # ★ B 端的「对方」：有目标就用目标 ✓；裸点 ⇒ **下一段的 connector0** ✓
        if tgts[i + 1]:
            bc, bmi, bl = tgts[i + 1]["cid"], tgts[i + 1]["mi"], tgts[i + 1]["layer"]
        else:
            if i == nseg - 1:
                raise SystemExit("✗ 折线的**终点**不能是裸点 ✗")
            bc, bmi, bl = "connector0", mi + 1, "copper0trace"
        segs.append((mi, title, coords[i], coords[i + 1], ac, ami, al, bc, bmi, bl,
                     tgts[i], tgts[i + 1]))

    blks, last = [], None
    for ttl, a, b in SP.blocks_of(text):
        if 'moduleIdRef="Wire' in text[a:b]:
            last = b
    if last is None:
        raise SystemExit("✗ 文件里一根 Wire 都没有 ⇒ 找不到插点 ✗")
    body = ""
    for (mi, title, pA, pB, ac, ami, al, bc, bmi, bl, _a_t, _b_t) in segs:
        body += "\n" + SEG.format(mi=mi, title=title, z=z,
                                  ax=PW.fmt(pA[0]), ay=PW.fmt(pA[1]),
                                  dx=PW.fmt(pB[0] - pA[0]), dy=PW.fmt(pB[1] - pA[1]),
                                  mils=mils, color=color,
                                  ac=ac, ami=ami, al=al, bc=bc, bmi=bmi, bl=bl).rstrip("\n")
    text2 = text[:last] + body + text[last:]

    # 回指 ✓（焊盘 / 已有走线 ✓；**裸点两侧的互指已经在 SEG 里写好了** ✓）
    for i, (mi, title, _pA, _pB, _ac, _ami, _al, _bc, _bmi, _bl, a_t, b_t) in enumerate(segs):
        if a_t is not None:
            text2 = add_backref(text2, a_t, mi, "connector0")
        if b_t is not None:
            text2 = add_backref(text2, b_t, mi, "connector1")

    try:
        ET.fromstring(text2)
    except ET.ParseError as e:
        raise SystemExit("✗ 改完不是合法 XML（%s）⇒ **不写文件** ✗" % e)
    n0 = len(re.findall(r"<instance\b", text))
    n1 = len(re.findall(r"<instance\b", text2))
    if n1 != n0 + len(segs):
        raise SystemExit("✗ `<instance` 计数 %d → %d（应 +%d）✗" % (n0, n1, len(segs)))
    zout = zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED)
    for it in zf.infolist():
        data = text2.encode("utf-8") if it.filename == fz else zf.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, date_time=it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zout.writestr(zi, data)
    zout.close()
    for (mi, title, pA, pB, *_r) in segs:
        print("   ✓ %s（mi=%d）(%.3f,%.3f)→(%.3f,%.3f) mm ｜ %.3f mm"
              % (title, mi, pA[0] * 25.4 / 90, pA[1] * 25.4 / 90,
                 pB[0] * 25.4 / 90, pB[1] * 25.4 / 90,
                 ((pB[0] - pA[0]) ** 2 + (pB[1] - pA[1]) ** 2) ** 0.5 * 25.4 / 90))
    print("   ✓ 写出 %s｜`<instance` %d → %d ✓｜XML 合法 ✓"
          % (os.path.basename(out_path), n0, n1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
