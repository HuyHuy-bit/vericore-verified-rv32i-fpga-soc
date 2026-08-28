#!/usr/bin/env python3
"""A minimal RV32I functional model: straight-line ALU + load/store subset.

Not a golden reference for the whole ISA (no branches/jumps/traps/CSRs) —
building that is what Spike is for (see docs/verification.md; blocked in
this sandbox on installing Spike's build deps). This covers exactly the
instruction subset tools/rand_gen.py emits, which is enough to catch
forwarding/hazard/LSU bugs via random final-register-state comparison
without needing an external simulator.
"""
import sys


def sext(v, bits):
    v &= (1 << bits) - 1
    if v & (1 << (bits - 1)):
        v -= (1 << bits)
    return v


def run(words, mem_words=64):
    regs = [0] * 32
    mem = [0] * mem_words  # word-addressed scratch, base address 0

    def w(v):
        return v & 0xFFFFFFFF

    for instr in words:
        opcode = instr & 0x7F
        rd = (instr >> 7) & 0x1F
        funct3 = (instr >> 12) & 0x7
        rs1 = (instr >> 15) & 0x1F
        rs2 = (instr >> 20) & 0x1F
        funct7 = (instr >> 25) & 0x7F
        imm_i = sext(instr >> 20, 12)
        imm_s = sext(((instr >> 25) << 5) | ((instr >> 7) & 0x1F), 12)
        shamt = (instr >> 20) & 0x1F

        if instr == 0x0000006F:  # halt (jal x0,0)
            break

        if opcode == 0x33:  # R-type
            a, b = regs[rs1], regs[rs2]
            if funct3 == 0x0: res = w(a - b) if funct7 == 0x20 else w(a + b)
            elif funct3 == 0x1: res = w(a << (b & 0x1F))
            elif funct3 == 0x2: res = 1 if sext(a, 32) < sext(b, 32) else 0
            elif funct3 == 0x3: res = 1 if w(a) < w(b) else 0
            elif funct3 == 0x4: res = w(a ^ b)
            elif funct3 == 0x5: res = w(sext(a, 32) >> (b & 0x1F)) if funct7 == 0x20 else w(a >> (b & 0x1F))
            elif funct3 == 0x6: res = w(a | b)
            else: res = w(a & b)
            if rd: regs[rd] = res
        elif opcode == 0x13:  # I-type ALU
            a = regs[rs1]
            if funct3 == 0x0: res = w(a + imm_i)
            elif funct3 == 0x2: res = 1 if sext(a, 32) < imm_i else 0
            elif funct3 == 0x3: res = 1 if w(a) < w(imm_i) else 0
            elif funct3 == 0x4: res = w(a ^ imm_i)
            elif funct3 == 0x6: res = w(a | imm_i)
            elif funct3 == 0x7: res = w(a & imm_i)
            elif funct3 == 0x1: res = w(a << shamt)
            else: res = w(sext(a, 32) >> shamt) if (funct7 == 0x20) else w(a >> shamt)
            if rd: regs[rd] = res
        elif opcode == 0x03:  # LOAD (word only, from the scratch region)
            addr = w(regs[rs1] + imm_i)
            val = mem[(addr // 4) % mem_words]
            if rd: regs[rd] = val
        elif opcode == 0x23:  # STORE (word only)
            addr = w(regs[rs1] + imm_s)
            mem[(addr // 4) % mem_words] = w(regs[rs2])
        elif opcode == 0x37:  # LUI
            if rd: regs[rd] = w(instr & 0xFFFFF000)
        elif opcode == 0x17:  # AUIPC — pc unknown to this straight-line model; unused by rand_gen
            raise NotImplementedError("AUIPC not supported by this model")
        else:
            raise NotImplementedError(f"opcode 0x{opcode:x} not supported by this model")

    return regs


if __name__ == "__main__":
    hexfile = sys.argv[1]
    words = [int(line, 16) for line in open(hexfile) if line.strip()]
    regs = run(words)
    for i in range(1, 32):
        if regs[i]:
            print(f"x{i}=0x{regs[i]:x}")
