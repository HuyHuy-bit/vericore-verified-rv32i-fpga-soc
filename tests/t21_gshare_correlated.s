# t21_gshare_correlated.s — two branches whose directions correlate through
# history, not through either branch's own repetition.
#
# branch1 ("b1") follows a period-4 pattern (T,T,N,N,...) from (x6 mod 4) < 2.
# branch2 ("b2") is taken iff branch1 was taken *one full loop iteration ago*
# (carried in x15, resolved and updated well before b2 is next predicted, so
# this isn't sensitive to exact pipeline depth). In isolation, b2's own
# sequence is just the same period-4 pattern - a lone PC-indexed counter has
# no way to know it's conditioned on b1, so a bimodal predictor and a gshare
# predictor see genuinely different information here. The measured
# accuracy/CPI difference (GSHARE=0 vs. 1 on this exact program) is in
# docs/architecture.md; this test itself only checks correctness
# (final register state) under the default GSHARE=0 build.
    addi x14, x0, 40       # loop count
    addi x6, x0, 0
    addi x15, x0, 0        # last iteration's b1 outcome
loop:
    andi x5, x6, 3
    addi x6, x6, 1
    slti x8, x5, 2         # x8 = 1 for the first half of each period-4 cycle
    beq  x8, x0, b1_nt
    addi x9, x9, 1         # b1 taken
b1_nt:
    beq  x15, x0, b2_nt
    addi x10, x10, 1       # b2 taken
b2_nt:
    add  x15, x0, x8       # remember this iteration's b1 for next iteration's b2
    addi x14, x14, -1
    bne  x14, x0, loop
    tohost
    halt
