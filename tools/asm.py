#!/usr/bin/env python3
"""Minimal RV32I assembler: .s -> .hex (Verilog $readmemh format)
Usage: python3 tools/asm.py input.s output.hex
"""
import sys, re

REGS = {f'x{i}': i for i in range(32)}
REGS.update({'zero':0,'ra':1,'sp':2,'gp':3,'tp':4,
             't0':5,'t1':6,'t2':7,'s0':8,'fp':8,'s1':9,
             'a0':10,'a1':11,'a2':12,'a3':13,'a4':14,'a5':15,
             'a6':16,'a7':17,'s2':18,'s3':19,'s4':20,'s5':21,
             's6':22,'s7':23,'s8':24,'s9':25,'s10':26,'s11':27,
             't3':28,'t4':29,'t5':30,'t6':31})

def r(s): return REGS[s.strip()]

def r_type(rd,rs1,rs2,f3,f7): return (f7<<25)|(r(rs2)<<20)|(r(rs1)<<15)|(f3<<12)|(r(rd)<<7)|0x33
def i_type(rd,rs1,imm12,f3,op): return ((imm12&0xFFF)<<20)|(r(rs1)<<15)|(f3<<12)|(r(rd)<<7)|op
def s_type(rs1,rs2,imm12,f3):
    i=imm12&0xFFF; return ((i>>5)<<25)|(r(rs2)<<20)|(r(rs1)<<15)|(f3<<12)|((i&0x1F)<<7)|0x23
def b_type(rs1,rs2,off,f3):
    o=off&0x1FFF
    return ((o>>12&1)<<31)|((o>>5&0x3F)<<25)|(r(rs2)<<20)|(r(rs1)<<15)|(f3<<12)|((o>>1&0xF)<<8)|((o>>11&1)<<7)|0x63
def u_type(rd,imm20,op): return ((imm20&0xFFFFF)<<12)|(r(rd)<<7)|op
def j_type(rd,off):
    o=off&0x1FFFFF
    return ((o>>20&1)<<31)|((o>>1&0x3FF)<<21)|((o>>11&1)<<20)|((o>>12&0xFF)<<12)|(r(rd)<<7)|0x6F

def assemble(src):
    CSRS={'mtvec':0x305,'mepc':0x341,'mcause':0x342,
          'mscratch':0x340,'mtval':0x343,'misa':0x301,
          'mvendorid':0xF11,'marchid':0xF12,'mimpid':0xF13,'mhartid':0xF14,
          'mstatus':0x300,'mie':0x304,'mip':0x344,
          'mtimecmp':0x7C0,'mtime':0x7C1,
          'mcycle':0xB00,'minstret':0xB02,'mcycleh':0xB80,'minstreth':0xB82}
    def CSR_NUM(s):
        s=s.strip().lower()
        return CSRS[s] if s in CSRS else (int(s,0)&0xFFF)
    # Pseudo-instructions that expand to more than one word. The label pass
    # has to know their true size or every label after one of them shifts -
    # which is exactly the bug that hardcoded handler offsets used to hide.
    SIZES={'la':2,'tohost':4}
    def op_words(line):
        return SIZES.get(re.split(r'[\s,()]+',line)[0].lower(), 1)

    labels={}; instrs=[]; addr=0
    for line in src.splitlines():
        line=line.split('#')[0].strip()
        if not line: continue
        m=re.match(r'^(\w+)\s*:(.*)',line)
        if m:
            labels[m.group(1)]=addr
            line=m.group(2).strip()
            if not line: continue
        instrs.append((addr,line)); addr+=4*op_words(line)

    words=[]
    for pc,line in instrs:
        p=re.split(r'[\s,()]+',line); p=[x for x in p if x]; op=p[0].lower()
        def iv(s):
            s=s.strip()
            return labels[s]-pc if s in labels else int(s,0)
        def i12(s): return iv(s)&0xFFF

        if   op=='add':   words.append(r_type(p[1],p[2],p[3],0,0x00))
        elif op=='sub':   words.append(r_type(p[1],p[2],p[3],0,0x20))
        elif op=='sll':   words.append(r_type(p[1],p[2],p[3],1,0x00))
        elif op=='slt':   words.append(r_type(p[1],p[2],p[3],2,0x00))
        elif op=='sltu':  words.append(r_type(p[1],p[2],p[3],3,0x00))
        elif op=='xor':   words.append(r_type(p[1],p[2],p[3],4,0x00))
        elif op=='srl':   words.append(r_type(p[1],p[2],p[3],5,0x00))
        elif op=='sra':   words.append(r_type(p[1],p[2],p[3],5,0x20))
        elif op=='or':    words.append(r_type(p[1],p[2],p[3],6,0x00))
        elif op=='and':   words.append(r_type(p[1],p[2],p[3],7,0x00))
        elif op=='addi':  words.append(i_type(p[1],p[2],i12(p[3]),0,0x13))
        elif op=='slti':  words.append(i_type(p[1],p[2],i12(p[3]),2,0x13))
        elif op=='sltiu': words.append(i_type(p[1],p[2],i12(p[3]),3,0x13))
        elif op=='xori':  words.append(i_type(p[1],p[2],i12(p[3]),4,0x13))
        elif op=='ori':   words.append(i_type(p[1],p[2],i12(p[3]),6,0x13))
        elif op=='andi':  words.append(i_type(p[1],p[2],i12(p[3]),7,0x13))
        elif op=='slli':  words.append(i_type(p[1],p[2],iv(p[3])&0x1F,1,0x13))
        elif op=='srli':  words.append(i_type(p[1],p[2],iv(p[3])&0x1F,5,0x13))
        elif op=='srai':  words.append(i_type(p[1],p[2],0x400|(iv(p[3])&0x1F),5,0x13))
        elif op in('lb','lh','lw','lbu','lhu'):
            f3={'lb':0,'lh':1,'lw':2,'lbu':4,'lhu':5}[op]
            words.append(i_type(p[1],p[3],i12(p[2]),f3,0x03))
        elif op=='jalr':
            if p[2] in REGS:           # jalr rd, rs1, imm
                words.append(i_type(p[1],p[2],i12(p[3]),0,0x67))
            else:                      # jalr rd, imm(rs1)
                words.append(i_type(p[1],p[3],i12(p[2]),0,0x67))
        elif op in('sb','sh','sw'):
            f3={'sb':0,'sh':1,'sw':2}[op]
            words.append(s_type(p[3],p[1],iv(p[2]),f3))
        elif op=='beq':   words.append(b_type(p[1],p[2],iv(p[3]),0))
        elif op=='bne':   words.append(b_type(p[1],p[2],iv(p[3]),1))
        elif op=='blt':   words.append(b_type(p[1],p[2],iv(p[3]),4))
        elif op=='bge':   words.append(b_type(p[1],p[2],iv(p[3]),5))
        elif op=='bltu':  words.append(b_type(p[1],p[2],iv(p[3]),6))
        elif op=='bgeu':  words.append(b_type(p[1],p[2],iv(p[3]),7))
        elif op=='lui':   words.append(u_type(p[1],iv(p[2]),0x37))
        elif op=='auipc': words.append(u_type(p[1],iv(p[2]),0x17))
        elif op=='jal':   words.append(j_type(p[1],iv(p[2])))
        elif op=='nop':   words.append(0x00000013)
        elif op=='halt':  words.append(0x0000006F)  # jal x0, 0 -> infinite self-loop
        elif op=='la':
            # la rd, label -> auipc rd, 0 ; addi rd, rd, (label - pc_of_auipc)
            # Lets a test name its handler instead of counting bytes to it.
            words.append(u_type(p[1],0,0x17))
            words.append(i_type(p[1],p[1],(labels[p[2]]-pc)&0xFFF,0,0x13))
        elif op=='tohost':
            # `tohost` / `tohost N` - signal test completion with exit code N
            # (default 1 = pass), per the riscv-tests convention. Expands to
            # two instructions: materialise the address, then store the code.
            # x31 is used as scratch; no directed test relies on it.
            code = int(p[1],0) if len(p)>1 else 1
            words.append(i_type('x31','x0',code,0,0x13))          # addi x31, x0, code
            words.append(u_type('x30',0x10,0x37))                 # lui  x30, 0x10  -> 0x10000
            words.append(i_type('x30','x30',-16,0,0x13))          # addi x30, x30, -16 -> 0xFFF0
            words.append(s_type('x30','x31',0,2))                 # sw   x31, 0(x30)
        elif op=='ret':   words.append(i_type('x0','x1',0,0,0x67))
        elif op=='ecall':  words.append(0x00000073)
        elif op=='ebreak': words.append(0x00100073)
        elif op=='mret':   words.append(0x30200073)
        elif op=='fence':  words.append(0x0FF0000F)  # fence iorw,iorw
        elif op in ('fence.i','fencei'): words.append(0x0000100F)
        elif op in ('word','.word'):
            words.append(int(p[1],0) & 0xFFFFFFFF)   # raw 32-bit word
        elif op in ('csrrw','csrrs','csrrc'):
            f3={'csrrw':1,'csrrs':2,'csrrc':3}[op]
            words.append((CSR_NUM(p[2])<<20)|(r(p[3])<<15)|(f3<<12)|(r(p[1])<<7)|0x73)
        elif op in ('csrrwi','csrrsi','csrrci'):
            f3={'csrrwi':5,'csrrsi':6,'csrrci':7}[op]
            words.append((CSR_NUM(p[2])<<20)|((int(p[3],0)&0x1F)<<15)|(f3<<12)|(r(p[1])<<7)|0x73)
        else: raise ValueError(f"Unknown op '{op}' at PC=0x{pc:x}")
    return words

if __name__=='__main__':
    if len(sys.argv)<3:
        print(f"Usage: {sys.argv[0]} input.s output.hex"); sys.exit(1)
    src=open(sys.argv[1]).read()
    words=assemble(src)
    with open(sys.argv[2],'w') as f:
        for w in words:
            f.write(f'{w:08x}\n')
    print(f"Assembled {len(words)} instructions -> {sys.argv[2]}")
