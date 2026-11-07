/*
 * probe.c —— 「自检报告版」：芯片自己试一遍 SPI，然后把结论用 PC6 闪码报出来
 *
 * 为什么要有它（2026-11-07）✓
 *   现象：正常固件跑起来后 `PC6` 一直停在 5 V（实测 4.9 V），WS2812 把持续高
 *   读成一串 1 ⇒ 全白。而同一根脚当 GPIO 用时是正常的。
 *   可能原因有两个，靠猜分不开 ⇒ 让芯片自己回答：
 *     A) SPI1 的寄存器根本写不进去（没时钟 / 基址不对）
 *     B) 寄存器写进去了，但引脚没有被 SPI 驱动（AF 没连上 / 需 AFIO 时钟）
 *
 * 怎么报（PC6 上闪「短闪次数 = 结论」，然后停 1 秒循环）：
 *   1 下 ⇒ **A 失败**：`SPI1_CTLR1` 读回来不对 ⇒ SPI1 没时钟或基址错
 *   2 下 ⇒ 寄存器 OK，但**引脚仍是高** ⇒ AF 没驱动这脚（复用问题）
 *   3 下 ⇒ 寄存器 OK，**引脚是低** ⇒ SPI 正在驱动 ⇒ 那问题就在时序/帧上
 *
 * ★ 这一版已经把 **AFIO 时钟**也一起打开（`RCC_APB2EN_AFIO`）：
 *   如果闪 3 下，就说明"缺 AFIO 时钟"就是根因 ✓
 */
#include "regs.h"

#define PIN 6u

static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * 2000u;
    while (n--) {
        __asm__ volatile("nop");
    }
}

static void pin_low(void)  { GPIOC_BCR  = (1u << PIN); }
static void pin_high(void) { GPIOC_BSHR = (1u << PIN); }

int main(void)
{
    /* ── 1. 使能时钟（含 AFIO）── */
    RCC_APB2PCENR |= RCC_APB2EN_IOPC | RCC_APB2EN_SPI1 | RCC_APB2EN_AFIO;
    (void)RCC_APB2PCENR;

    /* ── 2. PC6 = 复用推挽 50 MHz（= SPI1_MOSI）── */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_AF_PP_50M << GPIO_CFG_SHIFT(PIN));

    /* ── 3. 配 SPI1：主机、软件 NSS、8 位、CPOL=0 CPHA=0、PCLK/4 ── */
    SPI1_CTLR1 = 0;
    SPI1_CTLR1 = SPI_CTLR1_MSTR | SPI_CTLR1_SSM | SPI_CTLR1_SSI | SPI_CTLR1_BR_DIV4;
    SPI1_CTLR1 |= SPI_CTLR1_SPE;

    /* ── 4. 读回判定 A：寄存器到底写进去没有 ── */
    uint32_t rd = SPI1_CTLR1;
    const uint32_t want = SPI_CTLR1_MSTR | SPI_CTLR1_SSM | SPI_CTLR1_SSI | SPI_CTLR1_SPE;
    int regs_ok = ((rd & want) == want);

    /* ── 5. 判定 B：没有数据在发时，引脚实际是什么电平 ──
     *     PC6 现在是复用推挽输出，但 INDR 仍能读到引脚真实电平 ✓ */
    delay_ms(2);
    int pin_is_low = ((GPIOC_INDR & (1u << PIN)) == 0u);

    int code = regs_ok ? (pin_is_low ? 3 : 2) : 1;

    /* ── 6. 把 PC6 改回普通推挽输出，用闪码把结论报出来 ── */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_OUT_PP_2M << GPIO_CFG_SHIFT(PIN));

    for (;;) {
        for (int i = 0; i < code; i++) {
            pin_high();
            delay_ms(500);
            pin_low();
            delay_ms(500);
        }
        delay_ms(2000);   /* 组与组之间停 2 秒，方便万用表数 */
    }
}
