`default_nettype none

import rv32i_pkg::*;

// if_id_reg.sv - latches fetched instruction + PC into the ID stage.
module if_id_reg (
    input  var logic    clk,
    input  var logic    rst,
    input  var logic    flush,   // squash on taken branch/jump (control hazard)
    input  var logic    stall,   // hold contents (load-use hazard)
    input  var logic    freeze,  // hold contents, outranking flush (memory stall)
    input  var if_id_t  d,
    output var if_id_t  q
);
    // Priority: rst > freeze > flush > stall. freeze has to outrank flush,
    // unlike stall: a load-use stall coinciding with a mispredict must let the
    // flush win (the held instruction is wrong-path), but a memory stall means
    // the clock may as well not have ticked - every register holds, and the
    // flush is still there to act on once the memory answers.
    //
    // Clearing to '0 also clears q.instr, and an all-zero instruction word is
    // an illegal opcode, which control.sv decodes to no register/memory writes
    // - so a flushed slot is architecturally inert as well as invalid.
    always_ff @(posedge clk) begin
        if (freeze && !rst)    ;          // hold
        else if (rst || flush) q <= '0;
        else if (!stall)       q <= d;
    end
endmodule

`default_nettype wire
