# t22_fencei.s — FENCE.I decodes, invalidates the I-cache, and refetches.
#
# What this can and cannot prove, stated plainly: this core has *separate*
# instruction and data memories (instr_mem.sv and data_mem.sv are distinct
# arrays), so a store can never reach code space and self-modifying code is
# not expressible here at all - with or without FENCE.I. So this test does
# not, and cannot, demonstrate a store becoming visible to fetch.
#
# What it does check is the part that is real: FENCE.I is decoded (not
# treated as illegal), it commits, and the pc+4 refetch redirect lands on the
# right instruction. That redirect is the risky half of the implementation -
# it flushes the pipeline exactly like a trap, so getting the target wrong
# would send execution off the rails rather than fail quietly. The I-cache
# invalidation itself is verified separately, by watching the miss counter
# jump when a FENCE.I runs inside a loop (see docs/architecture.md).
    addi x10, x0, 1        # marker: reached before the fence
    fence.i
    addi x11, x0, 2        # only reached if the pc+4 redirect landed right
    fence.i
    fence.i                # back-to-back: each must redirect independently
    addi x12, x0, 3

    addi x14, x0, 4        # a short loop with a fence.i in the body, so the
loop:                      # invalidate/refill path runs repeatedly rather
    fence.i                # than once from a cold cache
    addi x13, x13, 1
    addi x14, x14, -1
    bne  x14, x0, loop

    tohost
    halt
