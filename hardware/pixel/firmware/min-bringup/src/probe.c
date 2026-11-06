/*
 * probe.c —— 「万用表探针版」：只做一件事，让 PC6 每秒翻转一次（1 Hz 方波）
 *
 * 为什么要有它（2026-11-07）✓：
 *   灯一直"全白"，但白的含义查不清 —— 可能是程序没跑、可能是引脚卡高、
 *   也可能是灯上一轮的残留帧。那颗灯已经不是可信的"眼睛" ✗
 *   ⇒ 换一个**不依赖灯**的判据：PC6 慢速翻转，万用表直流档一眼能看出来 ✓
 *
 * 怎么用：
 *   1) 烧 build/min-bringup-probe.hex（✗ 会覆盖正常固件，测完再烧回 min-bringup.hex）
 *   2) 万用表直流电压档：黑笔 GND，红笔点 **PC6 焊盘**（= 灯 DI 那一侧）
 *   3) 读数：
 *        · 在 0 V ↔ 5 V 之间**每秒来回跳**  ⇒ MCU 在跑、引脚能推挽输出 ✓
 *        · 一直是 0 V                        ⇒ MCU 没跑（烧录/启动/供电）✗
 *        · 一直是 5 V                        ⇒ 引脚卡高（这也会让 WS2812 读成全 1 = 白）✗
 *        · 一直是 2.5 V 左右                 ⇒ 表太快/太慢看不清，改用示波器或换成 0.5 Hz
 *
 * ★ 这一版**完全不碰 SPI**，所以它的结论与"SPI 时序对不对"无关 ✓
 */
#include "regs.h"

static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * 2000u;   /* 24 MHz 下约 12 周期/圈（与 main.c 同一口径） */
    while (n--) {
        __asm__ volatile("nop");
    }
}

int main(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPC;
    (void)RCC_APB2PCENR;

    /* PC6 = 推挽输出 2 MHz（MODE=10 CNF=00 ⇒ 0x2） */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | (GPIO_CFG_OUT_PP_2M << GPIO_CFG_SHIFT(6));

    for (;;) {
        GPIOC_BSHR = (1u << 6);   /* 高 */
        delay_ms(1000);
        GPIOC_BCR = (1u << 6);    /* 低 */
        delay_ms(1000);
    }
}
