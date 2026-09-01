`default_nettype none

import rv32i_pkg::*;

module cpu #(
    parameter int IMEM_LATENCY = 1,
    parameter int DMEM_LATENCY = 1,
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
    parameter logic [XLEN-1:0] RESET_PC = '0,
    parameter int IMEM_DEPTH_WORDS   = 524288,
    parameter int DMEM_DEPTH_WORDS   = 16384
) (
    input  var logic clk,
    input  var logic rst,
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
    output var logic dbg_flush_done
);
    logic imem_req, imem_burst, imem_ready;
    logic [XLEN-1:0] imem_addr;
    logic [ILEN-1:0] imem_rdata;
    logic dmem_req, dmem_burst, dmem_ready;
    logic [XLEN-1:0] dmem_addr, dmem_wdata, dmem_rdata;
    logic [XBYTES-1:0] dmem_wstrb;
    logic retired_debug;

    rv32i_core #(
        .ICACHE_BYTES(ICACHE_BYTES),
        .ICACHE_BLOCK_WORDS(ICACHE_BLOCK_WORDS),
        .ICACHE_WAYS(ICACHE_WAYS),
        .DCACHE_BYTES(DCACHE_BYTES),
        .DCACHE_BLOCK_WORDS(DCACHE_BLOCK_WORDS),
        .DCACHE_WAYS(DCACHE_WAYS),
        .DCACHE_WRITE_BACK(DCACHE_WRITE_BACK),
        .DCACHEABLE_BASE(XLEN'(0)),
        .DCACHEABLE_MASK(XLEN'(0)),
        .BTB_IDX_BITS(BTB_IDX_BITS),
        .BTB_TAG_BITS(BTB_TAG_BITS),
        .GSHARE(GSHARE),
        .RAS_DEPTH(RAS_DEPTH),
        .RESET_PC(RESET_PC)
    ) u_core (
        .clk(clk), .rst(rst), .irq_external(1'b0),
        .imem_req(imem_req), .imem_burst(imem_burst), .imem_addr(imem_addr),
        .imem_rdata(imem_rdata), .imem_ready(imem_ready),
        .dmem_req(dmem_req), .dmem_burst(dmem_burst), .dmem_addr(dmem_addr),
        .dmem_wstrb(dmem_wstrb), .dmem_wdata(dmem_wdata),
        .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready),
        .perf_cycle_count(perf_cycle_count), .perf_instr_retired(perf_instr_retired),
        .perf_stall_count(perf_stall_count), .perf_flush_count(perf_flush_count),
        .perf_mispredict_count(perf_mispredict_count), .perf_branch_count(perf_branch_count),
        .perf_mem_stall_count(perf_mem_stall_count),
        .perf_icache_access(perf_icache_access), .perf_icache_miss(perf_icache_miss),
        .perf_dcache_access(perf_dcache_access), .perf_dcache_miss(perf_dcache_miss),
        .dbg_flush(dbg_flush), .dbg_flush_done(dbg_flush_done),
        .retired_debug(retired_debug)
    );

    instr_mem #(
        .LATENCY(IMEM_LATENCY),
        .DEPTH_WORDS(IMEM_DEPTH_WORDS)
    ) u_instr_mem (
        .clk(clk), .rst(rst),
        .req(imem_req), .burst(imem_burst),
        .addr(imem_addr), .instr(imem_rdata), .ready(imem_ready)
    );

    data_mem #(
        .LATENCY(DMEM_LATENCY),
        .DEPTH_WORDS(DMEM_DEPTH_WORDS)
    ) u_data_mem (
        .clk(clk), .rst(rst),
        .req(dmem_req), .burst(dmem_burst),
        .addr(dmem_addr), .byte_en(dmem_wstrb),
        .write_word(dmem_wdata), .read_word(dmem_rdata), .ready(dmem_ready)
    );
endmodule

`default_nettype wire
