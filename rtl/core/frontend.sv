`default_nettype none

import rv32i_pkg::*;

// frontend.sv - instruction fetch: PC, branch prediction, I-cache, IF/ID.
//
// Split from the back end so the top level is wiring rather than logic. The
// boundary is the IF/ID register: everything that decides *which* instruction
// to fetch lives here, everything that decides what it *does* lives in
// backend.sv. The redirect inputs (mispredict, trap, load-use) all arrive
// from the back end, which is what makes this a front end rather than an
// independent fetch unit - there is no fetch queue, so a back-end stall
// stalls fetch directly.
module frontend #(
    parameter int ICACHE_BYTES       = 0,
    parameter int ICACHE_BLOCK_WORDS = 4,
    parameter int ICACHE_WAYS        = 1,
    parameter int IMEM_LATENCY       = 1,
    parameter int IMEM_DEPTH_WORDS   = 524288,
    parameter logic [XLEN-1:0] RESET_PC  = '0,
    parameter int BTB_IDX_BITS       = 6,
    parameter int BTB_TAG_BITS       = 10,
    parameter int GSHARE             = 0,
    parameter int RAS_DEPTH          = 8
) (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic        pipe_stall,       // whole-pipe freeze (either memory busy)

    // Redirects and holds, all resolved in the back end.
    input  var logic        load_use_stall,
    input  var logic        ex_flush,
    input  var logic [XLEN-1:0] ex_resolved_target,
    input  var logic        trap_redirect,
    input  var logic [XLEN-1:0] trap_target,
    input  var logic        icache_invalidate,   // FENCE.I committed in MEM

    // Predictor learning, from the EX-stage resolution.
    input  var logic        bp_update_en,
    input  var logic [XLEN-1:0] bp_update_pc,
    input  var logic        bp_update_taken,
    input  var logic [XLEN-1:0] bp_update_target,
    input  var logic [GHIST_BITS-1:0] bp_update_ghistory,

    output var if_id_t      if_id_q,          // the decoded-stage payload
    output var logic        imem_ready,       // 0 = fetch is stalling the pipe
    output var logic        icache_miss
);

    // IF stage
    logic [XLEN-1:0] pc_out, next_pc, pc_plus4_if;
    logic [ILEN-1:0] instr_if;

    pc #(.RESET_PC(RESET_PC)) u_pc ( .clk(clk), .rst(rst), .next_pc(next_pc), .pc_out(pc_out) );
    assign pc_plus4_if = pc_out + XLEN'(4);

    // Fetch path: optionally through the I-cache, otherwise straight to memory.
    logic [XLEN-1:0] ic_mem_addr;
    logic [ILEN-1:0] ic_mem_instr;
    logic        ic_mem_req, ic_mem_burst, ic_mem_ready;

    if (ICACHE_BYTES == 0) begin : g_no_icache
        assign ic_mem_addr  = pc_out;
        assign ic_mem_req   = 1'b1;   // bare fetch: every access is independent
        assign ic_mem_burst = 1'b0;
        assign instr_if     = ic_mem_instr;
        assign imem_ready   = ic_mem_ready;
        assign icache_miss  = 1'b0;
        // No cache to invalidate: fetch already goes straight to memory, so
        // FENCE.I is a no-op here rather than being silently wrong.
        logic unused_inval;
        assign unused_inval = icache_invalidate;
    end else begin : g_icache
        icache #(
            .BYTES(ICACHE_BYTES),
            .BLOCK_WORDS(ICACHE_BLOCK_WORDS),
            .WAYS(ICACHE_WAYS)
        ) u_icache (
            .clk(clk), .rst(rst),
            .invalidate(icache_invalidate),
            .addr(pc_out), .instr(instr_if), .ready(imem_ready),
            .mem_addr(ic_mem_addr), .mem_req(ic_mem_req), .mem_burst(ic_mem_burst),
            .mem_instr(ic_mem_instr), .mem_ready(ic_mem_ready),
            .miss_pulse(icache_miss)
        );
    end

    instr_mem #(.LATENCY(IMEM_LATENCY), .DEPTH_WORDS(IMEM_DEPTH_WORDS)) u_instr_mem (
        .clk(clk), .rst(rst),
        .req(ic_mem_req), .burst(ic_mem_burst),
        .addr(ic_mem_addr), .instr(ic_mem_instr), .ready(ic_mem_ready)
    );

    // Front-end branch prediction: index BHT+BTB with the fetch PC. On a
    // predicted-taken hit we redirect the very next fetch to the cached
    // target, so a correctly-predicted taken branch costs zero penalty.
    logic        predict_taken_if;
    logic [XLEN-1:0] predict_target_if;
    logic [GHIST_BITS-1:0] predict_ghistory_if;

    branch_predictor #(
        .IDX_BITS(BTB_IDX_BITS), .TAG_BITS(BTB_TAG_BITS), .GSHARE(GSHARE)
    ) u_branch_predictor (
        .clk(clk), .rst(rst),
        .pc_predict(pc_out),
        .predict_taken(predict_taken_if),
        .predict_target(predict_target_if),
        .predict_ghistory(predict_ghistory_if),
        .update_en(bp_update_en),
        .update_pc(bp_update_pc),
        .update_taken(bp_update_taken),
        .update_target(bp_update_target),
        .update_ghistory(bp_update_ghistory)
    );

    // Return-address stack. A cheap fetch-time pre-decode (opcode/rd/rs1 of
    // instr_if, ahead of and independent from control.sv's real decode)
    // classifies calls/returns per the RISC-V hint convention: rd/rs1 in
    // {x1,x5} mark a link register.
    logic [4:0] rd_if, rs1_if;
    assign rd_if  = instr_if[11:7];
    assign rs1_if = instr_if[19:15];
    function automatic logic is_link_reg(input logic [4:0] r);
        is_link_reg = (r == 5'd1) || (r == 5'd5);
    endfunction
    logic is_jal_if, is_jalr_if, call_rd_if, call_rs1_if;
    assign is_jal_if   = (instr_if[6:0] == OPCODE_JAL);
    assign is_jalr_if  = (instr_if[6:0] == OPCODE_JALR);
    assign call_rd_if  = is_link_reg(rd_if);
    assign call_rs1_if = is_link_reg(rs1_if);

    // A fetch is only "real" (worth pushing/popping for) on the same cycle
    // if_id_reg would actually latch it - re-presentations of a frozen or
    // held fetch must not push/pop twice.
    logic fetch_accept;
    assign fetch_accept = !pipe_stall && !load_use_stall;

    logic ras_push, ras_pop, ras_pop_valid;
    logic [XLEN-1:0] ras_pop_addr;
    // JAL/JALR with a link rd: call, push the return address (pc+4).
    assign ras_push = fetch_accept && call_rd_if && (is_jal_if || is_jalr_if);
    // JALR with a link rs1: return, pop - except rd==rs1 (both the same link
    // register), which the RISC-V hint table calls a call, not a return.
    assign ras_pop   = fetch_accept && is_jalr_if && call_rs1_if
                       && !(call_rd_if && (rd_if == rs1_if));

    // RAS_DEPTH = 0 disables the RAS entirely, the same convention
    // ICACHE_BYTES/DCACHE_BYTES = 0 use to bypass a structure rather than
    // instantiate a degenerate (zero-entry) one.
    if (RAS_DEPTH == 0) begin : g_no_ras
        assign ras_pop_valid = 1'b0;
        assign ras_pop_addr  = XLEN'(0);
    end else begin : g_ras
        ras #(.DEPTH(RAS_DEPTH)) u_ras (
            .clk(clk), .rst(rst),
            .push_en(ras_push), .push_addr(pc_plus4_if),
            .pop_en(ras_pop), .pop_valid(ras_pop_valid), .pop_addr(ras_pop_addr)
        );
    end

    // RAS wins over the plain BTB when it has an answer: a BTB entry for a
    // `ret` shared by multiple call sites can only remember the most recent
    // caller, while the RAS gives the address actually pushed for *this*
    // call chain. An empty/wrong-depth RAS (pop_valid=0) falls back to
    // whatever the BTB has - not guaranteed right, but better than assuming
    // not-taken on an instruction fetch-time decode already knows is an
    // unconditional jump.
    logic        predict_taken_final;
    logic [XLEN-1:0] predict_target_final;
    assign predict_taken_final  = ras_pop_valid ? 1'b1          : predict_taken_if;
    assign predict_target_final = ras_pop_valid ? ras_pop_addr  : predict_target_if;

    // Next-PC priority: memory stall (freeze) > trap/MRET (commit point) >
    // EX misprediction recovery > load-use stall (hold) > front-end
    // predicted-taken redirect (BTB or RAS) > sequential.
    assign next_pc = pipe_stall          ? pc_out                 // freeze: re-present same fetch
                    : trap_redirect       ? trap_target
                    : ex_flush            ? ex_resolved_target
                    : load_use_stall     ? pc_out                 // hold: re-fetch same address
                    : predict_taken_final ? predict_target_final  // speculative taken redirect
                    : pc_plus4_if;

    // IF/ID register
    if_id_t if_id_d;
    always_comb begin
        if_id_d                  = '0;
        if_id_d.pc               = pc_out;
        if_id_d.pc_plus4         = pc_plus4_if;
        if_id_d.instr            = instr_if;
        if_id_d.predicted_taken  = predict_taken_final;
        if_id_d.predicted_target = predict_target_final;
        if_id_d.predict_ghistory = predict_ghistory_if;
        if_id_d.valid            = 1'b1;   // IF always produces a real fetched instruction
    end

    if_id_reg u_if_id (
        .clk(clk), .rst(rst),
        .flush(ex_flush || trap_redirect),
        .stall(load_use_stall),
        .freeze(pipe_stall),
        .d(if_id_d), .q(if_id_q)
    );

`ifndef SYNTHESIS
    // The next-PC priority mux is this module's central claim; these check it.
    a_freeze_pc_stable: assert property (@(posedge clk) disable iff (rst)
        pipe_stall |=> $stable(pc_out));
    a_redirect_priority_trap: assert property (@(posedge clk) disable iff (rst)
        (trap_redirect && !pipe_stall) |-> (next_pc == trap_target));
    a_redirect_priority_mispredict: assert property (@(posedge clk) disable iff (rst)
        (ex_flush && !pipe_stall && !trap_redirect) |-> (next_pc == ex_resolved_target));
`endif

endmodule

`default_nettype wire
