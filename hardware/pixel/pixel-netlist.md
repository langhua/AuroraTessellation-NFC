# 像素板原理图网表（1 个像素）

> 原理图**只画一个像素**；4×4 = 16 块就是同一张图复制 16 份。
> 按项目约定：**现在画原理图，PCB 等 coupon 实测定间距后再做**；不画面包板视图。
> 草图路径：`hardware/pixel/pixel.fzz`（Fritzing 新建 → 保存到此路径）。
>
> ⚠️ **2026-09-25 状态**：
> - ✅ **本文的 U1 脚号已按 `CH32V003F4U6`（QFN20）全部改好** ✓ —— **照本文接线即可** ✓
>   （脚位依据：[`README.md`](README.md) §4.2/§4.3 ✓；接插件与板间三线见
>   [`connector-plan.md`](connector-plan.md) ✓；协议见 [`bus-protocol.md`](bus-protocol.md) ✓）
> - ✗ **旧的 `pixel.fzz` 已作废**（那是 SOP8 + 2020 + 4 线时代的图 ⇒ **不用去改它** ✓），
>   照本文**新建**一张 sketch 就好 ✓。

## 1. 元件（7 个器件 + 2 个电容 + 3 个网络标签）

| 位号 | 元件 | 库内名字 | 备注 |
|---|---|---|---|
| L1 | NFC 线圈 φ19 / 6 匝 | `NFC_Coil_20mm_6T_0p2_1` | MINE；连接器 `inner` / `outer` |
| D1 | `BAS70BRW`（4 × 70 V 肖特基，两对串联）| `BAS70BRW_SOT363_1` | MINE ✓；一颗 = **整个全波桥** ✓（连接器 `A1`/`AC1`/`C1` + `A2`/`AC2`/`C2`）|
| R1 | 10 kΩ | `R0603` | core |
| C1 | 100 nF | 0603 电容 | core；RC 对地 |
| C2 | 100 nF | 0603 电容 | core；U1 去耦 |
| U1 | `CH32V003F4U6`（或 `CH32V002F4U6`） | 本库已有 ✓ | QFN20，20 脚 + EPAD；SPI ✓ + OPA ✓ |
| LED1 | WS2812B 1010 | `WS2812B_1010_1` | MINE；`DIN` / `DOUT` / 电源脚（以库内实际名称为准） |
| — | Net Label ×4 | core `Net Label` | `5V` / `GND` / `DATA_IN` / `DATA_OUT` |

## 2. 网表（照这个连线）

| # | 起点 | 终点 | 说明 |
|---|---|---|---|
| 1 | `L1.inner` | `D1.AC1` | 线圈一端 → 桥 **AC1**（pin 6）|
| 2 | `L1.outer` | `D1.AC2` | 线圈另一端 → 桥 **AC2**（pin 3）|
| 3 | `D1.A1` | `GND` | 桥负 **A1**（pin 1）|
| 4 | `D1.A2` | `GND` | 桥负 **A2**（pin 2）|
| 5 | `D1.C1` | `R1.1` | 桥正 `BR+`：**C1**（pin 5）|
| 6 | `D1.C2` | `R1.1` | 桥正 `BR+`：**C2**（pin 4）|
| 7 | `R1.2` | `C1.1` | RC 节点 |
| 8 | `R1.2` | `U1.pin2`（**PA1**）| RC 节点 → ADC（**同一节点、两段线** ✓；PA1 也是 OPA 输入 `OPN0` ✓）|
| 9 | `C1.2` | `GND` | |
| 10 | `U1.pin4` | `GND` | **VSS**（pin 4）|
| 11 | `U1.pin6` | `5V` | **VDD**（pin 6）|
| 12 | `C2.1` | `5V` | 去耦 |
| 13 | `C2.2` | `GND` | 去耦 |
| 14 | `U1.pin3`（**PA2**）| `DATA_IN` | 链**上游脚**（收本板上游口的 `DATA` ✓）|
| 15 | `U1.pin5`（**PD0**）| `DATA_OUT` | 链**下游脚**（再生转发给下游口 ✓）|
| 15b | — | — | ⚠️ 两根数据网**不许短接** ✗（短接 = 真总线，接力链/回读时隙会打架 ✗）|
| 16 | `U1.pin13`（**PC6 / `SPI_MOSI`**）| `LED1.DIN` | 自驱本板 1010 ✓（固件走 SPI + DMA ✓）|
| 17 | `LED1.VDD` | `5V` | |
| 18 | `LED1.VSS` | `GND` | |
| 19 | `U1.pin0`（**EPAD**）| `GND` | ⚠️ **独立成网** —— 布线时**特意**接到 GND ✓（别指望自动合并 ✗）|

**不接**：`LED1.DOUT`（LED 不在硬件链上，链在 MCU 之间 ✓）；`U1.pin15`（**PD1 = SWIO**）留个测试点、平时悬空 ✓；其余 12 个备用脚（PD7 / PC0–PC5 / PC7 / PD2–PD6）也留测试点或悬空 ✓。

## 3. U1 引脚分配（`CH32V003F4U6`，QFN20，20 脚 + EPAD）

| 脚 | 名称 | 这里接 |
|---|---|---|
| **0** | **EPAD**（内部 = VSS）| `GND` ⚠️ **独立网，特意布线** ✓ |
| 1 | PD7 | 备用（也是 `NRST`）|
| **2** | **PA1**（ADC_IN1 / OPA `OPN0`）| 线圈包络 → **ADC** ✓ |
| **3** | **PA2**（ADC_IN0）| `DATA_IN`（链上游，**收**）✓ |
| 4 | VSS | `GND` ✓ |
| **5** | **PD0** | `DATA_OUT`（链下游，**发** —— 再生转发给下一块 ✓）|
| 6 | VDD | `5V` ✓ |
| 7 | PC0 | 备用 |
| 8 | PC1 | 备用（也是 `SPI_NSS`）|
| 9 | PC2 | 备用 |
| 10 | PC3 | 备用 |
| 11 | PC4（ADC_IN2）| 备用（第 2 路 ADC ✓）|
| 12 | PC5 | 备用（`SPI_SCK`，本设计不引出 ✓）|
| **13** | **PC6**（`SPI_MOSI`）| `LED1.DIN` ✓ |
| 14 | PC7 | 备用（`SPI_MISO`）|
| **15** | **PD1** | SWIO 烧录（留测试点，平时悬空 ✓）|
| 16 | PD2（ADC_IN3）| 备用 |
| 17 | PD3（ADC_IN4）| 备用 |
| 18 | PD4（ADC_IN7 / OPA `OPO`）| 备用（要放大时用 ✓）|
| 19 | PD5（ADC_IN5）| 备用 |
| 20 | PD6（ADC_IN6）| 备用 |

`CH32V002F4U6`（12-bit ADC、无 OPA）与它**同封装同脚位**，可直接换上 ✓。

## 4. 画图步骤（Fritzing GUI）

1. 新建 sketch（**旧 `pixel.fzz` 已作废、不要改它** ✓）→ 保存为 `hardware/pixel/pixel.fzz`；
2. 切到**原理图**视图，从 MINE / core 拖入 §1 的元件（MINE 搜型号：`CH32V003F4U6` ✓、`WS2812B_1010_1` ✓、`SH-1.0-3P-V` ✓…）；
3. 排布（左 → 右）：`L1 → D1 / D2 → R1 / C1 → U1 → LED1`；`5V / GND / DATA_IN / DATA_OUT` 四个网络标签放在 U1 两侧；
4. 按 §2 连线（Fritzing 会自动吸附到引脚端点）；
5. 保存后把 fzz 给我 —— 我读里面的 `wire` 元素**逐条核对网表**（和核对 single-channel 一样的方式）。
6. 作图规则（网格/位号/命名/字体）**沿用库仓**：`fritzing-parts-langhua/docs/schem-drawing-rules.md` ✓；
   画完可先自核一遍：`py -3.13 <库仓>\tools\sch_style_check.py hardware\pixel\pixel.fzz`
   （网格只作参考 ✓；**位号重复 / 名字只差大小写**会报 FAIL ✓）。

## 5. 暂不做

- **PCB 布局**：等 coupon 实测（20 / 22 mm 间距、孔内元件衰减）出来再做（见 [`README.md`](README.md) §6 与 [`coupon-layout.md`](coupon-layout.md)）；
- **面包板视图**：项目约定不画。

## 6. 备注

- **`BAS70BRW` 一颗就是整个全波桥** ✓（内部已是两对串联）：`AC1`(pin6) / `AC2`(pin3) = 线圈两端，
  `C1`(pin5) + `C2`(pin4) = `BR+`，`A1`(pin1) + `A2`(pin2) = `GND` ✓ —— **不要再外接二极管** ✗；
- 整流输出 `BR+` 要 < VDD（场强过大时加钳位，见 README §3 的"过压钳位（可选）"）；
- 固件里 LED 时序用 **SPI + DMA** 产生 ✓（QFN20 有 SPI ✓，走 `SPI_MOSI` = **pin 13**；见 README §5.2）；
- **EPAD（pin 0）单独一根线到 GND** ✓（库规则：它**不在任何总线里**，别指望自动连上 ✗）；
- 接插件针序 **`5V` / `GND`（居中）/ `DATA`**，两口**同型、都能当上游或下游用** ✓（固件自动识别哪边在收 ✓）；
  但板上 `DATA_IN` / `DATA_OUT` 是**两根网**（`PA2` / `PD0`）、**不许短接** ✗ —— 详见 [`connector-plan.md`](connector-plan.md) ✓。
