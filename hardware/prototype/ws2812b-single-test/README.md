# WS2812B 单颗测试（ESP32-S3-DevKitC-1）

验证单颗 WS2812B-5050 灯珠 + ESP32-S3 的最小点亮回路。✅ 已实测通过（2026-08-28）。

## 接线（已实测）

| ESP32-S3-DevKitC-1 | WS2812B-5050 | 说明 |
|---|---|---|
| `3V3` | `VDD` | 电源 3.3V（**实测用 3V3，不用 5Vin**，见下） |
| `GPIO15`（丝印 `15`，库内 connector7） | `DI` | 数据输入 |
| `GND` | `GND` | 共地 |
| — | `DO` | 空接 |

> ⚠️ **丝印核对**：GPIO15 在板子上丝印标号是 **`15`**（不是 `7`）。丝印标 `7` 的是 GPIO7（connector6）。按丝印字母找，别按位置数。

> ⚠️ **电源备注**：本板 `5Vin` 实测读 **0V**（USB 供电下仍为 0，板子本身能跑、板载灯正常），改用 **`3V3`** 给 VDD 后外部灯珠正常点亮。量产方案需另定电源路径（或修 5V 问题，或 3V3 供电）。

## 依赖（已装好）

- `arduino-cli` 1.2.2
- 核心：`esp32:esp32` 3.3.3
- 库：`Adafruit NeoPixel` 1.15.5

## 编译 + 烧录（arduino-cli）

```powershell
# 1) 确认板子 COM 口
arduino-cli board list

# 2) 编译（FQBN: ESP32S3 Dev Module）
arduino-cli compile --fqbn esp32:esp32:esp32s3 .

# 3) 烧录（把 COMx 换成实际端口）
arduino-cli upload -p COMx --fqbn esp32:esp32:esp32s3 .

# 4) 看串口日志（115200）
arduino-cli monitor -p COMx --config baudrate=115200
```

> 💡 如果烧录卡住提示连接失败：按住板子 **BOOT** 键不放再点上传，出现 "Connecting..." 时松开。
> 💡 若用 Arduino IDE：工具 > 开发板 > `ESP32S3 Dev Module`，管理库装 `Adafruit NeoPixel`，直接上传即可。

## 预期现象（已实测）

- 红灯渐亮 → 绿灯渐亮 → 蓝灯渐亮
- 红 / 绿 / 蓝 各常亮 1 秒
- 白灯常亮 1 秒
- 熄灭 1 秒后循环

## 测试结果（2026-08-28）

| 项 | 结果 |
|---|---|
| 板载 WS2812 (GPIO48) | ✅ 正常循环 |
| 外部 WS2812B-5050 (GPIO15) | ✅ 3V3 供电正常点亮 |
| 5Vin 供电 | ❌ 实测 0V，改用 3V3 |
| Adafruit NeoPixel 1.15.5 | ✅ 编译烧录正常 |

若灯不亮，先检查 VDD 是否接到了 3V3、GND 是否共地、DI 是否接在丝印 `15` 上。
