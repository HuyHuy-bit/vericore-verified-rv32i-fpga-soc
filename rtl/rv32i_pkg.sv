// rv32i_pkg.sv - shared constants for the RV32I core.
// Previously the opcode encodings were duplicated as localparams in both
// control.sv and imm_gen.sv; a change in one place could silently diverge
// from the other. Centralizing them here means the encoding is defined once.
`default_nettype none

package rv32i_pkg;

    // ---- Test-completion (riscv-tests "tohost" convention) ----
    // A store to this address ends a simulation run; the stored value is the
    // exit code (1 = pass, (n<<1)|1 = fail n). Placed near the top of the 64KB
    // data memory so it cannot collide with the low addresses the directed
    // tests use as scratch. Simulation-only - nothing in the RTL reacts to it.
    localparam logic [31:0] TOHOST_ADDR = 32'h0000_FFF0;

    // ---- Widths ----
    // XLEN is the datapath width: registers, PC, addresses, ALU operands,
    // immediates, CSRs. Changing it here changes all of them.
    //
    // ILEN is the *instruction* width and is deliberately NOT XLEN. RV64
    // instructions are still 32 bits — only the data path widens — so the
    // instruction memory, the I-cache line contents, and the encodings below
    // stay 32-bit regardless. Conflating the two is the classic way to get a
    // "parameterised" core that only ever worked at one width.
    //
    // Note this parameterises *width*, not the ISA: RV64I additionally needs
    // LD/SD and the *W instruction forms, which is decode work in control.sv
    // and lsu.sv, not a width change. See docs/architecture.md.
    localparam int XLEN   = 32;
    localparam int ILEN   = 32;

    // Global branch history width, for the optional gshare direction
    // predictor in branch_predictor.sv. Lives here rather than as a module
    // parameter because if_id_t/id_ex_t below need to size a field by it: a
    // gshare table index is a function of history, so the exact history
    // value used to make a prediction has to travel with that instruction
    // through the pipeline and be replayed at update time, or a second
    // in-flight branch's history update would corrupt the wrong table entry.
    localparam int GHIST_BITS = 6;
    localparam int XBYTES = XLEN / 8;              // byte lanes per data word
    localparam int XOFFW  = (XBYTES <= 1) ? 1 : $clog2(XBYTES);  // byte-offset width

    // ---- Opcodes (instr[6:0]) ----
    localparam logic [6:0] OPCODE_R_TYPE = 7'b0110011;
    localparam logic [6:0] OPCODE_I_TYPE = 7'b0010011;
    localparam logic [6:0] OPCODE_LOAD   = 7'b0000011;
    localparam logic [6:0] OPCODE_STORE  = 7'b0100011;
    localparam logic [6:0] OPCODE_BRANCH = 7'b1100011;
    localparam logic [6:0] OPCODE_JAL    = 7'b1101111;
    localparam logic [6:0] OPCODE_JALR   = 7'b1100111;
    localparam logic [6:0] OPCODE_LUI    = 7'b0110111;
    localparam logic [6:0] OPCODE_AUIPC  = 7'b0010111;
    localparam logic [6:0] OPCODE_FENCE  = 7'b0001111;
    localparam logic [2:0] F3_FENCEI     = 3'b001;   // FENCE.I vs FENCE (3'b000)

    // ---- ALU operation codes (control.sv -> alu.sv, the alu_op field) ----
    localparam logic [3:0] ALU_OP_ADD  = 4'b0000;
    localparam logic [3:0] ALU_OP_SUB  = 4'b0001;
    localparam logic [3:0] ALU_OP_AND  = 4'b0010;
    localparam logic [3:0] ALU_OP_OR   = 4'b0011;
    localparam logic [3:0] ALU_OP_XOR  = 4'b0100;
    localparam logic [3:0] ALU_OP_SLT  = 4'b0101;
    localparam logic [3:0] ALU_OP_SLTU = 4'b0110;
    localparam logic [3:0] ALU_OP_SLL  = 4'b0111;
    localparam logic [3:0] ALU_OP_SRL  = 4'b1000;
    localparam logic [3:0] ALU_OP_SRA  = 4'b1001;
    localparam logic [3:0] ALU_OP_PASSB = 4'b1010; // pass operand B through (LUI)

    // ---- pc_src / wb_src mux selectors (control.sv -> cpu.sv) ----
    // Previously raw 2'b.. literals duplicated in both control.sv and
    // cpu.sv; same duplication problem the opcode constants above exist to
    // solve, applied consistently.
    localparam logic [1:0] PC_SRC_SEQ    = 2'b00; // sequential (pc+4 / predicted)
    localparam logic [1:0] PC_SRC_BRANCH = 2'b01; // conditional branch
    localparam logic [1:0] PC_SRC_JALR   = 2'b10;
    localparam logic [1:0] PC_SRC_JAL    = 2'b11;

    localparam logic [1:0] WB_SRC_ALU  = 2'b00;
    localparam logic [1:0] WB_SRC_MEM  = 2'b01;
    localparam logic [1:0] WB_SRC_PC4  = 2'b10; // JAL/JALR link value
    localparam logic [1:0] WB_SRC_CSR  = 2'b11;

    // ---- Branch-condition funct3 (branch_unit.sv) ----
    localparam logic [2:0] F3_BEQ  = 3'b000;
    localparam logic [2:0] F3_BNE  = 3'b001;
    localparam logic [2:0] F3_BLT  = 3'b100;
    localparam logic [2:0] F3_BGE  = 3'b101;
    localparam logic [2:0] F3_BLTU = 3'b110;
    localparam logic [2:0] F3_BGEU = 3'b111;

    // ---- Load/store width funct3 (lsu.sv); low 2 bits = width, bit 2 =
    // unsigned for loads ----
    localparam logic [2:0] F3_LB  = 3'b000;
    localparam logic [2:0] F3_LH  = 3'b001;
    localparam logic [2:0] F3_LW  = 3'b010;
    localparam logic [2:0] F3_LBU = 3'b100;
    localparam logic [2:0] F3_LHU = 3'b101;

    // ---- SYSTEM opcode (CSR instructions, ECALL, EBREAK, MRET) ----
    localparam logic [6:0] OPCODE_SYSTEM = 7'b1110011;

    // funct3 encodings within OPCODE_SYSTEM
    localparam logic [2:0] F3_PRIV   = 3'b000; // ECALL/EBREAK/MRET (distinguished by imm)
    localparam logic [2:0] F3_CSRRW  = 3'b001;
    localparam logic [2:0] F3_CSRRS  = 3'b010;
    localparam logic [2:0] F3_CSRRC  = 3'b011;
    localparam logic [2:0] F3_CSRRWI = 3'b101;
    localparam logic [2:0] F3_CSRRSI = 3'b110;
    localparam logic [2:0] F3_CSRRCI = 3'b111;

    // full-instruction encodings for the privileged ops (F3_PRIV)
    localparam logic [ILEN-1:0] INSTR_ECALL  = 32'h00000073;
    localparam logic [ILEN-1:0] INSTR_EBREAK = 32'h00100073;
    localparam logic [ILEN-1:0] INSTR_MRET   = 32'h30200073;

    // ---- CSR addresses (instr[31:20]) - minimal M-mode set ----
    localparam logic [11:0] CSR_MSTATUS   = 12'h300;
    localparam logic [11:0] CSR_MIE       = 12'h304;
    localparam logic [11:0] CSR_MTVEC     = 12'h305;
    localparam logic [11:0] CSR_MIP       = 12'h344;

    // mtime/mtimecmp are memory-mapped devices in the privileged spec, not
    // CSRs. This core has no MMIO fabric, so they live in the custom M-mode
    // CSR space (0x7C0-0x7FF) instead. That is a deliberate, documented
    // deviation: the interrupt *architecture* is spec-conformant, only the
    // timer's discovery mechanism is not. Software written for a real CLINT
    // would need its two accessors changed and nothing else.
    localparam logic [11:0] CSR_MTIMECMP  = 12'h7C0;
    localparam logic [11:0] CSR_MTIME     = 12'h7C1;
    localparam logic [11:0] CSR_MEPC      = 12'h341;
    localparam logic [11:0] CSR_MCAUSE    = 12'h342;
    localparam logic [11:0] CSR_MSCRATCH  = 12'h340;
    localparam logic [11:0] CSR_MTVAL     = 12'h343;
    localparam logic [11:0] CSR_MISA      = 12'h301;
    localparam logic [11:0] CSR_MVENDORID = 12'hF11;
    localparam logic [11:0] CSR_MARCHID   = 12'hF12;
    localparam logic [11:0] CSR_MIMPID    = 12'hF13;
    localparam logic [11:0] CSR_MHARTID   = 12'hF14;
    localparam logic [11:0] CSR_MCYCLE    = 12'hB00;
    localparam logic [11:0] CSR_MINSTRET  = 12'hB02;
    localparam logic [11:0] CSR_MCYCLEH   = 12'hB80;
    localparam logic [11:0] CSR_MINSTRETH = 12'hB82;

    // misa: MXL=1 (32-bit) in [31:30], extension bit 'I' (bit 8). No other
    // extensions implemented.
    localparam logic [XLEN-1:0] MISA_VALUE = XLEN'('h4000_0100);

    // ---- mstatus / mie / mip bit positions ----
    localparam int MSTATUS_MIE_BIT  = 3;
    localparam int MSTATUS_MPIE_BIT = 7;
    localparam int MSTATUS_MPP_LSB  = 11;   // 2 bits [12:11]

    // Software and timer only. There is no external-interrupt bit because
    // nothing would drive it - a declared-but-unused IRQ_E_BIT would be
    // exactly the kind of dead constant that makes a spec gap look like
    // an oversight rather than a scoping decision.
    localparam int IRQ_S_BIT = 3;   // software
    localparam int IRQ_T_BIT = 7;   // timer

    // ---- Interrupt cause codes (mcause, interrupt bit = 1) ----
    // The MSB of mcause distinguishes an interrupt from an exception; the low
    // bits carry the same numbering as the mie/mip bit positions.
    localparam logic [XLEN-1:0] CAUSE_IRQ_SOFT  = {1'b1, {(XLEN-1){1'b0}}} | XLEN'(IRQ_S_BIT);
    localparam logic [XLEN-1:0] CAUSE_IRQ_TIMER = {1'b1, {(XLEN-1){1'b0}}} | XLEN'(IRQ_T_BIT);

    // ---- Exception cause codes (mcause, interrupt bit = 0) ----
    localparam logic [XLEN-1:0] CAUSE_MISALIGNED_FETCH = XLEN'(0);
    localparam logic [XLEN-1:0] CAUSE_ILLEGAL_INSTR    = XLEN'(2);
    localparam logic [XLEN-1:0] CAUSE_BREAKPOINT       = XLEN'(3);
    localparam logic [XLEN-1:0] CAUSE_MISALIGNED_LOAD  = XLEN'(4);
    localparam logic [XLEN-1:0] CAUSE_MISALIGNED_STORE = XLEN'(6);
    localparam logic [XLEN-1:0] CAUSE_ECALL_M          = XLEN'(11);

    // Every CSR address this core implements. Used both to decide whether an
    // access should trap illegal (cpu.sv) and to dispatch reads/writes
    // (csr.sv) — one list instead of two that can drift apart.
    function automatic logic csr_implemented(input logic [11:0] addr);
        case (addr)
            CSR_MSTATUS, CSR_MIE, CSR_MIP, CSR_MTIMECMP, CSR_MTIME,
            CSR_MTVEC, CSR_MEPC, CSR_MCAUSE, CSR_MSCRATCH, CSR_MTVAL, CSR_MISA,
            CSR_MVENDORID, CSR_MARCHID, CSR_MIMPID, CSR_MHARTID,
            CSR_MCYCLE, CSR_MINSTRET, CSR_MCYCLEH, CSR_MINSTRETH:
                csr_implemented = 1'b1;
            default:
                csr_implemented = 1'b0;
        endcase
    endfunction

    // Address bits [11:10] == 2'b11 is the standard RISC-V convention for a
    // read-only CSR; a write attempt to one must trap illegal-instruction.
    function automatic logic csr_read_only(input logic [11:0] addr);
        csr_read_only = (addr[11:10] == 2'b11);
    endfunction


    // ---- Pipeline payloads ----
    // One struct per pipeline register. Adding a signal to a stage is a
    // one-line change here instead of six edits across three files (a port on
    // the register module, its reset clause, its latch clause, and the
    // instantiation's input and output connections in cpu.sv).
    //
    // The register modules keep their own control logic rather than sharing a
    // generic one: their flush/stall/freeze priorities genuinely differ (IF/ID
    // alone has a `stall` that holds without clearing, and MEM/WB has no flush
    // at all), and collapsing those into one parameterised module would hide a
    // real distinction to save a few lines.

    typedef struct packed {
        logic       reg_write_en;
        logic       alu_src;
        logic       alu_a_src;
        logic [3:0] alu_op;
        logic       mem_write;
        logic       mem_read;
        logic       branch;
        logic [1:0] pc_src;
        logic [1:0] wb_src;
        logic       is_csr;
        logic       is_system;
        logic       is_fencei;
        logic       illegal;
        logic       uses_rs1;
        logic       uses_rs2;
    } ctrl_t;

    typedef struct packed {
        logic [XLEN-1:0] pc, pc_plus4;
        logic [ILEN-1:0] instr;
        logic            valid;
        logic            predicted_taken;
        logic [XLEN-1:0] predicted_target;
        logic [GHIST_BITS-1:0] predict_ghistory;
    } if_id_t;

    typedef struct packed {
        logic [XLEN-1:0] pc, pc_plus4, rs1_data, rs2_data, imm;
        logic [4:0]  rs1_addr, rs2_addr, rd_addr;
        logic [2:0]  funct3;
        ctrl_t       ctrl;
        logic        valid;
        logic        predicted_taken;
        logic [XLEN-1:0] predicted_target;
        logic [GHIST_BITS-1:0] predict_ghistory;
        logic [11:0]     csr_addr;
        logic [XLEN-1:0] csr_wdata;
        logic [ILEN-1:0] instr;
    } id_ex_t;

    typedef struct packed {
        logic [XLEN-1:0] alu_result, rs2_data, pc_plus4;
        logic [4:0]  rd_addr;
        logic [2:0]  funct3;
        logic        reg_write_en, mem_write, mem_read;
        logic [1:0]  wb_src;
        logic        valid;
        logic [XLEN-1:0] pc;
        logic            exc_pending;
        logic [XLEN-1:0] exc_cause;
        logic [XLEN-1:0] exc_tval;
        logic        is_csr, is_system, is_fencei;
        logic [11:0] csr_addr;
        logic [2:0]  csr_funct3;
        logic [XLEN-1:0] csr_wdata, csr_rdata;
        logic [ILEN-1:0] instr;
    } ex_mem_t;

    typedef struct packed {
        logic [XLEN-1:0] mem_read_data, alu_result, pc_plus4;
        logic [4:0]  rd_addr;
        logic        reg_write_en;
        logic [1:0]  wb_src;
        logic        valid;
    } mem_wb_t;

endpackage
