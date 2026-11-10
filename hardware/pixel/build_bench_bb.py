# -*- coding: utf-8 -*-
r"""把台架补料（`R2/R3/R4/R5/D4/TP1/TP2/TP3/C3`）摆到面包板图里 ⇒ `pixel-breadboard105.fzz`

用法: py -3.13 -u build_bench_bb.py [--dry]

**做法**（2026-11-10 ✓，用户定"方案 B：跟最新网表一致 ＋ 加 A/B" ✓）
1. 以 `pixel-breadboard104.fzz` 为骨架 ✓（`C1`/`C2`/`R1`/`L1`/`D3`/`U1`/`LED2`/`J1`/`J2` **不动** ✓）；
2. 新件**属性与另两个视图**从 `pixel-pcb-v111.fzz` 的对应实例**照搬** ✓
   （那是 v0.1.3 的同一批件 ✓ ⇒ 不另造 ✓）；只**重算 `breadboardView`** ✓；
3. 摆位从 `PLAN` 表读 ✓（孔号 = `pin<列><行>` ✓）；插孔声明 = `bb_route4` 的输入 ✓；
   腿（`<leg>`）按"**落点 − 件基准**"算 ✓ ⇒ 引脚恰好落在孔心上 ✓
   （这条口径是从 v104 的 `R1` **反推并验证**过的：`loc + geometry + leg 末端` = 孔心 ✓）；
4. 导线**全部留给 `bb_route4`** 重布 ✓（它自己会删旧线 ✓；`--keep-deco` 保住图例色条 ✓）。

★ 只读两个输入 ✓；输出另写一个文件 ✓（不就地改 ✓）。
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

BASE = "pixel-breadboard104.fzz"
SRC = "pixel-pcb-v111.fzz"
OUT = "pixel-breadboard105.fzz"

ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0,
         "X": 171.0, "W": 180.0}
COL = 9.0

# ── 摆位方案 ✓（列 = 孔号里的数字 ✓；行 = 字母 ✓；均落在**空区**列 39–62 内 ✓）
#   ★ 电阻/二极管：两脚**同一行、隔 4 列**（= v0.1.3 件自带的脚距 36 单位 ✓）
#   ★ 电解：两脚**同一列、相邻两行**（同一半区 ✓，脚距 9 单位 ✓）
#   ★ 测试点：单脚，各占一个孔 ✓
PLAN = [
    ("R2", "pin40G", "pin44G"),
    ("R3", "pin46G", "pin50G"),
    ("R4", "pin52G", "pin56G"),
    ("R5", "pin58G", "pin62G"),
    # ★ `D4`（= `RC` 的钳位管）两脚：`connector0` = **阴极 = 5V** ✓、`connector1` = **阳极 = RC** ✓
    #   ★★ 实测踩到两次（2026-11-10 ✓，都是**布线器的硬闸门**抓住的 ✓）：
    #     ① `pin40D/44D`（右下角）⇒ 「`RC` 连不上」（2 块 ✗）；
    #     ② `pin28E/32E` ⇒ **短接** ✗：`pin32E` 与 `pin32A`（`J2.connector0` = 5V）
    #        **同一列的下半区 bus** ✓ ⇒ bus 同时有 5V 与 RC ⇒ 布线器**拒绝写文件** ✓。
    #        ⇒ 教训：bus 是**一列 5 个孔**（F..J ／ A..E 各一条 ✓），**不是一行** ✗
    #          —— "同一条 bus" 要按**列**看 ✓。
    #   ⇒ 现在放在**空列**上：`pin36C`（阳极/RC）+ `pin40C`（阴极/5V），两列都空 ✓。
    ("D4", "pin36C", "pin40C"),
    # ★ 电解两脚本来就**同排隔 1 列**（实测：局部 y 相同、x 差 9 单位 ✓）⇒ 横放、腿长 0 ✓
    ("C3", "pin45D", "pin46D"),
    # ★ `TP1/TP2/TP3` **不画** ✗：`NetLabel-Pad` 这个库件**根本没有面包板视图** ✗
    #   （AGENTS §14 记着这条 ✓）⇒ 台架上就用表笔/探针 ✓；
    #   `bb_probe` 会把它们记成「该件不在本视图 ⇒ 不适用」✓（v104 实测就是这样 ✓）。
]
NEW_MI0 = 90018001
# ★ 源草图里没有的件 ⇒ 用**同一个件**的实例克隆 ✓（同 moduleId ⇒ 脚型/属性名一致 ✓）
SRC_ALIAS = {"R5": "R2"}
# ★ 克隆后要改的属性值 ✓（`R5` = 100 Ω，与板上 `R3`/`R4` 同值 ✓）
PROP_OVERRIDE = {"R5": {"resistance": "100"}}


def hole_xy(hid):
    m = re.fullmatch(r"pin(\d+)([A-Z])", hid)
    return (float(m.group(1)) * COL, ROW_Y[m.group(2)])


def instances_text(text):
    return re.search(r"<instances>.*</instances>", text, re.S).group(0)


def get_instance(text, title):
    for m in re.finditer(r'<instance [^>]*>.*?</instance>', text, re.S):
        if "<title>%s</title>" % title in m.group(0):
            return m.group(0)
    return None


def bb_block(inst):
    if not inst:
        return None
    m = re.search(r"<breadboardView.*?</breadboardView>", inst, re.S)
    return m.group(0) if m else None


def conn_geoms(bb):
    """{connectorId: (x, y)} —— 件**局部**坐标 ✓（v111 的 `breadboardView` 没写 transform ⇒ 恒等 ✓）"""
    out = {}
    for m in re.finditer(r'<connector connectorId="([^"]+)"[^>]*>(.*?)</connector>', bb, re.S):
        g = re.search(r'<geometry x="([-\d.]+)" y="([-\d.]+)"', m.group(2))
        if g:
            out[m.group(1)] = (float(g.group(1)), float(g.group(2)))
    return out


def local_pins_from_svg(fzp, svg):
    """`NetLabel-Pad` / 电解这类**v111 里没有面包板视图**的件 ⇒ 从它自己的 svg 量引脚中心 ✓"""
    import xml.etree.ElementTree as ET2
    sys.path.insert(0, r"f:\git\fritzing-parts-langhua\tools")
    import part_box as PB
    root = ET2.parse(svg).getroot()
    k, (ox, oy) = PB.svg_k(root)
    els = {}
    for e in root.iter():
        eid = e.get("id") or ""
        if eid.startswith("connector"):
            els[eid] = e
    ft = ET2.parse(fzp).getroot()
    out = {}
    for c in ft.iter("connector"):
        cid = c.get("id")
        sid = None
        for p in c.iter("p"):
            if (p.get("layer") or "") == "breadboard" and p.get("svgId"):
                sid = p.get("svgId")
                break
        if not sid or sid not in els:
            continue
        e = els[sid]
        tag = e.tag.split("}")[-1]
        if tag == "rect":
            cx = float(e.get("x")) + float(e.get("width")) / 2.0
            cy = float(e.get("y")) + float(e.get("height")) / 2.0
        elif tag in ("circle", "ellipse"):
            cx, cy = float(e.get("cx")), float(e.get("cy"))
        elif tag == "line":
            cx = (float(e.get("x1")) + float(e.get("x2"))) / 2.0
            cy = (float(e.get("y1")) + float(e.get("y2"))) / 2.0
        else:
            nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", e.get("d") or "")]
            if len(nums) < 2:
                continue
            cx, cy = sum(nums[0::2]) / len(nums[0::2]), sum(nums[1::2]) / len(nums[1::2])
        out[cid] = ((cx - ox) * k, (cy - oy) * k)
    return out


CORE = r"C:\Users\shi.jinghai-honor\AppData\Local\Programs\Fritzing\fritzing-parts"
CORE_SVG = CORE + r"\svg\core\breadboard"
ZX = CORE + r"\core"
#   电解：核心 `capacitor_electrolytic_medium.fzp`（默认 100 µF ✓）
ELEC_FZP = ZX + r"\capacitor_electrolytic_medium.fzp"
ELEC_SVG = CORE_SVG + r"\electrolytic_capacitor_220uF_35v_leg.svg"
NETPAD_FZP = r"C:\Users\shi.jinghai-honor\Documents\Fritzing\parts\user\NetLabel-Pad_1.fzp"
NETPAD_SVG = r"C:\Users\shi.jinghai-honor\Documents\Fritzing\parts\svg\user\breadboard\NetLabel-Pad_breadboard.svg"


def build_new_bb(inst_src, pins, holes, mi, board_mi, z=2.50196):
    """用源实例的 connector 局部坐标 + 目标孔 ⇒ 新的 `breadboardView` 文本 ✓"""
    bb = bb_block(inst_src)
    base = conn_geoms(bb) if bb else pins
    ids = sorted(base, key=lambda s: int(re.sub(r"\D", "", s)))
    H = [hole_xy(h) for h in holes if h]
    loc = (H[0][0] - base[ids[0]][0], H[0][1] - base[ids[0]][1])
    parts = []
    for i, cid in enumerate(ids):
        gx, gy = base[cid]
        if i < len(H):
            le = (H[i][0] - loc[0] - gx, H[i][1] - loc[1] - gy)
        else:
            le = (0.0, 0.0)
        conn = (
            '                    <connector connectorId="%s" layer="breadboard">\n'
            '                        <geometry x="%s" y="%s"/>\n'
            '                        <leg>\n'
            '                            <point x="0" y="0"/>\n'
            '                            <bezier/>\n'
            '                            <point x="%s" y="%s"/>\n'
            '                            <bezier/>\n'
            '                        </leg>\n'
            '                        <connects>\n'
            '                            <connect connectorId="%s" modelIndex="%s" layer="breadboardbreadboard"/>\n'
            '                        </connects>\n'
            '                    </connector>\n'
            % (cid, num(gx), num(gy), num(le[0]), num(le[1]), holes[i], board_mi))
        parts.append(conn)
    return (
        '                <breadboardView layer="breadboard">\n'
        '                    <geometry z="%s" x="%s" y="%s"/>\n'
        '                    <connectors>\n%s'
        '                    </connectors>\n'
        '                </breadboardView>' % (num(z), num(loc[0]), num(loc[1]), "".join(parts)))


def num(v):
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def main(argv):
    dry = "--dry" in argv
    zb = zipfile.ZipFile(BASE)
    name = [n for n in zb.namelist() if n.endswith(".fz")][0]
    btext = zb.read(name).decode("utf-8")
    items = [(i, zb.read(i.filename)) for i in zb.infolist()]

    zs = zipfile.ZipFile(SRC)
    sname = [n for n in zs.namelist() if n.endswith(".fz")][0]
    stext = zs.read(sname).decode("utf-8")

    board_mi = re.search(r'<instance [^>]*moduleIdRef="[^"]*[Bb]readboard[^"]*"[^>]*modelIndex="(\d+)"',
                         btext).group(1) if re.search(
        r'<instance [^>]*moduleIdRef="[^"]*[Bb]readboard[^"]*"[^>]*modelIndex="(\d+)"', btext) else None
    if board_mi is None:
        for m in re.finditer(r'<instance ([^>]*)>', btext):
            a = m.group(1)
            if "Breadboard" in a and "moduleIdRef" in a:
                board_mi = re.search(r'modelIndex="([^"]+)"', a).group(1)
                break
    print("板件 modelIndex =", board_mi)

    add = []
    for i, (ttl, h0, h1) in enumerate(PLAN):
        mi = NEW_MI0 + i
        holes = [h0] + ([h1] if h1 else [])
        pins = None
        if ttl == "C3":
            inst = ('<instance moduleIdRef="MediumElectrolyticCapacitorModuleID" modelIndex="%d" '
                    'path="%s">\n'
                    '                <property name="capacitance" value="100 µF"/>\n'
                    '                <property name="voltage" value="10V"/>\n'
                    '                <title>C3</title>\n'
                    '                <views>\n%%s\n                </views>\n'
                    '            </instance>' % (mi, ELEC_FZP.replace("\\", "/")))
            pins = local_pins_from_svg(ELEC_FZP, ELEC_SVG)
            bb = build_new_bb(None, pins, holes, mi, board_mi)
        elif ttl.startswith("TP"):
            inst = ('<instance moduleIdRef="NetLabel-Pad" modelIndex="%d" path="%s">\n'
                    '                <title>%s</title>\n'
                    '                <views>\n%%s\n                </views>\n'
                    '            </instance>' % (mi, NETPAD_FZP.replace("\\", "/"), ttl))
            pins = local_pins_from_svg(NETPAD_FZP, NETPAD_SVG)
            bb = build_new_bb(None, pins, holes, mi, board_mi)
        else:
            tmpl = SRC_ALIAS.get(ttl, ttl)
            src = get_instance(stext, tmpl)
            if src is None:
                raise SystemExit("源草图里没有 %s ✗" % tmpl)
            src = re.sub(r'modelIndex="\d+"', 'modelIndex="%d"' % mi, src, count=1)
            if tmpl != ttl:
                src = src.replace("<title>%s</title>" % tmpl, "<title>%s</title>" % ttl, 1)
            for pname, pval in PROP_OVERRIDE.get(ttl, {}).items():
                src, n = re.subn(r'(<property name="%s" value=")[^"]*(")' % pname,
                                 r"\g<1>%s\g<2>" % pval, src)
                if n != 1:
                    raise SystemExit("%s 的属性 %s 替换了 %d 次 ✗" % (ttl, pname, n))
            bb_old = bb_block(src)
            bb = build_new_bb(src, None, holes, mi, board_mi)
            src = src.replace(bb_old, "__BB__")
            inst = src
        inst_txt = inst % bb if "%s" in inst else inst.replace("__BB__", bb)
        add.append(inst_txt)
        print("  + %-4s %-9s %-9s mi=%d  脚=%s" % (ttl, h0, h1 or "-", mi,
                                                   {k: (round(v[0], 3), round(v[1], 3))
                                                    for k, v in (pins or conn_geoms(bb)).items()}))

    # 插到 `<instances>` 末尾（导线后面放零件也不影响 ✓ Fritzing 按 modelIndex 认 ✓）
    host_end = btext.rindex("</instances>")
    new_text = btext[:host_end] + "".join("            " + a + "\n" for a in add) + btext[host_end:]

    # 自检：XML 能解析、新件数对得上 ✓
    r = ET.fromstring(new_text)
    ttls = [(e.findtext("title") or "").strip() for e in r.iter("instance")]
    for ttl, _h0, _h1 in PLAN:
        assert ttl in ttls, "%s 没进去 ✗" % ttl
    print("实例总数 %d（原 %d ＋ 新 %d）✓" % (len(ttls), btext.count("<instance "), len(PLAN)))
    if dry:
        print("（--dry ⇒ 不写文件 ✓）")
        return 0

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == name:
                data = new_text.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    print("✓ 写出 %s" % OUT)
    return 0


sys.exit(main(sys.argv[1:]))
