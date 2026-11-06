/*
 * ch32v003.ld —— 自己写的最小链接脚本（不依赖 WCH SDK）
 * 存储器：FLASH 16 K @ 0x00000000（CH32V003 代码区就在 0，不是 0x08000000）
 *         RAM   2 K @ 0x20000000
 */
ENTRY(_start)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 16K
    RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 2K
}

SECTIONS
{
    /* 向量表 + 复位入口，必须落在 0x00000000 */
    .init :
    {
        KEEP(*(.init))
        . = ALIGN(4);
    } >FLASH

    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text.*)
        *(.rodata)
        *(.rodata.*)
        . = ALIGN(4);
    } >FLASH

    .data :
    {
        . = ALIGN(4);
        _data_vma = .;
        *(.data)
        *(.data.*)
        . = ALIGN(4);
        _edata = .;
    } >RAM AT>FLASH
    _data_lma = LOADADDR(.data);

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } >RAM

    /* 栈顶 = RAM 末尾（向下生长）；本固件递归只有一层，留 1 K 都嫌多 */
    _e_stack = ORIGIN(RAM) + LENGTH(RAM);
}
