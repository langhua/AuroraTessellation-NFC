# 4x4 子板原理图规格

本文件是 Fritzing 原理图的连线依据。先完成 CH0 单通道，再复制为 CH0~CH15。

## 线圈阵列参数（PCB 铜层）

阵列用 `coil_4x4_array.svg`（`fritzing-parts-langhua/svg/NFC-Coil/`）作为 80×80 mm 板顶层铜：

```text
线圈数量  4x4 = 16
中心间距  20 mm
线圈外径  phi 19 mm（不是 phi 20）
线圈内径  phi 8 mm
匝数      6
线宽      0.2 mm
焊盘      线圈内端 phi 1.0 / 外端 phi 1.0
```

重要：阵列线圈外径取 phi 19 mm 而不是 phi 20 mm。若取 phi 20，20 mm 间距下相邻线圈铜皮边缘刚好相切，会造成电气短路；最外圈也会贴到板边。phi 19 时相邻线圈间距 1 mm（每侧 0.5 mm），最外圈距板边 0.5 mm。生成脚本为同目录下的 `gen_coil.py`（`fritzing-parts-langhua/svg/NFC-Coil/gen_coil.py`），运行后 SVG 输出到脚本自身所在目录，可复现、可调参。

单线圈参考件 `svg.pcb.NFC_Coil_20mm_6T_0p2_pcb.svg` 保留 phi 20 尺寸，仅作单线圈封装参考，不用于 4x4 阵列铜层。

## 单通道信号链

```text
L0 o----+-------------------- COIL_A
        |       U1A
        +-------|1  BAT54S 2|------- BR+
                |3
                |
L0 o------------+

L1 o----+-------------------- COIL_B
        |       U1B
        +-------|1  BAT54S 2|------- BR+
                |3
                |
L1 o------------+
```

上图是逻辑示意，不代表封装外形。实际连接关系如下：

```text
U1A pin 1 -> BR-
U1A pin 3 -> COIL_A
U1A pin 2 -> BR+

U1B pin 1 -> BR-
U1B pin 3 -> COIL_B
U1B pin 2 -> BR+
```

其中：

- `COIL_A`、`COIL_B`：一只两线 PCB 线圈的两端
- `BR+`、`BR-`：四二极管桥的正、负输出
- `BR-`：系统模拟地
- 两颗 BAT54S 必须按其串联二极管方向连接，不得把两颗器件简单并联

## 滤波网络

```text
BR+ ---- R_CH0 10k ----+---- SENSE_CH0
                       |
                    C_CH0 100nF
                       |
                      GND
```

`SENSE_CH0` 是整流后的直流包络，连接到 TS3A44159 的 `COM1`。

## TS3A44159（U1）通道分配

每颗 TS3A44159 负责 4 个通道。第一颗芯片的通道分配如下：

```text
COM1 (pin 13) <- SENSE_CH0
NO1  (pin 16) -> MUX_C0
NC1  (pin 14) -> GND

COM2 (pin 2)  <- SENSE_CH1
NO2  (pin 1)  -> MUX_C1
NC2  (pin 3)  -> GND

COM3 (pin 6)  <- SENSE_CH2
NO3  (pin 5)  -> MUX_C2
NC3  (pin 7)  -> GND

COM4 (pin 10) <- SENSE_CH3
NO4  (pin 9)  -> MUX_C3
NC4  (pin 11) -> GND
```

电源和控制：

```text
U1 pin 12 VCC   -> +3V3
U1 pin 4  GND   -> GND
U1 pin 15 IN1-2 -> SEL_ALL
U1 pin 8  IN3-4 -> SEL_ALL
```

`SEL_ALL=1` 时选择 `NO` 正常信号路径，`SEL_ALL=0` 时选择 `NC` 背景路径。正式上电前用万用表验证实际开关状态。

每颗 TS3A44159 的 `VCC-GND` 旁放置 1 颗 100 nF 旁路电容。

## CD74HC4067 开发板连接

当前使用外接开发板，不在 4x4 传感器 PCB 上放置裸 MUX 芯片：

```text
MUX C0  <- TS3A44159-1 NO1
MUX C1  <- TS3A44159-1 NO2
MUX C2  <- TS3A44159-1 NO3
MUX C3  <- TS3A44159-1 NO4
MUX C4  <- TS3A44159-2 NO1
...
MUX C15 <- TS3A44159-4 NO4

MUX SIG/DIG -> ESP32-S3 ADC1
MUX S0     -> ESP32 GPIO
MUX S1     -> ESP32 GPIO
MUX S2     -> ESP32 GPIO
MUX S3     -> ESP32 GPIO
MUX EN     -> GND 或 ESP32 GPIO
MUX VCC    -> +3V3
MUX GND    -> GND
```

MUX 通道编号使用二进制地址，`S0` 为最低位。所有模拟信号必须保持在 `0~3.3 V` 范围内。

## 原理图元件清单

### 单通道 CH0

- `L0`：PCB 线圈
- `U0A`、`U0B`：BAT54S，2 颗
- `R0`：10 kOhm
- `C0`：100 nF
- `U1`：TS3A44159 中的通道 1

### 4 通道组

- BAT54S：8 颗
- TS3A44159：2 颗
- 10 kOhm：4 颗
- 100 nF 滤波电容：4 颗
- 100 nF 芯片旁路电容：2 颗

### 16 通道子板

- BAT54S：32 颗
- TS3A44159：4 颗
- 10 kOhm：16 颗
- 100 nF 滤波电容：16 颗
- 100 nF 芯片旁路电容：4 颗
- 输出测试点：`BR+`、`SENSE_CHx`、`MUX_Cx`
- 控制测试点：`+3V3`、`GND`、`SEL_ALL`

## Fritzing 元件准备

先建立并检查元件，再开始画原理图。建议在 Fritzing 中建立一个专用元件库或项目元件清单。

| 元件 | Fritzing 来源 | 必须确认的内容 |
|---|---|---|
| BAT54S | 现成肖特基/SOT-23 元件或自定义 | 1、2、3 脚与规格书一致，3 脚为两只二极管的中点 |
| TS3A44159 | 自定义元件 | PW/TSSOP-16 封装、`COM/NO/NC/IN/VCC/GND` 脚位 |
| CD74HC4067 开发板 | 自定义开发板元件 | `C0~C15`、`SIG/DIG`、`S0~S3`、`EN`、`VCC`、`GND` 端子 |
| ESP32-S3 开发板 | 现成 DevKitC 或自定义 | 实际开发板的 2×20 排针脚位，尤其 ADC 使用的 GPIO |
| PCB 线圈 | Inkscape SVG | 线圈两端是独立连接点，不要只作为装饰图形导入 |
| 10 kOhm 电阻 | 现成 0603 或 THT | 封装和两个引脚 |
| 100 nF 电容 | Fritzing 自带 0603 电容（标注 100nF） | 无需自建元件 |
| 4×4 WS2812B 模块 | 库内已建 `WS2812B-5050-4x4.fzpz` | 排针 GND/5V/DIN/GND + 独立 DOUT；~30×30mm、5050 灯珠、LED 中心距 7.5mm 均布；LED 扫序暂按蛇形，需对照实物丝印确认 |
| 16-pin 排针 | 现成元件 | 引脚编号和 2.54 mm 间距 |
| 1-pin 排针 | 现成元件 | `SEL_ALL` 标识 |

### 推荐建立顺序

1. 先建立 `BAT54S`，用万用表符号检查二极管方向。
2. 建立 `TS3A44159`，把 16 个引脚名称直接标在元件上。
3. 建立 `CD74HC4067` 开发板符号，优先按开发板端子命名，而不是裸芯片脚号。
4. 建立实际 ESP32-S3 开发板符号，保留 USB、5V、3V3 和 GND 标识。
5. 建立 PCB 线圈和 WS2812B 模块的连接器符号。
6. 用这些元件画 CH0，并对照本文件做连通性检查。

不要把 CD74HC4067 开发板误画成裸芯片：原型阶段的连接对象是 `C0~C15` 和 `SIG/DIG` 端子。正式母板若改用裸芯片，再另建一个裸芯片元件，避免两个封装混用。

## 画图顺序

1. 在 Fritzing Schematic 中先画 CH0。
2. 用万用表连通性检查桥式整流网络的四个二极管方向。
3. 复制 CH0 的整流和滤波部分至 CH1~CH15。
4. 放置 4 颗 TS3A44159，按通道组连接。
5. 把 16 个 `NO` 输出引出到 16-pin 排针，连接外部 MUX 开发板。
6. 在原理图通过后再开始 PCB 布局。
