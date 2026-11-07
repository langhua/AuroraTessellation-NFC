# CH32V003 最小固件 —— 一次编译，不要增量（两个文件，3 秒内跑完）
#
# 用法（Windows / cmd）：
#   build.bat                 ← 推荐：自动找工具链
#   make                      ← 工具链已在 PATH 时
#   make TC_DIR="D:/.../bin" PREFIX=riscv32-wch-elf-
#   make clean
#
# 产物：build/min-bringup.hex（WCH-LinkUtility 直接烧这个）
#       build/min-bringup.bin / .elf / .map

BUILD  := build
TARGET := min-bringup

# 本机装了 Git Bash ⇒ make 默认拿 bash 当 shell（`if not exist` 就废了）⇒ 显式指定
ifeq ($(OS),Windows_NT)
  SHELL := cmd.exe
  .SHELLFLAGS := /c
  MKDIR = if not exist "$(BUILD)" mkdir "$(BUILD)"
  RMDIR = if exist "$(BUILD)" rmdir /S /Q "$(BUILD)"
else
  MKDIR = mkdir -p $(BUILD)
  RMDIR = rm -rf $(BUILD)
endif

# MounRiver Studio 2 自带 RISC-V GCC（GCC12 的 prefix 是 riscv-wch-elf-）
TC_DIR ?= F:/MounRiver/MounRiver_Studio2/resources/app/resources/win32/components/WCH/Toolchain/RISC-V Embedded GCC12/bin
PREFIX ?= riscv-wch-elf-
EXE    ?= .exe

CC      := $(TC_DIR)/$(PREFIX)gcc$(EXE)
OBJCOPY := $(TC_DIR)/$(PREFIX)objcopy$(EXE)
SIZE    := $(TC_DIR)/$(PREFIX)size$(EXE)

# rv32ec = 只有 16 个寄存器 + 压缩指令（CH32V003 的核）；e 系列必须 ilp32e
ARCH := -march=rv32ec -mabi=ilp32e -msmall-data-limit=0 -mno-save-restore
CFLAGS  := $(ARCH) -Os -ffreestanding -fno-common -fno-builtin -Wall -Wextra -I src
LDFLAGS := $(ARCH) -T ld/ch32v003.ld -nostartfiles -nostdlib -Wl,--gc-sections

SRCS := src/startup.S src/main.c src/ws2812_gpio.c
HDRS := src/regs.h src/ws2812.h ld/ch32v003.ld

all: $(BUILD)/$(TARGET).hex

$(BUILD)/$(TARGET).hex: $(SRCS) $(HDRS)
	$(MKDIR)
	"$(CC)" $(CFLAGS) $(LDFLAGS) -Wl,-Map=$(BUILD)/$(TARGET).map -o $(BUILD)/$(TARGET).elf $(SRCS) -lgcc
	"$(OBJCOPY)" -O ihex   $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).hex
	"$(OBJCOPY)" -O binary $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin
	@"$(SIZE)" $(BUILD)/$(TARGET).elf

# ── 万用表探针版（2026-11-07 ✓）：PC6 当普通输出翻 1 Hz，完全不碰 SPI ──
# 用途：在“灯已经不可信”的时候，用表判断 MCU 到底有没有在跑 / 引脚能不能推挽输出。
# ✗ 会覆盖正常固件，测完请重新烧子 $(BUILD)/$(TARGET).hex ✗
probe: $(BUILD)/$(TARGET)-probe.hex

$(BUILD)/$(TARGET)-probe.hex: src/startup.S src/probe.c $(HDRS)
	$(MKDIR)
	"$(CC)" $(CFLAGS) $(LDFLAGS) -Wl,-Map=$(BUILD)/$(TARGET)-probe.map -o $(BUILD)/$(TARGET)-probe.elf src/startup.S src/probe.c -lgcc
	"$(OBJCOPY)" -O ihex $(BUILD)/$(TARGET)-probe.elf $(BUILD)/$(TARGET)-probe.hex
	@"$(SIZE)" $(BUILD)/$(TARGET)-probe.elf

# ── 自检报告版（2026-11-07 ✓）：芯片自己试 SPI，再用 PC6 闪码报结论 ──
# 闪 1 下 = SPI1 寄存器写不进（没时钟/基址错）｜2 下 = 寄存器 OK 但引脚仍是高｜3 下 = 引脚被拉低（SPI 在驱动）
probe2: $(BUILD)/$(TARGET)-probe2.hex

$(BUILD)/$(TARGET)-probe2.hex: src/startup.S src/probe2.c $(HDRS)
	$(MKDIR)
	"$(CC)" $(CFLAGS) $(LDFLAGS) -Wl,-Map=$(BUILD)/$(TARGET)-probe2.map -o $(BUILD)/$(TARGET)-probe2.elf src/startup.S src/probe2.c -lgcc
	"$(OBJCOPY)" -O ihex $(BUILD)/$(TARGET)-probe2.elf $(BUILD)/$(TARGET)-probe2.hex
	@"$(SIZE)" $(BUILD)/$(TARGET)-probe2.elf

clean:
	$(RMDIR)

.PHONY: all clean probe probe2
