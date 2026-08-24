# t18_trap_causes.s — ECALL, EBREAK and a misaligned LOAD, each returning via
# MRET. Closes the ecall/ebreak/misaligned-load trap-cause coverage that the
# earlier directed tests left unhit (t10 covers the misaligned *store* only).
# x6 accumulates each mcause, so a single value proves all three fired:
# 11 (ECALL) + 3 (EBREAK) + 4 (misaligned load) = 18.
    la    x1, handler      # mtvec = handler (label, not a byte count)
    csrrw x0, mtvec, x1

    addi  x10, x0, 77       # nonzero: ECALL handler must explicitly record 0
    addi  x11, x0, 88       # nonzero: EBREAK handler must explicitly record 0
    addi  x12, x0, 99       # nonzero: load handler must record exact addr 1
    addi  x8, x0, 1         # identify the ECALL handler visit
    ecall                   # cause 11
    addi  x8, x0, 2         # identify the EBREAK handler visit
    ebreak                  # cause 3
    addi  x8, x0, 3         # identify the misaligned-load handler visit
    lh    x4, 1(x0)         # addr 1 is odd -> misaligned load -> cause 4
    addi  x9, x0, 99        # marker: all three traps returned here
    tohost          # signal completion (exit code 1 = pass)
    halt

handler:
    addi  x15, x15, 1       # prove all three handler visits made progress
    csrrs x5, mcause, x0
    add   x6, x6, x5        # accumulate causes
    csrrs x7, mepc, x0
    csrrs x13, mtval, x0
    addi  x14, x0, 1
    beq   x8, x14, record_ecall
    addi  x14, x0, 2
    beq   x8, x14, record_ebreak
    addi  x12, x13, 0       # misaligned load mtval = exact address 1
    jal   x0, resume
record_ecall:
    addi  x10, x13, 0       # ECALL has no payload, mtval = 0
    jal   x0, resume
record_ebreak:
    addi  x11, x13, 0       # EBREAK has no payload, mtval = 0
resume:
    addi  x7, x7, 4         # skip the faulting instruction
    csrrw x0, mepc, x7
    mret
