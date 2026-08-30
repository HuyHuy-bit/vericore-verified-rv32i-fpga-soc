`default_nettype none

import rv32i_pkg::*;

module rv32i_core #(
    parameter int ICACHE_BYTES       = 0,
    parameter int ICACHE_BLOCK_WORDS = 4,
    parameter int ICACHE_WAYS        = 1,
    parameter int DCACHE_BYTES       = 0,
    parameter int DCACHE_BLOCK_WORDS = 4,
    parameter int DCACHE_WAYS        = 1,
    parameter int DCACHE_WRITE_BACK  = 0,
    parameter int BTB_IDX_BITS       = 6,
    parameter int BTB_TAG_BITS       = 10,
    parameter int GSHARE             = 0,
    parameter int RAS_DEPTH          = 8,
    parameter logic [XLEN-1:0] RESET_PC = '0
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic irq_external,
    output var logic imem_req,
    output var logic imem_burst,
    output var logic [XLEN-1:0] imem_addr,
    input  var logic [ILEN-1:0] imem_rdata,
    input  var logic imem_ready,
    output var logic dmem_req,
    output var logic dmem_burst,
    output var logic [XLEN-1:0] dmem_addr,
    output var logic [XBYTES-1:0] dmem_wstrb,
    output var logic [XLEN-1:0] dmem_wdata,
    input  var logic [XLEN-1:0] dmem_rdata,
    input  var logic dmem_ready,
    output var logic [XLEN-1:0] perf_cycle_count,
    output var logic [XLEN-1:0] perf_instr_retired,
    output var logic [XLEN-1:0] perf_stall_count,
    output var logic [XLEN-1:0] perf_flush_count,
    output var logic [XLEN-1:0] perf_mispredict_count,
    output var logic [XLEN-1:0] perf_branch_count,
    output var logic [XLEN-1:0] perf_mem_stall_count,
    output var logic [XLEN-1:0] perf_icache_access,
    output var logic [XLEN-1:0] perf_icache_miss,
    output var logic [XLEN-1:0] perf_dcache_access,
    output var logic [XLEN-1:0] perf_dcache_miss,
    input  var logic dbg_flush,
    output var logic dbg_flush_done,
    output var logic retired_debug
);
    if_id_t if_id_q;
    logic fetch_ready, data_ready, pipe_stall;
    logic load_use_stall, ex_flush, trap_redirect;
    logic [XLEN-1:0] ex_resolved_target, trap_target;
    logic bp_update_en, bp_update_taken;
    logic [XLEN-1:0] bp_update_pc, bp_update_target;
    logic [GHIST_BITS-1:0] bp_update_ghistory;
    logic icache_miss, dcache_access, dcache_miss, retired, mispredicted;
    logic icache_invalidate;

    assign pipe_stall = !fetch_ready || !data_ready;
    assign retired_debug = retired;

    frontend #(
        .ICACHE_BYTES(ICACHE_BYTES),
        .ICACHE_BLOCK_WORDS(ICACHE_BLOCK_WORDS),
        .ICACHE_WAYS(ICACHE_WAYS),
        .RESET_PC(RESET_PC),
        .BTB_IDX_BITS(BTB_IDX_BITS),
        .BTB_TAG_BITS(BTB_TAG_BITS),
        .GSHARE(GSHARE),
        .RAS_DEPTH(RAS_DEPTH)
    ) u_frontend (
        .clk(clk), .rst(rst), .pipe_stall(pipe_stall),
        .load_use_stall(load_use_stall),
        .ex_flush(ex_flush), .ex_resolved_target(ex_resolved_target),
        .trap_redirect(trap_redirect), .trap_target(trap_target),
        .icache_invalidate(icache_invalidate),
        .bp_update_en(bp_update_en), .bp_update_pc(bp_update_pc),
        .bp_update_taken(bp_update_taken), .bp_update_target(bp_update_target),
        .bp_update_ghistory(bp_update_ghistory),
        .if_id_q(if_id_q), .fetch_ready(fetch_ready), .icache_miss(icache_miss),
        .imem_req(imem_req), .imem_burst(imem_burst), .imem_addr(imem_addr),
        .imem_rdata(imem_rdata), .imem_ready(imem_ready)
    );

    backend #(
        .DCACHE_BYTES(DCACHE_BYTES),
        .DCACHE_BLOCK_WORDS(DCACHE_BLOCK_WORDS),
        .DCACHE_WAYS(DCACHE_WAYS),
        .DCACHE_WRITE_BACK(DCACHE_WRITE_BACK)
    ) u_backend (
        .clk(clk), .rst(rst), .irq_external(irq_external),
        .pipe_stall(pipe_stall), .if_id_q(if_id_q),
        .load_use_stall(load_use_stall),
        .ex_flush(ex_flush), .ex_resolved_target(ex_resolved_target),
        .trap_redirect(trap_redirect), .trap_target(trap_target),
        .icache_invalidate(icache_invalidate),
        .bp_update_en(bp_update_en), .bp_update_pc(bp_update_pc),
        .bp_update_taken(bp_update_taken), .bp_update_target(bp_update_target),
        .bp_update_ghistory(bp_update_ghistory),
        .dmem_ready(data_ready),
        .dcache_access(dcache_access), .dcache_miss(dcache_miss),
        .retired(retired), .mispredicted(mispredicted),
        .perf_cycle_count(perf_cycle_count), .perf_instr_retired(perf_instr_retired),
        .dbg_flush(dbg_flush), .dbg_flush_done(dbg_flush_done),
        .ext_dmem_req(dmem_req), .ext_dmem_burst(dmem_burst),
        .ext_dmem_addr(dmem_addr), .ext_dmem_wstrb(dmem_wstrb),
        .ext_dmem_wdata(dmem_wdata), .ext_dmem_rdata(dmem_rdata),
        .ext_dmem_ready(dmem_ready)
    );

    perf_counters u_perf (
        .clk(clk), .rst(rst), .pipe_stall(pipe_stall),
        .retired(retired), .load_use_stall(load_use_stall),
        .flushed(ex_flush || trap_redirect), .mispredicted(mispredicted),
        .branch_resolved(bp_update_en), .icache_miss(icache_miss),
        .dcache_access(dcache_access), .dcache_miss(dcache_miss),
        .cycle_count(perf_cycle_count), .instr_retired(perf_instr_retired),
        .stall_count(perf_stall_count), .flush_count(perf_flush_count),
        .mispredict_count(perf_mispredict_count), .branch_count(perf_branch_count),
        .mem_stall_count(perf_mem_stall_count), .icache_access(perf_icache_access),
        .icache_miss_count(perf_icache_miss), .dcache_access_count(perf_dcache_access),
        .dcache_miss_count(perf_dcache_miss)
    );

`ifndef SYNTHESIS
    a_stall_bounded: assert property (@(posedge clk) disable iff (rst || dbg_flush)
        pipe_stall |-> ##[1:256] (pipe_stall == 1'b0));
`endif
endmodule

`default_nettype wire
