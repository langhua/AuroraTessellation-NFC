# -*- coding: utf-8 -*-
r"""★★ 把**每一版** `pixel-pcb-v*.fzz` 渲成图片 ✓ ⇒ 在 VS Code 里**右键两版比对** ✓
（2026-10-07 用户要的「步骤 1+2」✓）

用户想法原话 ✓：「在 vscode 里做一个功能，能看到你每次画图与之前版本的变化和比较。
Fritzing 没有这个功能，修改 Fritzing 又复杂了，在 vscode 里做，会不会容易些？」✓

为什么要转成**图片** ✗：`.fzz` 是 zip ✗ ⇒ VS Code 的「Compare Selected」对它只会显示
二进制差异 ✗（看不出线动了没有 ✓）。⇒ 先渲成 **png** ✓（★ VS Code 的图像比对**只认位图** ✓，
svg 不一定认 ✗）＋ 同时留 **svg** ✓（想看细节/缩放用 ✓）。

渲染**不另写一套几何** ✗：直接调**元件库**的 `tools/render_pcb.py` ✓ —— 它用
`pcb_check.collect()` ✓（= 校验器**同一个世界模型** ✓，AGENTS §13「只允许一个声音」✓）。

用法 ✓：
  py tools\render_revs.py v59 v69 v76          # 只渲这几版 ✓
  py tools\render_revs.py --last 6             # 最近 6 版 ✓
  py tools\render_revs.py --all                # 全部 ✓
  py tools\render_revs.py --all --px 16        # 放大一点 ✓
  py tools\render_revs.py --all --index-only   # 不重渲 ✓，只重建索引（图片都在时用 ✓）
输出 ✓：`hardware\pixel\diff\<版本>.png` ＋ `.svg` ＋ `diff\README.md`（索引＋比对方法 ✓）
★ `diff\` **不入库** ✓（79 版≈77 MB ✗，且一条命令能重生 ✓）—— 已写进 `hardware\pixel\.gitignore` ✓
"""
import os
import re
import sys

# ★★ 控制台是 **GBK** 时 ✗：本库到处是 `✓`/`✗` ⇒ `print` 直接 **UnicodeEncodeError 崩掉** ✗
#   （2026-10-07 实测踩到 ✓）⇒ 一进来就把 stdout **钉成 utf-8 + 容错** ✓（✗ 不是改信息 ✗）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
except Exception:                            # noqa: BLE001  老解释器没这方法 ⇒ 忽略 ✓
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)                     # hardware\pixel ✓


def _lib_tools():
    """找到元件库的 `tools` ✓（✗ 不写死绝对路径 ✗ —— 一路往上找 `fritzing-parts-langhua` ✓）。"""
    d = HERE
    for _ in range(6):
        d = os.path.dirname(d)
        cand = os.path.join(d, "fritzing-parts-langhua", "tools")
        if os.path.isfile(os.path.join(cand, "render_pcb.py")):
            return cand
    raise SystemExit("找不到元件库 tools\render_pcb.py ✗（fritzing-parts-langhua 不在上面几层里 ✗）")


def _vkey(name):
    """版本号排序键 ✓：`pixel-pcb-v67_byHand.fzz` ⇒ `(67, 1, 'byHand')` ✓（手工版排在同号之后 ✓）。

    ★ 坑 ✓（2026-10-07 实测踩到 ✗）：正则必须**先剥扩展名** ✗ ——
      写成对**文件名**匹配 `$` 时 ⇒ `.fzz` 挂在尾巴上 ⇒ **所有版本号都读成 0** ✗
      ⇒ 表现是「v59 找不到 ✗」而文件明明就在那儿 ✓。
    ★ 坑 2 ✓（同日第二个 ✗）：后缀**不一定有分隔符** ✗ —— 手边就有 `v9b` `v9d` ✗
      ⇒ 只认 `[-_]suf` 会把它们当成**版本 0** ✗ ⇒ 索引里排在最前面、**顺序全乱** ✗
      ⇒ 改成「`-v` 后面**第一个数**是号，**剩下的全算后缀**」✓。
    """
    stem = os.path.splitext(name)[0]
    m = re.match(r"^.*?-v(\d+)(.*)$", stem)
    if not m:
        return (0, 0, stem)
    suf = m.group(2).strip("_-")
    return (int(m.group(1)), 1 if suf else 0, suf)


def main(argv):
    px = 12.0
    out = os.path.join(PIX, "diff")
    want, last, allv, index_only = [], None, False, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--px" and i + 1 < len(argv):
            px = float(argv[i + 1]); i += 2; continue
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]; i += 2; continue
        if a == "--last" and i + 1 < len(argv):
            last = int(argv[i + 1]); i += 2; continue
        if a == "--all":
            allv = True; i += 1; continue
        if a == "--index-only":
            index_only = True; i += 1; continue
        want.append(a.lstrip("v")); i += 1

    have = sorted([f for f in os.listdir(PIX)
                   if re.match(r"^pixel-pcb-v\d+.*\.fzz$", f)], key=_vkey)
    if want:
        pick = []
        for w in want:
            hit = [f for f in have if _vkey(f)[0] == int(w)]
            if not hit:
                print("!! 找不到 v%s ✗（手边有：%s）" % (w, " ".join("v%d" % _vkey(f)[0] for f in have)))
                continue
            pick += hit
    elif last:
        pick = have[-last:]
    elif allv:
        pick = have
    else:
        print(__doc__)
        return 2

    sys.path.insert(0, _lib_tools())
    sys.path.insert(0, os.path.dirname(HERE))
    import render_pcb as R                                        # noqa: E402

    if not os.path.isdir(out):
        os.makedirs(out)
    rows = []
    for f in pick:
        stem = os.path.splitext(f)[0]
        svg = os.path.join(out, stem + ".svg")
        if not index_only:
            print("── %s ⇒ %s" % (f, os.path.basename(svg)))
            try:
                R.main([os.path.join(PIX, f), svg, "--px", str(px), "--png"])
            except Exception as e:                                # noqa: BLE001  ✗ 一版坏别拖垮全部 ✗
                print("   !! %s 渲染失败：%s" % (f, e))
                rows.append((stem, False))
                continue
        rows.append((stem, os.path.isfile(os.path.join(out, stem + ".png"))))

    # ★ 索引 ✓：VS Code 里打开它就能一版一版点着看 ✓；比对方法写在最上面 ✓
    md = ["# PCB 版本比对（自动生成 ✓ 别手改 ✗）", "",
          "渲染命令：`py tools\\render_revs.py --all`（几何来自元件库 `render_pcb.py` ✓ 与校验器同源 ✓）", "",
          "## 怎么看两版的差别（VS Code 原生 ✓，不用装插件 ✓）", "",
          "1. 资源管理器里**点一个** `<版本>.png`，**按住 Ctrl 点第二个** ⇒ 右键 ⇒ "
          "**Compare Selected / 比较选中的文件** ✓",
          "2. 图像比对是**并排 + 可拖动**的 ⇒ 两版对不上的地方一眼看得出 ✓",
          "3. 想放大看细节 ⇒ 切到同名 `.svg`（VS Code 能预览 svg ✓）或直接用浏览器打开 ✓",
          "", "| 版本 | png（比对用） | svg（看细节） |", "|---|---|---|"]
    for stem, ok in rows:
        md.append("| %s | %s | %s |" % (stem,
                                        "[png](%s.png)" % stem if ok else "（无 ✗ 没装 cairosvg）",
                                        "[svg](%s.svg)" % stem))
    md += ["", "★ **关键三版**（这一年半的来龙去脉 ✓）：",
           "- `v59` ＝ **诚实基线** ✓（布线声明的**完整**来源 ✓；底部状态栏那次对齐就是照它 ✓）",
           "- `v69` ＝ 曾经被我**削瘦**的那版 ✗（线被整条删掉 ⇒ 网组丢失 ⇒ 「布线完成」假象 ✗）",
           "- `v76` ＝ **当前交付** ✓（`7 中的 5 网络布线完成，2 个接插件仍然需要布线` ✓ 你截图核对过 ✓）",
           ""]
    open(os.path.join(out, "README.md"), "w", encoding="utf-8", newline="\n").write("\n".join(md))
    n_png = sum(1 for _, ok in rows if ok)
    print("\n✓ 完成：%d 版 ⇒ %d 个 png%s ＋ %d 个 svg ✓；索引 %s"
          % (len(rows), n_png, "" if n_png == len(rows) else "（**没有 cairosvg** ✗ 图像比对就用不了 ✗）",
             len(rows), os.path.join(out, "README.md")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
