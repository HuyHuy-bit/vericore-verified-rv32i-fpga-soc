`default_nettype none

module reset_controller_tb;
    timeunit 1ns;
    timeprecision 1ps;

    logic clk = 1'b0;
    logic async_reset;
    logic rst;

    always #5 clk = ~clk;

    reset_controller #(.POWER_ON_CYCLES(4)) dut (
        .clk(clk), .async_reset(async_reset), .rst(rst)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    initial begin
        async_reset = 1'b0;
        check(rst, "power-on reset was not asserted");
        repeat (3) begin
            @(posedge clk);
            #1;
            check(rst, "power-on reset ended early");
        end
        @(posedge clk);
        #1;
        check(!rst, "power-on reset did not end after configured clocks");
        @(negedge clk);
        #1;
        check(!rst, "power-on reset fell away from a rising edge");

        @(negedge clk);
        async_reset = 1'b1;
        #1;
        check(rst, "button reset did not assert asynchronously");
        async_reset = 1'b0;
        @(posedge clk);
        #1;
        check(rst, "button reset deasserted after one clock");
        @(posedge clk);
        #1;
        check(!rst, "button reset did not deassert synchronously");

        $display("PASS reset controller");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
