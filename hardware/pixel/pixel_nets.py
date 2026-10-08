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
# ★★★ 2026-10-03 **撤销** 2026-10-02 那次“对调网表” ✓（用户定 ✓，原话：「之前允许 C2 的两脚网
#   因无极性而互换，看来是**草率**了」✓）—— 那次的扥法本末倒置 ✗：网表 = **设计意图** ✓，
#   板上的铜对不上就该改**板** ✗，不该改表 ✓。
#   ⇒ 用户把 `C2` **转 180°** 并**重新接线** ✓ ⇒ 5V/GND 不再打架 ✓（拿回本文件复核过 ✓：
#     C2 = 135° ✓、`C2.connector0` 在 `J1.0/J2.0` 那条链（= **5V** ✓）、
#     `C2.connector1` 在 `J1.1/J2.1` 那条链（= **GND** ✓）✓）。
#   ⇒ 编号回到**原来的那一套** ✓：GND = `#2`（connector1 ✓）／5V = `#1`（connector0 ✓）✓。
NETS = {
    "COIL_A":   [("L1", "inner"), ("D3", "AC1")],
    "COIL_B":   [("L1", "outer"), ("D3", "AC2")],
    "GND":      [("D3", "A1"), ("D3", "A2"), ("C1", "#2"), ("U1", "VSS"), ("C2", "#2"),
                 ("LED2", "GND"), ("J1", "#2"), ("J2", "#2"),
     # ★ 裸焊盘/底板必须接地（2026-09-26 用户定 ✓）：原来写成"独立成网、单脚网无线"是错的 ✗
     #   —— EPAD 要**接到 GND** ✓（原理图上就接过来 ✓；元件库里它仍是独立脚 ✓ 见 AGENTS §5 ✓）
                 ("U1", "EPAD")],
    "BR+":      [("D3", "C1"), ("D3", "C2"), ("R1", "#1")],
    # ★★ 2026-10-09 用户按 **PCB 布线需要**换了三只脚 ✓（手改版 `_work/v76_byHand.fzz` ✓，
    #   核实见 README §五十四 ✓）：`RC` 的 ADC 输入 **`PA1(ADC_IN1)` ⇒ `PD6(ADC_IN6)`** ✓
    #   （仍是 ADC 脚 ✓）；`DATA_IN` **`PA2` ⇒ `PC1`** ✓、`DATA_OUT` **`PD0` ⇒ `PD2`** ✓
    #   （都是普通数字脚 ✓）。
    #   ★ 代价（记着 ✗ 别忘 ✗）：① 线圈离开 `PA1` ⇒ **内置 OPA 的输入 `OPN0` 再也用不上** ✗
    #     （要用 OPA 就得把线圈搬回 `PA1` ✓）；② 吃掉 `PD2`/`PD6` 两个 ADC 备用脚的其中两个 ✓。
    #   ★ `LED_DIN` 仍留 **`PC6`** ✓（= `SPI_MOSI` ✓：用户 2026-10-09 决定**保住 SPI+DMA** ✓）。
    "RC":       [("R1", "#2"), ("C1", "#1"), ("U1", "PD6")],
    "5V":       [("U1", "VDD"), ("C2", "#1"), ("LED2", "VDD"), ("J1", "#1"), ("J2", "#1")],
    "DATA_IN":  [("U1", "PC1"), ("J1", "#3")],
    "DATA_OUT": [("U1", "PD2"), ("J2", "#3")],
    "LED_DIN":  [("U1", "PC6"), ("LED2", "DI")],
}

# ── 电源网（**按网分宽**用 ✓，2026-09-30 用户定 ✓）────────────────────────────
#   理由（**外部权威** ✓）：JST **SH** 连接器（1.0 mm 间距）官方规格页写的额定
#   **电流 1 A AC/DC（AWG #28 线）** ✓、耐压 50 V ✓ —— LCSC 的规格表也是 1 A ✓
#   ⇒ 板上的 5V/GND 走线按 **1 A** 配 ✓ ⇒ 取 **24 mil（标准 ✓ 0.61 mm ✓ ≈2 A ✓，
#   IPC-2221 1 oz 外层 10 ℃ 升仅需 ≈0.30 mm ✓）✓；信号网 12 mil ✓。
POWER = ("5V", "GND")

# ── 电流规格（`pcb_current.py` 读它 ⇒ 算线宽下限 / 段压降 ✓；2026-10-08 用户定 ✓）──
#   ★ 约束（用户 2026-10-08 原话 ✓）：「要加入约束条件，就是要考虑支持 **64 个 Pixel
#     串联**的电流供给」✓
#   ★ 用户 2026-10-08 **选定** ✓：**每 4 块一个注入点** ✓、**全板统一 8 mil** ✓
#     （= 走线宽度只有一个 ✓，仍是用户 2026-10-01 定的"整张 pcb 一个标准线宽"✓）。
#   ★ 实测依据（`pcb_current.py --seg-boards=N --try-mil=…` 在实板 v69 上量的 ✓，
#     段压降 ＝ 5V ＋ GND **两程之和** ✓）：
#       一段 8 块（0.496 A）：8 mil ⇒ **9.8%** ✗｜16 mil ⇒ 5.0% ✗｜**24 mil ⇒ 3.4%** ✓
#       一段 6 块（0.372 A）：8 mil ⇒ 5.7% ✗｜**12 mil ⇒ 3.8%** ✓｜24 mil ⇒ 2.0% ✓
#       一段 4 块（0.248 A）：**8 mil ⇒ 2.7%** ✓｜12 mil ⇒ 1.8% ✓｜24 mil ⇒ 0.9% ✓
#     ⇒ 4 块 + 8 mil 是唯一能同时满足「全板一个宽度」＋「压降 ≤ 5%」＋「载流余量」的组合 ✓。
#   ★ 别把"针"当瓶颈 ✗：`SH-1.0-3P-V` 官方额定 **1 A/触点** ✓ ⇒ 60 mA/颗时一段最多 **16 块** ✓；
#     一段 4 块 ⇒ 针上只有 **0.25 A** ✓（4 倍余量 ✓）；载流也是 ✓（8 mil = 0.75 A ✓）。
#   ★ 每颗 Pixel：WS2812B-1010 全白最坏 **60 mA**（官方 max ✓）＋ 2 mA 杂项 ✓
#     ⇒ 0.062 A/块 ✓；`misc_amps` = CH32V003 + NFC 那部分的摊派 ✓。
#   ★ 阵列接法 ⇒ 每 4 块从电源总线**单独引一路 5V/GND** ✓（16 路/64 块 ✓）；见
#     `connector-plan.md` §5 与 `README.md` §5 ✓。
POWER_SPEC = dict(
    seg_boards=4,        # 一段几块（两个注入点之间）✓
    pixel_amps=0.060,    # 一颗 WS2812B-1010 全白最坏 ✓
    misc_amps=0.002,     # 每块其余电路的摊派 ✓
    oz=1.0,              # 铜厚 ✓（两层板 ✓）
    rail=5.0,            # 母线电压 ✓
    drop_pct=5.0,        # 一段允许掉多少 % ✓
    connector_amps=1.0,  # `SH-1.0-3P-V` 额定 1 A/触点 ✓
    temp_rise=10.0,      # IPC-2221 口径 ✓
    board_mm=1.6,        # 板厚（过孔孔壁长度 ✓）
    power=("5V", "GND"),
)

# ── 网表核对器的期望（`check_netlist.py` ✓）──────────────────────────────────────
EXPECT = {
    "COIL_A": {"L1.connector0", "D3.connector5"},
    "COIL_B": {"L1.connector1", "D3.connector2"},
    "GND": {"D3.connector0", "D3.connector1", "C1.connector1", "U1.connector3",
            # ★ 2026-10-03 **改回** ✓（`C2` 转了 180° 并重接 ✓，见上面 `NETS` 的说明 ✓）：
            #   GND = connector1 ✓、5V = connector0 ✓
            "C2.connector1", "LED2.connector1", "J1.connector1", "J2.connector1",
            # ★ EPAD（U1 的裸焊盘 connector20 ✓）**必须接地** ✓（2026-09-26 用户定 ✓）：
            #   上一版把它写成"单脚网、图上留空"是错的 ✗ —— 裸盘要接到 GND ✓
            "U1.connector20"},
    "BR+": {"D3.connector3", "D3.connector4", "R1.connector0"},
    "RC": {"R1.connector1", "C1.connector0", "U1.connector19"},
    # ★ `U1.connector19` = **PD6** ✓（2026-10-09 换脚 ✓；原来 `connector1` = PA1 ✓）
    "5V": {"U1.connector5", "C2.connector0", "LED2.connector3", "J1.connector0",
           "J2.connector0"},
    "DATA_IN": {"U1.connector7", "J1.connector2"},
    #   ★ `connector7` = **PC1** ✓（原 `connector2` = PA2 ✓）
    "DATA_OUT": {"U1.connector15", "J2.connector2"},
    #   ★ `connector15` = **PD2** ✓（原 `connector4` = PD0 ✓）
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
