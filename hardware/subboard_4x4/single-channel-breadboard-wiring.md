# 传感器子板·面包板接线说明（SYB-118，无 MCU）

> 对应 `single-channel.fzz` 的**面包板视图**。面包板上是**子板元件**（线圈/整流/RC/TS3A/MUX）+ **J1 接口（8 路信号）**；**没有 MCU**。
> ESP32 在独立**控制板**（开发板或待建板，带 USB 供电/调试），经 **J1 引线**接到子板。子板原理图接线见 [`single-channel-schematic-wiring.md`](single-channel-schematic-wiring.md)。

## 布局总览

用 **2 块 SYB-118 面包板**（下称 BB2、BB3），子板元件分布：

```
BB2（左板）                          BB3（右板）
┌──────────────────────────┐        ┌──────────────────────────┐
│ L1 线圈 → A 列             │        │ U2 TS3A44159 → C/F 列     │
│ D1/D2 整流桥 → E/F 列       │        │ （pin37C~44C, 37F~44F）    │
│ R1/C1 RC 低通 → F/H/I 列    │        │                          │
│ MUX（U3）→ D/H 列          │        │                          │
│ （pin43H~58H, 47D~54D）    │        │                          │
│ J1 接口（8 路）→ 空白区   │        │                          │
└──────────────────────────┘        └──────────────────────────┘
```

> 插座记法：`pin<行号><列字母>`，如 `pin19J` = 第 19 行 J 列孔。列 A~E 一组、F~J 一组，同组相邻 5 孔内部连通。
> ⚠️ 原开发板占用的插座（BB2 的 J 列、BB3 的 D 列）现为空，J1 的 8 路信号可用跳线从元件引出到开发板。

## J1 · 接口引出（8 路信号 → 网络标签）

> 原理图上接口用 8 个网络标签标注（`ESP32-S3-DevKitC-1 IO1/IO2/3V3/IO4/IO5/IO6/IO7/GND`）；面包板实物用跳线把各信号引到开发板。

| 针 | 信号 | 去向（子板） |
|---|---|---|
| 1 | `VCC` | MUX `VCC`、TS3A `VCC` |
| 2 | `GND` | 全子板地 |
| 3 | `SIG` | MUX `SIG` |
| 4 | `S0` | MUX `S0` |
| 5 | `S1` | MUX `S1` |
| 6 | `S2` | MUX `S2` |
| 7 | `S3` | MUX `S3` |
| 8 | `SEL` | TS3A `IN1-2`/`IN3-4` |

## 元件插孔表（每个脚→面包板插座）

### U3 · CD74HC4067（MUX，BB2）

| 端子 | 插座 | 端子 | 插座 |
|---|---|---|---|
| C15 | `pin43H` | C14 | `pin44H` |
| C13 | `pin45H` | C12 | `pin46H` |
| C11 | `pin47H` | **SIG** | `pin47D` |
| C10 | `pin48H` | **S3** | `pin48D` |
| C9 | `pin49H` | **S2** | `pin49D` |
| C8 | `pin50H` | **S1** | `pin50D` |
| C7 | `pin51H` | **S0** | `pin51D` |
| C6 | `pin52H` | **EN** | `pin52D` |
| C5 | `pin53H` | **VCC** | `pin53D` |
| C4 | `pin54H` | **GND** | `pin54D` |
| C3 | `pin55H` | | |
| C2 | `pin56H` | | |
| C1 | `pin57H` | | |
| **C0** | `pin58H` | | |

### U2 · TS3A44159（BB3）

| 端子 | 插座 | 端子 | 插座 |
|---|---|---|---|
| **IN1-2** | `pin37C` | NO2 | `pin37F` |
| **NC1** | `pin38C` | COM2 | `pin38F` |
| **COM1** | `pin39C` | NC2 | `pin39F` |
| **NO1** | `pin40C` | **GND** | `pin40F` |
| **VCC** | `pin41C` | NO3 | `pin41F` |
| NC4 | `pin42C` | COM3 | `pin42F` |
| COM4 | `pin43C` | NC3 | `pin43F` |
| NO4 | `pin44C` | **IN3-4** | `pin44F` |

### L1 · NFC 线圈 / D1·D2 整流桥 / R1·C1 RC 低通（BB2）

| 元件 | 脚 | 插座 |
|---|---|---|
| L1 | inner | `pin28A` |
| L1 | outer | `pin35A` |
| D1 | A1 | `pin27F` |
| D1 | node | `pin28E` |
| D1 | K2 | `pin28F` |
| D2 | A1 | `pin34F` |
| D2 | node | `pin35E` |
| D2 | K2 | `pin35F` |
| R1 | 端1 | `pin28I` |
| R1 | 端2 | `pin31F` |
| C1 | 端1 | `pin31H` |
| C1 | 端2 | `pin34H` |

## 信号跳线表

元件插入后，按以下网络用跳线把对应插座连起来（同网即同电气节点）：

| 网络 | 插座（→ 脚） | 说明 |
|---|---|---|
| 通道1输出 | `BB2 pin58H`(MUX C0) ↔ `BB3 pin40C`(TS3A NO1) | 选通通道 1 → MUX |
| BR+ | `BB2 pin28F`(D1 K2) ↔ `BB2 pin28I`(R1 端1) | 整流输出 → RC 串联电阻 |
| node_RC | `BB2 pin31F`(R1 端2) ↔ `BB2 pin31H`(C1 端1) | RC 节点（→ TS3A COM1） |
| 线圈→桥 | L1 inner `pin28A` ↔ 桥A node `pin28E`；L1 outer `pin35A` ↔ 桥B node `pin35E` | 线圈两端接整流桥中点 |
| BR-（GND） | D1 A1 `pin27F`、D2 A1 `pin34F` → GND 电源轨 | 桥负极接地 |
| node_RC→TS3A | `BB2 pin31H`(C1 端1) ↔ `BB3 pin39C`(TS3A COM1) | 滤波输出进开关 |
| TS3A NC1→GND | `BB3 pin38C`(NC1) → GND | 背景采样 |
| TS3A SEL→J1 | `BB3 pin37C`(IN1-2)、`pin44F`(IN3-4) ↔ J1 pin8 `SEL` | 选通控制（两脚并联） |
| MUX SIG→J1 | `BB2 pin47D`(SIG) ↔ J1 pin3 `SIG` | 16 路选通输出 → 控制板 ADC |
| MUX 地址→J1 | S0 `pin51D`↔J1 pin4、S1 `pin50D`↔J1 pin5、S2 `pin49D`↔J1 pin6、S3 `pin48D`↔J1 pin7 | 通道选择，S0=最低位 |
| MUX 电源 | VCC `pin53D`→J1 pin1 `VCC`、GND `pin54D`→J1 pin2 `GND`、EN `pin52D`→GND | EN 子板接地常开 |
| C1 端2→GND | `BB2 pin34H`(C1 端2) → GND | 低通滤波对地 |
| 电源轨 | J1 pin1 `VCC` → 3V3 轨；J1 pin2 `GND` → GND 轨 | 由控制板经 J1 供电 |

> ⚠️ 装配前用万用表二极管档确认 BAT54S 实物方向（pin1→pin3→pin2）；整流输出须 < 3.3 V（ESP32 ADC 量程）。
> ⚠️ 面包板视图 = 子板原型（无 MCU）。ESP32 在独立控制板，经 J1 引线供电/读信号；控制板原理图待建。
