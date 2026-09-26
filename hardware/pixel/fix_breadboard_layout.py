# -*- coding: utf-8 -*-
r"""面包板**布局修正**（只做用户点名批准的那几处 ✓、幂等 ✓、可核对 ✓）

每一处 = 「把某个元件的某只脚从 A 孔挪到 B 孔」✓，一次改三样：
  ① 元件侧各视图（面包板 / PCB / 原理图 ✓）里指向 A 孔的连接 → B 孔 ✓；
  ② 面包板（modelIndex 5785 ✓）各视图里 A 孔上那条"接本元件"的记录 → B 孔 ✓
     （B 孔原本没有记录就**按需新建** ✓）；
  ③ 面包板视图里那条**腿**（`<leg>`）的末端按矩阵反解平移 ✓（`Δ局部 = M⁻¹·Δsketch` ✓）。

已批准的两处（2026-09-26 用户定 ✓）：
  A) `R1.connector1`：`pin21G` → `pin22G`
     —— 原位置与 `C1` 的 GND 脚(`21F`)同在 bus21 ✗ ⇒ 板上 **GND 与 RC 短接** ⇒ **C1 被旁路** ✗。
        22 列是 RC 那一列（`22F` = C1 的 RC 脚 ✓）⇒ 挪过去就分开 ✓。
  B) `C2` 两只脚**对调上下轨行**（`30Z`→`30Y`、`29Y`→`29Z`）
     —— 板子自己的 svg 上：**第一行(Z/X) 印蓝 = 负极 ✓、第二行(Y/W) 印红 = 正极 ✓**
        （实测：Z 上方的线 `#0000FF`、Y 下方的线 `#FF0000` ✓）
        ⇒ `5V` 该接**第二行**、`GND` 该接**第一行** ✓（用户 2026-09-26 ✓），原来正好接反 ✗。

幂等 ✓：已经在目标孔 ⇒ 跳过 ✓；两个孔都不是（用户自己挪过）⇒ **报出来、不动手** ✗。

用法：py -3.13 fix_breadboard_layout.py <输入.fzz> <输出.fzz>
"""
import copy
import sys
import zipfile
import xml.etree.ElementTree as ET

FIXES = [
    ("R1", "connector1", "pin21G", "pin22G", "解 GND/RC 短接（原本同在 bus21 ✗）"),
    ("C2", "connector0", "pin30Z", "pin30Y", "5V 改接**第二行** Y（板子印红 ✓）"),
    ("C2", "connector1", "pin29Y", "pin29Z", "GND 改接**第一行** Z（板子印蓝 ✓）"),
]


def tag(e):
    return e.tag.split("}")[-1]


def child(e, n):
    for c in e:
        if tag(c) == n:
            return c
    return None


def view_list(inst):
    vw = child(inst, "views")
    return [c for c in (vw if vw is not None else [])]


def find_conn(view, cid):
    box = child(view, "connectors")
    for c in (box if box is not None else []):
        if tag(c) == "connector" and c.get("connectorId") == cid:
            return c
    return None


def tf_of(el):
    """<transform m11…m32> → 2×3 矩阵 ✓（没有 ⇒ 单位阵 ✓）"""
    t = child(el, "transform")
    if t is None:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    g = lambda k, d: float(t.get(k) or d)            # noqa: E731
    return (g("m11", 1), g("m12", 0), g("m21", 0), g("m22", 1), g("m31", 0), g("m32", 0))


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def move_sketch_in_local(m, dx, dy):
    """把 sketch 里的位移 (dx,dy) 换成**局部**位移（解 M·Δlocal = Δ ✓）"""
    a, b, c, d = m[0], m[1], m[2], m[3]
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise SystemExit("✗ 变换不可逆 ✗")
    return ((d * dx - c * dy) / det, (-b * dx + a * dy) / det)


def main(argv):
    src, out = argv[0], argv[1]
    z = zipfile.ZipFile(src)
    name = [n for n in z.namelist() if n.endswith(".fz")][0]
    sroot = ET.fromstring(z.read(name))
    board = next(e for e in sroot.iter("instance")
                 if "breadboard" in (e.get("moduleIdRef") or "").lower()
                 and not (e.get("moduleIdRef") or "").startswith("Wire"))
    bmi = board.get("modelIndex")

    for ref, cid, old, new, why in FIXES:
        inst = next((e for e in sroot.iter("instance")
                     if (e.findtext("title") or "").strip() == ref), None)
        if inst is None:
            raise SystemExit("✗ 没找到位号 %s ✗" % ref)
        bb = next((v for v in view_list(inst) if tag(v) == "breadboardView"), None)
        con = find_conn(bb, cid) if bb is not None else None
        if con is None:
            raise SystemExit("✗ %s 的面包板视图里没有 %s ✗" % (ref, cid))
        lb = child(con, "connects")
        cur = [c.get("connectorId") for c in (lb if lb is not None else [])
               if tag(c) == "connect" and c.get("modelIndex") == bmi]
        if cur == [new]:
            print("✓ %s.%s 已经在 %s ⇒ 跳过（幂等 ✓）" % (ref, cid, new))
            continue
        if cur != [old]:
            raise SystemExit("✗ %s.%s 接的是 %s，不是 %s ⇒ 用户自己动过 ⇒ 我不动 ✗"
                             % (ref, cid, cur or "（没接孔）", old))
        # 目标孔在 sketch 里的位置：从**板子**两个孔的坐标差算 ✓（都在同一列/行 ✓）
        rmi = inst.get("modelIndex")
        # ① 元件侧：各视图里 old → new ✓
        n1 = 0
        for v in view_list(inst):
            for cs in v.iter():
                if tag(cs) == "connect" and cs.get("connectorId") == old \
                        and cs.get("modelIndex") == bmi:
                    cs.set("connectorId", new)
                    n1 += 1
        # ② 板子侧：old 上那条"接本元件"的记录搬到 new ✓（没有就新建 ✓）
        n2 = 0
        for v in view_list(board):
            oc = find_conn(v, old)
            if oc is None:
                continue
            box = child(oc, "connects")
            moved = [c for c in list(box if box is not None else [])
                     if tag(c) == "connect" and c.get("connectorId") == cid
                     and c.get("modelIndex") == rmi]
            if not moved:
                continue
            nc = find_conn(v, new)
            if nc is None:
                nc = ET.Element("connector", {"connectorId": new,
                                              "layer": oc.get("layer") or "breadboardbreadboard"})
                ET.SubElement(nc, "geometry", {"x": "0", "y": "0"})
                ET.SubElement(nc, "connects")
                child(v, "connectors").append(nc)
                print("       （视图 %s：%s 原本没记录 ⇒ 新建 ✓）" % (tag(v), new))
            nb = child(nc, "connects")
            if nb is None:
                nb = ET.SubElement(nc, "connects")
            for c in moved:
                box.remove(c)
                nb.append(copy.deepcopy(c))
                n2 += 1
        # ③ 腿末端平移到新孔 ✓（只动面包板视图 ✓）
        g = child(bb, "geometry")
        m = tf_of(g)
        dx, dy = hole_delta(old, new)
        dl = move_sketch_in_local(m, dx, dy)
        n3 = 0
        lg = child(con, "leg")
        if lg is not None:
            ps = [p for p in lg if tag(p) == "point"]
            if ps:
                ps[-1].set("x", "%.6g" % (float(ps[-1].get("x") or 0) + dl[0]))
                ps[-1].set("y", "%.6g" % (float(ps[-1].get("y") or 0) + dl[1]))
                n3 = 1
        if not (n1 and n2):
            raise SystemExit("✗ %s.%s 该改的没找齐 ⇒ 不写文件 ✗" % (ref, cid))
        print("✓ %s.%s: %s → %s（%s）｜元件侧 %d 处、板子侧 %d 条、腿 %d 处 ✓"
              % (ref, cid, old, new, why, n1, n2, n3))

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n == name else z.read(n))
    print("写入: %s" % out)
    return 0


ROW_Y = {"Z": 9.0, "Y": 18.0, "J": 45.0, "I": 54.0, "H": 63.0, "G": 72.0, "F": 81.0,
         "E": 108.0, "D": 117.0, "C": 126.0, "B": 135.0, "A": 144.0, "X": 171.0, "W": 180.0}
COL_PITCH = 9.0                             # 一个列距 = 2.54mm = 9 sketch 单位 ✓


def hole_delta(old, new):
    """两个孔 id 的 sketch 位移 ✓（数字=列 ✓ 字母=行 ✓）

    ★ 行**不是**字母序 ✗：板子自上而下是 Z Y J I H G F E D C B A X W ✓
      （实测：局部 y × 1.25 = sketch y ✓ ⇒ Z=9、Y=18、J=45…F=81、E=108…A=144、X=171、W=180 ✓）
    """
    import re
    mo = re.fullmatch(r"pin(\d+)([A-Z])", old)
    mn = re.fullmatch(r"pin(\d+)([A-Z])", new)
    if not (mo and mn):
        raise SystemExit("✗ 孔 id 认不出来: %s / %s ✗" % (old, new))
    for r in (mo.group(2), mn.group(2)):
        if r not in ROW_Y:
            raise SystemExit("✗ 行字母 %s 不在表里 ✗" % r)
    dx = (int(mn.group(1)) - int(mo.group(1))) * COL_PITCH
    dy = ROW_Y[mn.group(2)] - ROW_Y[mo.group(2)]
    return (dx, dy)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
