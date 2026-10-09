# -*- coding: utf-8 -*-
r"""net_group_check：**Fritzing 眼里的网表**闸门 ✓ —— "每个视图里每张网都成型了吗" ✓

用法 ✓：`py -X utf8 tools\net_group_check.py <a.fzz> [<b.fzz> …] [--nets=pixel_nets.py]`
退出码 ✓：0 = 成型 ✓；1 = 有问题 ✗。

## 它查什么（**与 Fritzing 同源同语义** ✓，判据逐条可核 ✓）

  · **D** `EXPECT` 的脚在 PCB 视图里**必须有连接器项** ✓
    （少一只 ⇒ Fritzing 眼里这张网变小了 ⇒ 状态栏谎报「布线完成」✗ —— v71/v74 那一类 ✓）；
  · **A** 每张网的脚在 PCB 视图里**必须连成一块铜** ✓（碎成 N 块 ⇒ 还差 N−1 条没布 ✗）；
  · **B** 不同网**不许被并成一张** ✗（= 短接 ✗；2026-10-10 的 v81 就是这条 ✓）；
  · **C** 每张网在 PCB 视图里至少 **2** 个焊盘 ✓（`=1` ⇒ Fritzing 当单脚网丢掉 ✗
    `utils/graphutils.cpp:502` ✓）。

★ 本文件**只做入口** ✗ —— 口径的唯一实现在 `tools\pcb_rats_probe.py` 的 `check()` ✓
（两把尺子同源 ✓，✗ 不抄第二份 ✗）。那里的表头写着全部源码出处 ✓
（`mainwindow.cpp:2298` ✓ / `sketchwidget.cpp:7013` ✓ / `graphutils.cpp:447` ✓ /
`connectoritem.cpp:1340`、`1413`、`1972` ✓ / `itembase.cpp:559` ✓）。

## ★★ 2026-10-10 **重标定** ✗⇒✓（原因与证据都在这里 ✓，不是"换尺子凑答案" ✗）

旧判据 ✗：把**所有视图**的 `<connect>` 并成一张图 ✓（节点 = `(mi, connectorId)` ✓，✗ 不带视图 ✗）
⇒ 再数"块里的元件脚个数 ≥ 3" ✓ —— 它**只对"带跨视图 glue 的文件"成立** ✗。实测两发反例 ✓：

| 文件 | 用户实测 | 旧判据 | 新判据 |
|---|---|---|---|
| `pixel-pcb-v68.fzz` ✓ | **三视图都正确** ✓（2026-10-05 用户读的 ✓） | ✗ 9 处"网不存在" ✗ | ✓ exit 0 ✓ |
| `pixel-pcb-v81.fzz` ✗ | PCB 报「**2 个连接仍然需要布线**」✗ | ✓ exit 0 ✗ | ✗ 4 处（2 张网被并 ✗） |

病根 ✗：`ItemBase::findConnectorItemWithSharedID()` 返回 `connector->connectorItem(m_viewID)` ✓
（`items/itembase.cpp:559` ✓）⇒ `<connect>` **只在"当前视图"里解析** ✗ ⇒ 面包板那些
`layer="breadboardbreadboard"` 的记录**只在 PCB 视图里生效** ✗、它们把网**并起来** ✗
（而**不是**把网撑到 ≥3 ✗）⇒ **旧判据奖励了那个 bug** ✗（有病的 v81 过 ✓、正确的 v68 挂 ✗）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PIX)
import pcb_rats_probe as PR                                  # noqa: E402


def parse(path):
    """★ 只读入口 ✓（旧版是"按缩进配对切实例" ✓；现在直接用探针那份 ✓，一份实现 ✓）"""
    text, name = PR.PW.read(path)
    return PR.load_insts(text), name


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opt = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if not args:
        print(__doc__)
        return 2
    nets = opt.get("nets", os.path.join(PIX, "pixel_nets.py"))
    bad = 0
    for path in args:
        probs, notes, info = PR.check(path, nets)
        print("== %s（包内 %s）==" % (info["name"], info["inner"]))
        for n in notes:
            print("   · %s" % n)
        for what, who in info["glue"]:
            print("   ⚠ 跨视图 glue ✗：%s 把 %s 牵在一起" % (what, "、".join(who)))
        for r in info["nets"]:
            net = "、".join(r["names"]) or "（不在网表里）"
            if r["K"]:
                print("   ✗ `%-9s`：%d 只脚散在 **%d 块**铜里 ✗ ⇒ Fritzing 会画鼠线 ✗"
                      % (net, r["pads"], r["pieces"]))
            else:
                print("   ✓ `%-9s`：%d 只脚都在一块铜里 ✓" % (net, r["pads"]))
        mine = [p for p in probs if p[:1] in "ABCD"]
        for p in mine:
            print("   ✗ %s" % p)
        print("   ⇒ %s" % ("✓ 全过：Fritzing 眼里的网表与 `pixel_nets.py` 一致 ✓"
                           if not mine else
                           "✗ %d 处：Fritzing 眼里的网表与 `pixel_nets.py` 不一致 ✗" % len(mine)))
        bad += len(mine)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
