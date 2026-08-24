# t15_csr_unimpl.s — a read of an unimplemented CSR must trap illegal.
    la    x1, handler      # mtvec = handler (label, not a byte count)
    csrrw x0, mtvec, x1    # mtvec = handler

    addi  x4, x0, 99       # marker: reached before the fault
    addi  x7, x0, 88       # mtval snapshot starts independently nonzero
    addi  x10, x0, 62
    csrrw x0, mtval, x10   # stale mtval is nonzero immediately before fault
    csrrs x2, 0x3a0, x0    # 0x3a002173: unimplemented CSR read -> illegal trap
    addi  x4, x0, 7        # wrong-path: squashed

handler:
    addi  x5, x0, 1        # reached handler
    csrrs x6, mcause, x0   # x6 = mcause (should be 2 = illegal instruction)
    csrrs x7, mtval, x0    # x7 = exact faulting instruction word
    tohost          # signal completion (exit code 1 = pass)
    halt
