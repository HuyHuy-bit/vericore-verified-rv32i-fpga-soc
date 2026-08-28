`default_nettype none

import rv32i_pkg::*;

module control_tb;
    logic [ILEN-1:0] instr;
    logic            reg_write_en;
    logic            alu_src;
    logic            mem_write;
    logic            mem_read;
    logic            branch;
    logic [3:0]      alu_op;
    logic [1:0]      pc_src;
    logic [1:0]      wb_src;
    logic            alu_a_src;
    logic            is_csr;
    logic            is_system;
    logic            is_fencei;
    logic            illegal;
    logic            uses_rs1;
    logic            uses_rs2;

    int unsigned checks;
    int unsigned failures;

    control dut (
        .instr(instr),
        .reg_write_en(reg_write_en),
        .alu_src(alu_src),
        .mem_write(mem_write),
        .mem_read(mem_read),
        .branch(branch),
        .alu_op(alu_op),
        .pc_src(pc_src),
        .wb_src(wb_src),
        .alu_a_src(alu_a_src),
        .is_csr(is_csr),
        .is_system(is_system),
        .is_fencei(is_fencei),
        .illegal(illegal),
        .uses_rs1(uses_rs1),
        .uses_rs2(uses_rs2)
    );

    task automatic check_outputs(
        input string           label,
        input logic [ILEN-1:0] word,
        input logic            want_illegal,
        input logic            want_uses_rs1,
        input logic            want_uses_rs2,
        input logic            want_reg_write_en,
        input logic            want_alu_src,
        input logic            want_mem_write,
        input logic            want_mem_read,
        input logic            want_branch,
        input logic [3:0]      want_alu_op,
        input logic [1:0]      want_pc_src,
        input logic [1:0]      want_wb_src,
        input logic            want_alu_a_src,
        input logic            want_is_csr,
        input logic            want_is_system,
        input logic            want_is_fencei
    );
        logic [19:0] got;
        logic [19:0] want;
        begin
            instr = word;
            #1;
            checks++;
            got = {
                illegal, uses_rs1, uses_rs2, reg_write_en, alu_src,
                mem_write, mem_read, branch, alu_op, pc_src, wb_src,
                alu_a_src, is_csr, is_system, is_fencei
            };
            want = {
                want_illegal, want_uses_rs1, want_uses_rs2,
                want_reg_write_en, want_alu_src, want_mem_write,
                want_mem_read, want_branch, want_alu_op, want_pc_src,
                want_wb_src, want_alu_a_src, want_is_csr,
                want_is_system, want_is_fencei
            };
            if (got !== want) begin
                failures++;
                $display("FAIL %-32s instr=%08x got=%05x want=%05x",
                         label, word, got, want);
            end
        end
    endtask

    task automatic check_illegal(
        input string           label,
        input logic [ILEN-1:0] word
    );
        begin
            check_outputs(label, word,
                          1'b1, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_op(
        input string           label,
        input logic [ILEN-1:0] word,
        input logic [3:0]      want_alu_op
    );
        begin
            check_outputs(label, word,
                          1'b0, 1'b1, 1'b1,
                          1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                          want_alu_op, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_op_imm(
        input string           label,
        input logic [ILEN-1:0] word,
        input logic [3:0]      want_alu_op
    );
        begin
            check_outputs(label, word,
                          1'b0, 1'b1, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                          want_alu_op, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_load(
        input string           label,
        input logic [ILEN-1:0] word
    );
        begin
            check_outputs(label, word,
                          1'b0, 1'b1, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b1, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_MEM,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_store(
        input string           label,
        input logic [ILEN-1:0] word
    );
        begin
            check_outputs(label, word,
                          1'b0, 1'b1, 1'b1,
                          1'b0, 1'b1, 1'b1, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_branch(
        input string           label,
        input logic [ILEN-1:0] word
    );
        begin
            check_outputs(label, word,
                          1'b0, 1'b1, 1'b1,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b1,
                          ALU_OP_SUB, PC_SRC_BRANCH, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic check_csr(
        input string           label,
        input logic [ILEN-1:0] word,
        input logic            want_uses_rs1
    );
        begin
            check_outputs(label, word,
                          1'b0, want_uses_rs1, 1'b0,
                          1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_CSR,
                          1'b0, 1'b1, 1'b0, 1'b0);
        end
    endtask

    task automatic test_op;
        logic [6:0] f7;
        logic [2:0] f3;
        logic [31:0] word;
        begin
            for (int unsigned funct3 = 0; funct3 < 8; funct3++) begin
                for (int unsigned funct7 = 0; funct7 < 128; funct7++) begin
                    f3 = 3'(funct3);
                    f7 = 7'(funct7);
                    word = {f7, 5'd3, 5'd2, f3, 5'd1, OPCODE_R_TYPE};
                    case (f3)
                        3'b000: begin
                            if (f7 == 7'b0000000)
                                check_op("ADD", word, ALU_OP_ADD);
                            else if (f7 == 7'b0100000)
                                check_op("SUB", word, ALU_OP_SUB);
                            else
                                check_illegal("reserved OP funct7", word);
                        end
                        3'b001: begin
                            if (f7 == 7'b0000000)
                                check_op("SLL", word, ALU_OP_SLL);
                            else
                                check_illegal("reserved SLL funct7", word);
                        end
                        3'b010: begin
                            if (f7 == 7'b0000000)
                                check_op("SLT", word, ALU_OP_SLT);
                            else
                                check_illegal("reserved SLT funct7", word);
                        end
                        3'b011: begin
                            if (f7 == 7'b0000000)
                                check_op("SLTU", word, ALU_OP_SLTU);
                            else
                                check_illegal("reserved SLTU funct7", word);
                        end
                        3'b100: begin
                            if (f7 == 7'b0000000)
                                check_op("XOR", word, ALU_OP_XOR);
                            else
                                check_illegal("reserved XOR funct7", word);
                        end
                        3'b101: begin
                            if (f7 == 7'b0000000)
                                check_op("SRL", word, ALU_OP_SRL);
                            else if (f7 == 7'b0100000)
                                check_op("SRA", word, ALU_OP_SRA);
                            else
                                check_illegal("reserved SRL/SRA funct7", word);
                        end
                        3'b110: begin
                            if (f7 == 7'b0000000)
                                check_op("OR", word, ALU_OP_OR);
                            else
                                check_illegal("reserved OR funct7", word);
                        end
                        3'b111: begin
                            if (f7 == 7'b0000000)
                                check_op("AND", word, ALU_OP_AND);
                            else
                                check_illegal("reserved AND funct7", word);
                        end
                    endcase
                end
            end
        end
    endtask

    task automatic test_op_imm;
        logic [6:0] f7;
        logic [2:0] f3;
        logic [31:0] word;
        begin
            for (int unsigned funct3 = 0; funct3 < 8; funct3++) begin
                for (int unsigned funct7 = 0; funct7 < 128; funct7++) begin
                    f3 = 3'(funct3);
                    f7 = 7'(funct7);
                    word = {f7, 5'd7, 5'd2, f3, 5'd1, OPCODE_I_TYPE};
                    case (f3)
                        3'b000: check_op_imm("ADDI",  word, ALU_OP_ADD);
                        3'b010: check_op_imm("SLTI",  word, ALU_OP_SLT);
                        3'b011: check_op_imm("SLTIU", word, ALU_OP_SLTU);
                        3'b100: check_op_imm("XORI",  word, ALU_OP_XOR);
                        3'b110: check_op_imm("ORI",   word, ALU_OP_OR);
                        3'b111: check_op_imm("ANDI",  word, ALU_OP_AND);
                        3'b001: begin
                            if (f7 == 7'b0000000)
                                check_op_imm("SLLI", word, ALU_OP_SLL);
                            else
                                check_illegal("reserved SLLI funct7", word);
                        end
                        3'b101: begin
                            if (f7 == 7'b0000000)
                                check_op_imm("SRLI", word, ALU_OP_SRL);
                            else if (f7 == 7'b0100000)
                                check_op_imm("SRAI", word, ALU_OP_SRA);
                            else
                                check_illegal("reserved SRLI/SRAI funct7", word);
                        end
                    endcase
                end
            end
        end
    endtask

    task automatic test_memory_branch_jalr;
        logic [2:0] f3;
        logic [31:0] word;
        begin
            for (int unsigned funct3 = 0; funct3 < 8; funct3++) begin
                f3 = 3'(funct3);

                word = {12'h5a5, 5'd2, f3, 5'd1, OPCODE_LOAD};
                case (f3)
                    3'b000, 3'b001, 3'b010, 3'b100, 3'b101:
                        check_load("legal load funct3", word);
                    default: check_illegal("reserved load funct3", word);
                endcase

                word = {7'h2d, 5'd3, 5'd2, f3, 5'h15, OPCODE_STORE};
                case (f3)
                    3'b000, 3'b001, 3'b010:
                        check_store("legal store funct3", word);
                    default: check_illegal("reserved store funct3", word);
                endcase

                word = {7'h2d, 5'd3, 5'd2, f3, 5'h15, OPCODE_BRANCH};
                case (f3)
                    3'b000, 3'b001, 3'b100, 3'b101, 3'b110, 3'b111:
                        check_branch("legal branch funct3", word);
                    default: check_illegal("reserved branch funct3", word);
                endcase

                word = {12'h5a5, 5'd2, f3, 5'd1, OPCODE_JALR};
                if (f3 == 3'b000)
                    check_outputs("JALR", word,
                                  1'b0, 1'b1, 1'b0,
                                  1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                                  ALU_OP_ADD, PC_SRC_JALR, WB_SRC_PC4,
                                  1'b0, 1'b0, 1'b0, 1'b0);
                else
                    check_illegal("reserved JALR funct3", word);
            end
        end
    endtask

    task automatic test_upper_jump;
        begin
            check_outputs("LUI immediate low", 32'h0000_00b7,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                          ALU_OP_PASSB, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
            check_outputs("LUI immediate high", 32'hffff_feb7,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                          ALU_OP_PASSB, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
            check_outputs("AUIPC immediate low", 32'h0000_0097,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b1, 1'b0, 1'b0, 1'b0);
            check_outputs("AUIPC immediate high", 32'hffff_fe97,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b1, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b1, 1'b0, 1'b0, 1'b0);
            check_outputs("JAL immediate low", 32'h0000_00ef,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_JAL, WB_SRC_PC4,
                          1'b0, 1'b0, 1'b0, 1'b0);
            check_outputs("JAL immediate high", 32'hffff_fdef,
                          1'b0, 1'b0, 1'b0,
                          1'b1, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_JAL, WB_SRC_PC4,
                          1'b0, 1'b0, 1'b0, 1'b0);
        end
    endtask

    task automatic test_system;
        logic [2:0] f3;
        logic [31:0] word;
        begin
            for (int unsigned funct3 = 1; funct3 < 8; funct3++) begin
                f3 = 3'(funct3);
                word = {12'h305, 5'd9, f3, 5'd4, OPCODE_SYSTEM};
                case (f3)
                    F3_CSRRW, F3_CSRRS, F3_CSRRC:
                        check_csr("CSR register form", word, 1'b1);
                    F3_CSRRWI, F3_CSRRSI, F3_CSRRCI:
                        check_csr("CSR immediate form", word, 1'b0);
                    default:
                        check_illegal("reserved SYSTEM funct3", word);
                endcase
            end

            check_csr("CSRRS register rs1=x0",
                      {12'h305, 5'd0, F3_CSRRS, 5'd4, OPCODE_SYSTEM}, 1'b1);
            check_csr("CSRRC register rs1=x0",
                      {12'h305, 5'd0, F3_CSRRC, 5'd4, OPCODE_SYSTEM}, 1'b1);
            check_csr("CSRRWI immediate uimm=0",
                      {12'h305, 5'd0, F3_CSRRWI, 5'd4, OPCODE_SYSTEM}, 1'b0);
            check_csr("CSRRSI immediate uimm=0",
                      {12'h305, 5'd0, F3_CSRRSI, 5'd4, OPCODE_SYSTEM}, 1'b0);
            check_csr("CSRRCI immediate uimm=0",
                      {12'h305, 5'd0, F3_CSRRCI, 5'd4, OPCODE_SYSTEM}, 1'b0);

            check_outputs("ECALL", INSTR_ECALL,
                          1'b0, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b1, 1'b0);
            check_outputs("EBREAK", INSTR_EBREAK,
                          1'b0, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b1, 1'b0);
            check_outputs("MRET", INSTR_MRET,
                          1'b0, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b1, 1'b0);

            check_illegal("WFI", 32'h1050_0073);
            check_illegal("SRET", 32'h1020_0073);
            check_illegal("SFENCE.VMA", 32'h1200_0073);
            check_illegal("SYSTEM-000 other immediate", 32'h1230_0073);
            check_illegal("ECALL with nonzero rd", 32'h0000_00f3);
            check_illegal("EBREAK with nonzero rs1", 32'h0010_8073);
            check_illegal("MRET with nonzero rd", 32'h3020_00f3);
            check_illegal("MRET with nonzero rs1", 32'h3020_8073);
        end
    endtask

    task automatic test_fence;
        logic [2:0] f3;
        logic [31:0] word;
        begin
            for (int unsigned funct3 = 0; funct3 < 8; funct3++) begin
                f3 = 3'(funct3);
                word = {12'habc, 5'd21, f3, 5'd10, OPCODE_FENCE};
                case (f3)
                    3'b000:
                        check_outputs("FENCE ignored fields", word,
                                      1'b0, 1'b0, 1'b0,
                                      1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                                      ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                                      1'b0, 1'b0, 1'b0, 1'b0);
                    F3_FENCEI:
                        check_outputs("FENCE.I ignored fields", word,
                                      1'b0, 1'b0, 1'b0,
                                      1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                                      ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                                      1'b0, 1'b0, 1'b0, 1'b1);
                    default:
                        check_illegal("reserved FENCE funct3", word);
                endcase
            end

            check_outputs("FENCE zero fields", 32'h0000_000f,
                          1'b0, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b0);
            check_outputs("FENCE.I all ignored fields", 32'hffff_ffff & ~32'h0000_707f | 32'h0000_100f,
                          1'b0, 1'b0, 1'b0,
                          1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                          ALU_OP_ADD, PC_SRC_SEQ, WB_SRC_ALU,
                          1'b0, 1'b0, 1'b0, 1'b1);
        end
    endtask

    initial begin
        instr = '0;
        checks = 0;
        failures = 0;

        test_op();
        test_op_imm();
        test_memory_branch_jalr();
        test_upper_jump();
        test_system();
        test_fence();
        check_illegal("unknown opcode", 32'hffff_ffff);

        if (failures != 0)
            $fatal(1, "control unit failed: %0d/%0d vectors mismatched",
                   failures, checks);

        $display("PASS control: %0d vectors", checks);
        $finish;
    end
endmodule

`default_nettype wire
