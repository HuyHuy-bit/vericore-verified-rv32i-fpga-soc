/* interp.c - tiny stack-machine interpreter.
 *
 * Exists because the other four kernels all have inner loops of a few dozen
 * instructions, so any I-cache at all holds them and the capacity axis of a
 * sweep comes out perfectly flat. An interpreter is the classic shape that
 * defeats that: a dispatch chain plus ~20 opcode handlers, executed in an
 * order the program data decides, so the instruction working set is the whole
 * body rather than one hot loop.
 *
 * The dispatch is a switch compiled with -fno-jump-tables. A jump table would
 * land in .rodata, which on this Harvard split lives in instr_mem where loads
 * cannot reach it; run_bench.sh fails the build if any .rodata survives.
 *
 * The stack pointer is masked rather than bounds-checked, so every possible
 * byte sequence is a valid program and the generator needs no validity rules.
 */
#define PROG_LEN 512
#define STACK_SZ 64
#define SP_MASK  (STACK_SZ - 1)
#define ITERS    100

static unsigned char prog[PROG_LEN];
static unsigned      stk[STACK_SZ];

unsigned bench(void) {
    unsigned seed = 0x5EED1234u, i, r;
    unsigned sp = 0, pc, acc = 0;

    for (i = 0; i < PROG_LEN; i++) {
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        /* Reduce to an opcode here, not in the dispatch loop: rv32i has no
         * hardware divide, so a % in the hot path would measure the software
         * modulo routine instead of the interpreter. */
        prog[i] = (unsigned char)((seed >> 8) % 20u);
    }
    for (i = 0; i < STACK_SZ; i++)
        stk[i] = i * 2654435761u;

    for (r = 0; r < ITERS; r++) {
        for (pc = 0; pc < PROG_LEN; pc++) {
            unsigned a = stk[sp & SP_MASK];
            unsigned b = stk[(sp - 1) & SP_MASK];

            switch (prog[pc]) {
            case 0:  stk[(sp + 1) & SP_MASK] = prog[pc]; sp++;          break;
            case 1:  stk[(sp + 1) & SP_MASK] = a;        sp++;          break;
            case 2:  stk[sp & SP_MASK] = b; stk[(sp - 1) & SP_MASK] = a; break;
            case 3:  sp--;                                              break;
            case 4:  stk[(sp - 1) & SP_MASK] = a + b;    sp--;          break;
            case 5:  stk[(sp - 1) & SP_MASK] = a - b;    sp--;          break;
            case 6:  stk[(sp - 1) & SP_MASK] = a ^ b;    sp--;          break;
            case 7:  stk[(sp - 1) & SP_MASK] = a & b;    sp--;          break;
            case 8:  stk[(sp - 1) & SP_MASK] = a | b;    sp--;          break;
            case 9:  stk[sp & SP_MASK] = a << (b & 31u);                break;
            case 10: stk[sp & SP_MASK] = a >> (b & 31u);                break;
            case 11: stk[sp & SP_MASK] = (a << 7) | (a >> 25);          break;
            case 12: stk[sp & SP_MASK] = 0u - a;                        break;
            case 13: stk[sp & SP_MASK] = ~a;                            break;
            case 14: stk[sp & SP_MASK] = a + 1u;                        break;
            case 15: stk[sp & SP_MASK] = a - 1u;                        break;
            case 16: stk[sp & SP_MASK] = (a < b) ? a : b;               break;
            case 17: stk[sp & SP_MASK] = (a < b) ? b : a;               break;
            case 18: acc += a;                                          break;
            default: acc ^= (a + b);                                    break;
            }
        }
    }

    for (i = 0; i < STACK_SZ; i++)
        acc = acc * 31u + stk[i];
    return acc;
}
