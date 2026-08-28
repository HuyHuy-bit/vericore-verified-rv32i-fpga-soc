`default_nettype none

// forwarding_unit.sv - decides whether the EX stage's rs1/rs2 operands should
// come from the register file (via ID/EX) or be bypassed from a later stage.
module forwarding_unit (
    input  var logic [4:0] rs1_addr_ex,
    input  var logic [4:0] rs2_addr_ex,

    input  var logic [4:0] rd_addr_mem,
    input  var logic       reg_write_en_mem,

    input  var logic [4:0] rd_addr_wb,
    input  var logic       reg_write_en_wb,

    output var logic [1:0] forward_a,   // 00 = no forward, 01 = from EX/MEM, 10 = from MEM/WB
    output var logic [1:0] forward_b
);
    always_comb begin
        // --- operand A (rs1) ---
        if (reg_write_en_mem && (rd_addr_mem != 5'd0) && (rd_addr_mem == rs1_addr_ex))
            forward_a = 2'b01;
        else if (reg_write_en_wb && (rd_addr_wb != 5'd0) && (rd_addr_wb == rs1_addr_ex))
            forward_a = 2'b10;
        else
            forward_a = 2'b00;

        // --- operand B (rs2) ---
        if (reg_write_en_mem && (rd_addr_mem != 5'd0) && (rd_addr_mem == rs2_addr_ex))
            forward_b = 2'b01;
        else if (reg_write_en_wb && (rd_addr_wb != 5'd0) && (rd_addr_wb == rs2_addr_ex))
            forward_b = 2'b10;
        else
            forward_b = 2'b00;
    end
endmodule

`default_nettype wire
