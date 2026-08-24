# t25_operand_use_hazards.s — live operands, not raw bit positions, stall.
    addi  x1, x0, 21
    sw    x1, 0(x0)
    addi  x2, x0, 22
    sw    x2, 4(x0)
    addi  x3, x0, 23
    sw    x3, 8(x0)
    addi  x4, x0, 24
    sw    x4, 12(x0)

    # LUI does not read rs1, even though immediate bits 19:15 equal x5.
    lw    x5, 0(x0)
    lui   x4, 0x28         # word 0x00028237: raw rs1 field is 5

    # OP-IMM does not read rs2, even though immediate bits 24:20 equal x6.
    lw    x6, 4(x0)
    addi  x7, x0, 6       # word 0x00600393: raw rs2 field is 6

    # CSR-immediate treats bits 19:15 as uimm=8, not register x8.
    lw    x8, 8(x0)
    csrrwi x9, mscratch, 8 # word 0x340454f3: raw rs1 field is 8

    # This is the only live load-use dependency and must insert one bubble.
    lw    x10, 12(x0)
    addi  x11, x10, 1
    csrrs x12, mscratch, x0

    tohost
    halt
