`default_nettype none

module button_debounce #(
    parameter int unsigned STABLE_CYCLES = 1_000_000
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic async_in,
    output var logic state,
    output var logic rise
);
    localparam int COUNT_W = STABLE_CYCLES <= 1 ? 1 : $clog2(STABLE_CYCLES);
    localparam logic [COUNT_W-1:0] STABLE_LAST = COUNT_W'(STABLE_CYCLES - 1);

    (* ASYNC_REG = "TRUE" *) logic sync_meta;
    (* ASYNC_REG = "TRUE" *) logic sync_value;
    logic [COUNT_W-1:0] stable_count;

    initial begin
        if (STABLE_CYCLES < 1)
            $fatal(1, "button_debounce: STABLE_CYCLES must be positive");
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            sync_meta <= 1'b0;
            sync_value <= 1'b0;
            stable_count <= '0;
            state <= 1'b0;
            rise <= 1'b0;
        end else begin
            sync_meta <= async_in;
            sync_value <= sync_meta;
            rise <= 1'b0;
            if (sync_value == state) begin
                stable_count <= '0;
            end else if (stable_count == STABLE_LAST) begin
                state <= sync_value;
                rise <= sync_value;
                stable_count <= '0;
            end else begin
                stable_count <= stable_count + 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
