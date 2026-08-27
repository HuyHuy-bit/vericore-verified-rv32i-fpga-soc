    addi x1, x0, 4
train:
    addi x1, x1, -1
    bne  x1, x0, train
    .fill 255
    addi x2, x2, 1
    tohost
    halt
