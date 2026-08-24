# crt0.S - minimal startup for the benchmark kernels.
#
# Reuses compliance/link/rv32i-pipeline.ld unchanged, so the entry symbol
# has to be the one that script names: rvtest_entry_point.
#
# Sets up the stack, zeroes .bss (elf2hex only emits .data, so NOBITS
# sections arrive as whatever $readmemh left behind), calls bench(), and
# retires a self-loop sentinel. The testbench stops on that retirement, and
# bench()'s return value is sitting in a0/x10 for the ref-file check.

    .section .text.init
    .globl rvtest_entry_point
rvtest_entry_point:
    la      sp, _stack_top

    la      t0, _bss
    la      t1, _ebss
1:  bgeu    t0, t1, 2f
    sw      zero, 0(t0)
    addi    t0, t0, 4
    j       1b

2:  call    bench
3:  j       3b
