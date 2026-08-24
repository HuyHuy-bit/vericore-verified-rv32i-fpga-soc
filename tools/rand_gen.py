#!/usr/bin/env python3
"""Random RV32I program generator.

Two modes, deliberately separate:

  default  — straight-line ALU + load/store, checked against the Python model
             in tools/rv32i_model.py (see `gen`). Scope-limited by what that
             model interprets.

  --spike  — emits assembly for the Spike lockstep flow instead (see
             `gen_spike`). Spike is a full ISA implementation, so this mode
             is not limited by the Python model and *does* generate branches
             and jumps: control flow was only ever excluded because the
             reference couldn't follow it, not because it wasn't worth
             testing. Compared retirement-by-retirement rather than on final
             register state, so a wrong value on a wrong path is caught at
             the instruction that produced it.
"""
_ORIGINAL_DOCSTRING = """Random RV32I program generator — straight-line ALU + load/store subset.

Emits raw instruction words directly (no assembler pass) plus a matching
.ref computed by tools/rv32i_model.py, so a generated program plugs straight
into the existing +MEMFILE=/+REFFILE= testbench comparison — no new
comparison logic needed.

Scope, deliberately: no branches/jumps/traps/CSRs (the model doesn't
interpret them; see its docstring), no negative load/store offsets (keeps
both the model's and the RTL's address truncation trivially in agreement).
Biased toward dependency distance 1-2, since that's where forwarding and
load-use bugs live.
"""
import random
import sys

REGS = list(range(1, 11))          # x1..x10: scratch
MEM_WORDS = 64                      # word-addressed scratch region, base 0

R_OPS = [  # (funct3, funct7)
    (0x0, 0x00), (0x0, 0x20), (0x1, 0x00), (0x2, 0x00), (0x3, 0x00),
    (0x4, 0x00), (0x5, 0x00), (0x5, 0x20), (0x6, 0x00), (0x7, 0x00),
]
I_OPS = [0x0, 0x2, 0x3, 0x4, 0x6, 0x7, 0x1, 0x5]  # funct3; shifts handled specially
TOHOST_ONE = [0x00100F93, 0x00010F37, 0xFF0F0F13, 0x01FF2023]


def r_type(rd, rs1, rs2, f3, f7):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | 0x33


def i_type(rd, rs1, imm12, f3, op=0x13):
    return ((imm12 & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def s_type(rs1, rs2, imm12, f3):
    imm12 &= 0xFFF
    return ((imm12 >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm12 & 0x1F) << 7) | 0x23


def lui(rd, imm20):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | 0x37


def b_type(rs1, rs2, off, f3):
    o = off & 0x1FFF
    return (((o >> 12) & 1) << 31) | (((o >> 5) & 0x3F) << 25) | (rs2 << 20) \
        | (rs1 << 15) | (f3 << 12) | (((o >> 1) & 0xF) << 8) | (((o >> 11) & 1) << 7) | 0x63


def j_type(rd, off):
    o = off & 0x1FFFFF
    return (((o >> 20) & 1) << 31) | (((o >> 1) & 0x3FF) << 21) | (((o >> 11) & 1) << 20) \
        | (((o >> 12) & 0xFF) << 12) | (rd << 7) | 0x6F


# The lockstep linker script (compliance/link/spike-lockstep.ld) puts RAM at
# 0x80300000; the RTL's data_mem decodes only low address bits, so that aliases
# back to word 0 of the same array the 0x0-linked flow uses. Held in a register
# because absolute 0(x0) addressing - fine for the RTL - would fault on Spike,
# where low memory simply isn't mapped.
DATA_BASE = 0x80300000
BASE_REG = 31

BR_OPS = [0x0, 0x1, 0x4, 0x5, 0x6, 0x7]   # beq bne blt bge bltu bgeu


def gen_spike(n, seed):
    """Random program with control flow, for the Spike lockstep comparison.

    Branches and jumps are forward-only and bounded, so the program is
    guaranteed to terminate rather than spinning on a random backward edge -
    the generator can pick targets freely precisely because it knows the
    whole layout before it emits anything.
    """
    rnd = random.Random(seed)
    body = []
    recent_rd = []

    def pick_src():
        if recent_rd and rnd.random() < 0.6:
            idx = 0 if (len(recent_rd) == 1 or rnd.random() < 0.7) else 1
            return recent_rd[idx]
        return rnd.choice(REGS)

    for i in range(n):
        room = n - i                     # instructions left after this one
        kinds  = ["r", "i", "load", "store"]
        weights = [30, 30, 12, 12]
        if room > 1:                     # only offer control flow with somewhere to go
            kinds += ["branch", "jal"]
            weights += [12, 4]
        kind = rnd.choices(kinds, weights=weights)[0]
        rd = rnd.choice(REGS)

        if kind == "r":
            f3, f7 = rnd.choice(R_OPS)
            body.append(r_type(rd, pick_src(), pick_src(), f3, f7))
        elif kind == "i":
            rs1 = pick_src()
            f3 = rnd.choice(I_OPS)
            if f3 in (0x1, 0x5):
                shamt = rnd.randint(0, 31)
                f7 = 0x20 if (f3 == 0x5 and rnd.random() < 0.5) else 0x00
                imm = (f7 << 5) | shamt
            else:
                imm = rnd.randint(-2048, 2047)
            body.append(i_type(rd, rs1, imm, f3))
        elif kind == "load":
            off = rnd.randrange(0, MEM_WORDS) * 4
            body.append(i_type(rd, BASE_REG, off, 0x2, op=0x03))
        elif kind == "store":
            off = rnd.randrange(0, MEM_WORDS) * 4
            body.append(s_type(BASE_REG, pick_src(), off, 0x2))
        elif kind == "branch":
            delta = rnd.randint(1, min(4, room))     # forward only, in range
            body.append(b_type(pick_src(), pick_src(), delta * 4, rnd.choice(BR_OPS)))
        else:  # jal, forward, link into a scratch reg
            delta = rnd.randint(1, min(4, room))
            body.append(j_type(rd, delta * 4))

        if kind not in ("store", "branch"):
            recent_rd = [rd] + recent_rd[:1]

    # Prologue. Two jobs, and the second one is not optional:
    #
    #   1. set the data base register (see DATA_BASE above), and
    #   2. initialise every scratch register the body might read.
    #
    # (2) exists because the two machines do NOT start from the same
    # architectural state. Spike enters through a boot ROM at 0x1000 that
    # leaves residue behind - x5 = 0x80000000 from the `lw t0, 24(t0)` it
    # uses to find the entry point, plus a0/a1 - while the RTL comes out of
    # reset with every register zero. A generated program that reads a
    # register before writing it is therefore reading *different values* on
    # the two machines, and diverges for a reason that has nothing to do with
    # the RTL being wrong. Hand-written compliance tests never trip this
    # because they set up their own registers; random code has no such
    # manners. Found the hard way, by exactly this flow.
    prologue = [lui(BASE_REG, DATA_BASE >> 12)]
    for r in REGS:
        prologue.append(i_type(r, 0, rnd.randint(-2048, 2047), 0x0))   # addi rN, x0, k

    return prologue + body + [0x0000006F]


def emit_asm(words, path):
    with open(path, "w") as f:
        f.write("# generated by tools/rand_gen.py --spike - do not edit\n")
        f.write("    .section .text.init,\"ax\",@progbits\n")
        f.write("    .globl rvtest_entry_point\n")
        f.write("rvtest_entry_point:\n")
        for w in words:
            f.write(f"    .word 0x{w:08x}\n")


def gen(n, seed):
    rnd = random.Random(seed)
    words = []
    recent_rd = []  # last few destination registers, for dependency bias

    def pick_src():
        # 60%: reuse a recent destination (distance 1-2), biased toward the
        # most recent. 40%: a fresh random register.
        if recent_rd and rnd.random() < 0.6:
            idx = 0 if (len(recent_rd) == 1 or rnd.random() < 0.7) else 1
            return recent_rd[idx]
        return rnd.choice(REGS)

    for _ in range(n):
        kind = rnd.choices(["r", "i", "load", "store"], weights=[35, 35, 15, 15])[0]
        rd = rnd.choice(REGS)
        if kind == "r":
            rs1, rs2 = pick_src(), pick_src()
            f3, f7 = rnd.choice(R_OPS)
            words.append(r_type(rd, rs1, rs2, f3, f7))
        elif kind == "i":
            rs1 = pick_src()
            f3 = rnd.choice(I_OPS)
            if f3 in (0x1, 0x5):        # SLLI / SRLI / SRAI: shamt in [0,31]
                shamt = rnd.randint(0, 31)
                f7 = 0x20 if (f3 == 0x5 and rnd.random() < 0.5) else 0x00
                imm = (f7 << 5) | shamt
            else:
                imm = rnd.randint(-2048, 2047)
            words.append(i_type(rd, rs1, imm, f3))
        elif kind == "load":
            off = rnd.randrange(0, MEM_WORDS) * 4
            words.append(i_type(rd, 0, off, 0x2, op=0x03))  # lw rd, off(x0)
        else:  # store
            off = rnd.randrange(0, MEM_WORDS) * 4
            rs2 = pick_src()
            words.append(s_type(0, rs2, off, 0x2))          # sw rs2, off(x0)

        if kind != "store":
            recent_rd = [rd] + recent_rd[:1]

    # Architectural completion for the directed/random harness. The following
    # self-loop is unreachable in RTL after the committed tohost write, but it
    # remains a useful fallback terminator for the straight-line Python model.
    words.extend(TOHOST_ONE)
    words.append(0x0000006F)
    return words


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=40, help="instruction count (excluding halt)")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--spike", metavar="ASMFILE",
                    help="emit assembly for the Spike lockstep flow (control flow "
                         "enabled, no Python-model .ref written)")
    ap.add_argument("hexfile", nargs="?")
    ap.add_argument("reffile", nargs="?")
    args = ap.parse_args()

    if args.spike:
        words = gen_spike(args.n, args.seed)
        emit_asm(words, args.spike)
        print(f"seed={args.seed} n={args.n} -> {args.spike}", file=sys.stderr)
        sys.exit(0)

    if not (args.hexfile and args.reffile):
        ap.error("hexfile and reffile are required unless --spike is given")

    words = gen(args.n, args.seed)
    with open(args.hexfile, "w") as f:
        for w in words:
            f.write(f"{w:08x}\n")

    sys.path.insert(0, sys.path[0])
    from rv32i_model import run
    regs = run(words, mem_words=MEM_WORDS)
    with open(args.reffile, "w") as f:
        f.write(f"cycles={args.n * 4 + 50}\n")
        for i in range(1, 32):
            if regs[i]:
                f.write(f"x{i}=0x{regs[i]:x}\n")

    print(f"seed={args.seed} n={args.n} -> {args.hexfile}", file=sys.stderr)
