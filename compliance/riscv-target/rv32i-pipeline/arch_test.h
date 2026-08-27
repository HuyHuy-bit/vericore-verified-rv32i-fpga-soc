#ifndef RV32I_PIPELINE_ARCH_TEST_H
#define RV32I_PIPELINE_ARCH_TEST_H

#include_next "arch_test.h"

#undef LA
#ifdef RVTEST_FIXED_LEN
#define LA(reg, val) \
    .option push; \
    .option norvc; \
    .align UNROLLSZ; \
    lla reg, val; \
    .align UNROLLSZ; \
    .option pop;
#else
#define LA(reg, val) \
    .option push; \
    .option norvc; \
    lla reg, val; \
    .option pop;
#endif

#endif
