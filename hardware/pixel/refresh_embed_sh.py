# -*- coding: utf-8 -*-
r"""把草图里**内嵌**的 `SH-1.0-3P-V` pcb svg 换成库仓里的**修好版** ✓

用法: py -3.13 -u refresh_embed_sh.py <in.fzz> <out.fzz>

**为什么**
- Fritzing 的**图层归属按 svg 的组 id 认** ✓（`.fzp` 只声明"这个视图有哪些层"✗）；
  丝印组若嵌在 `<g id="copper1">` 里 ⇒ 那几条丝印线**被当铜**✗ ⇒
  ① 界面上画成**铜色**（用户报「丝印为啥是铜色的」✓）；
  ② 出 Gerber 时**当铜导出**✗（2026-10-10 库仓 `00df811` 已修库里的那份 ✓，
     但**草图内嵌的是修之前的老副本** ✗ ⇒ 板上 J1/J2 还是坏样子 ✗）。
- 只换这**一个条目** ✗：几何／焊盘／id 一字不动 ✓（库版与老版的唯一差别就是那一层嵌套 ✓，
  已用 `difflib` 逐行核过 ✓）；其余条目**原样字节**拷回去 ✓。

★ 换完必须：
  ① 再扫一遍「丝印嵌在铜组里」= 0 ✓；
  ② 内嵌那份与库仓那份**逐字节相同**（按 LF 归一化 ✓）；
  ③ 跑 `pcb_check --nets` 复验连通 ✓；
  ④ 把库仓那份**部署**到 Fritzing MINE（`parts/svg/user/pcb/` ✓）——
     否则下次从元件箱拖出来的还是坏的那份 ✗。
"""
import sys
import zipfile

LIB = r"f:\git\fritzing-parts-langhua\svg\SH-1.0-3P-V\svg.pcb.SH-1.0-3P-V_pcb.svg"
ENTRY = "svg.pcb.SH-1.0-3P-V_pcb.svg"


def nested_silk(text):
    """返回「嵌在铜组里的丝印组 id」列表 ✓（空 = 干净 ✓）"""
    import xml.etree.ElementTree as ET
    bad = []

    def walk(e, inside):
        for ch in list(e):
            nid = ch.get("id") or ""
            if inside and nid.startswith("silkscreen"):
                bad.append(nid)
            walk(ch, inside or nid in ("copper0", "copper1"))

    walk(ET.fromstring(text), False)
    return bad


def main(argv):
    src, out = argv[0], argv[1]
    fixed = open(LIB, encoding="utf-8").read().replace("\r\n", "\n")

    zin = zipfile.ZipFile(src)
    items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    n_hit = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info, data in items:
            if info.filename == ENTRY:
                assert nested_silk(fixed) == [], "库版自己还嵌着丝印 ✗"
                data = fixed.encode("utf-8")
                n_hit += 1
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zo.writestr(zi, data)
    if n_hit != 1:
        raise SystemExit("要换的条目命中 %d 次 ✗（应为 1）" % n_hit)

    # ---- 自检（在**写出的文件**上做，不是在自己脑内做 ✓）----
    zchk = zipfile.ZipFile(out)
    names_new = zchk.namelist()
    names_old = [i.filename for i, _ in items]
    assert names_new == names_old, "条目清单/顺序变了 ✗"
    diff = [n for n in names_new if zchk.read(n) != dict((i.filename, d) for i, d in items)[n]]
    print("条目 %d 个；内容有变化的条目 = %s ✓" % (len(names_new), diff))
    assert diff == [ENTRY], "变化的条目不止它 ✗"
    got = zchk.read(ENTRY).decode("utf-8").replace("\r\n", "\n")
    print("内嵌那份 == 库仓那份：%s ✓" % (got == fixed))
    print("内嵌那份里「丝印嵌在铜组」= %d ✓" % len(nested_silk(got)))
    print("✓ 写出 %s（%d 条目）" % (out, len(names_new)))


main(sys.argv[1:3])
