# t20_ras_multi_caller.s — one subroutine, three call sites, called in a loop.
#
# A plain PC-indexed BTB has exactly one entry for the shared `ret`'s
# address, so it can only cache the *last* caller's return address - with
# three call sites round-robining, that entry is wrong roughly 2 times out
# of 3. A RAS instead tracks the actual call chain, so every return lands
# correctly regardless of which site called last. This test checks
# correctness only (final register state, which recovers either way via the
# normal mispredict flush); the measured accuracy/CPI difference (RAS_DEPTH=8
# vs. 0 on this exact program) is in docs/architecture.md.
    addi x14, x0, 5        # loop count
loop:
    jal  ra, sub            # call site A
    addi x10, x10, 1        # only reached if call A returned to the right place
    jal  ra, sub            # call site B
    addi x11, x11, 1        # only reached if call B returned to the right place
    jal  ra, sub            # call site C
    addi x12, x12, 1        # only reached if call C returned to the right place
    addi x14, x14, -1
    bne  x14, x0, loop
    tohost
    halt

sub:
    addi x13, x13, 1        # marker: subroutine body executed
    ret
