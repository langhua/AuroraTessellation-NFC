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
LDFLAGS := $(ARCH) -T ld/ch32v003.ld -nostartfiles -nostdlib -Wl,--gc-sections \
           -Wl,-Map=$(BUILD)/$(TARGET).map

SRCS := src/startup.S src/main.c
HDRS := src/regs.h ld/ch32v003.ld

all: $(BUILD)/$(TARGET).hex

$(BUILD)/$(TARGET).hex: $(SRCS) $(HDRS)
	$(MKDIR)
	"$(CC)" $(CFLAGS) $(LDFLAGS) -o $(BUILD)/$(TARGET).elf $(SRCS) -lgcc
	"$(OBJCOPY)" -O ihex   $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).hex
	"$(OBJCOPY)" -O binary $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin
	@"$(SIZE)" $(BUILD)/$(TARGET).elf

clean:
	$(RMDIR)

.PHONY: all clean
