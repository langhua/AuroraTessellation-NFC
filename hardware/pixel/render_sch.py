# -*- coding: utf-8 -*-
r"""把我的**原理图**渲染成 PNG ✓（"看得见" ✓ —— 本机 Fritzing 命令行导出是坏的 ✗）

══ 摆放模型（2026-09-27 **机验钉死** ✓，证据见 `--verify-export`）══

    sketch = geometry.(x,y) + M · ( k · (局部用户坐标 − viewBox原点) )

  · `M` = `<geometry>/<transform m11…m32>` ✓（**没有就是单位阵** ✓ —— 注意它是**子元素** ✗
    不是属性 ✗，我为此白查了一轮 ✓）；旋转（如 C1/C2 的 180°）就写在这里 ✓
    —— 直接调 `part_box.tf_of` ✓（**与算本体包围盒同一套数学** ✓，不另写 ✗）。
  · `k` = 声明物理尺寸 / viewBox宽 × **3.5433** ✓ —— ★★ **1mm = 3.5433 sketch 单位（1/90in）** ✓✓
    ⇒ **原理图与面包板同一套单位** ✓（`render_bb.py` 的 `SK` 一致 ✓）。

  ★ 我在这上面**错过一次** ✗，记下来别再犯 ✗：
    把我自己导出的 `pixel-schematic_图示.svg` 的 `viewBox 371.41 / 5.15847in = 72` ✗
    当成"原理图 1 单位 = 1/72in" ✗ —— 那是**导出文件自己的**单位 ✓（导出把 sketch ×0.8 出图 ✓，
    72/90 = 0.8 ✓）。**判据**（三条独立证据，逐位相符 ✓）：
      ① 导线 `Wire90012727` 起点 (0,−123.269) 就是 `J1` 的 pin0 ✓ ⇒ pin0 距原点 9.106 单位
         ÷ 局部 2.57mm = **3.5433 单位/mm** ✓（< 1/72in 的 2.83465 ✗）；
      ② 导出里零件组平移 = **0.8×sketch + 常数** ✓（9 件全对 ✓）；
      ③ 导线线宽 `mils 9.7222` ⇒ `×90/1000 = 0.875` 单位 ✓ ⇒ 导出里 `×0.8 = 0.699998` ✓✓。

  · **连接点 = `connectorNterminal`** ✓（**不是** pin 线中点 ✗ —— 对 pin 中点会差 12.8 单位 ✗）。
  · 图层名**照 fzp 的 `schematicView/layers/layer@layerId` 取** ✓（不写死 `schematic` ✗：
    `breadboard2.fzp` 的 schematicView 指向 `breadboardbreadboard` ✗）。
  · **面包板本体不画** ✓（Fritzing 自己也不画 ✓，导出可证 ✓：10 个零件组里没有它 ✓）。
  · **BOM 属性文本**：位号行 = instance `title` ✓；后续行 = fzp 里 `showInLabel="yes"` 的字段 ✓
    （导出实测：`C1`+`16V` ✓、`U3`+`BAS70BRW` ✓）。位置 = `titleGeometry` ✓、DroidSans 5 ✓ 黑 ✓。

══ 用法 ══

    py -3.13 render_sch.py <sketch.fzz> <out.png> [<px宽>]
    py -3.13 render_sch.py <sketch.fzz> <out.png> --view schematicView
    py -3.13 render_sch.py <sketch.fzz> out.png --verify-export <Fritzing导出的.svg>   # ★ 独立核对 ✓

★ **不许自证** ✓：本渲染器只是"眼睛" ✓；它的**对外结论**（"画得对"）必须由
  `--verify-export`（拿 Fritzing 自己的导出当尺子 ✓）或**用户的眼睛**给出 ✓。
"""
import collections
import html
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import toolpaths                                                  # noqa: E402
import part_box as PB                                             # noqa: E402
import sch_text as ST                                            # ★ 字宽表（唯一实现 ✓）
import sch_geom as SG                                            # ★ 几何判据（含斜线 ✓，唯一实现 ✓）
import sch_net                                                   # ★ 网标签规则（唯一实现 ✓，2026-09-29 ✓）
import sch_box as SB                                             # ★ “本体盒”唯一实现 ✓

# ★★ 下面这段常量与小工具（`UMM/HDR/ATTR_RE/tag/num/enum/attrs/inner/head_of/
#   viewbox_of/scale_of/layer_of/to_sketch`）**已全部搬到 `sch_box.py`** ✓
#   （2026-09-27 ✓ —— 因为“本体盒”原来在这里和布线器里**各算一套** ✗，实测同一件 `L1`
#    两边差 **0.43 单位** ✗ ⇒ 布线器的硬闸门物理上看不见判据报的那一段 ✗✗）。
#   ⇒ 这里只 import ✓，**不再本地定义** ✗（本地定义会盖掉共享实现 ✗ = 又是两套尺子 ✗）。
from sch_box import (tag, num, enum, attrs, inner, head_of,      # noqa: E402
                     viewbox_of, scale_of, layer_of, to_sketch, UMM, SK_U_PER_MM)
# ★★ `px` = **1/90 in**（= 0.8 × 1/72 ✓）—— 2026-09-27 **实测**定的 ✓，不是查文档 ✗：
#   把 v6 的导出与我的渲染逐件比"**同一零件内两个脚的向量**" ✓（这个量**不需要任何标定** ✓）
#   ⇒ 只有 `LED2`（`width="48px"`）与 `D3`（`width="66px"`）对不上 ✗，比值恰好 **0.64 / 0.8 = 0.8** ✓
#   ⇒ 我把 px 当 1/72in 算 ✗，Fritzing 按 1/90in 算 ✓（`1.25 × 0.8 = 1.0` ✓）。
#   后果就是用户截图里那两处"线没接到脚上" ✗（误差 ~2.5mm ✓）。
#   注：`pt` 仍是 1/72in ✓（只有 px 不同 ✓）。
UMM_MOVED_NOTE = True      # ★ 常量与小工具已搬去 `sch_box.py` ✓（见上面 import 那段 ✓）
#   ✗ 搬家时多动手碰坏过一次 ✓：`layer_of` 的尾巴被切掉了一段 ✗（它现在整段在 `sch_box.py` ✓）
#   ⇒ 教训（本仓旧规矩 ✓）：**一次只改一处** ✓ + 改完**读回** ✓ —— 这次是靠读回抓到的 ✓。


def anchors(txt_root):
    """零件 svg 里每个脚的**连接点**（根用户单位 ✓，走完祖先 transform ✓）

    ★ 优先 `connectorNterminal` ✓（原理图的连接点在这儿 ✓）；
      退回 `connectorNpin` 线的**中点** ✓（并标明用的是哪种 ✓，不静默 ✓）。
    """
    term, pin, bad = {}, {}, []

    def walk(el, m):
        if tag(el) == "defs":
            return
        for c in el:
            t = c.get("transform")
            mc = PB.mul(m, PB.parse_tf(t)) if t else m
            eid = c.get("id") or ""
            mt, mp = re.match(r"^(connector\d+)terminal$", eid), re.match(r"^(connector\d+)pin$", eid)
            if mt or mp:
                if tag(c) == "rect":
                    p = (enum(c, "x") + enum(c, "width") / 2.0,
                         enum(c, "y") + enum(c, "height") / 2.0)
                elif tag(c) in ("line", "polyline"):
                    p = ((enum(c, "x1") + enum(c, "x2")) / 2.0,
                         (enum(c, "y1") + enum(c, "y2")) / 2.0)
                elif tag(c) == "circle":
                    p = (enum(c, "cx"), enum(c, "cy"))
                else:
                    p = None
                if p is None:
                    bad.append("%s=<%s>（认不出参考点 ✗）" % (eid, tag(c)))
                else:
                    (term if mt else pin)[(mt or mp).group(1)] = PB.apply(mc, p[0], p[1])
            walk(c, mc)

    walk(txt_root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return term, pin, bad


resolve = SB.resolve_parts_svg       # ★ 唯一实现已搬去 `sch_box.py` ✓（本地不再定义 ✗）


# ═══════════════ 主流程 ═══════════════
# ★★ 位置参数 = “不以 `--` 开头、且**不是任何 `--` 选项的取值**” ✓（2026-09-28 修 ✗）
#   ✗ 原来只按“不以 `--` 开头”筛 ✗ ⇒ 用**空格式**写选项时，它的**取值**会被当成位置参数 ✗✗：
#     实测 `--verify-export _work\t58_1_图示.svg` ⇒ 那个 svg 落到 `args[2]`（= `px宽` ✗）
#     ⇒ `ValueError: could not convert string to float` ✗（用户**第二次**踩 ✓）。
#   ★ 本仓两种写法都用过 ✓（`--pins-out=` 必须带等号 ✗ / `--rails` 只能空格 ✗）
#     ⇒ **一律两种都收** ✓，而且选项的取值不再污染位置参数 ✓。
args, _i = [], 1
while _i < len(sys.argv):
    _a = sys.argv[_i]
    if _a.startswith("--"):
        _i += 1 if "=" in _a else 2          # 空格式：连它的取值一起跳过 ✓
        continue
    args.append(_a)
    _i += 1
opts = {}
for i, a in enumerate(sys.argv[1:]):
    if a.startswith("--") and "=" in a:
        k_, v_ = a[2:].split("=", 1)
        opts[k_] = v_
    elif a.startswith("--") and i + 1 < len(sys.argv[1:]):
        opts[a[2:]] = sys.argv[i + 2]
VIEW = opts.get("view", "schematicView")
path, out = args[0], args[1]
PXW = float(args[2]) if len(args) > 2 else 1800.0
MMU = 25.4 / 90.0                                   # 1 sketch 单位 = 1/90 in ✓

z = zipfile.ZipFile(path)
fzname = [n for n in z.namelist() if n.endswith(".fz")][0]
root = ET.fromstring(z.read(fzname))
packed = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".svg")}
print("== %s ▶ %s（%d 字节）" % (path, fzname, os.path.getsize(path)))

# ── ① 零件 ──
body_parts, PIN_SK, ALL_PTS = [], [], []
PART_BOX, PINS_REL, BOX_REL = {}, {}, {}          # ★ 本体框 / 相对锚点的脚位与框（摆位用 ✓）
LBL_TITLE = set()                                # ★ 网标签的标题 ✓（“标签是元件” ✓ B3.1.1 ✓）
LAB_REL = {}                                     # ★ 位号内容 + 字号（摆位脚本挑位置用 ✓）
# ★★ Fritzing **内置的类目单位** ✓（位号会把它补在值后面 ✓）—— **只列实测过的** ✓：
#   `resistance` ⇒ `Ω` ✓（依据：实例值 `220` ✓、fzp 无 `units` ✓，而 Fritzing 位号画 `220Ω` ✓；
#   见下面「位号行」一段的注释 ✓）。要再加类目 ⇒ **先要一份含该属性的 Fritzing 导出** ✓。
_UNIT_BY_PROP = {"resistance": "\u03a9"}
skipped = []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if mid.startswith("Wire"):
        continue
    ttl = (el.findtext("title") or "").strip()
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    g = next((c for c in sv if tag(c) == "geometry"), None)
    if g is None:
        continue                                    # 这一视图里没摆位的（如 PCB1 ✓）
    # ★★ 2026-09-29 ✓ **网标签也要画出来** ✗（用户发现：我的 png/svg 里**根本没有标签** ✗）
    #   ✗ 原因：它的 fzp 在磁盘上**不存在** ✗（`:/resources/parts/core/netlabel.fzp` ✓）
    #     ⇒ 下面那句 `os.path.isfile` 直接 `continue` ⇒ **跳过** ✗ ⇒ 图上看不见、判据也看不见 ✗。
    #   ✓ 现在：按**实测口径**把它画成“**带尖头的方框 + 网名**” ✓，并把它的脚**登进 `PIN_SK`** ✓
    #     ⇒ ① 图上看得见 ✓（人眼能校对位置 ✓）；② (A)/(A') 与“悬空端”判据**也能管它了** ✓。
    # ★ 名字取实例的 **`<property name="label">`** ✓（Fritzing 画的就是它 ✓；`<title>` 只是备忘 ✓
    #   —— 依据：用户造件 `_work/netlabels.fzz` 里 `<title>` 是 `RC1`、**画出来是 `RC`** ✓）
    _lab = next((_p.get("value") for _p in el.iter("property") if _p.get("name") == "label"), None)
    _lbl = sch_net.net_name(mid, ttl, _lab)
    if _lbl:
        # ★★ 2026-09-29 ✓ **几何全部实测** ✓（见 `sch_net.py` 的「本体几何」一节 ✓）：
        #   · 实例的 `geometry` = **局部原点** ✓；
        #   · 绘 = **绕板心 `C = (0.6 + W/2, 4.5)` 旋转** ✓（`sch_net.view` ✓）；
        #   · 文字 = **纯文字** ✓（`x=0.6 y=6.6` 局部 ✓、字号 **6.0** ✓、Droid Sans ✓、黑 ✓）
        #     —— ✗ 我原来画的那个"白底黑框大矩形"是**我发明的** ✗（Fritzing 根本没画 ✗）。
        #   · `transform` 的 `m31/m32` **Fritzing 不用** ✗（实测 ✓）⇒ 这里也**不用** ✓，
        #     **只用它的旋转部分** ✓。
        _geom = (enum(g, "x"), enum(g, "y"))                # ★ 局部原点 = 实例 `geometry` ✓
        _mi = el.get("modelIndex") or "0"                   # ✗ 别借用循环外面的 `mi` ✗
        #   （实测教训：原来那句用了外面漏下来的 `mi` ⇒ 换成**没有导线**的草图就 NameError ✗，
        #    而 v34 恰好有导线 ⇒ 一直没暴露 ✗）
        _tf = g.find("transform")
        _m = ((_tf.get("m11", "1"), _tf.get("m12", "0"),
               _tf.get("m21", "0"), _tf.get("m22", "1"))
              if _tf is not None else ("1", "0", "0", "1"))
        _bx = sch_net.label_box(_geom, _lbl, _m)             # ★ 本体框：**一处实现** ✓
        # ★★ 2026-09-29 修 ✗✗：**脚**要用源码口径（**锅头尖端那一侧** ✓）——
        #   ✗ 旧模型写“平端”✗ ⇒ 差整整一个旗标长（≈3.4mm ✗）⇒ ② 拿它当尺子时
        #     “线到底接没接上”根本量不准 ✗（详见 `sch_net.py` 那段 ✗✗）。
        _dir = next((_p.get("value") for _p in el.iter("property")
                     if _p.get("name") == "direction"), "right")
        _px, _py = sch_net.label_pin(_geom, _lbl, _m, go_left=(_dir == "left"))
        _deg = sch_net.rot_deg(_m)
        _cx, _cy = sch_net.pivot(_lbl)                       # 枢轴（局部 ✓）
        # ★★ 2026-09-29 ✓ **外框（箭头形旗标）** ✓ —— 用户指出我漏了它 ✓（实测见 `sch_net.label_flag` ✓）：
        #   · 形状 = 旗身 + 尖头 ✓，白底黑边 ✓ 线宽 0.30 sketch ✓（= 导出 0.24 ÷ 0.8 ✓）；
        #   · 盒 = 宽 **8.700**（定值 ✓）× 长 **`flag_len`**（随网名 ✓），尖头 **5.600** ✓；
        #   · **锚在“文字锚点”上** ✓、**与旋转无关** ✓（0°/90°/−90° 三组实测顶点完全一样 ✓）——
        #     ✗ 我上一版锚在“脚”上 ✗ ⇒ 差 2.7mm ✗（看着像“只对 −90° 对”✗）。
        #   ★ 顶点一律问 `sch_net.label_flag` ✓（**一处实现** ✓ —— 核对器用同一份 ✓，不另写 ✗）。
        _pv = []
        for _vx, _vy in sch_net.label_flag(_geom, _lbl, _m):
            _pv.append("%.4f,%.4f" % (_vx - _geom[0], _vy - _geom[1]))
            #   ★ 算出来是**视图坐标** ✓ ⇒ 减掉 `geom` 才是"组内坐标" ✓（这一组已 translate(geom) ✓；
            #     ✗ 不减就**偏移两份** ✗）
        _flag = ('<polygon points="%s" fill="#ffffff" stroke="#000000" '
                 'stroke-width="0.300000"/>' % " ".join(_pv))
        # ★★★ 2026-09-29 ✓ **文字朝向照 Fritzing 看** ✓（用户实测 ✓）：
        #   ✗ 我原来无论什么朝向都把 `<text>` 跟着转 θ ✗ ⇒ **180° 时字是倒着的** ✗；
        #   ✓ 用户指出：Fritzing 里那个 `RC`（`m11=-1 m22=-1` ✓）**字是正的** ✓
        #     —— 与 `NetLabel::makeSvg` 里那套 `align/reversed` 逻辑一致 ✓
        #     （源码原话：`bool reversed = (transform().m11() < -0.5);  // horizontal flip or 180°` ✓）。
        #   ⇒ 口径：**`m11 < 0`（镜像/180°）⇒ 文字不转** ✓（按**画出来的旗标盒**排布 ✓：
        #     左缘 + 一个字符边距 ✓、竖直居中 ✓）；其余朝向照旧跟着 θ 转 ✓（±90° 是竖排 ✓，
        #     用户此前的截图里 `GND` 就是竖的 ✓）。
        if float(_m[0]) < -0.5:
            _fb = sch_net.label_flag(_geom, _lbl, _m)
            _fx0 = min(p[0] for p in _fb)
            _fx1 = max(p[0] for p in _fb)
            _fy0 = min(p[1] for p in _fb)
            _fy1 = max(p[1] for p in _fb)
            #   ★ 靠**非尖端**那一侧 ✓（尖头在左 ⇒ 字靠右 ✓）—— 与源码 `alignForPolicy` /
            #     `reversed` 那套一致 ✓（✗ 我第一版靠左 ✗ ⇒ 字有一半压在尖头上 ✗，实测截图可见 ✗）。
            _txt = ('<text id="label" x="%.3f" y="%.3f" font-family="Droid Sans" '
                    'font-size="%.3f" fill="#000000" text-anchor="end">%s</text>'
                    % (_fx1 - _geom[0] - sch_net.LABEL_TEXT_X,
                       (_fy0 + _fy1) / 2.0 - _geom[1] + sch_net.LABEL_PLATE_H / 2.0,
                       sch_net.LABEL_FS, html.escape(_lbl)))
        else:
            _txt = ('<text id="label" x="%.3f" y="%.3f" font-family="Droid Sans" '
                    'font-size="%.3f" fill="#000000" transform="rotate(%.4f %.4f %.4f)">%s</text>'
                    % (sch_net.LABEL_TEXT_X, sch_net.LABEL_BASELINE_Y, sch_net.LABEL_FS,
                       _deg, _cx, _cy, html.escape(_lbl)))
        _art = ('<g partID="%s1"><g id="schematic" transform="translate(%.4f %.4f)">'
                "%s%s</g></g>"
                % (_mi, _geom[0], _geom[1], _flag, _txt))
        body_parts.append((ttl, "网标签 ✓ 脚(%.1f,%.1f) ✓ 朝向%d° ✓" % (_px, _py, round(_deg)),
                           _art))
        PIN_SK.append((ttl, "connector0", (_px, _py)))
        LBL_TITLE.add(ttl)                      # ★ 见下面“穿体”那条：**标签不豁免自己那根线** ✗
        PART_BOX[ttl] = _bx                     # ★ 与画图**同一个盒子** ✓（“标签是元件” ✓ B3.1.1 ✓）
        for _qc in ((_bx[0], _bx[1]), (_bx[2], _bx[3])):
            ALL_PTS.append(_qc)                 # ★ 画布要**圈住本体框** ✓（不是只圈脚 ✓）
        continue
    # ★★ **接地符号**（core `GroundModuleID` ✓，2026-09-29 ✓）：它的图形**也在 app 里** ✗
    #   （`:/resources/parts/core/schematic/ground.svg` ✓，`.fzz` 不带 ✓）⇒ **画不出来** ✓（待补 ✓）。
    #   ★ 但**脚位是知道的** ✓（`sch_net.ground_pin` ✓ —— 用**用户手画的两处线端**反推 ✓，
    #     两个样本给的偏移**完全一样** ✓✓）⇒ **照样登进 `PIN_SK`** ✓
    #   ⇒ 这样 ② 才量得出“线到底有没有接在接地符号上” ✓
    #   （✗ 不登的话它掉进“图形缺失 ⇒ 不判”那一档 ✗ ⇒ 线飘到哪都查不出来 ✗）。
    if sch_net.is_ground_symbol(mid):
        _gpx, _gpy = sch_net.ground_pin((enum(g, "x"), enum(g, "y")))
        PIN_SK.append((ttl, "connector0", (_gpx, _gpy)))
        ALL_PTS.append((_gpx, _gpy))
        # ★★ 2026-09-30 ✓ **图形入库了** ✓（用户导出 → 逐字摘出 ✓ 见 `_assets/` ✓）
        #   ⇒ 照 `sch_net.ground_art` 摆好位、直接画 ✓（脚位与图形**同一份口径** ✓）。
        _gart = sch_net.ground_art((enum(g, "x"), enum(g, "y")))
        if _gart:
            body_parts.append((ttl, "接地符号 ✓ 脚(%.1f,%.1f) ✓" % (_gpx, _gpy), _gart))
            # 本体盒（三根横线 + 竖杆的包围盒 ✓，sketch 坐标 ✓）—— 给“穿体/可读性”判据用 ✓
            # ★ 2026-09-30 ✓：口径**搬到 `sch_net.ground_box`** ✓（生成器画接地符号时判碰撞
            #   要用**同一个盒子** ✓ —— 原来这一行只在本文件里 ✓ ⇒ 迟早两边对不上 ✗）。
            PART_BOX[ttl] = sch_net.ground_box((enum(g, "x"), enum(g, "y")))
            for _qc in ((PART_BOX[ttl][0], PART_BOX[ttl][1]),
                        (PART_BOX[ttl][2], PART_BOX[ttl][3])):
                ALL_PTS.append(_qc)
        else:
            skipped.append((ttl, "**接地符号：图形文件没读到** ✗（`_assets/ground_symbol.svg` ✓）"
                                 "⇒ 只登脚位、不画 ✓（如实报出 ✓）"))
        continue
    fzp = (el.get("path") or "").replace("/", os.sep)
    if not os.path.isfile(fzp):
        skipped.append((ttl, "fzp 不存在 ⇒ %s" % fzp))
        continue
    fr = ET.parse(fzp).getroot()
    fam = next((p.get("value") for p in fr.iter("property") if p.get("name") == "family"), None)
    tax = (fr.findtext("taxonomy") or "")
    lay = fr.find(".//%s/layers" % VIEW)
    layerid = None
    if lay is not None:
        l0 = next((c for c in lay if tag(c) == "layer"), None)
        layerid = l0.get("layerId") if l0 is not None else None
    image = lay.get("image") if lay is not None else None
    if "breadboard" in tax.lower() or (fam or "").lower() == "breadboard":
        skipped.append((ttl, "**面包板本体：Fritzing 的原理图不画它** ✓（导出可证 ✓）"))
        continue
    txt, src = None, None
    if image:
        # ★ **磁盘优先** ✓（Fritzing 就是从 fzp 旁边加载 ✓）；包内副本只是备份 ✓（会注明 ✓）
        #   ★ 这两句现在走**共享实现** ✓（`sch_box.part_svg_text` ✓ —— 布线器用同一份 ✓）
        txt, src = SB.part_svg_text(fzp, packed, image)
        if txt is None:
            skipped.append((ttl, "svg 取不到（image=%s；%s）" % (image, src)))
            continue
    if txt is None:
        skipped.append((ttl, "fzp 里 `%s/layers@image` 为空 ✗" % VIEW))
        continue
    k, org, khow = scale_of(txt)
    if k is None:
        skipped.append((ttl, "k 算不出：%s" % khow))
        continue
    want_layer = layerid or "schematic"
    laytxt, lnote = layer_of(txt, want_layer)
    if laytxt is None:
        laytxt, lnote = inner(txt), lnote + " ⇒ 退回整张 svg 的 body ⚠"
    m = PB.tf_of(g)                       # hmm：`m` 已不再直接用 ✓（改用共享的 `SB.A_of` ✓）
    A = SB.A_of(txt, g)                   # ★ **唯一实现** ✓（与布线器同一份 ✓）
    e, f = enum(g, "x") + A[4], enum(g, "y") + A[5]
    # ★★ 多包两层 ✓（`partID` + `id="schematic"` ✓）—— 不是为了好看 ✗，是为了**当尺子** ✓：
    #   既有接线管线 `gen_schematic_wires.py` 的 `build_ruler()` 就是按 Fritzing **导出**里
    #   这两层找“零件原点 + 各脚坐标 + 本体轮廓” ✓（`partID` ⇒ 零件 ✓；`id="schematic"` ⇒ 原点/本体 ✓）。
    #   本机 Fritzing 命令行导出是坏的 ✗ ⇒ **我自己的渲染就是那份尺子** ✓（已对导出验平 ✓）。
    #   `partID` 用 `modelIndex + "0"` ✓（管线按 `startswith(mi)` + 长度 +1 匹配 ✓，与 Fritzing 同形 ✓）。
    mi = el.get("modelIndex") or "0"
    body_parts.append((ttl, "%s" % lnote,
                       '<g partID="%s0"><g transform="matrix(%.6f %.6f %.6f %.6f %.6f %.6f)">'
                       '<g id="schematic">%s</g></g></g>'
                       % (mi, A[0], A[1], A[2], A[3], e, f, laytxt)))
    # 脚的 sketch 坐标 ✓（自检/核对用 ✓）：**一处算清** ✓
    #   ★ `A` 里已经含了「减 viewBox 原点」✓（A = M·(k,0,0,k,−k·原点) ✓）
    #     ⇒ 映射就是 `geom + A·p` ✓ —— **不要再减一次原点** ✗（我在草稿里就重复扣减过 ✗）。
    try:
        term, pin, bad = anchors(ET.fromstring(txt))
    except Exception as ex:
        term, pin, bad = {}, {}, ["<svg 解析不了：%s>" % ex]
    pins, kind = (term, "terminal") if term else (pin, "pin")
    for cid, p in pins.items():
        PIN_SK.append((ttl, cid, to_sketch(g, A, p)))
    # 本体包围盒（sketch ✓）—— ★ 只调共享实现 ✓（原来这里和布线器**各算一套** ✗）
    _box, _A2, _note = SB.box_of(txt, g, A)
    bb = None
    if _box:
        for cx, cy in ((_box[0], _box[1]), (_box[2], _box[1]),
                       (_box[0], _box[3]), (_box[2], _box[3])):
            ALL_PTS.append((cx, cy))
        PART_BOX[ttl] = _box
        PINS_REL.setdefault(str(el.get("modelIndex")), {})["__title__"] = ttl
        for cid, p in pins.items():                      # ★ 各脚 → **相对锚点**（sketch 单位 ✓）
            PINS_REL.setdefault(str(el.get("modelIndex")), {})[cid] = \
                (to_sketch(g, A, p)[0] - enum(g, "x"), to_sketch(g, A, p)[1] - enum(g, "y"))
        BOX_REL[str(el.get("modelIndex"))] = (
            PART_BOX[ttl][0] - enum(g, "x"), PART_BOX[ttl][1] - enum(g, "y"),
            PART_BOX[ttl][2] - enum(g, "x"), PART_BOX[ttl][3] - enum(g, "y"))
    print("   %-12s img=%-42s 用了 %s" % (ttl, image or "（无）", os.path.basename(src)))
    print("        k=%.5f｜原点=(%g,%g)｜%s｜脚 %d 个（%s ✓）｜%s"
          % (k, org[0], org[1], khow, len(pins), kind, lnote))
    for b in bad:
        print("        ⚠ %s" % b)

# ★★ 2026-09-29 ✓ **只能判**“图形已解析到”的脚 ✗（用户拿 Fritzing 截图当场推翻了我 ✗）——
#   ✗ 我上一版把“声明接某脚、而线没画到那只脚上”一律算 ✗ ⇒ **漏了前提**：那只脚的**坐标根本不知道** ✗
#     （本例：4 个 **核心库网标签** `NetLabelModuleID` ✓，`path=":/resources/parts/core/netlabel.fzp"`
#      ⇒ 磁盘上**没有**这个文件 ✗ ⇒ 零件被**跳过** ✓ ⇒ 没进 `PIN_SK` ✗）
#     ⇒ 几何比对上**必然**报“没画到” ✗✗，而用户截图里那根线**正正好好地接在标签脚上** ✓。
#   ✓ 所以：**先问“这只脚的坐标知道吗”** ✓ —— 不知道 ⇒ **无法判定**（单列 ✓ 不计入 ✗）。
KNOWN_PIN = {(t, c) for (t, c, _q) in PIN_SK}          # 坐标**已知**的脚 ✓（= 图形已解析到 ✓）

# ── ② 导线 ──
wires, widx = [], []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if not mid.startswith("Wire"):
        continue
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    g = next((c for c in sv if tag(c) == "geometry"), None)
    if g is None:
        continue
    ttl = (el.findtext("title") or "").strip()
    col, mils = "#404040", None
    for c in sv.iter():
        if tag(c) == "wireExtras":
            col, mils = c.get("color") or col, c.get("mils")
    x, y = enum(g, "x"), enum(g, "y")
    a = (x + enum(g, "x1"), y + enum(g, "y1"))
    b = (x + enum(g, "x2"), y + enum(g, "y2"))
    w = (float(mils) * 90.0 / 1000.0) if mils else 0.875          # mils → 1/90in 单位 ✓；默认 9.7222mil ✓
    wires.append((ttl, a, b, col, w))
    widx.append((ttl, a, b))
    ALL_PTS += [a, b]
print("── 导线 %d 根 ｜ 颜色 %s ｜ 线宽 %s ──"
      % (len(wires), dict(collections.Counter(w[3] for w in wires)),
         sorted({round(w[4], 6) for w in wires})))

# ══ ②b ★★ **假连线**检查 ✓（2026-09-28 ✓，用户发现 ✓）══════════════════════════
#   ★ 为什么要它 ✗：本仓记过一条硬事实 —— **Fritzing 的连接显式记在 `<connects>` 里** ✓
#     ⇒ `check_netlist.py`（只看连接表 ✗）**永远看不见“图上的假象”** ✗✗：
#       (A) 声明接某只脚，而**线根本没画到那只脚上** ✗（图上看着**断开** ✓ —— px/1-90in 那个
#           bug 就是这种 ✓，我当时只查连接表 ⇒ 报了“45/45 全配上”而用户截图里线没到脚 ✗✗）；
#       (B) 线**画在**某只脚上（端点落在脚上 ✓、或线身**正好穿过**脚 ✓）而连接表里**没有**那条 ✗
#           ⇒ 读图的人以为接上了 ✓、电气上却是**断的** ✗（这是最阴的一种 ✓）。
#   ★ 判据（客观 ✓）：线端 / 线身 到脚的距离 ≤ 0.05 单位（= 1.4e-3 mm ✓）就算“碰上” ✓。
#   ★ 免责 ✗：`sch_edges` 的解析与 `check_netlist.py` **同源** ✓（理想是抽成共享模块 ✓，
#     已记为待办 ✓；这里为了“几何 vs 表”的对照而**再读一遍文件** ✓）。
SCH_LAYERS = {"schematic", "schematicTrace"}


def _p2seg(p, a, b):
    """点到线段距离 ✓（**一份实现** ✓ —— 已搬进 `sch_geom.p2seg` ✓，这里只是别名 ✓）"""
    return SG.p2seg(p, a, b)


def _fz_edges(inst):
    out = []
    vw = next((c for c in inst if tag(c) == "views"), None)
    sub = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sub is None:
        return out
    for cbox in sub.iter():
        if tag(cbox) != "connectors":
            continue
        for con in cbox:
            if tag(con) != "connector":
                continue
            for cs in con:
                if tag(cs) != "connects":
                    continue
                for c in cs:
                    if tag(c) == "connect" and (c.get("layer") or "") in SCH_LAYERS:
                        out.append((con.get("connectorId"), c.get("connectorId"),
                                    c.get("modelIndex")))
    return out


FZ_TITLE, FZ_EDGE, FZ_ISWIRE = {}, {}, {}
for _el in root.iter("instance"):
    _mi = _el.get("modelIndex")
    FZ_TITLE[_mi] = (_el.findtext("title") or "").strip()
    FZ_ISWIRE[_mi] = (_el.get("moduleIdRef") or "").startswith("Wire")
    FZ_EDGE[_mi] = _fz_edges(_el)

# 线**画**在哪只脚上：端点 + 线身（分两类 ✓）
# ★★ `PIN_HIT_TOL`：线端算“落在脚上”的容差 ✓ —— **实测定的** ✓（不是拍的 ✗，2026-09-29 ✓）：
#   Fritzing **吸附过的**坐标存进文件后仍带 **0.09~0.13 单位（0.03~0.04mm ✓）** 的零头 ✓
#   —— 实测 `v30_byHand` / `v31_rcgnd_byHand` 里 **4 处手画接头全是 0.09~0.13** ✓✓，
#     而**真断**的那些差 **3.5~12 单位**（0.99~3.5mm ✓）⇒ 两边**差两个量级** ✓ ⇒ 阈值很好定 ✓。
#   ✗ 原来这里写死 `0.05`（= 0.014mm ✗）⇒ 把**手画的**接头全判成“没画到” ✗✗ ⇒
#     `(A)` 永远在报假警 ✓、而真正 3.5mm 那种错反而混在噪声里看不见 ✗。
#   （线宽 0.25mm ✓ ⇒ 0.14mm 的容差远小于一根线宽 ✓，不会把“真断”吃进来 ✓。）
PIN_HIT_TOL = 0.5
geom_end, geom_body = [], []
for ttl_w, a, b, _c, _w in wires:
    pa = [(t, c) for (t, c, q) in PIN_SK if math.dist(q, a) <= PIN_HIT_TOL]
    pb = [(t, c) for (t, c, q) in PIN_SK if math.dist(q, b) <= PIN_HIT_TOL]
    geom_end.append((ttl_w, a, b, pa, pb))
    if len(a) and len(b):                      # 线身：**中段**正好穿过某只脚（端点不算 ✓）
        for (t3, c3, q3) in PIN_SK:
            if (math.dist(q3, a) <= PIN_HIT_TOL or math.dist(q3, b) <= PIN_HIT_TOL):
                continue
            d3 = _p2seg(q3, a, b)
            if d3 <= 0.05:
                geom_body.append((ttl_w, t3, c3, q3))

# ★★ (C) **退化为点的导线** ✓（2026-09-28 ✓ 用户手改版实测后新增的**第三类** ✓）
#   实测两根、性质**完全不同** ✓（都是**只读** `pixel-schematic-v16_byHand.fzz` 得来的 ✓）：
#     · `Wire90012908` = **点接头** ✓ —— 几何 (22.578,18.000)→(22.578,18.000) ✓
#       （**正好在 `U1.PD0` 引脚上** ✓），只声明原理图连接 ✓ ⇒ **功能正常** ✓；
#     · `Wire90012946` = **跨视图残留** ✗ —— 几何 (153.000,72.000)→(153.001,72.004) ✓
#       但它在**面包板/PCB** 里是**实体**（`R1.c0 ↔ Breadboard1.pin17G` ✓）
#       ⇒ 在**原理图**里塌成了一个点 ✗、且离它声称的 `R1.c0` 引脚 **25 单位** ✗。
#   ⇒ 这两类**都不是**“表里有、图上没有”✗、也**不是**“图上接上、表里没有”✗
#     ⇒ 单独算 **(C)** ✓，**不计入** (A)/(B) 与悬空端 ✗（否则永远报假错 ✗）；
#     ★ 但**照样报出来** ✓（绝不静默丢掉 ✗ —— 交给人看一眼 ✓）。
DEGEN_TOL = 0.05          # = 全仓“碰到/落在”的同一个容差 ✓（不新造数 ✗）
degen = [t for (t, a, b, _pa, _pb) in geom_end if math.dist(a, b) <= DEGEN_TOL]

# 连接表**说**接谁（把线端的两个目标摊平 ✓）
declared = {}                                  # ttl_w → {端点: {(标题, 脚)}}
for ttl_w, _a, _b, _c, _w in wires:
    _mi = next((m for m, t in FZ_TITLE.items() if t == ttl_w), None)
    d = {}
    for own, tcid, tmi in FZ_EDGE.get(_mi, []):
        tgt = (FZ_TITLE.get(tmi, "?"), tcid)
        if FZ_ISWIRE.get(tmi):
            continue                           # ★ 与另一根**导线**相连（链 ✓）⇒ 不算脚 ✓
        d.setdefault(own, set()).add(tgt)
    declared[ttl_w] = d

fake_a, fake_b, fake_unk = [], [], []
W_END = {t: (a, b) for (t, a, b, _pa, _pb) in geom_end}      # 每根线的两个端点 ✓（查接头用 ✓）
for ttl_w, a, b, pa, pb in geom_end:
    if ttl_w in degen:                         # ★ (C) 退化导线 ⇒ 不并进 (A)/(B) ✗（单独报 ✓）
        continue
    d = declared.get(ttl_w, {})
    tall = set().union(*d.values()) if d else set()
    # (A) 表里说了某只脚，可几何**完全不在这只脚上** ✗✗
    #   ★ 前提 ✓：这只脚的**坐标得知道** ✓（图形没解析到 ⇒ **无法判定** ✗ 不算错 ✗）
    for (t4, c4) in sorted(tall):
        if (t4, c4) not in KNOWN_PIN:
            fake_unk.append((ttl_w, t4, c4))
            continue
        if (t4, c4) not in pa and (t4, c4) not in pb:
            fake_a.append((ttl_w, t4, c4, a, b))
    # (B) 端点落在某脚上，而**没有任何导线贴在那一点**声明接它 ✗
    #   ★★ 修正 ✓（2026-09-28 ✓，`t27_1` 三坐标实测后定的 ✓）：
    #     ✗ 旧版只查**本根**的声明 ✗ ⇒ 链式接法里“拐点正好落在脚点上”时会**误报** ✗
    #       （实测 4 处一一对应：`Wire90012892` 的一端在 `C2.c0` 点上 ✓，而声明
    #        `C2.c0` 的是**链上相邻的那根** `Wire90012893` ✓ ⇒ 电气上是接上的 ✓）。
    #     ✓ 新版：只要有**任意一根**导线**在该点**声明接这只脚 ⇒ 就算接上 ✓。
    for (t5, c5) in (pa + pb):
        if (t5, c5) in tall:
            continue
        q5 = [q[2] for q in PIN_SK if q[0] == t5 and q[1] == c5]
        ok_chain = any(math.dist(q5[0], e) <= PIN_HIT_TOL
                       for tw in declared
                       for _own2, tg2 in declared[tw].items()
                       if (t5, c5) in tg2
                       for e in W_END.get(tw, ())) if q5 else False
        if not ok_chain:
            fake_b.append((ttl_w, t5, c5, a, b))
print("── ★★ **假连线**检查（几何 vs 连接表 ✓）：")
print("   (A) 表里声明接了某脚，而线**没画到**那只脚上：**%d 处** %s"
      % (len(fake_a), "✓" if not fake_a else "✗✗"))
for ttl_w, t4, c4, a, b in fake_a[:10]:
    print("      ✗ %-14s 声明接 %s.%s ✗ ｜ 实际画在 (%.1f,%.1f)→(%.1f,%.1f)"
          % (ttl_w, t4, c4, a[0], a[1], b[0], b[1]))
print("   (A') **脚的图形没解析到 ⇒ 无法几何判定**（单列 ✓ **不计入 (A)** ✗）：**%d 处** %s"
      % (len(fake_unk), "✓" if not fake_unk else "⚠ 信连接表 ✓ / 请人看一眼 ✓"))
for ttl_w, t4, c4 in sorted(set(fake_unk))[:8]:
    print("      ⊘ %-14s 声明接 %s.%s —— 该件图形缺失（如核心库件 `:/resources/…` ✓）⇒ 不判 ✓"
          % (ttl_w, t4, c4))
print("   (B) 线**画在**某脚上（端点 ✓ 或线身穿心 ✓），表里却没有这一条：**%d 处** %s"
      % (len(fake_b) + len(geom_body), "✓" if not (fake_b or geom_body) else "✗✗"))
for ttl_w, t5, c5, a, b in fake_b[:10]:
    # ★ 把**三方坐标**一起打出来 ✓（2026-09-28 ✓）—— 上一版只报“看着接上某脚” ✗
    #   ⇒ 无法判断到底是**图真错** ✗ 还是**我认错线** ✗。现在：线端坐标 ✓ + 被指脚坐标 ✓
    #     + 表里声明的伙伴及其坐标 ✓ ⇒ 一眼看出归属 ✓。
    _q = [q[2] for q in PIN_SK if q[0] == t5 and q[1] == c5]
    _d = declared.get(ttl_w, {})
    _tall = sorted(set().union(*_d.values())) if _d else []
    print("      ✗ %-14s 端点看着接上 %s.%s @%s ✗；线端 (%.2f,%.2f)/(%.2f,%.2f)；"
          "表里声明 = %s @%s"
          % (ttl_w, t5, c5, ["(%.2f,%.2f)" % q for q in _q], a[0], a[1], b[0], b[1],
             ["%s.%s" % t for t in _tall] or ["（空 ✗）"],
             ["(%.2f,%.2f)" % q[2] for q in PIN_SK if (q[0], q[1]) in _tall]))
for ttl_w, t3, c3, q3 in geom_body[:10]:
    print("      ✗ %-14s **线身穿过** %s.%s（%.1f,%.1f）✗ ⇒ 图上像接上了 ✓ 实际没连 ✗"
          % (ttl_w, t3, c3, q3[0], q3[1]))
print("   (C) **退化为点的导线**（点接头 ✓ / 跨视图残留 ✗ —— 上面两条**不算它们** ✓；"
      "这里**如实列出** ✓，请人看一眼 ✓）：**%d 根** %s"
      % (len(degen), "✓" if not degen else "⚠"))
for ttl_w in degen:
    _e = next((e for e in geom_end if e[0] == ttl_w), None)
    _a, _b = (_e[1], _e[2]) if _e else ((0, 0), (0, 0))
    _d = sorted(set().union(*declared.get(ttl_w, {}).values())) if declared.get(ttl_w) else []
    _ln = math.dist(_a, _b)
    _near = min(((math.dist(_a, q[2]), q) for q in PIN_SK), default=(1e18, None))
    print("      ⚠ %-14s 长度 %.3f 单位 ✗ ｜ 两端 (%.3f,%.3f)→(%.3f,%.3f) ｜ 声明接 %s ｜"
          " 离最近脚 %s.%s **%.2f 单位**"
          % (ttl_w, _ln, _a[0], _a[1], _b[0], _b[1], ["%s.%s" % x for x in _d] or "（无）",
             _near[1][0] if _near[1] else "?", _near[1][1] if _near[1] else "?", _near[0]))
tot = sum(math.dist(w[1], w[2]) for w in wires)
print("   总长 %.1f 单位 = %.1f mm" % (tot, tot * MMU))

# ★ 接点圆点 ✓（Fritzing 在导线**接头**上画实心小圆 ✓）
#   半径由导出**实测** ✓：导出里 `r=0.72` ✓ 而导出 = sketch×0.8 ✓ ⇒ sketch 里 **0.9 单位** ✓。
#   判据**由导出反推** ✓（2026-09-27 ✓，`_scratch/dot9.py` ✓）：
#     · 导出 v2：**50 个圆 = 25 个位置 × 每处 2 个** ✓（Fritzing 给每根线在接头处各画一个 ✓）；
#       视觉上"一处一个" ✓ ⇒ 我也只画**一个** ✓。
#     · ★ 判据（实测最接近的一版 ✓）：**该处 ≥2 个导线端点，且不在任何引脚上** ✓
#       ⇒ 我 29 个位置 ↔ 导出 25 个 ✓（差 4 个 ✓ 已量化 ✓，全在引脚附近 ✓；
#         我没再试第三条猜测 ✗ —— "该处 ≥3 根导线"实测得到 **0** 个 ✗，
#         因为网表是**链式**接法 ✓，每个接头就是 2 根端点 ✓）。
#     · 实测导出那 25 个位置上都是 **2 个导线端点** ✓；
#       ✗ 不在**引脚**（D3 的 A1/A2 ✓、C1 ✓、R1 ✓、C2 ✓、LED2 ✓、U1 ✓）与**纯拐角**处画点 ✓。
#   ★ 聚容差 0.01 单位**必须有** ✗：Fritzing 自己存的同一接头会差 0.001 ✓
#     （实测 `186.513` vs `186.512` ✓）⇒ 按小数位分组会把接头拆成两个 ✗。
DOT_R = 0.9               # 小点（**2 根线**相接 ✓）= 导出 0.72 ÷ 0.8 ✓
DOT_R_BIG = 1.8           # 大点（**≥3 根线**相接 ✓）= 导出 1.44 ÷ 0.8 ✓
JTOL = 0.01

# ★★ 大小之分：**用户 2026-09-29 给定口径** ✓（“大的 = 三条线以上接在一起 ✓、小的 = 两条 ✓”），
#   并在**导出里实测确认** ✓（`_work/v34_图示.svg` ✓）：
#     线端 2 根 ⇒ r=0.72（小 ✓）15 处 ｜ 线端 3 根 ⇒ r=1.44（大 ✓）11 处 ｜
#     另有 2 处 r=0.56、线端 0 根 ⇒ 那是**零件自己的小圆**（不是接点 ✓ 我不画 ✓）。
#   ★ 还量到：**Fritzing 给接点上的每根线各画一个圆** ✓（2 根线 ⇒ 2 个元素、3 根 ⇒ 3 个 ✓）
#     ⇒ 同一个位置上它们**半径相同** ✓ ⇒ 我只画**一个**（视觉等价 ✓）。


GRP = []
for _p in (p for _t, a, b, _c, _w in wires for p in (a, b)):
    _hit = next((g for g in GRP if math.dist(_p, g[0]) < JTOL), None)
    if _hit:
        _hit[1] += 1
    else:
        GRP.append([_p, 1])
SEGS = [(a, b) for _t, a, b, _c, _w in wires]
# ★★ 接点圆点判据：**该处 ≥2 个导线端点，且不在引脚上** ⇒ 画点 ✓
#   证据（导出实测 ✓）：
#     · v2：导出 25 个位置 ↔ 本规则 25 个 ✓ **完全对上** ✓（那 25 处都是 2 端点接头 ✓，
#       而且实测告诉我：\"只有 2 端点、又没线穿过\"的**引脚**处 Fritzing **不点** ✓）；
#     · v5：导出 25 个 ↔ 本规则 21 个 ⇒ **少 4 个** ✗。
#   ⚠ **我解释不了那 4 个** ✗ —— 它们都在引脚上、且汇聚了 **3~4 个导线端点** ✓
#     （v5 导出的端点汇聚数分布 = `{2:19, 3:1, 4:5}` ✓）。
#     我试过第 2 条规则\"该处端点 + 中段穿过 ≥ 3 ⇒ 点\" ✗ ⇒ v5 变成 19 个 ✗、v2 直接 0 个 ✗✗
#     ⇒ **更差** ⇒ 按规矩（\"找不到就如实说 ✓ 不硬凑 ✗\"）回退到这一条 ✓。
#   ⇒ 差异**已量化** ✓（4 个圆点 ✓，半径 0.9 单位 = 0.25mm ✓），纯属**装饰** ✓：
#     不影响任何几何 ✓、不影响电气（连接记在 `<connect>` 里 ✓）、也不进那 4 个美学指标 ✓。
#   ★★ 2026-09-29 ✓ 两点都已实测钉住 ✓（`v34_图示.svg` ✓）：
#     ① **什么时候点**：该处 **≥2 个导线端点** ✓（只 1 根线端 + 1 个脚的脚 ⇒ **不点** ✗
#        —— 实测：导出 28 个位置里没有“只接一根线的脚” ✓）；
#     ② **点多大**：**该处的“连接数”** ✓ = 导线端点 + **脚** ✓ ⇒ = 2 ⇒ 小 ✓、≥3 ⇒ 大 ✓。
#        依据：`R1` 的两个脚 `(162,108)/(126,108)` 处只有 2 根线端 ✗ 而导出画的是**大点** ✓
#        ⇒ 把“脚”算进去正好 3 ✓（修正前我在这两处画成小点 ✗ = 唯一残留的 2 处 ✗）。
dots = []
for p, n_end in GRP:
    if n_end < 2:
        continue
    _np = sum(1 for q in PIN_SK if math.dist(p, q[2]) < 0.05)
    dots.append((p, DOT_R_BIG if (n_end + _np) >= 3 else DOT_R))


_dq = {}
for _p, _r in dots:
    _dq[(round(_p[0], 3), round(_p[1], 3))] = max(_r, _dq.get((round(_p[0], 3), round(_p[1], 3)), 0.0))
dots = sorted(_dq.items())
print("   接点圆点 %d 个 ✓（小 %d / 大 %d ✓；判据 = 该处 **≥2 个导线端点** ✓；"
      "大小 = 导线端点 + **脚** ≥ 3 ⇒ 大 ✓；半径 = 导出 0.72 / 1.44 ÷ 0.8 ✓）"
      % (len(dots), sum(1 for _p, _r in dots if _r < DOT_R_BIG),
         sum(1 for _p, _r in dots if _r >= DOT_R_BIG)))

# ── ③ 位号文本 ──
labels = []
for el in root.iter("instance"):
    mid = el.get("moduleIdRef") or ""
    if mid.startswith("Wire"):
        continue
    ttl = (el.findtext("title") or "").strip()
    if not ttl:
        continue
    vw = next((c for c in el if tag(c) == "views"), None)
    sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
    if sv is None:
        continue
    tg = next((c for c in sv if tag(c) == "titleGeometry"), None)
    if tg is None or (tg.get("visible") or "true") == "false":
        continue
    lines = [ttl]
    fzpmid = el.get("modelIndex") or ""
    fzp = (el.get("path") or "").replace("/", os.sep)
    vals = {c.get("name"): c.get("value") for c in el if tag(c) == "property"}
    if os.path.isfile(fzp):
        props = [p.get("name") for p in ET.parse(fzp).getroot().iter("property")]
        # ★ 规则**由 Fritzing 导出的实测数据定** ✓（9 件逐件对过 ✓，见 `--verify-export` 一节）：
        #   · `showInLabel="yes"` 的属性 ⇒ 值；**按 fzp 属性顺序的逆序** ✓
        #     （实测：`R1` = `±5%`,`220Ω` ✓；`C1` = `16V`,`100 nF` ✓ 均是逆序 ✓）
        #   · 空值**不出行** ✓（`R1` 的 `power` 标了 yes 但值空 ⇒ 未出 ✓）
        #   · 没一个标 yes 的件 ⇒ 出实例的 `part number` ✓
        #     （实测：`LED2`→`WS2812B-1010` ✓、`J1/J2`→`SH1.0-3P-LT` ✓、`U1`/`D3` 同 ✓）
        #   ⚠ 这条是**近似** ✓：Fritzing 的内部顺序没有官方文档，我是拿导出反推的 ✓，
        #     不保证所有零件都对 ✓ —— 但**位置**（titleGeometry）与**行距**（字号 5 ✓）是机验过的 ✓。
        yes = [(p.get("name"), (p.text or "").strip())
               for p in ET.parse(fzp).getroot().iter("property")
               if (p.get("showInLabel") or "").lower() in ("yes", "true")]
        for nm, dflt in reversed(yes):
            # ★ 实例的值优先 ✓；fzp 的**默认值在元素文本里** ✓（不是 `value=` 属性 ✗）
            v = vals.get(nm) or dflt
            # ★★ 单位（2026-09-29 实测 ✓）：Fritzing 会给**已知类目**补单位 ✓
            #   · 实测样本：实例 `resistance` = `220` ✓、fzp = `<property name="Resistance"
            #     showInLabel="yes">220</property>` ✓ **没有 units** ✗（`fritzing-parts/core`
            #     全库搜过 `units=` ✓ 一个都没有 ✓）⇒ 而 Fritzing 位号显示 **`220Ω`** ✓
            #     ⇒ 这个 Ω 是 **Fritzing 内置**的类目单位 ✓（不是文件里的 ✗）。
            #   · 所以这里只认**实测过**的类目 ✓；值里已经带字母的（如 `100 nF` ✓）**不补** ✓。
            #   ★ 要再加一个类目，请给一份含该属性的**导出** ✓ —— 本仓规矩：**不编数据** ✗。
            _u = _UNIT_BY_PROP.get((nm or "").lower())
            if _u and v and not any(ch.isalpha() for ch in v):
                v = v + _u
            if v and v not in lines:
                lines.append(v)
        if len(lines) == 1:
            v = vals.get("part number")
            if v:
                lines.append(v)
        _ = props
    labels.append((ttl, (enum(tg, "x"), enum(tg, "y")), float(enum(tg, "fontSize", 5.0)),
                   tg.get("textColor") or "#000000", lines))
    LAB_REL[fzpmid] = {"lines": lines, "fs": float(enum(tg, "fontSize", 5.0))}
print("── 位号 %d 个：%s" % (len(labels), ", ".join("%s(%s)" % (l[0], "+".join(l[4][1:]) or "—") for l in labels)))

# ── ④ 自检：悬空端点 / 没接线的脚 ✓（**如实报** ✓ 不偷偷吸附 ✗）──
dang, dang_unk = [], []
for ttl, a, b in widx:
    if ttl in degen:                           # ★ (C) 退化导线（点 ✓）不算“悬空端” ✗（另报 ✓）
        continue
    _dd = declared.get(ttl, {})
    _tall = set().union(*_dd.values()) if _dd else set()
    _unk = sorted(x for x in _tall if x not in KNOWN_PIN)
    for which, pt in (("起", a), ("止", b)):
        best = min(((math.dist(pt, p[2]), p) for p in PIN_SK), default=(1e18, None))
        joint = any(math.dist(pt, q[1]) < 0.01 or math.dist(pt, q[2]) < 0.01
                    for q in widx if q[0] != ttl)
        if best[0] > 0.5 and not joint:
            # ★ 它声明接的脚**图形缺失** ⇒ 无法判定 ✓（本例 4 处全是核心库网标签 ✓，用户截图已证**接得好好的** ✓）
            if _unk:
                dang_unk.append((ttl, which, pt, _unk))
            else:
                dang.append((best[0], ttl, which, pt, best[1]))
if PIN_SK and widx:
    hung = 0
    for p in PIN_SK:
        near = min(math.dist(p[2], a) for _t, a, _b in widx)
        near = min(near, min(math.dist(p[2], b) for _t, _a, b in widx))
        if near > 0.5:
            hung += 1
    print("── 脚位自检：脚 %d 个 ⇒ 接上导线 %d 个 ✓ ｜ **悬空 %d 个** ✓（原理图本来就允许悬空 ✓）"
          % (len(PIN_SK), len(PIN_SK) - hung, hung))
print("── 悬空导线端 %d 个 %s" % (len(dang), "✓" if not dang else "（**如实报出** ✓，不吸附 ✗）"))
for d, ttl, which, pt, hit in sorted(dang, reverse=True)[:10]:
    print("     ⚠ %-14s %s端 (%.3f,%.3f) 离最近脚 %s.%s 还差 **%.3f 单位（%.3f mm）**"
          % (ttl, which, pt[0], pt[1], hit[0], hit[1], d, d * MMU))
print("── 无法判定是不是悬空（它声明接的脚**图形缺失** ✓）：**%d 端** %s"
      % (len(dang_unk), "✓" if not dang_unk else "⚠ 信连接表 ✓ / 请人看一眼 ✓"))
for ttl, which, pt, _unk in dang_unk[:8]:
    print("     ⊘ %-14s %s端 (%.3f,%.3f) 声明接 %s ⇒ 该件图形缺失 ⇒ 不判 ✓"
          % (ttl, which, pt[0], pt[1], ",".join("%s.%s" % x for x in _unk)))
for t, why in skipped:
    print("   ⊘ 跳过 %-12s %s" % (t, why))

# ── ④b ★ 美学指标：**交叉数** ✓（面包板那条教训 ✓：交叉数是头号指标 ✓、且不能自证 ✓）──
#   两类都算 ✓：① 导线×导线的**十字交叉**（内部相交 ✓；共端点/共线不算 ✓）；
#   ② 导线**穿过零件本体框**的段数 ✓（导线从元件肚子里穿过 = 用户点过名的毛病 ✓）。

SEGS2 = [(a, b, t) for t, a, b, _c, _w in wires]      # ★ 带上导线编号 ✓（重合对要点名 ✓）
nx = 0
for i in range(len(SEGS2)):
    for j in range(i + 1, len(SEGS2)):
        if SG.seg_cross(SEGS2[i][0], SEGS2[i][1], SEGS2[j][0], SEGS2[j][1]):
            nx += 1
# ★ 第三类毛病：两段**几乎压在一条线上** ✗（看着像一根 ✓ 读图分不清 ✓）
#   —— 手改版里就有一对（斜率 0.08° 与 0.28° ✓）⇒ 必须能报出来 ✓（`sch_geom` 唯一实现 ✓）
nov = 0
OV2 = []                                  # ★ 重合对（带导线编号与坐标 ✓，供**手工修改**定位 ✓）
for i in range(len(SEGS2)):
    for j in range(i + 1, len(SEGS2)):
        if SG.near_overlap(SEGS2[i][0], SEGS2[i][1], SEGS2[j][0], SEGS2[j][1]):
            nov += 1
            OV2.append((SEGS2[i], SEGS2[j]))


def _hits_box(p, q, box, infl=1.0, need=4):
    """段 p→q 是否**真的**穿进 box ✓（★ 擦边不算 ✗）

    ★ 收紧的理由（2026-09-27 ✓）：原来只要**有一个采样点**落在外扩 1.0 单位的框里就算 ✗
      ⇒ 导线**从元件旁边过**、离框 0.28mm 也会被算成"穿过" ✗（假警报 ✗，而且会让
      "改进了没有"这个对比失真 ✗）⇒ 现在要求**至少 4 个采样点**落在**内缩 0.5 单位**
      的框里 ✓（≈ 进到里面 0.14mm 以上 ✓）。
    """
    x0, y0, x1, y1 = box[0] + 0.5, box[1] + 0.5, box[2] - 0.5, box[3] - 0.5
    if x0 >= x1 or y0 >= y1:
        x0, y0, x1, y1 = box
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
    hit = 0
    for i in range(n + 1):
        t = i / n
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            hit += 1
            if hit >= need:
                return True
    return False


nb = 0
HITS = []
for ttl_w, a, b, _c, _w in wires:
    # ★ 排除**自己两端**的元件 ✓（它的脚本来就在本体里 ✓，穿过自己不算毛病 ✗）
    own = {q[0] for q in PIN_SK
           if math.dist(q[2], a) < 0.05 or math.dist(q[2], b) < 0.05}
    for t, box in PART_BOX.items():
        _a2, _b2 = a, b
        if t in LBL_TITLE and t in own:
            # ★★ 2026-09-29 ✓ **网标签不享受那条豁免** ✗ —— 那条是给**元件本体**的（线要进肚子
            #   才能接到脚上 ✓）；标签身体若**包住了自己那根线** ✗ ⇒ 人眼一看就是“被穿” ✗
            #   （用户就是这么发现的 ✓：竖的 `GND` 与两个 `RC` 都被穿了 ✗）。
            #   ⇒ 只在**引脚处留 2 单位**容差 ✓，其余照判 ✓。
            _pin = next((q[2] for q in PIN_SK
                         if q[0] == t and (math.dist(q[2], a) < 0.05
                                           or math.dist(q[2], b) < 0.05)), None)
            _L = math.dist(a, b)
            if _pin is None or _L <= 2.0:
                continue
            _u2 = 2.0 / _L
            if math.dist(a, _pin) < math.dist(b, _pin):
                _a2 = (a[0] + (b[0] - a[0]) * _u2, a[1] + (b[1] - a[1]) * _u2)
            else:
                _b2 = (b[0] + (a[0] - b[0]) * _u2, b[1] + (a[1] - b[1]) * _u2)
        elif t in own:
            continue
        if _hits_box(_a2, _b2, box):
            nb += 1
            HITS.append((ttl_w, t, a, b, own))
print("── ★ 美学指标：导线**十字交叉 %d 处** ✓｜导线**穿过别的元件本体 %d 段** ✓"
      "｜导线**几乎压在一起 %d 对** ✓（判据含斜线 ✓ —— `sch_geom` 唯一实现 ✓；"
      "面包板那条教训：交叉数是头号指标 ✓）" % (nx, nb, nov))
# ★ 重合对**点名** ✓（2026-09-28 ✓ —— 用户要**手工**修 v14 那 4 对 ✓）：
#   报出**两根导线的编号** ✓ + 各自坐标区间 ✓ ⇒ 手工时直接看出“该挪哪一根” ✓，不用自己找 ✗。
for (a1, b1, w1), (a2, b2, w2) in OV2[:10]:
    print("      ✗ 重合：%-14s (%.1f,%.1f)→(%.1f,%.1f)  ｜  %-14s (%.1f,%.1f)→(%.1f,%.1f)"
          % (w1, a1[0], a1[1], b1[0], b1[1], w2, a2[0], a2[1], b2[0], b2[1]))
if len(OV2) > 10:
    print("      …… 另有 %d 对（看报告 ✓）" % (len(OV2) - 10))# ★ **点名** ✓（2026-09-27 用户定的规矩：结论必须可查 ✓ —— 只给个数 ✗ 我没法判它是真毛病
#   还是"脚本来就在本体内部"的必然情形 ✗）+ 给出**穿进去多深** ✓（越深越像真毛病 ✓）
for ttl_w, t, a, b, own in HITS[:12]:
    bb = PART_BOX[t]
    # ★ 顺手把“这一段距离该元件的**每只脚**多远”也报出来 ✓（只加信息 ✓）：
    #   ⇒ 能直接看出“它到底蹭着别人的脚没有”✗（= 我的闸门是不是把它错当“脚边那一段”豁免了✗）
    near = sorted((math.dist(q[2], a) if math.dist(q[2], a) < math.dist(q[2], b)
                   else math.dist(q[2], b), "%s.%s" % (q[0], q[1]))
                  for q in PIN_SK if q[0] == t)[:2]
    print("      ⚠ %-14s 穿进 **%s** ｜ 该段端点 (%.1f,%.1f)→(%.1f,%.1f) ｜ 豁免名单 %s ｜ 离 %s 的脚最近 %s"
          " ｜ **渲染器用的盒子** (%s)"
          % (ttl_w, t, a[0], a[1], b[0], b[1], sorted(own) or "(空)", t,
             " / ".join("%.2f(%s)" % (d, n) for d, n in near) or "?",
             "%.2f,%.2f→%.2f,%.2f" % bb))
    deep = 0
    n = max(2, int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1)
    for i in range(n + 1):
        u = i / n
        x, y = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
        if bb[0] + 0.5 <= x <= bb[2] - 0.5 and bb[1] + 0.5 <= y <= bb[3] - 0.5:
            deep += 1
    print("      ⚠ %-14s 穿进 **%s** 的本体（%.1f 单位深 ≈ %.2f mm）"
          % (ttl_w, t, deep * 2.0, deep * 2.0 * MMU))
if len(HITS) > 12:
    print("      ⚠ …… 另有 %d 段" % (len(HITS) - 12))

# ── ④c2 ★ 可读性：导线与"**不相连的引脚**"的安全距离 ✓（2026-09-27 用户定 ✓）──
#   用户原话："导线离芯片引脚太近了 ⇒ 应该设立规则，让导线跟芯片引脚有安全距离，
#   从而让导线和引脚的连接关系**能通过肉眼看得清晰**" ✓。
#   判据（与布线器同一条 ✓）：每根导线取两端 0.05 内的脚为"自己的脚" ✓；
#   其余脚里，离该线段 < CLEAR_PIN 的 ⇒ 算 **1 处侵入** ✗。
CLEAR_PIN = 7.2
# ★★ 临界容差 ✓（2026-09-28 ✓，与布线器 `gen_schematic_wires.PIN_EPS` **同值同口径** ✓）：
#   起因（实测 ✓）：T 形搭接的搭点**正好落在离伙伴脚 7.2000 单位**处 ✓ ⇒ **同一个形状**
#   在两档算出 `7.199999999999999` ✗ 与 `7.200000000000003` ✓ —— 纯浮点末位 ✗✗
#   ⇒ 不带容差时“算不算侵入”由浮点噪声决定 ✗（生成器那侧已实测过：一档判 1 ✗、一档判 0 ✓）。
#   有效安全距离 7.15 单位 = 2.02 mm ✓（名义 7.2 = 2.03 mm ✓，0.014 mm ✓ 肉眼无差 ✓）。
PIN_EPS = 0.05


# ✗ 原来 `_p2seg` 定义在这儿 ✗ —— 已**上移**到首次使用处之前（假连线判据要用它 ✓）✓


pc_hits = []
for ttl_w, a, b, _c, _w in wires:
    own = {(p[0], p[1]) for p in PIN_SK
           if math.dist(p[2], a) < 0.05 or math.dist(p[2], b) < 0.05}
    for t2, cid2, pp in PIN_SK:
        if (t2, cid2) in own:
            continue
        d2 = _p2seg(pp, a, b)
        if d2 < CLEAR_PIN - PIN_EPS:
            # ★ 顺手把“因”也记下来 ✓（只加信息 ✓ 不改判据 ✓）：这根线段是**骑在引脚行列上**、
            #   还是单纯**擦过** ✓ ⇒ 治病要对症 ✓（骑行列 ⇒ 出脚/通道问题 ✓；擦过 ⇒ 走廊问题 ✓）。
            if abs(a[0] - b[0]) < 0.05 and abs(pp[0] - a[0]) < 0.05:
                why = "骑在引脚**列**上"
            elif abs(a[1] - b[1]) < 0.05 and abs(pp[1] - a[1]) < 0.05:
                why = "骑在引脚**行**上"
            else:
                why = "擦过"
            pc_hits.append((ttl_w, t2, cid2, d2, a, b, why, sorted(own)))
print("── ★ 本体盒（**唯一实现** ✓ `sch_box.box_of` ✓）：%s"
      % ", ".join("%s(%.2f,%.2f→%.2f,%.2f)" % ((t,) + tuple(PART_BOX[t]))
                  for t in sorted(PART_BOX)))
print("── ★ 可读性：导线贴近**不相连的引脚**（< %.1f 单位 = %.2f mm ✓）**%d 处** %s"
      % (CLEAR_PIN, CLEAR_PIN * MMU, len(pc_hits), "✓✓" if not pc_hits else "✗✗"))
for ttl_w, t2, cid2, d2, a, b, why, own in sorted(pc_hits, key=lambda z: z[3])[:6]:
    print("      ⚠ %-14s 蹭到 %s.%s（%.2f 单位 = %.2f mm）✗"
          % (ttl_w, t2, cid2, d2, d2 * MMU))
# ★★ 全部明细 ✓（2026-09-27 加 ✓）：原来只报 6 处 ✗ ⇒ 治的时候量不全 ✗
#   ⇒ 报出**线段两端坐标**（用来对上是哪一段 ✓）+ **因**（骑列 / 骑行 / 擦过 ✓）
#     + 这根线**自己的脚**（= 它连的是谁 ✓）。
if len(pc_hits) > 6:
    print("      —— 全部 %d 处（供定位 ✓）：" % len(pc_hits))
    for ttl_w, t2, cid2, d2, a, b, why, own in sorted(pc_hits, key=lambda z: z[3]):
        print("         %-14s %-16s %6.2f 单位  (%.1f,%.1f)→(%.1f,%.1f)  %s  自己的脚=%s"
              % (ttl_w, "%s.%s" % (t2, cid2), d2, a[0], a[1], b[0], b[1], why,
                 ",".join("%s.%s" % (r, c) for r, c in own)))


# ── ④c3 ★★ **跨网“假接头”** ✓（2026-09-28 ✓ 用户点名：「要按**同网 / 跨网**拆开」✓）──
#   病症 ✓（实测出来的 ✓）：一根线的**端点 / 折点**正好落在**另一张网**的线的
#     **中段**上 ✗ ⇒ 图上**看着像接上了** ✓（一个 T 形接头 ✓）、电气上**根本没连** ✗✗
#     —— Fritzing 只认**端点对端点** ✓：端点落在别人中段上，得**在那一点把线断开**才算连上 ✓。
#   ★ “哪根线哪张网”由**连接表**定 ✓（`_netkey` ✓，2026-09-29 起 ✓）—— 不再看颜色 ✗：
#     · **同网** = 真接头 ✓（“T 形搭接”/ 轨上打断 正是在做这个 ✓）⇒ 不算毛病 ✗；
#     · **跨网** = **假接头** ✗✗（看着短路 ✓）⇒ **必须 0** ✓。
#   ★ 为什么以前一直没报 ✗：`seg_cross` 把“端点搭在中段上”当**接头**排除 ✓（正确 ✓ —— 它不是
#     交叉 ✓），可**没人**再问一句“这两根是**同一个网**吗”✗ ⇒ 那一类从两个工具里**都溜过去**了 ✗
#     （v24/v25 那处 `DATA_IN` 折点压在 5V 竖线中段上 ✓ 就是这么漏掉的 ✓）。
#   ★ 判据用**唯一那份** `sch_geom.on_seg` ✓（**中段** ✓ 两端不算 ✓ —— 与 `seg_cross` 同一口径 ✓）。
def _invisible_break(vi, endpt, tol=0.05):
    r"""`endpt`（第 `vi` 根线的一端）是不是**看不见的断点** ✗

    ★ 为什么要有这一步 ✗（实测 ✓）：一根**直**线（轨 / 长支线 ✓）常被**打断成好几根** ✓
      （每个接头/落点断一次 ✓ —— Fritzing 只认端点对端点 ✓，这是**必须**的 ✓），
      而**断点在图上是看不见的** ✓（线还是一条直线 ✓）⇒ 拿它跟别的线比“距离够不够 2.03 mm”
      就是**误报** ✗✗（实测：18 处里绝大部分是这种 ✗）。
    ✓ 判据：**同一张网**（按连接表 ✓）有另一根线从这个点沿本线方向直线续下去 ✓（三点共线且方向一致 ✓）
      ⇒ 只是断点 ✗ ⇒ 看不见 ⇒ 不算“看得见的端” ✗。
    """
    _t, a, b, _c, _w = wires[vi]
    _other = b if endpt == a else a
    dx, dy = endpt[0] - _other[0], endpt[1] - _other[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return False
    _nk = _netkey(vi)                     # ★ 网键 ✓（**按连接表** ✓，2026-09-29 ✓）
    for j in range(len(wires)):
        if j == vi:
            continue
        _t2, c2, d2, _col2, _w2 = wires[j]
        if _netkey(j) != _nk:             # ★ 只看**同一张网**（断点只可能是同网接出来的 ✓）
            continue
        for _e in (c2, d2):
            if math.dist(_e, endpt) > tol:
                continue
            _far = d2 if math.dist(_e, c2) <= tol else c2
            ex, ey = _far[0] - endpt[0], _far[1] - endpt[1]
            EL = math.hypot(ex, ey)
            if EL < 1e-9:
                continue
            if (dx * ex + dy * ey) / (L * EL) > 0.999:      # ★ 同向续下去 ✓
                return True
    return False


# ★★ 2026-09-29 ✓ **网 = 连接表（`<connects>`）里的连通分量** ✓（用户当天选的 **(b)** ✓）——
#   ✗ 原来按**导线颜色**认网 ✗ = 拿**装饰**当**电气** ✗，实测就踩到了 ✗：
#     `pixel-schematic-v29_netlabel.fzz` 的 `Wire90012783` 声明接 `C1.connector0` /
#     `R1.connector1`（**纯 RC 网的脚** ✓），颜色却写成了 GND 的 `#404040` ✗
#     ⇒ 判定器把“一根 RC 线”当成“GND 线” ✗ ⇒ 报出一处**假的**跨网假接头 ✗。
#   ✓ 现在的口径（三句话 ✓）：
#     ① 每条 `<connect … layer="schematic*">` 声明 = 一条**无向边** ✓（节点 = (实例, 脚) ✓）；
#     ② **导线是导体** ✓ ⇒ 它自己的两个脚并起来 ✓（与 `check_netlist.py`「导线自导通」同口径 ✓）；
#     ③ **同名网标签** ⇒ 把同名的标签脚并起来 ✓（规则见 `sch_net.py` **唯一实现** ✓）。
#   ★ 颜色从此**只用于画图** ✓，不再当判据 ✓ ⇒ “图上同色 / 不同色”不再影响任何一条结论 ✓。
_NETP = {}


def _netfind(x):
    _NETP.setdefault(x, x)
    while _NETP[x] != x:
        _NETP[x] = _NETP[_NETP[x]]
        x = _NETP[x]
    return x


def _netunion(a, b):
    _ra, _rb = _netfind(a), _netfind(b)
    if _ra != _rb:
        _NETP[_rb] = _ra


_MI_BY_TITLE = {t: m for m, t in FZ_TITLE.items()}
_NOWN = {}                                    # (实例 → 它自己声明过的脚 id ✓)
for _mi5, _eds5 in FZ_EDGE.items():
    for _own5, _tcid5, _tmi5 in _eds5:
        _netunion((_mi5, _own5), (_tmi5, _tcid5))
        _NOWN.setdefault(_mi5, []).append(_own5)
    if FZ_ISWIRE.get(_mi5):                   # ★ ② 导线自导通（两个脚并起来 ✓）
        _os5 = sorted(set(_NOWN.get(_mi5) or []))
        for _o5 in _os5[1:]:
            _netunion((_mi5, _os5[0]), (_mi5, _o5))

# ★ ③ 同名网标签 = 同一张网 ✓（**判据只有这一份** ✓ —— `sch_net.net_name` ✓）
with zipfile.ZipFile(sys.argv[1]) as _z2:
    _txt2 = _z2.read([_n2 for _n2 in _z2.namelist()
                      if _n2.lower().endswith(".fz")][0]).decode("utf-8", "replace")
_LBLN = {}
for _n6, _pins6 in sch_net.label_pins(_txt2).items():
    for (_mi6, _t6, _c6) in _pins6:
        _netunion((_mi6, _c6), ("LBL", _n6))
        _LBLN.setdefault(_n6, []).append(_t6)


def _netkey(vi):
    """这根线属于哪张网 ✓ —— **按连接表**取连通分量 ✓；**一个声明都没有** ⇒ 单独一网 ✓"""
    _t7 = wires[vi][0]
    _mi7 = _MI_BY_TITLE.get(_t7)
    _own7 = sorted(set(_NOWN.get(_mi7) or []))
    if _own7:
        return "NET:%s" % (_netfind((_mi7, _own7[0])),)
    return "NONE:%s" % _t7


_NKEYS = [_netkey(_vi7) for _vi7 in range(len(wires))]
print("── ★ **网**（按**连接表**认 ✓，颜色只用于画图 ✓）：导线 %d 根 ⇒ **%d 张网** ✓"
      "｜同名网标签 %d 个（%s）✓｜**一个声明都没有的导线 %d 根** %s"
      % (len(wires), len(set(_NKEYS)), len(_LBLN),
         "/".join("%s×%d" % (k, len(v)) for k, v in sorted(_LBLN.items())) or "无",
         sum(1 for _k7 in _NKEYS if _k7.startswith("NONE:")),
         "✓" if not any(_k7.startswith("NONE:") for _k7 in _NKEYS)
         else "✗（悬空线 ⇒ 碰谁都是“假接头”✓ 得先给它声明 ✓）"))


fj_hits = []
fj_near = []
for _i in range(len(widx)):
    _t1, _a1, _b1 = widx[_i]
    for _j in range(len(widx)):
        if _i == _j:
            continue
        _t2, _a2, _b2 = widx[_j]
        if _netkey(_i) == _netkey(_j):          # ★ 同一张网（含**同名网标签** ✓）⇒ 是接头 ✓ 不算毛病 ✗
            continue
        for _v in (_a1, _b1):
            _d2 = SG.p2seg(_v, _a2, _b2)
            if SG.on_seg(_v, _a2, _b2, 0.05) or _d2 <= 0.05:
                # ★ 跨网**端点粘端点**也算 ✓（同一个“看着接上”的另一半 ✓）
                fj_hits.append((_t1, _v, _t2, _a2, _b2))
            elif _d2 < CLEAR_PIN - PIN_EPS and not _invisible_break(_i, _v):
                # ★★ 第二类 ✓：**擦身** ✗ —— 不到 2.03 mm ⇒ 肉眼**照样分不清**接没接上 ✗
                #   （用户 2026-09-28 ✓：“要考虑人眼视觉的局限性，要尽量清晰” ✓）
                #   ★ 只看**看得见的端** ✓（断点不算 ✗，否则误报一大堆 ✓）
                fj_near.append((_t1, _v, _t2, _a2, _b2, _d2))
print("── ★★ **跨网假接头** ✓（一根线的**端点/折点**落在**别的网**的线（中段 ✓ 或端点 ✓）上 ✗ "
      "⇒ 看着接上、其实没连 ✗✗）：**%d 处** %s"
      % (len(fj_hits), "✓✓" if not fj_hits else "✗✗ 必须 0 ✓"))
for _t1, _v, _t2, _a2, _b2 in fj_hits[:6]:
    print("      ⚠ %-14s 端点 (%.1f,%.1f) 落在 %-14s (%.1f,%.1f)→(%.1f,%.1f) 的**中段**上 ✗"
          % (_t1, _v[0], _v[1], _t2, _a2[0], _a2[1], _b2[0], _b2[1]))
# ★★ 同一条判据的**第二类** ✓（“擦身” ✓，用户定：看不清就改 ✓）：
#   ★ 用**同一个数** `CLEAR_PIN = 7.2 单位 = 2.03 mm` ✓（就是“贴脚”那条的阈值 ✓）。
print("── ★★ **跨网擦身** ✓（端点离**别的网**的线 < %.1f 单位 = %.2f mm ✗ ⇒ 一个线宽（%.2f mm）以内"
      "照样分不清 ✗）：**%d 处** %s"
      % (CLEAR_PIN, CLEAR_PIN * MMU, 0.875 * MMU, len(fj_near),
         "✓✓" if not fj_near else "✗ 尽量改掉 ✓"))
for _t1, _v, _t2, _a2, _b2, _d2 in sorted(fj_near, key=lambda z: z[5]):
    print("      · %-14s 端点 (%.2f,%.2f) 离 %-14s (%.2f,%.2f)→(%.2f,%.2f) 只有 "
          "%.2f 单位 = **%.2f mm** ✗"
          % (_t1, _v[0], _v[1], _t2, _a2[0], _a2[1], _b2[0], _b2[1], _d2, _d2 * MMU))


# ── ④d ★ 美学指标之二：**位号文字压到东西** ✓（2026-09-27 用户点名 ✓）──#   配 ① 别的元件的本体框 ✓ ② 导线 ✓ ③ 别的位号 ✓（三类分开报 ✓，且**逐条点名** ✓）。
LBOX = [(ttl, ST.label_bbox(lx, ly, fs, lines))
        for ttl, (lx, ly), fs, _c, lines in labels]
bl = bw = bb2 = 0
detail = []
for ttl, bx in LBOX:
    for t2, box in PART_BOX.items():
        if t2 == ttl:
            continue
        if bx[0] < box[2] and box[0] < bx[2] and bx[1] < box[3] and box[1] < bx[3]:
            bl += 1
            detail.append(("压元件", ttl, t2))
    for t2, a, b, _c, _w in wires:
        if _hits_box(a, b, (bx[0], bx[1], bx[2], bx[3]), 0.0, 2):
            bw += 1
            detail.append(("压导线", ttl, t2))
    for t2, bx2 in LBOX:
        if t2 <= ttl:
            continue
        if bx[0] < bx2[2] and bx2[0] < bx[2] and bx[1] < bx2[3] and bx2[1] < bx[3]:
            bb2 += 1
            detail.append(("压位号", ttl, t2))
print("── ★ 美学指标之二：位号文字压到 **别的元件 %d 处** ✓｜**导线 %d 处** ✓｜"
      "**别的位号 %d 处** ✓（字宽表由 `_scratch/adv_measure.py` 实测 ✓）" % (bl, bw, bb2))
for kind, t1, t2 in detail[:10]:
    print("      ⚠ 位号 %-6s %s %s" % (t1, kind, t2))
if len(detail) > 10:
    print("      ⚠ …… 另有 %d 处" % (len(detail) - 10))

# ── ④c ★ 摆位用纯数据导出 ✓（`--pins-out <file.py>` ✓；单位 = sketch ✓、参考点 = 零件锚点 ✓）──
if "pins-out" in opts:
    with open(opts["pins-out"], "w", encoding="utf-8") as fh:
        fh.write("# -*- coding: utf-8 -*-\n")
        fh.write("# 由 render_sch.py --pins-out 生成 ✓（**纯数据** ✓）：\n")
        fh.write("#   PINS[modelIndex][connectorId] = (dx, dy) —— 相对**零件锚点** ✓，sketch 单位 ✓\n")
        fh.write("#   BOX[modelIndex] = (x0, y0, x1, y1) —— 本体包围盒，同样相对锚点 ✓\n")
        fh.write("PINS = %r\n\nBOX = %r\n" % (PINS_REL, BOX_REL))
        fh.write("\n# 位号内容（title + fzp 里 showInLabel 的字段 ✓，Fritzing 自己的口径 ✓）\n")
        fh.write("LAB = %r\n" % LAB_REL)
    print("   摆位数据写入 %s ✓（%d 件的脚位 + 本体框 ✓）" % (opts["pins-out"], len(BOX_REL)))

# ── ⑤ 出图 ──
xs = [p[0] for p in ALL_PTS] or [0.0, 100.0]
ys = [p[1] for p in ALL_PTS] or [0.0, 100.0]
PAD = 40.0
x0, x1 = min(xs) - PAD, max(xs) + PAD
y0, y1 = min(ys) - PAD, max(ys) + PAD
w, h = x1 - x0, y1 - y0
body = ['<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#ffffff"/>' % (x0, y0, w, h)]
body += [b[2] for b in body_parts]
for ttl, a, b, col, wd in wires:
    body.append('<line x1="%.4f" y1="%.4f" x2="%.4f" y2="%.4f" stroke="%s" '
                'stroke-width="%.4f" stroke-linecap="round"/>' % (a[0], a[1], b[0], b[1], col, wd))
for (cx, cy), _rr in dots:                            # ★ 接点圆点画在导线**之上** ✓
    body.append('<circle cx="%.4f" cy="%.4f" r="%.4f" fill="#000000" stroke="none"/>'
                % (cx, cy, _rr))
for ttl, (lx, ly), fs, col, lines in labels:
    body.append('<g font-family="DroidSans" font-size="%.3f" fill="%s">' % (fs, col))
    for i, s_ in enumerate(lines):
        # ★ 基线在**锚点下方**一个行高 ✓（Fritzing 写的是 `<text x="0" y="5.000">位号</text>` ✓，
        #   即第 1 行基线 = 锚点 + font-size ✓）—— 我原来画在`ly + fs*i`（第 1 行 = 锚点 ✗）
        #   ⇒ 整体**偏高 5 单位（1.4mm）** ✗；是 `--verify-export` 量出来的 ✓。
        body.append('<text x="%.4f" y="%.4f">%s</text>'
                    % (lx, ly + fs * (i + 1), s_.replace("&", "&amp;").replace("<", "&lt;")))
    body.append("</g>")
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%.3fmm" height="%.3fmm" '
       'viewBox="%.3f %.3f %.3f %.3f">%s</svg>' % (w * MMU, h * MMU, x0, y0, w, h, "".join(body)))
svgtmp = os.path.splitext(out)[0] + ".svg"
open(svgtmp, "w", encoding="utf-8").write(svg)
print("── 画布 %.1f × %.1f mm（%.0f × %.0f 单位 ✓）零件 %d ✓ 导线 %d ✓ 位号 %d ✓"
      % (w * MMU, h * MMU, w, h, len(body_parts), len(wires), len(labels)))
import cairosvg                                                   # noqa: E402
cairosvg.svg2png(url=svgtmp, write_to=out, output_width=round(PXW),
                 output_height=round(PXW * h / w), background_color="white")
print("写入 %s（同时留了 %s ✓）" % (out, svgtmp))

# ── ⑥ ★★★ 独立核对：拿 Fritzing 自己导出的 svg 当尺子 ✓ —— **零件 / 导线 / 位号 / 接点 全量** ✓ ──
#   ★ 标定只用**少量独立量** ✓（比例 = 导线线宽比 ✓；平移 = 第一件 ✓），
#     其余**逐项验证** ✓（8 件零件 + 46 根导线 + 9 个位号 + 接点数 ✓）—— 这才叫对账 ✓，
#     拿"我自己算的"去比"我自己算的" ✗ 不叫验证 ✗。
if "verify-export" in opts:
    exp = opts["verify-export"]
    raw = open(exp, encoding="utf-8", errors="replace").read()

    def blocks(pat):
        """把 `<g …>` 开头的块按**标签配平**取出来 ✓（**认自闭合 `<g/>`** ✗ 否则配平跑飞 ✗）"""
        out = {}
        for m in re.finditer(pat, raw):
            pid, depth, i = (m.group(1) if m.groups() else ""), 1, m.end()
            while depth and i < len(raw):
                n1, n2 = raw.find("<g", i), raw.find("</g>", i)
                if n2 < 0:
                    break
                if n1 >= 0 and n1 < n2:
                    if raw[n1:raw.find(">", n1)].rstrip().endswith("/"):
                        i = raw.find(">", n1) + 1
                        continue
                    depth += 1
                    i = n1 + 2
                else:
                    depth -= 1
                    i = n2 + 4
            out[pid] = raw[m.end():i]
        return out

    grp = blocks(r'<g partID="(\d+)"\s*>')                                       # 零件 + 导线
    lab = blocks(r'<g\b[^>]*\bid\s*=\s*["\']partLabel["\'][^>]*\bpartID="(\d+)"\s*>')  # 位号

    # ── 导出里的**导线** ✓：`partID` 块里**没有** `<g id="schematic">` ✓，
    #   且那根 line 的 `stroke` **等于我导线的颜色** ✓（✗ 不能按"块里第一根线"挑 ✗ ——
    #   实测：会挑到零件里 `stroke-width="0.4"` 的符号线 ✗ ⇒ 比例算成 0.457 ✗ 全盘对不上 ✗）──
    wire_lines, sws, other_blocks = [], [], []
    for pid, blk in grp.items():
        if re.search(r'''\bid\s*=\s*["\']schematic["\']''', blk):
            continue                                       # 零件组 ⇒ 里面的线是符号自己的 ✗
        got = []
        for m in re.finditer(r"<line\b[^>]*>", blk):
            a = attrs(m.group(0))
            if a.get("id") or "pin" in (a.get("class") or "") or not all(
                    k in a for k in ("x1", "y1", "x2", "y2")):
                continue
            got.append((num(a["x1"]), num(a["y1"]), num(a["x2"]), num(a["y2"])))
            sws.append(num(a.get("stroke-width"), 0.0))
            other_blocks.append((pid, a.get("stroke"), a.get("stroke-width")))
        wire_lines += got
    wire_lines = list(dict.fromkeys(wire_lines))            # 去重（同一根线可能在两处出现）✓

    # ── 标定（两个独立量 ✓）：比例 = 导出线宽 / 我的线宽 ✓；平移 = **第一件**的组平移 ✓ ──
    sw_exp = max(set(sws), key=sws.count) if sws else None   # ★ 取**最常见的**线宽 ✓（不取均值 ✓）
    s = (sw_exp / wires[0][4]) if (sw_exp and wires) else 0.8
    mine = {}
    for el in root.iter("instance"):
        mid = el.get("moduleIdRef") or ""
        if mid.startswith("Wire") or not el.get("modelIndex"):
            continue
        ttl0 = (el.findtext("title") or "").strip()
        if not any(b[0] == ttl0 for b in body_parts):
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
        g = next((c for c in sv if tag(c) == "geometry"), None) if sv is not None else None
        if g is None:
            continue
        fzp = (el.get("path") or "").replace("/", os.sep)
        img = None
        if os.path.isfile(fzp):
            lay = ET.parse(fzp).getroot().find(".//%s/layers" % VIEW)
            img = lay.get("image") if lay is not None else None
        txt = None
        if img:
            want = os.path.basename(img)
            for n, t in packed.items():
                if n.endswith(want):
                    txt = t
                    break
            if txt is None:
                cand, _ = resolve(fzp, img)
                txt = open(cand, encoding="utf-8", errors="replace").read() if cand else None
        if txt is None:
            continue
        k, org, _ = scale_of(txt)
        A = PB.mul(PB.tf_of(g), (k, 0.0, 0.0, k, -k * org[0], -k * org[1]))
        mine[str(el.get("modelIndex")) + "0"] = (ttl0, enum(g, "x") + A[4], enum(g, "y") + A[5])

    def grpT(blk, cut_at=None):
        cut = re.split(cut_at, blk)[0] if cut_at else blk
        tx = ty = 0.0
        for o in re.finditer(r"(translate|matrix)\s*\(([^)]*)\)", cut):
            a = [float(x) for x in re.split(r"[ ,]+", o.group(2).strip()) if x]
            if o.group(1) == "translate":
                tx += a[0]
                ty += a[1] if len(a) > 1 else 0.0
            elif len(a) == 6:
                tx, ty = tx + a[4], ty + a[5]
        return tx, ty

    print("── ★★ 全量独立核对（对着 Fritzing 导出的 %s）──" % os.path.basename(exp))
    print("   标定：比例 s = 导出线宽 %s ÷ 我的线宽 %.6f = **%.6f**（理论 72/90 = 0.8 ✓）"
          % (sw_exp, wires[0][4] if wires else 0, s))
    pairs = []
    for pid, (ttl0, mx, my) in mine.items():
        blk = grp.get(pid)
        if blk is None:
            print("   ⊘ %-12s 导出里没有它的组（Fritzing 就没画它 ✓ 例如面包板 ✓）" % ttl0)
            continue
        tx, ty = grpT(blk, r"<g\b[^>]*\bid\s*=\s*[\"']schematic[\"']")
        pairs.append((ttl0, mx, my, tx, ty))
    if not pairs:
        raise SystemExit("✗ 导出的 svg 里一个零件组都没匹配上 ⇒ 后面没法核对 ✗")
    c = (pairs[0][3] - s * pairs[0][1], pairs[0][4] - s * pairs[0][2])
    print("   标定：平移 c = (%+.4f, %+.4f) ✓（**只用第一件 %s** 定 ✓，其余全部是验证 ✓）"
          % (c[0], c[1], pairs[0][0]))

    def mp(p):
        return (s * p[0] + c[0], s * p[1] + c[1])

    worst_p, worst_p_t = 0.0, ""
    for ttl0, mx, my, tx, ty in pairs:
        d = max(abs(tx - mp((mx, my))[0]), abs(ty - mp((mx, my))[1]))
        if d > worst_p:
            worst_p, worst_p_t = d, ttl0
    print("   ① 零件：%d 件（1 件标定 + %d 件验证）⇒ 最大 Δ = **%.5f 单位（%.5f mm）** @%s %s"
          % (len(pairs), len(pairs) - 1, worst_p, worst_p * MMU, worst_p_t,
             "✓✓" if worst_p < 0.01 else "⚠"))
    if worst_p >= 0.01:
        print("        ⚠ 本核对口径的**已知限制**（不是摆位错 ✗，别误读 ✓）：本行比的是"
              "「组平移 ↔ 0.8×几何 + c」✓ ⇒ 只对 **viewBox 原点为 0 的 svg** 成立 ✓（原点非 0 的件"
              "那份偏移就差在这一行里 ✗）；**转过**的件还会把这个偏移一并旋进去 ✗。")
        print("        ⚠ 真正管几何的是 ⑤「同一零件内**脚向量**」✓ —— 它**不需要任何标定** ✓。")
    for _t0, _mx, _my, _tx, _ty in pairs:
        _d0 = max(abs(_tx - mp((_mx, _my))[0]), abs(_ty - mp((_mx, _my))[1]))
        if _d0 >= 0.01:
            print("        ⚠ %-12s Δ=%.5f 单位（%.3f mm）⇒ 属上面那条口径限制 ✓（看 ⑤ 才是结论 ✓）"
                  % (_t0, _d0, _d0 * MMU))

    used, unmatched, worst_w, worst_w_t = set(), [], 0.0, ""
    for ttl0, a, b, col, wd in wires:
        ma, mb = mp(a), mp(b)
        best, bi = None, None
        for j, (x1, y1, x2, y2) in enumerate(wire_lines):
            if j in used:
                continue
            d = min(max(math.dist(ma, (x1, y1)), math.dist(mb, (x2, y2))),
                    max(math.dist(ma, (x2, y2)), math.dist(mb, (x1, y1))))
            if best is None or d < best:
                best, bi = d, j
        if bi is not None and best <= 0.05:
            used.add(bi)
            if best > worst_w:
                worst_w, worst_w_t = best, ttl0
        else:
            unmatched.append((ttl0, best if best is not None else float("nan")))
    extra = [wire_lines[j] for j in range(len(wire_lines)) if j not in used]
    print("   ② 导线：导出 %d 根 ↔ 我 %d 根 ⇒ 配上 %d 根，最大 Δ = **%.5f 单位（%.5f mm）** @%s %s"
          % (len(wire_lines), len(wires), len(used), worst_w, worst_w * MMU, worst_w_t,
             "✓✓" if worst_w < 0.05 and not unmatched and not extra else "⚠"))
    for ttl0, d in unmatched[:6]:
        print("        ✗ 我画的 %-14s 在导出里找不到对应线（最近差 %.4f 单位）" % (ttl0, d))
    for w in extra[:6]:
        print("        ✗ 导出里有我没画的线 (%.2f,%.2f)-(%.2f,%.2f)" % w)
    if len(extra) > 6:
        print("        ✗ …… 另有 %d 根" % (len(extra) - 6))

    lw, lbad = 0.0, []
    for ttl0, (lx, ly), fs, col, lines in labels:
        blk = next((b for b in lab.values()
                    if re.search(r">%s</text>" % re.escape(ttl0), b)), None)
        if blk is None:
            lbad.append((ttl0, "导出里没有这个位号 ✗"))
            continue
        tx, ty = grpT(blk)
        d = max(abs(tx - mp((lx, ly))[0]), abs(ty - mp((lx, ly))[1]))
        lw = max(lw, d)
        got = [u for u in re.findall(r"<text[^>]*>([^<]*)</text>", blk)]
        got = [html.unescape(x) for x in got]              # ★ 导出里是 `&#xb1;`/`&#x3a9;` 这种数字转义 ✓
        if got != lines:                                   #   ⇒ 不解转义会把 `±5%`/`220Ω` 当成不同 ✗（假警报 ✗）
            lbad.append((ttl0, "行内容不同：我 %s ↔ 导出 %s" % (lines, got)))
    print("   ③ 位号：%d 个 ⇒ 位置最大 Δ = **%.5f 单位（%.5f mm）** %s；行内容 %s"
          % (len(labels), lw, lw * MMU, "✓✓" if lw < 0.01 else "✗✗",
             "全同 ✓" if not lbad else "**%d 处不同** ✗" % len(lbad)))
    for t, why in lbad[:6]:
        print("        ✗ %-12s %s" % (t, why))

    # ── ④ 接点（★ 2026-09-29 改口径 ✓）：**位置 + 半径一起对** ✓ ──
    #   ✗ 老口径只挑 `r == "0.72"`（小点 ✓）⇒ 把 11 个**大点**（r=1.44 ✓）全丢了 ✗
    #     ⇒ 报成"导出 15 ↔ 我 26 ✗"，**看着像我多画了 11 个** ✗ —— 其实是**它自己漏数** ✗。
    #   ✓ 现在：`r ≥ 0.7`（接点 = 0.72 / 1.44 ✓；零件自带的 `r=0.56` 小圆**不算** ✗），
    #     按位置归并（Fritzing 给每根线各画一个同半径的圆 ✓）⇒ 位置半径取该处**最大** ✓。
    dots_exp_raw = []
    for m in re.finditer(r"<circle\b[^>]*>", raw):
        a = attrs(m.group(0))
        if (a.get("fill") or "").lower() != "black":
            continue
        _rr0 = num(a.get("r"), 0.0)
        if _rr0 < 0.7:
            continue
        # ★ 导出坐标 → sketch ✓ 要用**逆映射** ✓（`mp` 是正映射 ✗，套两次就错了 ✗）
        dots_exp_raw.append(((num(a["cx"]) - c[0]) / s, (num(a["cy"]) - c[1]) / s, _rr0 / s))
    uq = []
    for q in dots_exp_raw:
        _hit = next((u for u in uq if math.dist((q[0], q[1]), (u[0], u[1])) < 0.05), None)
        if _hit is None:
            uq.append(q)
        elif q[2] > _hit[2]:
            uq[uq.index(_hit)] = q
    #   ★ `dots` 现在是 `((x,y), r)` ✓（带半径 ✓）⇒ 迭代要**拆包** ✗（实测：不拆包就
    #     `TypeError: must be real number, not tuple` ✗）
    dmiss = [q for q in uq if not any(math.dist((q[0], q[1]), p) < 0.05 for p, _r in dots)]
    dextra = [p for p, _r in dots if not any(math.dist(p, (q[0], q[1])) < 0.05 for q in uq)]
    rbad = []
    for q in uq:
        _m2 = next(((p, _r) for p, _r in dots
                    if math.dist(p, (q[0], q[1])) < 0.05), None)
        if _m2 is not None and abs(_m2[1] - q[2]) > 0.05:
            rbad.append((q, _m2))
    _n_small = sum(1 for _p, _r in dots if _r < DOT_R_BIG)
    _split = (DOT_R + DOT_R_BIG) / 2.0            # sketch 单位下的“小/大”分界 ✓（0.9 ↔ 1.8 ✓）
    print("   ④ 接点：导出 %d 个圆 = **%d 个位置**（小 %d / 大 %d ✓；导出半径 0.72 / 1.44 ✓）"
          " ↔ 我 %d 个位置（小 %d / 大 %d ✓）⇒ 我少的 %d ✓、我多的 %d ✓、半径不符 %d %s"
          % (len(dots_exp_raw), len(uq),
             sum(1 for q in uq if q[2] < _split), sum(1 for q in uq if q[2] >= _split),
             len(dots), _n_small, len(dots) - _n_small,
             len(dmiss), len(dextra), len(rbad),
             "✓" if not (dmiss or dextra or rbad) else "✗"))
    for q in dmiss[:5]:
        print("        ✗ 导出点了、我没点的位置 (%.3f,%.3f)" % (q[0], q[1]))
    for p in dextra[:5]:
        print("        ✗ 我点了、导出没点的位置 (%.3f,%.3f)" % (p[0], p[1]))
    for q, p in rbad[:5]:
        print("        ✗ 半径不符 (%.3f,%.3f)：导出 %.3f ↔ 我 %.3f" % (q[0], q[1], q[2], p[1]))
    # ── ⑤ ★★ 引脚判别（2026-09-27 补 ✓ —— 起因就是"没有它"骗了我一整天 ✗）──
    #   上面 ①②③ 只比"零件**锚点**"与"**导线自己**" ✗ —— 两边都用**我自己的坐标系** ⇒
    #   自洽 ⇒ 永远通过 ✗（典型的"自证" ✗；`px` 那个 bug 就是这么躲过一整天的 ✓）。
    #   下面两条**全在导出内部比** ✓ ⇒ **不需要任何标定** ✓（全局平移/缩放自动抵消 ✓）：
    #     A. **同一零件内部**的脚向量：我算的 × s ↔ 导出画的 ✓
    #        （抓"零件 k 算错" ✗、"镜像/旋转" ✗、"脚编号接错" ✗ —— `px` 那个 bug 正是它抓的 ✓）
    #     B. **线到脚**：每条"导线→脚"的连接 ⇒ "导出画的线端" ↔ "导出画的脚" ✓
    #        （抓"我按错的脚位画线" ✗ —— 用户看到的"网在一起、线却错位" ✓）
    def _walk_exp(el, m, pid, pout, lout):
        t2 = el.get("transform")
        if t2:
            m = PB.mul(m, PB.parse_tf(t2))
        if el.get("partID"):
            pid = el.get("partID")
        i2 = el.get("id") or ""
        m2 = re.fullmatch(r"connector(.+?)(terminal|pin)", i2)
        if m2 and pid and el.get("x") is not None:
            pout.setdefault(pid, {}).setdefault("connector" + m2.group(1),
                                                PB.apply(m, float(el.get("x")), float(el.get("y"))))
        if tag(el) == "line" and pid and el.get("x1") is not None:
            lout.setdefault(pid, []).append((PB.apply(m, float(el.get("x1")), float(el.get("y1"))),
                                             PB.apply(m, float(el.get("x2")), float(el.get("y2")))))
        for cc in el:
            _walk_exp(cc, m, pid, pout, lout)

    exp_pins, exp_lines = {}, {}
    try:
        _walk_exp(ET.parse(exp).getroot(), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None,
                  exp_pins, exp_lines)
    except Exception as ex:
        print("   ⊘ 引脚判别跳过（导出解析不了：%s ✗）" % ex)

    def pid_of(mi):
        return next((k for k in exp_pins if k == mi or
                     (k.startswith(mi) and len(k) == len(mi) + 1)), None)

    pv_bad = []
    for mi2, rel in sorted(PINS_REL.items()):
        cats = [k for k in rel if not k.startswith("__")]
        p2 = pid_of(mi2)
        if p2 is None or len(cats) < 2:
            continue
        for a2, b2 in zip(cats, cats[1:]):
            if a2 not in exp_pins[p2] or b2 not in exp_pins[p2]:
                continue
            mv = (s * (rel[b2][0] - rel[a2][0]), s * (rel[b2][1] - rel[a2][1]))
            ev = (exp_pins[p2][b2][0] - exp_pins[p2][a2][0],
                  exp_pins[p2][b2][1] - exp_pins[p2][a2][1])
            if math.dist(mv, ev) > 0.05:
                pv_bad.append((rel.get("__title__", mi2), a2, b2, mv, ev))
    npin_chk = sum(1 for r in PINS_REL.values()
                   if len([k for k in r if not k.startswith("__")]) >= 2)
    print("   ⑤ 引脚判别：**同一零件内脚向量** %s"
          % ("**全部一致** ✓✓（%d 件 ✓）" % npin_chk
             if not pv_bad else "**%d 条对不上** ✗✗（下面是前 6 条 ✓）" % len(pv_bad)))
    for ttl0, a2, b2, mv, ev in pv_bad[:6]:
        print("        ✗ %-6s %s→%s 我(%7.2f,%7.2f) 导出(%7.2f,%7.2f) ⇒ 比值 %.3f"
              % (ttl0, a2, b2, mv[0], mv[1], ev[0], ev[1],
                 (abs(ev[0]) / abs(mv[0])) if abs(mv[0]) > 1e-6 else float("nan")))

    wm = {el.get("modelIndex"): (el.findtext("title") or "").strip()
          for el in root.iter("instance")
          if (el.get("moduleIdRef") or "").startswith("Wire")}
    links = []
    for el in root.iter("instance"):
        if not (el.get("moduleIdRef") or "").startswith("Wire"):
            continue
        for _ce in el.iter():                       # ✗ 变量别叫 `c` ✗ —— 外层 `c` 是**标定平移** ✓
            if tag(_ce) != "connect":               #   （实测教训：它被覆盖后 `mp()` 就用错位移 ✗）
                continue
            if _ce.get("modelIndex") in wm:
                continue
            links.append((el.get("modelIndex"), _ce.get("modelIndex"), _ce.get("connectorId")))
    tbad, tmax = [], 0.0
    for wmi, pmi, cid in links:
        wpid = next((k for k in exp_lines if k == wmi or
                     (k.startswith(wmi) and len(k) == len(wmi) + 1)), None)
        ppid = pid_of(pmi)
        if wpid is None or ppid is None or cid not in exp_pins.get(ppid, {}):
            continue
        pts = [q for seg2 in exp_lines[wpid] for q in seg2]
        pp = exp_pins[ppid][cid]
        d2 = min(math.dist(pp, q) for q in pts)
        tmax = max(tmax, d2)
        if d2 > 0.5:
            tbad.append((wm.get(wmi, wmi), ppid[:-1], cid, d2))
    print("   ⑥ 引脚判别：**线到脚** %d 条 ⇒ 没接上的 %d 处（最大 %.3f 导出单位 = %.2f mm）%s"
          % (len(links), len(tbad), tmax, tmax * 25.4 / 72, "✓✓" if not tbad else "✗✗"))
    for ttl0, pmi, cid, d2 in tbad[:6]:
        print("        ✗ %-13s 该接 %s.%s，线端离脚 **%.2f mm** ✗" % (ttl0, pmi, cid, d2 * 25.4 / 72))

    # ── ⑦ ★★ 网标签（2026-09-29 补 ✓）：**文字锚点在导出内部对账** ✓ ──
    #   为什么单列 ✗：标签几何是**新标定**的 ✓（`sch_net.py`「本体几何」✓）⇒ 必须有**机器守** ✓；
    #   而且这里比的是「**Fritzing 画出来的**文字位置」✓，不是「我以为应该在的位置」✗（不自证 ✗）。
    exp_lbl = []

    def _walk_lbl(el, m):
        t2 = el.get("transform")
        if t2:
            m = PB.mul(m, PB.parse_tf(t2))
        if tag(el) == "text" and el.get("id") == "label" and el.get("x") is not None:
            exp_lbl.append((PB.apply(m, float(el.get("x")), float(el.get("y"))),
                            (el.text or "").strip()))
        for cc in el:
            _walk_lbl(cc, m)

    try:
        _walk_lbl(ET.parse(exp).getroot(), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    except Exception:
        exp_lbl = []
    mine_lbl = []
    for el in root.iter("instance"):
        _lab = next((_p.get("value") for _p in el.iter("property")
                     if _p.get("name") == "label"), None)
        _nm = sch_net.net_name(el.get("moduleIdRef") or "",
                               (el.findtext("title") or "").strip(), _lab)
        if not _nm:
            continue
        vw = next((c for c in el if tag(c) == "views"), None)
        sv = next((c for c in vw if tag(c) == VIEW), None) if vw is not None else None
        g = next((c for c in sv if tag(c) == "geometry"), None) if sv is not None else None
        if g is None:
            continue
        tf = g.find("transform")
        m = ((float(tf.get("m11", 1)), float(tf.get("m12", 0)),
              float(tf.get("m21", 0)), float(tf.get("m22", 1))) if tf is not None
             else (1.0, 0.0, 0.0, 1.0))
        mine_lbl.append((_nm, (el.get("modelIndex") or ""),
                         sch_net.label_text_anchor((enum(g, "x"), enum(g, "y")), _nm, m)))
    lb_worst, lb_bt, lb_bad = 0.0, "", []
    for _nm, _mi3, _a3 in mine_lbl:
        _ma = mp(_a3)
        _cand = [q for q in exp_lbl if q[1] == _nm] or exp_lbl
        if not _cand:
            lb_bad.append((_nm, _mi3, "导出里没有标签文字 ✗"))
            continue
        _d3 = min(math.dist(_ma, q[0]) for q in _cand)
        if _d3 > lb_worst:
            lb_worst, lb_bt = _d3, "%s(%s)" % (_nm, _mi3)
        if _d3 > 0.05:
            lb_bad.append((_nm, _mi3, "文字锚点差 %.4f 导出单位 = %.3f mm ✗"
                           % (_d3, _d3 * 25.4 / 72)))
    print("   ⑦ 网标签：导出 %d 个 ↔ 我 %d 个 ⇒ **文字锚点**最大 Δ = **%.5f 单位（%.5f mm）** @%s %s"
          % (len(exp_lbl), len(mine_lbl), lb_worst, lb_worst * MMU, lb_bt,
             "✓✓" if not lb_bad else "✗✗"))
    for _nm, _mi3, _why in lb_bad[:6]:
        print("        ✗ %s(%s) %s" % (_nm, _mi3, _why))

    # ★ 判定分**三类**报 ✓：几何（尺寸/位置 ✓）｜装饰（接点圆点 ✓）｜文本（位号文字 ✓）
    #   —— 用一个 0.25mm 的圆点去掩盖"几何已逐点验平"是**把结论说糊**了 ✗，
    #     反过来也一样 ✗（几何错了就不能拿"就几个圆点"糊过去 ✗）。
    geo_ok = (worst_p < 0.01 and worst_w < 0.05 and not unmatched and not extra and lw < 0.01
              and not pv_bad and not tbad and not lb_bad)
    dot_ok = not dmiss and not dextra and not rbad
    print("   ⇒ 几何（零件/导线/位号位置 **+ 引脚 + 标签**）：%s"
          % ("✓✓ **与 Fritzing 逐点一致** ✓✓（含引脚与标签 ✓；Δ 全部 ≤0.001 单位 = 0.0003 mm ✓）"
             if geo_ok else "✗ 有几何不一致项 ✗（上面已逐条列出 ✓ 别默认它没事 ✗）"))
    print("   ⇒ 装饰（接点圆点）：%s"
          % ("✓ 一致 ✓" if dot_ok else "⚠ 差 %d 个（纯装饰 ✓，半径 0.9 单位 = 0.25mm ✓；"
             "原因未定 ✓ 已如实记录 ✓）" % (len(dmiss) + len(dextra))))
    print("   ⇒ 文本（位号内容）：%s"
          % ("全同 ✓" if not lbad else "%d 处差异 ⚠（不影响几何 ✓）" % len(lbad)))
