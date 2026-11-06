/*
 * startup.S —— CH32V003 最小启动（自己写的，不依赖 WCH SDK）
 *
 * 布局（照 EVT `startup_ch32v00x.S` 与 `Link.ld` 核对过）：
 *   0x00000000  .init 段的第一条 = `j reset`（复位后从这里开始执行）
 *   0x00000004  保留字
 *   0x00000008 起 = 异常/中断向量表（本固件不开中断 ⇒ 全部指向 trap）
 *
 * 注意：`mtvec` 用「向量表模式」（低 2 位置 3）⇒ 第 n 个异常跳到 _start + 4n。
 */
    .section .init, "ax", @progbits
    .globl  _start
    .align  2
_start:
    .option norvc                /* `j` 必须是 4 字节，后面每个 .word 才落在 4 的倍数上 */
    j       reset
    .word   0
    .rept   60                   /* NMI / HardFault / SysTick / SW + 38 个外设中断，一律进 trap */
    .word   trap
    .endr
    .option rvc

    .section .text.trap, "ax", @progbits
    .align  2
trap:
    j       trap                 /* 出异常就停在这里：LED 保持最后一次颜色 ⇒ 一眼看出「死了」 */

    .section .text.reset, "ax", @progbits
    .align  2
reset:
    la      sp, _e_stack         /* 先有栈，才能进 C */
    la      t0, _start
    ori     t0, t0, 3            /* mtvec = _start + 模式 3（绝对地址 + 向量表） */
    csrw    mtvec, t0

    /* 把 .data 从 Flash 搬到 RAM（本固件基本用不到，但保持 C 语义完整） */
    la      a0, _data_lma
    la      a1, _data_vma
    la      a2, _edata
1:  bgeu    a1, a2, 2f
    lw      t0, 0(a0)
    sw      t0, 0(a1)
    addi    a0, a0, 4
    addi    a1, a1, 4
    j       1b
2:
    /* 清 .bss */
    la      a0, _sbss
    la      a1, _ebss
3:  bgeu    a0, a1, 4f
    sw      zero, 0(a0)
    addi    a0, a0, 4
    j       3b
4:
    call    main
5:  j       5b                   /* main 不该返回 */
