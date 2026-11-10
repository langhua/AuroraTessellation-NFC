/*
 * pixel-min-bringup —— 像素板「台架第 ③ 步」最小固件
 *
 * 做什么（只做三件，不多做）：
 *   ① 上电自检：板载 WS2812B（`LED2`，数据在 `PC6` = SPI1_MOSI）**红 → 绿 → 蓝** 各 150 ms，
 *      然后灭 150 ms；ADC 初始化完再**紫闪一次**
 *      ⇒ 证明「MCU 活着 + SPI 时序对 + 这颗灯能点亮 + ADC 配置跑完」✓
 *      ★ 停在哪个颜色，就说明卡在它之后那一段 ⇒ 一眼定位 ✓
 *      ★ 第一帧**不用白**：白与「卡住残留的白」肉眼分不开 ✗（2026-11-07 的教训）
 *   ② 自检完挂「我活着」的**常亮暗白**；没信号时一直保持
 *      ⇒ **全黑 = 没跑起来**；**暗白常亮 = 一切正常、只等信号** ✓
 *   ③ 采 `PD6`（= A6 = ADC_IN6）：16 次 10-bit 采样累加后 >>2 ⇒ 12-bit（0…4092），
 *      并把读数**显示在灯上**：颜色 = 档位、亮度 = 档内大小
 *      ⇒ 不接任何仪器就能看出「有没有信号 / 随距离怎么变」✓
 *
 * 不做（故意留到下一步）：链上收发（`bus-protocol.md`）、IAP、基线标定。
 *
 * 时钟：**不配 PLL**，就用复位默认（HSI 24 MHz，Flash 0 等待）
 *       ⇒ SPI1 = PCLK2/4 = **6 MHz**（每个 WS2812 位用 8 个 SPI 位拼，1.33 µs/位）
 *       ⇒ ADC 时钟 = PCLK2/2 = **12 MHz**（正好是数据手册 ADC 特性表的标定点）
 */
#include "regs.h"
#include "ws2812.h"

/* ───────────────────────── 延时 ───────────────────────── */
/* `delay_ms()` 的唯一实现在 `regs.h`（SysTick 计数，24 MHz ⇒ 24000/ms ✓）。
 * ★ 2026-11-10 从「`ms × 2000` 次空循环」改过来 —— 那种写法一圈 3 条指令 ≈ 5 周期，
 *   2000 圈只有 0.4 ms ⇒ “毫秒”全体短 2–3 倍 ✗（详见 `regs.h` 里的注释 ✓）。 */

/* ─────────────── RC 节点的「放电脚」`PD5`（与 `PD6` 同一节点）───────────────
 * ★★ 2026-11-10 实测修（用户报「上电白一下、然后常亮红」✓）：
 *   `RC` 节点对地只有 `C1`（隔直 ✗）与 `D3`（反偏 ✗）⇒ **没有直流通路** ✗
 *   ⇒ `D4`（1N5819）的**反向漏电**把 `C1` 慢慢充到接近 5 V ✗
 *   ⇒ ADC 读到 ≥ 2 V ⇒ 灯停在「红档」✗（而“白一下”= 刚上电时 C1 还是 0 ✓）。
 *   设计里早留了这根脚（`v0.1.2` 把 `PD5` 引到同一节点 ✓ 当**开漏放电** ✓）⇒ 固件必须真的用它 ✓：
 *     ① 空闲 / 测前：`PD5` = **开漏输出 0** ⇒ 把节点钳在 0（不漂）✓；
 *     ② 要读数：先放电 2 ms（把 `C1` 放净 ✓）⇒ **释放成模拟输入**（高阻 ✓）
 *        ⇒ 等 3 ms（≈ 3τ，`τ = R1·C1 = 10k × 100n = 1 ms` ✓）⇒ 读到的是包络 ✓。
 *   ⚠ `PD5` 用**开漏**而非推挽：节点可能被 `R1` 抬到 >VDD，开漏只拉低、不会反向注流 ✓。
 */
#define RC_PIN 5

static void rc_low(void)
{
    GPIOD_BCR = (1u << RC_PIN);                 /* 先把输出寄存器置 0 ✓（开漏才会拉低 ✓）*/
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(RC_PIN)))
                | ((uint32_t)GPIO_CFG_OUT_OD_2M << GPIO_CFG_SHIFT(RC_PIN));
}

static void rc_release(void)
{
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(RC_PIN)))
                | ((uint32_t)GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(RC_PIN));
}

/* ──────────────────────── 初始化 ──────────────────────── */
static void adc_init(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPD | RCC_APB2EN_ADC1;
    delay_ms(1);

    /* PD6（A6，包络输入）设成**模拟输入**；节点电压可能高于 VDD，模拟输入不带施密特、不注入电流，最安全 ✓
     * ★ PD5 **不再**当模拟输入 ✗（那样没人放电 ⇒ 节点被 D4 漏电充到 5 V ✗，见上面那段 ✓）*/
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | ((uint32_t)GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(6));
    rc_low();                                   /* 放电脚先钳低 ✓ */

    /* 采样时间取最长（241 周期 @12 MHz ≈ 20 µs）：R1 = 10 kΩ 源阻抗偏高，采样窗给足 */
    ADC1_SAMPTR2 = (ADC1_SAMPTR2 & ~(7u << 18)) | (ADC_SMPT_241CYCLES << 18);

    ADC1_RSQR1 = 0;    /* L[23:20] = 0 ⇒ 规则组只转 1 个通道 */
    ADC1_RSQR3 = 6;    /* 秩 1 = 通道 6（= PD6 = A6） */

    ADC1_CTLR2 |= ADC_CTLR2_ADON;
    delay_ms(1);

    /* 上电校准（照 EVT：先 RSTCAL 等清零，再 CAL 等清零）—— ★ 两个等待都**带上限** */
    ADC1_CTLR2 |= ADC_CTLR2_RSTCAL;
    for (uint32_t t = 0; t < 200000u && (ADC1_CTLR2 & ADC_CTLR2_RSTCAL); t++) {
    }
    ADC1_CTLR2 |= ADC_CTLR2_CAL;
    for (uint32_t t = 0; t < 200000u && (ADC1_CTLR2 & ADC_CTLR2_CAL); t++) {
    }
}

/* ───────────────────────── 采样 ───────────────────────── */
static uint16_t adc_once(void)
{
    ADC1_CTLR2 |= ADC_CTLR2_SWSTART;
    /* ★ 等 EOC 也**带上限**（≈30 ms），不允许死等 */
    for (uint32_t t = 0; t < 200000u; t++) {
        if (ADC1_STATR & ADC_STATR_EOC) {
            break;
        }
    }
    return (uint16_t)(ADC1_RDATAR & 0x03FFu);   /* 10-bit 右对齐 */
}

/* 16 次累加再 >>2：10-bit → 12-bit（0…4092），噪声按 √16 = 4 倍衰减 */
static uint16_t adc_sample12(void)
{
    uint32_t sum = 0;
    for (uint8_t i = 0; i < 16; i++) {
        sum += adc_once();
    }
    return (uint16_t)(sum >> 2);
}

/* 12-bit 码值 → mV（Vref = VDD = 5.00 V；4092 对应 5000 mV）
 * 1251/1024 = 1.2217 ≈ 5000/4092 = 1.2219 ⇒ 误差 < 0.02%，而且不用真的做除法 */
static uint32_t code_to_mv(uint16_t code)
{
    return ((uint32_t)code * 1251u) >> 10;
}

/* ───────────────────────── 读数 → 灯 ───────────────────────── */
typedef struct {
    uint8_t r, g, b;
} rgb_t;

/* 档位色（按 mV 分 5 档）：一档一个颜色，用户不用记亮度绝对值也能判断量级
 * ★ 2026-11-10 阈值整体上移（原来 120/400/1000/2000 ⇒ 现在 800/1500/2500/3500）：
 *   低于 `NOISE_MV`（500 mV）的一律不显示档位 ✓ ⇒ 120–500 那段不再存在 ✓ */
static rgb_t band_color(uint32_t mv)
{
    if (mv < 800u)  { rgb_t c = {  0,   0, 255}; return c; }  /* 蓝：弱 */
    if (mv < 1500u) { rgb_t c = {  0, 200, 255}; return c; }  /* 青：中弱 */
    if (mv < 2500u) { rgb_t c = {  0, 255,   0}; return c; }  /* 绿：中 */
    if (mv < 3500u) { rgb_t c = {255, 120,   0}; return c; }  /* 橙：强 */
    rgb_t c = {255, 0, 0};                                     /* 红：很强（可能过压） */
    return c;
}

/* 亮度 = 40 + 215×(mv/2500) ⇒ 最暗也看得见（16%），2500 mV 以上满亮度 */
static uint8_t level_of(uint32_t mv)
{
    uint32_t lv = 40u + (mv * 215u) / 2500u;
    if (lv > 255u) {
        lv = 255u;
    }
    return (uint8_t)lv;
}

/* 按亮度缩放到 0…255（>>8 近似 /255） */
static uint8_t scale8(uint8_t c, uint8_t lv)
{
    return (uint8_t)(((uint16_t)c * lv) >> 8);
}

/* ───────────────────── 一次「放电→积分→采样」───────────────────── */
static uint16_t rc_read(void)
{
    rc_low();
    delay_ms(2);            /* 把 C1 放净 ✓（PD5 开漏拉低，百 µs 就够，给 2 ms 保险 ✓）*/
    rc_release();           /* 高阻 ⇒ 节点经 R1 向 BR+ 充电 ✓ */
    delay_ms(3);            /* 3τ（τ = R1·C1 = 1 ms）✓ */
    return adc_sample12();
}

/* 「活着但还没读数」的**暖白**：R>G>B ⇒ 一看就是暖白，不会和「蓝档」混 ✓
 * ★ 2026-11-10 改（用户：`(40,40,40)` 盯着看能分出蓝灯/绿灯、容易跟蓝档混 ✓）
 * ★ 亮度与原来相当（均值 ≈ 39/255 ≈ 15%，暗但看得见 ✓）
 * 全黑 = 没跑起来 / 灯这路坏；**暖白常亮 = MCU + 灯 + ADC 三样全对** ✓ */
#define ALIVE_R 52u
#define ALIVE_G 40u
#define ALIVE_B 24u

/* ★★ 2026-11-10 加 **零点标定 ＋ 门限 ＋ 滞回** ✓（用户实测：板子放着不动，读数会慢慢漂 0.1–0.5 V ✗）
 * 漂移的绝对量打不过“相对量”：**上电时先量一次当前电平当零点**（此时应无场 ✓），
 * 之后只有**高出零点 ≥ `NOISE_MV`** 才算信号 ✓ ⇒ 剩下的慢漂/噪声一律落在暖白区 ✓。
 * ⚠ 前提是**上电那一刻没有场**（台架上是这样 ✓）；要重新标定就断电重启 ✓。
 *
 * ★★ 2026-11-10 第二次修（用户报「还是不能稳定暖白、会变」✓）：
 *   实测节点静止在 **0.62–0.73 V**（30 s 内只动 110 mV ✓）⇒ 电路的漂其实已经很小 ✓；
 *   灯会变是因为**读数就在门限附近抖**：原来门限 120 mV，而 120–400 mV 这一段会显示
 *   **暗青色**（`(0,200,255)×亮度`）⇒ 跟暖白一比非常明显 ✗。
 *   ⇒ 两件事：① 门限抬到 **500 mV**（真正的 NFC 信号是伏级 ✓）；
 *            ② 加 **滞回 ＋ 连续 2 次确认**（`500` 进 / `350` 出 / 每次要连中 2 次）✓
 *   ⇒ 单次跳动与慢漂都不会再翻色 ✓
 */
#define NOISE_MV   500u     /* 进档门限：低于它 = 噪声/漂移 ⇒ 暖白 ✓ */
#define RELEASE_MV 350u     /* 退回暖白门限（滞回，比 NOISE_MV 低 150 mV ✓）*/
#define BASE_N      16u     /* 零点取 16 次的平均 ✓ */


/* ───────────────────────── main ───────────────────────── */
int main(void)
{
    ws_init();

    /* ① 上电自检：**红 → 绿 → 蓝**，各 150 ms（顺带验 GRB 色序）
     * ★ 第一帧**故意不用白**（2026-11-07 ✓）：白自检帧与「程序卡住时残留在灯上的白」
     *   在肉眼上分不开 ✗ ⇒ 会被误判成「没在跑」。用红/绿/蓝分段，停在哪一段一目了然 ✓
     *   而且每次上电都从红开始 ⇒ 若看到「红→绿→蓝 又回到红」= 芯片在**反复复位** ✓ */
    ws_rgb(160, 0, 0);
    delay_ms(150);
    ws_rgb(0, 160, 0);
    delay_ms(150);
    ws_rgb(0, 0, 160);
    delay_ms(150);
    ws_rgb(0, 0, 0);
    delay_ms(150);

    /* ② ADC 初始化（内部等待都已带上限，见 adc_init） */
    adc_init();
    (void)adc_once();   /* 使能后的第一次转换丢掉 */

    /* ③ **紫闪一次 = ADC 也初始化完了**（没看到这一闪 ⇒ 卡在 ADC 那一段）*/
    ws_rgb(120, 0, 120);
    delay_ms(120);

    /* ⑤ **零点标定**：连采 `BASE_N` 次取平均 —— 此刻应无场 ✓ ⇒ 把当前电平当 0 ✓
     * ★ 2026-11-10 用户定 ✓：标定期间灯做**一次呼吸**（紫 → 暗 → 紫）
     *   ⇒ 一眼看出"正在标定"，而不是"卡在某个颜色上了" ✗（原来标定时灯一直停在紫上 ✓）
     *   呼吸与采样同步：一次采样一步 ⇒ 16 步 = 一个来回（每步 120 ms，总长约 2 s ✓）
     */
    uint32_t acc = 0;
    for (uint8_t i = 0; i < BASE_N; i++) {
        acc += rc_read();

        uint8_t half = (uint8_t)(BASE_N / 2u);                        /* 8 */
        uint8_t k    = (i <= half) ? i : (uint8_t)(BASE_N - i);       /* 0 → 8 → 1 ✓ */
        uint8_t c    = (uint8_t)((120u * k) / half);                  /* 紫：0 → 120 → 15 ✓ */
        ws_rgb(c, 0, c);
        delay_ms(120);                                                /* 每步 120 ms ⇒ 一个来回 ≈ 2 s ✓ */
    }
    uint16_t base_code = (uint16_t)(acc / BASE_N);

    /* ④ 常亮暖白 = 活着、在循环里等读数 */
    ws_rgb(ALIVE_R, ALIVE_G, ALIVE_B);

    uint8_t hot  = 0u;          /* 0 = 暖白（无信号）／1 = 信号档 ✓ */
    uint8_t n_hi = 0u;          /* 连续超过 NOISE_MV 的次数 ✓ */
    uint8_t n_lo = 0u;          /* 连续低于 RELEASE_MV 的次数 ✓ */

    for (;;) {
        uint16_t code = rc_read();

        /* 只算**高出零点**的部分 ✓（慢漂/噪声都在零点附近 ⇒ 当作 0 ✓）*/
        uint32_t mv = 0;
        if (code > base_code) {
            mv = code_to_mv((uint16_t)(code - base_code));
        }

        /* ★ 滞回 ＋ 连续 2 次确认：单次跳动不翻色 ✓ */
        if (!hot) {
            if (mv >= NOISE_MV) {
                if (++n_hi >= 2u) { hot = 1u; n_lo = 0u; }
            } else {
                n_hi = 0u;
            }
        } else {
            if (mv < RELEASE_MV) {
                if (++n_lo >= 2u) { hot = 0u; n_hi = 0u; }
            } else {
                n_lo = 0u;
            }
        }

        if (!hot) {
            /* ★★ 2026-11-10 第四次修（用户实测：节点从 0.3 V 慢漂到 0.9 V ⇒ 差值越过门限 ⇒ 进档 ✗）
             * **零点慢跟随**：没进档时让 `base_code` 每轮向当前读数靠 `1/16`
             *   ⇒ 时间常数 τ ≈ 16 × 0.5 s = **8 s** ⇒ 分钟级的慢漂被吃掉 ✓
             *   ⇒ 稳态滞后 ≈ 漂速 × τ（实测漂速 ~3 mV/s ⇒ 滞后 ~25 mV ✓ 远小于 500 mV 门限 ✓）
             * ★ 只在 `!hot` 时跟随 ✗ —— 有信号时跟随会把真信号当成零点吃掉 ✗
             * ★ 四舍五入（`±8`），否则 ±15 个码（≈18 mV）的死区会让小漂永远不动 ✗
             */
            int32_t d = (int32_t)code - (int32_t)base_code;
            base_code = (uint16_t)((int32_t)base_code + (d >= 0 ? (d + 8) / 16 : (d - 8) / 16));

            /* 无信号：常亮暖白（不闪、不灭 ⇒ 不会看漏 ✓）*/
            ws_rgb(ALIVE_R, ALIVE_G, ALIVE_B);
        } else {
            rgb_t   c  = band_color(mv);
            uint8_t lv = level_of(mv);
            ws_rgb(scale8(c.r, lv), scale8(c.g, lv), scale8(c.b, lv));
        }

        delay_ms(500);   /* ≈2 Hz：包络本身只有 160 Hz 带宽，看趋势够了 */
    }
}
