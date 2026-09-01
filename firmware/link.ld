OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
    IMEM (rx)  : ORIGIN = 0x00000000, LENGTH = 32K
    DMEM (rwx) : ORIGIN = 0x20000000, LENGTH = 32K
}

SECTIONS {
    . = ORIGIN(IMEM);
    .text : ALIGN(4) {
        KEEP(*(.text.init))
        *(.text .text.*)
        *(.rodata .rodata.* .srodata .srodata.*)
        . = ALIGN(4);
        __text_end = .;
    } > IMEM

    . = ORIGIN(DMEM);
    .data : ALIGN(4) {
        *(.data .data.* .sdata .sdata.*)
        . = ALIGN(4);
        __data_end = .;
    } > DMEM

    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .;
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > DMEM

    __stack_top = ORIGIN(DMEM) + LENGTH(DMEM);

    /DISCARD/ : {
        *(.comment)
        *(.note .note.*)
        *(.eh_frame .eh_frame.*)
    }
}

ASSERT(__text_end <= ORIGIN(IMEM) + LENGTH(IMEM), "instruction BRAM overflow")
ASSERT(__data_end <= ORIGIN(DMEM) + LENGTH(DMEM), "data BRAM overflow")
ASSERT(__bss_end <= __stack_top, "BSS overlaps stack top")
