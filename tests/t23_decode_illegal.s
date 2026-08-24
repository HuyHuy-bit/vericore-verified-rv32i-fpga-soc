# t23_decode_illegal.s — precise traps for high-risk reserved encodings.
#
# Each case loads its own expected PC and instruction word before executing a
# raw illegal encoding.  The handler checks mcause/mepc/mtval, advances mepc by
# exactly one instruction, and returns.  x12 increments immediately after each
# fault, so an imprecise trap flush would execute a marker twice while a missing
# trap or redirect would lose handler/progress counts.
    la    x1, handler
    csrrw x0, mtvec, x1

    addi  x4, x0, 77       # faulting register destinations must stay unchanged
    addi  x5, x0, 3
    addi  x6, x0, 4
    addi  x10, x0, 2       # expected illegal-instruction cause
    addi  x13, x0, 85
    sw    x13, 0(x0)       # invalid STORE must not alter this memory marker
    addi  x19, x0, 91
    csrrw x0, mscratch, x19 # invalid SYSTEM must not alter this CSR marker
    la    x20, alias_redirect

    # Seed trap state away from all first-case expectations.  Later cases use
    # distinct PCs and instruction words, so stale trap metadata cannot pass.
    addi  x18, x0, 7
    csrrw x0, mcause, x18
    addi  x18, x0, 99
    csrrw x0, mtval, x18
    addi  x18, x0, 111
    csrrw x0, mepc, x18

    # M-extension alias: MUL x4,x5,x6 (unsupported by RV32I).
    la    x2, bad_m_extension
    lui   x3, 0x02628
    addi  x3, x3, 563
bad_m_extension:
    .word 0x02628233
    addi  x12, x12, 1

    # Reserved OP funct7 (neither ADD nor SUB).
    la    x2, bad_op_funct7
    lui   x3, 0x04628
    addi  x3, x3, 563
bad_op_funct7:
    .word 0x04628233
    addi  x12, x12, 1

    # Reserved SLLI upper immediate bits.
    la    x2, bad_slli
    lui   x3, 0x02629
    addi  x3, x3, 531
bad_slli:
    .word 0x02629213
    addi  x12, x12, 1

    # Reserved SRLI/SRAI upper immediate bits.
    la    x2, bad_srli
    lui   x3, 0x0262d
    addi  x3, x3, 531
bad_srli:
    .word 0x0262d213
    addi  x12, x12, 1

    # Reserved LOAD funct3=011 with rd=x4.
    la    x2, bad_load
    lui   x3, 0x00003
    addi  x3, x3, 515
bad_load:
    .word 0x00003203
    addi  x12, x12, 1

    # Reserved STORE funct3=011 with rs2=x13 and address zero.
    la    x2, bad_store
    lui   x3, 0x00d03
    addi  x3, x3, 35
bad_store:
    .word 0x00d03023
    addi  x12, x12, 1

    # Reserved BRANCH funct3=010.
    la    x2, bad_branch
    lui   x3, 0x0052a
    addi  x3, x3, 1123
bad_branch:
    .word 0x0052a463
    addi  x12, x12, 1

    # Reserved JALR funct3=001.  A broadened decoder would redirect through
    # x20 and overwrite x4 with a link; the legal trap does neither.
    la    x2, bad_jalr
    lui   x3, 0x000a1
    addi  x3, x3, 615
bad_jalr:
    .word 0x000a1267
    addi  x12, x12, 1

    # Reserved FENCE funct3=010; other fields are deliberately nonzero.
    la    x2, bad_fence
    lui   x3, 0xabcaa
    addi  x3, x3, 527
bad_fence:
    .word 0xabcaa20f
    addi  x12, x12, 1

    # Reserved SYSTEM funct3=100 targeting mscratch with rs1=x19 and rd=x4.
    la    x2, bad_system_funct3
    lui   x3, 0x3409c
    addi  x3, x3, 627
bad_system_funct3:
    .word 0x3409c273
    addi  x12, x12, 1

    # Unsupported privileged SYSTEM instructions.
    la    x2, bad_wfi
    lui   x3, 0x10500
    addi  x3, x3, 115
bad_wfi:
    .word 0x10500073
    addi  x12, x12, 1

    la    x2, bad_sret
    lui   x3, 0x10200
    addi  x3, x3, 115
bad_sret:
    .word 0x10200073
    addi  x12, x12, 1

    la    x2, bad_sfence_vma
    lui   x3, 0x12000
    addi  x3, x3, 115
bad_sfence_vma:
    .word 0x12000073
    addi  x12, x12, 1

    # funct3=000 is legal only for the exact ECALL/EBREAK/MRET words.
    la    x2, bad_ecall_rd
    addi  x3, x0, 627
bad_ecall_rd:
    .word 0x00000273
    addi  x12, x12, 1

    la    x2, bad_mret_fields
    lui   x3, 0x30208
    addi  x3, x3, 627
bad_mret_fields:
    .word 0x30208273
    addi  x12, x12, 1

    # Unknown opcode family.
    la    x2, bad_opcode
    addi  x3, x0, -1
bad_opcode:
    .word 0xffffffff
    addi  x12, x12, 1

    # Architectural side-effect checks after all 16 precise returns.
    lw    x14, 0(x0)
    csrrs x19, mscratch, x0
    addi  x15, x0, 123
    jal   x0, finish

alias_redirect:
    # Only a wrongly accepted reserved JALR can enter here.
    addi  x17, x0, 31

finish:
    tohost
    halt

handler:
    addi  x16, x16, 1
    csrrs x7, mcause, x0
    csrrs x8, mepc, x0
    csrrs x9, mtval, x0
    bne   x7, x10, metadata_failure
    bne   x8, x2, metadata_failure
    bne   x9, x3, metadata_failure
    addi  x11, x11, 1
    jal   x0, resume_fault

metadata_failure:
    addi  x17, x17, 1

resume_fault:
    addi  x8, x8, 4
    csrrw x0, mepc, x8
    mret
