// branch_predictor.sv - front-end branch prediction.
`default_nettype none

import rv32i_pkg::*;

module branch_predictor #(
    parameter int IDX_BITS = 6,                  // 2^6 = 64 entries
    parameter int TAG_BITS = 10,
    // 0 = bimodal: the direction table (bht) is indexed by PC alone, same as
    //     every branch's history being independent of every other branch's.
    // 1 = gshare: the direction table is indexed by PC XOR global history, so
    //     the *same* branch gets a different counter per recent global
    //     outcome pattern - separates "taken when the last branch was taken"
    //     from "taken when it wasn't" instead of averaging them into one
    //     counter. The BTB (tag/target) stays PC-indexed either way: a
    //     branch's target doesn't depend on history, only its direction does.
    parameter int GSHARE   = 0
) (
    input  var logic        clk,
    input  var logic        rst,

    // ---- predict port (IF stage) ----
    input  var logic [XLEN-1:0] pc_predict,          // current fetch PC
    output var logic        predict_taken,       // 1 => redirect fetch to predict_target
    output var logic [XLEN-1:0] predict_target,
    // Snapshot of the global history used for *this* prediction. Threaded
    // through the pipeline (if_id_t/id_ex_t) and handed back at update time,
    // so the write lands on the exact table entry the read used - the live
    // ghistory register may already have shifted past it by then.
    output var logic [GHIST_BITS-1:0] predict_ghistory,

    // ---- update port (EX stage, when a branch/jump resolves) ----
    input  var logic        update_en,           // this cycle a branch/jump resolved
    input  var logic [XLEN-1:0] update_pc,           // that instruction's PC
    input  var logic        update_taken,        // was it actually taken?
    input  var logic [XLEN-1:0] update_target,       // its actual target (valid when taken)
    input  var logic [GHIST_BITS-1:0] update_ghistory  // this instruction's predict-time snapshot
);
    localparam int NUM_ENTRIES = (1 << IDX_BITS);

    // index/tag slicing helpers
    function automatic logic [IDX_BITS-1:0] idx_of(input logic [XLEN-1:0] pc);
        idx_of = pc[IDX_BITS+1:2];               // drop 2 low (word-aligned) bits
    endfunction
    function automatic logic [TAG_BITS-1:0] tag_of(input logic [XLEN-1:0] pc);
        tag_of = pc[IDX_BITS+1+TAG_BITS : IDX_BITS+2];
    endfunction
    // gshare hash: PC index XOR history, resized to the index width.
    function automatic logic [IDX_BITS-1:0] bht_idx_of(
        input logic [XLEN-1:0]    pc,
        input logic [GHIST_BITS-1:0] hist
    );
        if (GSHARE != 0) bht_idx_of = idx_of(pc) ^ IDX_BITS'(hist);
        else        bht_idx_of = idx_of(pc);
    endfunction

    initial begin
        if ((GSHARE != 0) && GHIST_BITS > IDX_BITS) begin
            $fatal(1, "branch_predictor: GHIST_BITS(%0d) must be <= IDX_BITS(%0d) for gshare",
                   GHIST_BITS, IDX_BITS);
        end
    end

    // ---- storage ----
    logic [1:0]          bht      [NUM_ENTRIES];
    logic                btb_valid[NUM_ENTRIES];
    logic [TAG_BITS-1:0] btb_tag  [NUM_ENTRIES];
    logic [XLEN-1:0]         btb_tgt  [NUM_ENTRIES];

    // Global history: the last GHIST_BITS branch/jump outcomes, most recent
    // in bit 0. Only meaningful when GSHARE=1; harmless (unread) otherwise.
    logic [GHIST_BITS-1:0] ghistory;
    assign predict_ghistory = ghistory;

    // ---- predict (combinational read) ----
    logic [IDX_BITS-1:0] p_idx_btb, p_idx_bht;
    logic [TAG_BITS-1:0] p_tag;
    assign p_idx_btb = idx_of(pc_predict);
    assign p_idx_bht = bht_idx_of(pc_predict, ghistory);
    assign p_tag     = tag_of(pc_predict);

    logic btb_hit;
    assign btb_hit       = btb_valid[p_idx_btb] && (btb_tag[p_idx_btb] == p_tag);
    assign predict_taken = btb_hit && bht[p_idx_bht][1];   // high counter bit
    assign predict_target = btb_tgt[p_idx_btb];

    // ---- update (synchronous write) ----
    logic [IDX_BITS-1:0] u_idx_btb, u_idx_bht;
    logic [TAG_BITS-1:0] u_tag;
    assign u_idx_btb = idx_of(update_pc);
    assign u_idx_bht = bht_idx_of(update_pc, update_ghistory);
    assign u_tag     = tag_of(update_pc);

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int i = 0; i < NUM_ENTRIES; i++) begin
                bht[i]       <= 2'b01;             // weakly not-taken: neutral-ish start
                btb_valid[i] <= 1'b0;
                btb_tag[i]   <= '0;
                btb_tgt[i]   <= XLEN'(0);
            end
            ghistory <= '0;
        end else if (update_en) begin
            // 2-bit saturating counter toward the actual outcome
            if (update_taken) begin
                if (bht[u_idx_bht] != 2'b11) bht[u_idx_bht] <= bht[u_idx_bht] + 2'b01;
                // install/refresh BTB target on a taken branch
                btb_valid[u_idx_btb] <= 1'b1;
                btb_tag[u_idx_btb]   <= u_tag;
                btb_tgt[u_idx_btb]   <= update_target;
            end else begin
                if (bht[u_idx_bht] != 2'b00) bht[u_idx_bht] <= bht[u_idx_bht] - 2'b01;
                // note: we keep the BTB entry on not-taken; the counter alone
                // suppresses the prediction. Evicting on every not-taken would
                // thrash entries for branches that alternate.
            end
            ghistory <= {ghistory[GHIST_BITS-2:0], update_taken};
        end
    end
endmodule

`default_nettype wire
