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
 * 怎么报（PC6 上**依次输出两个稳定电平**，万用表直流档直接读数）：
 *   第 1 位（先看到的那个，持续 5 秒）：
 *       5 V ⇒ `SPI1_CTLR1` **写得进去**（SPI1 有时钟、基址对）
 *       0 V ⇒ **写不进去** ⇒ SPI1 没时钟 / 基址错
 *   第 2 位（隔 2 秒之后，持续 5 秒）：
 *       5 V ⇒ SPI 空闲时**引脚是低** = AF 已经把脚交给 SPI 了（正常）
 *       0 V ⇒ 引脚**仍是高** ⇒ 复用没生效
 *   ★ 只要报“先多少伏、后多少伏”即可 ✓
 *   ✗ 不用数闪几下（表上数不准）✗ 也不用占空比（自动档会当电阻量，读成 kΩ）
 *
 * ★ 这一版已经把 **AFIO 时钟**也一起打开（`RCC_APB2EN_AFIO`）：
 *   如果闪 3 下，就说明"缺 AFIO 时钟"就是根因 ✓
 */
#include "regs.h"

#define PIN 6u

/* `delay_ms()` 在 `regs.h`（SysTick 计数）✓ */

static void pin_low(void)  { GPIOC_BCR  = (1u << PIN); }
static void pin_high(void) { GPIOC_BSHR = (1u << PIN); }

int main(void)
{
    /* ── 1. 使能时钟（含 AFIO）── */
    RCC_APB2PCENR |= RCC_APB2EN_IOPC | RCC_APB2EN_SPI1 | RCC_APB2EN_AFIO;
    (void)RCC_APB2PCENR;

    /* ★ 时钟使能后要等一下再访问外设：刚使能就立刻读写，寄存器可能读回 0，
     *   会让探针给出假的“写不进去” ✗（2026-11-07） */
    delay_ms(2);

    /* ── 2. PC6 = 复用推挽 50 MHz（= SPI1_MOSI）── */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_AF_PP_50M << GPIO_CFG_SHIFT(PIN));

    /* ── 3. 配 SPI1：主机、软件 NSS、8 位、CPOL=0 CPHA=0、PCLK/4 ── */
    SPI1_CTLR1 = 0;
    SPI1_CTLR1 = SPI_CTLR1_MSTR | SPI_CTLR1_SSM | SPI_CTLR1_SSI | SPI_CTLR1_BR_DIV4;
    SPI1_CTLR1 |= SPI_CTLR1_SPE;

    /* 同上：等外设真的跑起来再读回 */
    delay_ms(2);

    /* ── 4. 读回判定 A：寄存器到底写进去没有 ── */
    uint32_t rd = SPI1_CTLR1;
    const uint32_t want = SPI_CTLR1_MSTR | SPI_CTLR1_SSM | SPI_CTLR1_SSI | SPI_CTLR1_SPE;
    int regs_ok = ((rd & want) == want);

    /* ── 5. 判定 B：没有数据在发时，引脚实际是什么电平 ──
     *     PC6 现在是复用推挽输出，但 INDR 仍能读到引脚真实电平 ✓ */
    delay_ms(2);
    int pin_is_low = ((GPIOC_INDR & (1u << PIN)) == 0u);

    /* ── 6. 把 PC6 改回普通推挽输出，**依次报两个位（稳定电平）** ──
     *   ✗ 不用“数闪几下”（表上数不准），✗ 也不用占空比（自动档会当成电阻）
     *   ⇒ 每一位都输出 **5 秒稳定的高/低**，中间隔 2 秒高阻不着（拉低）：
     *        第 1 位 = 寄存器写得进去吗（5 V = 写得进，0 V = 写不进）
     *        第 2 位 = SPI 空闲时引脚是低吗（5 V = 是低【正常】，0 V = 仍是高）
     *   所以只要报“先看到多少伏、再看到多少伏”两个数就够了 ✓ */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(PIN)))
                | (GPIO_CFG_OUT_PP_2M << GPIO_CFG_SHIFT(PIN));

    for (;;) {
        /* 第 1 位 */
        if (regs_ok) { pin_high(); } else { pin_low(); }
        delay_ms(5000);
        pin_low();
        delay_ms(2000);

        /* 第 2 位 */
        if (pin_is_low) { pin_high(); } else { pin_low(); }
        delay_ms(5000);
        pin_low();
        delay_ms(2000);
    }
}
