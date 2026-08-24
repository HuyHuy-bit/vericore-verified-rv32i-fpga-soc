`default_nettype none

import rv32i_pkg::*;

// backend.sv - decode through write-back, plus the trap/CSR commit point.
//
// Everything that decides what an instruction *does*. The front end decides
// only which one to fetch; see frontend.sv. The redirect outputs below
// (mispredict, trap, load-use) are what the front end consumes, and they are
// the entire interface in that direction.
module backend #(
    parameter int DCACHE_BYTES       = 0,
    parameter int DCACHE_BLOCK_WORDS = 4,
    parameter int DCACHE_WAYS        = 1,
    parameter int DCACHE_WRITE_BACK  = 0,
    parameter int DMEM_LATENCY       = 1,
    parameter int DMEM_DEPTH_WORDS   = 16384
) (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic        pipe_stall,
    input  var if_id_t      if_id_q,          // payload from the front end

    // Redirects and holds consumed by the front end.
    output var logic        load_use_stall,
    output var logic        ex_flush,
    output var logic [XLEN-1:0] ex_resolved_target,
    output var logic        trap_redirect,
    output var logic [XLEN-1:0] trap_target,
    output var logic        icache_invalidate,   // FENCE.I committed

    // Predictor learning, from the EX-stage resolution.
    output var logic        bp_update_en,
    output var logic [XLEN-1:0] bp_update_pc,
    output var logic        bp_update_taken,
    output var logic [XLEN-1:0] bp_update_target,
    output var logic [GHIST_BITS-1:0] bp_update_ghistory,

    output var logic        dmem_ready,       // 0 = data side is stalling the pipe
    output var logic        dcache_access,
    output var logic        dcache_miss,

    // Counter observations that only this side can see.
    output var logic        retired,          // a real instruction retired in WB
    output var logic        mispredicted,     // ...and it was a genuine branch mispredict

    // Live counters, fed back in so mcycle/minstret can read them. They are
    // produced by perf_counters.sv at the top level because the front end
    // contributes to them too.
    input  var logic [XLEN-1:0] perf_cycle_count,
    input  var logic [XLEN-1:0] perf_instr_retired,

    input  var logic        dbg_flush,
    output var logic        dbg_flush_done
);

    // ID stage
    logic [2:0] funct3_id;
    logic [4:0] rs1_addr_id, rs2_addr_id, rd_addr_id;
    assign rd_addr_id  = if_id_q.instr[11:7];
    assign funct3_id   = if_id_q.instr[14:12];
    assign rs1_addr_id = if_id_q.instr[19:15];
    assign rs2_addr_id = if_id_q.instr[24:20];

    logic        reg_write_en_id, alu_src_id, mem_write_id, mem_read_id, branch_id, alu_a_src_id;
    logic [3:0]  alu_op_id;
    logic [1:0]  pc_src_id, wb_src_id;
    logic        is_csr_id, is_system_id, is_fencei_id, illegal_id;
    logic        uses_rs1_id, uses_rs2_id;

    control u_control (
        .instr(if_id_q.instr),
        .reg_write_en(reg_write_en_id), .alu_src(alu_src_id),
        .mem_write(mem_write_id), .mem_read(mem_read_id),
        .branch(branch_id), .pc_src(pc_src_id), .wb_src(wb_src_id),
        .alu_a_src(alu_a_src_id), .alu_op(alu_op_id),
        .is_csr(is_csr_id), .is_system(is_system_id), .is_fencei(is_fencei_id),
        .illegal(illegal_id), .uses_rs1(uses_rs1_id), .uses_rs2(uses_rs2_id)
    );

    // CSR instruction operand fields (decoded in ID, used at commit in MEM).
    // CSRRWI/CSRRSI/CSRRCI (funct3[2]==1) use a zero-extended 5-bit uimm from
    // the rs1 field instead of a register value.
    logic [11:0] csr_addr_id;
    logic [XLEN-1:0] csr_wdata_id;
    assign csr_addr_id  = if_id_q.instr[31:20];
    // CSRRWI/SI/CI zero-extend a 5-bit uimm to the datapath width.
    assign csr_wdata_id = funct3_id[2] ? XLEN'(rs1_addr_id) : reg_rs1_data_id;

    logic [XLEN-1:0] reg_rs1_data_id, reg_rs2_data_id;
    logic [XLEN-1:0] write_back_data; // driven by WB stage, below

    reg_file u_reg_file (
        .clk(clk), .rst(rst),
        .rs1_addr(rs1_addr_id), .rs2_addr(rs2_addr_id), .rd_addr(mem_wb_q.rd_addr),
        .rd_data(write_back_data), .rd_write_en(mem_wb_q.reg_write_en),
        .rs1_data(reg_rs1_data_id), .rs2_data(reg_rs2_data_id)
    );

    logic [XLEN-1:0] imm_id;
    imm_gen u_imm_gen ( .instr(if_id_q.instr), .imm(imm_id) );

    // ID/EX register
    logic [XLEN-1:0] csr_rdata_ex;   // old CSR value, read combinationally in EX

    // A taken branch/jump resolves in EX one cycle before this register would
    // otherwise latch the two wrong-path instructions behind it - flush next cycle.
    // A load-use hazard inserts a bubble here too, while IF/ID holds so the
    // stalled instruction re-decodes correctly next cycle.
    logic id_ex_flush;
    assign id_ex_flush = ex_flush || load_use_stall || trap_redirect;

    id_ex_t id_ex_d, id_ex_q;
    always_comb begin
        id_ex_d                   = '0;
        id_ex_d.pc                = if_id_q.pc;
        id_ex_d.pc_plus4          = if_id_q.pc_plus4;
        id_ex_d.rs1_data          = reg_rs1_data_id;
        id_ex_d.rs2_data          = reg_rs2_data_id;
        id_ex_d.imm               = imm_id;
        id_ex_d.rs1_addr          = rs1_addr_id;
        id_ex_d.rs2_addr          = rs2_addr_id;
        id_ex_d.rd_addr           = rd_addr_id;
        id_ex_d.funct3            = funct3_id;
        id_ex_d.ctrl.reg_write_en = reg_write_en_id;
        id_ex_d.ctrl.alu_src      = alu_src_id;
        id_ex_d.ctrl.alu_a_src    = alu_a_src_id;
        id_ex_d.ctrl.alu_op       = alu_op_id;
        id_ex_d.ctrl.mem_write    = mem_write_id;
        id_ex_d.ctrl.mem_read     = mem_read_id;
        id_ex_d.ctrl.branch       = branch_id;
        id_ex_d.ctrl.pc_src       = pc_src_id;
        id_ex_d.ctrl.wb_src       = wb_src_id;
        id_ex_d.ctrl.is_csr       = is_csr_id;
        id_ex_d.ctrl.is_system    = is_system_id;
        id_ex_d.ctrl.is_fencei    = is_fencei_id;
        id_ex_d.ctrl.illegal      = illegal_id;
        id_ex_d.ctrl.uses_rs1     = uses_rs1_id;
        id_ex_d.ctrl.uses_rs2     = uses_rs2_id;
        id_ex_d.valid             = if_id_q.valid;
        id_ex_d.predicted_taken   = if_id_q.predicted_taken;
        id_ex_d.predicted_target  = if_id_q.predicted_target;
        id_ex_d.predict_ghistory  = if_id_q.predict_ghistory;
        id_ex_d.csr_addr          = csr_addr_id;
        id_ex_d.csr_wdata         = csr_wdata_id;
        id_ex_d.instr             = if_id_q.instr;
    end

    id_ex_reg u_id_ex (
        .clk(clk), .rst(rst), .flush(id_ex_flush), .freeze(pipe_stall),
        .d(id_ex_d), .q(id_ex_q)
    );

    // Hazard detection (load-use)
    // Checks the instruction now sitting in EX (via the ID/EX register's
    // own outputs) against the instruction currently being decoded in ID.
    hazard_detect u_hazard_detect (
        .mem_read_ex(id_ex_q.ctrl.mem_read), .rd_addr_ex(id_ex_q.rd_addr),
        .rs1_addr_id(rs1_addr_id), .rs2_addr_id(rs2_addr_id),
        .uses_rs1_id(uses_rs1_id), .uses_rs2_id(uses_rs2_id),
        .stall(load_use_stall)
    );

    // EX stage
    // Forwarding: pick rs1/rs2 from EX/MEM or MEM/WB instead of the raw
    // ID/EX-registered value whenever a not-yet-retired instruction ahead
    // in the pipe is about to write the same register.
    logic [1:0] forward_a, forward_b;
    forwarding_unit u_forwarding_unit (
        .rs1_addr_ex(id_ex_q.rs1_addr), .rs2_addr_ex(id_ex_q.rs2_addr),
        .rd_addr_mem(ex_mem_q.rd_addr), .reg_write_en_mem(ex_mem_q.reg_write_en),
        .rd_addr_wb(mem_wb_q.rd_addr),   .reg_write_en_wb(mem_wb_q.reg_write_en),
        .forward_a(forward_a), .forward_b(forward_b)
    );

    // The value the EX/MEM stage will actually write back: for a CSR
    // instruction it's the old CSR value, otherwise the ALU result. Forwarding
    // must use THIS, not raw ex_mem_q.alu_result, or a CSR read forwarded to the
    // next instruction delivers garbage.
    logic [XLEN-1:0] mem_fwd_value;
    assign mem_fwd_value = ex_mem_q.is_csr ? csr_rdata_commit : ex_mem_q.alu_result;

    logic [XLEN-1:0] rs1_data_ex_fwd, rs2_data_ex_fwd;
    always_comb begin
        case (forward_a)
            2'b01:   rs1_data_ex_fwd = mem_fwd_value;    // from EX/MEM (CSR-aware)
            2'b10:   rs1_data_ex_fwd = write_back_data;  // from MEM/WB (WB-stage mux output)
            default: rs1_data_ex_fwd = id_ex_q.rs1_data;      // no hazard - use registered value
        endcase
        case (forward_b)
            2'b01:   rs2_data_ex_fwd = mem_fwd_value;
            2'b10:   rs2_data_ex_fwd = write_back_data;
            default: rs2_data_ex_fwd = id_ex_q.rs2_data;
        endcase
    end

    // CSR write data must use the FORWARDED rs1 (register variants), else a
    // csrrw right after an instruction producing rs1 captures a stale value.
    // Immediate variants (funct3[2]==1) use the uimm carried from ID, hazard-free.
    logic [XLEN-1:0] csr_wdata_ex_fwd;
    assign csr_wdata_ex_fwd = id_ex_q.funct3[2] ? id_ex_q.csr_wdata   // uimm (from ID, no hazard)
                                           : rs1_data_ex_fwd; // register variant (forwarded)

    logic [XLEN-1:0] alu_a_ex, alu_b_ex, alu_result_ex;
    assign alu_a_ex = id_ex_q.ctrl.alu_a_src ? id_ex_q.pc : rs1_data_ex_fwd;
    assign alu_b_ex = id_ex_q.ctrl.alu_src   ? id_ex_q.imm : rs2_data_ex_fwd;

    alu u_alu (
        .a(alu_a_ex), .b(alu_b_ex), .alu_op(id_ex_q.ctrl.alu_op),
        .result(alu_result_ex)
    );

    logic branch_taken_ex;
    branch_unit u_branch_unit (
        .rs1(rs1_data_ex_fwd), .rs2(rs2_data_ex_fwd), .funct3(id_ex_q.funct3),
        .branch(id_ex_q.ctrl.branch), .pc_sel(branch_taken_ex)
    );

    logic [XLEN-1:0] branch_target_ex, jalr_target_ex;
    assign branch_target_ex = id_ex_q.pc + id_ex_q.imm;
    assign jalr_target_ex   = (rs1_data_ex_fwd + id_ex_q.imm) & ~XLEN'(1);

    // Resolve the actual control-flow outcome in EX.
    logic        actual_taken;      // did this instruction actually redirect?
    logic [XLEN-1:0] actual_target;     // ...and to where
    logic        is_cf_instr;       // is this a control-flow instruction at all?
    always_comb begin
        case (id_ex_q.ctrl.pc_src)
            PC_SRC_BRANCH: begin actual_taken = branch_taken_ex; actual_target = branch_target_ex; is_cf_instr = 1'b1; end
            PC_SRC_JALR:   begin actual_taken = 1'b1;            actual_target = jalr_target_ex;   is_cf_instr = 1'b1; end
            PC_SRC_JAL:    begin actual_taken = 1'b1;            actual_target = branch_target_ex; is_cf_instr = 1'b1; end
            default:       begin actual_taken = 1'b0;            actual_target = XLEN'(0);            is_cf_instr = 1'b0; end
        endcase
    end

    // The front end predicted a taken redirect to id_ex_q.predicted_target (only
    // meaningful when id_ex_q.predicted_taken). We mispredicted if:
    //   - actual outcome differs from predicted direction, OR
    //   - both said taken but the cached target was wrong (stale BTB).
    // On a misprediction we flush and redirect to the correct next PC:
    //   taken   -> actual_target
    //   not-taken (but predicted taken) -> the fall-through id_ex_q.pc + 4
    logic        mispredict;
    logic [XLEN-1:0] correct_next_pc;
    always_comb begin
        if (actual_taken && id_ex_q.predicted_taken && (actual_target == id_ex_q.predicted_target)) begin
            mispredict      = 1'b0;                 // correctly predicted taken to the right place
            correct_next_pc = actual_target;
        end else if (!actual_taken && !id_ex_q.predicted_taken) begin
            mispredict      = 1'b0;                 // correctly predicted not-taken
            correct_next_pc = id_ex_q.pc + XLEN'(4);
        end else if (actual_taken) begin
            mispredict      = 1'b1;                 // should have gone taken (or to a different target)
            correct_next_pc = actual_target;
        end else begin
            mispredict      = 1'b1;                 // predicted taken but actually not-taken
            correct_next_pc = id_ex_q.pc + XLEN'(4);
        end
    end

    // Only valid instructions can mispredict (a bubble in EX must not flush).
    // Special case: a non-control-flow instruction that the front end wrongly
    // predicted taken (stale BTB alias) must also recover, back to id_ex_q.pc+4.
    logic false_predict;
    assign false_predict = id_ex_q.valid && !is_cf_instr && id_ex_q.predicted_taken;

    assign ex_flush           = (id_ex_q.valid && is_cf_instr && mispredict) || false_predict;
    assign ex_resolved_target = false_predict ? (id_ex_q.pc + XLEN'(4)) : correct_next_pc;

    // Predictor learning: update on every resolved control-flow instruction.
    // Not while frozen - ID/EX holds, so the same branch would be presented
    // for as many cycles as the stall lasts and its saturating counter would
    // be driven to the rail by a single resolution.
    assign bp_update_en        = id_ex_q.valid && is_cf_instr && !pipe_stall;
    assign bp_update_pc        = id_ex_q.pc;
    assign bp_update_taken     = actual_taken;
    assign bp_update_target    = actual_target;
    assign bp_update_ghistory  = id_ex_q.predict_ghistory;

    // CSRRW(I) always writes; CSRRS/CSRRC(I) only when the operand is
    // nonzero (rs1 field doubles as the 5-bit uimm for the *I variants, so
    // id_ex_q.rs1_addr works for both forms).
    logic csr_attempts_write, csr_access_illegal;
    assign csr_attempts_write = (id_ex_q.funct3 == F3_CSRRW) || (id_ex_q.funct3 == F3_CSRRWI)
                               || (id_ex_q.rs1_addr != 5'd0);
    assign csr_access_illegal = !csr_implemented(id_ex_q.csr_addr)
                               || (csr_attempts_write && csr_read_only(id_ex_q.csr_addr));

    // ---- EX-stage exception detection (Part 1: illegal instruction) ----
    // Detected here, but not acted on until the commit point in MEM, so that
    // exceptions resolve in program order (precise). Part 2 adds misaligned
    // load/store here as well.
    logic        exc_pending_ex;
    logic [XLEN-1:0] exc_cause_ex;
    always_comb begin
        exc_pending_ex = 1'b0;
        exc_cause_ex   = XLEN'(0);
        if (id_ex_q.valid && id_ex_q.ctrl.illegal) begin
            exc_pending_ex = 1'b1;
            exc_cause_ex   = CAUSE_ILLEGAL_INSTR;
        end else if (id_ex_q.valid && id_ex_q.ctrl.is_csr && csr_access_illegal) begin
            // Either the address isn't implemented at all, or it's a
            // structurally read-only CSR ([11:10]==11) and this access
            // actually attempts a write (CSRRW(I) always writes; CSRRS/C(I)
            // only when the rs1/uimm operand is nonzero).
            exc_pending_ex = 1'b1;
            exc_cause_ex   = CAUSE_ILLEGAL_INSTR;
        end else if (id_ex_q.valid && is_cf_instr && actual_taken && actual_target[1]
                     && (id_ex_q.ctrl.pc_src == PC_SRC_BRANCH || id_ex_q.ctrl.pc_src == PC_SRC_JAL)) begin
            // Without the C extension, a taken branch or JAL must land on a
            // 4-byte boundary. JALR already masks bit 0 of its target (see
            // its assign above) and is out of scope here, matching the plan.
            exc_pending_ex = 1'b1;
            exc_cause_ex   = CAUSE_MISALIGNED_FETCH;
        end else if (id_ex_q.valid && id_ex_q.ctrl.mem_read) begin
            if ((id_ex_q.funct3[1:0] == 2'b10 && alu_result_ex[1:0] != 2'b00) ||
                (id_ex_q.funct3[1:0] == 2'b01 && alu_result_ex[0]   != 1'b0)) begin
                exc_pending_ex = 1'b1;
                exc_cause_ex   = CAUSE_MISALIGNED_LOAD;
            end
        end else if (id_ex_q.valid && id_ex_q.ctrl.mem_write) begin
            if ((id_ex_q.funct3[1:0] == 2'b10 && alu_result_ex[1:0] != 2'b00) ||
                (id_ex_q.funct3[1:0] == 2'b01 && alu_result_ex[0]   != 1'b0)) begin
                exc_pending_ex = 1'b1;
                exc_cause_ex   = CAUSE_MISALIGNED_STORE;
            end
        end
    end

    // ---- CSR read happens at the commit point (MEM), not here ----
    // For a CSR instruction, the old value read from the CSR is produced by the
    // csr module at commit and routed straight into write-back; nothing to do
    // in EX. csr_rdata_ex is carried as 0 (unused) to keep the pipe regs simple.
    assign csr_rdata_ex = XLEN'(0);

    // EX/MEM register

ex_mem_t ex_mem_d, ex_mem_q;
    always_comb begin
        ex_mem_d              = '0;
        ex_mem_d.alu_result   = alu_result_ex;
        ex_mem_d.rs2_data     = rs2_data_ex_fwd;
        ex_mem_d.pc_plus4     = id_ex_q.pc_plus4;
        ex_mem_d.rd_addr      = id_ex_q.rd_addr;
        ex_mem_d.funct3       = id_ex_q.funct3;
        ex_mem_d.reg_write_en = id_ex_q.ctrl.reg_write_en;
        ex_mem_d.mem_write    = id_ex_q.ctrl.mem_write;
        ex_mem_d.mem_read     = id_ex_q.ctrl.mem_read;
        ex_mem_d.wb_src       = id_ex_q.ctrl.wb_src;
        ex_mem_d.valid        = id_ex_q.valid;
        ex_mem_d.pc           = id_ex_q.pc;
        ex_mem_d.exc_pending  = exc_pending_ex;
        ex_mem_d.exc_cause    = exc_cause_ex;
        ex_mem_d.is_csr       = id_ex_q.ctrl.is_csr;
        ex_mem_d.is_system    = id_ex_q.ctrl.is_system;
        ex_mem_d.is_fencei    = id_ex_q.ctrl.is_fencei;
        ex_mem_d.csr_addr     = id_ex_q.csr_addr;
        ex_mem_d.csr_funct3   = id_ex_q.funct3;
        ex_mem_d.csr_wdata    = csr_wdata_ex_fwd;
        ex_mem_d.csr_rdata    = csr_rdata_ex;
        ex_mem_d.instr        = id_ex_q.instr;
    end

    ex_mem_reg u_ex_mem (
        .clk(clk), .rst(rst),
        .flush(trap_redirect),
        .freeze(pipe_stall),
        .d(ex_mem_d), .q(ex_mem_q)
    );

    // MEM stage
    logic mem_write_mem_gated;
    assign mem_write_mem_gated = ex_mem_q.mem_write && !(ex_mem_q.valid && ex_mem_q.exc_pending);

    // A faulting access must NOT be presented to memory. If it were, the pipe
    // would freeze waiting for an access to complete while the trap that would
    // release it can only commit once the pipe is unfrozen - a deadlock.
    logic dmem_req;
    assign dmem_req = ex_mem_q.valid && (ex_mem_q.mem_read || ex_mem_q.mem_write) && !ex_mem_q.exc_pending;

    logic [XLEN-1:0] mem_read_data_mem;   // load result, extended, into MEM/WB
    logic [XBYTES-1:0] dm_byte_en;
    logic [XLEN-1:0] dm_store_word, dm_read_word;

    lsu u_lsu (
        .funct3(ex_mem_q.funct3), .byte_off(ex_mem_q.alu_result[XOFFW-1:0]),
        .mem_write(mem_write_mem_gated), .mem_read(ex_mem_q.mem_read),
        .store_data(ex_mem_q.rs2_data), .mem_word(dm_read_word),
        .byte_en(dm_byte_en), .store_word(dm_store_word),
        .load_data(mem_read_data_mem)
    );

    // Data path: optionally through the D-cache, otherwise straight to memory.
    logic [XLEN-1:0] dc_mem_addr, dc_mem_write_word, dc_mem_read_word;
    logic [XBYTES-1:0] dc_mem_byte_en;
    logic        dc_mem_req, dc_mem_burst, dc_mem_ready;

    if (DCACHE_BYTES == 0) begin : g_no_dcache
        assign dc_mem_addr       = ex_mem_q.alu_result;
        assign dc_mem_req        = dmem_req;
        assign dc_mem_burst      = 1'b0;
        assign dc_mem_byte_en    = dm_byte_en;
        assign dc_mem_write_word = dm_store_word;
        assign dm_read_word      = dc_mem_read_word;
        assign dmem_ready        = dc_mem_ready;
        assign dcache_access     = 1'b0;
        assign dcache_miss       = 1'b0;
        assign dbg_flush_done    = dbg_flush;   // nothing cached, nothing to do
    end else begin : g_dcache
        dcache #(
            .BYTES(DCACHE_BYTES),
            .BLOCK_WORDS(DCACHE_BLOCK_WORDS),
            .WAYS(DCACHE_WAYS),
            .WRITE_BACK(DCACHE_WRITE_BACK)
        ) u_dcache (
            .clk(clk), .rst(rst),
            .req(dmem_req), .addr(ex_mem_q.alu_result),
            .byte_en(dm_byte_en), .write_word(dm_store_word),
            .read_word(dm_read_word), .ready(dmem_ready),
            .mem_addr(dc_mem_addr), .mem_req(dc_mem_req), .mem_burst(dc_mem_burst),
            .mem_byte_en(dc_mem_byte_en), .mem_write_word(dc_mem_write_word),
            .mem_read_word(dc_mem_read_word), .mem_ready(dc_mem_ready),
            .flush_req(dbg_flush), .flush_done(dbg_flush_done),
            .access(dcache_access), .miss_pulse(dcache_miss)
        );
    end

    data_mem #(.LATENCY(DMEM_LATENCY), .DEPTH_WORDS(DMEM_DEPTH_WORDS)) u_data_mem (
        .clk(clk), .rst(rst),
        .req(dc_mem_req), .burst(dc_mem_burst),
        .addr(dc_mem_addr),
        .byte_en(dc_mem_byte_en), .write_word(dc_mem_write_word),
        .read_word(dc_mem_read_word), .ready(dc_mem_ready)
    );

    // ---- Commit point: traps, MRET, and CSR writes all resolve here ----
    // This is the single point where control-flow-changing exceptional events
    // are decided, in program order. An instruction reaching MEM is the oldest
    // in-flight non-retired instruction, so acting here gives precise
    // exceptions for free: everything ahead has committed, everything behind
    // gets flushed.
    logic        trap_take;       // a synchronous trap fires this cycle
    logic        irq_take;        // an asynchronous interrupt is taken this cycle
    logic        fencei_take;     // FENCE.I commits this cycle: flush I$ + refetch
    logic        irq_pending;
    logic [XLEN-1:0] irq_cause;
    logic [XLEN-1:0] trap_cause_w;
    logic [XLEN-1:0] trap_val_w;      // -> mtval: faulting address or instruction, if any
    logic        mret_take;       // an MRET commits this cycle
    logic        csr_commit;      // a CSR instruction commits its write this cycle

    logic is_mret_mem, is_ecall_mem, is_ebreak_mem;
    assign is_mret_mem   = ex_mem_q.is_system && (ex_mem_q.instr == INSTR_MRET);
    assign is_ecall_mem  = ex_mem_q.is_system && (ex_mem_q.instr == INSTR_ECALL);
    assign is_ebreak_mem = ex_mem_q.is_system && (ex_mem_q.instr == INSTR_EBREAK);

    always_comb begin
        trap_take    = 1'b0;
        trap_cause_w = XLEN'(0);
        trap_val_w   = XLEN'(0);
        mret_take    = 1'b0;
        csr_commit   = 1'b0;
        irq_take     = 1'b0;
        fencei_take  = 1'b0;

        // !pipe_stall: an instruction sitting in MEM across a memory stall is
        // presented to this block every one of those cycles. Committing only on
        // the cycle the pipeline actually advances keeps trap/MRET/CSR strictly
        // once-per-instruction, and keeps the trap redirect from fighting the
        // frozen PC.
        if (ex_mem_q.valid && !pipe_stall) begin
            if (ex_mem_q.exc_pending) begin
                trap_take    = 1'b1;               // illegal instruction (Part 1)
                trap_cause_w = ex_mem_q.exc_cause;
                // mtval: faulting address for a misaligned access, the
                // offending word for illegal instruction (including an
                // illegal CSR access), 0 for misaligned-fetch (the target
                // isn't carried this far — spec permits mtval reading 0).
                case (ex_mem_q.exc_cause)
                    CAUSE_ILLEGAL_INSTR:                       trap_val_w = XLEN'(ex_mem_q.instr);
                    CAUSE_MISALIGNED_LOAD, CAUSE_MISALIGNED_STORE: trap_val_w = ex_mem_q.alu_result;
                    default: trap_val_w = XLEN'(0);
                endcase
            end else if (is_ecall_mem) begin
                trap_take    = 1'b1;
                trap_cause_w = CAUSE_ECALL_M;
            end else if (is_ebreak_mem) begin
                trap_take    = 1'b1;
                trap_cause_w = CAUSE_BREAKPOINT;
            end else if (is_mret_mem) begin
                mret_take    = 1'b1;
            end else if (ex_mem_q.is_csr) begin
                csr_commit   = 1'b1;
            end else if (ex_mem_q.is_fencei) begin
                // Completes normally and refetches from pc+4: anything already
                // fetched behind it may have come from the now-stale I-cache,
                // so the redirect is the point, not a side effect.
                fencei_take  = 1'b1;
            end else if (irq_pending) begin
                // Lowest priority, and deliberately only on a "plain"
                // instruction. An interrupt is level-held, so deferring it a
                // cycle costs nothing - whereas taking it alongside a CSR
                // write or an MRET would drop that instruction's effect,
                // because mepc points at the *next* instruction (see below)
                // and it would never be re-executed.
                irq_take = 1'b1;
            end
        end
    end

    // Interrupts are taken between instructions: the one in MEM completes
    // normally and mepc points at its successor. Synchronous traps are the
    // opposite - the faulting instruction is annulled and mepc points at it,
    // so it re-executes after the handler returns.
    //
    // This is why reg_write_en_mem_gated below is gated on trap_take and NOT
    // on irq_take: suppressing the register write while resuming at pc+4
    // would silently drop the instruction's result.
    logic [XLEN-1:0] trap_pc_w, trap_cause_final;
    assign trap_pc_w       = irq_take ? ex_mem_q.pc_plus4 : ex_mem_q.pc;
    assign trap_cause_final = irq_take ? irq_cause : trap_cause_w;

    logic [XLEN-1:0] mtvec_val, mepc_val, csr_rdata_commit;
    csr u_csr (
        .clk(clk), .rst(rst),
        .csr_access(csr_commit),
        .csr_addr(ex_mem_q.csr_addr),
        .csr_funct3(ex_mem_q.csr_funct3),
        .csr_wdata(ex_mem_q.csr_wdata),
        .csr_rdata(csr_rdata_commit),   // old CSR value -> write-back to rd
        .cycle_count(perf_cycle_count), .instret_count(perf_instr_retired),
        .trap_en(trap_take || irq_take),
        .trap_pc(trap_pc_w),
        .trap_cause(trap_cause_final),
        .trap_val(trap_val_w),
        .mtvec_out(mtvec_val),
        .mret_en(mret_take),
        .mepc_out(mepc_val),
        .irq_pending(irq_pending), .irq_cause(irq_cause)
    );

    // Trap/MRET redirect target computed here; signals declared near IF.
    assign trap_redirect     = trap_take || mret_take || irq_take || fencei_take;
    assign icache_invalidate = fencei_take;
    assign trap_target   = fencei_take            ? ex_mem_q.pc_plus4
                         : (trap_take || irq_take) ? mtvec_val
                         :                           mepc_val;

    // For a committing CSR instruction, the value written back to rd is the
    // OLD csr value. We fold it into the MEM-stage alu_result feeding MEM/WB,
    // since a CSR instruction doesn't use the ALU result for anything else.
    logic [XLEN-1:0] mem_result_for_wb;
    assign mem_result_for_wb = mem_fwd_value;  // same value used for forwarding

    // MEM/WB register

    // A trapping instruction must not commit its register write. Gate the
    // reg_write_en flowing into MEM/WB: on a trap, the offending instruction
    // writes no architectural register (only mepc/mcause change).
    logic reg_write_en_mem_gated;
    assign reg_write_en_mem_gated = ex_mem_q.reg_write_en && !(trap_take);

    mem_wb_t mem_wb_d, mem_wb_q;
    always_comb begin
        mem_wb_d               = '0;
        mem_wb_d.mem_read_data = mem_read_data_mem;
        mem_wb_d.alu_result    = mem_result_for_wb;
        mem_wb_d.pc_plus4      = ex_mem_q.pc_plus4;
        mem_wb_d.rd_addr       = ex_mem_q.rd_addr;
        mem_wb_d.reg_write_en  = reg_write_en_mem_gated;
        mem_wb_d.wb_src        = ex_mem_q.wb_src;
        mem_wb_d.valid         = ex_mem_q.valid;
    end

    mem_wb_reg u_mem_wb (
        .clk(clk), .rst(rst), .freeze(pipe_stall),
        .d(mem_wb_d), .q(mem_wb_q)
    );

    // Counter observations. `retired` is a genuinely retired instruction, not
    // a bubble; `mispredicted` is specifically a control-flow instruction the
    // predictor got wrong, which is narrower than "the pipe flushed".
    assign retired      = mem_wb_q.valid;
    assign mispredicted = id_ex_q.valid && is_cf_instr && mispredict;

    // WB stage
    always_comb begin
        case (mem_wb_q.wb_src)
            WB_SRC_MEM: write_back_data = mem_wb_q.mem_read_data; // loads
            WB_SRC_PC4: write_back_data = mem_wb_q.pc_plus4;      // jal / jalr return address
            default:    write_back_data = mem_wb_q.alu_result;    // r/i/lui/auipc, and CSR (folded in above)
        endcase
    end

`ifndef SYNTHESIS
    // ---- Retirement trace (RVFI-style naming) ----
    // Simulation-only, and deliberately NOT module ports: the PC and the
    // instruction word aren't otherwise needed past MEM, so carrying them
    // through mem_wb_reg would widen a real pipeline register by 64 bits to
    // serve a debug consumer. These two shadow registers mirror mem_wb_reg's
    // latch condition exactly (hold on rst, advance on !freeze), so they stay
    // in step with the instruction actually sitting in WB.
    //
    // tb/lockstep.cpp reads these by hierarchy and compares them against
    // Spike's commit log. RVFI names are used so the port is recognizable and
    // so a future formal flow can bind to it directly.
    // public_flat_rd: no RTL consumer, so Verilator would otherwise optimize
    // these away before the testbench could read them by hierarchy.
    logic [XLEN-1:0] rvfi_pc /* verilator public_flat_rd */;
    logic [ILEN-1:0] rvfi_insn /* verilator public_flat_rd */;
    always_ff @(posedge clk) begin
        if (rst) begin
            rvfi_pc   <= XLEN'(0);
            rvfi_insn <= ILEN'(0);
        end else if (!pipe_stall) begin
            rvfi_pc   <= ex_mem_q.pc;
            rvfi_insn <= ex_mem_q.instr;
        end
    end

    // ---- Test completion ----
    // Detected where the store *commits*, not by watching data_mem: with a
    // write-back cache the value can sit dirty in the cache indefinitely, so
    // a memory-side watcher would miss it or see it late. This fires on the
    // same cycle the store is architecturally performed, for every cache
    // configuration.
    logic            tohost_valid /* verilator public_flat_rd */;
    logic [XLEN-1:0] tohost_data  /* verilator public_flat_rd */;
    assign tohost_valid = ex_mem_q.valid && !pipe_stall && ex_mem_q.mem_write
                          && (ex_mem_q.alu_result == XLEN'(TOHOST_ADDR));
    assign tohost_data  = ex_mem_q.rs2_data;

    // One retirement per asserted cycle. Gated on !pipe_stall for the same
    // reason perf_instr_retired is: a frozen pipeline re-presents the same
    // instruction to WB every cycle, and an ungated valid would trace it once
    // per stalled cycle. This matches instret exactly, by construction.
    logic        rvfi_valid    /* verilator public_flat_rd */;
    logic [4:0]  rvfi_rd_addr  /* verilator public_flat_rd */;
    logic [XLEN-1:0] rvfi_rd_wdata /* verilator public_flat_rd */;
    assign rvfi_valid    = mem_wb_q.valid && !pipe_stall;
    assign rvfi_rd_addr  = (mem_wb_q.reg_write_en && mem_wb_q.rd_addr != 5'd0) ? mem_wb_q.rd_addr : 5'd0;
    assign rvfi_rd_wdata = (rvfi_rd_addr != 5'd0) ? write_back_data : XLEN'(0);
`endif
`ifndef SYNTHESIS
    // ---- Design invariants, checked every cycle of every test ----
    // Each property below is an invariant already explained in a comment
    // elsewhere in this file; this is that same reasoning made falsifiable.
    // Simulation-only: SVA isn't synthesized, and not every tool ignores it
    // silently the way Verilator's --lint-only does.

    // -- control-flow / redirect --
    a_trap_mret_excl: assert property (@(posedge clk) disable iff (rst)
        !(trap_take && mret_take));
    a_no_faulting_req: assert property (@(posedge clk) disable iff (rst)
        dmem_req |-> !ex_mem_q.exc_pending);
    // dbg_flush is a testbench-only cache-drain hook, not a hazard stall — it
    // can legitimately hold pipe_stall for as long as it takes to walk every
    // set/way of the D-cache, which is unbounded by this property's design.
    a_bubble_no_retire: assert property (@(posedge clk) disable iff (rst)
        !mem_wb_q.valid |-> !mem_wb_q.reg_write_en);
    a_trap_no_retire: assert property (@(posedge clk) disable iff (rst)
        trap_take |-> !reg_write_en_mem_gated);

    // -- forwarding --
    a_fwd_a_priority: assert property (@(posedge clk) disable iff (rst)
        (ex_mem_q.reg_write_en && ex_mem_q.rd_addr != 5'd0 && ex_mem_q.rd_addr == id_ex_q.rs1_addr)
        |-> forward_a == 2'b01);
    a_fwd_b_priority: assert property (@(posedge clk) disable iff (rst)
        (ex_mem_q.reg_write_en && ex_mem_q.rd_addr != 5'd0 && ex_mem_q.rd_addr == id_ex_q.rs2_addr)
        |-> forward_b == 2'b01);
    a_fwd_a_no_x0: assert property (@(posedge clk) disable iff (rst)
        id_ex_q.rs1_addr == 5'd0 |-> forward_a == 2'b00);
    a_fwd_b_no_x0: assert property (@(posedge clk) disable iff (rst)
        id_ex_q.rs2_addr == 5'd0 |-> forward_b == 2'b00);

    // -- interrupts (Phase 8) --
    // An interrupt and a synchronous trap must never commit together: they
    // write mepc/mcause from different sources, so both firing would corrupt
    // whichever lost.
    a_irq_exc_excl: assert property (@(posedge clk) disable iff (rst)
        !(irq_take && trap_take));
    a_irq_mret_excl: assert property (@(posedge clk) disable iff (rst)
        !(irq_take && mret_take));
    // An interrupt is only ever taken with interrupts globally enabled.
    a_irq_needs_mie: assert property (@(posedge clk) disable iff (rst)
        irq_take |-> irq_pending);
    // Taking an interrupt must disable them, or the handler re-enters itself.
    a_irq_disables_mie: assert property (@(posedge clk) disable iff (rst)
        irq_take |=> !u_csr.mstatus_mie);
    // An interrupt resumes at the *next* instruction, a trap re-runs the
    // faulting one. Getting these backwards silently drops or repeats work.
    a_irq_mepc_is_next: assert property (@(posedge clk) disable iff (rst)
        irq_take |-> (trap_pc_w == ex_mem_q.pc_plus4));
    a_trap_mepc_is_faulting: assert property (@(posedge clk) disable iff (rst)
        trap_take |-> (trap_pc_w == ex_mem_q.pc));
    // An interrupt lets the instruction in MEM complete; only a synchronous
    // trap annuls its register write.
    a_irq_preserves_write: assert property (@(posedge clk) disable iff (rst)
        (irq_take && ex_mem_q.reg_write_en) |-> reg_write_en_mem_gated);
    // mcause carries the interrupt bit for interrupts and not for traps.
    a_irq_cause_bit: assert property (@(posedge clk) disable iff (rst)
        irq_take |-> trap_cause_final[XLEN-1]);
    a_exc_cause_bit: assert property (@(posedge clk) disable iff (rst)
        trap_take |-> !trap_cause_final[XLEN-1]);
    // Any redirect out of the commit point is one of exactly three causes.
    a_redirect_accounted: assert property (@(posedge clk) disable iff (rst)
        trap_redirect |-> (trap_take || mret_take || irq_take || fencei_take));
    // A bubble never commits anything at the commit point.
    a_bubble_no_commit: assert property (@(posedge clk) disable iff (rst)
        !ex_mem_q.valid |-> !(trap_take || mret_take || irq_take || csr_commit || fencei_take));
    // The commit point is single-issue: at most one action per cycle.
    a_commit_onehot: assert property (@(posedge clk) disable iff (rst)
        $onehot0({trap_take, mret_take, irq_take, csr_commit, fencei_take}));

`endif

    // ---- Functional coverage ----
    // SystemVerilog covergroups aren't supported by this toolchain (COVERIGN);
    // cover property is the supported equivalent and feeds the same
    // --coverage database, read back with verilator_coverage. Crosses are
    // written out as explicit conjunctions since there's no native cross.
`ifdef VERILATOR
    logic cov_en; assign cov_en = !rst;

    // forward_a x forward_b (9 crosses)
    genvar gi, gj;
    generate
        for (gi = 0; gi < 3; gi++) begin : g_fwd_a
            for (gj = 0; gj < 3; gj++) begin : g_fwd_b
                cover property (@(posedge clk) disable iff (rst)
                    cov_en && forward_a == gi[1:0] && forward_b == gj[1:0]);
            end
        end
    endgenerate

    // predictor outcome: predicted_taken x actual_taken x target_match, only
    // meaningful for an actual control-flow instruction in EX
    logic cov_target_match;
    assign cov_target_match = (actual_target == id_ex_q.predicted_target);
    c_pred_tt_match:   cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && is_cf_instr && id_ex_q.predicted_taken && actual_taken && cov_target_match);
    c_pred_tt_mismatch: cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && is_cf_instr && id_ex_q.predicted_taken && actual_taken && !cov_target_match);
    c_pred_tn:          cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && is_cf_instr && id_ex_q.predicted_taken && !actual_taken);
    c_pred_nt:          cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && is_cf_instr && !id_ex_q.predicted_taken && actual_taken);
    c_pred_nn:          cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && is_cf_instr && !id_ex_q.predicted_taken && !actual_taken);
    c_false_predict:    cover property (@(posedge clk) disable iff (rst)
        cov_en && false_predict);

    // control-flow type (id_ex_q.ctrl.pc_src) x taken/not-taken
    c_branch_taken:    cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && id_ex_q.ctrl.pc_src == PC_SRC_BRANCH && actual_taken);
    c_branch_nottaken: cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && id_ex_q.ctrl.pc_src == PC_SRC_BRANCH && !actual_taken);
    c_jalr:            cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && id_ex_q.ctrl.pc_src == PC_SRC_JALR);
    c_jal:              cover property (@(posedge clk) disable iff (rst)
        cov_en && id_ex_q.valid && id_ex_q.ctrl.pc_src == PC_SRC_JAL);

    // trap cause, each implemented cause hit at least once
    c_cause_illegal:    cover property (@(posedge clk) disable iff (rst)
        cov_en && trap_take && trap_cause_w == CAUSE_ILLEGAL_INSTR);
    c_cause_mis_load:   cover property (@(posedge clk) disable iff (rst)
        cov_en && trap_take && trap_cause_w == CAUSE_MISALIGNED_LOAD);
    c_cause_mis_store:  cover property (@(posedge clk) disable iff (rst)
        cov_en && trap_take && trap_cause_w == CAUSE_MISALIGNED_STORE);
    c_cause_ecall:      cover property (@(posedge clk) disable iff (rst)
        cov_en && trap_take && trap_cause_w == CAUSE_ECALL_M);
    c_cause_ebreak:     cover property (@(posedge clk) disable iff (rst)
        cov_en && trap_take && trap_cause_w == CAUSE_BREAKPOINT);
    c_mret:             cover property (@(posedge clk) disable iff (rst)
        cov_en && mret_take);

    // hazard interactions
    c_load_use_and_mispredict: cover property (@(posedge clk) disable iff (rst)
        cov_en && load_use_stall && ex_flush);
    // trap_redirect only ever fires when !pipe_stall (see the commit-point
    // comment above), so the interesting cross is a trap-eligible instruction
    // parked in MEM *during* a stall, one cycle before it can commit.
    c_trap_pending_and_stall: cover property (@(posedge clk) disable iff (rst)
        cov_en && ex_mem_q.valid && ex_mem_q.exc_pending && pipe_stall);
`endif
endmodule

`default_nettype wire
