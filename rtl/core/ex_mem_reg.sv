`default_nettype none

import rv32i_pkg::*;

// ex_mem_reg.sv - latches ALU result + store data + control into the MEM stage.
module ex_mem_reg (
    input  var logic    clk,
    input  var logic    rst,
    input  var logic    flush,   // squash the instruction in EX (e.g. trap in MEM)
    input  var logic    freeze,  // hold contents, outranking flush (memory stall)
    input  var ex_mem_t d,
    output var ex_mem_t q
);
    always_ff @(posedge clk) begin
        if (freeze && !rst)    ;          // hold - a memory stall freezes the whole pipe
        else if (rst || flush) q <= '0;
        else                   q <= d;
    end
endmodule

`default_nettype wire
