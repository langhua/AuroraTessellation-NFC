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
 * 怎么报（PC6 上输出不同**占空比**的方波，万用表直流档直接读电压）：
 *   ≈ **1.25 V**（25% 占空）⇒ **A 失败**：`SPI1_CTLR1` 读回不对 ⇒ SPI1 没时钟或基址错
 *   ≈ **2.50 V**（50% 占空）⇒ 寄存器 OK，但**引脚仍是高** ⇒ AF 没驱动这脚（复用问题）
 *   ≈ **3.75 V**（75% 占空）⇒ 寄存器 OK，**引脚是低** ⇒ SPI 正在驱动 ⇒ 问题在时序/帧
 *
 * ★ 用占空比而不是"数闪几下"，是因为万用表上数跳变不可靠 ✗（2026-11-07 实测）
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

    /* ── 6. 把 PC6 改回普通推挽输出，用**占空比**把结论报出来 ──
     *   ✗ 不靠"数闪几下"（万用表上数不准）⇒ 改成不同占空比的方波，
     *   直流档直接读到一个**稳定的平均电压** ✓：
     *      code 1 ⇒ 25% 占空 ⇒ ≈1.25 V
     *      code 2 ⇒ 50% 占空 ⇒ ≈2.50 V
     *      code 3 ⇒ 75% 占空 ⇒ ≈3.75 V
     *   周期 8 ms（125 Hz），表的显示会一直是那个数，不会来回跳 ✓ */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_OUT_PP_2M << GPIO_CFG_SHIFT(PIN));

    const uint32_t hi_ms = (uint32_t)code * 2u;   /* 1⇒2ms 2⇒4ms 3⇒6ms（周期 8 ms） */
    for (;;) {
        pin_high();
        delay_ms(hi_ms);
        pin_low();
        delay_ms(8u - hi_ms);
    }
}
