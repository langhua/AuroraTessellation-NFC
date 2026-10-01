# -*- coding: utf-8 -*-
r"""像素板的**项目数据**（= 通用工具**不认识**、只属于这块板的东西 ✓）

★ 为什么单独一个文件 ✗✓（2026-09-30 ✓ 用户定：通用工具搬到库仓 `fritzing-parts-langhua/tools/`）：
  通用工具（`check_netlist.py` / `bb_route4.py` …）里**不该写着这块板的网名** ✗ ——
  否则工具一挪到库仓，就等于把项目数据塞进了公共仓 ✗。
  ⇒ 把三张表**原样搬到这里** ✓，工具改成读 `--nets=<本文件>` ✓（默认找当前目录 ✓）。
  ★ 数值**一字不改** ✓（原样搬运 ⇒ 生成结果必须逐字节不变 ✓，这是可验证的 ✓）。

三张表 ✓：
  · `NETS`    —— 网表（脚名按 .fzp 连接器名 ✓，大小写不敏感 ✓；`#N` = 第 N 个脚 ✓）
                 照 `pixel-netlist.md` §2 ✓；`gen_schematic_wires.py` 与 `bb_route4.py` 共用 ✓
  · `EXPECT`  —— 网表核对器 `check_netlist.py` 的**期望**（`"位号.connectorN"` ✓）
  · `COLOR`   —— 每张网的导线颜色 ✓（值**只能**取 Fritzing 官方配色表 ✓，
                 来源 `fritzing-app/resources/ratsnestcolors.xml` 的 `breadboardView` ✓；
                 ★ 官方 black 是 `#404040` ✗ 不是 `#000000` ✗）
"""

# ── 网表（照 `hardware/pixel/pixel-netlist.md` §2 ✓；脚名按 .fzp 的连接器名，
#    大小写不敏感 ✓；"#N" = 第 N 个脚（core 件没有名字 ✓））────────────────────────
# ★★★ 2026-10-02 用户定 ✗✓：**`C2` 的两只脚对调** ✓（原话：「电容问题，我选改网表」✓）
#   起因（**Fritzing 自己写的 `<connect>` 为准** ✓，不靠推导 ✓）：
#     · GND 那根总线上挂的是 `J1.connector1`（= JST 的 2 脚 ✓）… **`C2.connector0`** ✓
#       （`Wire90013341` 端0 → `C2.connector0` ✓）
#     · 5V 那根总线上挂的是 `J1.connector0`（= 1 脚 ✓）… **`C2.connector1`** ✓
#       （`Wire90013354` 端1 → `C2.connector1` ✓）
#   ⇒ 板上的铜与**本表原来的编号正好交叉** ✗ —— 电容无极性 ⇒ 实物没事 ✓，
#     但编号对不上就**永远验不过** ✗ ⇒ 按用户决定：**以板上的铜为准，改网表** ✓。
#     （另一条路是把 5V/GND 接回对面那只盘 / 把 C2 转 180° ✓，用户没选 ✓）
NETS = {
    "COIL_A":   [("L1", "inner"), ("D3", "AC1")],
    "COIL_B":   [("L1", "outer"), ("D3", "AC2")],
    "GND":      [("D3", "A1"), ("D3", "A2"), ("C1", "#2"), ("U1", "VSS"), ("C2", "#1"),
                 ("LED2", "GND"), ("J1", "#2"), ("J2", "#2"),
     # ★ 裸焊盘/底板必须接地（2026-09-26 用户定 ✓）：原来写成"独立成网、单脚网无线"是错的 ✗
     #   —— EPAD 要**接到 GND** ✓（原理图上就接过来 ✓；元件库里它仍是独立脚 ✓ 见 AGENTS §5 ✓）
                 ("U1", "EPAD")],
    "BR+":      [("D3", "C1"), ("D3", "C2"), ("R1", "#1")],
    "RC":       [("R1", "#2"), ("C1", "#1"), ("U1", "PA1")],
    "5V":       [("U1", "VDD"), ("C2", "#2"), ("LED2", "VDD"), ("J1", "#1"), ("J2", "#1")],
    "DATA_IN":  [("U1", "PA2"), ("J1", "#3")],
    "DATA_OUT": [("U1", "PD0"), ("J2", "#3")],
    "LED_DIN":  [("U1", "PC6"), ("LED2", "DI")],
}

# ── 电源网（**按网分宽**用 ✓，2026-09-30 用户定 ✓）────────────────────────────
#   理由（**外部权威** ✓）：JST **SH** 连接器（1.0 mm 间距）官方规格页写的额定
#   **电流 1 A AC/DC（AWG #28 线）** ✓、耐压 50 V ✓ —— LCSC 的规格表也是 1 A ✓
#   ⇒ 板上的 5V/GND 走线按 **1 A** 配 ✓ ⇒ 取 **24 mil（标准 ✓ 0.61 mm ✓ ≈2 A ✓，
#   IPC-2221 1 oz 外层 10 ℃ 升仅需 ≈0.30 mm ✓）✓；信号网 12 mil ✓。
POWER = ("5V", "GND")

# ── 网表核对器的期望（`check_netlist.py` ✓）──────────────────────────────────────
EXPECT = {
    "COIL_A": {"L1.connector0", "D3.connector5"},
    "COIL_B": {"L1.connector1", "D3.connector2"},
    "GND": {"D3.connector0", "D3.connector1", "C1.connector1", "U1.connector3",
            # ★ 2026-10-02 与上面 `NETS` 同步对调 ✓（`C2` 的两只脚 ✓）
            "C2.connector0", "LED2.connector1", "J1.connector1", "J2.connector1",
            # ★ EPAD（U1 的裸焊盘 connector20 ✓）**必须接地** ✓（2026-09-26 用户定 ✓）：
            #   上一版把它写成"单脚网、图上留空"是错的 ✗ —— 裸盘要接到 GND ✓
            "U1.connector20"},
    "BR+": {"D3.connector3", "D3.connector4", "R1.connector0"},
    "RC": {"R1.connector1", "C1.connector0", "U1.connector1"},
    "5V": {"U1.connector5", "C2.connector1", "LED2.connector3", "J1.connector0",
           "J2.connector0"},
    "DATA_IN": {"U1.connector2", "J1.connector2"},
    "DATA_OUT": {"U1.connector4", "J2.connector2"},
    "LED_DIN": {"U1.connector12", "LED2.connector2"},
}

# ── 导线颜色（只能用 Fritzing 官方配色表里的值 ✓，2026-09-26 定位到根 ✓）────────────
#   来源（权威 ✓）：`<Fritzing>/fritzing-app/resources/ratsnestcolors.xml`
#                    的 `<view name="breadboardView">` 下每个 `<color … wire="…">` ✓
#   ⇒ 认不出的 hex ⇒ 指示栏的「颜色」下拉回退到**第一项（蓝）** ✗ ——
#     这就是用户截图里"黑线显示蓝"的原因 ✓（`#000000` 不在表里 ✗，官方 black 是 `#404040` ✓）。
COLOR = {"GND": "#404040", "5V": "#cc1414", "DATA_IN": "#418dd9", "DATA_OUT": "#33ffc5",
         "LED_DIN": "#25cc35", "RC": "#ef6100", "BR+": "#ab58a2",
         "COIL_A": "#8c3b00", "COIL_B": "#fa50e6"}
