// dcache.sv - blocking data cache, write-through or write-back.
//
// Speaks the word + byte-enable vocabulary that lsu.sv produces, so it never
// has to know about lb/lh/sb/sh. A nonzero byte_en means the access is a store.
//
// WRITE_BACK = 0: write-through, no write-allocate.
//   Every store goes to memory and pays full latency whether or not the line is
//   resident; a store that hits also updates the cached copy so later loads see
//   it. Stores never allocate. Simple, and no line is ever dirty.
//
// WRITE_BACK = 1: write-back, write-allocate.
//   A store that hits updates the line, marks it dirty, and completes in one
//   cycle. A miss allocates, first flushing the victim if it is dirty. Memory
//   sees whole blocks instead of individual stores.
//
// The two share one FSM because the difference is small and localised, and
// because the point of building both is to measure the gap rather than to
// assert which one is better.
`default_nettype none

import rv32i_pkg::*;

module dcache #(
    parameter int BYTES       = 1024,
    parameter int BLOCK_WORDS = 4,
    parameter int WAYS        = 1,
    parameter int WRITE_BACK  = 0
) (
    input  var logic        clk,
    input  var logic        rst,

    // CPU side
    input  var logic        req,          // a load or store is presented
    input  var logic        cacheable,
    input  var logic        advance,
    input  var logic [XLEN-1:0] addr,
    input  var logic [XBYTES-1:0] byte_en,      // nonzero => store
    input  var logic [XLEN-1:0] write_word,   // already shifted into its lane
    output var logic [XLEN-1:0] read_word,
    output var logic        ready,

    // backing memory side
    output var logic [XLEN-1:0] mem_addr,
    output var logic        mem_req,
    output var logic        mem_burst,
    output var logic [XBYTES-1:0] mem_byte_en,
    output var logic [XLEN-1:0] mem_write_word,
    input  var logic [XLEN-1:0] mem_read_word,
    input  var logic        mem_ready,

    // Debug/maintenance: walk every line and write back the dirty ones, so the
    // backing memory holds architectural state again. Write-back means memory
    // alone is no longer the whole picture - the compliance harness reads its
    // signature straight out of data_mem, and without this it would be reading
    // stale words for every value still sitting dirty in the cache. This is the
    // same operation a fence would need.
    input  var logic        flush_req,
    output var logic        flush_done,

    // Counters are (access, miss), never (access, hit). A hit level is true
    // again the instant a refill lands, so counting it when the pipeline
    // advances scores every miss as a hit; misses have to be counted where the
    // decision is made, not where the access completes.
    output var logic        access,
    output var logic        miss_pulse
);
    localparam int SETS  = BYTES / (BLOCK_WORDS * 4 * WAYS);
    localparam int OFFW  = (BLOCK_WORDS <= 1) ? 1 : $clog2(BLOCK_WORDS);
    localparam int IDXW  = (SETS        <= 1) ? 1 : $clog2(SETS);
    localparam int OFFSH = (BLOCK_WORDS <= 1) ? 0 : OFFW;
    localparam int IDXSH = (SETS        <= 1) ? 0 : IDXW;
    localparam int TAGW  = 32 - 2 - OFFSH - IDXSH;
    localparam int WAYW  = (WAYS <= 1) ? 1 : $clog2(WAYS);
    localparam int FSW   = IDXW + 1;   // must hold SETS itself, not just SETS-1

    localparam logic [1:0] S_IDLE = 2'd0, S_WB = 2'd1, S_FILL = 2'd2, S_FLUSH = 2'd3;

    initial begin
        if (SETS * WAYS * BLOCK_WORDS * 4 != BYTES) begin
            $fatal(1, "dcache: BYTES(%0d) must equal SETS*WAYS*BLOCK_WORDS*4", BYTES);
        end
    end

    // Tag/valid/dirty stay small flip-flop arrays - narrow, and read
    // combinationally every cycle for the tag compare. The 32-bit-wide data
    // payload is the one worth handing to Block RAM; see g_way below.
    logic [TAGW-1:0] tag  [WAYS][SETS];
    logic            vld  [WAYS][SETS];
    logic            drty [WAYS][SETS];
    logic [WAYW-1:0] victim[SETS];

    // ---- address split ----
    logic [XLEN-1:0]     word_addr, blk_addr;
    logic [OFFW-1:0] off;
    logic [IDXW-1:0] idx;
    logic [TAGW-1:0] tg;

    assign word_addr = addr >> 2;
    assign blk_addr  = word_addr >> OFFSH;
    assign off       = (BLOCK_WORDS <= 1) ? '0 : OFFW'(word_addr);
    assign idx       = (SETS        <= 1) ? '0 : IDXW'(blk_addr);
    assign tg        = TAGW'(blk_addr >> IDXSH);

    logic [WAYS-1:0] way_hit;
    for (genvar w = 0; w < WAYS; w++) begin : g_ways
        assign way_hit[w] = vld[w][idx] && (tag[w][idx] == tg);
    end

    logic [WAYW-1:0] hit_way;
    always_comb begin
        hit_way = '0;
        for (int w = 0; w < WAYS; w++) begin
            if (way_hit[w]) hit_way = WAYW'(w);
        end
    end

    logic            is_store, line_present, wt_store, bypass, direct_request;
    logic            flush_start, flush_complete;
    assign is_store     = |byte_en;
    assign line_present = |way_hit;
    // A write-through store always goes to memory, resident or not.
    assign wt_store     = (WRITE_BACK == 0) && is_store;
    assign flush_start  = (state == S_IDLE) && flush_req && !flush_complete
                          && !direct_active && !direct_done;
    assign bypass       = (state == S_IDLE) && req && !cacheable && !flush_start;
    assign direct_request = bypass || ((state == S_IDLE) && !flush_start
                            && req && cacheable && wt_store);

    logic [1:0]      state;
    logic [OFFW-1:0] fill_word, wb_word;
    logic [WAYW-1:0] fill_way;
    logic direct_active;
    logic direct_done;
    logic [XLEN-1:0] direct_read_word;

    always_ff @(posedge clk) begin
        if (rst) begin
            direct_active <= 1'b0;
            direct_done <= 1'b0;
            direct_read_word <= '0;
        end else if (direct_done) begin
            if (!req || advance)
                direct_done <= 1'b0;
        end else if (direct_active) begin
            if (!req) begin
                direct_active <= 1'b0;
            end else if (mem_ready) begin
                direct_active <= 1'b0;
                if (!advance) begin
                    direct_done <= 1'b1;
                    direct_read_word <= mem_read_word;
                end
            end
        end else if (direct_request) begin
            if (mem_ready) begin
                if (!advance) begin
                    direct_done <= 1'b1;
                    direct_read_word <= mem_read_word;
                end
            end else begin
                direct_active <= 1'b1;
            end
        end
    end

    // The victim being written back. Held separately from idx/fill_way because
    // a flush walks lines unrelated to whatever address is on the CPU port.
    logic [IDXW-1:0] wb_idx;
    logic [WAYW-1:0] wb_way;
    logic            flushing;      // this writeback belongs to a flush walk
    logic [FSW-1:0]  flush_set;
    logic [WAYW-1:0] flush_way;

    assign flush_done = flush_complete;

    // ---- data storage: WAYS parallel single-way banks ----
    // One 2D array per way (a flat [SETS][BLOCK_WORDS], byte-enabled write,
    // registered read) instead of one [WAYS][SETS][BLOCK_WORDS] array
    // indexed by a runtime way select: the combined 3D-array-plus-way-mux
    // form doesn't match any BRAM inference template on Xilinx parts and
    // synthesizes to flip-flops regardless of the read being registered.
    // WAYS separate single-way arrays, read together and muxed *after* the
    // register, is also how a real set-associative cache's data array is
    // built in hardware - this restructuring isn't a workaround, it's the
    // actual right shape.
    //
    // Both consumers (a CPU-side hit load and the write-back flush path)
    // share one read address and one registered output per way, since the
    // two are mutually exclusive in time (loads only resolve in S_IDLE,
    // write-back only runs outside it) - the shared port costs nothing
    // niether path would have paid alone, and it's one BRAM read port
    // instead of needing two.
    logic [IDXW-1:0] rd_idx;
    logic [OFFW-1:0] rd_off;
    assign rd_idx = (state == S_WB) ? wb_idx  : idx;
    assign rd_off = (state == S_WB) ? wb_word : off;

    // Which way's registered output is the one that matters, delayed to
    // land on the same cycle the read it corresponds to becomes available.
    logic [WAYW-1:0] sel_way_reg;
    always_ff @(posedge clk) sel_way_reg <= (state == S_WB) ? wb_way : hit_way;

    // A write this cycle, and which way it targets - shared by the
    // write-through merge and the write-back-mode store-hit update, since
    // both write hit_way/idx/off with byte_en/write_word.
    logic wr_en;
    assign wr_en = (state == S_IDLE) && !flush_start
                   && req && cacheable && line_present &&
                   ((wt_store && mem_ready) || (!wt_store && is_store));

    // A refill word landing this cycle, and which way it targets.
    logic fill_en;
    assign fill_en = (state == S_FILL) && mem_ready;

    // Flat 1D, ram_style forced to block, read+write in one always_ff: the
    // canonical Xilinx byte-enable-BRAM template.
    //
    // Critically, ONE write address. A store writes `off` within the set and
    // a refill writes `fill_word`; expressing those as two separate indexed
    // assignments in the same block is what made Vivado report
    //   "Infeasible attribute ram_style = block ... implementing using LUTRAM"
    // and drop to distributed RAM, because a BRAM write port physically has
    // exactly one address input. Muxing address/data/byte-enable ahead of
    // the port - which is what the hardware does anyway - is the difference
    // between the array landing in Block RAM and landing in LUTs.
    //
    // The two sources are mutually exclusive by construction (wr_en requires
    // S_IDLE, fill_en requires S_FILL), so the mux needs no arbitration.
    localparam int WORDS = SETS * BLOCK_WORDS;
    localparam int AW    = (WORDS <= 1) ? 1 : $clog2(WORDS);

    logic [AW-1:0] wr_addr, rd_addr;
    logic [XLEN-1:0]   wr_data;
    logic [3:0]    wr_be;
    assign rd_addr = AW'(rd_idx * BLOCK_WORDS + 32'(rd_off));
    assign wr_addr = fill_en ? AW'(idx * BLOCK_WORDS + 32'(fill_word))
                             : AW'(idx * BLOCK_WORDS + 32'(off));
    assign wr_data = fill_en ? mem_read_word : write_word;
    assign wr_be   = fill_en ? 4'b1111       : byte_en;

    logic [XLEN-1:0] way_rd_reg [WAYS];
    for (genvar w = 0; w < WAYS; w++) begin : g_way
        (* ram_style = "block" *) logic [XLEN-1:0] way_mem [0:WORDS-1];
        logic way_wr_en;
        assign way_wr_en = (fill_en && (fill_way == WAYW'(w)))
                        || (wr_en   && (hit_way  == WAYW'(w)));

        always_ff @(posedge clk) begin
            if (way_wr_en) begin
                for (int b = 0; b < 4; b++) begin
                    if (wr_be[b]) way_mem[wr_addr][8*b +: 8] <= wr_data[8*b +: 8];
                end
            end
            way_rd_reg[w] <= way_mem[rd_addr];
        end
    end

    // Both consumers read the same muxed, registered output; they never
    // need it in the same cycle (CPU loads resolve in S_IDLE, write-back
    // reads happen outside it).
    logic [XLEN-1:0] rd_muxed;
    assign rd_muxed = way_rd_reg[sel_way_reg];

    logic wb_data_valid;
    always_ff @(posedge clk) begin
        if (rst || state != S_WB) wb_data_valid <= 1'b0;
        else if (!wb_data_valid)  wb_data_valid <= 1'b1;
        else if (mem_req && mem_ready) wb_data_valid <= 1'b0;
    end

    // A load hit takes one wait cycle for rd_muxed to catch up to the
    // address that was live when the hit was detected; a store hit still
    // completes same-cycle since it only writes; a write-through store
    // likewise never touches this path (wt_store still reads mem_ready).
    //
    // ready must be level, not a pulse: this cache's own hit is only half of
    // whether the pipeline actually advances next cycle - a concurrent
    // I-cache stall (or anything else holding pipe_stall) can keep this
    // exact request presented for several more cycles, and a wait flag that
    // resets itself every cycle regardless would drop ready while the
    // request is still outstanding, then re-arm and pulse again - forever.
    //
    // But it must also drop the instant the *address* changes, even to one
    // that also hits - otherwise back-to-back hits at different addresses
    // would report ready on the new address's first cycle, before rd_muxed
    // has caught up to it. Comparing against the address a qualifying hit
    // was last seen for (not just "was there a hit last cycle") is what
    // makes both cases correct at once - see the matching comment in
    // icache.sv.
    logic        load_hit_now, prev_load_hit;
    logic [XLEN-1:0] prev_addr;
    logic        load_hit_wait;
    assign load_hit_now = (state == S_IDLE) && !flush_start && req && cacheable
                          && !wt_store && !is_store && line_present;
    always_ff @(posedge clk) begin
        if (rst) begin
            prev_load_hit <= 1'b0;
            prev_addr     <= XLEN'(0);
        end else begin
            prev_load_hit <= load_hit_now;
            prev_addr     <= addr;
        end
    end
    assign load_hit_wait = prev_load_hit && load_hit_now && (addr == prev_addr);

    assign read_word = bypass ? (direct_done ? direct_read_word : mem_read_word)
                              : rd_muxed;
    assign access     = req && cacheable && !flush_start;

    // One pulse per access that finds its line absent. A write-through store
    // that misses sits in S_IDLE for its whole memory access without ever
    // refilling, so a bare level would count it once per stalled cycle; the
    // `counted` one-shot pins it to the first.
    logic counted;
    assign miss_pulse = req && cacheable && !flush_start && !line_present
                        && (state == S_IDLE) && !counted;

    always_ff @(posedge clk) begin
        if (rst)                       counted <= 1'b0;
        else if (!req)                 counted <= 1'b0;
        else if (miss_pulse)           counted <= !(ready && advance);
        else if (ready && advance)     counted <= 1'b0;
    end

    // State first: a flush runs with no access outstanding, and the pipeline
    // must be held for its duration rather than told the port is free.
    always_comb begin
        if (state != S_IDLE || flush_start) ready = 1'b0;
        else if (!req)       ready = 1'b1;
        else if (!cacheable) ready = direct_done || mem_ready;
        else if (wt_store)   ready = direct_done || mem_ready;
        else if (is_store)   ready = line_present;   // store-hit: no read-port wait
        else                 ready = load_hit_wait;  // load-hit: registered read latency
    end

    // ---- memory-side requests ----
    always_comb begin
        mem_req        = 1'b0;
        mem_burst      = 1'b0;
        mem_byte_en    = 4'b0000;
        mem_write_word = XLEN'(0);
        mem_addr       = addr;

        case (state)
            S_WB: begin   // flush the dirty victim, whole words, block order
                mem_req        = wb_data_valid;   // wait for rd_muxed to catch up
                mem_burst      = 1'b1;
                mem_byte_en    = 4'b1111;
                mem_write_word = rd_muxed;
                mem_addr       = ({{(32-TAGW){1'b0}}, tag[wb_way][wb_idx]} << (IDXSH + OFFSH + 2))
                               | ({{(32-IDXW){1'b0}}, wb_idx} << (OFFSH + 2))
                               | ({{(32-OFFW){1'b0}}, wb_word} << 2);
            end
            S_FILL: begin
                mem_req   = 1'b1;
                mem_burst = 1'b1;
                mem_addr  = (blk_addr << (OFFSH + 2))
                          + ({{(32-OFFW){1'b0}}, fill_word} << 2);
            end
            default: begin
                if (direct_request && !direct_done) begin
                    mem_req        = 1'b1;
                    mem_byte_en    = byte_en;
                    mem_write_word = write_word;
                    mem_addr       = addr;
                end
            end
        endcase
    end

    // ---- state ----
    // Note: the data payload itself (way_mem) is written up in g_way above,
    // driven combinationally by wr_en/fill_en - not here. Everything here is
    // metadata (tag/valid/dirty/victim) and the state machine.
    always_ff @(posedge clk) begin
        if (rst) begin
            state          <= S_IDLE;
            fill_word      <= '0;
            wb_word        <= '0;
            fill_way       <= '0;
            wb_idx         <= '0;
            wb_way         <= '0;
            flushing       <= 1'b0;
            flush_set      <= '0;
            flush_way      <= '0;
            flush_complete <= 1'b0;
            for (int w = 0; w < WAYS; w++) begin
                for (int s = 0; s < SETS; s++) begin
                    vld[w][s]  <= 1'b0;
                    drty[w][s] <= 1'b0;
                    tag[w][s]  <= '0;
                end
            end
            for (int s = 0; s < SETS; s++) victim[s] <= '0;
        end else begin
            if (!flush_req) flush_complete <= 1'b0;   // rearm once deasserted

            case (state)
                S_IDLE: begin
                    if (flush_start) begin
                        flush_set <= '0;
                        flush_way <= '0;
                        state     <= S_FLUSH;
                    end else if (req && cacheable) begin
                        if (wt_store) begin
                            // no metadata change: a resident line's dirty bit
                            // never gets set in write-through mode, and the
                            // data merge itself happens in g_way above.
                        end else if (line_present) begin
                            if (is_store) drty[hit_way][idx] <= 1'b1;
                        end else begin
                            // Miss: allocate. Loads always allocate; stores only
                            // do in write-back mode (write-allocate), and a
                            // write-through store never reaches this branch.
                            fill_way  <= victim[idx];
                            fill_word <= '0;
                            wb_word   <= '0;
                            wb_idx    <= idx;
                            wb_way    <= victim[idx];
                            flushing  <= 1'b0;
                            if ((WRITE_BACK != 0) && vld[victim[idx]][idx] && drty[victim[idx]][idx])
                                state <= S_WB;
                            else
                                state <= S_FILL;
                        end
                    end
                end

                S_WB: begin
                    if (mem_req && mem_ready) begin
                        if (wb_word == OFFW'(BLOCK_WORDS - 1)) begin
                            wb_word          <= '0;
                            drty[wb_way][wb_idx] <= 1'b0;   // memory is current again
                            // A miss-driven writeback is followed by the refill
                            // it made room for; a flush-driven one just resumes
                            // the walk.
                            state <= flushing ? S_FLUSH : S_FILL;
                        end else begin
                            wb_word <= wb_word + OFFW'(1);
                        end
                    end
                end

                S_FLUSH: begin
                    if (flush_set == FSW'(SETS)) begin
                        flush_complete <= 1'b1;
                        flushing       <= 1'b0;
                        state          <= S_IDLE;
                    end else if (vld[flush_way][flush_set[IDXW-1:0]]
                              && drty[flush_way][flush_set[IDXW-1:0]]) begin
                        // drty was cleared by the writeback, so returning here
                        // falls through to the advance branch instead of looping.
                        wb_idx   <= flush_set[IDXW-1:0];
                        wb_way   <= flush_way;
                        wb_word  <= '0;
                        flushing <= 1'b1;
                        state    <= S_WB;
                    end else if (flush_way == WAYW'(WAYS - 1)) begin
                        flush_way <= '0;
                        flush_set <= flush_set + FSW'(1);
                    end else begin
                        flush_way <= flush_way + WAYW'(1);
                    end
                end

                default: begin   // S_FILL
                    if (mem_ready) begin
                        // way_mem[idx][fill_word] itself is written in g_way
                        // above; only metadata is updated here.
                        if (fill_word == OFFW'(BLOCK_WORDS - 1)) begin
                            // Claim the line only once the block is complete.
                            vld[fill_way][idx]  <= 1'b1;
                            tag[fill_way][idx]  <= tg;
                            drty[fill_way][idx] <= 1'b0;
                            // ponytail: FIFO victim selection, as in icache.
                            victim[idx] <= (WAYS <= 1) ? '0 : victim[idx] + WAYW'(1);
                            state       <= S_IDLE;
                        end else begin
                            fill_word <= fill_word + OFFW'(1);
                        end
                    end
                end
            endcase
        end
    end

`ifdef VERILATOR
    // Every state, every legal transition, and hit/miss/dirty-evict crossed
    // with load/store. cover property is the supported stand-in for a
    // covergroup on this toolchain (see cpu.sv for the same note).
    c_state_idle:  cover property (@(posedge clk) disable iff (rst) state == S_IDLE);
    c_state_wb:    cover property (@(posedge clk) disable iff (rst) state == S_WB);
    c_state_fill:  cover property (@(posedge clk) disable iff (rst) state == S_FILL);
    c_state_flush: cover property (@(posedge clk) disable iff (rst) state == S_FLUSH);

    c_hit_load:  cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE && !flush_start && req && cacheable && line_present && !is_store);
    c_hit_store: cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE && !flush_start && req && cacheable && line_present && is_store);
    c_miss_load: cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE && !flush_start && req && cacheable && !line_present && !is_store);
    c_miss_store_alloc: cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE && !flush_start && req && cacheable
        && !line_present && is_store && !wt_store);
    c_dirty_evict: cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE && !flush_start && req && cacheable && !line_present
        && (WRITE_BACK != 0) && vld[victim[idx]][idx] && drty[victim[idx]][idx]);

    c_trans_idle_to_wb:    cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE ##1 state == S_WB);
    c_trans_idle_to_fill:  cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE ##1 state == S_FILL);
    c_trans_idle_to_flush: cover property (@(posedge clk) disable iff (rst)
        state == S_IDLE ##1 state == S_FLUSH);
    c_trans_wb_to_fill:    cover property (@(posedge clk) disable iff (rst)
        state == S_WB ##1 state == S_FILL);
    c_trans_wb_to_flush:   cover property (@(posedge clk) disable iff (rst)
        state == S_WB ##1 state == S_FLUSH);
    c_trans_flush_to_wb:   cover property (@(posedge clk) disable iff (rst)
        state == S_FLUSH ##1 state == S_WB);
    c_trans_fill_to_idle:  cover property (@(posedge clk) disable iff (rst)
        state == S_FILL ##1 state == S_IDLE);
    c_trans_flush_to_idle: cover property (@(posedge clk) disable iff (rst)
        state == S_FLUSH ##1 state == S_IDLE);
`endif

`ifndef SYNTHESIS
    a_bypass_no_cache_state: assert property (@(posedge clk) disable iff (rst)
        bypass |-> !wr_en && !fill_en && !access && !miss_pulse);
    a_bypass_completion: assert property (@(posedge clk) disable iff (rst)
        bypass && !direct_done |-> ready == mem_ready);
    a_bypass_held: assert property (@(posedge clk) disable iff (rst)
        bypass && direct_done |-> ready && !mem_req);
    a_flush_start_blocks_request: assert property (@(posedge clk) disable iff (rst)
        flush_start |-> !ready && !mem_req && !wr_en && !access && !miss_pulse);
    a_flush_walk_has_no_request: assert property (@(posedge clk) disable iff (rst)
        state == S_FLUSH |-> !mem_req);
    a_direct_active_request: assert property (@(posedge clk) disable iff (rst)
        direct_active && req |-> state == S_IDLE && mem_req);
    a_direct_held: assert property (@(posedge clk) disable iff (rst)
        direct_done && req |-> ready && !mem_req);
    a_flush_deferred_for_direct: assert property (@(posedge clk) disable iff (rst)
        flush_req && (direct_active || direct_done) |-> !flush_start);
`endif
endmodule

`default_nettype wire
