`default_nettype none

import rv32i_pkg::*;

// mem_wb_reg.sv - latches the write-back value + destination into WB.
// No flush port: MEM is the commit point, so nothing downstream of it is ever
// speculative. An instruction that reaches here retires.
module mem_wb_reg (
    input  var logic    clk,
    input  var logic    rst,
    input  var logic    freeze,  // hold contents (memory stall)
    input  var mem_wb_t d,
    output var mem_wb_t q
);
    always_ff @(posedge clk) begin
        if (rst)          q <= '0;
        else if (!freeze) q <= d;
    end
endmodule

`default_nettype wire
