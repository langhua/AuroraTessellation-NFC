# 布线工具：实测查出的真 bug 与 Fritzing 事实

> 立此存照（2026-10-03 ✓，全部**实测** ✓，每条附**复现命令** ✓）。
> 缘起：用户从 `pixel-pcb-v51_byHand.fzz` 开始"重新排布元件和布线" ✓。
> 结论一句话：**这轮挖出的三处硬伤都在我们自己的工具里** ✗，**不是**用户的画法 ✗。
> 文件名里的 `<...>` 与命令都可在 `hardware/pixel/` 下原样跑（诊断脚本在 `_work/`，**不入库** ✓）。

---

## BUG-1 ✗✗ `model["net_pads"]` 从未写回 ⇒ "同网豁免"形同虚设 ⇒ 报"起点格空"

**症状**：`BR+` / `DATA_IN` / `DATA_OUT` / `LED_DIN` 四张网永远布不通，原因写的是
`不可达/可达=False 起点格空`。

**根因（实测）**
- `pcb_route.obstacles()` 的注释写着：「布某张网时，把 `tag == 本网` 的障碍**减掉**」✓，
  它读的是 **`model["net_pads"]`** ✓；
- 而 `pcb_route.resolve_nets()` **只返回结果、不写回 `model`** ✗
  ⇒ 那张表**长期为空** ✗ ⇒ **每只焊盘都算不出网名** ✗
  ⇒ 邻居焊盘的盘框**永不被豁免** ✗ ⇒ 0.4 mm 脚距的 `U1`(QFN20) / `D3`(SOT363) 上，
  **起步格被隔壁盘框盖住** ✗。

**证据**（`_work/probe_start.py` ✓）
```
修改前： U1.connector2  中心 (46.08, 16.97) mm ⇒ 判到的网 = None  ✗
修改后： U1.connector2  中心 (46.08, 16.97) mm ⇒ 判到的网 = DATA_IN ✓
         U1.connector20（EPAD）⇒ 判到的网 = GND ✓（原来是 None ✗）
```
- 注意：**诊断脚本与生产脚本必须同参数** ✓ —— 本文件 BUG-3 后的"教训"一节有血例 ✗。

**修法**：调用方把返回表写回 —— `hardware/pixel/gen_routes.py` 一行 ✓：
```python
net_pads, unresolved = RT.resolve_nets(model, data.NETS)
model["net_pads"] = net_pads          # ★ 让 obstacles() 的同网豁免真正生效
```

**复现**
```
py -3.13 _work\probe_start.py _work\v56_place.fzz pixel_nets.py DATA_IN LED_DIN
```

**遗留**：修好后这四张网**仍未布通** ✗（起终点都干净 ⇒ 堵点在**路中间** ✓）。
`gen_routes` 的失败文案"起点格空"**会误导** ✗（真正被挡的可能是终点或中段），
下一步应给 `pcb_route` 加诊断：**分段失败时打印"起点泛洪到的格数 / 目标是哪个格 / 是否可达"**。

---

## BUG-2 ✗✗ 走线可以是**贝塞尔曲线**，我们只读了两个端点、按直线算 ✗

**Fritzing 的文件写法**（实测 `Wire90013354` ✓）
```xml
<geometry z="6.50017" x="187.799" y="81.5189" x1="0" y1="0" x2="7.123" y2="-17.751" wireFlags="4"/>
<wireExtras mils="24" color="#f28a00" opacity="1" banded="0">
    <bezier><cp0 x="0" y="0"/><cp1 x="7.92489" y="-7.57775"/></bezier>
</wireExtras>
```
**源码口径**（`F:\build-fritzing\fritzing-app\src\utils\bezier.h` ✓）
`Bezier(QPointF endpoint0, QPointF endpoint1, QPointF cp0, QPointF cp1)`
⇒ **三次贝塞尔 = 两个端点 ＋ 两个控制点**；端点**就是** `<geometry>` 那条线，
`cp0/cp1` 与 `x1..y2` **同一局部坐标系**（实测 `cp0=(0,0)` 正好 = 弦的起点 ✓）。
另有 2 个 `<geometry x="0" y="0"/>` 是"该实例不在那两个视图"的**占位** ⇒ 必须跳过 ✗。

**后果**（本板 25 根 PCB 走线里 **17 根是曲线** ✗）
- 线间距 ✗：`Wire90013354`(5V) ↔ `Wire90013339`(GND) —— 按弦算 **0.0733 mm** ✗，
  按曲线采样算 **0.7653 mm** ✓（差 0.69 mm ✗，结论从"疑似短路"翻成"比 0.127 mm 最小间距宽 6 倍" ✓）；
- 交叉判定 ✗、保线**障碍框** ✗（只框两端 ⇒ 弯的中段没人管 ✗）、渲染 ✗。

**修法**：`fritzing-parts-langhua/tools/pcb_wire.py`
- `parse_trace()` 补读 `<bezier>` ✓；新增 `curve_pts(geo, bezier, n)` 采样 ✓（**全仓唯一读法** ✓）；
- 消费方：`fz_keep_set.py` 存折线 ✓ ⇒ `gen_routes --keep` 逐段生成障碍框 ✓。

**复现**
```
py -3.13 _work\curve_check.py pixel-pcb-v51_byHand.fzz Wire90013354 Wire90013339
```

---

## BUG-3 ✗ `write_back` 的块扫描靠"同缩进配对" ⇒ 会**少一个实例**

**症状**：`gen_pcb.py` 写回后，实例数 **113 → 112** ✗（块边界被切错，上锁件也会莫名多/少几字节 ✗）。

**根因**：旧正则 `^([ \t]*)<instance\b.*?\n\1</instance>` 依赖**闭合标签与开标签同缩进** ✗；
Fritzing 的缩进并不总是这样 ✓ ⇒ 错位 ✗。

**修法**（`hardware/pixel/gen_pcb.py`）：按 `<title>` 定位 ⇒ `rfind("<instance")` / `find("</instance>")` ✓
（与 `fz_strip_pcb.blocks_of` **同一口径** ✓）。

**复现**
```
py -3.13 _work\block_diff.py _work\v51_clean.fzz _work\v51_lockplace.fzz --locked-only
```

---

## 三条**流程**教训（比 bug 本身更值钱）

1. **诊断脚本必须与生产脚本同参数** ✗ —— 本次探针忘了设 `RT.TRACE_MM`（生产 = 8 mil），
   用了模块默认 24 mil ⇒ 障碍加肥 0.6096/2+0.15 = **0.4548 mm** ✗ ⇒ 造出**假的**
   "EPAD 盖住 LED2.connector2" ✗。**同一类坑本次犯了三次** ✓。
2. **判据必须同源** ✓ —— "两根线相距 0.073 mm""两根线交叉""导出图把线截短" 全是自造判据的产物 ✗；
   换成"读 `<bezier>` + 采样"后就一致了 ✓。
3. **对不上时先怀疑自己** ✓ —— 用户三次指出"你的解析与 Fritzing 不一致"（曲线 ✓、
   多层几何 ✓、颜色写错 ✓），每次都是我对 ✗。

---

## 附：可直接引用的 Fritzing 事实（都有出处 ✓）

| 事实 | 出处 / 复核方式 |
|---|---|
| **锁** = 移动锁，写 `<pcbView locked="true">` | `itembase.cpp:294` 写 / `sketchwidget.cpp:281,318` 读设 / `:1076,:2442,:7162` 拦移动 / `connectoritem.cpp:2508` / `resizableboard.cpp:1228` |
| 一个实例**每个视图只有一个** `<geometry z=…>`（另有 2 个 `x=0,y=0` 占位） | `_work/view_geoms.py <fzz> Wire90013354` |
| 端点 = `loc+(x1,y1)` / `loc+(x2,y2)` | `viewgeometry.cpp` 的 `ViewGeometry(QDomElement&)` |
| PCB 走线/过孔 = 带 `<pcbView>` 的 `Wire`/`Via` 实例 | `_work/dump_wires2.py` |
| 用户手画线在导出图里按 **24 mil** 渲染（`.fz` 里可能写 22.2222 mil） | 导出 SVG 的 `stroke-width="1.728"`（1 pt = 0.35278 mm） |
| 导出 SVG：1 单位 = 1 pt、1 mm = 72/25.4、板原点由板框反推 | `fz_overlay2.py`（已校准到与板组 `translate` 一致 ✓） |

---

## 2026-10-03 续：`--why` 诊断补齐 ⇒ 四张网"堵在哪"有答案了 ✓

### 先修掉一个**让诊断看不见**的崩 ✗

`gen_routes.py` 的「保线」段里有个循环变量叫 **`key`** ✗ —— 它把**模块级函数** `key()`
**遮蔽**掉 ✓ ⇒ 后面写回自检调 `key(...)` 时抛
`TypeError: 'str' object is not callable` ✗ ⇒ **main 崩在半路** ✗
⇒ 打印"为什么布不通"那一段**根本跑不到** ✗。

⇒ 教训：我把"诊断没出现"先归因成"终端输出被截断" ✗ —— **错的** ✓；
先用 `2>&1 | Out-File -Encoding utf8` **落盘**再读 ✓，一眼就看见 traceback ✓
（PowerShell 的 `*>` 默认写 UTF-16 ✗，直接读是乱码 ✗ ⇒ 用 `_work/showlog.py` ✓）。

### 诊断做了什么 ✓

| 改动 | 位置 | 作用 |
|---|---|---|
| `Grid.OWN` + `self.own` | `pcb_route.py` | 记录**每个被挡格子的出处** ✓（默认**关** ✗ ⇒ 不开 `--why` 时速度/结果**一字不变** ✗，已实测 ✓） |
| `obstacles()` 多返回 `labels` | 同上 | 与 `items` **逐条对齐**的出处表 ✓（`盘:U1.connector3` / `件铜:L1` / `安装孔(Ø2.2 mm)` ✓） |
| 各挡块点贴标签 | `_route_once` | `盘:…`、`线:…`、`过孔:…`、`保线:…`、`板边` ✓ |
| `_why_report` / `boundary_report` / `grid_free` | 同上 | ① 起/终点**紧邻一圈**逐格报到谁挡的 ✓；② 可达区**边界**上是谁（按格数排序 ✓）；③ 全板可走格数（判"可达 N 格"是大是小 ✓） |
| **判决**（算出来 ✗，不写死 ✗） | 同上 | 起点侧大/终点侧小 ⇒ **终点口袋** ✓；反之 ⇒ **起点扇出口袋** ✓ |
| 只留**胜出那份**的诊断 | `route` / `route_ripup` | 6 种次序各报一遍 = 6 倍噪音 ✗，且**最后那遍未必是胜者** ✗ ⇒ 会把不存在的病报出来 ✗ |

### 结论（`_work/v56_place.fzz` + 用户保线 ✓，最终解 = 连通 5/9）

| 网 | 段 | 起点侧 | 终点侧 | **围住它的是谁** |
|---|---|---|---|---|
| `DATA_IN` | `U1.connector2→J1.connector2` | **39 格** ✗ | 25154 ✓ | `线:GND×18`、`盘:U1.connector3×9`、`盘:U1.connector1×7` |
| `DATA_OUT` | `U1.connector4→J2.connector2` | **44 格** ✗ | 25159 ✓ | `线:GND×19`、`盘:U1.connector3×9`、`过孔:5V×6` |
| `LED_DIN` | `U1.connector12→LED2.connector2` | **33 格** ✗ | **56 格** ✗ | 起点：`盘:U1.connector11/13/20`、`线:COIL_A×7`；终点：`线:GND×22`、`盘:LED2.connector1/3` |
| `BR+` | `D3.connector3→R1.connector0` | 15718 ✓ | **1321 格** ✗ | `线:5V×55`、`线:GND×49`、`过孔:GND×15`、`盘:C1.connector0×13` |

（全板可走 ≈ **25 000～27 400 格** ✓ ⇒ "可达 39 格"就是**0.15%** ✗，一眼看出是口袋 ✓）

### 病根一句话 ✓

**已经布好的 `GND` / `5V` 铜（含用户保线那几条 ✓）＋ QFN 的邻脚**，把要接的脚
**围成小口袋** ✗ —— 正是仓规 §5b ⑩「留路」那条病 ✓（先布的线把后布的路占掉 ✗）。
⇒ 下一步该动的**不是判据/系数** ✗，而是**布的次序与走廊预算** ✓（待与用户对齐 ✓）。

