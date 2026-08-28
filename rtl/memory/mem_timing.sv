// mem_timing.sv - access-cost model shared by instr_mem and data_mem.
//
// Two costs, matching how real bulk memory behaves:
//   - a fresh access costs LATENCY cycles (row open, round trip, the lot)
//   - the next sequential word, when the requester says it is bursting,
//     costs 1 cycle
//
// The burst discount is what makes a cache block-size sweep mean anything.
// Charge LATENCY per word of a refill and wider blocks always lose, so the
// sweep would "discover" that 1-word blocks are optimal - an artifact of the
// model, not a property of caches. Only a cache asserts burst; a bare CPU
// fetching straight from memory issues independent accesses and pays full
// price for every one.
//
// Timing contract (checked by sim/mem_timing_tb.cpp):
//   a fresh access is !ready for exactly LATENCY-1 cycles, then ready
//   a burst-sequential access is !ready for exactly 1 cycle, then ready
//   an access to the address already served is ready immediately
`default_nettype none

import rv32i_pkg::*;

module mem_timing #(
    parameter int LATENCY = 1
) (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic        req,     // an access is genuinely being presented
    input  var logic        burst,   // requester is walking sequential addresses
    input  var logic [XLEN-1:0] addr,
    output var logic        ready
);
    if (LATENCY <= 1) begin : g_fast
        assign ready = 1'b1;
    end else begin : g_slow
        // Wide enough for LATENCY-2 without pinning the compare to a constant.
        localparam int CW = $clog2(LATENCY + 1);

        logic [CW-1:0] cnt;          // stall cycles elapsed on the current access
        logic [XLEN-1:0] served_addr;
        logic          served;

        // ponytail: re-presenting the address already served is free, which
        // makes this a 1-entry cache. Behind a real cache that path is nearly
        // dead; in front of a bare CPU it only fires on a self-loop. Swap in an
        // explicit req/ack handshake if a measurement ever lands on it.
        logic seq;
        assign seq   = burst && served && (addr == served_addr + XLEN'(4));
        assign ready = !req || (served && (served_addr == addr));

        // served is a register, so it turns ready on the cycle AFTER the last
        // stall cycle. Completing at cnt == LATENCY-2 therefore yields exactly
        // LATENCY-1 stall cycles; a burst word completes at cnt == 0, for 1.
        logic [CW-1:0] target;
        assign target = seq ? CW'(0) : CW'(LATENCY - 2);

        always_ff @(posedge clk) begin
            if (rst) begin
                served      <= 1'b0;
                served_addr <= 32'd0;
                cnt         <= '0;
            end else if (!ready) begin
                if (cnt >= target) begin
                    served      <= 1'b1;
                    served_addr <= addr;
                    cnt         <= '0;
                end else begin
                    cnt <= cnt + CW'(1);
                end
            end
        end
    end
endmodule

`default_nettype wire
