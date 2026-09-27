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
import sch_box as SB                            # noqa: E402

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

    def walk(el, m, pid):
        t = el.get("transform")
        m2 = mul(m, parse_tf(t)) if t else m
        if el.get("partID"):
            pid = el.get("partID")
            ruler.setdefault(pid, {"origin": None, "pins": {}})
        if pid in ruler and el.get("id") == "schematic" and ruler[pid]["origin"] is None:
            ruler[pid]["origin"] = apply(m2, 0, 0)
        i = el.get("id") or ""
        mm = re.fullmatch(r"connector(.+?)(terminal|pin)", i)
        if mm and pid in ruler and el.get("x") is not None:
            ruler[pid]["pins"].setdefault("connector" + mm.group(1),
                                          apply(m2, float(el.get("x")), float(el.get("y"))))
        for c in el:
            walk(c, m2, pid)
    walk(root, (1, 0, 0, 1, 0, 0), None)
    return ruler

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
# ★★ `HARD_OVL`：**导线不许与已布好的线压在同一条直线上** ✓（用户规则② 的**真闸门** ✓，2026-09-28 ✓）
#   病症（实测 ✓，`t27_1` = v15 + `--hardpin` ✓）：用户规则②（「**不同的导线，不能重叠**」✓）
#     原来**只靠软代价**压 ✗（`wt = INT_W[0]×nov + …` ✓）⇒ 一开 `--hardpin` 候选集变小 ⇒
#     它**退回 1 对** ✗✗（`Wire90012917 (-6,9)→(22.6,9)` 与 `Wire90012918 (22.6,9)→(10.4,9)`
#     在 `y=9` 上压了 12.2 单位 ✓）⇒ **硬规则不能用软代价表达** ✗（与 `HARD_BODY` 同一个理由 ✓）。
#   ★ 与 `HARD_BODY`/`HARD_PIN` 同一套路 ✓：**只删候选** ✗，不动代价函数与档位次序 ✓；
#     删到一条不剩 ⇒ 调用处保留旧候选集 + 告警 ✓（不许把端点接不上 ✗）。
#   ★ 判据仍只有一份 ✓（`sch_geom.near_overlap` ✓）；`--noovl` 关掉 ⇒ A/B 对照 ✓。
HARD_OVL = True
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
    ruler = build_ruler(svg)
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
        pins, pins_export = {}, {}
        if pid:
            for cid, (ex, ey) in ruler[pid]["pins"].items():
                pins_export[cid] = (ex, ey)
                pins[cid] = sk(ex, ey)
        if PINS_FIX.get(mi):                  # ★ 优先用标定值 ✓（精确 ✓）
            for cid, p in PINS_FIX[mi].items():
                if cid in pins:
                    pins[cid] = p
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
        (x0, y0), (x1, y1), (x2, y2) = out[-1], q[i], q[i + 1]
        if abs((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)) > 1e-9:
            out.append(q[i])
    out.append(q[-1])
    return out


def esc_cands(a, b, na, nb, chx2, chy2):
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
    aps = [a] if na == (0.0, 0.0) else [(a[0] + na[0] * o, a[1] + na[1] * o) for o in ESC_OFFS]
    bps = [b] if nb == (0.0, 0.0) else [(b[0] + nb[0] * o, b[1] + nb[1] * o) for o in ESC_OFFS]
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
        for (p2, q2) in used:
            if SG.near_overlap(path[k], path[k + 1], p2, q2):
                return True
    return False


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


def pin_intr(path, own, pins_all):
    r"""路径**贴到几个“不相连的引脚”**上 ✓（< CLEAR_PIN 就算 ✓）

    ★ 为什么要这条（2026-09-27 用户定 ✓，原话："导线离芯片引脚太近了…让导线和引脚的连接
      关系**肉眼看得清**" ✓）：引脚线本来就有长度 ✓，导线从它末端擦过去 ⇒ 读图的人分不出
      "接上了"还是"路过" ✗ ⇒ 必须拉开一段可辨的距离 ✓。
    ★ `own` = 这根线自己两端的引脚 ✓ ⇒ 它们当然要“贴上” ✓（那是连接点 ✓ 不算侵入 ✗）。
    """
    if not pins_all:
        return 0
    n = 0
    for (ref, cid, px, py) in pins_all:
        if (ref, cid) in own:
            continue
        hit = False
        for i in range(len(path) - 1):
            p, q = path[i], path[i + 1]
            steps = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / P_STEP) + 1)
            for k in range(steps + 1):
                tt = k / steps
                x, y = p[0] + (q[0] - p[0]) * tt, p[1] + (q[1] - p[1]) * tt
                if math.dist((x, y), (px, py)) < CLEAR_PIN:
                    hit = True
                    break
            if hit:
                break
        if hit:
            n += 1
    return n


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
        for (p2, q2) in used:
            if seg_cross(path[k], path[k + 1], p2, q2):
                n += 1
    return n


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
    for k in range(len(path) - 1):
        p, q = path[k], path[k + 1]
        for box in own_boxes:
            if not seg_hits_box(p, q, box, -0.5):
                continue
            n = max(2, int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1)
            for i in range(n + 1):
                t = i / n
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                if (box[0] + 0.5 <= x <= box[2] - 0.5 and box[1] + 0.5 <= y <= box[3] - 0.5
                        and min(math.dist((x, y), path[0]),
                                math.dist((x, y), path[-1])) > R):
                    return True
    return False


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
    if "--freecorr" in argv:                   # ★★ 换机制 ✓：走廊改成**从空地算** ✓
        global FREECORR
        FREECORR = True
        print("空地走廊 FREECORR：**开** ✓（元件盒空档的中央当走廊 ✓，不再用“元件边 ± CH_OFFS” ✗）")
    if "--freecorr-k" in argv:                 # 一个空档里放几条走廊 ✓
        global FREECORR_K
        FREECORR_K = int(argv[argv.index("--freecorr-k") + 1])
        print("空地走廊条数 FREECORR_K = %d ✓（每个空档里按 (i+1)/(k+1) 分位放 ✓）" % FREECORR_K)
    if "--ring" in argv:                       # 实验 ✓：开“元件外圈环廊”（默认关 ✓）
        global OUTER_RING
        OUTER_RING = True
        print("外圈环廊 OUTER_RING：**开** ✓（从 UBOX 往外 %s ✓）" % (RING_OFFS,))
    if "--star" in argv:                       # 实验 ✓：指定星形拓扑的网（默认空 ✓）
        global STAR_NETS
        STAR_NETS = set((argv[argv.index("--star") + 1] or "").split(",")) - {""}
        print("星形拓扑 STAR_NETS = %s ✓" % (sorted(STAR_NETS) or "(空)"))
    if "--hardbody" in argv:                   # 实验 ✓：开启“不许进别人本体”的硬闸门（默认关 ✓）
        global HARD_BODY
        HARD_BODY = True
        print("硬闸门 HARD_BODY：**开启** ✓（`--hardbody` 实验 ✓；实测会多出 68 处“没候选” ✗）")
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

    chx, chy = set(), set()
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
    PIN_X = {p[0] for d in insts.values() for p in d["pins"].values()}
    PIN_Y = {p[1] for d in insts.values() for p in d["pins"].values()}
    boxes = {t: d["box"] for t, d in insts.items() if d["box"]}
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
    PIN_ALL = [(t, cid, p[0], p[1]) for t, d in insts.items()
               for cid, p in d["pins"].items()]
    print("引脚点表 %d 个 ✓；安全距离 CLEAR_PIN = %.1f 单位（%.2f mm ✓）"
          % (len(PIN_ALL), CLEAR_PIN, CLEAR_PIN * 25.4 / 90.0))
    # ★ 引脚**法线**表 ✓（出脚方向 ✓，2026-09-27 ✓）：看这个脚贴在它元件包围盒的哪条边上 ✓。
    #   ★ 为什么“贴边”能当法线用 ✓：`boxes` 是**画出来的东西**的包围盒 ✓ ⇒ 引脚线**末端**
    #     就落在盒边上 ✓（实测：U1 左排脚末端的 x 就等于盒左缘 22.6 ✓）。
    #   ★ 落在**盒内部**的脚（如 D3 的 `AC1/AC2` ✓）法线 = (0,0) ⇒ 不出脚 ✓
    #     （否则 “出脚” 会跑进自己肚子里 ✗）。
    PIN_N_BY_XY = {}
    for t, cid, px, py in PIN_ALL:
        bb = boxes.get(t)
        n = (0.0, 0.0)
        if bb:
            if abs(px - bb[0]) < 1.0:
                n = (-1.0, 0.0)
            elif abs(px - bb[2]) < 1.0:
                n = (1.0, 0.0)
            elif abs(py - bb[1]) < 1.0:
                n = (0.0, -1.0)
            elif abs(py - bb[3]) < 1.0:
                n = (0.0, 1.0)
        PIN_N_BY_XY[(round(px, 3), round(py, 3))] = n
    print("引脚法线表 %d 个 ✓（其中 %d 个能出脚 ✓ —— 贴在元件边上的；其它在元件内部 ✓ 不出脚 ✓）"
          % (len(PIN_N_BY_XY), sum(1 for v in PIN_N_BY_XY.values() if v != (0.0, 0.0))))
    # ★ 布线**次序**：先把电源/地布完 ✓、再布信号 ✓（面包板规则 ⑩ ✓：
    #   “先布电源/地，但**要把中间走廊留给后面的信号线**” ✓）。
    #   这里先只做前半条（次序 ✓）；后半条（给电源/地的“走中间”加权 ✓）还没做 ✗。
    POWER_FIRST = ("GND", "5V")
    net_order = [n for n in POWER_FIRST if n in NETS] + \
                [n for n in sorted(NETS) if n not in POWER_FIRST]
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
            for (p2, q2) in used:
                if SG.near_overlap(path[k], path[k + 1], p2, q2):
                    nov += 1
        ostep = int(out_len(path, UBOX) / 7.2 + 0.9999)          # ③ 出界几格 ✓
        # ④ 贴到几个不相连的脚 ✓ —— ★ **按“段”算** ✓（与渲染器同一个口径 ✓✓）：
        #   ✗ 原来按“**整条路径**”算 ✗ ⇒ 把这条网自己的脚**整条**豁免了 ✗ ⇒
        #     中段（它不属于任何一个脚 ✓）蹭到别人的脚就不算 ✗ ⇒ 脚本口径 11 ✓ 而渲染器口径 16 ✗
        #     （用户真正要的是后者 ✓：“不相连的引脚都要拉开距离” ✓）。
        #   ⇒ 改成：每一段各自看“两端命中的脚” ✓ —— 中段两端不是脚 ⇒ 它蹭到谁都算 ✓。
        pintr = 0
        for k in range(len(path) - 1):
            sk = {(t, c) for (t, c, x, y) in PIN_ALL
                  if math.dist((x, y), path[k]) < 0.05
                  or math.dist((x, y), path[k + 1]) < 0.05}
            pintr += pin_intr([path[k], path[k + 1]], sk, PIN_ALL)
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
        if NEW_ORDER:                  # ★ 默认开 ✓：用户规则（贴脚+重叠）排在代理规则之前 ✓
            return (1 if hits_own_body(path, own_boxes) else 0, ostep, wt, nvb,
                    cross_count(path, used), inside_count(path, own_boxes), bends(path),
                    plen(path) + diag_extra(path) + K_OUT * out_len(path, UBOX))
        # ✗ 旧次序（`--oldorder` = A 基线 ✓，实测与 v14 一字节不差 ✓）
        return (1 if hits_own_body(path, own_boxes) else 0, nvb, ostep, wt,
                cross_count(path, used), inside_count(path, own_boxes), bends(path),
                plen(path) + diag_extra(path) + K_OUT * out_len(path, UBOX))

    def route_pair(a, b, mine, own_pins, used, tag=""):
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
                esc_c = esc_cands(a, b, na, nb, chx_clean, chy_clean)
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
        # ★ 连接**对** ✓：默认 = 相邻两脚（链 ✓）；`STAR_NETS` 里的 = 每脚 → 汇点（星 ✓）
        pairs = []
        if net in STAR_NETS and len(pts) >= 2:
            hub = pick_hub(pts)
            print("网 %-9s **星形** ✓：汇点 (%.1f,%.1f) ✓（%d 根枝 ✓）" % (net, hub[0], hub[1], len(pts)))
            for d in pts:
                pairs.append({"a": d["p"], "ra": d["ref"], "ca": d["cid"],
                              "b": hub, "rb": None, "cb": None})
        else:
            for i in range(len(pts) - 1):
                pairs.append({"a": pts[i]["p"], "ra": pts[i]["ref"], "ca": pts[i]["cid"],
                              "b": pts[i + 1]["p"], "rb": pts[i + 1]["ref"],
                              "cb": pts[i + 1]["cid"]})
        for pr in pairs:
            a, b = pr["a"], pr["b"]
            mine = {pr["ra"]} | ({pr["rb"]} if pr["rb"] else set())
            own_pins = {(pr["ra"], pr["ca"])} | ({(pr["rb"], pr["cb"])} if pr["rb"] else set())
            tt = "%s %s.%s→%s" % (net, pr["ra"], pr["ca"],
                                   ("%s.%s" % (pr["rb"], pr["cb"])) if pr["rb"] else "汇点")
            # 三级：① 不碰本体 + 不与已布线段共线重叠 ✓ ② 只要求不碰本体 ✓ ③ 兜底（否则端点接不上 ✗）
            best, best_key = route_pair(a, b, mine, own_pins, used, tag=tt)
            if best is None:
                warn.append("%s: 没找到不碰本体的路径 ✗" % tt)
                best = candidates(a, b, sorted(chx), sorted(chy))[0]
            for k in range(len(best) - 1):
                used.append((best[k], best[k + 1]))
            segs.append({"a": best[0], "b": best[-1], "path": best,
                         "from": {"ref": pr["ra"], "cid": pr["ca"]},
                         "to": ({"ref": pr["rb"], "cid": pr["cb"]} if pr["rb"] else None),
                         # ★ 抽出重排要用同一套上下文 ✓（`mine`/`own_pins` ✓）
                         "mine": mine, "own_pins": own_pins, "key": best_key})
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
            for (p2, q2) in used_list:            # ★ 按“段”算 ✓（= 渲染器口径 ✓）
                own = {(t, c) for (t, c, x, y) in PIN_ALL
                       if math.dist((x, y), p2) < 0.05 or math.dist((x, y), q2) < 0.05}
                pc += pin_intr([p2, q2], own, PIN_ALL)
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
                a2, b2 = s["path"][0], s["path"][-1]
                segl = [(s["path"][k], s["path"][k + 1]) for k in range(len(s["path"]) - 1)]
                keep = [u for u in used if u not in segl]
                new, nk = route_pair(a2, b2, s["mine"], s["own_pins"], keep)
                oldk = route_key(s["path"], s["mine"], s["own_pins"], keep)
                ntry += 1
                if new is not None and nk < oldk:
                    s["path"] = new
                    segl = [(new[k], new[k + 1]) for k in range(len(new) - 1)]
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
    for (p1, q1), (p2, q2) in ov_pairs[:6]:
        print("      ✗ (%.1f,%.1f)→(%.1f,%.1f) 与 (%.1f,%.1f)→(%.1f,%.1f) 压在同一条直线上"
              % (p1[0], p1[1], q1[0], q1[1], p2[0], p2[1], q2[0], q2[1]))
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
        emit(sroot, insts, z, nets_segs, orig[0], out_path)
    return ov_fail              # ★ 真闸门 ✓：重叠非 0 ⇒ 退出码 1 ✓（见上面那条自检 ✓）


def fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else ("%.4f" % v)


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


def relabel(insts, boxes, used):
    r"""★ 布完线再把位号重摆一遍 ✓（2026-09-27 用户定 ✓）

    ★ 为什么要在**线布完之后**摆 ✗：摆位脚本那时候还不知道导线在哪 ✗（导线是后布的 ✓）
      ⇒ 实测总有 **3 处**"位号压导线" ✗。
    ★ 为什么不让**导线**避位号 ✗：试过了 ✓ —— 位号压导线只从 3 降到 2 ✗，
      代价是"压线 8→10、总长 +13" ✗ ⇒ **净亏** ✓（已回退 ✓）。
      正解在这头 ✓：**位号可以自由挪** ✓、导线挪一次要牵动全局 ✗。
    ★ 候选位与摆位脚本**同一套 7 个** ✓（上·左/右/中 ✓、下·左/右 ✓、左/右 ✓）；
      判碰只有 `sch_text.label_bbox` 一个实现 ✓（字宽表唯一 ✓）；
      权重：压**别的元件** 10 ✓、压**导线** 5 ✓、压**已放的位号** 5 ✓。
    """
    items = []
    for t, d in insts.items():
        lab = PR.LAB.get(d["mi"]) or {}
        ln, fs = lab.get("lines") or [], lab.get("fs", 5.0)
        tg = pm.child(d["sub"], "titleGeometry")
        if not ln or tg is None or (tg.get("visible") or "true") == "false":
            continue
        items.append((t, d, tg, ln, fs,
                      max(ST.twidth(s, fs) for s in ln), fs * len(ln)))

    def score(b, t):
        sc = 0
        for t2, box in boxes.items():
            if t2 != t and box and _ov2(b, box):
                sc += 10
        for (p, q) in used:
            if _seg_in_box(p, q, b):
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
        before[1] += sum(1 for (p, q) in used if _seg_in_box(p, q, b))
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
        after[1] += sum(1 for (p, q) in used if _seg_in_box(p, q, best))
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


def emit(sroot, insts, z, nets_segs, orig_path, out_path):
    """把每对脚的正交路径拆成「一段一根导线」✓；两端各记一份连接 ✓（链式，不出现 junction 点 ✓）"""
    oz = zipfile.ZipFile(orig_path)
    oroot = ET.fromstring(oz.read([n for n in oz.namelist() if n.endswith(".fz")][0]))
    tmpl = next((copy.deepcopy(e) for e in oroot.iter("instance")
                 if (e.get("moduleIdRef") or "").startswith("Wire")), None)
    if tmpl is None:
        raise SystemExit("✗ 原文件里没有 Wire 模板")
    host = pm.child(sroot, "instances")
    host = sroot if host is None else host
    next_mi = max(int(i.get("modelIndex")) for i in sroot.iter("instance")) + 1

    wires, links = [], []
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
                continue
            chain[0]["start_tgt"] = ("pin", s["from"])
            chain[-1]["end_tgt"] = ("pin", s["to"])
            for k in range(len(chain) - 1):
                chain[k]["end_tgt"] = ("wire", chain[k + 1], "connector0")
                chain[k + 1]["start_tgt"] = ("wire", chain[k], "connector1")
            wires.extend(chain)

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
