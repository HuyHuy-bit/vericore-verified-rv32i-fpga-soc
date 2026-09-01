`default_nettype none

module soc_smoke_tb;
    logic clk = 1'b0;
    logic rst;
    logic button_irq;
    logic [3:0] led;
    logic uart_tx;
    logic bus_fault;
    logic retired_debug;
    logic [31:0] progress_debug;
    int unsigned retired_pulses;
    logic saw_instruction_bus;

    always #1 clk = ~clk;

    always @(posedge clk) begin
        if (!rst && retired_debug)
            retired_pulses++;
        if (!rst && dut.i_wb_cyc)
            saw_instruction_bus <= 1'b1;
    end

    rv32i_soc #(
        .CLOCK_HZ(80),
        .UART_BAUD(10),
        .DEBOUNCE_CYCLES(4),
        .ICACHE_BYTES(1024),
        .ICACHE_BLOCK_WORDS(4),
        .ICACHE_WAYS(4),
        .DCACHE_BYTES(4096),
        .DCACHE_BLOCK_WORDS(4),
        .DCACHE_WAYS(4),
        .DCACHE_WRITE_BACK(1),
        .IMEM_DEPTH_WORDS(16),
        .DMEM_DEPTH_WORDS(16)
    ) dut (
        .clk(clk),
        .rst(rst),
        .button_irq(button_irq),
        .led(led),
        .uart_tx(uart_tx),
        .bus_fault(bus_fault),
        .retired_debug(retired_debug),
        .progress_debug(progress_debug)
    );

    task automatic check(input logic condition, input string label);
        if (!condition)
            $fatal(1, "%s", label);
    endtask

    initial begin
        rst = 1'b1;
        button_irq = 1'b0;
        retired_pulses = 0;
        saw_instruction_bus = 1'b0;
        repeat (4) @(posedge clk);
        @(negedge clk);
        check(uart_tx, "UART was not idle during reset");
        check(led == 4'h0, "LED reset value was not zero");
        check(!bus_fault, "bus fault was set during reset");
        rst = 1'b0;

        repeat (2000) begin
            @(posedge clk);
            if (progress_debug >= 3)
                break;
        end
        @(negedge clk);
        check(saw_instruction_bus, "instruction bus was never active");
        check(progress_debug >= 3, "core made no retirement progress");
        check(retired_pulses >= 3, "retirement debug did not pulse");
        check(!bus_fault, "self-loop caused a bus fault");
        check(uart_tx, "unused UART left idle state");
        check(led == 4'h0, "unused GPIO changed LED state");

        $display("PASS integrated SoC smoke");
        $finish;
    end

    initial begin
        repeat (2200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
