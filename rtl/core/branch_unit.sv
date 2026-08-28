`default_nettype none

import rv32i_pkg::*;

module branch_unit (
    input var logic [XLEN-1:0] rs1,
    input var logic [XLEN-1:0] rs2,
    input var logic [2:0] funct3,
    input var logic branch,
    output var logic pc_sel
);
    logic branch_taken;
    always_comb begin
        case (funct3)
            F3_BEQ:  branch_taken = (rs1 == rs2);
            F3_BNE:  branch_taken = (rs1 != rs2);
            F3_BLT:  branch_taken = ($signed(rs1) < $signed(rs2));
            F3_BGE:  branch_taken = ($signed(rs1) >= $signed(rs2));
            F3_BLTU: branch_taken = (rs1 < rs2);
            F3_BGEU: branch_taken = (rs1 >= rs2);
            default: branch_taken = 1'b0; // FENCE, or any other funct3 reaching here
        endcase
    end
    assign pc_sel = branch & branch_taken;
endmodule

`default_nettype wire
