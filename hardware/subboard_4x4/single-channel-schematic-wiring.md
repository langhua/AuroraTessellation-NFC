# 传感器子板·原理图接线说明（1×8 接口，无 MCU）

> 对应 `single-channel.fzz` 的**原理图/PCB 视图**。子板上**没有 MCU**：8 路接口信号用 **8 个网络标签**（Fritzing 核心 `Net Label`，标注 `ESP32-S3-DevKitC-1 IO1/IO2/3V3/IO4/IO5/IO6/IO7/GND`）标出对应 ESP32 开发板/控制板引脚，接独立的 **ESP32 控制板**（含 WROOM-1 + USB Type-C + CH340 + 3.3V LDO + EN/BOOT，待建）。
> 面包板原型接线见 [`single-channel-breadboard-wiring.md`](single-channel-breadboard-wiring.md)。

## 架构（方案 C）

```text
传感器子板                          ESP32 控制板（独立，待建）
 线圈→整流→RC→TS3A→MUX                 WROOM-1 + USB-C + CH340 + LDO
        │                                  │
        └─ 8×网络标签(ESP32 引脚标注) ──引线── 对应接口
          VCC GND SIG S0 S1 S2 S3 SEL       IO1 IO2 IO4-7 ...
```

## 信号链

```text
两线线圈
  -> 2 × BAT54S 全波桥（BR+ / BR-）
  -> R=10 kΩ 串联、C=100 nF 对地低通
  -> TS3A44159 COM（NO=通道输出，NC=GND 背景采样）
  -> CD74HC4067（MUX，C0~C15）
  -> J1.SIG -> ESP32 控制板 ADC1（GPIO1/IO1）
```

## 元件清单（库内元件）

| 编号 | 元件 | 连接器 |
|---|---|---|
| U整流A/B | `BAT54S.fzpz` | `A1`(1) / `node`(3) / `K2`(2) |
| **U3**（MUX） | `CD74HC4067.fzpz` | `C0~C15`(connector0..15) / `SIG`(16) / `S0~S3`(17..20) / `EN`(21) / `VCC`(22) / `GND`(23) |
| **U2** | `TS3A44159PWR.fzpz` | `NO1`(connector12)/`COM1`(13)/`NC1`(14)、`IN1-2`(15)、`IN3-4`(7)、`VCC`(11)、`GND`(3)（NO2-4/COM2-4/NC2-4 同序） |
| **J1**（接口） | 自建 `NetLabel-Pad` ×8 | 8 个网络标签，PCB 上生成 8 个实体过孔焊盘（PAD-2.0-H1.0：Ø2.0mm 焊盘 / Ø1.0mm 钻孔，2.54mm 间距），标注信号对应 ESP32 开发板/控制板引脚（`IO1/IO2/3V3/IO4/IO5/IO6/IO7/GND`） |
| L1 | `NFC-Coil.fzpz` | `inner` / `outer` |
| R1 / C1 | 核心元件 | 10 kΩ / 100 nF |

> 注：TS3A 括号内为**库内 connector 编号**（= 物理脚 − 1，如 NO1=物理 13 脚→connector12）。

## J1 接口定义（8 个过孔焊盘，EN 子板固定接地）

> 下表为**实际物理脚序**（PnP 实测，板右缘一列，上→下）：`3V3, IO1, IO2, IO4, IO5, IO6, IO7, GND`。
> 3V3（VCC）与 GND **分居两端**（相距 7 个焊盘），不会互相短路。

| 脚（上→下） | 标签 | 信号 | 去向 | 对应 ESP32 控制板 |
|---|---|---|---|---|
| 1（顶） | `3V3` | VCC | MUX VCC + TS3A VCC | 3V3 |
| 2 | `IO1` | SIG | MUX 公共输出 | IO1（ADC1_CH0，GPIO1） |
| 3 | `IO2` | SEL | TS3A IN1-2/IN3-4（并联） | IO2（GPIO2） |
| 4 | `IO4` | S0 | MUX 地址 0（LSB） | IO4（GPIO4） |
| 5 | `IO5` | S1 | MUX 地址 1 | IO5（GPIO5） |
| 6 | `IO6` | S2 | MUX 地址 2 | IO6（GPIO6） |
| 7 | `IO7` | S3 | MUX 地址 3（MSB） | IO7（GPIO7） |
| 8（底） | `GND` | GND | 全子板地（MUX/TS3A/桥/RC/EN） | GND |

> MUX `EN` 已在子板上接 GND（低有效常开），不引出。
> 接口在原理图上用 8 个网络标签表示，标签文字标出对应 ESP32 控制板引脚（IO1/IO2/IO4~IO7/3V3/GND）。这 8 个网络标签使用自建 **`NetLabel-Pad`** 元件（2026-08-30，2026-08-31 更新），**PCB 上已生成 8 个实体过孔焊盘**（**PAD-2.0-H1.0**：Ø2.0mm 焊盘 / Ø1.0mm 钻孔，**2.54mm 间距**，Bottom 面右缘一列），已实测：PnP 为 `PAD-2.0-H1.0`、drill 文件有 8×Ø0.97mm 钻孔（2026-08-31 从 PAD-1.2-H0.6 无钻孔改为现封装，焊盘环用 circle 才能生成钻孔）。**标准 2.54mm 排针可直接插入**。

## 子板网表（通道 1 为例）

| 起点 | 终点 | 说明 |
|---|---|---|
| L1 `inner` | U整流A.`node` | 线圈一端接桥 A 中点 |
| L1 `outer` | U整流B.`node` | 线圈另一端接桥 B 中点 |
| U整流A.`A1` | GND | BR- |
| U整流B.`A1` | GND | BR- |
| U整流A.`K2` | `BR+` | 整流输出正 |
| U整流B.`K2` | `BR+` | 整流输出正 |
| `BR+` | R1(10 kΩ) | 串联电阻 |
| R1 另一端 | `node_RC` | 低通节点 |
| `node_RC` | C1(100 nF) → GND | 低通滤波 |
| `node_RC` | U2.`COM1` | 滤波输出进开关 |
| U2.`NO1` | U3.`C0` | 通道 1 输出 → MUX（裸芯片 `I0`=9 脚） |
| U2.`NC1` | GND | 背景采样路径 |
| U2.`IN1-2` / `IN3-4` | J1.`SEL` | 两脚并联到同一 SEL |
| U2.`VCC` | J1.`VCC` | 3.3V 由控制板供给 |
| U2.`GND` | J1.`GND` | |
| U3.`VCC` | J1.`VCC` | 裸芯片 24 脚 |
| U3.`GND` | J1.`GND` | 裸芯片 12 脚 |
| U3.`EN` | GND（子板） | 低有效常开 |
| U3.`S0`~`S3` | J1.`S0`~`S3` | 通道选择，S0 最低位（裸芯片 10/11/14/13：S0=10、S1=11、S2=14、S3=13） |
| U3.`SIG` | J1.`SIG` | 16 路选通输出（裸芯片 1 脚 COM） |

## ESP32 控制板 GPIO 对应（待建板）

| 用途 | GPIO | WROOM-1 引脚 | 库内连接器 |
|---|---|---|---|
| J1 `SIG`（ADC1_CH0） | GPIO1 | IO1 | connector38 |
| J1 `SEL` | GPIO2 | IO2 | connector37 |
| J1 `S0` | GPIO4 | IO4 | connector3 |
| J1 `S1` | GPIO5 | IO5 | connector4 |
| J1 `S2` | GPIO6 | IO6 | connector5 |
| J1 `S3` | GPIO7 | IO7 | connector6 |
| WS2812B `DI`（显示，如用） | GPIO15 | IO15 | connector7 |
| 板载 WS2812（未用） | GPIO48 | IO48 | connector24 |

> ADC1 = GPIO1~GPIO10（CH0~CH9）。J1 `SIG` 接控制板 **GPIO1/IO1（ADC1_CH0，connector38）**，Arduino 里 `analogRead(1)` / `analogReadMilliVolts(1)` 读取（0~3.3V → 0~4095）。
> ⚠️ 整流输出须 < 3.3 V（ESP32 ADC 量程）；若场强过大需加钳位（如 3.3 V 齐纳）。
