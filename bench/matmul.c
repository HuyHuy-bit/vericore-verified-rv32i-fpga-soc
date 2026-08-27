/* matmul.c - 16x16 unsigned integer matrix multiply.
 *
 * Two things at once: strided access over three 1KB arrays (row-major reads
 * of `a` are sequential, column-major reads of `b` are not), and 4096 calls
 * into the software __mulsi3, because rv32i has no hardware multiply. When the
 * M extension lands, the second half of that cost disappears.
 *
 * Note: no const/global initialised data anywhere in these kernels. .rodata
 * is linked into instr_mem, but loads read data_mem - a const table would
 * silently read garbage on this Harvard split. Everything is generated at
 * runtime into .bss instead.
 */
#define N 16

static unsigned a[N][N], b[N][N], c[N][N];

/* xorshift32: fills without multiplying, so the init loop doesn't drown the
 * kernel it's setting up in soft-multiply cycles. */
static unsigned rnd(unsigned *s) {
    unsigned x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

unsigned bench(void) {
    unsigned seed = 0x1234567u, i, j, k, sum = 0;

    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            a[i][j] = rnd(&seed) >> 20;
            b[i][j] = rnd(&seed) >> 20;
        }

    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned s = 0;
            for (k = 0; k < N; k++)
                s += a[i][k] * b[k][j];
            c[i][j] = s;
        }

    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++)
            sum = sum * 31u + c[i][j];

    return sum;
}
