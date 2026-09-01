`default_nettype none

module uart_tx_tb;
    logic clk = 1'b0;
    logic rst;
    logic valid;
    logic [7:0] data;
    logic ready;
    logic tx;

    always #1 clk = ~clk;

    uart_tx #(.CLOCK_HZ(80), .UART_BAUD(10)) dut (
        .clk(clk), .rst(rst), .valid(valid), .data(data),
        .ready(ready), .tx(tx)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic sample_after(input int clocks,
                                input logic expected,
                                input string label);
        begin
            repeat (clocks) @(posedge clk);
            @(negedge clk);
            check(tx == expected, label);
        end
    endtask

    initial begin
        rst = 1'b1;
        valid = 1'b0;
        data = '0;
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        check(ready && tx, "UART did not reset idle");

        valid = 1'b1;
        data = 8'ha5;
        @(posedge clk);
        @(negedge clk);
        valid = 1'b0;
        check(!ready && !tx, "UART did not accept frame");

        sample_after(4, 1'b0, "start bit mismatch");
        valid = 1'b1;
        data = 8'h3c;
        @(posedge clk);
        @(negedge clk);
        valid = 1'b0;
        sample_after(7, 1'b1, "data bit 0 mismatch");
        sample_after(8, 1'b0, "data bit 1 mismatch");
        sample_after(8, 1'b1, "data bit 2 mismatch");
        sample_after(8, 1'b0, "data bit 3 mismatch");
        sample_after(8, 1'b0, "data bit 4 mismatch");
        sample_after(8, 1'b1, "data bit 5 mismatch");
        sample_after(8, 1'b0, "data bit 6 mismatch");
        sample_after(8, 1'b1, "data bit 7 mismatch");
        sample_after(8, 1'b1, "stop bit mismatch");
        sample_after(4, 1'b1, "UART did not return idle");
        check(ready, "UART did not become ready");

        $display("PASS UART transmitter");
        $finish;
    end

    initial begin
        repeat (200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
