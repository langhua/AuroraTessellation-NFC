/*
 * probe4 —— **PD5 放电脚"看得见"版**（2026-11-10 ✓）
 *
 * 用途：台架实测出现「读数在 0.1–2.5 V 之间大幅游走」✗ 时，用万用表一次判死：
 *   · `PD5` 是 `RC` 节点上的**放电脚**（与 `PD6` 同一节点 ✓）；
 *   · 本版**不做 ADC、不做颜色档位**，只把 `PD5` 做成**慢方波**：
 *       拉低 0.7 s  →  释放（模拟输入／高阻）1.3 s  →  循环
 *   · 表笔搭在 `PD6`（对 GND）上看到：
 *       0 V（≈0.7 s） ↔ 原本那个漂着的电平（≈1.3 s）  ⇒ **放电脚工作正常** ✓
 *       一直不动（既不归 0、也没有高电平段）        ⇒ **`PD5` 没有真的接到节点** ✗
 *   · 灯固定**暖白**（52,40,24）= 证明 MCU 在跑 ✓
 *
 * ✗ 会覆盖正常固件：测完请重新烧 `build/min-bringup.hex` ✗
 */
#include "regs.h"
#include "ws2812.h"

#define LOOPS_PER_MS 2000u
static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * LOOPS_PER_MS;
    while (n--) {
        __asm__ volatile("nop");
    }
}

/* ★ 与 main.c 的 rc_low / rc_release **同一套写法** ✓（`PD5`，开漏拉低 ⇒ 高阻）*/
#define RC_PIN 5

static void rc_low(void)
{
    GPIOD_BCR = (1u << RC_PIN);                 /* 输出寄存器置 0 ✓（开漏才会拉低 ✓）*/
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(RC_PIN)))
                | ((uint32_t)GPIO_CFG_OUT_OD_2M << GPIO_CFG_SHIFT(RC_PIN));
}

static void rc_release(void)
{
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(RC_PIN)))
                | ((uint32_t)GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(RC_PIN));
}

int main(void)
{
    ws_init();
    ws_rgb(52, 40, 24);                 /* 暖白 = 在跑 ✓（探针版不做颜色判断）*/

    RCC_APB2PCENR |= RCC_APB2EN_IOPD;
    delay_ms(1);
    /* PD6 = 模拟输入（只当"测量点"，本版不采 ✓）*/
    GPIOD_CFGLR = (GPIOD_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | ((uint32_t)GPIO_CFG_ANALOG << GPIO_CFG_SHIFT(6));
    rc_low();

    for (;;) {
        rc_low();
        delay_ms(700);                  /* 放电段：表应读到 ≈0 V ✓ */
        rc_release();
        delay_ms(1300);                 /* 高阻段：表读节点自己的电平 ✓ */
    }
}
