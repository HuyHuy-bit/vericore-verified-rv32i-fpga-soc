`timescale 1ns/1ps

module arty_post_route_tb;
    localparam time UART_BIT = 8680ns;
    localparam string EXPECTED = "rv32i soc ready\n";

    logic clk100 = 1'b0;
    logic [1:0] btn = 2'b00;
    wire [3:0] led;
    wire uart_tx;

    arty_a7_35t_top dut (
        .clk100(clk100),
        .btn(btn),
        .led(led),
        .uart_tx(uart_tx)
    );

    always #5ns clk100 = ~clk100;

    task automatic receive_byte(output logic [7:0] value);
        wait (uart_tx === 1'b1);
        @(negedge uart_tx);
        #(UART_BIT / 2);
        if (uart_tx !== 1'b0)
            $fatal(1, "UART start bit was not low");
        for (int bit_index = 0; bit_index < 8; bit_index++) begin
            #UART_BIT;
            if (!$isunknown(uart_tx))
                value[bit_index] = uart_tx;
            else
                $fatal(1, "UART data bit was unknown");
        end
        #UART_BIT;
        if (uart_tx !== 1'b1)
            $fatal(1, "UART stop bit was not high");
    endtask

    initial begin
        logic [7:0] value;
        for (int index = 0; index < EXPECTED.len(); index++) begin
            receive_byte(value);
            if (value !== EXPECTED[index])
                $fatal(1, "UART mismatch at byte %0d: got %02x expected %02x",
                    index, value, EXPECTED[index]);
        end
        #1us;
        if (led !== 4'h1)
            $fatal(1, "boot LED value was %x", led);
        if (uart_tx !== 1'b1)
            $fatal(1, "UART was not idle after the boot banner");
        $display("PASS Arty A7 post-route timing simulation");
        $finish;
    end

    initial begin
        #3ms;
        $fatal(1, "post-route timing simulation deadline expired");
    end
endmodule
