`default_nettype none

module wb_dmem #(
    parameter int DEPTH_WORDS = 8192,
    parameter logic [31:0] BASE_ADDR = 32'h2000_0000,
    parameter string INIT_FILE = ""
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic wb_cyc,
    input  var logic wb_stb,
    input  var logic wb_we,
    input  var logic [31:0] wb_adr,
    input  var logic [31:0] wb_dat_w,
    input  var logic [3:0] wb_sel,
    output var logic wb_ack,
    output var logic wb_err,
    output var logic [31:0] wb_dat_r
);
    localparam int INDEX_W = DEPTH_WORDS <= 1 ? 1 : $clog2(DEPTH_WORDS);
    localparam logic [32:0] SIZE_BYTES = 33'(DEPTH_WORDS * 4);

    (* ram_style = "block" *) logic [31:0] mem [0:DEPTH_WORDS-1];
    logic busy;
    logic in_range;
    logic [INDEX_W-1:0] word_index;
    logic [32:0] address_offset;
`ifndef SYNTHESIS
    string init_path;
`endif

    assign address_offset = {1'b0, wb_adr} - {1'b0, BASE_ADDR};
    assign in_range = !address_offset[32] && address_offset < SIZE_BYTES
                      && address_offset[1:0] == 2'b00;
    assign word_index = address_offset[INDEX_W+1:2];

    initial begin
        if (DEPTH_WORDS < 1)
            $fatal(1, "wb_dmem: DEPTH_WORDS must be positive");
`ifndef SYNTHESIS
        if ($value$plusargs("DMEMFILE=%s", init_path))
            $readmemh(init_path, mem);
        else if (INIT_FILE != "")
            $readmemh(INIT_FILE, mem);
`else
        if (INIT_FILE != "")
            $readmemh(INIT_FILE, mem);
`endif
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0;
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;
        end else begin
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;
            if (busy) begin
                busy <= 1'b0;
            end else if (wb_cyc && wb_stb) begin
                busy <= 1'b1;
                if (!in_range) begin
                    wb_err <= 1'b1;
                end else begin
                    wb_ack <= 1'b1;
                    if (wb_we) begin
                        for (int lane = 0; lane < 4; lane++) begin
                            if (wb_sel[lane])
                                mem[word_index][8*lane +: 8] <= wb_dat_w[8*lane +: 8];
                        end
                    end else begin
                        wb_dat_r <= mem[word_index];
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
        !(wb_ack && wb_err));
`endif
endmodule

`default_nettype wire
