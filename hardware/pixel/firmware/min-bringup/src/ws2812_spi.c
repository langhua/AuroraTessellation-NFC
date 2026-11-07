/*
 * ws2812_spi.c —— WS2812B 驱动：**SPI1 + MOSI** 版（原方案，当前**不编译**）
 *
 * 现状（2026-11-07）✗：本板上这条路走不通 —— `PC6` 复用成 MOSI 后空闲一直停在
 *   ~4.9 V（WS2812 把它读成一串 1 ⇒ 全灯白），探针读回 `SPI1_CTLR1` 也不对，
 *   而同一根脚当普通输出完全正常。手边没有示波器，暂时定位不到根因。
 *   ⇒ 默认改用 `ws2812_gpio.c`（GPIO 位翻转）✓
 *
 * 想切回来：把 Makefile 的 SRCS 里 `ws2812_gpio.c` 换成 `ws2812_spi.c` 即可 ✓
 *   （接口完全一样：`ws_init()` / `ws_rgb()`）
 *
 * 一帧的位编码（SPI 6 MHz ⇒ 1 个 WS2812 位 = 8 个 SPI 位 = 1.333 µs）：
 *   '0' → 0xC0（高 0.33 µs / 低 1.00 µs）
 *   '1' → 0xF8（高 0.83 µs / 低 0.50 µs）
 */
#include "regs.h"
#include "ws2812.h"

#define WS_CODE_0 0xC0u
#define WS_CODE_1 0xF8u

static void delay_ms(uint32_t ms)
{
    uint32_t n = ms * 2000u;
    while (n--) {
        __asm__ volatile("nop");
    }
}

static void ws_spi_send_byte(uint8_t b)
{
    for (int8_t i = 7; i >= 0; i--) {
        SPI1_DATAR = (b & (1u << i)) ? WS_CODE_1 : WS_CODE_0;
        /* 等发送缓冲空。★ 带上限：不许死等（见 main.c / README 的教训） */
        for (uint32_t t = 0; t < 40000u; t++) {
            if (SPI1_STATR & SPI_STATR_TXE) {
                break;
            }
        }
    }
}

void ws_init(void)
{
    RCC_APB2PCENR |= RCC_APB2EN_IOPC | RCC_APB2EN_SPI1;

    /* PC6 = SPI1_MOSI（数据手册表 2-2：默认复用就是 MOSI，不用 AFIO 重映射） */
    GPIOC_CFGLR = (GPIOC_CFGLR & ~(0xFu << GPIO_CFG_SHIFT(6)))
                | (GPIO_CFG_AF_PP_50M << GPIO_CFG_SHIFT(6));

    SPI1_CTLR1 = 0;
    SPI1_CTLR1 = SPI_CTLR1_MSTR | SPI_CTLR1_SSM | SPI_CTLR1_SSI | SPI_CTLR1_BR_DIV4;
    SPI1_CTLR1 |= SPI_CTLR1_SPE;
}

void ws_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    ws_spi_send_byte(g);
    ws_spi_send_byte(r);
    ws_spi_send_byte(b);
    delay_ms(1);    /* 锁存：> 280 µs 低电平（✗ 不再死等 BSY）*/
}
