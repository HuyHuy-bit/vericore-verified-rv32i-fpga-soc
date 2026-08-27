# t19_dcache_evict.s — force D-cache miss-on-load, dirty lines, and eviction.
# The coverage build is 4KB / 4-way / 4-word blocks = 64 sets, so addresses
# 1024 bytes apart collide in the same set. Touching five of them dirties four
# ways and then evicts one, which is the only way to reach the write-back
# states (IDLE->WB->FILL) and the dirty-evict cross from a directed test.
    addi  x1, x0, 0
    addi  x2, x0, 1024
    addi  x3, x0, 2048
    addi  x4, x0, 3072

    addi  x5, x0, 11
    sw    x5, 0(x1)         # dirty way 0
    addi  x5, x0, 22
    sw    x5, 0(x2)         # dirty way 1
    addi  x5, x0, 33
    sw    x5, 0(x3)         # dirty way 2
    addi  x5, x0, 44
    sw    x5, 0(x4)         # dirty way 3

    lw    x6, 0(x1)         # load hits
    lw    x7, 0(x2)
    lw    x8, 0(x3)
    lw    x9, 0(x4)

    # a fifth line in the same set: forces eviction of a dirty way
    lui   x10, 1            # x10 = 4096
    addi  x11, x0, 55
    sw    x11, 0(x10)       # miss -> evict dirty victim -> WB then FILL
    lw    x12, 0(x10)       # read it back
    lw    x13, 0(x1)        # re-load the evicted line: miss-on-load + refill
    tohost          # signal completion (exit code 1 = pass)
    halt
