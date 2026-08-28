`default_nettype none

import rv32i_pkg::*;

// id_ex_reg.sv - latches decoded operands + control into the EX stage.
module id_ex_reg (
    input  var logic   clk,
    input  var logic   rst,
    input  var logic   flush,   // bubble insert (mispredict, load-use, or trap)
    input  var logic   freeze,  // hold contents, outranking flush (memory stall)
    input  var id_ex_t d,
    output var id_ex_t q
);
    // Clearing to '0 zeroes every control field, which is what makes a flushed
    // slot an architectural NOP: no register write, no memory access, no
    // branch.
    always_ff @(posedge clk) begin
        if (freeze && !rst)    ;          // hold - a memory stall freezes the whole pipe
        else if (rst || flush) q <= '0;
        else                   q <= d;
    end
endmodule

`default_nettype wire
