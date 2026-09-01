`default_nettype none

module arty_clock (
    input  var logic clk100,
    input  var logic reset,
    output var logic soc_clk,
    output var logic locked
);
`ifdef SYNTHESIS
    logic feedback;
    logic feedback_buffered;
    logic soc_clk_unbuffered;

    MMCME2_BASE #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKFBOUT_MULT_F(10.000),
        .CLKIN1_PERIOD(10.000),
        .CLKOUT0_DIVIDE_F(20.000),
        .DIVCLK_DIVIDE(1),
        .STARTUP_WAIT("FALSE")
    ) mmcm (
        .CLKFBOUT(feedback),
        .CLKFBOUTB(),
        .CLKOUT0(soc_clk_unbuffered),
        .CLKOUT0B(),
        .CLKOUT1(),
        .CLKOUT1B(),
        .CLKOUT2(),
        .CLKOUT2B(),
        .CLKOUT3(),
        .CLKOUT3B(),
        .CLKOUT4(),
        .CLKOUT5(),
        .CLKOUT6(),
        .LOCKED(locked),
        .CLKFBIN(feedback_buffered),
        .CLKIN1(clk100),
        .PWRDWN(1'b0),
        .RST(reset)
    );

    BUFG feedback_buffer (
        .I(feedback),
        .O(feedback_buffered)
    );

    BUFG soc_clock_buffer (
        .I(soc_clk_unbuffered),
        .O(soc_clk)
    );
`else
    assign soc_clk = clk100;
    assign locked = !reset;
`endif
endmodule

`default_nettype wire
