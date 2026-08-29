# AuroraTessellation-NFC
Aurora Tessellation NFC（NFC极光镶嵌）：一款桌面级NFC磁场可视化工具。灵感来自极光——太阳风在地球磁场中留下的光痕；用64个线圈组成的“磁像素”阵列，将13.56 MHz的近场磁场分布实时呈现为极光热力图。

## 项目状态

当前从 4×4、16 通道子板开始验证，使用 ESP32-S3 和 4×4 WS2812B 显示模块。第一阶段采用“全波整流 + TS3A44159 差分背景采样”方案，实施顺序和验收标准见 [4×4 子板验证文档](docs/phase-1-4x4-validation.md)。

### Fritzing 部件进度（fritzing-parts-langhua）

| 部件 | 状态 |
|---|---|
| NFC Coil（20mm 6 匝平面感应线圈） | ✅ 已完成并提交 |
| coil_4x4_array（φ19mm 4×4 阵列铜层） | ✅ 已完成 |
| BAT54S（SOT-23 双肖特基二极管） | ✅ 已完成并提交 |
| TS3A44159（TSSOP-16 差分开关） | ✅ 已完成并提交（`TS3A44159PWR.fzpz`，引脚 13~16 已按 SCDS225 核对） |
| CD74HC4067（24 脚 MUX） | ✅ 已完成并提交（`CD74HC4067.fzpz`，四视图 icon/schematic/breadboard/PCB 按 datasheet 绘制） |

## 文档

- [4×4 子板验证文档](docs/phase-1-4x4-validation.md)
- [Fritzing 自定义部件开发指南](../fritzing-parts-langhua/docs/part-dev-guide.md)（位于 fritzing-parts-langhua 部件库，做 BAT54S、TS3A44159 等部件前必读）

## 重要设计说明

本项目输出的是 13.56 MHz NFC 近场磁场的相对分布，不等同于经过校准的 A/m 绝对场强测量仪。打板前必须确认整流拓扑：BAT54S 是双二极管器件，不能直接视为完整四二极管全波整流桥。
