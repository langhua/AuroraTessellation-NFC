# -*- coding: utf-8 -*-
r"""网标签（net label）规则 —— **全仓唯一实现** ✓

★ 规则（用户 2026-09-26 定 ✓；2026-09-29 用户要求落到判定器 ✓）：
  **同名网标签 = 同一张网** ✓ —— 这是**抽象连接** ✓ ⇒ **只适用原理图** ✓
  （面包板 / PCB 要物理连接 ✗ —— 见 `fritzing-parts-langhua/docs/breadboard-routing-rules.md` ✓）。

★ 怎么认（实测取证 ✓，`hardware/pixel/pixel-schematic-v29_netlabel.fzz` ✓）：
  · 网标签是**元件实例** ✓，其 `moduleIdRef` 里带 `NetLabel` ✓
    —— 核心库 = `NetLabelModuleID` ✓；本库 = `NetLabel-Pad` ✓；
  · **实例标题（`<title>`）= 网名** ✓（该草图里 4 个实例标题为 `RC` / `RC` / `GND` / `GND` ✓，
    两个 `RC` 与两个 `GND` 各自互为同一张网 ✓）。

★ 消费方式（两个判定器都调这两行 ✓，别各写一份 ✗）：
    name = sch_net.net_name(module_id_ref, instance_title)      # 不是网标签 ⇒ None ✓
    # 然后：把**同名**的所有标签脚 union 到一起 ✓

★ **几何**（本体框 / 引脚 / 文字位置 / 朝向）也**只有这一份** ✓ —— 见下面「本体几何」一节 ✓，
  常数**全部实测**并注明出处 ✓；生成器、渲染器、判定器都调它 ✓（各写一套就是等着两边对不上 ✗）。
"""
import math
import re

_MOD = re.compile(r'moduleIdRef\s*=\s*"([^"]*)"')
_TTL = re.compile(r"<title>(.*?)</title>", re.S)
_MI = re.compile(r'modelIndex\s*=\s*"([^"]*)"')

# ══════════════════════════════════════════════════════════════════════════════
# 本体几何 —— **实测标定** ✓（2026-09-29 ✓）／**唯一实现** ✓
#
# 证据一：用户导出的 `hardware/pixel/_work/v34_图示.svg`（**Fritzing 自己画的** ✓）
#   · 4 个标签各只有一段 `<text id="label">` ✓ ⇒ **原理图里网标签 = 纯文字，没有方框** ✓
#     （我原来画的那个大矩形框是**我发明的** ✗ ⇒ 当然和 Fritzing 对不上 ✗）。
#   · 文字属性：`font-family="Droid Sans"` ✓、`font-size="4.8"`（导出单位 ✓ = sketch **6.0** ✓）、
#     `fill="#000000"` ✓、`x="0.48" y="5.28"`（= sketch **0.6 / 6.6** ✓，相对实例 `geometry` ✓）、
#     **没有 `text-anchor`** ✓ ⇒ x = 文字**左缘** ✓。
# 证据二：`pixel-schematic-v29_netlabel.fzz`（**Fritzing 自己写的** ✓）里两个**旋转过**的标签：
#   `RC`  R=(−1,0,0,−1)  m31/m32=(12.5219, 9) ⇒ 反解枢轴 (6.26095, 4.5) ⇒ 板宽 **11.3219**
#   `GND` R=(−1,0,0,−1)  m31/m32=(18.2055, 9) ⇒ 反解枢轴 (9.10275, 4.5) ⇒ 板宽 **17.0055**
#   ⇒ 两个名字两个板宽 ✓，都满足 **枢轴 = (0.6 + W/2, 4.5)** ✓。
# 证据三：`v34_图示.svg` 里那两个旋转标签**画出来的**文字位置 ✓（4 个方程解 1 个未知数 W ✓）
#   ⇒ W = 17.0048 / 17.0000（名字都是 `GND` ✓）✓ 与证据二的 17.0055 一致到 **3‱** ✓✓。
#   ⇒ **画法 = 绕 `(0.6 + W/2, 4.5)` 旋转** ✓：`view(p) = 几何 + C + R·(p − C)` ✓。
#
# ★★ 两条**反直觉但已证**的结论 ✓：
#   ① 文件里 `transform` 的 `m31/m32` **Fritzing 画图时不用** ✗ —— 证据：v34 的 `GND#1`
#      `m31=m32=0` ✓ 而 Fritzing 照样把它绕枢轴转 ✗；`GND#2` 的 `(10.7609,−1.76096)` 又对不上
#      画出来的位置 ✗ ⇒ 两个样本**只有**「忽略 m31/m32 + 绕枢轴」能同时成立 ✓（各差 < 1e-4 ✓）。
#   ② 所以**写文件时把 `m31/m32` 写成 `(I−R)·C`** ✓（Fritzing 自己就这么写 ✓，见证据二 ✓）
#      ⇒ "忽略它"与"尊重它"**两种读法都落在同一处** ✓（不给人埋坑 ✓）。
#
# ⚠ 板宽 W（已从“两点拟合”升级为**真字宽** ✓ 2026-09-29 当日晚 ✓）：
#   Fritzing **不自带字体** ✓（搜遍安装目录：无 ttf/otf/woff/rcc ✓）⇒ 它请求 `Droid Sans`、
#   由 **Qt6 从系统字体回退** ✓ ⇒ 回退到哪个字体 **用实测反解验证** ✓：
#     · 拿系统里**全部 345 个字体**逐一拟合 ✓：**Noto Sans → rms 0.034mm** ✓✓
#       （Segoe UI Bold 0.097 ✗ ｜ Calibri 0.134 ✗ ｜ DejaVu 0.154 ✗）；
#     ⇒ 字宽表 = `sch_glyphs.py`（**纯数据** ✓，由 `_scratch/gen_sch_glyphs.py` 导出 ✓）。
#   ★★ **W 与框是同一个量** ✓（用户第二份 `netlabels.fzz` 实测后确定 ✓）：
#     框盒（相对**文字锚点** ✓）在局部 x 上从 **0.15** 到 **L+0.15** ✓ ⇒ 枢轴 = 盒心 = `0.15 + L/2` ✓
#     ⇒ 与我的 `pivot() = 0.6 + W/2` 对照 ⇒ **`W = L − 0.9`** ✓。
#     验：`RC` L=12.221 ⇒ W=**11.321** ✓（独立量到 11.3219 ✓）；`GND` L=17.916 ⇒ W=**17.016** ✓
#     （独立量到 17.0055 ✓）⇒ 两条互证 ✓✓。
LABEL_FS = 6.0            # 字号（sketch ✓）= 导出 4.8 × 1.25 ✓
LABEL_TEXT_X = 0.6        # 文字**左缘**（以实例 `geometry` 为原点 ✓）= 导出 0.48 ✓
LABEL_BASELINE_Y = 6.6    # 文字**基线** = 导出 5.28 ✓
LABEL_PLATE_H = 4.2       # 本体板高 = 0.7em ✓（由枢轴 y = 4.5 反推 ✓ = 2×(4.5 − 2.4) ✓）
LABEL_PIN_DY = 4.5        # 引脚在**半高线**上 ✓（枢轴 y ✓）—— 但**横坐标不在平端** ✗，见下 ✗✗

# ══════════════════════════════════════════════════════════════════════════════
# ★★★ **脚到底在哪** ✓✗ —— 2026-09-29 修正 ✗✗（我错了**整整一个旗标长 ≈ 3.4mm** ✗）
#
# 证据 = Fritzing **自己生成标签 SVG 的源码** ✓（`src/items/symbolpaletteitem.cpp`
#   `NetLabel::makeSvg` ✓；本机 exe 里跑的就是这份逻辑 ✓）：
#     double totalHeight = 300/divisor;  double arrowWidth = totalHeight / 2;   // 100 / 50
#     double strokeWidth = 10/divisor;   double halfStrokeWidth = strokeWidth / 2;  // 3.333 / 1.667
#     if (goLeft)  pin = pin.arg(0).arg(0).arg(arrowWidth).arg(totalHeight);
#     else         pin = pin.arg(totalWidth - arrowWidth - 0.1).arg(0).arg(arrowWidth).arg(totalHeight);
#     // 旗标 polygon：goLeft ⇒ 尖点在**左** (halfStrokeWidth)；否则尖点在**右** (totalWidth − halfStrokeWidth)
#   ⇒ 脚的局部 x = **pin rect 的外缘** ✓（靠箭头那侧 ✓）：
#       · `direction="right"`（默认 ✓ = goLeft=false）：x = (W − 0.1) 单位
#         = 旗标右缘 + (1.667 − 0.1) × 0.09 = **+0.141 sketch** ✓
#       · `direction="left"`（goLeft=true）        ：x = 0 单位
#         = 旗标左缘 − 1.667 × 0.09 = **−0.150 sketch** ✓
#     （1 SVG 单位 = 1/1000 in ✓；1 sketch 单位 = 1/90 in ✓ ⇒ ×0.09 ✓）
#
# ★ 用**手画的线**验过 ✓✓（Fritzing 存的是**吸附后**的真脚位 ✓ ⇒ 手改版就是权威尺子 ✓）：
#     `v30_byHand` `RC`(180°)   旧模型差 **3.535 mm** ✗ ｜ 新模型差 **0.004 mm** ✓✓
#     `v31_rcgnd_byHand` `RC`(90°) 旧 3.535 ✗ ｜ 新 **0.004** ✓✓
#     `v31_rcgnd_byHand` `RC`(0°)  旧 3.535 ✗ ｜ 新 **0.258** ✓
#   ★★ 后果（必须记住 ✗）：按旧模型生成的 `pixel-schematic-v30.fzz` 里，**四个标签在 Fritzing 里
#     全部是断的** ✗✗（线停在平端、脚在尖端 ✓ = “看着接上、其实没接” ✗）——
#     而当时的自检（②）**量的是我自己的模型** ✗ ⇒ 它当然报 0 ✓✓ = “**自证**”那条教训又吃了一次 ✗。
#     现在 ② 的真尺子是**手画数据 + 源码** ✓，不再是自己编的坐标 ✓。
LABEL_PIN_GAP_R = (10.0 / 3 / 2 - 0.1) * 0.09     # = 0.141 ✓（指向右 ⇒ 脚在右 ✓）
LABEL_PIN_GAP_L = (10.0 / 3 / 2) * 0.09           # = 0.150 ✓（指向左 ⇒ 脚在左 ✓）

# ★ 四个朝向（**SVG 口径** ✓：`rotate(θ)` ⇒ `(a,b,c,d) = (cosθ, sinθ, −sinθ, cosθ)` ✓）
#   —— 四个都在 Fritzing 自己的文件里出现过 ✓（identity / ±90° / 180° ✓）；
#   上面那套画法对**任意** `R` 都成立 ✓（枢轴 = 板心 ✓ 与 `R` 无关 ✓）。
MATRIX = {
    0: (1.0, 0.0, 0.0, 1.0),
    90: (0.0, 1.0, -1.0, 0.0),
    180: (-1.0, 0.0, 0.0, -1.0),
    270: (0.0, -1.0, 1.0, 0.0),
}
IDENT = MATRIX[0]


def flag_len(text):
    """外框（旗标 ✓）的**长**（sketch ✓）—— `L = FLAG_A × Σ(步进/em) + FLAG_B` ✓

    常数由**用户第二份 `netlabels.fzz`**（★ 零标定量法 ✓：框顶点↔文字锚点，全在导出内部 ✓）
    的 **9 个名字**最小二乘拟合 ✓ ⇒ rms **0.064mm** ✓（各名字最大差 0.16mm ✓）。
    """
    import sch_glyphs as _G
    return _G.A_EM * _G.adv_sum(text) + _G.B_PAD


def plate_w(text):
    """本体板宽 W（sketch ✓）—— ★ 与框是**同一个量** ✓：`W = flag_len − 0.9` ✓

    （框盒从局部 x=0.15 到 L+0.15 ✓ ⇒ 盒心 = 0.15 + L/2 ✓ ⇒ 与 `pivot()` 对照得 W = L − 0.9 ✓；
      拿两个独立量到的枢轴验过 ✓：`RC` 11.321 ↔ 11.3219 ✓、`GND` 17.016 ↔ 17.0055 ✓。）
    """
    return flag_len(text) - 0.9


def pivot(text):
    """旋转枢轴（相对实例 `geometry` ✓）= **板心** ✓ = `(0.6 + W/2, 4.5)` ✓（实测 ✓）"""
    return (LABEL_TEXT_X + plate_w(text) / 2.0, LABEL_PIN_DY)


def pin_local(text, go_left=False):
    """引脚（相对实例 `geometry` ✓）—— 在**半高线**上、**箭头尖端那一侧** ✓

    ★ 2026-09-29 修正 ✗✗：旧模型写“平端 `(0, 4.5)`”✗ —— 那是**错的** ✗，
      差了整整一个旗标长（≈ 3.4mm ✗）⇒ 照它生成的线**碰不到脚** ✗。
      现行口径 + 证据见上面那段 ✗✗（源码 `NetLabel::makeSvg` ✓ + 手画数据 ✓）。
    """
    L = flag_len(text)
    x0 = LABEL_TEXT_X + FLAG_X0                   # 旗标左缘 ✓（= 0.15 ✓）
    x1 = x0 + L                                   # 旗标右缘 ✓
    return ((x0 - LABEL_PIN_GAP_L) if go_left else (x1 + LABEL_PIN_GAP_R),
            LABEL_PIN_DY)


def norm_m(m):
    """取 2×2 部分 ✓（`(m11, m12, m21, m22)` ✓）；`None` ⇒ 单位阵 ✓"""
    if m is None:
        return IDENT
    return (float(m[0]), float(m[1]), float(m[2]), float(m[3]))


def mv(m, p):
    """2×2 作用（**SVG 口径** ✓：`a=m11,b=m12,c=m21,d=m22` ⇒ `(a·x + c·y, b·x + d·y)` ✓）"""
    m = norm_m(m)
    return (m[0] * p[0] + m[2] * p[1], m[1] * p[0] + m[3] * p[1])


def view(geom, text, m, p):
    """局部点 → 视图点 ✓：**`几何 + C + R·(p − C)`** ✓（绕板心旋转 ✓，**实测** ✓）"""
    c = pivot(text)
    q = mv(m, (p[0] - c[0], p[1] - c[1]))
    return (geom[0] + c[0] + q[0], geom[1] + c[1] + q[1])


def label_geom(pin_pt, text, m, go_left=False):
    """**反解** ✓：要让**画出来的脚**落在 `pin_pt` 上，实例 `geometry` 该写多少 ✓

    （生成器用它 ✓ ⇒ "脚在线端上"是**画出来的**位置 ✓，不是我以为的位置 ✓。）
    """
    c = pivot(text)
    _p = pin_local(text, go_left)
    q = mv(m, (_p[0] - c[0], _p[1] - c[1]))
    return (pin_pt[0] - c[0] - q[0], pin_pt[1] - c[1] - q[1])


def label_pin(geom, text, m=IDENT, go_left=False):
    """**画出来的脚**（视图坐标 ✓）—— 判定器拿它跟导线端点对账 ✓"""
    return view(geom, text, m, pin_local(text, go_left))


def label_text_anchor(geom, text, m=IDENT):
    """**画出来的文字基线左端**（视图坐标 ✓）—— 渲染器画它、核对器量它 ✓"""
    return view(geom, text, m, (LABEL_TEXT_X, LABEL_BASELINE_Y))


def rot_deg(m):
    """变换里的旋转角（度 ✓）—— 给渲染器 `rotate(θ cx cy)` 用 ✓"""
    m = norm_m(m)
    return math.degrees(math.atan2(m[1], m[0]))


def label_box(geom, text, m=IDENT):
    """**看见的那块**（sketch ✓，**轴对齐包围盒** ✓）= **外框（旗标 ✓）的 5 个顶点**的包围盒 ✓

    ★ 「标签是一个元件」✓（用户 2026-09-29 定 ✓）⇒ 判定器拿它当**实体**判穿体/贴脚 ✓；
      与渲染器**同一份** ✓（不许各写一套 ✗）。

    ✗✗ **原来这里返回的是「板」（`[0.6,0.6+W] × [2.4,6.6]` ✗）⇒ 比旗标小一圈** ✗ ——
      板 = **文字墨迹框**（4.2 高 ✓ 就是字高 ✓）、而**看得见的旗标**是 **8.7 宽 ✓**（= 板的 2 倍）
      ⇒ 拿板去判碰撞 ⇒ **有一根线从旗标身上穿过去，判据却说“违例 0”** ✗✗
      （2026-09-29 实测 ✓：`_work/v30.fzz` 的 `RC` 标签上，**5V 的红竖线正穿旗标** ✗，
        而生成器打印的是“违例 0 ✓” ✗ —— 我差点把它当成干净的版本交出去 ✗）。
    ★ 教训：**判碰撞要用“看得见的那块”** ✓ —— 用户看的是旗标 ✓，不是我看的那个隐形的板 ✗
      （与 AGENTS「以用户观察为准」✓、「判据要跟画出来的东西同一个」✓ 同一条）。
    ★ 板的用途只剩一个：**旋转枢轴** ✓（= 板心 ✓，实测 ✓）—— 那是**变换**的事 ✓，
      与「实体在哪」是**两个问题** ✓（所以 `pivot()` 照旧 ✓、这里换成旗标 ✓）。

    ★ 实现上**直接调 `label_flag`** ✓（不重算一遍顶点 ✗ ⇒ 一份几何 ✓；旗标一改这里自动跟上 ✓）。
    """
    v = label_flag(geom, text, m)
    xs = [q[0] for q in v]
    ys = [q[1] for q in v]
    return (min(xs), min(ys), max(xs), max(ys))


def canonical_d(text, m):
    """Fritzing 自己写的 `m31/m32` ✓ = **`(I−R)·C`** ✓（证据二那两个样本都是 ✓）

    ⇒ 写文件时用它 ✓：Fritzing 忽略它 ✓，而"尊重它"的读者算出来**也是同一个位置** ✓。
    """
    c = pivot(text)
    q = mv(m, c)
    return (c[0] - q[0], c[1] - q[1])

# ══════════════════════════════════════════════════════════════════════════════
# 本体**外框（箭头形旗标）** ✓ —— 我漏过它 ✗（Fritzing 给一个标签写**两组**：`mi+"0"` 装框 ✓、
#   `mi+"1"` 装文字 ✓；我上次只查了后者 ✗ —— 用户 2026-09-29 指出 ✓）。
#
# ★★ 口径（**零标定**量出来的 ✓✓ —— 用户第二份 `netlabels.fzz` ✓，17 个标签、三种旋转 ✓）：
#   把框的顶点换算到「**相对文字锚点 ℓ**」的局部坐标（用**导出自己**的旋转矩阵 ✓）：
#     `框盒 = (−0.45, −6.45) → (L−0.45, +2.25)`（sketch ✓）= 宽 **8.700** × 长 **L** ✓
#     - **0° / 90° / −90° 三组顶点完全一样** ✓✓ ⇒ 框是 **锚在文字上** ✓、**与旋转无关** ✓
#       （我原来锚在“脚”上 ✗ ⇒ 差 2.7mm ✗，且看着像“只对 −90° 对”✗）。
#     - 尖点在 `(L−0.45, −2.10)` ✓、尖头长 **4.350** ✓
#       （= 尖点 x − 旗身右缘 x ✓；⚠ 我一度写成 5.60 ✗ —— 那是拿**盒长**去减出来的 ✗，
#        实测两批都是 **3.48 导出 = 4.35 sketch** ✓：`DCIN` 129.668−126.188 ✓、`RC` 9.417−5.938 ✓）。
# ══════════════════════════════════════════════════════════════════════════════
FLAG_W = 8.700            # 框宽（定值 ✓）
FLAG_TIP = 4.350          # 尖头长（定值 ✓ 见上）
FLAG_X0 = -0.45           # 框相对**文字锚点**的左缘 ✓
FLAG_Y0 = -6.45           # 相对文字锚点的上缘 ✓（⇒ 下缘 = FLAG_Y0 + FLAG_W +2.25 ✓）


def label_flag(geom, text, m=IDENT):
    """外框（旗标 ✓）的 5 个顶点（**视图坐标** ✓）—— 顺序 = 绕一圈 ✓

    `view(p) = 几何 + C + R·(p − C)` ✓（与文字用**同一份**映射 ✓ ⇒ 朝向自动一致 ✓）。
    """
    L = flag_len(text)
    lx, ly = LABEL_TEXT_X, LABEL_BASELINE_Y                 # ℓ = 文字基线左端 ✓
    x0, y0 = lx + FLAG_X0, ly + FLAG_Y0                     # 框盒左上（sketch ✓）
    x1, y1 = x0 + L, y0 + FLAG_W
    pts = [(x0, y0), (x0, y1), (x1 - FLAG_TIP, y1),
           (x1, (y0 + y1) / 2.0), (x1 - FLAG_TIP, y0)]
    return [view(geom, text, m, p) for p in pts]

def is_label_module(module_id):
    """这个 `moduleIdRef` 是不是**网标签**元件 ✓"""
    _m = (module_id or "").lower()
    return "netlabel" in _m or "net label" in _m


# ══════════════════════════════════════════════════════════════════════════════
# **接地符号**（core `GroundModuleID` ✓）—— 它凭什么把网连起来 ✓（2026-09-29 ✓ 用户问 ✓）
#
# ★★ 证据**在 Fritzing 源码 / 它自己的件定义里** ✓（不是猜的 ✗）：
#   · 件定义（嵌在 `…\Fritzing\Fritzing.exe` 里的 `resources/parts/core/ground.fzp` ✓，
#     与草图里那条 `path=":/resources/parts/core/ground.fzp"` **对得上** ✓）：
#       <connector type="male" id="connector0" name="GND"> … <erc etype="ground">
#       <buses><bus id="groundbus"><nodeMember connectorId="connector0"/></bus></buses>
#   · 取等电位（`src/items/symbolpaletteitem.cpp::busConnectorItems` ✓）：
#       if (m_isNetLabel)                    mitems = LocalNetLabels[ key(getLabel()) ]
#       else if (bus->id() == "groundbus")   mitems = **LocalGrounds**      ← ★ 就是它
#       else                                 mitems = LocalVoltages[ voltage ]
#   · 谁算 `LocalGrounds`（`src/connectors/connectoritem.cpp::isGrounded` ✓）：
#       return name == "gnd" || name == "vss" || name == "ground";   // 大小写不敏感 ✓
#
# ⇒ ★★ **规则（反直觉 ✓，可这就是 Fritzing 干的 ✓）**：
#     接地符号**不是**“两个符号互相连” ✗ —— 它是把**全图所有「脚名 ∈ {GND,VSS,GROUND}」的
#     连接器**一把拉成同一张网 ✓（`LocalGrounds` ✓）。
#     ⇒ `U1` 的 **`VSS`** 脚 ✓、`LED2` 的 **`GND`** 脚 ✓ 都**自动**与接地符号同网 ✓ ——
#       哪怕图上**一根线都没连到它们** ✓（用户实测 ✓：把 GND 标签换成接地符号，照样一张 GND 网 ✓）。
#   ★ 反过来：**图里没有接地符号 ⇒ 什么也不合并** ✗ —— 那些脚只是“名字叫 GND”而已 ✓，
#     得有人（符号 ✓ / 网标签 ✓ / 导线 ✓）把它们拉起来才算同网 ✓。
#   ★ 判据**只在 `sch_net.py` 一份** ✓（`check_netlist.py` / `render_sch.py` 都调它 ✓，
#     各写一套就是等着两边对不上 ✗）。
GROUND_SYMBOL_MODULES = ("GroundModuleID",)     # ★ 只认**原理图接地符号** ✓
#   ✗ 别写成 `"ground" in moduleId` ✗ —— `GroundPlaneModuleID`（**铜箔地平面** ✓）也含这个词 ✗，
#     它不是原理图符号、也没有 `groundbus` ✗ ⇒ 混进来就是**假合并** ✗（真做 PCB 时立刻踩 ✗）。
GROUND_PIN_NAMES = ("gnd", "vss", "ground")     # 实测口径 ✓（大小写不敏感 ✓）


def is_ground_symbol(module_id):
    """这个 `moduleIdRef` 是不是**接地符号** ✓（core `GroundModuleID` ✓）"""
    return (module_id or "") in GROUND_SYMBOL_MODULES


# ★★ 接地符号的**脚** = 它 `<geometry>` 原点 **+ (9.001, 0.596)** sketch ✓（实测反推 ✓）
#   ★ 它也在**自己的 svg 里**（`schematic/ground.svg` 的 `connector0pin` ✓）✗ —— `.fzz` 不带那份
#     SVG ✗ ⇒ 拿不到就**反推** ✓（和网标签同一招 ✓：用**用户手画**的线端 ✓ = Fritzing 吸附后的真脚位 ✓）。
#   两个样本**完全一致** ✓✓：
#     `Ground1` 原点 (206.999, 26.4044) ← 线端 (216.000, 27.000) ⇒ 偏 (+9.001, +0.596)
#     `Ground2` 原点 (152.999, 152.404) ← 线端 (162.000, 153.000) ⇒ 偏 (+9.001, +0.596)
#   （物理上是“原点在图形左缘、脚在顶上中间” ✓ —— 9.001 sketch = 2.54mm = 0.1in ✓。）
GROUND_PIN_DX = 9.001
GROUND_PIN_DY = 0.596


def ground_pin(geom):
    """接地符号**画出来的脚**（视图坐标 ✓）—— 原点 + (9.001, 0.596) ✓（见上 ✓）"""
    return (geom[0] + GROUND_PIN_DX, geom[1] + GROUND_PIN_DY)


def grounded_connectors(inst_module, module_conn_names, inst_conn_ids=None):
    """按 Fritzing 规则**算作接地**的那些连接器 ✓ ⇒ `[(modelIndex, connectorId), …]`

    · `inst_module`：`{modelIndex: moduleIdRef}` ✓
    · `module_conn_names`：`{moduleIdRef: {connectorId: 脚名}}` ✓ —— **从 `.fzz` 自带的那份
      `.fzp` 里读** ✓（草图里只写 `connectorId="connector20"` ✗，**看不到脚名** ✗）
    · `inst_conn_ids`：`{modelIndex: [connectorId, …]}` ✓（**可省** ✓）
    ★★ **接地符号自己的脚也算接地** ✓ —— 而且它**不能靠 `module_conn_names` 拿到** ✗：
      `GroundModuleID` 是**嵌在 app 里的 core 件** ✗（`path=":/resources/parts/core/ground.fzp"` ✓）
      ⇒ **`.fzz` 里根本没有它的 `.fzp`** ✗ ⇒ 少了这一条，两个接地符号各自只拉动自己那半 ✗
      ⇒ `GND` 照样被拆成 2 段 ✗（2026-09-29 实测撞上 ✓：那时我还以为规则没生效 ✗）。
      依据：它的连接器名就是 **`GND`** ✓（core 件定义原话 ✓）⇒ 它自己也在 `LocalGrounds` 里 ✓。
    ★ **图里没有接地符号 ⇒ 返回空** ✗（没人把它们拉成一张网 ✓）。
    """
    sym = sorted(mi for mi, m in inst_module.items() if is_ground_symbol(m))
    if not sym:
        return []
    out = []
    for mi in sym:                                  # ★ 符号自己的脚 ✓（见上 ✗✗）
        for cid in ((inst_conn_ids or {}).get(mi) or ["connector0"]):
            out.append((str(mi), cid))
    for mi, mod in inst_module.items():
        if is_ground_symbol(mod):
            continue
        for cid, nm in (module_conn_names.get(mod) or {}).items():
            if (nm or "").strip().lower() in GROUND_PIN_NAMES:
                out.append((str(mi), cid))
    return sorted(set(out))


def ground_links(inst_module, module_conn_names, inst_conn_ids=None):
    """接地符号带来的**额外连通** ✓ ⇒ `[((mi, cid), (mi, cid)), …]`（喂并查集 ✓）

    （Fritzing 把它们并成一张网 ✓ ⇒ 这里给出“把它们并起来”的那些边 ✓；没有符号 ⇒ 空 ✓。）
    """
    g = grounded_connectors(inst_module, module_conn_names, inst_conn_ids)
    return [(g[0], g[i]) for i in range(1, len(g))]



def net_name(module_id, title, label=None):
    """网标签 ⇒ **网名** ✓；不是网标签 ⇒ `None` ✓

    ★ 名字以实例的 **`<property name="label">`** 为准 ✓，没写才退回 `<title>` ✓。
      依据（用户造件实测 ✓ 2026-09-29）：`_work/netlabels.fzz` 里 `<title>` 是 `RC1`/`MCLR1`…
      而 **Fritzing 画出来的是 `RC`/`MCLR`** ✓ = 那个属性的值 ✓ ⇒ 属性才是“看得见的名字” ✓
      （与 AGENTS 里“以看得见的为准 ✓、不以源码里的借名为准 ✗”同一条 ✓）。
    """
    if not is_label_module(module_id):
        return None
    _t = ((label if (label or "").strip() else title) or "").strip()
    return _t or None


def label_pins(text):
    """从**草图 XML 文本**里取 `{网名: [(modelIndex, 实例标题, 脚 id), …]}` ✓（只含网标签实例 ✓）

    ★ 给“手上只有文本”的消费者用 ✓；已经有实例模型的（如 `check_netlist.py` ✓）
      直接调 `net_name()` 即可 ✓ —— **判据仍是这一份** ✓。
    ★ 要带 **modelIndex** 回来 ✓：**同名标签是两个不同实例** ✓ ⇒ 只靠标题去重会把它们并成一个 ✗
      （实测 2026-09-29 ✓：两个 `GND` / 两个 `RC` 各只剩 1 个 ⇒ 第二个标签的脚**并不进网** ✗）。
    """
    out = {}
    for blk in re.findall(r"<instance[^>]*>.*?</instance>", text, re.S):
        m = _MOD.search(blk)
        t = _TTL.search(blk)
        if not m or not t:
            continue
        _lb = re.search(r'<property\s+name="label"\s+value="([^"]*)"', blk)
        _n = net_name(m.group(1), t.group(1), _lb.group(1) if _lb else None)
        if not _n:
            continue
        # ★ 草图里写的是 **`connectorId="connector0"`** ✓（实测 2026-09-29 ✓：
        #   `pixel-schematic-v29_netlabel.fzz` 的标签块 = `<connector connectorId="connector0" …>` ✓
        #   —— **没有** 独立的 `id` 属性 ✗；我第一版按 `\bid=` 抓 ⇒ 一个也抓不到 ✗）。
        #   ★ 同一个标签**每个视图各有一份 `<connectors>`** ✓（breadboard/pcb/schematic ✓，
        #   id 都是 `connector0` ✓）⇒ **只对本实例去重** ✓（按网名去重会把第二个实例吃掉 ✗）。
        _t = t.group(1).strip()
        _mi = _MI.search(blk)
        _seen = set()
        for _cid in re.findall(r"<connector\b[^>]*\bconnectorId\s*=\s*\"([^\"]*)\"", blk):
            if _cid in _seen:
                continue
            _seen.add(_cid)
            out.setdefault(_n, []).append((_mi.group(1) if _mi else "?", _t, _cid))
    return out
