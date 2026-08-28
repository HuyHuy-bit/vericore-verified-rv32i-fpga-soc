// imm_gen.sv - extracts and sign-extends the immediate for each format.
`default_nettype none

import rv32i_pkg::*;

module imm_gen (
    input  var logic [ILEN-1:0] instr,   // the full instruction word (always 32-bit)
    output var logic [XLEN-1:0] imm      // sign-extended to the datapath width
);
    logic [6:0] opcode;
    assign opcode = instr[6:0];

    always_comb begin
        case (opcode)
            // Each immediate is assembled at its natural width, then sign-
            // extended to XLEN by the signed cast. Writing the extension as
            // {{20{instr[31]}}, ...} would hardcode a 32-bit result and
            // silently produce a wrong-width immediate at any other XLEN.
            OPCODE_I_TYPE, OPCODE_LOAD, OPCODE_JALR:
                imm = XLEN'($signed(instr[31:20]));                                     // I-type
            OPCODE_STORE:
                imm = XLEN'($signed({instr[31:25], instr[11:7]}));                      // S-type
            OPCODE_BRANCH:
                imm = XLEN'($signed({instr[31], instr[7], instr[30:25], instr[11:8], 1'b0}));
            OPCODE_LUI, OPCODE_AUIPC:
                imm = XLEN'($signed({instr[31:12], 12'b0}));                            // U-type
            OPCODE_JAL:
                imm = XLEN'($signed({instr[31], instr[19:12], instr[20], instr[30:21], 1'b0}));
            default:
                imm = XLEN'(0);
        endcase
    end
endmodule

`default_nettype wire
