/*
 * regs.h —— CH32V003F4U6 用到的寄存器（只写本固件需要的那些）
 *
 * ★ 这里**不引用 WCH SDK**：地址与位定义都照
 *   ① 数据手册 `CH32V003DS0.PDF`（V1.8）
 *   ② MounRiver Studio 2 自带 EVT 里的 `ch32v00x.h` / `ch32v00x_adc.c` / `ch32v00x_rcc.h`
 *      （只用来核对数值，不拷代码）
 *   核对记录见同目录 README「数字从哪来」。
 */
#ifndef PIXEL_REGS_H
#define PIXEL_REGS_H

#include <stdint.h>

#define REG32(a) (*(volatile uint32_t *)(a))
#define REG16(a) (*(volatile uint16_t *)(a))

/* ── 存储器映射（ch32v00x.h：PERIPH_BASE=0x40000000、APB2=+0x10000、AHB=+0x20000）── */
#define FLASH_R_BASE   0x40022000u          /* AHBPERIPH_BASE + 0x2000 */
#define RCC_BASE       0x40021000u          /* AHBPERIPH_BASE + 0x1000 */
#define GPIOA_BASE     0x40010800u          /* APB2PERIPH_BASE + 0x0800 */
#define GPIOC_BASE     0x40011000u          /* APB2PERIPH_BASE + 0x1000 */
#define GPIOD_BASE     0x40011400u          /* APB2PERIPH_BASE + 0x1400 */
#define ADC1_BASE      0x40012400u          /* APB2PERIPH_BASE + 0x2400 */
#define SPI1_BASE      0x40013000u          /* APB2PERIPH_BASE + 0x3000 */

/* ── RCC（结构照 RCC_TypeDef）── */
#define RCC_CTLR       REG32(RCC_BASE + 0x00)
#define RCC_CFGR0      REG32(RCC_BASE + 0x04)
#define RCC_APB2PCENR  REG32(RCC_BASE + 0x18)

/* RCC_APB2PCENR 位（ch32v00x_rcc.h：RCC_APB2Periph_*） */
#define RCC_APB2EN_AFIO    0x00000001u
#define RCC_APB2EN_IOPA    0x00000004u
#define RCC_APB2EN_IOPC    0x00000010u
#define RCC_APB2EN_IOPD    0x00000020u
#define RCC_APB2EN_ADC1    0x00000200u
#define RCC_APB2EN_SPI1    0x00001000u

/* ── FLASH（结构照 FLASH_TypeDef：ACTLR 是第 0 个字）── */
#define FLASH_ACTLR    REG32(FLASH_R_BASE + 0x00)

/* ── GPIO（结构照 GPIO_TypeDef；CH32V003 每个口只有 8 根脚 ⇒ 只有 CFGLR）── */
#define GPIOA_CFGLR    REG32(GPIOA_BASE + 0x00)
#define GPIOC_CFGLR    REG32(GPIOC_BASE + 0x00)
#define GPIOD_CFGLR    REG32(GPIOD_BASE + 0x00)

/* 位设置/清除寄存器（CH32V00x：BSHR 0x10 置位、BCR 0x14 清零）——
 * 只给 src/probe.c（探针版）用：PC6 当普通输出 ✓ */
#define GPIOC_INDR     REG32(GPIOC_BASE + 0x08)
#define GPIOC_BSHR     REG32(GPIOC_BASE + 0x10)
#define GPIOC_BCR      REG32(GPIOC_BASE + 0x14)

/* CFGLR 里每根脚 4 位：低 2 位 = MODE，高 2 位 = CNF；脚 n 在 bit[4n+3:4n] */
#define GPIO_CFG_SHIFT(pin)   (4u * (pin))
/* 常用组合（MODE: 00=输入 10=输出2MHz 11=输出50MHz；CNF 在输入时: 00=模拟 01=浮空 10=上下拉；在输出时: 00=推挽 10=复用推挽） */
#define GPIO_CFG_ANALOG       0x0u   /* MODE=00 CNF=00 ⇒ 模拟输入 */
#define GPIO_CFG_OUT_PP_2M    0x2u   /* MODE=10 CNF=00 ⇒ 推挽输出 2 MHz */
#define GPIO_CFG_AF_PP_50M    0xBu   /* MODE=11 CNF=10 ⇒ 复用推挽 50 MHz */

/* ── ADC1（结构照 ADC_TypeDef：STATR 0x00、CTLR1 0x04、CTLR2 0x08、
 *        SAMPTR1 0x0C、SAMPTR2 0x10、IOFR1..4 0x14..0x20、WDHTR 0x24、WDLTR 0x28、
 *        RSQR1 0x2C? —— 按 ch32v00x_adc.c 的实际用法，先把偏移核对成下表）──
 *   核对：ADC_RegularChannelConfig 写 `RSQR3/RSQR2/RSQR1`，ADC_GetConversionValue 读 RDATAR。
 */
#define ADC1_STATR     REG32(ADC1_BASE + 0x00)
#define ADC1_CTLR1     REG32(ADC1_BASE + 0x04)
#define ADC1_CTLR2     REG32(ADC1_BASE + 0x08)
#define ADC1_SAMPTR1   REG32(ADC1_BASE + 0x0C)
#define ADC1_SAMPTR2   REG32(ADC1_BASE + 0x10)
#define ADC1_WDHTR     REG32(ADC1_BASE + 0x24)
#define ADC1_WDLTR     REG32(ADC1_BASE + 0x28)
#define ADC1_RSQR1     REG32(ADC1_BASE + 0x2C)
#define ADC1_RSQR2     REG32(ADC1_BASE + 0x30)
#define ADC1_RSQR3     REG32(ADC1_BASE + 0x34)
#define ADC1_RDATAR    REG32(ADC1_BASE + 0x4C)

/* ADC 位（ch32v00x_adc.c 里的宏值） */
#define ADC_STATR_EOC       0x00000002u   /* ADC_FLAG_EOC */
#define ADC_CTLR2_ADON      0x00000001u
#define ADC_CTLR2_CAL       0x00000004u
#define ADC_CTLR2_RSTCAL    0x00000008u
#define ADC_CTLR2_SWSTART   0x00400000u   /* 软件启动规则组转换 */

/* 采样时间编码（ch32v00x_adc.h：ADC_SampleTime_3Cycles=0 … 241Cycles=7） */
#define ADC_SMPT_241CYCLES  7u

/* ── SPI1（结构照 SPI_TypeDef：CTLR1 0x00、CTLR2 0x04、STATR 0x08、DATAR 0x0C）── */
#define SPI1_CTLR1     REG16(SPI1_BASE + 0x00)
#define SPI1_CTLR2     REG16(SPI1_BASE + 0x04)
#define SPI1_STATR     REG16(SPI1_BASE + 0x08)
#define SPI1_DATAR     REG16(SPI1_BASE + 0x0C)

#define SPI_CTLR1_CPHA      0x0001u
#define SPI_CTLR1_CPOL      0x0002u
#define SPI_CTLR1_MSTR      0x0004u
#define SPI_CTLR1_BR_DIV4   0x0008u   /* BR[2:0]=001 ⇒ PCLK2/4（SPI_BaudRatePrescaler_4） */
#define SPI_CTLR1_SPE       0x0040u
#define SPI_CTLR1_SSI       0x0100u
#define SPI_CTLR1_SSM       0x0200u   /* SPI_NSS_Soft */

#define SPI_STATR_RXNE      0x0001u
#define SPI_STATR_TXE       0x0002u
#define SPI_STATR_BSY       0x0080u

#endif /* PIXEL_REGS_H */
