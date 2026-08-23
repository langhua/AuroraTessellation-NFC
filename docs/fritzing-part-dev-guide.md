# Fritzing 自定义部件开发指南

本文档总结了为 Aurora Tessellation 制作 `NFC Coil` 部件过程中踩过的坑和验证过的做法。**做下一个部件（BAT54S、TS3A44159 等）时，先读本文，按清单操作，避免重复踩坑。**

---

## 1. 核心原则

1. **不要凭空设计 SVG，先抄官方部件**。官方部件（`Fritzing安装目录/fritzing-parts/svg/core/`）的每个视图都是经过验证的格式，直接仿照能避开 90% 的坑。
2. **`.fzpz` 是最终交付物**，Fritzing 通过导入 `.fzpz` 使用部件。`.fzp` + 4 个视图 SVG 是它的内部构成。
3. **连接器（connector）是灵魂**。图标/符号/焊盘画得再好，连接器定义不对，就无法连线/布线。

---

## 2. 文件结构与打包

### 2.1 部件由 5 个文件组成

| 文件 | 作用 |
|---|---|
| `part.<id>.fzp` | 部件清单：元数据 + 视图引用 + 连接器定义 |
| `svg.breadboard.<id>_breadboard.svg` | 面包板视图 |
| `svg.schematic.<id>_schematic.svg` | 原理图符号 |
| `svg.pcb.<id>_pcb.svg` | PCB 焊盘/走线 |
| `svg.icon.<id>_icon.svg` | 部件库图标 |

### 2.2 `.fzpz` 打包规则（已验证）

- `.fzpz` 本质是 zip，**内部文件平铺**，不放子目录。
- 但 `.fzp` 里的 `image=` 引用**必须用子目录路径**：`icon/xxx.svg`、`breadboard/xxx.svg`、`schematic/xxx.svg`、`pcb/xxx.svg`。

```xml
<iconView><layers image="icon/NFC_Coil_xxx_icon.svg">...</layers></iconView>
<pcbView><layers image="pcb/NFC_Coil_xxx_pcb.svg">...</layers></pcbView>
```

> ⚠️ **坑**：`.fzp` 里如果直接写 `svg.icon.xxx.svg`（平铺名），Fritzing 找不到视图 → 部件库图标空白、视图缺失。这是 NFC Coil 第一版"空白方格"的根因。

**仓库目录约定**：
- 源文件（`.fzp` + 4 个 `svg.*` + 生成脚本）放在 `svg/<部件名>/`。
- 打包好的 `.fzpz` 输出到仓库顶层 `fzpz/` 目录（生成脚本里 `OUT_DIR/../../fzpz`），与其他部件一致。
- `.fzpz` 是给 Fritzing 导入的最终交付物。

---

## 3. `.fzp` 文件关键写法

### 3.1 pcbView 层声明

**通孔元件**必须声明 `copper0`、`copper1`、`silkscreen` 三层：

```xml
<pcbView>
  <layers image="pcb/NFC_Coil_xxx_pcb.svg">
    <layer layerId="silkscreen"/>
    <layer layerId="copper0"/>
    <layer layerId="copper1"/>
  </layers>
</pcbView>
```

### 3.2 连接器定义（通孔元件）

每个 connector 在 `pcbView` 里**同时映射 copper0 和 copper1**，Fritzing 才会生成过孔（via）连接上下层：

```xml
<connector id="connector0" name="inner" type="male">
  <views>
    <breadboardView><p layer="breadboard" svgId="connector0pin"/></breadboardView>
    <schematicView><p layer="schematic" svgId="connector0pin" terminalId="connector0terminal"/></schematicView>
    <pcbView>
      <p layer="copper0" svgId="connector0pin"/>
      <p layer="copper1" svgId="connector0pin"/>
    </pcbView>
  </views>
</connector>
```

> ⚠️ **坑**：如果只映射 `copper1`，切到底层视图看不到焊盘、也无法在底层布线。

---

## 4. 各视图规范与坑

### 4.1 schematic（原理图符号）

**直接复用官方符号**，不自己画弧线。NFC Coil 用的就是官方 `svg/core/schematic/inductor.svg` 原样内容。

结构要点：

```svg
<g id='schematic'>
  ...符号身体（弧线/图形）...
  <line class='pin' id='connector0pin' connectorname='1' x1='..' y1='..' x2='..' y2='..' stroke='#787878' .../>
  <rect class='terminal' id='connector0terminal' x='..' y='..' .../>
</g>
```

> ⚠️ **坑（关键）**：`connectorXpin` 必须带 `class='pin'` 和 `connectorname`，`connectorXterminal` 必须带 `class='terminal'`。**缺少这些属性，导线无法吸附到端子**（原理图里连不上线）。这是 NFC Coil 第二版"原理图无法连线"的根因。
>
> `terminal`（端子）是导线吸附点，必须放在引脚线的最外端。

### 4.2 breadboard（面包板视图）

参考：官方 `svg/core/breadboard/inductor_leg.svg`、`svg/molding_power_inductors/SHC0420/*_breadboard.svg`。

要点：
- 整个视图在 `<g id='breadboard'>` 内。
- `connectorXpin` 是**有填充的实心矩形**（如 `#8C8C8C` 灰色），可以加切面多边形模拟金属质感（SHC0420 风格）。
- 引脚间距**必须是 2.54mm 的整数倍**（标准面包板孔距），例如 7×2.54 = 17.78mm。
- SVG 的 viewBox/灰框尺寸应**与 PCB 视图一致**，避免部件在面包板上看起来过大/过小。

> ⚠️ **坑**：引脚（leg/pin）不要画到板体外；如果部件是"板载元件"，引脚应在板体轮廓内。

### 4.3 pcb（PCB 视图）—— 通孔元件最容易错的地方

参考：官方 `svg/core/pcb/inductor_400mil.svg`。

**正确结构（嵌套）**：

```svg
<g id="copper0">            <!-- 底层（外层） -->
  <g id="copper1">          <!-- 顶层（嵌套在内） -->
    ...走线/焊盘...
    <circle ... id="connector0pin" .../>   <!-- 每个连接器 id 只出现一次 -->
    <circle ... id="connector1pin" .../>
  </g>
</g>
<g id="silkscreen">...</g>
```

> ⚠️ **坑 1（关键）**：`connectorXpin` 每个 id **只能在 SVG 里出现一次**。如果 copper0、copper1 各画一次，Fritzing 把它当成两个独立 SMD 焊盘，不会生成过孔 → 上下层不通。
>
> ⚠️ **坑 2**：不要把预布线（stub/引出线）画进 PCB 视图，布线是用户自己的事，否则底部会多出一根"幽灵导线"。
>
> ⚠️ **坑 3**：焊盘要小，阵列排列时避免与相邻元件焊盘短路。用 `circle`（环形，fill=none + stroke）比实心方块更好——不"盖住"旁边的铜线。

### 4.4 icon（图标）

- 32×32 视口。
- 建议用**面包板视图的图形缩小版**，让部件库里的图标和实际外观一致。
- 图标通常不需要 connector 定义。

---

## 5. 已验证的坑速查表

| # | 症状 | 根因 | 解决 |
|---|---|---|---|
| 1 | 部件库图标空白、视图缺失 | `.fzp` 里 `image=` 用了平铺文件名 | 改用子目录路径 `icon/...`、`pcb/...` |
| 2 | 原理图里导线连不上端子 | `connectorXpin` 缺 `class='pin'`/`connectorname`；`terminal` 缺 `class='terminal'` | 加属性，端子放引脚外端 |
| 3 | 焊盘只在一层、底层无法布线 | connector 的 pcbView 只映射了 `copper1` | 同时映射 `copper0` + `copper1` |
| 4 | 上下层焊盘不通（缺 via） | `connectorXpin` 在 SVG 两层各画一次 | 只在嵌套 `copper0>copper1` 里画一次 |
| 5 | 底部多一根导线 | PCB 视图里预画了 stub | 删掉，只留焊盘 |
| 6 | 焊盘太大、相邻短路 | 焊盘过大/实心 | 用环形小焊盘（circle, r≈0.55） |
| 7 | 面包板引脚间距不符 | 引脚间距不是 2.54 整数倍 | 取 7×2.54 等整数倍 |
| 8 | 符号形状怪异 | 自己画弧线 | 复用官方 `svg/core/schematic/inductor.svg` |

---

## 6. 建议工作流

1. **定位参考部件**：找官方或库里功能最接近的部件（电感→inductor，二极管→SOD-123/SOD-123FL，开关→SHC0420 等），读它的 `.fzp` 和 4 个 SVG。
2. **复制 `.fzp` 结构**，改 `moduleId`、`title`、`properties`、`connectors`（数量/名称）。
3. **逐个做视图**：schematic → breadboard → pcb → icon，每个都对照参考文件的属性。
4. **打包 `.fzpz`**：zip 平铺 5 个文件。
5. **在 Fritzing 实测**（必须实测，不能只靠看代码）：
   - 导入后图标是否显示；
   - 面包板/原理图能否连线；
   - PCB 能否布线、上下层是否通、是否短路。

> 💡 强烈建议用**脚本生成**（如 `gen_part.py`），参数化几何（尺寸、引脚间距），改参数重跑即可，避免手改 SVG 出错。脚本与 SVG 放同一目录。

---

## 7. 生成脚本模板要点

- 输出目录 = `os.path.dirname(os.path.abspath(__file__))`，让部件文件夹自包含、可拷走复用。
- 用 `zipfile` 打包 `.fzpz`，内部平铺。
- 几何参数集中定义在文件顶部（外径、内径、匝数、线宽、焊盘半径、引脚间距等）。
- 运行后打印 `wrote <file>` 便于确认。
