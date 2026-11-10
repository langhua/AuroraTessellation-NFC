# -*- coding: utf-8 -*-
r"""台架（面包板）网表 = **板上网表 ＋ 台架第二轮补料**

★ 为什么要**单独一个文件** ✓（2026-11-10 ✓，用户定：面包板跟最新网表一致 ＋ 加 A/B ✓）：
  `pixel_nets.py` 是 **PCB / 原理图** 的判据（= v0.1.3 的 BOM ✓）；台架上多两件 ✓：
  - `C3` = **100 µF 电解**（Fritzing 核心件 `MediumElectrolyticCapacitorModuleID` ✓，
    `connector1` = `+` / `connector0` = `-` ✓）⇒ 储能，跨在 `5V` 与 `GND` 之间 ✓；
  - `R5` = **100 Ω** ⇒ 串进 LED 数据线（`PC6` → `LED2.DI`）✓ ⇒ 把 `LED_DIN` 拆成两段 ✓。
  混进 `pixel_nets.py` ✗ ⇒ **PCB 判据**会要求板上也有这两件 ✗（板上没有 ✓，那是 v0.1.4 的候选 ✓）。
  ⇒ 基础 12 张网**仍然只有一处定义**（`pixel_nets.py` ✓）✓；本文件**只做增量** ✓。

用法 ✓（凡支持 `--nets=` 的工具都可以指它 ✓）：
  · `py -3.13 <库仓>/tools/bb_probe.py    像素.fzz --nets=hardware/pixel/pixel_bench_nets.py`
  · `py -3.13 <库仓>/tools/bb_route4.py   <in>.fzz <out>.fzz --nets=…/pixel_bench_nets.py`
  · `py -3.13 <库仓>/tools/bb_precheck.py <in>.fzz --nets=…/pixel_bench_nets.py`
"""
import os as _os
import sys as _sys

# ★★ 2026-11-10 ✓：`projdata.load()` 是**按路径 exec 本文件**（✗ 不会把本目录塞进 `sys.path` ✗）
#   ⇒ 直接 `from pixel_nets import …` 会 `ModuleNotFoundError` ✗（实测 ✓）
#   ⇒ 先把**本文件所在目录**加进 `sys.path` ✓（与 cwd 无关 ✓）。
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from pixel_nets import COLOR as _COLOR                     # noqa: E402,F401
from pixel_nets import EXPECT as _BOARD_EXPECT             # noqa: E402
from pixel_nets import NETS as _BOARD_NETS                 # noqa: E402
from pixel_nets import POWER, POWER_SPEC                   # noqa: E402,F401  （原样转发 ✓）

NETS = {k: list(v) for k, v in _BOARD_NETS.items()}

# ── ① R5（100 Ω）：LED 数据线加阻尼 ⇒ 拆成 `LED_DIN`（MCU 侧）+ `LED_DIN_L`（灯珠侧）──
#   ★ 值取 **100 Ω** ✓（与板上 `R3`/`R4` 同值 ✓ ⇒ BOM 少一个阻值 ✓）
NETS["LED_DIN"] = [p for p in NETS["LED_DIN"] if p[0] != "LED2"] + [("R5", "#1")]
NETS["LED_DIN_L"] = [("R5", "#2"), ("LED2", "DI")]

# ── ② C3（100 µF 电解）：`+`（connector1）→ `5V`、`-`（connector0）→ `GND` ──
#   ★ 极性不能接反 ✗（电解反接会鼓 ✗）；核心件的连接器名就是 `+` / `-` ✓
NETS["5V"].append(("C3", "+"))
NETS["GND"].append(("C3", "-"))

# ── ③ R6（1 MΩ）= **`BR+` → `GND` 的直流泄放** ✓（2026-11-10 ✓）─────────────────
#   为什么 ✗（实测 ✓，见 `data-acquisition.md` §10.10）：`BR+`（`D3` 两阴极 ＋ `R1` 上端）
#   对地**没有直流通路**（`D3` 反偏、`C1` 隔直）⇒ 电平由泄漏平衡决定
#   ⇒ 无信号时读数在 0.1–0.5 V 之间**分钟级漂移** ⇒ 灯在「浅蓝 ↔ 绿」之间自己跳 ✗。
#   ★ 必须加在 **`BR+`** 上 ✗ 加在 `RC` 上没用（`R1` 会把它重新拉向 `BR+` ✓）。
#   ★ 取值 1 MΩ：`50 nA × 1 MΩ = 50 mV` ⇒ 落在暖白/无信号区 ✓；太小会把包络拉低 ✗。
NETS["BR+"].append(("R6", "#1"))
NETS["GND"].append(("R6", "#2"))

# ── 增量后的期望表（`check_netlist` / `bb_probe` 用 ✓）────────────────────────────
EXPECT = {k: set(v) for k, v in _BOARD_EXPECT.items()}
EXPECT["LED_DIN"] = (EXPECT["LED_DIN"] - {"LED2.connector2"}) | {"R5.connector0"}
EXPECT["LED_DIN_L"] = {"R5.connector1", "LED2.connector2"}
EXPECT["5V"] = EXPECT["5V"] | {"C3.connector1"}
EXPECT["GND"] = EXPECT["GND"] | {"C3.connector0"} | {"R6.connector1"}
EXPECT["BR+"] = EXPECT["BR+"] | {"R6.connector0"}

# ── 颜色 ✓（只能取官方配色表 ✓，`breadboardView` 那节 ✓；见 `pixel_nets.py` 的说明 ✓）──
#   ★ `LED_DIN_L` 与 `LED_DIN` **同色** ✓：它们是**同一根信号**、只隔一个串阻 ✓
#     （AGENTS §11：13 色只能用 11 个 ⇒ 共用要挑语义成对的 ✓；剩下两色是黄/白，
#       面包板上黄不明显 ✗、白几乎看不见 ✗ ⇒ 都不用 ✓）
COLOR = dict(_COLOR)
COLOR["LED_DIN_L"] = COLOR["LED_DIN"]
