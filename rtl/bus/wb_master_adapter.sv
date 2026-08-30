`default_nettype none

module wb_master_adapter (
    input  var logic clk,
    input  var logic rst,
    input  var logic src_req,
    input  var logic [31:0] src_addr,
    input  var logic [3:0] src_wstrb,
    input  var logic [31:0] src_wdata,
    output var logic [31:0] src_rdata,
    output var logic src_ready,
    output var logic fault_pulse,
    output var logic wb_cyc,
    output var logic wb_stb,
    output var logic wb_we,
    output var logic [31:0] wb_adr,
    output var logic [31:0] wb_dat_w,
    output var logic [3:0] wb_sel,
    input  var logic wb_ack,
    input  var logic wb_err,
    input  var logic [31:0] wb_dat_r
);
    typedef enum logic {IDLE, ACTIVE} state_t;
    state_t state;
    logic [31:0] addr_q, wdata_q;
    logic [3:0] wstrb_q;

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            addr_q <= '0;
            wdata_q <= '0;
            wstrb_q <= '0;
            fault_pulse <= 1'b0;
        end else begin
            fault_pulse <= state == ACTIVE && wb_err;
            if (state == IDLE) begin
                if (src_req) begin
                    state <= ACTIVE;
                    addr_q <= src_addr;
                    wdata_q <= src_wdata;
                    wstrb_q <= src_wstrb;
                end
            end else if (wb_ack || wb_err) begin
                state <= IDLE;
            end
        end
    end

    always_comb begin
        wb_cyc = state == ACTIVE;
        wb_stb = state == ACTIVE;
        wb_we = |wstrb_q;
        wb_adr = addr_q;
        wb_dat_w = wdata_q;
        wb_sel = wb_we ? wstrb_q : 4'b1111;
        src_ready = state == IDLE ? !src_req : wb_ack || wb_err;
        src_rdata = state == ACTIVE && wb_ack ? wb_dat_r : 32'h0;
    end

`ifndef SYNTHESIS
    a_request_stable: assert property (@(posedge clk) disable iff (rst)
        wb_cyc && !(wb_ack || wb_err)
        |=> $stable({wb_adr, wb_we, wb_sel, wb_dat_w}));
    a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
        !(wb_ack && wb_err));
    a_fault_from_error: assert property (@(posedge clk) disable iff (rst)
        fault_pulse |-> $past(wb_err));
`endif
endmodule

`default_nettype wire
