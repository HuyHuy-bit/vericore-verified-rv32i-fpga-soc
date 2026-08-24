# t10_misaligned.s — misaligned store trap.
    la    x1, handler      # mtvec = handler (label, not a byte count)
    csrrw x0, mtvec, x1    # mtvec = handler

    addi  x2, x0, 100      # a value to store
    addi  x3, x0, 2        # a deliberately misaligned address (2, not 4-aligned)
    addi  x4, x0, 99       # marker: reached before the fault
    sw    x2, 0(x3)        # STORE WORD to addr 2 -> MISALIGNED -> trap
    addi  x4, x0, 7        # wrong-path: squashed

handler:
    addi  x5, x0, 1        # reached handler
    csrrs x6, mcause, x0   # x6 = mcause (should be 6 = store misaligned)
    csrrs x7, mepc,   x0   # x7 = mepc (faulting PC)
    csrrs x8, mtval,  x0   # x8 = exact faulting effective address (2)
    tohost          # signal completion (exit code 1 = pass)
    halt
