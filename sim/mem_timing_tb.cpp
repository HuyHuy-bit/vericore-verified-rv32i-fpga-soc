// mem_timing_tb.cpp - asserts the access-cost contract in rtl/memory/mem_timing.sv.
//
// Built with LATENCY=10. The LATENCY<=1 branch is `assign ready = 1'b1` and is
// covered by the full CPU suite, which produces identical cycle counts with the
// model present and absent. This checks the part that can actually be wrong:
// the off-by-ones in the countdown, which would silently bias every CPI number
// the project reports rather than failing anything outright.
#include "Vmem_timing.h"
#include "verilated.h"
#include <cstdio>
#include <memory>

static const int LATENCY = 10;

static int failures = 0;

static void check(const char* what, int got, int want) {
    bool ok = (got == want);
    if (!ok) failures++;
    std::printf("  %-52s got %2d want %2d  %s\n", what, got, want, ok ? "ok" : "FAIL");
}

int main(int argc, char** argv) {
    const std::unique_ptr<VerilatedContext> ctx{new VerilatedContext};
    ctx->commandArgs(argc, argv);
    const std::unique_ptr<Vmem_timing> dut{new Vmem_timing{ctx.get()}};

    auto tick = [&]() {
        dut->clk = 1; dut->eval();
        dut->clk = 0; dut->eval();
    };

    dut->clk = 0; dut->rst = 1; dut->req = 0; dut->burst = 0; dut->addr = 0;
    tick();
    dut->rst = 0;

    // Present an access and count the cycles it is not ready, then burn the
    // cycle on which the requester consumes the data.
    auto access = [&](uint32_t addr, bool burst) {
        int stalls = 0;
        dut->req = 1; dut->burst = burst ? 1 : 0; dut->addr = addr;
        for (;;) {
            dut->eval();
            if (dut->ready) break;
            stalls++;
            tick();
        }
        tick();
        return stalls;
    };

    std::printf("mem_timing contract (LATENCY=%d):\n", LATENCY);

    check("fresh access costs LATENCY-1 stall cycles",
          access(0x1000, false), LATENCY - 1);

    check("same address again is free",
          access(0x1000, false), 0);

    check("next word without burst pays full price",
          access(0x1004, false), LATENCY - 1);

    check("next word with burst costs 1 stall cycle",
          access(0x1008, true), 1);
    check("burst continues at 1 stall cycle",
          access(0x100C, true), 1);

    check("burst that is not sequential pays full price",
          access(0x9000, true), LATENCY - 1);

    check("burst resumes at 1 after re-anchoring",
          access(0x9004, true), 1);

    // req low means no access is being presented, so nothing should ever stall.
    dut->req = 0; dut->burst = 0; dut->addr = 0xDEAD0000;
    dut->eval();
    check("no request is always ready", dut->ready ? 1 : 0, 1);

    std::printf(failures ? "mem_timing: FAIL\n" : "mem_timing: PASS\n");
    return failures ? 1 : 0;
}
