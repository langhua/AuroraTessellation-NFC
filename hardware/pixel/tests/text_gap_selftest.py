# -*- coding: utf-8 -*-
r"""`text_gap_selftest`：第四十九轮「**文字 ↔ 被绘制对象 净距**」硬闸门的**验收自测** ✓

★ 两把尺子**都**要在场 ✓（否则就是"自证通过" ✗）：
  ① **判据本身**（共享实现 `tools/sch_textgap.py` ✓ —— 与生成器闸门 / 探针 ⑫ / 渲染器同一份 ✓）
     在**合成数据**上的口径 ✓（同库仓 `sch_textgap_selftest.py` 那一套的口径几条 ✓）；
  ② **交付件**（`pixel-pcb-v79.fzz` = **改前** ✓ ／ `pixel-pcb-v80.fzz` = **改后** ✓）上
     的**真实数字** ✓（改前 3 对 ✗ ⇒ 改后 0 对 ✓）—— 这就是用户截图那一处 `LED2` ✓。
★ 命名保留 `*_selftest.py` ✓（✗ 故意不叫 `test_*.py` ✗）；一行跑全部见 `tests\run_all.py` ✓。
★ 路径：库仓工具**只从 `toolpaths.py` 认** ✓（唯一实现 ✓），不写死机器路径 ✗。

用法：py -X utf8 tests\text_gap_selftest.py
"""
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)                  # hardware/pixel ✓
sys.path.insert(0, PIX)
import toolpaths                             # noqa: E402  —— 已把库仓 tools/ 放进 sys.path ✓
sys.path.insert(0, toolpaths.TOOLS)
import sch_textgap as TG                     # noqa: E402

BEFORE = os.path.join(PIX, "pixel-pcb-v79.fzz")
AFTER = os.path.join(PIX, "pixel-pcb-v80.fzz")

ok = True


def chk(name, cond, extra=""):
    global ok
    print("  %s %s %s" % ("✓" if cond else "✗", name, extra))
    if not cond:
        ok = False


def load(path):
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0])
                         .decode("utf-8"))
    packed = {n: z.read(n).decode("utf-8", "replace")
              for n in z.namelist() if n.endswith(".svg")}
    return root, packed


def main():
    print("== 文字 ↔ 对象 净距（第四十九轮）验收自测 ==")

    # ── ① 判据的口径（合成数据 ✓，与库仓那套同源 ✓）──
    chk("① 缺省净距 = 0.150 mm", abs(TG.DEFAULT_MM - 0.15) < 1e-12)
    chk("① 范围 = [0, 2.54] mm", TG.MIN_MM == 0.0 and abs(TG.MAX_MM - 2.54) < 1e-12)
    v, why = TG.clamp_mm(9.0)
    chk("① 越界**夹取 ＋ 给话**（不静默 ✗）", v == TG.MAX_MM and bool(why))
    chk("① 相交 ⇒ 净距 0", TG.box_dist((0, 0, 10, 10), (5, 5, 15, 15)) == 0.0)
    chk("① 对角 (3,4) ⇒ 5", abs(TG.box_dist((0, 0, 10, 10), (13, 14, 20, 20)) - 5.0) < 1e-9)

    # ── ② 交付件：改前 3 对 / 改后 0 对 ✓ ──
    if not (os.path.isfile(BEFORE) and os.path.isfile(AFTER)):
        chk("② 交付件在场（%s ／ %s）" % (os.path.basename(BEFORE),
                                     os.path.basename(AFTER)), False)
        return 1
    rb, pb = load(BEFORE)
    ra, pa = load(AFTER)
    badb, txb, obb, _gb = TG.check(rb, pb, TG.DEFAULT_MM)
    bada, txa, oba, ga = TG.check(ra, pa, TG.DEFAULT_MM)
    chk("② 改前（v79）**恰好 3 对** ✗（实测 %d）" % len(badb), len(badb) == 3)
    chk("② 改后（v80）**0 对** ✓（实测 %d）" % len(bada), len(bada) == 0)
    chk("② 覆盖度：11 文字 × 59 对象（扫了 %d × %d）" % (len(txa), len(oba)),
        len(txa) == 11 and len(oba) == 59)
    chk("② 判据单位：0.15 mm = 0.5315 单位（%.4f）" % ga, abs(ga - 0.531496) < 1e-5)

    # ── ③ 改前那三条**逐条点名**（用户截图那一处 ✓）──
    names = sorted("%s↔%s" % (t["name"], o["name"]) for t, o, _d, _i in badb)
    chk("③ 改前含 `LED2+WS2812B-1010 ↔ Ground2`（用户截图 ✓）",
        "LED2+WS2812B-1010↔Ground2" in names, str(names))
    chk("③ 改前含 `LED2+WS2812B-1010 ↔ Wire90015558`（接地符号那条引线 ✓）",
        "LED2+WS2812B-1010↔Wire90015558" in names)
    chk("③ 改前含 `D3+BAS70BRW ↔ Wire90014108`（0.05 单位 = 0.014 mm ✓）",
        "D3+BAS70BRW↔Wire90014108" in names)

    # ── ④ 改后：文字只被**挪**过（不是删 ✗），且挪动 ≤ 12 单位（≈ 二个车道 ✓）──
    def boxes(root, packed):
        t, _o = TG.items(root, packed)
        return {x["name"]: x["box"] for x in t}
    bb, ba = boxes(rb, pb), boxes(ra, pa)
    chk("④ 文字个数一字不差（改前 %d ／ 改后 %d）" % (len(bb), len(ba)), len(bb) == len(ba))
    moved = {k: (bb[k][0] - ba[k][0], bb[k][1] - ba[k][1]) for k in bb
             if abs(bb[k][0] - ba[k][0]) > 1e-6 or abs(bb[k][1] - ba[k][1]) > 1e-6}
    chk("④ 只挪了 2 个位号块（实测 %d：%s）" % (len(moved), ", ".join(sorted(moved))),
        len(moved) == 2 and "LED2+WS2812B-1010" in moved and "D3+BAS70BRW" in moved)
    chk("④ 位移都 ≤ 12 单位（≈ 3.4 mm ✓ —— 少移动优先 ✓）",
        all((dx * dx + dy * dy) ** 0.5 <= 12.0 for dx, dy in moved.values()),
        str({k: (round(v[0], 3), round(v[1], 3)) for k, v in moved.items()}))
    chk("④ LED2 的框**不再碰** Ground2（净距 %.4f ≥ %.4f）"
        % (TG.box_dist(ba["LED2+WS2812B-1010"],
                       next(o["box"] for o in oba
                            if o["kind"] == "接地符号" and o["name"] == "Ground2")), ga),
        TG.box_dist(ba["LED2+WS2812B-1010"],
                    next(o["box"] for o in oba
                         if o["kind"] == "接地符号" and o["name"] == "Ground2")) >= ga)

    # ── ⑤ 闸门**默认关**（不给 `--text-gap` ⇒ 旧行为逐字节相同 ✓）──
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gsw", os.path.join(PIX, "gen_schematic_wires.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    chk("⑤ 生成器里 `TEXT_GAP_ON` **默认 False** ✓（零副作用 ✓）", m.TEXT_GAP_ON is False)
    chk("⑤ 生成器里 `TEXT_GAP_MM` 缺省 = 0.15 ✓", abs(m.TEXT_GAP_MM - 0.15) < 1e-12)
    chk("⑤ `STUB_DIVE` 默认关 ✓（B 段那个实验不参与交付 ✓）", m.STUB_DIVE is False)

    # ── ⑥ 文字内容口径**一份实现**（`sch_text.fritzing_lines` ✓）──
    import sch_text as ST
    chk("⑥ `fritzing_lines` 在场（渲染器/生成器/探针共用 ✓）", callable(ST.fritzing_lines))

    print()
    if not ok:
        print("✗ **有不过** ✗")
        return 1
    print("✓ **全过** ✓（改前 3 对 ✗ ⇒ 改后 0 对 ✓ ｜ 文字一个没少 ✓ ｜ 只挪 2 处 ≤ 12 单位 ✓ ｜ "
          "闸门默认关 ✓）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
