/*
 * pixel-min-bringup —— 像素板「台架第 ③ 步」最小固件
 *
 * 做什么（只做三件，不多做）：
 *   ① 上电自检：板载 WS2812B-1010（`LED2`，数据在 `PC6` = SPI1_MOSI）白光闪 3 次
 *      ⇒ 证明「MCU 活着 + 5 V 在 + 这颗灯能点亮」✓
 *   ② 采 `PD6`（= A6 = ADC_IN6）：16 次 10-bit 采样累加后 >>2 ⇒ 12-bit（0…4092）
 *   ③ 把读数**显示在灯上**：颜色 = 档位、亮度 = 档内大小
 *      ⇒ 不接任何仪器就能看出「有没有信号 / 随距离怎么变」✓
 *
 * 不做（故意留到下一步）：链上收发（`bus-protocol.md`）、IAP、基线标定。
 *
 * 时钟：**不配 PLL**，就用复位默认（HSI 24 MHz，Flash 0 等待）
 *       ⇒ SPI1 = PCLK2/4 = **6 MHz**（每个 WS2812 位用 8 个 SPI 位拼，1.33 µs/位）
 *       ⇒ ADC 时钟 = PCLK2/2 = **12 MHz**（正好是数据手册 ADC 特性表的标定点）
 */
#include "regs.h"

/* ───────────────────────── 粗延时 ───────────────────────── */
/* 24 MHz 下空循环约 12 个周期 ⇒ 1 ms ≈ 2000 次。只用于「几百毫秒」级，
 * 精度 ±30% 不影响任何判据（WS2812 复位要求 >280 µs，这里给 1 ms）。 */
#define LOOPS_PER_MS 2000u
static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * LOOPS_PER_MS;
    while (n--) {
        __asm__ volatile("nop");
    }
}

/* ───────────────────────── WS2812B-1010 ───────────────────────── */
/* 一个 WS2812 位用 8 个 SPI 位拼（SPI 6 MHz ⇒ 8 位 = 1.33 µs）：
 *   '0' → 11000000（高 0.33 µs / 低 1.00 µs）
 *   '1' → 11111000（高 0.83 µs / 低 0.50 µs）
 * 都在 WS2812B 的容差内（T0H 0.4±0.15、T1H 0.85±0.15、周期 1.25±0.6 µs）。 */
#define WS_CODE_0 0xC0u
#define WS_CODE_1 0xF8u

static void ws_send_byte(uint8_t b)
{
    for (int8_t i = 7; i >= 0; i--) {
        SPI1_DATAR = (b & (1u << i)) ? WS_CODE_1 : WS_CODE_0;
        while ((SPI1_STATR & SPI_STATR_TXE) == 0) {
            /* 等发送寄存器空 */
        }
    }
}

/* 锁存：等移位完成，再拉低 >280 µs（这期间 MOSI 一直是低 ⇒ 就是复位码） */
static void ws_latch(void)
{
    while (SPI1_STATR & SPI_STATR_BSY) {
    }
    delay_ms(1);
}

/* 一颗灯：WS2812B 的时序是 G→R→B */
static void ws_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    ws_send_byte(g);
    ws_send_byte(r);
    ws_send_byte(b);
    ws_latch();
}

/* ───────────────────────── 初始化 ───────────────────────── */
static void spi_init(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPC | RCC_APB2EN_SPI1;

    /* PC6 = SPI1_MOSI（数据手册表 2-2：PC6 默认复用就是 MOSI，不用 AFIO 重映射） */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | (GPIO_CFG_AF_PP_50M << GPIO_CFG_SHIFT(6));

    SPI1_CTLR1 = 0;
    SPI1_CTLR1 = SPI_CTLR1_MSTR                    /* 主机 */
               | SPI_CTLR1_SSM | SPI_CTLR1_SSI     /* 软件 NSS，内部拉高（不然会进模式错） */
               | SPI_CTLR1_BR_DIV4;                /* PCLK2/4 = 6 MHz；CPOL=0 CPHA=0、8 位、MSB 先出 */
    SPI1_CTLR1 |= SPI_CTLR1_SPE;
}

static void adc_init(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPD | RCC_APB2EN_ADC1;
    delay_ms(1);

    /* PD6（A6，包络输入）与 PD5（A5，与 PD6 同节点）都设成**模拟输入**：
     * 节点电压可能高于 VDD，模拟输入不带施密特、不注入电流，最安全。 */
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | (GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(6));
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(5)))
                | (GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(5));

    /* 采样时间取最长（241 周期 @12 MHz ≈ 20 µs）：R1 = 10 kΩ 源阻抗偏高，采样窗给足 */
    ADC1_SAMPTR2 = (ADC1_SAMPTR2 & ~(7u << 18)) | (ADC_SMPT_241CYCLES << 18);

    ADC1_RSQR1 = 0;    /* L[23:20] = 0 ⇒ 规则组只转 1 个通道 */
    ADC1_RSQR3 = 6;    /* 秩 1 = 通道 6（= PD6 = A6） */

    ADC1_CTLR2 |= ADC_CTLR2_ADON;
    delay_ms(1);

    /* 上电校准（照 EVT：先 RSTCAL 等清零，再 CAL 等清零） */
    ADC1_CTLR2 |= ADC_CTLR2_RSTCAL;
    while (ADC1_CTLR2 & ADC_CTLR2_RSTCAL) {
    }
    ADC1_CTLR2 |= ADC_CTLR2_CAL;
    while (ADC1_CTLR2 & ADC_CTLR2_CAL) {
    }
}

/* ───────────────────────── 采样 ───────────────────────── */
static uint16_t adc_once(void)
{
    ADC1_CTLR2 |= ADC_CTLR2_SWSTART;
    while ((ADC1_STATR & ADC_STATR_EOC) == 0) {
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

/* 档位色（按 mV 分 5 档）：一档一个颜色，用户不用记亮度绝对值也能判断量级 */
static rgb_t band_color(uint32_t mv)
{
    if (mv < 120u)  { rgb_t c = {  0,   0, 255}; return c; }  /* 蓝：几乎没信号 */
    if (mv < 400u)  { rgb_t c = {  0, 200, 255}; return c; }  /* 青：弱 */
    if (mv < 1000u) { rgb_t c = {  0, 255,   0}; return c; }  /* 绿：中 */
    if (mv < 2000u) { rgb_t c = {255, 120,   0}; return c; }  /* 橙：强 */
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

/* 心跳/刷新节拍：主循环 ≈500 ms 一圈 ⇒ 2 圈 ≈1 s */
#define BEAT_ITERS 2u

/* ───────────────────────── main ───────────────────────── */
int main(void)
{
    spi_init();
    adc_init();
    (void)adc_once();   /* 使能后的第一次转换丢掉 */

    /* ① 上电自检：白光闪 3 次 */
    for (uint8_t i = 0; i < 3; i++) {
        ws_rgb(60, 60, 60);
        delay_ms(60);
        ws_rgb(0, 0, 0);
        delay_ms(240);
    }

    uint16_t beat = 0;
    for (;;) {
        /* 每圈开头采样：离上一次 LED 刷新（`ws_latch` 之后）已过 ≥500 ms
         * ⇒ 刷新瞬间 VDD 的那一下跌落早没了（节点 τ = R1·C1 = 1 ms）✓ */
        uint16_t code = adc_sample12();
        uint32_t mv   = code_to_mv(code);

        if (mv < 20u) {
            /* 读数≈0：灯灭就看不出「有没有在跑」⇒ 每秒给一次暗白心跳（1% 占空，不烦人） */
            if (++beat >= BEAT_ITERS) {
                beat = 0;
                ws_rgb(20, 20, 20);
                delay_ms(10);
                ws_rgb(0, 0, 0);
            }
        } else {
            beat = 0;
            rgb_t   c  = band_color(mv);
            uint8_t lv = level_of(mv);
            ws_rgb(scale8(c.r, lv), scale8(c.g, lv), scale8(c.b, lv));
        }

        delay_ms(500);   /* ≈2 Hz：包络本身只有 160 Hz 带宽，看趋势够了 */
    }
}
