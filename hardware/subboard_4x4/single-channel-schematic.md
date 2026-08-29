# 单通道传感原理图（M0）

方案 C 信号链：线圈 → 2×BAT54S 全波桥 → RC 低通 → TS3A44159 → CD74HC4067 → ESP32-S3 ADC1

```text
两线线圈
  -> 2 × BAT54S 全波桥（BR+ / BR-）
  -> R=10 kΩ 串联、C=100 nF 对地低通
  -> TS3A44159 COM（NO=通道输出，NC=GND 背景采样）
  -> CD74HC4067
  -> ESP32-S3-DevKitC-1 ADC1 (GPIO1)
```

## 元件与引脚（库内连接器名，2026-08-29 核对）

### NFC-Coil（`NFC-Coil.fzpz`）
| 连接器 | 含义 |
|---|---|
| `inner` | 线圈内端 |
| `outer` | 线圈外端 |

### BAT54S（`BAT54S.fzpz`，SOT-23，两二极管串联 pin1→pin3→pin2）
| 连接器 | 对应封装脚 | 含义 |
|---|---|---|
| `A1` | 1 | 二极管 D1 阳极 |
| `node` | 3 | D1 阴极 + D2 阳极（串联中点） |
| `K2` | 2 | 二极管 D2 阴极 |

### TS3A44159PWR（`TS3A44159PWR.fzpz`，TSSOP-16）
| 连接器 | 封装脚 | 含义 |
|---|---|---|
| `NO1`/`COM1`/`NC1` | 13/14/15 | 通道 1 |
| `NO2`/`COM2`/`NC2` | 1/2/3 | 通道 2 |
| `NO3`/`COM3`/`NC3` | 5/6/7 | 通道 3 |
| `NO4`/`COM4`/`NC4` | 9/10/11 | 通道 4 |
| `IN1-2` | 16 | 控制通道 1/2（与 IN3-4 并联） |
| `IN3-4` | 8 | 控制通道 3/4（与 IN1-2 并联） |
| `VCC` | 12 | 电源 3.3 V |
| `GND` | 4 | 地 |

## 单通道网表（以通道 1 为例）

| 起点 | 终点 | 说明 |
|---|---|---|
| 线圈 `inner` | U整流A.`node` | 线圈一端接桥 A 中点 |
| 线圈 `outer` | U整流B.`node` | 线圈另一端接桥 B 中点 |
| U整流A.`A1` | `BR-`（GND） | |
| U整流B.`A1` | `BR-`（GND） | |
| U整流A.`K2` | `BR+` | |
| U整流B.`K2` | `BR+` | |
| `BR+` | R1(10 kΩ) | 整流输出串联电阻 |
| R1 另一端 | `node_RC` | 低通节点 |
| `node_RC` | C1(100 nF) → GND | 低通滤波 |
| `node_RC` | TS3A44159.`COM1` (14) | 滤波输出进开关 |
| TS3A44159.`NO1` (13) | 通道输出 → MUX 开发板 `C0`（裸芯片为 `I0`=9 脚） | 正常路径 |
| TS3A44159.`NC1` (15) | GND | 背景采样路径 |
| TS3A44159.`IN1-2` (16) | ESP32-S3-DevKitC-1 **GPIO2**（丝印 `2`，connector38） | 与 `IN3-4`(8) 并联后接同一 GPIO；四颗 TS3A44159 的控制线并联到同一 GPIO |
| TS3A44159.`VCC` (12) | 3.3 V | |
| TS3A44159.`GND` (4) | GND | |
| MUX `VCC`（裸芯片 24 脚） | 3.3 V | |
| MUX `GND`（裸芯片 12 脚） | GND | |
| MUX `EN`（裸芯片 15 脚） | GND（低有效常开） | |
| MUX `S0`~`S3`（裸芯片 10/11/13/14 脚） | ESP32-S3-DevKitC-1 **GPIO4~GPIO7**（丝印 `4`~`7`，connector3~6） | 通道选择，S0 为最低位 |
| MUX `SIG`/`COM`（裸芯片 1 脚） | ESP32-S3-DevKitC-1 **GPIO1**（ADC1_CH0，丝印 `1`，connector37） | 16 路选通输出 |

## GPIO 分配（ESP32-S3-DevKitC-1）

| 用途 | GPIO | 丝印 | 库内连接器 |
|---|---|---|---|
| MUX `SIG`（ADC1_CH0） | GPIO1 | `1` | connector37 |
| TS3A44159 `SEL`（IN1-2/IN3-4） | GPIO2 | `2` | connector38 |
| MUX `S0` | GPIO4 | `4` | connector3 |
| MUX `S1` | GPIO5 | `5` | connector4 |
| MUX `S2` | GPIO6 | `6` | connector5 |
| MUX `S3` | GPIO7 | `7` | connector6 |
| WS2812B `DI`（显示） | GPIO15 | `15` | connector7 |
| 板载 WS2812（未用） | GPIO48 | `48` | connector24 |

> ⚠️ 装配前用万用表二极管档确认 BAT54S 实物方向（pin1→pin3→pin2）。
> ⚠️ 整流输出须 < 3.3 V（ESP32-S3 ADC 量程）；若场强过大需加钳位（如 3.3 V 齐纳）。

## 原理图 SVG 裁边修复（2026-08-29）

`TS3A44159PWR` 与 `ESP32-S3-DevKitC-1` 的原理图 SVG 未裁边（viewBox 远大于符号内容），已按库内惯例（内容距边 3 单位）裁边，使 viewBox 紧贴符号：

| 元件 | 裁边前 viewBox | 裁边后 viewBox | 内容平移 (dx,dy) |
|---|---|---|---|
| TS3A44159PWR | `0 0 212 320`（旧仓库版为 `55 0 212 320`，含 55 偏移 bug） | `0 0 190.0001 306` | (10, 7) |
| ESP32-S3-DevKitC-1 | `0 0 340 300`（内容 x∈[86,254]，两侧各 86 空边） | `0 0 174.0001 266` | (83, 17) |

同步位置：
- Fritzing MINE 库：`Documents\Fritzing\parts\svg\user\schematic\`
- 开源库 `fritzing-parts-langhua`：`svg\TS3A44159PWR\`、`svg\ESP32-S3-DevKitC-1\`（TS3A 顺带修掉了旧仓库里的 55 偏移 bug）
- 本 fzz 内嵌副本 `svg.schematic.*`

已用 `-svg` 渲染验证：裁边后 Fritzing 会从 SVG 重新计算引脚终端，U1（ESP32，44 脚）/U2（TS3A44159，16 脚）全部引脚保留，连线精确贴附新终端（U2 11 根、U1 8 根），无回归。

## CD74HC4067 元件重画（2026-08-29 建立，2026-08-30 完善）

原来的 `Analog_Digital_MUX_Breakout`（官方旧元件）质量差：原理图符号极小、终端位置导致 12 根连线悬空偏移约 100 单位。已按规格书要求（按开发板端子命名、不画成裸芯片）自建新元件：

- 新元件 `CD74HC4067`（`fritzing-parts-langhua/svg/CD74HC4067/gen_part.py`，交付 `fzpz/CD74HC4067.fzpz`）
- 端子：`C0~C15`（connector0..15，原理图左侧）+ `SIG/S0~S3/EN/VCC/GND`（connector16..23，右侧）
- 四视图齐全：icon 按 datasheet p.20 PW0024A（TSSOP-24）封装绘制（芯片体 7.8×4.4mm、每侧 12 引脚、0.65mm 间距）；schematic 为干净 IC 框 + 引脚号 + 裁边（Fig 4-1，无顶部缺口）；breadboard 为 16 通道开发板布局（左 16 针 + 右 8 针，2.54mm 排针，右排落在孔位网格可插面包板）；PCB 为 TSSOP-24 SMD 焊盘（datasheet p.21：2 列×12、1.5×0.45mm、列心距 5.8mm、间距 0.65mm，copper1 层）
- `single-channel.fzz` 已把旧 MUX 替换为新元件（.fz 连接器按名称重映射 + 内嵌新元件 5 文件）
- **渲染验证：23 根线、0 游离端点、MUX 9 个端子（C0/SIG/S0-S3/EN/VCC/GND）全部正确连线**，面包板视图也正常

## ESP32 电源引脚内部互通（`<buses>`，2026-08-29）

`ESP32-S3-DevKitC-1` 与 `ESP32-S3-WROOM-1` 的 fzp 已用 `<buses>` 声明内部互通（Fritzing 官方机制，同库内 N16R8 变体写法）：

```xml
<buses>
  <bus id="GND">
   <nodeMember connectorId="connector0"/>
   <nodeMember connectorId="connector39"/>
   <nodeMember connectorId="connector40"/>
   <nodeMember connectorId="connector43"/>
  </bus>
  <bus id="3V3">
   <nodeMember connectorId="connector1"/>
   <nodeMember connectorId="connector41"/>
  </bus>
 </buses>
```

- 4×GND、2×3V3 在元件内部同 net，连线到任意一个即等效。
- 已集成进 `gen_part.py` 的 `buses_xml()`，fzpz 与 MINE 库均已同步。
> ⚠️ **坑**：`single-channel.fzz` 曾被 Fritzing 打开/保存时自动迁移（补了面包板布线，原理图线从 23 根变成 34 根、连线悬空）。已用干净的纯原理图 `.fz`（23 线）重建。**若在 Fritzing GUI 打开后保存导致布局/连线变化，用 git 恢复本文件即可**。

## 待办核对（M0）

- [x] BAT54S 为 SOT-23、1/2 串联、3 中点（已入元件库）
- [ ] 采购 BAT54S 至 32 颗（每通道 2 颗 × 16）
- [x] 单通道网表（本文档）
- [x] Fritzing 单通道原理图 `single-channel.fzz` 已整理成直接连线并核对网表（2026-08-29，共 13 个网络；原理图视图直接连线，面包板视图为飞线）
  - 布局优化：模拟链路（线圈→全波桥→RC）放上部、U2 居中、MUX/ESP32 在右，主信号链不穿芯片本体；面包板视图按左→右排布。
  - 修复库元件 `TS3A44159PWR` schematic SVG 的 viewBox 起点（55,0 → 0,0，所有 x −55），使连线能精确接到引脚。
- [ ] 确认整流输出不超 ADC 量程（实测 M1 项）
- [x] CD74HC4067：HC 型、3.3 V、E 低有效（开发板 SIG/DIG、C0~C15、S0~S3、EN）

> 备注：MUX 裸芯片通道脚 `I0~I15`（I0=9 脚）对应 SparkFun 开发板的 `C0~C15`；`COM`(1) = `SIG`。
> MUX 必须上电：VCC(24)=3.3V、GND(12)=GND，EN(15) 低有效，S0~S3 接 GPIO。
> ADC1 = GPIO1~GPIO10（CH0~CH9）。本设计用 ESP32-S3-DevKitC-1 的 **GPIO1（ADC1_CH0）** 接 MUX `SIG`，Arduino 里 `analogRead(1)` / `analogReadMilliVolts(1)` 读取（0~3.3V → 0~4095）。
