`default_nettype none

import rv32i_pkg::*;

module reg_file (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic [4:0]  rs1_addr,     // source register 1 number
    input  var logic [4:0]  rs2_addr,     // source register 2 number
    input  var logic [4:0]  rd_addr,      // destination register number
    input  var logic [XLEN-1:0] rd_data,      // data to write to rd
    input  var logic        rd_write_en,  // write enable
    output var logic [XLEN-1:0] rs1_data,     // value read from rs1
    output var logic [XLEN-1:0] rs2_data      // value read from rs2
);
    // 32 entries is the RV32I/RV64I register count, not the data width.
    logic [XLEN-1:0] reg_array [0:31];

    // Read-during-write bypass: if WB is writing rd this exact cycle and ID
    // is reading that same register this exact cycle, forward the incoming
    // write data instead of the (stale, about-to-be-overwritten) array value.
    // Without this, an instruction whose producer is exactly 3 instructions
    // earlier reads garbage - the write and the read race on the same edge,
    // and combinational read-before-write loses that race.
    assign rs1_data = (rs1_addr == 5'd0) ? XLEN'(0)
                     : (rd_write_en && rd_addr != 5'd0 && rd_addr == rs1_addr) ? rd_data
                     : reg_array[rs1_addr];
    assign rs2_data = (rs2_addr == 5'd0) ? XLEN'(0)
                     : (rd_write_en && rd_addr != 5'd0 && rd_addr == rs2_addr) ? rd_data
                     : reg_array[rs2_addr];

    // Debug taps removed — the testbench reads all 32 registers directly via
    // the simulator's hierarchical root (sim/cpu_tb.cpp), so these ports were
    // dead weight left over from the single-cycle predecessor.
    always_ff @(posedge clk) begin
        if (rst) begin
            for (int i = 0; i < 32; i++) begin
                reg_array[i] <= XLEN'(0);
            end
        end else if (rd_write_en && rd_addr != 5'd0) begin
            reg_array[rd_addr] <= rd_data;
        end
    end

`ifndef SYNTHESIS
    // x0 is hardwired to zero; the write path above already guards on
    // rd_addr != 0, so this checks the guard actually holds rather than the
    // (weaker, and sometimes-true) claim that rd_write_en never fires at
    // rd_addr==0 — a NOP encoded as "addi x0, x0, 0" does exactly that.
    a_x0_never_written: assert property (@(posedge clk) disable iff (rst)
        $stable(reg_array[0]));
`endif
endmodule

`default_nettype wire
