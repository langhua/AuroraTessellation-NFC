/*
 * ws2812.h —— WS2812 写入接口（与底层实现无关）
 *
 * 两种实现，编哪一个由 Makefile 的 SRCS 决定：
 *   ws2812_gpio.c  ← GPIO 位翻转（**当前使用**：2026-11-07 起）
 *   ws2812_spi.c   ← SPI1 + MOSI（原本的方案；本板上 SPI1 不响应，暂时不用）
 */
#ifndef WS2812_H
#define WS2812_H

#include <stdint.h>

/* 把 PC6 配成输出（GPIO 版是普通推挽输出；SPI 版是复用推挽 + SPI1 初始化） */
void ws_init(void);

/* 送一颗灯的颜色并锁存（WS2812B 的顺序是 G→R→B） */
void ws_rgb(uint8_t r, uint8_t g, uint8_t b);

/* 只送一个字节的原始位（不锁存）。★ 只给探针版（probe3）用，
 * 正常固件请用 ws_rgb() —— 单独发字节不构成一帧 ✓ */
void ws_send_byte(uint8_t b);

#endif /* WS2812_H */
