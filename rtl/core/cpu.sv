`default_nettype none

// cpu.sv - top-level module: 5-stage pipelined RV32I CPU.
module cpu #(
    parameter int IMEM_LATENCY = 1,
    parameter int DMEM_LATENCY = 1,
    // ICACHE_BYTES = 0 bypasses the cache entirely and wires fetch straight to
    // instr_mem, so the no-cache baseline stays bit-for-bit what it was before
    // the cache existed rather than being a degenerate cache configuration.
    parameter int ICACHE_BYTES       = 0,
    parameter int ICACHE_BLOCK_WORDS = 4,
    parameter int ICACHE_WAYS        = 1,
    parameter int DCACHE_BYTES       = 0,
    parameter int DCACHE_BLOCK_WORDS = 4,
    parameter int DCACHE_WAYS        = 1,
    parameter int DCACHE_WRITE_BACK  = 0,
    // Branch predictor: BTB size/tag, direction-table hash (0=bimodal,
    // 1=gshare), and the return-address-stack depth. See branch_predictor.sv
    // and ras.sv.
    parameter int BTB_IDX_BITS       = 6,
    parameter int BTB_TAG_BITS       = 10,
    parameter int GSHARE             = 0,
    parameter int RAS_DEPTH          = 8,
    // Reset vector. 0 for every normal build; the lockstep flow overrides it
    // so the RTL's PC matches the address Spike's memory map forces programs
    // to link at (see tools/lockstep.py).
    parameter logic [XLEN-1:0] RESET_PC  = '0,
    // Backing-memory depth. Defaults match the pre-parameterization sizes
    // (2MB instruction ROM, 64KB data RAM) so simulation is unaffected;
    // synthesis overrides these to fit a target device's BRAM budget - see
    // syn/build.tcl.
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
    // Debug: drive high to write every dirty D-cache line back to memory, and
    // wait for dbg_flush_done. Only meaningful for a write-back D-cache, where
    // memory on its own no longer holds all of architectural state.
    input  var logic        dbg_flush,
    output var logic        dbg_flush_done
);


    // The two halves. The front end decides which instruction to fetch; the
    // back end decides what it does. Everything crossing between them is in
    // the port lists below - there is no shared state.
    if_id_t if_id_q;

    // Memory stall. Either memory being busy freezes the entire pipeline for
    // the cycle - PC, every pipeline register, the predictor, the CSR file and
    // the counters all hold, so the machine resumes exactly where it left off.
    // Computed here because it is the one signal genuinely owned by neither
    // half: each contributes a ready, and both consume the result.
    //
    // ponytail: one global freeze, rather than letting the back end drain
    // through an instruction-fetch miss. That costs some overlap the real
    // thing would recover, and it inflates baseline and post-cache numbers
    // alike. Decoupling the front end needs a fetch buffer - worth it only if
    // the I-cache miss rate stays high enough to care.
    logic imem_ready, dmem_ready, pipe_stall;
    assign pipe_stall = !imem_ready || !dmem_ready;

    // Back-end -> front-end redirects.
    logic        load_use_stall, ex_flush, trap_redirect;
    logic [XLEN-1:0] ex_resolved_target, trap_target;
    logic        bp_update_en, bp_update_taken;
    logic [XLEN-1:0] bp_update_pc, bp_update_target;
    logic [GHIST_BITS-1:0] bp_update_ghistory;

    // Counter observations.
    logic icache_miss, dcache_access, dcache_miss, retired, mispredicted;
    logic icache_invalidate;

    frontend #(
        .ICACHE_BYTES(ICACHE_BYTES),
        .ICACHE_BLOCK_WORDS(ICACHE_BLOCK_WORDS),
        .ICACHE_WAYS(ICACHE_WAYS),
        .IMEM_LATENCY(IMEM_LATENCY),
        .IMEM_DEPTH_WORDS(IMEM_DEPTH_WORDS),
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
        .if_id_q(if_id_q), .imem_ready(imem_ready), .icache_miss(icache_miss)
    );

    backend #(
        .DCACHE_BYTES(DCACHE_BYTES),
        .DCACHE_BLOCK_WORDS(DCACHE_BLOCK_WORDS),
        .DCACHE_WAYS(DCACHE_WAYS),
        .DCACHE_WRITE_BACK(DCACHE_WRITE_BACK),
        .DMEM_LATENCY(DMEM_LATENCY),
        .DMEM_DEPTH_WORDS(DMEM_DEPTH_WORDS)
    ) u_backend (
        .clk(clk), .rst(rst), .pipe_stall(pipe_stall),
        .if_id_q(if_id_q),
        .load_use_stall(load_use_stall),
        .ex_flush(ex_flush), .ex_resolved_target(ex_resolved_target),
        .trap_redirect(trap_redirect), .trap_target(trap_target),
        .icache_invalidate(icache_invalidate),
        .bp_update_en(bp_update_en), .bp_update_pc(bp_update_pc),
        .bp_update_taken(bp_update_taken), .bp_update_target(bp_update_target),
        .bp_update_ghistory(bp_update_ghistory),
        .dmem_ready(dmem_ready),
        .dcache_access(dcache_access), .dcache_miss(dcache_miss),
        .retired(retired), .mispredicted(mispredicted),
        .perf_cycle_count(perf_cycle_count), .perf_instr_retired(perf_instr_retired),
        .dbg_flush(dbg_flush), .dbg_flush_done(dbg_flush_done)
    );

    perf_counters u_perf (
        .clk(clk), .rst(rst),
        .pipe_stall(pipe_stall),
        .retired(retired),
        .load_use_stall(load_use_stall),
        .flushed(ex_flush || trap_redirect),
        .mispredicted(mispredicted),
        .branch_resolved(bp_update_en),
        .icache_miss(icache_miss),
        .dcache_access(dcache_access),
        .dcache_miss(dcache_miss),
        .cycle_count(perf_cycle_count),
        .instr_retired(perf_instr_retired),
        .stall_count(perf_stall_count),
        .flush_count(perf_flush_count),
        .mispredict_count(perf_mispredict_count),
        .branch_count(perf_branch_count),
        .mem_stall_count(perf_mem_stall_count),
        .icache_access(perf_icache_access),
        .icache_miss_count(perf_icache_miss),
        .dcache_access_count(perf_dcache_access),
        .dcache_miss_count(perf_dcache_miss)
    );

`ifndef SYNTHESIS
    // The only invariant that belongs to neither half: pipe_stall is formed
    // here, and dbg_flush is a top-level port.
    //
    // dbg_flush is a testbench-only cache-drain hook, not a hazard stall - it
    // can legitimately hold pipe_stall for as long as it takes to walk every
    // set/way of the D-cache, which is unbounded by this property's design.
    a_stall_bounded: assert property (@(posedge clk) disable iff (rst || dbg_flush)
        pipe_stall |-> ##[1:256] (pipe_stall == 1'b0));
`endif

endmodule

`default_nettype wire
