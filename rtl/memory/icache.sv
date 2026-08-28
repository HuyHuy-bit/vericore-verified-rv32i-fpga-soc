// icache.sv - blocking, read-only instruction cache.
//
// Sits between the fetch stage and instr_mem. Read-only means no dirty bits,
// no write-back, no coherence: instruction memory is never written on this
// core, so the entire write path a D-cache needs simply doesn't exist here.
// That is why this one comes first.
//
// Parameterised on BYTES / BLOCK_WORDS / WAYS so the geometry can be swept -
// the sweep is the actual deliverable, not any single configuration.
//
// A miss costs: 1 cycle to notice, then the block walked word by word out of
// the backing memory with burst asserted (so mem_timing charges full latency
// for the first word and 1 cycle per word after), then 1 cycle to turn the
// fill around into a hit. The pipeline is frozen throughout, so `addr` is
// stable for the whole refill and doesn't need latching.
`default_nettype none

import rv32i_pkg::*;

module icache #(
    parameter int BYTES       = 1024,
    parameter int BLOCK_WORDS = 4,
    parameter int WAYS        = 1
) (
    input  var logic        clk,
    input  var logic        rst,

    // FENCE.I: drop every cached line so the next fetch of any address goes
    // back to memory. Only ever pulsed from the MEM commit point, which is
    // gated on !pipe_stall and therefore cannot coincide with a refill (a
    // refill holds imem_ready low, which *is* pipe_stall) - so this doesn't
    // need to abort an in-flight fill.
    input  var logic        invalidate,

    // CPU side
    input  var logic [XLEN-1:0] addr,
    output var logic [ILEN-1:0] instr,
    output var logic        ready,

    // backing memory side
    output var logic [XLEN-1:0] mem_addr,
    output var logic        mem_req,
    output var logic        mem_burst,
    input  var logic [ILEN-1:0] mem_instr,
    input  var logic        mem_ready,

    // Counters are misses only; the CPU counts accesses as advancing cycles.
    // A hit level would be true again the moment a refill lands, so counting it
    // on pipeline advance would score every miss as a hit too.
    output var logic        miss_pulse
);
    localparam int SETS  = BYTES / (BLOCK_WORDS * 4 * WAYS);

    // Widths are forced to at least 1: a 1-word block or a single-set cache
    // would otherwise ask for a zero-width slice. OFFSH/IDXSH are the real
    // shift amounts, which are allowed to be 0.
    localparam int OFFW  = (BLOCK_WORDS <= 1) ? 1 : $clog2(BLOCK_WORDS);
    localparam int IDXW  = (SETS        <= 1) ? 1 : $clog2(SETS);
    localparam int OFFSH = (BLOCK_WORDS <= 1) ? 0 : OFFW;
    localparam int IDXSH = (SETS        <= 1) ? 0 : IDXW;
    localparam int TAGW  = 32 - 2 - OFFSH - IDXSH;
    localparam int WAYW  = (WAYS <= 1) ? 1 : $clog2(WAYS);

    initial begin
        if (SETS * WAYS * BLOCK_WORDS * 4 != BYTES) begin
            $fatal(1, "icache: BYTES(%0d) must equal SETS*WAYS*BLOCK_WORDS*4", BYTES);
        end
    end

    logic [TAGW-1:0]  tag   [WAYS][SETS];
    logic             vld   [WAYS][SETS];
    logic [WAYW-1:0]  victim[SETS];

    // ---- address split ----
    logic [XLEN-1:0] word_addr, blk_addr;
    logic [OFFW-1:0] off;
    logic [IDXW-1:0] idx;
    logic [TAGW-1:0] tg;

    assign word_addr = addr >> 2;
    assign blk_addr  = word_addr >> OFFSH;
    assign off       = (BLOCK_WORDS <= 1) ? '0 : OFFW'(word_addr);
    assign idx       = (SETS        <= 1) ? '0 : IDXW'(blk_addr);
    assign tg        = TAGW'(blk_addr >> IDXSH);

    // ---- lookup ----
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

    logic            refilling;
    logic [OFFW-1:0] fill_word;
    logic [WAYW-1:0] fill_way;

    logic hit;
    assign hit = |way_hit;

    // ---- data storage: WAYS parallel single-way banks ----
    // One flat [SETS*BLOCK_WORDS] array per way, read together and muxed
    // *after* the register - not one [WAYS][SETS][BLOCK_WORDS] array indexed
    // by a runtime way select. The 3D-array-plus-way-mux form matches no BRAM
    // inference template on Xilinx parts and synthesizes to flip-flops even
    // with the read registered; dcache.sv proved that the hard way (65,600 ->
    // 17,106 LUT from this restructuring alone). This is also just how a real
    // set-associative data array is built, so it's the right shape, not a
    // synthesis workaround.
    //
    // Simpler than dcache.sv's version in one respect: this cache is read-only
    // on the hit path, so a refill is the *only* writer and there is no second
    // write address to mux against. The "one physical write address per BRAM
    // port" constraint that forced dcache.sv's unified write port is satisfied
    // here by construction.
    localparam int WORDS = SETS * BLOCK_WORDS;
    localparam int AW    = (WORDS <= 1) ? 1 : $clog2(WORDS);

    logic [AW-1:0] rd_addr, wr_addr;
    assign rd_addr = AW'(idx      * BLOCK_WORDS + 32'(off));
    assign wr_addr = AW'(idx      * BLOCK_WORDS + 32'(fill_word));

    logic fill_en;
    assign fill_en = refilling && mem_ready;

    logic [ILEN-1:0] way_rd_reg [WAYS];
    for (genvar w = 0; w < WAYS; w++) begin : g_way
        (* ram_style = "block" *) logic [ILEN-1:0] way_mem [0:WORDS-1];
        always_ff @(posedge clk) begin
            if (fill_en && (fill_way == WAYW'(w))) way_mem[wr_addr] <= mem_instr;
            way_rd_reg[w] <= way_mem[rd_addr];
        end
    end

    // The way select has to be delayed to land on the same cycle as the
    // registered read it corresponds to - the read is one cycle behind the
    // hit_way that produced its address.
    logic [WAYW-1:0] hit_way_reg;
    always_ff @(posedge clk) hit_way_reg <= hit_way;

    logic [ILEN-1:0] data_rd_reg;
    assign data_rd_reg = way_rd_reg[hit_way_reg];

    // ready must be level, not a pulse: whether the pipeline actually
    // advances next cycle also depends on the D-cache, which can hold
    // pipe_stall for several more cycles after this cache's own hit is
    // detected, so a wait flag that just resets itself every cycle would
    // drop ready while the same request is still outstanding, then re-arm
    // and pulse again - oscillating forever instead of holding steady.
    //
    // But it must also drop back to 0 the instant the *address* changes,
    // even if the new address also hits - otherwise back-to-back hits at
    // different addresses would report ready on the new address's first
    // cycle, before data_rd_reg has caught up to it. Comparing against the
    // address a hit was last seen for (not just "was there a hit last
    // cycle") is what makes both cases correct at once.
    logic        prev_hit;
    logic [XLEN-1:0] prev_addr;
    logic        hit_wait;
    always_ff @(posedge clk) begin
        if (rst) begin
            prev_hit  <= 1'b0;
            prev_addr <= '0;
        end else begin
            prev_hit  <= hit;
            prev_addr <= addr;
        end
    end
    assign hit_wait = prev_hit && hit && (addr == prev_addr);

    assign ready = hit_wait;
    assign instr = data_rd_reg;

    // One pulse per refill: the cycle a miss is seen and no refill is running.
    assign miss_pulse = !hit && !refilling;

    // ---- refill ----
    // burst is asserted for every word including the first. mem_timing decides
    // for itself whether an address is sequential to what it last served, so a
    // refill that happens to follow on from the previous block gets the
    // streaming discount on its first word too - which is what an open row does.
    assign mem_req   = refilling;
    assign mem_burst = refilling;
    assign mem_addr  = (blk_addr << (OFFSH + 2)) + ({{(XLEN-OFFW){1'b0}}, fill_word} << 2);

    always_ff @(posedge clk) begin
        if (rst) begin
            refilling <= 1'b0;
            fill_word <= '0;
            fill_way  <= '0;
            for (int w = 0; w < WAYS; w++) begin
                for (int s = 0; s < SETS; s++) begin
                    vld[w][s] <= 1'b0;
                    tag[w][s] <= '0;
                end
            end
            for (int s = 0; s < SETS; s++) victim[s] <= '0;
        end else if (invalidate) begin
            // Valid bits only: the tag/data arrays can keep their contents,
            // since nothing can hit on them again until a refill rewrites the
            // tag. Clearing one bit per line instead of the whole tag array is
            // what keeps this a flop-array reset and not a BRAM walk.
            for (int w = 0; w < WAYS; w++) begin
                for (int s = 0; s < SETS; s++) vld[w][s] <= 1'b0;
            end
        end else if (!refilling) begin
            if (!hit) begin
                refilling <= 1'b1;
                fill_word <= '0;
                fill_way  <= victim[idx];
            end
        end else if (mem_ready) begin
            // the data word itself is written by the per-way block above
            if (fill_word == OFFW'(BLOCK_WORDS - 1)) begin
                // Claim the line only once the whole block is present, so a
                // partially filled block can never be read as a hit.
                refilling         <= 1'b0;
                vld[fill_way][idx] <= 1'b1;
                tag[fill_way][idx] <= tg;
                // ponytail: FIFO victim selection, not true LRU. For 2-way the
                // two policies rarely diverge; if an associativity sweep ever
                // hinges on it, 2-way LRU is one bit per set.
                victim[idx] <= (WAYS <= 1) ? '0 : victim[idx] + WAYW'(1);
            end else begin
                fill_word <= fill_word + OFFW'(1);
            end
        end
    end
endmodule

`default_nettype wire
