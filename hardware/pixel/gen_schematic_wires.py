# -*- coding: utf-8 -*-
r"""全接线布线：正交（0°/90°）折线 → 每段一根实体导线 ✓（不再用网标签 ✗）

依据（2026-09-26 从源码 + 用户自己的 sketch 取证 ✓，详见 tools/README.md）：
  · 导线折点：Fritzing **没有**折线导线 ✗ —— 只有「两点直线」✓ 或「两点 + <bezier>」曲线 ✓
    （`items/wire.cpp:856` 调 `m_bezier->write()`；`utils/bezier.cpp:195` 写
     `<bezier><cp0 x y/><cp1 x y/></bezier>`）
    ⇒ **直角拐弯 = 两段导线端点相接** ✓（端点相接即电气相连 ✓）
  · junction **不存文件** ✗，由连接图推出（`wire.cpp:1449` `collectDirectWires`），
    只在 **>2 根线** 交汇处画圆点 ✓ ⇒ 用"两两相连的链"接法就不会出现 junction 点 ✓
  · 连接仍是**连接器级、两端各记一份** ✓

用法：
  py -3.13 f:\git\_scratch\route_build.py <干净画布.fzz> <尺子.svg> <输出.fzz> [--preview 预览.svg]
"""
import copy
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SCRATCH = os.path.dirname(os.path.abspath(__file__))
# ★★ 2026-09-27（用户定 ✓）：通用工具只有一份，在**库仓 tools/** ✓（定位见 `toolpaths.py` ✓）
import toolpaths                                 # noqa: E402
import part_measure as pm                       # noqa: E402
import sch_geom as SG                           # ★ 几何判据（唯一实现 ✓，含斜线 ✓）
import sch_text as ST                           # ★ 字宽表（与渲染器、摆位脚本同一份 ✓）
import pins_ref as PR                           # ★ 生成的位号数据（行/字号 ✓，入库 ✓）
from pin_ruler import apply, mul, parse_tf       # noqa: E402
# ★★ “本体盒”的唯一实现 ✓（2026-09-27 ✓）—— 必须放在 `import toolpaths` **之后** ✓
#   （`part_box` 在库仓那边 ✓，路由靠 `toolpaths` 把路径接好 ✓）。
#   ✗ 原来本文件自己 walk 尺子 svg 算盒 ✗ ⇒ 实测与判据（渲染器）差 **0.43 单位** ✗ ⇒
#     硬闸门物理上看不见判据报的那一段 ✗✗（详见 `sch_box.py` 开头那段血教训 ✓）。
import part_box as PB                           # noqa: E402
import sch_box as SB
import sch_net                                  # ★ 网标签规则（**唯一实现** ✓）                            # noqa: E402

# ── 网表（照 `hardware/pixel/pixel-netlist.md` §2 ✓；脚名按 .fzp 的连接器名，
#    大小写不敏感 ✓；"#N" = 第 N 个脚（core 件没有名字 ✓））────────────────────────
NETS = {
    "COIL_A":   [("L1", "inner"), ("D3", "AC1")],
    "COIL_B":   [("L1", "outer"), ("D3", "AC2")],
    "GND":      [("D3", "A1"), ("D3", "A2"), ("C1", "#2"), ("U1", "VSS"), ("C2", "#2"),
                 ("LED2", "GND"), ("J1", "#2"), ("J2", "#2"),
     # ★ 裸焊盘/底板必须接地（2026-09-26 用户定 ✓）：原来写成"独立成网、单脚网无线"是错的 ✗
     #   —— EPAD 要**接到 GND** ✓（原理图上就接过来 ✓；元件库里它仍是独立脚 ✓ 见 AGENTS §5 ✓）
                 ("U1", "EPAD")],
    "BR+":      [("D3", "C1"), ("D3", "C2"), ("R1", "#1")],
    "RC":       [("R1", "#2"), ("C1", "#1"), ("U1", "PA1")],
    "5V":       [("U1", "VDD"), ("C2", "#1"), ("LED2", "VDD"), ("J1", "#1"), ("J2", "#1")],
    "DATA_IN":  [("U1", "PA2"), ("J1", "#3")],
    "DATA_OUT": [("U1", "PD0"), ("J2", "#3")],
    "LED_DIN":  [("U1", "PC6"), ("LED2", "DI")],
}


def build_ruler(svg):
    r"""从 Fritzing 导出的 SVG 建"尺子"：partID → {绘图原点, 各脚坐标}（导出坐标 ✓）

    注：这套坐标只用于**元件内部**的相对量取 ✓；跨元件的绝对换算必须用 recal_pins.py
    从渲染反推的全局映射 ✗（2026-09-26 踩坑：逐元件公式跨元件不成立 ✓）。
    """
    root = ET.parse(svg).getroot()
    ruler = {}
    # ★★★ 2026-10-04 ✓ **没有 `partID` 的终端**（core 件：地符号 ✓ / 网标签 ✓）
    #   ✗ 病（实测 ✓）：`Ground1`/`Ground2` 的原理图 svg 来自 **Fritzing 安装目录的 core 件**
    #     （`path=":/resources/parts/core/ground.fzp"` ✗ —— 包内**没有**它们的 svg 副本 ✗，
    #      磁盘上也搜不到 ✗）⇒ 渲染器认不出它 ✗ ⇒ 尺子里它的终端**没有 `partID`** ✗
    #     ⇒ `pin_of` 报「导出里没有 @90012780 的 connector0」✗（本次真踩 ✓）。
    #   ✓ 但它**在尺子里** ✓（实测：`<g id="connector0terminal" x="6.728" y="0">` ✓ ——
    #     正是 core `ground.svg` 里那个 `rect x=6.728 y=0 w=0.945 h=0.953` ✓）
    #     ⇒ 收进 `orphan` ✓，下面由**离它最近的、解析不到脚位的实例**认领 ✓（例：两个地符号 ✓）。
    orphan = []
    # ★★ 备用池 `soft` ✓（2026-10-04 ✓）：**有 `partID`、但元素本身没有 `x/y`** 的终端 ✓。
    #   ✗ 实测病：`RC` 网标签的终端**不在 `ruler` 里** ✗（认领时最近还有 72.75 单位 ✗）
    #     ⇒ 它的 `connector0pin/terminal` 大概是 `<line>`/`<path>` ✗（没有 `x/y` ✗）
    #     ⇒ 上面那句 `el.get("x") is not None` 直接把它**跳过**了 ✗。
    #   ★ 只做**备用** ✓（不动主表 `ruler` ✗）—— 否则会改变**其它网**现有那些脚位的取法 ✗
    #     （那些件全都有小方块 `connectorNterminal` ✓，本来就走得很准 ✓，不该动 ✗）。
    soft = {}
    # ★★ 终端方块的中心 ✓（`<rect id="connectorNterminal">` 的 x+w/2 ✓）—— 用来挑
    #   “引脚线的哪个端点是**真脚点**” ✓（见下 ✓）。
    term_c = {}
    # ★★ 实例分组号 ✓（`schematic` 组出现一次 +1 ✓）—— 池子去重必须**按实例** ✗：
    #   两个地符号都叫 `connector0` ✗ ⇒ 按 cid 全局去重会把第二个**误删** ✗
    #   （实测：池里只剩 1 个 ✗ ⇒ `Ground2` 接不上 ✗）。
    _grp = [0]

    def _segs_of(el):
        r"""把 `<line>` / 简单 `<path d="M x,y[v dy|h dx]">` 的**两个端点**读出来 ✓

        ✗ 为什么必须这么读（实测踩的 ✗）：core `ground.svg` 的脚点是
          `<path id="connector0pin" d="M7.201,7.575v-7.2"/>` ✗ —— 拿**终端方块的
          `x/y`（= 左上角 ✗）当脚点，会**差 0.17mm** ✗ ⇒ Fritzing 里又显示“没接上”✗✗；
          而按“**离方块中心最近的端点**”取 ✓ ⇒ 实测得 **`(161.328,166.801)`** ✓
          = 用户在 Fritzing 里亲手连的那根线的端点 ✓✓（`Wire90012781` ✓，逐字节对得上 ✓）。
        """
        if tag(el) == "line" and el.get("x1") is not None:
            return [(float(el.get("x1")), float(el.get("y1"))),
                    (float(el.get("x2")), float(el.get("y2")))]
        _d = (el.get("d") or "").strip()
        _m = re.fullmatch(r"M\s*(-?[\d.]+)\s*,?\s*(-?[\d.]+)\s*[vV]\s*(-?[\d.]+)", _d)
        if _m:
            _x, _y, _dy = (float(_m.group(1)), float(_m.group(2)), float(_m.group(3)))
            return [(_x, _y), (_x, _y + _dy)]
        _m = re.fullmatch(r"M\s*(-?[\d.]+)\s*,?\s*(-?[\d.]+)\s*[hH]\s*(-?[\d.]+)", _d)
        if _m:
            _x, _y, _dx = (float(_m.group(1)), float(_m.group(2)), float(_m.group(3)))
            return [(_x, _y), (_x + _dx, _y)]
        return []

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("id") == "schematic":
            _grp[0] += 1                 # ★ 每个实例的 `schematic` 组 = 一个实例 ✓
        _g2 = _grp[0]
        if el.get("partID"):
            pid = el.get("partID")
            ruler.setdefault(pid, {"origin": None, "pins": {}})
        if pid in ruler and el.get("id") == "schematic" and ruler[pid]["origin"] is None:
            ruler[pid]["origin"] = apply(m2, 0, 0)
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm:
            _cid = "connector" + mm.group(1)
            _is_term = mm.group(2) == "terminal"
            _pt = None
            if _is_term and el.get("x") is not None:
                _cx2 = float(el.get("x")) + float(el.get("width") or 0) / 2.0
                _cy2 = float(el.get("y")) + float(el.get("height") or 0) / 2.0
                term_c[_cid] = apply(m2, _cx2, _cy2)
                _pt = apply(m2, float(el.get("x")), float(el.get("y")))
            elif not _is_term:
                _ends = _segs_of(el)
                if _ends and _cid in term_c:
                    _tgt2 = term_c[_cid]
                    _x2 = [(math.dist(apply(m2, _a2, _b2), _tgt2), _a2, _b2) for _a2, _b2 in _ends]
                    _sc2 = min(_x2)[1:]
                    _pt = apply(m2, _sc2[0], _sc2[1])
                elif _ends:
                    _pt = apply(m2, _ends[-1][0], _ends[-1][1])
            if _pt is None:
                pass
            elif _is_term:
                if pid in ruler:
                    ruler[pid]["pins"].setdefault(_cid, _pt)
                elif not any(_c3 == _cid and _g3 == _g2 for _c3, _p3, _g3 in orphan):
                    # ★★ 往池子里放的是**终端方块的中心** ✓ —— ✗ 不是它的左上角 ✗：
                    #   实测（拿用户手画原图标定 ✓）：地符号真脚点 = **`(161.328,166.801)`** ✓
                    #   （= 用户在 Fritzing 里亲手连的那根线的端点 ✓）；而方块**左上角**偏 0.47 单位
                    #   （**0.13mm** ✗）；**中心**只差 **0.036mm** ✓ ⇒ 落在终端的命中矩形里 ✓。
                    #   ★ 验证点 ✓：认领日志里的距离应当是 **9.02**（= 原点→真脚点 ✓），
                    #     如果还是 **8.41**（= 原点→方块左上角 ✗）就说明这一段没生效 ✗。
                    orphan.append((_cid, term_c.get(_cid) or _pt, _g2))
            else:
                # ★★ 只填**两个备用池** ✗ —— **绝不覆盖主表** ✗✗（2026-10-04 实测踩的 ✗）：
                #   ✗ 我第一版顺手写了 `ruler[pid]["pins"][cid] = _pt` ✗ ⇒ **所有元件**的脚位
                #     都被换成“引脚线端点” ✗ ⇒ 实测导线 49 → **56 根** ✗、总长 612 → **769 mm** ✗✗
                #     （全图都变了 ✗）—— 正是“**只改点名的那个**”那条规矩的反面教材 ✗。
                #   ✓ 本步的**唯一目的**是给 core 件（地符号 ✓）补脚位 ✓ ⇒ 只动池子 ✓。
                if pid and not ruler.get(pid, {}).get("pins"):
                    soft.setdefault(pid, {})[_cid] = _pt
                elif not pid:
                    for _j3, (_c3, _p3, _g3) in enumerate(orphan):
                        if _c3 == _cid and _g3 == _g2:
                            orphan[_j3] = (_cid, _pt, _g2)  # ★ 同实例内有 ⇒ **改用引脚线端点** ✓
                            break
                    else:
                        orphan.append((_cid, _pt, _g2))     # ★ 没有 ⇒ **先放进去** ✓（比方块准 ✓）
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)
    return ruler, orphan, soft

RATIO = 1.25
CLEAR = 6.0            # 导线离元件本体至少留这么远（sketch 单位；6 ≈ 1.7mm ✓）
# ★ 走廊偏移 ✓。✗ 试过“加密到每 6 单位一条（8 条）” ✗ ⇒ **一对都没少** ✗（仍 7 对、逐条相同 ✓）
#   ⇒ 证明病根**不是通道不够** ✓（见下：是贪婪抢占 ✗）。已退回 4 条 ✓ 不添无用改动 ✓。
CH_OFFS = (CLEAR, 12.0, 22.0, 34.0)
DIAG_PEN = 1.25        # ★ 斜线的小罚分（“长度 × 1.25 才等于” ✓）
# ★★ K：一个“交集”值多少长度 ✓（面包板规则 ⑧ ✓：**K = 10mm/交集** ✓）
#   —— 这是**人为选的经验值** ✓（不是从数据推的 ✗），**是个可以调的系数** ✓：
#     调大 = 更看重少交叉 ✓；调小 = 更看重短而直 ✓。代码里就这一行 ✓。
#   单位换算：10mm × 3.5433 = **35.4 sketch 单位** ✓。
K_INTER = 35.4
# ★★ K_OUT：**一根线跑到"所有零件包围盒之外"的那部分长度**值多少倍 ✓
#   （2026-09-27 ✓，从**用户手改版**里学来的性格 ✓）
#   ✗ 我的 v8 有一根线先向左跑 **61 单位**（比 J1 还左 ✗）再横着回来 ⇒
#     画布被撑到 90.9×90.5mm ✗、中间空出一大块 ✗、还横穿 3 根线 ✗（用户：“扎眼” ✗）；
#   ✓ 他的手改版：画布 **78.7×83.1mm** ✓、每根线都待在零件之间 ✓。
#   ⇒ 跑出去的长度按 K_OUT 倍罚 ✓（只罚“出去”那一段 ✓，出界一点点（标签/45° 小拐角）不受怨 ✓）。
K_OUT = 10.0
OUT_MARGIN = 7.2      # 包围盒外扩（1 格 ✓）：小出界不算往外跑 ✓

# ★★ **每根导线的颜色 = 按网络** ✓（2026-09-28 ✓ —— 抄自**用户手改版**的做法 ✓）
#   用户那一版 9 个网**各有各的色** ✓（红/黑/橙/紫/青/绿/蓝/棕/粉 ✓）⇒ 一眼能分清谁是谁 ✓；
#   我的自动版**全一个灰 `#404040`** ✗ ⇒ 读图的人得顺着线摸 ✗。
#   ★ 色值 = **原理图那一节**的官方值 ✓（`fritzing-app/resources/ratsnestcolors.xml`
#     → `<view name="schematicView">` ✓）—— ✗ **不是**面包板那节 ✗（2026-09-28 ✓ 教训：
#     我拿面包板的表去判原理图的线色 ⇒ **误报用户** ✗：原理图橙 = **`#ff7300`** ✓，
#     而 `#ef6100` 在原理图里是 `<obsolete>` 作废值 ✗；同一名字**两个视图不同值** ✓）。
#   ★ 约定**照官方 XML 自己的声明** ✓：`black` 下挂 `connector name="gnd"` ✓、
#     `red` 下挂 `3v3`/`+5v` ✓ ⇒ **GND = 黑 `#404040` ✓、5V = 红 `#cc1414` ✓**。
#   ★★ 具体配色**照抄本项目面包板那一套** ✓（用户 2026-09-28 明确 ✓：「我选的线的颜色，
#      跟你画的面包板里完全一致」✓；权威表在 `bb_route4.py:COLOR` ✓ + `breadboard-wiring.md`
#      的颜色表 ✓）—— ✗ **不要**自己按顺序另配一套 ✗（我第一版就是这么干的 ✗，与用户不一致 ✗）。
#   ★ **同一个名字（orange）两个视图取值不同** ✓：面包板 `#ef6100` ✓、**原理图 `#ff7300`** ✓
#     ⇒ 这里取**原理图**的值 ✓（用户手改版里就是 `#ff7300` ✓ 实测 ✓）。
SCHEM_PALETTE = ["#418dd9", "#25cc35", "#fff800", "#999999", "#ff7300",
                 "#a37911", "#33ffc5", "#ab58a2", "#8c3b00", "#fa50e6", "#ffffff"]
NET_COLOR = {
    "GND":      "#404040",     # 黑 ✓（官方 black 的 wire 值 ✓，不是 #000000 ✗）
    "5V":       "#cc1414",     # 红 ✓
    "DATA_IN":  "#418dd9",     # 蓝
    "DATA_OUT": "#33ffc5",     # 青
    "LED_DIN":  "#25cc35",     # 绿
    "RC":       "#ff7300",     # 橙（面包板表写 #ef6100 ✓；**原理图**官方值 = #ff7300 ✓）
    "BR+":      "#ab58a2",     # 紫
    "COIL_A":   "#8c3b00",     # 棕
    "COIL_B":   "#fa50e6",     # 粉
}
for _i, _n in enumerate(sorted(N for N in NETS if N not in NET_COLOR)):   # 兜底：新增网按序分色 ✓
    NET_COLOR[_n] = SCHEM_PALETTE[_i % len(SCHEM_PALETTE)]
# ★★ `CLEAR_PIN`：**导线与“不相连的引脚”之间要留的安全距离** ✓（2026-09-27 用户定 ✓）
#   用户原话："导线离芯片引脚太近了 ⇒ 应该有安全距离，让导线和引脚的连接关系**肉眼看得清**" ✓。
#   实测（把导出放大看 ✓）：U1 右侧 `14/15/12/11` 的**引脚线末端正好落在导线上** ✗、
#   上侧 `20..16` 与下侧 `7..10` 那么贴着导线 ✗ ⇒ 谁接了、谁没接，**图上分不出来** ✗。
#   取 **1 格（7.2 单位 = 2.03mm）** ✓（引脚间距本身是 9∼15 单位 ✓ ⇒ 7.2 能既留出可辨的距离、
#   又不会无路可走 ✓）。规则放在**交叉数之前**的档位 ✓（它是可读性规则 ✓ 不是审美点缀 ✓）。
CLEAR_PIN = 7.2
ESC_PIN = CLEAR_PIN + 5.0      # 第一条出脚长度 ✓（= 出去就已超过安全距离 ✓）
# ★★ `ESC_OFFS`：**沿引脚法线出脚的长度**（两档 ✓ = 两条平行车道 ✓）
#   （2026-09-27 ✓ —— 用户两条规则的**机器化**：① 导线与不相连的引脚要有安全距离 ✓
#     ② 不同的导线不能重叠 ✓。两个病根是**同一个** ✓：主干直接**骑在引脚行列上** ✗。）
#   ★★ 病史（三错一改 ✓，全写在里，不要重犯 ✗）：
#     ✗ 错 1（早先）：只给**一条**逃出通道（`ESC_PIN` 单值 ✓）⇒ 侵入 13 → **15** ✗（回退 ✓）；
#       当时我以为病根是“主干挤同一条车道” ✗（把两个现象接上了，但不完整 ✗）。
#     ✗ 错 2：把“引脚列 ± ESC_OFFS”当成**普通通道**加进 `chx/chy` ✗ ⇒
#        实测**四档（0 / 12.2 / 12.2,19.4 / ×3）结果一字节不差** ✗✗ —— **完全无效** ✗。
#     ✗ 错 3（我当时的推断）：以为是被前面的档位一票否决 ✗ ⇒ 去写探针 ✓（而不是去改档位 ✗）✓。
#     ✓ `--why` 探针给出了真相 ✓（第一次就问准了 ✓）：
#        `GND U1.connector3→U1.connector20` 选中与亚军**贴脚都是 3** ✗ ⇒
#        **根本没有一条候选能把 3 降下来** ✗ —— 不是档位问题 ✗，是**形状缺一种** ✗：
#        · `[a,(x,a1),(x,b1),b]` 的**末段是横线** ⇒ 目标脚在**底排**时它**正好沿着底排引脚行**跑 ✗；
#        · `[a,(a0,y),(b0,y),b]` 的**首段是竖线** ⇒ 起点在**左排**时它**正好沿着左排引脚列**跑 ✗。
#     ✓ 正解 = **先沿引脚法线出脚 ✓ → 走“干净的”通道 ✓ → 再沿法线拐进脚 ✓**
#        （= `esc_cands` ✓），且通道集里**不放任何引脚坐标** ✓（`chx_clean/chy_clean` ✓）。
#     ★ 另有一处必须一起改 ✓（否则新形状还是用不上 ✗，实测推理 ✓）：
#        出脚必然要**绕到别的元件附近**（例：从 U1 左排往左出，就靠近 J1 ✓）⇒
#        我那条代理规则“离别的元件 6 单位以内算碰”排在第 2 档 ✗ ⇒ **会一票否决出脚** ✗。
#        ⇒ 把这条**我自己加的代理规则**降到用户规则（贴脚+重叠 ✓）之后 ✓（新增次序 ✓）。
#        两处都有实验开关可以分开测 ✓（`--esc` / `--neworder` ✓）⇒ 归因不靠猜 ✓。
ESC_OFFS = (ESC_PIN, ESC_PIN + 7.2)
# ★★ `USE_ESC` / `NEW_ORDER`：**默认都开** ✓（2026-09-27 **用户决定** ✓：“**重叠 0 优先**” ✓）
#   ★ 四档实测（`_scratch/run_esc2.py` ✓ 一次跑完 ✓，同一摆位 / 同一套判据 ✓）：
#     A 旧形状+旧次序（= v14 基线）  重叠 5 ｜ 贴脚 13 ｜ 交叉 13 ｜ **穿体 0** ✓
#     B 只开 `USE_ESC`            **与 A 一字节不差** ✗ ⇒ 出脚候选**全被代理规则否决** ✗（解释被证实 ✓）
#     D 只开 `NEW_ORDER`          重叠 2 ｜ 贴脚 11 ✓ ｜ 交叉 **15** ✗ ｜ **穿体 4** ✗
#     C 两个都开                  重叠 **0** ✓✓ ｜ 贴脚 11 ｜ 交叉 **16** ✗ ｜ **穿体 5** ✗ ｜ 位号压线 **4** ✗
#   ★ 所以这两处不是“技术修补” ✓ —— 它们是**规则之间的取舍** ✗：
#     要让主干**离开引脚列**（= 安全距离 ✓，也是“不重叠”的前提 ✓）⇒ 它就得**借道别的元件旁边的空地** ✓
#     （实测：从 U1 左排往左出，必经 J1 旁边 ✓）；而我那条代理规则“离任何元件 6 单位以内算碰” ✗
#     ⇒ **天然冲突、二选一** ✓ ⇒ 不能我偷着选 ✗ ⇒ 已问过用户 ✓：
#     **用户选“重叠 0 优先”** ✓（接受 穿体 5 / 交叉 16 / 位号压线 4 的代价 ✓）⇒ 两个开关**默认开** ✓。
#   ★ 待办 ✓（用户同一次定的 ✓）：**贴脚要降到个位数** ✓（现在 11 ✗）—— 下一轮单独量、单独治 ✓。
#   ★ 基线随时可回 ✓：`--noesc --oldorder`（= A ✓，实测与 v14 一字节不差 ✓）。
# ★★ `HARD_BODY`：**硬闸门** —— 非“脚边一小段”的部分不许进入别的元件本体 ✓
#   （2026-09-27 ✓ 用户定「穿体必须是 0」✓；例外与判据见 `body_hard_bad` ✓）
#   ★★ 实测结论（2026-09-27 ✓，**盒子对齐之后**的干净数据 ✓）：
#     打开它 ⇒ 穿体 **8** ✗（v15 是 6 ✗）、**68 对网“找不到候选”** ✗✗ ⇒
#       **反而变差** ✓ —— 因为闸门删到没路时只能兜底退回旧候选集 ✓。
#     而 v14 曾经做到**穿体 0** ✓（不靠闸门 ✓，靠**代价函数自己躲** ✓ = 旧档位次序 ✓）。
#     ⇒ 所以“重叠 0”与“穿体 0”**在当前候选集 + 当前摆位下不能兼得** ✓（两版都有硬数据 ✓）：
#         v14 = 穿体 0 ✓ / 重叠 4 ✗；v15 = 重叠 0 ✓ / 穿体 6 ✗；硬闸门 = 两者都做不到 ✗。
#   ⇒ **默认关** ✓（保持 v15 的干净基线 ✓）；留 `--hardbody` 供以后配合“换拓扑/换候选集”再试 ✓。
HARD_BODY = False
# ★★ `OTHER_BODY`：**不许钻“别人的”元件肚子** ✓（2026-09-28 ✓，判据与 `hits_own_body` 同一个 ✓）
#   ★ 用法与 `HARD_BODY` 的**区别是关键** ✓：`HARD_BODY` 是“**只删候选**”✗ ⇒ 实测删到没路 ⇒
#     兜底退回旧候选集 ⇒ 反而更差 ✗（68 对“找不到候选” ✗）。`OTHER_BODY` 是**软代价 + 字典序第一档** ✓
#     ⇒ 候选一条不删 ✓；“全都没路”时各候选该项都非 0 ⇒ 自然退化回现状 ✓ **不会更差** ✓。
#   ★ 病根（`--otherbody` 那一大段实测证据写在 `hits_other_body` 的 docstring 里 ✓）。
#   ★ 默认**关** ✓ ⇒ v18 仍可逐项复现 ✓。
OTHER_BODY = False
# ★★ `ONLY_NETS`（`--only=GND,5V` ✓，2026-09-28 ✓ 用户要求「**请先在图上实际画出天地轨来**」✓）：
#   只布指定的网 ✓ ⇒ 先出一个**中间产物**：**天地轨 + 元件 + 电源支线** ✓，信号线留到下一轮 ✓。
#   ★ 这是用户那条新逻辑的第 ①～③ 步 ✓（先画天地轨 ✓ → 排元件 ✓ → 只连 5V/GND ✓）。
#   ★ 顺序不变 ✓（`POWER_FIRST` 仍在最前 ✓）；只是**后面那些网整批不布** ✓。
#   ⚠ 中间产物**不能用出厂检查评价** ✗：`check_netlist` 会报“网对不上”✓、
#     渲染器会报很多“悬空导线端”✓ —— 那是**故意的** ✓（信号还没连呢 ✓）。
ONLY_NETS = None
# ★★ `HARD_PIN`：**线不许落在“别的脚”上** ✓（2026-09-28 ✓ 用户发现 v14 有 **9 处线身穿心** ✗）
#   病症（实测 ✓，`_scratch/fake_conn.py` ✓）：一根竖线正好从 `U1` 左排三只脚的**坐标点**上
#     穿过去（`(22.6,-18/-9/0)` ✓）⇒ **图上看着接上了 ✓、电气上是断的** ✗✗
#     （Fritzing 的连接只记在 `<connects>` 里 ✓ ⇒ `check_netlist.py` 结构上就看不见 ✗）。
#   这正是用户那条「**贴脚必须是 0**」的**几何形态** ✓ —— 0.00 距离任何阈值都能杀掉 ✓。
#   ★ 风格与 `body_hard_bad` 一致 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓。
#   ★★ **默认开 ✓**（2026-09-28 ✓ **用户定** ✓）：实测它是**唯一**能把 (B) 假连线打到 **0**
#      的开关 ✓（(A)/(B)：v14 = 0/9 ✗ ｜ v15 = 0/8 ✗ ｜ `--hardpin` = **0/0 ✓✓**）。
#      ⇒ 旧基线仍可一键复现 ✓：`--nopin`（= v15 行为 ✓）。
HARD_PIN = True
PIN_EPS = 0.05
# ★★ `LANE_EPS`：**“同一条竖直车道”**（支线共享同网竖线时）判同的容差 ✓（2026-09-28 ✓ 实测定 ✓）
#   病灶（实测 ✓✓，`DBG_T2` 把 `used` 打出来才看见 ✗）：`U1.connector3` 的脚 x = `58.578` ✓，
#     而 `J1.connector1` 的落点 x = **`22.5779`** ✗（= 它的脚 x `15.3779` + 7.2 ✓）——
#     两者相差 **1e-4** ✗（不是整数个 7.2 ✓）⇒ 用 `1e-6` 判“同车道” ✗ ⇒ **永远不命中** ✗
#     （实测：候选加完**零效果** ✗、两档数字与 v27 逐字相同 ✗）。
#   ★ 这 1e-4 是**零件自身坐标的浮点末位** ✓（同一个坑 2026-09-28 在 `DATA_IN` 断成两段上踩过 ✓）；
#     `.fzz` **写出时四舍五入到 0.01 单位** ✓ ⇒ 写进文件后**两条线端点重合** ✓、Fritzing 载入后是**真接头** ✓。
#   ⇒ 容差取 `1e-2` 单位 = 0.0028 mm ✓（网格步长 7.2 ✓ ⇒ 绝无误判 ✓）。
LANE_EPS = 1e-2
# ★★ `HARD_OVL`：**导线不许与已布好的线压在同一条直线上** ✓（用户规则② 的**真闸门** ✓，2026-09-28 ✓）
#   病症（实测 ✓，`t27_1` = v15 + `--hardpin` ✓）：用户规则②（「**不同的导线，不能重叠**」✓）
#     原来**只靠软代价**压 ✗（`wt = INT_W[0]×nov + …` ✓）⇒ 一开 `--hardpin` 候选集变小 ⇒
#     它**退回 1 对** ✗✗（`Wire90012917 (-6,9)→(22.6,9)` 与 `Wire90012918 (22.6,9)→(10.4,9)`
#     在 `y=9` 上压了 12.2 单位 ✓）⇒ **硬规则不能用软代价表达** ✗（与 `HARD_BODY` 同一个理由 ✓）。
#   ★ 与 `HARD_BODY`/`HARD_PIN` 同一套路 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓；
#     删到一条不剩 ⇒ 调用处保留旧候选集 + 告警 ✓（不许把端点接不上 ✗）。
#   ★ 判据仍只有一份 ✓（`sch_geom.near_overlap` ✓）；`--noovl` 关掉 ⇒ A/B 对照 ✓。
HARD_OVL = True
# ★★ `HARD_CLEAR`：**贴脚零容忍** ✓（2026-09-28 ✓ **用户定**：「**贴脚的容忍度也是 0，
#   所以，这一项必须改。**」✗）
#   ★ 病症（用仓里**唯一那份**判据量的 ✓）：`Wire90012757`（GND ✓）在 `x=202.53` 竖走 89 单位 ✓
#     ⇒ 离 `LED2.connector0` 只剩 **1.15 单位 = 0.32 mm** ✗ ⇒ 渲染器报「贴近不相连的引脚
#     **1 处**」✗ —— 正是 band1 里唯一那一处 ✓（band0 有 9 处同型 ✓）。
#   ★ 用户**手改版**把同一条车道挪到 `x=209.06`（+6.5 单位 ✓）⇒ 贴脚 **1 → 0** ✓
#     ⇒ **合格的形状是存在的** ✓（不是无解 ✗）⇒ 病在**判据的位置** ✗：贴脚原本只是**软代价**
#     （`wt` 的第 ③ 档 ✓，`INT_W[1] = 1` ✓）⇒ 擦 1.15 单位只花 **1 分** ✗ ⇒ 拼不过“短 6.5 单位” ✗。
#   ⇒ **硬规则不能用软代价表达** ✓（与 `HARD_OVL` / `HARD_PIN` 同一条教训 ✓）⇒ 用**闸门**：
#     把“贴脚 ≠ 0”的候选**直接删掉** ✓；删光 ⇒ 保留旧候选集 + 告警 ✓（不许把端点接不上 ✗）。
#   ★ 判据**只有一份** ✓：`seg_pin_intr`（逐段取自己的脚 + `pin_intr` ✓）—— 与 `render_sch.py`
#     的 ④c2 **同一口径** ✓（`sch_geom.p2seg` + `< CLEAR_PIN − PIN_EPS` ✓），代价 / 闸门 /
#     每轮全局验收 `gstat` **三处共用它** ✓（抄三份 ⇒ 早晚有一份跟渲染器对不上 ✗）。
#   ★ `--noclear` 关掉 ⇒ A/B 对照 ✓（关掉后应与 v23 **逐字节相同** ✓）。
HARD_CLEAR = True
# ★★ `HARD_FJ`：**不许出现“跨网假接头”** ✓（2026-09-28 ✓ **用户点名**：「要按**同网 / 跨网**拆开」✓）
#   病症 ✓：一根线的**端点 / 折点**搭在**别的网**的线的**中段**（或端点 ✓）上 ✗
#     ⇒ 图上**看着接上了** ✓（T 形接头 ✓）、电气上**根本没连** ✗✗（Fritzing 只认端点对端点 ✓）。
#   实测 ✓（用渲染器新增的那条判据量的 ✓）：v24 = **3 处** ✗（其中两处是 `DATA_IN` 的折点
#     压在 5V 竖线中段上 ✓）；v25 = **1 处** ✗（5V 上轨的外伸端点压在 GND 竖线中段上 ✗）。
#   ★ 两道一起上 ✓（同一个规则的两个执行点 ✓）：
#     ① **路由门**（`fj_path_bad` ✓，本开关 ✓）—— 候选路径的顶点不许搭在别的网上 ✗；
#     ② **收尾修轨**（`fj_vertex_bad` / `fj_endpoint_used` ✓）—— 轨的两端若搭上了，
#        **没接东西**就往里收 `2 × MIN_SEG` ✓；**接了东西**就不动 + 告警 ✓（不拆真接头 ✗）。
#   ★ `--nofj` 关掉 ⇒ A/B 对照 ✓（回到 v25 ✓）。
HARD_FJ = True
# ★★ `FJ_GAP`：**“跨网假接头”要看得出距离** ✓（2026-09-28 ✓ **用户定**：
#   「**要考虑人眼视觉的局限性，要尽量清晰**」✓）
#   ★ 取 **`CLEAR_PIN` = 7.2 单位 = 2.03 mm** ✓ —— 就是用户定“导线离引脚要多远才看得清”
#     的**同一个数** ✓（一样是“肉眼能不能分出接没接上”这件事 ✓ ⇒ **不新造数** ✗）。
#   ✗ 实测过的反例（记下来 ✗）：第一版只让开 `2 × MIN_SEG = 0.1`（= **0.028 mm** ✗）
#     ⇒ 判据上干净了 ✓，可 0.028 mm **比线宽 0.25 mm 还细** ✗ ⇒ 看图的人**照样分不清** ✗
#     ⇒ 等于没修 ✗。
FJ_GAP = CLEAR_PIN
USE_ESC = True
NEW_ORDER = True
# ★★ `OUTER_RING`：**元件外圈环廊** ✓（2026-09-28 ✓ 用户点名的第 **1** 条 ✓）
#   病症（实测 ✓）：硬闸门一开就有 **68 对网“找不到候选”** ✗ ⇒ 主干**没有任何绕出去的路** ✓。
#   现有通道 `CH_OFFS = 6/12/22/34` **全部贴着元件** ✗ ⇒ 在**全体零件的总包围盒 `UBOX`**
#   **外面**再给几圈通道 ✓ ⇒ 主干可以“绕外围走” ✓。每档一格 = 7.2 单位 ✓。
OUTER_RING = False
RING_OFFS = (7.2, 14.4, 21.6, 28.8)
# ★★ `STAR_NETS`：**星形拓扑** ✓（2026-09-28 ✓ 用户点名的第 **2** 条 ✓）
#   病症（实测 ✓）：`GND` 是一条长链 ✓ 按 (x,y) 逐个串 ✓ ⇒ 必然出现“沿引脚行列长跑” ✗
#     （实测 8 处 **0.00 距离**的贴脚 ✓ 就是这么来的 ✓）。
#   做法 ✓：这些网**不走链** ✗，而是**每只脚各拉一根到公共汇点** ✓（汇点从干净通道里挑 ✓，
#     挑法见 `pick_hub` ✓）。★ 汇点是**没有连接器的裸端点** ✓ ⇒ 到底成不成连接 ✓
#     由 `check_netlist.py` **当场判定** ✓（不猜 ✗）—— 若不成立我就如实报出来 ✓。
STAR_NETS = set()
# ★★★ 2026-10-03 ✓ **`VLANES`：这些网改走「**竖直车道**」** ✓（用户选 A ✓）
#   起因（用户实测 ✓）：「**GND 网没有精简**」✗ —— 同一支网（从 `LED2` 的 GND 脚顺下去 ✓）
#     我 **142.9 mm** ✗ vs 用户手画 **70.7 mm** ✓。
#   ★ 病根（量出来的 ✓）：GND 9 只脚散布在 **7 个不同的行**（y=-72/-43.2/9/17/84/98/135 ✓），
#     而“轨”**只能水平** ✗ ⇒ 想贴得近就得**穿过 `U1`/`J1`/`D3` 的本体** ✗（过不了硬闸门 ✗）
#     ⇒ 大家只好**全拉到包围盒外的底轨 y=163.8** ✗ ⇒ 单根竖线就 **146.8** ✗（≈41.4mm ✗）。
#   ★ 用户手画版怎么解 ✓：干线是**竖的** ✓（x=210.6 ✓，从 y=17 直走到 y=-72 ✓）+ 短横支线 ✓
#     ⇒ 又短又清楚 ✓。⇒ 本开关就是把这个形状做成一种可选模式 ✓。
#   ★★ 纪律（与 `--label` / `--ground` 同一条 ✓）：**不给开关 ⇒ 一字节不差** ✓
#     （只对点名的网生效 ✓，其它网一个像素不动 ✓）。
VLANES = set()
# ★★ 2026-10-04 ✓ `VLANE_X`：**用户直接指挥车道 x** ✓（写法 `--vlanes=GND@210.58` ✓）
#   ★ 为什么要有它 ✗：自动挑只能算**几何距离** ✗ ⇒ 实测挑到了 `x=42.5`（左边那一簇 ✓），
#     而**用户手画挑的是 `x=210.58`** ✓（右边 `LED2`/`J2` 那一簇 ✓）——
#     “哪边看着简单”是**审美判断** ✓（§9 B 节 ✓），算法未必算得出 ⇒ **把方向盘给人** ✓。
#     用户给的数**就是**权威 ✓（不猜 ✗、不换算 ✗ —— 同一个 sketch 坐标空间 ✓）。
#   ★ 默认仍是自动挑 ✓（不给 `@x` ⇒ `pick_vlane` ✓）；给了 `@x` ⇒ **先用两道门核一遍** ✗，
#     不合格就**如实报出来**并把理由说清 ✓（不静默地用一条错车道 ✗）。
VLANE_X = {}
# ★★★ 2026-10-04 ✓ **`ISLAND_NETS`：允许这些网在原理图里“分岛”** ✓（用户 2026-10-04 定 ✓）
#   起因（用户自己画了一版 ✓ `_work/D_210_58_161_3_154_170_byHand.fzz` ✓，并说：
#     「**左边的地线轨删除了，补上右边轨就行了，逻辑太僵硬了**」✓）——
#   ★ 量出来的事实 ✓：他那一版 **44 根 / 486.9mm / 交叉 22** ✓（我这版 48 / 565.4 / 23 ✗），
#     差的就是**左边那根 235.8 单位（66.9mm）的“轨间互连”** ✗；
#     而他的 GND 里，**低处那一簇（`D3`/`C1`/`Ground1`）在原理图里与上面那半没有导线相连** ✓
#     —— 它们靠**别的视图**（面包板 GND 轨 / PCB ✓）连通 ✓。
#   ★ 而 **Fritzing 的“网”本来就是跨视图算的** ✓（本仓早先实测过 ✓：`schematicView` 里
#     那些不属于本视图的 `<connect>` 会让 Fritzing 把两块粘在一起 ✗ ✓）。
#     ⇒ 所以“**原理图里两条平行轨必须用一根线接起来**” ✗ **不是 Fritzing 的要求** ✗ ——
#       那是**我自己加的硬约束** ✗（用户原话：“逻辑太僵硬” ✓）。
#   ★ 用法：`--islands=GND` ✓ ⇒ 该网**不画轨间互连** ✗ ✓（各岛各自成立 ✓），
#     并在日志里**如实报出“本网分成了几个岛”** ✓（不静默 ✗）。
#   ★ 纪律：不给这个开关 ⇒ 与原来**一字不改** ✓（默认仍画互连 ✓）。
ISLAND_NETS = set()
# ★★ 已证伪并回退（2026-09-27 ✓）——“出脚车道过滤”这一整轴 ✗：
#   做法：把出脚候选的车道按“**跨度内会贴着别的脚** ⇒ 丢掉”精确过滤 ✓（比全局砍通道准得多 ✓）
#   ⇒ `_scratch/t17.py` 两档 A/B 实测：① 带过滤 与 ② `--escraw` **一字节不差** ✗ ⇒ **零效果** ✗
#     ⇒ 说明**出脚候选本来就没被选中** ✗ ⇒ 改它的车道 = 白改 ✓。
#   ★★ 本轮最终根因（定量 ✓，不是猜的 ✓）：**不是路由问题 ✗，是摆位问题** ✓ ——
#     U1 左缘 `x=22.6` 与 J1 右缘 `x=15.4` ⇒ 中间**只剩 7.2** ✓，而安全距离 `CLEAR_PIN`
#     也刚好是 **7.2** ✗ ⇒ **一条 ≥7.2 的空走廊都没有** ✗ ⇒ 从 U1 左排出发，
#     **往左必蹭 J1 的脚** ✗、**在列内跑必蹭同列别的脚** ✗ ⇒ 出脚候选的 `wt`
#     **永远 ≥ “骑引脚列”的 3** ✗ ⇒ 布线器只能选“骑” ✓。
#   ⇒ 本轴**到此停手** ✓（两次实测：一次越改越差 ✗、一次零效果 ✗）⇒ 改到**摆位**轴上再谈 ✓。
P_STEP = 2.0          # 判定用的采样步长（单位 ✓，与其余判据同一套口径 ✓）
# ★★ 抽出重排的轮数 ✓（2026-09-27 ✓，面包板验证过的最后一道工序 ✓）：
#   把每段抽出来、在“看得见其它所有线”的条件下重算 ✓ ⇒ **只留更优的** ✓（单调改进 ✓）。
#   0 = 关掉 ✓（A/B 对照用 ✓）。
#   ★ 实测（同一摆位 ✓，`_scratch/run_rip.py` ✓）：
#     rip 0 ⇒ 交叉 15 / 重叠 6 / 贴脚 13 / 总长 2055
#     rip 2 ⇒ 交叉 **13** ✓ / 重叠 **4** ✓ / 贴脚 16 ✗ / 总长 2059 ✓
#   ⇒ “交叉 / 重叠”（头两条规则 ✓）都降 ✓ ⇒ **默认开 3 轮** ✓。
#     ⚠ 贴脚 13→16 ✗：局部改进（每段只看自己 ✓）会让**别的**线贴脚 ✓ —— 同一个“局部 vs 全局”
#       病 ✓；下一步用“**每轮全局验收**”（把贴脚也当全局指标重算 ✓，变差就把这轮撤回 ✓）。
RIP_ROUNDS = 3
# ★ 每轮"全局验收"的权重 ✓（一整行可调 ✓）：`w1×重叠 + w2×贴脚 + w3×交叉` ✓
#   重叠 = 用户点名的**硬规则**（"不同的导线不能重叠" ✓）⇒ 给最高权 ✓
#   贴脚 = 用户点名的**可读性规则** ✓；交叉 = 审美头号指标 ✓
SNAP_WEIGHTS = (10, 1, 1)
# ★ 布线时“两条用户规则”的权重 ✓（必须与 `SNAP_WEIGHTS` **同一组刻度** ✓，否则两把尺子打架 ✗）
#   （重叠, 贴脚）与 `SNAP_WEIGHTS[0:2]` 一致 ✓。把重叠调大 ⇒ 更少压线 ✓；调小 ⇒ 更少贴脚 ✓。
INT_W = (SNAP_WEIGHTS[0], SNAP_WEIGHTS[1])
USE45 = True           # 是否允许 45° dogleg 候选 ✓（`--no45` 关掉 ✓，A/B 用 ✓）
#   ★ 为什么是“罚”不是“禁” ✗（2026-09-27 用户定 ✓：“允许 45° 斜线” ✓）：
#     · 用户指明了允许斜线 ✓；
#     · 我**量了他手改的那一版** ✓ —— 里面的斜线**不是** 45° ✗，而是 **20.1° / 23.4° /
#       28.8° / 2:1…** ✓ ⇒ 他实际的做法是“**两脚之间直接连一根直线**” ✓；
#     ⇒ 实现成**任意角直线**（含 45° ✓），并像面包板那样给斜线一点小罚分 ✓
#       （`bb_route4.py` 的 `DIAG_PEN` 同一个系数 ✓），让它只有在**躲开交叉/避让元件**
#       时才被选中 ✓。`,

# ★★ `--why` 决策探针 ✓（2026-09-27 ✓）—— **只观测、不改行为** ✓
#   用途 ✓：字典序代价里“**候选为什么没被选中**”一直靠我猜 ✗（今天猜错两次 ✗）。
#   它把“选中路径”与“亚军路径”的**代价元组**并排列出 ✓，并指出**第一处不同的档位** ✓
#   ⇒ 一眼看出是哪一档一票否决的 ✓，不用再猜 ✓。
WHY = False
PHASE = ["greedy"]        # “greedy” = 首轮布线 ✓；“rip” = 抽出重排 ✓（探针只报首轮 ✓）
TIER = ("穿自己本体", "靠别的元件", "出界格", "压线+贴脚", "交叉",
        "穿自己本体2", "弯", "长度")      # 与 `route_key` 的元组一一对应 ✓
# ★ 新次序对应的档名 ✓（`--oldorder` 时用上面那组 ✓）
TIER_NEW = ("穿自己本体", "出界格", "压线+贴脚", "靠别的元件", "交叉",
            "穿自己本体2", "弯", "长度")
# ★ 标定过的脚位置（由 recal_pins.py 从 Fritzing 自己的渲染反推 ✓）：
#   {modelIndex: {connectorId: (x, y)}} —— 有它就用它 ✓（逐元件公式跨元件不成立 ✗，2026-09-26）
PINS_FIX = {}


def tag(el):
    return el.tag.split("}")[-1]


def shape_pts(el):
    a, t = el.attrib, tag(el)
    n = lambda k: pm.num(a.get(k))            # noqa: E731
    if t == "rect":
        x, y, w, h = n("x"), n("y"), n("width"), n("height")
        return [(x, y), (x + w, y + h)] if None not in (x, y, w, h) else []
    if t == "line":
        return [(n("x1"), n("y1")), (n("x2"), n("y2"))]
    if t == "circle":
        cx, cy, r = n("cx"), n("cy"), n("r")
        return [(cx - r, cy - r), (cx + r, cy + r)] if None not in (cx, cy, r) else []
    if t == "ellipse":
        cx, cy, rx, ry = n("cx"), n("cy"), n("rx"), n("ry")
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)] if None not in (cx, cy, rx, ry) else []
    if t in ("polyline", "polygon", "path"):
        key = "points" if t in ("polyline", "polygon") else "d"
        v = [float(x) for x in re.findall(r"-?[\d.]+", a.get(key) or "")]
        return list(zip(v[0::2], v[1::2]))
    return []


def body_pts(el, m, out):
    """本体的导出坐标点 ✓

    ★★ 2026-09-27 修（实测 ✓）：原来**跳过** `class="pin"` 与 `*terminal` ✗
      ⇒ keep-out 盒**只框住本体矩形** ✗（实测 `U1(41.5,-31.5→104.5,31.5)` ✓ 63×63 ✓，
        而 U1 的引脚线伸到 x=29.8…116.2 ✓）⇒ 布线器就钻了空子 ✗：
        在 **x=106.13** 竖着走 135 单位 ✓ —— 正好在 **U1 引脚线那一带** ✗
        ⇒ 导线从**引脚线之间**穿过去 ✗（视觉上就像接上了 ✗ **最容易误导人** ✗）。
      ✓ 现在把引脚线也算进本体框 ✓（与 `render_sch.py` 的量尺**同口径** ✓），
        这样"贴着一排脚的外侧"就不再是可走的走廊 ✓。
      ⚠ 注意：引脚**末端**就在框边界上 ✓ ⇒ 导线从**外面**接到脚上不会因此被挡 ✗
        （自己的元件本来就有豁免 ✓，且豁免已收紧到"端点 R 单位以内" ✓）。
    """
    if tag(el) == "text":
        return
    for (x, y) in shape_pts(el):
        out.append(apply(m, x, y))
    t = el.get("transform")
    m2 = pm_mul(m, t)
    for c in el:
        body_pts(c, m2, out)


def pm_mul(m, t):
    from pin_ruler import mul, parse_tf
    return mul(m, parse_tf(t)) if t else m


# ─────────────────────────── 几何 ───────────────────────────
def load_geom(fzz, svg):
    ruler, orphan, soft = build_ruler(svg)
    if soft:
        print("★ 备用池 `soft`（有 `partID`、但元素没有 `x/y` 的终端 ✓）：%s ✓"
              % ", ".join("%s×%d" % (k, len(v)) for k, v in sorted(soft.items())))
    if orphan:
        print("★ 尺子里**没有 `partID` 的终端** ✓：%d 个（core 件，如地符号 ✓）⇒ 由最近的、"
              "解析不到脚位的实例**认领** ✓" % len(orphan))
    root = ET.parse(svg).getroot()
    BOX_MISS = []

    def walk(el, m, pid):
        m2 = pm_mul(m, el.get("transform"))
        if el.get("partID"):
            pid = el.get("partID")
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)

    z = zipfile.ZipFile(fzz)
    sroot = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    conname, con_of = {}, {}
    # ★ 零件的**原理图 svg 文本** ✓（算“本体盒”用 ✓，2026-09-27 ✓）：
    #   `.fzp` 里 `<schematicView image="schematic/xx.svg">` ✓ ⇒ 去 zip 里找同名条目 ✓。
    svg_by_mid = {}          # ★ 已废弃 ✗（见下面那段教训 ✓）—— 保留空字典是为少改一行 ✓
    packed = {n: z.read(n).decode("utf-8", "replace")
              for n in z.namelist() if n.endswith(".svg")}
    print("零件 svg：包内有 %d 份副本 ✓（磁盘取不到时兜底 ✓）" % len(packed))
    for n in z.namelist():
        if n.startswith("part.") and n.endswith(".fzp"):
            r = ET.fromstring(z.read(n))
            conname[r.get("moduleId")] = {c.get("id"): (c.get("name") or "")
                                          for c in r.iter("connector")}
    insts = {}
    for e in sroot.iter("instance"):
        vw = pm.child(e, "views")
        sub = pm.child(vw, "schematicView") if vw is not None else None
        g = pm.child(sub, "geometry") if sub is not None else None
        if g is None or g.get("x") is None:
            continue
        mi = e.get("modelIndex")
        title = (e.findtext("title") or "").strip()
        loc = (pm.num(g.get("x")), pm.num(g.get("y")))
        pid = next((p for p in ruler if p.startswith(mi) and len(p) == len(mi) + 1),
                   mi if mi in ruler else None)
        ox, oy = ruler[pid]["origin"] if pid else (0, 0)
        # ★★★ `sk`：尺子坐标 → sketch 坐标 ✓ —— **只有一句：乘一个比例** ✓✓
        #   ✗ 旧写法 `loc + RATIO*(x - ox)`（`ox` = 尺子里"用户坐标 (0,0)"的位置）**是错的** ✗：
        #     `ox` ≠ 零件锚点 ✗ ⇒ 它会**减掉每个零件自己的平移** ✗ ⇒
        #     凡 `viewBox 原点 ≠ (0,0)` 或**带旋转**的零件，脚位一律偏 ✗
        #     （2026-09-27 实测 ✓，`_scratch/diag_pins.py` 逐件对出来的 ✓）：
        #       D3/L1/LED2/R1（原点 (0,0)）差 **0.0001 单位** ✓ 看不出问题 ✗；
        #       J1/J2（`viewBox="0.00 -0.50 …"`）差 **1.7718 = k×0.5mm** ✗；
        #       U1（`viewBox="-190 -190 …"`）差 **17.1 = k×190** ✗；
        #       C1/C2（再加旋转 180°）差 **31.37** ✗。
        #     ⇒ 后果：**画出来的导线够不到脚** ✗（用户原图里那 6 个"悬空端"就是这么来的 ✓，
        #       不是手画错 ✗ —— 我当时误判成用户的图 ✗，记下来别再犯 ✗）。
        #   ✓ 正解：尺子本身就是"一张按比例画的 sketch" ✓ ⇒ `sketch = RATIO × 尺子坐标` ✓；
        #     比例由**尺子的单位**定：Fritzing 导出（1/72in）= **1.25** ✓；
        #     本项目 `render_sch.py` 出图（就是 sketch 单位）= **1.0** ✓（`--ratio` ✓）。
        sk = lambda x, y: (RATIO * x, RATIO * y)                     # noqa: E731
        # ★★★ 2026-10-04 ✓ **先认出「网锚点」**（网标签 / 接地符号 ✓）—— 取脚位之前就要知道 ✓
        #   ✓ 口径（**照它自己的语义** ✓，不猜 ✗）：
        #     · `GroundModuleID` ⇒ 网 = **GND** ✓（它就是地符号 ✓）；
        #     · `NetLabelModuleID` ⇒ 网 = `<property name="label">` ✓（实测：两个 `RC` 标签都写
        #       `name="label" value="RC"` ✓）—— ★ 标题只是位号 ✗（两个都叫 `RC` ✗
        #       ⇒ 按标题存会**互相盖掉** ✗，实测就是丢了一个 ✗）。
        _mid2 = e.get("moduleIdRef") or ""
        anchor = None
        _akind = None
        if "GroundModuleID" in _mid2:
            anchor, _akind = "GND", "ground"
        elif "NetLabelModuleID" in _mid2:
            anchor, _akind = None, "netlabel"
            for _pv in e.iter("property"):
                if (_pv.get("name") or "").lower() == "label":
                    anchor = (_pv.get("value") or "").strip()
        pins, pins_export = {}, {}
        if pid:
            for cid, (ex, ey) in ruler[pid]["pins"].items():
                pins_export[cid] = (ex, ey)
                pins[cid] = sk(ex, ey)
        if PINS_FIX.get(mi):                  # ★ 优先用标定值 ✓（精确 ✓）
            for cid, p in PINS_FIX[mi].items():
                if cid in pins:
                    pins[cid] = p
        # ★★★ 2026-10-04 ✓ **锚点认领一个没有 `partID` 的终端** ✓（core 件：地符号 ✓）
        #   ✗ 为什么必须放在这里 ✗：`pins, pins_export = {}, {}` 在**上面** ✗ ——
        #     我第一版把认领写在了它**前面** ✗ ⇒ 认领到的脚**当场被空字典冲掉** ✗✗
        #     （症状：还是报「导出里没有 @90012780 的 connector0」✗）—— 必须放在**之后** ✓。
        #   ★ 判据 = **离实例原点最近** ✓（限 30 单位 ≈ 8.5mm ✓，免得抢了别人的 ✓）；
        #     认领后**从池子里拿走** ✓（两个地符号各拿一个 ✓，不会共用 ✗）。
        if anchor:
            _best2, _bd2 = None, 30.0
            for _j2, (_c2, _q2, _g2b) in enumerate(orphan):
                _d2 = math.dist((RATIO * _q2[0], RATIO * _q2[1]), sk(*loc))
                if _d2 < _bd2:
                    _best2, _bd2 = _j2, _d2
            if _best2 is not None:
                _c2, _q2, _g2c = orphan.pop(_best2)
                pins_export[_c2] = _q2
                pins[_c2] = sk(*_q2)
                print("   ✓ 锚点 **%s**（%s）认领到 %s ✓ 距原点 %.2f 单位 = %.2f mm ✓"
                      % (title, anchor, _c2, _bd2, _bd2 * 25.4 / 90.0))
            else:
                _near = [math.dist((RATIO * _q2[0], RATIO * _q2[1]), sk(*loc))
                         for _c2, _q2, _g2d in orphan]
                print("   ⚠ 锚点 **%s**（%s）**没有可认领的终端** ✗（池里剩 %d 个，最近 %s）"
                      "⇒ 它这次**接不上**（请人看一眼 ✓）"
                      % (title, anchor, len(_near),
                         "%.2f 单位" % min(_near) if _near else "—"))
            # ★★ 备用池兜底 ✓：该件**自己的**终端（只是元素没有 `x/y` ✗，如 `<line>`/`<path>` ✓）
            if not pins and pid and soft.get(pid):
                for _sc, _sp in soft.pop(pid).items():
                    pins_export[_sc] = _sp
                    pins[_sc] = sk(*_sp)
                print("   ✓ 锚点 **%s**（%s）从**备用池**取到脚位 ✓：%s ✓（元素没有 `x/y` ✗ ⇒"
                      "主表取不到 ✓）" % (title, anchor, ", ".join(sorted(pins))))
        # ★★ 本体盒：**只调共享实现** ✓（2026-09-27 ✓）
        #   ✗ 第一版我在这里猜错了取 svg 的写法 ✗ ⇒ 10 件全取不到 ✗ ⇒ 盒子全空 ✗ ⇒ 闸门失效 ✗
        #   ✓ 正解（= 渲染器那一套 ✓，已搬进 `sch_box.part_svg_text` ✓）：
        #     ① 实例的 **`path=`** 给的是磁盘 fzp ✓；② svg 名在它的 `<schematicView><layers image=…>` ✓；
        #     ③ **磁盘优先** ✓、包内副本兜底 ✓。
        box, _note = None, ""
        _fzp = (e.get("path") or "").replace("/", os.sep)
        _txt, _src = None, None
        if _fzp and os.path.isfile(_fzp):
            try:
                _lay = ET.parse(_fzp).getroot().find(".//schematicView/layers")
                _img = _lay.get("image") if _lay is not None else None
            except Exception as ex:
                _img, _note = None, "fzp 解析不了：%s" % ex
            if _img:
                _txt, _src = SB.part_svg_text(_fzp, packed, _img)
        if _txt and g is not None:
            box, _A, _note = SB.box_of(_txt, g)      # ★ 共享实现 ✓（与判据同一份 ✓）
        else:
            _note = _note or "零件 svg 取不到 ✗（本体盒算不出 ⇒ 闸门拦不住它 ✗）"
        if box is None:
            BOX_MISS.append("%s：%s" % (title or (pid or "?"), _note))
        # ★ 位号框避让 —— **试过、实测不划算、已回退** ✗（2026-09-27 ✓）：
        #   让布线器认识位号框后，位号压导线只从 **3 → 2** ✗（剩下的是 `L1`：
        #   它旁边根本没有别的通道 ✓），代价却是 **压线 8 → 10** ✗、总长 +13 ✗
        #   ⇒ 净亏 ✓。位号那条得靠**位号自己挪**（布线完再重摆 ✓ = 下一手 ✓），
        #   不是让导线绕 ✗ —— 按规矩：“修一个小问题要叠第二个补偿性改动 ⇒ 停手” ✓。
        insts[title] = {"mi": mi, "mid": e.get("moduleIdRef"), "el": e, "sub": sub,
                        "loc": loc, "pins": pins, "box": box, "names": conname,
                        "ox": (ox, oy) if pid else None, "pins_export": pins_export}
        # ★★★ 2026-10-04 ✓ **网锚点**（网标签 / 接地符号）**也要进它自己的网** ✗（用户报的 bug ✓）
        #   ✗ 病（实测 ✓，`_work/_dangling.py` ✓）：`RC` ×2 / `Ground1` / `Ground2` **在输入里就悬空** ✗
        #     （`sch_strip_wires.py` 剥掉原理图导线后，它们**一个连接都没有** ✗），
        #     而布线器只管网表里那些脚 ✗ ⇒ 它们一路悬空到产出 ✗ ⇒ 用户看到：
        #       · 「**接地标志没有接入地线网络**」✗；
        #       · 「**RC 标签没有把中间的线省去**」✗（标签成了摆设 ✗）。
        #   ✓ 口径（**照它自己的语义** ✓，不猜 ✗）：
        #     · `GroundModuleID` ⇒ 网 = **GND** ✓（它就是地符号 ✓）；
        #     · `NetLabelModuleID` ⇒ 网 = `<property name="label">` ✓（实测：两个 `RC` 标签都写
        #       `name="label" value="RC"` ✓）—— ★ 标题只是位号 ✗（两个都叫 `RC` ✗
        #       ⇒ 按标题存会**互相盖掉** ✗，实测就是丢了一个 ✗）。
        #   ★ 所以锚点存**唯一键** `"@<modelIndex>"` ✓（并且**不再用标题键** ✓ ⇒ 不会有两份 ✗）：
        #     `el`/`mi`/`pins` 指向**同一个 XML 元素** ✓ ⇒ 实例不会写两遍 ✓
        #     （实例的写出是**按 XML** 走的 ✓，不是遍历 `insts` ✓）。
        if anchor:
            del insts[title]
            insts["@%s" % mi] = {"mi": mi, "mid": _mid2, "el": e, "sub": sub,
                                 "loc": loc, "pins": pins, "box": box, "names": conname,
                                 "ox": (ox, oy) if pid else None, "pins_export": pins_export,
                                 "anchor": anchor, "anchor_title": title, "anchor_kind": _akind}

    # ★ 全局映射：拿"同一个脚在 sketch 与在导出 SVG 里的坐标"最小二乘拟合 ✓
    #   （2026-09-26：原以为能用 `导出 = ox − loc/1.25` 逐元件推 ✗ —— 实测离散 22 单位 ✗，
    #    说明那个关系只是**逐元件内部**自洽，不能当全局映射 ✓；脚是地面真值 ✓）
    def lin_fit(pairs):
        n = len(pairs)
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        den = sum((p[0] - mx) ** 2 for p in pairs)
        s = sum((p[0] - mx) * (p[1] - my) for p in pairs) / den if den else 1.0
        a = my - s * mx
        return s, a, max(abs(p[1] - (a + s * p[0])) for p in pairs)

    xp, yp = [], []
    for d in insts.values():
        for cid, (ex, ey) in d["pins_export"].items():
            sx, sy = d["pins"][cid]
            xp.append((sx, ex))
            yp.append((sy, ey))
    fit = {"x": lin_fit(xp), "y": lin_fit(yp), "n": len(xp)}
    if BOX_MISS:                              # ★ 算不出的件要**吭声** ✓（闸门对它们失效 ✓ 不静默 ✗）
        print("⚠ 本体盒算不出的件 %d 个 ✗（那些件闸门拦不住 ✓）：%s"
              % (len(BOX_MISS), "；".join(BOX_MISS)))
    return sroot, insts, z, fit


def anchor_pins_from_orig(orig_path, want):
    r"""从**用户手画原图**里取「网标签 / 接地符号」的**真脚点** ✓

    ★ 判据（可验证 ✓）：该锚点接的**导线端点**里，**离它自己实例原点最近**的那个 ✓。
      实测（用户原图 ✓）：`RC#1` 原点 (148.935,65.0999) ⇒ 取到 **(161.462,69.604)** ✓；
      `RC#2` 原点 (32.9771,-19.6917) ⇒ 取到 **(39.178,-9.000)** ✓
      —— 另一个端点都是**别的元件的脚** ✓（离得更远 ✓）。
    ★ 为什么必须从**原图**取 ✗：core `netlabel.fzp` 的原理图 svg **不画终端** ✗
      （只有一个 `<polygon>` + `<text>` ✓）⇒ 尺子里根本没有它的脚位 ✗；
      而它的连接点**也不在实例原点** ✗（实测偏 (12.5, 4.5) ✓）。
    ★ 返回 `{modelIndex: (x, y)}` ✓（sketch 坐标 ✓，与实例几何同一空间 ✓）。
    """
    out = {}
    try:
        z = zipfile.ZipFile(orig_path)
        sroot = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".fz")][0]))
    except Exception as ex:                       # ★ 读不了要**吭声** ✓ 不静默 ✗
        print("   ⚠ 原图读不了 ✗（%s）⇒ 锚点脚位只能算了 ✗" % ex)
        return out
    org, con = {}, {}
    for e in sroot.iter("instance"):
        mi = e.get("modelIndex")
        for v in e.iter():
            if v.tag.split("}")[-1] != "schematicView":
                continue
            for g in v:
                if g.tag.split("}")[-1] == "geometry" and g.get("x") is not None:
                    org[mi] = (float(g.get("x")), float(g.get("y")))
            break
        for x in e.iter():
            if x.tag.split("}")[-1] == "connect":
                con.setdefault(str(x.get("modelIndex")), []).append(e)
    for mi in want:
        if mi not in org:
            continue
        ox, oy = org[mi]
        best = None
        for e in con.get(str(mi), []):
            for v in e.iter():
                if v.tag.split("}")[-1] != "schematicView":
                    continue
                for g in v:
                    if g.tag.split("}")[-1] != "geometry" or g.get("x") is None:
                        continue
                    gx, gy = float(g.get("x")), float(g.get("y"))
                    for _e2 in ((float(g.get("x1") or 0), float(g.get("y1") or 0)),
                                (float(g.get("x2") or 0), float(g.get("y2") or 0))):
                        p = (gx + _e2[0], gy + _e2[1])
                        d = math.dist(p, (ox, oy))
                        if best is None or d < best[0]:
                            best = (d, p)
                break
        if best is not None:
            out[mi] = best[1]
    return out


def pin_of(insts, ref, name):
    d = insts[ref]
    cmap = d["names"].get(d["mid"], {})
    if name.startswith("#"):
        cid = "connector" + str(int(name[1:]) - 1)
    else:
        cid = next((c for c, nm in cmap.items() if nm.lower() == name.lower()), None)
        if cid is None:
            raise SystemExit("✗ %s 找不到名叫 %s 的脚（有：%s）"
                             % (ref, name, ", ".join("%s=%s" % kv for kv in cmap.items())))
    if cid not in d["pins"]:
        raise SystemExit("✗ 导出里没有 %s 的 %s" % (ref, cid))
    return cid, d["pins"][cid]


# ─────────────────────────── 布线 ───────────────────────────
def seg_hits_box(p, q, box, clear):
    """线段 p→q 是否穿过 box（外扩 clear ✓）"""
    if box is None:
        return False
    x0, y0, x1, y1 = box[0] - clear, box[1] - clear, box[2] + clear, box[3] + clear
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
    for i in range(n + 1):
        t = i / n
        x = p[0] + (q[0] - p[0]) * t
        y = p[1] + (q[1] - p[1]) * t
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def overlap(a, b, c, d, tol=0.5):
    """两段是否**压在一条直线上** ✗（外壳 —— 真正实现在 `sch_geom.near_overlap` ✓

    ★ 为什么删掉自己的实现 ✗（2026-09-27 ✓）：`render_sch.py` 和这里原本**各一份**
      ⇒ 一旦允许斜线，两份会给出**不同**的数 ✗（面包板那天的教训：判碰只能一份实现 ✓）。
      现在这里只是包装 ✓ —— 而且换成**通用**判据（不再只认轴对齐 ✗）✓。
    """
    return SG.near_overlap(a, b, c, d, tol)


def candidates(a, b, chx, chy):
    """候选路径 ✓（★ 含**真正的 45° 斜线** ✓ —— 2026-09-27 用户定 ✓）

    ★ 为什么**不是“任意角直连”** ✗（实测推翻了我自己的实现 ✓）：
      ① 先按用户原话“允许 45°” ✓，又去量了他手改版里的 15 根斜线 ✓ ⇒
         角度是 `20.1° / 23.4° / 28.8° / 2:1…` ✗ —— 不是 45° ✓；
      ② 于是我改成“任意角直连” ✓（想跟他的手画一致 ✓）⇒ **实测大幅变差** ✗✗：
         交叉 **8 → 37∼42** ✗、压线 19 → **88∼100** ✗、总长 2496 → **4941** ✗
         （因为直连线**横穿全图** ✗，且开头几根就把后面的路全堵了 ✗）。
      ⇒ 结论：**只有 45° 的“小斜切”能用** ✓ —— 它只会把拐角“抹掉一点” ✓，
        不会拉出一根横穿全图的斜线 ✗。这就是**工程上的 45° 布线**本意 ✓。
      ★ 斜切只在**省长度**时才被选中 ✓（`diag_extra` 只在最后一档 ✓）：
        斜边 1.414 优于两边 2.0 ✓ ⇒ 对齐得好的地方会自然长出 45° ✓。
    """
    out = []
    # ✗ 这里曾试过“把引脚自己的列左右各挪 `ESC_OFFS` 当车道”✗ ⇒
    #   实测**四档结果一字节不差** ✗✗（完全无效 ✓）⇒ 已撤 ✓。
    #   原因在 `ESC_OFFS` 那段注释里 ✓：“进 / 出引脚那一段在排内跑”✗ ⇒ 只能靠 `esc_cands` ✓。
    if abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6:
        out.append([a, b])                     # ★ **只在轴对齐时**才给直连 ✓
        #   ✗ 非轴对齐的“直连”= **任意角** ✗ ⇒ 实测交叉 8 → 40 ✗✗（它会横穿全图 ✓）
        #   ⇒ 不许 ✓：非轴对齐只走 L 形 / 45° dogleg / 走通道 ✓
    out.append([a, (b[0], a[1]), b])           # L 形
    out.append([a, (a[0], b[1]), b])
    dx, dy = b[0] - a[0], b[1] - a[1]
    sx = 1.0 if dx >= 0 else -1.0
    sy = 1.0 if dy >= 0 else -1.0
    if USE45 and abs(dx) > 1e-6 and abs(dy) > 1e-6:
        # ③④⑤⑥ 45° + 正交的 "dogleg" ✓ —— **四种**落法 × 两侧 = 8 条 ✓
        #   （每一条里**恰有一段是 45°** ✓、另一段正交 ✓ ⇒ 全路径只有 45° 和 0°/90° ✓）
        #   落法：`斜段靠在 a 端`（跑到 b 的列 / 行 ✓）、`斜段靠在 b 端` ✓
        for s in (1.0, -1.0):
            out.append([a, (b[0], a[1] + s * abs(dx)), b])          # 斜段→跑到 b 的列 ✓
            out.append([a, (a[0] + s * abs(dy), b[1]), b])          # 斜段→跑到 b 的行 ✓
            out.append([a, (a[0], b[1] - s * abs(dx)), b])          # 斜段在 b 端，先竖直 ✓
            out.append([a, (b[0] - s * abs(dy), a[1]), b])          # 斜段在 b 端，先水平 ✓
    for x in chx:
        out.append([a, (x, a[1]), (x, b[1]), b])
    for y in chy:
        out.append([a, (a[0], y), (b[0], y), b])
    # ★★ 全部候选**统一**过一遍 `dedup_path` ✓（2026-09-28 ✓）——
    #   · 消掉 **0.000~0.001 单位**的残段 ✗（否则会写出“点导线”✗，见 `MIN_SEG` ✓）；
    #   · 并且**对全体候选一律公平** ✓（`bends()` 是按**点数**算的 ✓ ⇒ 少一个假点就少一档
    #     代价 ✓；只给出脚候选去重 ✗ 会让两边的“弯”不同尺度 ✗✗）。
    #   ★ 放在**源头**这里 ✓（不在 `route_pair` 里再兜一次 ✗）⇒ 下游 `esc_ids`（按 `id()` ✓）
    #     与 `used` 都还是同一批对象 ✓，不会错位 ✗。
    return [dedup_path(pp) for pp in out]


def dedup_path(p):
    r"""去掉重合点 ✓ + 合并共线段 ✓（否否则“弯”会被算多 ✗：

    ★ 为什么要合并共线 ✓：`bends()` 数的是**点数** ✓ ⇒ 出脚后的第一段常与第二段共线 ✓
      （如法线向左出脚 + 再向左横走 ✓）⇒ 不合并就会多算 1 个弯 ✗ ⇒ 出脚形状在“弯”
      那一档亏分 ✗（不公平 ✓）。
    ★★ 去重容差从 `1e-9` 提到 **`MIN_SEG`（=0.05 单位 = 0.014 mm ✓）**（2026-09-28 ✓）：
      ✗ 原来是 1e-9 ⇒ **0.000~0.001 单位**的残段活下来 ✗ ⇒ 生成器会写出
        **“点导线”** ✗（实测 v16 里有 **4 根** ✓：`Wire90012893` 0.000 单位@`C2.c0` ✓、
        `Wire90012902` 0.001@`L1.c0` ✓、`Wire90012933` 0.000@`U1.c12` ✓、
        `Wire90012940` 0.000@`R1.c1` ✓ —— 电气无害 ✓ 但是垃圾 ✗）。
      ✓ 成因：**引脚坐标与通道网格差一点点** ⇒ 生出一小截 ✗ ⇒ 按全仓同一个“碰到”容差
        （0.05 ✓，**不新造数** ✗）当它不存在 ✓。
    """
    q = [p[0]]
    for r in p[1:]:
        if math.dist(r, q[-1]) > MIN_SEG:
            q.append(r)
    if len(q) < 3:
        return q
    out = [q[0]]
    for i in range(1, len(q) - 1):
        # ★★ 2026-09-28 ✓ “共线”判据改用**距离容差** ✓（`MIN_SEG` = 0.05 ✓ = 全仓既有的那个 ✓）：
        #   ✗ 原来是**叉积严格 ≠ 0**（`1e-9` ✗ + 绝对单位 ✗）⇒ 实测 `DATA_IN`
        #     （`J1.c2` ↔ `U1.c2` ✓ = **一条直线** ✓）被**打断成两根** ✗✗：
        #     两端 `y = 0.0001` / `0.0002`（差 **0.0001 单位 = 0.000025 mm** ✗），
        #     中间那个出脚点 (46.3779,0.0001) 离 a→b 直线只有 **0.00003 单位** ✓，
        #     却因叉积 = **1.2e-3** ✗ > 1e-9 ⇒ **不合并** ✗ ⇒ 写出两根线 ✗
        #     （用户点名：「是一条直线被打断成两段 ⇒ 这个 bug 应该修掉」✓）。
        #   ✓ 现在：`p2seg(点, 前一个保留点, 下一个点) <= MIN_SEG` ⇒ 偏差 ≤ 0.014 mm 的
        #     中间点**一律当“在直线上”** ✓ 删掉 ✓（判据仍是仓里**唯一那份**点到线段距离 ✓）。
        if SG.p2seg(q[i], out[-1], q[i + 1]) > MIN_SEG:
            out.append(q[i])
    out.append(q[-1])
    return out


def pin_normal(px, py, bb):
    r"""这个脚的**外法线** ✓（看它贴在元件包围盒的哪条边上 ✓；盒**内部** ⇒ `(0,0)` ✓）

    ★ **唯一实现** ✓：`edge_pins`（“最边缘的脚”清单 ✓）与主流程的 `PIN_N_BY_XY` **共用它** ✓
      （扶两份 ⇒ 早晚对不上 ✗ —— 本仓的老规矩 ✓）。
    """
    if not bb:
        return (0.0, 0.0)
    if abs(px - bb[0]) < 1.0:
        return (-1.0, 0.0)
    if abs(px - bb[2]) < 1.0:
        return (1.0, 0.0)
    if abs(py - bb[1]) < 1.0:
        return (0.0, -1.0)
    if abs(py - bb[3]) < 1.0:
        return (0.0, 1.0)
    return (0.0, 0.0)


def edge_pins(insts, boxes):
    r"""★ **“最边缘的脚”清单** ✓（`--noescape=edge` 用 ✓，2026-09-28 ✓ 用户点名的判据 ✓）

    ★ 口径 ✓（**按“危险腿”的方向定义** ✓）：
      “不出脚”时，腿是**沿着本行 / 本列**走的 ✓（`esc_cands` 的四族形状 ✓）——
      · 法线是 **±x**（贴在竖边上 ✓）⇒ 危险腿沿 **本列（x 相同 ✓）** 走 ✓
        ⇒ 资格 = **在同一列里 `y` 最上 / 最下** ✓（`R1.c1` 就靠这个拿到 ✓ —— 它那列只有它自己 ✓）；
      · 法线是 **±y**（贴在横边上 ✓）⇒ 危险腿沿 **本行** 走 ✓ ⇒ 资格 = **同一行里 `x` 最左 / 最右** ✓。
      ★ 为什么不“行列都算” ✗（我第一版就是这么写的 ✗）：**行里往往只有自己一只脚** ✗
        ⇒ `min == max == 自己` ⇒ **45/45 全合格** ✗（实测 ✓ 白名单形同虚设 ✗）。
    ★ 返回 = **坐标集合** ✓（`route_pair` 手里只有点 ✗，没有“这是哪只脚” ✓）⇒ 先算成点表 ✓。
    """
    out = set()
    for _t, _d in insts.items():
        _bb = boxes.get(_t)
        grp = {}
        for _cid, _p in _d["pins"].items():
            _n = pin_normal(_p[0], _p[1], _bb)
            _ax = 0 if abs(_n[0]) > 0.5 else 1
            grp.setdefault((_ax, round(_p[_ax], 3)), []).append(_p[1 - _ax])
        for _cid, _p in _d["pins"].items():
            _n = pin_normal(_p[0], _p[1], _bb)
            _ax = 0 if abs(_n[0]) > 0.5 else 1
            _g = grp[(_ax, round(_p[_ax], 3))]
            _v = _p[1 - _ax]
            if abs(_v - min(_g)) < 1e-6 or abs(_v - max(_g)) < 1e-6:
                out.add((round(_p[0], 3), round(_p[1], 3)))
    return out


def _noesc_ok(p, edge_pts):
    r"""这只脚能不能“不出脚” ✓（`off` 一律不给 ✗ / `all` 都给 ✓ / `edge` 只给最边缘那只 ✓）"""
    if NOESC == "all":
        return True
    if NOESC == "edge":
        return (round(p[0], 3), round(p[1], 3)) in edge_pts
    return False


def esc_cands(a, b, na, nb, chx2, chy2, edge_pts=None):
    r"""**出脚组合**候选 ✓（2026-09-27 ✓）—— 先沿引脚法线出脚 ✓ → 走**干净通道** ✓ → 再拐进脚 ✓

    ★ 为什么需要它（`--why` 探针实测 ✓）：
      实测 `GND U1.connector3→U1.connector20`：选中与亚军**贴脚都是 3** ✗ ⇒
      **候选里没有一条能把 3 降下来** ✗ —— 不是被前面的档位压掉 ✗（我先猜的就是它 ✗，猜错 ✓）。
      原因：原有“车道”形状**出脚方向不对** ✗ ——
        · `[a,(x,a1),(x,b1),b]` 末段横的 ⇒ 目标脚在**底排**时它**沿底排引脚行**跑 ✗；
        · `[a,(a0,y),(b0,y),b]` 首段竖的 ⇒ 起点在**左排**时它**沿左排引脚列**跑 ✗。
    ★ `na/nb` = 两端引脚的**法线** ✓（由“脚贴在元件的哪条边上”算出 ✓；
      元件内部的脚（如 D3 的 `AC1/AC2` ✓）法线为 (0,0) ⇒ 不出脚 ✓）。
    ★ `chx2/chy2` = **干净通道** ✓（只含“元件边 ± `CH_OFFS`” ✓，**不含任何引脚坐标** ✗）⇒
      主干不会骑在别人的引脚行列上 ✓；再把两端**出脚点自己的行列**加进去 ✓
      （那是已离开引脚 `ESC_OFFS` 的平行车道 ✓ > `CLEAR_PIN` ✓）。
    ★ 为什么要**卡根范围**（± 40 单位 ✓）：候选数直接决定跑得多快 ✓
      （`route_key` 每条候选要扫全图 45 个脚 ✓）⇒ 只取端点附近的通道 ✓
      （跑出包围范围很多的通道 = 绕远路 ✓，本来就会被长度项罚 ✓）。
    """
    aps = [] if na == (0.0, 0.0) else [(a[0] + na[0] * o, a[1] + na[1] * o) for o in ESC_OFFS]
    bps = [] if nb == (0.0, 0.0) else [(b[0] + nb[0] * o, b[1] + nb[1] * o) for o in ESC_OFFS]
    # ★★ `--noescape` ✓：把“**脚本身**”也当一个出脚点 ✓（= “不出脚，直接沿本行/本列走” ✓）
    #   —— 这是用户手改版 `RC` 那一步的关键形状 ✓（实测它不在候选里时，多拐一次 = +24.4 单位 ✗）。
    _ep = edge_pts if edge_pts is not None else set()
    if na == (0.0, 0.0) or _noesc_ok(a, _ep):
        aps.append(a)
    if nb == (0.0, 0.0) or _noesc_ok(b, _ep):
        bps.append(b)
    xs = [q[0] for q in aps + bps]
    ys = [q[1] for q in aps + bps]
    cx = [v for v in sorted(set(chx2) | set(xs)) if min(xs) - 40.0 <= v <= max(xs) + 40.0]
    cy = [v for v in sorted(set(chy2) | set(ys)) if min(ys) - 40.0 <= v <= max(ys) + 40.0]
    out = []
    # ✗ 曾在这里加过“车道跨度内贴引脚 ⇒ 丢掉”的精确过滤 ✓ ⇒ 实测**零效果** ✗（见上面那段证伪记录 ✓），
    #   已撤 ✓ —— 原因：“出脚候选根本没被选中”✗，改它的车道无意义 ✓。
    for ap in aps:
        for bp in bps:
            for x in cx:
                out.append(dedup_path([a, ap, (x, ap[1]), (x, bp[1]), bp, b]))
            for y in cy:
                out.append(dedup_path([a, ap, (ap[0], y), (bp[0], y), bp, b]))
            out.append(dedup_path([a, ap, (bp[0], ap[1]), bp, b]))
            out.append(dedup_path([a, ap, (ap[0], bp[1]), bp, b]))
    return out


def bends(path):
    return max(0, len(path) - 2)


def free_runs(iv, lo, hi, min_gap):
    r"""占位区间 `iv`（可重叠 ✓，内部会排序 ✓）在 `[lo, hi]` 里的**空档** ✓

    ★ 只返回**宽度 ≥ `min_gap`** 的空档 ✓（窄得放不下线的直接不算 ✓）。
    """
    out, cur = [], lo
    for a, b in sorted(iv):
        if a - cur >= min_gap:
            out.append((cur, a))
        cur = max(cur, b)
    if hi - cur >= min_gap:
        out.append((cur, hi))
    return out


# ★★ **小于这个长度**的段视为“没有” ✓（2026-09-28 ✓）—— 取 **0.05 单位 = 0.014 mm** ✓
#   = 全仓“碰到 / 落在”的**同一个容差** ✓（**不新造数** ✗）。
#   实测（2026-09-28 ✓）：`v16` 里有 **4 根 0.000~0.001 单位**的“**点导线**” ✗ ——
#   **引脚坐标与通道网格差一点点** ⇒ 生出一小截 ✗ ⇒ 被当成“导线”写出去了 ✗。
#   电气上无害 ✓（Fritzing 的连接只认 `<connects>` ✓），但是**垃圾** ✗、
#   而且任何“几何 vs 表”的检查都会当成“跨视图残留/点接头”报出来 ✗ ⇒ 必须消掉 ✓。
MIN_SEG = 0.05

# ★★ `FREECORR`：**空地走廊** ✓（2026-09-28 ✓ 换**机制**，不是再加开关找参数 ✓）
#   病根（今日四次失败共同指向的那一个 ✓）：现在的通道集是
#     “**元件盒边 ± `CH_OFFS`（4 档）**” + 引脚坐标 ✗ ⇒ **与元件盒耦合** ✗
#     ⇒ 一挪元件 / 一删通道，通道集自己就乱 ✗（`--socket 4/7`、`--chans 2`、`--nopinrows`
#       三条轴实测全灭 ✗，交叉 23 一动不动 ✗，见 `t31`/`t32` ✓）。
#   新机制 ✓（就是把“人画线时会走的地方”算出来 ✓）：
#     ① 把**元件本体**在每个轴上的投影收集起来 ✓；
#     ② 取它们的**空档（gap）** ✓（= 真正可以走线的地带 ✓）；
#     ③ 在每个空档里放 k 条走廊 ✓，位置取 `(i+1)/(k+1)` 分位 ✓，
#        但**离空档两边各 ≥ `CLEAR`** 才要 ✓（即“别贴着元件走” ✓）；
#     ④ 空档太小（< `2×CLEAR` ✓）就**不放走廊** ✓（那儿本来就挤不进线 ✓）。
#   与旧通道集的区别 ✓：
#     · 旧：位置由**元件边**定 ✗ ⇒ 换成“贴着元件走” ✗（也是“骑引脚行列”的来源之一 ✗）；
#     · 新：位置由**空地中央**定 ✓ ⇒ 天然**离开所有元件 ≥ `CLEAR`** ✓、也**天然不在引脚行列上** ✓
#       （引脚列本就在元件边附近 ✓），而且**走廊条数由空间决定** ✓。
#   ★ 引脚坐标仍然保留 ✓（`PIN_X`/`PIN_Y` ✓）—— 不然线进不了脚 ✗。
#   `--freecorr` 打开 ✓；`--freecorr-k N` 改一个空档里放几条（默认 3 ✓）。
FREECORR = False
FREECORR_K = 3

# ★★ `RAILS`：**电源轨** ✓（2026-09-28 ✓ **用户提的架构** ✓，仿面包板的电源轨 ✓）
#   用户原话 ✓：「穿体都是 5V 线和 GND 带来的，可以类似面包板，在**所有步骤之前**，先在图的上方
#     和下方，各画两条贯穿图纸的 5V 线和 GND 线，然后再排元件，元件的 5V 和 GND **优先跟上下的
#     5V/GND 线连接**。……原理图在开始阶段**不用考虑线长约束、图纸大小约束**」✓
#   为什么打在病根上 ✓（实测 ✓）：v18 的 **穿体 6 段全是 `GND`/`5V` 的长横线**穿过
#     `U1`/`LED2`/`C2` ✗（如 `(55,-25.9)→(187,-25.9)` ✓）—— 因为它们现在是**链式**接法 ✓
#     ⇒ 一条线要串起散布全图的脚 ✗ ⇒ 必然横穿别人的肚子 ✗。
#   做法 ✓：`GND`/`5V` **不走链** ✗ ⇒ 每只脚就近**打一条短支线**到上/下电源轨 ✓；轨本身是
#     **预置线段** ✓（不参与重排 ✗ ⇒ `fixed` ✓）。
#   ★★ 两个必须记住的点 ✓：
#     · 轨要在**每个接头 x 处断开** ✓ —— Fritzing 的连接是**端点对端点** ✗ ⇒ 支线落在干线的
#       **中段**上是**连不上**的 ✗（这是 `emit` 里“同点即连”能生效的前提 ✓）。
#     · 轨的 y 在**零件总包围盒之外** ✓（上/下各两条 ✓）⇒ 不压任何元件 ✓、也不在引脚行列上 ✓。
#   `--rails` 打开 ✓（默认关 ✓ ⇒ v18 一字不变 ✓、可逐项复现 ✓）。
RAILS = False
# ★★ 2026-10-04 ✓ `RAIL_ONLY`：**只让点名的网**走水平轨 ✓（`--rails=5V` ✓）
#   ★ 为什么要这个 ✗：用户 2026-10-04 要对比 **B 方案**（GND 走分岛 + 接地符号 ✓）
#     ⇒ 需要“5V 照旧用轨 ✓、GND 不用 ✗”才能**隔离**出 B 的效果 ✓；
#     ✗ 否则一去掉 `--rails`，5V 也一起改 ✗ ⇒ 两个变化混在一起、量不出 B 到底好不好 ✗。
#   ★ 空集 = 全部（原行为 ✓，一字不差 ✓）。
RAIL_ONLY = set()
# ★★ `RAIL_MARGIN`：轨离零件总包围盒多远 ✓
#   ✗ 原来 **7.2**（1 格）**是个 bug** ✗✗ —— 2026-09-28 实测抓住 ✓（`t56_0` 跑出退出码 1 ✓）：
#     5V 上轨落在 `y = -50.4` ✓，而 **U1 上边那 6 只脚在 `y = -43.2`** ✓ ⇒ 两者**正好差 7.2**
#     ⇒ 触发用户那条规则「**导线与不相连的引脚要留安全距离**」✗（`CLEAR_PIN = 7.2` ✓，
#       要求 **≥ 7.2 才算过** ✗，恰好等于不算过 ✓）⇒ 硬闸门直接判不合格 ✗
#     （报错原文：`Wire90012891 U1.connector17 7.20 单位` ✓、`…connector18` ✓、
#      `Wire90012902 U1.connector15..19` ✓ —— 一条轨**蹭了 U1 一整排脚** ✗）。
#   ★★ 这条同时解释了 `t46` 那档「**贴脚 11 → 23**」✗✗ 的真正来源 ✓：
#     我当时只归因于“支线要穿中间元件” ✗ —— **只对了一半** ✗；另一半就是这里 ✓：
#     **轨骑在引脚行上** ⇒ 一条横轨一次性蹭掉十几只脚 ✗。
#   ✓ 修法：**引脚安全距离（7.2）+ 一格（7.2）= 14.4** ✓ —— 两个数都是仓里既有的 ✓（不新造 ✗）。
RAIL_MARGIN = 14.4     # 轨离包围盒多远（2 格 ✓ = CLEAR_PIN + 1 格 ✓）
RAIL_GAP = 14.4        # 同侧两条轨之间（2 格 ✓）

# ★★ `CHAN_N` / `NO_PINROWS`：**从用户手改版量出来的两条规则** ✓（2026-09-28 ✓，同一份 layout ✓）
#   实测（`t30` ✓）：
#     · 手改版：竖线 **14** 个 x ／ 横线 **9** 个 y ✓、总长 **1923.8** ✓、交叉 **11** ✓
#     · 自动版：竖线 **19** 个 x ／ 横线 **19** 个 y ✗、总长 2273.7 ✗、交叉 **23** ✗
#     · 自动版那 19 个 y 里，**6 个正是 `U1` 的引脚行**（−43.2 / −9.0 / 0.0 / 9.0 / 17.0 ✗）
#       —— 这就是“骑行列 0.00 / 线身穿心 / 贴脚”的**病根** ✓
#       （为什么会这样 ✓：通道集里**直接放了引脚坐标** ✓ ⇒ 那几条行列就当上了主干 ✗）。
#     · 手改版的 9 个 y 里**一个引脚行也没有** ✓（−54 / −18.1 / 18 / 26.9 / 65.2 / 77.2 / 85 / 126 / 162 ✓）。
#   ⇒ 两个开关（**默认关** ✓，先 A/B 量了再说 ✓ —— 本仓规矩：不拿没量过的当默认 ✗）：
#     · `--chans N`：每方向只留元件边 ± `CH_OFFS[:N]` 的通道 ✓（= 通道**收敛** ✓）
#     · `--nopinrows`：**别的脚的**行列不再当主干通道 ✓（但**这一对脚自己**的行列仍然保留 ✓
#       —— 不然线进不了脚 ✗）。
#   ★ 与已证伪那条的区别 ✓（别搞混 ✗）：以前那条是“离任何引脚坐标 <`CLEAR_PIN` 就全局丢” ✗
#     ⇒ 通道 72→20 ✗ ⇒ **全线变差** ✗；这里只剔“**正好落在**别的脚行列上”的那几条 ✓（更窄 ✓、
#     而且**这一对脚**的通道一定留 ✓）。
#   ★★ **实测结论：两条都被否掉 ✗（2026-09-28 ✓，`_scratch/t31.py` 四档 A/B ✓）** ——
#      `0` 基线 ｜ `1 --chans 2` ｜ `2 --nopinrows` ｜ `3` 两者（同一 `layout8.fzz` + `--rip 3`）：
#        基线     ：重叠 0 ｜ 贴脚 11 ｜ 交叉 **23** ｜ 穿体 9 ｜ 总长 **2274** ｜ 19/19 通道
#        `--chans 2`：重叠 0 ｜ 贴脚 11 ｜ 交叉 **27** ✗ ｜ 穿体 8 ｜ 总长 **2436** ✗ ｜ **19/19** ✗
#        `--nopinrows`：重叠 0 ｜ 贴脚 **12** ✗ ｜ 交叉 23 ｜ 穿体 9 ｜ 总长 2269 ｜ **18/19** ✗
#      ⇒ **① 通道数根本没降**（19→19 / 19→18 ✗）；**② 交叉反而涨到 27** ✗；**③ 贴脚也差了一点** ✗。
#   ★★ 为什么我错了 ✓（**指标本身是假的** ✗，这是本轮最大的教训 ✓）：
#      “通道签名”数的是**产出线里出现过的不同 x/y** ✓ —— 可每根线**必须从引脚所在的行列出发** ✓
#      ⇒ 那些 y **必然**出现在统计里 ✗ ⇒ **它根本测不出“主干用得多不多”** ✗✗。
#      手改版的 9 个 y 里同样含引脚行 ✓（`18.0` / `−18.1` ✓）⇒ 两边不可比 ✗；
#      我拿这个假指标推出规则②③ ⇒ **推理错、结论也错** ✗（数据没错 ✓，是我读错了意思 ✗）。
#   ⇒ ★ **默认关是最后防线** ✓：两个开关**一组都没启用** ✓，基线仍是 `0` 档 ✓（重叠 0 ✓、(A)(B)(C) 全 0 ✓）。
#     —— 本仓规矩：“不拿没量过的当默认” ✓ 就是为今天这种情形定的 ✓。
CHAN_N = 0                 # 0 = 不限制 ✓（全部 CH_OFFS ✓）；**已证伪 ⇒ 保持 0** ✗
NO_PINROWS = False         # True = 别的脚的行列不当主干通道 ✓；**已证伪 ⇒ 保持 False** ✗

# ★★ `CHAIN`：**每个网内部的「链序」（连接顺序）** ✓（2026-09-28 ✓ 第**四**条候选规则 ✓）
#   为什么换到这一轴 ✗：摆位 / 通道那两条轴**三连否** ✗（`--socket 4/7` 实测：交叉 **23/23/23
#    一动不动** ✗、总长 **+15%** ✗、画布 **+29%** ✗；见 `t32` ✓）—— 根因是**通道集与摆位耦合**
#     ✗（`CH_OFFS` 相对元件边 ✓ ⇒ 一挪元件通道集就乱 ✗）。
#   而**链序**是剩下来唯一没试、又**直击头号指标**（交叉 **23 vs 手改 11** ✓）的一轴 ✓：
#     现状 = 把每网的脚按 `(x, y)` 硬排 ✗（= 链就从左往右串 ✓）—— 人画的时候不会这么死板 ✓。
#   取值 ✓：`xy`（旧默认 ✗）/ `yx` / `revxy` / **`revyx`** / `nn`（最近邻 ✓）
#   ★★ **实测结果（2026-09-28 ✓，`_scratch/t33.py` + `t34.py`，同一 `layout8.fzz` + `--rip 3`）**：
#        档位     重叠 贴脚 交叉 穿体   总长    画布
#        `xy`      0    11   23    9   2274   82.0×86.3   ← 旧默认 ✗
#        `yx`      0    18   10    9   2011   78.7×82.9   ← 交叉最好 ✗ 但贴脚变差 ✗
#        `revxy`   0     9   13   10   2146   **104.0** ✗✗
#        `nn`      0    11   18    6   2018   82.0×86.3   ← **零回退** ✓
#        **`revyx`** 0    11   **10**  10   2060   83.2×82.9   ← ★ **采纳 ✓（兼得 ✓）**
#      ⇒ **交叉 23 → 10** ✓✓（比用户手改版的 11 还好 ✓）、贴脚不变 ✓、总长 −9% ✓、告警 0 ✓；
#        代价只有**穿体 9 → 10** ✗。
#   ★★ **`--hardbody` 复测仍不合格 ✗**（`t35.py` ✓）：`revyx --hardbody` / `nn --hardbody` 都出现
#      **告警 1** ✗ ⇒ 删到没候选又**退回旧候选集**了 ✗ ⇒ “穿体好看”是**假象** ✗（规则没生效 ✗）
#      ⇒ **带告警的档一律不采纳** ✗（这条判据就是为这种情形预先定下的 ✓）。
#   ★ 回旧行为：`--chain xy` ✓（= 旧默认 ✓，可逐项复现 ✓）。
CHAIN = "revyx"
# ★★ `REVPAIR`（`--revpair` ✓，2026-09-28 ✓ **用户提的 A/B 测试** ✓）：
#   链上每一对**反方向**接 ✓ —— 即原本接 `a→b` 的，改成从 `b` 那头起头接 `b→a` ✓。
#   ★ 为什么会不一样 ✗（不是“镜像应该一样” ✓，实测待定 ✓）：
#     ① `esc_cands` 的**四个形状族**对“两端出脚点”是**不对称**的 ✓
#        （`[a,ap,(x,ap.y),(x,bp.y),bp,b]` / `[a,ap,(ap.x,y),(bp.x,y),bp,b]` /
#         `[a,ap,(bp.x,ap.y),bp,b]` / `[a,ap,(ap.x,bp.y),bp,b]` ✓）⇒ 换成 b 起头
#        **会换出另一批形状** ✓（谁先“出脚”、从哪个角拐 ✓ 不一样 ✓）；
#     ② 贪婪布线里**先接的那一对先占 `used`** ✓（链序不变、对内方向一变 ⇒ 后接的能用的路不一样 ✓）。
#   ★ **实测（2026-09-28 ✓，两档 ✓）**：反方向接与不开这一档 **逐段完全相同** ✓
#     （`t72`：只在 A 的 0 段 ｜ 只在 B 的 0 段 ✓；两档指标逐项相同 ✓）
#     ⇒ **方向不构成杠杆** ✗（四个形状族对本例其实是**反向封闭**的 ✓，代价函数也对称 ✓）
#     ⇒ 这一轴到此结案 ✓（留着开关 ✓，以后换摆位/换链序时可以再 A/B 一次 ✓）。
REVPAIR = False
# ★★ `NOESC`（`--noescape=off|all|edge` ✓，2026-09-28 ✓ **用户提的**：
#   「**不出脚，仅限于脚是最边缘的脚吧？**」✓）
#   背景 ✓：`esc_cands` 的“出脚点”只给 `a + 法线 × o`（o = 12.2 / 19.4 ✓）
#     ⇒ “**就直接沿着自己那一列 / 那一行走**”这种形状**压根不在候选里** ✗
#     ⇒ 实测代价 = 一个**多余的拐 + 回头** ✓（`RC` 实测 **+24.4 单位** ✗，用户手改版 ✓）。
#   ★ “不出脚”安全与否**取决于脚在不在最边上** ✓：
#     · **最边缘的脚**（如 `R1.c1` = `R1` 最右那只 ✓）⇒ 腿往**外**走，一个邻居都不碰 ✓；
#     · **中间的脚** ⇒ 腿沿本行/本列走**必然擦过邻居** ✗ ⇒ 两道闸门（`HARD_PIN` 0.05 ✗
#       / `HARD_CLEAR` 7.15 ✗）**本来就会把那些形状删掉** ✓。
#   ⇒ 所以：`all` 与 `edge` 在**结果上应当一致** ✓（`edge` 只是**少生成**那些注定被删的候选 ✓、
#     跑得快些 ✓）；`off` = v24 现状 ✓（可逐项复现 ✓）。
#   ★★ **用户 2026-09-28 定：采用 `all`** ✓（“采用 all”✓）⇒ 默认 = `all` ✓：
#     ✗ 不用“仅最边缘”那道限制 ✓ —— 因为**两道闸门已经等同地做到了** ✓
#     （中间脚那条腿必然 0 距离贴邻居 ✗ ⇒ 必被删 ✓），实测 **`all` 与 `edge` 逐项相同** ✓
#     （档1 = 2699 / 14 / 0 / 0 ✓；档0 = 2545 / 14 / 4 ✓；耗时 5∼6 s ✓）⇒
#     既然用户要“每只脚都可不出脚” ✓，就按**更宽的那个**来 ✓（少一层隐含限制 ✓、更好解释 ✓）。
#   ★ 回旧行为：`--noescape=off` ✓（= v24 ✓，逐字节复现 ✓）。
NOESC = "all"


def pin_hard_bad(path, pin_all, own_pins=(), eps=PIN_EPS):
    r"""★ **硬规则**：**非自己两端**的脚，线**不许**落在它上面 ✓（含“线身穿心” ✗）
    （2026-09-28 ✓ —— 用户发现 v14 有 **9 处线身穿心** ✗ ≤ 图上像接上、实际没连 ✗✗）

    ★ 为什么必须有它 ✗：Fritzing 的连接只记在 `<connects>` 里 ✓ ⇒ `check_netlist.py`
      **结构上看不见“图上的假象”** ✗✗；而本仓今天刚把“几何 vs 连接表”拉出来对（`fake_conn` ✓）
      ⇒ 实测 (A)=0 ✓ 而 **(B)=13** ✗。
    ★★ 豁免 = **这一跳真正的两只脚**（`own_pins` ✓ = 网表里那一对 ✓）：
      ✗ 第一版按“**坐标**落在路径端点上的脚”豁免 ✗ ⇒ **太宽** ⇒ 一根线的**拐点**正好
        落在别人脚上时 ✓ 那个脚也被放行 ✗✗（实测 `--hardpin` 后 (B) 只降到 **4** ✗，
        残留的正是这类“端点看着接上” ✓）⇒ 已改成按**网表**豁免 ✓。
    ★ 与 `body_hard_bad` 同一风格 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓。
    ★ 判据用**唯一一份**点到线段距离 `sch_geom.p2seg` ✓（渲染器的可读性那条也是它 ✓）。
    """
    own = set(own_pins)
    for k in range(len(path) - 1):
        p, q = path[k], path[k + 1]
        for (t, c, x, y) in pin_all:
            if (t, c) in own:
                continue
            if SG.p2seg((x, y), p, q) <= eps:
                return True
    return False


def ovl_hard_bad(path, used):
    r"""★ **硬规则**：这条路径**不许与已布好的线压在同一条直线上** ✓（用户规则② ✓，2026-09-28 ✓）

    ★ 病症（实测 ✓，`t27_1` = v15 + `--hardpin` ✓）：用户规则②（「**不同的导线，不能重叠**」✓）
      原来**只靠软代价**压 ✗（`wt = INT_W[0]×nov + …` ✓）⇒ 一开 `--hardpin` 候选集变小 ⇒
      它**退回 1 对** ✗✗（`Wire90012917 (-6,9)→(22.6,9)` 与 `Wire90012918 (22.6,9)→(10.4,9)`
      在 `y=9` 上压了 12.2 单位 ✓）⇒ **硬规则不能用软代价表达** ✗（与 `HARD_BODY` 同一个理由 ✓）。
    ★ 与 `HARD_BODY`/`HARD_PIN` 同一风格 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓；
      删到一条不剩 ⇒ 调用处保留旧候选集 + 告警 ✓（不许把端点接不上 ✗）。
    ★ 判据用**唯一一份** `sch_geom.near_overlap` ✓（渲染器报“压在一起”也是它 ✓）——
      端点相接（接头 ✓）与十字交叉**都不算**重叠 ✓（口径见 `sch_geom` 头部 ✓）。
    """
    for k in range(len(path) - 1):
        for _u in used:
            # ★ `used` 每一项 = **`(p, q, net)`** ✓（2026-09-28 ✓ 带网名 ✓，T 形搭接要用 ✓）
            #   ⇒ 这里**按下标取** ✓（不写死元数 ✗ ⇒ 以后再加字段不用改消费者 ✓）。
            if SG.near_overlap(path[k], path[k + 1], _u[0], _u[1]):
                return True
    return False


def ovl_partners(path, used, limit=4):
    r"""★ **诊断**：这条路径与 `used` 里**哪些段**共线重叠 ✓（连双方坐标一起报出 ✓）

    ★ 判据仍调**唯一一份** `sch_geom.near_overlap` ✓（判碰只许一份实现 ✗ —— 面包板那天的
      教训 ✓：两套实现混用 ⇒ 数字对不上、还找不到原因 ✗）。
    ★ 为什么需要它 ✗（2026-09-28 ✓）：`GND D3.connector0` 的 12 个候选**全**报
      「与已布线重叠 True」✗ ⇒ 可**跟谁**重叠、是**同网还是异网**，报告里没有 ✗ ⇒
      没法判断「能不能学用户手改版那根」✓（Task 2 ✓）。
    """
    out = []
    for k in range(len(path) - 1):
        for _u in used:
            p2, q2 = _u[0], _u[1]
            if SG.near_overlap(path[k], path[k + 1], p2, q2):
                out.append((path[k], path[k + 1], p2, q2))
                if len(out) >= limit:
                    return out
    return out


def body_hard_bad(path, boxes, pin_all, r_touch=0.05):
    r"""★ **硬闸门**：不许进入**别的**元件的本体 ✓（2026-09-27 ✓，用户定「**穿体必须是 0**」✓）

    ★ 取向（用户已定 ✓）：**硬约束优先，指标该让就让** ✓ —— 闸门**只删候选** ✗，
      **不动**代价函数与档位次序 ✓（保住“重叠 0”的机制 ✓）。
    ★★ 判据的**三版教训** ✓（都写这儿，别再走回去 ✗）：
      ✗ 第一版：豁免“整段两端都在端点 19.4 单位以内” ✗ ⇒ 太宽 ⇒ 实测穿体只降到 **1** ✗；
      ✗ 第二版：**完全不豁免** ✗ ⇒ 穿体**仍是 1** ✗ —— 根因：豁免是**按整条路径**的 ✗
        （`mine` = 这条线两端是谁 ⇒ **整条**都不查那些元件 ✗）⇒ 只要 `L1` 出现在任一端，
        整条线穿 `L1` 都放行 ✗✗（实测 `Wire90012918` 就钻了 **52** 单位深 ✗）。
      ✓ 第三版（现在）：**按段豁免** ✓ —— 只豁免“**这一段**的端点上正好有它的脚”的元件 ✓
        ★ 这一条**与渲染器报“穿体”的口径完全一致** ✓（那边也是按段建 `own` ✓）
          ⇒ “过了这道门 ⇒ 渲染器必不报” 才真的成立 ✓（本仓规矩：判据只能一份口径 ✓）。
    ★ 判据用**内缩**的盒子 ✓（`-0.25` ✓）：比渲染器（内缩 0.5 ✓ + 至少 4 个采样点 ✓）**更严** ✓。
    """
    for k in range(len(path) - 1):
        p, q = path[k], path[k + 1]
        own = {t for (t, _c, x, y) in pin_all
               if math.dist((x, y), p) <= r_touch or math.dist((x, y), q) <= r_touch}
        for t, box in boxes.items():
            if t in own:
                continue
            if seg_hits_box(p, q, box, -0.6):     # ★ (b) 内缩 0.6 > 判据的 0.5 ✓（更保守）
                return True
    return False


def fj_vertex_bad(v, net, used, tol=0.05):
    r"""★ **这个点是不是落在“别的网”的线上** ✗ —— “**跨网假接头**” ✓（2026-09-28 ✓ 用户点名 ✓）

    ★ 病症 ✓（实测 ✓）：一根线的**端点 / 折点**正好搭在**另一根不同网**的线的**中段**上 ✗
      ⇒ 图上**看着接上了** ✓（一个 T 形接头 ✓）、电气上**根本没连** ✗✗
      （Fritzing 只认**端点对端点** ✓ —— 端点落在中段上要**在那点把线断开**才算连 ✓）；
      跨网**端点粘端点**也一样 ✗（同一个“看着接上”的另一半 ✓）。
    ★ 判据调**全仓唯一那份**：`sch_geom.on_seg`（**中段** ✓）+ 点到端点距离 ✓，容差 `0.05` ✓。
    """
    for _u in used:
        if _u[2] == net:                  # ★ 同网 = 真接头 ✓（“T 形搭接”正是在做这个 ✓）
            continue
        if SG.on_seg(v, _u[0], _u[1], tol):
            return True
        if math.dist(v, _u[0]) <= tol or math.dist(v, _u[1]) <= tol:
            return True
    return False


def fj_path_bad(path, net, used, tol=0.05):
    r"""★ 这条路**不许**把**端点 / 折点**搭在**别的网**的线上 ✗（= “跨网假接头” ✗✗，用户点名 ✓）

    ★ 与 `HARD_PIN` / `HARD_OVL` 同一套路 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓；
      删光 ⇒ 调用处保留旧候选集 + 告警 ✓（不许把端点接不上 ✗）。
    ★ 为什么必需 ✗（不只是“后处理收尾” ✓）：v24 那处 `DATA_IN` 就是**路由自己**把**折点**
      落在 5V 竖线中段上造成的 ✗ —— 之所以后来没了，是靠**共线合并**把它抹掉 ✓（运气 ✓）；
      有了这道门 ✓ ⇒ 以后靠**规则** ✓ 而不是靠运气 ✗。
    """
    for _v in path:
        if fj_vertex_bad(_v, net, used, tol):
            return True
    return False


def fj_too_close(v, net, used, gap=None):
    r"""这个点离**别的网**的线是不是**太近** ✗（`< gap` ✓，`gap` 缺省 = `FJ_GAP` ✓）

    ★ 为什么要一个**看得见**的距离 ✗（用户 2026-09-28 ✓：「**要考虑人眼视觉的局限性，
      要尽量清晰**」✓）：
      · “搭上”（距离 ≈ 0 ✓）= **假接头** ✗✗ ⇒ 图上完全分不出是接上还是路过 ✗；
      · “擦着 0.03～0.3 mm”（= 一个线宽以内 ✗）= **一样分不清** ✗✗（实测那种“修法”
        判据上干净了 ✓、肉眼看还是贴在一起 ✗ —— 等于没修 ✗）。
      ⇒ 取 `FJ_GAP = CLEAR_PIN = 7.2 单位 = **2.03 mm**` ✓ —— 就是用户定“导线离引脚
        要多远才看得清”的**同一个数** ✓（一样是“肉眼能不能分出接没接上”这件事 ✓，不新造数 ✗）。
    """
    if gap is None:
        gap = FJ_GAP
    for _u in used:
        if _u[2] == net:                  # ★ 同网随便近 ✓（那是接头 ✓）
            continue
        # ★ 带上全仓那个容差 `PIN_EPS` ✓（与判据同一口径 ✓ —— 实测踩过 ✗：
        #   `7.200000000000003 < 7.2` ⇒ 明明正好 2.03 mm ✗ 却被判“太近” ✗
        #   ⇒ 退让四步全失败 ⇒ 又退回 0.1 那个**看不见**的收法 ✗✗）。
        if SG.p2seg(v, _u[0], _u[1]) < gap - PIN_EPS:
            return True
    return False


def fj_endpoint_used(v, used, net, tol=0.05):
    r"""这个端点上**已经接了同网的线**吗 ✓ —— 接了就**不许**为了避开假接头而挪它 ✗
    （挪了就把一个真接头拆了 ✗✗ —— 宁可留着 + 告警 ✓，也不悄悄拆连接 ✓）。"""
    for _u in used:
        if _u[2] != net:
            continue
        if math.dist(v, _u[0]) <= tol or math.dist(v, _u[1]) <= tol:
            return True
    return False


def out_len(path, ubox, margin=OUT_MARGIN):
    """路径**跑在“所有零件包围盒”之外**的那部分长度 ✓（2026-09-27 ✓，从用户手改版学的 ✓）

    ★ 为什么只罚“出去的那段”而不是禁 ✗：标签、45° 小拐角、引脚伸出的线都会
      略微出框 ✓ —— 那不算往外跑 ✗；真正要打的是“跑到比所有元件还左/还下”的长途绕行 ✓。
    ★ 采样口径与别的判据一致 ✓（每 2 单位一个中点 ✓，用段长 × 命中数 ✓）。
    """
    if not ubox:
        return 0.0
    x0, y0, x1, y1 = (ubox[0] - margin, ubox[1] - margin,
                      ubox[2] + margin, ubox[3] + margin)
    tot = 0.0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        seg = math.dist(p, q)
        if seg < 1e-9:
            continue
        n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
        step = seg / n
        for k in range(n):
            tm = (k + 0.5) / n
            x, y = p[0] + (q[0] - p[0]) * tm, p[1] + (q[1] - p[1]) * tm
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                tot += step
    return tot


def pin_intr_list(path, own, pins_all):
    r"""路径**贴到的引脚清单** ✓（**唯一实现** ✓；`pin_intr` = 它的长度 ✓）

    ★ 为什么拆出来 ✓（2026-09-28 ✓）：实测**同一个形状**（`D3.connector0` 的 T 形搭接候选 ✓）
      在**两档里给出不同贴脚数** ✗（socket0 = 1 ✗、socket4 = 0 ✓）—— 因为这里判距原来是**采样**的 ✗
      ⇒ 结果会被**采样步长**决定 ✗ ⇒ 必须能**点名**是哪只脚、精确距离多少 ✓（用仓里唯一那份
      `sch_geom.p2seg` ✓）才能判它是"真太近"还是"采样跳过去了" ✗。
    ★★ 判距现在**用精确值** ✓（`sch_geom.p2seg` ✓ —— 仓里唯一那一份 ✓）：
      ✗ 原来抽样（每 `P_STEP` 取点 ✗）⇒ `7.2000` 这种**正好压在阈值上**的情形
        会因采样落点不同而 0/1 翻转 ✗✗（同一个形状两档结果不同 ✗）。
      ★ 阈值口径**不变**（仍 `< CLEAR_PIN` ✓）⇒ 与渲染器那条 ④c2 **完全同一口径** ✓。
    """
    if not pins_all:
        return []
    out = []
    for (ref, cid, px, py) in pins_all:
        if (ref, cid) in own:
            continue
        for i in range(len(path) - 1):
            # ★★ 临界上**必须带容差** ✗（2026-09-28 ✓ 实测证据 ✓）：本仓这桩案子
            #   （T 形搭接的搭点**正好落在离伙伴脚 7.2000 单位**处 ✓）里，**同一个形状**
            #   在两档算出 `7.199999999999999` ✗ 与 `7.200000000000003` ✓ —— 纯浮点末位 ✗✗
            #   ⇒ 不带容差时“算不算侵入”就由浮点噪声决定 ✗（socket0 判 1 ✗ / socket4 判 0 ✓）。
            #   ✓ 用全仓既有的那个容差 `PIN_EPS = 0.05` 单位（= 0.014 mm ✓ 肉眼无差 ✓）
            #     ⇒ 有效安全距离 7.15 单位 = 2.02 mm ✓（名义 7.2 = 2.03 mm ✓）。
            #   ★ 渲染器那条 ④c2 已改**同口径** ✓（否则闸门与报告对不上 ✗）。
            if SG.p2seg((px, py), path[i], path[i + 1]) < CLEAR_PIN - PIN_EPS:
                out.append((ref, cid, px, py))
                break
    return out


def pin_intr(path, own, pins_all):
    r"""路径**贴到几个“不相连的引脚”**上 ✓（< CLEAR_PIN 就算 ✓）

    ★ 为什么要这条（2026-09-27 用户定 ✓，原话："导线离芯片引脚太近了…让导线和引脚的连接
      关系**肉眼看得清**" ✓）：引脚线本来就有长度 ✓，导线从它末端擦过去 ⇒ 读图的人分不出
      "接上了"还是"路过" ✗ ⇒ 必须拉开一段可辨的距离 ✓。
    ★ `own` = 这根线自己两端的引脚 ✓ ⇒ 它们当然要“贴上” ✓（那是连接点 ✓ 不算侵入 ✗）。
    """
    return len(pin_intr_list(path, own, pins_all))


def diag_extra(path):
    """斜线比正交**多算**的那部分长度 ✓（= `DIAG_PEN` 罚分 ✓；正交段为 0 ✓）

    ★ 只在**最后一档**（长度）里加 ✓ ⇒ 它压不过"少交叉""不穿本体""不出界" ✓
      —— "正交比斜线好看" ✓，但"斜线能换掉一个交叉 / 缩短一截"时仍然选斜线 ✓。
    """
    e = 0.0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        if abs(p[0] - q[0]) > 1e-6 and abs(p[1] - q[1]) > 1e-6:
            e += (DIAG_PEN - 1.0) * math.hypot(q[0] - p[0], q[1] - p[1])
    return e


def plen(path):
    return sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
               for i in range(len(path) - 1))


def inside_count(path, own_boxes, shrink=0.5):
    """路径有多少采样点落在**自己两端元件的本体里** ✓（用一个很小的罚分去避 ✓）

    ★ 为什么要它（2026-09-27 用户的眼睛发现 ✓）：原来对 `my_boxes` **整个豁免** ✗
      ⇒ 导线为了走直线，会从 **U1 / D3 / LED2 的本体里穿过去** ✗（v3 图上很明显 ✗）。
      ✗ 但不能改成"一律禁止" ✗ —— 有的脚（D3 的 `AC1/AC2` ✓）**本来就在本体内部** ✓，
      禁了就无路可走 ✗。⇒ 改成**记代价** ✓：先选不改路 ✓，再选穿得**最少**的路 ✓。
      判据用**采样点数**当代理长度 ✓（与 `seg_hits_box` 同一套采样 ✓）。
    """
    n = 0
    for i in range(len(path) - 1):
        p, q = path[i], path[i + 1]
        for box in own_boxes:
            if seg_hits_box(p, q, box, -shrink):
                steps = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / 2) + 1)
                for k in range(steps + 1):
                    t = k / steps
                    x = p[0] + (q[0] - p[0]) * t
                    y = p[1] + (q[1] - p[1]) * t
                    if (box[0] + shrink <= x <= box[2] - shrink
                            and box[1] + shrink <= y <= box[3] - shrink):
                        n += 1
    return n


def seg_cross(p, q, r, s, eps=0.05):
    """两段导线的**内部十字交叉** ✓（外壳 ⇒ `sch_geom.seg_cross` ✓，含斜线 ✓）

    ★ 原来是**正交专用**的本地实现 ✗ ⇒ 一放开斜线，“交叉数”就**少算** ✗✗
      （实测：用户手改版按旧判据是 4 ✗、按新判据是 **18** ✓ —— 拿假数字下过结论 ✗）。
      面包板还教过：判据**只能一份实现** ✓。
    """
    return SG.seg_cross(p, q, r, s)


def cross_count(path, used):
    """这条路径会与**已布好的线**十字交叉几处 ✓（用于代价排序 ✓）"""
    n = 0
    for k in range(len(path) - 1):
        for _u in used:
            p2, q2 = _u[0], _u[1]
            if seg_cross(path[k], path[k + 1], p2, q2):
                n += 1
    return n


def _body_hit(path, boxlist, R):
    r"""**钻肚子判据（唯一实现 ✓）** —— 路径有没有**深深穿进**这些盒子里 ✓

    ★ 采样口径与渲染器那一套一致 ✓（内缩 0.5 ✓），`R` = 允许在**路径两端 R 单位以内**
      碰盒子（= “从脚上走出来” ✓）；`R = 0` ⇒ 进盒就算 ✗（别人的元件用这个 ✓）。
    """
    for k in range(len(path) - 1):
        p, q = path[k], path[k + 1]
        for box in boxlist:
            if not seg_hits_box(p, q, box, -0.5):
                continue
            n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
            for i in range(n + 1):
                t = i / n
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                if not (box[0] + 0.5 <= x <= box[2] - 0.5
                        and box[1] + 0.5 <= y <= box[3] - 0.5):
                    continue
                if R > 0.0 and min(math.dist((x, y), path[0]),
                                   math.dist((x, y), path[-1])) <= R:
                    continue                    # 端点附近 = 从脚上出来 ✓ 豁免 ✓
                return True
    return False


def hits_own_body(path, own_boxes, R=10.0):
    """路径是否**穿过了自己两端元件的本体** ✓（隔端点 R 单位**以外**才算 ✗）

    ★★ 为什么要这条硬限制（2026-09-27 实测 ✓）：
      ✗ 原来对 `my_boxes` **整个豁免** ✗（因为脚往往就在本体边界上 ✓，不允许碰就无路可走 ✓）
        ⇒ 但这样一来，布线器发现了一条**漏洞** ✗✗：
        **在元件肚子里走，谁也遇不到 ⇒ 交叉数最低** ✗ ⇒ 它专挑这种路 ✗
        （实测：一段竖直总线从 `U1` 肚子里穿了 **48.5 mm** ✗、还有一段穿 `J1` 9.6 mm ✗）。
      ✓ 现在：自己的本体只允许在**路径两端 R 单位以内**碰 ✓（= "从脚上走出来" ✓）；
        隔得远还在本体里 ⇒ 一律不许 ✓。R = 10 单位 ≈ 2.8 mm ✓（够离开引脚与边界 ✓）。
    """
    return _body_hit(path, own_boxes, R)


def hits_other_body(path, boxes, mine, R=0.0):
    r"""路径是否**钻进了“别人的”元件本体** ✓（`--otherbody` ✓，2026-09-28 ✓）

    ★★ 为什么必须有它 ✗（2026-09-28 实测 ✓，**和“自己本体”那条是同一个漏洞** ✗）：
      当时只补了“自己的元件”✗ —— 而**别人的元件**这里是敞开的 ✗✗：
        `route_key` 里对别人只算 `nv` = **“离盒子 < `CLEAR`(6) 的段数”** ✗，
        而且 `nvb = 1 if nv else 0` ⇒ **布尔化** ✗ ⇒ 于是：
          · “擦着盒边过 1 段” ✓ 与 “从 `U1` 肚子里横穿 124 单位” ✗ **同价** ✗✗
          · 而“钻肚子”还**免费**拿到“零交叉 + 最短” ✓✓ ⇒ 布线器当然选它 ✗
      ⇒ 实测证据（基线 v18 ✓，用渲染器**点名**的穿体段 + 写出的 `.fzz` 颜色反查网 ✓）：
        6 段穿体全是**长横线** ✓ 且都是**最长的几根** ——
        `GND 157.2 单位`（穿 LED2 84 深 + U1 **172** 深 ✗）、`DATA_OUT 157.2`（穿 C2 ✗）、
        `5V 151.6`（穿 U1 **170** 深 ✗）、`5V 132.0`（穿 U1 **124** 深 ✗）、
        `RC 127.2`（穿 C2 ✗）—— 全是“从右边 J2 的脚列一路横穿到左边 U1 的脚列” ✗。
      ⇒ 判据**与 `hits_own_body` 同一个** ✓（`_body_hit` 一份实现 ✓），只是：
        · `R = 0` ✓（**不豁免**：别人的元件不是这条线的落脚点 ✓，没有“从脚上出来”一说 ✓）；
        · 排位与 `hits_own_body` **并列第一** ✓（“不许钻任何元件的肚子” ✓）——
          ✗ **不是**照 `HARD_BODY` 那样“只删候选” ✗（实测那会把候选删光 ⇒ 68 对“找不到候选”
            ⇒ 兜底退回旧候选集 ⇒ 反而更差 ✗，见上面 `HARD_BODY` 那段病史 ✓）。
    """
    return _body_hit(path, [b for t, b in boxes.items() if t not in mine], R)



# ★★★ NL2 ✓（2026-09-29 用户定 ✓）：**功能模块 A** 的零件标题 ✓（其余 = 模块 B ✓）
#   像素板：A = L1/D3/R1/C1 ✓（取能+整流+RC 取出 ✓）；B = 以 MCU 为核心 ✓。
LABEL_MOD_A = set()

# ★★★ NL1 ✓（2026-09-29 ✓）：要贴网标签的**网名**集合 ✓。
#   ✗ 原来只在 `main()` 里 `global LABEL_NETS`（`if _lblv is not None:` 那一支 ✓）⇒
#     **不给 `--label` 开关时这个全局压根没被创建** ✗ ⇒ `emit()` 一读就
#     `NameError: name 'LABEL_NETS' is not defined` ✗✗ ——
#     而"不给开关 ⇒ 行为不变（v29 可复现 ✓）"正是这一支的**唯一用途** ✓
#     ⇒ 等于**承诺的那条路从来没跑过** ✗（2026-09-29 实测复现 v29 时当场撞上 ✓）。
#   ✓ 正解：和 `LABEL_MOD_A` 一样，**模块级给空集初值** ✓（"零 = 不生效" ✓，两种模式都安全 ✓）。
LABEL_NETS = set()

# ★★★ 标签朝向的**候选集** ✓（2026-09-30 ✓ **改正** ✓）：
#   ✗✗ 我 2026-09-29 在这里写过「**不许 180°** ✗，因为 180° 会把字倒着写」✗ ——
#      **那条是错的** ✗✗，2026-09-30 由**用户截图**推翻 ✓（他手改版里那只 `RC`
#      就是 `m11=-1 m22=-1` ✓，**字是正的** ✓）。
#   ✓ 真相（`render_sch.py` 里**同一天早就写对**了 ✓，这边却是旧结论 ✗ —— 同一件事两份口径 ✗）：
#     Fritzing 对标签文字做**自动摆正** ✓ —— `NetLabel::makeSvg` 里
#     `bool reversed = (transform().m11() < -0.5);  // horizontal flip or 180°` ✓
#     ⇒ **`m11 < 0`（镜像 / 180°）时文字不跟着转** ✓（±90° 才是竖排 ✓，用户此前的 `GND` 截图即是 ✓）。
#   ★ 而且 180° 是**唯一**能把旗标摆到**接线点左侧/右侧**两个方向的手段之一 ✓（脚在尖端那侧 ✓，
#     180° ⇒ 脚落在左端 ⇒ 旗标往右伸 ✓）—— 用户手改版正是这么把标签**贴在引脚旁边**的 ✓
#     （离脚 15.4 单位 ✓）。⇒ 放进候选集 ✓，但排在**最后** ✓：
#     挑选键是 `(违例数, 本侧结点远近, 方向, 距离, 朝向)` ✓ ⇒ 朝向只在**前面全平手**时才起作用 ✓，
#     断口那几只标签不受影响 ✓（实测：v33→v34 之外，v35 只挪动了该挪的那只 ✓）。
LBL_ROTS = (0, 90, 270, 180)

# ★★★ 2026-09-30 ✓ **`--ground=<网>`：地网画成「接地符号」** ✓（用户 2026-09-29 的改法 ✓）——
#   · 背景 ✓：`NL1/NL2` 会在功能模块边界把网切开、断口贴同名标签 ✓；用户把**地**那个网的
#     两个 `GND` 标签换成了两个**接地符号** ✓（`_work/v30_byHand.fzz` ✓；同效：Fritzing 的
#     `LocalGrounds` 把全图 `GND/VSS/GROUND` 的脚拉成一张网 ✓ 见 `sch_net.py` 那段源码依据 ✓）。
#   · ★★ 但**不能把符号挂在切口上** ✗（实测 ✗）：切口形状是固定的 ✗，实测那个断口
#     正好是一根长竖线的顶端 ⇒ 往下挂会让**线从符号身上穿过去** ✗ ⇒ 本开关的语义是：
#     **那个网不参与切** ✓ + **在整张网上挑点往下挂** ✓（挑法见 `ground_spots` ✓）——
#     电气上仍靠 `LocalGrounds` 并成一张网 ✓，与“每个模块各一个符号”两全 ✓。
#   · **默认空** ✓ ⇒ 不给开关**一字节不差** ✓（v29 可复现 ✓，实测 26/26 条目相同 ✓）。
GROUND_NETS = set()
# ★★ `--relabel` ✓（用户 2026-09-30 定 ✓）：**布完线之后再拿最终导线当障碍摆一遍位号** ✓
#   —— 为什么、跑在哪、为什么用同一个 `relabel()`，全写在 `emit()` 末尾那段注释里 ✓。
#   ★ **默认关** ✓ ⇒ 不给开关时输出仍与已入库 `v29` **逐字节相同** ✓（回归要守 ✓）。
RELABEL_AFTER = False
# ★★ `--snaprails=<网>` ✓（用户 2026-09-30 定 ✓）：把“**所有脚都在这几个网上**”的件**摆到轨上** ✓
#   —— 口径、为什么必须“先钉住轨再挪件”、以及验收，全写在 `snap_rails()` 的文档串里 ✓。
#   ★ **默认空** ✓ ⇒ 不给开关**一字节不差** ✓（v29 / v35 都可复现 ✓）。
SNAP_RAILS = set()
# ★ `GROUND_GAP`：接地符号的脚离线端多远 ✓（**一个 Fritzing 原理图网格步** = 0.1in = **9 单位** ✓）
#   ★ 出处 = **从用户手改版量的** ✓（两个样本：`10.000` ✓ / `9.039` ✓ —— 都是≈一个网格步 ✓；
#     而它们的**脚 y 分别落在 27 / 153**，都是 9 的整数倍 ✓ = 网格线 ✓）。
#   ★ 这是个**一行可调**的经验值 ✓（改大 ⇒ 符号挂得更低 ✓），不是从原理推的 ✗。
GROUND_GAP = 9.0
LBL_OFFS = (0.0, 7.2, 14.4, 21.6, 28.8, 36.0, 43.2)


def main(argv):
    fzz, svg, out_path = argv[0], argv[1], argv[2]
    if "--ratio" in argv:
        # ★ 尺子的单位换算以**尺子自己**为准 ✓（2026-09-27 加 ✓）：
        #   · Fritzing 导出的 svg = **1/72 in** 一套 ⇒ sketch(1/90in) = 导出 × 1.25 ✓（默认 ✓）；
        #   · 本项目 `render_sch.py` 出的尺子 = **sketch 单位**一套 ⇒ RATIO = **1.0** ✓
        #     （渲染器已对 Fritzing 导出验平 Δ≤0.0004 单位 ✓ ⇒ 不必再让用户手导图 ✗）
        global RATIO
        RATIO = float(argv[argv.index("--ratio") + 1])
        print("尺子换算：RATIO = %.4f（导出尺子 1.25 ✓ / 渲染尺子 1.0 ✓）" % RATIO)
    # ★ 写法**两种都收** ✓（`--label=GND,5V` ✓ / `--label GND,5V` ✓）——
    #   ✗ 我第一版只判 `"--label" in argv` ✗ ⇒ 传 `--label=GND` 时**根本进不来** ✗
    #     （命令行里那个字符串是 `--label=GND` ✗，不等于 `--label` ✗）⇒ 静默没生效 ✗。
    _modv = None
    for _i, _a in enumerate(argv):
        if _a.startswith("--modules="):
            _modv = _a.split("=", 1)[1]
        elif _a == "--modules" and _i + 1 < len(argv):
            _modv = argv[_i + 1]
    if _modv is not None:                     # ★★ NL2 ✓（用户定 ✓：功能模块划分 ✓）
        global LABEL_MOD_A
        LABEL_MOD_A = set(v.strip() for v in _modv.split(",") if v.strip())
        print("★ **NL2 功能模块 A** ✓：%s ✓（其余当作模块 B ✓）"
              % ", ".join(sorted(LABEL_MOD_A)))
    _lblv = None
    for _i, _a in enumerate(argv):
        if _a.startswith("--label="):
            _lblv = _a.split("=", 1)[1]
        elif _a == "--label" and _i + 1 < len(argv):
            _lblv = argv[_i + 1]
    if _lblv is not None:                     # ★★ NL1 ✓（2026-09-29 用户定 ✓，从他手改 pilot 学 ✓）
        global LABEL_NETS
        LABEL_NETS = set(v.strip() for v in _lblv.split(",") if v.strip())
        print("★ **NL1 网标签** ✓：对 `%s` 里的网 ⇒ 切掉一段长直段 ✓、"
              "**两个断口各贴一个同名标签** ✓（电气靠“同名即连通”✓；不给 = 行为不变 ✓）"
              % ", ".join(sorted(LABEL_NETS)))
    # ★★ 2026-09-30 ✓ `--ground=<网>`：地网改画**接地符号** ✓（两种写法都认 ✓ —— 见下 --only 那条教训 ✓）
    _gv = None
    for _i, _a in enumerate(argv):
        if _a.startswith("--ground="):
            _gv = _a.split("=", 1)[1]
        elif _a == "--ground" and _i + 1 < len(argv):
            _gv = argv[_i + 1]
    if _gv is not None:
        global GROUND_NETS
        GROUND_NETS = set(v.strip() for v in _gv.split(",") if v.strip())
        print("★ **`--ground`** ✓：`%s` 网**不切** ✓、改在整张网上**挑点往下挂接地符号** ✓"
              "（每个功能模块一个 ✓；脚离挂点 %.1f 单位 ✓ = 一个网格步 0.1in ✓）"
              % (", ".join(sorted(GROUND_NETS)), GROUND_GAP))
    # ★★ 2026-09-30 ✓ `--trim=<网>`：剪掉那些网里**多余的线** ＋ **把支线改接到更省的点** ✓
    #   （口径与两趟流程见 `trim_plan` ✓；两种写法都认 ✓）
    _tv = None
    for _i, _a in enumerate(argv):
        if _a.startswith("--trim="):
            _tv = _a.split("=", 1)[1]
        elif _a == "--trim" and _i + 1 < len(argv):
            _tv = argv[_i + 1]
    if _tv is not None:
        global TRIM_NETS
        TRIM_NETS = set(v.strip() for v in _tv.split(",") if v.strip())
        print("★ **`--trim`** ✓：剪 `%s` 网里**多余的线** ✓（删了不改终端分块、且不留悬空端 ✓），"
              "并把支线**改接到更省的点** ✓（判据 = 不违反任何规则 ✓ ＋ `长度 + %.1f×交集` 更省 ✓）"
              % (", ".join(sorted(TRIM_NETS)), K_TRIM))
    # ★★★ 2026-09-30 ✓ `--relabel`：**布完线之后再把位号摆一遍** ✓（用户点名的一手 ✓）
    #   · `relabel()` 本来就跑 ✓，但它在 **`emit()` 之前** ✗ —— 那时只有“**计划的**导线” ✗，
    #     而 `emit()` 里导线**还会变**（标签引线 / 改接的新线 / 接地引线 / 共线合并 ✓）
    #     ⇒ 实测 `U1` 的位号正好压在新拉出来的一根线上 ✗（渲染器每次都报 ✓）。
    #   · ✓ 这个开关 = 拿**最终导线**当障碍**再跑一遍同一个 `relabel()`** ✓
    #     （候选位 / 权重 / 判碰全是它那一套 ✓，**不另写一份** ✗）。
    #   · ★ 默认关 ✓ ⇒ 不给开关时输出仍与已入库 `v29` **逐字节相同** ✓（回归要守 ✓）。
    if "--relabel" in argv:
        global RELABEL_AFTER
        RELABEL_AFTER = True
        print("★ **`--relabel`** ✓：布完线（含标签引线 / 改接 / 接地引线 / 共线合并 ✓）之后，"
              "再拿**最终导线**当障碍把位号摆一遍 ✓")
    # ★★ 2026-09-30 ✓ `--snaprails=<网>`：把“所有脚都在这几个网上”的件**摆到轨上** ✓
    #   （口径见 `snap_rails()` ✓；**必须“先钉住轨再挪件”** ✗ —— 只挪件是实测否掉的 ✗）
    _rv = None
    for _i, _a in enumerate(argv):
        if _a.startswith("--snaprails="):
            _rv = _a.split("=", 1)[1]
        elif _a == "--snaprails" and _i + 1 < len(argv):
            _rv = argv[_i + 1]
    if _rv is not None:
        global SNAP_RAILS
        SNAP_RAILS = set(v.strip() for v in _rv.split(",") if v.strip())
        print("★ **`--snaprails`** ✓：把“**所有脚都在 `%s` 上**”的件**摆到轨上** ✓（轨 = 同网最长的光板直段 ✓；"
              "先钉住轨再挪件 ✓ —— 实测“只挪件”会被轨跑掉 ✗）" % ",".join(sorted(SNAP_RAILS)))
    if "--choffs" in argv:                    # 走廊偏移可扫 ✓（逗号分隔 ✓，单位=sketch ✓）
        global CH_OFFS
        CH_OFFS = tuple(float(v) for v in argv[argv.index("--choffs") + 1].split(","))
        print("走廊偏移 CH_OFFS = %s ✓（从“画出来的包围盒”往外量 ✓；第一条要 > CLEAR_PIN=%.1f 才能不贴脚 ✓）"
              % (CH_OFFS, CLEAR_PIN))
    if "--escs" in argv:                      # 出脚长度可扫 ✓（逗号分隔 ✓；一档 = 一条车道 ✓）
        global ESC_OFFS
        ESC_OFFS = tuple(float(v) for v in argv[argv.index("--escs") + 1].split(","))
        print("出脚长度 ESC_OFFS = %s ✓（沿引脚法线往外量 ✓；%d 档 ⇒ %d 条平行车道 ✓；"
              "第一档 > CLEAR_PIN=%.1f 才算离开安全距离 ✓）" % (ESC_OFFS, len(ESC_OFFS), len(ESC_OFFS), CLEAR_PIN))
    if "--why" in argv:                       # 决策探针 ✓（只观测 ✓ 不改行为 ✓）
        global WHY
        WHY = True
        print("决策探针 --why：报首轮**选中 vs 亚军**的代价元组 ✓（不改布线结果 ✓）")
    if "--noesc" in argv:                      # A/B 用 ✓：关掉“出脚组合”候选（回到旧形状集 ✓）
        global USE_ESC
        USE_ESC = False
        print("出脚组合候选：**关闭** ✓（`--noesc` = A 基线的一半 ✓）")
    if "--oldorder" in argv:                   # A/B 用 ✓：回到旧档位次序（代理规则排在用户规则前 ✓）
        global NEW_ORDER
        NEW_ORDER = False
        print("档位次序：**旧** ✓（`--oldorder`；两个都关 = A 基线 ✓ = v14 一字节不差 ✓）")
    if "--hardpin" in argv:                    # 兼容旧命令 ✓（2026-09-28 起**已默认开** ✓，用户定 ✓）
        print("硬闸门 HARD_PIN：**已是默认 ✓**（`--hardpin` 留作兼容 ✓；要关掉用 `--nopin` ✓）")
    if "--nopin" in argv:                      # A/B 用 ✓：关掉 ⇒ 回到 v15 行为 ✓
        global HARD_PIN
        HARD_PIN = False
        print("硬闸门 HARD_PIN：**关闭** ✓（`--nopin` ⇒ 可一键复现 v15 ✓）")
    if "--noovl" in argv:                      # A/B 用 ✓：关掉规则②的真闸门 ✓
        global HARD_OVL
        HARD_OVL = False
        print("硬闸门 HARD_OVL：**关闭** ✓（`--noovl` ⇒ 回到“重叠只靠软代价”✓）")
    if "--noclear" in argv:                    # A/B 用 ✓：关掉“贴脚零容忍”这道闸门 ✓
        global HARD_CLEAR
        HARD_CLEAR = False
        print("硬闸门 HARD_CLEAR：**关闭** ✓（`--noclear` ⇒ 回到“贴脚只靠软代价”= v23 ✓）")
    if "--nofj" in argv:                       # A/B 用 ✓：关掉“跨网假接头”判据 ✓
        global HARD_FJ
        HARD_FJ = False
        print("硬闸门 HARD_FJ：**关闭** ✓（`--nofj` ⇒ 回到 v25：跨网假接头不拦 ✗）")
    if "--chans" in argv:                      # 实验 ✓：通道收敛（每方向只留前 N 档 ✓）
        global CHAN_N
        CHAN_N = int(argv[argv.index("--chans") + 1])
        print("通道收敛 CHAN_N = %d ✓（每方向只留元件边 ± 前 %d 档 = %s）"
              % (CHAN_N, CHAN_N, CH_OFFS[:CHAN_N]))
    if "--nopinrows" in argv:                  # 实验 ✓：别的脚的**行列**不当主干通道 ✓
        global NO_PINROWS
        NO_PINROWS = True
        print("引脚行列回避 NO_PINROWS：**开** ✓（别的脚的行列不当主干 ✓；这一对脚自己的保留 ✓）")
    if "--chain" in argv:                      # 实验 ✓：每网内部的**链序** ✓（第 4 条候选规则 ✓）
        global CHAIN
        CHAIN = argv[argv.index("--chain") + 1]
        print("链序 CHAIN = %s ✓（xy=旧默认 ✓ / yx / revxy / revyx=采纳 ✓ / nn=最近邻 ✓）" % CHAIN)
    if "--revpair" in argv:                    # ★ A/B 用 ✓：链上每一对**反方向**接 ✓（2026-09-28 ✓ 用户提 ✓）
        global REVPAIR
        REVPAIR = True
        print("对内方向 REVPAIR：**反方向** ✓（每对改从另一端起头接 ✓；与不开这一档逐项对比 ✓）")
    # ★★ `--noescape=off|all|edge` ✓（支持“空格”与“=”两种写法 ✓ —— 本仓两种都出现过 ✓）
    if ("--noescape" in argv
            or any(_a.startswith("--noescape=") for _a in argv)):
        global NOESC
        if "--noescape" in argv and argv.index("--noescape") + 1 < len(argv):
            NOESC = argv[argv.index("--noescape") + 1]
        else:
            NOESC = next(_a.split("=", 1)[1] for _a in argv if _a.startswith("--noescape="))
        print("不出脚候选 NOESC = %s ✓（off=现状 ✓ / all=每只脚都给 ✓ / "
              "edge=**只给最边缘那只脚** ✓）" % NOESC)
    if "--freecorr" in argv:                   # ★★ 换机制 ✓：走廊改成**从空地算** ✓
        global FREECORR
        FREECORR = True
        print("空地走廊 FREECORR：**开** ✓（元件盒空档的中央当走廊 ✓，不再用“元件边 ± CH_OFFS” ✗）")
    if "--freecorr-k" in argv:                 # 一个空档里放几条走廊 ✓
        global FREECORR_K
        FREECORR_K = int(argv[argv.index("--freecorr-k") + 1])
        print("空地走廊条数 FREECORR_K = %d ✓（每个空档里按 (i+1)/(k+1) 分位放 ✓）" % FREECORR_K)
    for _i, _a in enumerate(argv):            # ★★ 2026-10-04 ✓ `--rails` / `--rails=<网,…>`
        #   ★ 为什么要能**点名** ✗：用户 2026-10-04 要对比 **B 方案**（GND 改走**分岛 + 接地符号** ✓）
        #     ⇒ 必须能“**只让 5V 用水平轨** ✓、GND 不用 ✗”才能**隔离**出 B 的效果 ✓
        #     —— ✗ 否则一去掉 `--rails` 就连 5V 也一起改了 ✗ ⇒ 两个变化混在一起，量不出 B 到底好不好 ✗
        #     （实测：不带 `--rails` 的 B1 = 48 根 / 644.1mm / 交叉 **35** ✗ —— 但那 35 里混了 5V 的账 ✗）。
        #   ★ 不给 `=` ⇒ 行为**与原来一字不差** ✓（全部有轨的网都走轨 ✓）。
        _rv2 = None
        if _a.startswith("--rails="):
            _rv2 = _a.split("=", 1)[1]
        elif _a == "--rails" and _i + 1 < len(argv) and not argv[_i + 1].startswith("-"):
            _rv2 = argv[_i + 1]
        if _a == "--rails" or _a.startswith("--rails="):
            global RAILS, RAIL_ONLY
            RAILS = True
            RAIL_ONLY = set(v.strip() for v in (_rv2 or "").split(",") if v.strip())
            print("电源轨 RAILS：**开** ✓（%s 每脚就近接上/下轨 ✓，不再走链 ✗）"
                  % ("`%s` 这几个网" % ",".join(sorted(RAIL_ONLY)) if RAIL_ONLY
                     else "GND/5V"))
            break
    if "--ring" in argv:                       # 实验 ✓：开“元件外圈环廊”（默认关 ✓）
        global OUTER_RING
        OUTER_RING = True
        print("外圈环廊 OUTER_RING：**开** ✓（从 UBOX 往外 %s ✓）" % (RING_OFFS,))
    if "--star" in argv:                       # 实验 ✓：指定星形拓扑的网（默认空 ✓）
        global STAR_NETS
        STAR_NETS = set((argv[argv.index("--star") + 1] or "").split(",")) - {""}
        print("星形拓扑 STAR_NETS = %s ✓" % (sorted(STAR_NETS) or "(空)"))
    # ★★ 2026-10-03 ✓ `--vlanes=<网>`：这些网改走**竖直车道** ✓（两种写法都认 ✓ —— 见上面
    #   `--label` 那条教训 ✗：只判 `"--vlanes" in argv` 的话 `--vlanes=GND` **进不来** ✗）
    global VLANES
    for _i, _a in enumerate(argv):
        _vv = None
        if _a.startswith("--vlanes="):
            _vv = _a.split("=", 1)[1]
        elif _a == "--vlanes" and _i + 1 < len(argv):
            _vv = argv[_i + 1]
        if _vv is not None:
            VLANES, VLANE_X = set(), {}
            for _vvx in _vv.split(","):
                _vvx = _vvx.strip()
                if not _vvx:
                    continue
                if "@" in _vvx:                # ★ `网@x1:x2:…` ✓（一个网可以给**多条**车道 ✓）
                    #   ✗ 实测踩的 ✗：原来车道之间也用 `,` 分隔 ✗ —— 而 `,` 在**外层**是
                    #     “**多个网**”的分隔符 ✗ ⇒ `GND@210.58,66` 里的 `66` 被当成**网名** ✗
                    #     （日志里印出 “`66,GND` 网” ✗ ⇒ 车道一条也没多 ✓）。
                    #   ✓ 现在：网与网之间用 `,` ✓；**同一个网的多条车道用 `:`（也认 `;`）** ✓。
                    _n2, _x2 = _vvx.split("@", 1)
                    VLANES.add(_n2.strip())
                    for _t2 in _x2.replace(";", ":").split(":"):
                        _t2 = _t2.strip()
                        if not _t2:
                            continue
                        try:
                            VLANE_X.setdefault(_n2.strip(), []).append(float(_t2))
                        except ValueError:
                            print("⚠ `--vlanes=%s` 里的 x 读不出数 ✗ ⇒ 跳过这个值 ✓" % _vvx)
                else:
                    VLANES.add(_vvx)
            break
    if VLANES:
        print("★ **`--vlanes`** ✓：`%s` 网多一条**竖直车道**可选 ✓（哪只脚走它由距离定 ✓；"
              "其它网**一字节不动** ✓）%s"
              % (",".join(sorted(VLANES)),
                 "；**用户指定车道 x** ✓：%s"
                 % ", ".join("%s @ %s" % (k, "/".join("%.3f" % _v for _v in v))
                             for k, v in sorted(VLANE_X.items()))
                 if VLANE_X else ""))
    # ★★ `--islands=<网>` ✓（两种写法都认 ✓）—— 允许这些网在原理图里**分岛** ✓
    global ISLAND_NETS
    for _i, _a in enumerate(argv):
        _iv = None
        if _a.startswith("--islands="):
            _iv = _a.split("=", 1)[1]
        elif _a == "--islands" and _i + 1 < len(argv):
            _iv = argv[_i + 1]
        if _iv is not None:
            ISLAND_NETS = set(v.strip() for v in _iv.split(",") if v.strip())
            break
    if ISLAND_NETS:
        print("★ **`--islands`** ✓：`%s` 网**允许在原理图里分岛** ✓（不画“轨间互连”✗）——"
              "依据：**Fritzing 的网是跨视图算的** ✓ ⇒ 岛的连续性由**面包板/PCB** 提供 ✓"
              % ",".join(sorted(ISLAND_NETS)))
    if "--hardbody" in argv:                   # 实验 ✓：开启“不许进别人本体”的硬闸门（默认关 ✓）
        global HARD_BODY
        HARD_BODY = True
        print("硬闸门 HARD_BODY：**开启** ✓（`--hardbody` 实验 ✓；实测会多出 68 处“没候选” ✗）")
    if "--otherbody" in argv:                  # ★★ 第二手 ✓：不许**钻“别人的”肚子** ✓（软代价 ✓）
        global OTHER_BODY
        OTHER_BODY = True
        print("钻别人肚子 OTHER_BODY：**开** ✓（“进别人的元件本体”与“穿自己本体”并列第一档 ✓；"
              "★ 软代价、**不删候选** ✓ —— 与 `--hardbody` 的“只删候选”不同 ✗ ✓）")
    # ★★ 只布几个网 ✓（先出天地轨的中间产物 ✓）—— ★ 支持**两种写法** ✓（2026-09-28 修 ✗）：
    #   ✗ 原来只认 `--only GND,5V`（空格式 ✗），而驱动脚本写的却是 `--only=GND,5V`（等号式 ✗）
    #     ⇒ 那个 `if "--only" in argv` **静默为假** ✗✗ ⇒ `t56_0` / `t56_1` 其实都是“**全布**”✗、
    #        而且两档**完全重复** ✗（白跑一档 ✓）。
    #   ★ 教训：**开关的名字别只按一种写法匹配** ✗ —— 本仓两种写法都出现过 ✓
    #     （`--pins-out=` 必须带等号 ✗ / `--rails` 只能空格 ✗ ⇒ 很容易踩 ✓；
    #      其它开关先不动 ✗，但**新开关一律两种都认** ✓）。
    _only = None
    if "--only" in argv:
        _only = argv[argv.index("--only") + 1]
    else:
        _only = next((a.split("=", 1)[1] for a in argv if a.startswith("--only=")), None)
    if _only is not None:
        global ONLY_NETS
        ONLY_NETS = set(_only.split(",")) - {""}
        print("只布这些网 ONLY_NETS = %s ✓（中间产物 ✓：其余网这一轮不布 ✓）" % sorted(ONLY_NETS))
    if "--rip" in argv:                       # 抽出重排轮数 ✓（默认 3 ✓；0 = 关 ✓）
        global RIP_ROUNDS
        RIP_ROUNDS = int(argv[argv.index("--rip") + 1])
        print("抽出重排轮数 RIP_ROUNDS = %d ✓" % RIP_ROUNDS)
    if "--Kout" in argv:                      # “出界长度”的倍率 ✓（默认 10 ✓）
        global K_OUT
        K_OUT = float(argv[argv.index("--Kout") + 1])
        print("出界代价 K_OUT = %.1f（越大越不许线跑出零件包围盒 ✓）" % K_OUT)
    if "--K" in argv:                         # 一个“交集”值多少长度 ✓（默认 35.4 = 10mm ✓）
        global K_INTER
        K_INTER = float(argv[argv.index("--K") + 1])
        print("交集当量 K_INTER = %.1f sketch 单位（= %.1f mm ✓；越大越看重少交叉 ✓）"
              % (K_INTER, K_INTER * 25.4 / 90.0))
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None
    if "--no45" in argv:                     # A/B 用 ✓：关掉 45° 候选（只留正交 ✓）
        global USE45
        USE45 = False
        print("45° 斜线：**关闭** ✓（只走正交 ✓，用于 A/B 对照 ✓）")
    if "--diag" in argv:                      # 斜线罚分可调 ✓（默认 1.25 ✓）
        global DIAG_PEN
        DIAG_PEN = float(argv[argv.index("--diag") + 1])
        print("斜线罚分 DIAG_PEN = %.2f（1.0 = 斜线与正交同价 ✓；越大越少用斜线 ✓）" % DIAG_PEN)
    orig = [argv[argv.index("--orig") + 1]] if "--orig" in argv else [None]
    if "--pins" in argv:                      # 载入标定过的脚位置 ✓
        import importlib.util
        p = argv[argv.index("--pins") + 1]
        spec = importlib.util.spec_from_file_location("pins_fixed", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PINS_FIX.update(mod.PINS)
        print("标定脚位置: 载入 %d 个元件（%s）" % (len(PINS_FIX), p))

    sroot, insts, z, fit = load_geom(fzz, svg)
    print("画布: %d 个实例（%s）" % (len(insts), ", ".join(sorted(insts))))
    print("映射: %d 个脚拟合 ⇒ x: 导出=%.6f·sketch+%.3f（残差 %.4f）✓  y: 导出=%.6f·sketch+%.3f（残差 %.4f）✓"
          % (fit["n"], fit["x"][0], fit["x"][1], fit["x"][2],
             fit["y"][0], fit["y"][1], fit["y"][2]))

    # ★★★ 2026-10-04 ✓ **把网锚点接进各自的网** ✗（用户 2026-10-04 报的两个毛病都指向它 ✓）
    #   ★ 放在这里的原因 ✓：上面那两条 `print`（实例数 / 映射）保持**原样** ✓
    #     —— 锚点只是**换了个键**（`@<modelIndex>` ✓），实例数不变 ✓、名字日志也不变 ✓。
    #   ★ 认不出网名就**如实报出来** ✓（不静默 ✓、也不瞎猜一个网塞进去 ✗）。
    _anch_add, _anch_bad = [], []
    # ★★ 先给「取不到脚位」的锚点补一遍 ✓ —— 从**用户手画原图**里取它接的那根线的端点 ✓
    #   （= 它在 Fritzing 里的真脚点 ✓）。✗ 为什么尺子取不到 ✗：core `netlabel.fzp` 的原理图 svg
    #   **根本不画终端** ✗（只有一个 `<polygon>` + `<text>` ✓）⇒ 尺子里没有它的脚位 ✗；
    #   而它的连接点**也不在实例原点** ✗（实测偏 (12.5,4.5) ✓）。
    _noPin = [(k, d) for k, d in insts.items() if k.startswith("@") and not d.get("pins")]
    if _noPin and orig[0]:
        _op = anchor_pins_from_orig(orig[0], [str(d["mi"]) for _, d in _noPin])
        for _k2, _d2 in _noPin:
            _p2 = _op.get(str(_d2["mi"]))
            if _p2:
                _d2["pins"] = {"connector0": _p2}     # ★ 原图坐标与实例几何**同一空间** ✓（都是 .fz ✓）
                #   ⇒ 直接当 sketch 坐标用 ✓；**不动 `pins_export`** ✗（那是导出空间 ✓，
                #     塞错会让后面的全局拟合跟着偏 ✗）
                print("   ✓ 锚点 **%s**（%s）从**原图**取到真脚点 ✓ (%.3f,%.3f) ✓（离它接的线端点最近 ✓）"
                      % (_d2.get("anchor_title"), _d2.get("anchor"), _p2[0], _p2[1]))
    for _k, _d in list(insts.items()):
        if not _k.startswith("@"):
            continue
        _net2 = _d.get("anchor")
        if not _d.get("pins"):
            # ★★ 取不到脚位 ⇒ **跳过、不崩** ✗（✗ 第一版直接接上去 ⇒ `pin_of` 抛 SystemExit ✗
            #   ⇒ **整个生成失败** ✗✗ —— 一个件认不出，不该把整张图带下水 ✗）
            _anch_bad.append("%s（%s ✗ **脚位取不到** ✗）" % (_d.get("anchor_title"), _net2))
            continue
        if _net2 in NETS:
            NETS[_net2].append((_k, "#1"))       # `#1` = 它的第 1 个脚（= connector0 ✓）
            _anch_add.append("%s→%s" % (_d.get("anchor_title"), _net2))
        else:
            _anch_bad.append("%s（网 `%s` ✗ 不在网表里）" % (_d.get("anchor_title"), _net2))
    if _anch_add:
        print("★ **网锚点进网** ✓：%d 个（%s ✓）—— 它们原来**在输入里就悬空** ✗"
              "（剥线后一个连接都没有 ✓）" % (len(_anch_add), ", ".join(_anch_add)))
    else:
        print("★ **网锚点进网** ✓：输入里没有悬空的网标签/接地符号 ✓")
    if _anch_bad:
        print("   ⚠ 这些锚点**认不出网名** ✗ ⇒ 本次**不接**（请人看一瞩 ✓）：%s" % "; ".join(_anch_bad))

    # ★★★ 2026-10-04 ✓ **「省线」= 带 ≥2 个标签的网按标签分岛** ✓（用户报的毛病① ✓）
    #   ✗ 病（用户原话 ✓）：「**RC 标签没有把中间的线省去**」✗ —— 标签贴在那儿 ✓，
    #     可整张网还是一条长线连到底 ✗ ⇒ 标签成了摆设 ✗。
    #   ✓ 口径（就是网标签的本来含义 ✓）：**同名即连通** ✓ ⇒ 每个岛各自接到**自己的那个标签** ✓
    #     即可 ✓ ⇒ **岛与岛之间那一段线根本不画** ✓✓。
    #   ★ 怎么分（数据决定 ✓，不猜 ✗）：每只**非标签**的脚 ⇒ 归**离它最近的那个标签** ✓。
    #   ★ 实现：把 `NETS["RC"]` 换成 `NETS["RC-1"]` / `NETS["RC-2"]` ✓ ⇒ 后面整套机器
    #     （布线 / 自检 / 上色）**照旧跑** ✓，只是它们各自是一个“小网” ✓；颜色跟着原名 ✓。
    #   ★ 只在**真有 ≥2 个标签**且**两边都分到脚**时才动 ✓ ⇒ 否则一字不改 ✓。
    _lbl_of = {}
    for _k, _d in insts.items():
        # ★★ 只收**真网标签**（`NetLabelModuleID`）✗ —— ✗ **地符号不能当分岛点** ✗：
        #   它不靠“同名”连通 ✓、靠**导线** ✓ ⇒ 拿它分岛 ⇒ 实测交叉 26 → **32** ✗✗、
        #   还多 1 对重叠 ✗（GND 被切成 4+7 两只小网、各算各的轨 ✓）。
        if (_k.startswith("@") and _d.get("pins") and _d.get("anchor")
                and _d.get("anchor_kind") == "netlabel"):
            _lbl_of.setdefault(_d["anchor"], []).append(_k)
    for _net3 in sorted(_lbl_of):
        _ks = sorted(_lbl_of[_net3])
        if len(_ks) < 2 or _net3 not in NETS:
            continue
        _others = [x for x in NETS[_net3] if x[0] not in _ks]
        if not _others:
            continue
        _pos = {k: insts[k]["pins"]["connector0"] for k in _ks}
        _isl = {k: [] for k in _ks}
        for _r3, _n3 in _others:
            _p3 = pin_of(insts, _r3, _n3)[1]
            _isl[min(_ks, key=lambda k: math.dist(_pos[k], _p3))].append((_r3, _n3))
        _new = {}
        for _i3, _k3 in enumerate(_ks, 1):
            if not _isl[_k3]:
                continue
            _nm3 = "%s-%d" % (_net3, _i3)
            _new[_nm3] = _isl[_k3] + [(_k3, "#1")]
            NET_COLOR[_nm3] = NET_COLOR.get(_net3, "#404040")
        if len(_new) >= 2:
            del NETS[_net3]
            NETS.update(_new)
            print("   ★ 网 **%s** 按**已有的 %d 个标签**分岛 ✓ ⇒ %s ✓（同名即连通 ✓ ⇒ "
                  "**中间那段线不画了** ✓ = 用户要的「省线」✓）"
                  % (_net3, len(_ks), " / ".join("%s（%d 只脚 ✓）" % (n, len(v))
                                                 for n, v in sorted(_new.items()))))

    chx, chy = set(), set()
    # ★★★ 2026-09-30 ✓ `--snaprails=<网>`：**骑轨件在“布线之前”就先摆到轨上** ✓（结构性 ✓）
    #   顺序是关键 ✗✓：**先用“其它件”的包围盒定轨 ✓ → 再把骑轨件摆上去 ✓** ——
    #   ✗ 反过来的话（先摆件再算轨 ✓）**轨会跟着它跑** ✗ ⇒ 脚永远追不上轨 ✗
    #     （实测总长 1971.3 ✗，比不摆还差 ✗）；
    #   ✗ 而“收尾再挪”（`snap_rails` ✓）会撞上另一个毛病 ✓：**轨留着“为旧脚位延伸出来的”那一段** ✗
    #     ⇒ 件一挪，那一段就从它的新身体里穿过去 ✗（实测当场复验不过 ✓）。
    HUG_UBOX = None
    if RAILS and SNAP_RAILS:
        _hug = rail_huggers(insts, SNAP_RAILS)
        if _hug:
            _hugset = {q for q, _pl, _d in _hug}
            _rest = [d["box"] for t, d in insts.items()
                     if t not in _hugset and d.get("box")
                     and "breadboard" not in t.lower()]
            if _rest:
                HUG_UBOX = (min(b[0] for b in _rest), min(b[1] for b in _rest),
                            max(b[2] for b in _rest), max(b[3] for b in _rest))
                print("   ★ 骑轨预摆位 ✓：轨按**其它件**的包围盒锚定（y %.1f…%.1f ✓；"
                      "骑轨件 %s ✓ **不算进这个盒子** ✗ ⇒ 摆上去不会把轨带跑 ✓）"
                      % (HUG_UBOX[1], HUG_UBOX[3], ", ".join(sorted(_hugset))))
                rail_hug_place(insts, _hug, rail_y_map(HUG_UBOX))
    # ★★ **干净通道** ✓：只收“元件边 ± `CH_OFFS`” ✓ —— **不放任何引脚坐标** ✗
    #   ⇒ 出脚组合（`esc_cands` ✓）只准用干净通道 ✓；直连 / L 形 / 45° 仍用 `chx/chy` ✓
    #     （它们“进脚”那一段本来就必须落在引脚行列上 ✓ —— 那是连接点 ✓）。
    #   ✗ 已证伪并回退的做法（2026-09-27 ✓，太粗暴 ✗）：把**全局**通道按“离任何引脚坐标 <
    #     `CLEAR_PIN` 就丢”过滤 ✗ ⇒ 实测 x 72→**20** ✗、y 72→**26** ✗ ⇒ 通道不够 ⇒
    #     贴脚 **11→16** ✗、重叠 **0→1** ✗、穿体 **6→8** ✗、总长 +5% ✗ ——
    #     **全部指标一起变差** ✗（= “通道少 ⇒ 布线器没路可走” ✓）。
    #   ✓ 正确做法（有针对性 ✓）：只把**出脚候选里、跨度内会贴着引脚跑**的那几条车道剔掉 ✓
    #     （跨度是知道的 ✓ ⇒ 能精确判 ✓），全局通道一条不动 ✓。
    chx_clean, chy_clean = set(), set()
    for d in insts.values():
        b = d["box"]
        # ✗ 试过把“走廊从含引脚的边界起算” ✗ ⇒ 实测侵入反而 13 → **19 处** ✗（回退 ✓）。
        #   ★ 为什么这条路走不通 ✓（同一天晚些时候由 `--why` 探针弄清 ✓）：
        #     病根**不是**“谁占哪条走廊” ✗，而是**候选形状里没有“沿法线出脚”那一种** ✗
        #     ⇒ 只能“进脚 / 出脚都在排内跑” ✗ ⇒ 怎么挪走廊都没用 ✗。
        #     正解 = `esc_cands` ✓（见 `ESC_OFFS` 那段完整病史 ✓）。
        #   ⇒ 这一条保持回退 ✓（不再往这个方向打补丁 ✗）。
        if b:
            chx.update(b[0] - o for o in CH_OFFS)
            chx.update(b[2] + o for o in CH_OFFS)
            chy.update(b[1] - o for o in CH_OFFS)
            chy.update(b[3] + o for o in CH_OFFS)
            chx_clean.update(b[0] - o for o in CH_OFFS)
            chx_clean.update(b[2] + o for o in CH_OFFS)
            chy_clean.update(b[1] - o for o in CH_OFFS)
            chy_clean.update(b[3] + o for o in CH_OFFS)
        for p in d["pins"].values():
            chx.add(p[0])
            chy.add(p[1])
    # ✗ 另试过“沿引脚轴向逃出去”的通道（`ESC_PIN` 单值 ✓）⇒ 侵入 13 → **15** ✗（也回退 ✓）。
    #   当时的解释是“主干型长线从一整排脚前面经过 ⇒ 走廊归属问题” ✗ —— **不够准** ✓；
    #   真正的毛病是：那种“车道形状”的**出脚方向是错的** ✗（横形状的末段会沿底排行跑 ✗、
    #   竖形状的首段会沿左排列跑 ✗ ✓，实测见 `--why` ✓）⇒ 已由 `esc_cands` 修正 ✓。
    # ★★★ 面包板**不算障碍** ✓（2026-09-28 ✓ 探针实测定位 ✓）：
    #   ✗ 它的 `box` 是**整个画布** ✗（实测 `Breadboard1 (0.00,0.00→468.24,151.20)` ✓）
    #     ⇒ `body_hard_bad` 会把**几乎每一根线**都判成“穿体” ✗ ——
    #     实测：**4 条本该合格的 L 形支线全被这道门挡住** ✗（`t58_report.txt` 的探针行：
    #       `↳ 第 1 段 (8.93,98.00)→(8.93,180.00) 命中盒子 **Breadboard1** …` ✗✗）。
    #     而通用路由**看不出** ✗：它“删光了就保留旧候选” ⇒ 误判被兜底掩盖 ✓。
    #   ★ 原理图上**根本不画面包板** ✓（渲染器也是 `⊘ 跳过 Breadboard1` ✓）
    #     ⇒ 它**不是障碍** ✓ ⇒ 从“元件盒 / 引脚点表 / 通道候选”里一律剔除 ✓
    #     （与“面包板退出电气”同一个精神 ✓：它既不参与网 ✓、也不参与几何 ✓）。
    _BB = {t for t, d in insts.items()
           if "breadboard" in t.lower()
           or "breadboard" in (d.get("mid") or "").lower()}
    if _BB:
        print("   ⊘ 面包板**不算障碍** ✓：%s ✓（盒子是整个画布 ✗ ⇒ 不剔除就会让 `body_hard_bad` "
              "把几乎每根线都判成“穿体” ✗；原理图**根本不画它** ✓）" % ", ".join(sorted(_BB)))
    PIN_X = {p[0] for t, d in insts.items() if t not in _BB for p in d["pins"].values()}
    PIN_Y = {p[1] for t, d in insts.items() if t not in _BB for p in d["pins"].values()}
    boxes = {t: d["box"] for t, d in insts.items() if d["box"] and t not in _BB}
    # ★★ 实验①：**通道收敛** ✓（`--chans N` ✓）—— 只留元件边 ± `CH_OFFS[:N]` 的通道 ✓，
    #   **引脚坐标一律保留** ✓（不然线进不了脚 ✗）。只在开关打开时动 ✓（默认一条不动 ✓）。
    if CHAN_N:
        _keep = {o for o in CH_OFFS[:CHAN_N]}

        def _box_chan(v, axis):
            for _t, _b in boxes.items():
                for _e in ((_b[0], _b[2]) if axis == "x" else (_b[1], _b[3])):
                    for _o in _keep:
                        if abs(v - (_e - _o)) < 1e-6 or abs(v - (_e + _o)) < 1e-6:
                            return True
            return False

        _px = {p[0] for d in insts.values() for p in d["pins"].values()}
        _py = {p[1] for d in insts.values() for p in d["pins"].values()}
        _ox, _oy = len(chx), len(chy)
        chx = {v for v in chx if v in _px or _box_chan(v, "x")}
        chy = {v for v in chy if v in _py or _box_chan(v, "y")}
        chx_clean = {v for v in chx_clean if _box_chan(v, "x")}
        chy_clean = {v for v in chy_clean if _box_chan(v, "y")}
        print("通道收敛 ✓：x %d→%d ✓、y %d→%d ✓（干净通道 x %d / y %d ✓）"
              % (_ox, len(chx), _oy, len(chy), len(chx_clean), len(chy_clean)))
    # ★ 零件**总包围盒** ✓（“出界”代价项的参照 ✓）：
    UBOX = None
    if boxes:
        UBOX = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
                max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values()))
        print("零件总包围盒 %.1f,%.1f → %.1f,%.1f（外扩 %.1f 单位 ✓；出界的长按 K_OUT=%.1f 倍罚 ✓）"
              % (UBOX[0], UBOX[1], UBOX[2], UBOX[3], OUT_MARGIN, K_OUT))
    print("keep-out 盒: %s" % ", ".join("%s(%.2f,%.2f→%.2f,%.2f)" % ((t,) + b)
                                         for t, b in sorted(boxes.items())))

    # ★★ 电源轨的 y ✓（`--rails` ✓，2026-09-28 ✓ 用户提的架构 ✓）—— 全部在包围盒**之外** ✓
    #   ★ 2026-09-30 ✓ 公式搬进 `rail_y_map()` ✓（**唯一实现** ✓）：骑轨预摆位要用**同一条** ✓
    #     而且**锚在“其它件”的包围盒**上 ✓（`HUG_UBOX` ✓）—— 骑轨件不算进这个盒子 ✗，
    #     否则它一往上摆、盒子就往上长、轨又跑远 ✗（实测否掉 ✓）。
    RAIL_Y = {}
    if RAILS and UBOX is not None:
        _ub = HUG_UBOX or UBOX
        RAIL_Y = rail_y_map(_ub)
        print("电源轨 ✓：上 GND y=%.1f / 5V y=%.1f ｜ 下 5V y=%.1f / GND y=%.1f ✓"
              "（锚定盒 y %.1f…%.1f ✓%s）"
              % (RAIL_Y["GND"][0], RAIL_Y["5V"][0], RAIL_Y["5V"][1], RAIL_Y["GND"][1],
                 _ub[1], _ub[3],
                 "；**锚在“其它件”上** ✓" if HUG_UBOX else ""))

    # ★★ 空地走廊 ✓（`--freecorr` ✓，2026-09-28 ✓ **换机制** ✓）—— 走廊位置由**空档中央**定 ✓
    #   ① 元件盒在各轴上的投影 ⇒ ② 空档（gap）✓ ⇒ ③ 每个空档里按 `(i+1)/(k+1)` 分位放走廊 ✓
    #   （离空档两边都 ≥ `CLEAR` 才要 ✓；空档 < `2×CLEAR` 就不放 ✓ —— 那儿本来也挤不进线 ✓）
    if FREECORR and UBOX is not None:
        _fx = free_runs([(b[0], b[2]) for b in boxes.values()],
                        UBOX[0] - OUT_MARGIN, UBOX[2] + OUT_MARGIN, 2 * CLEAR)
        _fy = free_runs([(b[1], b[3]) for b in boxes.values()],
                        UBOX[1] - OUT_MARGIN, UBOX[3] + OUT_MARGIN, 2 * CLEAR)

        def _mids(runs):
            vs = []
            for a, b in runs:
                g = b - a
                for i in range(FREECORR_K):
                    v = a + g * (i + 1) / (FREECORR_K + 1)
                    if v - a >= CLEAR and b - v >= CLEAR:
                        vs.append(v)
            return vs

        _mx, _my = _mids(_fx), _mids(_fy)
        chx = set(_mx) | PIN_X                   # ★ 引脚坐标保留 ✓（不然线进不了脚 ✗）
        chy = set(_my) | PIN_Y
        # 干净通道（出脚候选用 ✓）= 那些**不落在引脚行列上**的走廊 ✓
        chx_clean = {v for v in _mx if not any(abs(v - q) <= 0.05 for q in PIN_X)}
        chy_clean = {v for v in _my if not any(abs(v - q) <= 0.05 for q in PIN_Y)}
        print("空地走廊 ✓：x 空档 %d 个 ⇒ 走廊 %d 条（+引脚 = %d ✓）｜ "
              "y 空档 %d 个 ⇒ 走廊 %d 条（+引脚 = %d ✓）｜ 空档下限 %.1f = 2×CLEAR ✓"
              % (len(_fx), len(_mx), len(chx), len(_fy), len(_my), len(chy), 2 * CLEAR))
        print("      x 走廊：%s" % ["%.1f" % v for v in sorted(_mx)])
        print("      y 走廊：%s" % ["%.1f" % v for v in sorted(_my)])

    if OUTER_RING:                             # ★ 外圈环廊 ✓（用户点名的第 1 条 ✓）
        added = 0
        for o in RING_OFFS:
            for s, v in ((chx, UBOX[0] - o), (chx, UBOX[2] + o),
                         (chy, UBOX[1] - o), (chy, UBOX[3] + o)):
                if v not in s:
                    s.add(v)
                    added += 1
            chx_clean.add(UBOX[0] - o)
            chx_clean.add(UBOX[2] + o)
            chy_clean.add(UBOX[1] - o)
            chy_clean.add(UBOX[3] + o)
        print("外圈环廊 ✓：UBOX 外各加 %d 条通道（x %d / y %d ✓）"
              % (len(RING_OFFS), len(chx), len(chy)))
    used, nets_segs, warn = [], {}, []
    # ★ 全图的**引脚点表** ✓（安全距离规则用 ✓）：绝对 sketch 坐标 ✓
    PIN_ALL = [(t, cid, p[0], p[1]) for t, d in insts.items() if t not in _BB
               for cid, p in d["pins"].items()]
    print("引脚点表 %d 个 ✓；安全距离 CLEAR_PIN = %.1f 单位（%.2f mm ✓）"
          % (len(PIN_ALL), CLEAR_PIN, CLEAR_PIN * 25.4 / 90.0))
    # ★ “最边缘的脚”清单 ✓（`--noescape=edge` 用 ✓；面包板照样剔除 ✗）
    EDGE_PTS = edge_pins({t: d for t, d in insts.items() if t not in _BB}, boxes)
    if NOESC != "off":
        print("   不出脚资格 ✓（NOESC=%s ✓）：%d / %d 只脚合格 ✓"
              % (NOESC, len(EDGE_PTS), len(PIN_ALL)))
    # ★ 引脚**法线**表 ✓（出脚方向 ✓，2026-09-27 ✓）：看这个脚贴在它元件包围盒的哪条边上 ✓。
    #   ★ 为什么“贴边”能当法线用 ✓：`boxes` 是**画出来的东西**的包围盒 ✓ ⇒ 引脚线**末端**
    #     就落在盒边上 ✓（实测：U1 左排脚末端的 x 就等于盒左缘 22.6 ✓）。
    #   ★ 落在**盒内部**的脚（如 D3 的 `AC1/AC2` ✓）法线 = (0,0) ⇒ 不出脚 ✓
    #     （否则 “出脚” 会跑进自己肚子里 ✗）。
    PIN_N_BY_XY = {}
    for t, cid, px, py in PIN_ALL:
        # ★ 法线**唯一实现** ✓（`pin_normal` ✓ —— `edge_pins` 也调它 ✓）
        PIN_N_BY_XY[(round(px, 3), round(py, 3))] = pin_normal(px, py, boxes.get(t))
    print("引脚法线表 %d 个 ✓（其中 %d 个能出脚 ✓ —— 贴在元件边上的；其它在元件内部 ✓ 不出脚 ✓）"
          % (len(PIN_N_BY_XY), sum(1 for v in PIN_N_BY_XY.values() if v != (0.0, 0.0))))
    # ★ 布线**次序**：先把电源/地布完 ✓、再布信号 ✓（面包板规则 ⑩ ✓：
    #   “先布电源/地，但**要把中间走廊留给后面的信号线**” ✓）。
    #   这里先只做前半条（次序 ✓）；后半条（给电源/地的“走中间”加权 ✓）还没做 ✗。
    POWER_FIRST = ("GND", "5V")
    net_order = [n for n in POWER_FIRST if n in NETS] + \
                [n for n in sorted(NETS) if n not in POWER_FIRST]

    def trim_on_rail(seg_list, net, rail_ys):
        r"""把“脚→轨”支线里**趴在轨上的多余点**删掉 ✓，并**同步 `used`** ✓（2026-09-28 ✓）

        ★ 为什么要点 ✓（明细实测 ✓，不是推的 ✗）：支线为了避开别人的线，会**沿着轨横走一段**
          才到落点 ✗ —— 而**那一段本来就是轨** ✗（同网 ✓ 同一条水平线 ✓ 电学上同一段导体 ✓）。
          ⇒ 它一删，支线就只剩“竖直 / 斜着到达落点”那一段 ✓ ⇒ **与轨不共线** ✓✓
          ⇒ 实测：`(27.4,43.2)→(55.0,-57.6)` 原来正是“两段（一竖一横）” ✓，现在是**一条斜线** ✓。
        ★★ 两件必须一起做 ✓（否则又白干 ✗）：
          ① **保留最后一个点（= 落点）** ✓ ⇒ 落点**保持不变** ✓ ⇒ 下面建轨时用它当断点依然有效 ✓；
          ② **同步 `used`** ✗ —— ✗ 第一版只改 `path` 不改 `used` ✗ ⇒ 自检拿**陈旧段**报
             “重叠 6 对” ✗✗（而**渲染器从写出的文件量**是 **0 对** ✓ ⇒ 假警报 ✓）。
        ★ 两次调用 ✓（布完支线后 ✓ + 抽出重排后 ✓）：重排会把路径**重算一遍** ✗ ⇒ 又会
          把支线放回轨上 ✗ ⇒ 必须再清一次 ✓。因为**落点不变** ✓，不用重建轨 ✓✓。
        """
        n = 0
        for s in seg_list:
            if s.get("fixed") or s.get("to") is not None:
                continue                          # 只动“脚→轨”支线 ✓
            p = s.get("path") or []
            if len(p) < 2:
                continue
            _ny = p[-1][1]
            _old = [(p[k], p[k + 1], net) for k in range(len(p) - 1)]
            # ★★ 2026-09-28 ✓ **判据改对了** ✗（原版把“支线停在同网竖线上”那条 **剪成只剩 1 个点** ✗✗）：
            #   ✗ 原版：`_k = 第一次出现 y == 末点 y 的点` ✗ —— 对「**沿脚行横走**」的共享竖线
            #     型支线 ✗，它的**首点就在脚行上** ✓ ⇒ `_k = 0` ⇒ `del p[1:]` ⇒ 路径只剩
            #     `[a]` ✗ ⇒ 被当“段被丢弃 ✗”扔掉 ✗ ⇒ **网表 ✗**（U1.connector3 的 GND 断开 ✗）。
            #   ✓ 正解：**“在轨上”= 落在本网某一条轨的 y 上** ✓（`rail_ys` ✓）——
            #     共享竖线型支线**根本不到轨** ✓ ⇒ `_k is None` ⇒ **原样跳过** ✓（形状保留 ✓）。
            _k = next((i for i, q in enumerate(p)
                       if any(abs(q[1] - _ry) < 1e-6 for _ry in rail_ys)), None)
            if _k is None or _k >= len(p) - 1:
                continue                      # 没碰到轨 / 终点就是第一次碰轨 ⇒ 本来就好 ✓
            # ★★ 截到“**第一次碰到轨**”那一点 ✓（2026-09-28 ✓ 第二版实测后改回来 ✓）
            #   ✗ 第二版“删掉所有在轨上的点、保留最后一个落点” ✗ ⇒ 实测**重叠确实归零了 ✓**，
            #     但**副作用**是：支线被逼成**一条斜线** ✗ ⇒ 实测 `Wire90012890`
            #     `(27.4,43.2)→(55.0,-57.6)` **斜穿过 U1 本体 152 单位深** ✗✗
            #     （它原来是“竖直 + 水平”两段 ✓ 绕在 U1 外面 ✓）。
            #   ✓ 截到第一次碰轨处 ⇒ 支线保持竖直 ✓ ⇒ 不会斜穿 ✓；
            #     而“沿轨挪”的那一截交给轨 ✓（同网、同一条水平线 ✓）—— 那一段本来就多余 ✓。
            del p[_k + 1:]
            s["b"] = p[-1]
            _new = [(p[k], p[k + 1], net) for k in range(len(p) - 1)]
            for _sg in _old:                      # ★ 同步 used ✓（陈旧段必须拔掉 ✗）
                if _sg not in _new and _sg in used:
                    used.remove(_sg)
            for _sg in _new:
                if _sg not in used:
                    used.append(_sg)
            n += 1
        return n

    def truncate_branch_at(s, i, junction, net):
        r"""把支线 `s` 在**第 i 段中途**截断到 `junction` 上 ✓（同步 `used` ✓），返回旧值以便回退 ✓

        ★★ 用于「**接管**」那一招 ✓（学用户手改版第三次的**右半** ✓）：邻居那根竖线**跨过**
          本支线的脚行 ✗（`LED2` 的竖线 y: 17 → -72 ✓，而 `J2.c1` 的脚行是 y=9 ✓）
          ⇒ 本支线沿脚行横走过去、**接管脚行以下那截竖线** ✓，邻居**截到交点** ✓
          ⇒ 两线在交点**端点对端点** ✓（Fritzing 只认这个 ✓）；由本支线一路通到轨 ✓。
        ★ 套路与 `trim_on_rail` 完全一致 ✓（改 `path` ✓、改 `b` ✓、**同步 `used`** ✗ ——
          只改一处 ⇒ 自检拿陈旧段报假重叠 ✗，2026-09-28 踩过 ✓）。
        """
        _old = [(s["path"][k], s["path"][k + 1], net) for k in range(len(s["path"]) - 1)]
        _bak = (list(s["path"]), s["b"])
        s["path"] = list(s["path"][:i + 1]) + [junction]
        s["b"] = junction
        _new = [(s["path"][k], s["path"][k + 1], net) for k in range(len(s["path"]) - 1)]
        for _sg in _old:
            if _sg not in _new and _sg in used:
                used.remove(_sg)
        for _sg in _new:
            if _sg not in used:
                used.append(_sg)
        return _bak
    # ★★ `--only=GND,5V` ✓（用户 2026-09-28：「**请先在图上实际画出天地轨来**」✓）——
    #   只布指定的网 ✓ ⇒ 先出**中间产物**：**天地轨 + 元件 + 电源支线** ✓（第 ①～③ 步 ✓）。
    #   ★ 顺序不变 ✓（电源仍在最前 ✓）—— 只是**后面那些网整批不布** ✓。
    if ONLY_NETS:
        _keep = [n for n in net_order if n in ONLY_NETS]
        print("★ `--only` ✓：只布 %s ✓（其余 %d 个网这一轮不布 ✓ —— 中间产物 ✓）"
              % (",".join(_keep), len(net_order) - len(_keep)))
        net_order = _keep

    def seg_pin_intr(path):
        r"""这条路径**贴到几个不相连的引脚** ✓ —— **逐段**取“自己的脚” ✓（唯一实现 ✓）

        ★ 为什么“自己的脚”必须**逐段**取 ✗（不能按整条线取 ✗）：一条线的**中段**不属于任何脚 ✓
          —— 按整条线豁免 ⇒ 中段蹭到别人的脚就不算 ✗（实测：脚本口径 11 ✗ 而渲染器 16 ✗ ✓）。
        ★ 判据 = `pin_intr`（`< CLEAR_PIN − PIN_EPS` ✓，用仓里唯一那份 `sch_geom.p2seg` ✓）
          ⇒ 与 `render_sch.py` 的 ④c2 **同一口径** ✓。
        ★ 三处共用这一份 ✓：① 代价 `route_key` ✓ ② **闸门 `HARD_CLEAR`** ✓ ③ 每轮全局验收 `gstat` ✓
          （抄三份 ⇒ 早晚有一份跟渲染器对不上 ✗ —— 面包板那天的教训 ✓）。
        """
        n = 0
        for k in range(len(path) - 1):
            sk = {(t, c) for (t, c, x, y) in PIN_ALL
                  if math.dist((x, y), path[k]) < 0.05
                  or math.dist((x, y), path[k + 1]) < 0.05}
            n += pin_intr([path[k], path[k + 1]], sk, PIN_ALL)
        return n

    def route_key(path, mine, own_pins, used):
        r"""**一条路径的代价** ✓ —— 唯一实现 ✓（首轮布线 / 抽出重排 / “旧路径重算”全用它 ✓）

        ★★ 为什么必须只有一份 ✗（2026-09-27 ✓，面包板踩过的坑 ✓）：
          重排时若给“新路径”和“旧路径”用**不同口径**（少传了“自己的元件豁免”之类 ✗）
          ⇒ 每轮都误报“有改进” ✗、全局却一动不动 ✗（白转 8 轮 ✓）。

        代价是**字典序元组** ✓（面包板规则 ⑧ 的教训 ✓：写进最后一档（长度）的系数几乎不起作用 ✗）：
          ① 不穿**自己**元件肚子 ✓
          ② **不出零件包围盒**（按格数 ✓）
          ③ **两条用户规则**（少贴不相连的引脚 ✓ + 少与别的线重叠 ✓，加权可交换 ✓）
          ④ **离别的元件别太近**（★ 我加的**代理**规则 ✓，**降到这里** ✓）
          ⑤ 少**十字交叉** ✓（头号指标 ✓）⑥ 少穿自己本体 ⑦ 弯少 ⑧ 短（含斜线小罚 ✓）
          （`--oldorder` = 把 ④ 放回 ② 位 ⇒ A/B 对照 ✓）
        """
        own_boxes = [box for t, box in boxes.items() if t in mine]
        nv = 0                       # ② 碰到**别的元件**本体（越少越好 ✓）
        for k in range(len(path) - 1):
            for t, box in boxes.items():
                if t not in mine and seg_hits_box(path[k], path[k + 1], box, CLEAR):
                    nv += 1
        nov = 0                      # ⑤ 与已布好的线**压在同一条直线上** ✗
        for k in range(len(path) - 1):
            for _u in used:
                if SG.near_overlap(path[k], path[k + 1], _u[0], _u[1]):
                    nov += 1
        ostep = int(out_len(path, UBOX) / 7.2 + 0.9999)          # ③ 出界几格 ✓
        # ④ 贴到几个不相连的脚 ✓ —— ★ **按“段”算** ✓（与渲染器同一个口径 ✓✓）：
        #   ✗ 原来按“**整条路径**”算 ✗ ⇒ 把这条网自己的脚**整条**豁免了 ✗ ⇒
        #     中段（它不属于任何一个脚 ✓）蹭到别人的脚就不算 ✗ ⇒ 脚本口径 11 ✓ 而渲染器口径 16 ✗
        #     （用户真正要的是后者 ✓：“不相连的引脚都要拉开距离” ✓）。
        #   ⇒ 改成：每一段各自看“两端命中的脚” ✓ —— 中段两端不是脚 ⇒ 它蹭到谁都算 ✓。
        #   ★ 2026-09-28 ✓ 抽成 `seg_pin_intr` ✓：**同一份判据**也给闸门 `HARD_CLEAR` 与
        #     全局验收 `gstat` 用 ✓（三份抄写早晚对不上 ✗）。
        pintr = seg_pin_intr(path)
        # ★★ 两条用户规则合成**一个加权项** ✓（2026-09-27 ✓）：
        #   ✗ 原来 `pintr` 与 `nov` 各占一档（字典序 ✗）⇒ 它们**不能互相交换** ✗
        #     ⇒ “躲引脚”一路优先 ⇒ 重叠反而从 6 涨到 **10** ✗（实测 ✓）。
        #   ✓ 改成 `INT_W[0]×重叠 + INT_W[1]×贴脚` ✓ —— 权重与“每轮全局验收”的
        #     `SNAP_WEIGHTS` **同一组** ✓（两把尺子同一个刻度 ✓），可交换 ✓。
        # ★★ 次序（2026-09-27 ✓，四档扫描后改的 ✓）：用户规则（贴脚 + 重叠）
        #   **必须排在**我自己加的代理规则“离别的元件 ≥6”**之前** ✗ ——
        #   否则**出脚路线必然被一票否决** ✗（出脚就是要绕到别的元件附近 ✓：
        #   实测从 U1 左排往左出、就会经过 J1 旁边的空档 ✓）。
        wt = INT_W[0] * nov + INT_W[1] * pintr
        nvb = 1 if nv else 0
        # ★★ `--otherbody` ✓：把“**钻别人的肚子**”提到**与 `hits_own_body` 并列的第一档** ✓
        #   （默认关 ⇒ 下面两行的元组**逐字节不变** ✓ ⇒ v18 可复现 ✓）。
        ob = 1 if (OTHER_BODY and hits_other_body(path, boxes, mine)) else 0
        if NEW_ORDER:                  # ★ 默认开 ✓：用户规则（贴脚+重叠）排在代理规则之前 ✓
            return (1 if (hits_own_body(path, own_boxes) or ob) else 0, ostep, wt, nvb,
                    cross_count(path, used), inside_count(path, own_boxes), bends(path),
                    plen(path) + diag_extra(path) + K_OUT * out_len(path, UBOX))
        # ✗ 旧次序（`--oldorder` = A 基线 ✓，实测与 v14 一字节不差 ✓）
        return (1 if (hits_own_body(path, own_boxes) or ob) else 0, nvb, ostep, wt,
                cross_count(path, used), inside_count(path, own_boxes), bends(path),
                plen(path) + diag_extra(path) + K_OUT * out_len(path, UBOX))

    def route_pair(a, b, mine, own_pins, used, tag="", net=None):
        """在候选里挑最优路径 ✓（代价见 `route_key` ✓）

        ★ `tag` 非空 + `--why` + 首轮 ⇒ 把“选中 / 亚军”两个代价元组与**第一处不同的档位**
          打到 stdout ✓（探针 ✓ 不改行为 ✓）。
        """
        # ★ 实验③：**别的脚的「行列」不当主干道** ✓（`--nopinrows` ✓，默认关 ✓）
        #   ★ 这一对脚**自己**的行列必须留 ✓（`a`/`b` 的行列 ✓），否则线进不了脚 ✗。
        if NO_PINROWS:
            _px = {round(a[0], 4), round(b[0], 4)}
            _py = {round(a[1], 4), round(b[1], 4)}
            _cx = sorted(v for v in chx if v in _px
                         or not any(abs(v - q) <= 0.05 for q in PIN_X))
            _cy = sorted(v for v in chy if v in _py
                         or not any(abs(v - q) <= 0.05 for q in PIN_Y))
        else:
            _cx, _cy = sorted(chx), sorted(chy)
        base_c = candidates(a, b, _cx, _cy)
        esc_c = []
        if USE_ESC:                    # ★ 默认开 ✓（用户定：重叠 0 优先 ✓）
            na = PIN_N_BY_XY.get((round(a[0], 3), round(a[1], 3)), (0.0, 0.0))
            nb = PIN_N_BY_XY.get((round(b[0], 3), round(b[1], 3)), (0.0, 0.0))
            if na != (0.0, 0.0) or nb != (0.0, 0.0):
                esc_c = esc_cands(a, b, na, nb, chx_clean, chy_clean, EDGE_PTS)
        cands = base_c + esc_c
        esc_ids = {id(p) for p in esc_c}     # ★ 用来单独盯“出脚候选”的成绩 ✓（探针用 ✓）
        seen, uniq = set(), []         # ★ 去掉重复候选 ✓（出脚形状会与直连/L 形撞车 ✓）
        for p in cands:
            t = tuple((round(q[0], 4), round(q[1], 4)) for q in p)
            if t not in seen:
                seen.add(t)
                uniq.append(p)
        cands = uniq
        # ★★ 硬闸门 ✓（2026-09-27 ✓，用户定「**穿体必须是 0**」✓）：
        #   非“脚边一小段”的部分进别人本体 ⇒ 这条候选**直接不要** ✓。
        #   ★ 为什么不靠调档位 ✗：档位只能表达“先后”✗，表达不了“**必须**”✗；
        #     而且一动档位次序，费了很大劲才拿到的“**重叠 0**”就可能没了 ✗
        #     （重叠和贴脚合在同一个加权项里 ✓ ⇒ 次序一改，两项就互相让位 ✗）。
        #   ⇒ 用**闸门**：代价函数、档位次序**一个字不动** ✓，只在候选集上删 ✓。
        if HARD_BODY:
            ok = [p for p in cands if not body_hard_bad(p, boxes, PIN_ALL)]
            if ok:
                cands = ok
            else:
                warn.append("%s：**没有一条候选**能避开别人的本体 ✗（保留旧候选集 ✓ 否则会接不上 ✗）" % tag)
        if HARD_PIN:                   # ★ 线不许落在“别的脚”上（含线身穿心 ✗，2026-09-28 ✓）
            ok2 = [p for p in cands if not pin_hard_bad(p, PIN_ALL, own_pins)]
            if ok2:
                cands = ok2
            else:
                warn.append("%s：**没有一条候选**能避开别的引脚 ✗（保留旧候选集 ✓）" % tag)
        if HARD_OVL:                   # ★ 用户规则②的真闸门 ✓：不许与已布的线压在同一条直线上 ✓
            ok3 = [p for p in cands if not ovl_hard_bad(p, used)]
            if ok3:
                cands = ok3
            else:
                warn.append("%s：**没有一条候选**能与已布的线不重叠 ✗（保留旧候选集 ✓ 否则接不上 ✗）"
                            % tag)
        if HARD_CLEAR:                 # ★ 用户定（2026-09-28 ✓）：**贴脚 = 0**（零容忍 ✓）
            ok4 = [p for p in cands if seg_pin_intr(p) == 0]
            if ok4:
                cands = ok4
            else:
                warn.append("%s：**没有一条候选**能“一个不相连的脚也不贴” ✗"
                            "（保留旧候选集 ✓ 否则会接不上 ✗）" % tag)
        if HARD_FJ:                    # ★ 用户点名（2026-09-28 ✓）：**端点/折点不许搭在别的网上** ✗
            ok5 = [p for p in cands if not fj_path_bad(p, net, used)]
            if ok5:
                cands = ok5
            else:
                warn.append("%s：**没有一条候选**能“端点/折点不搭在别的网上” ✗"
                            "（保留旧候选集 ✓ 否则会接不上 ✗）" % tag)
        best, best_key, alt, alt_key = None, None, None, None
        esc_best, esc_best_key = None, None
        for path in cands:
            key = route_key(path, mine, own_pins, used)
            if id(path) in esc_ids and (esc_best_key is None or key < esc_best_key):
                esc_best, esc_best_key = path, key
            if best_key is None or key < best_key:
                if best is not None:           # ★ 上一名降为“亚军” ✓
                    alt, alt_key = best, best_key
                best, best_key = path, key
            elif alt_key is None or key < alt_key:
                alt, alt_key = path, key
        if WHY and tag and PHASE[0] == "greedy" and alt is not None:
            dif = next((i for i in range(len(best_key))
                        if best_key[i] != alt_key[i]), -1)
            print("   [why] %-22s 候选 %d 条（直连/L/45°/通道 %d ✓ + 出脚 %d ✓）"
                  % (tag, len(cands), len(base_c), len(esc_c)))
            print("   [why] %-22s 选中 %s ｜ 路径 %s"
                  % ("", best_key, " ".join("%.1f,%.1f" % (q[0], q[1]) for q in best)))
            print("   [why] %-22s 亚军 %s ⇒ 第 %d 档「%s」定胜负"
                  % ("", alt_key, dif + 1,
                     (TIER_NEW if NEW_ORDER else TIER)[dif] if dif >= 0 else "全同"))
            # ★★ “出脚候选”自己的最好成绩 ✓（2026-09-27 ✓）—— 直接看它们输在哪一档 ✓，不再靠我推 ✗
            if esc_best is not None:
                print("   [why] %-22s 出脚最好 %s ｜ 路径 %s"
                      % ("", esc_best_key,
                         " ".join("%.1f,%.1f" % (q[0], q[1]) for q in esc_best)))
            else:
                print("   [why] %-22s 出脚候选：**一条未生成** ✗（法线缺失 / 被去重吃掉 ✗）" % "")
        return best, best_key

    def pick_hub(plist):
        r"""星形网的**公共汇点** ✓（2026-09-28 ✓ 用户点名的第 2 条 ✓）

        ★ 选法（客观 ✓）：① 取各脚几何中心 ✓；② 在**干净通道**里取离中心最近的 6×6 个交点 ✓；
          ③ 合格的 = **不在任何别的元件盒里**（内缩 0.5 ✓）且**离任何引脚 ≥ CLEAR_PIN** ✓；
          ④ 在合格里取**离中心最近**的 ✓；一个都不合格 ⇒ 退回中心 ✓（并印告警 ✓ 不静默 ✗）。
        ★ 为什么从通道交点里挑 ✓：汇点落在通道上 ✓ ⇒ 每根枝都能沿正交/45° 到它 ✓，
          而不会因为“汇点在没通道的野地”被迫绕远 ✗。
        """
        cx0 = sum(d["p"][0] for d in plist) / len(plist)
        cy0 = sum(d["p"][1] for d in plist) / len(plist)
        xs = sorted(chx_clean, key=lambda v: abs(v - cx0))[:6]
        ys = sorted(chy_clean, key=lambda v: abs(v - cy0))[:6]

        def bad(x, y):
            for t2, bb in boxes.items():
                if bb and (bb[0] + 0.5 <= x <= bb[2] - 0.5 and bb[1] + 0.5 <= y <= bb[3] - 0.5):
                    return True
            return any(math.dist((x, y), (q[2], q[3])) < CLEAR_PIN for q in PIN_ALL)

        ok = [(math.hypot(x - cx0, y - cy0), x, y)
              for x in xs for y in ys if not bad(x, y)]
        if ok:
            _d, x, y = min(ok)
            return (x, y)
        warn.append("星形汇点：**通道交点上全不合格** ✗ ⇒ 退回几何中心 (%.1f,%.1f) ✓" % (cx0, cy0))
        return (cx0, cy0)

    def _lane_span(_x):
        r"""这条车道**实际要跑的那一段** ✓ = “**会选它**的那几只脚”的 y 跨度 ✓

        ✗ 实测踩的坑（2026-10-04 ✓）：原来闸门拿**整张网**的 y 跨度验 ✗（`min…max` over all pts ✓）
          ⇒ GND 跨 `-72…166.8` ✗ ⇒ `x=60/66/72/80` **一律“穿本体”** ✗（撞 `U1` 的身子 ✓）
          —— 可**车道只服务它自己那一簇** ✓（`D3`/`U1`/`J1` ✓，跨度只有 `-43.2…98` ✓）
          ⇒ 按簇验 ⇒ **多条车道**才有意义 ✓（用户 2026-10-04 选 B ✓）。
        ★ 返回 `(y0, y1, 几只脚)` ✓；**一只脚都不选它** ⇒ `None` ✓（那就别建 ✓）。
        ★ 只读外边作用域的 `pts` / `rail_ys` ✓（调用时已就绑 ✓ ⇒ 快照式闭包 ✓ 不会读到上一张网的 ✗）。
        """
        _s = [d["p"][1] for d in pts
              if abs(d["p"][0] - _x) > 1e-9
              and abs(d["p"][0] - _x) < min(abs(d["p"][1] - _r) for _r in rail_ys)]
        return (min(_s), max(_s), len(_s)) if _s else None

    def pick_vlane(plist, own_pins, rail_ys):
        r"""竖直车道的 **x** ✓（2026-10-03 ✓ 用户选 A ✓）

        ★ 判分（客观 ✓）：候选 = **干净竖直通道** `chx_clean` ✓（不在任何脚的列上 ✓）；
          分数 = `Σ min(|脚.x − x| , |脚.y − 最近轨|)` ✓
          —— 即“**这只脚走车道 vs 走水平轨，哪个近**” ✓ 的逐脚取小 ✓。
        ★ 两道闸门（**与水平轨同一个口径** ✓，不另立一套 ✗）：
          ① 竖直干线 `(x, ymin)…(x, ymax)` **不穿任何本体** ✓（`body_hard_bad` ✓）；
          ② 不压**别的网**的脚 ✓（`pin_hard_bad` + 本网自己的脚 ✓ —— 自己网的脚允许 ✓）。
        ★ 全不合格 ⇒ 返回 `None` ✓（**不静默** ✓：告警写进 `warn` ✓）。
        ★★ v1 否证记录 ✗：v1 是“**清空水平轨、所有脚都走车道**” ✗ ⇒ 实测车道被逼到
          `x=42.5` ✗（`Σ|Δx| = 676` ✗）、还多 **1 对重叠** ✗ —— 因为用户手画的干线
          **只服务它旁边那一簇** ✓（`LED2`/`C2`/`J2` ✓），远处那些脚照旧走**水平轨** ✓。
        """
        ymin = min(d["p"][1] for d in plist)
        ymax = max(d["p"][1] for d in plist)
        # ★★★ 2026-10-04 ✓ **加「过线惩罚」** ✓（用户点名的那一手 ✓，现在**有标尺了** ✓）
        #   ✗ 病（实测 ✓）：原来只算**距离** ✗ ⇒ 自动挑到 `x=42.528` ✗（左边那一簇 ✓），
        #     而**用户手画挑的是 `x=210.58`** ✓（右边 `LED2`/`J2` 那一簇 ✓）——
        #     同一套其它参数下 **交叉 32 ✗ vs 24 ✓** ⇒ 差别全在车道位置 ✓。
        #   ✓ 代理判据（不用等别的网布完 ✓，**现在就能算** ✓）：
        #     某只脚要**横着走到车道** ✓ ⇒ 这条路**穿过的“别的网的脚”越多，越可能撞上别的线** ✗
        #     ⇒ 每数到一只，按 `K_INTER`（= **35.4 单位 = 10mm** ✓，与本仓目标函数同一个 K ✓）罚 ✓。
        #   ★ 为什么这条代理**够用** ✓：实测 `x=42.5` 那一带挤着 `U1`/`J1` 的一排脚 ✗（罚重 ✗），
        #     而 `x=210.58` 右侧那一条**只有 0 只挡路脚** ✓ ⇒ 两项一加，210.58 胜出 ✓
        #     —— 这就是“**用 210.58 当标尺**” ✓（挑不出这一带就不算对 ✓）。
        _NEAR2 = 15.0            # 别的网的脚离“将要画的支线”多近算挡路 ✓（15 单位 ≈ 4.3mm ✓）

        def _pen(x):
            r"""挡路脚清点 ✓（返回 `(条数, 名单)` ✓）"""
            _n2, _who = 0, []
            for d in plist:
                _px, _py = d["p"]
                if abs(_px - x) >= min(abs(_py - _r) for _r in rail_ys):
                    continue                 # 这只脚**不会**走车道 ⇒ 不算它 ✓
                for (_t4, _c4, _qx, _qy) in PIN_ALL:
                    if (_t4, _c4) in own_pins:
                        continue
                    if (min(_px, x) - 1e-9 <= _qx <= max(_px, x) + 1e-9
                            and abs(_qy - _py) < _NEAR2):
                        _n2 += 1
                        _who.append("%s.%s" % (_t4, _c4))
            return _n2, _who

        def _score(x):
            return (sum(min(abs(d["p"][0] - x),
                            min(abs(d["p"][1] - r) for r in rail_ys)) for d in plist)
                    + K_INTER * _pen(x)[0])

        _cand = sorted(chx_clean, key=lambda v: (_score(v), v))
        for x in _cand:
            _sp2 = _lane_span(x)
            if _sp2 is None:
                continue                       # 没有脚会选它 ✓
            seg = [(x, _sp2[0]), (x, _sp2[1])]   # ★ 按**它自己的簇**验 ✗（不是整张网 ✓）
            if body_hard_bad(seg, boxes, PIN_ALL):
                continue                       # 穿本体 ✗
            if pin_hard_bad(seg, PIN_ALL, own_pins):
                continue                       # 压**别的网**的脚 ✗
            _b = sum(min(abs(d["p"][0] - x),
                         min(abs(d["p"][1] - _r) for _r in rail_ys)) for d in plist)
            _n3, _w3 = _pen(x)
            print("   ★ 竖直车道候选 ✓：x=%.3f ✓（距离项 %.1f ＋ 挡路脚 %d × %.1f = %.1f "
                  "⇒ **总分 %.1f** 单位 = %.1f mm ✓；%d 条候选里总分最低、且过两道门的 ✓）%s"
                  "（★ 距离项 = 逐脚“走车道 vs 走最近轨”**取小** ✓ —— 与 `_score` 同一个式子 ✓）"
                  % (x, _b, _n3, K_INTER, K_INTER * _n3, _score(x), _score(x) * 25.4 / 90.0,
                     len(_cand),
                     "；挡路：%s ✓" % ", ".join(_w3[:6]) if _w3 else "（**没人挡路** ✓）"))
            return x
        warn.append("竖直车道：**%d 条候选全不合格** ✗（穿本体 / 压别人的脚 ✗）"
                    "⇒ 该网**照旧用水平轨** ✓" % len(_cand))
        return None

    for net in net_order:
        pins = NETS[net]
        if len(pins) < 2:
            print("网 %-9s 只有 %d 个脚 ⇒ 没有线可画 ✓（保持独立 ✓）" % (net, len(pins)))
            continue
        pts = []
        for ref, name in pins:
            cid, p = pin_of(insts, ref, name)
            pts.append({"ref": ref, "cid": cid, "p": p})
        # ★ 链序 ✓（`--chain` ✓，第 4 条候选规则 ✓）：
        #   `xy` = 现状（按 (x,y) ✓）；`yx` / `revxy` / `revyx` = 同族探索 ✓；
        #   `nn` = **最近邻链** ✓（从最左的脚出发 ✓、每次接最近的未访脚 ✓；平手按坐标 ✓ ⇒ 确定性 ✓）。
        if CHAIN == "yx":
            pts.sort(key=lambda d: (round(d["p"][1], 3), round(d["p"][0], 3)))
        elif CHAIN == "revyx":
            pts.sort(key=lambda d: (round(d["p"][1], 3), round(d["p"][0], 3)))
            pts.reverse()
        elif CHAIN in ("xy", "revxy"):
            pts.sort(key=lambda d: (round(d["p"][0], 3), round(d["p"][1], 3)))
            if CHAIN == "revxy":
                pts.reverse()
        elif CHAIN == "nn":
            _rest = sorted(pts, key=lambda d: (round(d["p"][0], 3), round(d["p"][1], 3)))
            _ord = [_rest.pop(0)]
            while _rest:
                _cur = _ord[-1]["p"]
                _nxt = min(_rest, key=lambda d: (round(math.dist(_cur, d["p"]), 3),
                                                 round(d["p"][0], 3), round(d["p"][1], 3)))
                _rest.remove(_nxt)
                _ord.append(_nxt)
            pts = _ord
        segs = []
        # ★ 连接**对** ✓：默认 = 相邻两脚（链 ✓）；`STAR_NETS` 里的 = 每脚 → 汇点（星 ✓）；
        #   ★★ `RAILS` 里的 = 每脚 → **就近的上/下电源轨** ✓（2026-09-28 ✓ 用户提的架构 ✓）
        pairs = []
        rail_ys = RAIL_Y.get(net, []) if RAILS else []
        if RAIL_ONLY and net not in RAIL_ONLY:
            rail_ys = []            # ★ 点名的网以外 ⇒ **不用水平轨** ✓（`--rails=5V` 用 ✓）
        # ★★★ 2026-10-03 ✓ **`--vlanes=<网>`** ✓：点名的网**多一条竖直车道可选** ✓（用户选 A ✓）
        #   ★★ v1 已实测否证 ✗（记下来 ✗）：v1 把 `rail_ys` **清空**、让**所有脚**都走车道 ✗
        #     ⇒ 实测车道被逼到 `x=42.528` ✗（`Σ|Δx| = 676.4` ✗）、并多出 **1 对导线重叠** ✗
        #     （退出码 1 ✗）。根因：用户手画的竖直干线**只服务它附近那一簇脚** ✓
        #     （`LED2`/`C2`/`J2` ✓），远处那些脚（`D3`/`C1`/`U1` ✓）照旧走**水平轨** ✓。
        #   ★ v2 口径 ✓：**车道与水平轨并存** ✓ ⇒ 哪只脚走哪边**由数据定** ✓
        #     （下面在轨支线建完以后逐脚重定 ✓），不是我一句话一刀切 ✗。
        _VLX = []                       # ★★★ 2026-10-04 ✓ **车道** x **可以有多条** ✓（用户选 B ✓）
        #   ★ 为什么要多条 ✗：实测（用户 2026-10-04 问 ✓）GND **两条水平轨**（y=-72 ✓ 与 y=163.8 ✓）
        #     ⇒ Fritzing 里两条平行线**不会自己通** ✗ ⇒ 必须补一根竖线把它们接起来 ✗
        #     ⇒ 左边就多出 **235.8 单位 = 66.9mm** ✗（全图 **11.8%** ✗）的一根“纯连线” ✗。
        #   ✓ 思路：把左边那一簇（`D3`/`U1`/`J1`/`C1` ✓）也交给**它自己的竖直干线** ✓
        #     ⇒ 底轨可能整个不需要 ✓ ⇒ **互连自然消失** ✓（而不是去删它 ✓）。
        if net in VLANE_X:
            # ★ 用户指定的车道（**可以给多条** ✓）—— 但**每条**都要过那两道门 ✗（不静默 ✗）
            _uown = {(d["ref"], d["cid"]) for d in pts}
            for _ux in VLANE_X[net]:
                _sp = _lane_span(_ux)
                if not rail_ys:
                    print("⚠ 用户指定车道 x=%.3f ✗：该网**没有水平轨** ✗（`--rails` 没开 / 没点名它 ✓）"
                          "⇒ 车道要先有轨才能“逐脚比远近” ✓ ⇒ **本条不用** ✗" % _ux)
                elif _sp is None:
                    print("⚠ 用户指定车道 x=%.3f ✗：**没有一只脚会选它** ✗（比它自己的轨还远 ✓）"
                          "⇒ **本条不用** ✓" % _ux)
                elif body_hard_bad([(_ux, _sp[0]), (_ux, _sp[1])], boxes, PIN_ALL):
                    print("⚠ 用户指定车道 x=%.3f ✗：**穿本体** ✗（它要跑 y %.1f → %.1f ✓，`%d` 只脚）"
                          "⇒ **本条不用** ✓" % (_ux, _sp[0], _sp[1], _sp[2]))
                elif pin_hard_bad([(_ux, _sp[0]), (_ux, _sp[1])], PIN_ALL, _uown):
                    print("⚠ 用户指定车道 x=%.3f ✗：**压别人的脚** ✗（y %.1f → %.1f ✓）"
                          "⇒ **本条不用** ✓" % (_ux, _sp[0], _sp[1]))
                else:
                    _VLX.append(_ux)
                    print("   ★ 竖直车道 = **用户指定** ✓ x=%.3f ✓（它要跑 y %.1f → %.1f ✓、`%d` 只脚 ✓；"
                          "不穿体 ✓、不压别人的脚 ✓）" % (_ux, _sp[0], _sp[1], _sp[2]))
        elif net in VLANES and rail_ys:
            _a = pick_vlane(pts, {(d["ref"], d["cid"]) for d in pts}, rail_ys)
            if _a is not None:
                _VLX = [_a]
        _VL = _VLX[0] if _VLX else None      # 下面还有几处只判“有没有车道” ✓

        _vtrunks = []
        # ★★★ 2026-10-03 ✓（用户点名"继续"后加 ✓）：轨的 y **不只有"包围盒外那两条"** ✗
        #   —— 再补**一条"穿中缝"的内部候选** ✓ = 该网**脚行的中位 y** ✓。
        #   · 动机（实测 ✓）：用户手画的 GND 主干是**穿中缝**的 ✓、脚**坐在干线上** ✓
        #     （支线长度 ≈ 0 ✓）；而本工具原来只给"包围盒外 2 格 / 4 格"两条 ✗
        #     ⇒ 每条支线都得跑到图外 ✗ ⇒ 实测 `--rails` 总长 **946.4 mm** ✗（同摆位手画 487.7 ✓）。
        #   · 只加**一条** ✗（不把整张走廊表塞进来 ✗）：轨的 x 范围 = "所有落到该轨上的支线"
        #     的 min/max ✓ ⇒ 候选一多 ⇒ 会画出**好几条长轨** ✗ ⇒ 反而更长 ✗。
        #   · 安全 ✓：候选**先过两道门** ✗ —— 不穿任何本体 ✓、不压**别的网**的脚 ✓；
        #     自己网的脚**允许**在轨上 ✓ —— 那正是 `_sit` 那套"轨在脚的 x 处断开" ✓ 的最优形态 ✓。
        if rail_ys and len(pts) >= 3:
            _own0 = {(d["ref"], d["cid"]) for d in pts}
            _xs0 = [d["p"][0] for d in pts]
            _mid = sorted(d["p"][1] for d in pts)[len(pts) // 2]
            # 候选排序 ✓：① 该网脚行 ✓（**坐在上面的脚越多越优先** ✓）② 干净通道 ✓（离中位行近的先 ✓）
            _rows = {}
            for d in pts:
                _rows[round(d["p"][1], 4)] = _rows.get(round(d["p"][1], 4), 0) + 1
            _cand = sorted(_rows.items(), key=lambda kv: (-kv[1], abs(kv[0] - _mid)))
            _cand += [(round(v, 4), 0) for v in sorted(chy_clean, key=lambda v: abs(v - _mid))]
            _picked = None
            for _v, _n in _cand:
                if any(abs(_v - _w) < 1e-6 for _w in rail_ys):
                    continue                       # 已经有了（= 包围盒外那两条）⇒ 不算新增 ✓
                _seg0 = [(min(_xs0), _v), (max(_xs0), _v)]
                if body_hard_bad(_seg0, boxes, PIN_ALL):
                    continue                       # 穿本体 ✗
                if pin_hard_bad(_seg0, PIN_ALL, _own0):
                    continue                       # 压**别的网**的脚 ✗（自己的脚可以坐上去 ✓）
                _picked = (_v, _n)
                break
            if _picked:
                rail_ys = list(rail_ys) + [_picked[0]]
                print("   ★ 轨 y **加一条内部候选** ✓：y=%.1f ✓（该行有 %d 只本网的脚 ✓；"
                      "不穿本体 ✓、不压别人的脚 ✓）" % _picked)
        _sit = []                       # ★ 本网“**脚正好落在轨上**”的脚 ✓（`(x, ref, cid, y)` ✓）
        if rail_ys:
            print("网 %-9s **电源轨** ✓：轨 y = %s ✓（%d 只脚各打一条支线 ✓）"
                  % (net, ["%.1f" % v for v in rail_ys], len(pts)))
            _n_rail = len(pairs)        # ★ 本网轨支线的起点（见下：按 x 升序 ✓）
            for d in pts:
                # ★★★ 2026-09-30 ✓ **脚正好落在轨上的**：**不建支线** ✗ —— 改成
                #   “**把轨在这个 x 处断开**” ✓（记进 `_sit` ✓，下面建轨时并进断点 ✓）。
                #   ✗ 旧做法会造出一条 **0 长度支线** ✗ ⇒ 被 `dedup_path` 折成 1 个点 ✗
                #     ⇒ 收尾当“退化段”丢掉 ✗ ⇒ **脚一根线都没有** ✗✗ ——
                #     而它**正压在轨线上** ✓ ⇒ 图上看着接上了 ✓、七道闸门全被骗过 ✗。
                #     实测：`C2.connector0` 在 44 根线里**一次都没出现** ✗，是
                #     **用户的眼睛**看出来的 ✓✓ —— 又一次“没量到 ≠ 对” ✗。
                #   ✓ 正解：脚**自带**一个断点 ⇒ 轨在它那儿一分为二 ⇒ 脚与**两个端点重合** ✓
                #     ⇒ 端点到端点**真连上** ✓，且**不出现退化导线** ✓。
                if any(abs(d["p"][1] - _ry) < 0.6 for _ry in rail_ys):
                    _sit.append((d["p"][0], d["ref"], d["cid"], d["p"][1]))
                    print("   ★ 脚**正好落在轨上** ✓：%s.%s (%.2f,%.2f) ✓ ⇒ **不建支线** ✗，"
                          "改成轨在该 x 处**断开** ✓（脚与两个断点重合 = 端点到端点真连上 ✓）"
                          % (d["ref"], d["cid"], d["p"][0], d["p"][1]))
                    continue
                # ★★★ 选轨（2026-09-28 ✓ 实测修正 ✓）：**就近优先 ✓，但"走过去不许穿体"优先于"就近"** ✗
                #   ✗ 病（实测 `Wire90012727` ✓）：`U1.VDD`（y=43.2）到**下轨**(143.4) 的距离
                #     100.2，比到**上轨**(-57.6) 的 100.8 **略近 0.6** ✗ ⇒ 于是它**竖直向下 100 单位**
                #     ⇒ **正好穿过 `D3` 的整个本体** ✗（D3 盒 y∈[72,110] ✓）⇒ 穿 **74 单位深 ≈ 20.9mm** ✗✗，
                #     还顺带贴上 `D3.connector5/2`（5.85 < CLEAR_PIN ✗）。
                #   ✓ 修法：把两条轨**按就近排好序** ✓，逐条试"脚 → 该轨"的直连段 ✓，
                #     **第一条不穿体的就用** ✓；都穿体 ⇒ 用就近那条 ✓（回到旧行为 ✓ 不更差 ✓）。
                #   ★ 为什么只查"直连段"够 ✓：这段就是"从脚竖直去轨"的路 ✓（横向偏移由后面的
                #     `route_pair`/L 形负责 ✓）；直连段不穿体 ⇒ 后面那步也多半不穿 ✓。
                _yb = sorted(rail_ys, key=lambda v: abs(v - d["p"][1]))
                _y = _yb[0]
                for _yy in _yb:
                    if not body_hard_bad([d["p"], (d["p"][0], _yy)], boxes, PIN_ALL):
                        if _yy != _y:
                            print("   ★ 支线**改接另一条轨** ✓：%s.%s 就近是 y=%.1f ✗（走过去会穿体 ✗）"
                                  "⇒ 改接 y=%.1f ✓" % (d["ref"], d["cid"], _y, _yy))
                        _y = _yy
                        break
                pairs.append({"a": d["p"], "ra": d["ref"], "ca": d["cid"],
                              "b": (d["p"][0], _y), "rb": None, "cb": None,
                              "rail_b": (d["p"][0], _y)})   # ★ 车道支线若不成就**退回它** ✓
            # ★★ 2026-09-28 ✓ **同一条轨上的支线：按“脚的 x”从小到大布** ✓（= 锚点先落 ✓）
            #   病灶（实测 ✓）：布序 = 网表顺序 ✗ ⇒ `U1.connector3`（x=58.6）**先于**
            #     `J1.connector1`（x=15.4）布 ✗ ⇒ 轮到 `U1.c3` 想“**共享竖线**”时，
            #     `J1` 那根竖线**还没画** ✗ ⇒ `used` 里搜不到搭接点 ✗ ⇒ 只能自己竖一趟 ✓
            #   ⇒ 只要**让锚点先落** ✓（同一根轨按 x 升序 ✓），共享候选就自然命中 ✓。
            pairs[_n_rail:] = sorted(pairs[_n_rail:], key=lambda q: q["a"][0])
            # ★★★ 2026-10-03 ✓ `--vlanes` v2 ✓：**逐脚重定** —— “更近车道”的改走车道 ✓
            #   ★ 为什么放在**轨支线建完之后** ✗：这样 `_sit`（脚正好坐在轨上 ✓）、
            #     “改接另一条轨”（不穿体 ✓）这些**已经跑过一遍**了 ✓ ⇒ 本步只**改写**
            #     选中那几只脚的对 → 车道 ✓ ⇒ **附加式改动** ✓，不会把轨那套弄乱 ✗。
            #   ★ 标准 ✓：`|Δx 到车道| < |Δy 到最近轨|` ✓（就是 `pick_vlane` 打分用的那个式子 ✓，
            #     同一口径 ✓）；并且**至少 2 只脚**选中才值得单画一条干线 ✗（1 只不值 ✗）。
            #   ★ 先占 `used` ✓ ⇒ 支线不会“沿着车道跑” ✗（那会与干线重叠 ✗）。
            if _VLX:
                # ★★ 两步走 ✓：先算“每条车道分到几只脚” ✓ ⇒ **不足 2 只的不建** ✓
                #   （✗ 一步到位会把那几只脚改成指向一条**不存在的干线** ✗ ⇒ 又变成“一根线都没有” ✗✗）
                _bys = {_x: [] for _x in _VLX}
                for _pr in pairs[_n_rail:]:
                    _px, _py = _pr["a"]
                    _near = min(_VLX, key=lambda _x: abs(_px - _x))
                    if abs(_px - _near) > 1e-9 and abs(_px - _near) < min(abs(_py - _r) for _r in rail_ys):
                        _bys[_near].append(_pr)
                for _x in sorted(_bys):
                    _prs = _bys[_x]
                    if len(_prs) < 2:
                        if _prs:
                            print("   ⊘ 车道 x=%.3f **不用** ✓：只有 %d 只脚更近 ✗（< 2 ⇒ 不值得单画一条 ✓）"
                                  "⇒ 那几只照旧走**水平轨** ✓" % (_x, len(_prs)))
                        continue
                    _vys = sorted({round(_pr["a"][1], 4) for _pr in _prs})
                    _tr = [(_x, _y) for _y in _vys]
                    for _pr in _prs:
                        _pr["b"] = (_x, _pr["a"][1])
                        _pr["rb"], _pr["cb"] = None, None
                        _pr["vlane"] = True      # ★★ 必须打这个标记 ✗ —— 否则下面的支线会掉回
                        #   “轨专用”那套形状 ✗ ⇒ 造出**两端同点的退化段** ✗ ⇒ 收尾被丢 ✗
                        #   ⇒ 那只脚**一根线都没有** ✗✗（实测：`LED2.connector1` ✓）。
                    for _k in range(len(_tr) - 1):
                        used.append((_tr[_k], _tr[_k + 1], net))
                    _vtrunks.append(_tr)
                    print("   ★ **竖直车道** ✓：x=%.3f ✓ 服务 **%d 只脚** ✓（y %.1f → %.1f ✓）"
                          "—— 剩下的照旧走**水平轨** ✓"
                          % (_x, len(_prs), _tr[0][1], _tr[-1][1]))
        elif net in STAR_NETS and len(pts) >= 2:
            hub = pick_hub(pts)
            print("网 %-9s **星形** ✓：汇点 (%.1f,%.1f) ✓（%d 根枝 ✓）" % (net, hub[0], hub[1], len(pts)))
            for d in pts:
                pairs.append({"a": d["p"], "ra": d["ref"], "ca": d["cid"],
                              "b": hub, "rb": None, "cb": None})
        else:
            for i in range(len(pts) - 1):
                _p1, _p2 = pts[i], pts[i + 1]
                if REVPAIR:            # ★ A/B ✓：这一对**反方向**接 ✓（2026-09-28 ✓ 用户提 ✓）
                    _p1, _p2 = _p2, _p1
                pairs.append({"a": _p1["p"], "ra": _p1["ref"], "ca": _p1["cid"],
                              "b": _p2["p"], "rb": _p2["ref"],
                              "cb": _p2["cid"]})
        _tjs = []                       # ★ T 形搭接清单 ✓（本网 ✓，报告里逐条列 ✓）
        for pr in pairs:
            a, b = pr["a"], pr["b"]
            mine = {pr["ra"]} | ({pr["rb"]} if pr["rb"] else set())
            own_pins = {(pr["ra"], pr["ca"])} | ({(pr["rb"], pr["cb"])} if pr["rb"] else set())
            tt = "%s %s.%s→%s" % (net, pr["ra"], pr["ca"],
                                   ("%s.%s" % (pr["rb"], pr["cb"])) if pr["rb"] else "汇点")
            # ★★★ 支线（脚 → 轨）：**优先「多档出脚 + 直上到轨」** ✓（2026-09-28 ✓ 用户选 ✓）
            #   ★ 用户的判据 ✓：「**你的目的是接到轨上，不是点上**」✓ ⇒ 形状应当是
            #     「沿引线方向出脚 → 直上/直下到轨」= **拐一次（L 形）** ✓。
            #   ✗ 失败过的那版（记下来 ✗）：**硬限制"拐点 ≤1"** ✗ ⇒ 支线只能在**脚的 x** 上
            #     竖直走 ✗ ⇒ 而**同一元件的一列脚 x 相同** ✗ ⇒ **不同网的支线互相重叠** ✗
            #     ⇒ 「重叠 0」硬闸门删光候选 ⇒ 退回旧候选 ⇒ 实测 **重叠 5 ✗✗、退化导线 9 根 ✗**。
            #   ✓ 正解 = **出脚长度可变**（1…4 格 ✓）：每条支线**自己挑一个空的落点 x** ✓
            #     ⇒ 既拐一次 ✓、又互不重叠 ✓；且**只在完全合格时才用** ✓：
            #     不穿体 ✓、不压别人的脚 ✓、不与已布线重叠 ✓、**贴脚 = 0** ✓（用户定：零容忍 ✓）。
            #     四档都不合格 ⇒ **退回通用路由** ✓ ⇒ **绝不会比原来差** ✓。
            _L = None
            _Lfall = None                    # ★ 2026-09-28 ✓：「自己竖一趟」的兜底候选 ✓
            # ★★★ 2026-10-04 ✓ **竖直车道的支线：走它自己的形状** ✓（用户手画里就是**一条水平线** ✓）
            #   ✗ 实测踩的坑（**必须记住** ✗）：我把 `pr["b"]` 改成车道点以后 ✗，它就掉进了
            #     **轨专用**的那套候选机器 ✗（那套形状全是“顺着一列竖到轨 y” ✗，`b[1]` 当轨 y 用 ✗）
            #     ⇒ 造出 `[(180.38,17.00),(180.38,17.00)]` 这种**两端同点**的退化段 ✗
            #     ⇒ 收尾被当“path 只有 2 个点”丢掉 ✗ ⇒ **`LED2.connector1` 一根线都没有** ✗✗
            #     （日志里白纸黑字：`⚠ 段被丢弃 ✗：path 只有 2 个点 ｜ a=(180.38,17.00) b=(180.38,17.00)
            #       ｜ from={'ref':'LED2','cid':'connector1'} to=None` ✓）——
            #     图纸看着“接上了” ✓、而机器一查就是**断的** ✗（正是用户 10-03 报的那类病 ✓）。
            #   ✓ 正解：车道支线**只走一条候选** ✓ = `[脚, (车道x, 脚y)]` **一条水平线** ✓
            #     （= 用户手画的 `Wire90012757 (180.38,17.00)…(210.58,17.00)` ✓ 一模一样 ✓）；
            #     过不了四道闸门 ⇒ **退回它自己原来的轨目标** ✓（`rail_b` ✓）——
            #     ★ 绝不 `continue` ✗（那会让这只脚**一根线都没有** ✗✗）。
            #   ★ 干线上的“没支线接的断点”**无害** ✓（干线是一串首尾相接的段 ✓ ⇒ 照样连通 ✓）。
            if pr.get("vlane"):
                _vl_path = [a, (b[0], a[1])]
                if (not body_hard_bad(_vl_path, boxes, PIN_ALL)
                        and not pin_hard_bad(_vl_path, PIN_ALL, own_pins)
                        and pin_intr(_vl_path, own_pins, PIN_ALL) == 0
                        and not ovl_hard_bad(_vl_path, used)):
                    _L = _vl_path
                    print("   ★ 支线 **横到车道（0 拐）** ✓：%-16s 沿脚行到 x=%.3f ✓"
                          "（贴脚 0 ✓ 不重叠 ✓ 不穿体 ✓）" % (tt, b[0]))
                else:
                    pr["b"] = pr.get("rail_b") or pr["b"]
                    b = pr["b"]
                    pr.pop("vlane", None)
                    print("   ⊘ 车道支线不合格 ✗ ⇒ %s **退回它自己的水平轨** ✓（目标 (%.1f,%.1f) ✓）"
                          % (tt, b[0], b[1]))
            if _L is None and rail_ys and pr["rb"] is None:
                _n = PIN_N_BY_XY.get((round(a[0], 3), round(a[1], 3)), (0.0, 0.0))
                # ★★★ 2026-09-30 ✓ **竖直法线的脚也要允许“先横着出脚”** ✗✓（实测踩的 ✓）：
                #   ✗ 原来只给**水平法线**开这条路 ✗ ⇒ 竖直法线的脚（电容 / 电阻 ✓）只能
                #     “**直上到轨**” ✗ ⇒ 而两只脚之间**必然夹着一条轨** ✗（脚距 27.0 vs 轨距 14.4
                #     ⇒ 躲不开 ✓）⇒ 轨就得**伸进身体的 x 范围**才能接上 ✗ ⇒ 实测
                #     「轨从 `C2` 身上穿过去 **3.95mm**」✗✗（渲染器报的 ✓）。
                #   ✓ 用户手改版正是**先横着出脚、再竖着到轨** ✓（`C2`：`(270,-45)→(251,-45.2)
                #     →(237.4,-57.6)` ✓）⇒ 竖着下去那一段落在身体**外面** ✓ ⇒ 轨**不必进屋** ✓。
                #   ⇒ 这里只放开**形状**（“出脚”那一段横着走 ✓），**合格条件一条不动** ✗：
                #     不穿体 ✓ / 不压别人的脚 ✓ / 不与已布线重叠 ✓ / **贴脚 0** ✓；
                #     全不合格 ⇒ 照旧**退回通用路由** ✓（绝不会比原来差 ✓）。
                #   ★ 判据仍要求**法线已知**（≠(0,0) ✓）⇒ 不知道法线的脚**不新增候选** ✗。
                # ★★★ 2026-09-30 ✓ **但只“按需”放开** ✗✓（先全局放开试过 ✓ ⇒ 实测**基线变差** ✗）：
                #   全局放开 ⇒ 基线（不带 `--snaprails` ✓）的**十字交叉 8 → 10** ✗
                #   （长度倒是省 9.2 ✓，可**交叉数是头号指标** ✓、用户的判据是“看着简单” ✓）
                #   ⇒ 收回 ✓。**触发条件**（能说清为什么 ✓）：
                #   **本网某条轨的 y 正好从“这只有脚的那个元件”的肚子中间穿过** ✓ ⇒ 这时
                #   “直上到轨”会把**轨**拽进身体的 x 范围 ✗（实测 `C2` = 3.95mm ✗）⇒ 才需要
                #   横着出脚、把竖着下去那一段甩到身子外面 ✓。别的情况下**一条候选都不加** ✗
                #   ⇒ 基线**一字不动** ✓（可验证 ✓）。
                _needjog = False
                _mb = boxes.get(pr["ra"])
                if _mb:
                    for _ry in rail_ys:
                        if _mb[1] + 0.5 < _ry < _mb[3] - 0.5:
                            _needjog = True
                            break
                if (abs(_n[0]) > 0.5 and abs(_n[1]) < 1e-6) or (abs(_n[1]) > 0.5 and _needjog):
                    # ★ 档位 1…6 格 ✓、**两个方向**都试 ✓（2026-09-28 ✓ 用户选方案 1 ✓）：
                    #   ✗ 原来只试 4 格 + 只试"法线方向" ✗ ⇒ 实测 **14 条支线里只成功 3 条** ✗
                    #     （U1 左列那只 GND 脚的 4 档全不合格 ⇒ 退回 Z 字 ✗）。
                    #   ✓ 两个方向都试 ✓：**反向出脚 = 朝元件内侧** ⇒ 会进本体 ✗
                    #     ⇒ `body_hard_bad` **自动挡掉** ✓（不必我另写判据 ✓）。
                    #   ★ 次序 = **先法线方向**（更自然 ✓，引线本来朝外 ✓），再反向 ✓；
                    #     长度**从短到长** ✓（短的自然、省线 ✓）⇒ 取**第一个全合格的** ✓。
                    _s0 = 1.0 if _n[0] > 0 else -1.0
                    for _i2, _sgn in enumerate((_s0, -_s0)):
                        # ★★ 2026-09-28 ✓ **车道从哪来** ✓ —— 两批 ✓（次序就是“优先用哪一批” ✓）：
                        #   ① **7.2 的整数档** ✓（网格 ✓、法线方向先试 ✓）—— 本仓既有的做法 ✓；
                        #   ② **同网“已布竖线”所在的车道** ✓（**邻居驱动** ✓，只加在第二趟 ✓）——
                        #      ✗ 手改版那半（`J2.c1` → `LED2` 竖线 ✓）**根本不在 7.2 网格上** ✗：
                        #        档0 实测 脚 x=244.58、邻居车道 x=210.58 ⇒ 相差 **34.0**
                        #        = 4.72 × 7.2 ✗ ⇒ **档位永远踩不到** ✗✗（实测：接管候选零效果 ✗）。
                        #      ✓ 正解 = **不按网格找，直接看邻居的竖线在哪** ✓（这才是手改版的做法 ✓）。
                        _lanes = [a[0] + _sgn * _k * 7.2 for _k in (1, 2, 3, 4, 5, 6)]
                        # ★★★ 2026-09-30 ✓ **车道不许贴着“自己那件”的身子** ✗✗（用户截图点名的 ✓）：
                        #   ✗ 实测：`C2` 的 GND 脚出脚 **7.2** 恰好是它**自己的板边**
                        #     （电容板半宽 = 7.2 ✓，盒子 x = 259.96…274.36 ✓）
                        #     ⇒ 那条**竖线贴着本体边缘**跑 ✗（用户："黑色竖线离电容太近了吧" ✓）。
                        #   ✓ 判据：车道落在 **本件盒子 ± `CLEAR`（6.0 单位 = 1.7mm ✓）** 之内 ⇒ **剔掉** ✗
                        #     ⇒ 退到下一档（±14.4 ✓ = 离板边 7.2 ✓ 看得清 ✓）。
                        #   ★ 为什么只剔“自己那件”✗：别的件的贴合由既有闸门管 ✓（穿体 ✓ / 压脚 ✓ / 重叠 ✓）；
                        #     而**自己那件**恰恰是唯一被豁免的 ✗（线要进肚子才能接到脚上 ✓）⇒ 只有这里管得住 ✓。
                        #   ★ 只**剔车道**、不动合格条件 ✗ ⇒ 全不合格照旧退回通用路由 ✓（不会更差 ✓）。
                        _mb0 = boxes.get(pr["ra"])
                        if _mb0:
                            _lanes = [v for v in _lanes
                                      if not (_mb0[0] - CLEAR < v < _mb0[2] + CLEAR)]
                        if _i2 == 1:
                            _lanes += [_u[0][0] for _u in used
                                       if _u[2] == net
                                       and abs(_u[0][0] - _u[1][0]) < LANE_EPS
                                       and abs(_u[0][0] - a[0]) > LANE_EPS]
                        for _qx in _lanes:
                            _q = (_qx, a[1])
                            # ★★ 先试 **T 形搭接** ✓（2026-09-28 ✓ 学用户手改版 ✓，用户选 A✓）
                            #   病灶（实测 ✓）：同网、**同一条竖直车道**上的两条支线里，
                            #     后布的那条**一路画到轨** ✗ ⇒ 整条盖住先布的那条 ✗ ⇒
                            #     硬闸门判「与已布线重叠」✗（实测 `GND D3.connector0`：
                            #     **12 档全灭** ⇒ 退回 `route_pair` 绕成 **6 段** ✗✗）。
                            #   用户手改版（`t72` 逐步明细 ✓）：后布的那条**停在先布那条的端点上** ✓
                            #     ⇒ `(x,84.0)→(x,98.0)` 与既有 `(x,98.0)→(x,157.8)` **只共一个端点** ✓
                            #     ⇒ 不算重叠 ✓（`near_overlap` 的投影重叠≈0 ✓）、
                            #     电学上**端点对端点真连上** ✓、少画 37 单位 ✓（GND 29 段→26 段 ✓）。
                            #   ★ 安全条件 = **我能验证的那一条** ✓：被搭接的那段必须
                            #     **自己有一端正好落在轨 y 上** ✓ ⇒ 它**必定通到轨** ✓ ⇒
                            #     不会“搭在死胡同桩子上”✗（那会重新长出飞线 ✗✗）。
                            #     链条式搭接（搭在“也是搭来的”那条上）**这一轮不做** ✗。
                            for _u in used:
                                if _u[2] != net:                    # 只搭**同网** ✓
                                    continue
                                _p2, _q2 = _u[0], _u[1]
                                if (abs(_p2[0] - _q[0]) > LANE_EPS
                                        or abs(_q2[0] - _q[0]) > LANE_EPS):
                                    continue                        # 必须**同一条竖直车道** ✓
                                # ★ 轨可能在**下方**（y 更大 ✓）也可能在**上方** ✗ ⇒ 判据要**对称** ✓：
                                #   ✗ 第一版写成 `abs(min(_p2[1], _q2[1]) - b[1])` ✗ ⇒ 只有"轨在上方"
                                #     才成立 ✗ ⇒ 本仓这桩案子（GND 下轨 y=157.8，轨端是 **max** ✗）
                                #     **永远不触发** ✗（实测：两档数字与改前**逐字相同** ✗）。
                                #   ✓ 正解 = **任一端落在轨 y 上** ✓、搭**另一端** ✓。
                                _e1, _e2 = _p2[1], _q2[1]
                                if (abs(_e1 - b[1]) > LANE_EPS
                                        and abs(_e2 - b[1]) > LANE_EPS):
                                    continue                        # 它必须**自己通到轨** ✓
                                _ye = _e2 if abs(_e1 - b[1]) < LANE_EPS else _e1
                                # ★★ 2026-09-28 ✓ **搭点允许落在“本支线的脚行”上** ✓
                                #   （用户选 ②：在**支线搜索**里加这种候选 ✓；手改版第三次出现 ✓）
                                #   病灶 ✗：原来要求 `min + ε < _ye < max − ε` ✗
                                #     ⇒ 只认“邻居先到**某个中间端点**、本支线再到那个端点”✗
                                #     ⇒ 而手改版的做法是：**邻居那根竖线本来就通到这条脚行** ✓
                                #     （`J1` 的竖线 `(22.58,9)→(22.58,-72)` ✓）⇒ 本支线**横走到它的端点上** ✓
                                #     ⇒ 此时 `_ye == a[1]` ✗ ⇒ 被那个严格不等式**一票否决** ✗✗
                                #     （实测：`U1.c3` 一直自己竖一趟 81+7.2 ✗，而手改版只走 36 ✓）。
                                #   ✓ 现在：`_ye == a[1]` 也放行 ✓（= 端点对端点 ✓ 电学上真连 ✓）；
                                #     形状是 2 点 ✓ ⇒ 必须 `dedup_path` ✓（否则会多出一段**零点导线** ✗）。
                                if abs(_ye - a[1]) < LANE_EPS:
                                    _c4 = dedup_path([a, _q, (_q[0], _ye)])
                                elif min(a[1], b[1]) + PIN_EPS < _ye < max(a[1], b[1]) - PIN_EPS:
                                    _c4 = dedup_path([a, _q, (_q[0], _ye)])
                                elif (min(_p2[1], _q2[1]) + PIN_EPS < a[1]
                                      < max(_p2[1], _q2[1]) - PIN_EPS):
                                    # ★★ 2026-09-28 ✓ **第三种：接管**（学手改版第三次的**右半** ✓）
                                    #   病状 ✓：邻居那根竖线**跨过**本支线的脚行 ✗
                                    #     （`LED2` 的竖线 y: 17 → -72 ✓，`J2.c1` 的脚行 y=9 ✓）
                                    #     ⇒ 旧判据要求搭点在「脚行与轨**之间**」✗ ⇒ 一票否决 ✗
                                    #     （实测：`J2.c1` 一直自己竖一趋 81+7.2 ✗，而手改版只走 34 ✓）。
                                    #   ✓ 做法：本支线沿脚行横走过去、**接管脚行以下那截** ✓，
                                    #     邻居**截到交点** ✓ ⇒ 交点处**端点对端点** ✓（Fritzing 只认这个 ✓）。
                                    #   ★ 先“乐观地”截 ✓、再跑四道闸门 ✓；任何一道不过 ⇒ **原样回退** ✓
                                    #     （`used` 快照恢复 ✓）⇒ 绝不比原来差 ✓。
                                    _own = None
                                    for _s3 in segs:
                                        if _s3.get("fixed") or _s3.get("to") is not None:
                                            continue
                                        _pp = _s3.get("path") or []
                                        for _i3 in range(len(_pp) - 1):
                                            _A, _B = _pp[_i3], _pp[_i3 + 1]
                                            if ((abs(_A[0] - _p2[0]) < LANE_EPS
                                                 and abs(_A[1] - _p2[1]) < LANE_EPS
                                                 and abs(_B[0] - _q2[0]) < LANE_EPS
                                                 and abs(_B[1] - _q2[1]) < LANE_EPS)
                                                    or (abs(_A[0] - _q2[0]) < LANE_EPS
                                                        and abs(_A[1] - _q2[1]) < LANE_EPS
                                                        and abs(_B[0] - _p2[0]) < LANE_EPS
                                                        and abs(_B[1] - _p2[1]) < LANE_EPS)):
                                                _own = (_s3, _i3)
                                                break
                                        if _own:
                                            break
                                    if _own is None:
                                        continue              # 找不到“哪根线”⇒ 不接管 ✓（宁可不做 ✗）
                                    _snap = list(used)
                                    _bak = truncate_branch_at(_own[0], _own[1],
                                                              (_p2[0], a[1]), net)
                                    _c4 = [a, (_p2[0], a[1]), (_p2[0], b[1])]
                                    if (not body_hard_bad(_c4, boxes, PIN_ALL)
                                            and not pin_hard_bad(_c4, PIN_ALL, own_pins)
                                            and not ovl_hard_bad(_c4, used)
                                            and pin_intr(_c4, own_pins, PIN_ALL) == 0):
                                        _L = _c4
                                        break
                                    _own[0]["path"], _own[0]["b"] = _bak[0], _bak[1]
                                    used[:] = _snap            # ★ 原样回退 ✓
                                    continue
                                else:
                                    continue                        # 既不在脚行上、也不在之间 ⇒ 不行 ✗
                                if (not body_hard_bad(_c4, boxes, PIN_ALL)
                                        and not pin_hard_bad(_c4, PIN_ALL, own_pins)
                                        and not ovl_hard_bad(_c4, used)
                                        and pin_intr(_c4, own_pins, PIN_ALL) == 0):
                                    _L = _c4
                                    break
                            if _L is not None:
                                break
                            _cand = [a, _q, (_q[0], b[1])]
                            if (not body_hard_bad(_cand, boxes, PIN_ALL)
                                    and not pin_hard_bad(_cand, PIN_ALL, own_pins)
                                    and not ovl_hard_bad(_cand, used)
                                    and pin_intr(_cand, own_pins, PIN_ALL) == 0):
                                # ★★ 2026-09-28 ✓ **不立刻定案** ✗ —— 这是「自己竖一趟」的形状 ✓，
                                #   先记下来当**兜底** ✓，继续往后（k 更大 / 另一方向）找
                                #   「**共享竖线**」✓ —— 共享一定更短 ✓（实测 88.2 → 36.0 ✓），
                                #   而第一版在这里就 `break` ✗ ⇒ 新候选永远轮不到 ✗（实测零效果 ✗）。
                                if _Lfall is None:
                                    _Lfall = _cand
                                continue
                        if _L is not None:
                            break
                    if _L is None:
                        _L = _Lfall
            if _L is not None:
                best, best_key = _L, route_key(_L, mine, own_pins, used)
                # ★ 形状**从几何自己读** ✓（不加标志位 ✗ —— 两处记账早晚失步 ✗）：
                #   2 点 = 直连 ✓；3 点且末点落在轨 y 上 = L 形到轨 ✓；
                #   3 点而末点**不在轨上** = **T 形搭接** ✓（搭在别人的端点上 ✓）。
                _tjpt = None
                if pr.get("vlane"):
                    # ★ 车道支线**几何自己说话**：一条水平线 ✓（不加标志位 ✗ —— 见上面那条教训 ✓）
                    _shape, _det = ("横到车道（0 拐）", "沿脚行 %s %.1f ⇒ 到竖直车道 x=%.3f ✓"
                                    % ("向右" if _L[-1][0] > a[0] else "向左",
                                       abs(_L[-1][0] - a[0]), _L[-1][0]))
                elif len(_L) == 2 and abs(_L[1][1] - _L[0][1]) > LANE_EPS:
                    _shape, _det = "直连（0 拐）", "直上/直下到轨"
                elif len(_L) == 2:
                    # ★★ 2026-09-28 ✓ 新形状 ✓：**沿脚行横走，搭到同网那根竖线的端点上** ✓
                    #   （= 用户手改版第三次的做法 ✓；`_ye == a[1]` 那一支 ✓；
                    #    这种支线**根本不到轨** ✗ ⇒ 上面 `trim_on_rail` 必须认得它 ✗✗）
                    _shape = "共享竖线（0 拐）"
                    _det = ("沿脚行 %s %.1f ⇒ 搭在同网竖线的端点 (%.1f,%.1f) ✓"
                            "（**不自己再竖一趟** ✓）"
                            % ("向右" if _L[1][0] > a[0] else "向左",
                               abs(_L[1][0] - a[0]), _L[-1][0], _L[-1][1]))
                    _tjpt = _L[-1]
                elif abs(_L[-1][1] - b[1]) < LANE_EPS:
                    # ★★ 2026-09-28 ✓ **「接管」要能从几何读出来** ✓（不加标志位 ✗ ——
                    #   两处记账早晚失步 ✗）：有**同网**的已布段**以我的拐点为起点** ✓、
                    #   而它的终点**不是**我的终点 ✗（我那段竖线要到轨 ✓）⇒ 那就是被截到
                    #   交点的邻居 ✓。
                    _shared = None
                    if (len(_L) == 3 and abs(_L[1][0] - _L[0][0]) > LANE_EPS
                            and abs(_L[2][1] - _L[1][1]) > LANE_EPS):
                        # ★ 判据：**同网**已布段**有一个端点正好落在我的拐点上** ✓、
                        #   而它的**另一个端点不是我的终点** ✗（我那段竖线要到轨 ✓）
                        #   ⇒ 那就是被截到交点的邻居 ✓。两个端点都要看 ✗ ——
                        #   ✗ 第一版只看了段首 ✗ ⇒ 邻居那段（它的**末端**才是交点 ✗）
                        #     没被认出来 ⇒ 形状打印退回“L 形” ✗（形状对了、名字错了 ✗）。
                        _shared = _L[1] if any(
                            _u[2] == net and (
                                (abs(_u[0][0] - _L[1][0]) < LANE_EPS
                                 and abs(_u[0][1] - _L[1][1]) < LANE_EPS
                                 and not (abs(_u[1][0] - _L[2][0]) < LANE_EPS
                                          and abs(_u[1][1] - _L[2][1]) < LANE_EPS))
                                or (abs(_u[1][0] - _L[1][0]) < LANE_EPS
                                    and abs(_u[1][1] - _L[1][1]) < LANE_EPS
                                    and not (abs(_u[0][0] - _L[2][0]) < LANE_EPS
                                             and abs(_u[0][1] - _L[2][1]) < LANE_EPS)))
                            for _u in used) else None
                    if _shared is not None:
                        _shape = "共享竖线（1 拐）"
                        _det = ("沿脚行 %s %.1f ⇒ 在 (%.1f,%.1f) **接管**同网竖线"
                                "（邻居截到该点 ✓）⇒ 一路到轨 y=%.1f ✓"
                                % ("向右" if _L[1][0] > a[0] else "向左",
                                   abs(_L[1][0] - a[0]), _shared[0], _shared[1], b[1]))
                        _tjpt = _shared
                    else:
                        _shape = "L 形（1 拐）"
                        _det = "出脚 %s %.1f" % ("向右" if _L[1][0] > a[0] else "向左",
                                                abs(_L[1][0] - a[0]))
                else:
                    _shape = "T 形搭接（1 拐）"
                    _det = ("出脚 %s %.1f ⇒ 搭在同网同车道的端点 (%.1f,%.1f) ✓"
                            % ("向右" if _L[1][0] > a[0] else "向左",
                               abs(_L[1][0] - a[0]), _L[-1][0], _L[-1][1]))
                    _tjpt = _L[-1]
                print("   ★ 支线 **%s** ✓：%-22s %s ✓ 贴脚 0 ✓ 不重叠 ✓ 不穿体 ✓"
                      % (_shape, tt, _det))
                if _tjpt is not None:
                    _tjs.append((tt, _tjpt))
            else:
                # ★ 诊断 ✓（2026-09-28 ✓ 用户选方案 1 后实测："加大到 6 格 + 双向" 仍只成功 3 条 ✗
                #   ⇒ 说明**瓶颈不是档位** ✗ ⇒ 把 4 个闸门在**第一档**上的结果**如实打出来** ✓，
                #   别猜 ✗。`False` = 该闸门通过 ✓。）
                if rail_ys and pr["rb"] is None:
                    _n2 = PIN_N_BY_XY.get((round(a[0], 3), round(a[1], 3)), (0.0, 0.0))
                    if abs(_n2[0]) > 0.5 and abs(_n2[1]) < 1e-6:
                        _s2 = 1.0 if _n2[0] > 0 else -1.0
                        _c2 = [a, (a[0] + _s2 * 7.2, a[1]), (a[0] + _s2 * 7.2, b[1])]
                        print("   ⚠ 支线 L 形**全不合格** ✗：%-22s 法线 (%.3f,%.3f) ✓ ｜ "
                              "第一档（出脚 %.1f ✓）四个闸门 = 穿体 %s ｜ 压别人脚 %s ｜ "
                              "与已布线重叠 %s ｜ **贴脚数 %d** ✓（`False`/`0` = 通过 ✓）"
                              % (tt, _n2[0], _n2[1], abs(_c2[1][0] - a[0]),
                                 body_hard_bad(_c2, boxes, PIN_ALL),
                                 pin_hard_bad(_c2, PIN_ALL, own_pins),
                                 ovl_hard_bad(_c2, used),
                                 pin_intr(_c2, own_pins, PIN_ALL)))
                        # ★ 细诊 ✓（`STEM_DIAG=<子串>` 命中该支线时才打 ✓，免得报告被淹 ✗）：
                        #   逐档（**2 方向 × 6 档 = 12 档** ✓）报出**每个闸门**与**跟谁重叠** ✓
                        #   ⇒ 一眼看出卡在哪道门、对手是**同网的轨**还是**别的线** ✓（Task 2 ✓）。
                        _sd = os.environ.get("STEM_DIAG", "")
                        if _sd and _sd in tt:
                            print("      ↳ 逐档细诊 ✓（`STEM_DIAG=%s` ✓）：脚 (%.1f,%.1f) ✓ "
                                  "落点 x 候选 %s ✓ ｜ `used` 现有 %d 段 ✓"
                                  % (_sd, a[0], a[1], "右/左各 6 档", len(used)))
                            for _sgn in (_s2, -_s2):
                                for _k in (1, 2, 3, 4, 5, 6):
                                    _q = (a[0] + _sgn * _k * 7.2, a[1])
                                    _cc = [a, _q, (_q[0], b[1])]
                                    _ps = ovl_partners(_cc, used)
                                    print("        · 出脚 %s %.1f ⇒ 垂直到轨 y=%.1f："
                                          "穿体 %s ｜ 压别人脚 %s ｜ 重叠 %d 段 ｜ 贴脚 %d"
                                          % ("右" if _sgn > 0 else "左", _k * 7.2, b[1],
                                             body_hard_bad(_cc, boxes, PIN_ALL),
                                             pin_hard_bad(_cc, PIN_ALL, own_pins),
                                             len(_ps), pin_intr(_cc, own_pins, PIN_ALL)))
                                    for (_m, _n, _p2, _q2) in _ps:
                                        print("            ↳ 候选段 (%.1f,%.1f)→(%.1f,%.1f) "
                                              "压住已布段 (%.1f,%.1f)→(%.1f,%.1f) ✗"
                                              % (_m[0], _m[1], _n[0], _n[1],
                                                 _p2[0], _p2[1], _q2[0], _q2[1]))
                            # ★★ T 形搭接**为什么没触发** ✓（2026-09-28 ✓ 实测 socket0 没触发、
                            #   socket4 触发了 ✗ ⇒ 别猜原因 ✗）：把 `used` **全量** + 每条
                            #   「同网 + 同竖直车道 + 自己通到轨」的候选**逐门**打出来 ✓。
                            #   ★ 判据仍调**同一批函数** ✓（不自证 ✗）。
                            print("      ↳ `used` 全量 ✓（%d 段 ✓）：" % len(used))
                            for _u3 in used:
                                print("        · [%s] (%.3f,%.3f)→(%.3f,%.3f)"
                                      % (_u3[2], _u3[0][0], _u3[0][1], _u3[1][0], _u3[1][1]))
                            _any = False
                            for _sgn2 in (_s2, -_s2):
                                for _k2 in (1, 2, 3, 4, 5, 6):
                                    _q2 = (a[0] + _sgn2 * _k2 * 7.2, a[1])
                                    for _u2 in used:
                                        if _u2[2] != net:
                                            continue
                                        if (abs(_u2[0][0] - _q2[0]) > 1e-6
                                                or abs(_u2[1][0] - _q2[0]) > 1e-6):
                                            continue
                                        _e1, _e2 = _u2[0][1], _u2[1][1]
                                        if (abs(_e1 - b[1]) > 1e-6
                                                and abs(_e2 - b[1]) > 1e-6):
                                            continue
                                        _ye2 = _e2 if abs(_e1 - b[1]) < 1e-6 else _e1
                                        if not (min(a[1], b[1]) < _ye2 < max(a[1], b[1])):
                                            continue
                                        _any = True
                                        _c5 = [a, _q2, (_q2[0], _ye2)]
                                        _pn5 = pin_intr_list(_c5, own_pins, PIN_ALL)
                                        print("        ★ T 候选 车道 x=%.3f（%s出脚 %.1f）"
                                              "搭点 (%.3f,%.3f)：穿体 %s ｜ 压脚 %s ｜ "
                                              "重叠 %s ｜ 贴脚 %d"
                                              % (_q2[0], "右" if _sgn2 > 0 else "左", _k2 * 7.2,
                                                 _q2[0], _ye2,
                                                 body_hard_bad(_c5, boxes, PIN_ALL),
                                                 pin_hard_bad(_c5, PIN_ALL, own_pins),
                                                 ovl_hard_bad(_c5, used),
                                                 len(_pn5)))
                                        # ★ **点名**是哪只脚 ✓ + 精确距离 ✓（用仓里唯一那份
                                        #   `sch_geom.p2seg` ✓）⇒ 分清"真太近"✗ 与"采样误报"✗
                                        for (_r3, _c3n, _x3, _y3) in _pn5:
                                            _dd = min(SG.p2seg((_x3, _y3), _c5[_j], _c5[_j + 1])
                                                      for _j in range(len(_c5) - 1))
                                            print("            ↳ 贴到 %s.%s (%.3f,%.3f) ⇒ 精确距离 "
                                                  "%.6f 单位（阈值 < %.1f ⇒ %s）"
                                                  % (_r3, _c3n, _x3, _y3, _dd, CLEAR_PIN,
                                                     "确实太近 ✗" if _dd < CLEAR_PIN
                                                     else "其实够远 ✓ ⇒ **采样误报** ✗"))
                            if not _any:
                                print("        ✗ **没有**任何「同网 + 同竖直车道 + 自己通到轨」"
                                      "的已布段 ⇒ T 形搭接无从发起 ✗")
                    else:
                        # ★★★ 垂直法线 ⇒ **优先试"直连（0 拐）"** ✓（2026-09-28 ✓ 用户选 A ✓）：
                        #   实测（`t58_report.txt` ✓）：`GND C1.c1` 与 `GND U1.c20`（EPAD ✗）
                        #   的直连**四个闸门全过** ✓（贴脚 0 ✓、不穿体 ✓、不压别人的脚 ✓、不重叠 ✓）
                        #   ⇒ 却**没被 `route_pair` 选中** ✗ ⇒ 白绕了一截 ✗。
                        #   ✓ 所以支线**优先试直连** ✓（最短最简单 ✓）；不合格才交回通用路由 ✓。
                        #   ★ 安全 ✓：若法线**背向**轨（直连会穿自己的元件 ✗）⇒
                        #     `body_hard_bad` 会拒 ✓ ⇒ 自动回落 ✓，不必另写判据 ✓。
                        _c3 = [a, (a[0], b[1])]
                        if (not body_hard_bad(_c3, boxes, PIN_ALL)
                                and not pin_hard_bad(_c3, PIN_ALL, own_pins)
                                and not ovl_hard_bad(_c3, used)
                                and pin_intr(_c3, own_pins, PIN_ALL) == 0):
                            _L = _c3
                        else:
                            print("   · 支线**法线不是水平** ⇒ L 形不适用 ✓、直连也不合格 ✗："
                                  "%-22s 法线 (%.3f,%.3f) ✓ 脚 (%.1f,%.1f) ✓ ｜ 四个闸门 = "
                                  "穿体 %s ｜ 压别人脚 %s ｜ 与已布线重叠 %s ｜ **贴脚数 %d** ✓"
                                  % (tt, _n2[0], _n2[1], a[0], a[1],
                                     body_hard_bad(_c3, boxes, PIN_ALL),
                                     pin_hard_bad(_c3, PIN_ALL, own_pins),
                                     ovl_hard_bad(_c3, used),
                                     pin_intr(_c3, own_pins, PIN_ALL)))
                # ★★★ `_L` **必须在这里再判一次** ✓（2026-09-28 ✓ 修死代码 ✗）：
                #   ✗ 上一版把"用 `_L`"写在 `if _L is not None:`（在本块**之前**）里 ✗
                #     ⇒ "法线不是水平"这一支里设的 `_L` **被本行 `route_pair` 无条件覆盖** ✗
                #     = **死代码** ✗（既不打印、也不生效 ✗）。
                #   实测症状 ✓（自证的错 ✗，用报告对出来的 ✓）：`GND C1.c1` 与 `GND U1.c20`
                #     两条**四门全过**的直连在报告里**连"不合格"都不打** ✗，两档数字与改前**逐字相同** ✗。
                #   ★ 次序仍是"**直连优先、不合格才交回通用路由**"✓（与上面注释同义 ✓）。
                if _L is not None:
                    best, best_key = _L, route_key(_L, mine, own_pins, used)
                    print("   ★ 支线 **直连（0 拐）** ✓：%-22s 直上/直下到轨 ✓ "
                          "贴脚 0 ✓ 不重叠 ✓ 不穿体 ✓" % tt)
                else:
                    best, best_key = route_pair(a, b, mine, own_pins, used, tag=tt, net=net)
            if best is None:
                warn.append("%s: 没找到不碰本体的路径 ✗" % tt)
                best = candidates(a, b, sorted(chx), sorted(chy))[0]
            for k in range(len(best) - 1):
                used.append((best[k], best[k + 1], net))
            segs.append({"a": best[0], "b": best[-1], "path": best,
                         "from": {"ref": pr["ra"], "cid": pr["ca"]},
                         "to": ({"ref": pr["rb"], "cid": pr["cb"]} if pr["rb"] else None),
                         # ★ 抽出重排要用同一套上下文 ✓（`mine`/`own_pins`/`net` ✓）
                         "mine": mine, "own_pins": own_pins, "net": net, "key": best_key})
        # ── ★★ 修“重叠 6 对” ✓（2026-09-28 ✓ 明细实测 ✓，不是推的 ✗）─────────────────
        #   病状 ✓（`t57` 的 6 对**全是同一个形态** ✓）：
        #       支线 `(0.0,-57.6)→(83.8,-57.6)` 与 轨段 `(49.4,-57.6)→(83.8,-57.6)` **共线** ✗
        #   病根 ✓：支线为了避开别人的线，会**先沿轨横走一段**才到落点 ✗ ——
        #       而**那一段本来就是轨** ✗（同网 ✓、同一条水平线 ✓、电学上是同一段导体 ✓）。
        #   ✓ 治法：把支线**第一次到达轨 y 之后的部分全部截掉** ✓（那部分交给轨去覆盖 ✓）
        #       ⇒ 支线的终点 = 它**垂直到达轨**的那个点 ✓
        #       ⇒ 轨再按**这些接口点**去连 ✓ ⇒ 谁都不与谁共线 ✓✓
        #   ★ 电气上等价 ✓（截掉的那截与轨同网、且被轨覆盖 ✓）；用户规则②“不许重叠”直接归零 ✓。
        if rail_ys:
            _nt = trim_on_rail(segs, net, rail_ys)
            print("   支线清理 ✓：%d 条支线“趴在轨上”的多余点已删 ✓（落点保持不变 ✓；`used` 同步 ✓）"
                  % _nt)
        # ★ T 形搭接清单 ✓（用户要求“把被改动的支线清单打出来” ✓，2026-09-28 ✓）
        if _tjs:
            print("   ★ T 形搭接清单 ✓（%d 条 ✓，网 %s ✓）：%s"
                  % (len(_tjs), net,
                     "; ".join("%s→搭点(%.1f,%.1f)" % (t2.split()[1], p2[0], p2[1])
                               for t2, p2 in _tjs)))

        # ★★ 电源轨**本身** = 这条网的**预置线段** ✓（`fixed` ✓ ⇒ 不参与抽出重排 ✗）
        #   ★ 断点 = **支线真正落到轨上的那些点** ✓（= 截断后的终点 ✓，**不是**“脚的 x” ✗）——
        #     Fritzing 的连接是**端点对端点** ✗ ⇒ 支线落在干线**中段**上就连不上 ✗；
        #     而用“脚的 x”当断点时，支线的落点常常**不在那儿** ✗（它绕了 ✓）⇒ 支线得沿轨挪过去 ✗
        #     ⇒ 那正是上面那 6 对重叠的来源 ✓。用**落点本身**当断点 ⇒ 一次对上 ✓。
        # ★★★ 轨的 x 范围 = **该网自己所有接头（上下两轨合并）的 min/max** ✓
        #   ✗ 两个被实测否证的版本（都留了**悬空线头** ✗ ⇒ Fritzing 画飞线 ✗，见下 ✓）：
        #     · 初版：`min(_xs)/max(_xs)` **每条轨各算各的** ✗ ⇒ 两轨端点不齐（-17.172 vs -0.672 ✗）
        #       ⇒ 一根竖线接不上 ⇒ 得补折线 ⇒ 像打补丁 ✗；
        #     · 方案 A（用户选过 ✓）：锚到**整个零件包围盒** ± margin ✗ ⇒ 两轨对齐了 ✓
        #       但轨**横贯全图** ✗ ⇒ 实测总长 2025 → **3518** ✗✗、画布 94.7 → **163.6** ✗。
        #   ✓ 现在这版：**用该网自己的接头范围** ⇒ ① 同网两轨**天然对齐** ✓（同一对 min/max ✓）
        #     ② 轨**不外伸** ⇒ 端点**正好落在最外侧的支线落点上** ✓ ⇒ **没有悬空线头** ✓✓
        #     ③ 顺带把长度收回来 ✓。
        _allx = sorted({round(s["b"][0], 4) for s in segs
                        if not s.get("fixed") and s.get("to") is None
                        and any(abs(s["b"][1] - _yy) < 1e-6 for _yy in rail_ys)}
                       | {round(_x7, 4) for (_x7, _r7, _c7, _y7) in _sit})
        _rx = {}
        if _allx:
            # ★ **左端再外伸一格**（= 7.2 = `CLEAR_PIN` ✓），**右端不外伸** ✓ —— 为什么 ✗：
            #   ✗ 原来竖线放在 `x = min(_allx)` ✗ ⇒ 实测**与最左侧那条支线的竖直段共线** ✗：
            #       支线 (-2.8,-9.0)→(-2.8,-72.0) 与 竖线 (-2.8,-72.0)→(-2.8,180.0)
            #       ⇒ 重叠段 [-72,-9] ✗ ⇒ 自检报「不同的导线重叠 **1 对**」✗、**退出码 1** ✗
            #         （电气上无害 ✓ —— 同一网的导体；但本仓「不同的导线不许重叠」是**硬闸门** ✗）。
            #   ✓ 左端外伸一格 ⇒ 竖线落在这**一格之外** ✓ ⇒ 与任何支线都不共线 ✓；
            #     而竖线的**两个端点**分别落在**上/下轨的端点**上 ✓（轨端就在这个 x ✓）⇒ **不算悬空** ✓
            #     ⇒ 悬空线头同时归零 ✓（右端不外伸 ⇒ 那里也没有线头 ✓）。
            #   ★ 位置安全 ✓：x 在**所有元件左侧**、y 是轨线（本就在包围盒之外 ✓）⇒ 不穿本体 ✓。
            # ★★★ 轨间互连竖线：**优先与最外侧那条支线共用一根** ✓
            #   （2026-09-28 ✓ 学用户手改版 `pixel-schematic-v21_byHand.fzz` ✓）
            #   病灶（逐段实测 ✓）：老样子把互连竖线放在 `min(_allx) - 7.2` ✗ ⇒ 它**自己跑一趟**
            #     （GND 实测 229.8 ✓）、而最外侧那条支线**又跑一趟**到轨 ✗ ⇒ 同一段竖直**各画一遍** ✗。
            #   手改版把两者并成一根 ✓ ⇒ GND **−72.3** ✓、交叉 **−3** ✓（账目逐项对得上 ✓）。
            #   ✓ 新法：互连竖线放在**最外侧支线的车道** `x = min(_allx)` ✓，并把那条支线
            #     **截成只剩出脚** ✓（竖直段由互连竖线**兼任** ✓）—— 与上一手 T 形搭接**同一招** ✓
            #     （那次是“支线搭支线” ✓，这次是“互连搭支线” ✓）。
            #   ★ 只在**三个闸门全过**时才用 ✓（不穿体 ✓、不压脚 ✓、不与已布线重叠 ✓）；
            #     否则**原样回退** ✓ ⇒ 绝不比老样子差 ✓。
            #   ★ 交界点 = **那条支线的脚行 y** ✓ ⇒ 精确正交 ✓（手改版在这里有 0.1 单位的斜量 ✗）。
            _lane = min(_allx)
            _split_ys, _mg = [], []
            # ★ 2026-10-04 ✓ **把“轨 x 范围的原料”报出来** ✓（用户问“右边那段多余的地线哪来的” ✓）——
            #   轨的 x 范围 = `min/max(_allx)` ✓，所以这几个数**就是**病根 ✓；
            #   ✗ 不报数就只能猜 ✗（本仓规矩：判据要能被独立复核 ✓）。
            print("   · 轨 x 范围原料 ✓：min/max(_allx) = %.3f / %.3f ✓（%d 个落点 ✓：%s%s ✓）"
                  % (min(_allx), max(_allx), len(_allx),
                     " ".join("%.1f" % v for v in sorted(_allx)[:12]),
                     " …" if len(_allx) > 12 else ""))
            for _s in segs:
                if _s.get("fixed") or _s.get("to") is not None:
                    continue
                _p = _s.get("path") or []
                if (len(_p) == 3 and abs(_p[1][0] - _lane) < 1e-6
                        and abs(_p[2][0] - _lane) < 1e-6
                        and abs(_p[1][1] - _p[0][1]) < 1e-6
                        and abs(_p[2][1] - _p[1][1]) > 1e-6
                        and any(abs(_p[2][1] - _ry) < 1e-6 for _ry in rail_ys)
                        and min(rail_ys) + 1e-6 < _p[0][1] < max(rail_ys) - 1e-6):
                    _mg.append(_s)
                    _split_ys.append(_p[0][1])
            _vx, _x0, _x1 = min(_allx) - 7.2, min(_allx) - 7.2, max(_allx)
            if _mg:
                _used0 = list(used)
                _p0 = [(_s, list(_s["path"]), _s["b"]) for _s in _mg]
                for _s in _mg:                       # 截成只剩出脚 ✓（同步 used ✓）
                    _old = [(_s["path"][k], _s["path"][k + 1], net)
                            for k in range(len(_s["path"]) - 1)]
                    _s["path"] = _s["path"][:2]
                    _s["b"] = _s["path"][-1]
                    _new = [(_s["path"][0], _s["path"][1], net)]
                    for _sg in _old:
                        if _sg not in _new and _sg in used:
                            used.remove(_sg)
                    for _sg in _new:
                        if _sg not in used:
                            used.append(_sg)
                _drawn_pre = [_ry for _ry in rail_ys          # 与下面轨循环**同一个判据** ✓
                              if any(not _s.get("fixed") and _s.get("to") is None
                                     and abs(_s["b"][1] - _ry) < 1e-6 for _s in segs)]
                _vp_pre = ([(_lane, _y) for _y in sorted(set(_drawn_pre) | set(_split_ys))]
                           if len(_drawn_pre) > 1 else [])
                # ★ 三道门**逐项报数** ✓（2026-09-28 ✓ 教训：糊成一句"未全过"✗ ⇒ 同一个车道
                #   在两档结论不同时**查不出原因** ✗）⇒ 报出 穿体 / 贴脚 / 重叠 与**点名**那只脚 ✓。
                _nv_b = 1 if (_vp_pre and body_hard_bad(_vp_pre, boxes, PIN_ALL)) else 0
                _nv_p = pin_intr(_vp_pre, set(), PIN_ALL) if _vp_pre else 0
                _nv_o = 1 if (_vp_pre and ovl_hard_bad(_vp_pre, used)) else 0
                if _vp_pre and not (_nv_b or _nv_p or _nv_o):
                    _vx, _x0 = _lane, _lane
                    print("   ★ 轨间互连**与最外侧支线共用** ✓：车道 x=%.3f ✓"
                          "（截短 %d 条支线 ✓、交界点 %s ✓；老法是 x=%.3f ✗）"
                          % (_lane, len(_mg),
                             "/".join("%.1f" % _y for _y in _split_ys),
                             min(_allx) - 7.2))
                else:
                    used[:] = _used0                       # ★ 原样回退 ✓
                    for _s, _p2, _b2 in _p0:
                        _s["path"] = _p2
                        _s["b"] = _b2
                    _split_ys, _mg = [], []
                    # ★★ 2026-09-28 ✓ 修（`J1` 转 180° 后暴露 ✗）：**兜底位置也要过那三道门** ✗
                    #   ✗ 原来兜底直接取 `min(_allx) − 7.2` ✗、**从不检查** ✗ ⇒ 实测它**正好落在
                    #     `J1` 旋转后的引脚列上**（`x = 15.378` ✓）⇒ 一根 GND 竖线把 `c0/c1/c2`
                    #     串穿 ✗ ⇒ 判据报 **`(B) = 3`** ✗ + 贴脚 3 处（0.00 单位 ✗）。
                    #     ★ v22 之所以没暴露 ✓：那时 `J1` 的脚在**左缘 `x=0`** ✓，老位置 15.378
                    #       落在它盒子的**右缘**（边界 ✓）⇒ 一个脚都没压到 ⇒ **蒙对了** ✓。
                    #   ✓ 现在：向外逐档试 `min(_allx) − 7.2·k`（k = 1…4 ✓），取第一个
                    #     **不压脚 ✓ 不穿体 ✓ 不重叠 ✓** 的位置 ✓；四档都不行 ⇒ 保留老位置 + 告警 ✓。
                    _hit = None
                    for _k5 in range(1, 5):
                        _v5 = min(_allx) - 7.2 * _k5
                        _c5 = [(_v5, _y5) for _y5 in sorted(set(_drawn_pre) | set(_split_ys))]
                        if len(_c5) < 2:
                            break
                        if (not body_hard_bad(_c5, boxes, PIN_ALL)
                                and pin_intr(_c5, set(), PIN_ALL) == 0
                                and not ovl_hard_bad(_c5, used)):
                            _hit = (_v5, _k5)
                            break
                    if _hit:
                        _vx, _x0 = _hit[0], _hit[0]
                        print("   ★ 兜底位置**避开引脚列** ✓：x=%.3f ✓（老位置 x=%.3f 会压脚 ✗，"
                              "向外挪 %d 档 ✓；穿体/压脚/重叠 三门全过 ✓）"
                              % (_vx, min(_allx) - 7.2, _hit[1]))
                    else:
                        print("   ⚠ 兜底位置**四档都不合格** ✗ ⇒ 仍用老位置 x=%.3f ✓（请人看一眼 ✓）"
                              % _vx)
                    print("   · 轨间互连**不能共用** ✗（车道 x=%.3f：穿体 %d ｜ 贴脚 %d ｜ "
                          "与已布线重叠 %d ｜ 可搭支线 %d 条 ✗）⇒ 用老位置 x=%.3f ✓"
                          % (_lane, _nv_b, _nv_p, _nv_o, len(_p0), _vx))
                    for (_r4, _c4n, _x4, _y4) in (pin_intr_list(_vp_pre, set(), PIN_ALL)
                                                  if _vp_pre else []):
                        _d4 = min(SG.p2seg((_x4, _y4), _vp_pre[_k4], _vp_pre[_k4 + 1])
                                  for _k4 in range(len(_vp_pre) - 1))
                        print("            ↳ 连它太近 ✗：%s.%s (%.3f,%.3f) 距离 %.3f 单位"
                              % (_r4, _c4n, _x4, _y4, _d4))
            # ★★★ 2026-10-04 ✓ **分岛 ⇒ 每段轨只看自己的落点** ✓（用户点名 ✓「**把底部右侧的
            #   多余的地线删除**」✓）——
            #   ✗ 病：`_x0/_x1` 用的是**整张网**的 min/max ✗（那是为了给"轨间互连竖线"找一个
            #     **共同 x** ✓，见上面那段注释 ✓）；可**分岛之后那根竖线不画了** ✗ ⇒ 这个范围
            #     就**只剩副作用** ✗：下轨被拉到 x -6.222…180.000 ✓ 而它自己的落点只有
            #     37.728…161.328 ✓ ⇒ **左右各挂一截悬空线头** ✗✗（实测 43.95 + 18.67 = 62.6
            #     单位 = **17.7 mm** ✗）；上轨左端同样白挂 28.8 = 8.1 mm ✗。
            #   ✓ 现在：点名的岛网**且本网有 ≥2 段活轨**（= 确实"故意不连"✓）时，
            #     每段轨只取**自己落点**的首尾 ✓ ⇒ 端点落在落点上 ✓ ⇒ **悬空线头归零** ✓。
            #   ★ 只在这一种情形下收紧 ✓：别的网、以及不画岛的时候，`_x0/_x1` 照旧 ✗
            #     （那根互连竖线要靠"两轨端点对齐"才不悬空 ✓）。
            def _landings(_yy):
                r"""落在轨 y=`_yy` 上的 x ✓（**唯一实现** ✓：轨循环与"有几段活轨"共用 ✓，不抄两份 ✗）"""
                return sorted({round(s["b"][0], 4) for s in segs
                               if not s.get("fixed") and s.get("to") is None
                               and abs(s["b"][1] - _yy) < 1e-6}
                              | {round(_x7, 4) for (_x7, _r7, _c7, _y7) in _sit
                                 if abs(_y7 - _yy) < 0.6})

            _n_live = sum(1 for _yy in rail_ys if _landings(_yy))
            _tight = (net in ISLAND_NETS and _n_live > 1)
            if _tight:
                print("   ★ **轨按自己的落点收紧** ✓（岛网 `%s` ✓，本网 %d 段活轨 ✓）："
                      "轨两端**不再外伸到“整张网的 min/max”** ✗ ⇒ 悬空线头归零 ✓"
                      % (net, _n_live))

            _drawn = []
            for _y in rail_ys:
                _xs = _landings(_y)
                if not _xs:
                    continue                      # 这条轨上一条支线、一只坐脚都没有 ⇒ 不必画 ✗
                # ★★ 2026-09-28 ✓ **轨的两端不许“看着接在别的网上”** ✗（= “跨网假接头” ✗✗，用户点名 ✓）
                #   实测（v25 ✓）：5V 上轨的**外伸段端点** `(22.578,-57.6)` 正落在 GND 那根竖线
                #     `(22.578,9)→(22.578,-72)` 的**中段**上 ✗ ⇒ 图上**看着 5V 接在 GND 上** ✗✗
                #     （两个网的坐标都是 7.2 的整数倍 ⇒ **同一条网格线**上碰巧重合 ✓）。
                #   ✗ 第一版治法是“往里收 `2 × MIN_SEG = 0.1`”✗ ⇒ 判据上干净了 ✓，但那只有
                #     **0.028 mm < 线宽 0.25 mm** ✗ ⇒ **肉眼看还是贴在一起** ✗ = 等于没修 ✗。
                #   ✓ 现在（用户定 ✓：“要考虑人眼视觉的局限性 ✓ 要尽量清晰” ✓）：
                #     ① 要求**让开 `FJ_GAP = 2.03 mm`**（= 用户定“贴脚”判据的**同一个数** ✓）；
                #     ② 让开时**按 7.2 的整数步往回退**（1…4 步 ✓）⇒ 端点仍在**网格**上 ✓、
                #        而且多半正好落在**本网最外侧那个落点**上 ✓ ⇒ 顺带把“悬空线端”也消掉 ✓；
                #     ③ 不许退过最外侧落点（否则路径会回头成锯齿 ✗）；
                #     ④ 四步都让不开 ⇒ 退到**最小让开量** `2 × MIN_SEG` + **告警** ✓；
                #     ⑤ 这一端**接了东西** ⇒ **不动** ✓ + 告警 ✓（不许悄悄拆掉真接头 ✗）。
                _x0r, _x1r = ((_xs[0], _xs[-1]) if (_tight and len(_xs) >= 2)
                              else (_x0, _x1))
                for _sgn7, _nm7 in ((1.0, "左"), (-1.0, "右")):
                    _e7 = (_x0r, _y) if _sgn7 > 0 else (_x1r, _y)
                    if not fj_too_close(_e7, net, used):
                        continue
                    if fj_endpoint_used(_e7, used, net):
                        warn.append("%s 的 %s端 (%.3f,%.1f) 离**别的网**的线不到 %.1f 单位 ✗，"
                                    "但它上面**接了东西** ⇒ 不动 ✓（请人看一眼 ✓）"
                                    % (net, _nm7, _e7[0], _y, FJ_GAP))
                        continue
                    _lim7 = _xs[0] if _sgn7 > 0 else _xs[-1]      # ★ 不许退过最外侧落点 ✓
                    _done7 = False
                    for _k7 in range(1, 5):
                        _xv7 = _e7[0] + _sgn7 * 7.2 * _k7
                        if _sgn7 > 0 and _xv7 > _lim7:
                            break
                        if _sgn7 < 0 and _xv7 < _lim7:
                            break
                        if fj_too_close((_xv7, _y), net, used):
                            continue
                        if _sgn7 > 0:
                            _x0r = _xv7
                        else:
                            _x1r = _xv7
                        _done7 = True
                        print("   ★ 轨 %s端**让开跨网假接头** ✓：y=%.1f 由 x=%.3f 退到 x=%.3f ✓"
                              "（让开 %.1f 单位 = **%.2f mm** ✓ 肉眼分得清 ✓；退 %d 步 × 7.2 ✓）"
                              % (_nm7, _y, _e7[0], _xv7, abs(_xv7 - _e7[0]),
                                 abs(_xv7 - _e7[0]) * 25.4 / 90.0, _k7))
                        break
                    if not _done7:                                # 退不开 ⇒ 最小让开 + 告警 ✓
                        if _sgn7 > 0:
                            _x0r = _x0 + 2 * MIN_SEG
                        else:
                            _x1r = _x1 - 2 * MIN_SEG
                        warn.append("%s 的 %s端 (%.3f,%.1f) 离**别的网**的线不到 %.1f 单位 ✗，"
                                    "但四步都让不开 ⇒ 只退到最小让开量 %.2f 单位 ✗（请人看一眼 ✓）"
                                    % (net, _nm7, _e7[0], _y, FJ_GAP, 2 * MIN_SEG))
                # ★ 端点去重 ✓（收紧后 `_x0r` 就是 `_xs[0]` ✓ ⇒ 老写法会生成**零长段** ✗）
                _path = [(_x0r, _y)]
                for _v9 in list(_xs) + [_x1r]:
                    if abs(_v9 - _path[-1][0]) > 1e-6:
                        _path.append((_v9, _y))
                if len(_path) < 2:
                    continue                       # 只剩一个点 ⇒ 没有轨可画（支线自己就落在轨上 ✓）
                print("   · 轨 y=%.1f ✓：x %.3f → %.3f ✓（%d 个落点 ✓，长 %.1f 单位 = %.1f mm ✓%s）"
                      % (_y, _path[0][0], _path[-1][0], len(_xs),
                         abs(_path[-1][0] - _path[0][0]),
                         abs(_path[-1][0] - _path[0][0]) * 25.4 / 90.0,
                         " ★按落点收紧 ✓" if (_tight and len(_xs) >= 2) else ""))
                for _k in range(len(_path) - 1):
                    used.append((_path[_k], _path[_k + 1], net))
                # ★★★ 2026-09-30 ✓ **把轨在“坐脚点”处切成两段，并记上那只脚** ✓✗（实测踩的 ✓）：
                #   ✗ 老版整条轨是**一段**、`from`/`to` 都是 `None` ✗ ⇒ `--trim` 的“终端分块”
                #     里**看不见坐在轨上的那只脚** ✗（`_term_nodes` 只认 `("pin", 非 None)` ✓）
                #     ⇒ 它把**载着断点的那截轨**当“多余”删掉 ✗ ⇒ 脚又孤零零了 ✗
                #     （实测：`C2.connector0` 明明已经坐在 5V 轨上 ✓，收尾一剪 ⇒ **全表 44 根线里
                #      一次都不出现** ✗✗；而图上它正压在轨线上 ✓ ⇒ 肉眼像接上了 ✓ ⇒ 七道闸门全过 ✗）。
                #   ✓ 现在：轨在**每只坐脚**处断开 ✓，断点两侧的两段各把那只脚记成 `to`/`from` ✓
                #     ⇒ ① 连接**显式** ✓ ② `--trim` 看得见这个终端 ✓ 不敢删 ✓
                #     ③ `check_netlist` / 假连线判据也看得见 ✓。
                _sits_here = {}
                for (_x7, _r7, _c7, _y7) in _sit:
                    if abs(_y7 - _y) < 0.6:
                        _sits_here[round(_x7, 4)] = (_r7, _c7)
                _idx = [0]
                for _k8 in range(1, len(_path) - 1):
                    if round(_path[_k8][0], 4) in _sits_here:
                        _idx.append(_k8)
                _idx.append(len(_path) - 1)
                for _i8 in range(len(_idx) - 1):
                    _p8 = _path[_idx[_i8]:_idx[_i8 + 1] + 1]
                    if len(_p8) < 2:
                        continue
                    _s8 = _sits_here.get(round(_p8[0][0], 4))
                    _e8 = _sits_here.get(round(_p8[-1][0], 4))
                    segs.append({"a": _p8[0], "b": _p8[-1], "path": _p8,
                                 "from": ({"ref": _s8[0], "cid": _s8[1]} if _s8 else None),
                                 "to": ({"ref": _e8[0], "cid": _e8[1]} if _e8 else None),
                                 "mine": set(), "own_pins": set(),
                                 "net": net, "key": None, "fixed": True})
                _drawn.append(_y)
                _rx[_y] = _x0r

            # ★★★ 同网的多条轨**必须互连** ✗（2026-09-28 ✓ 实测真断点 ✓）：
            #   **导线是导体 ⇒ 只有接上才算同一个网** ✓；两条平行的轨**不会自动通** ✗。
            #   ✗ 实测：GND 上轨（6 只脚 ✓）与下轨（3 只脚 ✓）**分成两个连通分量** ✗ ⇒
            #     而 Fritzing 底部**看不出** ✗（它只数"每条连接有没有导线"✗ ⇒ 用户原话
            #     "**只管接全没有、不管接对没有**"✓）。
            #   ★ 形状（2026-09-28 修订 ✓）：两轨端点**已经对齐**（同一对 min/max ✓）
            #     ⇒ **一根竖线**即可 ✓ ⇒ 竖线两端**分别落在两条轨的端点上** ✓（重合 ✓）
            #     ⇒ **不留悬空线头** ✓（这是"飞线"的关键 ✓ —— 见上面那条注释 ✓）。
            if len(_drawn) > 1 and net in ISLAND_NETS:
                # ★★★ 2026-10-04 ✓ **允许分岛** ✓（用户 2026-10-04 定 ✓，原话「**左边的地线轨删除了，
                #   补上右边轨就行了，逻辑太僵硬了**」✓）——
                #   ✗ 我原来把“**原理图里两条平行轨必须用一根导线接起来**”当硬约束 ✗
                #     ⇒ 于是被迫画那根 235.8 单位（66.9mm ✗）的互连 ✗（用户：**逻辑太僵硬** ✓）。
                #   ✓ 而 **Fritzing 的网是跨视图算的** ✓（本仓早先实测 ✓）⇒ 岛的连续性由
                #     **面包板 GND 轨 / PCB** 提供 ✓ ⇒ 原理图里**允许分岛** ✓。
                #   ★ 如实报数 ✓（不静默 ✗）：本网原理图里有几段轨 ⇒ 就是几个岛 ✓。
                print("   ⊘ **`--islands`** ✓：网 `%s` **不画轨间互连** ✗ ⇒ 原理图里分成 **%d 个岛** ✓"
                      "（各段轨 y %s ✓）—— 连续性由**别的视图**（面包板/PCB ✓）提供 ✓"
                      % (net, len(_drawn), "/".join("%.1f" % _y for _y in sorted(_drawn))))
            elif len(_drawn) > 1:
                # ★ 合并时**在每条被截支线的脚行处打断** ✓ ⇒ 支线端点与它**端点对端点**对上 ✓
                _vp = [(_vx, _y) for _y in sorted(set(_drawn) | set(_split_ys))]
                for _k in range(len(_vp) - 1):
                    used.append((_vp[_k], _vp[_k + 1], net))
                segs.append({"a": _vp[0], "b": _vp[-1], "path": _vp,
                             "from": None, "to": None, "mine": set(), "own_pins": set(),
                             "net": net, "key": None, "fixed": True})
                print("   ★ 同网两条轨**互连** ✓：竖线 x=%.3f ✓（y %.1f → %.1f ✓）"
                      "—— 不连就是**两个网** ✗（Fritzing 底部**看不出** ✗）"
                      % (_vx, min(_drawn), max(_drawn)))
        for _tr2 in _vtrunks:
            segs.append({"a": _tr2[0], "b": _tr2[-1], "path": list(_tr2),
                         "from": None, "to": None, "mine": set(), "own_pins": set(),
                         "net": net, "key": None, "fixed": True})
            print("   ★ **竖直干线** ✓：x=%.3f ✓，y %.1f → %.1f ✓（%d 段 ✓；端点在落点上 ✓ "
                  "⇒ 支线与它**端点对端点** ✓；就算支线拐过了头，收尾那条「压中段」也会补上接头 ✓）"
                  % (_tr2[0][0], _tr2[0][1], _tr2[-1][1], len(_tr2) - 1))
        nets_segs[net] = segs
        print("网 %-9s %d 个脚 → %d 段（弯 %d）"
              % (net, len(pts), len(segs), sum(bends(s["path"]) for s in segs)))

    # ── ★★ 抽出重排 ✓（2026-09-27 ✓，面包板验证过的那一步 ✓）──
    #   ★ 要治的病 ✓：贪婪布线下**先布的线占住了走廊** ✗，后布的看不见“未来的线” ✗ ⇒
    #     重叠/交叉/贴脚怎么罚都降不到 0 ✗（实测：罚、禁、加密走廊三种都试过 ✓ 无效 ✗）。
    #   ★ 做法 ✓：把每段**抽出来**（从 `used` 里摘掉 ✓）⇒ 此刻它“**看得见其它所有线**” ✓
    #     再算一遍 ✓；用**同一套代价**与旧路径比 ✓（`route_pair` 一份实现 ✓）⇒
    #     只留**更优**的 ✓ —— 所以这是**单调改进** ✓，不会越改越差 ✓。
    #   ★ 配参一致 ✓（面包板踩过的坑 ✗：旧路径必须用**同一组参数**重算 ✓，
    #     否则会出现“每轮都报有改进、全局一动不动”✗）。
    if RIP_ROUNDS > 0:
        PHASE[0] = "rip"                       # ★ 探针只报首轮 ✓（重排会反复重算 ✓，报了就噪 ✓）
        allseg = [s for net in net_order for s in nets_segs.get(net, [])]

        def gstat(used_list, seg_list):
            r"""**全局**评分 ✓（每轮验收用 ✓）—— 重叠 / 贴脚 / 交叉 / 总长 ✓

            ★ 为什么要这一层 ✗（2026-09-27 ✓）：重排是**逐段**改进的 ✓（只看自己那根 ✓）
              ⇒ 它降交叉时会**让别的线去贴脚** ✗（实测：重叠 6→4 ✓、交叉 15→13 ✓，
              但贴脚 13→**16** ✗）。这就是"局部最优 ≠ 全局最优" ✗。
              ⇒ 每轮结束再算一遍**全局** ✓，**变差就把整轮撤回** ✓。
            ★ 加权和用 `10×重叠 + 贴脚 + 交叉` ✓（权重是我选的 ✓、一行可调 ✓）：
              重叠是用户点名的**硬规则**（"不能重叠" ✓）⇒ 权重最高 ✓；
              贴脚是用户点名的**可读性规则** ✓；交叉是审美头号指标 ✓。
              实测标定 ✓：贪婪版 (重叠6,贴脚13,交叉15) = 88；重排后 (4,16,13) = 69 ✓
              ⇒ 后者更好 ✓ 该接受 ✓（若用"逐项不许变差"就会把它拒掉 ✗ 那反而不对 ✓）。
            """
            ov = 0
            n = len(used_list)
            for i in range(n):
                for j in range(i + 1, n):
                    if SG.near_overlap(used_list[i][0], used_list[i][1],
                                       used_list[j][0], used_list[j][1]):
                        ov += 1
            cr = 0
            for i in range(n):
                for j in range(i + 1, n):
                    if SG.seg_cross(used_list[i][0], used_list[i][1],
                                    used_list[j][0], used_list[j][1]):
                        cr += 1
            pc = 0
            for _u in used_list:                  # ★ 按“段”算 ✓（= 渲染器口径 ✓）
                # ★ 2026-09-28 ✓ 改用 `seg_pin_intr` ✓ —— 与代价 `route_key`、闸门 `HARD_CLEAR`
                #   **同一份判据** ✓（以前这里也抄了一遍 ✓）。
                pc += seg_pin_intr([_u[0], _u[1]])
            ln = sum(plen(s["path"]) for s in seg_list)
            score = (SNAP_WEIGHTS[0] * ov + SNAP_WEIGHTS[1] * pc
                     + SNAP_WEIGHTS[2] * cr)
            return ov, pc, cr, ln, score

        print("── ★★ 抽出重排：%d 段 × %d 轮（每段抽出来、在看得见其它所有线的条件下重算 ✓）"
              % (len(allseg), RIP_ROUNDS))
        g0 = gstat(used, allseg)
        print("   起始全局：重叠 %d ｜ 贴脚 %d ｜ 交叉 %d ｜ 总长 %.1f ｜ 加权分 %.0f ✓"
              % (g0[0], g0[1], g0[2], g0[3], g0[4]))
        for rnd in range(RIP_ROUNDS):
            nimp, ntry = 0, 0
            snap = [(s, list(s["path"])) for s in allseg]
            used_snap = list(used)
            base = gstat(used, allseg)
            for s in allseg:
                if s.get("fixed"):             # ★ 电源轨是**预置**的 ✓ ⇒ 不参与重排 ✗
                    continue
                # ★★ “**脚→轨**”支线也**不参与重排** ✗（2026-09-28 ✓）——
                #   它们刚被 `trim_on_rail` 收拾干净 ✓（截到第一次碰轨 ✓），而重排会
                #   `route_pair(a2, b2, …)` **重算一遍** ✗ ⇒ 又会把支线放回轨上 ✗✗
                #   （实测：重排后再清理一次 = “4 条/2 条”又回来了 ✓）。
                #   ★ 两条代价一起省了 ✓：不用“重排后再清理” ✓、也不用**重建轨** ✓。
                if RAILS and s.get("to") is None:
                    continue
                a2, b2 = s["path"][0], s["path"][-1]
                segl = [(s["path"][k], s["path"][k + 1], s["net"])
                        for k in range(len(s["path"]) - 1)]
                keep = [u for u in used if u not in segl]
                new, nk = route_pair(a2, b2, s["mine"], s["own_pins"], keep, net=s["net"])
                oldk = route_key(s["path"], s["mine"], s["own_pins"], keep)
                ntry += 1
                if new is not None and nk < oldk:
                    s["path"] = new
                    segl = [(new[k], new[k + 1], s["net"]) for k in range(len(new) - 1)]
                    nimp += 1
                used = keep + segl
            now = gstat(used, allseg)
            if now[4] > base[4]:                      # ★ 全局变差 ⇒ **整轮撤回** ✓
                for s, p in snap:
                    s["path"] = p
                used = used_snap
                print("   第 %d 轮：逐段改进 %d 段 ✓，但**全局变差** ⇒ **撤回** ✓"
                      "（重叠/贴脚/交叉 %d/%d/%d → %d/%d/%d；加权 %.0f → %.0f ✗）"
                      % (rnd + 1, nimp, base[0], base[1], base[2],
                         now[0], now[1], now[2], base[4], now[4]))
            else:
                print("   第 %d 轮：接受 ✓ 改进 %d/%d 段 ✓（重叠/贴脚/交叉 %d/%d/%d → %d/%d/%d；"
                      "加权 %.0f → %.0f ✓）"
                      % (rnd + 1, nimp, ntry, base[0], base[1], base[2],
                         now[0], now[1], now[2], base[4], now[4]))

    # ✗ “抽出重排后再清理一次”**已取消** ✓（2026-09-28 ✓）：现在重排**跳过**“脚→轨”支线 ✗
    #   ⇒ 它们自始至终没被改过 ✓ ⇒ 不需要再清 ✓（也就不会因为“落点变了”而要重建轨 ✓）。

    # ── ★ 规则自检（闸门 ✓）：“**不同的导线不能重叠**” ✓（2026-09-27 用户定 ✓）──
    #   ★★ 次序很重要 ✗（面包板那天的教训 ✓）：**先查“有没有重叠” ✓、再查连通 ✓** ——
    #     反了就会报假通过 ✗（“网连上了”与“两根线叠在一起”是两件事 ✓）。
    ov_pairs = []
    for i2 in range(len(used)):
        for j2 in range(i2 + 1, len(used)):
            if SG.near_overlap(used[i2][0], used[i2][1], used[j2][0], used[j2][1]):
                ov_pairs.append((used[i2], used[j2]))
    print("── ★★ 规则自检：**不同的导线重叠 %d 对** %s（面包板那条同族 ✓：一个孔只能插一根线 ✓）"
          % (len(ov_pairs), "✓✓" if not ov_pairs else "✗✗ 必须 0 ✓"))
    # ★★ 2026-10-03 修 ✗（实测崩过 ✓）：`used` 的元素是**3 元组** `(端点, 端点, 网名)` ✓，
    #   而这里原来写成 `for (p1, q1), (p2, q2) in …` ✗ ⇒ `ValueError: too many values to unpack` ✗✗
    #   ⇒ **崩在报告循环里** ✗ ⇒ 后面的写文件**根本没执行** ✗✗（症状：`--rails` 跑完"没产出" ✗，
    #     而日志最后一行是 `规则自检：不同的导线重叠 1 对` ✓ ⇒ 看起来像"拒写" ✗，其实是崩 ✓）。
    #   ⇒ 顺带把**网名**一起打出来 ✓（一眼看出是哪个网压了哪个网 ✓）。
    for _t1, _t2 in ov_pairs[:6]:
        (p1, q1, n1) = (_t1[0], _t1[1], _t1[2] if len(_t1) > 2 else "?")
        (p2, q2, n2) = (_t2[0], _t2[1], _t2[2] if len(_t2) > 2 else "?")
        print("      ✗ [%s] (%.1f,%.1f)→(%.1f,%.1f) 与 [%s] (%.1f,%.1f)→(%.1f,%.1f) 压在同一条直线上"
              % (n1, p1[0], p1[1], q1[0], q1[1], n2, p2[0], p2[1], q2[0], q2[1]))
    #   ★★ **真闸门** ✓（2026-09-28 ✓ 用户定「要」✓）：这一条是**用户规则②** ✓，可它以前
    #     只是**打印一行** ✗ —— 重叠 1 对时**照写文件、照常退出 0** ✗（实测 `t27_1` ✓）
    #     ⇒ 等于没守 ✗（我因此一度把不合格那版当合格版用 ✓）。
    #   ⇒ 现在：重叠非 0 ⇒ **退出码 = 1** ✓；合格 ⇒ 0 ✓。
    #     ★ 文件**仍然写出** ✓（我们要能打开图看是哪儿压了 ✓）；口径与 `check_fake_wires.py`
    #       「机器守用退出码说话」一致 ✓。
    ov_fail = 1 if ov_pairs else 0
    if ov_fail:
        print("── ★★ ⇒ **退出码 1** ✓（“不同的导线重叠”必须 0 ✓；文件已照常写出 ✓ 供你打开看哪儿压了 ✓）")

    # ── ★ 布完线再重摆位号 ✓（2026-09-27 用户定 ✓）──
    relabel(insts, boxes, used)

    if preview:
        draw_preview(preview, svg, insts, nets_segs, fit)
        print("预览: %s" % preview)
    if warn:
        print("\n⚠ %d 处需要人看：" % len(warn))
        for w in warn:
            print("   " + w)

    if orig[0]:
        emit(sroot, insts, z, nets_segs, orig[0], out_path, PIN_ALL, boxes)
    return ov_fail              # ★ 真闸门 ✓：重叠非 0 ⇒ 退出码 1 ✓（见上面那条自检 ✓）


def fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else ("%.4f" % v)


# ★★★ 2026-09-29 ✓ **NL1：网标签替代长直段** ✓（用户定 ✓，规格来自他手改的 pilot ✓）——
#   · 模板**逐字照抄** Fritzing 自己写出来的那份 ✓（`pixel-schematic-v29_netlabel.fzz` ✓）：
#     `moduleIdRef="NetLabelModuleID"` ✓、`path=":/resources/parts/core/netlabel.fzp"` ✓、
#     `<property name="label">` ＋ `<title>` **都**写网名 ✓（Fritzing 显示用前者 ✓、判定器用后者 ✓）、
#     三个视图 ✓（原理图里那个带 `transform` ✓）。
#   · **锚点 = 引脚 − (0, 4.5)** ✓ —— 实测两个样本都是 `(0, +4.5)` 单位 ✓（`m31` 分别是
#     `12.5219` / `18.2055` ✗ **不影响** ✓）⇒ 这条是**量出来的**，不是我推的 ✓。
# ★ 几何（`geometry` 写多少 / `transform` 写什么 / 本体框多大）**全在 `sch_net.py`** ✓
#   —— **一处实现** ✓，常数全是**实测**的 ✓（见那边的「本体几何」一节 ✓）；
#   ✗ 这里**不再自己拼变换** ✗ —— 原来那个 `_LBL_ATTR` 是把 v29 里**某个位置的标签**的
#   `m31/m32` **逐字抄**过来 ✗ ⇒ 换个位置就摆错 ✗（实测教训 ✓：Fritzing 画图**不用**
#   `m31/m32` ✗，它**绕板心**转 ✓）。
_LBL_MIN_GAP = 14.4        # 切掉的空档至少 **2 格** ✓（1 格 = 7.2 单位 ✓）——
#   ★ 为什么不用更大 ✗：✗ 第一版取 36（5 格）⇒ 实测**一个候选都没有** ✓（上轨各落点之间
#     平均才 ~30 ✓）⇒ 规则等于不存在 ✗。标签**本体本来就在断口外侧** ✓ ⇒
#     断口只要**看得清是两截**（≥ CLEAR_PIN = 7.2 ✓）就够了 ✓。


def fmt4(v):
    """矩阵/小位移用 **4 位** ✓（`fmt` 是 2 位 ✓ ⇒ 写 `m31/m32` 精度不够 ✗）"""
    s = "%.4f" % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def build_label(net, pin_pt, mi, direction="right", rot=0):
    """造一个**核心库网标签**实例 ✓ —— **画出来的脚**正落在 `pin_pt` 上 ✓

    ★ 几何一律问 `sch_net` ✓（实测口径 ✓）：
      `geometry = sch_net.label_geom(pin_pt, net, R)` ✓（**反解** ✓）
      `transform = [R | (I−R)·C]` ✓（Fritzing 自己就是这么写的 ✓ 见 `sch_net.canonical_d` ✓）
    """
    _m = sch_net.MATRIX[rot]
    gx, gy = sch_net.label_geom(pin_pt, net, _m, go_left=(direction == "left"))
    _d = sch_net.canonical_d(net, _m)
    _tf = ('m11="%s" m12="%s" m13="0" m21="%s" m22="%s" m23="0" '
           'm31="%s" m32="%s" m33="1"'
           % (fmt4(_m[0]), fmt4(_m[1]), fmt4(_m[2]), fmt4(_m[3]),
              fmt4(_d[0]), fmt4(_d[1])))
    return ET.fromstring(
        '<instance moduleIdRef="NetLabelModuleID" modelIndex="%s" '
        'path=":/resources/parts/core/netlabel.fzp">'
        '<property name="label" value="%s"/><property name="direction" value="%s"/>'
        "<title>%s</title><views>"
        '<breadboardView layer="schematic"><geometry z="3.50007" x="%s" y="%s"/></breadboardView>'
        '<pcbView layer="schematic"><geometry z="3.50007" x="%s" y="%s"/></pcbView>'
        '<schematicView layer="schematic">'
        '<geometry z="2.50025" x="%s" y="%s"><transform %s/></geometry>'
        "</schematicView></views></instance>"
        % (mi, net, direction, net, fmt(gx), fmt(gy), fmt(gx), fmt(gy), fmt(gx), fmt(gy), _tf))


def build_ground(mi, idx, pin_pt):
    """造一个**核心库接地符号**实例 ✓ —— **画出来的脚**正落在 `pin_pt` 上 ✓

    ★ 模板**逐字照抄** Fritzing 自己写出来的那份 ✓（`_work/v32.fzz` 的 `Ground1` ✓）：
      `moduleIdRef="GroundModuleID"` ✓、`path=":/resources/parts/core/ground.fzp"` ✓、
      `<property name="voltage" value="0"/>` ✓、`<title>Ground%d</title>` ✓、
      `schematicView/geometry z="3.00063"` ✓（**没有 `transform`** ✓ —— 用户那份就是不旋转的 ✓）。
      ★ `<connectors>` 不在这里写 ✓：后面的“两侧各记一份连接”统一写 ✓
        （它建的连接器 `layer` = 视图的 `layer` = `schematic` ✓，与 v32 逐字一致 ✓）。
    ★ 几何一律问 `sch_net` ✓（**反解** ✓）：`geometry = sch_net.ground_geom(pin_pt)` ✓
      （实测互逆 ✓：`(210.578,27.0)` → `(201.5770,26.4044)` = v32 的 `Ground1` 逐位相同 ✓✓）
    """
    gx, gy = sch_net.ground_geom(pin_pt)
    return ET.fromstring(
        '<instance moduleIdRef="GroundModuleID" modelIndex="%s" '
        'path=":/resources/parts/core/ground.fzp">'
        '<property name="voltage" value="0"/><title>Ground%d</title><views>'
        '<schematicView layer="schematic">'
        '<geometry z="3.00063" x="%s" y="%s"/></schematicView>'
        '<breadboardView layer="schematic">'
        '<geometry z="3.00063" x="%s" y="%s"/></breadboardView>'
        '<pcbView layer="schematic">'
        '<geometry z="3.00063" x="%s" y="%s"/></pcbView>'
        "</views></instance>"
        % (mi, idx, fmt(gx), fmt(gy), fmt(gx), fmt(gy), fmt(gx), fmt(gy)))


# ══════════════════════════════════════════════════════════════════════════════
# ★★★ 2026-09-30 ✓ **`--trim=<网>`：剪掉电 / 地网里多余的线 ＋ 把支线改接到更省的点** ✓
#   —— 用户原话 ✓：「**检查每根 5V 和 GND 接线，如果删除不影响网的连通，就删除；
#      如果有更好的连接点可以不违反任何规则又节省线长，就更改接线。**」✓
#
# ★★ “多余”的判据 = **终端分块不变** ✓（终端 = 脚 / 网标签脚 / 接地符号脚 ✓）：
#   删掉一根线之后，**每个终端各自所在的那一块必须一模一样** ✓ —— 比“整张网还连通”更严 ✓，
#   它同时挡住两种坏结果 ✗：① 把 `NL2` 切开的两个模块**又接回去** ✗；② 把某个终端**甩掉** ✗。
# ★★ “更好的连接点”的判据 = **不违反任何规则 ＋ 加权更省** ✓：
#   · 规则 ✓：同一根线**压线** ✗、蹭到不相连的脚（< `CLEAR_PIN` ✗）、**穿元件本体** ✗、
#     压**已放好的标签/接地符号** ✗、**跨网假接头**（顶点搭在别的网的线上 ✗）、**跑出画布** ✗；
#   · 加权 ✓：`长度 + K × 交集` —— **K 就借布线那个 `K_INTER`** ✓（= 10mm/交集 ✓ = AGENTS §5b ⑧）
#     ⇒ **同一个目标函数、同一个系数** ✓，不新造第二把尺子 ✓（这是“不许自证”那条的反向应用：
#       既然是同一件事，就该同一份口径 ✓）。
# ★ 必须守的形状 ✓：**不许产生悬空线端** ✗（删/改完，某个结点上只剩一根线 ⇒ 那个端就悬空了 ✗
#   ⇒ 该改动不成立 ✓）—— 悬空端正是 v29 起就有的那个毛病 ✗，只许减、不许增 ✓。
# ★ **默认空** ✓ ⇒ 不给开关**一字节不差** ✓（与 `--label` / `--ground` 同一条纪律 ✓）。
TRIM_NETS = set()
K_TRIM = K_INTER          # 与布线同一个 K ✓（10mm/交集 ✓）


def _rk(p, nd=3):
    """点 → 可哈希的规范键 ✓（容差 1e-3 单位 = 0.0003mm ✓，与 `LANE_EPS` 同一档 ✓）"""
    return (round(p[0], nd), round(p[1], nd))


def _part_of(edges, pts, merge=()):
    """终端分块的**规范键** ✓（并查集 → 排序后的分块 ✓）：两次算出来一样才算“没变” ✓

    ★ `merge` ✓（2026-09-30 ✓）：**同名网标签 / 接地符号的脚先并起来** ✓ —— 这是 Fritzing 自己
      的语义 ✓（`LocalGrounds` 把全图地脚拉成一张网 ✓、同名标签即同网 ✓ 见 `sch_net.py` ✓）。
      ✗ 不并就会把“用户手改版删掉 GND 左侧回路”判成**改变分块** ✗ —— 实测那个回路是
      那三个脚（`D3.c0/c1` + `C1.c1`）**唯一**的线路径 ✗，但它们与另一侧**靠两个接地符号同网** ✓
      ⇒ 电气上并没断 ✓（`check_netlist.py` 也照这个语义判 ✓ ⇒ 它的网表是全对的 ✓）。
    """
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    _grp = {}
    for (p, g) in merge:                       # ★ 先按“名字”并 ✓（组内所有点两两连通 ✓）
        _grp.setdefault(g, []).append(p)
    for _pts in _grp.values():
        for _q in _pts[1:]:
            ra, rb = find(_pts[0]), find(_q)
            if ra != rb:
                par[rb] = ra
    for (a, b) in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            par[rb] = ra
    grp = {}
    for p in pts:
        grp.setdefault(find(p), []).append(p)
    return tuple(sorted(tuple(sorted(v)) for v in grp.values()))


def _term_nodes(wires, net):
    """该网上**有终端**的那些点 ✓（脚 / 网标签脚 / 接地符号脚 ✓ —— 都记在 `start_tgt`/`end_tgt` 里 ✓）

    ★★ `t[1] is not None` **必须判** ✗✗（2026-09-30 实测撞上 ✓）：「脚→轨」支线的**远端**会写
      `("pin", s["to"])`，而 `s["to"]` 是 `None` ✗ ⇒ 那个元组是 `("pin", None)` ⇒
      **它非空 ⇒ 真值 ⇒ 被当成一只终端** ✗ ⇒ 实测 5V 报出 **10 个终端**（5 只真脚 + 5 个假的轨结点 ✗）、
      而且连**轨的中间段**都被当成“支线”去改接 ✗ ⇒ 兜底一验：把 `U1.VDD` **孤立**了 ✗✗。
      —— 与 `emit()` 里“同点即连”那条笔记是**同一个坑** ✓（那边写的是
      `_live1 = t1 is not None and t1[1] is not None` ✓）；那边逃过了、这边又踩了 ✗ ⇒
      **“`("pin", None)` 是裸端点”这件事实只有一处说得清** ✓ ⇒ 以后凡是读 `start_tgt`/`end_tgt`
      的地方，一律这么判 ✓。
    """
    out = set()
    for w in wires:
        if w.get("net") != net:
            continue
        for tk, e in (("start_tgt", w["p"]), ("end_tgt", w["q"])):
            t = w.get(tk)
            if t and t[0] == "pin" and t[1] is not None:
                out.add(_rk(e))
    return out


def _paths_to(a, b):
    """两点之间的候选走法 ✓：直线（对齐时 ✓）＋ 两种 L ✓ —— **只给正交形状** ✓"""
    if abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6:
        return [[a, b]]
    return [[a, (a[0], b[1]), b], [a, (b[0], a[1]), b]]


def dead_end_pin(wires, start, stop, terms, eps=0.05):
    r"""从 `start`（标签**原来**贴的那个断口 ✓）沿导线往外走 ⇒ 会不会走到一只**真脚**上 ✗

    ★ 为什么需要 ✓（2026-09-30 ✓ 实测踩的坑 ✓）：`③` 把标签挪到“本侧引脚旁边”之后 ✓
      原来通到断口的那一截就成断头 ✓ ⇒ 要清掉 ✓。**但**如果那一截的**尽头是一只真脚**
      （实测：`RC` 的断口 → 两根线 → **`R1` 的脚** ✓）⇒ 清掉就把那只脚**孤立**了 ✗✗
      （它的整张网就只剩它自己 ✗）；而**留着**又会在断口处留一个悬空端 ✗
      ⇒ 两个都不行 ⇒ 正确结论是：**这一侧不许挪** ✓（标签留在断口上 ✓）。
    ★ 走法 ✓：只沿**度 ≤ 2** 的结点走 ✓（碰到分叉点 = 那一支是纯断头 ✓ 丢它是安全的 ✓）；
      走到 **`stop`**（= 候选那个结点 ✓）就停 ⇒ **它外面那截还挂在标签上** ✓ 安全 ✓
      （✗ 不设 `stop` 就会把“标签顺着同一条链挪近一点”也误判成危险 ✗）。
    ★ 返回：危险那只脚的结点键 ✓（安全则 `None` ✓）—— 调用方拿它**否掉这个候选** ✓。
    """
    cur = _rk(start)
    seen = set()
    for _ in range(400):
        if cur == _rk(stop):
            return None
        if cur in terms:
            return cur
        ends = [e for w in wires for e in (w["p"], w["q"]) if _rk(e) == cur]
        if len(ends) >= 3:                      # 分叉点 ⇒ 丢这一支不动别人 ✓
            return None
        nxt = None
        for w in wires:
            for e, o in ((w["p"], w["q"]), (w["q"], w["p"])):
                if _rk(e) != cur:
                    continue
                k = str(w.get("mi"))
                if k in seen:
                    continue
                seen.add(k)
                nxt = _rk(o)
        if nxt is None:
            return None                         # 光秃端 ⇒ 纯断头 ✓
        cur = nxt
    return cur


def prune_dangling(wires, pin_all, eps=0.05, rounds=500):
    r"""把**悬空线端**级联清掉 ✓ ⇒ 返回要删的 mi 集合 ✓（判据 = **叶子** ✓）

    ★ 为什么安全 ✓：“**一端悬空**（那一端上没有别的线端、也没有终端）”的线 = **死头** ✓
      ⇒ 删它**不会动任何端子之间的连通** ✓（另一头就算有脚 ✓，那个脚也不靠它连别人 ✓）
      ⇒ 与 `--trim` 里那步（带终端分块校验 ✓）是**同一套几何** ✓，只是这里不必再验一次 ✓。
    ★ 什么时候用 ✓：**标签从断口挪到本侧引脚旁**之后 ✓，原来通到断口的那一截就成了死头 ✗
      ⇒ 不刷掉就是白留一根断线 ✗（实测：`RC` 的 A 侧那一截 = 133.7 单位 ✗）。
    """
    terms = set()
    for w in wires:
        for tk, e in (("start_tgt", w["p"]), ("end_tgt", w["q"])):
            t = w.get(tk)
            if t and t[1] is not None and t[0] in ("pin", "label"):
                # ★★ 2026-09-30 ✓ **标签的脚也是终端** ✓（“标签是一个元件” ✓ B3.1.1 ✓）——
                #   ✗ 原来只认 `("pin", …)` ✗ ⇒ 给标签新拉的那一截引线（另一头 = 标签 ✓）
                #   被当成“悬空叶子”**删掉** ✗✗ ⇒ 实测 `v36` 里那只 `RC` 标签
                #   **浮空 11.5 单位** ✗（五道判据全绿也没发现 ✗ —— 靠 `_scratch/lbl_touch.py`
                #   独立量出来的 ✓）。
                terms.add(_rk(e))
    out = set()
    for _ in range(rounds):
        live = [w for w in wires if str(w["mi"]) not in out]
        deg = {}
        for v in live:
            for q in (v["p"], v["q"]):
                deg[_rk(q)] = deg.get(_rk(q), 0) + 1
        cand = None
        for v in live:
            # ★★ 2026-09-30 ✓ **挂着真终端的线一律不删** ✗（实测踩的坑 ✓）：级联清断头时
            #   把 `R1` 那只脚**唯一的那根线**也吃了 ✗ ⇒ 脚被孤立 ✗、标签浮空 ✗
            #   （五道判据都没拦住 ✗ ⇒ 靠 `_scratch/lbl_touch.py` 独立量出来的 ✓）。
            #   真终端 = `("pin", 非 None)` ✓ / `("label", …)` ✓；`("pin", None)` 是裸端点 ✗ 不算 ✓。
            _has_term = False
            for _tk in ("start_tgt", "end_tgt"):
                _t = v.get(_tk)
                if _t and _t[1] is not None and _t[0] in ("pin", "label"):
                    _has_term = True
            if _has_term:
                continue
            for e in (v["p"], v["q"]):
                k = _rk(e)
                if k not in terms and deg.get(k) == 1:
                    cand = v
                    break
            if cand is not None:
                break
        if cand is None:
            break
        out.add(str(cand["mi"]))
    return out


def trim_plan(net, wires, boxes, other_boxes, pin_all, K=K_INTER, eps=0.05, merge=()):
    r"""**只算不动** ✓ ⇒ `(要删的 mi 集合, [(新路径, 终端在路径哪一端, 那个 pin 目标)], 报告行)` ✓

    ★★ 三件事 ✓（**2026-09-30 第二版** ✓ —— 三处都是**从用户手改版学来的** ✓：他把总长
      从 2421.7 压到 1934.8 单位（**−486.9 = −137.4mm** ✓）而**规则一条没破** ✓
      ⇒ 说明我原来那三处口径**不够** ✓）：
      ① **成组删** ✓：✗ 原来逐根试、还要求“每删一根都不留悬空端” ✗ ⇒ 找不到“**一整块回路**
         一起删” ✓（他删掉 GND 左侧回路 **3 根 / 302.6 单位** ✓ —— 单删任何一根都会先留下
         悬空端 ✗）⇒ 现在：**允许中途留悬空端** ✓，删完再**级联清理**悬空端 ✓
         （每次删除都单独验终端分块 ✓、清理时也验 ✓；收尾再整体验一遍 ✓）。
      ② **支线 = 整条** ✓：✗ 原来拿“**新整条路径**的长度”比“**旧路径里带脚的那一片**” ✗
         ⇒ 实测把他那个改接（135.2 → 79.2 ✓ 省 56 ✓）**误判成更贵** ✗（79.2 ≥ 34.4 ✗）⇒ 拒了 ✗。
         现在：**沿“度 2 的结点”串出整条支线**（脚 → 第一个分叉点 ✓）⇒ 拿**整条**比 ✓。
      ③ **规则优先** ✓：接受条件 = **`(违例数, 价)` 字典序更小** ✓ ⇒ 正是用户原话
         “**不违反任何规则 ＋ 节省线长**” ✓；违例数**更少**时允许**略长** ✓
         （实测：他那根被删的竖线**正贴着 `RC` 标签** ✗ —— 消掉它比省几单位更重要 ✓）。
    """
    mine = [w for w in wires if w.get("net") == net]
    rep = []
    if len(mine) < 3:
        rep.append("   · 网 `%s` 只有 %d 根线 ⇒ 不动 ✓" % (net, len(mine)))
        return set(), [], rep
    _xs = [q[0] for w in wires for q in (w["p"], w["q"])]
    _ys = [q[1] for w in wires for q in (w["p"], w["q"])]
    ubox = (min(_xs), min(_ys), max(_xs), max(_ys))
    terms = _term_nodes(wires, net)
    live = {w["mi"]: {"w": w, "mi": w["mi"], "path": [w["p"], w["q"]]} for w in mine}
    tgt = {}
    for w in mine:
        for tk, side in (("start_tgt", "p"), ("end_tgt", "q")):
            t = w.get(tk)
            if t and t[0] == "pin" and t[1] is not None:      # ★ 同上 ✓：`("pin", None)` 不算 ✓
                tgt[w["mi"]] = side
    base = _part_of([(_rk(v["path"][0]), _rk(v["path"][-1])) for v in live.values()], terms,
                    merge=[(_rk(p), g) for (p, g) in merge])
    print("   ── **`--trim`** ✓：网 `%s` ｜ %d 根线 ｜ 终端 %d 个 ｜ 分块 %d 块 ｜ 现长 %.1f 单位"
          % (net, len(mine), len(terms), len(base),
             sum(math.dist(v["path"][0], v["path"][-1]) for v in live.values())))

    def _live(exc=()):
        return [v for k, v in live.items() if k not in exc]

    def _mik(s):
        """排序键 ✓（改接时造的伪结点名不是数字 ⇒ 排到末尾 ✓）"""
        return int(s) if str(s).isdigit() else 10 ** 9

    def _part(live_):
        return _part_of([(_rk(v["path"][0]), _rk(v["path"][-1])) for v in live_], terms,
                        merge=[(_rk(p), g) for (p, g) in merge])

    def _deg(live_, k):
        return sum(1 for v in live_ for q in (v["path"][0], v["path"][-1]) if _rk(q) == k)

    def _bare_ends(live_):
        """**悬空线端**所在的线 ✓（一端的结点上只有它自己、而且那儿没有终端 ✓）"""
        return sorted({v["mi"] for v in live_
                       for e in (v["path"][0], v["path"][-1])
                       if _rk(e) not in terms and _deg(live_, _rk(e)) == 1},
                      key=lambda s: int(s))

    # ── ① 删冗余 ✓（**成组** ✓：中途允许留悬空端 ✗，紧接着**级联清理**收尾 ✓）──
    del_mi = set()
    rounds = 0
    while True:
        rounds += 1
        # ①a 删一根“删了不改终端分块”的线 ✓（**从最长那根开始** ✓ —— 环上先删最长 ⇒ 剩下最短 ✓）
        _pick = None
        _nofail, _first = 0, None
        for w in sorted(_live(del_mi),
                        key=lambda x: (-math.dist(x["path"][0], x["path"][-1]), _mik(x["mi"]))):
            _p2 = _part(_live(del_mi | {w["mi"]}))
            if _p2 == base:
                _pick = w
                break
            _nofail += 1
            if _first is None:
                _first = (w, _p2)
        if _pick is None and _first is not None:
            _w1, _p21 = _first
            rep.append("   · ①a：剩 %d 根**一根都不能删** ✗（删了会改变终端分块 ✓）—— "
                       "最长那根 %s（%.1f 单位 ✓）的后果：分块 %d → %d ｜ 各块大小 %s → %s"
                       % (_nofail, _w1["mi"], math.dist(_w1["path"][0], _w1["path"][-1]),
                          len(base), len(_p21), [len(g) for g in base],
                          [len(g) for g in _p21]))
            for _g in _p21:
                rep.append("        · 分出来的块：%s" % (list(_g),))
        if _pick is None:
            # ①b 没有“环”可删了 ⇒ 清**悬空线端**（叶子 ✓）；清完可能又露出新的环 ⇒ 回到 ①a ✓
            _leaf = next((mi0 for mi0 in _bare_ends(_live(del_mi))
                          if _part(_live(del_mi | {mi0})) == base), None)
            if _leaf is None:
                break
            del_mi.add(_leaf)
            rep.append("   🧹 清理悬空线端：删 %s ✓（那儿没接任何东西 ✓、删了不改终端分块 ✓）"
                       % _leaf)
            continue
        del_mi.add(_pick["mi"])
        rep.append("   ✂ **删掉 %s**（%.1f 单位 ✓）：终端分块不变 ✓（中途的悬空端交给清理 ✓）"
                   % (_pick["mi"], math.dist(_pick["path"][0], _pick["path"][-1])))
    _kept = _live(del_mi)
    if del_mi:
        rep.append("   · ① 小结 ✓：删 **%d 根**（%d 轮 ✓）｜剩 %d 根 / 总长 **%.1f** 单位 ✓ ｜ "
                   "悬空端 %d 个 %s"
                   % (len(del_mi), rounds, len(_kept),
                      sum(math.dist(v["path"][0], v["path"][-1]) for v in _kept),
                      len(_bare_ends(_kept)), "✓" if not _bare_ends(_kept) else "✗（兜底会拦 ✓）"))
    else:
        rep.append("   · ① 小结 ✓：**没有可删的** ✓（本来就无环、无悬空端 ✓）")

    # ── ② 改接点 ✓（**支线 = 整条** ✓：从脚出发、沿“度 2 的结点”串到第一个分叉点 ✓）──
    add = []
    for _mi0 in sorted(tgt, key=_mik):
        if _mi0 in del_mi:
            continue
        _live0 = _live(del_mi)
        w0 = next((v for v in _live0 if v["mi"] == _mi0), None)
        if w0 is None:
            continue
        side = tgt[_mi0]
        A = w0["path"][0] if side == "p" else w0["path"][-1]        # 终端那端 ✓
        Q = w0["path"][-1] if side == "p" else w0["path"][0]         # 另一头 ✓
        chain = [_mi0]
        while True:                                                  # ★ 串出整条支线 ✓
            if _rk(Q) in terms:
                break                                                # 撞上另一个终端 ⇒ 停 ✓
            _inc = [v for v in _live0 if v["mi"] not in chain
                    and any(_rk(q) == _rk(Q) for q in (v["path"][0], v["path"][-1]))]
            if len(_inc) != 1:
                break                                                # 度 ≥3（分叉点 ✓）⇒ 就落在这儿 ✓
            chain.append(_inc[0]["mi"])
            Q = (_inc[0]["path"][0] if _rk(_inc[0]["path"][0]) == _rk(Q)
                 else _inc[0]["path"][-1])
        if _rk(Q) in terms:
            continue                                                 # 两头都是终端 ⇒ 干线 ✓ 不动
        others = [v for v in _live0 if v["mi"] not in chain]
        allw = [x for x in wires if x["mi"] not in del_mi]
        _cur_segs = [(v["path"][0], v["path"][-1]) for v in _live0 if v["mi"] in chain]

        def _ev(segs, ex_pts):
            """`(违例数, 交叉数, 总长)` ✓ —— 现状与候选**同一套口径** ✓（这就是“不违反任何规则”✓）"""
            v, cr, ln = 0, 0, 0.0
            for (a, b) in segs:
                ln += math.dist(a, b)
                for o in others:
                    c, d = o["path"][0], o["path"][-1]
                    if SG.near_overlap(a, b, c, d):
                        v += 1
                    if SG.seg_cross(a, b, c, d):
                        cr += 1
                for b2 in list(boxes.values()) + [x[1] for x in other_boxes]:
                    if b2 and SG.seg_hits_box(a, b, b2):
                        v += 1
                for (_r, _c, x, y) in pin_all:
                    if any(math.dist((x, y), p) < eps for p in ex_pts):
                        continue                                     # ★ 这一段**自己那两端的脚** ✓
                    if SG.p2seg((x, y), a, b) < CLEAR_PIN:
                        v += 1
                for k2 in (a, b):
                    for o in allw:                                   # ★ 跨网假接头 ✓
                        if o.get("net") == net:
                            continue
                        if SG.p2seg(k2, o["p"], o["q"]) < FJ_GAP:
                            v += 1
                    if not (ubox[0] - OUT_MARGIN <= k2[0] <= ubox[2] + OUT_MARGIN
                            and ubox[1] - OUT_MARGIN <= k2[1] <= ubox[3] + OUT_MARGIN):
                        v += 1                                       # ★ 别跑出画布 ✓
            return v, cr, ln

        _cur_v, _cur_cr, _cur_ln = _ev(_cur_segs, (A, Q))
        cur = _cur_ln + K * _cur_cr
        cand = sorted({_rk(q) for v in others for q in (v["path"][0], v["path"][-1])}
                      - {_rk(A), _rk(Q)} - terms)
        best = None
        for k in cand:
            for path in _paths_to(A, k):
                segs = [(path[j], path[j + 1]) for j in range(len(path) - 1)]
                v2, cr2, ln2 = _ev(segs, (A, path[-1]))
                if v2:
                    continue
                c2 = ln2 + K * cr2
                if best is None or (c2, cr2, ln2) < (best[0], best[1], best[2]):
                    best = (c2, cr2, ln2, path, k, v2)
        if best is None:
            rep.append("   ⊘ 不改 %s（整条支线 %.1f 单位 ✓）：%d 个候选结点里**没有一个不违例**的 ✗"
                       "（口径 = 压线 / 交叉 / 蹭脚 / 穿体 / 压标签 / 跨网假接头 / 出界 ✓）"
                       % (chain[-1], _cur_ln, len(cand)))
            continue
        if (best[5], best[0]) < (_cur_v, cur - 1e-6):
            _p = best[3]
            # ★ `w0` 是**包装层** ✗（`{"w": 真线, "mi": …, "path": …}` ✓）⇒ 取目标要 `w0["w"]` ✓
            #   （✗ 写成 `w0.get("start_tgt")` ⇒ 拿到 `None` ✗ ⇒ 新线**没有连接** ✗ ⇒ 实测 `(B)=1` ✗）
            add.append((_p, 0 if side == "p" else len(_p) - 1,
                        w0["w"].get("start_tgt") if side == "p" else w0["w"].get("end_tgt"), _mi0))
            for _m2 in chain:                                        # ★ 整条支线都撤掉 ✓
                del_mi.add(_m2)
                live.pop(_m2, None)
            for j in range(len(_p) - 1):
                live["new%d-%d" % (len(add), j)] = {"w": None, "mi": "new%d-%d" % (len(add), j),
                                                  "path": [_p[j], _p[j + 1]]}
            rep.append("   ↪ **改接 %s** ✓：支线 %d 段 %.1f 单位 ⇒ 落到 (%.1f,%.1f) ✓ ｜ "
                       "新路 %d 段 %.1f 单位 ✓ ｜ 交集 %d → %d ✓ ｜ 违例 %d → %d ✓ ｜ 价 %.1f → %.1f ✓"
                       % (_mi0, len(chain), _cur_ln, best[4][0], best[4][1], len(_p) - 1, best[2],
                          _cur_cr, best[1], _cur_v, best[5], cur, best[0]))
        else:
            rep.append("   ⊘ 不改 %s：整条支线 %.1f 单位 ⇒ 改到最近的结点也只到 %.1f ✗"
                       "（%d 个候选里没有更省的 ✓；违例 %d → %d ✓）"
                       % (_mi0, _cur_ln, best[0], len(cand), _cur_v, best[5]))

    # ── ③ 兜底：整体再验一遍 **终端分块 ＋ 悬空线端** ✓（任一变了就**全撤** ✗ —— 宁可不动 ✓）──
    final = _live(del_mi)
    for (_p, _ti, _pt, _mi0) in add:
        for j in range(len(_p) - 1):
            final.append({"mi": "new%s-%d" % (_mi0, j), "path": [_p[j], _p[j + 1]]})
    _fbare = _bare_ends(final)
    if _part(final) != base or _fbare:
        rep.append("   ✗ **兜底否决**：这套改动整体会%s ✗ ⇒ **全部撤回** ✓（宁缺勿错 ✓）"
                   % ("改变终端分块" if _part(final) != base else
                      "留下悬空线端 %s" % _fbare))
        if _part(final) != base:
            rep.append("      · 终端点 %d 个：%s" % (len(terms), sorted(terms)))
            rep.append("      · 撤前分块 %s" % (base,))
            rep.append("      · 改后分块 %s" % (_part(final),))
        return set(), [], rep
    if not del_mi:
        rep.append("   · 结论：**没有可删/可改的** ✓（本来就不冗余 ✓）")
    else:
        rep.append("   · 结论 ✓：删 **%d 根**、改接 **%d 处** ✓ ｜ 悬空端 0 ✓"
                   % (len(del_mi) - sum(1 for a in add), len(add)))
    return del_mi, [(a[0], a[1], a[2]) for a in add], rep


def ground_spots(net, wires, pin_all, boxes, other_boxes, mod_a, text_boxes=(), gap=GROUND_GAP):
    r"""地网的**挂点候选表** ✓（2026-09-30 ✓）⇒ `[(组, 到该组脚的距, 违例数, d, P, Q, 延长谁, 理由)]`

    ★★ 形态**从用户手改版量的** ✓（`_work/v32.fzz` ✓）：两个接地符号都是**竖着向下挂**出来的
      （`(210.578,17) → (210.578,27)` ✓、`(161.328,143.961) → (161.328,153)` ✓）
      ⇒ 规则：**一律往下挂** ✓（脚在下、图形再往下 ✓ 见 `sch_net.GROUND_ART_BOX` ✓），
      而且**一个功能模块挂一个** ✓（= 他那两个的位置一个在 B 区（`U1`/`LED2` 那一侧 ✓）、
      一个在 A 区（`D3` 那一侧 ✓）✓ —— 与他那两个 `GND` 标签想说的“A/B 各自的地”同一件事 ✓）。

    ★★ 为什么**不能“就挂在切口上”** ✗（v33 第一版就是这么错的 ✗，用户级判断：“线穿过符号” ✗）：
      切口的形状是**固定**的 ✗ —— 实测那个切口 `(−6.22,−72)` 正好是一根**长竖线的顶端** ✗
      ⇒ 往下挂必然让那根线从**符号的三根横线里穿过去** ✗（图上看就是“符号挂在线上、线把符号打穿”✗）。
      ⇒ 所以要在**整张网上挑一个挂得下的点** ✓ —— 这就是本函数干的事 ✓。

    ★ 候选点 = 该网**导线的端点** ✓（免端点检查）；每个点只考虑**往下**的三种距离 ✓。
      · **延长**（`ext` ✓）：P 是某根线的端、那根线**竖直且从上方下来**（`o.y < P.y` ✓）、
        且该端**没有别人**（`end_is_free` ✓）⇒ 把那根线的端搬到 `Q` ✓（= 用户的做法 ✓：
        他手改版里 `90012759` 就是这么向下延长了 10 ✓），**不加新实例** ✓；
      · **加引线**（`ext = None` ✓）：P 是结点/横线的端 ⇒ 从 P 往下一小段新导线 ✓
        （与他 `Ground1` 那根 10 单位引线同理 ✓）—— 电气靠后面的“同点即连” ✓（同网 ✓）。
      ✗ 端点落在**脚**上的候选**直接跳过** ✗（从脚上挂个符号 ⇒ 三通 + 画出来像“脚上长东西”✗）。

    ★ 打分 = **违例数** ✓（越少越好 ✓）：引线压住/交叉别的线 ✓、引线蹭到不相连的脚（< `CLEAR_PIN` ✓）、
      **符号本体框**被线穿 ✓、蹭到脚 ✓、压到元件本体 ✓、压到**元件的位号/参数文字** ✓
      （`text_boxes` ✓ —— 实测漏了它 ✗：v34 第一版把 B 组那个挂在 `C2` 的 `100 nF` 上 ✗，
       图上就是“接地符号横线把 100 划掉”✗）、压到已放好的标签 ✓。
      再取**离本模块那些脚最近**的 ✓（贴着它要接的东西 ✓），最后按枚举次序定序 ✓（可复现 ✓）。
    """
    E = 0.05
    mine = [w for w in wires if w.get("net") == net]
    if not mine:
        return []
    _refs = set()
    for w in mine:
        for t in (w.get("start_tgt"), w.get("end_tgt")):
            if t and t[0] == "pin" and t[1]:
                _refs.add(t[1]["ref"])
    _mk = {}
    for (_r, _c, _x, _y) in pin_all:
        _mk.setdefault(_r, []).append((_x, _y))
    groups = []
    if mod_a:
        _a = sorted(_refs & set(mod_a))
        _b = sorted(_refs - set(mod_a))
        if _a:
            groups.append(("A", [p for r in _a for p in _mk.get(r, [])]))
        if _b:
            groups.append(("B", [p for r in _b for p in _mk.get(r, [])]))
    if not groups:
        groups = [("net", [p for r in sorted(_refs) for p in _mk.get(r, [])])]

    _pin_at = {(round(x, 3), round(y, 3)) for (_r, _c, x, y) in pin_all}
    pts = {}
    for w in mine:
        for e in (w["p"], w["q"]):
            pts.setdefault((round(e[0], 3), round(e[1], 3)), []).append(w)

    out = []
    for _k in sorted(pts):
        P = (_k[0], _k[1])
        if P in _pin_at:
            continue
        ws = pts[_k]
        ext = None
        for w in ws:                          # ★ “竖直 + 从上方下来 + 端上没别人” ⇒ 延长它 ✓
            o = w["q"] if math.dist(w["p"], P) < E else w["p"]
            if abs(o[0] - P[0]) < E and o[1] < P[1] - E and end_is_free(wires, w, P, pin_all):
                ext = w
                break
        for d in (gap, 2 * gap, 3 * gap):
            Q = (P[0], P[1] + d)
            bx = sch_net.ground_box(sch_net.ground_geom(Q))
            v, why = 0, []
            for w2 in wires:
                if w2 is ext:
                    continue                  # ★ 自己要延长的那根不算“被别人穿” ✓
                if SG.near_overlap(P, Q, w2["p"], w2["q"]):
                    v += 1
                    why.append("引线压住 %s" % w2["mi"])
                if SG.seg_cross(P, Q, w2["p"], w2["q"]):
                    v += 1
                    why.append("引线与 %s 交叉" % w2["mi"])
                if SG.seg_hits_box(w2["p"], w2["q"], bx):
                    v += 1
                    why.append("符号被 %s 穿" % w2["mi"])
            for (_r, _c, x, y) in pin_all:
                if SG.p2seg((x, y), P, Q) < CLEAR_PIN:
                    v += 1
                    why.append("引线蹭脚 %s.%s" % (_r, _c))
                if bx[0] < x < bx[2] and bx[1] < y < bx[3]:
                    v += 1
                    why.append("符号压脚 %s.%s" % (_r, _c))
                elif (bx[0] - CLEAR_PIN < x < bx[2] + CLEAR_PIN
                        and bx[1] - CLEAR_PIN < y < bx[3] + CLEAR_PIN):
                    v += 1
                    why.append("符号贴着脚 %s.%s" % (_r, _c))
            for _t, b2 in boxes.items():
                if b2 and _ov2(bx, b2):
                    v += 1
                    why.append("符号压元件 %s" % _t)
            for _t, b2 in text_boxes:
                if _ov2(bx, b2):
                    v += 1
                    why.append("符号压%s 的文字" % _t)
            for _m2, b2 in other_boxes:
                if _ov2(bx, b2):
                    v += 1
                    why.append("符号压已放的标签 %s" % _m2)
            for _g, gpins in groups:
                if not gpins:
                    continue
                dd = min(math.dist(P, gp) for gp in gpins)
                out.append((_g, dd, v, d, P, Q, ext, tuple(why)))
    pick = {}
    for _c in out:                            # ★ 每组取一个 ✓（违例少 → 离本组脚近 → 枚举次序 ✓）
        _g = _c[0]
        if _g not in pick or (_c[2], _c[1]) < (pick[_g][2], pick[_g][1]):
            pick[_g] = _c
    return [pick[g] for g in sorted(pick)]


def cut_at_module_boundary(wires, net, mod_a, eps=1e-3):
    """NL2 ✓：把**跨功能模块**的那一根线挑出来删掉 ✓
       ⇒ 返回 `(要删的 mi 集合, [(断口点, 侧, 长度) × 2])` ✓

    ★ 判据（用户 2026-09-29 定 ✓ ⇒ `fritzing-parts-langhua/docs/schem-drawing-rules.md` **B3.1** ✓）：
      **切点必须落在功能模块的边界上** ✓ —— 删掉它之后，
      「模块 A 的脚」与「模块 B 的脚」**正好**被分开 ✓（两边各自都还连着东西 ✓）。
      ✗ 不许在模块**内部**找个空档切一刀 ✗ —— 那是“剪断再接回去” = **净信息为零** ✗
        （实测 ✓：GND 上轨中间切 135.8 单位 + 2 标签 ⇒ 判据全绿 ✓ 但用户判「**毫无意义**」✗）。
    ★ 只删**自己不连脚**的线 ✓（否则删完就有脚没线 ✗ ⇒ 网表 ✗）。
    ★ 挑**最短**的那一根 ✓（删得越少越好 ✓ —— 目的不是省长度 ✓，是让两个模块各成一块 ✓）。
    """
    _wn = [w for w in wires if w.get("net") == net]
    if len(_wn) < 3:
        return set(), []
    _pins = {}
    for w in _wn:
        _pins[w["mi"]] = [_t[1]["ref"] for _t in (w.get("start_tgt"), w.get("end_tgt"))
                           if _t and _t[1] and _t[1].get("ref")]
    best = None
    for w in _wn:
        if _pins.get(w["mi"]):
            continue                          # ★ 自己不连脚 ✓
        rest = [x for x in _wn if x is not w]
        par = {}

        def _f(x):
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        def _u(x, y):
            _rx, _ry = _f(x), _f(y)
            if _rx != _ry:
                par[_ry] = _rx

        for i in range(len(rest)):            # 用“端点重合”把剩下的线并块 ✓（与写文件同口径 ✓）
            for j in range(i + 1, len(rest)):
                for _e in (rest[i]["p"], rest[i]["q"]):
                    for _f2 in (rest[j]["p"], rest[j]["q"]):
                        if math.dist(_e, _f2) < eps:
                            _u(rest[i]["mi"], rest[j]["mi"])
        grp = {}
        for x in rest:
            grp.setdefault(_f(x["mi"]), []).append(x["mi"])
        if len(grp) != 2:
            continue                          # 分不成就不是模块边界 ✓
        sides = []
        for ms in grp.values():
            _s = set()
            for m in ms:
                for r in (_pins.get(m) or []):
                    _s.add("A" if r in mod_a else "B")
            sides.append(_s)
        if any(len(s) != 1 for s in sides) or sides[0] == sides[1]:
            continue                          # 必须一边全 A、另一边全 B ✓
        _ln = math.dist(w["p"], w["q"])
        if best is None or _ln < best[0]:
            best = (_ln, w)
    if best is None:
        return set(), []
    _ln, w = best
    print("      · NL2 诊断 ✓：网 `%s` 靠删这一根（%.1f 单位 ✓）正好分开 A/B ✓ ｜ 断口 %s ↔ %s ✓"
          % (net, _ln, tuple(w["p"]), tuple(w["q"])))
    return {w["mi"]}, [(w["p"], "L", _ln), (w["q"], "R", _ln)]


def cut_span_for_labels(segs, eps=1e-3, min_gap=_LBL_MIN_GAP):
    """✗ **已废弃** ✗（2026-09-29 用户判定「毫无意义」✓）——它切的是**模块内部**的空档 ✗ ⇒
    “剪断再接回去”= 净信息为零 ✗。口径已改为 `cut_at_module_boundary` ✓（B3.1 ✓）；
    这里只在 **`--modules` 没给** 时才可能被调到 ✓（= 旧行为 ✓，保留只为对照 ✓，下次清代码时删 ✓）。
    """
    return segs, []


def _cut_span_unused(segs, eps=1e-3, min_gap=_LBL_MIN_GAP):
    """NL1 ✓：在这条**长直段**（轨 ✓）上，把**相邻两个落点之间**的那截切掉 ✓
    ⇒ 返回 `(新 segs, [(断口点, 侧, 省下的长度) × 2])` ✓

    ★★ 事实（实测两版才对上 ✓，与“轨是断的”那个**猜测**相反 ✗）：
      轨在 `nets_segs` 里是**一整条** ✓（例：GND 上轨 = 一个段 ✓，path 从 `(-6.22,-72.0)`
      一直到 `(271.96,-72.0)` = **278.2 单位** ✓）；断开成一段段是**后面建链时**才做的 ✓。
      ⇒ ✗ “整条删掉一段”会连**所有支线的落点**一起删 ⇒ 支线全成断头 ✗（实测 ✓）；
      ⇒ ✓ 正解 = **切掉两个相邻落点之间的一截** ✓（那截里**没有**落点 ✓）⇒
        两半各自都还挂着自己的落点 ✓、断口就是那两个落点 ✓、标签贴在那两点上 ✓。

    ★ 三道护栏都**从几何读** ✓（不看标志位 ✓）：
      ① `i ≥ 1` 且 `j ≤ len-2` ✓ ⇒ 两半各自都还剩**至少一个点** ✓；
      ② 两半**各自有正长度** ✓（✗ 实测：一条“脚→落点”的支线，它的两个落点就是首尾 ✗ ⇒
        邻着切会把**整条支线**切光 ⇒ 那半根线被丢 ⇒ 那只脚凭空少一根线 ⇒ **网表 ✗** ✓）；
      ③ 空档 ≥ `min_gap`（2 格 ✓）⇒ 两个断口肉眼分得开 ✓。

    ★★★ 最后定下来的做法 ✓（实测三轮才对 ✓）：**轨在 `nets_segs` 里是一条“光板”直段** ✓——
      GND 上轨 = 一个段 ✓，path 就是 `[(-6.22,-72.0), (271.96,-72.0)]` **两个点** ✓（278.2 单位 ✓），
      而支线的落点（= 别的段的端点 ✓）**落在它的中段上** ✗ —— **不是**它的 path 点 ✓！
      ⇒ ✗ 按“path 上的归属点”去找相邻对，永远只有 `{0, 1}` 两个（= 自己的首尾 ✓）⇒
        **一个候选都没有** ✗（实测两次 ✓）。
      ✓ 所以：**落点从别处的端点算 x** ✓，在轨上**插入**两个断点 ✓ ⇒
        左半 = `[起点 … (x0,y)]` ✓、右半 = `[(x1,y) … 终点]` ✓
        ⇒ 两边各自的落点**全都还在** ✓、断口正好是两个落点 ✓、标签贴那两点 ✓。
    """
    best = None
    for s in segs:
        p = list(s.get("path") or [])
        if len(p) < 2 or s.get("from") or s.get("to"):
            continue                      # 只动“两端都不连脚”的段（= 轨 ✓）
        if not all(abs(q[1] - p[0][1]) < eps for q in p):
            continue                      # 只切**直线**段 ✓（有拐角的先不动 ✓）
        _y = p[0][1]
        _x0, _x1 = min(q[0] for q in p), max(q[0] for q in p)
        xs = set()
        for t in segs:
            if t is s:
                continue
            tp = t.get("path") or []
            if not tp:
                continue
            for e in (tp[0], tp[-1]):
                if abs(e[1] - _y) < eps and _x0 + eps < e[0] < _x1 - eps:
                    xs.add(round(e[0], 4))
        xs = sorted(xs)
        for _k in range(len(xs) - 1):
            g = xs[_k + 1] - xs[_k]
            if g < min_gap:
                continue
            if best is None or g > best[0]:
                best = (g, s, xs[_k], xs[_k + 1], _y)
    if best is None:
        return segs, []
    g, s, xa, xb, y = best
    p = list(s["path"])
    left, right = dict(s), dict(s)
    left["path"] = [q for q in p if q[0] <= xa + eps] + [(xa, y)]
    right["path"] = [(xb, y)] + [q for q in p if q[0] >= xb - eps]
    left["to"], right["from"] = None, None
    print("      · NL1 选段诊断 ✓：轨 y=%.1f ✓ 落点 x：%s ✓ ｜ 切掉 **%.1f 单位** ✓"
          "（x %.1f → %.1f ✓）"
          % (y, ["%.1f" % v for v in (xa, xb)], g, xa, xb))
    return [t for t in segs if t is not s] + [left, right], \
        [((xa, y), "L", g), ((xb, y), "R", g)]


def _cut_span_unused(segs, eps=1e-3, min_gap=_LBL_MIN_GAP):
    best = None
    for s in segs:
        p = list(s.get("path") or [])
        if len(p) < 3:
            continue
        att = set()
        if s.get("from"):
            att.add(0)
        if s.get("to"):
            att.add(len(p) - 1)
        for t in segs:
            if t is s:
                continue
            tp = t.get("path") or []
            if not tp:
                continue
            for k, q in enumerate(p):
                for e in (tp[0], tp[-1]):
                    if abs(q[0] - e[0]) < eps and abs(q[1] - e[1]) < eps:
                        att.add(k)
        _a = sorted(att)
        for _k in range(len(_a) - 1):
            i, j = _a[_k], _a[_k + 1]
            if j <= i + 1:
                continue
            if i < 1 or j > len(p) - 2:
                continue
            if math.dist(p[0], p[i]) < eps or math.dist(p[j], p[-1]) < eps:
                continue
            g = sum(math.dist(p[k], p[k + 1]) for k in range(i, j))
            if g < min_gap:
                continue
            if best is None or g > best[0]:
                best = (g, s, i, j, len(p))
    if best is None:
        return segs, []
    g, s, i, j, _np = best
    p = list(s["path"])
    left, right = dict(s), dict(s)
    left["path"], left["to"] = p[:i + 1], None
    right["path"], right["from"] = p[j:], None
    print("      · NL1 选段诊断 ✓：原 path %d 点 ✓ ｜ 切掉 [%d..%d] = **%.1f 单位** ✓ ｜ "
          "左半 %d 点（%s → %s ✓）｜ 右半 %d 点（%s → %s ✓）"
          % (_np, i, j, g, i + 1, tuple(p[0]), tuple(p[i]),
             len(p) - j, tuple(p[j]), tuple(p[-1])))
    return [t for t in segs if t is not s] + [left, right], \
        [(p[i], "L", g), (p[j], "R", g)]


def build_wire(tmpl, w):
    """克隆模板导线 → 只留 schematicView + 设本段几何 ✓（连接留到后面统一写 ✓）"""
    e = copy.deepcopy(tmpl)
    e.set("modelIndex", w["mi"])
    t = pm.child(e, "title")
    if t is not None:
        t.text = "Wire" + w["mi"]
    vw = pm.child(e, "views")
    for sub in list(vw):
        if not tag(sub) == "schematicView":
            vw.remove(sub)
    sub = pm.child(vw, "schematicView")
    sub.set("layer", "schematicTrace")
    g = pm.child(sub, "geometry")
    if g is None:
        g = ET.SubElement(sub, "geometry")
    dx, dy = w["q"][0] - w["p"][0], w["q"][1] - w["p"][1]
    # ★ wireFlags 是**位标**（`viewgeometry.h:42`）：NoFlag=0, RoutedFlag=2, PCBTraceFlag=4,
    #   ObsoleteJumperFlag=8, RatsnestFlag=16, AutoroutableFlag=32, NormalFlag=64,
    #   **SchematicTraceFlag=128**
    #   原理图导线的 trace flag 就是 128 ✓（`schematicsketchwidget.cpp:358`）；
    #   少了这一位，`modelbase.cpp` 的 `checkOldSchematics()` 会把线当"旧版导线" ⇒
    #   **不算布线** ✗ ⇒ Fritzing 画虚线、状态栏显示"仍有 N 个插接件需要布线" ✗
    #   （2026-09-26 用户截图发现 ✓；模板是面包板导线，它的值是 64 ✗ 不能照抄 ✓）
    g.attrib.update({"x": fmt(w["p"][0]), "y": fmt(w["p"][1]),
                     "x1": "0", "y1": "0", "x2": fmt(dx), "y2": fmt(dy),
                     "wireFlags": "128"})
    we = pm.child(sub, "wireExtras")
    if we is None:
        we = ET.SubElement(sub, "wireExtras")
    # ★ **按网络上色** ✓（2026-09-28 ✓）：色值取原理图官方调色板 ✓（`NET_COLOR` ✓）
    we.attrib.update({"mils": "9.7222",
                      "color": NET_COLOR.get(w.get("net") or "", "#404040"),
                      "opacity": "1", "banded": "0"})
    for boxel in sub.iter():                     # 清掉模板带来的旧连接 ✗
        if tag(boxel) == "connects":
            for c in list(boxel):
                if tag(c) == "connect":
                    boxel.remove(c)
    return e


def add_conn(view, owner_cid, other_cid, other_mi, other_layer, fallback_layer):
    """把一条连接写进**连接器级** ✓（Fritzing 1.0 只读这一份 ✗）"""
    box = None
    for c in view:
        if tag(c) == "connectors":
            box = c
    if box is None:
        box = ET.SubElement(view, "connectors")
    conn = None
    for c in box:
        if tag(c) == "connector" and c.get("connectorId") == owner_cid:
            conn = c
    if conn is None:
        conn = ET.SubElement(box, "connector", {"connectorId": owner_cid,
                                                 "layer": view.get("layer") or fallback_layer})
        ET.SubElement(conn, "geometry", {"x": "0", "y": "0"})
    cs = pm.child(conn, "connects")
    if cs is None:
        cs = ET.SubElement(conn, "connects")
    ET.SubElement(cs, "connect", {"connectorId": other_cid,
                                   "modelIndex": str(other_mi), "layer": other_layer})


def relabel(insts, boxes, used, extra=False):
    r"""★ 布完线再把位号重摆一遍 ✓（2026-09-27 用户定 ✓）

    ★ 为什么要在**线布完之后**摆 ✗：摆位脚本那时候还不知道导线在哪 ✗（导线是后布的 ✓）
      ⇒ 实测总有 **3 处**"位号压导线" ✗。
    ★ 为什么不让**导线**避位号 ✗：试过了 ✓ —— 位号压导线只从 3 降到 2 ✗，
      代价是"压线 8→10、总长 +13" ✗ ⇒ **净亏** ✓（已回退 ✓）。
      正解在这头 ✓：**位号可以自由挪** ✓、导线挪一次要牵动全局 ✗。
    ★ 候选位与摆位脚本**同一套 7 个** ✓（上·左/右/中 ✓、下·左/右 ✓、左/右 ✓）；
      判碰只有 `sch_text.label_bbox` 一个实现 ✓（字宽表唯一 ✓）；
      权重：压**别的元件** 10 ✓、压**导线** 5 ✓、压**已放的位号** 5 ✓。
    ★★ `extra=True` ✓（2026-09-30 用户定 ✓，**只有 `emit()` 里那遍用** ✓）：
      再多一圈候选位（各边**往外再加一格** ✓）—— 实测 `U1` 的 7 个候选位**全被导线占着** ✗
      （它上方正好横着 5V 长轨 ✗，而它的位号本来就在那一行 ✓ ⇒ 一圈之内**无处可去** ✗）
      ⇒ 不给第二圈就只能原地不动 ✗。★ 默认 `False` ✓ ⇒ **摆位那一遍的候选集一字不改** ✓
      （那是与已入库 v29 逐字节相同的回归 ✓，不能动 ✗）。
    """
    items = []
    for t, d in insts.items():
        lab = PR.LAB.get(d["mi"]) or {}
        ln, fs = lab.get("lines") or [], lab.get("fs", 5.0)
        tg = pm.child(d["sub"], "titleGeometry")
        if not ln or tg is None or (tg.get("visible") or "true") == "false":
            continue
        items.append((t, d, tg, ln, fs,
                      max(ST.twidth(s, fs) for s in ln),
                      # ★★★ 2026-09-30 ✓ **盒高要用 `label_bbox` 那一份** ✗✓（用户对整的两把尺子 ✓）：
                      #   ✗ 这里原来写 `fs * len(ln)` ✗（= 纯字高 ✓）⇒ 而渲染器/本文件其他地方
                      #     都用 `ST.label_bbox()` ✓（还把**上下留白**算进去 ✓）⇒ 候选矩形**矮了 4.75 单位** ✗
                      #     ⇒ 实测：`U1` 的位号落在一个“我认为不压 `R1` ✓”而“渲染器说压了” ✗
                      #     的位置上 —— 同一个概念两个口径 ✗（本仓那条老毛病 ✗）。
                      #   ✓ 现在：**就调 `label_bbox` 反推** ✓ ⇒ 两边永远一致 ✓（`label_bbox(x, y-0.25fs, …)`
                      #     的**上缘正好是 y** ✓ ⇒ “盒左上角 = (x, y)” 这个对外语义没变 ✓）。
                      ST.label_bbox(0.0, 0.0, fs, ln)[3] - ST.label_bbox(0.0, 0.0, fs, ln)[1]))

    def score(b, t):
        sc = 0
        for t2, box in boxes.items():
            if t2 != t and box and _ov2(b, box):
                sc += 10
        for _u in used:
            if _seg_in_box(_u[0], _u[1], b):
                sc += 5
        for t2, b2 in placed:
            if _ov2(b, b2):
                sc += 5
        return sc

    # 长位号先放（大的先占位 ✓，与摆位脚本同一策略 ✓）
    items.sort(key=lambda z: -z[5])
    placed, moved, before, after = [], 0, [0, 0, 0], [0, 0, 0]
    for t, d, tg, ln, fs, w, h in items:                     # 先量"现状" ✓
        b = ST.label_bbox(pm.num(tg.get("x")), pm.num(tg.get("y")), fs, ln)
        before[0] += sum(1 for t2, box in boxes.items() if t2 != t and box and _ov2(b, box))
        before[1] += sum(1 for _u in used if _seg_in_box(_u[0], _u[1], b))
        before[2] += sum(1 for _t2, b2 in placed if _ov2(b, b2))
        placed.append((t, b))
    placed = []
    for t, d, tg, ln, fs, w, h in items:
        bx, gap = boxes.get(t), 7.2
        if bx is None:
            continue
        cand = [(bx[0], bx[1] - gap - h), (bx[2] - w, bx[1] - gap - h),
                ((bx[0] + bx[2] - w) / 2.0, bx[1] - gap - h),
                (bx[0], bx[3] + gap), (bx[2] - w, bx[3] + gap),
                (bx[0] - gap - w, bx[1]), (bx[2] + gap, bx[1])]
        if extra:                       # ★ 再往外一圈 ✓（只有 `emit()` 那遍用 ✓，见文档串 ✓）
            g2, g3 = gap + h + gap, gap + w + gap
            cand += [(bx[0], bx[1] - g2 - h), (bx[2] - w, bx[1] - g2 - h),
                     ((bx[0] + bx[2] - w) / 2.0, bx[1] - g2 - h),
                     (bx[0], bx[3] + g2), (bx[2] - w, bx[3] + g2),
                     ((bx[0] + bx[2] - w) / 2.0, bx[3] + g2),
                     (bx[0] - g3 - w, bx[1]), (bx[2] + g3, bx[1])]
        old = ST.label_bbox(pm.num(tg.get("x")), pm.num(tg.get("y")), fs, ln)
        best, bk = None, None
        for x, y in cand:
            b = (x, y, x + w, y + h)
            sc = score(b, t)
            if bk is None or sc < bk:
                best, bk = b, sc
        if best is None:
            continue
        if (abs(best[0] - old[0]) > 0.01 or abs(best[1] - old[1]) > 0.01):
            tg.set("x", fmt(best[0]))
            tg.set("y", fmt(best[1] - 0.25 * fs))            # `label_bbox` 的盒上缘 = y + 0.25fs ✓
            d2 = insts[t]
            tg.set("xOffset", fmt(best[0] - d2["loc"][0]))
            tg.set("yOffset", fmt(best[1] - 0.25 * fs - d2["loc"][1]))
            moved += 1
        placed.append((t, best))
        after[0] += sum(1 for t2, box in boxes.items() if t2 != t and box and _ov2(best, box))
        after[1] += sum(1 for _u in used if _seg_in_box(_u[0], _u[1], best))
        after[2] += sum(1 for _t2, b2 in placed[:-1] if _ov2(best, b2))
    print("── ★ 位号**布完线重摆** ✓：动 %d 个 ✓ ｜ 压元件 %d→%d ✓ ｜ 压导线 %d→%d ✓"
          " ｜ 压位号 %d→%d ✓" % (moved, before[0], after[0], before[1], after[1],
                                  before[2], after[2]))


def _ov2(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _seg_in_box(p, q, b):
    n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
    hit = 0
    for k in range(n + 1):
        tt = k / n
        x, y = p[0] + (q[0] - p[0]) * tt, p[1] + (q[1] - p[1]) * tt
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            hit += 1
            if hit >= 3:                     # ★ 与渲染器的判法一致：≥3 个采样点才算"压到" ✓
                return True
    return False


def end_is_free(wires, w_self, pt, pin_all, eps=0.05):
    r"""这个线端上，**除了它自己**，还有没有**别人的端点 / 脚** ✓（`True` = 没有 ✓）

    ★ 用途（2026-09-29 ✓ 用户定 ✓）：挪标签时**先问这一句** ——
      · **没有**（`True` ✓）⇒ **直接把这根线的线端搬过去** ✓（= 线变长一点 ✓）
        ⇒ 标签脚正落在线端上 ✓、**一根线直通** ✓ ⇒ **不留接缝、不长多余的圆点** ✓；
      · **有**（`False` ✓）⇒ 那个线端是个**真接头**（别人的线端 / 某只脚 ✓）⇒ **动不得** ✗
        ⇒ 照旧**另拉一小段引线** ✓（老接头原地不动 ✓）。

    ★ 为什么这是**判据**、不是两种喜好挑一个 ✗（2026-09-29 实测 ✓）：
      ✗ 原来**一律加引线** ✗ ⇒ 实测 `_work/v30.fzz` 的 `RC` 标签：沿轴左挪 7.2 后，
        在 (46.38,−9.00) 留下一个**纯接缝**（`Wire90012777` 的端 ↔ 引线的端 ✓）⇒
        Fritzing 按「**≥2 个线端 ⇒ 画圆点** ✓」在那儿画了个**小圆点** ✗ ——
        而两根线其实**在同一条直线**上 ✗ ⇒ 这个圆点**不代表任何分叉** ✗（用户当场问
        “为什么要有这个圆点”✓）。
      ✗ 反过来**一律搬线端** ✗ 也错 ✓：那个线端若正落在**别的线端**（或某只脚 ✓）上，
        一搬就把接头扯断 ✗ ⇒ 实测网表 ✗、连通块 9 → 10 ✗（= 现有那段引线代码的出处 ✓）。
      ⇒ 两条路**各对一半** ✓ ⇒ 判据就是这一句：**先问那儿有没有别人** ✓。
    """
    for w in wires:
        if w is w_self:
            continue
        for q in (w["p"], w["q"]):
            if math.dist(q, pt) <= eps:
                return False
    for (_t, _c, _x, _y) in pin_all:
        if math.dist((_x, _y), pt) <= eps:
            return False
    return True


def rail_y_map(ubox):
    r"""电源轨的 y ✓ —— ★ **唯一实现** ✓（主流程与“骑轨预摆位”**共用** ✓）

    ★ 为什么必须共用 ✗（实测教训 ✓）：预摆位要**在布线之前**算出轨的 y ✓
      ⇒ 若在那里**再抄一份公式** ✗ ⇒ 两处一旦不同步 ⇒ **两把尺子** ✗
      ⇒ 摆的轨和画的轨不是同一条 ✗（本仓最贵的那一类错 ✗）。
    口径 ✓：**内**轨（5V ✓，支线短 ✓）离包围盒 `RAIL_MARGIN`（= `CLEAR_PIN` + 1 格 ✓）、
       **外**轨（GND ✓）再隔 `RAIL_GAP`（= 2 格 ✓）⇒ 上、下各两条 ✓（支线就近挑 ✓）。
    """
    _top = ubox[1] - RAIL_MARGIN
    _bot = ubox[3] + RAIL_MARGIN
    return {"5V": [_top, _bot], "GND": [_top - RAIL_GAP, _bot + RAIL_GAP]}


def pin_net_map(insts):
    """脚 → 网 ✓（口径同路由 ✓：`NETS` ✓）"""
    out = {}
    for _net, _ps in NETS.items():
        for _ref, _nm in _ps:
            _cid, _p = pin_of(insts, _ref, _nm)
            if _cid:
                out[(_ref, _cid)] = _net
    return out


def rail_huggers(insts, rail_nets):
    r"""挑“**骑得了轨**”的件 ✓：**每一只脚都在轨网上** ✓（≥2 只脚 ✓）

    ★ 为什么只挑这种 ✓：一只脚在轨网、另一只在信号网上（如 `C1` = RC + GND ✓）**骑不了** ✗ ——
      另一只脚必须走信号路径 ✓ ⇒ 挪得再贴也只是把信号线拉长 ✗。
    """
    m = pin_net_map(insts)
    out = []
    for _t, d in sorted(insts.items()):
        if "breadboard" in _t.lower() or "breadboard" in (d.get("mid") or "").lower():
            continue
        _pl = [(c, p) for c, p in sorted((d.get("pins") or {}).items())]
        if len(_pl) < 2 or not d.get("box"):
            continue
        _nets = {m.get((_t, c)) for c, _p in _pl}
        if None in _nets or any(n not in rail_nets for n in _nets):
            continue
        out.append((_t, _pl, d))
    return out


def rail_hug_place(insts, hug, ry):
    r"""把骑轨件**就地**摆到轨上 ✓（改 `loc` / `pins` / `box` ＋ XML 几何 ✓）——★ **在布线之前** ✓

    ★ 口径 ✓：候选 = **两个朝向**（保持 ✓ / 翻 180° ✓）× 平移（让**某一只脚**踩上**它那条**轨 ✓）
      ⇒ 取「**脚到轨的 y 距离之和**」最小的 ✓；**只有严格更小才动** ✓（与 `--snaprails` 同一条 ✓）。
    ★ 为什么必须在**布线之前** ✗（“收尾再挪”已被实测否掉 ✓）：轨是按**零件包围盒**算的 ✓
      ⇒ 摆完再算轨、轨又跑远了 ✗（实测总长 1971.3 ✗）
      ⇒ 正解 = **先用“其它件”的包围盒定轨 ✓ → 再把骑轨件摆上去 ✓**（轨就不再随它跑 ✓）。
    ★ 比“收尾挪”干净在哪 ✗✓：**这一版没有任何补丁** ✗ —— 支线 / 轨的起止 / 通道 / keep-out
      全是现有机制在新位置上**重新算出来**的 ✓。收尾那版（`snap_rails` ✓）得删旧支线 ✓、
      复验 ✓、回滚 ✓，而且**轨会留着“为旧脚位延伸出来的那一段”** ✗ ⇒ 件一挪就穿身 ✗
      —— 实测正是这么栽的 ✓（`⊘ 网 5V 的段 (237.38,-57.60)→(281.56,-57.60) 真的穿进 C2 的本体` ✗）。
    """
    m = pin_net_map(insts)
    log = []
    for _t, _pl, d in hug:
        loc, box = d.get("loc"), d.get("box")
        if loc is None or box is None:
            continue

        def _obj(pins):
            return sum(min(abs(p[1] - v) for v in ry[m[(_t, c)]]) for (c, p) in pins)
        cur = _obj(_pl)
        best = None
        for flip in (False, True):
            base = [(_c, ((2 * loc[0] - p[0], 2 * loc[1] - p[1]) if flip else p))
                    for (_c, p) in _pl]
            for (_c0, _p0) in base:
                dy = min(ry[m[(_t, _c0)]], key=lambda v: abs(v - _p0[1])) - _p0[1]
                moved = [(_c, (p[0], p[1] + dy)) for (_c, p) in base]
                o = _obj(moved)
                if best is None or o < best[0] - 1e-9:
                    best = (o, flip, dy, moved)
        if best is None or best[0] >= cur - 1e-6:
            continue                                   # 不严格更好 ⇒ 原样 ✓
        o, flip, dy, moved = best
        nbox = ((2 * loc[0] - box[2], 2 * loc[1] - box[3] + dy,
                 2 * loc[0] - box[0], 2 * loc[1] - box[1] + dy) if flip
                else (box[0], box[1] + dy, box[2], box[3] + dy))
        _hit = []
        for _t2, _d2 in insts.items():                 # 压到别的件 ⇒ 不动 ✓
            _b2 = _d2.get("box")
            if _t2 == _t or not _b2:
                continue
            if (nbox[0] < _b2[2] and _b2[0] < nbox[2]
                    and nbox[1] < _b2[3] and _b2[1] < nbox[3]):
                _hit.append(_t2)
        if _hit:
            print("   ⊘ 骑轨预摆位：%s 摆到轨上会压到 %s ✗ ⇒ 不动 ✓"
                  % (_t, ", ".join(sorted(_hit))))
            continue
        g = pm.child(d["sub"], "geometry")
        if g is None:
            continue
        g.set("y", fmt(loc[1] + dy))
        tf = pm.child(g, "transform")
        if tf is not None and flip:
            # ★ 翻 180° 要**整个 2×3 一起翻** ✗✓（只翻 `m11/m12/m21/m22` 而留着 `m31/m32`
            #   ⇒ 零件整体平移了 (m31,m32) ✗ ⇒ 脚不在我以为的地方 ✗ —— 与 `snap_rails` 同一条 ✓）
            for _k2 in ("m11", "m12", "m21", "m22", "m31", "m32"):
                if _k2 in tf.attrib:
                    tf.set(_k2, fmt(-float(tf.get(_k2))))
        d["loc"] = (loc[0], loc[1] + dy)
        d["pins"] = {c: p for (c, p) in moved}
        d["box"] = nbox
        log.append("%s：预摆到轨上 ✓（%s、y 移 %.1f ✓）脚到轨之和 %.1f → %.1f 单位 ✓"
                   % (_t, "翻 180°" if flip else "保持", dy, cur, o))
    if log:
        print("   ★ **骑轨预摆位** ✓（在**布线之前** ✓ ⇒ 支线 / 轨的起止都是**重新算出来的** ✓，"
              "不带任何补丁 ✓）：")
        for ln in log:
            print("      · " + ln)
    return log


def snap_rails(insts, boxes, pin_all, nets_segs, rail_nets, eps=0.05, tol=0.6):
    r"""★★★ `--snaprails=<网>`：把「**所有脚都在这几个网上**」的件**摆到轨上** ✓（2026-09-30 ✓）

    ★ 为什么（**从用户手改版量出来的** ✓，不是想出来的 ✗ —— 见 README 第三十手 ✓）：
      用户把 `C2`（去耦电容 ✓，两只脚 = 5V + GND ✓）摆成“**两只脚各自踩在一条轨上**” ✓
      ⇒ GND 支线 **0.0** ✓、5V 支线只剩 18.4 ✓ ⇒ 总长 **1941.0 → 1836.3** ✓（−104.7 单位 ✓）。
      而 v35 里它被转了 **180°** ✗ ⇒ 白绕 **65（GND）+44（5V）** ✓。
    ★★ 为什么**不能只在摆位阶段挪** ✗（实测否掉 ✓，`_scratch/move_c2.py` ✓）：
      **轨是按零件箱子边算出来的** ✓ ⇒ 件一挪、箱子上去了、**轨跟着跑** ✗ ⇒ 脚又不在轨上了 ✗
      （实测总长反而 1971.3 ✗）。⇒ **必须“先把轨钉住、再挪件”** ✓ ——
      做法 = 在**已经布好线的这张图**上收尾 ✓（**不动路由器** ✗，与 `--trim` / `--relabel` 同一层 ✓）。

    ★ 认“轨”的口径 ✓：同网里**最长的、两端都不接脚**（`from`/`to` 都是 `None` ✓ = “光板” ✓）
      且**是直线**的那一段 ✓（口径与 `_cut_span_unused` 同一条 ✓，不另写 ✗）。

    ★ 打分 ✓：目标 = 每只脚到它那条轨**线段**的距离之和 ✓（= 之后要补的支线长度 ✓）；
      候选姿态 = **保持朝向 / 翻 180°** ✓ × 平移（把某只脚“对”到它那条轨上 ✓）；
      取目标最小的那个 ✓；**必须严格更小** ✓，且挪完的箱子**不压到别的件** ✗ ⇒ 才采纳 ✓。

    ★ 落点已经在轨上（≤ `tol`）的脚 ✓：**把旧支线删掉** ✓，并**在轨上该处切开** ⇒
      两半各把端点记成这只脚 ✓ ⇒ 电气上是“脚直接接在轨上” ✓✓（**不会留 0 长度残根** ✗ ——
      用户那版留了一根 ⚠，规则版不继承 ✓）。
    """
    def _dist_seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        return math.dist(p, (a[0] + dx * t, a[1] + dy * t))

    def _near(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        return (a[0] + dx * t, a[1] + dy * t)

    # ① 认轨 ✓（每个网一段 ✓）
    trunk = {}
    for _net in sorted(rail_nets):
        best = None
        for s in nets_segs.get(_net, []):
            pp = list(s.get("path") or [])
            if len(pp) < 2 or s.get("from") is not None or s.get("to") is not None:
                continue
            if not all(abs(q[1] - pp[0][1]) < eps for q in pp):
                continue
            L = abs(max(q[0] for q in pp) - min(q[0] for q in pp))
            if best is None or L > best[0]:
                best = (L, (min(q[0] for q in pp), pp[0][1]), (max(q[0] for q in pp), pp[0][1]), s)
        if best is None:
            print("   ⊘ `--snaprails`：网 `%s` 找不到“光板直段” ✓ ⇒ 这一网跳过 ✓" % _net)
            continue
        trunk[_net] = {"a": best[1], "b": best[2], "seg": best[3], "len": best[0]}
    if not trunk:
        return []

    # ② 脚 → 网 ✓（口径同路由：`NETS` + `pin_of` ✓）
    pin_net = {}
    for _net, _ps in NETS.items():
        for _ref, _nm in _ps:
            _cid, _p = pin_of(insts, _ref, _nm)
            if _cid:
                pin_net[(_ref, _cid)] = _net
    by_part = {}
    for (_t, _cid, _x, _y) in pin_all:
        by_part.setdefault(_t, []).append((_cid, (_x, _y)))

    log = []
    for _t in sorted(by_part):
        _pl = by_part[_t]
        _nets = {pin_net.get((_t, _c)) for (_c, _p) in _pl}
        if len(_pl) < 2 or None in _nets or any(n not in trunk for n in _nets):
            continue                                  # 要“**所有**脚都在有轨的网上” ✓
        d = insts.get(_t) or {}
        loc, box = d.get("loc"), boxes.get(_t)
        if loc is None or box is None:
            continue

        def _obj(pins):
            return sum(_dist_seg(p, trunk[pin_net[(_t, _c)]]["a"], trunk[pin_net[(_t, _c)]]["b"])
                       for (_c, p) in pins)
        cur = _obj(_pl)
        best = None
        for flip in (False, True):
            base = [(_c, ((2 * loc[0] - p[0], 2 * loc[1] - p[1]) if flip else p)) for (_c, p) in _pl]
            for _k, (_c0, _p0) in enumerate(base):
                _net0 = pin_net[(_t, _c0)]
                _tgt = _near(_p0, trunk[_net0]["a"], trunk[_net0]["b"])
                dx, dy = _tgt[0] - _p0[0], _tgt[1] - _p0[1]
                moved = [(_c, (p[0] + dx, p[1] + dy)) for (_c, p) in base]
                o = _obj(moved)
                if best is None or o < best[0] - 1e-9:
                    best = (o, flip, (dx, dy), moved)
        if best is None or best[0] >= cur - 1e-6:
            continue                                  # 不严格更好 ⇒ 原样不动 ✓
        o, flip, (dx, dy), moved = best
        nbox = (2 * loc[0] - box[2] + dx, 2 * loc[1] - box[3] + dy,
                2 * loc[0] - box[0] + dx, 2 * loc[1] - box[1] + dy) if flip else \
               (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        if any(_t2 != _t and b2 and nbox[0] < b2[2] and b2[0] < nbox[2]
               and nbox[1] < b2[3] and b2[1] < nbox[3] for _t2, b2 in boxes.items()):
            print("   ⊘ `--snaprails`：%s 挪过去会压到别的件 ✗ ⇒ 原样不动 ✓" % _t)
            continue
        # ★★★ 2026-09-30 ✓ **改成「摆了才算」** ✗✓ —— 老版是「**先预测、再搬**」✗：
        #   它拿“把端点搬过去、其余点不动”预测出来的段去判“穿体” ✗ ⇒ 实测 **误否决** ✗：
        #   落地时**本来就要把那条旧支线整条删掉** ✓（见 ④ ✓），可预测时还把它算在内 ✗
        #   ⇒ 那条**马上要消失**的残根当然“穿过新身体” ✗ ⇒ **用户那种摆法被毙掉** ✗
        #   （实测 ✓：`⊘ C2 … 网 GND 的段 C2.connector1→None` ✗ = 那正是要删掉的那一段 ✓）。
        #   ✓ 现在：**先摆（含删旧支线 ✓）→ 用渲染器同一条判据复验 → 不过就整份回滚** ✓。
        g = pm.child(d["sub"], "geometry")
        if g is None:
            continue
        tf = pm.child(g, "transform")
        _old = dict(_pl)                       # 旧脚位 ✓（删旧支线要从这里出发 ✓）

        def _on_trunk(p, _net):
            _tr = trunk.get(_net)
            return _tr is not None and _dist_seg(p, _tr["a"], _tr["b"]) <= tol

        def _stub_chain(_net, _p0):
            r"""从**旧脚位**出发沿“脚→轨”支线往外走 ✓，返回 `(要删的段 ✓, 停下的点 ✓)`

            ★ 只走**简单链** ✗：某点挂着 **0 段**（到头 ✓）或 **≥2 段**（岔路 ✓）⇒ **停手** ✓
              —— 岔路上可能挂着别人的线 ✗ ⇒ 宁可少删 ✓ 也不许误删 ✓。
            ★ 走到**轨上**（≤ `tol` ✓）就停 ✓ —— 那之后的都是轨自己 ✓，不能删 ✗。
            """
            out, cur = [], _p0
            for _ in range(40):
                hit = []
                for s in nets_segs.get(_net, []):
                    if s in out:
                        continue
                    pp = list(s.get("path") or [])
                    if len(pp) < 2:
                        continue
                    if abs(pp[0][0] - cur[0]) < 0.05 and abs(pp[0][1] - cur[1]) < 0.05:
                        hit.append((s, pp[-1]))
                    elif abs(pp[-1][0] - cur[0]) < 0.05 and abs(pp[-1][1] - cur[1]) < 0.05:
                        hit.append((s, pp[0]))
                if len(hit) != 1:
                    break
                s, far = hit[0]
                out.append(s)
                cur = far
                if _on_trunk(cur, _net):
                    break
            return out, cur

        def _own_pins(a, b):
            """渲染器那一条豁免 ✓：**端点落在这只脚上**的段 ⇒ 对**这一件**免判穿体 ✓"""
            out = set()
            for _t6, _c6, _x6, _y6 in pin_all:
                if (abs(_x6 - a[0]) < 0.05 and abs(_y6 - a[1]) < 0.05) or \
                   (abs(_x6 - b[0]) < 0.05 and abs(_y6 - b[1]) < 0.05):
                    out.add(_t6)
            return out

        def _thru():
            """复验 ✓：**摆完之后**还有哪一段真的穿进谁的本体 ✓（判据 = `SG.hits_box` ✓）"""
            for _n2, _sg2 in nets_segs.items():
                for s2 in _sg2:
                    pp2 = list(s2.get("path") or [])
                    for _k4 in range(len(pp2) - 1):
                        _a5, _b5 = pp2[_k4], pp2[_k4 + 1]
                        _ow = _own_pins(_a5, _b5)
                        for _t2, b2 in boxes.items():
                            if not b2 or _t2 in _ow:
                                continue
                            if SG.hits_box(_a5, _b5, b2):
                                return (_n2, _t2, _a5, _b5)
            return None

        def _snap2():
            """回滚点 ✓：这一遍要动的东西**全部存下来** ✓"""
            return (copy.deepcopy(nets_segs), dict(boxes), list(pin_all),
                    dict(d["pins"]), d.get("loc"), copy.deepcopy(trunk),
                    g.get("x"), g.get("y"),
                    dict(tf.attrib) if tf is not None else None)

        def _backup(sn):
            nets_segs.clear()
            nets_segs.update(sn[0])
            boxes.clear()
            boxes.update(sn[1])
            pin_all[:] = sn[2]
            d["pins"].clear()
            d["pins"].update(sn[3])
            d["loc"] = sn[4]
            trunk.clear()
            trunk.update(sn[5])
            g.set("x", sn[6])
            g.set("y", sn[7])
            if tf is not None and sn[8] is not None:
                for _k5 in list(tf.attrib):
                    del tf.attrib[_k5]
                tf.attrib.update(sn[8])

        _sn = _snap2()
        _lg0 = len(log)

        # ③ 落地：改实例几何 ✓、改脚/箱/脚表 ✓
        newloc = ((2 * loc[0] - loc[0] + dx) if flip else loc[0] + dx,
                  (2 * loc[1] - loc[1] + dy) if flip else loc[1] + dy)
        g = pm.child(d["sub"], "geometry")
        tf = pm.child(g, "transform") if g is not None else None
        if g is None:
            continue
        g.set("x", fmt(newloc[0]))
        g.set("y", fmt(newloc[1]))
        if tf is not None and flip:
            # ★★ 翻 180° 要**整个 2×3 一起翻** ✗✓（实测教训 ✓）：只翻 `m11/m12/m21/m22` ✗
            #   而留着 `m31/m32` ⇒ 零件**整体平移**了 (m31,m32) ✗（`C2` 正好带 `m31=14.4`
            #   `m32=27.875` ✓）⇒ 画出来的脚**不在我以为的地方** ✗ ⇒ 判据 `(A)` 当场报 **2 处**
            #   “声明接 C2 的脚、线却画在别处” ✗✗。
            for _k2 in ("m11", "m12", "m21", "m22", "m31", "m32"):
                if _k2 in tf.attrib:
                    tf.set(_k2, fmt(-float(tf.get(_k2))))
        newpins = {c: p for (c, p) in moved}
        for _c in list(d["pins"]):
            if _c in newpins:
                d["pins"][_c] = newpins[_c]
        for _i2 in range(len(pin_all)):
            if pin_all[_i2][0] == _t and pin_all[_i2][1] in newpins:
                pin_all[_i2] = (_t, pin_all[_i2][1]) + newpins[pin_all[_i2][1]]
        d["loc"] = newloc
        boxes[_t] = nbox

        # ④ 支线：脚已经落到轨上的 ⇒ 删支线 + 在轨上切开；否则只把支线端点搬过去 ✓
        for (_c, _p) in moved:
            _net = pin_net[(_t, _c)]
            _tr = trunk[_net]
            _d = _dist_seg(_p, _tr["a"], _tr["b"])
            _br = None
            for s in nets_segs.get(_net, []):
                for _side in ("from", "to"):
                    q = s.get(_side)
                    if q and q.get("ref") == _t and q.get("cid") == _c:
                        _br = (s, _side)
            if _br is None:
                continue
            s, _side = _br
            if _side == "from":
                path = s.get("path") or []
                s["path"] = [_p] + list(path[1:])
                if s.get("a") is not None:
                    s["a"] = _p
            else:
                path = s.get("path") or []
                s["path"] = list(path[:-1]) + [_p]
                if s.get("b") is not None:
                    s["b"] = _p
            if _d <= tol:                              # 脚就在轨上 ⇒ 只要“切开 + 挂上”✓
                # ★★★ 2026-09-30 ✓ **还要把整条旧支线删掉** ✗✓（实测踩的 ✓）：
                #   ✗ 老版只删“贴着这只脚的那一段”（= 上面那个 `s` ✓）✗ ⇒ 支线的**其余部分**
                #     （拐点之后到轨那一截 ✗）**吊在半空** ✗ —— 实测它正好从这件的**新身体里穿过** ✗
                #     ⇒ 被复验当场抓住 ✗；就算不穿过 ✓ 也会留一个**悬空端点** ✗（判据红 ✗）。
                #   ✓ 从**旧脚位**往外走到轨 ✓ ⇒ 这一整条都删 ✓（只走简单链 ✓，岔路停手 ✓）。
                _kill, _endp = _stub_chain(_net, _old[_c])
                for _s7 in _kill:
                    if _s7 in nets_segs.get(_net, []):
                        nets_segs[_net].remove(_s7)
                if _kill:
                    log.append("%s.%s：旧支线 **%d 段**删掉 ✓（走到轨 (%.2f,%.2f) ✓）"
                               % (_t, _c, len(_kill), _endp[0], _endp[1]))
                _pr = _near(_p, _tr["a"], _tr["b"])
                _tseg = _tr["seg"]
                _tp = list(_tseg.get("path") or [])
                if _tseg in nets_segs.get(_net, []) and len(_tp) >= 2:
                    _seg_pin = {"ref": _t, "cid": _c}
                    # ★★ 投影点要**插进 path** ✓，不许“拿首尾两点重造” ✗✗ ——
                    #   实测教训 ✓：第一版写成 `[_tp[0], _pr]` ✗ ⇒ 轨要是**多点 path**（有拐角 ✓）
                    #   就把中间那些点**整段丢掉** ✗ ⇒ 这一版的导线从 46 根掉到 **40 根** ✗✗
                    #   ⇒ 六道判据**全红** ✗（网表都不过 ✓）。正解：**按投影所在的那一段切开** ✓。
                    _k1 = None
                    for _k in range(len(_tp) - 1):
                        if _dist_seg(_pr, _tp[_k], _tp[_k + 1]) < 1e-6:
                            _k1 = _k
                            break
                    if _k1 is None:
                        continue                            # 投影不在轨上 ✗ ⇒ 不切 ✓（保守 ✓）
                    _lp = list(_tp[:_k1 + 1]) + [_pr]
                    _rp = [_pr] + list(_tp[_k1 + 1:])
                    nets_segs[_net].remove(_tseg)
                    nets_segs[_net].append({"a": _lp[0], "b": _pr, "path": _lp,
                                            "from": _tseg.get("from"), "to": _seg_pin})
                    nets_segs[_net].append({"a": _pr, "b": _rp[-1], "path": _rp,
                                            "from": _seg_pin, "to": _tseg.get("to")})
                    if s in nets_segs.get(_net, []):
                        nets_segs[_net].remove(s)
                    trunk[_net] = {"a": _lp[0], "b": _pr, "seg": None, "len": 0.0}
                    log.append("%s.%s：支线删掉 ✓ + 轨在 (%.2f,%.2f) 切开挂上 ✓"
                               % (_t, _c, _pr[0], _pr[1]))
                    continue
            log.append("%s.%s：支线端点搬到 (%.2f,%.2f) ✓（离线 %.2f）"
                       % (_t, _c, _p[0], _p[1], _d))
        # ★★ 2026-09-30 ✓ **复验**：摆完之后若仍有导线真的穿进谁的本体 ✗ ⇒ **整份回滚** ✓
        #   （“一个判据一份实现” ✓：用的是渲染器那份 `SG.hits_box` ✓ 与同一条“端点在自己脚上就豁免” ✓）
        _bad2 = _thru()
        if _bad2:
            _backup(_sn)
            del log[_lg0:]
            print("   ⊘ `--snaprails`：%s 摆完**复验不过** ✗（网 `%s` 的段 "
                  "(%.2f,%.2f)→(%.2f,%.2f) 真的穿进 `%s` 的本体 ✗）⇒ **整份回滚** ✓"
                  "（宁可少省 ✓，也不交带缺陷的图 ✗）"
                  % (_t, _bad2[0], _bad2[2][0], _bad2[2][1], _bad2[3][0], _bad2[3][1],
                     _bad2[1]))
            continue
        log.append("%s：姿态%s、平移到 (%.2f,%.2f) ✓ ⇒ 支线总和 %.1f → %.1f 单位 ✓"
                   % (_t, "翻 180°" if flip else "保持", newloc[0], newloc[1], cur, o))
    if log:
        print("   ★ `--snaprails` ✓：摆到轨上的件 ——")
        for ln in log:
            print("      · " + ln)
    else:
        print("   ★ `--snaprails` ✓：没有需要摆到轨上的件 ✓（或都不划算 ✓）")
    return log


def emit(sroot, insts, z, nets_segs, orig_path, out_path, PIN_ALL=(), boxes=None):
    """把每对脚的正交路径拆成「一段一根导线」✓；两端各记一份连接 ✓（链式，不出现 junction 点 ✓）"""
    oz = zipfile.ZipFile(orig_path)
    oroot = ET.fromstring(oz.read([n for n in oz.namelist() if n.endswith(".fz")][0]))
    tmpl = next((copy.deepcopy(e) for e in oroot.iter("instance")
                 if (e.get("moduleIdRef") or "").startswith("Wire")), None)
    if tmpl is None:
        raise SystemExit("✗ 原文件里没有 Wire 模板")
    host = pm.child(sroot, "instances")
    host = sroot if host is None else host
    # ★★★ 先清掉**输入文件里残留的旧导线实例** ✓（2026-09-28 ✓ —— 修“C1/EPAD 那条飞线”✓）
    #   ★ 病因（`t62` 量出来的事实 ✓，不是推的 ✗）：输入 `.fzz` 里存着 **90 个实例**
    #     的 `schematicView` **已被上一站删掉** ✗（`gen_schematic_layout3` 只 `vw.remove(sub)` ✗，
    #     **实例本身留在 `<instances>` 里** ✓）⇒ 它们**没有几何** ✗、却**还挂着 `<connects>`** ✗
    #     （实测 `Wire90012840/870/871` 就挂在 `U1.c20`（EPAD）上 ✓）
    #     ⇒ Fritzing 认为那一网“**还有没接完的东西**” ✗ ⇒ **画飞线** ✗✗
    #       （用户看到的“C1 两端那条虚线”就是它 ✓）。
    #   ✓ 这里兜底：**进 `emit` 先把所有 Wire 实例清掉** ✓（本函数后面会重新写全部导线 ✓）
    #     ⇒ 输出文件保证干净 ✓，不依赖上游删得干不干净 ✓。
    #   ★★ 判据要**两种都认** ✓（2026-09-28 ✓ 实测教训 ✓）：第一次只看了 `moduleIdRef` ✗
    #     ⇒ 那一行**根本没打印** ✗（= 一个都没匹配上 ✗），可 `t62` 明明数出 **90 个**
    #     “几何读不到的实例”（`Wire90012727…` 一整串 ✓）⇒ 它们**不是**靠 `moduleIdRef` 认出来的 ✗
    #     ⇒ 它们的 `title` 才叫 `Wire…` ✓。⇒ 两个判据都算 ✓（覆盖 ✓ 不会漏 ✓）。
    _zomb, _zmi = 0, set()
    for _e in list(host):
        if tag(_e) != "instance":
            continue
        _mid = _e.get("moduleIdRef") or ""
        _ttl = (_e.findtext("title") or "").strip()
        if _mid.startswith("Wire") or _ttl.startswith("Wire"):
            _zmi.add(str(_e.get("modelIndex")))
            host.remove(_e)
            _zomb += 1
    # ★★★ **同时**要把“**指向它们的连接**”删掉 ✓（2026-09-28 ✓ —— 不删就会造出**短接** ✗✗）
    #   ✗ 只删实例（上一版 ✓）⇒ **别人还记着“我连着 `Wire90012727`”** ✗ ⇒ 于是两个**本来不同网**
    #     的元件，通过一个**已经不存在的 mi** 被**间接连通** ✗ ⇒ 实测 **9 个网对不上** ✗✗
    #     （`5V` 里多出 `D3.connector4`、`DATA_IN/DATA_OUT/LED_DIN` 里多出一大堆 ✓ ——
    #      几何上看着挺好看 ✓，电气上**串成一片** ✗，只有 `check_netlist.py` 那一列看得见 ✗）。
    #   ✓ 正解：把指向这些 mi 的 `<connect>` 一并删掉 ✓ ⇒ 连接表恢复自洽 ✓。
    _nref = 0
    if _zmi:
        # ★ 不赌层级 ✓：`<connect>` 在哪一层**不许猜** ✗（本仓踩过 ✓）⇒ 用**父映射**收全部 ✓。
        _par = {_c: _p for _p in sroot.iter() for _c in _p}
        for _cn in [c for c in sroot.iter("connect") if str(c.get("modelIndex")) in _zmi]:
            _p = _par.get(_cn)
            if _p is not None:
                _p.remove(_cn)
                _nref += 1
    if _zomb:
        print("   ★ 清掉输入里**残留的旧导线实例 %d 个** ✓ + **指向它们的连接 %d 条** ✓"
              "（只删实例不删连接 ⇒ 不同网会被“不存在的 mi”间接连通 ⇒ **短接** ✗✗）"
              % (_zomb, _nref))
    else:
        print("   ★ 输入里没有残留的导线实例 ✓（判据：`moduleIdRef` **或** `title` 以 `Wire` 开头 ✓）")
    next_mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1

    # ★★★ **原理图去粘**（**修订版** ✓，2026-09-28 ✓ 用户实测 + `t67` 定位 ✓）：
    #   ✗ 上一版按 `moduleIdRef` 含 `breadboard` 去找 ⇒ **只清了面包板实例自己那一份** ✗
    #     ⇒ 而**真正的粘源在元件侧** ✗。实测 `t67_report.txt` ✓——U1 的 `schematicView` 里，
    #     **每只插在面包板上的脚**都挂着一条 `layer="breadboardbreadboard"` 的 connect ✗
    #     （指向 `mi=5785` = 面包板 ✓）：
    #         <connector connectorId="connector0" layer="schematic">
    #           <connects>
    #             <connect connectorId="pin39F" modelIndex="5785" layer="breadboardbreadboard"/>
    #     ⇒ **Fritzing 在原理图视图里照它连通** ✗ ⇒ 插在**同一列孔**上的脚
    #       **在原理图里被粘成一片** ✗。
    #   ★ 用户实测（权威 ✓）：「在 Fritzing 里点那条飞线 ⇒ **GND 和 RC 两个网都高亮**」✗
    #     —— 即 Fritzing 认定它们是**同一个网** ✓（PA1 属 RC ✓、VSS 属 GND ✓，
    #     都是 U1 的脚 ✓、面包板上**同一列** ✓）。也解释了「**删掉面包板就都 OK**」✓。
    #   ★ 为什么以前查不出来 ✗：`check_netlist.py` 与我的诊断**一律按 `layer ∈ SCH` 过滤** ✗
    #     并且**排除面包板** ✗ ⇒ **恰好把这条边过滤掉了** ✗✗ —— “自证式”盲区 ✓。
    #   ✓ 正解 = **只按 layer 清，不按身份清** ✓：`schematicView` 下**任何** layer 不是
    #     `schematic` / `schematicTrace` 的 `<connect>`，都是**别的视图的关系**被复制过来的一份 ✗
    #     ⇒ 在本视图里**不该生效** ✓。
    #     一条规则同时覆盖：元件侧的 44 条 ✓ + 面包板实例侧的 44 条 ✓（实测 = 88 条 ✓）。
    #   ★ `breadboardView` / `pcbView` 里的那一份**原样不动** ✓（它们自己那份是**对的** ✓）。
    _dn, _dinst = 0, 0
    for _e in list(host):
        if tag(_e) != "instance":
            continue
        _vw = pm.child(_e, "views")
        _sub = pm.child(_vw, "schematicView") if _vw is not None else None
        if _sub is None:
            continue
        _par = {_c: _p for _p in _sub.iter() for _c in _p}
        _k = 0
        for _cn in [c for c in _sub.iter() if tag(c) == "connect"]:
            if (_cn.get("layer") or "") in ("schematic", "schematicTrace"):
                continue
            _p = _par.get(_cn)
            if _p is not None:
                _p.remove(_cn)
                _k += 1
        if _k:
            _dinst += 1
            _dn += _k
    if _dn:
        print("   ★ 原理图去粘 ✓：**%d 个实例**在 `schematicView` 里**不属于本视图**的连接"
              " **%d 条**已清 ✓（`layer` 不是 `schematic`/`schematicTrace` ✗ ⇒ 那是**别的视图**"
              "的关系被复制过来的一份 ⇒ Fritzing 会照它在**原理图**里连通 ⇒ "
              "**把插在同列孔上的脚粘成一片** ✗）" % (_dinst, _dn))
    else:
        print("   ★ 原理图去粘 ✓：`schematicView` 里没有跨视图的连接 ✓（本来就干净 ✓）")

    wires, links = [], []

    # ★★★ 面包板**退出电气** ✓（方案 b ✓，2026-09-28 ✓ 用户选 ✓）：
    #   ★ 用户实测（**权威判据** ✓）：「把面包板挪开、元件不插它 ⇒ 原理图里**就没有虚线了**」✓
    #     ⇒ 机制由此定案 ✓：**Fritzing 的"网"是跨视图算的** ✗
    #       （`ConnectorItem::collectEqualPotential` 会**穿过面包板的 bus** ✓）
    #       ⇒ 插在**同一列孔**上的脚 ⇒ **在它眼里就是同一个网** ✗
    #       ⇒ 跨网的脚被粘在一起 ⇒ 画飞线 ✗（实测：飞线两端 = U1 的 **PA2 与 VSS** ✗，
    #         两只脚在面包板上**同一列** ✓；而**删掉面包板** ⇒ 立刻正常 ✓✓✓）。
    #   ✗ 我前面几轮走的弯路（要记住 ✗）：
    #     · 清 `schematicView` 里的跨视图连接（上一版 ✓）**只是清了"抄本"** ✗ ——
    #       **活的链在面包板视图的孔连接里** ✗ ⇒ 清完飞线照旧 ✗；
    #     · 更早还怀疑过 `wireFlags` ✗ ⇒ 被实测否证 ✓（用户手画的原图**同样是 128** ✓）。
    #   ✓ 方案 b = **位置不动、只断连接** ✓ ⇒ 面包板视图**照样"看得见元件插在孔上"** ✓
    #     （几何全留 ✓），但**不参与任何网** ✓ ⇒ 与用户手动"删掉面包板再加回来"**等价** ✓，
    #     且**与摆位无关** ✓（将来面包板挪到哪都不会再影响原理图 ✓）。
    _bbmi = {str(_x.get("modelIndex")) for _x in host
             if tag(_x) == "instance"
             and "breadboard" in (_x.get("moduleIdRef") or "").lower()}
    _bk = 0
    if _bbmi:
        for _e in list(host):
            if tag(_e) != "instance":
                continue
            _vw = pm.child(_e, "views")
            if _vw is None:
                continue
            _me = str(_e.get("modelIndex"))
            _par = {_c: _p for _p in _vw.iter() for _c in _p}
            for _cn in [c for c in _vw.iter() if tag(c) == "connect"]:
                # 任一端是面包板 ⇒ 断掉 ✓（别人的脚指向它 ✓ / 它自己指向别人 ✓）
                if _me in _bbmi or str(_cn.get("modelIndex")) in _bbmi:
                    _p = _par.get(_cn)
                    if _p is not None:
                        _p.remove(_cn)
                        _bk += 1
    if _bk:
        print("   ★ 面包板**退出电气** ✓：断掉 **%d 条「脚 ↔ 孔」连接** ✓"
              "（**位置不动** ✓ ⇒ 画面上照样插在孔上 ✓；但 Fritzing 不再跨视图粘网 ✗）"
              "—— 这正是用户实测「删掉面包板就没虚线了 ✓」的**等效做法** ✓" % _bk)
    else:
        print("   ★ 面包板**退出电气** ✓：本来就没有「脚 ↔ 孔」连接 ✓（已断开 ✓）")
    # ★★★ 2026-09-29 ✓ **NL1：网标签替代长直段** ✓（用户定 ✓）——
    #   只对 `--label=<网>` 点名的网生效 ✓ ⇒ **不给就一字节不差** ✓（v29 可复现 ✓）。
    #   切在**建链之前** ✓（链是从 `s["path"]` 建的 ✓）。
    _lbl_jobs = []
    _lbl_boxes = []          # ★ 已放好的标签本体框 ✓（后放的标签不许压先放的 ✓）
    _gcnt = 0                # ★ 接地符号的编号（`Ground1` / `Ground2` ✓ —— Fritzing 自己也是这么编的 ✓）
    if LABEL_NETS and not LABEL_MOD_A:
        for _net in sorted(nets_segs):
            if _net not in LABEL_NETS:
                continue
            # ★★★ 2026-09-30 ✓ **`--ground` 点名的网不切** ✗（详见 `ground_spots` 那段 ✓）：
            #   切口的形状是固定的 ✗ —— 实测那个切口正好是一根**长竖线的顶端** ✗ ⇒ 切出来的
            #   两个断口**挂不下接地符号** ✗（往下挂必然穿图形 ✗）。用户手改版里的两个符号
            #   也**不是**挂在断口上 ✓，而是挂在**整张网上挑出来的、挂得下的点**上 ✓。
            if _net in GROUND_NETS:
                print("   ⊘ **--ground** ✓：网 `%s` **不切** ✗（改在整张网上挑点挂接地符号 ✓）"
                      % _net)
                continue
            _new, _jobs = cut_span_for_labels(nets_segs[_net])
            if _jobs:
                nets_segs[_net] = _new
                _lbl_jobs += [(_net, q) for q in _jobs]
                print("   ★ **NL1** ✓：网 `%s` 切掉 **%.1f 单位** ✓ ｜ 断口 "
                      "(%.1f,%.1f) ↔ (%.1f,%.1f) ⇒ 两端各贴一个同名标签 ✓"
                      % (_net, _jobs[0][2], _jobs[0][0][0], _jobs[0][0][1],
                         _jobs[1][0][0], _jobs[1][0][1]))
            else:
                print("   ⊘ **NL1**：网 `%s` 找不到“切了**两半都还有脚**、且空档 ≥ %.0f 单位”"
                      "的长直段 ✗ ⇒ 不动 ✓" % (_net, _LBL_MIN_GAP))
                _sgs = nets_segs.get(_net) or []
                print("      · 诊断 ✓：本网 %d 段 ✓" % len(_sgs))
                for _s9 in _sgs[:14]:
                    _p9 = list(_s9.get("path") or [])
                    _l9 = sum(math.dist(_p9[k], _p9[k + 1]) for k in range(len(_p9) - 1)) \
                        if len(_p9) > 1 else 0.0
                    _n9 = 0
                    for _t9 in _sgs:
                        if _t9 is _s9 or not (_t9.get("path") or []):
                            continue
                        for _e9 in (_t9["path"][0], _t9["path"][-1]):
                            for _q9 in (_p9[0], _p9[-1]):
                                if abs(_e9[0] - _q9[0]) < 1e-3 and abs(_e9[1] - _q9[1]) < 1e-3:
                                    _n9 += 1
                    print("        %-1s 点 %d ✓ 长 %7.1f ✓ 两端被邻段接上 %d 次 ✓ "
                          "from=%s to=%s ✓ ｜ %s → %s"
                          % ("✗" if (_s9.get("from") or _s9.get("to") or _l9 < _LBL_MIN_GAP
                                     or _n9 < 2) else "✓", len(_p9), _l9, _n9,
                             bool(_s9.get("from")), bool(_s9.get("to")),
                             tuple(_p9[0]) if _p9 else "-",
                             tuple(_p9[-1]) if _p9 else "-"))
    # ★★★ 2026-09-30 ✓ **`--snaprails`：把件摆到轨上** ✓ —— **必须在这里** ✗✓：
    #   ① **在“把 `nets_segs` 拆成一根根导线”之前** ✓（下面那个双层循环 ⇒ 拆完再改就晚了 ✗）；
    #   ② **在“轨已经算好”之后** ✓（`nets_segs` 就是路由器算出来的轨 ✓）⇒ 这才叫“**先把轨钉住、再挪件**” ✓；
    #      ✗ 只挪件（在摆位阶段挪）是**实测否掉**的 ✗：轨按零件箱子边算 ⇒ 件一挪轨跟着跑 ✗
    #      （`_scratch/move_c2.py` ✓：总长反而 1941.0 → 1971.3 ✗）。
    #   ③ 也**必须在标签/接地/剪冗余之前** ✓ —— 挪完件的几何要成为它们的障碍 ✓。
    if SNAP_RAILS:
        snap_rails(insts, boxes, PIN_ALL, nets_segs, SNAP_RAILS)
    for net in sorted(nets_segs):
        for s in nets_segs[net]:
            chain = []
            for k in range(len(s["path"]) - 1):
                p, q = s["path"][k], s["path"][k + 1]
                if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                    continue
                chain.append({"mi": str(next_mi), "p": p, "q": q, "net": net,
                              "start_tgt": None, "end_tgt": None})
                next_mi += 1
            if not chain:
                # ★ 诊断 ✓（2026-09-28 加 ✓ —— 起因：用户报「**C1 两端有条虚线**」✗，
                #   量出来真凶是 **`U1.c20`（= EPAD）孤立** ✗：它属于 GND 网，却**一根线都没有** ✗
                #   ⇒ Fritzing 就给它画一条“该连而未连”的飞线 ✓）。
                #   ✗ 这里原来是**静默丢弃** ✗ ⇒ 写出的文件里那只脚**凭空少一根线** ✗，
                #     而所有检查都看不出（连接表里它只是“没有连接”✗）⇒ 必须**吭声** ✓。
                print("   ⚠ 段被丢弃 ✗：`path` 只有 %d 个点 ✓｜a=%s b=%s ✓｜from=%s to=%s ✓"
                      % (len(s.get("path") or []),
                         "(%.2f,%.2f)" % tuple(s["path"][0]) if s.get("path") else "-",
                         "(%.2f,%.2f)" % tuple(s["path"][-1]) if s.get("path") else "-",
                         s.get("from"), s.get("to")))
                continue
            chain[0]["start_tgt"] = ("pin", s["from"])
            chain[-1]["end_tgt"] = ("pin", s["to"])
            for k in range(len(chain) - 1):
                chain[k]["end_tgt"] = ("wire", chain[k + 1], "connector0")
                chain[k + 1]["start_tgt"] = ("wire", chain[k], "connector1")
            wires.extend(chain)

    # ★★ NL2 ✓（2026-09-29 用户定 ✓）：**在功能模块边界上**切 ✓ —— 判据见 `cut_at_module_boundary` ✓
    #   口径：切点必须让「模块 A 的脚」与「模块 B 的脚」**正好分开** ✓ ⇒ 两边各贴一个同名标签 ✓。
    if LABEL_NETS and LABEL_MOD_A:
        _del2, _jobs2 = set(), []
        for _net2 in sorted(set(w["net"] for w in wires)):
            if _net2 not in LABEL_NETS:
                continue
            if _net2 in GROUND_NETS:            # ★ 地网不切 ✓（见 `ground_spots` 那段 ✓）
                continue
            _d2, _j2 = cut_at_module_boundary(wires, _net2, LABEL_MOD_A)
            if _j2:
                _del2 |= _d2
                _jobs2 += [(_net2, q) for q in _j2]
                print("   ★ **NL2 模块边界** ✓：网 `%s` 删掉 %d 根跨块线 ✓"
                      " ⇒ A/B 两块边界各贴一个同名标签 ✓" % (_net2, len(_d2)))
        if _del2:
            wires = [w for w in wires if w["mi"] not in _del2]
            _n2 = 0
            for w in wires:                      # 断口那两头的指向要改回**裸端** ✓
                for _k2 in ("start_tgt", "end_tgt"):
                    _t2 = w.get(_k2)
                    if _t2 and _t2[0] == "wire" and _t2[1] and _t2[1].get("mi") in _del2:
                        w[_k2] = None
                        _n2 += 1
            print("   ★ **NL2** ✓：删了 %d 根导线 ✓（%d 个头尾改回裸端 ✓）" % (len(_del2), _n2))
        _lbl_jobs += _jobs2

    for w in wires:                              # 建实例 ✓
        w["el"] = build_wire(tmpl, w)
        host.append(w["el"])
        w["view"] = pm.child(pm.child(w["el"], "views"), "schematicView")
    wire_by_mi = {w["mi"]: w for w in wires}
    part_by_mi = {d["mi"]: d for d in insts.values()}

    for w in wires:                              # 收集两端归属 ✓
        for cid, tgt in (("connector0", w["start_tgt"]), ("connector1", w["end_tgt"])):
            if tgt is None:
                continue
            if tgt[0] == "pin":
                p = tgt[1]
                if p is None:                    # ★ 星形的汇点端 = **裸端点** ✓（没有连接器 ✓）
                    continue                     #   ⇒ 连接性由 `check_netlist.py` 当场判 ✓
                links.append((w["mi"], cid, "schematicTrace",
                              insts[p["ref"]]["mi"], p["cid"], "schematic"))
            else:
                ow = tgt[1]
                links.append((w["mi"], cid, "schematicTrace",
                              ow["mi"], tgt[2], "schematicTrace"))

    # ★★ NL1 ✓：把标签实例**建出来**、贴到两个断口上 ✓ —— **声明要双向写** ✓
    #   （判定器按**连接表**认网 ✓ ⇒ 光画在那儿、不写 `<connect>` 是不算的 ✗）
    # ★★★ 2026-09-30 ✓ **标签就近贴“本侧引脚”** ✓（③，学用户手改版 ✓；见 `sch-drawing-rules` B3.1 ✓）
    #   ✗ 原来一律贴在**模块边界的断口**上 ✗ ⇒ 本侧“为了够到断口”的那一长段就白留了 ✗：
    #     实测 `RC` 的 A 侧为了够到断口 `(46.4,55.2)` 走了 **143.7 单位** ✗（用户把标签挪到
    #     `R1` 旁边 ✓ ⇒ 那一段立刻变成**断头** ⇒ 清掉 ✓ = 省 **128.3** ✓），
    #     而两个标签**同名即同网** ✓ ⇒ 电气上照样成立 ✓✓。
    #   ⇒ 现在：候选 = **本侧所有导线端点** ✓，按“离本侧的脚最近”排 ✓；再走原来的
    #     （沿轴外推 × 朝向 × 违例）搜索 ✓；取（违例少 → 离脚近 → 挪得近 → 朝向 0°）✓。
    # ★ 标签画出来的脚（给下面的“共线合并”当**终端**用 ✓：那一点上不许并 ✗）
    _lbl_pins = []
    for _net, (_pt, _side, _gain) in _lbl_jobs:
        _sidew = [x for x in wires if x.get("net") == _net]
        _par0 = {}

        def _f0(x):
            _par0.setdefault(x, x)
            while _par0[x] != x:
                _par0[x] = _par0[_par0[x]]
                x = _par0[x]
            return x
        for _x0 in _sidew:                        # 本侧 = 与断口**连通**的那些线 ✓
            _a0, _b0 = _f0(_rk(_x0["p"])), _f0(_rk(_x0["q"]))
            if _a0 != _b0:
                _par0[_b0] = _a0
        _root0 = _f0(_rk(_pt))
        _comp = [x for x in _sidew if _f0(_rk(x["p"])) == _root0]
        _nodes0 = {_rk(q) for x in _comp for q in (x["p"], x["q"])}
        _pins0 = [(x, y) for (_r, _c, x, y) in PIN_ALL if _rk((x, y)) in _nodes0]
        _cands = []
        for _x0 in _comp:
            for _cid0, _q40, _tk0 in (("connector0", _x0["p"], "start_tgt"),
                                      ("connector1", _x0["q"], "end_tgt")):
                _d0 = min([math.dist(_q40, _p0) for _p0 in _pins0] or [0.0])
                _cands.append((_d0, str(_x0["mi"]), _x0, _cid0, _tk0))
        _cands.sort(key=lambda z: (z[0], z[1]))
        # ★★ 2026-09-30 ✓ 本侧“**真终端**”的结点表 ✓（脚 + 别的标签 ✓）—— 给
        #   `dead_end_pin` 用 ✓：候选要是把一段**尽头挂着真脚**的链丢掉 ⇒ 否掉它 ✗
        #   （否则那只脚会被孤立 ✗，而留着又会在断口留悬空端 ✗ ⇒ 只能不挪这一侧 ✓）。
        _term_pts = set()
        for _w5 in _sidew:
            for _tk5, _e5 in (("start_tgt", _w5["p"]), ("end_tgt", _w5["q"])):
                _t5 = _w5.get(_tk5)
                if _t5 and _t5[1] is not None and _t5[0] in ("pin", "label"):
                    _term_pts.add(_rk(_e5))
        _pick = None
        for _rank, (_dist0, _mi0, _w, _cid, _tk) in enumerate(_cands):
            _other = _w["q"] if _tk == "start_tgt" else _w["p"]
            _end = _w["p"] if _tk == "start_tgt" else _w["q"]
            _ex, _ey = _end[0] - _other[0], _end[1] - _other[1]
            _EL = math.hypot(_ex, _ey)
            _ux, _uy = (_ex / _EL, _ey / _EL) if _EL > 1e-9 else (0.0, 0.0)
            # ★★★ 2026-09-30 ✓ **外推方向从“只沿轴”扩到 4 个方向** ✓（学用户手改版 ✓）：
            #   ✗ 只沿轴 ⇒ 在芯片旁边那只脚上，标签**只能往线的正上/正下方向挪** ✗
            #     ⇒ 撞上元件本体 ⇒ 只能越挪越远 ✗（实测：跳到第 4 近的结点、还多带 28.8 单位 ✗）；
            #   ✓ 加上两个**垂方向** ⇒ 它就能像用户那样摆在引脚**旁边** ✓（他那只是往右 15.4 ✓）。
            #   ★ 次序仍先挑“沿轴向外”（= 原来那套、断口上的做法不变 ✓），违例一样时才轮到垂方向 ✓。
            _pts_to_try = []
            for _di, (_dx0, _dy0) in enumerate(((_ux, _uy), (-_ux, -_uy),
                                                (_uy, -_ux), (-_uy, _ux))):
                for _d in LBL_OFFS:
                    _pts_to_try.append((_di, _d, (_end[0] + _dx0 * _d, _end[1] + _dy0 * _d)))
            for _di, _d, _q2 in _pts_to_try:
                # ★ 判据的落点用 **`_end`**（= 引线/搬线端的**落脚结点** ✓）而**不是** `_q2` ✗：
                #   标签是靠引线**挂在 `_end` 上**的 ✓ ⇒ `_end` 那一侧**没被丢** ✓；
                #   丢掉的是 `_pt` → `_end` 之间那一截 ✓（✗ 用 `_q2` 会把“顺着同一条链挪近一点”
                #   也判成危险 ✗ —— 而用户手改版正是这么挪的 ✓）。
                if dead_end_pin(wires, _pt, _end, _term_pts) is not None:
                    continue                   # ★ 丢这一截会把一只真脚孤立 ✗ ⇒ 这个候选不能用 ✓
                for _rot2 in LBL_ROTS:             # ★ 三个朝向都是实测口径 ✓，但 180° 不许挑 ✓
                    #   （2026-09-29 ✓ 拿到 Fritzing 导出后**反解**出“绕板心转” ✓ ⇒
                    #    三个朝向与 Fritzing 画出来的**逐点一致** ✓（各差 < 1e-4 ✓）；
                    #    ✗ 上一版只敢用两个、还抄了别处的 `m31/m32` ✗ ⇒ 摆错 ✓ 见 `_LBL_ATTR` 那条注 ✓）
                    _m2 = sch_net.MATRIX[_rot2]
                    _geom2 = sch_net.label_geom(_q2, _net, _m2)     # ★ **反解** `geometry` ✓
                    _bx2 = sch_net.label_box(_geom2, _net, _m2)     # ★ 本体框：**一处实现** ✓
                    _v2 = 0
                    for _w2 in wires:
                        _a2, _b2 = _w2["p"], _w2["q"]
                        if _w2 is _w:
                            # ★★ 自己那根线**也不许被身体包住** ✗（用户 2026-09-29 看图指出
                            #   “竖着的 GND 和两个 RC 都被穿了” ✓）—— 只在**引脚处留 2 单位**容差 ✓。
                            _L2 = math.dist(_a2, _b2)
                            if _L2 <= 2.0:
                                continue
                            _t2 = 2.0 / _L2
                            if math.dist(_a2, _q2) < math.dist(_b2, _q2):
                                _a2 = (_a2[0] + (_b2[0] - _a2[0]) * _t2,
                                       _a2[1] + (_b2[1] - _a2[1]) * _t2)
                            else:
                                _b2 = (_b2[0] + (_a2[0] - _b2[0]) * _t2,
                                       _b2[1] + (_a2[1] - _b2[1]) * _t2)
                        if SG.seg_hits_box(_a2, _b2, _bx2):
                            _v2 += 1
                    for (_t3, _bb3) in _lbl_boxes:
                        if (_bx2[0] < _bb3[2] and _bb3[0] < _bx2[2]
                                and _bx2[1] < _bb3[3] and _bb3[1] < _bx2[3]):
                            _v2 += 1
                    # ★★★ 2026-09-30 ✓ **标签的脚也不许被别的线贴近** ✗（判据与“脚”同一条 ✓
                    #   `CLEAR_PIN` = 2.03mm ✓）：✗ 原来只查“线穿过旗标本体” ✗ ⇒ 实测标签挪到
                    #   引脚旁之后，另一根线离它的脚只有 **0.85mm** ✗（渲染器当场报“贴近不相连的
                    #   引脚 1 处”✗）= 看着像接上了 ✗ ⇒ 补上这条 ✓（自己那根引线豁免 ✓）。
                    for _w4 in wires:
                        if _w4 is _w:
                            continue
                        if SG.p2seg(_q2, _w4["p"], _w4["q"]) < CLEAR_PIN:
                            _v2 += 1
                    if _d:                                # ★ 伸长的那一截本身也不许蹭脚 ✗
                        for _p3 in PIN_ALL:
                            # ★★ 2026-09-30 ✓ **自己出发的那只脚不算** ✗✗（实测找出来的 ✓）：
                            #   引线是从那只脚上长出来的 ✓ ⇒ 它到引线的距离**恒为 0** ✗ ⇒ 不排它的话
                            #   **每条带引线的候选都白背 1 个违例** ✗ ⇒ 贴在本侧引脚旁边的候选
                            #   **全被否掉** ✗，只能退到 28.8 单位外的结点上 ✗ ——
                            #   而用户手改版恰恰就贴在引脚旁 15.4 单位处 ✓（截图那只 `RC` ✓）。
                            #   容差取全仓统一的 **1 单位** ✓（= §5b ⑫ 那条口径 ✓）。
                            if math.dist((_p3[2], _p3[3]), _end) < 1.0:
                                continue
                            if SG.p2seg((_p3[2], _p3[3]), _end, _q2) < CLEAR_PIN:
                                _v2 += 1
                    for _p3 in PIN_ALL:                   # 标签本体附近不许有别的脚 ✓
                        if (_bx2[0] - CLEAR_PIN < _p3[2] < _bx2[2] + CLEAR_PIN
                                and _bx2[1] - CLEAR_PIN < _p3[3] < _bx2[3] + CLEAR_PIN):
                            _v2 += 1
                    # ★★★ 2026-09-30 ✓ **标签（一个元件 ✓）不许压在/贴住任何元件的本体上** ✗
                    #   —— 用户 2026-09-30 指着截图问“**RC 本体压在了 U1 上，这没有违规吗**？”✓
                    #   （他手改版里那只 `RC` 落在 `(176.48,81.00)` ✓ = **就在 `U1` 方框里** ✗）
                    #   ⇒ 原因：这里原来只查 导线 / 别的标签 / 引脚 ✗，**没查本体框** ✗。
                    #   ★ 留边距用 `CLEAR`（6.0 单位 ≈ 1.7mm ✓）—— 与“导线离元件本体”**同一条** ✓
                    #     （不是 0 ✓：贴着边框看着仍旧是“压住”✗）。
                    for _t6, _bb6 in boxes.items():
                        if _bb6 is None or len(_bb6) < 4:
                            continue
                        if (_bx2[0] - CLEAR < _bb6[2] and _bb6[0] < _bx2[2] + CLEAR
                                and _bx2[1] - CLEAR < _bb6[3] and _bb6[1] < _bx2[3] + CLEAR):
                            _v2 += 1
                    if _pick is None or ((_v2, _rank, _di, _d, _rot2)
                                         < (_pick[0], _pick[1], _pick[2], _pick[3], _pick[4])):
                        _pick = (_v2, _rank, _di, _d, _rot2, _q2, _bx2, _w, _cid, _tk, _dist0)
        if _pick is None:
            print("      ⊘ NL1：本侧 (%.2f,%.2f) 这一侧**找不到能贴标签的地方** ✗ ⇒ 不贴 ✓"
                  % (_pt[0], _pt[1]))
            continue
        _v2, _rank2, _di2, _d2, _rot2, _q2, _bx2, _w, _cid, _tk, _dist0 = _pick
        _other = _w["q"] if _tk == "start_tgt" else _w["p"]
        _end = _w["p"] if _tk == "start_tgt" else _w["q"]
        print("      · NL1 选点 ✓：本侧第 %d 近的结点（离本侧最近的脚 %.1f 单位 ✓）｜ "
              "外推方向 %s ✓ —— 比“贴在断口 (%.2f,%.2f)”近 ✓"
              % (_rank2 + 1, _dist0, ("沿轴向外", "沿轴反向", "垂向 A", "垂向 B")[_di2],
                 _pt[0], _pt[1]))
        _mi = str(next_mi)
        next_mi += 1
        # ★ 只有**沿轴**那两个方向能“搬线端” ✓ —— 垂方向搬过去会把这根线**弄成斜线** ✗
        #   （用户手改版的做法是再加一截垂直引线 ✓ = 下面 `elif` 那条 ✓）。
        if _d2 and _di2 < 2 and end_is_free(wires, _w, _end, PIN_ALL):
            # ★★ 2026-09-29 ✓ 用户定 ✓：**那一端上没有别人** ⇒ **直接把它搬过去** ✓
            #   （= 这根线变长一点点 ✓，标签脚正好落在线端上 ✓）
            #   ⇒ 没有接缝 ⇒ **不会凭空多一个圆点** ✓（判据与正反两面证据见 `end_is_free` ✓）。
            #   ★ 一个坑 ✓：实例**已经建过**了（建实例在前、贴标签在后 ✓）⇒ 搬完必须**重建** ✓；
            #     ✗ 直接 `append` 会把这根线挪到 `<instances>` 末尾 ✗ ⇒ 叠放次序跟着变 ✗ ——
            #     那是**白改** ✓（肉眼与文件都变了 ✓、而需求只是“标签挪个位置”✗）⇒ 按**原位插回** ✓。
            _oldel = _w.get("el")
            _at = list(host).index(_oldel) if _oldel is not None else None
            if _oldel is not None:
                host.remove(_oldel)
            if _tk == "start_tgt":
                _w["p"] = _q2
            else:
                _w["q"] = _q2
            _w[_tk] = ("label", _mi)      # ★ 那一端现在属于**标签** ✓（否则会被当悬空端清掉 ✗）
            _w["el"] = build_wire(tmpl, _w)
            _w["view"] = pm.child(pm.child(_w["el"], "views"), "schematicView")
            if _at is None:
                host.append(_w["el"])
            else:
                host.insert(_at, _w["el"])
            print("      · 直接搬线端 ✓ %s：%s 端 (%.2f,%.2f) ⇒ (%.2f,%.2f) ✓"
                  "（线长 %.1f → %.1f ✓；那一端**没有别人的端点/脚** ✓"
                  " ⇒ 不留接缝、不长多余圆点 ✓）"
                  % (_w["mi"], "p" if _tk == "start_tgt" else "q",
                     _end[0], _end[1], _q2[0], _q2[1],
                     math.dist(_other, _end), math.dist(_other, _q2)))
        elif _d2:
            # ★★ 那一端上**有别人**（别的线端 / 某只脚 ✓）⇒ 那个接头**动不得** ✗ ⇒
            #   原地保留 ✓、从原线端**新拉一小段**（引线 ✓）伸到标签脚 ✓ ⇒ 老接头不动 ✓。
            #   ★ 代价：多一个**接缝** ⇒ Fritzing 会在那儿画个**小圆点** ✓
            #     （≥2 个线端 ✓）—— 这是**换来的**（保接头 ✓），不是白拿的 ✓。
            _stub = {"mi": str(next_mi), "p": _end, "q": _q2, "net": _net,
                     "start_tgt": ("wire", _w, _cid), "end_tgt": ("label", _mi)}
            next_mi += 1
            _stub["el"] = build_wire(tmpl, _stub)
            _stub["view"] = pm.child(pm.child(_stub["el"], "views"), "schematicView")
            host.append(_stub["el"])
            wires.append(_stub)
            wire_by_mi[_stub["mi"]] = _stub
            if _tk == "start_tgt":
                _w["start_tgt"] = ("wire", _stub, "connector1")
            else:
                _w["end_tgt"] = ("wire", _stub, "connector1")
            links.append((_w["mi"], _cid, "schematicTrace",
                          _stub["mi"], "connector0", "schematicTrace"))
            _w, _tk, _cid = _stub, "end_tgt", "connector1"
            print("      · 加引线 ✓ %s：(%.2f,%.2f)→(%.2f,%.2f) ✓（%.1f 单位 ✓）"
                  % (_stub["mi"], _end[0], _end[1], _q2[0], _q2[1], _d2))
        _lbl_boxes.append((_mi, _bx2))
        _lbl_pins.append((_q2[0], _q2[1]))
        _el = build_label(_net, _q2, _mi, rot=_rot2)
        print("      · 标签 ✓ %s（%s ✓）@(%.2f,%.2f) ✓ 朝向 %d° ✓ 挪 %.1f 单位（%s ✓）违例 %d %s｜盒 (%.1f,%.1f→%.1f,%.1f)"
              % (_mi, _net, _q2[0], _q2[1], _rot2, _d2,
                 ("沿轴向外", "沿轴反向", "垂向 A", "垂向 B")[_di2], _v2, "✓" if not _v2 else "✗",
                 _bx2[0], _bx2[1], _bx2[2], _bx2[3]))
        host.append(_el)
        _sub = pm.child(pm.child(_el, "views"), "schematicView")
        _key = "LBL" + _mi
        insts[_key] = {"mi": _mi, "mid": "NetLabelModuleID", "net": _net,
                       "el": _el, "sub": _sub}
        # ★ 两个字典的**键不一样** ✗（实测撞过两次 ✓）：`insts` 用 `_key` ✓，
        #   而 `part_by_mi` 是**按 `mi`** 建的 ✓ ⇒ 写连接时查的是 `part_by_mi[mi]` ✓
        #   （✗ 我上一版写成 `part_by_mi[_key]` ⇒ `KeyError: '90012775'` ✗✗）
        part_by_mi[_mi] = insts[_key]
        _w[_tk] = ("pin", {"ref": _key, "cid": "connector0"})
        links.append((_w["mi"], _cid, "schematicTrace", _mi, "connector0", "schematic"))
        print("      ✓ NL1：标签 %s（%s ✓）@(%.2f,%.2f) ↔ 导线 %s.%s ✓"
              % (_mi, _net, _pt[0], _pt[1], _w["mi"], _cid))

    # ★★★ 2026-09-30 ✓ 标签挪到“本侧引脚旁”之后 ✓，**原来通到断口那一截就成了断头** ✗
    #   ⇒ 顺手**级联清掉** ✓（判据 = 叶子：一端悬空、且那一端上没有终端 ✓）
    if _lbl_jobs:
        _pruned = prune_dangling(wires, PIN_ALL)
        if _pruned:
            _n0 = len(links)
            for _mi0 in sorted(_pruned, key=lambda s: int(s) if str(s).isdigit() else 10 ** 9):
                _w0 = wire_by_mi.pop(_mi0, None)
                if _w0 is None:
                    continue
                if _w0.get("el") is not None and _w0["el"] in list(host):
                    host.remove(_w0["el"])
                if _w0 in wires:
                    wires.remove(_w0)
            for _w0 in wires:
                for _tk in ("start_tgt", "end_tgt"):
                    _t0 = _w0.get(_tk)
                    if (_t0 and _t0[0] == "wire" and _t0[1] is not None
                            and str(_t0[1].get("mi")) in _pruned):
                        _w0[_tk] = None
            links = [L for L in links
                     if str(L[0]) not in _pruned and str(L[3]) not in _pruned]
            # ★★★ 2026-09-30 ✓ **清完之后，端点正好落在“真脚 / 标签”上的，要当场补连接** ✓：
            #   ✗ 实测漏网的一种 ✗：标签的新落脚点**就是某只脚所在的结点**（`RC` 那只落在
            #     `R1` 脚上 ✓）⇒ 给它拉的那截引线，`start_tgt` 指的是**原来那根线** ✗
            #     ⇒ 那根线被清掉之后目标被置空 ✗ ⇒ 图上**引线端点正压在脚上、却没有连接** ✗
            #     = “看着接上、其实没接” ✗（判据 ② 的 `(B)` 正好抓住它 ✓ 实测 `(B)=1` ✗）。
            #   ✓ 口径：**裸端点**（目标为空 ✓）落在某只脚 / 某个标签的画出位置上（≤ 0.05 ✓）
            #     ⇒ 登记连接 ✓（与“同点即连”同一条思路 ✓：Fritzing 的连接是**声明**的 ✓，
            #       “端点重合”本身不算连 ✓）。
            _nfix = 0
            for _w0 in wires:
                for _cid0, _e0, _tk0 in (("connector0", _w0["p"], "start_tgt"),
                                         ("connector1", _w0["q"], "end_tgt")):
                    if _w0.get(_tk0) is not None:
                        continue
                    _hit = None
                    for (_r5, _c5, _x5, _y5) in PIN_ALL:
                        # ★ `PIN_ALL` 的元素是 `(实例键, 连接器 id, x, y)` ✓ ——
                        #   ✗ 我第一版把 `_c5` 当成 `{"ref":…, "cid":…}` 那个字典了 ✗
                        #   （字典是**目标元组**里的第二项 ✓，不是这张表里的 ✗）⇒ `AttributeError` ✗。
                        if abs(_x5 - _e0[0]) < 0.05 and abs(_y5 - _e0[1]) < 0.05:
                            _hit = (_r5, _c5)
                            break
                    if _hit is None:
                        continue
                    _d5 = insts.get(_hit[0]) or {}
                    if _d5.get("mi") is None:
                        continue
                    _w0[_tk0] = ("pin", {"ref": _hit[0], "cid": _hit[1]})
                    links.append((_w0["mi"], _cid0, "schematicTrace",
                                  _d5["mi"], _hit[1], "schematic"))
                    _nfix += 1
            if _nfix:
                print("      ↪ 断头清理后**补连接** %d 处 ✓（端点正落在脚/标签上、原来没声明 ✗）"
                      % _nfix)
            print("   ★ 标签挪位后的**断头**清理 ✓：删 %d 根 ✓（%s）—— 都是“一端悬空、那一端"
                  "又没有终端”的叶子 ✓ ⇒ 不动任何端子之间的连通 ✓；顺手剔掉 %d 条连接 ✓"
                  % (len(_pruned), "、".join(sorted(_pruned)), _n0 - len(links)))

    # ★★★ 2026-09-30 ✓ **`--ground=<网>`：给地网挂接地符号** ✓（用户 2026-09-29 的改法 ✓）
    #   · 那些网**不切** ✓（见上面两处 `continue` ✓）⇒ 电气上仍是**一整张网** ✓（导线连着 ✓）；
    #   · 每个功能模块挂**一个** ✓（= 用户手改版里那两个的分布 ✓：A 区一个、B 区一个 ✓）；
    #     挂点由 `ground_spots` **挑** ✓（候选表与打分口径都在那儿 ✓）。
    #   ★★ 为什么“不切”也能表达“两块地” ✓：Fritzing 的 `LocalGrounds` 把全图
    #     `GND/VSS/GROUND` 的脚拉成**一张**网 ✓（依据在 `sch_net.py` 那段源码笔记里 ✓）
    #     ⇒ 两个符号**不必用线相连**就同网 ✓ ⇒ “各模块各摆一个符号”在电气上仍是一张地网 ✓✓。
    for _gnet in sorted(GROUND_NETS):
        # ★ 障碍里要带**元件的文字**（位号 + 参数 ✓）：实测 v34 第一版把符号挂到了 `C2` 的
        #   `100 nF` 上 ✗ —— 图上就是“符号的横线把 `100` 划掉”✗（判据只算了本体框 ✗）。
        #   盒子用 `sch_text.label_bbox` ✓（与 `relabel()` **同一份**口径 ✓）。
        _txb = []
        for _t, _d in insts.items():
            _lab = PR.LAB.get(_d["mi"]) or {}
            _ln2, _fs2 = _lab.get("lines") or [], _lab.get("fs", 5.0)
            _tg = pm.child(_d["sub"], "titleGeometry")
            if not _ln2 or _tg is None or (_tg.get("visible") or "true") == "false":
                continue
            _txb.append((_t, ST.label_bbox(pm.num(_tg.get("x")), pm.num(_tg.get("y")),
                                           _fs2, _ln2)))
        _spots = ground_spots(_gnet, wires, PIN_ALL, boxes or {}, _lbl_boxes, LABEL_MOD_A, _txb)
        if not _spots:
            print("   ⊘ **--ground**：网 `%s` 挑不出挂点 ✗ ⇒ **不挂** ✓（如实报出 ✓）" % _gnet)
            continue
        for (_grp, _dist, _v, _dd, _P, _Q, _ext, _why) in _spots:
            _mi = str(next_mi)
            next_mi += 1
            _gcnt += 1
            if _ext is not None:             # ★ 延长那根线 ✓（= 用户的做法 ✓，不加新实例 ✓）
                _tk = "start_tgt" if math.dist(_ext["p"], _P) < 0.05 else "end_tgt"
                _cid = "connector0" if _tk == "start_tgt" else "connector1"
                _oldel = _ext.get("el")
                _at = list(host).index(_oldel) if _oldel is not None else None
                if _oldel is not None:
                    host.remove(_oldel)
                if _tk == "start_tgt":
                    _ext["p"] = _Q
                else:
                    _ext["q"] = _Q
                _ext["el"] = build_wire(tmpl, _ext)
                _ext["view"] = pm.child(pm.child(_ext["el"], "views"), "schematicView")
                if _at is None:
                    host.append(_ext["el"])
                else:
                    host.insert(_at, _ext["el"])
                _att, _atk, _acid = _ext, _tk, _cid
                print("      · **延长导线** ✓ %s：%s 端 (%.2f,%.2f) ⇒ (%.2f,%.2f) ✓（+%.1f 单位 ✓）"
                      % (_ext["mi"], "p" if _tk == "start_tgt" else "q",
                         _P[0], _P[1], _Q[0], _Q[1], _dd))
            else:                            # ★ 加一小段引线 ✓（电气靠后面的“同点即连”✓）
                _lead = {"mi": str(next_mi), "p": _P, "q": _Q, "net": _gnet,
                         "start_tgt": None, "end_tgt": None}
                next_mi += 1
                _lead["el"] = build_wire(tmpl, _lead)
                _lead["view"] = pm.child(pm.child(_lead["el"], "views"), "schematicView")
                host.append(_lead["el"])
                wires.append(_lead)
                wire_by_mi[_lead["mi"]] = _lead
                _att, _atk, _acid = _lead, "end_tgt", "connector1"
                print("      · **引线** ✓ %s：(%.2f,%.2f)→(%.2f,%.2f) ✓（%.1f 单位 ✓）"
                      % (_lead["mi"], _P[0], _P[1], _Q[0], _Q[1], _dd))
            _el = build_ground(_mi, _gcnt, _Q)
            host.append(_el)
            _sub = pm.child(pm.child(_el, "views"), "schematicView")
            _key = "GND" + _mi
            insts[_key] = {"mi": _mi, "mid": "GroundModuleID", "net": _gnet,
                           "el": _el, "sub": _sub}
            part_by_mi[_mi] = insts[_key]
            _att[_atk] = ("pin", {"ref": _key, "cid": "connector0"})
            links.append((_att["mi"], _acid, "schematicTrace", _mi, "connector0", "schematic"))
            _lbl_boxes.append((_mi, sch_net.ground_box(sch_net.ground_geom(_Q))))
            print("      ✓ **接地符号 Ground%d** ✓ %s（组 %s ✓）脚 (%.2f,%.2f) ✓ 离本组脚 %5.1f ✓ "
                  "违例 %d %s ｜ %s"
                  % (_gcnt, _mi, _grp, _Q[0], _Q[1], _dist, _v,
                     "✓" if not _v else "✗", "、".join(_why) if _why else "（干净 ✓）"))

    # ★★★ 2026-09-30 ✓ `--trim=<网>`：**剪冗余 ＋ 改接点** ✓（口径见 `trim_plan` ✓）
    #   ★★ 位置**改到“标签/接地都挂完之后”** ✗✓（原来放在它们之前 ✗ ⇒ 少算了一条语义 ✗✗）：
    #     同名标签 / 接地符号在 Fritzing 里**本来就同网** ✓（`LocalGrounds` / 同名即连 ✓）
    #     ⇒ 它们接的两侧**不用线连着也算通** ✓ ⇒ 用户手改版删掉“GND 左侧回路”就是这么成立的 ✓
    #     （实测：那三根是 `D3.c0/c1 ＋ C1.c1` **唯一**的线路径 ✗，但两侧靠两个**接地符号**同网 ✓
    #     ⇒ 电气上没断 ✓，`check_netlist.py` 也照这个语义判 ✓）。✗ 放在挂之前 ⇒ 这块永远删不掉 ✗。
    #   ★ 另：删掉的线要把 `links` 里指向它的条目也剔掉 ✓（links 早就收集过了 ✓）。
    if TRIM_NETS:
        _merge = []
        for _w0 in wires:
            for _tk in ("start_tgt", "end_tgt"):
                _t0 = _w0.get(_tk)
                if not (_t0 and _t0[0] == "pin" and _t0[1] is not None):
                    continue
                _d0 = insts.get(str(_t0[1].get("ref"))) or {}
                _mid0 = _d0.get("mid") or ""
                _pt0 = _w0["p"] if _tk == "start_tgt" else _w0["q"]
                if sch_net.is_ground_symbol(_mid0):
                    _merge.append((_pt0, "@GROUND"))          # ★ 全图地脚 = 一张网 ✓
                elif sch_net.is_label_module(_mid0):
                    _merge.append((_pt0, "@LBL:" + (_d0.get("net") or "")))   # ★ 同名即同网 ✓
        if _merge:
            print("   ★ `--trim`：**同名标签 / 接地符号先按 Fritzing 语义并起来** ✓（%d 个脚 ✓ —— "
                  "不并的话，靠符号同网的那两块会被误判成“删了就断” ✗）" % len(_merge))
        for _tnet in sorted(TRIM_NETS):
            _del, _add, _rep = trim_plan(_tnet, wires, boxes or {}, _lbl_boxes, PIN_ALL,
                                         K=K_TRIM, merge=_merge)
            for _l in _rep:
                print(_l)
            for _mi0 in sorted(_del, key=lambda s: int(s) if str(s).isdigit() else 10 ** 9):
                _w0 = wire_by_mi.pop(_mi0, None)
                if _w0 is None:
                    continue
                if _w0.get("el") is not None and _w0["el"] in list(host):
                    host.remove(_w0["el"])
                if _w0 in wires:
                    wires.remove(_w0)
            for _w0 in wires:                    # 指向被删线的那些头尾要清掉 ✓（悬空端交给后面判 ✓）
                for _tk in ("start_tgt", "end_tgt"):
                    _t0 = _w0.get(_tk)
                    if (_t0 and _t0[0] == "wire" and _t0[1] is not None
                            and str(_t0[1].get("mi")) in _del):
                        _w0[_tk] = None
            if _del:
                _n0 = len(links)
                links = [L for L in links
                         if str(L[0]) not in _del and str(L[3]) not in _del]
                print("   ★ 剪掉的线上原本还挂着 %d 条连接 ✓ ⇒ 一并剔除 ✓" % (_n0 - len(links)))
            for (_p, _ti, _pt) in _add:          # 改接后的新路径 ✓（中继点靠“同点即连”✓）
                for _j in range(len(_p) - 1):
                    _seg = {"mi": str(next_mi), "p": _p[_j], "q": _p[_j + 1], "net": _tnet,
                            "start_tgt": None, "end_tgt": None}
                    next_mi += 1
                    if _j == 0 and _ti == 0:
                        _seg["start_tgt"] = _pt
                    if _j == len(_p) - 2 and _ti == len(_p) - 1:
                        _seg["end_tgt"] = _pt
                    _seg["el"] = build_wire(tmpl, _seg)
                    _seg["view"] = pm.child(pm.child(_seg["el"], "views"), "schematicView")
                    host.append(_seg["el"])
                    wires.append(_seg)
                    wire_by_mi[_seg["mi"]] = _seg
                    # ★★ 新线**自己那一端要接线** ✗✗（2026-09-30 实测撞上 ✓）：`links` 是**早先**
                    #   收集好的 ✓ —— ✗ 那时这根线还不存在 ⇒ 它的 `<connect>` 永远写不出来 ✗ ⇒
                    #   实测 `(B)=1` 假连线 ✗（`Wire90012784` 的端落在 `U1.connector5` 上、
                    #   表里却声明为空 ✗）⇒ 新线的那一端必须**在这里补一条连接** ✓。
                    for _tk2, _cid2 in (("start_tgt", "connector0"), ("end_tgt", "connector1")):
                        _t2 = _seg.get(_tk2)
                        if not (_t2 and _t2[0] == "pin" and _t2[1] is not None):
                            continue
                        _d2 = insts.get(str(_t2[1].get("ref"))) or {}
                        if _d2.get("mi") is not None:
                            links.append((_seg["mi"], _cid2, "schematicTrace",
                                          _d2["mi"], _t2[1].get("cid"), "schematic"))

    # ★★★ 2026-09-30 ✓ **同网 ＋ 共端点 ＋ 完全共线**的两根导线 ⇒ **并成一根** ✗✗
    #   ★ 为什么（用户 2026-09-30 指着截图说「**红色线上多了一个接线点**」✓）：
    #     `--trim` 的“改接”会把一条**长直线切成两段共线的线** ✗（实测 5V：
    #     `(29.78,-57.60)→(49.38,-57.60)` ＋ `(49.38,-57.60)→(180.38,-57.60)` ✗ ✓），
    #     而 Fritzing 会在那个**切口**上画一个**小圆点** ✓ ⇒ 看着就像“凭空多出一个接线点” ✗
    #     （用户手改版那条是**一整根** ✓ ⇒ 没有点 ✓）。
    #   ★ 判据（很保守 ✓）：两点①同网 ✓ ②在那一点上**恰好只有这两个线端**（度 2 ✓）
    #     ③从该点伸向两边的方向**严格反向**（叉积≈0 ✓、点积<0 ✓）⇒ 才并 ✓；
    #     折角（不共线 ✓）**一律不动** ✗（手改版里那些折角就是普通接头 ✓ 不该并 ✓）。
    #   ★ 合并后要：重建元素（保持原**叠放位置** ✓）、把指向被并那根的连接剔掉 ✓、
    #     两端归属照旧跟着**外侧**两个端走 ✓（内部那个接头从此不存在 ✓）。
    #   ★★ 两条**安全条件**（2026-09-30 第一版没写、当场撞了 ✗）：
    #     ① 合并点上**不许有真终端**（脚 / 标签 ✓）—— 实测：标签那截引线的接头
    #        正是 `R1` 的脚 ✗，并进去就等于“让线**穿过**那只脚”✗ ⇒ 脚上没有线端了 ✗
    #        ⇒ 判据 `(A)/(B)` 当场各报 1 ✗；
    #     ② 只在**带开关**（`--label/--ground/--trim` ✓）时才跑 —— 无开关时输出必须与
    #        `v29` 逐字节相同 ✓（实测：不限制的话它会去并 `v29` 自己那两段 ✗ ⇒ 26/26 变 25/26 ✗）。
    if TRIM_NETS or _lbl_jobs or GROUND_NETS:
      for _round in range(200):
        _pts = {}
        for _w0 in wires:
            for _tk0, _e0, _o0 in (("start_tgt", _w0["p"], _w0["q"]),
                                   ("end_tgt", _w0["q"], _w0["p"])):
                _pts.setdefault(_rk(_e0), []).append((_w0, _tk0, _o0))
        _done = False
        for _k, _lst in _pts.items():
            if len(_lst) != 2:
                continue
            (_w1, _tk1, _o1), (_w2, _tk2, _o2) = _lst
            if _w1 is _w2 or _w1.get("net") != _w2.get("net"):
                continue
            if _w1["mi"] not in wire_by_mi or _w2["mi"] not in wire_by_mi:
                continue
            _c = _k
            if any(abs(_px - _c[0]) < 0.05 and abs(_py - _c[1]) < 0.05
                   for (_r7, _c7, _px, _py) in PIN_ALL):
                continue                           # ① 那一点上有**真脚** ⇒ 不许并 ✗
            if any(abs(_px - _c[0]) < 0.05 and abs(_py - _c[1]) < 0.05
                   for (_px, _py) in _lbl_pins):
                continue                           # ① 那一点上是**标签的脚** ⇒ 不许并 ✗
            _va = (_o1[0] - _c[0], _o1[1] - _c[1])
            _vb = (_o2[0] - _c[0], _o2[1] - _c[1])
            _la, _lb = math.hypot(*_va), math.hypot(*_vb)
            if _la < 1e-6 or _lb < 1e-6:
                continue
            _cr = abs(_va[0] * _vb[1] - _va[1] * _vb[0]) / (_la * _lb)
            _dt = (_va[0] * _vb[0] + _va[1] * _vb[1]) / (_la * _lb)
            if _cr > 1e-3 or _dt > -0.999:        # 不严格共线反向 ⇒ 折角 ✓ 不动 ✓
                continue
            _at = list(host).index(_w1["el"]) if _w1.get("el") in list(host) else None
            if _w1.get("el") in list(host):
                host.remove(_w1["el"])
            if _w2.get("el") in list(host):
                host.remove(_w2["el"])
            _far2 = "end_tgt" if _tk2 == "start_tgt" else "start_tgt"
            if _tk1 == "start_tgt":
                _w1["p"], _w1["q"] = _o1, _o2
                _w1["start_tgt"] = _w1.get("start_tgt")     # 外侧端照旧 ✓
                _w1["end_tgt"] = _w2.get(_far2)
            else:
                _w1["q"], _w1["p"] = _o1, _o2
                _w1["end_tgt"] = _w1.get("end_tgt")
                _w1["start_tgt"] = _w2.get(_far2)
            _w1["el"] = build_wire(tmpl, _w1)
            _w1["view"] = pm.child(pm.child(_w1["el"], "views"), "schematicView")
            if _at is None:
                host.append(_w1["el"])
            else:
                host.insert(_at, _w1["el"])
            links = [L for L in links
                     if not (str(L[0]) == str(_w1["mi"]) and str(L[3]) == str(_w2["mi"]))
                     and not (str(L[3]) == str(_w1["mi"]) and str(L[0]) == str(_w2["mi"]))]
            # ★★ 别的线 / 别的连接里**还指着被并掉那根**的要改指 ✓（✗ 不改就 `KeyError` ✗
            #   实测：写文件时 `part_by_mi['90012736']` 找不到 ✗）—— 口径：
            #   · 指的是它**外侧那一端** ⇒ 改指 w1 对应的那一端 ✓；
            #   · 指的是它**被并掉的那一端**（= 现在不存在的那个接头 ✓）⇒ 这条连接**丢掉** ✓。
            _c2_share = "connector0" if _tk2 == "start_tgt" else "connector1"
            _c2_far = "connector1" if _tk2 == "start_tgt" else "connector0"
            _c1_far = "connector1" if _tk1 == "start_tgt" else "connector0"
            _fin = []
            for _L in links:
                _a = (str(_L[0]), _L[1])
                _b = (str(_L[3]), _L[4])
                if _a[0] == str(_w2["mi"]) or _b[0] == str(_w2["mi"]):
                    _cid2 = _a[1] if _a[0] == str(_w2["mi"]) else _b[1]
                    _other1 = (_b[0] if _a[0] == str(_w2["mi"]) else _a[0]) == str(_w1["mi"])
                    if _other1 or _cid2 == _c2_share:
                        continue
                    if _a[0] == str(_w2["mi"]):
                        _a = (str(_w1["mi"]), _c1_far)
                    else:
                        _b = (str(_w1["mi"]), _c1_far)
                _fin.append((_a[0], _a[1], _L[2], _b[0], _b[1], _L[5]))
            links[:] = _fin
            for _w0 in wires:
                for _tk0 in ("start_tgt", "end_tgt"):
                    _t0 = _w0.get(_tk0)
                    if (_t0 and _t0[0] == "wire" and _t0[1] is not None
                            and str(_t0[1].get("mi")) == str(_w2["mi"])):
                        _w0[_tk0] = (None if _t0[2] == _c2_share
                                     else ("wire", _w1, _c1_far))
            wires.remove(_w2)
            wire_by_mi.pop(_w2["mi"], None)
            print("      ⋈ 共线合并 ✓ %s ＋ %s ⇒ %s：%.1f ＋ %.1f ⇒ %.1f 单位 ✓"
                  "（**去掉那个多余的接线点** ✓）"
                  % (_w1["mi"], _w2["mi"], _w1["mi"],
                     math.dist(_o1, _c), math.dist(_c, _o2), math.dist(_o1, _o2)))
            _done = True
            break
        if not _done:
            break

    # ★★ “**同点即连**” ✓（2026-09-28 ✓ 电源轨架构必需 ✓）：两条导线的**端点重合** ⇒ 互记连接 ✓
    #   ★ 为什么必需 ✗：Fritzing 的连接是**端点对端点** ✓ ⇒ 支线落在干线**中段**上连不上 ✗
    #     ⇒ 电源轨已在**每个接头处断开** ✓（见 `RAILS` ✓），这里只负责把重合的端点连起来 ✓。
    #   ★★ **只连同一个网的** ✓（否则就成**短路**了 ✗✗）—— 跨网的重合**不连**、但**如实报出** ✓。
    _eps = {}
    for w in wires:
        for cid, p, tgt in (("connector0", w["p"], w["start_tgt"]),
                            ("connector1", w["q"], w["end_tgt"])):
            _eps.setdefault((round(p[0], 3), round(p[1], 3)), []).append((w, cid, tgt))
    _add, _skip = 0, 0
    for _v in _eps.values():
        for i in range(len(_v)):
            for j in range(i + 1, len(_v)):
                (w1, c1, t1), (w2, c2, t2) = _v[i], _v[j]
                if w1 is w2:
                    continue
                if w1.get("net") != w2.get("net"):
                    _skip += 1
                    continue
                # ★★ 只在“**至少一侧还没有归属**”时才补 ✓（2026-09-28 ✓）：
                #   ✗ 初版不看归属 ⇒ 把链上“两根导线在**同一个引脚点**相接”的情形也补了一遍 ✗
                #     ⇒ 基线档凭空多出 **37 条冗余连接** ✗ ⇒ **破坏 v18 的可复现性** ✗
                #       （几何/指标/网表都一样 ✓，但写出来的文件不同了 ✗ —— 这就不算复现 ✗）。
                #   ✓ 加上这一条 ⇒ 链内的接头（两侧都已归属 ✓）**不动** ✓；
                #     只有“**悬空的端点正好落在别人身上**”（= 电源轨支线 ✓）才补 ✓。
                # ★★★ “**真的接到东西了吗**” ✓（2026-09-28 修 ✗ —— **这是本轮的关键 bug** ✓）：
                #   ✗ 原来写的是 `t1 is not None and t2 is not None` ✗ —— 可是**“脚→轨”支线**
                #     与**轨的每一段**，它们的 `end_tgt` 都是 `("pin", s["to"])`，而 `s["to"] is None`
                #     ⇒ 也就是 **`("pin", None)`** ✗ ⇒ **它不是 `None`** ✗✗
                #     ⇒ 两边都“非 None” ⇒ 一律 `continue` ✗ ⇒ 实测那一行就是 **“补 0 对”** ✗✗
                #     ⇒ **支线端点落在轨上却没有任何连接** ✗ ⇒ **Fritzing 里看着就是断的** ✗✗✗
                #   ★ 证据（用户的眼睛先发现 ✓，机器形态随后对上 ✓）：
                #     · 用户的导出 `t58_1_图示.svg`：“**很多线没有接上**”✗；
                #     · 写文件时：**65 根导线只有 71 条连接** ✗（v18 是 46/79 ✓ —— 每根线两端
                #       本该各有一条 ✓）；
                #     · 导出的 svg 里 `<circle>`（接点圆点）**76 → 24** ✗、`stroke="none"` 115 → 63 ✗
                #       —— 两边都少 **52** ✓（同一个数 ⇒ 同一批元素 ✓）。
                #   ✓ 正解：按“**裸端点** = `("pin", None)`”算悬空 ✓ ⇒ 支线端点 ↔ 轨端点才会补上 ✓。
                #   ★ v18 **不受影响** ✓：它是链式 ✓，每段两端都有归属 ✓、没有 `("pin", None)` 端点 ✓
                #     （那种端点只在 `RAILS` / `STAR_NETS` 下出现 ✓）⇒ 补的仍是 0 对 ✓、可复现 ✓。
                _live1 = t1 is not None and t1[1] is not None
                _live2 = t2 is not None and t2[1] is not None
                if _live1 and _live2:
                    continue
                links.append((w1["mi"], c1, "schematicTrace", w2["mi"], c2, "schematicTrace"))
                _add += 1
    print("   ★ 同点即连 ✓：补 %d 对（点重合、同网、**且至少一侧是裸端点** ✓）；"
          "**跨网重合 %d 对不连** ✓（不连才是对的 ✓）" % (_add, _skip))

    # ★★★ 2026-10-03 ✓ **「端点压在**同网**另一根线的中段上」也要连** ✓（用户报的 bug ✓）
    #   病灶（实测 ✓，`_work/_all_wires.py` 逐根打印 ✓）：
    #     `Wire90013960  (180.378,-11.000)…(180.378,-45.000)  connector0→[LED2.connector3]
    #                                                        connector1→[ ]` ✗✗
    #     —— 那是 `LED2.VDD` 的支线 ✓，它的**远端落在 5V 轨的中段**上 ✓
    #     （`(180.378,-45.0)` 落在 `(180.000,-45.0)→(230.178,-45.0)` 上 ✓，只差 **0.378 单位
    #      = 0.107 mm** ✗ —— 因为 `LED2.VDD` 的脚列 x=180.378 与 `C2.c0` 的脚列 x=180.000
    #      **本来就差 0.378** ✗）；而轨的断点表里**没有**这个 x ✗（断点取自"落在轨上的支线
    #     落点" ✓，这一条不知为何没进去 —— 不管为什么 ✓，**判据本身就不该依赖它** ✓）
    #     ⇒ 上面那遍"同点即连"只认**端点重合** ✗ ⇒ 判不出来 ✗ ⇒ 这条支线 `connector1`
    #     **一条连接都没有** ✗ ⇒ **Fritzing 里 VDD 根本不在 5V 网里** ✗（用户截图 ✓）。
    #   ★ 口径依据（§13 ✓ **与 Fritzing 同源** ✓）：Fritzing **自己另存时就会补写**
    #     "几何上真碰上的 `Wire↔Wire` 接头" ✓ ⇒ 「端点压在另一根线的段上」= 一个 **T 形接头** ✓
    #     （它也会在那儿画接点圆点 ✓）⇒ 补这条连接是**对齐它** ✓，不是自造语义 ✓。
    #   ★ 只连**同网** ✓（跨网重合仍**不连** ✓，与上一遍同一个口径 ✓）。
    _add2 = 0
    _seg_of = [(w, w["p"], w["q"], w.get("net")) for w in wires
               if math.dist(w["p"], w["q"]) > 1e-9]
    for _w in wires:
        for _cid, _pt, _tk in (("connector0", _w["p"], _w["start_tgt"]),
                               ("connector1", _w["q"], _w["end_tgt"])):
            if _tk is not None and _tk[1] is not None:
                continue                      # 已经有归属 ⇒ 不动 ✓（不许多嘴 ✓）
            for (_o, _a, _b, _net) in _seg_of:
                if _o is _w or _net != _w.get("net"):
                    continue
                if SG.p2seg(_pt, _a, _b) > 0.05:
                    continue                  # 不在它的段上 ✗
                _d0, _d1 = math.dist(_pt, _a), math.dist(_pt, _b)
                if min(_d0, _d1) < 0.05:
                    continue                  # 就是它的**端点** ⇒ 上一遍已经管了 ✓
                _oc = "connector0" if _d0 <= _d1 else "connector1"
                links.append((_w["mi"], _cid, "schematicTrace",
                              _o["mi"], _oc, "schematicTrace"))
                _add2 += 1
                print("   ★ **端点压在别人中段上** ✓ ⇒ 补接头 ✓：`%s.%s` (%.3f,%.3f) 压在 "
                      "`%s` (%.3f,%.3f)→(%.3f,%.3f) 上（离段 %.4f 单位 = %.4f mm ✓，网 %s ✓）"
                      % (_w["mi"], _cid, _pt[0], _pt[1], _o["mi"], _a[0], _a[1], _b[0], _b[1],
                         SG.p2seg(_pt, _a, _b), SG.p2seg(_pt, _a, _b) * 25.4 / 90.0, _net))
    if _add2:
        print("   ★ 「压中段」补接头 ✓：**%d 条** ✓（✗ 它们原来**一条连接都没有** ✗ ⇒ "
              "Fritzing 里就是断的 ✗）" % _add2)
    else:
        print("   ★ 「压中段」补接头 ✓：0 条 ✓（没有端点压在别人中段上 ✓）")

    # ★ 去重（2026-09-26）：链上同一对"导线↔导线"会从两头各收集一次 ✗ ⇒
    #   不去重就会写出两条一模一样的 <connect> ✗（实测 Wire…connector1 里出现两条 ✓）
    seen, uniq = set(), []
    for L in links:
        key = tuple(sorted([(L[0], L[1]), (L[3], L[4])]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(L)
    links = uniq

    for (a_mi, a_cid, a_layer, b_mi, b_cid, b_layer) in links:   # 两侧各记一份 ✓
        if a_mi in wire_by_mi:
            add_conn(wire_by_mi[a_mi]["view"], a_cid, b_cid, b_mi, b_layer, a_layer)
        else:
            add_conn(part_by_mi[a_mi]["sub"], a_cid, b_cid, b_mi, b_layer, a_layer)
        if b_mi in wire_by_mi:
            add_conn(wire_by_mi[b_mi]["view"], b_cid, a_cid, a_mi, a_layer, b_layer)
        else:
            add_conn(part_by_mi[b_mi]["sub"], b_cid, a_cid, a_mi, a_layer, b_layer)

    # ★★★ 2026-09-30 ✓ **`--relabel`：布完线再摆一次位号** ✓（用户点名的一手 ✓）
    #   · 为什么必须在这里 ✗：`relabel()` 在 `emit()` 之前跑过 ✓（line 2780 ✓），
    #     那时它只知道“**计划的**导线” ✗；而 `emit()` 之后导线**还会变** ✓：
    #     标签引线 ✓、改接出来的新线 ✓、接地引线 ✓、共线合并 ✓ ⇒ 实测 `U1` 的位号
    #     正好压在新拉的一根线上 ✗（渲染器每次都如实报“位号 U1 压导线”✗）。
    #   · ✓ 正解（用户 2026-09-30 定的思路 ✓）：**位号可以自由挪 ✓、导线挪一次要牵动全局 ✗**
    #     ⇒ 拿**最终导线**当障碍，**再跑一遍同一个 `relabel()`** ✓（候选位 / 权重 /
    #     判碰**都是它那一套** ✓ —— 不另写第二份 ✗）。
    if RELABEL_AFTER:
        relabel(insts, boxes, [(w["p"], w["q"]) for w in wires], extra=True)
        print("   ★ `--relabel` ✓：已拿最终 %d 根导线当障碍重摆位号 ✓（候选位多一圈 ✓）"
              % len(wires))

    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(sroot, encoding="utf-8")
    print("网络配色（原理图官方色 ✓）：" + " ｜ ".join(
        "%s=%s" % (n, NET_COLOR.get(n, "?")) for n in sorted(nets_segs)))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n.endswith(".fz") else z.read(n))
    print("写入: %s（%d 根导线、%d 条连接 ✓）" % (out_path, len(wires), len(links)))


COLORS = ["#c00000", "#0070c0", "#00a050", "#c08000", "#8000c0",
          "#00a0a0", "#c060a0", "#606060", "#a0a000", "#004080"]


def draw_preview(path, base_svg, insts, nets_segs, fit):
    r"""预览 = **Fritzing 自己导出的 SVG**（真符号 ✓）+ 我的走线叠在上面 ✓

    ★ 2026-09-26 用户指出：不许自创一套元件图标 ✗ —— 元件图形完全来自 Fritzing 导出 ✓。
    叠层用**拟合出来的**全局映射 ✓（导出 = s·sketch + A ✓，s≈0.8 = 1/1.25 ✓）。
    """
    txt = open(base_svg, encoding="utf-8").read()
    sx, ax, rx = fit["x"]
    sy, ay, ry = fit["y"]
    print("预览映射: x %.6f/%.3f（残差 %.4f）  y %.6f/%.3f（残差 %.4f）"
          % (sx, ax, rx, sy, ay, ry))
    L = ['<g transform="translate(%.4f,%.4f) scale(%.6f,%.6f)" fill="none">' % (ax, ay, sx, sy)]
    for i, (net, segs) in enumerate(sorted(nets_segs.items())):
        c = COLORS[i % len(COLORS)]
        for s in segs:
            d = " ".join("%s%.1f,%.1f" % ("M" if k == 0 else "L", p[0], p[1])
                         for k, p in enumerate(s["path"]))
            L.append('<path d="%s" stroke="%s" stroke-width="1.15"/>' % (d, c))
        p = segs[0]["path"][0]                 # 网名只作汇总标注（不入 .fzz ✓）
        L.append('<text x="%.1f" y="%.1f" font-size="14" fill="%s" stroke="none">%s</text>'
                 % (p[0] + 6, p[1] - 5, c, net))
    L.append("</g>")
    out = txt.replace("</svg>", "\n".join(L) + "\n</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
