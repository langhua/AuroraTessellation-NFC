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

/* 8 位，MSB 先出 */
static void ws_send_byte(uint8_t b)
{
    for (uint8_t m = 0x80u; m != 0u; m >>= 1) {
        if (b & m) {
            GPIOC_BSHR = MASK;      /* 高 */
            NOP8; NOP8; NOP4;       /* 见 README：按反汇编凑 20 周期 */
            GPIOC_BCR = MASK;       /* 低 */
            NOP4; NOP2;
        } else {
            GPIOC_BSHR = MASK;
            NOP4; NOP2;
            GPIOC_BCR = MASK;
            NOP8; NOP4;
        }
    }
}

void ws_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    ws_send_byte(g);
    ws_send_byte(r);
    ws_send_byte(b);
    delay_ms(1);    /* 锁存：> 280 µs 低电平 */
}
