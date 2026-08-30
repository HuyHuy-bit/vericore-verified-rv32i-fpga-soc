`default_nettype none

module reset_controller #(
    parameter int unsigned POWER_ON_CYCLES = 16
) (
    input  var logic clk,
    input  var logic async_reset,
    output var logic rst
);
    timeunit 1ns;
    timeprecision 1ps;

    localparam int COUNT_W = POWER_ON_CYCLES < 2 ? 1
        : $clog2(POWER_ON_CYCLES + 1);
    localparam logic [COUNT_W-1:0] POWER_ON_LIMIT = COUNT_W'(POWER_ON_CYCLES);

    logic [COUNT_W-1:0] power_count;
    (* ASYNC_REG = "TRUE" *) logic [1:0] reset_sync;

    initial begin
        power_count = '0;
        reset_sync = 2'b11;
        if (POWER_ON_CYCLES < 1)
            $fatal(1, "reset_controller: POWER_ON_CYCLES must be positive");
    end

    assign rst = reset_sync[1] || power_count < POWER_ON_LIMIT;

    always_ff @(posedge clk) begin
        if (power_count < POWER_ON_LIMIT)
            power_count <= power_count + 1'b1;
    end

    always_ff @(posedge clk or posedge async_reset) begin
        if (async_reset)
            reset_sync <= 2'b11;
        else
            reset_sync <= {reset_sync[0], 1'b0};
    end

`ifndef SYNTHESIS
    a_power_on_hold: assert property (@(posedge clk)
        power_count < POWER_ON_LIMIT |-> rst);
    a_synchronous_release: assert property (@(posedge clk)
        $fell(rst) |-> reset_sync == 2'b00 && power_count >= POWER_ON_LIMIT);
    always @(negedge rst)
        assert (clk);
`endif
endmodule

`default_nettype wire
