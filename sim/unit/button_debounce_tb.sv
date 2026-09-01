`default_nettype none

module button_debounce_tb;
    logic clk = 1'b0;
    logic rst;
    logic async_in;
    logic state;
    logic rise;

    always #1 clk = ~clk;

    button_debounce #(.STABLE_CYCLES(4)) dut (
        .clk(clk), .rst(rst), .async_in(async_in),
        .state(state), .rise(rise)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic tick;
        begin
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    initial begin
        rst = 1'b1;
        async_in = 1'b0;
        repeat (2) tick();
        rst = 1'b0;

        repeat (3) begin
            async_in = 1'b1;
            repeat (2) tick();
            async_in = 1'b0;
            repeat (2) tick();
            check(!state && !rise, "bounce changed debounced state");
        end

        async_in = 1'b1;
        repeat (5) begin
            tick();
            check(!state && !rise, "button accepted before stable interval");
        end
        tick();
        check(state && rise, "stable press was not accepted");
        tick();
        check(state && !rise, "held button repeated rise");

        async_in = 1'b0;
        repeat (5) begin
            tick();
            check(state && !rise, "release accepted before stable interval");
        end
        tick();
        check(!state && !rise, "stable release was not accepted");

        $display("PASS button debounce");
        $finish;
    end

    initial begin
        repeat (200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
