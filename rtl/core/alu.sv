// alu.sv - arithmetic/logic unit. The op selector comes from control.sv.
`default_nettype none

import rv32i_pkg::*;

module alu (
    input  var logic [XLEN-1:0] a,       // first operand
    input  var logic [XLEN-1:0] b,       // second operand (register OR immediate)
    input  var logic [3:0]  alu_op,  // operation selector
    output var logic [XLEN-1:0] result   // result of the operation
);
    // The 'zero' output was removed - it was never consumed. All branch
    // decisions are made by branch_unit.sv from the raw operands, not from
    // an ALU zero flag, so this port was dead weight.
    // Shift amount is log2(XLEN) bits: 5 for RV32, 6 for RV64. Hardcoding
    // [4:0] would silently truncate every shift above 31 at XLEN=64.
    localparam int SHAMTW = $clog2(XLEN);
    logic [SHAMTW-1:0] shamt;
    assign shamt = b[SHAMTW-1:0];

    always_comb begin
        case (alu_op)
            ALU_OP_ADD:   result = a + b;
            ALU_OP_SUB:   result = a - b;
            ALU_OP_AND:   result = a & b;
            ALU_OP_OR:    result = a | b;
            ALU_OP_XOR:   result = a ^ b;
            ALU_OP_SLT:   result = ($signed(a)   < $signed(b))   ? XLEN'(1) : XLEN'(0);
            ALU_OP_SLTU:  result = ($unsigned(a) < $unsigned(b)) ? XLEN'(1) : XLEN'(0);
            ALU_OP_SLL:   result = a << shamt;
            ALU_OP_SRL:   result = a >> shamt;
            ALU_OP_SRA:   result = $signed(a) >>> shamt;
            ALU_OP_PASSB: result = b;                            // LUI
            default:      result = XLEN'(0);
        endcase
    end
endmodule

`default_nettype wire
