`default_nettype none

module wb_gpio_irq_tb;
    logic clk = 1'b0;
    logic rst;
    logic wb_cyc, wb_stb, wb_we, wb_ack, wb_err;
    logic [31:0] wb_adr, wb_dat_w, wb_dat_r;
    logic [3:0] wb_sel;
    logic button_state, button_rise;
    logic [3:0] led;
    logic irq_external;

    always #1 clk = ~clk;

    wb_gpio_irq dut (
        .clk(clk), .rst(rst),
        .wb_cyc(wb_cyc), .wb_stb(wb_stb), .wb_we(wb_we),
        .wb_adr(wb_adr), .wb_dat_w(wb_dat_w), .wb_sel(wb_sel),
        .wb_ack(wb_ack), .wb_err(wb_err), .wb_dat_r(wb_dat_r),
        .button_state(button_state), .button_rise(button_rise),
        .led(led), .irq_external(irq_external)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic wb_access(input logic [31:0] addr,
                             input logic we,
                             input logic [3:0] sel,
                             input logic [31:0] write_data,
                             input logic expected_error,
                             output logic [31:0] read_data);
        int cycles;
        begin
            @(negedge clk);
            wb_cyc = 1'b1;
            wb_stb = 1'b1;
            wb_we = we;
            wb_adr = addr;
            wb_sel = sel;
            wb_dat_w = write_data;
            cycles = 0;
            while (!(wb_ack || wb_err) && cycles < 10) begin
                @(posedge clk);
                @(negedge clk);
                cycles++;
            end
            check(cycles < 10, "Wishbone GPIO timeout");
            check(wb_err == expected_error, "Wishbone GPIO ERR mismatch");
            check(wb_ack == !expected_error, "Wishbone GPIO ACK mismatch");
            read_data = wb_dat_r;
            wb_cyc = 1'b0;
            wb_stb = 1'b0;
            @(posedge clk);
            @(negedge clk);
            check(!wb_ack && !wb_err, "Wishbone GPIO repeated response");
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    logic [31:0] value;

    initial begin
        rst = 1'b1;
        wb_cyc = 1'b0; wb_stb = 1'b0; wb_we = 1'b0;
        wb_adr = '0; wb_dat_w = '0; wb_sel = '0;
        button_state = 1'b0;
        button_rise = 1'b0;
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        check(led == 4'h0 && !irq_external, "GPIO reset state wrong");

        wb_access(32'h1000_1000, 1'b1, 4'h1, 32'h5, 1'b0, value);
        wb_access(32'h1000_1000, 1'b0, 4'hf, '0, 1'b0, value);
        check(value == 32'h5 && led == 4'h5, "LED readback mismatch");

        button_state = 1'b1;
        wb_access(32'h1000_1004, 1'b0, 4'hf, '0, 1'b0, value);
        check(value == 32'h1, "button readback mismatch");
        wb_access(32'h1000_100c, 1'b1, 4'h1, 32'h1, 1'b0, value);

        button_rise = 1'b1;
        @(posedge clk);
        @(negedge clk);
        button_rise = 1'b0;
        wb_access(32'h1000_1008, 1'b0, 4'hf, '0, 1'b0, value);
        check(value == 32'h1 && irq_external, "pending IRQ did not latch");

        wb_access(32'h1000_1008, 1'b1, 4'h1, 32'h1, 1'b0, value);
        check(!irq_external, "pending W1C did not clear IRQ");

        @(negedge clk);
        wb_cyc = 1'b1; wb_stb = 1'b1; wb_we = 1'b1;
        wb_adr = 32'h1000_1008; wb_sel = 4'h1; wb_dat_w = 32'h1;
        button_rise = 1'b1;
        @(posedge clk);
        @(negedge clk);
        button_rise = 1'b0;
        check(wb_ack && !wb_err, "simultaneous pending response wrong");
        wb_cyc = 1'b0; wb_stb = 1'b0;
        @(posedge clk);
        @(negedge clk);
        @(posedge clk);
        @(negedge clk);
        wb_access(32'h1000_1008, 1'b0, 4'hf, '0, 1'b0, value);
        check(value == 32'h1, "set did not win over pending clear");

        wb_access(32'h1000_100c, 1'b1, 4'h1, 32'h0, 1'b0, value);
        check(!irq_external, "IRQ enable did not gate pending");
        wb_access(32'h1000_1004, 1'b1, 4'h1, 32'h1, 1'b1, value);
        wb_access(32'h1000_1010, 1'b0, 4'hf, '0, 1'b1, value);
        wb_access(32'h1000_1002, 1'b0, 4'hf, '0, 1'b1, value);

        $display("PASS Wishbone GPIO interrupt");
        $finish;
    end

    initial begin
        repeat (300) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
