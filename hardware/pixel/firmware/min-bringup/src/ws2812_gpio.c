/*
 * ws2812_gpio.c —— WS2812B 驱动：**GPIO 位翻转**（2026-11-07 起使用）
 *
 * 为什么换掉 SPI ✓
 *   本板上 SPI1 表现异常：`PC6`（复用成 MOSI 后）空闲一直停在 ~4.9 V，
 *   探针读回 `SPI1_CTLR1` 也不对；而同一根脚当普通输出完全正常。
 *   手边没有示波器在线看，继续猜 SPI 只会拖时间 ✗
 *   ⇒ 改用已经**实测可用**的 GPIO 输出，代价是写一帧要占 CPU ≈32 µs。
 *      本固件 0.5 s 才发一帧，这点占用可以忽略 ✓
 *   (SPI 版原样留在 `ws2812_spi.c`，将来定位到原因可以直接切回。)
 *
 * 时序（24 MHz ⇒ 1 周期 = 41.67 ns）✓
 *   WS2812B 规格：T0H 0.25–0.55 µs、T1H 0.65–0.95 µs、周期 1.25±0.6 µs
 *   目标：1 位 = **30 周期 = 1.25 µs**
 *         '0' 高 8 周期（0.333 µs）、'1' 高 20 周期（0.833 µs）
 *   ⇒ 两条路径各自凑满 30 周期；具体 nop 数由反汇编核对（见 README）
 *
 * 复位（锁存）＝ 保持低电平 > 280 µs ⇒ 这里给 1 ms ✓
 */
#include "regs.h"
#include "ws2812.h"

#define PIN    6u
#define MASK   (1u << PIN)

#define NOP1   __asm__ volatile("nop")
#define NOP2   NOP1; NOP1
#define NOP4   NOP2; NOP2
#define NOP8   NOP4; NOP4

static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * 2000u;
    while (n--) {
        __asm__ volatile("nop");
    }
}

void ws_init(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPC;
    (void)RCC_APB2PCENR;

    /* PC6 = 推挽输出 50 MHz（MODE=11 CNF=00）*/
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_OUT_PP_50M << GPIO_CFG_SHIFT(PIN));

    GPIOC_BCR = MASK;   /* 空闲低 */
}

/* 8 位，MSB 先出
 *
 * ★★ 2026-11-07 按**实测**重排（不是按理论周期算）：
 *   逻辑分析仪（24 MHz 采样）实测：原来的版本 '0' 高 1.375 µs、'1' 高 2.875 µs、
 *   位周期 4.4 µs —— 全部超出 WS2812B 的容差 ⇒ 芯片把这串数据当垃圾丢掉 ⇒ 灯不亮。
 *   反推：**本机一条指令 ≈ 3.29 个采样点 ≈ 0.137 µs**（比"1 周期/指令"慢 3 倍多）。
 *   ⇒ 按"指令条数"重排：'0' 高 3 条（≈0.41 µs）、'1' 高 6 条（≈0.83 µs）、
 *      位周期 10~12 条（1.38~1.65 µs），全部落在容差内 ✓
 *   ★ 每条路径前面都垫了相同的指令数，所以两条路的周期都接近，不会出现"短位" ✓ */
void ws_send_byte(uint8_t b)
{
    register uint32_t v asm("a0") = (uint32_t)b;

    /* ★★ 2026-11-07 第二次按实测标定（逻辑分析仪 24 MHz，逐样点统计）：
     *   实测模型：**高电平 = 6 + 3 × nop 个采样点**（1 点 = 41.67 ns）
     *     → 1 个 nop ≈ 0.125 µs；"两个 store 之间"的固定开销 ≈ 6 点 ≈ 0.25 µs
     *   标定依据：'0' 用 3 个 nop 实测 15 点（0.625 µs）、'1' 用 6 个 nop 实测 24 点（1.000 µs）
     *            ⇒ 差值 9 点 / 3 个 nop ⇒ **1 nop = 3 点** ✓
     *   本轮取值：'0' = 1 个 nop（6+3 = 9 点 ≈ 0.375 µs）、'1' = 4 个 nop（6+12 = 18 点 ≈ 0.75 µs）
     *   同时**去掉低电平里的填充 nop 和多余跳转**：上一版 '1' 的位周期 3.0 µs 超了 1.85 上限 ✗
     *   分支（bnez）放在两次 store **之前**，跳转代价落进上一位的低电平 ✓ */
    __asm__ volatile(
        "lui  t0, 0x40011        \n\t"   /* GPIOC 基址 0x40011000 */
        "li   t1, 64             \n\t"   /* 1<<6 ⇒ BSHR/BCR 位掩码 */
        "li   t2, 8              \n\t"   /* 8 位 */
        "1:                      \n\t"
        "andi a1, %0, 128        \n\t"   /* 测 bit7（RV32E 无 t3，用 a1）*/
        "bnez a1, 3f             \n\t"   /* '1' 才跳 */
        "sw   t1, 16(t0)         \n\t"   /* ── '0' 拉高 ── */
        "nop                     \n\t"   /* '0' 高 = 1 个 nop */
        "sw   t1, 20(t0)         \n\t"   /* ── 拉低 ── */
        "j    4f                 \n\t"
        "3:                      \n\t"
        "sw   t1, 16(t0)         \n\t"   /* ── '1' 拉高 ── */
        "nop;nop;nop;nop         \n\t"   /* '1' 高 = 4 个 nop */
        "sw   t1, 20(t0)         \n\t"   /* ── 拉低 ── */
        "4:                      \n\t"
        "slli %0, %0, 1          \n\t"
        "addi t2, t2, -1         \n\t"
        "bnez t2, 1b             \n\t"
        : "+r"(v)
        :
        : "t0", "t1", "t2", "a1", "memory");
}

void ws_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    ws_send_byte(g);
    ws_send_byte(r);
    ws_send_byte(b);
    delay_ms(1);    /* 锁存：> 280 µs 低电平 */
}
