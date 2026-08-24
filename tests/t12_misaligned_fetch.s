# t12_misaligned_fetch.s — JAL to a target not 4-byte aligned must trap.
    la    x1, handler      # mtvec = handler (label, not a byte count)
    csrrw x0, mtvec, x1    # mtvec = handler

    addi  x4, x0, 99       # marker: reached before the fault
    addi  x8, x0, 85       # non-link marker: faulting JAL must preserve it
    jal   x8, 2            # JAL to pc+2 -> MISALIGNED (bit1 set) -> trap
    addi  x4, x0, 7        # wrong-path: squashed

handler:
    addi  x5, x0, 1        # reached handler
    csrrs x6, mcause, x0   # x6 = mcause (should be 0 = misaligned fetch)
    csrrs x7, mepc,   x0   # x7 = mepc (faulting PC, the jal instruction)
    csrrs x9, mtval,  x0   # x9 = resolved JAL target (mepc + 2)
    tohost          # signal completion (exit code 1 = pass)
    halt
