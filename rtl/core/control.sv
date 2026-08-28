// control.sv - authoritative full-instruction decode.
`default_nettype none

import rv32i_pkg::*;

module control (
    input  var logic [ILEN-1:0] instr,
    output var logic            reg_write_en,
    output var logic            alu_src,
    output var logic            mem_write,
    output var logic            mem_read,
    output var logic            branch,
    output var logic [3:0]      alu_op,
    output var logic [1:0]      pc_src,
    output var logic [1:0]      wb_src,
    output var logic            alu_a_src,
    output var logic            is_csr,
    output var logic            is_system,
    output var logic            is_fencei,
    output var logic            illegal,
    output var logic            uses_rs1,
    output var logic            uses_rs2
);
    logic [6:0] opcode;
    logic [2:0] funct3;
    logic [6:0] funct7;

    assign opcode = instr[6:0];
    assign funct3 = instr[14:12];
    assign funct7 = instr[31:25];

    always_comb begin
        // An unrecognized encoding is a valid pipeline entry with no action.
        // The backend carries it to the precise illegal-instruction trap.
        reg_write_en = 1'b0;
        alu_src      = 1'b0;
        mem_write    = 1'b0;
        mem_read     = 1'b0;
        branch       = 1'b0;
        alu_op       = ALU_OP_ADD;
        pc_src       = PC_SRC_SEQ;
        wb_src       = WB_SRC_ALU;
        alu_a_src    = 1'b0;
        is_csr       = 1'b0;
        is_system    = 1'b0;
        is_fencei    = 1'b0;
        illegal      = 1'b1;
        uses_rs1     = 1'b0;
        uses_rs2     = 1'b0;

        case (opcode)
            OPCODE_R_TYPE: begin
                case ({funct7, funct3})
                    10'b0000000_000: begin illegal = 1'b0; alu_op = ALU_OP_ADD;  end
                    10'b0100000_000: begin illegal = 1'b0; alu_op = ALU_OP_SUB;  end
                    10'b0000000_001: begin illegal = 1'b0; alu_op = ALU_OP_SLL;  end
                    10'b0000000_010: begin illegal = 1'b0; alu_op = ALU_OP_SLT;  end
                    10'b0000000_011: begin illegal = 1'b0; alu_op = ALU_OP_SLTU; end
                    10'b0000000_100: begin illegal = 1'b0; alu_op = ALU_OP_XOR;  end
                    10'b0000000_101: begin illegal = 1'b0; alu_op = ALU_OP_SRL;  end
                    10'b0100000_101: begin illegal = 1'b0; alu_op = ALU_OP_SRA;  end
                    10'b0000000_110: begin illegal = 1'b0; alu_op = ALU_OP_OR;   end
                    10'b0000000_111: begin illegal = 1'b0; alu_op = ALU_OP_AND;  end
                    default: ;
                endcase
                if (!illegal) begin
                    reg_write_en = 1'b1;
                    uses_rs1     = 1'b1;
                    uses_rs2     = 1'b1;
                end
            end

            OPCODE_I_TYPE: begin
                case (funct3)
                    3'b000: begin illegal = 1'b0; alu_op = ALU_OP_ADD;  end
                    3'b010: begin illegal = 1'b0; alu_op = ALU_OP_SLT;  end
                    3'b011: begin illegal = 1'b0; alu_op = ALU_OP_SLTU; end
                    3'b100: begin illegal = 1'b0; alu_op = ALU_OP_XOR;  end
                    3'b110: begin illegal = 1'b0; alu_op = ALU_OP_OR;   end
                    3'b111: begin illegal = 1'b0; alu_op = ALU_OP_AND;  end
                    3'b001: begin
                        if (funct7 == 7'b0000000) begin
                            illegal = 1'b0;
                            alu_op  = ALU_OP_SLL;
                        end
                    end
                    3'b101: begin
                        case (funct7)
                            7'b0000000: begin illegal = 1'b0; alu_op = ALU_OP_SRL; end
                            7'b0100000: begin illegal = 1'b0; alu_op = ALU_OP_SRA; end
                            default: ;
                        endcase
                    end
                    default: ;
                endcase
                if (!illegal) begin
                    reg_write_en = 1'b1;
                    alu_src      = 1'b1;
                    uses_rs1     = 1'b1;
                end
            end

            OPCODE_LOAD: begin
                case (funct3)
                    F3_LB, F3_LH, F3_LW, F3_LBU, F3_LHU: illegal = 1'b0;
                    default: ;
                endcase
                if (!illegal) begin
                    reg_write_en = 1'b1;
                    alu_src      = 1'b1;
                    mem_read     = 1'b1;
                    wb_src       = WB_SRC_MEM;
                    uses_rs1     = 1'b1;
                end
            end

            OPCODE_STORE: begin
                case (funct3)
                    3'b000, 3'b001, 3'b010: illegal = 1'b0;
                    default: ;
                endcase
                if (!illegal) begin
                    alu_src   = 1'b1;
                    mem_write = 1'b1;
                    uses_rs1  = 1'b1;
                    uses_rs2  = 1'b1;
                end
            end

            OPCODE_BRANCH: begin
                case (funct3)
                    F3_BEQ, F3_BNE, F3_BLT, F3_BGE, F3_BLTU, F3_BGEU:
                        illegal = 1'b0;
                    default: ;
                endcase
                if (!illegal) begin
                    branch   = 1'b1;
                    alu_op   = ALU_OP_SUB;
                    pc_src   = PC_SRC_BRANCH;
                    uses_rs1 = 1'b1;
                    uses_rs2 = 1'b1;
                end
            end

            OPCODE_JAL: begin
                illegal      = 1'b0;
                reg_write_en = 1'b1;
                pc_src       = PC_SRC_JAL;
                wb_src       = WB_SRC_PC4;
            end

            OPCODE_JALR: begin
                if (funct3 == 3'b000) begin
                    illegal      = 1'b0;
                    reg_write_en = 1'b1;
                    alu_src      = 1'b1;
                    pc_src       = PC_SRC_JALR;
                    wb_src       = WB_SRC_PC4;
                    uses_rs1     = 1'b1;
                end
            end

            OPCODE_LUI: begin
                illegal      = 1'b0;
                reg_write_en = 1'b1;
                alu_src      = 1'b1;
                alu_op       = ALU_OP_PASSB;
            end

            OPCODE_AUIPC: begin
                illegal      = 1'b0;
                reg_write_en = 1'b1;
                alu_src      = 1'b1;
                alu_a_src    = 1'b1;
            end

            OPCODE_FENCE: begin
                case (funct3)
                    3'b000: illegal = 1'b0;
                    F3_FENCEI: begin
                        illegal   = 1'b0;
                        is_fencei = 1'b1;
                    end
                    default: ;
                endcase
            end

            OPCODE_SYSTEM: begin
                case (funct3)
                    F3_PRIV: begin
                        case (instr)
                            INSTR_ECALL, INSTR_EBREAK, INSTR_MRET: begin
                                illegal   = 1'b0;
                                is_system = 1'b1;
                            end
                            default: ;
                        endcase
                    end
                    F3_CSRRW, F3_CSRRS, F3_CSRRC: begin
                        illegal      = 1'b0;
                        reg_write_en = 1'b1;
                        wb_src       = WB_SRC_CSR;
                        is_csr       = 1'b1;
                        uses_rs1     = 1'b1;
                    end
                    F3_CSRRWI, F3_CSRRSI, F3_CSRRCI: begin
                        illegal      = 1'b0;
                        reg_write_en = 1'b1;
                        wb_src       = WB_SRC_CSR;
                        is_csr       = 1'b1;
                    end
                    default: ;
                endcase
            end

            default: ;
        endcase
    end
endmodule

`default_nettype wire
