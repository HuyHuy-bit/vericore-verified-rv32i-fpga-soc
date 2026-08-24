# t24_misaligned_control_flow.s — precise taken-branch and JALR alignment traps.
    la    x1, handler
    csrrw x0, mtvec, x1

    addi  x29, x0, 0        # count handler entries
    addi  x4, x0, 99        # branch wrong-path marker
    addi  x5, x0, 1
    addi  x6, x0, 1
    addi  x20, x0, 1        # branch handler visit
    bne   x5, x6, 2         # not taken: its misaligned alternate must not trap
    addi  x21, x0, 71       # branch cause snapshot starts nonzero
    addi  x17, x0, 7
    csrrw x0, mcause, x17   # stale mcause is nonzero immediately before fault
    beq   x5, x6, 2         # taken target = 48 + 2 = 50 -> trap
    addi  x4, x0, 7         # wrong path: handler must observe 99

after_branch:
    addi  x10, x0, 99       # JALR wrong-path marker
    addi  x15, x0, 85       # non-link marker: faulting JALR must preserve it
    addi  x11, x0, 64
    addi  x20, x0, 2        # JALR handler visit
    addi  x25, x0, 75       # JALR cause snapshot starts nonzero
    addi  x17, x0, 9
    csrrw x0, mcause, x17   # independently reseed immediately before JALR
    jalr  x15, x11, 3       # sum=67 (bits 1:0=11), masked target=66 (bit 1 set)
    addi  x10, x0, 7        # wrong path: handler must observe 99

after_jalr:
    addi  x18, x0, 123      # both traps resumed at their chosen continuation
    tohost
    halt

handler:
    addi  x29, x29, 1
    addi  x19, x0, 1
    beq   x20, x19, branch_handler

    addi  x28, x10, 0       # observe wrong-path marker before resume
    csrrs x25, mcause, x0
    csrrs x26, mepc, x0
    csrrs x27, mtval, x0
    la    x1, after_jalr
    csrrw x0, mepc, x1
    mret

branch_handler:
    addi  x24, x4, 0        # observe wrong-path marker before resume
    csrrs x21, mcause, x0
    csrrs x22, mepc, x0
    csrrs x23, mtval, x0
    la    x1, after_branch
    csrrw x0, mepc, x1
    mret
