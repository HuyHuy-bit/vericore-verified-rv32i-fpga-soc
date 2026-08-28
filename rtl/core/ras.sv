`default_nettype none

import rv32i_pkg::*;

// ras.sv - return-address stack: a small LIFO predicting JALR-return targets.
//
// A BTB indexes purely by PC, so every call site into the same function
// shares one BTB entry for that function's `ret` - the entry can only ever
// hold the *last* caller's return address, so a function called from more
// than one place mispredicts every return but the most recent one. A RAS
// sidesteps this: a call's return address is known unconditionally at fetch
// time (no prediction needed, it's just pc+4), so pushing it and popping it
// on the matching return gives the *actual* address regardless of how many
// call sites share that `ret`.
//
// Speculative and unrepaired: push/pop happen at fetch time, before the
// pipeline knows whether this fetch is even on the correct path, and a
// flush does not roll the stack back. This can corrupt the stack after a
// misprediction - accepted for the same reason the BTB itself is a simple,
// uncheckpointed structure (see docs/MICROARCHITECTURE.md). A wrong pop is
// still just a misprediction, caught and corrected the normal way at EX.
module ras #(
    parameter int DEPTH = 8
) (
    input  var logic        clk,
    input  var logic        rst,

    input  var logic        push_en,
    input  var logic [XLEN-1:0] push_addr,

    input  var logic        pop_en,
    output var logic        pop_valid,     // 0 => stack empty, no prediction
    output var logic [XLEN-1:0] pop_addr
);
    localparam int PTRW = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int CNTW = $clog2(DEPTH + 1);

    logic [XLEN-1:0] stack [DEPTH];
    logic [PTRW-1:0] sp;              // next free slot to write
    logic [CNTW-1:0] count;           // valid entries, 0..DEPTH

    // Most-recently-pushed entry, read combinationally (same timing as the
    // BTB's own combinational read - both act on this cycle's fetch PC).
    logic [PTRW-1:0] top_idx;
    assign top_idx   = (sp == '0) ? PTRW'(DEPTH - 1) : (sp - PTRW'(1));
    assign pop_valid = pop_en && (count != '0);
    assign pop_addr  = stack[top_idx];

    always_ff @(posedge clk) begin
        if (rst) begin
            sp    <= '0;
            count <= '0;
        end else if (push_en && pop_en) begin
            // "call through a link register" (rd != rs1, both link regs):
            // this cycle's prediction already used pop_addr/top_idx above;
            // the new return address replaces that same slot in place, so
            // depth doesn't change.
            stack[top_idx] <= push_addr;
        end else if (push_en) begin
            stack[sp] <= push_addr;
            sp        <= sp + PTRW'(1);   // wraps on overflow: see below
            if (count != CNTW'(DEPTH)) count <= count + CNTW'(1);
        end else if (pop_en && count != '0) begin
            sp    <= top_idx;
            count <= count - CNTW'(1);
        end
    end

    // Overflow (call depth > DEPTH) isn't guarded against: sp wraps and the
    // oldest entry is silently overwritten. The returns for calls deeper
    // than DEPTH just get whatever stale address now occupies that slot -
    // a misprediction, not a hang, and self-corrects the normal way. This
    // is the standard, accepted RAS overflow behavior in real cores too.
endmodule

`default_nettype wire
